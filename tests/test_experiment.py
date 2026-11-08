#!/usr/bin/env python3
"""Offline tests for the experiment runner's scheduling. No camera or Pi needed."""
import importlib.util
import os
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "sunset_experiment", ROOT / "experiments" / "sunset-experiment.py"
)
exp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exp)


def timer_spacing_s():
    """Minutes between regular captures, read from the production capture timer."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pi", "systemd", "sunset-capture.timer")
    with open(path) as f:
        spec = [l.split("=", 1)[1].strip() for l in f if l.startswith("OnCalendar=")][0]
    return int(spec.split("/")[1]) * 60


SLOT = 1793775600  # 2026-11-04T07:00:00Z, a real capture slot
SUNSET = 1793839520  # 2026-11-05T00:45:20Z


class ClearToStart(unittest.TestCase):
    """A real capture must never lose the camera to an experiment."""

    def test_clear_in_the_middle_of_the_gap(self):
        self.assertTrue(exp.clear_to_start(SLOT + exp.SLOT_S // 2, est_s=10))

    def test_slot_spacing_matches_the_capture_timer(self):
        # A mismatch would let experiments take the camera in a real capture's minute.
        self.assertEqual(exp.SLOT_S, timer_spacing_s())

    def test_refuses_a_shot_that_would_run_into_the_next_slot(self):
        self.assertFalse(exp.clear_to_start(SLOT + exp.SLOT_S - 12, est_s=10))

    def test_allows_a_shot_that_finishes_before_the_margin(self):
        self.assertTrue(exp.clear_to_start(SLOT + exp.SLOT_S - 30, est_s=10))

    def test_refuses_while_the_real_capture_may_still_be_running(self):
        self.assertFalse(exp.clear_to_start(SLOT + 20, est_s=5))

    def test_allows_after_the_real_capture_has_had_its_time(self):
        self.assertTrue(exp.clear_to_start(SLOT + exp.AFTER_SLOT_S + 1, est_s=5))

    def test_long_exposure_needs_a_bigger_gap(self):
        self.assertTrue(exp.clear_to_start(SLOT + exp.SLOT_S - 100, est_s=10))
        self.assertFalse(exp.clear_to_start(SLOT + exp.SLOT_S - 100, est_s=120))


class EstimatedTime(unittest.TestCase):
    def test_long_exposures_take_several_frames(self):
        self.assertGreaterEqual(exp.estimate_s(8_000_000), 24)

    def test_auto_exposure_has_a_floor(self):
        self.assertGreaterEqual(exp.estimate_s(None), 6)


class DayPlan(unittest.TestCase):
    def labels(self, t):
        return [s.label for s in exp.day_shots(t, SUNSET)]

    def test_skips_slot_minutes_because_the_real_capture_is_that_frame(self):
        self.assertEqual(self.labels(SLOT + 11 * 3600 + exp.SLOT_S), [])

    def test_ordinary_minute_is_one_auto_jpeg(self):
        shots = exp.day_shots(SLOT + 11 * 3600 + 60, SUNSET)
        self.assertEqual([s.label for s in shots], ["rate"])
        self.assertFalse(shots[0].raw)

    def test_sunset_window_brackets_each_minute(self):
        minute = SUNSET - (SUNSET % 60) - 600 + 60
        if minute % exp.SLOT_S == 0:
            minute += 60
        self.assertEqual(self.labels(minute)[:3], ["ev-2", "ev+0", "ev+2"])

    def test_outside_the_sunset_window_has_no_brackets(self):
        self.assertNotIn("ev-2", self.labels(SUNSET - 46 * 60))

    def test_sunset_window_adds_metering_and_raw_every_five_minutes(self):
        minute = SUNSET - (SUNSET % 300) - 600 + 60   # the minute after a regular capture
        shots = exp.day_shots(minute, SUNSET)
        labels = [s.label for s in shots]
        self.assertIn("meter-average", labels)
        self.assertIn("meter-spot", labels)
        self.assertTrue(any(s.raw for s in shots))

    def test_sun_ladder_runs_every_ten_minutes_in_the_afternoon(self):
        minute = SUNSET - 3 * 3600
        minute = minute - minute % 600 + 60   # the minute after a regular capture
        self.assertIn("sun-100us", self.labels(minute))

    def test_sun_ladder_continues_into_the_sunset_window_until_sunset(self):
        # The sun is only in frame in the last ~30 minutes before sunset at the pilot-3 framing.
        minute = SUNSET - (SUNSET % 300) - 600 + 60   # the minute after a regular capture
        labels = self.labels(minute)
        self.assertIn("sun-100us", labels)
        self.assertIn("sun-500us", labels)

    def test_sun_ladder_in_the_sunset_window_is_only_every_five_minutes(self):
        minute = SUNSET - (SUNSET % 300) - 600 + 120   # two minutes after a regular capture
        self.assertNotIn("sun-100us", self.labels(minute))

    def test_no_sun_ladder_after_sunset(self):
        minute = SUNSET - (SUNSET % 300) + 600 + 60
        self.assertNotIn("sun-100us", self.labels(minute))

    def test_every_minute_of_the_sunset_window_fits_in_the_gap_budget(self):
        for t in range(SUNSET - SUNSET % 60 - 45 * 60, SUNSET + 45 * 60, 60):
            total = sum(exp.estimate_s(s.shutter_us) for s in exp.day_shots(t, SUNSET))
            self.assertLess(total, 180, f"minute {t} plans {total} s of shooting")


class DuskLadder(unittest.TestCase):
    """Experiment 13: fixed exposures through the gap before the night frame takes over."""

    DUSK = ["dusk-250ms", "dusk-500ms", "dusk-1000ms", "dusk-2000ms", "dusk-4000ms"]

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
        self.assertEqual([s.shutter_us for s in shots], [250_000, 500_000, 1_000_000, 2_000_000, 4_000_000])
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
        self.assertEqual((shots[0].shutter_us, shots[0].gain), (4_000_000, 1))

    def test_skips_the_real_capture_minute(self):
        self.assertEqual(exp.night_rate_shots(SLOT + exp.SLOT_S), [])


class NightSweep(unittest.TestCase):
    """Experiment 14: every exposure and setting worth trying at night."""

    def setUp(self):
        self.shots = exp.night_sweep_shots()
        self.labels = [s.label for s in self.shots]

    def test_covers_every_shutter_and_gain(self):
        ladder = [s for s in self.shots if s.label.startswith("ladder-")]
        self.assertEqual(len(ladder), 12 * 7)
        for label in ("ladder-100ms-g1", "ladder-30000ms-g8", "ladder-6000ms-g1.5", "ladder-20000ms-g3"):
            self.assertIn(label, self.labels)

    def test_labels_are_unique_so_results_can_be_told_apart(self):
        self.assertEqual(len(self.labels), len(set(self.labels)))

    def test_colour_gains_are_a_grid_not_a_guess(self):
        grid = [s for s in self.shots if s.label.startswith("gains-")]
        self.assertGreaterEqual(len(grid), 30)
        for label in ("gains-1.6-1.6", "gains-2.6-2.8", "gains-2.2-2.2", "gains-2.25-2.40"):
            self.assertIn(label, self.labels)

    def test_every_white_balance_mode(self):
        for mode in ("auto", "incandescent", "tungsten", "fluorescent", "indoor", "daylight", "cloudy"):
            self.assertIn("awb-" + mode, self.labels)

    def test_denoise_modes_at_several_exposures(self):
        for mode in ("auto", "off", "cdn_off", "cdn_fast", "cdn_hq"):
            for seconds in (2, 4, 8):
                self.assertIn(f"denoise-{mode}-{seconds}s", self.labels)

    def test_processing_swept_across_a_range(self):
        for option, values in (("contrast", ("0.6", "0.8", "1.0", "1.2", "1.4")),
                               ("saturation", ("0.6", "0.8", "1.0", "1.2", "1.4")),
                               ("sharpness", ("0", "0.5", "1.0", "1.5", "2.0"))):
            for value in values:
                self.assertIn(f"{option}-{value}", self.labels)

    def test_a_tuned_shot_passes_its_setting_to_the_camera(self):
        shot = next(s for s in self.shots if s.label == "awb-tungsten")
        cmd = shot.command("/tmp/x")
        self.assertEqual(cmd[cmd.index("--awb") + 1], "tungsten")
        self.assertIn("--shutter", cmd)

    def test_fits_inside_one_sweep_interval(self):
        total = sum(exp.estimate_s(s.shutter_us) for s in self.shots)
        self.assertLess(total, exp.NIGHT_SWEEP_EVERY_S)


class SweepDue(unittest.TestCase):
    def test_first_sweep_runs_straight_away(self):
        self.assertTrue(exp.sweep_due(SLOT, None, 7200))

    def test_waits_for_the_interval(self):
        self.assertFalse(exp.sweep_due(SLOT + 7199, SLOT, 7200))
        self.assertTrue(exp.sweep_due(SLOT + 7200, SLOT, 7200))


class DaySweep(unittest.TestCase):
    """Experiment 15: one set of settings an hour through the day."""

    def minute_at(self, past_hour):
        return SLOT + 5 * 3600 + past_hour * 60

    def test_runs_once_an_hour(self):
        labels = [s.label for s in exp.day_shots(self.minute_at(exp.DAY_SWEEP_MINUTE), SUNSET)]
        self.assertIn("sweep-ev-1", labels)
        self.assertNotIn("sweep-ev-1", [s.label for s in exp.day_shots(self.minute_at(exp.DAY_SWEEP_MINUTE + 1), SUNSET)])

    def test_never_on_a_capture_minute(self):
        self.assertNotEqual(exp.DAY_SWEEP_MINUTE * 60 % exp.SLOT_S, 0)

    def test_fits_the_gap_budget(self):
        total = sum(exp.estimate_s(s.shutter_us) for s in exp.day_sweep_shots())
        self.assertLess(total, 180)


class SunsetColour(unittest.TestCase):
    """Experiment 16: auto white balance may be taking the orange out of a sunset."""

    def test_every_five_minutes_tries_fixed_white_balance(self):
        minute = SUNSET - (SUNSET % 300) - 600 + 60   # the minute after a regular capture
        labels = [s.label for s in exp.day_shots(minute, SUNSET)]
        for label in ("ev-1", "awb-daylight", "awb-cloudy"):
            self.assertIn(label, labels)


class Sunrise(unittest.TestCase):
    """Experiment 16: the same treatment either side of sunrise."""

    SUNRISE = SUNSET - 9 * 3600

    def minute(self, offset_s):
        t = self.SUNRISE + offset_s
        return t - t % 60 + 60

    def labels(self, t):
        return [s.label for s in exp.day_shots(t, SUNSET, self.SUNRISE)]

    def test_brackets_around_sunrise(self):
        t = self.minute(300)
        if t % exp.SLOT_S < 60:
            t += 60
        self.assertEqual(self.labels(t)[:3], ["ev-2", "ev+0", "ev+2"])

    def test_no_brackets_when_no_sunrise_is_given(self):
        t = self.minute(300)
        if t % exp.SLOT_S < 60:
            t += 60
        self.assertNotIn("ev-2", [s.label for s in exp.day_shots(t, SUNSET)])

    def test_dawn_ladder_before_sunrise(self):
        t = self.minute(-600)
        if t % exp.SLOT_S < 60:
            t += 60
        self.assertIn("dawn-1000ms", self.labels(t))

    def test_no_dawn_ladder_after_sunrise(self):
        self.assertEqual([x for x in self.labels(self.minute(600)) if x.startswith("dawn-")], [])

    def test_every_minute_fits_the_gap_budget(self):
        for t in range(self.minute(-60 * 60), self.minute(60 * 60), 60):
            total = sum(exp.estimate_s(s.shutter_us) for s in exp.day_shots(t, SUNSET, self.SUNRISE))
            self.assertLess(total, 180, f"minute {t} plans {total} s of shooting")


class FailureGuard(unittest.TestCase):
    """A dead camera must not be retried non-stop: each try holds it through real capture slots."""

    def failed(self, guard, times, now=SLOT):
        for _ in range(times):
            guard.note(False, now)

    def test_keeps_shooting_through_a_single_failure(self):
        guard = exp.FailureGuard()
        self.failed(guard, 1)
        self.assertTrue(guard.allowed(SLOT + 1))

    def test_holds_off_after_repeated_failures(self):
        guard = exp.FailureGuard()
        self.failed(guard, exp.MAX_FAILURES)
        self.assertFalse(guard.allowed(SLOT + 1))
        self.assertFalse(guard.allowed(SLOT + exp.HOLD_OFF_S - 1))

    def test_tries_again_after_the_hold(self):
        guard = exp.FailureGuard()
        self.failed(guard, exp.MAX_FAILURES)
        self.assertTrue(guard.allowed(SLOT + exp.HOLD_OFF_S))

    def test_one_more_failure_after_the_hold_holds_off_again(self):
        guard = exp.FailureGuard()
        self.failed(guard, exp.MAX_FAILURES)
        later = SLOT + exp.HOLD_OFF_S
        guard.note(False, later)
        self.assertFalse(guard.allowed(later + 1))

    def test_a_good_shot_clears_the_count(self):
        guard = exp.FailureGuard()
        self.failed(guard, exp.MAX_FAILURES - 1)
        guard.note(True, SLOT)
        self.failed(guard, exp.MAX_FAILURES - 1)
        self.assertTrue(guard.allowed(SLOT + 1))

    def test_a_good_shot_after_the_hold_returns_to_normal(self):
        guard = exp.FailureGuard()
        self.failed(guard, exp.MAX_FAILURES)
        later = SLOT + exp.HOLD_OFF_S
        guard.note(True, later)
        guard.note(False, later)
        self.assertTrue(guard.allowed(later + 1))


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
