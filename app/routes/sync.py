"""Sync status routes (Phase 0).

Read-only view of the data-ingestion state for the frontend / orchestrator.
New endpoints live under /api/sync/ and are purely additive — no existing route
is touched. NO network here: this only reads the local DB.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.db import db_conn

router = APIRouter()

# Tables the dashboard counts to show ingestion coverage.
_COUNT_TABLES = (
    "activities",
    "daily_wellness",
    "sleep_nights",
    "nutrition_days",
)
_KNOWN_SOURCES = ("garmin", "strava")


@router.get("/sync/status")
def sync_status() -> dict[str, Any]:
    """Per-source sync state + row counts for each ingested table.

    Shape:
        {
          "sources": {
            "garmin": {"last_run_at": ..., "last_status": ..., "last_watermark": ...},
            "strava": {...}
          },
          "counts": {"activities": N, "daily_wellness": N, ...}
        }
    Sources that have never run report nulls rather than being absent.
    """
    with db_conn() as conn:
        state_rows = conn.execute(
            "SELECT source, last_run_at, last_status, last_watermark FROM sync_state"
        ).fetchall()
        by_source = {r["source"]: dict(r) for r in state_rows}

        sources: dict[str, Any] = {}
        for name in _KNOWN_SOURCES:
            row = by_source.get(name)
            sources[name] = {
                "last_run_at": row["last_run_at"] if row else None,
                "last_status": row["last_status"] if row else None,
                "last_watermark": row["last_watermark"] if row else None,
            }
        # Surface any extra sources that exist in the table but aren't known.
        for name, row in by_source.items():
            if name not in sources:
                sources[name] = {
                    "last_run_at": row["last_run_at"],
                    "last_status": row["last_status"],
                    "last_watermark": row["last_watermark"],
                }

        counts: dict[str, int] = {}
        for table in _COUNT_TABLES:
            counts[table] = conn.execute(
                f"SELECT COUNT(*) AS c FROM {table}"
            ).fetchone()["c"]

    return {"sources": sources, "counts": counts}
