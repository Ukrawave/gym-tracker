"""TDD — Phase 2 "The Plan": pure glide-path engine + write-route semantics.

Fully offline: no network, no running server. The pure-engine tests need no DB
at all; the write-path tests point GYM_DB_PATH at a temp file and call the route
handlers directly (mirrors tests/test_sync_route.py — the venv has no httpx, so
FastAPI's TestClient is unavailable by design).

stdlib unittest only (no pytest in the venv).
"""
from __future__ import annotations

import importlib
import os
import tempfile
import unittest


# ===========================================================================
# PURE ENGINE — ideal_weight / weigh_in_week / classify_pace
# ===========================================================================
class TestIdealWeight(unittest.TestCase):
    def _cfg(self, start, target, horizon=24):
        return {
            "start_date": "2026-01-01",
            "start_weight": start,
            "target_weight": target,
            "horizon_weeks": horizon,
        }

    def test_loss_endpoints_and_midpoint(self) -> None:
        from app.routes.plan import ideal_weight

        cfg = self._cfg(90.0, 80.0, 24)  # cut
        self.assertAlmostEqual(ideal_weight(0, cfg), 90.0, places=6)
        self.assertAlmostEqual(ideal_weight(24, cfg), 80.0, places=6)
        self.assertAlmostEqual(ideal_weight(12, cfg), 85.0, places=6)

    def test_gain_endpoints_and_midpoint(self) -> None:
        from app.routes.plan import ideal_weight

        cfg = self._cfg(70.0, 80.0, 20)  # bulk
        self.assertAlmostEqual(ideal_weight(0, cfg), 70.0, places=6)
        self.assertAlmostEqual(ideal_weight(20, cfg), 80.0, places=6)
        self.assertAlmostEqual(ideal_weight(10, cfg), 75.0, places=6)

    def test_recomp_is_flat(self) -> None:
        from app.routes.plan import ideal_weight

        cfg = self._cfg(80.0, 80.0, 24)  # recomp
        self.assertAlmostEqual(ideal_weight(0, cfg), 80.0, places=6)
        self.assertAlmostEqual(ideal_weight(12, cfg), 80.0, places=6)
        self.assertAlmostEqual(ideal_weight(24, cfg), 80.0, places=6)

    def test_week_clamped_to_horizon_range(self) -> None:
        from app.routes.plan import ideal_weight

        cfg = self._cfg(90.0, 80.0, 24)
        # Below 0 clamps to start; beyond horizon clamps to target.
        self.assertAlmostEqual(ideal_weight(-5, cfg), 90.0, places=6)
        self.assertAlmostEqual(ideal_weight(99, cfg), 80.0, places=6)


class TestWeighInWeek(unittest.TestCase):
    def test_start_date_is_week_zero(self) -> None:
        from app.routes.plan import weigh_in_week

        self.assertAlmostEqual(weigh_in_week("2026-01-01", "2026-01-01"), 0.0, places=6)

    def test_seven_days_is_one_week(self) -> None:
        from app.routes.plan import weigh_in_week

        self.assertAlmostEqual(weigh_in_week("2026-01-08", "2026-01-01"), 1.0, places=6)
        self.assertAlmostEqual(weigh_in_week("2026-01-15", "2026-01-01"), 2.0, places=6)

    def test_fractional_week(self) -> None:
        from app.routes.plan import weigh_in_week

        self.assertAlmostEqual(
            weigh_in_week("2026-01-11", "2026-01-01"), 10.0 / 7.0, places=6
        )


class TestClassifyPace(unittest.TestCase):
    def test_cut_below_ideal_is_ahead(self) -> None:
        from app.routes.plan import classify_pace

        # dir<0 (cut): lower is better.
        self.assertEqual(classify_pace(84.0, 85.0, -1), "ahead")
        self.assertEqual(classify_pace(85.0, 85.0, -1), "ahead")  # at-or-below

    def test_cut_above_ideal_plus_tol_is_behind(self) -> None:
        from app.routes.plan import classify_pace

        self.assertEqual(classify_pace(86.0, 85.0, -1, tol=0.5), "behind")

    def test_cut_within_tol_band_is_on_pace(self) -> None:
        from app.routes.plan import classify_pace

        # Slightly above ideal but inside the tolerance band.
        self.assertEqual(classify_pace(85.3, 85.0, -1, tol=0.5), "on_pace")

    def test_bulk_mirrors_cut(self) -> None:
        from app.routes.plan import classify_pace

        # dir>0 (bulk): higher is better.
        self.assertEqual(classify_pace(76.0, 75.0, 1), "ahead")
        self.assertEqual(classify_pace(75.0, 75.0, 1), "ahead")
        self.assertEqual(classify_pace(74.0, 75.0, 1, tol=0.5), "behind")
        self.assertEqual(classify_pace(74.7, 75.0, 1, tol=0.5), "on_pace")

    def test_recomp_within_tol_is_on_pace(self) -> None:
        from app.routes.plan import classify_pace

        self.assertEqual(classify_pace(80.3, 80.0, 0, tol=0.5), "on_pace")
        self.assertEqual(classify_pace(79.7, 80.0, 0, tol=0.5), "on_pace")

    def test_recomp_drift_beyond_tol_is_behind(self) -> None:
        from app.routes.plan import classify_pace

        # Recomp has no "good" direction — any drift past tol is off-plan.
        self.assertEqual(classify_pace(82.0, 80.0, 0, tol=0.5), "behind")
        self.assertEqual(classify_pace(78.0, 80.0, 0, tol=0.5), "behind")

    def test_null_inputs_are_unknown(self) -> None:
        from app.routes.plan import classify_pace

        self.assertEqual(classify_pace(None, 85.0, -1), "unknown")
        self.assertEqual(classify_pace(85.0, None, -1), "unknown")


# ===========================================================================
# MILESTONES — every milestone_weeks, hit/miss vs nearest weigh-in
# ===========================================================================
def _cfg_loss():
    return {
        "start_date": "2026-01-01",
        "start_weight": 90.0,
        "target_weight": 80.0,
        "horizon_weeks": 24,
        "phases": [],
    }


class TestMilestones(unittest.TestCase):
    def test_grid_every_four_weeks_with_ideals(self) -> None:
        from app.routes.plan import build_milestones

        ms = build_milestones(_cfg_loss(), [], milestone_weeks=4)
        weeks = [m["week"] for m in ms]
        self.assertEqual(weeks, [0, 4, 8, 12, 16, 20, 24])
        wk12 = next(m for m in ms if m["week"] == 12)
        self.assertAlmostEqual(wk12["ideal_weight"], 85.0, places=6)

    def test_nearby_weigh_in_on_track_is_hit(self) -> None:
        from app.routes.plan import build_milestones

        # 2026-01-29 == week 4; ideal@wk4 ~ 88.33; actual 88.0 (<=) -> ahead -> hit.
        weights = [{"date": "2026-01-29", "weight_kg": 88.0, "source": "manual"}]
        ms = build_milestones(_cfg_loss(), weights, milestone_weeks=4)
        wk4 = next(m for m in ms if m["week"] == 4)
        self.assertEqual(wk4["status"], "hit")
        self.assertAlmostEqual(wk4["actual_weight"], 88.0, places=6)

    def test_nearby_weigh_in_off_track_is_miss(self) -> None:
        from app.routes.plan import build_milestones

        # actual 89.0 > ideal(88.33)+0.5 -> behind -> miss.
        weights = [{"date": "2026-01-29", "weight_kg": 89.0, "source": "manual"}]
        ms = build_milestones(_cfg_loss(), weights, milestone_weeks=4)
        wk4 = next(m for m in ms if m["week"] == 4)
        self.assertEqual(wk4["status"], "miss")

    def test_milestone_without_nearby_weigh_in_is_pending(self) -> None:
        from app.routes.plan import build_milestones

        weights = [{"date": "2026-01-29", "weight_kg": 88.0, "source": "manual"}]
        ms = build_milestones(_cfg_loss(), weights, milestone_weeks=4)
        wk8 = next(m for m in ms if m["week"] == 8)
        self.assertEqual(wk8["status"], "pending")
        self.assertIsNone(wk8["actual_weight"])


# ===========================================================================
# ACCOUNTABILITY — rate, required-rate, verdict on a known series
# ===========================================================================
class TestAccountability(unittest.TestCase):
    def _series(self):
        # Cut 90 -> 80 over 24wk. Weigh-ins at wk0/wk4/wk8.
        return [
            {"date": "2026-01-01", "weight_kg": 90.0, "source": "manual"},  # wk0
            {"date": "2026-01-29", "weight_kg": 88.0, "source": "manual"},  # wk4
            {"date": "2026-02-26", "weight_kg": 86.0, "source": "manual"},  # wk8
        ]

    def test_known_series_rates_and_verdict(self) -> None:
        from app.routes.plan import build_accountability

        acc = build_accountability(_cfg_loss(), self._series())
        self.assertAlmostEqual(acc["weeks_elapsed"], 8.0, places=6)
        self.assertAlmostEqual(acc["weeks_remaining"], 16.0, places=6)
        self.assertAlmostEqual(acc["kg_to_target"], -6.0, places=6)  # 80 - 86
        self.assertAlmostEqual(acc["current_rate"], -0.5, places=6)  # (86-90)/8
        self.assertAlmostEqual(acc["required_rate"], -0.375, places=6)  # (80-86)/16
        # actual 86 <= ideal@wk8 (86.667) -> ahead.
        self.assertEqual(acc["verdict"], "ahead")

    def test_empty_series_returns_none(self) -> None:
        from app.routes.plan import build_accountability

        self.assertIsNone(build_accountability(_cfg_loss(), []))

    def test_single_weigh_in_has_no_current_rate(self) -> None:
        from app.routes.plan import build_accountability

        weights = [{"date": "2026-01-01", "weight_kg": 90.0, "source": "manual"}]
        acc = build_accountability(_cfg_loss(), weights)
        self.assertIsNotNone(acc)
        self.assertIsNone(acc["current_rate"])  # need >=2 points


# ===========================================================================
# BUILD_PLAN — full payload + empty-state semantics
# ===========================================================================
class TestBuildPlan(unittest.TestCase):
    def test_no_config_is_unconfigured(self) -> None:
        from app.routes.plan import build_plan

        self.assertEqual(build_plan(None, []), {"configured": False})

    def test_configured_without_weigh_ins_still_renders_ideal_line(self) -> None:
        from app.routes.plan import build_plan

        out = build_plan(_cfg_loss(), [])
        self.assertTrue(out["configured"])
        self.assertEqual(out["direction"], -1)
        # Ideal line sampled 0..horizon inclusive.
        self.assertEqual(out["ideal_line"][0]["week"], 0)
        self.assertEqual(out["ideal_line"][-1]["week"], 24)
        self.assertAlmostEqual(out["ideal_line"][0]["weight"], 90.0, places=6)
        self.assertAlmostEqual(out["ideal_line"][-1]["weight"], 80.0, places=6)
        # No weigh-ins -> no accountability yet, but the key still exists.
        self.assertIsNone(out["accountability"])
        self.assertEqual(out["weigh_ins"], [])

    def test_configured_with_weigh_ins_has_full_payload(self) -> None:
        from app.routes.plan import build_plan

        weights = [
            {"date": "2026-01-01", "weight_kg": 90.0, "source": "manual"},
            {"date": "2026-01-29", "weight_kg": 88.0, "source": "manual"},
        ]
        out = build_plan(_cfg_loss(), weights)
        self.assertTrue(out["configured"])
        self.assertEqual(len(out["weigh_ins"]), 2)
        # weigh-ins carry their computed week.
        self.assertAlmostEqual(out["weigh_ins"][0]["week"], 0.0, places=6)
        self.assertAlmostEqual(out["weigh_ins"][1]["week"], 4.0, places=6)
        self.assertIsNotNone(out["accountability"])
        self.assertTrue(out["milestones"])

    def test_direction_inferred_from_weights(self) -> None:
        from app.routes.plan import build_plan

        gain = dict(_cfg_loss(), start_weight=70.0, target_weight=80.0)
        recomp = dict(_cfg_loss(), start_weight=80.0, target_weight=80.0)
        self.assertEqual(build_plan(gain, [])["direction"], 1)
        self.assertEqual(build_plan(recomp, [])["direction"], 0)


# ===========================================================================
# WRITE-PATH VALIDATION — Pydantic models reject bad input (FastAPI -> 422)
# ===========================================================================
class TestWriteValidation(unittest.TestCase):
    def test_weight_must_be_positive(self) -> None:
        from pydantic import ValidationError
        from app.routes.plan import WeightIn

        with self.assertRaises(ValidationError):
            WeightIn(date="2026-01-01", weight_kg=0)
        with self.assertRaises(ValidationError):
            WeightIn(date="2026-01-01", weight_kg=-5)

    def test_weight_must_be_under_500(self) -> None:
        from pydantic import ValidationError
        from app.routes.plan import WeightIn

        with self.assertRaises(ValidationError):
            WeightIn(date="2026-01-01", weight_kg=600)

    def test_weight_date_must_be_iso(self) -> None:
        from pydantic import ValidationError
        from app.routes.plan import WeightIn

        with self.assertRaises(ValidationError):
            WeightIn(date="01/01/2026", weight_kg=80.0)

    def test_config_horizon_must_be_in_range(self) -> None:
        from pydantic import ValidationError
        from app.routes.plan import PlanConfigIn

        with self.assertRaises(ValidationError):
            PlanConfigIn(
                start_date="2026-01-01", start_weight=90, target_weight=80,
                horizon_weeks=0,
            )
        with self.assertRaises(ValidationError):
            PlanConfigIn(
                start_date="2026-01-01", start_weight=90, target_weight=80,
                horizon_weeks=200,
            )

    def test_config_weights_must_be_positive_and_bounded(self) -> None:
        from pydantic import ValidationError
        from app.routes.plan import PlanConfigIn

        with self.assertRaises(ValidationError):
            PlanConfigIn(start_date="2026-01-01", start_weight=0, target_weight=80)
        with self.assertRaises(ValidationError):
            PlanConfigIn(start_date="2026-01-01", start_weight=90, target_weight=900)

    def test_config_defaults_horizon_to_24(self) -> None:
        from app.routes.plan import PlanConfigIn

        cfg = PlanConfigIn(start_date="2026-01-01", start_weight=90, target_weight=80)
        self.assertEqual(cfg.horizon_weeks, 24)


# ===========================================================================
# WRITE-PATH PERSISTENCE — handlers against a temp DB (no server, no network)
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
        import app.routes.plan as plan

        importlib.reload(plan)
        self.plan = plan

    def tearDown(self) -> None:
        os.environ.pop("GYM_DB_PATH", None)
        os.unlink(self.path)
        import app.db as db

        importlib.reload(db)  # restore default path for other tests

    def test_get_plan_unconfigured_on_fresh_db(self) -> None:
        out = self.plan.get_plan()
        self.assertEqual(out, {"configured": False})

    def test_post_config_persists_single_row_and_updates(self) -> None:
        self.plan.save_config(
            self.plan.PlanConfigIn(
                start_date="2026-01-01", start_weight=90, target_weight=80,
                horizon_weeks=24,
            )
        )
        # Second POST changes values — must UPDATE row id=1, not insert a 2nd.
        self.plan.save_config(
            self.plan.PlanConfigIn(
                start_date="2026-02-01", start_weight=88, target_weight=78,
                horizon_weeks=20,
            )
        )
        with self.db.db_conn() as conn:
            rows = conn.execute("SELECT * FROM plan_config").fetchall()
        self.assertEqual(len(rows), 1, "single-row config table (id=1)")
        self.assertEqual(rows[0]["id"], 1)
        self.assertAlmostEqual(rows[0]["start_weight"], 88.0, places=6)
        self.assertEqual(rows[0]["horizon_weeks"], 20)

    def test_post_weight_upserts_by_date(self) -> None:
        self.plan.log_weight(self.plan.WeightIn(date="2026-01-10", weight_kg=89.5))
        # Same date again -> update in place, no duplicate.
        self.plan.log_weight(self.plan.WeightIn(date="2026-01-10", weight_kg=89.0))
        with self.db.db_conn() as conn:
            rows = conn.execute("SELECT * FROM body_weight").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["weight_kg"], 89.0, places=6)
        self.assertEqual(rows[0]["source"], "manual")

    def test_delete_weight_removes_then_404(self) -> None:
        from fastapi import HTTPException

        self.plan.log_weight(self.plan.WeightIn(date="2026-01-10", weight_kg=89.0))
        resp = self.plan.delete_weight("2026-01-10")
        self.assertEqual(resp.status_code, 204)
        with self.db.db_conn() as conn:
            n = conn.execute("SELECT COUNT(*) AS c FROM body_weight").fetchone()["c"]
        self.assertEqual(n, 0)
        # Deleting an absent date -> 404.
        with self.assertRaises(HTTPException) as ctx:
            self.plan.delete_weight("2099-12-31")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_plan_full_after_config_and_weight(self) -> None:
        self.plan.save_config(
            self.plan.PlanConfigIn(
                start_date="2026-01-01", start_weight=90, target_weight=80,
                horizon_weeks=24,
            )
        )
        self.plan.log_weight(self.plan.WeightIn(date="2026-01-01", weight_kg=90.0))
        out = self.plan.get_plan()
        self.assertTrue(out["configured"])
        self.assertEqual(len(out["weigh_ins"]), 1)
        self.assertEqual(out["direction"], -1)
        self.assertTrue(out["ideal_line"])

    def test_config_round_trips_phases(self) -> None:
        self.plan.save_config(
            self.plan.PlanConfigIn(
                start_date="2026-01-01", start_weight=90, target_weight=80,
                horizon_weeks=24,
                phases=[
                    {"name": "Aggressive cut", "start_week": 0, "end_week": 12},
                    {"name": "Taper", "start_week": 12, "end_week": 24},
                ],
            )
        )
        out = self.plan.get_plan()
        self.assertEqual(len(out["phases"]), 2)
        self.assertEqual(out["phases"][0]["name"], "Aggressive cut")


if __name__ == "__main__":
    unittest.main()
