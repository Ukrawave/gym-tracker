"""TDD — orchestration logic in app.sync, exercised offline with FAKE injected
sources (no network, no garminconnect/requests). Verifies:
- one failing source does not abort the other
- outcomes are recorded in sync_state
- date/epoch windows go incremental once a watermark exists
"""
from __future__ import annotations

import sqlite3
import unittest
from datetime import date


def _fresh_db() -> sqlite3.Connection:
    from app.db import SCHEMA_SQL

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


class FakeGarmin:
    """Stand-in with the GarminSource surface run_sync/ingest_garmin touch."""

    source = "garmin"

    def __init__(self, blow_up=False):
        self.blow_up = blow_up

    def fetch_activities(self, start, end):
        if self.blow_up:
            raise RuntimeError("garmin boom")
        return [
            {
                "activityId": 7,
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "2026-06-20 06:15:00",
                "duration": 1800.0,
                "distance": 5000.0,
                "averageHR": 150.0,
                "elevationGain": 40.0,
                "calories": 400.0,
            }
        ]

    def fetch_sleep(self, ds):
        return None  # skip per-day pillars in this orchestration test

    def fetch_wellness(self, ds):
        return None

    def normalize_activity(self, raw):
        from app.sources.garmin import GarminSource

        return GarminSource(None, None).normalize_activity(raw)


class FakeStrava:
    source = "strava"

    def __init__(self, blow_up=False):
        self.blow_up = blow_up

    def fetch_activities(self, after, per_page=100):
        if self.blow_up:
            raise RuntimeError("strava boom")
        return [
            {
                "id": 555,
                "type": "Ride",
                "start_date": "2026-06-21T10:00:00Z",
                "elapsed_time": 3600,
                "distance": 20000.0,
                "average_heartrate": 140.0,
                "total_elevation_gain": 200.0,
                "calories": 500,
            }
        ]

    def normalize_activity(self, raw):
        from app.sources.strava import StravaSource

        return StravaSource(None, None, None).normalize_activity(raw)


class TestRunSyncIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _fresh_db()

    def tearDown(self) -> None:
        self.conn.close()

    def test_one_failing_source_does_not_abort_the_other(self) -> None:
        from app.sync import run_sync

        results = run_sync(
            self.conn,
            garmin=FakeGarmin(blow_up=True),
            strava=FakeStrava(blow_up=False),
            backfill_days=30,
        )
        by = {r["source"]: r for r in results}
        self.assertTrue(by["garmin"]["status"].startswith("error"))
        self.assertEqual("ok", by["strava"]["status"])

        # Strava's row landed despite Garmin failing.
        n = self.conn.execute(
            "SELECT COUNT(*) FROM activities WHERE source='strava'"
        ).fetchone()[0]
        self.assertEqual(1, n)

    def test_outcomes_recorded_in_sync_state(self) -> None:
        from app.sync import run_sync

        run_sync(
            self.conn,
            garmin=FakeGarmin(blow_up=True),
            strava=FakeStrava(blow_up=False),
            backfill_days=30,
        )
        states = {
            r["source"]: r
            for r in self.conn.execute("SELECT * FROM sync_state").fetchall()
        }
        self.assertIn("garmin", states)
        self.assertIn("strava", states)
        self.assertTrue(states["garmin"]["last_status"].startswith("error"))
        self.assertEqual("ok", states["strava"]["last_status"])
        self.assertIsNotNone(states["strava"]["last_run_at"])

    def test_both_ok(self) -> None:
        from app.sync import run_sync

        results = run_sync(
            self.conn,
            garmin=FakeGarmin(),
            strava=FakeStrava(),
            backfill_days=30,
        )
        self.assertTrue(all(r["status"] == "ok" for r in results))
        n = self.conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
        self.assertEqual(2, n)


class TestWindows(unittest.TestCase):
    def test_date_window_backfills_without_watermark(self) -> None:
        from app.sync import _date_window

        start, end = _date_window(None, 10, today=date(2026, 6, 22))
        self.assertEqual("2026-06-12", start)
        self.assertEqual("2026-06-22", end)

    def test_date_window_incremental_with_watermark(self) -> None:
        from app.sync import _date_window

        start, end = _date_window("2026-06-20", 10, today=date(2026, 6, 22))
        self.assertEqual("2026-06-20", start)

    def test_epoch_window_incremental_with_watermark(self) -> None:
        from app.sync import _epoch_window

        self.assertEqual(1700000000, _epoch_window("1700000000", 10))


if __name__ == "__main__":
    unittest.main()
