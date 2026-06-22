"""Garmin Connect data source (Phase 0).

Wraps `garminconnect.Garmin` (v0.3.6 — method names verified in GROUND_TRUTH.md).
Network methods (`login`, `fetch_*`) lazy-import the library so this module — and
its pure `normalize_*` methods — import and unit-test with NO `garminconnect`
installed and NO network access. The orchestrator (Task 7) runs the real fetch.

Field mappings flagged `# VALIDATE` are best-effort paths to be pinned against a
real captured payload before the live sync.
"""
from __future__ import annotations

from typing import Any, Optional

from app.sources.base import coerce_float, coerce_int, dig, store_raw


class GarminSource:
    """Fetch (network) + normalize (pure) for Garmin Connect.

    `email`/`password`/`tokenstore` may be None when only the pure normalizers
    are used (tests, offline). `login()`/`fetch_*()` require real credentials.
    """

    source = "garmin"

    def __init__(
        self,
        email: Optional[str],
        password: Optional[str],
        tokenstore: Optional[str] = None,
    ) -> None:
        self.email = email
        self.password = password
        self.tokenstore = tokenstore
        self._client: Any = None

    # ------------------------------------------------------------------
    # Network — lazy-imported, never exercised by the offline test suite.
    # ------------------------------------------------------------------
    def login(self) -> Any:
        """Authenticate, reusing a cached token dir when present.

        Reuses `tokenstore` so repeat runs don't re-login (underlying auth lib
        is `garth`). Returns the live client. NETWORK — do not call in tests.
        """
        from garminconnect import Garmin  # lazy: keep import offline-safe

        client = Garmin(self.email, self.password)
        # tokenstore caches OAuth tokens between runs; first run logs in and
        # writes the cache, later runs resume from it.
        client.login(tokenstore=self.tokenstore)
        self._client = client
        return client

    def _ensure_client(self) -> Any:
        if self._client is None:
            return self.login()
        return self._client

    def fetch_activities(self, since_date: str, end_date: str) -> list[dict]:
        """get_activities_by_date(start, end). NETWORK."""
        client = self._ensure_client()
        return client.get_activities_by_date(since_date, end_date)

    def fetch_sleep(self, date: str) -> dict:
        """get_sleep_data(date). NETWORK."""
        client = self._ensure_client()
        return client.get_sleep_data(date)

    def fetch_wellness(self, date: str) -> dict:
        """Stitch the several daily getters into one combined dict.

        Mirrors the envelope the wellness normalizer expects. Each getter is a
        separate Garmin endpoint (see GROUND_TRUTH.md). NETWORK.
        """
        client = self._ensure_client()
        return {
            "date": date,
            "stats_and_body": client.get_stats_and_body(date),
            "hrv": client.get_hrv_data(date),
            "training_readiness": client.get_training_readiness(date),
            "rhr": client.get_rhr_day(date),
            # Body Battery getter is date-ranged; single day = (date, date).
            "body_battery": client.get_body_battery(date, date),
            "all_day_stress": client.get_all_day_stress(date),
            # training_status carries acute/chronic training load.
            # VALIDATE: get_training_status exists in 0.3.6 (GROUND_TRUTH) but is
            # not in the brief's explicit fetch list; included so the
            # training_load_* columns aren't dead. Confirm the load path below.
            "training_status": client.get_training_status(date),
        }

    def fetch_nutrition(self, date: str) -> None:
        """Nutrition is DEFERRED.

        # VALIDATE: no nutrition endpoint in 0.3.6 — garminconnect 0.3.6 has no
        # clean food-diary getter (GROUND_TRUTH.md §NOT available). The
        # nutrition_days table exists for forward-compatibility (design spec
        # §9.6) but the Garmin source leaves it empty for now. Returns None so
        # the orchestrator simply writes no nutrition rows.
        """
        return None

    # ------------------------------------------------------------------
    # Normalizers — PURE, fixture-tested, no network.
    # ------------------------------------------------------------------
    def normalize_activity(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map one Garmin activity dict to an `activities` row."""
        activity_id = raw.get("activityId")
        # VALIDATE: activity type lives at activityType.typeKey (e.g. "running").
        atype = dig(raw, "activityType", "typeKey")
        row = {
            "id": f"garmin:{activity_id}",
            "source": self.source,
            "type": atype,
            # VALIDATE: prefer GMT start; confirm field name on real payload.
            "start_time": raw.get("startTimeGMT") or raw.get("startTimeLocal"),
            "duration_s": coerce_int(raw.get("duration")),
            "distance_m": coerce_float(raw.get("distance")),
            "avg_hr": coerce_int(raw.get("averageHR")),
            "elevation_m": coerce_float(raw.get("elevationGain")),
            "calories": coerce_int(raw.get("calories")),
        }
        return store_raw(row, raw)

    def normalize_sleep(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a get_sleep_data payload to a `sleep_nights` row.

        Survives an all-null night (the real-shaped fixture): only `date` is
        guaranteed; every duration/score is None when not recorded.
        """
        dto = raw.get("dailySleepDTO") or {}
        row = {
            # VALIDATE: wake-up date at dailySleepDTO.calendarDate.
            "date": dto.get("calendarDate"),
            "duration_s": coerce_int(dto.get("sleepTimeSeconds")),
            "deep_s": coerce_int(dto.get("deepSleepSeconds")),
            "light_s": coerce_int(dto.get("lightSleepSeconds")),
            "rem_s": coerce_int(dto.get("remSleepSeconds")),
            "awake_s": coerce_int(dto.get("awakeSleepSeconds")),
            # VALIDATE: sleep score at dailySleepDTO.sleepScores.overall.value
            # (absent in the all-null fixture; confirm on a scored night).
            "sleep_score": coerce_int(dig(dto, "sleepScores", "overall", "value")),
        }
        return store_raw(row, raw)

    def normalize_wellness(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map the combined wellness envelope to a `daily_wellness` row.

        `raw` is the dict assembled by fetch_wellness() (one key per getter).
        """
        date = raw.get("date") or dig(raw, "stats_and_body", "calendarDate")
        stats = raw.get("stats_and_body") or {}

        # VO2max for running: PINNED (Task 7) to the training_status payload, which
        # carries the authoritative value. stats_and_body has no vo2 field for this
        # account. Fall back to a stats key only if training_status is absent.
        vo2 = dig(
            raw, "training_status", "mostRecentVO2Max", "generic", "vo2MaxValue"
        )
        if vo2 is None and isinstance(stats, dict):
            vo2 = stats.get("vo2MaxRunning") or stats.get("vO2MaxValue")

        # Overnight HRV at hrv.hrvSummary.lastNightAvg. PINNED: this account does NOT
        # record HRV (get_hrv_data -> {}), so this is None in practice. Kept for
        # accounts/devices that do record it.
        hrv = dig(raw, "hrv", "hrvSummary", "lastNightAvg")

        # training_readiness: PINNED empty for this account (watch model doesn't
        # compute it; getter returns []). Handles list/dict shapes for devices that do.
        tr = raw.get("training_readiness")
        readiness = None
        if isinstance(tr, list) and tr:
            readiness = tr[0].get("score")
        elif isinstance(tr, dict):
            readiness = tr.get("score")

        # Body Battery high/low: PINNED to the daily summary fields in stats_and_body
        # (always present, one call). Fall back to deriving from the body_battery
        # values array only if the summary fields are missing.
        bb_high = coerce_int(stats.get("bodyBatteryHighestValue")) if isinstance(stats, dict) else None
        bb_low = coerce_int(stats.get("bodyBatteryLowestValue")) if isinstance(stats, dict) else None
        if bb_high is None and bb_low is None:
            bb_high, bb_low = self._body_battery_high_low(raw.get("body_battery"))

        # Training load: PINNED. garminconnect 0.3.6 exposes MONTHLY aerobic/anaerobic
        # loads under the per-device map (no acute/chronic split). Take the first
        # device entry. acute<-monthlyLoadAerobicLow, chronic<-monthlyLoadAerobicHigh
        # as the two aerobic buckets we surface (see PINNED_FIELDS.md).
        load_acute = None
        load_chronic = None
        dev_map = dig(
            raw, "training_status", "mostRecentTrainingLoadBalance",
            "metricsTrainingLoadBalanceDTOMap",
        )
        if isinstance(dev_map, dict) and dev_map:
            first_dev = next(iter(dev_map.values()), None)
            if isinstance(first_dev, dict):
                load_acute = first_dev.get("monthlyLoadAerobicLow")
                load_chronic = first_dev.get("monthlyLoadAerobicHigh")

        # avg stress: PINNED to stats_and_body.averageStressLevel (one call). Fall
        # back to the dedicated all_day_stress getter if absent.
        stress = stats.get("averageStressLevel") if isinstance(stats, dict) else None
        if stress is None:
            stress = dig(raw, "all_day_stress", "avgStressLevel")

        row = {
            "date": date,
            "vo2max_running": coerce_float(vo2),
            # resting HR: dedicated rhr getter first, fall back to stats.
            "resting_hr": coerce_int(
                dig(raw, "rhr", "restingHeartRate")
                if dig(raw, "rhr", "restingHeartRate") is not None
                else stats.get("restingHeartRate")
            ),
            "hrv_overnight": coerce_float(hrv),
            "body_battery_high": bb_high,
            "body_battery_low": bb_low,
            "stress_avg": coerce_int(stress),
            "training_readiness": coerce_int(readiness),
            "training_load_acute": coerce_float(load_acute),
            "training_load_chronic": coerce_float(load_chronic),
            "steps": coerce_int(stats.get("totalSteps") if isinstance(stats, dict) else None),
        }
        return store_raw(row, raw)

    @staticmethod
    def _body_battery_high_low(
        bb: Any,
    ) -> tuple[Optional[int], Optional[int]]:
        """Derive Body Battery daily high/low from the values array.

        VALIDATE: real get_body_battery returns a list whose [0] holds
        `bodyBatteryValuesArray` of [timestamp_ms, level] pairs; high/low are
        max/min of the levels. Confirm against a real capture.
        """
        if isinstance(bb, list) and bb:
            entry = bb[0]
        elif isinstance(bb, dict):
            entry = bb
        else:
            return None, None
        values = entry.get("bodyBatteryValuesArray") if isinstance(entry, dict) else None
        levels = []
        if isinstance(values, list):
            for pair in values:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    lvl = coerce_int(pair[1])
                    if lvl is not None:
                        levels.append(lvl)
        if levels:
            return max(levels), min(levels)
        # No values array → cannot derive high/low. (charged/drained are daily
        # totals, NOT high/low, so we do not substitute them.) VALIDATE shape.
        return None, None
