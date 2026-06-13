"""Set-entry routes — add to a session, update, delete.

Adding or updating a set re-evaluates PRs for the affected exercise.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db import db_conn
from app.routes.records import reevaluate_prs_for_exercise

router = APIRouter()

ALLOWED_STATUSES = {"Warm-up", "Completed", "Failure"}


class SetCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    exercise_id: str
    set_index: int = Field(..., ge=1, le=99)
    weight: float = Field(..., ge=0)
    reps: int = Field(..., ge=0, le=999)
    entry_status: str = Field(default="Completed")

    @field_validator("entry_status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in ALLOWED_STATUSES:
            raise ValueError(f"entry_status must be one of {sorted(ALLOWED_STATUSES)}")
        return v


class SetUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    weight: Optional[float] = None
    reps: Optional[int] = None
    entry_status: Optional[str] = None
    set_index: Optional[int] = None

    @field_validator("entry_status")
    @classmethod
    def _validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALLOWED_STATUSES:
            raise ValueError(f"entry_status must be one of {sorted(ALLOWED_STATUSES)}")
        return v


@router.post("/sessions/{session_id}/sets", status_code=201)
def add_set(session_id: int, payload: SetCreate) -> dict[str, Any]:
    """Add a set to a session. Triggers PR re-evaluation for the exercise."""
    with db_conn() as conn:
        sess = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not sess:
            raise HTTPException(404, detail=f"session {session_id} not found")
        ex = conn.execute("SELECT id FROM exercises WHERE id = ?", (payload.exercise_id,)).fetchone()
        if not ex:
            raise HTTPException(404, detail=f"exercise '{payload.exercise_id}' not found")
        try:
            cur = conn.execute(
                """INSERT INTO set_entries
                   (session_id, exercise_id, set_index, weight, reps, entry_status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    payload.exercise_id,
                    payload.set_index,
                    payload.weight,
                    payload.reps,
                    payload.entry_status,
                ),
            )
            new_id = cur.lastrowid
        except Exception as exc:  # sqlite IntegrityError surfaces here
            raise HTTPException(400, detail=str(exc))
        row = conn.execute("SELECT * FROM set_entries WHERE id = ?", (new_id,)).fetchone()
    # PR re-evaluation lives in its own write transaction.
    reevaluate_prs_for_exercise(payload.exercise_id)
    return dict(row)


@router.put("/sets/{set_id}")
def update_set(set_id: int, payload: SetUpdate) -> dict[str, Any]:
    fields: list[str] = []
    values: list[Any] = []
    if payload.weight is not None:
        fields.append("weight = ?")
        values.append(payload.weight)
    if payload.reps is not None:
        fields.append("reps = ?")
        values.append(payload.reps)
    if payload.entry_status is not None:
        fields.append("entry_status = ?")
        values.append(payload.entry_status)
    if payload.set_index is not None:
        fields.append("set_index = ?")
        values.append(payload.set_index)
    if not fields:
        with db_conn() as conn:
            row = conn.execute("SELECT * FROM set_entries WHERE id = ?", (set_id,)).fetchone()
        if not row:
            raise HTTPException(404, detail=f"set {set_id} not found")
        return dict(row)
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM set_entries WHERE id = ?", (set_id,)).fetchone()
        if not row:
            raise HTTPException(404, detail=f"set {set_id} not found")
        ex_id = row["exercise_id"]
        values.append(set_id)
        conn.execute(f"UPDATE set_entries SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM set_entries WHERE id = ?", (set_id,)).fetchone()
    reevaluate_prs_for_exercise(ex_id)
    return dict(row)


@router.delete("/sets/{set_id}")
def delete_set(set_id: int) -> Response:
    with db_conn() as conn:
        row = conn.execute("SELECT exercise_id FROM set_entries WHERE id = ?", (set_id,)).fetchone()
        if not row:
            raise HTTPException(404, detail=f"set {set_id} not found")
        ex_id = row["exercise_id"]
        conn.execute("DELETE FROM set_entries WHERE id = ?", (set_id,))
    reevaluate_prs_for_exercise(ex_id)
    return Response(status_code=204)
