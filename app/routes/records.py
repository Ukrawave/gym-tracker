"""Personal-record routes + PR re-evaluation helpers.

A set is a PR if either (a) its weight beats the previous absolute max weight
for the exercise, OR (b) its Brzycki est-1RM beats the previous best est-1RM
for the exercise. Warm-up sets are excluded from PR consideration.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.db import db_conn, brzycki_est_1rm

router = APIRouter()


# ---------- internal helpers ----------

def _delete_prs_for_exercise(conn, exercise_id: str) -> None:
    conn.execute("DELETE FROM personal_records WHERE exercise_id = ?", (exercise_id,))


def reevaluate_prs_for_exercise(exercise_id: str) -> int:
    """Re-walk all non-warmup sets for this exercise in time order and stamp PRs.

    Returns the number of PR rows created.
    """
    inserted = 0
    with db_conn() as conn:
        sets = conn.execute(
            """SELECT se.id, se.weight, se.reps, se.entry_status, s.date
               FROM set_entries se
               JOIN sessions s ON s.id = se.session_id
               WHERE se.exercise_id = ?
               ORDER BY s.date, se.id""",
            (exercise_id,),
        ).fetchall()
        _delete_prs_for_exercise(conn, exercise_id)
        best_w = 0.0
        best_1rm = 0.0
        for r in sets:
            if r["entry_status"] == "Warm-up":
                continue
            w = float(r["weight"])
            reps = int(r["reps"])
            if reps <= 0 or w <= 0:
                continue
            est = brzycki_est_1rm(w, reps)
            is_pr = False
            if w > best_w + 1e-9:
                is_pr = True
            if est > best_1rm + 1e-9:
                is_pr = True
            if is_pr:
                conn.execute(
                    """INSERT OR IGNORE INTO personal_records
                       (exercise_id, set_entry_id, pr_date, est_1rm, max_weight)
                       VALUES (?, ?, ?, ?, ?)""",
                    (exercise_id, r["id"], r["date"], round(est, 2), w),
                )
                inserted += 1
                best_w = max(best_w, w)
                best_1rm = max(best_1rm, est)
    return inserted


def reevaluate_prs_for_session(session_id: int) -> dict[str, int]:
    """Re-evaluate PRs for every exercise touched by the given session."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT exercise_id FROM set_entries WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["exercise_id"]] = reevaluate_prs_for_exercise(r["exercise_id"])
    return counts


# ---------- HTTP routes ----------

@router.get("/records")
def list_records(limit: int = 100) -> list[dict[str, Any]]:
    """All PRs, most recent first. Joins exercise + originating set for context."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT pr.*, ex.name AS exercise_name, ex.muscle_group, ex.media_slug,
                      se.weight AS set_weight, se.reps AS set_reps, se.entry_status,
                      se.session_id
               FROM personal_records pr
               JOIN exercises ex ON ex.id = pr.exercise_id
               JOIN set_entries se ON se.id = pr.set_entry_id
               ORDER BY pr.pr_date DESC, pr.id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/records/exercise/{exercise_id}")
def records_for_exercise(exercise_id: str) -> list[dict[str, Any]]:
    with db_conn() as conn:
        ex = conn.execute("SELECT id FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
        if not ex:
            raise HTTPException(404, detail=f"exercise '{exercise_id}' not found")
        rows = conn.execute(
            """SELECT pr.*, se.weight AS set_weight, se.reps AS set_reps, se.entry_status,
                      se.session_id
               FROM personal_records pr
               JOIN set_entries se ON se.id = pr.set_entry_id
               WHERE pr.exercise_id = ?
               ORDER BY pr.pr_date DESC, pr.id DESC""",
            (exercise_id,),
        ).fetchall()
    return [dict(r) for r in rows]
