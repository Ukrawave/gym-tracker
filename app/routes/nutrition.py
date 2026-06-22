"""Nutrition (Phase 3) - manual calorie/macro intake vs user-set daily targets,
a logging streak, and a true in-vs-out-vs-net view.

Garmin has NO food data for this account (probed live - see
PHASE3_GROUND_TRUTH.md), so calories/macros IN are entered by hand. Calories
OUT, however, are already synced: the route READS them at request time from the
existing `daily_wellness` table (raw_json -> stats_and_body -> totalKilocalories)
- there is NO live Garmin call here.

Endpoints (registered under /api in app/main.py):
    GET    /api/nutrition              -> full payload, or {"configured": false}
    POST   /api/nutrition/targets      -> create/update the single targets row (id=1)
    POST   /api/nutrition/log          -> upsert a day's intake by date (201)
    DELETE /api/nutrition/log/{date}   -> remove a day's intake (404 if absent)

This is goal-agnostic: no target is hardcoded - Hugo sets calories + macros in
the UI. The PURE engine (calories_out_from_raw, streak, net_calories, adherence,
build_nutrition) lives in module-level functions with no DB or IO so it can be
unit-tested fully offline. See tests/test_nutrition.py. Write-route validation
mirrors app/routes/sets.py (Pydantic models + field validators -> 422 on bad
input, 404 where relevant).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db import db_conn

router = APIRouter()

# How many recent days the history series carries (the streak still spans the
# full logged history, not just this window).
RECENT_WINDOW_DAYS = 30


# ===========================================================================
# PURE HELPERS (no DB, no IO) - unit-tested in tests/test_nutrition.py
# ===========================================================================

def _parse_date(s: str):
    """Parse a 'YYYY-MM-DD' string to a date. Raises ValueError if malformed."""
    return datetime.strptime(str(s).strip(), "%Y-%m-%d").date()


def _round1(v: Optional[float]) -> Optional[float]:
    """Round to 1 decimal, preserving None (keeps the payload tidy, None-safe)."""
    return None if v is None else round(float(v), 1)


def calories_out_from_raw(raw: Optional[str]) -> Optional[float]:
    """Pull calories-OUT from a daily_wellness.raw_json blob.

    Path: raw_json -> "stats_and_body" -> "totalKilocalories" (BMR + active).
    None-safe at every step: empty/missing blob, malformed JSON, absent key, or
    a null value all return None rather than raising. No network - this only
    parses an already-synced local row.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    stats = data.get("stats_and_body")
    if not isinstance(stats, dict):
        return None
    val = stats.get("totalKilocalories")
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def streak(dates_with_logs: list[str], today: str) -> int:
    """Count consecutive days with a logged row, ending today OR yesterday.

    Grace: the streak stays "alive" if today isn't logged yet but yesterday was,
    so the count doesn't collapse to zero just because the user hasn't entered
    today's food. Walk back day-by-day from the anchor until the first gap.
    Duplicate / unordered input is fine (dates are de-duped into a set).
    """
    logged = {str(d).strip() for d in dates_with_logs if d}
    if not logged:
        return 0
    today_d = _parse_date(today)
    yesterday_d = today_d - timedelta(days=1)

    if today_d.isoformat() in logged:
        cursor = today_d
    elif yesterday_d.isoformat() in logged:
        cursor = yesterday_d  # grace: today not logged yet, but yesterday was
    else:
        return 0

    count = 0
    while cursor.isoformat() in logged:
        count += 1
        cursor -= timedelta(days=1)
    return count


def net_calories(intake: Optional[float], calories_out: Optional[float]) -> Optional[float]:
    """Net = intake - out. None-safe: either side missing -> None (not a guess)."""
    if intake is None or calories_out is None:
        return None
    return float(intake) - float(calories_out)


def adherence(intake: Optional[float], target: Optional[float]) -> Optional[int]:
    """Intake as a whole-percent of target. None-safe; clamps sensibly.

    Returns None when either input is missing or the target is non-positive
    (can't divide). A negative intake clamps to 0%. Over-target is allowed to
    exceed 100 so the UI can show 'over' honestly rather than capping silently.
    """
    if intake is None or target is None:
        return None
    if float(target) <= 0:
        return None
    pct = max(0.0, float(intake)) / float(target) * 100.0
    return int(round(pct))


def build_nutrition(
    targets: Optional[dict[str, Any]],
    days: list[dict[str, Any]],
    calories_out_by_date: dict[str, float],
    today: str,
) -> dict[str, Any]:
    """Assemble the full nutrition payload, or the empty-state sentinel.

    ``targets`` is None when no nutrition_targets row exists -> {"configured":
    false} so the UI renders a setup CTA instead of empty cards. Otherwise every
    section is present and NULL-safe: today zero-fills when unlogged, calories-out
    and net are None when there's no wellness row, and the recent history is the
    most recent RECENT_WINDOW_DAYS in ascending date order for the trend chart.
    """
    if targets is None:
        return {"configured": False}

    calories_out_by_date = calories_out_by_date or {}

    # Index logged days by date; ascending order drives the history series.
    by_date: dict[str, dict[str, Any]] = {}
    for d in days:
        dt = d.get("date")
        if dt:
            by_date[dt] = d
    ordered = [by_date[k] for k in sorted(by_date)]

    target_calories = targets.get("target_calories")

    # Today: the logged row if present, else a zero-filled manual placeholder so
    # the UI shows 0 vs target rather than a broken/empty card.
    today_row = by_date.get(today)
    if today_row is None:
        today_payload = {
            "date": today, "calories": 0, "protein_g": 0, "carbs_g": 0,
            "fat_g": 0, "source": "manual",
        }
    else:
        today_payload = {
            "date": today,
            "calories": today_row.get("calories") or 0,
            "protein_g": today_row.get("protein_g") or 0,
            "carbs_g": today_row.get("carbs_g") or 0,
            "fat_g": today_row.get("fat_g") or 0,
            "source": today_row.get("source") or "manual",
        }

    calories_out_today = calories_out_by_date.get(today)
    net_today = net_calories(today_payload["calories"], calories_out_today)

    recent = []
    for d in ordered[-RECENT_WINDOW_DAYS:]:
        dt = d["date"]
        cal = d.get("calories")
        out = calories_out_by_date.get(dt)
        recent.append({
            "date": dt,
            "calories": cal,
            "target_calories": target_calories,
            "calories_out": out,
            "net": _round1(net_calories(cal, out)),
        })

    return {
        "configured": True,
        "targets": {
            "target_calories": targets.get("target_calories"),
            "target_protein_g": targets.get("target_protein_g"),
            "target_carbs_g": targets.get("target_carbs_g"),
            "target_fat_g": targets.get("target_fat_g"),
        },
        "today": today_payload,
        "calories_out_today": calories_out_today,
        "net_today": _round1(net_today),
        "streak": streak(list(by_date.keys()), today),
        "recent": recent,
        "adherence_pct": adherence(today_payload["calories"], target_calories),
    }


# ===========================================================================
# WRITE-ROUTE MODELS - mirror app/routes/sets.py (Pydantic + field validators)
# ===========================================================================

def _validate_iso_date(v: str) -> str:
    """Field validator: require a strict 'YYYY-MM-DD' calendar date."""
    try:
        _parse_date(v)
    except (ValueError, TypeError):
        raise ValueError("date must be 'YYYY-MM-DD'")
    return str(v).strip()


class NutritionTargetsIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    target_calories: int = Field(..., ge=0, le=20000)
    target_protein_g: float = Field(..., ge=0, le=2000)
    target_carbs_g: float = Field(..., ge=0, le=2000)
    target_fat_g: float = Field(..., ge=0, le=2000)


class NutritionLogIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: str
    calories: int = Field(..., ge=0, le=30000)
    protein_g: float = Field(default=0, ge=0, le=5000)
    carbs_g: float = Field(default=0, ge=0, le=5000)
    fat_g: float = Field(default=0, ge=0, le=5000)

    @field_validator("date")
    @classmethod
    def _check_date(cls, v: str) -> str:
        return _validate_iso_date(v)


# ===========================================================================
# DB READERS (thin) + ROUTE HANDLERS
# ===========================================================================

def _today_iso() -> str:
    """Local calendar date as 'YYYY-MM-DD' (the app runs single-tenant local)."""
    return date.today().isoformat()


def _read_targets(conn) -> Optional[dict[str, Any]]:
    """Load the single nutrition_targets row as an engine dict, or None if unset."""
    row = conn.execute("SELECT * FROM nutrition_targets WHERE id = 1").fetchone()
    if not row:
        return None
    return {
        "target_calories": row["target_calories"],
        "target_protein_g": row["target_protein_g"],
        "target_carbs_g": row["target_carbs_g"],
        "target_fat_g": row["target_fat_g"],
    }


def _read_days(conn) -> list[dict[str, Any]]:
    """All manual intake rows, date-ascending, as plain dicts."""
    return [dict(r) for r in conn.execute(
        "SELECT date, calories, protein_g, carbs_g, fat_g, source "
        "FROM nutrition_days ORDER BY date"
    ).fetchall()]


def _read_calories_out(conn) -> dict[str, float]:
    """Map date -> calories-OUT, derived from the already-synced wellness rows.

    Reads daily_wellness.raw_json and digs stats_and_body.totalKilocalories. No
    network: this is a pure read of local data. Dates with no usable value are
    omitted so callers see None via .get() rather than a zero."""
    out: dict[str, float] = {}
    for r in conn.execute("SELECT date, raw_json FROM daily_wellness"):
        val = calories_out_from_raw(r["raw_json"])
        if val is not None and r["date"]:
            out[r["date"]] = val
    return out


@router.get("/nutrition")
def get_nutrition() -> dict[str, Any]:
    """Full nutrition payload, or {"configured": false} until targets are set."""
    today = _today_iso()
    with db_conn() as conn:
        targets = _read_targets(conn)
        if targets is None:
            return {"configured": False}
        days = _read_days(conn)
        calories_out_by_date = _read_calories_out(conn)
    return build_nutrition(targets, days, calories_out_by_date, today)


@router.post("/nutrition/targets")
def save_targets(payload: NutritionTargetsIn) -> dict[str, Any]:
    """Create or update the single targets row (id=1). Returns the full payload."""
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO nutrition_targets
                   (id, target_calories, target_protein_g, target_carbs_g,
                    target_fat_g, updated_at)
               VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(id) DO UPDATE SET
                   target_calories  = excluded.target_calories,
                   target_protein_g = excluded.target_protein_g,
                   target_carbs_g   = excluded.target_carbs_g,
                   target_fat_g     = excluded.target_fat_g,
                   updated_at       = CURRENT_TIMESTAMP""",
            (
                payload.target_calories,
                payload.target_protein_g,
                payload.target_carbs_g,
                payload.target_fat_g,
            ),
        )
    return get_nutrition()


@router.post("/nutrition/log", status_code=201)
def log_nutrition(payload: NutritionLogIn) -> dict[str, Any]:
    """Upsert a day's intake keyed by date (re-logging a date overwrites it)."""
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO nutrition_days
                   (date, calories, protein_g, carbs_g, fat_g, source, logged_at)
               VALUES (?, ?, ?, ?, ?, 'manual', CURRENT_TIMESTAMP)
               ON CONFLICT(date) DO UPDATE SET
                   calories  = excluded.calories,
                   protein_g = excluded.protein_g,
                   carbs_g   = excluded.carbs_g,
                   fat_g     = excluded.fat_g,
                   source    = 'manual',
                   logged_at = CURRENT_TIMESTAMP""",
            (
                payload.date,
                payload.calories,
                payload.protein_g,
                payload.carbs_g,
                payload.fat_g,
            ),
        )
        row = conn.execute(
            "SELECT date, calories, protein_g, carbs_g, fat_g, source, logged_at "
            "FROM nutrition_days WHERE date = ?",
            (payload.date,),
        ).fetchone()
    return dict(row)


@router.delete("/nutrition/log/{date}")
def delete_nutrition(date: str) -> Response:
    """Delete a day's intake by date. 404 if no row for that date."""
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM nutrition_days WHERE date = ?", (date,))
        if cur.rowcount == 0:
            raise HTTPException(404, detail=f"no nutrition logged for {date}")
    return Response(status_code=204)
