"""TDD — upsert is idempotent: running a sync twice over the same data must not
duplicate rows, and must update changed values in place.

Uses a real temp SQLite FILE (not :memory:) per the brief, exercising the same
db_conn path the app uses. Fully offline.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name: str):
    with open(os.path.join(FIXDIR, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _first(raw, list_key="activities"):
    if isinstance(raw, list):
        return raw[0]
    return raw[list_key][0]


class TestUpsertIdempotent(unittest.TestCase):
    def setUp(self) -> None:
        from app.db import SCHEMA_SQL

        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)

    def tearDown(self) -> None:
        self.conn.close()
        os.unlink(self.path)

    def test_garmin_activity_upsert_twice_no_duplicate(self) -> None:
        from app.sources.base import upsert
        from app.sources.garmin import GarminSource

        src = GarminSource(None, None)
        raw = _first(load("garmin_activities.json"))
        row = src.normalize_activity(raw)

        upsert(self.conn, "activities", "id", row)
        upsert(self.conn, "activities", "id", row)
        self.conn.commit()

        n = self.conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
        self.assertEqual(1, n, "re-running the same activity must not duplicate")

    def test_strava_activity_upsert_updates_in_place(self) -> None:
        from app.sources.base import upsert
        from app.sources.strava import StravaSource

        src = StravaSource(None, None, None)
        raw = _first(load("strava_activities.json"))
        row = src.normalize_activity(raw)

        upsert(self.conn, "activities", "id", row)
        # simulate a re-sync where calories got corrected upstream
        row2 = dict(row, calories=4242)
        upsert(self.conn, "activities", "id", row2)
        self.conn.commit()

        rows = self.conn.execute(
            "SELECT * FROM activities WHERE id = ?", (row["id"],)
        ).fetchall()
        self.assertEqual(1, len(rows))
        self.assertEqual(4242, rows[0]["calories"], "value updated in place")

    def test_wellness_upsert_twice_no_duplicate(self) -> None:
        from app.sources.base import upsert
        from app.sources.garmin import GarminSource

        src = GarminSource(None, None)
        row = src.normalize_wellness(load("garmin_wellness.json"))

        upsert(self.conn, "daily_wellness", "date", row)
        upsert(self.conn, "daily_wellness", "date", row)
        self.conn.commit()

        n = self.conn.execute("SELECT COUNT(*) FROM daily_wellness").fetchone()[0]
        self.assertEqual(1, n)

    def test_sleep_upsert_twice_no_duplicate(self) -> None:
        from app.sources.base import upsert
        from app.sources.garmin import GarminSource

        src = GarminSource(None, None)
        row = src.normalize_sleep(load("garmin_sleep.json"))

        upsert(self.conn, "sleep_nights", "date", row)
        upsert(self.conn, "sleep_nights", "date", row)
        self.conn.commit()

        n = self.conn.execute("SELECT COUNT(*) FROM sleep_nights").fetchone()[0]
        self.assertEqual(1, n)


if __name__ == "__main__":
    unittest.main()
