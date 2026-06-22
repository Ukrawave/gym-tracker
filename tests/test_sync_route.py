"""TDD — /api/sync/status route logic, exercised offline by calling the handler
function directly (no running server, no network). It reads the live DB via
db_conn(), so we point GYM_DB_PATH at a temp file seeded with known state.
"""
from __future__ import annotations

import importlib
import os
import tempfile
import unittest


class TestSyncStatusRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        os.environ["GYM_DB_PATH"] = self.path
        # Re-import db so DB_PATH picks up the temp path.
        import app.db as db

        importlib.reload(db)
        db.init_schema()
        self.db = db

    def tearDown(self) -> None:
        os.environ.pop("GYM_DB_PATH", None)
        os.unlink(self.path)
        import app.db as db

        importlib.reload(db)  # restore default path for other tests

    def test_status_reports_sources_and_counts(self) -> None:
        # Seed one source + one activity row.
        from app.sources.base import upsert, write_watermark

        with self.db.db_conn() as conn:
            write_watermark(conn, "garmin", watermark="2026-06-21", status="ok")
            upsert(
                conn,
                "activities",
                "id",
                {
                    "id": "garmin:1",
                    "source": "garmin",
                    "type": "running",
                    "start_time": "2026-06-21T06:00:00",
                    "raw_json": "{}",
                },
            )

        # Reload the route module so its db_conn closure uses the temp DB.
        import app.routes.sync as sync_route

        importlib.reload(sync_route)
        out = sync_route.sync_status()

        self.assertIn("garmin", out["sources"])
        self.assertIn("strava", out["sources"])
        self.assertEqual("ok", out["sources"]["garmin"]["last_status"])
        self.assertEqual("2026-06-21", out["sources"]["garmin"]["last_watermark"])
        # strava never ran -> nulls, not missing
        self.assertIsNone(out["sources"]["strava"]["last_status"])
        # counts present for every ingested table
        for table in ("activities", "daily_wellness", "sleep_nights", "nutrition_days"):
            self.assertIn(table, out["counts"])
        self.assertEqual(1, out["counts"]["activities"])


if __name__ == "__main__":
    unittest.main()
