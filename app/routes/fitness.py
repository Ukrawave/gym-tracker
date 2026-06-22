"""Fitness dashboard routes (Phase 1) — READ-ONLY over the Phase 0 tables.

Surfaces Garmin + Strava data (activities, daily_wellness, sleep_nights,
sync_state) for four dashboard views. Purely additive: no existing route,
table, or schema is touched. NO network — only reads the local DB.

Endpoints (registered under /api in app/main.py):
    GET /api/fitness/overview   -> compact KPIs for the Dashboard tiles
    GET /api/fitness/running    -> VO2max trend, deduped runs, race predictions
    GET /api/fitness/training   -> load trend, resting-HR trend, derived readiness
    GET /api/fitness/sleep      -> sleep-score + stage + body-battery/stress series

The PURE logic (dedup, Riegel race prediction, push/hold/rest derivation, and
the row->payload builders) lives in small module-level functions so it can be
unit-tested fully offline. See tests/test_fitness.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter

from app.db import db_conn

router = APIRouter()


# ===================================================================
# PURE HELPERS (no DB, no IO) — unit-tested in tests/test_fitness.py
# ===================================================================

# Map the two sources' free-text activity types onto a small canonical set.
# Garmin emits lowercase ("running"), Strava TitleCase ("Run"). Matching MUST
# be case-insensitive and cover both spellings. Extra sports are recognised so
# a future cycling/walking view can reuse this without a schema change.
_TYPE_ALIASES = {
    "run": "run", "running": "run",
    "ride": "ride", "cycling": "ride", "biking": "ride", "bike": "ride",
    "walk": "walk", "walking": "walk", "hiking": "walk", "hike": "walk",
}


def normalize_activity_type(raw: Optional[str]) -> Optional[str]:
    """Canonicalise an activity type string. Returns None for unknown/empty."""
    if not raw:
        return None
    return _TYPE_ALIASES.get(str(raw).strip().lower())


def _epoch(start_time: Optional[str]) -> Optional[float]:
    """Parse an ISO start_time to epoch seconds. None if unparseable.

    Garmin emits a naive ``startTimeGMT`` ("2026-06-17 06:26:57") that is ALREADY
    UTC despite carrying no offset, while Strava emits "...Z". A naive string must
    therefore be interpreted as UTC, not local time — otherwise the same physical
    run from the two sources lands an offset (e.g. 1h) apart and dedup fails to
    cluster them.
    """
    if not start_time:
        return None
    raw = str(start_time).strip()
    # sqlite/Garmin emit a trailing 'Z'; fromisoformat wants +00:00.
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except (ValueError, OverflowError):
        return None
    # Naive timestamp -> treat as UTC (Garmin GMT without an explicit offset).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _dist_tol(anchor_m: Optional[float]) -> float:
    """Distance tolerance for treating two runs as the same physical run.

    max(100 m, 2% of distance): absolute floor for short runs, percentage for
    long ones where GPS providers diverge more in metres.
    """
    if anchor_m is None:
        return 100.0
    return max(100.0, abs(float(anchor_m)) * 0.02)


def _completeness(row: dict[str, Any]) -> int:
    """Count populated 'rich' fields — used only to break source ties."""
    return sum(
        1 for k in ("avg_hr", "elevation_m", "calories", "duration_s")
        if row.get(k) is not None
    )


def _prefer_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the canonical row for a cluster: Garmin wins (richer), else the
    most complete row, else the first."""
    garmin = [r for r in rows if (r.get("source") or "").lower() == "garmin"]
    pool = garmin or rows
    return max(pool, key=_completeness)


def dedup_runs(
    rows: list[dict[str, Any]],
    time_tol_s: int = 300,
    only_type: Optional[str] = "run",
) -> list[dict[str, Any]]:
    """Collapse the SAME physical activity recorded by both Garmin and Strava
    into one row, preferring the Garmin copy.

    Two rows are the same activity when their start times are within
    ``time_tol_s`` (default 5 min) AND their distances are within ``_dist_tol``.
    Greedy time-ordered clustering: robust to 5-minute-boundary straddling that
    naive fixed-window bucketing gets wrong. Output is sorted start-time desc.

    ``only_type`` filters to a canonical type ("run"); pass None to keep all.
    """
    if only_type is not None:
        rows = [r for r in rows if normalize_activity_type(r.get("type")) == only_type]

    # Stable time order; rows with an unparseable time sort last as singletons.
    decorated = [(_epoch(r.get("start_time")), r) for r in rows]
    decorated.sort(key=lambda t: (t[0] is None, t[0] or 0.0))

    clusters: list[dict[str, Any]] = []
    for ep, r in decorated:
        placed = False
        if ep is not None:
            rdist = r.get("distance_m")
            for cl in clusters:
                if cl["ep"] is None:
                    continue
                if abs(ep - cl["ep"]) > time_tol_s:
                    continue
                adist = cl["dist"]
                if rdist is None or adist is None:
                    continue  # can't confirm same distance -> keep separate
                if abs(float(rdist) - float(adist)) <= _dist_tol(adist):
                    cl["rows"].append(r)
                    placed = True
                    break
        if not placed:
            clusters.append({"ep": ep, "dist": r.get("distance_m"), "rows": [r]})

    out = [_prefer_row(cl["rows"]) for cl in clusters]
    out.sort(key=lambda r: r.get("start_time") or "", reverse=True)
    return out


# Riegel's endurance model: T2 = T1 * (D2 / D1) ** 1.06. The 1.06 fatigue
# exponent is Pete Riegel's published constant (Runner's World, 1977) and is
# the standard simple race-time predictor. Good within ~3x of the source
# distance; we extrapolate 5K..Marathon from a recent run, which is in range.
_RIEGEL_EXP = 1.06

# Canonical race distances (metres). Half = 21.0975 km, Marathon = 42.195 km.
_RACES = (
    ("5K", 5000.0),
    ("10K", 10000.0),
    ("Half Marathon", 21097.5),
    ("Marathon", 42195.0),
)


def riegel_predict_time(d1_m: float, t1_s: float, d2_m: float) -> float:
    """Predicted time (s) to cover d2 given a d1 run in t1, via Riegel."""
    return float(t1_s) * (float(d2_m) / float(d1_m)) ** _RIEGEL_EXP


def hms(seconds: Optional[float]) -> str:
    """Format seconds as 'M:SS' or 'H:MM:SS'. '—' for None/invalid."""
    if seconds is None:
        return "—"
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "—"
    if s < 0:
        return "—"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def race_predictions(distance_m: Optional[float], time_s: Optional[float]) -> list[dict[str, Any]]:
    """Riegel predictions for the standard race ladder from one source run.

    Returns [] when the source run is missing/zero (NULL-safe)."""
    if not distance_m or not time_s:
        return []
    try:
        d1 = float(distance_m)
        t1 = float(time_s)
    except (TypeError, ValueError):
        return []
    if d1 <= 0 or t1 <= 0:
        return []
    preds = []
    for name, d2 in _RACES:
        t2 = riegel_predict_time(d1, t1, d2)
        preds.append({"distance": name, "distance_m": d2, "time_s": round(t2, 1), "time": hms(t2)})
    return preds


def _pace_s_per_km(distance_m: Optional[float], duration_s: Optional[float]) -> Optional[float]:
    """Average pace in seconds per kilometre, or None if not computable."""
    if not distance_m or not duration_s:
        return None
    try:
        km = float(distance_m) / 1000.0
        if km <= 0:
            return None
        return float(duration_s) / km
    except (TypeError, ValueError, ZeroDivisionError):
        return None


# Derived-readiness thresholds (NOT Garmin's training_readiness, which is always
# NULL for this account). We infer a push/hold/rest signal from two independent
# strain proxies and count how many fire:
#   2 -> rest, 1 -> hold, 0 -> push.
_LOAD_STRAIN_RATIO = 1.3   # acute load >=130% of its recent baseline = strained
_RHR_STRAIN_DELTA = 4      # resting HR >=4 bpm over baseline = under-recovered


def derive_readiness(
    acute_load: Optional[float],
    rhr_latest: Optional[float],
    rhr_baseline: Optional[float],
    load_high: Optional[float],
) -> dict[str, str]:
    """Derive a push/hold/rest readiness signal. Clearly labelled as DERIVED.

    ``load_high`` is the recent baseline acute load to compare against.
    All-None inputs degrade safely to 'push' (no strain detected).
    """
    reasons: list[str] = []
    strain = 0

    load_strained = (
        acute_load is not None
        and load_high is not None
        and load_high > 0
        and float(acute_load) >= float(load_high) * _LOAD_STRAIN_RATIO
    )
    if load_strained:
        strain += 1
        reasons.append(
            f"acute load {float(acute_load):.0f} is {float(acute_load)/float(load_high)*100:.0f}% "
            f"of recent baseline {float(load_high):.0f}"
        )
    elif acute_load is not None and load_high:
        reasons.append(f"acute load {float(acute_load):.0f} near baseline {float(load_high):.0f}")

    rhr_elevated = (
        rhr_latest is not None
        and rhr_baseline is not None
        and float(rhr_latest) >= float(rhr_baseline) + _RHR_STRAIN_DELTA
    )
    if rhr_elevated:
        strain += 1
        reasons.append(
            f"resting HR {float(rhr_latest):.0f} is +{float(rhr_latest)-float(rhr_baseline):.0f} "
            f"over baseline {float(rhr_baseline):.0f}"
        )
    elif rhr_latest is not None and rhr_baseline is not None:
        reasons.append(f"resting HR {float(rhr_latest):.0f} steady vs baseline {float(rhr_baseline):.0f}")

    if strain >= 2:
        state = "rest"
    elif strain == 1:
        state = "hold"
    else:
        state = "push"

    if not reasons:
        reasons.append("insufficient recent data — defaulting to push")
    return {"state": state, "reason": "; ".join(reasons) + " (derived)"}


def _latest_with(rows: list[dict[str, Any]], key: str) -> Optional[dict[str, Any]]:
    """Most recent row (by 'date' desc) whose ``key`` is non-null."""
    candidates = [r for r in rows if r.get(key) is not None and r.get("date")]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["date"])


def _mean(values: list[float]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_overview(
    wellness: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    sleep: list[dict[str, Any]],
    sync: dict[str, Any],
) -> dict[str, Any]:
    """Compact KPI dict for the Dashboard Overview tiles. NULL-safe throughout:
    every section is None when its data is absent, and the always-NULL columns
    (hrv_overnight, training_readiness) are never required."""
    vo2_row = _latest_with(wellness, "vo2max_running")
    vo2max = (
        {"value": vo2_row["vo2max_running"], "date": vo2_row["date"]}
        if vo2_row else None
    )

    rhr_row = _latest_with(wellness, "resting_hr")
    resting_hr = (
        {"value": rhr_row["resting_hr"], "date": rhr_row["date"]}
        if rhr_row else None
    )

    bb_row = _latest_with(wellness, "body_battery_high")
    body_battery = (
        {
            "high": bb_row["body_battery_high"],
            "low": bb_row.get("body_battery_low"),
            "date": bb_row["date"],
        }
        if bb_row else None
    )

    runs = dedup_runs(activities)
    last_run = None
    if runs:
        r = runs[0]
        last_run = {
            "id": r.get("id"),
            "date": (r.get("start_time") or "")[:10] or None,
            "start_time": r.get("start_time"),
            "distance_m": r.get("distance_m"),
            "duration_s": r.get("duration_s"),
            "avg_hr": r.get("avg_hr"),
            "pace_s_per_km": _pace_s_per_km(r.get("distance_m"), r.get("duration_s")),
        }

    sleep_row = _latest_with(sleep, "duration_s")
    last_sleep = (
        {
            "score": sleep_row.get("sleep_score"),
            "date": sleep_row["date"],
            "duration_s": sleep_row.get("duration_s"),
        }
        if sleep_row else None
    )

    # Data-freshness summary from sync_state (most-recent run across sources).
    sources = (sync or {}).get("sources", {}) or {}
    last_sync = None
    for s in sources.values():
        ts = s.get("last_run_at") if isinstance(s, dict) else None
        if ts and (last_sync is None or ts > last_sync):
            last_sync = ts

    return {
        "vo2max": vo2max,
        "resting_hr": resting_hr,
        "last_run": last_run,
        "body_battery": body_battery,
        "last_sleep": last_sleep,
        "freshness": {"last_sync": last_sync, "sources": sources},
    }


def _vo2max_series(wellness: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """[{date,value}] for days with a VO2max reading, date-ascending. The value
    is flat between qualifying runs — that step shape is correct, not faked."""
    series = [
        {"date": r["date"], "value": r["vo2max_running"]}
        for r in wellness
        if r.get("vo2max_running") is not None and r.get("date")
    ]
    series.sort(key=lambda p: p["date"])
    return series


def _best_run_for_prediction(runs: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Pick the prediction basis: fastest pace among recent runs >=3 km (short
    runs make Riegel over-optimistic; a solid recent run is most predictive)."""
    eligible = [
        r for r in runs
        if (r.get("distance_m") or 0) >= 3000
        and _pace_s_per_km(r.get("distance_m"), r.get("duration_s")) is not None
    ]
    pool = eligible or [
        r for r in runs
        if _pace_s_per_km(r.get("distance_m"), r.get("duration_s")) is not None
    ]
    if not pool:
        return None
    return min(pool, key=lambda r: _pace_s_per_km(r["distance_m"], r["duration_s"]))


def build_running(
    activities: list[dict[str, Any]],
    wellness: list[dict[str, Any]],
) -> dict[str, Any]:
    """Running page payload: VO2max series, deduped runs (with pace), and a
    Riegel race-prediction table from the best recent run."""
    runs = dedup_runs(activities)
    enriched = []
    for r in runs:
        enriched.append({
            "id": r.get("id"),
            "source": r.get("source"),
            "date": (r.get("start_time") or "")[:10] or None,
            "start_time": r.get("start_time"),
            "distance_m": r.get("distance_m"),
            "duration_s": r.get("duration_s"),
            "avg_hr": r.get("avg_hr"),
            "elevation_m": r.get("elevation_m"),
            "calories": r.get("calories"),
            "pace_s_per_km": _pace_s_per_km(r.get("distance_m"), r.get("duration_s")),
        })

    basis = _best_run_for_prediction(runs)
    preds = race_predictions(basis.get("distance_m"), basis.get("duration_s")) if basis else []

    return {
        "vo2max_series": _vo2max_series(wellness),
        "runs": enriched,
        "race_predictions": preds,
        "prediction_basis": (
            {
                "date": (basis.get("start_time") or "")[:10] or None,
                "distance_m": basis.get("distance_m"),
                "duration_s": basis.get("duration_s"),
                "pace_s_per_km": _pace_s_per_km(basis.get("distance_m"), basis.get("duration_s")),
            }
            if basis else None
        ),
    }


def build_training(
    wellness: list[dict[str, Any]],
    activities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Training page payload: acute/chronic load series, resting-HR series, and
    a DERIVED push/hold/rest readiness signal (training_readiness is NULL)."""
    rows = sorted([r for r in wellness if r.get("date")], key=lambda r: r["date"])

    load_series = [
        {
            "date": r["date"],
            "acute": r.get("training_load_acute"),
            "chronic": r.get("training_load_chronic"),
        }
        for r in rows
    ]
    resting_hr_series = [
        {"date": r["date"], "value": r.get("resting_hr")} for r in rows
    ]

    # Readiness inputs derived from the series itself (no Garmin readiness):
    #  - acute_load: most recent non-null acute load
    #  - load_high : mean of the PRIOR acute loads (recent baseline)
    #  - rhr_latest / rhr_baseline: latest vs mean of prior resting HRs
    acute_rows = [r for r in rows if r.get("training_load_acute") is not None]
    acute_load = acute_rows[-1]["training_load_acute"] if acute_rows else None
    load_high = _mean([r["training_load_acute"] for r in acute_rows[:-1]]) if len(acute_rows) > 1 else None

    rhr_rows = [r for r in rows if r.get("resting_hr") is not None]
    rhr_latest = rhr_rows[-1]["resting_hr"] if rhr_rows else None
    rhr_baseline = _mean([r["resting_hr"] for r in rhr_rows[:-1]]) if len(rhr_rows) > 1 else None

    readiness = derive_readiness(acute_load, rhr_latest, rhr_baseline, load_high)

    return {
        "load_series": load_series,
        "resting_hr_series": resting_hr_series,
        "readiness": readiness,
        "inputs": {
            "acute_load": acute_load,
            "load_baseline": round(load_high, 1) if load_high is not None else None,
            "rhr_latest": rhr_latest,
            "rhr_baseline": round(rhr_baseline, 1) if rhr_baseline is not None else None,
        },
    }


def build_sleep(
    sleep: list[dict[str, Any]],
    wellness: list[dict[str, Any]],
) -> dict[str, Any]:
    """Sleep page payload. Un-worn / un-synced nights (NULL duration) are
    SKIPPED — never plotted as zero."""
    nights_raw = sorted(
        [r for r in sleep if r.get("duration_s") is not None and r.get("date")],
        key=lambda r: r["date"],
    )
    nights = [
        {
            "date": r["date"],
            "duration_s": r.get("duration_s"),
            "deep_s": r.get("deep_s"),
            "light_s": r.get("light_s"),
            "rem_s": r.get("rem_s"),
            "awake_s": r.get("awake_s"),
            "score": r.get("sleep_score"),
        }
        for r in nights_raw
    ]
    score_series = [
        {"date": r["date"], "score": r["sleep_score"]}
        for r in nights_raw
        if r.get("sleep_score") is not None
    ]

    wrows = sorted([r for r in wellness if r.get("date")], key=lambda r: r["date"])
    stress_series = [
        {"date": r["date"], "value": r["stress_avg"]}
        for r in wrows
        if r.get("stress_avg") is not None
    ]
    body_battery_series = [
        {"date": r["date"], "high": r.get("body_battery_high"), "low": r.get("body_battery_low")}
        for r in wrows
        if r.get("body_battery_high") is not None or r.get("body_battery_low") is not None
    ]

    return {
        "score_series": score_series,
        "nights": nights,
        "stress_series": stress_series,
        "body_battery_series": body_battery_series,
    }


# ===================================================================
# DB READERS (thin) + ROUTE HANDLERS
# ===================================================================

def _fetch_wellness(conn) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        """SELECT date, vo2max_running, resting_hr, hrv_overnight,
                  body_battery_high, body_battery_low, stress_avg,
                  training_readiness, training_load_acute, training_load_chronic, steps
           FROM daily_wellness ORDER BY date"""
    ).fetchall()]


def _fetch_activities(conn) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        """SELECT id, source, type, start_time, duration_s, distance_m,
                  avg_hr, elevation_m, calories
           FROM activities ORDER BY start_time DESC"""
    ).fetchall()]


def _fetch_sleep(conn) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        """SELECT date, duration_s, deep_s, light_s, rem_s, awake_s, sleep_score
           FROM sleep_nights ORDER BY date"""
    ).fetchall()]


def _fetch_sync(conn) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT source, last_run_at, last_status, last_watermark FROM sync_state"
    ).fetchall()
    return {"sources": {r["source"]: dict(r) for r in rows}}


@router.get("/fitness/overview")
def fitness_overview() -> dict[str, Any]:
    """Compact KPIs for the Dashboard Overview tiles."""
    with db_conn() as conn:
        wellness = _fetch_wellness(conn)
        activities = _fetch_activities(conn)
        sleep = _fetch_sleep(conn)
        sync = _fetch_sync(conn)
    return build_overview(wellness, activities, sleep, sync)


@router.get("/fitness/running")
def fitness_running() -> dict[str, Any]:
    """VO2max trend, deduped runs, and Riegel race predictions."""
    with db_conn() as conn:
        activities = _fetch_activities(conn)
        wellness = _fetch_wellness(conn)
    return build_running(activities, wellness)


@router.get("/fitness/training")
def fitness_training() -> dict[str, Any]:
    """Training-load + resting-HR trends and a derived readiness signal."""
    with db_conn() as conn:
        wellness = _fetch_wellness(conn)
        activities = _fetch_activities(conn)
    return build_training(wellness, activities)


@router.get("/fitness/sleep")
def fitness_sleep() -> dict[str, Any]:
    """Sleep-score, stage breakdown, stress, and Body Battery night-by-night."""
    with db_conn() as conn:
        sleep = _fetch_sleep(conn)
        wellness = _fetch_wellness(conn)
    return build_sleep(sleep, wellness)
