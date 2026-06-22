"""Generic, network-free persistence helpers shared by all data sources.

Everything here is a pure function over a sqlite3 connection plus plain dicts,
so it is fully unit-testable offline. No source-specific logic lives here.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of real column names for `table`.

    Used to filter a normalizer's output down to columns that actually exist,
    so an extra/forward-compat key in a row dict never raises
    "table has no column named ...". PRAGMA is cheap; no caching needed (and
    caching on id(conn) would be unsafe across GC'd connections).
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # PRAGMA rows: (cid, name, type, notnull, dflt_value, pk) — name is idx 1.
    return {r[1] for r in rows}


# --------------------------------------------------------------------------
# Pure value-coercion helpers used by the normalizers. Kept here (not in the
# source modules) so they're covered by the offline base tests and reused by
# both Garmin and Strava.
# --------------------------------------------------------------------------

def coerce_int(value: Any) -> Optional[int]:
    """Best-effort int. Rounds floats, parses numeric strings, None-safe.

    Returns None for None/empty/unparseable input rather than raising, because
    real wellness payloads carry nulls on days a metric wasn't recorded.
    """
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def coerce_float(value: Any) -> Optional[float]:
    """Best-effort float. None-safe; returns None on unparseable input."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def dig(obj: Any, *keys: str, default: Any = None) -> Any:
    """Walk nested dict keys, returning `default` if any hop is missing.

    Survives a non-dict encountered partway down the path (returns default),
    so deep Garmin JSON paths can be mapped without a pile of `.get()` guards.
    """
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur if cur is not None else default


def upsert(
    conn: sqlite3.Connection,
    table: str,
    pk_col: str,
    row: dict[str, Any],
) -> Any:
    """INSERT a row, or UPDATE it in place on PK conflict (no duplicates).

    Only keys that map to real columns are written; unknown keys are dropped so
    a normalizer can emit forward-compatible extras safely. Returns the primary
    key value of the upserted row. Caller controls the transaction (commit).
    """
    cols = _table_columns(conn, table)
    if pk_col not in cols:
        raise ValueError(f"pk_col '{pk_col}' is not a column of '{table}'")

    data = {k: v for k, v in row.items() if k in cols}
    if pk_col not in data:
        raise ValueError(f"row is missing primary key '{pk_col}' for '{table}'")

    col_names = list(data.keys())
    placeholders = ", ".join("?" for _ in col_names)
    col_list = ", ".join(col_names)

    # Update every non-PK column that was supplied.
    update_cols = [c for c in col_names if c != pk_col]
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)

    if set_clause:
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT({pk_col}) DO UPDATE SET {set_clause}"
        )
    else:
        # PK-only row — nothing to update, just ignore the conflict.
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT({pk_col}) DO NOTHING"
        )

    conn.execute(sql, [data[c] for c in col_names])
    return data[pk_col]


def store_raw(row: dict[str, Any], payload: Any) -> dict[str, Any]:
    """Return a shallow copy of `row` with the raw payload JSON-encoded.

    Keeps an audit trail of the exact source response in the `raw_json` column
    so the orchestrator can re-derive fields later without a re-fetch. Does not
    mutate the input dict.
    """
    out = dict(row)
    out["raw_json"] = json.dumps(payload, ensure_ascii=False, default=str)
    return out


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string (seconds precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_watermark(conn: sqlite3.Connection, source: str) -> Optional[str]:
    """Return the last incremental watermark for `source`, or None if unseen."""
    r = conn.execute(
        "SELECT last_watermark FROM sync_state WHERE source = ?", (source,)
    ).fetchone()
    if r is None:
        return None
    # Works whether row_factory is sqlite3.Row or the default tuple.
    return r[0]


def write_watermark(
    conn: sqlite3.Connection,
    source: str,
    *,
    watermark: Optional[str] = None,
    status: str = "ok",
    last_run_at: Optional[str] = None,
) -> None:
    """Upsert this source's sync bookkeeping row in `sync_state`.

    `last_run_at` defaults to now (UTC). Caller controls the transaction.
    """
    upsert(
        conn,
        "sync_state",
        "source",
        {
            "source": source,
            "last_run_at": last_run_at or _now_iso(),
            "last_watermark": watermark,
            "last_status": status,
        },
    )
