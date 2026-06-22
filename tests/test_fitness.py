"""TDD — pure logic for the Phase 1 fitness dashboard endpoints.

Fully offline: no network, no running server, no DB. These tests pin the
pure helpers in app.routes.fitness (dedup, Riegel race prediction, derived
push/hold/rest readiness) plus NULL-safety of the row->payload builders.

stdlib unittest only (no pytest in the venv).
"""
from __future__ import annotations

import unittest


# ---------------------------------------------------------------------------
# Activity type normalization (case-insensitive; garmin lowercase vs strava Cap)
# ---------------------------------------------------------------------------
class TestNormalizeActivityType(unittest.TestCase):
    def test_run_variants_map_to_run(self) -> None:
        from app.routes.fitness import normalize_activity_type

        for raw in ("Run", "run", "running", "RUNNING", "  Running  "):
            self.assertEqual(normalize_activity_type(raw), "run", raw)

    def test_ride_and_walk_recognized(self) -> None:
        from app.routes.fitness import normalize_activity_type

        self.assertEqual(normalize_activity_type("Ride"), "ride")
        self.assertEqual(normalize_activity_type("cycling"), "ride")
        self.assertEqual(normalize_activity_type("Walk"), "walk")
        self.assertEqual(normalize_activity_type("walking"), "walk")

    def test_unknown_or_null_returns_none(self) -> None:
        from app.routes.fitness import normalize_activity_type

        self.assertIsNone(normalize_activity_type("Yoga"))
        self.assertIsNone(normalize_activity_type(None))
        self.assertIsNone(normalize_activity_type(""))


# ---------------------------------------------------------------------------
# Dedup: Garmin + Strava hold the SAME physical runs -> collapse to one,
# preferring the (richer) Garmin row.
# ---------------------------------------------------------------------------
def _run(id_, source, start, dist, **kw):
    base = {
        "id": id_,
        "source": source,
        "type": "running" if source == "garmin" else "Run",
        "start_time": start,
        "distance_m": dist,
        "duration_s": kw.get("duration_s", 1700),
        "avg_hr": kw.get("avg_hr", 145),
        "elevation_m": kw.get("elevation_m", 40.0),
        "calories": kw.get("calories"),
    }
    base.update(kw)
    return base


class TestDedupRuns(unittest.TestCase):
    def test_same_run_two_sources_collapses_to_one_prefers_garmin(self) -> None:
        from app.routes.fitness import dedup_runs

        rows = [
            _run("strava:18953879918", "strava", "2026-06-17T06:26:57Z", 5029.3),
            _run("garmin:23278799308", "garmin", "2026-06-17T06:27:00Z", 5031.0,
                 calories=320),
        ]
        out = dedup_runs(rows)
        self.assertEqual(len(out), 1, "the same physical run must collapse to one")
        self.assertEqual(out[0]["source"], "garmin", "Garmin row preferred")
        self.assertEqual(out[0]["id"], "garmin:23278799308")

    def test_distinct_days_are_kept_separate(self) -> None:
        from app.routes.fitness import dedup_runs

        rows = [
            _run("garmin:1", "garmin", "2026-06-17T06:27:00Z", 5000.0),
            _run("garmin:2", "garmin", "2026-06-18T06:27:00Z", 5000.0),
        ]
        self.assertEqual(len(dedup_runs(rows)), 2)

    def test_same_time_different_distance_not_merged(self) -> None:
        from app.routes.fitness import dedup_runs

        rows = [
            _run("garmin:1", "garmin", "2026-06-17T06:27:00Z", 5000.0),
            _run("strava:2", "strava", "2026-06-17T06:27:20Z", 10000.0),
        ]
        self.assertEqual(len(dedup_runs(rows)), 2)

    def test_order_independent_still_prefers_garmin(self) -> None:
        from app.routes.fitness import dedup_runs

        # Garmin listed first this time; result must be identical.
        rows = [
            _run("garmin:9", "garmin", "2026-06-17T06:27:00Z", 5031.0),
            _run("strava:8", "strava", "2026-06-17T06:26:57Z", 5029.3),
        ]
        out = dedup_runs(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "garmin")

    def test_real_world_mixed_timestamp_formats_collapse(self) -> None:
        """Regression: Garmin emits a NAIVE 'YYYY-MM-DD HH:MM:SS' (already GMT,
        no offset) while Strava emits 'YYYY-MM-DDTHH:MM:SSZ'. Same wall-clock run
        must collapse — a naive ts must be read as UTC, not local, or the two
        land an hour apart and never cluster (the bug caught against real data)."""
        from app.routes.fitness import dedup_runs

        rows = [
            _run("garmin:23278799308", "garmin", "2026-06-17 06:26:57", 5029.27),
            _run("strava:18953879918", "strava", "2026-06-17T06:26:57Z", 5029.3),
        ]
        out = dedup_runs(rows)
        self.assertEqual(len(out), 1, "naive-GMT + Z-UTC same run must collapse")
        self.assertEqual(out[0]["source"], "garmin")


# ---------------------------------------------------------------------------
# Riegel race prediction: T2 = T1 * (D2/D1) ** 1.06
# ---------------------------------------------------------------------------
class TestRiegel(unittest.TestCase):
    def test_predicting_same_distance_returns_same_time(self) -> None:
        from app.routes.fitness import riegel_predict_time

        # D2 == D1 -> ratio 1 -> identical time.
        self.assertAlmostEqual(riegel_predict_time(5000, 1500, 5000), 1500, delta=1)

    def test_10k_from_5k_known_value(self) -> None:
        from app.routes.fitness import riegel_predict_time

        # 5K in 25:00 (1500s) -> 10K ~ 1500 * 2 ** 1.06 ~ 3127s (~52:07).
        t = riegel_predict_time(5000, 1500, 10000)
        self.assertAlmostEqual(t, 3127, delta=25)

    def test_race_predictions_table_shape_and_values(self) -> None:
        from app.routes.fitness import race_predictions

        preds = race_predictions(5000.0, 1500)
        names = [p["distance"] for p in preds]
        self.assertEqual(names, ["5K", "10K", "Half Marathon", "Marathon"])
        # 5K predicted from a 5K effort echoes the input time back.
        p5 = next(p for p in preds if p["distance"] == "5K")
        self.assertAlmostEqual(p5["time_s"], 1500, delta=5)
        # every row carries a human-readable time string
        self.assertTrue(all(isinstance(p["time"], str) and p["time"] for p in preds))

    def test_race_predictions_empty_on_bad_input(self) -> None:
        from app.routes.fitness import race_predictions

        self.assertEqual(race_predictions(0, 0), [])
        self.assertEqual(race_predictions(None, None), [])


# ---------------------------------------------------------------------------
# Derived readiness: push / hold / rest from acute load + RHR trend.
# (training_readiness is always NULL for this account — must be derived.)
# ---------------------------------------------------------------------------
class TestReadiness(unittest.TestCase):
    def test_high_load_and_elevated_rhr_is_rest(self) -> None:
        from app.routes.fitness import derive_readiness

        r = derive_readiness(
            acute_load=300.0, rhr_latest=60, rhr_baseline=52, load_high=200.0
        )
        self.assertEqual(r["state"], "rest")
        self.assertIsInstance(r["reason"], str)
        self.assertTrue(r["reason"])

    def test_low_load_and_low_rhr_is_push(self) -> None:
        from app.routes.fitness import derive_readiness

        r = derive_readiness(
            acute_load=80.0, rhr_latest=50, rhr_baseline=52, load_high=200.0
        )
        self.assertEqual(r["state"], "push")

    def test_single_signal_is_hold(self) -> None:
        from app.routes.fitness import derive_readiness

        # High load but resting HR steady -> one strain signal -> hold.
        r = derive_readiness(
            acute_load=300.0, rhr_latest=52, rhr_baseline=52, load_high=200.0
        )
        self.assertEqual(r["state"], "hold")

    def test_null_inputs_degrade_to_a_safe_state(self) -> None:
        from app.routes.fitness import derive_readiness

        # All-None must not raise and must still return a valid state.
        r = derive_readiness(
            acute_load=None, rhr_latest=None, rhr_baseline=None, load_high=None
        )
        self.assertIn(r["state"], {"push", "hold", "rest"})


# ---------------------------------------------------------------------------
# NULL-safety: the row->payload builders must never crash on the always-NULL
# columns (hrv_overnight, training_readiness) or on un-worn / un-synced nights.
# ---------------------------------------------------------------------------
class TestBuilderNullSafety(unittest.TestCase):
    def test_overview_builder_handles_null_fields(self) -> None:
        from app.routes.fitness import build_overview

        wellness = [
            {
                "date": "2026-06-22", "vo2max_running": 54.0, "resting_hr": 56,
                "hrv_overnight": None, "body_battery_high": 90,
                "body_battery_low": 51, "stress_avg": 58,
                "training_readiness": None, "training_load_acute": 192.92,
                "training_load_chronic": 0.0, "steps": 1180,
            }
        ]
        activities = [
            _run("garmin:1", "garmin", "2026-06-17T06:27:00Z", 5031.0, calories=320),
        ]
        sleep = [
            {"date": "2026-06-17", "duration_s": 27240, "deep_s": 4620,
             "light_s": 15960, "rem_s": 6660, "awake_s": 0, "sleep_score": 94},
        ]
        out = build_overview(wellness, activities, sleep, sync={"sources": {}})
        # VO2max surfaces; HRV/readiness being None must not break the dict.
        self.assertEqual(out["vo2max"]["value"], 54.0)
        self.assertEqual(out["last_run"]["distance_m"], 5031.0)
        self.assertEqual(out["last_sleep"]["score"], 94)

    def test_overview_builder_with_empty_tables(self) -> None:
        from app.routes.fitness import build_overview

        out = build_overview([], [], [], sync={"sources": {}})
        # No data anywhere -> every section None, but the keys still exist.
        self.assertIsNone(out["vo2max"])
        self.assertIsNone(out["last_run"])
        self.assertIsNone(out["last_sleep"])
        self.assertIsNone(out["body_battery"])

    def test_training_builder_handles_null_readiness_and_hrv(self) -> None:
        from app.routes.fitness import build_training

        wellness = [
            {"date": "2026-06-20", "resting_hr": 55, "hrv_overnight": None,
             "training_readiness": None, "training_load_acute": 150.0,
             "training_load_chronic": 0.0},
            {"date": "2026-06-22", "resting_hr": 56, "hrv_overnight": None,
             "training_readiness": None, "training_load_acute": 192.92,
             "training_load_chronic": 0.0},
        ]
        out = build_training(wellness, [])
        self.assertIn(out["readiness"]["state"], {"push", "hold", "rest"})
        # load series skips nothing here; resting HR series present
        self.assertEqual(len(out["load_series"]), 2)
        self.assertEqual(len(out["resting_hr_series"]), 2)

    def test_sleep_builder_skips_null_duration_nights(self) -> None:
        from app.routes.fitness import build_sleep

        sleep = [
            {"date": "2026-06-16", "duration_s": None, "deep_s": None,
             "light_s": None, "rem_s": None, "awake_s": None, "sleep_score": None},
            {"date": "2026-06-17", "duration_s": 27240, "deep_s": 4620,
             "light_s": 15960, "rem_s": 6660, "awake_s": 0, "sleep_score": 94},
        ]
        wellness = [
            {"date": "2026-06-17", "stress_avg": 58, "body_battery_high": 90,
             "body_battery_low": 51},
        ]
        out = build_sleep(sleep, wellness)
        # The NULL night is dropped from nights + score_series.
        self.assertEqual(len(out["nights"]), 1)
        self.assertEqual(out["nights"][0]["date"], "2026-06-17")
        self.assertEqual(len(out["score_series"]), 1)


if __name__ == "__main__":
    unittest.main()
