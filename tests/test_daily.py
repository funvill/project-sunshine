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
FONT_CANDIDATES = (daily.DEFAULT_FONT_FILE, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                   "C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf")
TEST_FONT = next((f for f in FONT_CANDIDATES if os.path.exists(f)), None)
FAKE_JPEG = b"\xff\xd8\xff\xd9"   # start and end markers only: passes the job's check, never decoded


def real_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Vancouver")
    except Exception:
        raise unittest.SkipTest("no time zone database on this machine")


def stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fake_elevation(minutes):
    """Fake days go dark exactly 30 minutes after sunset."""
    return daily.DARK_ELEVATION_DEG if minutes >= 30 else -1.0


def frame_at(minutes, az=None, sunset=SUNSET, elevation=None):
    """A Frame the way list_frames builds it, `minutes` after `sunset`."""
    t = sunset + timedelta(minutes=minutes)
    sun = {"azimuth_deg": 250.0 if az is None else az,
           "elevation_deg": fake_elevation(minutes) if elevation is None else elevation,
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

    def add(self, t, sunset=SUNSET, write_json=True, az=250.0, name_suffix="", schedule="regular",
            setup_id=None, image=None):
        """schedule None leaves out the Capture block, as on frames from before 2026-11-04."""
        folder = os.path.join(self.frames, t.strftime("%Y"), t.strftime("%m"), t.strftime("%d"))
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, "wide_%s%s" % (t.strftime("%Y%m%dT%H%M%SZ"), name_suffix))
        if image or self.image:
            shutil.copyfile(image or self.image, base + ".jpg")
        else:
            with open(base + ".jpg", "wb") as f:
                f.write(FAKE_JPEG)
        if write_json:
            minutes = (t - sunset).total_seconds() / 60.0
            data = {"ExposureTime": 1000, "Lux": 400.0,
                    "Sun": {"azimuth_deg": az, "elevation_deg": fake_elevation(minutes),
                            "azimuth_ref": "true_north",
                            "computed_for_utc": stamp(t),
                            "nearest_sunset_utc": stamp(sunset),
                            "minutes_from_sunset": round(minutes, 1)}}
            if schedule is not None:
                data["Capture"] = {"schema_version": 1, "camera": "wide", "kind": "day", "schedule": schedule}
                if setup_id:
                    data["Capture"]["setup_id"] = setup_id
            with open(base + ".json", "w") as f:
                json.dump(data, f)
        return base

    def add_day(self, count=96, sunset=SUNSET):
        """`count` frames, 15 minutes apart, the last one exactly 30 minutes after sunset."""
        last = sunset + timedelta(minutes=30)
        for i in range(count):
            self.add(last - timedelta(minutes=15 * i), sunset)

    def config(self, **over):
        values = dict(frames_dir=self.frames, daily_dir=self.daily, crop_file=self.crop_file,
                      tz=PST, start_date=datetime(2026, 12, 21).date(), font_file=TEST_FONT,
                      expected_frames=96)   # the fake frames are 15 minutes apart
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
    def test_dark_frame_after_sunset_makes_it_due(self):
        self.assertEqual(daily.due_sunsets([frame_at(60, elevation=-9.0)]), [SUNSET])

    def test_frame_not_yet_dark_does_not(self):
        self.assertEqual(daily.due_sunsets([frame_at(60, elevation=-8.99)]), [])

    def test_dark_frame_before_that_sunset_does_not(self):
        # The small hours are dark too, but they lead up to this sunset.
        self.assertEqual(daily.due_sunsets([frame_at(-200, elevation=-40.0)]), [])

    def test_frame_with_no_sun_block_does_not(self):
        self.assertEqual(daily.due_sunsets([daily.Frame(SUNSET, "x.jpg", None)]), [])

    def test_frame_with_no_elevation_does_not(self):
        frame = frame_at(60)
        del frame.sun["elevation_deg"]
        self.assertEqual(daily.due_sunsets([frame]), [])

    def test_two_sunsets_come_back_oldest_first(self):
        later = SUNSET + timedelta(days=1)
        self.assertEqual(daily.due_sunsets([frame_at(40, sunset=later), frame_at(40)]), [SUNSET, later])


class DayEnd(unittest.TestCase):
    def test_is_the_first_dark_frame_after_sunset(self):
        frames = [frame_at(-200, elevation=-40.0), frame_at(30, elevation=-6.0),
                  frame_at(45, elevation=-9.0), frame_at(60, elevation=-12.0)]
        self.assertEqual(daily.day_end(frames, SUNSET), SUNSET + timedelta(minutes=45))

    def test_ignores_the_dark_frames_of_another_sunset(self):
        later = SUNSET + timedelta(days=1)
        frames = [frame_at(45, elevation=-9.0, sunset=later)]
        self.assertIsNone(daily.day_end(frames, SUNSET))


class Window(unittest.TestCase):
    def test_runs_from_just_after_start_up_to_and_including_end(self):
        start, end = SUNSET - timedelta(hours=24), SUNSET
        frames = [daily.Frame(start, "start", None),
                  daily.Frame(start + timedelta(minutes=15), "inside-first", None),
                  daily.Frame(end, "inside-last", None),
                  daily.Frame(end + timedelta(minutes=15), "after", None)]
        self.assertEqual([f.jpg for f in daily.select_window(frames, start, end)],
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


class SkyScoreMaths(unittest.TestCase):
    WARM, GREY, DARK = (200, 100, 50), (120, 120, 120), (30, 15, 5)

    def rows(self, *pixels):
        """A picture two pixels wide, one row per colour given."""
        return b"".join(bytes(p) * 2 for p in pixels)

    def test_warm_fraction_counts_bright_pixels_with_red_well_above_blue(self):
        data = self.rows(self.WARM, self.GREY, self.DARK, self.WARM)
        self.assertEqual(daily.warm_fraction(data, 2, 1.0), 0.5, "grey and near-black are not warm")

    def test_only_the_top_rows_count_as_sky(self):
        data = self.rows(self.WARM, self.WARM, self.GREY, self.GREY)
        self.assertEqual(daily.warm_fraction(data, 2, 0.5), 1.0)
        self.assertEqual(daily.warm_fraction(data, 2, 1.0), 0.5)

    def test_score_is_percent_of_the_full_score_warm_share_and_stops_at_100(self):
        full = daily.SKY_FULL_SCORE_WARM
        self.assertEqual(daily.sky_score_value(0.0), 0)
        self.assertEqual(daily.sky_score_value(full / 2), 50)
        self.assertEqual(daily.sky_score_value(full), 100)
        self.assertEqual(daily.sky_score_value(0.9), 100)

    def test_a_camera_can_have_its_own_full_score_share(self):
        self.assertEqual(daily.sky_score_value(0.05, 0.2), 25)

    def test_labels_are_three_bands(self):
        self.assertEqual([daily.sky_label(v) for v in (0, 19, 20, 59, 60, 100)],
                         ["grey", "grey", "some colour", "some colour", "colourful", "colourful"])


class SkyScoreRobust(unittest.TestCase):
    """The day's score from several frames, not one; a minimum number of frames; the crop's columns."""
    W, H = daily.SKY_SIZE

    def picture(self, warm_share, left_only=False):
        """A SKY_SIZE picture whose sky rows are warm for this share of their width, from the left."""
        warm, grey = bytes((200, 100, 50)), bytes((120, 120, 120))
        cut = int(round(self.W * warm_share)) if not left_only else self.W // 2
        row = warm * cut + grey * (self.W - cut)
        return row * self.H

    def score(self, shares, crop=None, frame_w=None, **kw):
        window = [daily.Frame(SUNSET + timedelta(minutes=i - len(shares) // 2), "f%d.jpg" % i, None)
                  for i in range(len(shares))]
        pictures = {"f%d.jpg" % i: (s if isinstance(s, bytes) else self.picture(s)) for i, s in enumerate(shares)}
        return daily.sky_score(None, window, SUNSET, rows=1.0, full=1.0, crop=crop, frame_w=frame_w,
                               read_pixels=lambda cfg, path: pictures[path], **kw)

    def test_one_bright_outlier_frame_does_not_set_the_score(self):
        # Before: the best frame alone, 90. Now: the mean of the best five, (0.9 + 4 x 0.1) / 5 = 0.26.
        sky = self.score([0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0])
        self.assertEqual(sky["score"], 26)
        self.assertEqual(sky["score_best_frame"], 90, "the old one-frame score is kept beside it")
        self.assertEqual(sky["warm_sky_percent"], 90.0, "and so is the best frame's share")
        self.assertEqual(sky["frames_scored"], 8)
        self.assertEqual(sky["top_frames"], 5)

    def test_under_the_minimum_number_of_frames_there_is_no_score(self):
        self.assertIsNone(self.score([0.5] * (daily.SKY_MIN_FRAMES - 1)))
        self.assertIsNotNone(self.score([0.5] * daily.SKY_MIN_FRAMES))

    def test_the_minimum_can_be_changed(self):
        self.assertIsNotNone(self.score([0.5, 0.5], min_frames=2))

    def test_crop_columns_are_scored_beside_the_full_width(self):
        # Warm on the left half only; the crop is the right half of a 1600 px frame.
        half = self.picture(0, left_only=True)
        sky = self.score([half] * 6, crop={"x": 800, "width": 800}, frame_w=1600)
        self.assertEqual(sky["score"], 50, "half the full width is warm")
        self.assertEqual(sky["crop"]["score"], 0, "none of the crop is")
        self.assertEqual(sky["crop"]["columns"], [80, 160])

    def test_no_crop_given_means_no_crop_score(self):
        self.assertNotIn("crop", self.score([0.5] * 6))


class JpegCheck(unittest.TestCase):
    def write(self, data):
        fd, path = tempfile.mkstemp(suffix=".jpg")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        self.addCleanup(os.remove, path)
        return path

    def test_a_whole_jpeg_passes(self):
        self.assertTrue(daily.jpeg_ok(self.write(b"\xff\xd8" + b"\x00" * 100 + b"\xff\xd9")))

    def test_empty_truncated_missing_and_not_a_jpeg_fail(self):
        self.assertFalse(daily.jpeg_ok(self.write(b"")))
        self.assertFalse(daily.jpeg_ok(self.write(b"\xff\xd8" + b"\x00" * 100)), "cut off before its end marker")
        self.assertFalse(daily.jpeg_ok(self.write(b"\x89PNG\r\n\x1a\n\xff\xd9")))
        self.assertFalse(daily.jpeg_ok(os.path.join(tempfile.gettempdir(), "no-such-frame.jpg")))


class RegularFrames(unittest.TestCase):
    def test_the_capture_block_says_which_are_dense(self):
        t = datetime(2026, 12, 22, 0, 3, tzinfo=UTC)
        self.assertFalse(daily.is_regular(daily.Frame(t, "x.jpg", None, None, {"schedule": "dense"})))
        self.assertTrue(daily.is_regular(daily.Frame(t, "x.jpg", None, None, {"schedule": "regular"})))

    def test_without_a_capture_block_the_minute_decides(self):
        # The 5-minute timer fires on the minute (OnCalendar=*:00/5) and the slot always wins the camera.
        on_slot = datetime(2026, 11, 3, 4, 15, 2, tzinfo=UTC)
        between = datetime(2026, 11, 3, 4, 16, 0, tzinfo=UTC)
        self.assertTrue(daily.is_regular(daily.Frame(on_slot, "x.jpg", None)))
        self.assertFalse(daily.is_regular(daily.Frame(between, "x.jpg", None)))
        self.assertTrue(daily.is_regular(daily.Frame(on_slot, "x.jpg", None, None, {"camera": "wide"})),
                        "a Capture block with no schedule falls back too")


class Gaps(unittest.TestCase):
    def test_largest_gap_is_between_frames_and_says_where(self):
        start = SUNSET - timedelta(hours=2)
        times = [start + timedelta(minutes=m) for m in (35, 40, 80, 85)]   # a late start is not a gap
        got = daily.frame_gaps(times, SUNSET, SUNSET + timedelta(minutes=60))
        self.assertEqual(got["largest_gap_min"], 40.0)
        self.assertEqual(got["largest_gap_at_utc"], stamp(start + timedelta(minutes=40)))

    def test_sunset_gap_only_counts_gaps_that_touch_the_sunset_window(self):
        start = SUNSET - timedelta(hours=3)
        # A 50-minute gap early in the afternoon, then 1-minute frames from 61 minutes before sunset.
        times = [start + timedelta(minutes=m) for m in (5, 55)]
        times += [SUNSET + timedelta(minutes=m) for m in range(-62, 31)]
        got = daily.frame_gaps(times, SUNSET, SUNSET + timedelta(minutes=30))
        self.assertEqual(got["largest_gap_min"], 63.0, "from 125 to 62 min before sunset")
        self.assertEqual(got["largest_sunset_gap_min"], 1.0, "it ends before the hour before sunset")
        moved = [t for t in times if not SUNSET - timedelta(minutes=63) < t < SUNSET - timedelta(minutes=59)]
        got = daily.frame_gaps(moved, SUNSET, SUNSET + timedelta(minutes=30))
        self.assertEqual(got["largest_sunset_gap_min"], 66.0, "now it reaches into that hour")

    def test_a_short_gap_at_sunset(self):
        start = SUNSET - timedelta(minutes=70)
        times = [SUNSET + timedelta(minutes=m) for m in range(-69, 31) if not -5 < m < 5]
        got = daily.frame_gaps(times, SUNSET, SUNSET + timedelta(minutes=30))
        self.assertEqual((got["largest_gap_min"], got["largest_sunset_gap_min"]), (10.0, 10.0))


class DaySettings(unittest.TestCase):
    DAY = datetime(2026, 11, 20).date()

    def test_settings_inside_the_calibration_in_force_win(self):
        cfg = {"blur": [[1, 2, 3, 4]], "view": {"top": 0, "height": 100}, "sky_full_warm": 0.1,
               "calibrations": [
                   {"start": "2026-11-01", "setup_id": "a", "blur": [[5, 6, 7, 8]], "cx": 1, "fits": []},
                   {"start": "2026-11-15", "setup_id": "b", "blur": [[9, 9, 9, 9]], "sky_full_warm": 0.2,
                    "cx": 1, "fits": []}]}
        got = daily.day_settings(cfg, self.DAY)
        self.assertEqual(got["setup_id"], "b")
        self.assertEqual(got["blur"], [[9, 9, 9, 9]])
        self.assertEqual(got["sky_full_warm"], 0.2)
        self.assertEqual(got["view"], {"top": 0, "height": 100}, "a key the entry lacks comes from the top level")
        old = daily.day_settings(cfg, datetime(2026, 11, 10).date())
        self.assertEqual((old["setup_id"], old["blur"]), ("a", [[5, 6, 7, 8]]), "rebuilding an old day")

    def test_top_level_only_configs_keep_working(self):
        cfg = {"blur": [[1, 2, 3, 4]], "mask": [[0, 0, 1, 1]], "offset_px": 7}
        got = daily.day_settings(cfg, self.DAY)
        self.assertEqual((got["blur"], got["mask"], got["offset_px"], got["setup_id"]),
                         ([[1, 2, 3, 4]], [[0, 0, 1, 1]], 7, None))

    def test_defaults_when_nothing_is_set(self):
        got = daily.day_settings({}, self.DAY)
        self.assertEqual((got["mask"], got["offset_px"], got["view"], got["blur"]), ([], 0, None, None))
        self.assertEqual((got["sky_rows"], got["sky_full_warm"]), (daily.SKY_ROWS, daily.SKY_FULL_SCORE_WARM))

    def test_the_checked_in_cm4wide_config_has_its_settings_inside_the_calibration(self):
        with open(os.path.join(os.path.dirname(HERE), "nas", "crop.cm4wide.json")) as f:
            cfg = json.load(f)
        for key in ("blur", "view", "mask", "sky_full_warm", "blur_sigma"):
            self.assertNotIn(key, cfg, "%s now lives in the calibration entry" % key)
        got = daily.day_settings(cfg, datetime(2026, 11, 12).date())
        self.assertEqual(got["setup_id"], "cm4-window-1")
        self.assertEqual(got["view"], {"top": 100, "height": 2440})
        self.assertEqual(got["sky_full_warm"], 0.178)
        self.assertEqual(len(got["blur"]), 7)
        self.assertEqual(daily.active_calibration(cfg, datetime(2026, 11, 12).date())["f_px"], 1880.0)


class CropView(unittest.TestCase):
    CAL = {"cx": 2028, "f_px": 1000.0, "az0_deg": 270.0}
    VIEW = {"top": 100, "height": 1600}

    def crop(self, view, w=4056, h=3040):
        return daily.crop_for_day(w, h, 270.0, self.CAL, None, 0, None, view=view)

    def test_no_view_is_the_full_height_from_the_top(self):
        got = self.crop(None)
        self.assertEqual((got["y"], got["height"], got["width"]), (0, 3040, 1710))

    def test_a_view_is_a_shorter_window_of_the_same_9_by_16_shape(self):
        got = self.crop(self.VIEW)
        self.assertEqual((got["y"], got["height"], got["width"]), (100, 1600, 900))
        self.assertEqual(got["x"], 2028 - 450, "still centred on the sun")

    def test_a_view_is_kept_inside_the_frame(self):
        self.assertEqual(self.crop({"top": 2800, "height": 1600})["y"], 1440)
        self.assertEqual(self.crop({"top": -50, "height": 1600})["y"], 0)

    def test_a_view_taller_than_the_frame_is_the_full_height(self):
        self.assertEqual(self.crop({"top": 0, "height": 5000})["height"], 3040)

    def test_the_window_stays_even_for_yuv420p(self):
        self.assertEqual(self.crop({"top": 0, "height": 1601})["width"] % 2, 0)


class ViewLabel(unittest.TestCase):
    def test_compass_names_cover_the_circle_in_16_points(self):
        got = [daily.compass_name(a) for a in (0, 22.5, 90, 180, 233.7, 243, 270, 292.5, 308.8, 359.9)]
        self.assertEqual(got, ["N", "NNE", "E", "S", "SW", "WSW", "W", "WNW", "NW", "N"])

    def test_label_is_the_name_and_whole_degrees(self):
        self.assertEqual(daily.view_label(242.97), "WSW 243°")
        self.assertEqual(daily.view_label(270.0), "W 270°")

    def test_negative_and_over_360_wrap(self):
        self.assertEqual(daily.view_label(-90), "W 270°")
        self.assertEqual(daily.view_label(360.2), "N 0°")


class CenterAzimuth(unittest.TestCase):
    CAL = {"cx": 2028, "f_px": 2000.0, "az0_deg": 250.0}

    def test_crop_centred_on_the_axis_looks_at_az0(self):
        self.assertEqual(daily.center_azimuth({"center_x": 2028}, self.CAL, 243.0), 250.0)

    def test_crop_off_the_axis_uses_the_lens_model(self):
        # tan(az - 250) = 2000 / 2000 -> 45 degrees either side of the axis
        self.assertAlmostEqual(daily.center_azimuth({"center_x": 4028}, self.CAL, 243.0), 295.0, places=4)
        self.assertAlmostEqual(daily.center_azimuth({"center_x": 28}, self.CAL, 243.0), 205.0, places=4)

    def test_with_no_calibration_it_is_the_sunset_azimuth(self):
        self.assertEqual(daily.center_azimuth({"center_x": 1450}, None, 243.0), 243.0)

    def test_with_nothing_it_is_unknown(self):
        self.assertIsNone(daily.center_azimuth({"center_x": 1450}, None, None))


class StartTime(unittest.TestCase):
    def test_local_clock_time_becomes_utc(self):
        self.assertEqual(daily.local_start(datetime(2026, 12, 21).date(), "07:30", PST),
                         datetime(2026, 12, 21, 15, 30, tzinfo=UTC))

    def test_bad_values_are_refused(self):
        for bad in ("7", "25:00", "07:61", "morning"):
            with self.assertRaises(ValueError):
                daily.local_start(datetime(2026, 12, 21).date(), bad, PST)


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


class OverlayTime(unittest.TestCase):
    def test_is_year_short_month_day_and_24_hour_local_time(self):
        self.assertEqual(daily.overlay_time(SUNSET, PST), "2026-Dec-21 16:14")

    def test_frame_after_midnight_utc_keeps_its_local_date(self):
        self.assertEqual(daily.overlay_time(datetime(2026, 12, 22, 7, 30, tzinfo=UTC), PST), "2026-Dec-21 23:30")

    def test_summer_frame_uses_daylight_time(self):
        self.assertEqual(daily.overlay_time(datetime(2027, 6, 22, 4, 22, tzinfo=UTC), real_tz()),
                         "2027-Jun-21 21:22")

    def test_seconds_are_dropped_not_rounded(self):
        self.assertEqual(daily.overlay_time(datetime(2026, 11, 5, 6, 5, 34, tzinfo=UTC), PST), "2026-Nov-04 22:05")


class ConcatList(unittest.TestCase):
    def test_shows_every_frame_a_twelfth_of_a_second_with_no_hold(self):
        frames = [daily.Frame(SUNSET, "/a/one.jpg", None), daily.Frame(SUNSET, "/a/two.jpg", None),
                  daily.Frame(SUNSET, "/a/three.jpg", None)]
        lines = daily.concat_list(frames).splitlines()
        self.assertEqual(lines, ["file '/a/one.jpg'", "duration 0.083333",
                                 "file '/a/two.jpg'", "duration 0.083333",
                                 "file '/a/three.jpg'", "duration 0.083333",
                                 "file '/a/three.jpg'"])

    def test_quote_in_a_path_is_escaped(self):
        f = daily.Frame(SUNSET, "/a/it's.jpg", None)
        self.assertIn(r"file '/a/it'\''s.jpg'", daily.concat_list([f]))


class RunWithoutEncoding(unittest.TestCase):
    """The decisions run() makes, with a stand-in encoder (ffmpeg is tested below)."""
    NOW = SUNSET + timedelta(hours=1)

    def setUp(self):
        self.tree = Tree(self)
        self.encoded = []

    def run_job(self, now=NOW, **over):
        def fake_encode(cfg, frames, crop, mask, out):
            self.encoded.append((out, len(frames), [f.time for f in frames]))
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

    def test_one_minute_frames_around_sunset_all_go_in(self):
        # The Pi adds 1-a-minute frames near sunset on top of the 15-minute ones.
        self.tree.add_day()
        for m in range(-60, 31):
            if m % 15:
                self.tree.add(SUNSET + timedelta(minutes=m), schedule="dense")
        self.assertEqual(self.run_job(), 0)
        times = self.encoded[0][2]
        self.assertEqual(len(times), 96 + 91 - 7)
        self.assertEqual(times, sorted(times))
        self.assertEqual(self.tree.record()["sunset_frame"], "wide_20261222T001400Z.jpg")
        self.assertEqual(times[-1], SUNSET + timedelta(minutes=30), "it still ends on the first dark frame")

    def remove(self, t):
        base = os.path.join(self.tree.frames, t.strftime("%Y"), t.strftime("%m"), t.strftime("%d"),
                            "wide_%s" % t.strftime("%Y%m%dT%H%M%SZ"))
        os.remove(base + ".jpg")
        os.remove(base + ".json")

    def test_an_unreadable_frame_is_left_out_and_counted(self):
        self.tree.add_day()
        empty = SUNSET - timedelta(hours=4)   # 20:14 UTC, one of the 15-minute frames
        base = os.path.join(self.tree.frames, "2026", "12", "21", "wide_%s" % empty.strftime("%Y%m%dT%H%M%SZ"))
        open(base + ".jpg", "wb").close()
        cut = SUNSET - timedelta(hours=2)
        base = os.path.join(self.tree.frames, "2026", "12", "21", "wide_%s" % cut.strftime("%Y%m%dT%H%M%SZ"))
        with open(base + ".jpg", "wb") as f:
            f.write(b"\xff\xd8" + b"\x00" * 50)   # cut off: no end marker
        self.assertEqual(self.run_job(), 0)
        self.assertEqual(self.encoded[0][1], 94)
        self.assertNotIn(empty, self.encoded[0][2])
        rec = self.tree.record()
        self.assertEqual((rec["status"], rec["frames"], rec["dropped_frames"]), ("encoded", 94, 2))
        self.assertEqual(rec["dropped"], ["wide_20261221T201400Z.jpg", "wide_20261221T221400Z.jpg"])

    def test_a_bad_fused_frame_falls_back_to_the_original(self):
        self.tree.add_day()
        fused_dir = os.path.join(self.tree.dir, "fused")
        os.makedirs(fused_dir)
        name = "wide_%s.jpg" % (SUNSET - timedelta(minutes=15)).strftime("%Y%m%dT%H%M%SZ")
        open(os.path.join(fused_dir, name), "wb").close()
        self.run_job(fused_dir=fused_dir)
        rec = self.tree.record()
        self.assertEqual((rec["frames"], rec["dropped_frames"]), (96, 0))

    def test_dense_frames_do_not_hide_missing_regular_frames(self):
        # A 9-hour outage loses 36 of the 96 regular frames; 1-minute frames near sunset add 84,
        # so all frames together (144) would have passed the old check.
        self.tree.add_day()
        for i in range(36):
            self.remove(SUNSET - timedelta(hours=3) - timedelta(minutes=15 * i))
        for m in range(-60, 31):
            if m % 15:
                self.tree.add(SUNSET + timedelta(minutes=m), schedule="dense")
        self.run_job()
        self.assertEqual(self.encoded, [])
        rec = self.tree.record()
        self.assertEqual(rec["status"], "skipped")
        self.assertIn("60 of 96 expected regular frames", rec["reason"])
        self.assertEqual((rec["regular_frames"], rec["dense_frames"]), (60, 84))

    def test_frames_with_no_capture_block_count_as_regular_on_a_5_minute_slot(self):
        # Old frames (before 2026-11-04) have no Capture block; their file name's minute decides.
        last = SUNSET + timedelta(minutes=31)   # 00:45, a 5-minute slot
        for i in range(96):
            self.tree.add(last - timedelta(minutes=15 * i), schedule=None)
        self.run_job()
        rec = self.tree.record()
        self.assertEqual((rec["status"], rec["regular_frames"]), ("encoded", 96))

    def test_the_record_keeps_the_largest_gap(self):
        self.tree.add_day()
        self.run_job()
        rec = self.tree.record()
        self.assertEqual((rec["largest_gap_min"], rec["largest_sunset_gap_min"]), (15.0, 15.0))

    def test_a_long_gap_skips_the_day_even_with_enough_frames(self):
        self.tree.add_day()
        for i in range(5):   # 5 frames lost: 90 minutes from one frame to the next
            self.remove(SUNSET - timedelta(hours=6) - timedelta(minutes=15 * i))
        self.run_job()
        self.assertEqual(self.encoded, [])
        rec = self.tree.record()
        self.assertEqual((rec["status"], rec["largest_gap_min"]), ("skipped", 90.0))
        self.assertIn("90", rec["reason"])

    def test_the_gap_limit_can_be_raised(self):
        self.tree.add_day()
        for i in range(5):
            self.remove(SUNSET - timedelta(hours=6) - timedelta(minutes=15 * i))
        self.run_job(max_gap_min=120)
        self.assertEqual(self.tree.record()["status"], "encoded")

    def test_a_shorter_gap_at_sunset_also_skips(self):
        self.tree.add_day()
        self.remove(SUNSET - timedelta(minutes=15))
        self.remove(SUNSET)
        self.run_job()   # 45 minutes, -30 to +15: under the 60-minute day limit, over the sunset one
        rec = self.tree.record()
        self.assertEqual((rec["status"], rec["largest_sunset_gap_min"]), ("skipped", 45.0))
        self.assertIn("sunset", rec["reason"])

    def setup_record(self, frame_setup, config_setup):
        cal = {"start": "2026-12-01", "cx": 2028, "fits": [{"date": "2026-12-10", "f_px": 2000.0, "az0_deg": 250.0}]}
        if config_setup:
            cal["setup_id"] = config_setup
        self.write_crop(calibrations=[cal])
        last = SUNSET + timedelta(minutes=30)
        for i in range(96):
            self.tree.add(last - timedelta(minutes=15 * i), setup_id=frame_setup)
        self.run_job()
        return self.tree.record()

    def test_a_frame_from_another_camera_position_marks_the_day_do_not_post(self):
        rec = self.setup_record("pilot-4", "pilot-3")
        self.assertTrue(rec["setup_mismatch"])
        self.assertEqual((rec["setup_id_expected"], rec["setup_id_frame"]), ("pilot-3", "pilot-4"))
        self.assertFalse(rec["post_ok"])
        self.assertIn("setup_mismatch", rec["post_blockers"])
        self.assertEqual(rec["status"], "encoded", "the video is still made, to look at")

    def test_the_same_camera_position_is_not_a_mismatch(self):
        rec = self.setup_record("pilot-4", "pilot-4")
        self.assertFalse(rec["setup_mismatch"])
        self.assertNotIn("setup_mismatch", rec["post_blockers"])

    def test_no_setup_on_either_side_is_unknown_not_a_mismatch(self):
        self.assertIsNone(self.setup_record(None, "pilot-4")["setup_mismatch"])
        self.tree = Tree(self)
        self.assertIsNone(self.setup_record("pilot-4", None)["setup_mismatch"])

    def test_blur_inside_the_calibration_reaches_the_encoder(self):
        self.write_crop(blur=[[1, 1, 1, 1]], calibrations=[
            {"start": "2026-12-01", "cx": 2028, "blur": [[2, 2, 2, 2]], "blur_sigma": 3,
             "view": {"top": 100, "height": 1600},
             "fits": [{"date": "2026-12-10", "f_px": 2000.0, "az0_deg": 250.0}]}])
        self.tree.add_day()
        self.run_job()
        crop = self.tree.record()["crop"]
        self.assertEqual((crop["blur"], crop["blur_sigma"], crop["y"], crop["height"]), ([[2, 2, 2, 2]], 3, 100, 1600))

    def test_the_record_says_how_it_was_made(self):
        with open(self.tree.crop_file, "wb") as f:
            f.write(b'{"offset_px": 0}\n')
        self.tree.add_day()
        for m in (-10, -5, 5):
            self.tree.add(SUNSET + timedelta(minutes=m), schedule="dense")
        self.run_job()
        rec = self.tree.record()
        self.assertEqual(rec["schema_version"], daily.RECORD_SCHEMA_VERSION)
        p = rec["provenance"]
        self.assertEqual(p["script_version"], daily.SCRIPT_VERSION)
        import hashlib
        self.assertEqual(p["crop_config_sha256"], hashlib.sha256(b'{"offset_px": 0}\n').hexdigest())
        self.assertEqual(p["frames_by_kind"], {"regular": 96, "dense": 3, "fused": 0, "dropped": 0})
        if HAVE_FFMPEG:
            self.assertTrue(p["ffmpeg"].startswith("ffmpeg version"))

    def test_with_no_crop_file_the_hash_is_empty(self):
        self.tree.add_day()
        self.run_job()
        self.assertIsNone(self.tree.record()["provenance"]["crop_config_sha256"])

    def test_first_day_with_no_video_before_it_covers_24_hours(self):
        self.tree.add_day()
        self.run_job()
        rec = self.tree.record("2026-12-21")
        self.assertEqual(rec["start_utc"], "2026-12-21T00:44:00Z")
        self.assertEqual(rec["end_utc"], "2026-12-22T00:44:00Z")

    def test_starts_right_after_the_previous_video_ended(self):
        # The day before ended at 01:14 on the 21st, so this one starts at the 01:29 frame.
        os.makedirs(self.tree.daily)
        with open(os.path.join(self.tree.daily, "2026-12-20.json"), "w") as f:
            json.dump({"status": "encoded", "end_utc": "2026-12-21T01:14:00Z"}, f)
        self.tree.add_day()
        self.run_job()
        rec = self.tree.record("2026-12-21")
        self.assertEqual(self.encoded[0][2][0], datetime(2026, 12, 21, 1, 29, tzinfo=UTC))
        self.assertEqual(rec["start_utc"], "2026-12-21T01:14:00Z")
        self.assertEqual(rec["frames"], 94)
        self.assertEqual(rec["expected_frames"], 94)

    def test_by_default_a_day_with_a_third_of_its_five_minute_frames_is_skipped(self):
        # Capture is every 5 minutes (288 a day), so 96 frames means two thirds were lost.
        self.tree.add_day(96)
        cfg = dict(self.tree.config().__dict__)
        del cfg["expected_frames"]
        self.encoded = []
        daily.run(daily.Config(**cfg), self.NOW, encode=lambda *a: self.fail("encoded"),
                  frame_size=lambda path: (4056, 3040), check_image=lambda *a: None)
        rec = self.tree.record("2026-12-21")
        self.assertEqual(rec["status"], "skipped")
        self.assertEqual(rec["expected_frames"], 288)

    def test_a_skipped_day_still_says_where_it_ended(self):
        self.tree.add_day(10)
        self.run_job()
        rec = self.tree.record("2026-12-21")
        self.assertEqual(rec["status"], "skipped")
        self.assertEqual(rec["end_utc"], "2026-12-22T00:44:00Z")

    def test_consecutive_videos_neither_overlap_nor_leave_a_gap(self):
        # Dark comes 2 minutes later on day two, which moves its end to the next frame.
        second = SUNSET + timedelta(hours=24, minutes=2)
        t = SUNSET + timedelta(minutes=30) - timedelta(hours=24) + timedelta(minutes=15)
        while t <= second + timedelta(minutes=75):
            self.tree.add(t, SUNSET if t < SUNSET + timedelta(hours=12) else second)
            t += timedelta(minutes=15)
        self.run_job(second + timedelta(hours=2))
        first_times, second_times = self.encoded[0][2], self.encoded[1][2]
        self.assertEqual(len(first_times), 96)
        self.assertEqual(len(second_times), 97)
        self.assertEqual(second_times[0], first_times[-1] + timedelta(minutes=15))
        self.assertEqual(self.tree.record("2026-12-22")["expected_frames"], 97)

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

    def test_failed_encode_leaves_a_failed_record_and_the_next_run_retries_and_replaces_it(self):
        self.tree.add_day()

        def broken(*a):
            raise daily.EncodeError("disk full")
        rc = daily.run(self.tree.config(), self.NOW, encode=broken,
                       frame_size=lambda path: (4056, 3040), check_image=lambda *a: None)
        self.assertEqual(rc, 1)
        rec = self.tree.record("2026-12-21")
        self.assertEqual(rec["status"], "failed")
        self.assertIn("disk full", rec["error"])
        self.assertEqual(rec["attempts"], 1)
        self.assertEqual(rec["end_utc"], "2026-12-22T00:44:00Z", "where it ended is still known")
        self.assertFalse(rec["post_ok"])
        self.assertFalse(os.path.exists(os.path.join(self.tree.daily, "2026-12-21.mp4")))
        rc = daily.run(self.tree.config(), self.NOW + timedelta(minutes=30), encode=broken,
                       frame_size=lambda path: (4056, 3040), check_image=lambda *a: None)
        self.assertEqual(self.tree.record("2026-12-21")["attempts"], 2)
        self.assertEqual(self.run_job(self.NOW + timedelta(hours=1)), 0)
        rec = self.tree.record("2026-12-21")
        self.assertEqual(rec["status"], "encoded")
        self.assertNotIn("error", rec)

    def test_any_error_in_one_day_is_recorded_and_the_other_days_still_run(self):
        later = SUNSET + timedelta(days=1)
        self.tree.add_day(sunset=SUNSET)
        self.tree.add_day(sunset=later)
        sizes = {"calls": 0}

        def size(path):
            sizes["calls"] += 1
            if sizes["calls"] == 1:
                raise KeyError("streams")   # e.g. ffprobe gave JSON with no stream
            return (4056, 3040)

        def fake_encode(cfg, frames, crop, mask, out):
            open(out, "wb").close()
        rc = daily.run(self.tree.config(), later + timedelta(hours=1), encode=fake_encode,
                       frame_size=size, check_image=lambda *a: None)
        self.assertEqual(rc, 1)
        first = self.tree.record("2026-12-21")
        self.assertEqual(first["status"], "failed")
        self.assertIn("KeyError", first["error"])
        self.assertEqual(self.tree.record("2026-12-22")["status"], "encoded")

    def test_a_failed_day_older_than_the_lookback_is_not_retried(self):
        self.tree.add_day()
        os.makedirs(self.tree.daily)
        with open(os.path.join(self.tree.daily, "2026-12-21.json"), "w") as f:
            json.dump({"status": "failed", "error": "x", "attempts": 3}, f)
        self.run_job(SUNSET + timedelta(days=5))
        self.assertEqual(self.encoded, [])
        self.assertEqual(self.tree.record()["status"], "failed")

    def test_failed_check_image_does_not_lose_the_day(self):
        self.tree.add_day()

        def broken(*a):
            raise daily.EncodeError("no check image")

        def fake_encode(cfg, frames, crop, mask, out):
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

    def test_a_start_time_begins_the_video_at_that_local_time_and_ignores_the_day_before(self):
        # 07:30 PST on the 21st is 15:30 UTC. The day before ended at 01:14, which no longer matters.
        os.makedirs(self.tree.daily)
        with open(os.path.join(self.tree.daily, "2026-12-20.json"), "w") as f:
            json.dump({"status": "encoded", "end_utc": "2026-12-21T01:14:00Z"}, f)
        self.tree.add_day()
        self.tree.add(datetime(2026, 12, 21, 15, 30, tzinfo=UTC))
        self.run_job(start_local="07:30")
        rec = self.tree.record("2026-12-21")
        self.assertEqual(rec["start_utc"], "2026-12-21T15:30:00Z")
        self.assertEqual(self.encoded[0][2][0], datetime(2026, 12, 21, 15, 30, tzinfo=UTC), "07:30 itself is in")
        self.assertEqual(self.encoded[0][2][-1], SUNSET + timedelta(minutes=30), "it still ends on the first dark frame")

    def test_a_start_time_does_not_trip_the_too_few_frames_check_on_a_shorter_video(self):
        self.tree.add_day()
        self.run_job(start_local="07:30")
        self.assertEqual(self.tree.record("2026-12-21")["status"], "encoded")

    def test_a_fused_frame_replaces_the_frame_of_the_same_name_and_keeps_its_sun_data(self):
        self.tree.add_day()
        fused_dir = os.path.join(self.tree.dir, "fused")
        os.makedirs(fused_dir)
        name = "wide_%s.jpg" % (SUNSET - timedelta(minutes=15)).strftime("%Y%m%dT%H%M%SZ")
        with open(os.path.join(fused_dir, name), "wb") as f:
            f.write(FAKE_JPEG)
        seen = []

        def fake_encode(cfg, frames, crop, mask, out):
            seen.extend((f.jpg, f.sun is not None) for f in frames)
            with open(out, "wb") as f:
                f.write(b"video")
        daily.run(self.tree.config(fused_dir=fused_dir), self.NOW, encode=fake_encode,
                  frame_size=lambda path: (4056, 3040), check_image=lambda *a: None)
        swapped = [x for x in seen if x[0].startswith(fused_dir)]
        self.assertEqual([os.path.basename(p) for p, _ in swapped], [name])
        self.assertTrue(swapped[0][1], "the original's Sun block is still read")
        self.assertEqual(len(seen), 96)

    def test_the_record_keeps_the_view_direction(self):
        with open(self.tree.crop_file, "w") as f:
            json.dump({"calibrations": [{"start": "2026-12-01", "cx": 2028, "fits": [
                {"date": "2026-12-10", "f_px": 2000.0, "az0_deg": 250.0}]}]}, f)
        self.tree.add_day()
        self.run_job()
        self.assertEqual(self.tree.record("2026-12-21")["crop"]["center_azimuth_deg"], 250.0)

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
        # That frame leaves a real 60-minute hole before the end, which this test isn't about.
        self.run_job(SUNSET + timedelta(hours=2), max_sunset_gap_min=90)
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


@unittest.skipUnless(HAVE_FFMPEG and TEST_FONT, "ffmpeg or a bold font not installed")
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
        # 96 frames at 12 per second is 8 s, with no hold on sunset.
        self.assertAlmostEqual(float(info["format"]["duration"]), 8.0, delta=0.2)
        with open(path, "rb") as f:
            data = f.read()
        self.assertLess(data.index(b"moov"), data.index(b"mdat"), "moov atom must come first")

    def test_an_unreadable_frame_in_the_list_fails_the_encode_instead_of_cutting_the_video_short(self):
        # Without -xerror, ffmpeg stopped at the empty file, kept 3 of 11 frames and exited 0.
        empty = os.path.join(self.dir, "empty.jpg")
        open(empty, "wb").close()
        frames = [daily.Frame(SUNSET, p, None) for p in (self.white, self.white, empty, self.white, self.white)]
        tree = Tree(self)
        os.makedirs(tree.daily)
        with self.assertRaises(daily.EncodeError):
            daily.encode_video(tree.config(), frames, {"x": 0, "width": 270, "height": 480}, [],
                               os.path.join(tree.daily, "video.mp4"))

    def test_video_frame_count_is_checked_after_encoding(self):
        tree = Tree(self)
        os.makedirs(tree.daily)
        out = os.path.join(tree.daily, "video.mp4")
        frames = [daily.Frame(SUNSET, self.white, None)] * 5
        daily.encode_video(tree.config(), frames, {"x": 0, "width": 270, "height": 480}, [], out)
        self.assertEqual(daily.count_video_frames(tree.config(), out), daily.expected_video_frames(5))
        daily.check_frame_count(tree.config(), out, 5)   # passes
        with self.assertRaises(daily.EncodeError):
            daily.check_frame_count(tree.config(), out, 50)

    def test_video_is_converted_and_tagged_as_bt709(self):
        # 200,100,50 in the JPEG (BT.601, full range) must come back as the same colour when the
        # video is read the way its tags say: BT.709, limited range.
        src = os.path.join(self.dir, "colour.jpg")
        make_image(src, color="0xC86432")
        tree = Tree(self)
        os.makedirs(tree.daily)
        out = os.path.join(tree.daily, "video.mp4")
        daily.encode_video(tree.config(), [daily.Frame(SUNSET, src, None)] * 3,
                           {"x": 0, "width": 270, "height": 480}, [], out)
        v = probe(out)["streams"][0]
        self.assertEqual((v.get("color_space"), v.get("color_transfer"), v.get("color_primaries"), v.get("color_range")),
                         ("bt709", "bt709", "bt709", "tv"))

        def rgb(matrix):
            raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", out, "-frames:v", "1", "-vf",
                                  "crop=8:8:100:100,scale=in_color_matrix=%s:in_range=tv:out_range=pc,format=rgb24"
                                  % matrix, "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
            return [sum(raw[i::3]) / (len(raw) / 3) for i in range(3)]
        for got, want in zip(rgb("bt709"), (200, 100, 50)):
            self.assertAlmostEqual(got, want, delta=4)
        self.assertGreater(abs(rgb("bt601")[0] - 200), 6, "read as BT.601 it is off, so it really was converted")

    def test_last_light_frame_keeps_its_brightness_when_dark_frames_follow(self):
        # Real dusk: a deflicker filter pulled the sunset frame from 101 down to 59.
        gray, black = os.path.join(self.dir, "gray.jpg"), os.path.join(self.dir, "black.jpg")
        make_image(gray, color="gray")
        make_image(black, color="black")
        frames = [daily.Frame(SUNSET, gray, None) for _ in range(10)]
        frames += [daily.Frame(SUNSET, black, None) for _ in range(5)]
        tree = Tree(self)
        os.makedirs(tree.daily)
        out = os.path.join(tree.daily, "video.mp4")
        crop = {"x": 0, "width": 270, "height": 480}
        daily.encode_video(tree.config(), frames, crop, [], out)
        before = gray_row(out, 960, seek=0)
        last = gray_row(out, 960, seek=9.5 / 12)   # the 10th frame, the last gray one
        self.assertAlmostEqual(sum(last) / len(last), sum(before) / len(before), delta=2)

    def overlay_video(self, minutes, center_azimuth_deg=None, **config):
        """Gray frames at these minutes after SUNSET, encoded with the overlay."""
        gray = os.path.join(self.dir, "gray.jpg")
        make_image(gray, color="gray")
        frames = [daily.Frame(SUNSET + timedelta(minutes=m), gray, None) for m in minutes]
        tree = Tree(self)
        os.makedirs(tree.daily)
        out = os.path.join(tree.daily, "video.mp4")
        crop = {"x": 0, "width": 270, "height": 480}
        if center_azimuth_deg is not None:
            crop["center_azimuth_deg"] = center_azimuth_deg
        daily.encode_video(tree.config(**config), frames, crop, [], out)
        return out

    def band(self, path, top, height, seek):
        """Rows top..top+height of one frame, as luma bytes."""
        return b"".join(gray_row(path, y, seek=seek) for y in range(top, top + height))

    def change(self, a, b):
        """Mean luma difference. Compression noise alone stays well under 1."""
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a)

    def test_title_and_timestamp_are_drawn_bottom_left_and_nothing_else(self):
        out = self.overlay_video([0, 15, 30])
        title = gray_row(out, daily.TITLE_Y + daily.TITLE_SIZE // 2, seek=0)
        time_row = gray_row(out, daily.TIME_Y + daily.TIME_SIZE // 2, seek=0)
        for row in (title, time_row):
            self.assertGreater(max(row[:540]) - min(row[:540]), 100, "text should be drawn on the left")
        self.assertGreater(max(title[540:800]) - min(title[540:800]), 100, "the handle follows the title")
        # The timestamp's width depends on the font: it ends near x=620 in Arial Bold (Windows) and
        # x=750 in DejaVu Sans Bold (Linux, and the NAS image). 900 holds for both, so the layout
        # is checked the same way on every machine.
        self.assertLess(max(time_row[900:]) - min(time_row[900:]), 20, "the timestamp stays on the left")
        self.assertEqual(1920 - (daily.LOC_Y + daily.LOC_SIZE), 140, "the last line is 140 px above the bottom edge")
        self.assertLess(daily.TIME_Y + daily.TIME_SIZE, daily.LOC_Y, "the location is under the date")
        for y in (100, 960, 1400):   # top, middle and the rest of the bottom half stay clear
            row = gray_row(out, y, seek=0)
            self.assertLess(max(row) - min(row), 20, "row %d should be untouched" % y)

    def test_location_and_direction_are_small_and_under_the_date(self):
        out = self.overlay_video([0, 15, 30], center_azimuth_deg=242.97)
        self.assertLess(daily.LOC_SIZE, daily.TIME_SIZE // 1.5, "small text")
        row = gray_row(out, daily.LOC_Y + daily.LOC_SIZE // 2, seek=0)
        self.assertGreater(max(row[:540]) - min(row[:540]), 100, "the location line is drawn on the left")
        self.assertLess(max(row[900:]) - min(row[900:]), 20, "and stays on the left")

    def test_no_location_means_no_third_line(self):
        out = self.overlay_video([0, 15, 30], location="")
        band = self.band(out, daily.LOC_Y, daily.LOC_SIZE, 0)
        self.assertLess(max(band) - min(band), 20)

    def test_degree_sign_survives_the_filter_file(self):
        # The filter script has to be written as UTF-8 for ffmpeg, whatever the machine's locale.
        out = self.overlay_video([0, 15, 30], center_azimuth_deg=270.0)
        self.assertTrue(os.path.getsize(out) > 0)

    def blur_row(self, blur):
        """A white/black edge at full-frame x=320, with a blur box across it; the row at the edge."""
        edge = os.path.join(self.dir, "edge.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=white:s=640x480:d=1,drawbox=x=320:y=0:w=320:h=480:color=black:t=fill",
                        "-frames:v", "1", "-q:v", "2", edge], check=True)
        frames = [daily.Frame(SUNSET + timedelta(minutes=m), edge, None) for m in (0, 15, 30)]
        tree = Tree(self)
        os.makedirs(tree.daily)
        out = os.path.join(tree.daily, "video.mp4")
        crop = {"x": 185, "width": 270, "height": 480}   # the edge lands at video x = 540
        if blur:
            crop.update(blur=blur, blur_sigma=5)
        daily.encode_video(tree.config(), frames, crop, [], out)
        return gray_row(out, 960, seek=0.05)

    def soft_pixels(self, row):
        return len([v for v in row[400:700] if 60 < v < 190])

    def test_blur_box_softens_what_is_inside_it(self):
        sharp = self.soft_pixels(self.blur_row(None))
        soft = self.soft_pixels(self.blur_row([[300, 0, 40, 480]]))
        self.assertLess(sharp, 8, "an unblurred edge is a step")
        self.assertGreater(soft, 12, "a blurred edge is a ramp")

    SKY_EXTRA = (-35, -25, -20, -10, -5, 5, 10, 20, 25)   # 5-minute frames between the 15-minute ones

    def sky_record(self, color, extra=SKY_EXTRA):
        path = os.path.join(self.dir, "%s.jpg" % color)
        make_image(path, color=color)
        tree = Tree(self, path)
        tree.add_day()
        for m in extra:
            tree.add(SUNSET + timedelta(minutes=m), schedule="dense")
        self.assertEqual(self.run_real(tree), 0)
        return tree.record()

    def test_record_has_a_sky_score_from_the_frames_around_sunset(self):
        sky = self.sky_record("orange")
        self.assertEqual((sky["sky"]["score"], sky["sky"]["label"]), (100, "colourful"))
        self.assertEqual(sky["sky"]["frames_scored"], 13, "-35 to +25 minutes: 4 regular and 9 extra frames")
        self.assertTrue(sky["sky"]["provisional"])
        self.assertEqual(sky["sky"]["crop"]["score"], 100, "the crop's columns are orange too")

    def test_too_few_frames_around_sunset_gives_no_score_and_says_why(self):
        rec = self.sky_record("orange", extra=())
        self.assertIsNone(rec["sky"], "4 frames is under the minimum")
        self.assertIn("4", rec["sky_note"])
        self.assertIn("no_sky_score", rec["post_blockers"])

    def test_a_grey_sky_scores_zero(self):
        sky = self.sky_record("gray")["sky"]
        self.assertEqual((sky["score"], sky["label"]), (0, "grey"))

    def half_and_half(self):
        path = os.path.join(self.dir, "halves.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=white:s=640x480:d=1,drawbox=x=0:y=240:w=640:h=240:color=black:t=fill",
                        "-frames:v", "1", "-q:v", "2", path], check=True)
        return path

    def view_mean(self, y):
        frames = [daily.Frame(SUNSET + timedelta(minutes=m), self.half_and_half(), None) for m in (0, 15, 30)]
        tree = Tree(self)
        os.makedirs(tree.daily)
        out = os.path.join(tree.daily, "video.mp4")
        daily.encode_video(tree.config(), frames, {"x": 100, "y": y, "width": 134, "height": 240}, [], out)
        row = gray_row(out, 700, seek=0.05)
        return sum(row) / len(row)

    def test_a_view_crops_rows_as_well_as_columns(self):
        self.assertGreater(self.view_mean(0), 200, "the top half is white")
        self.assertLess(self.view_mean(240), 50, "the bottom half is black")

    def test_blur_box_leaves_the_rest_of_the_frame_alone(self):
        row = self.blur_row([[300, 0, 40, 480]])
        self.assertGreater(min(row[100:300]), 200)
        self.assertLess(max(row[800:1000]), 40)

    def test_timestamp_follows_each_frame(self):
        out = self.overlay_video([0, 15, 30, 30])   # each frame 1/12 s; the last two share a minute
        top, height = daily.TIME_Y, daily.TIME_SIZE
        bands = [self.band(out, top, height, (i + 0.5) / 12) for i in range(4)]
        self.assertGreater(self.change(bands[0], bands[1]), 3)
        self.assertGreater(self.change(bands[1], bands[2]), 3)
        self.assertLess(self.change(bands[2], bands[3]), 1, "the same minute gives the same text")

    def test_a_day_of_one_minute_frames_still_encodes(self):
        # One timestamp filter per frame: 1,440 of them would not fit on a command line.
        out = self.overlay_video(range(1440))
        self.assertAlmostEqual(float(probe(out)["format"]["duration"]), 1440 / 12, delta=0.2)

    def test_title_stays_the_same_from_frame_to_frame(self):
        out = self.overlay_video([0, 15, 30])
        top, height = daily.TITLE_Y, daily.TITLE_SIZE
        self.assertLess(self.change(self.band(out, top, height, 0.02), self.band(out, top, height, 0.19)), 1)

    def test_an_empty_frame_on_the_nas_is_left_out_and_the_video_keeps_the_rest(self):
        tree = self.frames()
        bad = SUNSET - timedelta(hours=4)
        open(os.path.join(tree.frames, "2026", "12", "21", "wide_%s.jpg" % bad.strftime("%Y%m%dT%H%M%SZ")), "wb").close()
        self.assertEqual(self.run_real(tree), 0)
        rec = tree.record()
        self.assertEqual((rec["status"], rec["frames"], rec["dropped_frames"]), ("encoded", 95, 1))
        self.assertEqual(daily.count_video_frames(tree.config(), os.path.join(tree.daily, rec["video"])),
                         daily.expected_video_frames(95))

    def test_no_temporary_files_are_left_behind(self):
        tree = self.frames(68)
        self.run_real(tree)
        names = sorted(n for n in os.listdir(tree.daily) if not n.endswith((".json", ".mp4", ".jpg", ".txt")))
        self.assertEqual(names, [])
        self.assertEqual(sorted(os.listdir(tree.daily)),
                         ["2026-12-21.json", "2026-12-21.mp4", "2026-12-21.txt", "2026-12-21_check.jpg"])

    def test_broken_ffmpeg_keeps_no_video_only_a_failed_record(self):
        tree = self.frames(68)
        rc = self.run_real(tree, ffmpeg="ffmpeg-that-does-not-exist")
        self.assertEqual(rc, 1)
        self.assertEqual(os.listdir(tree.daily), ["2026-12-21.json"])
        self.assertEqual(tree.record()["status"], "failed")

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


def add_dense(tree, first=-60, last=30, skip=()):
    """1-a-minute frames around SUNSET between the 15-minute ones, as the Pi adds them."""
    for m in range(first, last + 1):
        if m % 15 and m not in skip:
            tree.add(SUNSET + timedelta(minutes=m), schedule="dense")


class SunsetCutWindow(unittest.TestCase):
    def test_from_the_minutes_before_sunset_to_the_first_frame_at_the_end_elevation(self):
        frames = [frame_at(-70), frame_at(-60), frame_at(-30), frame_at(0), frame_at(20),
                  frame_at(30, elevation=-9.0), frame_at(40, elevation=-10.0)]
        got, info = daily.sunset_cut_frames(frames, SUNSET, 60, -9.0, 60)
        self.assertEqual([f.sun["minutes_from_sunset"] for f in got], [-60, -30, 0, 20, 30])
        self.assertEqual(info["end_by"], "elevation")

    def test_the_end_elevation_can_be_lower(self):
        frames = [frame_at(-10), frame_at(30, elevation=-9.0), frame_at(40, elevation=-10.0),
                  frame_at(50, elevation=-12.5)]
        got, _ = daily.sunset_cut_frames(frames, SUNSET, 60, -12.0, 90)
        self.assertEqual([f.sun["minutes_from_sunset"] for f in got], [-10, 30, 40, 50])

    def test_with_no_elevation_it_stops_at_the_minutes_limit(self):
        frames = [frame_at(m) for m in (-5, 20, 44, 45, 46)]
        for f in frames:
            del f.sun["elevation_deg"]
        got, info = daily.sunset_cut_frames(frames, SUNSET, 60, -9.0, 45)
        self.assertEqual([f.sun["minutes_from_sunset"] for f in got], [-5, 20, 44, 45])
        self.assertEqual(info["end_by"], "minutes")

    def test_frames_of_another_sunset_are_left_out(self):
        later = SUNSET + timedelta(days=1)
        frames = [frame_at(-10), frame_at(-10, sunset=later), frame_at(30, elevation=-9.0)]
        got, _ = daily.sunset_cut_frames(frames, SUNSET, 60, -9.0, 60)
        self.assertEqual(len(got), 2)

    def test_a_frame_with_no_sun_block_goes_by_its_time(self):
        frames = [daily.Frame(SUNSET - timedelta(minutes=61), "early", None),
                  daily.Frame(SUNSET - timedelta(minutes=10), "in", None), frame_at(30, elevation=-9.0)]
        got, _ = daily.sunset_cut_frames(frames, SUNSET, 60, -9.0, 60)
        self.assertEqual([f.jpg for f in got], ["in", "unused.jpg"])


class MasterGeometry(unittest.TestCase):
    def test_full_frame_is_scaled_to_3840_wide_and_kept_even(self):
        g = daily.master_geometry(4056, 3040, None, 3840)
        self.assertEqual((g["x"], g["y"], g["width"], g["height"], g["out_width"], g["out_height"], g["from"]),
                         (0, 0, 4056, 3040, 3840, 2878, "full_frame"))

    def test_a_master_view_box_is_used_and_never_scaled_up(self):
        g = daily.master_geometry(4056, 3040, {"x": 101, "y": 200, "width": 2001, "height": 1001}, 3840)
        self.assertEqual((g["x"], g["y"], g["width"], g["height"], g["out_width"], g["out_height"], g["from"]),
                         (100, 200, 2000, 1000, 2000, 1000, "master_view"), "even, for yuv420p")

    def test_a_box_is_kept_inside_the_frame(self):
        g = daily.master_geometry(4056, 3040, {"x": 4000, "y": 3000, "width": 1000, "height": 500}, 3840)
        self.assertEqual((g["x"], g["y"], g["width"], g["height"]), (3056, 2540, 1000, 500))

    def test_the_width_can_be_lower(self):
        g = daily.master_geometry(4056, 3040, None, 1920)
        self.assertEqual((g["out_width"], g["out_height"]), (1920, 1440), "1439.05 rounds to the nearest even")


class ScriptVersions(unittest.TestCase):
    def test_versions_compare_by_date_then_number(self):
        key = daily.version_key
        self.assertLess(key("2026-11-15.9"), key("2026-11-15.10"))
        self.assertLess(key("2026-11-14.3"), key("2026-11-15.1"))
        self.assertLess(key(None), key("2026-11-15.1"))
        self.assertLess(key("not a version"), key("2026-11-15.1"))
        self.assertEqual(key("2026-11-15.2"), key("2026-11-15.2"))

    def test_the_current_version_is_newer_than_the_last_one(self):
        self.assertLess(daily.version_key("2026-11-15.1"), daily.version_key(daily.SCRIPT_VERSION))


class ExtraOutputs(unittest.TestCase):
    """The sunset-only cut, the master and the redo rule, with stand-in encoders."""
    NOW = SUNSET + timedelta(hours=1)

    def setUp(self):
        self.tree = Tree(self)
        self.encoded = []
        self.masters = []

    def run_job(self, now=NOW, cut_fails=False, **over):
        def fake_encode(cfg, frames, crop, mask, out):
            if cut_fails and "_sunset" in out:
                raise daily.EncodeError("cut broke")
            self.encoded.append((os.path.basename(out), [f.time for f in frames], dict(crop)))
            with open(out, "wb") as f:
                f.write(b"video")

        def fake_master(cfg, frames, geometry, out):
            self.masters.append((os.path.basename(out), [f.time for f in frames], dict(geometry)))
            with open(out, "wb") as f:
                f.write(b"master")
        return daily.run(self.tree.config(**over), now, encode=fake_encode, frame_size=lambda path: (4056, 3040),
                         check_image=lambda *a: None, master_encode=fake_master)

    def write_crop(self, **cfg):
        with open(self.tree.crop_file, "w") as f:
            json.dump(cfg, f)

    def files(self):
        return sorted(os.listdir(self.tree.daily))

    def test_both_are_off_by_default_and_the_record_is_unchanged(self):
        self.tree.add_day()
        add_dense(self.tree)
        self.assertEqual(self.run_job(), 0)
        self.assertEqual(len(self.encoded), 1)
        self.assertEqual(self.masters, [])
        rec = self.tree.record()
        for key in ("sunset_cut", "master", "redo"):
            self.assertNotIn(key, rec)
        self.assertEqual(self.files(), ["2026-12-21.json", "2026-12-21.mp4", "2026-12-21.txt"])

    def test_sunset_cut_is_the_hour_before_sunset_to_dark(self):
        self.tree.add_day()
        add_dense(self.tree)
        self.assertEqual(self.run_job(sunset_cut=True), 0)
        self.assertEqual([e[0] for e in self.encoded], [".2026-12-21.mp4.tmp", ".2026-12-21_sunset.mp4.tmp"])
        times = self.encoded[1][1]
        self.assertEqual(times, [SUNSET + timedelta(minutes=m) for m in range(-60, 31)])
        self.assertEqual(self.encoded[1][2], self.encoded[0][2], "the same crop, blur and overlay as the daily video")
        rec = self.tree.record()
        cut = rec["sunset_cut"]
        self.assertEqual((cut["status"], cut["video"], cut["frames"], cut["expected_frames"], cut["dropped_frames"]),
                         ("encoded", "2026-12-21_sunset.mp4", 91, 91, 0))
        self.assertEqual(cut["largest_gap_min"], 1.0)
        w = cut["window"]
        self.assertEqual((w["before_min"], w["end_elevation_deg"], w["end_by"]), (60, -9.0, "elevation"))
        self.assertEqual((w["first_utc"], w["last_utc"]), ("2026-12-21T23:14:00Z", "2026-12-22T00:44:00Z"))
        self.assertEqual((w["first_minutes"], w["last_minutes"]), (-60.0, 30.0))
        self.assertIn("2026-12-21_sunset.mp4", self.files())
        self.assertEqual(rec["status"], "encoded")

    def test_the_cut_window_can_be_changed(self):
        self.tree.add_day()
        add_dense(self.tree)
        self.run_job(sunset_cut=True, cut_before_min=30)
        self.assertEqual(len(self.encoded[1][1]), 61)
        self.assertEqual(self.tree.record()["sunset_cut"]["window"]["first_minutes"], -30.0)

    def test_too_few_frames_in_the_cut_window_skips_only_the_cut(self):
        self.tree.add_day()   # 15-minute frames only: 7 of the 91 one-minute frames
        self.assertEqual(self.run_job(sunset_cut=True), 0)
        self.assertEqual(len(self.encoded), 1)
        rec = self.tree.record()
        self.assertEqual(rec["status"], "encoded")
        cut = rec["sunset_cut"]
        self.assertEqual((cut["status"], cut["frames"]), ("skipped", 7))
        self.assertIn("7 of 91", cut["reason"])
        self.assertNotIn("video", cut)
        self.assertNotIn("2026-12-21_sunset.mp4", self.files())

    def test_a_gap_in_the_cut_window_skips_the_cut(self):
        self.tree.add_day()
        add_dense(self.tree, skip=range(-29, -15))   # -30 to -15 with nothing between
        self.run_job(sunset_cut=True, cut_max_gap_min=10)
        cut = self.tree.record()["sunset_cut"]
        self.assertEqual((cut["status"], cut["largest_gap_min"]), ("skipped", 15.0))
        self.assertIn("15-minute gap", cut["reason"])

    def test_by_default_the_cut_gap_limit_is_the_sunset_one(self):
        self.tree.add_day()
        add_dense(self.tree, skip=range(-29, -15))
        self.run_job(sunset_cut=True)
        self.assertEqual(self.tree.record()["sunset_cut"]["status"], "encoded")

    def test_an_unreadable_frame_is_left_out_of_the_cut(self):
        self.tree.add_day()
        add_dense(self.tree)
        t = SUNSET - timedelta(minutes=20)
        open(os.path.join(self.tree.frames, "2026", "12", "21", "wide_%s.jpg" % t.strftime("%Y%m%dT%H%M%SZ")), "wb").close()
        self.run_job(sunset_cut=True)
        cut = self.tree.record()["sunset_cut"]
        self.assertEqual((cut["frames"], cut["dropped_frames"], cut["dropped"]),
                         (90, 1, ["wide_20261221T235400Z.jpg"]))
        self.assertNotIn(t, self.encoded[1][1])

    def test_a_failed_cut_keeps_the_daily_video_and_says_why(self):
        self.tree.add_day()
        add_dense(self.tree)
        self.assertEqual(self.run_job(sunset_cut=True, cut_fails=True), 1)
        rec = self.tree.record()
        self.assertEqual((rec["status"], rec["video"]), ("encoded", "2026-12-21.mp4"))
        self.assertEqual(rec["sunset_cut"]["status"], "failed")
        self.assertIn("cut broke", rec["sunset_cut"]["error"])
        self.assertEqual(self.files(), ["2026-12-21.json", "2026-12-21.mp4", "2026-12-21.txt"])

    def test_a_skipped_day_makes_neither_and_says_so(self):
        self.tree.add_day(10)
        self.run_job(sunset_cut=True, master=True)
        rec = self.tree.record()
        self.assertEqual(rec["status"], "skipped")
        self.assertEqual((rec["sunset_cut"]["status"], rec["master"]["status"]), ("skipped", "skipped"))
        self.assertIn("day was skipped", rec["master"]["reason"])
        self.assertEqual((self.encoded, self.masters), ([], []))

    def test_master_is_the_whole_day_full_frame_at_3840_wide(self):
        self.tree.add_day()
        add_dense(self.tree)
        self.assertEqual(self.run_job(master=True), 0)
        self.assertEqual(len(self.masters), 1)
        name, times, geometry = self.masters[0]
        self.assertEqual(name, ".2026-12-21_master.mp4.tmp")
        self.assertEqual(times, self.encoded[0][1], "the same frames as the daily video")
        self.assertEqual((geometry["out_width"], geometry["out_height"], geometry["from"]), (3840, 2878, "full_frame"))
        m = self.tree.record()["master"]
        self.assertEqual((m["status"], m["video"], m["frames"]), ("encoded", "2026-12-21_master.mp4", 180))
        self.assertEqual((m["codec"], m["crf"], m["preset"], m["pix_fmt"]), ("libx264", 14, "slow", "yuv420p"))
        self.assertEqual((m["width"], m["height"]), (3840, 2878))
        self.assertEqual(m["source"], {"x": 0, "y": 0, "width": 4056, "height": 3040, "from": "full_frame"})
        self.assertEqual((m["overlay"], m["blur"], m["mask"]), (False, False, False))
        self.assertEqual(m["size_bytes"], 6)
        self.assertIn("2026-12-21_master.mp4", self.files())

    def test_master_settings_are_recorded(self):
        self.tree.add_day()
        self.run_job(master=True, master_codec="libx265", master_crf=16, master_preset="medium",
                     master_pix_fmt="yuv420p10le", master_width=1920)
        m = self.tree.record()["master"]
        self.assertEqual((m["codec"], m["crf"], m["preset"], m["pix_fmt"], m["width"]),
                         ("libx265", 16, "medium", "yuv420p10le", 1920))

    def test_master_view_in_the_calibration_sets_the_box(self):
        self.write_crop(blur=[[0, 0, 10, 10]], calibrations=[
            {"start": "2026-12-01", "cx": 2028, "master_view": {"x": 0, "y": 100, "width": 4056, "height": 2440},
             "fits": [{"date": "2026-12-10", "f_px": 2000.0, "az0_deg": 250.0}]}])
        self.tree.add_day()
        self.run_job(master=True)
        g = self.masters[0][2]
        self.assertEqual((g["x"], g["y"], g["width"], g["height"], g["out_width"], g["out_height"], g["from"]),
                         (0, 100, 4056, 2440, 3840, 2310, "master_view"))
        self.assertEqual(self.tree.record()["master"]["source"]["from"], "master_view")

    def test_master_is_made_when_the_camera_position_does_not_match(self):
        self.write_crop(calibrations=[{"start": "2026-12-01", "setup_id": "pilot-3", "cx": 2028,
                                       "fits": [{"date": "2026-12-10", "f_px": 2000.0, "az0_deg": 250.0}]}])
        last = SUNSET + timedelta(minutes=30)
        for i in range(96):
            self.tree.add(last - timedelta(minutes=15 * i), setup_id="pilot-4")
        self.run_job(master=True)
        rec = self.tree.record()
        self.assertTrue(rec["setup_mismatch"])
        self.assertEqual(rec["master"]["status"], "encoded", "no blur boxes to misplace")

    def test_a_failed_master_keeps_the_daily_video(self):
        self.tree.add_day()

        def broken(*a):
            raise daily.EncodeError("4K broke")

        def fake_encode(cfg, frames, crop, mask, out):
            open(out, "wb").close()
        rc = daily.run(self.tree.config(master=True), self.NOW, encode=fake_encode,
                       frame_size=lambda path: (4056, 3040), check_image=lambda *a: None, master_encode=broken)
        self.assertEqual(rc, 1)
        rec = self.tree.record()
        self.assertEqual((rec["status"], rec["master"]["status"]), ("encoded", "failed"))
        self.assertIn("4K broke", rec["master"]["error"])

    # The redo rule.

    def test_turning_an_output_on_later_does_not_redo_a_finished_day(self):
        self.tree.add_day()
        self.run_job()
        first = self.tree.record()
        self.run_job(self.NOW + timedelta(minutes=30), master=True, sunset_cut=True)
        self.assertEqual((len(self.encoded), self.masters), (1, []))
        self.assertEqual(self.tree.record(), first)

    def test_redo_missing_outputs_redoes_a_day_without_them(self):
        self.tree.add_day()
        self.run_job()
        self.run_job(self.NOW + timedelta(minutes=30), master=True, redo_missing_outputs=True)
        self.assertEqual((len(self.encoded), len(self.masters)), (2, 1))
        rec = self.tree.record()
        self.assertEqual(rec["master"]["status"], "encoded")
        self.assertIn("master", rec["redo"]["reason"])
        self.run_job(self.NOW + timedelta(minutes=60), master=True, redo_missing_outputs=True)
        self.assertEqual(len(self.masters), 1, "once it has them, it is left alone")

    def test_redo_missing_outputs_also_redoes_a_failed_output(self):
        self.tree.add_day()
        add_dense(self.tree)
        self.run_job(sunset_cut=True, cut_fails=True)
        self.assertEqual(self.tree.record()["sunset_cut"]["status"], "failed")
        self.run_job(self.NOW + timedelta(minutes=30), sunset_cut=True, redo_missing_outputs=True)
        self.assertEqual(self.tree.record()["sunset_cut"]["status"], "encoded")

    def test_redo_older_than_a_version(self):
        self.tree.add_day()
        self.run_job()
        path = os.path.join(self.tree.daily, "2026-12-21.json")
        rec = self.tree.record()
        rec["provenance"]["script_version"] = "2026-11-14.1"
        rec["posted"], rec["posted_utc"] = True, "2026-12-22T03:00:00Z"
        with open(path, "w") as f:
            json.dump(rec, f)
        self.run_job(self.NOW + timedelta(minutes=30), redo_older_than=daily.SCRIPT_VERSION)
        self.assertEqual(len(self.encoded), 2)
        rec = self.tree.record()
        self.assertEqual(rec["provenance"]["script_version"], daily.SCRIPT_VERSION)
        self.assertEqual(rec["redo"]["previous_script_version"], "2026-11-14.1")
        self.assertEqual((rec["posted"], rec["posted_utc"]), (True, "2026-12-22T03:00:00Z"),
                         "a redo never makes a posted day look unposted")
        self.run_job(self.NOW + timedelta(minutes=60), redo_older_than=daily.SCRIPT_VERSION)
        self.assertEqual(len(self.encoded), 2, "made by this version: left alone")

    def test_a_record_with_no_version_counts_as_older(self):
        self.tree.add_day()
        os.makedirs(self.tree.daily)
        with open(os.path.join(self.tree.daily, "2026-12-21.json"), "w") as f:
            json.dump({"status": "skipped", "reason": "old rules", "end_utc": "2026-12-22T00:44:00Z"}, f)
        self.run_job(redo_older_than="2026-11-15.2")
        rec = self.tree.record()
        self.assertEqual(rec["status"], "encoded")
        self.assertIsNone(rec["redo"]["previous_script_version"])

    def test_redo_is_limited_to_the_lookback_unless_a_range_is_given(self):
        self.tree.add_day()
        self.run_job()
        later = SUNSET + timedelta(days=5)
        self.run_job(later, master=True, redo_missing_outputs=True)
        self.assertEqual(self.masters, [])
        self.run_job(later, master=True, redo_missing_outputs=True,
                     redo_from=datetime(2026, 12, 21).date(), redo_to=datetime(2026, 12, 21).date())
        self.assertEqual(len(self.masters), 1)

    def test_days_outside_the_range_are_left_alone(self):
        self.tree.add_day()
        self.run_job()
        self.run_job(master=True, redo_missing_outputs=True,
                     redo_from=datetime(2026, 12, 22).date(), redo_to=datetime(2026, 12, 30).date())
        self.assertEqual(self.masters, [])

    def test_a_range_also_makes_days_that_were_never_made(self):
        self.tree.add_day()
        self.run_job(SUNSET + timedelta(days=5), redo_from=datetime(2026, 12, 21).date())
        self.assertEqual(self.tree.record()["status"], "encoded")


class EnvironmentSettings(unittest.TestCase):
    BASE = {"FRAMES_DIR": "/f", "DAILY_DIR": "/d", "SITE_TZ": "UTC"}

    def config(self, **env):
        real_tz()
        return daily.config_from_env(dict(self.BASE, **env))

    def test_new_outputs_and_redo_are_off_by_default(self):
        cfg = self.config()
        self.assertEqual((cfg.sunset_cut, cfg.master, cfg.redo_missing_outputs, cfg.redo_older_than,
                          cfg.redo_from, cfg.redo_to), (False, False, False, None, None, None))
        self.assertEqual((cfg.cut_before_min, cfg.cut_end_elevation, cfg.cut_after_min, cfg.cut_max_gap_min),
                         (60.0, -9.0, 60.0, None))
        self.assertEqual((cfg.master_codec, cfg.master_crf, cfg.master_preset, cfg.master_width, cfg.master_pix_fmt),
                         ("libx264", 14, "slow", 3840, "yuv420p"))

    def test_settings_are_read(self):
        cfg = self.config(SUNSET_CUT="1", SUNSET_CUT_BEFORE_MIN="45", SUNSET_CUT_END_ELEVATION="-12",
                          SUNSET_CUT_AFTER_MIN="70", SUNSET_CUT_MAX_GAP_MIN="5", MASTER="1",
                          MASTER_CODEC="libx265", MASTER_CRF="18", MASTER_PRESET="medium", MASTER_WIDTH="1920",
                          MASTER_PIX_FMT="yuv420p10le", REDO_OLDER_THAN_VERSION="2026-11-15.2",
                          REDO_MISSING_OUTPUTS="1", REDO_FROM="2026-11-01", REDO_TO="2026-11-30")
        self.assertEqual((cfg.sunset_cut, cfg.cut_before_min, cfg.cut_end_elevation, cfg.cut_after_min,
                          cfg.cut_max_gap_min), (True, 45.0, -12.0, 70.0, 5.0))
        self.assertEqual((cfg.master, cfg.master_codec, cfg.master_crf, cfg.master_preset, cfg.master_width,
                          cfg.master_pix_fmt), (True, "libx265", 18, "medium", 1920, "yuv420p10le"))
        self.assertEqual((cfg.redo_older_than, cfg.redo_missing_outputs, cfg.redo_from.isoformat(),
                          cfg.redo_to.isoformat()), ("2026-11-15.2", True, "2026-11-01", "2026-11-30"))

    def test_zero_and_empty_mean_off(self):
        cfg = self.config(SUNSET_CUT="0", MASTER="", REDO_MISSING_OUTPUTS="0")
        self.assertEqual((cfg.sunset_cut, cfg.master, cfg.redo_missing_outputs), (False, False, False))


def ffmpeg_encoders():
    if not HAVE_FFMPEG:
        return ""
    return subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout


@unittest.skipUnless(HAVE_FFMPEG and TEST_FONT, "ffmpeg or a bold font not installed")
class RealExtraOutputs(unittest.TestCase):
    """The sunset cut and the master with the real ffmpeg."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.white = os.path.join(cls.dir, "white.jpg")
        make_image(cls.white)
        cls.edge = os.path.join(cls.dir, "edge.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=white:s=640x480:d=1,drawbox=x=320:y=0:w=320:h=480:color=black:t=fill",
                        "-frames:v", "1", "-q:v", "2", cls.edge], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, True)

    def run_real(self, tree, **over):
        return daily.run(tree.config(**over), SUNSET + timedelta(hours=1))

    def test_sunset_cut_is_a_reel_of_the_cut_frames(self):
        tree = Tree(self, self.white)
        tree.add_day()
        add_dense(tree)
        self.assertEqual(self.run_real(tree, sunset_cut=True), 0)
        cut = tree.record()["sunset_cut"]
        self.assertEqual(cut["status"], "encoded")
        path = os.path.join(tree.daily, cut["video"])
        v = probe(path)["streams"][0]
        self.assertEqual((v["codec_name"], v["width"], v["height"], v["color_space"]), ("h264", 1080, 1920, "bt709"))
        # The job's own check allows VIDEO_FRAME_SLACK: ffmpeg 7.1 on Windows gave 185 for 91 pictures
        # (expected 183, from rounding 1/12 s durations), ffmpeg 4.4 gave 183.
        self.assertAlmostEqual(daily.count_video_frames(tree.config(), path), daily.expected_video_frames(91),
                               delta=daily.VIDEO_FRAME_SLACK)
        self.assertTrue(os.path.exists(os.path.join(tree.daily, "2026-12-21.mp4")))

    def master(self, image, crop=None, **over):
        tree = Tree(self, image)
        tree.add_day(68)
        if crop:
            with open(tree.crop_file, "w") as f:
                json.dump(crop, f)
        self.assertEqual(self.run_real(tree, master=True, **over), 0)
        return tree, tree.record()

    def test_master_is_high_quality_bt709_with_no_text(self):
        tree, rec = self.master(self.white)
        m = rec["master"]
        self.assertEqual(m["status"], "encoded", m)
        path = os.path.join(tree.daily, m["video"])
        info = probe(path)
        v = info["streams"][0]
        self.assertEqual((v["codec_name"], v["pix_fmt"], v["width"], v["height"], v["r_frame_rate"]),
                         ("h264", "yuv420p", 640, 480, "24/1"), "a 640 frame is not scaled up")
        self.assertEqual((v.get("color_space"), v.get("color_transfer"), v.get("color_primaries"), v.get("color_range")),
                         ("bt709", "bt709", "bt709", "tv"))
        self.assertEqual(daily.count_video_frames(tree.config(), path), daily.expected_video_frames(68))
        for y in (20, 240, 400, 460):   # white frames with nothing drawn on them
            row = gray_row(path, y, width=640, seek=0.05)
            self.assertLess(max(row) - min(row), 20, "row %d should be untouched" % y)
        self.assertEqual(m["size_bytes"], os.path.getsize(path))
        self.assertGreaterEqual(m["encode_seconds"], 0)
        self.assertEqual(sorted(os.listdir(tree.daily)), ["2026-12-21.json", "2026-12-21.mp4", "2026-12-21.txt",
                                                          "2026-12-21_check.jpg", "2026-12-21_master.mp4"])

    def test_master_has_no_blur(self):
        tree, rec = self.master(self.edge, crop={"blur": [[300, 0, 40, 480]], "blur_sigma": 5})
        row = gray_row(os.path.join(tree.daily, rec["master"]["video"]), 240, width=640, seek=0.05)
        self.assertLess(len([v for v in row[280:360] if 60 < v < 190]), 4, "the edge stays a step")

    def test_master_view_crops_the_box(self):
        tree, rec = self.master(self.edge, crop={"master_view": {"x": 300, "y": 0, "width": 40, "height": 480}})
        v = probe(os.path.join(tree.daily, rec["master"]["video"]))["streams"][0]
        self.assertEqual((v["width"], v["height"]), (40, 480))
        row = gray_row(os.path.join(tree.daily, rec["master"]["video"]), 240, width=40, seek=0.05)
        self.assertGreater(row[5], 200)
        self.assertLess(row[35], 50)

    @unittest.skipUnless("libx265" in ffmpeg_encoders(), "this ffmpeg has no libx265")
    def test_master_can_be_10_bit_hevc(self):
        tree, rec = self.master(self.white, master_codec="libx265", master_pix_fmt="yuv420p10le")
        self.assertEqual(rec["master"]["status"], "encoded", rec["master"])
        v = probe(os.path.join(tree.daily, rec["master"]["video"]))["streams"][0]
        self.assertEqual((v["codec_name"], v["pix_fmt"], v.get("codec_tag_string"), v.get("color_space")),
                         ("hevc", "yuv420p10le", "hvc1", "bt709"))

    def test_an_encoder_this_ffmpeg_lacks_skips_the_master_cleanly(self):
        tree, rec = self.master(self.white, master_codec="libnosuchcodec")
        self.assertEqual(rec["status"], "encoded")
        self.assertEqual(rec["master"]["status"], "skipped")
        self.assertIn("libnosuchcodec", rec["master"]["reason"])
        self.assertNotIn("2026-12-21_master.mp4", os.listdir(tree.daily))


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
                   SITE_TZ="America/Vancouver", START_DATE="2026-12-21", FONT_FILE=TEST_FONT or "",
                   EXPECTED_FRAMES="96")
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
