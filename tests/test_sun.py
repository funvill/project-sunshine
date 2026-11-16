"""Tests for sunset-sun.py. Reference values are standard published figures for
~49.25N 123W, to the tolerance noted; run with: python3 tests/test_sun.py"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "pi", "sunset-sun.py")
spec = importlib.util.spec_from_file_location("sunset_sun", SCRIPT)
sun = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sun)

LAT, LON = 49.25, -122.98   # approximate Burnaby
UTC = timezone.utc


def utc(*a):
    return datetime(*a, tzinfo=UTC)


class SunMath(unittest.TestCase):
    def test_winter_solstice_sunset_time_and_azimuth(self):
        s = sun.next_sunset(utc(2026, 12, 21, 20, 0), LAT, LON)
        # Vancouver winter solstice sunset ~16:14 PST = 00:14 UTC on the 22nd
        self.assertLess(abs((s - utc(2026, 12, 22, 0, 14)).total_seconds()), 3 * 60, s)
        az, el = sun.sun_position(s, LAT, LON)
        # Geometric horizon crossing is 232.4 (acos(sin(decl)/cos(lat)) from the other side);
        # sunset is the upper limb at zenith 90.833, ~0.83 deg lower, which moves the sun
        # ~1.2 deg further along the horizon here -> 233.6. CLAUDE.md estimate: ~233.
        self.assertAlmostEqual(az, 233.6, delta=0.4)
        self.assertAlmostEqual(el, -0.83, delta=0.4)     # on the horizon, refraction included

    def test_summer_solstice_sunset_time_and_azimuth(self):
        s = sun.next_sunset(utc(2027, 6, 21, 20, 0), LAT, LON)
        # ~21:22 PDT = 04:22 UTC on the 22nd
        self.assertLess(abs((s - utc(2027, 6, 22, 4, 22)).total_seconds()), 3 * 60, s)
        az, _ = sun.sun_position(s, LAT, LON)
        self.assertAlmostEqual(az, 308.8, delta=0.4)     # geometric 307.6 + the same offset; brief: ~306

    def test_equinox_sets_due_west(self):
        s = sun.next_sunset(utc(2027, 3, 20, 20, 0), LAT, LON)
        az, _ = sun.sun_position(s, LAT, LON)
        self.assertAlmostEqual(az, 270.0, delta=1.5)

    def test_solar_noon_elevation_winter(self):
        # 90 - lat - 23.44 = 17.3 deg at solar noon; azimuth due south
        best = max((sun.sun_position(utc(2026, 12, 21, 19, 30) + timedelta(minutes=m), LAT, LON)
                    for m in range(0, 120)), key=lambda x: x[1])
        self.assertAlmostEqual(best[1], 17.35, delta=0.3)
        self.assertAlmostEqual(best[0], 180.0, delta=1.5)

    def test_night_sun_below_horizon(self):
        _, el = sun.sun_position(utc(2026, 12, 21, 10, 0), LAT, LON)  # 02:00 PST
        self.assertLess(el, -40)

    def test_swing_between_solstices_matches_brief(self):
        w = sun.sun_position(sun.next_sunset(utc(2026, 12, 21, 20), LAT, LON), LAT, LON)[0]
        s = sun.sun_position(sun.next_sunset(utc(2027, 6, 21, 20), LAT, LON), LAT, LON)[0]
        self.assertAlmostEqual(s - w, 75.0, delta=3)     # brief says ~73 deg

    def test_next_sunset_is_in_future_and_daily(self):
        t = utc(2026, 11, 28, 12, 0)
        prev = None
        for _ in range(400):
            s = sun.next_sunset(t, LAT, LON)
            self.assertGreater(s, t)
            if prev:
                gap = (s - prev).total_seconds() / 3600
                self.assertTrue(23.9 < gap < 24.1, gap)
            prev = s
            t = s + timedelta(minutes=1)

    def test_after_sunset_returns_tomorrows(self):
        s1 = sun.next_sunset(utc(2026, 12, 21, 20, 0), LAT, LON)
        s2 = sun.next_sunset(s1 + timedelta(minutes=5), LAT, LON)
        self.assertAlmostEqual((s2 - s1).total_seconds() / 3600, 24, delta=0.1)

    def test_polar_night_has_no_sunset(self):
        self.assertIsNone(sun.next_sunset(utc(2026, 12, 21, 12), 80.0, 0.0))

    def test_time_parsing(self):
        want = utc(2026, 12, 21, 16, 5, 9)
        for t in ("20261221T160509Z", "2026-12-21T16:05:09Z", "2026-12-21T08:05:09-08:00"):
            self.assertEqual(sun.parse_time(t), want, t)
        with self.assertRaises(ValueError):
            sun.parse_time("tomorrow")


class Sunrise(unittest.TestCase):
    def test_sunrise_matches_the_frames_on_6_november(self):
        # The frames' Sun blocks put the crossing at about 15:08Z (daily-video session, checked on the Pi).
        r = sun.next_sunrise(utc(2026, 11, 6, 12, 0), LAT, LON)
        self.assertLess(abs((r - utc(2026, 11, 6, 15, 8, 20)).total_seconds()), 90, r)

    def test_sunrise_and_sunset_use_the_same_sun_height(self):
        r = sun.next_sunrise(utc(2026, 11, 6, 12, 0), LAT, LON)
        s = sun.next_sunset(utc(2026, 11, 6, 12, 0), LAT, LON)
        self.assertAlmostEqual(sun.sun_position(r, LAT, LON)[1], sun.sun_position(s, LAT, LON)[1], delta=0.05)

    def test_winter_solstice_sunrise(self):
        # ~08:05 PST = 16:05 UTC
        r = sun.next_sunrise(utc(2026, 12, 21, 12, 0), LAT, LON)
        self.assertLess(abs((r - utc(2026, 12, 21, 16, 5)).total_seconds()), 3 * 60, r)


class DenseWindow(unittest.TestCase):
    """1-a-minute frames: sun at -9 deg to sunrise + 60 min, and sunset - 60 min to -9 deg."""
    def window(self, *t):
        return sun.dense_window(utc(*t), LAT, LON)

    def test_around_sunrise(self):
        rise = sun.next_sunrise(utc(2026, 11, 6, 12, 0), LAT, LON)
        self.assertEqual(sun.dense_window(rise, LAT, LON), "sunrise")
        self.assertEqual(sun.dense_window(rise + timedelta(minutes=59), LAT, LON), "sunrise")
        self.assertIsNone(sun.dense_window(rise + timedelta(minutes=61), LAT, LON))

    def test_around_sunset(self):
        sset = sun.next_sunset(utc(2026, 11, 6, 12, 0), LAT, LON)
        self.assertEqual(sun.dense_window(sset, LAT, LON), "sunset")
        self.assertEqual(sun.dense_window(sset - timedelta(minutes=59), LAT, LON), "sunset")
        self.assertIsNone(sun.dense_window(sset - timedelta(minutes=61), LAT, LON))

    def test_dark_ends_at_minus_9_degrees(self):
        sset = sun.next_sunset(utc(2026, 11, 6, 12, 0), LAT, LON)
        t = sset
        while sun.sun_position(t, LAT, LON)[1] >= -9:
            self.assertEqual(sun.dense_window(t, LAT, LON), "sunset")
            t += timedelta(minutes=1)
        self.assertIsNone(sun.dense_window(t, LAT, LON))
        self.assertLess((t - sset).total_seconds(), 90 * 60)   # about an hour at this latitude

    def test_dawn_starts_at_minus_9_degrees(self):
        rise = sun.next_sunrise(utc(2026, 11, 6, 12, 0), LAT, LON)
        t = rise
        while sun.sun_position(t, LAT, LON)[1] >= -9:
            self.assertEqual(sun.dense_window(t, LAT, LON), "sunrise")
            t -= timedelta(minutes=1)
        self.assertIsNone(sun.dense_window(t, LAT, LON))

    def test_midday_and_midnight_are_not_dense(self):
        self.assertIsNone(self.window(2026, 11, 6, 20, 0))     # noon local
        self.assertIsNone(self.window(2026, 11, 6, 9, 0))      # 1 am local
        self.assertIsNone(self.window(2027, 6, 21, 20, 0))     # summer noon
        self.assertIsNone(self.window(2027, 6, 22, 9, 0))      # summer 2 am, sun about -17

    def test_summer_windows_exist(self):
        sset = sun.next_sunset(utc(2027, 6, 21, 12, 0), LAT, LON)
        rise = sun.next_sunrise(utc(2027, 6, 22, 6, 0), LAT, LON)
        self.assertEqual(sun.dense_window(sset + timedelta(minutes=30), LAT, LON), "sunset")
        self.assertEqual(sun.dense_window(rise + timedelta(minutes=30), LAT, LON), "sunrise")


class SunBlockVersion(unittest.TestCase):
    def test_sun_block_names_its_algorithm(self):
        # #27: a later change of formula must be visible in the frames it touched.
        b = sun.sun_block(utc(2026, 12, 21, 23, 58), LAT, LON)
        self.assertEqual(b["algorithm"], "noaa-1")
        for key in ("azimuth_deg", "elevation_deg", "azimuth_ref", "computed_for_utc",
                    "nearest_sunset_utc", "minutes_from_sunset"):
            self.assertIn(key, b)            # existing names unchanged


class MultiYearSweep(unittest.TestCase):
    """The whole five-year run, 2026-12 to 2032-01: one sunset a day about 24 h apart, and the dense
    windows unbroken across UTC midnight (winter sunsets fall around 00:15 UTC) and on 2028-02-29."""
    START, END = utc(2026, 12, 1), utc(2032, 1, 1)

    def test_one_sunset_per_day_about_24_hours_apart(self):
        t, prev, days = self.START, None, set()
        while t < self.END:
            s = sun.next_sunset(t, LAT, LON)
            if prev is not None:
                gap = (s - prev).total_seconds() / 3600
                self.assertTrue(23.9 < gap < 24.1, (s, gap))
            local_day = (s - timedelta(hours=8)).date()   # one sunset per local (PST) day
            self.assertNotIn(local_day, days, s)
            days.add(local_day)
            prev, t = s, s + timedelta(minutes=1)
        self.assertGreater(len(days), 5 * 365)

    def test_dense_windows_cover_every_sunrise_and_sunset(self):
        day = self.START
        while day < self.END:
            noon = day + timedelta(hours=20)                 # about local noon
            sset, rise = sun.next_sunset(noon, LAT, LON), sun.next_sunrise(day + timedelta(hours=8), LAT, LON)
            self.assertEqual(sun.dense_window(sset, LAT, LON), "sunset", sset)
            self.assertEqual(sun.dense_window(sset - timedelta(minutes=59), LAT, LON), "sunset", sset)
            self.assertEqual(sun.dense_window(rise, LAT, LON), "sunrise", rise)
            self.assertEqual(sun.dense_window(rise + timedelta(minutes=59), LAT, LON), "sunrise", rise)
            day += timedelta(days=1)

    def test_no_gap_in_a_window_at_utc_midnight(self):
        day = self.START
        while day < self.END:
            seen = [sun.dense_window(day + timedelta(minutes=m), LAT, LON) for m in range(-5, 6)]
            changes = sum(1 for a, b in zip(seen, seen[1:]) if a != b)
            self.assertLessEqual(changes, 1, (day, seen))
            day += timedelta(days=1)

    def test_leap_day_windows_are_contiguous(self):
        start = utc(2028, 2, 28, 8)                          # midnight PST, 28 Feb to 2 Mar 2028
        runs = []
        for m in range(3 * 24 * 60):
            w = sun.dense_window(start + timedelta(minutes=m), LAT, LON)
            if runs and runs[-1][0] == w:
                runs[-1][1] += 1
            else:
                runs.append([w, 1])
        windows = [(w, n) for w, n in runs if w]
        self.assertEqual([w for w, _ in windows], ["sunrise", "sunset"] * 3)
        for w, minutes in windows:
            self.assertTrue(90 <= minutes <= 150, (w, minutes))


class Cli(unittest.TestCase):
    def run_cli(self, *args, env=None):
        e = dict(os.environ)
        e.pop("SITE_LAT", None); e.pop("SITE_LON", None)
        e.update(env or {})
        return subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True, env=e)

    def test_annotate_merges_without_losing_fields_or_leaking_site(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.json")
            with open(p, "w") as f:
                json.dump({"ExposureTime": 1000, "Lux": 12.5}, f)
            r = self.run_cli("annotate", p, "--time", "20261221T235800Z",
                             env={"SITE_LAT": str(LAT), "SITE_LON": str(LON)})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertRegex(r.stdout.strip(), r"^az=\d+\.\d el=-?\d+\.\d$")
            with open(p) as f:
                data = json.load(f)
            self.assertEqual(data["ExposureTime"], 1000)
            self.assertEqual(data["Lux"], 12.5)
            self.assertIn("azimuth_deg", data["Sun"])
            self.assertIn("minutes_from_sunset", data["Sun"])
            self.assertAlmostEqual(data["Sun"]["minutes_from_sunset"], -16, delta=4)
            self.assertNotIn(str(LAT), json.dumps(data))   # exact site stays out of frame files
            self.assertEqual(os.listdir(d), ["f.json"])    # no temp file left behind

    def annotate_file(self, content):
        """Run annotate on a file holding `content` (None: no file at all). Returns (result, data)."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "f.json")
        if content is not None:
            with open(p, "w") as f:
                f.write(content)
        r = self.run_cli("annotate", p, "--time", "20261221T235800Z",
                         env={"SITE_LAT": str(LAT), "SITE_LON": str(LON)})
        with open(p) as f:
            data = json.load(f)
        self.assertEqual(os.listdir(d), ["f.json"])
        return r, data

    def test_annotate_bad_json_starts_again_and_says_so(self):
        # #27: Sun can be computed without rpicam's metadata, so the frame still gets its JSON.
        r, data = self.annotate_file("{not json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(data["rpicam_metadata"], "invalid")
        self.assertIn("azimuth_deg", data["Sun"])
        self.assertIn("rpicam=invalid", r.stdout)

    def test_annotate_missing_metadata_file_starts_from_nothing(self):
        r, data = self.annotate_file(None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(data["rpicam_metadata"], "missing")
        self.assertIn("minutes_from_sunset", data["Sun"])
        self.assertRegex(r.stdout.strip(), r"^az=\d+\.\d el=-?\d+\.\d rpicam=missing$")

    def test_annotate_top_level_not_an_object_is_invalid(self):
        r, data = self.annotate_file("[1, 2]")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(data["rpicam_metadata"], "invalid")

    def test_annotate_good_metadata_is_not_flagged(self):
        r, data = self.annotate_file('{"Lux": 3}')
        self.assertNotIn("rpicam_metadata", data)
        self.assertNotIn("rpicam=", r.stdout)

    def test_annotate_into_a_missing_folder_is_still_an_error(self):
        r = self.run_cli("annotate", os.path.join(tempfile.gettempdir(), "no-such-dir-sun", "f.json"),
                         env={"SITE_LAT": str(LAT), "SITE_LON": str(LON)})
        self.assertEqual(r.returncode, 2)

    def test_bad_time_is_still_an_error(self):
        r = self.run_cli("position", "--time", "tomorrow", env={"SITE_LAT": str(LAT), "SITE_LON": str(LON)})
        self.assertEqual(r.returncode, 2)

    def test_missing_site_is_an_error(self):
        r = self.run_cli("position")
        self.assertEqual(r.returncode, 2)
        self.assertIn("SITE_LAT", r.stderr)

    def test_sunset_epoch_and_json(self):
        env = {"SITE_LAT": str(LAT), "SITE_LON": str(LON)}
        e = self.run_cli("sunset", "--after", "2026-12-21T20:00:00Z", "--epoch", env=env)
        j = json.loads(self.run_cli("sunset", "--after", "2026-12-21T20:00:00Z", "--json", env=env).stdout)
        self.assertEqual(int(e.stdout), j["epoch"])
        self.assertTrue(j["sunset_utc"].startswith("2026-12-22T00:1"))

    def test_dense_exit_status(self):
        env = {"SITE_LAT": str(LAT), "SITE_LON": str(LON)}
        r = self.run_cli("dense", "--time", "20261107T003000Z", env=env)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "sunset"))
        r = self.run_cli("dense", "--time", "20261106T153000Z", env=env)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "sunrise"))
        r = self.run_cli("dense", "--time", "20261106T200000Z", env=env)
        self.assertEqual((r.returncode, r.stdout.strip()), (1, "none"))
        self.assertEqual(self.run_cli("dense").returncode, 2)   # no site


if __name__ == "__main__":
    unittest.main(verbosity=1)
