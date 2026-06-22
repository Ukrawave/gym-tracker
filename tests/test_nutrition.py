"""TDD - Phase 3 "Nutrition": pure intake/streak/net engine + write-route semantics.

Fully offline: no network, no running server. The pure-engine tests need no DB
at all; the write-path tests point GYM_DB_PATH at a temp file and call the route
handlers directly (mirrors tests/test_plan.py + tests/test_sync_route.py - the
venv has no httpx, so FastAPI's TestClient is unavailable by design).

Calories-OUT is read from the already-synced daily_wellness.raw_json
(stats_and_body.totalKilocalories) - never a live Garmin call.

stdlib unittest only (no pytest in the venv).
"""
from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from datetime import date, timedelta


# ===========================================================================
# PURE: calories_out_from_raw - dig stats_and_body.totalKilocalories, None-safe
# ===========================================================================
class TestCaloriesOutFromRaw(unittest.TestCase):
    def test_reads_total_kilocalories(self) -> None:
        from app.routes.nutrition import calories_out_from_raw

        raw = json.dumps({"stats_and_body": {"totalKilocalories": 1202.0,
                                              "bmrKilocalories": 1182.0}})
        self.assertAlmostEqual(calories_out_from_raw(raw), 1202.0, places=6)

    def test_missing_key_is_none(self) -> None:
        from app.routes.nutrition import calories_out_from_raw

        self.assertIsNone(calories_out_from_raw(json.dumps({"stats_and_body": {}})))
        self.assertIsNone(calories_out_from_raw(json.dumps({})))

    def test_bad_json_or_empty_is_none(self) -> None:
        from app.routes.nutrition import calories_out_from_raw

        self.assertIsNone(calories_out_from_raw("not json"))
        self.assertIsNone(calories_out_from_raw(""))
        self.assertIsNone(calories_out_from_raw(None))

    def test_null_total_is_none(self) -> None:
        from app.routes.nutrition import calories_out_from_raw

        raw = json.dumps({"stats_and_body": {"totalKilocalories": None}})
        self.assertIsNone(calories_out_from_raw(raw))


# ===========================================================================
# PURE: streak - consecutive logged days ending today OR yesterday (grace)
# ===========================================================================
class TestStreak(unittest.TestCase):
    def test_consecutive_days_including_today(self) -> None:
        from app.routes.nutrition import streak

        today = "2026-06-22"
        logged = ["2026-06-22", "2026-06-21", "2026-06-20"]
        self.assertEqual(streak(logged, today), 3)

    def test_gap_breaks_the_streak(self) -> None:
        from app.routes.nutrition import streak

        # 06-21 is missing -> only today counts.
        today = "2026-06-22"
        logged = ["2026-06-22", "2026-06-20", "2026-06-19"]
        self.assertEqual(streak(logged, today), 1)

    def test_today_not_logged_but_yesterday_is_grace(self) -> None:
        from app.routes.nutrition import streak

        # Today not yet logged; grace keeps the streak alive off yesterday.
        today = "2026-06-22"
        logged = ["2026-06-21", "2026-06-20", "2026-06-19"]
        self.assertEqual(streak(logged, today), 3)

    def test_neither_today_nor_yesterday_is_zero(self) -> None:
        from app.routes.nutrition import streak

        today = "2026-06-22"
        logged = ["2026-06-20", "2026-06-19"]  # last log was 2 days ago
        self.assertEqual(streak(logged, today), 0)

    def test_empty_is_zero(self) -> None:
        from app.routes.nutrition import streak

        self.assertEqual(streak([], "2026-06-22"), 0)

    def test_single_today_is_one(self) -> None:
        from app.routes.nutrition import streak

        self.assertEqual(streak(["2026-06-22"], "2026-06-22"), 1)

    def test_duplicates_and_unordered_input(self) -> None:
        from app.routes.nutrition import streak

        today = "2026-06-22"
        logged = ["2026-06-20", "2026-06-22", "2026-06-21", "2026-06-22"]
        self.assertEqual(streak(logged, today), 3)


# ===========================================================================
# PURE: net_calories - intake minus out, None-safe either side
# ===========================================================================
class TestNetCalories(unittest.TestCase):
    def test_intake_minus_out(self) -> None:
        from app.routes.nutrition import net_calories

        self.assertAlmostEqual(net_calories(1800, 1202.0), 598.0, places=6)

    def test_zero_intake_is_negative_out(self) -> None:
        from app.routes.nutrition import net_calories

        # Matches the documented empty-today payload: 0 - 1202 = -1202.
        self.assertAlmostEqual(net_calories(0, 1202.0), -1202.0, places=6)

    def test_missing_intake_is_none(self) -> None:
        from app.routes.nutrition import net_calories

        self.assertIsNone(net_calories(None, 1202.0))

    def test_missing_out_is_none(self) -> None:
        from app.routes.nutrition import net_calories

        self.assertIsNone(net_calories(1800, None))


# ===========================================================================
# PURE: adherence - percent of target, None-safe, clamped sensible
# ===========================================================================
class TestAdherence(unittest.TestCase):
    def test_exact_target_is_100(self) -> None:
        from app.routes.nutrition import adherence

        self.assertEqual(adherence(2400, 2400), 100)

    def test_half_target_is_50(self) -> None:
        from app.routes.nutrition import adherence

        self.assertEqual(adherence(1200, 2400), 50)

    def test_zero_intake_is_0(self) -> None:
        from app.routes.nutrition import adherence

        self.assertEqual(adherence(0, 2400), 0)

    def test_over_target_exceeds_100(self) -> None:
        from app.routes.nutrition import adherence

        self.assertEqual(adherence(3000, 2400), 125)

    def test_none_inputs_are_none(self) -> None:
        from app.routes.nutrition import adherence

        self.assertIsNone(adherence(None, 2400))
        self.assertIsNone(adherence(1200, None))

    def test_zero_or_negative_target_is_none(self) -> None:
        from app.routes.nutrition import adherence

        self.assertIsNone(adherence(1200, 0))
        self.assertIsNone(adherence(1200, -10))

    def test_negative_intake_clamps_to_zero(self) -> None:
        from app.routes.nutrition import adherence

        self.assertEqual(adherence(-500, 2400), 0)


# ===========================================================================
# PURE: build_nutrition - full payload + empty-state semantics
# ===========================================================================
def _targets():
    return {
        "target_calories": 2400,
        "target_protein_g": 160.0,
        "target_carbs_g": 250.0,
        "target_fat_g": 70.0,
    }


def _day(d, cal, p=0.0, c=0.0, f=0.0, source="manual"):
    return {"date": d, "calories": cal, "protein_g": p, "carbs_g": c,
            "fat_g": f, "source": source}


class TestBuildNutrition(unittest.TestCase):
    def test_no_targets_is_unconfigured(self) -> None:
        from app.routes.nutrition import build_nutrition

        out = build_nutrition(None, [], {}, "2026-06-22")
        self.assertEqual(out, {"configured": False})

    def test_configured_today_logged_full_payload(self) -> None:
        from app.routes.nutrition import build_nutrition

        days = [
            _day("2026-06-20", 2000, 150, 200, 60),
            _day("2026-06-21", 2200, 158, 220, 66),
            _day("2026-06-22", 1800, 150, 200, 60),  # today
        ]
        out_by_date = {"2026-06-22": 1202.0, "2026-06-21": 2222.0}
        out = build_nutrition(_targets(), days, out_by_date, "2026-06-22")

        self.assertTrue(out["configured"])
        self.assertEqual(out["targets"]["target_calories"], 2400)
        self.assertEqual(out["today"]["date"], "2026-06-22")
        self.assertEqual(out["today"]["calories"], 1800)
        self.assertEqual(out["today"]["source"], "manual")
        self.assertAlmostEqual(out["calories_out_today"], 1202.0, places=6)
        self.assertAlmostEqual(out["net_today"], 598.0, places=6)  # 1800-1202
        self.assertEqual(out["streak"], 3)
        self.assertEqual(out["adherence_pct"], 75)  # 1800/2400

    def test_recent_carries_per_day_out_and_net(self) -> None:
        from app.routes.nutrition import build_nutrition

        days = [
            _day("2026-06-20", 2000),
            _day("2026-06-21", 2200),
            _day("2026-06-22", 1800),
        ]
        out_by_date = {"2026-06-22": 1202.0, "2026-06-21": 2222.0}  # 06-20 has no out
        out = build_nutrition(_targets(), days, out_by_date, "2026-06-22")

        recent = out["recent"]
        self.assertEqual(len(recent), 3)
        # Ascending by date so the history chart plots left-to-right.
        self.assertEqual([r["date"] for r in recent],
                         ["2026-06-20", "2026-06-21", "2026-06-22"])
        by = {r["date"]: r for r in recent}
        # Each recent row echoes the target and computes net vs out.
        self.assertEqual(by["2026-06-22"]["target_calories"], 2400)
        self.assertAlmostEqual(by["2026-06-22"]["calories_out"], 1202.0, places=6)
        self.assertAlmostEqual(by["2026-06-22"]["net"], 598.0, places=6)
        self.assertAlmostEqual(by["2026-06-21"]["net"], -22.0, places=6)  # 2200-2222
        # No out for 06-20 -> net is None, not a guess.
        self.assertIsNone(by["2026-06-20"]["calories_out"])
        self.assertIsNone(by["2026-06-20"]["net"])

    def test_configured_today_not_logged_zero_fills(self) -> None:
        from app.routes.nutrition import build_nutrition

        # Targets set; nothing logged today; last log was two days ago.
        days = [_day("2026-06-20", 2000)]
        out_by_date = {"2026-06-22": 1202.0}
        out = build_nutrition(_targets(), days, out_by_date, "2026-06-22")

        self.assertTrue(out["configured"])
        self.assertEqual(out["today"]["calories"], 0)
        self.assertEqual(out["today"]["protein_g"], 0)
        self.assertEqual(out["today"]["source"], "manual")
        self.assertAlmostEqual(out["calories_out_today"], 1202.0, places=6)
        self.assertAlmostEqual(out["net_today"], -1202.0, places=6)  # 0-1202
        self.assertEqual(out["streak"], 0)  # neither today nor yesterday logged
        self.assertEqual(out["adherence_pct"], 0)

    def test_configured_no_wellness_row_net_is_none(self) -> None:
        from app.routes.nutrition import build_nutrition

        days = [_day("2026-06-22", 1800)]
        out = build_nutrition(_targets(), days, {}, "2026-06-22")  # no out anywhere
        self.assertIsNone(out["calories_out_today"])
        self.assertIsNone(out["net_today"])  # None-safe, not a guess

    def test_recent_window_is_bounded(self) -> None:
        from app.routes.nutrition import build_nutrition

        # 40 consecutive days; default window keeps the most recent 30.
        base = date(2026, 5, 14)
        days = [_day((base + timedelta(days=i)).isoformat(), 2000) for i in range(40)]
        today = (base + timedelta(days=39)).isoformat()
        out = build_nutrition(_targets(), days, {}, today)
        self.assertEqual(len(out["recent"]), 30)
        self.assertEqual(out["recent"][-1]["date"], today)  # today is the last point
        self.assertEqual(out["streak"], 40)  # streak spans full history, not window


# ===========================================================================
# WRITE-PATH VALIDATION - Pydantic models reject bad input (FastAPI -> 422)
# ===========================================================================
class TestWriteValidation(unittest.TestCase):
    def test_targets_reject_negative(self) -> None:
        from pydantic import ValidationError
        from app.routes.nutrition import NutritionTargetsIn

        with self.assertRaises(ValidationError):
            NutritionTargetsIn(target_calories=-1, target_protein_g=160,
                               target_carbs_g=250, target_fat_g=70)
        with self.assertRaises(ValidationError):
            NutritionTargetsIn(target_calories=2400, target_protein_g=-5,
                               target_carbs_g=250, target_fat_g=70)

    def test_log_rejects_negative_calories(self) -> None:
        from pydantic import ValidationError
        from app.routes.nutrition import NutritionLogIn

        with self.assertRaises(ValidationError):
            NutritionLogIn(date="2026-06-22", calories=-10, protein_g=0,
                           carbs_g=0, fat_g=0)

    def test_log_rejects_negative_macros(self) -> None:
        from pydantic import ValidationError
        from app.routes.nutrition import NutritionLogIn

        with self.assertRaises(ValidationError):
            NutritionLogIn(date="2026-06-22", calories=1800, protein_g=-1,
                           carbs_g=0, fat_g=0)

    def test_log_rejects_bad_date(self) -> None:
        from pydantic import ValidationError
        from app.routes.nutrition import NutritionLogIn

        with self.assertRaises(ValidationError):
            NutritionLogIn(date="22/06/2026", calories=1800, protein_g=0,
                           carbs_g=0, fat_g=0)

    def test_log_macros_default_to_zero(self) -> None:
        from app.routes.nutrition import NutritionLogIn

        m = NutritionLogIn(date="2026-06-22", calories=1800)
        self.assertEqual(m.protein_g, 0)
        self.assertEqual(m.carbs_g, 0)
        self.assertEqual(m.fat_g, 0)


# ===========================================================================
# WRITE-PATH PERSISTENCE - handlers against a temp DB (no server, no network)
# ===========================================================================
class TestWritePaths(unittest.TestCase):
    def setUp(self) -> None:
        self.fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        os.environ["GYM_DB_PATH"] = self.path
        import app.db as db

        importlib.reload(db)
        db.init_schema()
        self.db = db
        import app.routes.nutrition as nut

        importlib.reload(nut)
        self.nut = nut

    def tearDown(self) -> None:
        os.environ.pop("GYM_DB_PATH", None)
        os.unlink(self.path)
        import app.db as db

        importlib.reload(db)  # restore default path for other tests

    def test_get_nutrition_unconfigured_on_fresh_db(self) -> None:
        out = self.nut.get_nutrition()
        self.assertEqual(out, {"configured": False})

    def test_post_targets_persists_single_row_and_updates(self) -> None:
        self.nut.save_targets(self.nut.NutritionTargetsIn(
            target_calories=2400, target_protein_g=160, target_carbs_g=250,
            target_fat_g=70))
        # Second POST changes values - must UPDATE row id=1, not insert a 2nd.
        self.nut.save_targets(self.nut.NutritionTargetsIn(
            target_calories=2200, target_protein_g=170, target_carbs_g=210,
            target_fat_g=65))
        with self.db.db_conn() as conn:
            rows = conn.execute("SELECT * FROM nutrition_targets").fetchall()
        self.assertEqual(len(rows), 1, "single-row targets table (id=1)")
        self.assertEqual(rows[0]["id"], 1)
        self.assertEqual(rows[0]["target_calories"], 2200)
        self.assertAlmostEqual(rows[0]["target_protein_g"], 170.0, places=6)

    def test_post_log_upserts_by_date(self) -> None:
        self.nut.log_nutrition(self.nut.NutritionLogIn(
            date="2026-06-22", calories=1800, protein_g=150, carbs_g=200, fat_g=60))
        # Same date again -> update in place, no duplicate.
        self.nut.log_nutrition(self.nut.NutritionLogIn(
            date="2026-06-22", calories=1900, protein_g=155, carbs_g=205, fat_g=62))
        with self.db.db_conn() as conn:
            rows = conn.execute("SELECT * FROM nutrition_days").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["calories"], 1900)
        self.assertEqual(rows[0]["source"], "manual")
        self.assertIsNotNone(rows[0]["logged_at"])  # stamped on write

    def test_delete_log_removes_then_404(self) -> None:
        from fastapi import HTTPException

        self.nut.log_nutrition(self.nut.NutritionLogIn(
            date="2026-06-22", calories=1800))
        resp = self.nut.delete_nutrition("2026-06-22")
        self.assertEqual(resp.status_code, 204)
        with self.db.db_conn() as conn:
            n = conn.execute("SELECT COUNT(*) AS c FROM nutrition_days").fetchone()["c"]
        self.assertEqual(n, 0)
        # Deleting an absent date -> 404.
        with self.assertRaises(HTTPException) as ctx:
            self.nut.delete_nutrition("2099-12-31")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_full_reads_calories_out_from_wellness(self) -> None:
        # Calories-OUT comes from the already-synced daily_wellness.raw_json,
        # never a live call. Seed a wellness row for today and assert it surfaces.
        today = date.today().isoformat()
        with self.db.db_conn() as conn:
            conn.execute(
                "INSERT INTO daily_wellness (date, raw_json) VALUES (?, ?)",
                (today, json.dumps({"stats_and_body": {"totalKilocalories": 1500.0}})),
            )
        self.nut.save_targets(self.nut.NutritionTargetsIn(
            target_calories=2400, target_protein_g=160, target_carbs_g=250,
            target_fat_g=70))
        self.nut.log_nutrition(self.nut.NutritionLogIn(
            date=today, calories=1800, protein_g=150, carbs_g=200, fat_g=60))

        out = self.nut.get_nutrition()
        self.assertTrue(out["configured"])
        self.assertEqual(out["today"]["calories"], 1800)
        self.assertAlmostEqual(out["calories_out_today"], 1500.0, places=6)
        self.assertAlmostEqual(out["net_today"], 300.0, places=6)  # 1800-1500
        self.assertEqual(out["streak"], 1)
        self.assertEqual(out["adherence_pct"], 75)


# ===========================================================================
# GUARDED SCHEMA - the ADD COLUMN guard survives init_schema() running twice
# ===========================================================================
class TestGuardedSchema(unittest.TestCase):
    def setUp(self) -> None:
        self.fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        os.environ["GYM_DB_PATH"] = self.path
        import app.db as db

        importlib.reload(db)
        self.db = db

    def tearDown(self) -> None:
        os.environ.pop("GYM_DB_PATH", None)
        os.unlink(self.path)
        import app.db as db

        importlib.reload(db)  # restore default path for other tests

    def test_add_column_runs_twice_without_error(self) -> None:
        # SQLite ALTER ADD COLUMN is NOT idempotent; the PRAGMA guard must make
        # init_schema() safe to re-run on every boot.
        self.db.init_schema()
        self.db.init_schema()  # would raise "duplicate column" if unguarded

        with self.db.db_conn() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(nutrition_days)")}
        self.assertIn("source", cols)
        self.assertIn("logged_at", cols)

    def test_nutrition_targets_table_created(self) -> None:
        self.db.init_schema()
        with self.db.db_conn() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='nutrition_targets'"
            ).fetchone()
        self.assertIsNotNone(row)

    def test_source_column_defaults_to_manual(self) -> None:
        self.db.init_schema()
        with self.db.db_conn() as conn:
            conn.execute(
                "INSERT INTO nutrition_days (date, calories) VALUES ('2026-06-22', 1800)")
            row = conn.execute(
                "SELECT source FROM nutrition_days WHERE date='2026-06-22'").fetchone()
        self.assertEqual(row["source"], "manual")


if __name__ == "__main__":
    unittest.main()
