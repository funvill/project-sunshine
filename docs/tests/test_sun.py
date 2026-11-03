"""Tests for sunset-sun.py. Reference values are standard published figures for
~49.25N 123W, to the tolerance noted; run with: python3 tests/test_sun.py"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "sunset-sun.py")
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

    def test_annotate_bad_json_leaves_file_alone(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.json")
            with open(p, "w") as f:
                f.write("{not json")
            r = self.run_cli("annotate", p, env={"SITE_LAT": "49", "SITE_LON": "-123"})
            self.assertEqual(r.returncode, 2)
            with open(p) as f:
                self.assertEqual(f.read(), "{not json")

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


if __name__ == "__main__":
    unittest.main(verbosity=1)
