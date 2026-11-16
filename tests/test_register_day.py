"""Tests for tools/register_day.py: python3 tests/test_register_day.py (skipped without numpy and OpenCV)

Synthetic scenes only: a random skyline of towers with window grids under a sky that is
replaced from frame to frame. Nothing here has seen a real frame.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = np = None

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "tools", "register_day.py")

# Tolerances these tests hold the tool to, in full-resolution pixels.
SUBPIXEL_TOL = 0.5     # small shifts, day scene
LARGE_TOL = 1.0        # 600 px shifts
NIGHT_TOL = 1.0
ROT_TOL_DEG = 0.08     # measured worst 0.046 (0.3 deg with 0.995 scale); some room for other OpenCV builds
SCALE_TOL = 0.002


def load():
    spec = importlib.util.spec_from_file_location("register_day", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MARGIN = 700   # the scene is drawn this much larger on every side, so a shift never shows an edge


def skyline(seed, width, height, night_seed=None):
    """(buildings, sky mask) on a canvas MARGIN larger on every side. Tops of the towers are
    between 35% and 70% of the frame height, so the matching band holds sky as well."""
    rng = np.random.default_rng(seed)
    lit = np.random.default_rng(night_seed) if night_seed is not None else None
    w, h = width + 2 * MARGIN, height + 2 * MARGIN
    img = np.full((h, w), 5.0, np.float32)
    sky = np.ones((h, w), bool)
    x = 0
    while x < w:
        bw = int(rng.integers(30, 160))
        top = int(MARGIN + height * rng.uniform(0.35, 0.7))
        shade = rng.uniform(40, 140)
        img[top:, x:x + bw] = 12.0 if lit else shade
        sky[top:, x:x + bw] = False
        for wy in range(top + 8, h, int(rng.integers(12, 24))):
            for wx in range(x + 5, x + bw - 8, int(rng.integers(10, 20))):
                dim = rng.uniform(0.4, 0.8)
                if lit is None:
                    img[wy:wy + 6, wx:wx + 5] = shade * dim
                elif lit.uniform() < 0.4:
                    img[wy:wy + 6, wx:wx + 5] = lit.uniform(120, 250)
        x += bw + int(rng.integers(0, 20))
    return img, sky


def gradient_sky(top=200, bottom=120):
    return lambda rng, h, w: np.tile(np.linspace(top, bottom, h, dtype=np.float32)[:, None], (1, w))


def noise_sky(rng, h, w):
    return rng.uniform(0, 255, (h, w)).astype(np.float32)


def cloud_sky(rng, h, w):
    small = rng.uniform(60, 240, (h // 40 + 2, w // 40 + 2)).astype(np.float32)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def dark_sky(rng, h, w):
    return np.full((h, w), 20.0, np.float32)


def render(scene, width, height, dx=0.0, dy=0.0, rot=0.0, scale=1.0, sky=None, gain=1.0, sun=None,
           seed=0, noise=3.0):
    """One 8-bit frame: the scene moved by (dx, dy), turned `rot` degrees counter-clockwise and
    scaled about the frame centre, with its own sky, brightness, sun and sensor noise."""
    img, mask = scene
    rng = np.random.default_rng(seed)
    h, w = img.shape
    sky_img = (sky or gradient_sky())(rng, h, w)
    full = np.where(mask, sky_img, img * gain)
    if sun is not None:
        yy, xx = np.mgrid[0:h, 0:w]
        full = full + 250 * np.exp(-((xx - sun[0] - MARGIN) ** 2 + (yy - sun[1] - MARGIN) ** 2) / (2 * 40.0 ** 2))
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), rot, scale)
    m[0, 2] += dx
    m[1, 2] += dy
    out = cv2.warpAffine(full.astype(np.float32), m, (w, h), flags=cv2.INTER_LINEAR)
    out = out[MARGIN:MARGIN + height, MARGIN:MARGIN + width] + rng.normal(0, noise, (height, width))
    return np.clip(out, 0, 255).astype(np.uint8)


def expected_at_band_centre(width, height, dx, dy, rot, scale, band):
    """Where the middle of the matching band moves to under the render() transform."""
    cx, cy = width / 2.0, height * (band[0] + band[1]) / 2.0
    m = cv2.getRotationMatrix2D((width / 2.0 + MARGIN, height / 2.0 + MARGIN), rot, scale)
    m[0, 2] += dx
    m[1, 2] += dy
    p = m @ np.array([cx + MARGIN, cy + MARGIN, 1.0])
    return p[0] - MARGIN - cx, p[1] - MARGIN - cy


@unittest.skipIf(np is None, "needs numpy and OpenCV: pip install numpy opencv-python-headless")
class Measure(unittest.TestCase):
    W, H = 1600, 1200

    @classmethod
    def setUpClass(cls):
        cls.rd = load()
        cls.scene = skyline(1, cls.W, cls.H)
        cls.ref = render(cls.scene, cls.W, cls.H)
        cls.settings = cls.rd.Settings(work_scale=1.0)

    def measure(self, frame, settings=None):
        return self.rd.measure_pair(self.ref, frame, settings or self.settings)

    def assert_shift(self, got, dx, dy, tol):
        self.assertAlmostEqual(got["phase"]["dx_px"], dx, delta=tol, msg=got)
        self.assertAlmostEqual(got["phase"]["dy_px"], dy, delta=tol, msg=got)
        self.assertGreaterEqual(got["phase"]["response"], self.settings.min_response, got)
        self.assertTrue(got["used"], got)

    def test_sub_pixel_shift(self):
        for dx, dy in ((3.3, -1.7), (-0.6, 0.4), (12.25, 7.75)):
            with self.subTest(dx=dx, dy=dy):
                got = self.measure(render(self.scene, self.W, self.H, dx, dy, seed=5))
                self.assert_shift(got, dx, dy, SUBPIXEL_TOL)

    def test_no_shift_reads_as_none(self):
        got = self.measure(render(self.scene, self.W, self.H, seed=9, sky=cloud_sky))
        self.assert_shift(got, 0, 0, SUBPIXEL_TOL)

    def test_large_shifts_of_600_px(self):
        for dx, dy in ((600, 0), (-600, 150), (0, -300)):
            with self.subTest(dx=dx, dy=dy):
                got = self.measure(render(self.scene, self.W, self.H, dx, dy, seed=6))
                self.assert_shift(got, dx, dy, LARGE_TOL)

    def test_half_scale_work_gives_full_resolution_pixels(self):
        settings = self.rd.Settings(work_scale=0.5)
        got = self.measure(render(self.scene, self.W, self.H, 41.5, -13.0, seed=7), settings)
        self.assert_shift(got, 41.5, -13.0, 2 * SUBPIXEL_TOL)

    def test_lighting_sky_and_sun_do_not_move_the_answer(self):
        cases = [dict(gain=0.5, sky=noise_sky, sun=(800, 500)),
                 dict(gain=1.6, sky=gradient_sky(30, 250), sun=(300, 650)),
                 dict(gain=0.8, sky=cloud_sky, sun=(1200, 700)),
                 dict(gain=0.3, sky=gradient_sky(250, 250))]
        for i, kw in enumerate(cases):
            with self.subTest(case=i):
                got = self.measure(render(self.scene, self.W, self.H, 10.0, -4.0, seed=20 + i, **kw))
                self.assert_shift(got, 10.0, -4.0, SUBPIXEL_TOL)

    def test_rotation_and_scale_from_the_feature_match(self):
        band = self.settings.band
        for rot, scale in ((0.5, 1.0), (-1.0, 1.0), (0.0, 1.01), (0.3, 0.995)):
            with self.subTest(rot=rot, scale=scale):
                got = self.measure(render(self.scene, self.W, self.H, 20.0, 0.0, rot=rot, scale=scale, seed=8))
                orb = got["orb"]
                self.assertTrue(orb and orb["ok"], got)
                self.assertAlmostEqual(orb["rotation_deg"], rot, delta=ROT_TOL_DEG)
                self.assertAlmostEqual(orb["scale"], scale, delta=SCALE_TOL)
                ex, ey = expected_at_band_centre(self.W, self.H, 20.0, 0.0, rot, scale, band)
                self.assertAlmostEqual(orb["dx_px"], ex, delta=1.0)
                self.assertAlmostEqual(orb["dy_px"], ey, delta=1.0)

    def test_methods_agree_on_a_pure_shift(self):
        got = self.measure(render(self.scene, self.W, self.H, 25.0, 5.0, seed=11))
        self.assertTrue(got["orb"]["ok"])
        self.assertFalse(got["methods_disagree"], got)

    def test_unrelated_skyline_is_low_confidence_not_a_confident_answer(self):
        other = skyline(99, self.W, self.H)
        got = self.measure(render(other, self.W, self.H, seed=3))
        self.assertLess(got["phase"]["response"], self.settings.min_response, got)
        self.assertFalse(got["used"])
        self.assertFalse(got["orb"]["ok"], got)

    def test_noise_is_low_confidence(self):
        got = self.measure(np.random.default_rng(3).integers(0, 256, (self.H, self.W)).astype(np.uint8))
        self.assertLess(got["phase"]["response"], self.settings.min_response)
        self.assertFalse(got["used"])

    def test_size_mismatch_is_reported_not_raised(self):
        got = self.measure(np.zeros((100, 100), np.uint8))
        self.assertFalse(got["used"])
        self.assertIn("size", got["error"])


@unittest.skipIf(np is None, "needs numpy and OpenCV: pip install numpy opencv-python-headless")
class Summary(unittest.TestCase):
    def setUp(self):
        self.rd = load()
        self.settings = self.rd.Settings()

    def m(self, dx, dy, response=0.5, rot=None, scale=None):
        orb = None if rot is None else {"ok": True, "rotation_deg": rot, "scale": scale, "dx_px": dx, "dy_px": dy}
        return {"phase": {"dx_px": dx, "dy_px": dy, "response": response},
                "used": response >= self.settings.min_response, "orb": orb}

    def test_median_resists_one_bad_frame_even_a_confident_one(self):
        ms = [self.m(5.0, 2.0), self.m(5.2, 1.9), self.m(4.9, 2.1), self.m(5.1, 2.0),
              self.m(40.0, -30.0, response=0.6)]
        s = self.rd.summarise(ms, self.settings)
        self.assertAlmostEqual(s["dx_px"], 5.1, delta=0.2)
        self.assertAlmostEqual(s["dy_px"], 2.0, delta=0.2)
        self.assertLess(s["spread_px"], 0.5)
        self.assertTrue(s["reliable"])

    def test_low_response_frames_are_left_out(self):
        ms = [self.m(5.0, 2.0), self.m(5.0, 2.0), self.m(80.0, 80.0, response=0.02)]
        s = self.rd.summarise(ms, self.settings)
        self.assertEqual(s["frames_used"], 2)
        self.assertEqual(s["frames_measured"], 3)
        self.assertAlmostEqual(s["dx_px"], 5.0)

    def test_nothing_usable_is_unreliable_with_no_numbers(self):
        s = self.rd.summarise([self.m(1, 1, response=0.01)], self.settings)
        self.assertFalse(s["reliable"])
        self.assertIsNone(s["dx_px"])
        self.assertEqual(s["confidence"], 0.0)

    def test_scattered_frames_are_unreliable(self):
        ms = [self.m(0, 0), self.m(10, 0), self.m(20, 0), self.m(30, 0)]
        self.assertFalse(self.rd.summarise(ms, self.settings)["reliable"])

    def test_rotation_is_the_median_of_the_feature_matches(self):
        ms = [self.m(5, 2, rot=0.2, scale=1.001), self.m(5, 2, rot=0.21, scale=1.0), self.m(5, 2, rot=5.0, scale=1.2)]
        s = self.rd.summarise(ms, self.settings)
        self.assertAlmostEqual(s["rotation_deg"], 0.21)
        self.assertAlmostEqual(s["scale"], 1.001)

    def test_moved_against_the_thresholds(self):
        still = self.rd.summarise([self.m(0.5, -0.4), self.m(0.6, -0.3)], self.settings)
        nudged = self.rd.summarise([self.m(8.0, 0.0), self.m(8.2, 0.1)], self.settings)
        turned = self.rd.summarise([self.m(0.0, 0.0, rot=0.5, scale=1.0), self.m(0.0, 0.0, rot=0.5, scale=1.0)],
                                   self.settings)
        self.assertEqual(self.rd.decide_moved(still, None, self.settings)[0], False)
        self.assertEqual(self.rd.decide_moved(nudged, None, self.settings)[0], True)
        self.assertEqual(self.rd.decide_moved(turned, None, self.settings)[0], True)
        unsure = self.rd.summarise([self.m(1, 1, response=0.01)], self.settings)
        self.assertIsNone(self.rd.decide_moved(unsure, unsure, self.settings)[0])
        self.assertEqual(self.rd.decide_moved(unsure, nudged, self.settings)[0], True)


@unittest.skipIf(np is None, "needs numpy and OpenCV: pip install numpy opencv-python-headless")
class Day(unittest.TestCase):
    """A whole UTC day folder: daytime frames, night frames, a dark auto frame, an old frame."""
    W, H = 1200, 900
    CAM = "cm4wide"

    @classmethod
    def setUpClass(cls):
        cls.rd = load()
        cls.scene = skyline(4, cls.W, cls.H)
        cls.night = [skyline(4, cls.W, cls.H, night_seed=s) for s in (50, 51, 52, 53)]

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.frames = os.path.join(self.dir, "frames", self.CAM)
        self.day = os.path.join(self.frames, "2026", "11", "14")
        os.makedirs(self.day)
        self.out = os.path.join(self.dir, "out")
        self.refdir = os.path.join(self.dir, "refs")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def put(self, stamp, image, elevation=None, setup="cm4-window-1", night=False, sun=True):
        base = os.path.join(self.day, "%s_%s%s" % (self.CAM, stamp, "_night" if night else ""))
        cv2.imwrite(base + ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        data = {"ExposureTime": 1000}
        if sun:
            data["Sun"] = {"azimuth_deg": 200.0, "elevation_deg": elevation, "azimuth_ref": "true_north"}
        if setup:
            data["Capture"] = {"schema_version": 1, "camera": self.CAM, "kind": "night" if night else "auto",
                               "schedule": "regular", "setup_id": setup}
        with open(base + ".json", "w") as f:
            json.dump(data, f)
        return base + ".jpg"

    def build(self, dx, dy, bad_frame=False):
        skies = [gradient_sky(), noise_sky, cloud_sky, gradient_sky(40, 230), cloud_sky, gradient_sky(250, 90)]
        for i, sky in enumerate(skies):
            img = render(self.scene, self.W, self.H, dx, dy, sky=sky, gain=0.6 + 0.15 * i, seed=100 + i,
                         sun=(150 * i + 100, 450))
            if bad_frame and i == 2:
                img = render(skyline(77, self.W, self.H), self.W, self.H, seed=1)
            self.put("20261114T%02d0000Z" % (17 + i), img, elevation=8.0 + i, setup="cm4-window-1" if i else None)
        # dark auto frames and one in the early morning: not daytime, so not used
        self.put("20261114T060000Z", render(self.night[0], self.W, self.H, dx, dy, sky=dark_sky), elevation=-30.0)
        self.put("20261114T160000Z", render(self.scene, self.W, self.H, dx, dy, seed=3), elevation=2.0)
        for i, scene in enumerate(self.night[1:]):
            self.put("20261114T%02d0000Z" % (8 + i), render(scene, self.W, self.H, dx, dy, sky=dark_sky, seed=60 + i),
                     elevation=-40.0, night=True)

    def reference(self):
        ref_day = os.path.join(self.dir, "refsrc")
        os.makedirs(ref_day)
        src = os.path.join(ref_day, "%s_20261101T200000Z.jpg" % self.CAM)
        cv2.imwrite(src, render(self.scene, self.W, self.H, seed=500), [cv2.IMWRITE_JPEG_QUALITY, 95])
        with open(src[:-4] + ".json", "w") as f:
            json.dump({"Sun": {"elevation_deg": 15.0}, "Capture": {"setup_id": "cm4-window-1"}}, f)
        nsrc = os.path.join(ref_day, "%s_20261101T080000Z_night.jpg" % self.CAM)
        cv2.imwrite(nsrc, render(self.night[0], self.W, self.H, sky=dark_sky, seed=501), [cv2.IMWRITE_JPEG_QUALITY, 95])
        ref = os.path.join(self.refdir, "cm4wide-day.jpg")
        nref = os.path.join(self.refdir, "cm4wide-night.jpg")
        self.rd.make_reference(src, ref)
        self.rd.make_reference(nsrc, nref)
        return ref, nref

    def hashes(self):
        out = {}
        for name in sorted(os.listdir(self.day)):
            with open(os.path.join(self.day, name), "rb") as f:
                out[name] = hashlib.sha256(f.read()).hexdigest()
        return out

    def run_day(self, ref, nref=None, **kw):
        # These frames are 1200 px wide, a real one 4056. At full size here the windows are about
        # as many pixels as at the default 0.5 on a real frame; at 0.5 here the synthetic night
        # frames drop under the response limit (0.13 against 0.15), so the night test would test nothing.
        settings = self.rd.Settings(work_scale=1.0, **kw)
        return self.rd.register_day(self.frames, self.CAM, "2026-11-14", ref, self.out, settings, night_reference=nref)

    def test_reference_sidecar(self):
        ref, _ = self.reference()
        with open(ref[:-4] + ".json") as f:
            side = json.load(f)
        self.assertEqual(side["setup_id"], "cm4-window-1")
        self.assertEqual(side["source_frame"], "cm4wide_20261101T200000Z.jpg")
        with open(ref, "rb") as f:
            self.assertEqual(side["sha256"], hashlib.sha256(f.read()).hexdigest())
        with self.assertRaises(FileExistsError):
            self.rd.make_reference(os.path.join(self.dir, "refsrc", "cm4wide_20261101T200000Z.jpg"), ref)

    def test_a_nudged_camera_is_found_and_frames_are_untouched(self):
        self.build(9.0, -3.0)
        ref, nref = self.reference()
        before = self.hashes()
        record = self.run_day(ref, nref)
        self.assertEqual(self.hashes(), before, "frames must never change")
        path = os.path.join(self.out, self.CAM, "2026-11-14.json")
        with open(path) as f:
            saved = json.load(f)
        self.assertEqual(saved, record)
        self.assertFalse([n for n in os.listdir(os.path.dirname(path)) if n.endswith(".tmp")])
        self.assertEqual(saved["schema_version"], 1)
        self.assertEqual(saved["camera"], self.CAM)
        self.assertEqual(saved["day_utc"], "2026-11-14")
        self.assertEqual(saved["reference"]["setup_id"], "cm4-window-1")
        self.assertEqual(saved["setup_ids_seen"], ["cm4-window-1"])
        self.assertEqual(saved["frames_without_setup_id"], 1)
        day, night = saved["day"], saved["night"]
        self.assertEqual(day["frames_measured"], 6)
        self.assertEqual(night["frames_measured"], 3)
        self.assertTrue(day["reliable"], day)
        self.assertAlmostEqual(day["dx_px"], 9.0, delta=2 * SUBPIXEL_TOL)
        self.assertAlmostEqual(day["dy_px"], -3.0, delta=2 * SUBPIXEL_TOL)
        self.assertTrue(night["reliable"], night)
        self.assertAlmostEqual(night["dx_px"], 9.0, delta=2 * NIGHT_TOL)
        self.assertAlmostEqual(night["dy_px"], -3.0, delta=2 * NIGHT_TOL)
        self.assertIs(saved["moved"], True)
        names = {m["frame"] for m in saved["frames"]}
        self.assertNotIn("cm4wide_20261114T160000Z.jpg", names, "sun at 2 deg is not daytime")
        self.assertNotIn("cm4wide_20261114T060000Z.jpg", names)

    def test_a_still_camera_is_not_moved(self):
        self.build(0.3, -0.2)
        ref, nref = self.reference()
        record = self.run_day(ref, nref)
        self.assertIs(record["moved"], False, record["day"])

    def test_one_bad_frame_does_not_set_the_day(self):
        self.build(9.0, -3.0, bad_frame=True)
        ref, nref = self.reference()
        day = self.run_day(ref, nref)["day"]
        self.assertEqual(day["frames_used"], 5, day)
        self.assertAlmostEqual(day["dx_px"], 9.0, delta=2 * SUBPIXEL_TOL)

    def test_fewer_frames_when_asked(self):
        self.build(0, 0)
        ref, _ = self.reference()
        record = self.run_day(ref, day_frames=3, night_frames=1)
        self.assertEqual(record["day"]["frames_measured"], 3)
        self.assertEqual(record["night"]["frames_measured"], 1)
        self.assertIsNone(record["night_reference"])

    def test_an_empty_day_writes_a_record_that_says_so(self):
        ref, _ = self.reference()
        shutil.rmtree(self.day)
        record = self.run_day(ref)
        self.assertEqual(record["day"]["frames_measured"], 0)
        self.assertIsNone(record["moved"])

    def test_command_line(self):
        self.build(9.0, -3.0)
        src = os.path.join(self.day, "%s_20261114T170000Z.jpg" % self.CAM)
        ref = os.path.join(self.refdir, "r.jpg")
        got = subprocess.run([sys.executable, SCRIPT, "--make-reference", src, "--reference", ref],
                             capture_output=True, text=True)
        self.assertEqual(got.returncode, 0, got.stderr)
        got = subprocess.run([sys.executable, SCRIPT, "--frames", self.frames, "--day", "2026-11-14",
                              "--reference", ref, "--out", self.out, "--night-frames", "0"],
                             capture_output=True, text=True)
        self.assertEqual(got.returncode, 0, got.stderr)
        lines = got.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, got.stdout)
        self.assertIn("cm4wide 2026-11-14", lines[0])
        self.assertIn("moved: no", lines[0])   # the reference is a frame of the same day
        self.assertTrue(os.path.exists(os.path.join(self.out, self.CAM, "2026-11-14.json")))


if __name__ == "__main__":
    unittest.main()
