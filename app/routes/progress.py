"""Progress + dashboard routes.

GET /api/progress/exercise/{id}  -> per-session series for charts
GET /api/dashboard               -> aggregate telemetry for the home HUD
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Any

from fastapi import APIRouter, HTTPException

from app.db import db_conn, brzycki_est_1rm

router = APIRouter()


@router.get("/progress/exercise/{exercise_id}")
def progress_for_exercise(exercise_id: str) -> dict[str, Any]:
    """Per-session aggregates for charting: max weight, est 1RM, total volume."""
    with db_conn() as conn:
        ex = conn.execute(
            "SELECT id, name, muscle_group, media_slug FROM exercises WHERE id = ?",
            (exercise_id,),
        ).fetchone()
        if not ex:
            raise HTTPException(404, detail=f"exercise '{exercise_id}' not found")
        rows = conn.execute(
            """SELECT s.id AS session_id, s.date,
                      se.weight, se.reps, se.entry_status
               FROM set_entries se
               JOIN sessions s ON s.id = se.session_id
               WHERE se.exercise_id = ? AND se.entry_status != 'Warm-up'
               ORDER BY s.date, se.id""",
            (exercise_id,),
        ).fetchall()
    by_session: dict[int, dict[str, Any]] = {}
    for r in rows:
        sid = r["session_id"]
        b = by_session.setdefault(
            sid,
            {"session_id": sid, "date": r["date"], "max_weight": 0.0, "est_1rm": 0.0, "total_volume": 0.0, "sets": 0},
        )
        w = float(r["weight"])
        reps = int(r["reps"])
        b["max_weight"] = max(b["max_weight"], w)
        b["est_1rm"] = max(b["est_1rm"], brzycki_est_1rm(w, reps))
        b["total_volume"] += w * reps
        b["sets"] += 1
    series = sorted(by_session.values(), key=lambda x: (x["date"], x["session_id"]))
    for s in series:
        s["max_weight"] = round(s["max_weight"], 2)
        s["est_1rm"] = round(s["est_1rm"], 2)
        s["total_volume"] = round(s["total_volume"], 2)
    return {
        "exercise": dict(ex),
        "series": series,
    }


def _iso_week_key(d: str) -> str:
    """Return ISO-week key 'YYYY-Www' for a 'YYYY-MM-DD' string."""
    try:
        dt = datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return d
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


@router.get("/dashboard")
def dashboard() -> dict[str, Any]:
    """Aggregate telemetry for the home HUD."""
    today_iso = date.today().isoformat()
    # 'Counted sessions' = sessions that include at least one set_entries row.
    # This keeps the headline counters consistent with the history list and
    # with the storage-hygiene rule enforced by app/cleanup.py.
    _COUNTED = "EXISTS (SELECT 1 FROM set_entries se WHERE se.session_id = sessions.id)"
    with db_conn() as conn:
        total_sessions = conn.execute(
            f"SELECT COUNT(*) AS c FROM sessions WHERE {_COUNTED}"
        ).fetchone()["c"]
        agg = conn.execute(
            """SELECT COALESCE(SUM(weight*reps),0) AS vol,
                      COUNT(*) AS sets,
                      COALESCE(SUM(reps),0) AS reps
               FROM set_entries"""
        ).fetchone()
        last7 = conn.execute(
            f"""SELECT COUNT(*) AS c FROM sessions
               WHERE {_COUNTED} AND date >= date(?, '-7 days')""",
            (today_iso,),
        ).fetchone()["c"]
        last30 = conn.execute(
            f"""SELECT COUNT(*) AS c FROM sessions
               WHERE {_COUNTED} AND date >= date(?, '-30 days')""",
            (today_iso,),
        ).fetchone()["c"]
        muscle_rows = conn.execute(
            """SELECT ex.muscle_group, COUNT(se.id) AS sets
               FROM set_entries se
               JOIN sessions s ON s.id = se.session_id
               JOIN exercises ex ON ex.id = se.exercise_id
               WHERE s.date >= date(?, '-30 days')
               GROUP BY ex.muscle_group""",
            (today_iso,),
        ).fetchall()
        recent_prs = conn.execute(
            """SELECT pr.*, ex.name AS exercise_name, ex.muscle_group
               FROM personal_records pr
               JOIN exercises ex ON ex.id = pr.exercise_id
               ORDER BY pr.pr_date DESC, pr.id DESC LIMIT 5"""
        ).fetchall()
        current = conn.execute(
            """SELECT id, category, start_time, date FROM sessions
               WHERE end_time IS NULL
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        recent_sessions_rows = conn.execute(
            """SELECT s.*,
                      (SELECT COUNT(*) FROM set_entries se WHERE se.session_id = s.id) AS total_sets,
                      (SELECT COALESCE(SUM(weight*reps),0) FROM set_entries se WHERE se.session_id = s.id) AS total_volume
               FROM sessions s
               WHERE EXISTS (SELECT 1 FROM set_entries se2 WHERE se2.session_id = s.id)
               ORDER BY s.id DESC LIMIT 5"""
        ).fetchall()
        weekly_rows = conn.execute(
            """SELECT s.date AS d, COALESCE(SUM(se.weight*se.reps),0) AS vol
               FROM sessions s
               LEFT JOIN set_entries se ON se.session_id = s.id
               WHERE s.date >= date(?, '-90 days')
                 AND EXISTS (SELECT 1 FROM set_entries se2 WHERE se2.session_id = s.id)
               GROUP BY s.date""",
            (today_iso,),
        ).fetchall()

    muscle_distribution: dict[str, int] = {}
    for r in muscle_rows:
        muscle_distribution[r["muscle_group"]] = int(r["sets"])

    weekly: dict[str, float] = {}
    for r in weekly_rows:
        wk = _iso_week_key(r["d"])
        weekly[wk] = round(weekly.get(wk, 0.0) + float(r["vol"]), 2)
    weekly_series = [{"week": k, "volume": v} for k, v in sorted(weekly.items())][-12:]

    recent_sessions = []
    for r in recent_sessions_rows:
        s = dict(r)
        s["total_sets"] = int(s.get("total_sets") or 0)
        s["total_volume"] = round(float(s.get("total_volume") or 0), 2)
        recent_sessions.append(s)

    return {
        "total_sessions": int(total_sessions),
        "total_volume_kg": round(float(agg["vol"] or 0), 2),
        "total_sets": int(agg["sets"] or 0),
        "total_reps": int(agg["reps"] or 0),
        "sessions_last_7_days": int(last7),
        "sessions_last_30_days": int(last30),
        "muscle_distribution": muscle_distribution,
        "weekly_volume": weekly_series,
        "recent_prs": [dict(r) for r in recent_prs],
        "current_session": dict(current) if current else None,
        "recent_sessions": recent_sessions,
    }
