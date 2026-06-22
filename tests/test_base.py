"""TDD — pure helpers in app.sources.base + additive schema in app.db.

Fully offline: a temp SQLite file, no network, stdlib unittest only.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest


def _fresh_db() -> sqlite3.Connection:
    """In-memory DB with the full app schema applied (additive tables included)."""
    from app.db import SCHEMA_SQL

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


class TestSchemaAdditive(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _fresh_db()

    def tearDown(self) -> None:
        self.conn.close()

    def test_new_tables_exist(self) -> None:
        names = {
            r["name"]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for t in (
            "activities",
            "daily_wellness",
            "sleep_nights",
            "nutrition_days",
            "sync_state",
        ):
            self.assertIn(t, names, f"missing additive table {t}")

    def test_existing_tables_untouched(self) -> None:
        names = {
            r["name"]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for t in ("exercises", "sessions", "set_entries", "personal_records"):
            self.assertIn(t, names, f"existing table {t} must remain")

    def test_activities_columns(self) -> None:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(activities)")}
        expected = {
            "id",
            "source",
            "type",
            "start_time",
            "duration_s",
            "distance_m",
            "avg_hr",
            "elevation_m",
            "calories",
            "raw_json",
            "created_at",
        }
        self.assertEqual(expected, cols)

    def test_activities_indexes_present(self) -> None:
        idx = {
            r["name"]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='activities'"
            )
        }
        # at least the two the brief asks for (names may vary, so check by columns)
        index_cols = []
        for name in idx:
            cols = [r["name"] for r in self.conn.execute(f"PRAGMA index_info('{name}')")]
            index_cols.append(tuple(cols))
        self.assertIn(("start_time",), index_cols)
        self.assertIn(("source", "type"), index_cols)


class TestUpsert(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _fresh_db()

    def tearDown(self) -> None:
        self.conn.close()

    def test_upsert_inserts_then_updates_in_place(self) -> None:
        from app.sources.base import upsert

        row = {
            "id": "strava:1",
            "source": "strava",
            "type": "Ride",
            "start_time": "2026-06-19T17:45:00Z",
            "duration_s": 3920,
            "distance_m": 24850.0,
            "avg_hr": 141,
            "elevation_m": 312.0,
            "calories": 720,
            "raw_json": "{}",
        }
        upsert(self.conn, "activities", "id", row)
        # second upsert with a changed value
        row2 = dict(row, calories=999, type="Run")
        upsert(self.conn, "activities", "id", row2)

        rows = self.conn.execute("SELECT * FROM activities").fetchall()
        self.assertEqual(1, len(rows), "no duplicate row on conflict")
        self.assertEqual(999, rows[0]["calories"], "value updated in place")
        self.assertEqual("Run", rows[0]["type"])

    def test_upsert_returns_pk(self) -> None:
        from app.sources.base import upsert

        pk = upsert(
            self.conn,
            "daily_wellness",
            "date",
            {"date": "2026-06-20", "steps": 11432, "raw_json": "{}"},
        )
        self.assertEqual("2026-06-20", pk)

    def test_upsert_ignores_unknown_columns_safely(self) -> None:
        # A normalizer might emit a key not in the table; upsert should only
        # write known columns rather than raising "no column named ...".
        from app.sources.base import upsert

        upsert(
            self.conn,
            "sleep_nights",
            "date",
            {
                "date": "2026-06-20",
                "duration_s": 27000,
                "deep_s": 5400,
                "bogus_extra": "ignore me",
                "raw_json": "{}",
            },
        )
        r = self.conn.execute("SELECT * FROM sleep_nights").fetchone()
        self.assertEqual(27000, r["duration_s"])


class TestStoreRaw(unittest.TestCase):
    def test_store_raw_serializes_payload_into_raw_json(self) -> None:
        from app.sources.base import store_raw

        payload = {"a": 1, "nested": {"b": [1, 2, 3]}}
        out = store_raw({"id": "garmin:1"}, payload)
        self.assertIn("raw_json", out)
        import json

        self.assertEqual(payload, json.loads(out["raw_json"]))
        # original keys preserved, original dict not mutated destructively
        self.assertEqual("garmin:1", out["id"])

    def test_store_raw_does_not_mutate_input(self) -> None:
        from app.sources.base import store_raw

        original = {"id": "garmin:1"}
        store_raw(original, {"x": 1})
        self.assertNotIn("raw_json", original)


class TestCoercion(unittest.TestCase):
    def test_coerce_int_rounds_floats(self) -> None:
        from app.sources.base import coerce_int

        self.assertEqual(145, coerce_int(145.0))
        self.assertEqual(146, coerce_int(145.6))
        self.assertEqual(5, coerce_int("5"))

    def test_coerce_int_none_safe(self) -> None:
        from app.sources.base import coerce_int

        self.assertIsNone(coerce_int(None))
        self.assertIsNone(coerce_int(""))
        self.assertIsNone(coerce_int("not a number"))

    def test_coerce_float_none_safe(self) -> None:
        from app.sources.base import coerce_float

        self.assertEqual(5029.27, coerce_float(5029.27))
        self.assertIsNone(coerce_float(None))
        self.assertIsNone(coerce_float("nope"))

    def test_dig_walks_nested_keys(self) -> None:
        from app.sources.base import dig

        d = {"a": {"b": {"c": 42}}}
        self.assertEqual(42, dig(d, "a", "b", "c"))
        self.assertIsNone(dig(d, "a", "x", "c"))
        self.assertEqual("fallback", dig(d, "a", "x", default="fallback"))

    def test_dig_handles_non_dict_midway(self) -> None:
        from app.sources.base import dig

        d = {"a": 5}
        self.assertIsNone(dig(d, "a", "b"))


class TestWatermark(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _fresh_db()

    def tearDown(self) -> None:
        self.conn.close()

    def test_watermark_roundtrip(self) -> None:
        from app.sources.base import read_watermark, write_watermark

        self.assertIsNone(read_watermark(self.conn, "garmin"))
        write_watermark(
            self.conn, "garmin", watermark="2026-06-21", status="ok"
        )
        self.assertEqual("2026-06-21", read_watermark(self.conn, "garmin"))

    def test_write_watermark_upserts_state(self) -> None:
        from app.sources.base import write_watermark

        write_watermark(self.conn, "strava", watermark="100", status="ok")
        write_watermark(self.conn, "strava", watermark="200", status="error")
        rows = self.conn.execute(
            "SELECT * FROM sync_state WHERE source='strava'"
        ).fetchall()
        self.assertEqual(1, len(rows))
        self.assertEqual("200", rows[0]["last_watermark"])
        self.assertEqual("error", rows[0]["last_status"])
        self.assertIsNotNone(rows[0]["last_run_at"])


if __name__ == "__main__":
    unittest.main()
