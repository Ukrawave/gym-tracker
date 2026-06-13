"""Storage hygiene: drop session history we don't want to keep.

Rule (per Hugo, 2026-06-13): the history view should show ONLY sessions that
include exercise weights data. A 'session with exercise weights' means a row
in ``sessions`` that has at least one related row in ``set_entries``. Anything
else (e.g. a session that was created but abandoned before a single set was
logged) is dropped.

This module is intentionally side-effect-free *except* for the explicit
``cleanup_empty_sessions`` call. It is safe to call at boot and from a CLI.

CLI usage:
    python -m app.cleanup --dry-run
    python -m app.cleanup           # actually delete

The function is also wired into FastAPI's startup so the invariant holds on
every boot — if a future bug or manual ``INSERT`` lands an empty session, the
next restart sweeps it out.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from app.db import db_conn

# Rows that match this WHERE clause are 'sessions without exercise weights'.
# We treat 'any row in set_entries' as evidence of weights — even a zero-weight
# warm-up set counts as user-entered data the user might want to keep. If you
# need a stricter rule later (e.g. ``weight > 0``), change this single literal.
_EMPTY_SESSIONS_SQL = """
    SELECT s.id, s.date, s.category, s.start_time, s.end_time, s.notes
    FROM sessions s
    WHERE NOT EXISTS (
        SELECT 1 FROM set_entries se WHERE se.session_id = s.id
    )
"""


def list_empty_sessions() -> list[dict[str, Any]]:
    """Return the sessions that would be removed. Read-only."""
    with db_conn() as conn:
        rows = conn.execute(_EMPTY_SESSIONS_SQL + " ORDER BY s.id").fetchall()
        return [dict(r) for r in rows]


def cleanup_empty_sessions() -> dict[str, Any]:
    """Delete sessions with zero ``set_entries``.

    Returns a small report: ``{deleted: int, ids: [...]}``. ON DELETE CASCADE
    on ``set_entries`` is irrelevant here (these sessions have none), and
    ``personal_records`` only ever points at real set rows, so the deletion
    is leaf-only and cannot orphan anything.
    """
    with db_conn() as conn:
        rows = conn.execute(_EMPTY_SESSIONS_SQL).fetchall()
        ids = [int(r["id"]) for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"DELETE FROM sessions WHERE id IN ({placeholders})", ids
            )
    return {"deleted": len(ids), "ids": ids}


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="list the sessions that would be deleted but do not delete.",
    )
    args = p.parse_args(argv)

    if args.dry_run:
        empties = list_empty_sessions()
        if not empties:
            print("no empty sessions; nothing to do.")
            return 0
        print(f"would delete {len(empties)} empty session(s):")
        for r in empties:
            print(f"  id={r['id']:>4}  date={r['date']}  category={r['category']}  start={r['start_time']}")
        return 0

    report = cleanup_empty_sessions()
    if report["deleted"] == 0:
        print("no empty sessions; nothing to do.")
    else:
        print(f"deleted {report['deleted']} session(s): {report['ids']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
