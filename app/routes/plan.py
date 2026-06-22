"""The Plan (Phase 2) — a goal-agnostic 24-week glide-path with weight-vs-target,
phases, milestones, and an accountability summary.

This is the app's FIRST set of write endpoints beyond the gym logger:
    GET    /api/plan                 -> full plan payload, or {"configured": false}
    POST   /api/plan/config          -> create/update the single config row (id=1)
    POST   /api/plan/weight          -> upsert a manual weigh-in by date
    DELETE /api/plan/weight/{date}   -> remove a weigh-in (404 if absent)

Garmin has NO body-weight data for this account (probed live — see
PHASE2_GROUND_TRUTH.md), so the "actual weight" line is entered by hand through
the new weight-log UI and stored in `body_weight` (source default 'manual',
'garmin' reserved for a future smart scale).

The plan is goal-agnostic: loss / gain / recomp are all ONE linear glide-path,
with direction inferred from sign(target_weight - start_weight). No personal
numbers are hardcoded — the user sets everything in the UI.

The PURE engine (ideal_weight, weigh_in_week, classify_pace, build_milestones,
build_accountability, build_plan) lives in module-level functions with no DB or
IO so it can be unit-tested fully offline. See tests/test_plan.py. Write-route
validation mirrors app/routes/sets.py (Pydantic models + field validators ->
422 on bad input, 404 where relevant).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db import db_conn

router = APIRouter()

# Default cadence for milestone checkpoints and the pace-tolerance band (kg).
MILESTONE_WEEKS = 4
PACE_TOL_KG = 0.5
# How close (days) a weigh-in must sit to a milestone date to score it.
MILESTONE_MATCH_DAYS = 3


# ===========================================================================
# PURE HELPERS (no DB, no IO) — unit-tested in tests/test_plan.py
# ===========================================================================

def _parse_date(s: str):
    """Parse a 'YYYY-MM-DD' string to a date. Raises ValueError if malformed."""
    return datetime.strptime(str(s).strip(), "%Y-%m-%d").date()


def _direction(start: float, target: float) -> int:
    """Goal direction: -1 cut (target<start), +1 bulk (target>start), 0 recomp."""
    diff = float(target) - float(start)
    if diff < 0:
        return -1
    if diff > 0:
        return 1
    return 0


def ideal_weight(week: float, cfg: dict[str, Any]) -> float:
    """The glide-path's ideal weight at a given week.

    Linear interpolation from start to target across the horizon; ``week`` is
    clamped to [0, horizon] so the path is flat before the start and after the
    finish rather than over-shooting.
    """
    start = float(cfg["start_weight"])
    target = float(cfg["target_weight"])
    horizon = float(cfg["horizon_weeks"])
    if horizon <= 0:
        return start
    w = max(0.0, min(float(week), horizon))
    return start + (target - start) * (w / horizon)


def weigh_in_week(date: str, start_date: str) -> float:
    """A weigh-in's position on the plan, in (possibly fractional) weeks."""
    return (_parse_date(date) - _parse_date(start_date)).days / 7.0


def classify_pace(
    actual: Optional[float],
    ideal: Optional[float],
    direction: int,
    tol: float = PACE_TOL_KG,
) -> str:
    """Classify actual-vs-ideal as 'ahead' / 'on_pace' / 'behind' / 'unknown'.

    Goal-direction aware:
      * cut  (dir<0): lower is better — at/below ideal is ahead, >ideal+tol behind.
      * bulk (dir>0): mirror — at/above ideal is ahead, <ideal-tol behind.
      * recomp (dir==0): any drift beyond ±tol from ideal is behind.
    A missing reading is 'unknown' rather than a guessed verdict.
    """
    if actual is None or ideal is None:
        return "unknown"
    delta = float(actual) - float(ideal)
    if direction < 0:  # cut
        if delta <= 0:
            return "ahead"
        if delta > tol:
            return "behind"
        return "on_pace"
    if direction > 0:  # bulk
        if delta >= 0:
            return "ahead"
        if delta < -tol:
            return "behind"
        return "on_pace"
    # recomp — hold the line
    if abs(delta) <= tol:
        return "on_pace"
    return "behind"


def _sorted_weights(weights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Weigh-ins sorted by date ascending; ignores rows without a date/weight."""
    clean = [
        w for w in weights
        if w.get("date") and w.get("weight_kg") is not None
    ]
    return sorted(clean, key=lambda w: w["date"])


def build_milestones(
    cfg: dict[str, Any],
    weights: list[dict[str, Any]],
    milestone_weeks: int = MILESTONE_WEEKS,
) -> list[dict[str, Any]]:
    """Checkpoint grid every ``milestone_weeks`` from 0 up to the horizon.

    Each milestone carries its ideal weight and, when a weigh-in lands within
    ±MILESTONE_MATCH_DAYS of the checkpoint date, the nearest actual weight and
    a hit/miss verdict. Milestones with no nearby weigh-in are 'pending'.
    """
    start_date = cfg["start_date"]
    horizon = int(cfg["horizon_weeks"])
    direction = _direction(cfg["start_weight"], cfg["target_weight"])
    start = _parse_date(start_date)
    clean = _sorted_weights(weights)

    out: list[dict[str, Any]] = []
    for week in range(0, horizon + 1, max(1, milestone_weeks)):
        ideal = ideal_weight(week, cfg)
        checkpoint = start + timedelta(weeks=week)

        nearest = None
        best_gap = None
        for w in clean:
            gap = abs((_parse_date(w["date"]) - checkpoint).days)
            if gap <= MILESTONE_MATCH_DAYS and (best_gap is None or gap < best_gap):
                best_gap = gap
                nearest = w

        if nearest is None:
            status = "pending"
            actual = None
        else:
            actual = float(nearest["weight_kg"])
            pace = classify_pace(actual, ideal, direction)
            status = "hit" if pace in ("ahead", "on_pace") else "miss"

        out.append({
            "week": week,
            "date": checkpoint.isoformat(),
            "ideal_weight": round(ideal, 2),
            "actual_weight": round(actual, 2) if actual is not None else None,
            "status": status,
        })
    return out


def build_accountability(
    cfg: dict[str, Any],
    weights: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Headline accountability: where you are vs. where the plan says you should
    be, plus current vs. required rate. Returns None with no weigh-ins."""
    clean = _sorted_weights(weights)
    if not clean:
        return None

    start_date = cfg["start_date"]
    target = float(cfg["target_weight"])
    horizon = float(cfg["horizon_weeks"])
    direction = _direction(cfg["start_weight"], cfg["target_weight"])

    latest = clean[-1]
    latest_weight = float(latest["weight_kg"])
    weeks_elapsed = weigh_in_week(latest["date"], start_date)
    weeks_remaining = horizon - weeks_elapsed
    kg_to_target = target - latest_weight

    # Current rate over the last ~4 weigh-ins (kg/week). Needs >=2 points and a
    # positive time span; otherwise it's not yet measurable.
    window = clean[-4:]
    current_rate = None
    if len(window) >= 2:
        first = window[0]
        span = weigh_in_week(latest["date"], first["date"])
        if span > 0:
            current_rate = (latest_weight - float(first["weight_kg"])) / span

    required_rate = None
    if weeks_remaining > 0:
        required_rate = kg_to_target / weeks_remaining

    ideal_now = ideal_weight(weeks_elapsed, cfg)
    verdict = classify_pace(latest_weight, ideal_now, direction)

    return {
        "latest_weight": round(latest_weight, 2),
        "latest_date": latest["date"],
        "ideal_now": round(ideal_now, 2),
        "kg_to_target": round(kg_to_target, 2),
        "weeks_elapsed": round(weeks_elapsed, 4),
        "weeks_remaining": round(weeks_remaining, 4),
        "current_rate": round(current_rate, 4) if current_rate is not None else None,
        "required_rate": round(required_rate, 4) if required_rate is not None else None,
        "verdict": verdict,
    }


def build_plan(
    cfg: Optional[dict[str, Any]],
    weights: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the full plan payload, or the empty-state sentinel.

    ``cfg`` is None when no plan_config row exists -> {"configured": false} so
    the UI can render a setup CTA instead of a broken chart. Otherwise every
    section is present (NULL-safe: accountability is None until the first
    weigh-in, but the key always exists)."""
    if cfg is None:
        return {"configured": False}

    horizon = int(cfg["horizon_weeks"])
    direction = _direction(cfg["start_weight"], cfg["target_weight"])
    start_date = cfg["start_date"]

    ideal_line = [
        {"week": w, "weight": round(ideal_weight(w, cfg), 2)}
        for w in range(0, horizon + 1)
    ]

    weigh_ins = []
    for w in _sorted_weights(weights):
        week = weigh_in_week(w["date"], start_date)
        weigh_ins.append({
            "date": w["date"],
            "weight_kg": round(float(w["weight_kg"]), 2),
            "source": w.get("source") or "manual",
            "note": w.get("note"),
            "week": round(week, 4),
            "ideal": round(ideal_weight(week, cfg), 2),
        })

    return {
        "configured": True,
        "config": {
            "start_date": start_date,
            "start_weight": round(float(cfg["start_weight"]), 2),
            "target_weight": round(float(cfg["target_weight"]), 2),
            "horizon_weeks": horizon,
        },
        "direction": direction,
        "phases": cfg.get("phases") or [],
        "ideal_line": ideal_line,
        "weigh_ins": weigh_ins,
        "milestones": build_milestones(cfg, weights),
        "accountability": build_accountability(cfg, weights),
    }


# ===========================================================================
# WRITE-ROUTE MODELS — mirror app/routes/sets.py (Pydantic + field validators)
# ===========================================================================

def _validate_iso_date(v: str) -> str:
    """Field validator: require a strict 'YYYY-MM-DD' calendar date."""
    try:
        _parse_date(v)
    except (ValueError, TypeError):
        raise ValueError("date must be 'YYYY-MM-DD'")
    return str(v).strip()


class PhaseIn(BaseModel):
    """One optional plan phase: a named week-range band (e.g. 'Aggressive cut')."""
    model_config = ConfigDict(extra="ignore")
    name: str = Field(..., min_length=1, max_length=60)
    start_week: int = Field(..., ge=0, le=104)
    end_week: int = Field(..., ge=0, le=104)


class PlanConfigIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start_date: str
    start_weight: float = Field(..., gt=0, lt=500)
    target_weight: float = Field(..., gt=0, lt=500)
    horizon_weeks: int = Field(default=24, ge=1, le=104)
    phases: Optional[list[PhaseIn]] = None

    @field_validator("start_date")
    @classmethod
    def _check_date(cls, v: str) -> str:
        return _validate_iso_date(v)


class WeightIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: str
    weight_kg: float = Field(..., gt=0, lt=500)
    note: Optional[str] = None

    @field_validator("date")
    @classmethod
    def _check_date(cls, v: str) -> str:
        return _validate_iso_date(v)


# ===========================================================================
# DB READERS (thin) + ROUTE HANDLERS
# ===========================================================================

def _read_config(conn) -> Optional[dict[str, Any]]:
    """Load the single plan_config row as an engine cfg dict, or None if unset."""
    row = conn.execute("SELECT * FROM plan_config WHERE id = 1").fetchone()
    if not row:
        return None
    phases: list[Any] = []
    if row["phases_json"]:
        try:
            phases = json.loads(row["phases_json"]) or []
        except (ValueError, TypeError):
            phases = []
    return {
        "start_date": row["start_date"],
        "start_weight": row["start_weight"],
        "target_weight": row["target_weight"],
        "horizon_weeks": row["horizon_weeks"],
        "phases": phases,
    }


def _read_weights(conn) -> list[dict[str, Any]]:
    """All weigh-ins, date-ascending, as plain dicts."""
    return [dict(r) for r in conn.execute(
        "SELECT date, weight_kg, source, note FROM body_weight ORDER BY date"
    ).fetchall()]


@router.get("/plan")
def get_plan() -> dict[str, Any]:
    """Full plan payload, or {"configured": false} on a fresh (unconfigured) DB."""
    with db_conn() as conn:
        cfg = _read_config(conn)
        weights = _read_weights(conn) if cfg is not None else []
    return build_plan(cfg, weights)


@router.post("/plan/config")
def save_config(payload: PlanConfigIn) -> dict[str, Any]:
    """Create or update the single plan-config row (id=1). Returns the full plan."""
    phases_json = (
        json.dumps([p.model_dump() for p in payload.phases])
        if payload.phases else None
    )
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO plan_config
                   (id, start_date, horizon_weeks, start_weight, target_weight,
                    phases_json, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(id) DO UPDATE SET
                   start_date    = excluded.start_date,
                   horizon_weeks = excluded.horizon_weeks,
                   start_weight  = excluded.start_weight,
                   target_weight = excluded.target_weight,
                   phases_json   = excluded.phases_json,
                   updated_at    = CURRENT_TIMESTAMP""",
            (
                payload.start_date,
                payload.horizon_weeks,
                payload.start_weight,
                payload.target_weight,
                phases_json,
            ),
        )
    return get_plan()


@router.post("/plan/weight", status_code=201)
def log_weight(payload: WeightIn) -> dict[str, Any]:
    """Upsert a manual weigh-in keyed by date (re-logging a date overwrites it)."""
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO body_weight (date, weight_kg, source, note)
               VALUES (?, ?, 'manual', ?)
               ON CONFLICT(date) DO UPDATE SET
                   weight_kg = excluded.weight_kg,
                   note      = excluded.note""",
            (payload.date, payload.weight_kg, payload.note),
        )
        row = conn.execute(
            "SELECT date, weight_kg, source, note FROM body_weight WHERE date = ?",
            (payload.date,),
        ).fetchone()
    return dict(row)


@router.delete("/plan/weight/{date}")
def delete_weight(date: str) -> Response:
    """Delete a weigh-in by date. 404 if no row for that date."""
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM body_weight WHERE date = ?", (date,))
        if cur.rowcount == 0:
            raise HTTPException(404, detail=f"no weigh-in logged for {date}")
    return Response(status_code=204)
