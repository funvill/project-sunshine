"""Tests for nas/sunset-daily.py: python3 tests/test_daily.py

Fake frames only, no Instagram. Encoding tests run the real ffmpeg on small images
and are skipped if ffmpeg is not installed. Expected values are worked out by hand.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "nas", "sunset-daily.py")
spec = importlib.util.spec_from_file_location("sunset_daily", SCRIPT)
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)

UTC = timezone.utc
PST = timezone(timedelta(hours=-8))   # enough for December cases; no tz database needed
SUNSET = datetime(2026, 12, 22, 0, 14, tzinfo=UTC)   # local 21 December, 4:14 pm
HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def real_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Vancouver")
    except Exception:
        raise unittest.SkipTest("no time zone database on this machine")


def stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def frame_at(minutes, az=None, sunset=SUNSET):
    """A Frame the way list_frames builds it, `minutes` after `sunset`."""
    t = sunset + timedelta(minutes=minutes)
    sun = {"azimuth_deg": 250.0 if az is None else az, "elevation_deg": -1.0,
           "azimuth_ref": "true_north", "computed_for_utc": stamp(t),
           "nearest_sunset_utc": stamp(sunset), "minutes_from_sunset": float(minutes)}
    return daily.Frame(t, "unused.jpg", sun)


class Tree:
    """A frames folder laid out the way the Pi's sync leaves it on the NAS."""

    def __init__(self, test, image=None):
        self.dir = tempfile.mkdtemp()
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.frames = os.path.join(self.dir, "wide")
        self.daily = os.path.join(self.dir, "daily")
        self.crop_file = os.path.join(self.dir, "crop.json")
        self.image = image

    def add(self, t, sunset=SUNSET, write_json=True, az=250.0, name_suffix=""):
        folder = os.path.join(self.frames, t.strftime("%Y"), t.strftime("%m"), t.strftime("%d"))
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, "wide_%s%s" % (t.strftime("%Y%m%dT%H%M%SZ"), name_suffix))
        if self.image:
            shutil.copyfile(self.image, base + ".jpg")
        else:
            open(base + ".jpg", "wb").close()
        if write_json:
            minutes = (t - sunset).total_seconds() / 60.0
            with open(base + ".json", "w") as f:
                json.dump({"ExposureTime": 1000, "Lux": 400.0,
                           "Sun": {"azimuth_deg": az, "elevation_deg": -1.0,
                                   "azimuth_ref": "true_north",
                                   "computed_for_utc": stamp(t),
                                   "nearest_sunset_utc": stamp(sunset),
                                   "minutes_from_sunset": round(minutes, 1)}}, f)
        return base

    def add_day(self, count=96, sunset=SUNSET):
        """`count` frames, 15 minutes apart, the last one exactly 30 minutes after sunset."""
        last = sunset + timedelta(minutes=30)
        for i in range(count):
            self.add(last - timedelta(minutes=15 * i), sunset)

    def config(self, **over):
        values = dict(frames_dir=self.frames, daily_dir=self.daily, crop_file=self.crop_file,
                      tz=PST, start_date=datetime(2026, 12, 21).date())
        values.update(over)
        return daily.Config(**values)

    def record(self, date="2026-12-21"):
        with open(os.path.join(self.daily, date + ".json")) as f:
            return json.load(f)


def make_image(path, width=640, height=480, color="white"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=%s:s=%dx%d:d=1" % (color, width, height),
                    "-frames:v", "1", "-q:v", "2", path], check=True)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                         check=True, capture_output=True).stdout
    return json.loads(out)


def gray_row(path, y, width=1080, height=1920, seek=None):
    """One row of luma from a frame of a video or an image."""
    args = ["ffmpeg", "-loglevel", "error"]
    if seek is not None:
        args += ["-ss", str(seek)]
    args += ["-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(args, check=True, capture_output=True).stdout
    return raw[y * width:(y + 1) * width]


class FrameNames(unittest.TestCase):
    def test_reads_utc_time_from_a_day_frame(self):
        self.assertEqual(daily.parse_frame_time("wide_20261222T001500Z.jpg"),
                         datetime(2026, 12, 22, 0, 15, tzinfo=UTC))

    def test_night_frame_is_not_a_normal_frame(self):
        self.assertIsNone(daily.parse_frame_time("wide_20261222T001500Z_night.jpg"))

    def test_other_files_are_ignored(self):
        self.assertIsNone(daily.parse_frame_time("wide_20261222T001500Z.dng"))
        self.assertIsNone(daily.parse_frame_time("notes.jpg"))


class ListFrames(unittest.TestCase):
    def test_reads_both_utc_date_folders_in_time_order(self):
        tree = Tree(self)
        tree.add(datetime(2026, 12, 22, 0, 0, tzinfo=UTC))
        tree.add(datetime(2026, 12, 21, 23, 45, tzinfo=UTC))
        got = daily.list_frames(tree.frames, datetime(2026, 12, 21, 12, tzinfo=UTC),
                                datetime(2026, 12, 22, 12, tzinfo=UTC))
        self.assertEqual([f.time.strftime("%d %H:%M") for f in got], ["21 23:45", "22 00:00"])

    def test_leaves_out_night_frames(self):
        tree = Tree(self)
        t = datetime(2026, 12, 22, 0, 0, tzinfo=UTC)
        tree.add(t)
        tree.add(t, name_suffix="_night")
        got = daily.list_frames(tree.frames, t - timedelta(hours=1), t + timedelta(hours=1))
        self.assertEqual(len(got), 1)

    def test_frame_with_no_json_still_counts_but_has_no_sun(self):
        tree = Tree(self)
        t = datetime(2026, 12, 22, 0, 0, tzinfo=UTC)
        tree.add(t, write_json=False)
        got = daily.list_frames(tree.frames, t - timedelta(hours=1), t + timedelta(hours=1))
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0].sun)

    def test_frame_with_broken_json_still_counts_but_has_no_sun(self):
        tree = Tree(self)
        t = datetime(2026, 12, 22, 0, 0, tzinfo=UTC)
        base = tree.add(t)
        with open(base + ".json", "w") as f:
            f.write("{ cut off")
        got = daily.list_frames(tree.frames, t - timedelta(hours=1), t + timedelta(hours=1))
        self.assertIsNone(got[0].sun)

    def test_drops_frames_outside_the_range(self):
        tree = Tree(self)
        t = datetime(2026, 12, 22, 0, 0, tzinfo=UTC)
        tree.add(t)
        got = daily.list_frames(tree.frames, t + timedelta(minutes=1), t + timedelta(hours=1))
        self.assertEqual(got, [])


class DueSunsets(unittest.TestCase):
    def test_frame_30_minutes_after_sunset_makes_it_due(self):
        self.assertEqual(daily.due_sunsets([frame_at(30)]), [SUNSET])

    def test_frame_just_under_30_minutes_does_not(self):
        self.assertEqual(daily.due_sunsets([frame_at(29.9)]), [])

    def test_frame_before_sunset_does_not(self):
        self.assertEqual(daily.due_sunsets([frame_at(-200)]), [])

    def test_frame_with_no_sun_block_does_not(self):
        self.assertEqual(daily.due_sunsets([daily.Frame(SUNSET, "x.jpg", None)]), [])

    def test_two_sunsets_come_back_oldest_first(self):
        later = SUNSET + timedelta(days=1)
        self.assertEqual(daily.due_sunsets([frame_at(40, sunset=later), frame_at(40)]), [SUNSET, later])


class Window(unittest.TestCase):
    def test_is_the_24_hours_ending_30_minutes_after_sunset(self):
        # Ends 2026-12-22 00:44; starts 2026-12-21 00:44, not inclusive.
        frames = [daily.Frame(datetime(2026, 12, 21, 0, 44, tzinfo=UTC), "start", None),
                  daily.Frame(datetime(2026, 12, 21, 0, 45, tzinfo=UTC), "inside-first", None),
                  daily.Frame(datetime(2026, 12, 22, 0, 44, tzinfo=UTC), "inside-last", None),
                  daily.Frame(datetime(2026, 12, 22, 0, 45, tzinfo=UTC), "after", None)]
        self.assertEqual([f.jpg for f in daily.select_window(frames, SUNSET)],
                         ["inside-first", "inside-last"])


class SunsetFrame(unittest.TestCase):
    def test_picks_the_frame_closest_to_sunset(self):
        frames = [frame_at(-20), frame_at(4), frame_at(-6)]
        self.assertEqual(daily.nearest_frame(frames, SUNSET).sun["minutes_from_sunset"], 4.0)

    def test_works_without_sun_data(self):
        f = daily.Frame(SUNSET + timedelta(minutes=2), "x.jpg", None)
        self.assertIs(daily.nearest_frame([f], SUNSET), f)


class SunsetAzimuth(unittest.TestCase):
    def test_interpolates_between_the_frames_either_side(self):
        # -5 min 250.0, +10 min 253.0: a third of the way along is 251.0.
        az, how = daily.sunset_azimuth([frame_at(-5, 250.0), frame_at(10, 253.0)], SUNSET)
        self.assertAlmostEqual(az, 251.0)
        self.assertEqual(how, "interpolated")

    def test_uses_the_closest_pair_not_the_first_pair(self):
        frames = [frame_at(-20, 100.0), frame_at(-5, 250.0), frame_at(10, 253.0), frame_at(25, 400.0)]
        self.assertAlmostEqual(daily.sunset_azimuth(frames, SUNSET)[0], 251.0)

    def test_single_frame_after_sunset_is_corrected_back(self):
        # +10 min at 0.19 deg/min is 1.9 deg: 253.0 - 1.9
        az, how = daily.sunset_azimuth([frame_at(10, 253.0)], SUNSET)
        self.assertAlmostEqual(az, 251.1)
        self.assertEqual(how, "single_frame")

    def test_single_frame_before_sunset_is_corrected_forward(self):
        az, how = daily.sunset_azimuth([frame_at(-10, 250.0)], SUNSET)
        self.assertAlmostEqual(az, 251.9)
        self.assertEqual(how, "single_frame")

    def test_frames_far_from_sunset_are_not_used(self):
        self.assertEqual(daily.sunset_azimuth([frame_at(-120), frame_at(120)], SUNSET), (None, None))

    def test_pair_with_one_far_frame_falls_back_to_the_near_one(self):
        az, how = daily.sunset_azimuth([frame_at(-120, 200.0), frame_at(10, 253.0)], SUNSET)
        self.assertAlmostEqual(az, 251.1)
        self.assertEqual(how, "single_frame")

    def test_a_different_sunsets_frame_is_not_used(self):
        other = SUNSET + timedelta(days=1)
        self.assertEqual(daily.sunset_azimuth([frame_at(-5, sunset=other)], SUNSET), (None, None))

    def test_frames_with_no_sun_block_are_not_used(self):
        self.assertEqual(daily.sunset_azimuth([daily.Frame(SUNSET, "x.jpg", None)], SUNSET), (None, None))

    def test_interpolates_across_00_utc_when_a_frame_is_late(self):
        # Sunset 00:14 with the 00:00 and 00:15 frames gone: 23:45 and 00:30 straddle midnight.
        before = frame_at(-29, 247.0)
        after = frame_at(16, 256.0)
        self.assertEqual(before.time.day, 21)
        self.assertEqual(after.time.day, 22)
        # 29/45 of the way from 247.0 to 256.0: 247 + 9 * 29/45 = 252.8
        self.assertAlmostEqual(daily.sunset_azimuth([before, after], SUNSET)[0], 252.8)


class StepFlag(unittest.TestCase):
    def test_flags_more_than_one_degree_from_the_day_before(self):
        self.assertTrue(daily.azimuth_step_flagged(251.1, 250.0))
        self.assertTrue(daily.azimuth_step_flagged(248.9, 250.0))

    def test_normal_seasonal_step_is_not_flagged(self):
        self.assertFalse(daily.azimuth_step_flagged(250.6, 250.0))

    def test_no_data_is_not_flagged(self):
        self.assertFalse(daily.azimuth_step_flagged(None, 250.0))
        self.assertFalse(daily.azimuth_step_flagged(250.0, None))


class Calibration(unittest.TestCase):
    DAY = datetime(2027, 2, 1).date()

    def test_averages_the_fits_so_far(self):
        cfg = {"calibrations": [{"start": "2026-12-21", "cx": 2028, "fits": [
            {"date": "2026-12-28", "f_px": 1000.0, "az0_deg": 270.0},
            {"date": "2027-01-28", "f_px": 1200.0, "az0_deg": 272.0}]}]}
        self.assertEqual(daily.active_calibration(cfg, self.DAY),
                         {"cx": 2028, "f_px": 1100.0, "az0_deg": 271.0, "fits_used": 2})

    def test_ignores_fits_after_the_day(self):
        cfg = {"calibrations": [{"start": "2026-12-21", "cx": 2028, "fits": [
            {"date": "2026-12-28", "f_px": 1000.0, "az0_deg": 270.0},
            {"date": "2027-03-01", "f_px": 1400.0, "az0_deg": 280.0}]}]}
        self.assertEqual(daily.active_calibration(cfg, self.DAY)["f_px"], 1000.0)

    def test_a_bump_starts_over_and_never_averages_across_it(self):
        cfg = {"calibrations": [
            {"start": "2026-12-21", "cx": 2028, "fits": [{"date": "2026-12-28", "f_px": 1000.0, "az0_deg": 270.0}]},
            {"start": "2027-01-15", "cx": 2030, "fits": [{"date": "2027-01-20", "f_px": 1100.0, "az0_deg": 268.0}]}]}
        self.assertEqual(daily.active_calibration(cfg, self.DAY),
                         {"cx": 2030, "f_px": 1100.0, "az0_deg": 268.0, "fits_used": 1})

    def test_regenerating_an_old_day_uses_the_calibration_of_that_day(self):
        cfg = {"calibrations": [
            {"start": "2026-12-21", "cx": 2028, "fits": [{"date": "2026-12-28", "f_px": 1000.0, "az0_deg": 270.0}]},
            {"start": "2027-01-15", "cx": 2030, "fits": [{"date": "2027-01-20", "f_px": 1100.0, "az0_deg": 268.0}]}]}
        got = daily.active_calibration(cfg, datetime(2027, 1, 10).date())
        self.assertEqual(got["f_px"], 1000.0)

    def test_month_with_no_clear_day_is_recorded_but_not_averaged(self):
        cfg = {"calibrations": [{"start": "2026-12-21", "cx": 2028, "fits": [
            {"date": "2026-12-28", "f_px": 1000.0, "az0_deg": 270.0},
            {"date": "2027-01-28", "note": "no clear day"}]}]}
        self.assertEqual(daily.active_calibration(cfg, self.DAY)["fits_used"], 1)

    def test_no_usable_fit_means_no_calibration(self):
        self.assertIsNone(daily.active_calibration({"calibrations": [{"start": "2026-12-21", "cx": 2028, "fits": []}]}, self.DAY))
        self.assertIsNone(daily.active_calibration({}, self.DAY))


class CropWindow(unittest.TestCase):
    CAL = {"cx": 2028, "f_px": 1000.0, "az0_deg": 270.0}

    def crop(self, az, cal=CAL, offset=0, prev=None, fixed=None, w=4056, h=3040):
        return daily.crop_for_day(w, h, az, cal, fixed, offset, prev)

    def test_full_height_crop_is_1710_wide(self):
        got = self.crop(270.0)
        self.assertEqual((got["width"], got["height"]), (1710, 3040))

    def test_width_is_kept_even_for_small_frames(self):
        # 304 * 9/16 = 171, which yuv420p can't scale evenly, so 170.
        self.assertEqual(self.crop(None, None, w=406, h=304)["width"], 170)

    def test_sun_on_the_lens_axis_is_centred(self):
        got = self.crop(270.0)
        self.assertEqual((got["sun_x"], got["x"], got["source"], got["clamped"]), (2028, 1173, "azimuth", False))

    def test_tangent_model_north_of_the_axis(self):
        # tan(45) = 1: 2028 + 1000 = 3028; 3028 - 855 = 2173
        got = self.crop(315.0)
        self.assertEqual((got["sun_x"], got["x"], got["clamped"]), (3028, 2173, False))

    def test_tangent_model_south_of_the_axis(self):
        # 2028 - 1000 = 1028; 1028 - 855 = 173
        self.assertEqual(self.crop(225.0)["x"], 173)

    def test_offset_moves_the_crop_not_the_predicted_sun(self):
        got = self.crop(270.0, offset=100)
        self.assertEqual((got["sun_x"], got["x"]), (2028, 1273))

    def test_clamps_at_the_right_edge(self):
        got = self.crop(315.0, dict(self.CAL, f_px=2028.0))
        self.assertEqual((got["x"], got["clamped"]), (2346, True))

    def test_clamps_at_the_left_edge(self):
        got = self.crop(225.0, dict(self.CAL, f_px=2028.0))
        self.assertEqual((got["x"], got["clamped"]), (0, True))

    def test_no_azimuth_uses_the_previous_days_centre(self):
        got = self.crop(None, prev=2500)
        self.assertEqual((got["x"], got["source"], got["sun_x"]), (1645, "previous_day", None))

    def test_no_azimuth_and_no_previous_day_uses_the_fixed_centre(self):
        got = self.crop(None, fixed=2500)
        self.assertEqual((got["x"], got["source"]), (1645, "fixed"))

    def test_no_calibration_uses_the_fixed_centre_even_with_an_azimuth(self):
        got = self.crop(250.0, None, prev=3000, fixed=2500)
        self.assertEqual((got["x"], got["source"]), (1645, "fixed"))

    def test_fixed_centre_defaults_to_the_middle_of_the_frame(self):
        self.assertEqual(self.crop(None, None)["x"], 1173)

    def test_fixed_centre_clamps_too(self):
        got = self.crop(None, None, fixed=4000)
        self.assertEqual((got["x"], got["clamped"]), (2346, True))


class Dates(unittest.TestCase):
    def test_winter_sunset_belongs_to_the_previous_utc_date(self):
        self.assertEqual(daily.local_date(SUNSET, PST).isoformat(), "2026-12-21")

    def test_summer_sunset_uses_daylight_time(self):
        tz = real_tz()
        s = datetime(2027, 6, 22, 4, 22, tzinfo=UTC)
        self.assertEqual(daily.local_date(s, tz).isoformat(), "2027-06-21")
        self.assertIn("9:22 pm", daily.build_caption(s, tz, datetime(2026, 12, 21).date()))


class Caption(unittest.TestCase):
    START = datetime(2026, 12, 21).date()

    def test_first_day(self):
        self.assertEqual(daily.build_caption(SUNSET, PST, self.START),
                         "Sunset, 21 December 2026, 4:14 pm\nDay 1, looking west.\n\n"
                         "#sunset #timelapse #raspberrypi")

    def test_counts_up_with_no_total(self):
        got = daily.build_caption(SUNSET + timedelta(days=100), PST, self.START)
        self.assertIn("Day 101, looking west.", got)
        self.assertNotIn(" of ", got)

    def test_dry_run_before_the_start_has_no_day_number(self):
        got = daily.build_caption(SUNSET - timedelta(days=5), PST, self.START)
        self.assertIn("\nLooking west.\n", got)
        self.assertNotIn("Day", got)

    def test_tags_can_be_changed(self):
        self.assertTrue(daily.build_caption(SUNSET, PST, self.START, "#vancouver").endswith("\n\n#vancouver"))

    def test_morning_and_noon_hours_read_normally(self):
        got = daily.build_caption(datetime(2026, 12, 22, 20, 5, tzinfo=UTC), PST, self.START)
        self.assertIn("12:05 pm", got)


class ConcatList(unittest.TestCase):
    def test_shows_each_frame_a_twelfth_of_a_second_and_holds_sunset(self):
        frames = [daily.Frame(SUNSET, "/a/one.jpg", None), daily.Frame(SUNSET, "/a/two.jpg", None),
                  daily.Frame(SUNSET, "/a/three.jpg", None)]
        lines = daily.concat_list(frames, frames[1]).splitlines()
        self.assertEqual(lines, ["file '/a/one.jpg'", "duration 0.083333",
                                 "file '/a/two.jpg'", "duration 1.583333",
                                 "file '/a/three.jpg'", "duration 0.083333",
                                 "file '/a/three.jpg'"])

    def test_quote_in_a_path_is_escaped(self):
        f = daily.Frame(SUNSET, "/a/it's.jpg", None)
        self.assertIn(r"file '/a/it'\''s.jpg'", daily.concat_list([f], f))


class RunWithoutEncoding(unittest.TestCase):
    """The decisions run() makes, with a stand-in encoder (ffmpeg is tested below)."""
    NOW = SUNSET + timedelta(hours=1)

    def setUp(self):
        self.tree = Tree(self)
        self.encoded = []

    def run_job(self, now=NOW, **over):
        def fake_encode(cfg, frames, sunset_frame, crop, mask, out):
            self.encoded.append((out, len(frames)))
            with open(out, "wb") as f:
                f.write(b"video")
        return daily.run(self.tree.config(**over), now, encode=fake_encode,
                         frame_size=lambda path: (4056, 3040), check_image=lambda *a: None)

    def test_does_nothing_before_a_sunset_is_due(self):
        self.tree.add_day()
        self.assertEqual(self.run_job(SUNSET + timedelta(minutes=29)), 0)
        self.assertEqual(self.encoded, [])

    def test_encodes_once_and_records_it(self):
        self.tree.add_day()
        self.assertEqual(self.run_job(), 0)
        self.assertEqual(len(self.encoded), 1)
        self.assertEqual(self.encoded[0][1], 96)
        rec = self.tree.record("2026-12-21")
        self.assertEqual(rec["status"], "encoded")
        self.assertEqual(rec["sunset_utc"], "2026-12-22T00:14:00Z")
        self.assertEqual(rec["frames"], 96)
        self.assertTrue(rec["caption"].startswith("Sunset, 21 December 2026"))
        self.assertTrue(os.path.exists(os.path.join(self.tree.daily, rec["video"])))
        self.assertFalse(rec["posted"])

    def test_second_run_leaves_the_day_alone(self):
        self.tree.add_day()
        self.run_job()
        first = self.tree.record("2026-12-21")
        self.run_job(self.NOW + timedelta(minutes=30))
        self.assertEqual(len(self.encoded), 1)
        self.assertEqual(self.tree.record("2026-12-21"), first)

    def test_too_few_frames_skips_and_says_why(self):
        # 70% of 96 is 67.2, so 67 is too few.
        self.tree.add_day(67)
        self.assertEqual(self.run_job(), 0)
        self.assertEqual(self.encoded, [])
        rec = self.tree.record("2026-12-21")
        self.assertEqual(rec["status"], "skipped")
        self.assertEqual(rec["frames"], 67)
        self.assertIn("67", rec["reason"])

    def test_just_enough_frames_encodes(self):
        self.tree.add_day(68)
        self.run_job()
        self.assertEqual(self.tree.record("2026-12-21")["status"], "encoded")

    def test_skipped_day_is_not_tried_again(self):
        self.tree.add_day(10)
        self.run_job()
        self.run_job()
        self.assertEqual(self.encoded, [])
        self.assertEqual(self.tree.record("2026-12-21")["status"], "skipped")

    def test_missed_day_is_caught_up_the_next_day(self):
        tomorrow = SUNSET + timedelta(days=1)
        self.tree.add_day(sunset=SUNSET)
        self.tree.add(SUNSET + timedelta(hours=12), SUNSET)
        self.assertEqual(self.run_job(tomorrow - timedelta(hours=2)), 0)
        self.assertEqual(self.tree.record("2026-12-21")["status"], "encoded")

    def test_sunset_older_than_the_lookback_is_left_alone(self):
        self.tree.add_day()
        self.run_job(SUNSET + timedelta(days=5))
        self.assertEqual(self.encoded, [])

    def test_failed_encode_writes_no_record_so_the_next_run_retries(self):
        self.tree.add_day()

        def broken(*a):
            raise daily.EncodeError("disk full")
        rc = daily.run(self.tree.config(), self.NOW, encode=broken,
                       frame_size=lambda path: (4056, 3040), check_image=lambda *a: None)
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.tree.daily, "2026-12-21.json")))
        self.assertEqual(self.run_job(), 0)
        self.assertEqual(self.tree.record("2026-12-21")["status"], "encoded")

    def test_failed_check_image_does_not_lose_the_day(self):
        self.tree.add_day()

        def broken(*a):
            raise daily.EncodeError("no check image")

        def fake_encode(cfg, frames, sunset_frame, crop, mask, out):
            open(out, "wb").close()
        rc = daily.run(self.tree.config(), self.NOW, encode=fake_encode,
                       frame_size=lambda path: (4056, 3040), check_image=broken)
        self.assertEqual(rc, 0)
        self.assertEqual(self.tree.record("2026-12-21")["status"], "encoded")

    def test_another_run_in_progress_means_nothing_happens(self):
        self.tree.add_day()
        os.makedirs(self.tree.daily)
        open(os.path.join(self.tree.daily, ".lock"), "w").close()
        self.assertEqual(self.run_job(), 0)
        self.assertEqual(self.encoded, [])

    def test_lock_left_by_a_crashed_run_expires(self):
        self.tree.add_day()
        os.makedirs(self.tree.daily)
        lock = os.path.join(self.tree.daily, ".lock")
        open(lock, "w").close()
        old = time.time() - 7 * 3600
        os.utime(lock, (old, old))
        self.run_job()
        self.assertEqual(len(self.encoded), 1)

    def test_lock_is_released_afterwards(self):
        self.tree.add_day()
        self.run_job()
        self.assertFalse(os.path.exists(os.path.join(self.tree.daily, ".lock")))

    def write_crop(self, **cfg):
        with open(self.tree.crop_file, "w") as f:
            json.dump(cfg, f)

    def test_no_calibration_yet_uses_the_fixed_crop_and_still_records_the_azimuth(self):
        self.tree.add_day()
        self.run_job()
        crop = self.tree.record("2026-12-21")["crop"]
        self.assertEqual((crop["source"], crop["x"]), ("fixed", 1173))
        # add_day gives every frame 250.0, so any interpolation between them is 250.0
        self.assertEqual(crop["azimuth_deg"], 250.0)
        self.assertEqual(crop["azimuth_method"], "interpolated")

    def test_calibration_moves_the_crop(self):
        self.write_crop(calibrations=[{"start": "2026-12-01", "cx": 2028, "fits": [
            {"date": "2026-12-10", "f_px": 2000.0, "az0_deg": 250.0}]}], offset_px=50)
        self.tree.add_day()
        self.run_job()
        crop = self.tree.record("2026-12-21")["crop"]
        # On the axis: sun at 2028, plus the 50 px offset, minus 855.
        self.assertEqual((crop["source"], crop["sun_x"], crop["x"]), ("azimuth", 2028, 1223))

    def test_missing_sun_data_falls_back_to_yesterdays_crop(self):
        self.write_crop(calibrations=[{"start": "2026-12-01", "cx": 2028, "fits": [
            {"date": "2026-12-10", "f_px": 2000.0, "az0_deg": 250.0}]}])
        os.makedirs(self.tree.daily)
        with open(os.path.join(self.tree.daily, "2026-12-20.json"), "w") as f:
            json.dump({"status": "encoded", "crop": {"center_x": 2600, "azimuth_deg": 249.5}}, f)
        last = SUNSET + timedelta(minutes=30)
        for i in range(96):
            t = last - timedelta(minutes=15 * i)
            near = abs((t - SUNSET).total_seconds()) < 3 * 3600
            self.tree.add(t, SUNSET, write_json=not near)
        # Too far from sunset to give an azimuth, but it still shows the sunset has passed.
        self.tree.add(SUNSET + timedelta(minutes=90), SUNSET)
        self.run_job(SUNSET + timedelta(hours=2))
        crop = self.tree.record("2026-12-21")["crop"]
        self.assertEqual((crop["source"], crop["center_x"]), ("previous_day", 2600))

    def test_broken_crop_file_stops_rather_than_quietly_using_the_wrong_crop(self):
        with open(self.tree.crop_file, "w") as f:
            f.write("{ cut off")
        self.tree.add_day()
        self.assertEqual(self.run_job(), 1)
        self.assertEqual(self.encoded, [])
        self.assertFalse(os.path.exists(os.path.join(self.tree.daily, ".lock")))

    def test_big_jump_from_yesterday_flags_the_day_but_keeps_the_crop(self):
        self.write_crop(calibrations=[{"start": "2026-12-01", "cx": 2028, "fits": [
            {"date": "2026-12-10", "f_px": 2000.0, "az0_deg": 250.0}]}])
        os.makedirs(self.tree.daily)
        with open(os.path.join(self.tree.daily, "2026-12-20.json"), "w") as f:
            json.dump({"status": "encoded", "crop": {"center_x": 2000, "azimuth_deg": 248.0}}, f)
        self.tree.add_day()
        self.run_job()
        crop = self.tree.record("2026-12-21")["crop"]
        self.assertTrue(crop["azimuth_step_flag"])
        self.assertEqual(crop["sun_x"], 2028)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class RealEncoding(unittest.TestCase):
    """The real ffmpeg, against what the issue says Instagram needs."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.white = os.path.join(cls.dir, "white.jpg")
        make_image(cls.white)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, True)

    def frames(self, count=96):
        tree = Tree(self, self.white)
        tree.add_day(count)
        return tree

    def run_real(self, tree, **over):
        return daily.run(tree.config(**over), SUNSET + timedelta(hours=1))

    def test_video_meets_the_reel_format(self):
        tree = self.frames()
        self.assertEqual(self.run_real(tree), 0)
        path = os.path.join(tree.daily, tree.record()["video"])
        info = probe(path)
        video = [s for s in info["streams"] if s["codec_type"] == "video"]
        self.assertEqual(len(video), 1)
        v = video[0]
        self.assertEqual((v["codec_name"], v["pix_fmt"], v["width"], v["height"], v["r_frame_rate"]),
                         ("h264", "yuv420p", 1080, 1920, "24/1"))
        # 96 frames at 12 per second is 8 s, plus the 1.5 s hold.
        self.assertAlmostEqual(float(info["format"]["duration"]), 9.5, delta=0.2)
        with open(path, "rb") as f:
            data = f.read()
        self.assertLess(data.index(b"moov"), data.index(b"mdat"), "moov atom must come first")

    def test_no_temporary_files_are_left_behind(self):
        tree = self.frames(68)
        self.run_real(tree)
        names = sorted(n for n in os.listdir(tree.daily) if not n.endswith((".json", ".mp4", ".jpg", ".txt")))
        self.assertEqual(names, [])
        self.assertEqual(sorted(os.listdir(tree.daily)),
                         ["2026-12-21.json", "2026-12-21.mp4", "2026-12-21.txt", "2026-12-21_check.jpg"])

    def test_broken_ffmpeg_keeps_no_video_and_no_record(self):
        tree = self.frames(68)
        rc = self.run_real(tree, ffmpeg="ffmpeg-that-does-not-exist")
        self.assertEqual(rc, 1)
        self.assertEqual(os.listdir(tree.daily), [])

    def mask_row(self, center_x):
        """Run with a mask at full-frame x 400-499 and return the row from the middle of the video."""
        tree = self.frames(68)
        with open(tree.crop_file, "w") as f:
            json.dump({"mask": [[400, 0, 100, 480]]}, f)
        self.assertEqual(self.run_real(tree, crop_center_x=center_x), 0)
        return gray_row(os.path.join(tree.daily, tree.record()["video"]), 960, seek=1)

    def test_mask_follows_the_scene_at_the_right_hand_crop(self):
        # 640x480 crops to 270 wide, scaled by 4. Centre 505 clamps to x=370, so the mask
        # lands at crop x 30-129, video x 120-519.
        row = self.mask_row(505)
        self.assertLess(row[320], 50, "inside the mask should be black")
        self.assertGreater(row[800], 150, "outside the mask should be white")

    def test_mask_stays_put_when_the_crop_is_at_the_other_extreme(self):
        # Centre 135 is x=0, which ends at 270: the mask at 400 is out of the crop. A mask
        # applied after the crop would be out of the picture in both cases.
        row = self.mask_row(135)
        self.assertGreater(min(row[50], row[320], row[1000]), 150)

    def test_check_image_draws_the_crop_on_the_full_frame(self):
        tree = self.frames(68)
        self.run_real(tree)
        path = os.path.join(tree.daily, "2026-12-21_check.jpg")
        info = probe(path)["streams"][0]
        self.assertEqual(info["width"], 1000)
        row = gray_row(path, info["height"] // 2, width=1000)
        # Centred crop of a 640 frame is x 185-455, or 289-711 at this width.
        self.assertLess(min(row[285:295]), 200, "left edge of the crop should be drawn")
        self.assertLess(min(row[705:716]), 200, "right edge of the crop should be drawn")
        self.assertGreater(row[500], 230, "inside of the crop should stay clear")


class CommandLine(unittest.TestCase):
    def test_runs_from_environment_settings(self):
        real_tz()
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg not installed")
        image_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, image_dir, True)
        image = os.path.join(image_dir, "white.jpg")
        make_image(image)
        tree = Tree(self, image)
        sunset = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0)
        tree.add_day(68, sunset=sunset)
        env = dict(os.environ, FRAMES_DIR=tree.frames, DAILY_DIR=tree.daily, CROP_FILE=tree.crop_file,
                   SITE_TZ="America/Vancouver", START_DATE="2026-12-21")
        got = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(len([n for n in os.listdir(tree.daily) if n.endswith(".mp4")]), 1)

    def test_missing_settings_is_a_clear_error(self):
        env = {k: v for k, v in os.environ.items() if k not in ("FRAMES_DIR", "DAILY_DIR")}
        got = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True)
        self.assertEqual(got.returncode, 2)
        self.assertIn("FRAMES_DIR", got.stderr)


if __name__ == "__main__":
    unittest.main()
