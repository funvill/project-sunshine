"""Tests for tools/fog_scan.py: python3 tests/test_fog_scan.py (skipped without numpy and OpenCV)"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

try:
    import cv2
    import numpy as np
except ImportError:
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))
UTC = timezone.utc


def load():
    spec = importlib.util.spec_from_file_location("fog_scan", os.path.join(os.path.dirname(HERE), "tools", "fog_scan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scene(blur=0, seed=1, h=240, w=320):
    """A sky over a 'skyline' of random blocks; blur stands in for fog or condensation."""
    rng = np.random.RandomState(seed)
    img = np.full((h, w), 170, np.uint8)
    for _ in range(60):
        x, y = rng.randint(0, w - 20), rng.randint(int(h * 0.35), int(h * 0.85))
        img[y:y + rng.randint(5, 40), x:x + rng.randint(3, 20)] = rng.randint(20, 120)
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    return img


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class Measure(unittest.TestCase):
    def setUp(self):
        self.fs = load()

    def test_a_blurred_scene_reads_less_sharp_and_less_contrasty(self):
        sharp, foggy = self.fs.measure(scene()), self.fs.measure(scene(blur=4))
        self.assertLess(foggy["sharpness"], sharp["sharpness"] * 0.3)
        self.assertLess(foggy["contrast"], sharp["contrast"])

    def test_only_the_band_counts(self):
        img = scene()
        top = img.copy()
        top[: int(img.shape[0] * 0.3)] = np.random.RandomState(2).randint(0, 255, (int(img.shape[0] * 0.3), img.shape[1]))
        self.assertAlmostEqual(self.fs.measure(img)["sharpness"], self.fs.measure(top)["sharpness"], places=6)

    def test_brightness_alone_does_not_change_sharpness_much(self):
        # an evening frame is darker but no less clear: sharpness is measured on the log of the brightness
        img = scene().astype(np.float32)
        dim = np.clip(img * 0.5, 0, 255).astype(np.uint8)
        a, b = self.fs.measure(img.astype(np.uint8))["sharpness"], self.fs.measure(dim)["sharpness"]
        self.assertLess(abs(a - b) / a, 0.25)


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class Frames(unittest.TestCase):
    def setUp(self):
        self.fs = load()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def add(self, t, suffix="", lux=500.0, el=20.0, setup="pilot-4", img=None):
        folder = os.path.join(self.dir, t.strftime("%Y/%m/%d"))
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, "wide_%s%s" % (t.strftime("%Y%m%dT%H%M%SZ"), suffix))
        cv2.imwrite(base + ".jpg", scene() if img is None else img)
        with open(base + ".json", "w") as f:
            json.dump({"Lux": lux, "Sun": {"elevation_deg": el}, "Capture": {"setup_id": setup}}, f)
        return base + ".jpg"

    def test_lists_regular_frames_only_at_the_step(self):
        t0 = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)
        for m in range(0, 30, 5):
            self.add(t0 + timedelta(minutes=m))
        self.add(t0, "_night")
        self.add(t0, "_ev0")
        self.add(t0 + timedelta(minutes=1, seconds=12))      # a dense frame
        found = self.fs.list_frames(self.dir, "wide", t0.date(), t0.date(), every_min=15)
        self.assertEqual([f["time"] for f in found], [t0, t0 + timedelta(minutes=15)])
        self.assertEqual(found[0]["lux"], 500.0)
        self.assertEqual(found[0]["elevation"], 20.0)
        self.assertEqual(found[0]["setup_id"], "pilot-4")

    def test_scan_caches_each_finished_day(self):
        t0 = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)
        self.add(t0)
        out = os.path.join(self.dir, "out")
        rows = self.fs.scan(self.dir, "wide", t0.date(), t0.date(), out, every_min=5, today=t0.date() + timedelta(days=1))
        self.assertEqual(len(rows), 1)
        cache = os.path.join(out, "wide", "2026-11-14.csv")
        self.assertTrue(os.path.exists(cache))
        os.remove(os.path.join(self.dir, "2026/11/14", "wide_20261114T200000Z.jpg"))
        again = self.fs.scan(self.dir, "wide", t0.date(), t0.date(), out, every_min=5, today=t0.date() + timedelta(days=1))
        self.assertAlmostEqual(again[0]["sharpness"], rows[0]["sharpness"], places=3)


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class Clarity(unittest.TestCase):
    def setUp(self):
        self.fs = load()

    def rows(self, days=8, foggy_day=None, foggy_hours=(), setup=lambda d: "a"):
        out, t0 = [], datetime(2026, 11, 4, tzinfo=UTC)
        for d in range(days):
            for hour in range(24):
                t = t0 + timedelta(days=d, hours=hour)
                fog = d == foggy_day and hour in foggy_hours
                out.append({"time": t, "sharpness": 20.0 if fog else 100.0 + hour, "contrast": 30.0, "mean": 100.0,
                            "lux": 500.0, "elevation": 20.0 if 16 <= hour <= 23 else -20.0, "setup_id": setup(d)})
        return out

    def test_a_normal_day_reads_about_one(self):
        rows = self.fs.add_clarity(self.rows())
        last = [r["clarity"] for r in rows if r["time"].day == 11]
        self.assertTrue(all(abs(c - 1.0) < 0.01 for c in last))

    def test_the_first_days_have_no_baseline(self):
        rows = self.fs.add_clarity(self.rows(), min_baseline=3)
        self.assertIsNone(rows[0]["clarity"])

    def test_fog_reads_low(self):
        rows = self.fs.add_clarity(self.rows(foggy_day=7, foggy_hours=(17, 18, 19)))
        fog = [r["clarity"] for r in rows if r["time"].day == 11 and r["time"].hour in (17, 18, 19)]
        self.assertTrue(all(c < 0.3 for c in fog))

    def test_a_setup_change_restarts_the_baseline(self):
        rows = self.fs.add_clarity(self.rows(setup=lambda d: "a" if d < 6 else "b"), min_baseline=3)
        self.assertIsNone(next(r for r in rows if r["time"].day == 10)["clarity"])

    def test_low_runs_finds_the_daylight_run_only(self):
        rows = self.fs.add_clarity(self.rows(foggy_day=7, foggy_hours=(2, 3, 4, 17, 18, 19)))
        runs = self.fs.low_runs(rows, threshold=0.5, min_frames=3)
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0]["start"].hour, runs[0]["end"].hour, runs[0]["frames"]), (17, 19, 3))
        self.assertLess(runs[0]["min_clarity"], 0.3)


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class Glare(unittest.TestCase):
    """A low sun in front of the west window flares the glass: that is glare, not fog (#33)."""

    def setUp(self):
        self.fs = load()

    def test_sun_on_glass_needs_a_low_sun_in_front_of_the_window(self):
        self.assertTrue(self.fs.sun_on_glass(227.0, 9.2))          # Nov 15, 23:15 UTC: flare
        self.assertFalse(self.fs.sun_on_glass(200.3, 21.2))        # Nov 10, 21:15 UTC: high, south-west
        self.assertFalse(self.fs.sun_on_glass(150.0, 10.0))        # low, but behind the building
        self.assertFalse(self.fs.sun_on_glass(270.0, -1.0))        # set
        self.assertFalse(self.fs.sun_on_glass(None, 9.0))          # unknown counts as no
        self.assertTrue(self.fs.sun_on_glass(320.0, 14.0))
        self.assertFalse(self.fs.sun_on_glass(320.0, 14.0, max_elevation=10.0))
        self.assertFalse(self.fs.sun_on_glass(320.0, 14.0, half_width=40.0))

    def rows(self, el, az):
        t0 = datetime(2026, 11, 15, 22, 0, tzinfo=UTC)
        return [{"time": t0 + timedelta(minutes=5 * i), "clarity": 0.3, "elevation": el, "azimuth": az}
                for i in range(4)]

    def test_runs_get_a_cause(self):
        self.assertEqual(self.fs.low_runs(self.rows(9.0, 227.0))[0]["cause"], "glare")
        self.assertEqual(self.fs.low_runs(self.rows(20.0, 200.0))[0]["cause"], "fog")

    def test_a_run_is_glare_only_when_most_frames_have_the_sun_on_the_glass(self):
        rows = self.rows(20.0, 200.0)
        rows[0].update(elevation=9.0, azimuth=227.0)
        self.assertEqual(self.fs.low_runs(rows)[0]["cause"], "fog")
        for r in rows[:3]:
            r.update(elevation=9.0, azimuth=227.0)
        self.assertEqual(self.fs.low_runs(rows)[0]["cause"], "glare")

    def test_frames_carry_the_azimuth_and_old_caches_are_read_again(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        t = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)
        folder = os.path.join(d, "2026/11/14")
        os.makedirs(folder)
        cv2.imwrite(os.path.join(folder, "wide_20261114T200000Z.jpg"), scene())
        with open(os.path.join(folder, "wide_20261114T200000Z.json"), "w") as f:
            json.dump({"Sun": {"elevation_deg": 9.0, "azimuth_deg": 227.0}}, f)
        self.assertEqual(self.fs.list_frames(d, "wide", t.date(), t.date())[0]["azimuth"], 227.0)
        old = os.path.join(d, "old.csv")
        with open(old, "w") as f:      # a cache written before the azimuth column
            f.write("# every_min=5\ntime,sharpness,contrast,mean,lux,elevation,setup_id\n"
                    "2026-11-14T20:00:00Z,1,1,1,1,9,a\n")
        self.assertIsNone(self.fs.read_rows(old, 5))
        out = os.path.join(d, "out")
        first = self.fs.scan(d, "wide", t.date(), t.date(), out, today=t.date() + timedelta(days=1))
        again = self.fs.scan(d, "wide", t.date(), t.date(), out, today=t.date() + timedelta(days=1))
        self.assertEqual(again[0]["azimuth"], 227.0)
        self.assertEqual(first[0]["azimuth"], 227.0)


if __name__ == "__main__":
    unittest.main()
