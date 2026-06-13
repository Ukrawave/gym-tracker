"""Exercise catalog routes.

GET /api/exercises                  list all
GET /api/exercises/{id}             one
GET /api/exercises/{id}/last        last-session sets (history one-row)
GET /api/exercises/{id}/history     per-session history (weight/1RM/volume)
GET /api/categories/{category}/lineup  default ordered lineup for a session category
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from app.db import db_conn, brzycki_est_1rm

router = APIRouter()

CATEGORY_LINEUPS: dict[str, list[str]] = {
    "Chest-and-Biceps": [
        "barbell-bench-press",
        "incline-dumbbell-press",
        "dumbbell-fly",
        "barbell-curl",
        "dumbbell-hammer-curl",
    ],
    "Back-and-Triceps": [
        "lat-pulldown",
        "barbell-bent-over-row",
        "seated-cable-row",
        "triceps-pushdown",
        "dumbbell-overhead-triceps-extension",
    ],
    "Legs": [
        "barbell-full-squat",
        "romanian-deadlift",
        "leg-press",
        "lying-leg-curl",
        "standing-calf-raise",
    ],
    "Shoulders": [
        "barbell-shoulder-press",
        "dumbbell-lateral-raise",
        "dumbbell-reverse-fly",
        "dumbbell-front-raise",
        "dumbbell-shrug",
    ],
    "Custom": [],
}


def _row_to_exercise(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "muscle_group": row["muscle_group"],
        "form_cues": json.loads(row["form_cues"]),
        "media_slug": row["media_slug"],
        "created_at": row["created_at"],
    }


@router.get("/exercises")
def list_exercises() -> list[dict[str, Any]]:
    """All catalog exercises, alphabetical by name."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM exercises ORDER BY muscle_group, name"
        ).fetchall()
    return [_row_to_exercise(r) for r in rows]


@router.get("/exercises/{exercise_id}")
def get_exercise(exercise_id: str) -> dict[str, Any]:
    """Single exercise by slug id."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM exercises WHERE id = ?", (exercise_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, detail=f"exercise '{exercise_id}' not found")
    return _row_to_exercise(row)


@router.get("/exercises/{exercise_id}/last")
def last_sets(exercise_id: str) -> list[dict[str, Any]]:
    """Sets logged in the most recent session that contains this exercise."""
    with db_conn() as conn:
        latest = conn.execute(
            """SELECT session_id FROM set_entries
               WHERE exercise_id = ?
               ORDER BY session_id DESC LIMIT 1""",
            (exercise_id,),
        ).fetchone()
        if not latest:
            return []
        rows = conn.execute(
            """SELECT set_index, weight, reps, entry_status
               FROM set_entries
               WHERE session_id = ? AND exercise_id = ?
               ORDER BY set_index""",
            (latest["session_id"], exercise_id),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/exercises/{exercise_id}/history")
def history(exercise_id: str) -> list[dict[str, Any]]:
    """One row per session: date, est_1rm best, max_weight, total_volume."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT s.id AS session_id, s.date,
                      e.weight, e.reps
               FROM set_entries e
               JOIN sessions s ON s.id = e.session_id
               WHERE e.exercise_id = ? AND e.entry_status != 'Warm-up'
               ORDER BY s.date, e.id""",
            (exercise_id,),
        ).fetchall()
    by_session: dict[int, dict[str, Any]] = {}
    for r in rows:
        sid = r["session_id"]
        bucket = by_session.setdefault(
            sid,
            {"date": r["date"], "max_weight": 0.0, "est_1rm": 0.0, "total_volume": 0.0},
        )
        bucket["max_weight"] = max(bucket["max_weight"], float(r["weight"]))
        est = brzycki_est_1rm(r["weight"], r["reps"])
        bucket["est_1rm"] = max(bucket["est_1rm"], est)
        bucket["total_volume"] += float(r["weight"]) * int(r["reps"])
    out = []
    for sid, b in by_session.items():
        out.append(
            {
                "session_id": sid,
                "date": b["date"],
                "est_1rm": round(b["est_1rm"], 2),
                "max_weight": round(b["max_weight"], 2),
                "total_volume": round(b["total_volume"], 2),
            }
        )
    out.sort(key=lambda x: (x["date"], x["session_id"]))
    return out


@router.get("/categories/{category}/lineup")
def category_lineup(category: str) -> list[dict[str, Any]]:
    """Pre-populated exercise lineup for the given session category."""
    if category not in CATEGORY_LINEUPS:
        raise HTTPException(404, detail=f"unknown category '{category}'")
    slugs = CATEGORY_LINEUPS[category]
    if not slugs:
        return []
    with db_conn() as conn:
        placeholders = ",".join("?" for _ in slugs)
        rows = conn.execute(
            f"SELECT * FROM exercises WHERE id IN ({placeholders})", slugs
        ).fetchall()
    by_id = {r["id"]: _row_to_exercise(r) for r in rows}
    # Preserve canonical order from CATEGORY_LINEUPS.
    return [by_id[s] for s in slugs if s in by_id]
