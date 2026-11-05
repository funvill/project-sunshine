#!/usr/bin/env python3
"""Offline tests for the experiment runner's scheduling. No camera or Pi needed."""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "sunset_experiment", ROOT / "experiments" / "sunset-experiment.py"
)
exp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exp)

SLOT = 1793775600  # 2026-11-04T07:00:00Z, a real quarter-hour capture slot
SUNSET = 1793839520  # 2026-11-05T00:45:20Z


class ClearToStart(unittest.TestCase):
    """A real capture must never lose the camera to an experiment."""

    def test_clear_in_the_middle_of_the_gap(self):
        self.assertTrue(exp.clear_to_start(SLOT + 300, est_s=10))

    def test_refuses_a_shot_that_would_run_into_the_next_slot(self):
        self.assertFalse(exp.clear_to_start(SLOT + 900 - 12, est_s=10))

    def test_allows_a_shot_that_finishes_before_the_margin(self):
        self.assertTrue(exp.clear_to_start(SLOT + 900 - 30, est_s=10))

    def test_refuses_while_the_real_capture_may_still_be_running(self):
        self.assertFalse(exp.clear_to_start(SLOT + 20, est_s=5))

    def test_allows_after_the_real_capture_has_had_its_time(self):
        self.assertTrue(exp.clear_to_start(SLOT + exp.AFTER_SLOT_S + 1, est_s=5))

    def test_long_exposure_needs_a_bigger_gap(self):
        self.assertTrue(exp.clear_to_start(SLOT + 800, est_s=10))
        self.assertFalse(exp.clear_to_start(SLOT + 800, est_s=120))


class EstimatedTime(unittest.TestCase):
    def test_long_exposures_take_several_frames(self):
        self.assertGreaterEqual(exp.estimate_s(8_000_000), 24)

    def test_auto_exposure_has_a_floor(self):
        self.assertGreaterEqual(exp.estimate_s(None), 6)


class DayPlan(unittest.TestCase):
    def labels(self, t):
        return [s.label for s in exp.day_shots(t, SUNSET)]

    def test_skips_quarter_hours_because_the_real_capture_is_that_frame(self):
        self.assertEqual(self.labels(SLOT + 11 * 3600 + 900), [])

    def test_ordinary_minute_is_one_auto_jpeg(self):
        shots = exp.day_shots(SLOT + 11 * 3600 + 60, SUNSET)
        self.assertEqual([s.label for s in shots], ["rate"])
        self.assertFalse(shots[0].raw)

    def test_sunset_window_brackets_each_minute(self):
        minute = SUNSET - (SUNSET % 60) - 600 + 60
        if minute % 900 == 0:
            minute += 60
        self.assertEqual(self.labels(minute)[:3], ["ev-2", "ev+0", "ev+2"])

    def test_outside_the_sunset_window_has_no_brackets(self):
        self.assertNotIn("ev-2", self.labels(SUNSET - 46 * 60))

    def test_sunset_window_adds_metering_and_raw_every_five_minutes(self):
        minute = SUNSET - (SUNSET % 300) - 600
        if minute % 900 == 0:
            minute += 300
        shots = exp.day_shots(minute, SUNSET)
        labels = [s.label for s in shots]
        self.assertIn("meter-average", labels)
        self.assertIn("meter-spot", labels)
        self.assertTrue(any(s.raw for s in shots))

    def test_sun_ladder_runs_every_ten_minutes_in_the_afternoon(self):
        minute = SUNSET - 3 * 3600
        minute -= minute % 600
        if minute % 900 == 0:
            minute += 600
        self.assertIn("sun-100us", self.labels(minute))

    def test_every_minute_of_the_sunset_window_fits_in_the_gap_budget(self):
        for t in range(SUNSET - SUNSET % 60 - 45 * 60, SUNSET + 45 * 60, 60):
            total = sum(exp.estimate_s(s.shutter_us) for s in exp.day_shots(t, SUNSET))
            self.assertLess(total, 180, f"minute {t} plans {total} s of shooting")


class DuskLadder(unittest.TestCase):
    """Experiment 13: fixed exposures through the gap before the night frame takes over."""

    DUSK = ["dusk-250ms", "dusk-500ms", "dusk-1000ms", "dusk-2000ms"]

    def minute(self, after_sunset_s):
        t = SUNSET + after_sunset_s
        return t - t % 60 + 60  # the first whole minute at or after that moment

    def dusk_labels(self, t, sunset=SUNSET):
        return [s.label for s in exp.day_shots(t, sunset) if s.label.startswith("dusk-")]

    def test_takes_the_ladder_ten_minutes_after_sunset(self):
        self.assertEqual(self.dusk_labels(self.minute(600)), self.DUSK)

    def test_keeps_the_auto_frame_alongside_it(self):
        labels = [s.label for s in exp.day_shots(self.minute(600), SUNSET)]
        self.assertIn("ev+0", labels)

    def test_repeats_every_five_minutes_only(self):
        self.assertEqual(self.dusk_labels(self.minute(900)), self.DUSK)
        self.assertEqual(self.dusk_labels(self.minute(660)), [])

    def test_stops_after_fifty_minutes(self):
        self.assertEqual(self.dusk_labels(self.minute(3000)), self.DUSK)
        self.assertEqual(self.dusk_labels(self.minute(3300)), [])

    def test_not_before_ten_minutes(self):
        self.assertEqual(self.dusk_labels(self.minute(300)), [])

    def test_a_ladder_that_lands_on_a_real_capture_moves_to_the_next_minute(self):
        sunset = SLOT - 600  # so sunset + 10 min is exactly a capture slot
        self.assertEqual(self.dusk_labels(SLOT, sunset), [])
        self.assertEqual(self.dusk_labels(SLOT + 60, sunset), self.DUSK)

    def test_gain_one_auto_white_balance_no_raw(self):
        shots = [s for s in exp.day_shots(self.minute(600), SUNSET) if s.label.startswith("dusk-")]
        self.assertEqual([s.shutter_us for s in shots], [250_000, 500_000, 1_000_000, 2_000_000])
        self.assertTrue(all(s.gain == 1 and s.awbgains is None and not s.raw for s in shots))

    def test_fits_the_gap_budget_with_the_bracket(self):
        total = sum(exp.estimate_s(s.shutter_us) for s in exp.day_shots(self.minute(600), SUNSET))
        self.assertLess(total, 180)


class NightPlan(unittest.TestCase):
    def setUp(self):
        self.shots = exp.night_shots()
        self.labels = [s.label for s in self.shots]

    def test_ladder_covers_every_shutter_and_gain(self):
        ladder = [s for s in self.shots if s.label.startswith("ladder-")]
        self.assertEqual(len(ladder), 15)
        self.assertTrue(all(s.raw for s in ladder))

    def test_compares_the_current_colour_gains_with_measured_ones(self):
        self.assertIn("colour-1.6-1.8", self.labels)
        self.assertIn("colour-2.07-2.28", self.labels)
        self.assertIn("colour-auto", self.labels)

    def test_takes_a_stack_of_short_exposures(self):
        self.assertEqual(sum(label.startswith("stack-") for label in self.labels), 8)


class NightRatePlan(unittest.TestCase):
    def test_ordinary_minute_is_one_fixed_exposure(self):
        shots = exp.night_rate_shots(SLOT + 3600 + 60)
        self.assertEqual([s.label for s in shots], ["rate-night"])
        self.assertEqual((shots[0].shutter_us, shots[0].gain), (8_000_000, 1))

    def test_skips_the_real_capture_minute(self):
        self.assertEqual(exp.night_rate_shots(SLOT + 900), [])


class ShotCommand(unittest.TestCase):
    def test_includes_fixed_exposure_and_raw(self):
        shot = exp.Shot("x", shutter_us=2_000_000, gain=2, raw=True, awbgains="2.07,2.28")
        cmd = shot.command("/tmp/x")
        for part in ("--shutter", "2000000", "--gain", "2", "--raw", "--awbgains", "2.07,2.28"):
            self.assertIn(part, cmd)

    def test_auto_shot_sets_no_fixed_exposure(self):
        cmd = exp.Shot("x").command("/tmp/x")
        self.assertNotIn("--shutter", cmd)
        self.assertNotIn("--gain", cmd)
        self.assertNotIn("--raw", cmd)

    def test_never_writes_into_the_outbox(self):
        self.assertNotIn("outbox", str(exp.EXP_ROOT))
        self.assertNotIn("project_sunshine/", exp.NAS_EXP_ROOT)


if __name__ == "__main__":
    unittest.main()
