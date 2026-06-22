"""Sync orchestrator (Phase 0).

`python -m app.sync` pulls Garmin + Strava into the additive tables. Each source
runs inside its own try/except so one failing source never aborts the other, and
every run records its outcome in `sync_state` (so /api/sync/status and the next
incremental run can read it).

First run backfills `SYNC_BACKFILL_DAYS` of history; later runs are incremental
from each source's watermark.

NO network happens at import or during `--help`: credentials are read and source
clients built only inside `run_sync()`, and the network libraries are lazy
-imported inside the source methods. This keeps the module importable with no
`garminconnect`/`requests` installed and no creds present.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from app.sources.base import read_watermark, write_watermark

DEFAULT_BACKFILL_DAYS = 120


# ----------------------------------------------------------------------
# Per-source isolation wrapper — pure control flow, unit-testable offline.
# ----------------------------------------------------------------------
def _run_one(
    conn: sqlite3.Connection,
    name: str,
    work: Callable[[], Optional[str]],
) -> dict[str, Any]:
    """Run one source's `work()`, isolating failures and recording state.

    `work` does the fetch+normalize+upsert and returns the new watermark. On
    success we stamp status 'ok' + the new watermark; on ANY exception we stamp
    an 'error: ...' status (preserving the prior watermark) and swallow it so a
    sibling source still runs. The transaction is committed here per-source so a
    later source's failure can't roll back an earlier source's rows.
    """
    try:
        new_watermark = work()
        write_watermark(conn, name, watermark=new_watermark, status="ok")
        conn.commit()
        return {"source": name, "status": "ok", "watermark": new_watermark}
    except Exception as exc:  # noqa: BLE001 — deliberate per-source isolation
        conn.rollback()
        prior = read_watermark(conn, name)
        msg = f"error: {type(exc).__name__}: {exc}"
        write_watermark(conn, name, watermark=prior, status=msg)
        conn.commit()
        return {"source": name, "status": msg, "watermark": prior}


# ----------------------------------------------------------------------
# Date-window helpers (pure).
# ----------------------------------------------------------------------
def _today() -> date:
    return datetime.now(timezone.utc).date()


def _date_window(
    watermark: Optional[str], backfill_days: int, today: Optional[date] = None
) -> tuple[str, str]:
    """(start, end) ISO dates. Incremental from watermark, else backfill."""
    today = today or _today()
    if watermark:
        start = watermark[:10]  # tolerate a full timestamp watermark
    else:
        start = (today - timedelta(days=backfill_days)).isoformat()
    return start, today.isoformat()


def _epoch_window(
    watermark: Optional[str], backfill_days: int, today: Optional[date] = None
) -> int:
    """`after` epoch seconds. Incremental from watermark, else backfill."""
    today = today or _today()
    if watermark:
        try:
            return int(float(watermark))
        except (TypeError, ValueError):
            pass
    start_dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) - timedelta(
        days=backfill_days
    )
    return int(start_dt.timestamp())


# ----------------------------------------------------------------------
# Per-source ingest (network via the source's fetch_*; not run in tests).
# ----------------------------------------------------------------------
def ingest_garmin(conn: sqlite3.Connection, source: Any, backfill_days: int) -> str:
    """Pull Garmin activities + per-day sleep/wellness; return new watermark."""
    from app.sources.base import upsert

    start, end = _date_window(read_watermark(conn, source.source), backfill_days)

    activities = source.fetch_activities(start, end) or []
    for raw in activities:
        upsert(conn, "activities", "id", source.normalize_activity(raw))

    # Per-day pillars across the window.
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    day = d0
    while day <= d1:
        ds = day.isoformat()
        try:
            sleep_raw = source.fetch_sleep(ds)
            if sleep_raw:
                upsert(conn, "sleep_nights", "date", source.normalize_sleep(sleep_raw))
        except Exception:  # noqa: BLE001 — a single missing day shouldn't abort
            pass
        try:
            well_raw = source.fetch_wellness(ds)
            if well_raw:
                upsert(conn, "daily_wellness", "date", source.normalize_wellness(well_raw))
        except Exception:  # noqa: BLE001
            pass
        day += timedelta(days=1)

    return end  # watermark = last day synced (idempotent re-pull on next run)


def ingest_strava(conn: sqlite3.Connection, source: Any, backfill_days: int) -> str:
    """Pull Strava activities after the watermark; return new watermark epoch."""
    from app.sources.base import upsert

    after = _epoch_window(read_watermark(conn, source.source), backfill_days)
    activities = source.fetch_activities(after) or []

    latest = after
    for raw in activities:
        upsert(conn, "activities", "id", source.normalize_activity(raw))
        # Advance watermark to the newest activity start we saw.
        sd = raw.get("start_date")
        if sd:
            try:
                ts = int(
                    datetime.fromisoformat(sd.replace("Z", "+00:00")).timestamp()
                )
                latest = max(latest, ts)
            except (TypeError, ValueError):
                pass
    return str(latest)


# ----------------------------------------------------------------------
# Top-level orchestration.
# ----------------------------------------------------------------------
def run_sync(
    conn: sqlite3.Connection,
    *,
    garmin: Any = None,
    strava: Any = None,
    sources: Optional[list[str]] = None,
    backfill_days: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Run the requested sources, isolating failures. Returns per-source results.

    `garmin`/`strava` may be injected (tests); otherwise they're built from env.
    """
    if backfill_days is None:
        backfill_days = int(os.environ.get("SYNC_BACKFILL_DAYS", DEFAULT_BACKFILL_DAYS))
    sources = sources or ["garmin", "strava"]
    results: list[dict[str, Any]] = []

    if "garmin" in sources:
        gs = garmin or _build_garmin()
        results.append(_run_one(conn, "garmin", lambda: ingest_garmin(conn, gs, backfill_days)))

    if "strava" in sources:
        ss = strava or _build_strava()
        results.append(_run_one(conn, "strava", lambda: ingest_strava(conn, ss, backfill_days)))

    return results


def _build_garmin() -> Any:
    from app.sources.garmin import GarminSource

    return GarminSource(
        email=os.environ.get("GARMIN_EMAIL"),
        password=os.environ.get("GARMIN_PASSWORD"),
        tokenstore=os.environ.get("GARMIN_TOKENSTORE", ".garmin_tokens"),
    )


def _build_strava() -> Any:
    from app.sources.strava import StravaSource

    return StravaSource(
        client_id=os.environ.get("STRAVA_CLIENT_ID"),
        client_secret=os.environ.get("STRAVA_CLIENT_SECRET"),
        refresh_token=os.environ.get("STRAVA_REFRESH_TOKEN"),
    )


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.sync",
        description="Sync Garmin + Strava into the gym-tracker SQLite DB.",
    )
    parser.add_argument(
        "--source",
        choices=["all", "garmin", "strava"],
        default="all",
        help="which source(s) to sync (default: all)",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=None,
        help="override SYNC_BACKFILL_DAYS for the first/backfill run",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry. `--help` works with no creds and no network (argparse exits)."""
    args = _parse_args(argv)

    # Load .env only now (after --help would have exited). dotenv is a declared
    # dep; a missing .env is a no-op.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # noqa: BLE001 — never fail the run on env loading
        pass

    from app.db import get_connection, init_schema

    init_schema()
    sources = ["garmin", "strava"] if args.source == "all" else [args.source]
    conn = get_connection()
    try:
        results = run_sync(conn, sources=sources, backfill_days=args.backfill_days)
    finally:
        conn.close()

    for r in results:
        print(f"[sync] {r['source']:7s} status={r['status']} watermark={r['watermark']}")
    # Non-zero exit if every requested source errored, so cron/systemd notices.
    if results and all(r["status"].startswith("error") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
