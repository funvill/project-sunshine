#!/usr/bin/env python3
"""pi/sunset-sky.py: the evening's sky score for Home Assistant's good-sunset alert. Offline: the
pixels come from a stub, the sun from pi/sunset-sun.py with a made-up site, the share is a folder."""
import importlib.util
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
UTC = timezone.utc


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sky = load("sunset_sky", os.path.join(REPO, "pi", "sunset-sky.py"))
daily = load("sunset_daily", os.path.join(REPO, "nas", "sunset-daily.py"))
sun = load("sunset_sun", os.path.join(REPO, "pi", "sunset-sun.py"))

W, H = sky.SKY_SIZE
WARM, GREY = (200, 120, 60), (120, 120, 130)
LAT, LON = "49.0", "-123.0"   # a made-up site near Vancouver, never the real one


def picture(warm_rows):
    """rgb24 at SKY_SIZE: the top `warm_rows` rows warm, the rest grey."""
    out = bytearray()
    for y in range(H):
        out += bytes(WARM if y < warm_rows else GREY) * W
    return bytes(out)


def stub_reader(warm_by_name):
    def read(path):
        name = os.path.basename(path)
        if name not in warm_by_name:
            raise OSError("unreadable")
        return picture(warm_by_name[name])
    return read


class SameMathsAsTheDailyJob(unittest.TestCase):
    """The PC's score (nas/sunset-daily.py, in the reports and build_video) and the Pi's must agree."""

    def test_constants(self):
        for name in ("SKY_BEFORE_MIN", "SKY_AFTER_MIN", "SKY_WARM_RATIO", "SKY_WARM_MIN_BRIGHT", "SKY_SIZE",
                     "SKY_TOP_FRAMES", "SKY_MIN_FRAMES"):
            self.assertEqual(getattr(sky, name), getattr(daily, name), name)
        self.assertEqual(sky.SKY_ROWS_DEFAULT, daily.SKY_ROWS)

    def test_warm_fraction_and_score(self):
        for rows in (0, 5, 24, 48, 100):
            rgb = picture(rows)
            self.assertAlmostEqual(sky.warm_fraction(rgb, W, 0.40), daily.warm_fraction(rgb, W, 0.40))
        for f in (0.0, 0.01, 0.05, 0.178, 0.5):
            self.assertEqual(sky.score_value(f, 0.178), daily.sky_score_value(f, 0.178))
        for s in (0, 19, 20, 59, 60, 100):
            self.assertEqual(sky.label(s), daily.sky_label(s))

    def test_scale_is_cm4wide_calibration(self):
        with open(os.path.join(REPO, "nas", "crop.cm4wide.json"), encoding="utf-8") as f:
            cals = json.load(f)["calibrations"]
        self.assertEqual(sky.SKY_FULL_WARM_DEFAULT, cals[-1]["sky_full_warm"])

    def test_score_matches_the_daily_jobs_block(self):
        names = ["f%02d.jpg" % i for i in range(10)]
        warm = {n: i * 4 for i, n in enumerate(names)}
        mine = sky.score_frames(names, 0.40, 0.178, read=stub_reader(warm))
        scored = [(daily.warm_fraction(picture(warm[n]), W, 0.40), None, n) for n in names]
        theirs = daily.sky_from_scored(scored, full=0.178)
        for key in ("score", "label", "warm_sky_percent", "warm_sky_percent_top_mean", "best_frame", "frames_scored"):
            self.assertEqual(mine[key], theirs[key], key)


class Score(unittest.TestCase):
    def test_too_few_frames_is_no_score(self):
        names = ["a%d.jpg" % i for i in range(sky.SKY_MIN_FRAMES)]
        warm = {n: 30 for n in names[:-1]}   # the last one is unreadable
        got = sky.score_frames(names, 0.40, 0.178, read=stub_reader(warm))
        self.assertIsNone(got["score"])
        self.assertEqual(got["label"], "none")
        self.assertIn("needed", got["reason"])

    def test_wrong_size_is_left_out(self):
        names = ["a%d.jpg" % i for i in range(8)]
        got = sky.score_frames(names, 0.40, 0.178, read=lambda p: b"\0" * 30)
        self.assertIsNone(got["score"])


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = self.tmp.name
        self.nas = os.path.join(base, "share", "project_sunshine")
        self.outbox = os.path.join(base, "sunset", "outbox")
        os.makedirs(self.nas)
        os.makedirs(self.outbox)
        lat, lon = float(LAT), float(LON)
        # Frames are named to the second; the sun module's sunset has microseconds.
        self.sunset = sun.next_sunset(datetime(2026, 11, 22, 18, 0, tzinfo=UTC), lat, lon).replace(microsecond=0)
        self.env = {"CAM_NAME": "cm4wide", "SETUP_ID": "cm4-window-4", "NAS_TARGET": self.nas + "/",
                    "OUT_ROOT": self.outbox, "SITE_LAT": LAT, "SITE_LON": LON,
                    "SKY_LOG": os.path.join(base, "sky.log"),
                    "SKY_REQUIRE_MOUNT": "0",
                    "SKY_OUT": os.path.join(base, "share", "project_sunshine_sky")}
        self.warm = {}

    def frame(self, minutes, warm_rows=30, where="nas", suffix=""):
        t = self.sunset + timedelta(minutes=minutes)
        root = self.nas if where == "nas" else self.outbox
        folder = os.path.join(root, "cm4wide", t.strftime("%Y/%m/%d"))
        os.makedirs(folder, exist_ok=True)
        name = "cm4wide_%sZ%s.jpg" % (t.strftime("%Y%m%dT%H%M%S"), suffix)
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"jpeg")
        self.warm[name] = warm_rows
        return name

    def run_at(self, minutes_after):
        env = dict(self.env, SUNSET_NOW=str((self.sunset + timedelta(minutes=minutes_after)).timestamp()))
        return sky.run(env, read=stub_reader(self.warm), sun=sun)

    def results(self):
        folder = os.path.join(self.env["SKY_OUT"], "cm4wide")
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def result(self):
        with open(os.path.join(self.env["SKY_OUT"], "cm4wide", self.results()[0]), encoding="utf-8") as f:
            return json.load(f)

    def test_scores_once_after_the_delay(self):
        for m in range(-40, 30):
            self.frame(m)
        self.assertEqual(self.run_at(30), 0)
        self.assertEqual(self.results(), [], "not before SKY_DELAY_MIN")
        self.assertEqual(self.run_at(45), 0)
        self.assertEqual(len(self.results()), 1)
        r = self.result()
        self.assertEqual(r["frames_scored"], 61, "35 min before to 25 after, a frame a minute")
        self.assertEqual(r["camera"], "cm4wide")
        self.assertEqual(r["setup_id"], "cm4-window-4")
        self.assertEqual(r["sunset_utc"], self.sunset.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertEqual(r["score"], sky.score_value(30 * W / (48 * W), 0.178))
        self.assertTrue(r["provisional"])
        path = os.path.join(self.env["SKY_OUT"], "cm4wide", self.results()[0])
        before = os.path.getmtime(path)
        time.sleep(0.01)
        self.run_at(60)
        self.assertEqual(os.path.getmtime(path), before, "a scored day is never scored again")

    def test_result_is_private(self):
        for m in range(-10, 10):
            self.frame(m)
        self.run_at(45)
        text = json.dumps(self.result())
        for word in ("Sun", "lat", "lon", "azimuth", "elevation", LAT, LON):
            self.assertNotIn(word, text)

    def test_only_regular_and_dense_frames(self):
        for m in range(-10, 0):
            self.frame(m, warm_rows=0)
            self.frame(m, warm_rows=48, suffix="_ev-2")
            self.frame(m, warm_rows=48, suffix="_night")
        self.run_at(45)
        self.assertEqual(self.result()["score"], 0)
        self.assertEqual(self.result()["frames_scored"], 10)

    def test_outside_the_window_is_left_out(self):
        for m in (-60, -36, 26, 40):
            self.frame(m, warm_rows=48)
        for m in range(-35, -25):
            self.frame(m, warm_rows=0)
        self.run_at(45)
        self.assertEqual(self.result()["score"], 0)

    def test_frames_not_synced_yet_come_from_the_outbox(self):
        for m in range(-10, -5):
            self.frame(m)
        for m in range(-5, 5):
            self.frame(m, where="outbox")
        self.run_at(45)
        self.assertEqual(self.result()["frames_scored"], 15)

    def test_no_share_writes_nothing_and_tries_again(self):
        for m in range(-10, 10):
            self.frame(m)
        os.rename(self.nas, self.nas + ".away")
        self.assertEqual(self.run_at(45), 1)
        self.assertEqual(self.results(), [])
        with open(self.env["SKY_LOG"], encoding="utf-8") as f:
            self.assertIn("SKIPPED", f.read())
        os.rename(self.nas + ".away", self.nas)
        self.assertEqual(self.run_at(60), 0)
        self.assertEqual(len(self.results()), 1)

    def test_too_late_gives_up(self):
        for m in range(-10, 10):
            self.frame(m)
        self.run_at(7 * 60)
        self.assertEqual(self.results(), [])

    def test_no_frames_still_records_the_evening(self):
        self.run_at(45)
        self.assertIsNone(self.result()["score"])
        self.assertEqual(self.result()["label"], "none")

    def test_no_site_refuses(self):
        env = dict(self.env, SITE_LAT="", SUNSET_NOW=str(self.sunset.timestamp() + 2700))
        self.assertEqual(sky.run(env, read=stub_reader({}), sun=sun), 1)

    def test_share_on_the_sd_card_is_refused(self):
        for m in range(-10, 10):
            self.frame(m)
        env = dict(self.env, SKY_REQUIRE_MOUNT="1")
        env["SUNSET_NOW"] = str((self.sunset + timedelta(minutes=45)).timestamp())
        self.assertEqual(sky.run(env, read=stub_reader(self.warm), sun=sun), 1)
        self.assertEqual(self.results(), [])

    def test_settings_defaults(self):
        cfg = sky.settings({"NAS_TARGET": "/mnt/nas-camera/project_sunshine/", "OUT_ROOT": "/home/x/sunset/outbox"})
        self.assertEqual(cfg["out"], "/mnt/nas-camera/project_sunshine_sky")
        self.assertEqual(cfg["log"], "/home/x/sunset/sky.log")
        self.assertEqual(cfg["full"], 0.178)
        self.assertEqual(sky.settings({"SKY_FULL_WARM": "nonsense"})["full"], 0.178)
        self.assertEqual(sky.settings({"NAS_TARGET": "user@host:/x/"})["out"], "")


if __name__ == "__main__":
    unittest.main()
