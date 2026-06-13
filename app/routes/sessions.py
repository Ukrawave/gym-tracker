"""Session routes — create, list, fetch (with nested sets), update, delete.

Triggers PR re-evaluation when a session is closed (end_time set) and when
sets are added through the dedicated sets router.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, ConfigDict, field_validator

from app.db import db_conn

router = APIRouter()

ALLOWED_CATEGORIES = {
    "Chest-and-Biceps",
    "Back-and-Triceps",
    "Legs",
    "Shoulders",
    "Custom",
}
ALLOWED_STATUSES = {"Warm-up", "Completed", "Failure"}


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    category: str = Field(..., description="One of Chest-and-Biceps/Back-and-Triceps/Legs/Shoulders/Custom")
    notes: Optional[str] = None
    start_time: Optional[str] = None

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v: str) -> str:
        if v not in ALLOWED_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(ALLOWED_CATEGORIES)}")
        return v


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    notes: Optional[str] = None
    end_time: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session_summary(conn, session_id: int) -> dict[str, Any]:
    """Return aggregate stats for a session: total sets, volume, exercise count."""
    row = conn.execute(
        """SELECT COUNT(*) AS sets,
                  COALESCE(SUM(weight*reps),0) AS volume,
                  COUNT(DISTINCT exercise_id) AS exercises
           FROM set_entries WHERE session_id = ?""",
        (session_id,),
    ).fetchone()
    return {
        "total_sets": int(row["sets"] or 0),
        "total_volume": round(float(row["volume"] or 0), 2),
        "exercise_count": int(row["exercises"] or 0),
    }


@router.post("/sessions", status_code=201)
def create_session(payload: SessionCreate) -> dict[str, Any]:
    """Create a session. Defaults start_time to now if not provided."""
    start = payload.start_time or _now_iso()
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (category, start_time, notes) VALUES (?, ?, ?)",
            (payload.category, start, payload.notes),
        )
        sid = cur.lastrowid
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    return dict(row)


@router.get("/sessions")
def list_sessions(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Most recent sessions first; includes summary stats."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM sessions ORDER BY id DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        out = []
        for r in rows:
            s = dict(r)
            s.update(_session_summary(conn, s["id"]))
            out.append(s)
    return out


@router.get("/sessions/{session_id}")
def get_session(session_id: int) -> dict[str, Any]:
    """Full session payload, nested by exercise.

    Returns ``exercises: [{id, name, muscle_group, media_slug, form_cues, sets:[...]}]``
    plus a flat ``set_entries`` array for clients that need linear order.
    """
    with db_conn() as conn:
        srow = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not srow:
            raise HTTPException(404, detail=f"session {session_id} not found")
        sets = conn.execute(
            """SELECT se.*, ex.name AS exercise_name, ex.muscle_group, ex.media_slug, ex.form_cues
               FROM set_entries se
               JOIN exercises ex ON ex.id = se.exercise_id
               WHERE session_id = ?
               ORDER BY se.id""",
            (session_id,),
        ).fetchall()
        summary = _session_summary(conn, session_id)

    grouped: dict[str, dict[str, Any]] = {}
    flat: list[dict[str, Any]] = []
    for r in sets:
        s = dict(r)
        flat.append(
            {
                "id": s["id"],
                "set_index": s["set_index"],
                "exercise_id": s["exercise_id"],
                "weight": s["weight"],
                "reps": s["reps"],
                "entry_status": s["entry_status"],
                "created_at": s["created_at"],
            }
        )
        eid = s["exercise_id"]
        g = grouped.setdefault(
            eid,
            {
                "id": eid,
                "name": s["exercise_name"],
                "muscle_group": s["muscle_group"],
                "media_slug": s["media_slug"],
                "form_cues": json.loads(s["form_cues"]),
                "sets": [],
            },
        )
        g["sets"].append(
            {
                "id": s["id"],
                "set_index": s["set_index"],
                "weight": s["weight"],
                "reps": s["reps"],
                "entry_status": s["entry_status"],
                "created_at": s["created_at"],
            }
        )

    out = dict(srow)
    out["summary"] = summary
    out["exercises"] = list(grouped.values())
    out["set_entries"] = flat
    return out


@router.put("/sessions/{session_id}")
def update_session(session_id: int, payload: SessionUpdate) -> dict[str, Any]:
    """Update notes and/or end_time. Closing the session triggers PR re-eval."""
    from app.routes.records import reevaluate_prs_for_session  # local to avoid cycle

    fields: list[str] = []
    values: list[Any] = []
    if payload.notes is not None:
        fields.append("notes = ?")
        values.append(payload.notes)
    if payload.end_time is not None:
        fields.append("end_time = ?")
        values.append(payload.end_time)
    if not fields:
        return get_session(session_id)
    with db_conn() as conn:
        ex = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not ex:
            raise HTTPException(404, detail=f"session {session_id} not found")
        values.append(session_id)
        conn.execute(f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?", values)
    # If closing the session, re-evaluate PRs touched by this session.
    if payload.end_time is not None:
        reevaluate_prs_for_session(session_id)
    return get_session(session_id)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int) -> Response:
    """Cascade delete a session and all its sets / PR pointers."""
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, detail=f"session {session_id} not found")
    return Response(status_code=204)
