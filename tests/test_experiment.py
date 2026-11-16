#!/usr/bin/env python3
"""Offline tests for the experiment runner's scheduling. No camera or Pi needed."""
import importlib.util
import os
import pathlib
import time
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


class DenseFrameGuard(unittest.TestCase):
    """The production dense frame starts at :00 every minute and skips itself if the camera is busy."""

    MID_GAP = SLOT + 120  # a minute well clear of the regular slot

    def test_no_shot_starts_in_the_first_seconds_of_a_minute(self):
        for s in range(exp.DENSE_AFTER_S):
            self.assertFalse(exp.clear_to_start(self.MID_GAP + s, est_s=3), s)

    def test_short_shot_starts_after_the_dense_frame(self):
        self.assertTrue(exp.clear_to_start(self.MID_GAP + exp.DENSE_AFTER_S, est_s=3))

    def test_no_shot_runs_into_the_next_minute(self):
        self.assertFalse(exp.clear_to_start(self.MID_GAP + 55, est_s=3))
        self.assertFalse(exp.clear_to_start(self.MID_GAP + 30, est_s=30))

    def test_night_exposures_too_long_for_a_minute_are_not_held_to_it(self):
        # Only scheduled at night, outside the dense windows (sun below -9 degrees).
        self.assertTrue(exp.clear_to_start(self.MID_GAP + 30, est_s=exp.estimate_s(16_000_000)))

    def test_twilight_ladders_fit_the_minute_guard(self):
        # The dusk and dawn ladders run inside the dense windows, so they must not be exempt.
        for ms in exp.DUSK_MS:
            self.assertLessEqual(exp.estimate_s(ms * 1000), exp.MINUTE_GUARD_MAX_S, ms)


class SunsetPlan(unittest.TestCase):
    """Experiment 19: real inputs for the options Steven preferred (E, B, D)."""

    def minute(self, offset_s):
        m = SUNSET + offset_s
        return m - m % 60

    def five(self, offset_s):
        m = self.minute(offset_s)
        return m - m % exp.SLOT_S + 60  # the minute after a regular slot

    def plain(self, offset_s):
        m = self.five(offset_s)
        return m + 60

    def labels(self, minute):
        return [s.label for s in exp.sunset_shots(minute, SUNSET)]

    def test_every_minute_shoots_both_halves_of_e_and_b(self):
        self.assertEqual(self.labels(self.plain(-1200)), ["ev-2-daylight", "ev+0-daylight", "ev-2"])

    def test_daylight_shots_use_the_daylight_preset(self):
        for s in exp.sunset_shots(self.plain(600), SUNSET):
            if s.label.endswith("-daylight"):
                self.assertEqual(s.extra, ("--awb", "daylight"))
            else:
                self.assertEqual(s.extra, ())
        evs = {s.label: s.ev for s in exp.sunset_shots(self.plain(600), SUNSET)}
        self.assertEqual(evs, {"ev-2-daylight": -2, "ev+0-daylight": 0, "ev-2": -2})

    def test_five_minute_extras_before_sunset(self):
        self.assertEqual(self.labels(self.five(-1200))[3:], ["ev-3-daylight", "sun-100us", "sun-500us"])

    def test_no_sun_shots_after_sunset(self):
        self.assertEqual(self.labels(self.five(1200))[3:], ["ev-3-daylight"])

    def test_skips_the_regular_capture_minute(self):
        m = self.minute(-1200)
        self.assertEqual(exp.sunset_shots(m - m % exp.SLOT_S, SUNSET), [])

    def test_nothing_outside_the_window(self):
        self.assertEqual(exp.sunset_shots(self.plain(-exp.SUNSET_WINDOW_S - 600), SUNSET), [])
        self.assertEqual(exp.sunset_shots(self.plain(exp.SUNSET_WINDOW_S + 600), SUNSET), [])

    def test_a_busy_minute_fits_between_dense_frames(self):
        # Shots run back to back from the guard's start; each took about 2.5 s on Nov 8.
        minute = self.five(-1200)
        t = minute + exp.DENSE_AFTER_S
        for s in exp.sunset_shots(minute, SUNSET):
            self.assertTrue(exp.clear_to_start(t, exp.estimate_s(s.shutter_us)), s.label)
            t += 2.5
        self.assertLess(t, minute + 60)


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


class Calibration(unittest.TestCase):
    """Shots to take before the mount is glued (#12): dark, flat field, checkerboard."""

    def test_dark_frames_at_four_and_eight_seconds_with_bias(self):
        shots = exp.dark_shots()
        by = lambda p: [s for s in shots if s.label.startswith(p)]
        self.assertEqual(len(by("dark-4000ms-")), 5)
        self.assertEqual(len(by("dark-8000ms-")), 5)
        self.assertEqual(len(by("bias-")), 5)
        self.assertTrue(all(s.shutter_us == 4_000_000 for s in by("dark-4000ms-")))
        self.assertTrue(all(s.shutter_us == 100 for s in by("bias-")))
        self.assertTrue(all(s.raw and s.gain == 1 and s.awbgains for s in shots))
        self.assertEqual(len({s.label for s in shots}), len(shots))

    def test_dark_frame_count_can_change(self):
        self.assertEqual(len(exp.dark_shots(count=2)), 6)

    def test_flat_field_is_auto_exposed_with_raw(self):
        shots = exp.flat_shots()
        self.assertEqual(len(shots), 9)
        self.assertTrue(all(s.raw and s.shutter_us is None and s.gain is None for s in shots))
        self.assertEqual(len({s.label for s in shots}), 9)

    def test_checkerboard_is_jpeg_only(self):
        shots = exp.checker_shots()
        self.assertEqual(len(shots), 30)
        self.assertTrue(all(not s.raw for s in shots))
        self.assertEqual(len({s.label for s in shots}), 30)

    def test_programs_take_every_shot_and_space_the_checkerboard(self):
        class FakeRun:
            def __init__(self):
                self.taken = []

            def take(self, shot, max_wait_s):
                self.taken.append((shot.label, max_wait_s))

        slept = []
        saved = exp.time.sleep
        exp.time.sleep = slept.append
        try:
            for program, n in (("dark", 15), ("flat", 9), ("checker", 30)):
                run = FakeRun()
                args = exp.argparse.Namespace(program=program, count=None, every=4)
                exp.run_program(run, args)
                self.assertEqual(len(run.taken), n, program)
                self.assertTrue(all(w >= 300 for _, w in run.taken))
        finally:
            exp.time.sleep = saved
        self.assertEqual(slept.count(4), 29)      # between the 30 checkerboard frames only

    def test_the_command_line_knows_the_programs(self):
        for program in ("dark", "flat", "checker"):
            args = exp.parse_args([program, "--run", "calib-1"])
            self.assertEqual(args.program, program)
        self.assertEqual(exp.parse_args(["dark", "--run", "x", "--count", "3"]).count, 3)


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


class MoonPlan(unittest.TestCase):
    """Experiment 18: the moon in frame."""

    def test_minute_after_a_slot_is_the_full_ladder(self):
        shots = exp.moon_shots(SLOT + 60)
        self.assertEqual([s.shutter_us for s in shots], [50, 100, 250, 500, 1000, 2000, 4000])
        self.assertTrue(all(s.gain == 1 for s in shots))
        self.assertTrue(all(s.extra == ("--awb", "daylight") for s in shots))
        self.assertEqual([s.shutter_us for s in shots if s.raw], [250, 1000])

    def test_ladder_fits_in_the_gap_between_captures(self):
        total = sum(exp.estimate_s(s.shutter_us) for s in exp.moon_shots(SLOT + 60))
        self.assertLess(total, exp.SLOT_S - 60 - exp.AFTER_SLOT_S - exp.BEFORE_SLOT_S)

    def test_other_minutes_are_one_track_shot(self):
        for minute in (SLOT + 120, SLOT + 180, SLOT + 240):
            shots = exp.moon_shots(minute)
            self.assertEqual([(s.label, s.shutter_us, s.raw) for s in shots], [("moon-track", 1000, False)])

    def test_skips_the_real_capture_minute(self):
        self.assertEqual(exp.moon_shots(SLOT), [])
        self.assertEqual(exp.moon_shots(SLOT + exp.SLOT_S), [])

    def test_labels_are_unique_within_a_minute(self):
        labels = [s.label for s in exp.moon_shots(SLOT + 60)]
        self.assertEqual(len(labels), len(set(labels)))


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




class Rotation(unittest.TestCase):
    """An upside-down camera (ROTATION=180 in sunset.env) gets upright experiment shots too."""

    def setUp(self):
        self.saved = os.environ.pop("ROTATION", None)

    def tearDown(self):
        os.environ.pop("ROTATION", None)
        if self.saved is not None:
            os.environ["ROTATION"] = self.saved

    def test_no_rotation_unless_set(self):
        self.assertNotIn("--rotation", exp.Shot("x", ev=0).command("/tmp/x"))

    def test_rotation_180_rotates_every_shot(self):
        os.environ["ROTATION"] = "180"
        cmd = exp.Shot("x", shutter_us=4_000_000, gain=1).command("/tmp/x")
        self.assertEqual(cmd[cmd.index("--rotation") + 1], "180")

    def test_other_values_are_ignored(self):
        os.environ["ROTATION"] = "90"
        self.assertNotIn("--rotation", exp.Shot("x").command("/tmp/x"))

    def test_read_from_sunset_env(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = pathlib.Path(d) / "sunset.env"
            env.write_text("CAM_NAME=cm4wide\nROTATION=180  # upside down\n")
            saved, exp.ENV_FILE = exp.ENV_FILE, env
            try:
                exp.load_site_env()
            finally:
                exp.ENV_FILE = saved
        self.assertEqual(os.environ.get("ROTATION"), "180")


class BackgroundUpload(unittest.TestCase):
    """The upload must not stop the camera: on the CM4's slow Wi-Fi it blocked the run for about
    7 minutes every half hour, so cm4-sunset-1 (Nov 12) lost 15 to 9 minutes before sunset."""

    def setUp(self):
        import tempfile, threading
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (exp.EXP_ROOT, exp.subprocess.run, exp.Run._nas_ready if hasattr(exp.Run, "_nas_ready") else None,
                      exp.NAS_EXP_ROOT)
        exp.EXP_ROOT = pathlib.Path(self.tmp.name) / "runs"
        exp.NAS_EXP_ROOT = str(pathlib.Path(self.tmp.name) / "nas")
        self.release = threading.Event()
        self.entered = threading.Event()
        self.calls = []

        def fake_run(args, **kw):
            sent = None
            if any(str(a).startswith("--files-from") for a in args):
                ff = [a for a in args if str(a).startswith("--files-from")][0].split("=", 1)[1]
                sent = pathlib.Path(ff).read_text().split("\0")
            self.calls.append((list(map(str, args)), sent))
            if "--remove-source-files" in args:
                self.entered.set()
                self.release.wait(5)
            return exp.subprocess.CompletedProcess(args, 0, b"", b"")

        exp.subprocess.run = fake_run
        exp.Run._nas_ready = lambda self_: True
        self.run_ = exp.Run("t")
        (self.run_.dir / "a.jpg").write_bytes(b"a")
        self.run_.record(utc="x", label="a", status="ok")

    def tearDown(self):
        self.release.set()
        self.run_.finish_upload()
        exp.EXP_ROOT, exp.subprocess.run, exp.NAS_EXP_ROOT = self.saved[0], self.saved[1], self.saved[3]
        if self.saved[2] is None:
            del exp.Run._nas_ready
        else:
            exp.Run._nas_ready = self.saved[2]
        self.tmp.cleanup()

    def frames_sent(self):
        return [sent for args, sent in self.calls if "--remove-source-files" in args]

    def test_returns_while_the_copy_is_still_running(self):
        t0 = time.time()
        self.run_.upload()
        self.assertLess(time.time() - t0, 1)
        self.assertTrue(self.run_.uploading())

    def test_sends_only_the_files_there_when_it_was_called(self):
        self.run_.upload()
        (self.run_.dir / "b.jpg").write_bytes(b"half-written")
        self.release.set()
        self.run_.finish_upload()
        sent = [s for s in self.frames_sent()[0] if s]
        self.assertEqual(sent, ["a.jpg"])

    def test_manifest_goes_separately_and_is_never_removed(self):
        self.release.set()
        self.run_.upload(wait=True)
        self.assertNotIn("manifest.csv", self.frames_sent()[0])
        self.assertTrue(any(args[-2].endswith("manifest.csv") and "--remove-source-files" not in args
                            for args, _ in self.calls))

    def test_skips_while_one_is_already_running(self):
        self.run_.upload()
        self.assertTrue(self.entered.wait(5))
        self.run_.upload()
        self.assertEqual(len(self.frames_sent()), 1)

    def test_final_upload_waits_for_everything(self):
        self.run_.upload()
        (self.run_.dir / "b.jpg").write_bytes(b"b")
        self.release.set()
        self.run_.upload(wait=True)
        self.assertFalse(self.run_.uploading())
        self.assertIn("b.jpg", self.frames_sent()[-1])

    def test_last_upload_time_is_set_when_it_starts(self):
        before = time.time()
        self.run_.upload()
        self.assertGreaterEqual(self.run_.last_upload, before)


class BoundedUpload(BackgroundUpload):
    """#27: the final upload waited with no limit, holding .experiment.lock, so later programs
    queued behind a copy that can take up to an hour."""

    def setUp(self):
        super().setUp()
        self.saved_join = exp.UPLOAD_JOIN_S
        exp.UPLOAD_JOIN_S = 0.2

    def tearDown(self):
        exp.UPLOAD_JOIN_S = self.saved_join
        super().tearDown()

    def test_waiting_for_a_stuck_copy_has_a_limit(self):
        self.run_.upload()
        self.assertTrue(self.entered.wait(5))
        t0 = time.time()
        self.assertFalse(self.run_.finish_upload(timeout=0.2))
        self.assertLess(time.time() - t0, 2)
        self.assertTrue(self.run_.uploading())

    def test_final_upload_gives_up_on_a_stuck_copy_without_starting_another(self):
        self.run_.upload()
        self.assertTrue(self.entered.wait(5))
        t0 = time.time()
        self.run_.upload(wait=True)
        self.assertLess(time.time() - t0, 2)
        self.assertEqual(len(self.frames_sent()), 1)


class FakeLock:
    def __init__(self, free=True):
        self.free = free
        self.held = False
        self.events = []

    def acquire(self):
        self.events.append("acquire")
        if self.free:
            self.held = True
        return self.free

    def release(self):
        self.events.append("release")
        self.held = False


class ShotWithTheCaptureLock(unittest.TestCase):
    """#14: the runner takes production's lock around each shot, so a regular capture waits for an
    overrunning shot instead of failing on a busy camera, and a dense frame skips cleanly."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {name: getattr(exp, name) for name in
                      ("EXP_ROOT", "clear_to_start", "camera_busy", "read_text", "subprocess", "time",
                       "sd_low_reason")}
        exp.EXP_ROOT = pathlib.Path(self.tmp.name) / "runs"
        exp.sd_low_reason = lambda usage: None      # whatever the test machine's disk holds
        exp.clear_to_start = lambda now, est: True
        exp.camera_busy = lambda: False
        exp.read_text = lambda cmd: ""
        self.run_ = exp.Run("t")
        self.lock = self.run_.camera_lock = FakeLock()

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(exp, name, value)
        self.tmp.cleanup()

    def rows(self):
        import csv
        with self.run_.manifest.open() as f:
            return list(csv.DictReader(f))

    def fake_subprocess(self, behaviour):
        import types
        calls = []

        def run(cmd, **kw):
            calls.append((cmd, kw, self.lock.held))
            return behaviour(cmd, kw)
        exp.subprocess = types.SimpleNamespace(run=run, TimeoutExpired=exp.subprocess.TimeoutExpired,
                                               SubprocessError=exp.subprocess.SubprocessError,
                                               CompletedProcess=exp.subprocess.CompletedProcess)
        return calls

    def test_the_shot_runs_while_holding_the_lock_and_lets_go_after(self):
        calls = self.fake_subprocess(lambda cmd, kw: exp.subprocess.CompletedProcess(cmd, 0))
        self.run_.take(exp.Shot("ev-2", ev=-2), max_wait_s=0)
        self.assertTrue(calls[0][2], "lock not held during the shot")
        self.assertEqual(self.lock.events, ["acquire", "release"])
        self.assertEqual(self.rows()[0]["status"], "ok")

    def test_no_shot_while_a_capture_holds_the_lock(self):
        self.lock.free = False
        calls = self.fake_subprocess(lambda cmd, kw: self.fail("shot taken without the lock"))
        exp.time = __import__("types").SimpleNamespace(time=time.time, sleep=lambda s: None,
                                                       strftime=time.strftime, gmtime=time.gmtime)
        self.run_.take(exp.Shot("ev-2", ev=-2), max_wait_s=0)
        self.assertEqual(calls, [])
        self.assertEqual(self.rows()[0]["status"], "skipped: camera busy (capture lock)")

    def test_waits_for_the_lock_within_its_time(self):
        self.lock.free = False
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            self.lock.free = True       # the capture finishes
        exp.time = __import__("types").SimpleNamespace(time=time.time, sleep=sleep,
                                                       strftime=time.strftime, gmtime=time.gmtime)
        self.fake_subprocess(lambda cmd, kw: exp.subprocess.CompletedProcess(cmd, 0))
        self.run_.take(exp.Shot("ev-2", ev=-2), max_wait_s=30)
        self.assertEqual(len(sleeps), 1)
        self.assertEqual(self.rows()[0]["status"], "ok")

    def test_a_hung_shot_is_killed_soon_after_its_estimate_and_frees_the_lock(self):
        def hang(cmd, kw):
            raise exp.subprocess.TimeoutExpired(cmd, kw["timeout"])
        calls = self.fake_subprocess(hang)
        shot = exp.Shot("ev-2", ev=-2)
        self.run_.take(shot, max_wait_s=0)
        self.assertEqual(calls[0][1]["timeout"], exp.estimate_s(None) + 1 + exp.SHOT_TIMEOUT_MARGIN_S)
        self.assertEqual(self.rows()[0]["status"], "failed timeout")
        self.assertFalse(self.lock.held)
        self.assertEqual(self.lock.events, ["acquire", "release"])

    def test_a_real_overrunning_process_is_stopped_at_the_timeout(self):
        import sys
        saved_timeout, saved_command = exp.shot_timeout_s, exp.Shot.command
        exp.shot_timeout_s = lambda shot: 1.0
        exp.Shot.command = lambda self_, base: [sys.executable, "-c", "import time; time.sleep(30)"]
        try:
            t0 = time.time()
            self.run_.take(exp.Shot("ev-2", ev=-2), max_wait_s=0)
            took = time.time() - t0
        finally:
            exp.shot_timeout_s, exp.Shot.command = saved_timeout, saved_command
        self.assertLess(took, 10)
        row = self.rows()[0]
        self.assertEqual(row["status"], "failed timeout")
        self.assertLess(float(row["seconds"]), 10)
        self.assertFalse(self.lock.held)

    def test_timeouts_are_the_estimate_plus_a_margin(self):
        self.assertEqual(exp.SHOT_TIMEOUT_MARGIN_S, 15)
        self.assertEqual(exp.shot_timeout_s(exp.Shot("auto")), 6 + 1 + 15)
        night = exp.Shot("n", shutter_us=4_000_000, gain=1)
        self.assertEqual(exp.shot_timeout_s(night), exp.estimate_s(4_000_000) + 1 + 15)
        self.assertLess(exp.shot_timeout_s(night), 60 + 4 * 4)          # the old limit
        settle = exp.Shot("s", settle_ms=3000)
        self.assertEqual(exp.shot_timeout_s(settle), 6 + 3 + 15)


class CaptureLockFile(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, ".sunset-capture.lock")
        self.saved_env = os.environ.pop("LOCK_FILE", None)

    def tearDown(self):
        os.environ.pop("LOCK_FILE", None)
        if self.saved_env is not None:
            os.environ["LOCK_FILE"] = self.saved_env

    def test_same_file_as_the_capture_script(self):
        # sunset-capture.sh: $(dirname "$OUT_ROOT")/.sunset-capture.lock, and the runner lives in
        # ~/sunset/experiments, so its parent is ~/sunset.
        self.assertEqual(exp.capture_lock_path(), exp.HERE.parent / ".sunset-capture.lock")
        os.environ["LOCK_FILE"] = "/elsewhere/lock"
        self.assertEqual(str(exp.capture_lock_path()), str(pathlib.Path("/elsewhere/lock")))

    def test_without_fcntl_locking_is_skipped_not_fatal(self):
        saved = exp.fcntl
        exp.fcntl = None
        try:
            lock = exp.CaptureLock(self.path)
            self.assertTrue(lock.acquire())
            lock.release()
        finally:
            exp.fcntl = saved

    @unittest.skipIf(exp.fcntl is None, "flock needs Linux")
    def test_a_lock_held_by_the_capture_blocks_the_runner(self):
        import fcntl
        with open(self.path, "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertFalse(exp.CaptureLock(self.path).acquire())
        lock = exp.CaptureLock(self.path)
        self.assertTrue(lock.acquire())
        with open(self.path) as other:
            with self.assertRaises(OSError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock.release()
        with open(self.path) as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @unittest.skipIf(exp.fcntl is None, "flock needs Linux")
    def test_creates_the_file_if_the_capture_never_has(self):
        lock = exp.CaptureLock(self.path)
        self.assertTrue(lock.acquire())
        lock.release()
        self.assertTrue(os.path.exists(self.path))


class SdGuard(unittest.TestCase):
    """#27: an absolute 5 GB floor let experiments push a 64 GB card past production's 85% DNG drop."""
    GB = 1024 ** 3

    def usage(self, total_gb, free_gb):
        import collections
        u = collections.namedtuple("usage", "total used free")
        return u(total_gb * self.GB, (total_gb - free_gb) * self.GB, free_gb * self.GB)

    def test_stops_above_the_percentage(self):
        self.assertEqual(exp.MAX_SD_USED_PCT, 70)
        self.assertIn("71%", exp.sd_low_reason(self.usage(64, 18.5)))

    def test_carries_on_below_it(self):
        self.assertIsNone(exp.sd_low_reason(self.usage(64, 30)))

    def test_absolute_floor_still_applies(self):
        self.assertIsNotNone(exp.sd_low_reason(self.usage(8, 4)))   # 50% used but only 4 GB free

    def test_skips_the_shot(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        saved = exp.EXP_ROOT, exp.sd_low_reason, exp.clear_to_start, exp.camera_busy
        exp.EXP_ROOT = pathlib.Path(tmp.name)
        exp.sd_low_reason = lambda usage: "SD 90% used"
        exp.clear_to_start, exp.camera_busy = (lambda now, est: True), (lambda: False)
        try:
            run = exp.Run("t")
            run.camera_lock = FakeLock()
            run.take(exp.Shot("x"), max_wait_s=0)
        finally:
            exp.EXP_ROOT, exp.sd_low_reason, exp.clear_to_start, exp.camera_busy = saved
        self.assertIn("skipped: SD low", run.manifest.read_text())
        self.assertFalse(run.camera_lock.held)


class FinalUpload(unittest.TestCase):
    """#27: .experiment.lock is let go before the last copy, so the next program can start."""

    def test_lock_released_before_the_final_upload(self):
        import contextlib, tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = {"held": False, "held_at_upload": None}

        @contextlib.contextmanager
        def fake_lock(path):
            state["held"] = True
            try:
                yield
            finally:
                state["held"] = False

        def fake_upload(self_, wait=False):
            state["held_at_upload"] = state["held"]
        saved = exp.experiment_lock, exp.run_program, exp.Run.upload, exp.EXP_ROOT, exp.load_site_env
        exp.experiment_lock, exp.Run.upload = fake_lock, fake_upload
        exp.run_program = lambda run, args: self.assertTrue(state["held"])
        exp.EXP_ROOT, exp.load_site_env = pathlib.Path(tmp.name), (lambda: None)
        try:
            exp.main(["sunset", "--run", "t", "--sunset", "1", "--until", "1"])
        finally:
            exp.experiment_lock, exp.run_program, exp.Run.upload, exp.EXP_ROOT, exp.load_site_env = saved
        self.assertIs(state["held_at_upload"], False)


if __name__ == "__main__":
    unittest.main()
