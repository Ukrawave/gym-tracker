"""TDD — pure normalizers map raw API payloads to additive-table rows.

Runs fully offline against the synthetic/real-shaped fixtures in
tests/fixtures/. No network, no credentials. The fetch_* methods (which DO hit
the network) are intentionally NOT exercised here — only the pure normalizers.
"""
from __future__ import annotations

import json
import os
import unittest

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name: str):
    with open(os.path.join(FIXDIR, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


# Columns of each target table (mirrors app.db SCHEMA_SQL).
ACTIVITY_COLS = {
    "id", "source", "type", "start_time", "duration_s", "distance_m",
    "avg_hr", "elevation_m", "calories", "raw_json",
}
WELLNESS_COLS = {
    "date", "vo2max_running", "resting_hr", "hrv_overnight",
    "body_battery_high", "body_battery_low", "stress_avg",
    "training_readiness", "training_load_acute", "training_load_chronic",
    "steps", "raw_json",
}
SLEEP_COLS = {
    "date", "duration_s", "deep_s", "light_s", "rem_s", "awake_s",
    "sleep_score", "raw_json",
}


class TestGarminActivityNormalizer(unittest.TestCase):
    def setUp(self) -> None:
        from app.sources.garmin import GarminSource

        self.src = GarminSource(email=None, password=None)
        self.raw = load("garmin_activities.json")

    def test_returns_activities_row(self) -> None:
        raw_one = self.raw[0] if isinstance(self.raw, list) else self.raw["activities"][0]
        row = self.src.normalize_activity(raw_one)
        self.assertEqual(set(row.keys()), ACTIVITY_COLS)

    def test_id_is_source_prefixed(self) -> None:
        raw_one = self.raw[0] if isinstance(self.raw, list) else self.raw["activities"][0]
        row = self.src.normalize_activity(raw_one)
        self.assertTrue(row["id"].startswith("garmin:"))
        self.assertEqual("garmin", row["source"])

    def test_types_are_db_friendly(self) -> None:
        raw_one = self.raw[0] if isinstance(self.raw, list) else self.raw["activities"][0]
        row = self.src.normalize_activity(raw_one)
        self.assertIsInstance(row["duration_s"], int)
        self.assertIsInstance(row["distance_m"], float)
        self.assertIsInstance(row["avg_hr"], int)
        self.assertIsInstance(row["calories"], int)
        self.assertIsInstance(row["type"], str)
        # raw_json must be a JSON string round-trippable back to the source dict
        self.assertEqual(json.loads(row["raw_json"])["activityId"], raw_one["activityId"])


class TestGarminSleepNormalizer(unittest.TestCase):
    def setUp(self) -> None:
        from app.sources.garmin import GarminSource

        self.src = GarminSource(email=None, password=None)
        self.raw = load("garmin_sleep.json")

    def test_returns_sleep_row(self) -> None:
        row = self.src.normalize_sleep(self.raw)
        self.assertEqual(set(row.keys()), SLEEP_COLS)

    def test_date_is_populated(self) -> None:
        row = self.src.normalize_sleep(self.raw)
        self.assertEqual(row["date"], "2026-06-22")

    def test_all_null_night_does_not_crash(self) -> None:
        # The real-shaped fixture is a night with every sleep-seconds field null.
        # Normalizer must degrade gracefully: date set, the rest None — no raise.
        row = self.src.normalize_sleep(self.raw)
        self.assertIsNone(row["duration_s"])
        self.assertIsNone(row["deep_s"])
        self.assertIsNone(row["sleep_score"])


class TestGarminWellnessNormalizer(unittest.TestCase):
    def setUp(self) -> None:
        from app.sources.garmin import GarminSource

        self.src = GarminSource(email=None, password=None)
        self.raw = load("garmin_wellness.json")

    def test_returns_wellness_row(self) -> None:
        row = self.src.normalize_wellness(self.raw)
        self.assertEqual(set(row.keys()), WELLNESS_COLS)

    def test_known_values_map_through(self) -> None:
        row = self.src.normalize_wellness(self.raw)
        self.assertEqual(row["date"], "2026-06-20")
        self.assertEqual(row["steps"], 11432)
        self.assertEqual(row["resting_hr"], 48)
        self.assertEqual(row["stress_avg"], 34)
        self.assertEqual(row["training_readiness"], 81)
        self.assertEqual(row["hrv_overnight"], 68)
        # VO2max running is sourced from training_status.mostRecentVO2Max.generic
        # (pinned against the real payload in Task 7).
        self.assertEqual(row["vo2max_running"], 52.0)

    def test_body_battery_high_low_derived(self) -> None:
        row = self.src.normalize_wellness(self.raw)
        # high/low read from stats_and_body.bodyBatteryHighest/LowestValue
        # (pinned: the daily summary fields, present on every real day).
        self.assertEqual(row["body_battery_high"], 88)
        self.assertEqual(row["body_battery_low"], 21)

    def test_training_load_mapped(self) -> None:
        row = self.src.normalize_wellness(self.raw)
        # garminconnect 0.3.6 exposes MONTHLY aerobic loads under the per-device
        # map (no acute/chronic split); acute<-aerobicLow, chronic<-aerobicHigh.
        self.assertEqual(row["training_load_acute"], 412.0)
        self.assertEqual(row["training_load_chronic"], 388.0)


class TestStravaActivityNormalizer(unittest.TestCase):
    def setUp(self) -> None:
        from app.sources.strava import StravaSource

        self.src = StravaSource(
            client_id=None, client_secret=None, refresh_token=None
        )
        self.raw = load("strava_activities.json")

    def test_returns_activities_row(self) -> None:
        raw_one = self.raw[0] if isinstance(self.raw, list) else self.raw["activities"][0]
        row = self.src.normalize_activity(raw_one)
        self.assertEqual(set(row.keys()), ACTIVITY_COLS)

    def test_id_is_source_prefixed(self) -> None:
        raw_one = self.raw[0] if isinstance(self.raw, list) else self.raw["activities"][0]
        row = self.src.normalize_activity(raw_one)
        self.assertEqual(row["id"], f"strava:{raw_one['id']}")
        self.assertEqual("strava", row["source"])

    def test_types_are_db_friendly(self) -> None:
        raw_one = self.raw[0] if isinstance(self.raw, list) else self.raw["activities"][0]
        row = self.src.normalize_activity(raw_one)
        self.assertIsInstance(row["duration_s"], int)
        self.assertIsInstance(row["distance_m"], float)
        self.assertIsInstance(row["avg_hr"], int)
        self.assertIsInstance(row["type"], str)
        self.assertEqual(json.loads(row["raw_json"])["id"], raw_one["id"])


if __name__ == "__main__":
    unittest.main()
