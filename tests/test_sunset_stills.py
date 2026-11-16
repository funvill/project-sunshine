"""Tests for tools/sunset_stills.py: python3 tests/test_sunset_stills.py (standard library only)

Small fixture trees of fake JPEGs (start and end markers only) with JSON beside them.
"""
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
SCRIPT = os.path.join(os.path.dirname(HERE), "tools", "sunset_stills.py")
UTC = timezone.utc
FMT = "%Y-%m-%dT%H:%M:%SZ"
CAM = "cm4wide"


def load():
    spec = importlib.util.spec_from_file_location("sunset_stills", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stamp(t):
    return t.strftime("%Y%m%dT%H%M%SZ")


def elevation_at(minutes):
    """Roughly the sun near sunset here in November: -0.25 deg at sunset, 0.13 deg a minute."""
    return round(-0.25 - 0.13 * minutes, 2)


class Tree:
    def __init__(self, root):
        self.root = root
        self.frames = os.path.join(root, "project_sunshine")

    def jpg(self, path, tag):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"\xff\xd8" + tag.encode() + b"\xff\xd9")
        return path

    def frame(self, t, sunset, cam=CAM, sun=True, setup="cm4-window-1", night=False, capture=True, json_file=True,
              broken=False):
        folder = os.path.join(self.frames, cam, t.strftime("%Y"), t.strftime("%m"), t.strftime("%d"))
        base = os.path.join(folder, "%s_%s%s" % (cam, stamp(t), "_night" if night else ""))
        if broken:
            os.makedirs(folder, exist_ok=True)
            open(base + ".jpg", "wb").close()
        else:
            self.jpg(base + ".jpg", "prod " + stamp(t))
        if not json_file:
            return base + ".jpg"
        data = {"ExposureTime": 1000}
        minutes = (t - sunset).total_seconds() / 60.0
        if sun:
            data["Sun"] = {"azimuth_deg": round(240.0 + 0.19 * minutes, 2), "elevation_deg": elevation_at(minutes),
                           "azimuth_ref": "true_north", "computed_for_utc": t.strftime(FMT), "algorithm": "noaa-1",
                           "nearest_sunset_utc": sunset.strftime(FMT), "minutes_from_sunset": round(minutes, 1)}
        if capture:
            data["Capture"] = {"schema_version": 1, "camera": cam, "kind": "night" if night else "auto",
                               "schedule": "regular", "setup_id": setup}
        with open(base + ".json", "w") as f:
            json.dump(data, f)
        return base + ".jpg"

    def evening(self, sunset, before=60, after=30, step=5, **kw):
        """Frames every `step` minutes on the minute, from `before` min before sunset to `after` after."""
        start = (sunset - timedelta(minutes=before)).replace(second=0)
        start -= timedelta(minutes=start.minute % step)
        out, t = [], start
        while t <= sunset + timedelta(minutes=after):
            out.append(self.frame(t, sunset, **kw))
            t += timedelta(minutes=step)
        return out


class Stills(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Same rule as tests/test_daily.py: a Python with no time zone database (Windows without
        # the tzdata package) can't work out local dates, so skip, don't fail.
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo("America/Vancouver")
        except Exception:
            raise unittest.SkipTest("no time zone database on this machine")

    def setUp(self):
        self.ss = load()
        self.dir = tempfile.mkdtemp()
        self.tree = Tree(self.dir)
        self.out = os.path.join(self.dir, "stills")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def run_range(self, first, last, **kw):
        kw.setdefault("cameras", [CAM])
        opts = self.ss.Options(**kw)
        return self.ss.make_stills(self.tree.frames, first, last, self.out, opts)

    def index(self):
        with open(os.path.join(self.out, CAM, "index.json")) as f:
            return json.load(f)

    def still_bytes(self, day):
        with open(os.path.join(self.out, CAM, day + ".jpg"), "rb") as f:
            return f.read()

    # --- choosing the frame ---------------------------------------------------------------

    def test_normal_day_picks_the_frame_nearest_the_target_elevation(self):
        # sunset 03:00 UTC (summer-like), all frames in one UTC folder; local date is the day before
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        self.tree.evening(sunset)
        self.run_range("2026-06-20", "2026-06-20")
        day = self.index()["days"]["2026-06-20"]
        self.assertEqual(day["status"], "ok", day)
        # +0.5 deg is 5.8 min before sunset: the 04:15 frame (-5.5 min, +0.47 deg)
        self.assertEqual(day["frame"], "cm4wide_20260621T041500Z.jpg")
        self.assertEqual(day["source_kind"], "production")
        self.assertEqual(day["selected_by"], "elevation")
        self.assertAlmostEqual(day["sun_elevation_deg"], elevation_at(-5.5))
        self.assertAlmostEqual(day["minutes_from_sunset"], -5.5)
        self.assertEqual(day["frame_utc"], "2026-06-21T04:15:00Z")
        self.assertEqual(day["sunset_utc"], "2026-06-21T04:20:30Z")
        self.assertEqual(day["setup_id"], "cm4-window-1")
        self.assertIn("sun_azimuth_deg", day)
        self.assertEqual(self.still_bytes("2026-06-20"), b"\xff\xd8prod 20260621T041500Z\xff\xd9")
        with open(os.path.join(self.out, CAM, "2026-06-20.json")) as f:
            self.assertEqual(json.load(f)["Sun"]["minutes_from_sunset"], -5.5)

    def test_target_elevation_is_configurable(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        self.tree.evening(sunset)
        self.run_range("2026-06-20", "2026-06-20", target_elevation=3.0)
        # 3.0 deg is 25 min before sunset: 03:55 (-25.5 min)
        self.assertEqual(self.index()["days"]["2026-06-20"]["frame"], "cm4wide_20260621T035500Z.jpg")

    def test_evening_split_across_two_utc_folders(self):
        # Sunset at 00:10 UTC on Nov 15 is 16:10 on Nov 14 in Vancouver. The evening's frames are in
        # 2026/11/14 (before midnight UTC) and 2026/11/15 (after).
        sunset = datetime(2026, 11, 15, 0, 10, 0, tzinfo=UTC)
        self.tree.evening(sunset, before=60, after=40)
        # the next evening's first frames are in the 11/15 folder too, and must not be mixed in
        nxt = datetime(2026, 11, 16, 0, 9, 0, tzinfo=UTC)
        for minute in (40, 45, 50, 55):
            self.tree.frame(datetime(2026, 11, 15, 23, minute, tzinfo=UTC), nxt)
        self.assertTrue(os.listdir(os.path.join(self.tree.frames, CAM, "2026", "11", "14")))
        self.run_range("2026-11-14", "2026-11-14")
        day = self.index()["days"]["2026-11-14"]
        self.assertEqual(day["frame"], "cm4wide_20261115T000500Z.jpg")   # -5 min, +0.40 deg, in 11/15
        self.run_range("2026-11-14", "2026-11-14", target_elevation=2.0, redo=True)
        day = self.index()["days"]["2026-11-14"]
        self.assertEqual(day["frame"], "cm4wide_20261114T235500Z.jpg")   # -15 min, +1.70 deg, in 11/14
        self.assertEqual(day["sunset_utc"], "2026-11-15T00:10:00Z")
        self.assertEqual(sorted(self.index()["days"]), ["2026-11-14"])

    def test_night_frames_are_never_chosen(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        self.tree.evening(sunset)
        self.tree.frame(datetime(2026, 6, 21, 4, 15, 30, tzinfo=UTC), sunset, night=True)
        self.run_range("2026-06-20", "2026-06-20")
        self.assertNotIn("night", self.index()["days"]["2026-06-20"]["frame"])

    def test_a_frame_too_far_from_the_target_is_not_used(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        for minutes in (-60, -55, 20, 25):   # a gap: the nearest frame is 2.85 deg below the target
            self.tree.frame(sunset + timedelta(minutes=minutes), sunset)
        self.run_range("2026-06-20", "2026-06-20")
        day = self.index()["days"]["2026-06-20"]
        self.assertEqual(day["status"], "none")
        self.assertIn("deg from the target", day["reason"])

    def test_a_broken_jpeg_is_passed_over(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        self.tree.evening(sunset)
        self.tree.frame(datetime(2026, 6, 21, 4, 15, tzinfo=UTC), sunset, broken=True)
        self.run_range("2026-06-20", "2026-06-20")
        self.assertNotEqual(self.index()["days"]["2026-06-20"]["frame"], "cm4wide_20260621T041500Z.jpg")

    # --- missing Sun data -----------------------------------------------------------------

    def test_some_frames_without_sun_use_the_others(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        self.tree.evening(sunset)
        self.tree.frame(datetime(2026, 6, 21, 4, 15, tzinfo=UTC), sunset, sun=False, capture=False)
        self.run_range("2026-06-20", "2026-06-20")
        day = self.index()["days"]["2026-06-20"]
        self.assertEqual(day["selected_by"], "elevation")
        self.assertIn(day["frame"], ("cm4wide_20260621T041000Z.jpg", "cm4wide_20260621T042000Z.jpg"))

    def test_no_sun_block_anywhere_falls_back_to_nearest_sunset_from_the_site(self):
        # Burnaby, roughly: the tool works out the sunset itself (pi/sunset-sun.py)
        sunset = datetime(2026, 11, 15, 0, 25, 0, tzinfo=UTC)   # only for spacing the frames
        self.tree.evening(sunset, before=40, after=20, sun=False, capture=False)
        self.run_range("2026-11-14", "2026-11-14", site=(49.25, -123.0))
        day = self.index()["days"]["2026-11-14"]
        self.assertEqual(day["status"], "ok", day)
        self.assertEqual(day["selected_by"], "nearest_sunset_time")
        self.assertIsNone(day["sun_elevation_deg"])
        self.assertIsNone(day["setup_id"])
        real = datetime.strptime(day["sunset_utc"], FMT).replace(tzinfo=UTC)
        chosen = datetime.strptime(day["frame_utc"], FMT).replace(tzinfo=UTC)
        self.assertLessEqual(abs((chosen - real).total_seconds()), 150)

    def test_no_sun_block_and_no_site_says_why(self):
        sunset = datetime(2026, 11, 15, 0, 25, 0, tzinfo=UTC)
        self.tree.evening(sunset, sun=False, json_file=False)
        self.run_range("2026-11-14", "2026-11-14")
        day = self.index()["days"]["2026-11-14"]
        self.assertEqual(day["status"], "none")
        self.assertIn("no Sun data", day["reason"])

    def test_no_frames_says_why(self):
        self.run_range("2026-11-10", "2026-11-11")
        days = self.index()["days"]
        self.assertEqual(sorted(days), ["2026-11-10", "2026-11-11"])
        for d in days.values():
            self.assertEqual(d["status"], "none")
            self.assertTrue(d["reason"])
        self.assertFalse([n for n in os.listdir(os.path.join(self.out, CAM)) if n.endswith(".jpg")])

    # --- which version of the frame ---------------------------------------------------------

    def put_fused_and_ev2(self, sunset, chosen):
        fused = os.path.join(self.dir, "fused")
        self.tree.jpg(os.path.join(fused, os.path.basename(chosen)), "fused")
        run = os.path.join(self.dir, "experiments", "cm4-sunset-2")
        t = datetime.strptime(os.path.basename(chosen)[len(CAM) + 1:-4], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        ev2 = self.tree.jpg(os.path.join(run, "ev-2_%s.jpg" % stamp(t + timedelta(seconds=40))), "ev-2")
        with open(ev2[:-4] + ".json", "w") as f:
            json.dump({"Sun": {"elevation_deg": 0.4}, "ExposureTime": 250}, f)
        self.tree.jpg(os.path.join(run, "ev+0-daylight_%s.jpg" % stamp(t + timedelta(seconds=20))), "ev+0")
        return fused, os.path.join(self.dir, "experiments")

    def test_fused_frame_is_preferred(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        frames = self.tree.evening(sunset)
        chosen = [f for f in frames if f.endswith("041500Z.jpg")][0]
        fused, exp = self.put_fused_and_ev2(sunset, chosen)
        self.run_range("2026-06-20", "2026-06-20", fused=[(None, fused)], experiments=[(CAM, exp)])
        day = self.index()["days"]["2026-06-20"]
        self.assertEqual(day["source_kind"], "fused")
        self.assertEqual(self.still_bytes("2026-06-20"), b"\xff\xd8fused\xff\xd9")
        with open(os.path.join(self.out, CAM, "2026-06-20.json")) as f:
            self.assertEqual(json.load(f)["Capture"]["setup_id"], "cm4-window-1")   # the production frame's JSON

    def test_ev2_is_next_and_its_own_json_comes_with_it(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        frames = self.tree.evening(sunset)
        chosen = [f for f in frames if f.endswith("041500Z.jpg")][0]
        _, exp = self.put_fused_and_ev2(sunset, chosen)
        self.run_range("2026-06-20", "2026-06-20", experiments=[(CAM, exp)])
        day = self.index()["days"]["2026-06-20"]
        self.assertEqual(day["source_kind"], "experiment")
        self.assertEqual(day["source_label"], "ev-2")
        self.assertEqual(day["source_utc"], "2026-06-21T04:15:40Z")
        self.assertEqual(day["frame_utc"], "2026-06-21T04:15:00Z")
        self.assertEqual(self.still_bytes("2026-06-20"), b"\xff\xd8ev-2\xff\xd9")
        with open(os.path.join(self.out, CAM, "2026-06-20.json")) as f:
            self.assertEqual(json.load(f)["ExposureTime"], 250)

    def test_ev2_too_far_in_time_is_not_used(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        frames = self.tree.evening(sunset)
        chosen = [f for f in frames if f.endswith("041500Z.jpg")][0]
        _, exp = self.put_fused_and_ev2(sunset, chosen)
        self.run_range("2026-06-20", "2026-06-20", experiments=[(CAM, exp)], ev2_seconds=30)
        self.assertEqual(self.index()["days"]["2026-06-20"]["source_kind"], "production")

    def test_experiments_for_another_camera_are_ignored(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        frames = self.tree.evening(sunset)
        chosen = [f for f in frames if f.endswith("041500Z.jpg")][0]
        _, exp = self.put_fused_and_ev2(sunset, chosen)
        self.run_range("2026-06-20", "2026-06-20", experiments=[("wide", exp)])
        self.assertEqual(self.index()["days"]["2026-06-20"]["source_kind"], "production")

    # --- registration, idempotence, the command line -----------------------------------------

    def test_registration_dx_dy_go_in_the_index(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        self.tree.evening(sunset)
        reg = os.path.join(self.dir, "registration", CAM)
        os.makedirs(reg)
        with open(os.path.join(reg, "2026-06-21.json"), "w") as f:   # the UTC day of the chosen frame
            json.dump({"schema_version": 1, "day": {"dx_px": 3.5, "dy_px": -1.25, "rotation_deg": 0.01,
                                                    "reliable": True}, "night": {"reliable": False},
                       "moved": True}, f)
        self.run_range("2026-06-20", "2026-06-20", registration=os.path.join(self.dir, "registration"))
        r = self.index()["days"]["2026-06-20"]["registration"]
        self.assertEqual((r["dx_px"], r["dy_px"]), (3.5, -1.25))
        self.assertEqual(r["day_utc"], "2026-06-21")
        self.assertIs(r["moved"], True)

    def test_rerun_does_not_recopy_unless_redo(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        self.tree.evening(sunset)
        first = self.run_range("2026-06-20", "2026-06-20")
        self.assertEqual(first["copied"], 1)
        still = os.path.join(self.out, CAM, "2026-06-20.jpg")
        os.utime(still, (1_000_000_000, 1_000_000_000))
        with open(os.path.join(self.out, CAM, "index.json")) as f:
            index_before = f.read()
        again = self.run_range("2026-06-20", "2026-06-20")
        self.assertEqual(again["copied"], 0)
        self.assertEqual(again["unchanged"], 1)
        self.assertEqual(os.path.getmtime(still), 1_000_000_000)
        with open(os.path.join(self.out, CAM, "index.json")) as f:
            self.assertEqual(f.read(), index_before)
        redo = self.run_range("2026-06-20", "2026-06-20", redo=True)
        self.assertEqual(redo["copied"], 1)
        self.assertNotEqual(os.path.getmtime(still), 1_000_000_000)

    def test_a_changed_choice_is_recopied(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        frames = self.tree.evening(sunset)
        self.run_range("2026-06-20", "2026-06-20")
        chosen = [f for f in frames if f.endswith("041500Z.jpg")][0]
        fused, _ = self.put_fused_and_ev2(sunset, chosen)
        got = self.run_range("2026-06-20", "2026-06-20", fused=[(None, fused)])
        self.assertEqual(got["copied"], 1)
        self.assertEqual(self.still_bytes("2026-06-20"), b"\xff\xd8fused\xff\xd9")

    def test_other_days_in_the_index_are_kept(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        self.tree.evening(sunset)
        self.run_range("2026-06-20", "2026-06-20")
        self.run_range("2026-06-25", "2026-06-25")
        self.assertEqual(sorted(self.index()["days"]), ["2026-06-20", "2026-06-25"])

    def test_frames_are_not_changed(self):
        sunset = datetime(2026, 6, 21, 4, 20, 30, tzinfo=UTC)
        self.tree.evening(sunset)
        before = {}
        for dirpath, _, names in os.walk(self.tree.frames):
            for n in names:
                p = os.path.join(dirpath, n)
                before[p] = (os.path.getsize(p), os.path.getmtime(p))
        self.run_range("2026-06-20", "2026-06-20")
        after = {}
        for dirpath, _, names in os.walk(self.tree.frames):
            for n in names:
                p = os.path.join(dirpath, n)
                after[p] = (os.path.getsize(p), os.path.getmtime(p))
        self.assertEqual(before, after)

    def test_command_line(self):
        sunset = datetime(2026, 11, 15, 0, 10, 0, tzinfo=UTC)
        frames = self.tree.evening(sunset)
        chosen = [f for f in frames if f.endswith("000500Z.jpg")][0]
        fused, exp = self.put_fused_and_ev2(sunset, chosen)
        got = subprocess.run([sys.executable, SCRIPT, "--frames", self.tree.frames, "--from", "2026-11-13",
                              "--to", "2026-11-14", "--out", self.out, "--experiments", "%s=%s" % (CAM, exp)],
                             capture_output=True, text=True)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("cm4wide 2026-11-14: experiment ev-2", got.stdout)
        self.assertIn("cm4wide 2026-11-13: none", got.stdout)
        self.assertEqual(self.index()["days"]["2026-11-14"]["source_kind"], "experiment")


if __name__ == "__main__":
    unittest.main()
