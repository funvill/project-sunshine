"""Tests for windowtracking/sunset-windowlight.py: python3 tests/test_windowlight.py

Fake night frames only. Detection and aggregation are tested on synthetic greys; the
ffmpeg loader is tested with the real ffmpeg and skipped if it is not installed.
"""
import csv
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
SCRIPT = os.path.join(os.path.dirname(HERE), "windowtracking", "sunset-windowlight.py")
spec = importlib.util.spec_from_file_location("sunset_windowlight", SCRIPT)
wl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wl)

UTC = timezone.utc
DAY = datetime(2026, 12, 22).date()
NIGHT = datetime(2026, 12, 22, 3, 0, tzinfo=UTC)
HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def gray_image(width, height, points):
    """A grey with the given (x, y) points lit to 255, everything else 0."""
    g = bytearray(width * height)
    for x, y in points:
        g[y * width + x] = 255
    return g


def two_blobs(width=10, height=10):
    """Two bright blobs: a 2x2 (area 4) and a 3x2 (area 6)."""
    pts = [(1, 1), (1, 2), (2, 1), (2, 2), (6, 6), (6, 7), (7, 6), (7, 7), (8, 6), (8, 7)]
    return gray_image(width, height, pts)


def fake_load(cfg, jpg, box):
    return 10, 10, two_blobs()


class Tree:
    """A frames folder laid out the way the Pi's sync leaves it on the NAS."""

    def __init__(self, test):
        self.dir = tempfile.mkdtemp()
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.frames = os.path.join(self.dir, "wide")
        self.analysis = os.path.join(self.dir, "windowlight")
        self.towers_file = os.path.join(self.dir, "towers.json")

    def folder(self, t):
        return os.path.join(self.frames, t.strftime("%Y"), t.strftime("%m"), t.strftime("%d"))

    def add_night(self, t, setup="pilot-3"):
        folder = self.folder(t)
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, "wide_%s_night" % t.strftime("%Y%m%dT%H%M%SZ"))
        open(base + ".jpg", "wb").close()
        with open(base + ".json", "w") as f:
            json.dump({"Capture": {"kind": "night", "schedule": "regular", "setup_id": setup}}, f)
        return base

    def add_day(self, t):
        folder = self.folder(t)
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, "wide_%s" % t.strftime("%Y%m%dT%H%M%SZ"))
        open(base + ".jpg", "wb").close()
        return base

    def write_towers(self, setups):
        with open(self.towers_file, "w") as f:
            json.dump(setups, f)

    def config(self, **over):
        values = dict(frames_dir=self.frames, analysis_dir=self.analysis,
                      towers_file=self.towers_file, reference_min_frames=1, reference_days=14)
        values.update(over)
        return wl.Config(**values)

    def towers(self):
        return wl.load_towers(self.towers_file)

    def record(self, day=DAY):
        with open(os.path.join(self.analysis, "records", day.isoformat() + ".json")) as f:
            return json.load(f)

    def csv_rows(self, day=DAY):
        path = os.path.join(self.analysis, "per_frame", "%04d" % day.year, "%02d" % day.month,
                            "%s.csv" % day.isoformat())
        with open(path, newline="") as f:
            return list(csv.DictReader(f))


class FrameNames(unittest.TestCase):
    def test_reads_utc_time_from_a_night_frame(self):
        self.assertEqual(wl.parse_night_time("wide_20261222T031500Z_night.jpg"),
                         datetime(2026, 12, 22, 3, 15, tzinfo=UTC))

    def test_normal_and_dng_files_are_not_night_frames(self):
        self.assertIsNone(wl.parse_night_time("wide_20261222T031500Z.jpg"))
        self.assertIsNone(wl.parse_night_time("wide_20261222T031500Z.dng"))
        self.assertIsNone(wl.parse_night_time("notes.jpg"))


class SetupId(unittest.TestCase):
    def test_reads_setup_id_from_capture(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        base = os.path.join(d, "wide_20261222T031500Z_night")
        with open(base + ".json", "w") as f:
            json.dump({"Capture": {"setup_id": "pilot-3"}}, f)
        self.assertEqual(wl.read_setup_id(base + ".jpg"), "pilot-3")

    def test_missing_or_broken_json_gives_none(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        base = os.path.join(d, "wide_20261222T031500Z_night")
        self.assertIsNone(wl.read_setup_id(base + ".jpg"))
        with open(base + ".json", "w") as f:
            f.write("{ cut off")
        self.assertIsNone(wl.read_setup_id(base + ".jpg"))


class ListFrames(unittest.TestCase):
    def test_reads_only_night_frames_in_time_order(self):
        tree = Tree(self)
        tree.add_night(datetime(2026, 12, 22, 3, 15, tzinfo=UTC))
        tree.add_day(datetime(2026, 12, 22, 3, 15, tzinfo=UTC))       # ignored: not a night frame
        tree.add_night(datetime(2026, 12, 22, 3, 0, tzinfo=UTC))
        got = wl.list_day_night_frames(tree.frames, DAY)
        self.assertEqual([f.time.strftime("%H:%M") for f in got], ["03:00", "03:15"])
        self.assertEqual([f.setup_id for f in got], ["pilot-3", "pilot-3"])

    def test_other_days_are_not_read(self):
        tree = Tree(self)
        tree.add_night(datetime(2026, 12, 23, 3, 0, tzinfo=UTC))
        self.assertEqual(wl.list_day_night_frames(tree.frames, DAY), [])


class HistogramAndThreshold(unittest.TestCase):
    def test_histogram_counts_luma(self):
        g = gray_image(4, 4, [(0, 0), (1, 1)])
        hist = wl.histogram(g)
        self.assertEqual(hist[0], 14)
        self.assertEqual(hist[255], 2)

    def test_percentile_is_the_nearest_rank(self):
        hist = [0] * 256
        for v in (5, 10, 15):
            hist[v] += 1
        self.assertEqual(wl.percentile(hist, 3, 50), 10)

    def test_threshold_floor_on_uniform_dark(self):
        self.assertEqual(wl.threshold_for(bytearray(100), 30), 30)

    def test_floor_rescues_a_pure_black_and_white_image(self):
        # Pure 0 background and 255 blobs: Otsu returns 0, the floor rescues it to 30.
        self.assertEqual(wl.threshold_for(two_blobs(), 30), 30)

    def test_otsu_splits_noisy_background_from_windows(self):
        g = bytearray(1000)
        for i in range(1000):
            g[i] = 10 + (i % 30)          # noisy dark facade, luma 10..39
        for p in (3, 4, 5, 103, 104, 105):
            g[p] = 255
        t = wl.threshold_for(g, 30)
        self.assertGreater(t, 39)         # above the facade noise, so blobs are found
        self.assertLess(t, 255)


class Analyze(unittest.TestCase):
    def test_counts_blobs_above_min_area(self):
        blobs, area, boxes = wl.analyze(two_blobs(), 10, 10, 100, min_area=4)
        self.assertEqual((blobs, area), (2, 10))
        self.assertEqual(len(boxes), 2)

    def test_smaller_than_min_area_is_noise(self):
        pts = [(1, 1), (2, 1), (6, 6), (6, 7), (7, 6), (7, 7)]
        blobs, area, _ = wl.analyze(gray_image(10, 10, pts), 10, 10, 100, min_area=4)
        self.assertEqual((blobs, area), (1, 4))   # the 2x2 stays; the two lone pixels drop

    def test_diagonal_pixels_are_not_connected(self):
        # 4-way connectivity: two diagonally touching pixels are separate regions.
        blobs, area, _ = wl.analyze(gray_image(4, 4, [(1, 1), (2, 2)]), 4, 4, 100, min_area=1)
        self.assertEqual((blobs, area), (2, 2))


class Hourly(unittest.TestCase):
    def row(self, minute, lit):
        return {"utc": NIGHT + timedelta(minutes=minute), "frame": "x", "setup_id": "pilot-3",
                "tower": "left", "lit_windows": lit, "lit_area_px": lit * 5,
                "total_windows": 20, "total_window_area": 100, "fraction": lit / 20}

    def test_stats_and_transitions_per_hour(self):
        rows = [self.row(0, 2), self.row(5, 5), self.row(60, 3), self.row(65, 1)]
        summary = wl.hourly_summary(rows)["left"]
        self.assertEqual(set(summary), {"03", "04"})
        self.assertEqual(summary["03"]["lit_windows_mean"], 3.5)
        self.assertEqual(summary["03"]["turned_on"], 3)   # 2 -> 5
        self.assertEqual(summary["04"]["turned_off"], 2)  # 3 -> 1
        self.assertEqual(summary["04"]["net"], -2)


class TowersFor(unittest.TestCase):
    def test_reads_boxes_for_a_setup_and_nothing_else(self):
        towers = {"setups": {"pilot-3": {"towers": {"left": [1, 2, 3, 4], "right": [5, 6, 7, 8]}}}}
        self.assertEqual(wl.towers_for(towers, "pilot-3"),
                         {"left": [1, 2, 3, 4], "right": [5, 6, 7, 8]})
        self.assertEqual(wl.towers_for(towers, "pilot-9"), {})
        self.assertEqual(wl.towers_for({}, "pilot-3"), {})


class Reference(unittest.TestCase):
    def test_due_when_older_than_the_window(self):
        old = {"last_frame_utc": "2026-12-01T00:00:00Z"}
        self.assertTrue(wl.reference_due(old, datetime(2026, 12, 22, tzinfo=UTC), 14))
        self.assertFalse(wl.reference_due(old, datetime(2026, 12, 10, tzinfo=UTC), 14))

    def test_missing_timestamp_is_due(self):
        self.assertTrue(wl.reference_due({}, datetime(2026, 12, 22, tzinfo=UTC), 14))


class ProcessDay(unittest.TestCase):
    NOW = datetime(2026, 12, 23, 1, 0, tzinfo=UTC)

    def setUp(self):
        self.tree = Tree(self)
        self.tree.write_towers({"setups": {"pilot-3": {"towers": {"left": [0, 0, 10, 10]}}}})

    def test_writes_rows_hourly_and_a_record(self):
        self.tree.add_night(NIGHT)
        self.tree.add_night(NIGHT + timedelta(minutes=5))
        wl.process_day(self.tree.config(), DAY, self.tree.towers(), self.NOW, load=fake_load)
        rows = self.tree.csv_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual((int(rows[0]["lit_windows"]), int(rows[0]["lit_area_px"]),
                          float(rows[0]["fraction"])), (2, 10, 1.0))
        self.assertEqual(self.tree.record()["status"], "ok")
        self.assertEqual(self.tree.record()["rows"], 2)
        with open(os.path.join(self.tree.analysis, "hourly", "2026", "12", "2026-12-22.json")) as f:
            hourly = json.load(f)
        self.assertEqual(hourly["towers"]["left"]["03"]["lit_windows_mean"], 2.0)

    def test_reference_is_written_and_reused(self):
        self.tree.add_night(NIGHT)
        wl.process_day(self.tree.config(), DAY, self.tree.towers(), self.NOW, load=fake_load)
        ref_dir = os.path.join(self.tree.analysis, "reference")
        self.assertEqual(os.listdir(ref_dir), ["pilot-3_left.json"])
        with open(os.path.join(ref_dir, "pilot-3_left.json")) as f:
            ref = json.load(f)
        self.assertEqual((ref["total_windows"], ref["total_window_area"]), (2, 10))

    def test_unknown_setup_is_counted_not_silently_dropped(self):
        self.tree.add_night(NIGHT, setup="pilot-9")
        wl.process_day(self.tree.config(), DAY, self.tree.towers(), self.NOW, load=fake_load)
        rec = self.tree.record()
        self.assertEqual(rec["rows"], 0)
        self.assertEqual(rec["skipped_frames"], {"pilot-9": 1})
        self.assertEqual(self.tree.csv_rows(), [])

    def test_reference_is_built_once_per_tower_across_frames(self):
        self.tree.add_night(NIGHT)
        self.tree.add_night(NIGHT + timedelta(minutes=5))
        self.tree.add_night(NIGHT + timedelta(minutes=10))
        calls = []
        original = wl.build_reference
        wl.build_reference = lambda *a, **k: (calls.append(1), None)[1]
        try:
            wl.process_day(self.tree.config(), DAY, self.tree.towers(), self.NOW, load=fake_load)
        finally:
            wl.build_reference = original
        self.assertEqual(len(calls), 1, "one tower, built once across three frames")

    def test_empty_day_is_recorded(self):
        wl.process_day(self.tree.config(), DAY, self.tree.towers(), self.NOW, load=fake_load)
        self.assertEqual(self.tree.record()["status"], "empty")


class Run(unittest.TestCase):
    NOW = datetime(2026, 12, 23, 1, 0, tzinfo=UTC)

    def setUp(self):
        self.tree = Tree(self)
        self.tree.write_towers({"setups": {"pilot-3": {"towers": {"left": [0, 0, 10, 10]}}}})

    def test_processes_yesterday_and_is_idempotent(self):
        self.tree.add_night(NIGHT)
        self.assertEqual(wl.run(self.tree.config(lookback_days=2), self.NOW, load=fake_load), 0)
        self.assertEqual(self.tree.record()["status"], "ok")
        first = self.tree.record()
        self.assertEqual(wl.run(self.tree.config(lookback_days=2), self.NOW, load=fake_load), 0)
        self.assertEqual(self.tree.record(), first)

    def test_missing_towers_file_stops_the_run(self):
        self.tree.add_night(NIGHT)
        os.remove(self.tree.towers_file)
        self.assertEqual(wl.run(self.tree.config(), self.NOW, load=fake_load), 1)
        self.assertFalse(os.path.exists(os.path.join(self.tree.analysis, ".lock")))

    def test_failed_load_writes_no_record_so_the_next_run_retries(self):
        self.tree.add_night(NIGHT)

        def broken(cfg, jpg, box):
            raise wl.EncodeError("no ffmpeg")
        self.assertEqual(wl.run(self.tree.config(), self.NOW, load=broken), 1)
        self.assertFalse(os.path.exists(os.path.join(self.tree.analysis, "records", "2026-12-22.json")))
        self.assertEqual(wl.run(self.tree.config(), self.NOW, load=fake_load), 0)
        self.assertEqual(self.tree.record()["status"], "ok")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class RealLoader(unittest.TestCase):
    def make_image(self, color="gray", size="40x30"):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "frame.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=%s:s=%s:d=1" % (color, size), "-frames:v", "1", "-q:v", "2", path],
                       check=True)
        return path

    def test_load_gray_crops_and_reads_luma(self):
        path = self.make_image(color="white")
        cfg = wl.Config(frames_dir=os.path.dirname(path), analysis_dir=os.path.dirname(path),
                        towers_file="unused")
        w, h, gray = wl.load_gray(cfg, path, [10, 5, 20, 10])
        self.assertEqual((w, h, len(gray)), (20, 10, 200))
        self.assertTrue(all(v > 200 for v in gray), "white stays bright")

    def test_load_gray_reads_dark_as_dark(self):
        path = self.make_image(color="black")
        cfg = wl.Config(frames_dir=os.path.dirname(path), analysis_dir=os.path.dirname(path),
                        towers_file="unused")
        _, _, gray = wl.load_gray(cfg, path, [0, 0, 40, 30])
        self.assertTrue(all(v < 30 for v in gray), "black stays dark")

    def test_load_gray_preserves_non_text_bytes(self):
        # 0x8f is not valid cp1252, so this catches any accidental text decoding of the luma.
        path = self.make_image(color="0x8f8f8f", size="8x8")
        cfg = wl.Config(frames_dir=os.path.dirname(path), analysis_dir=os.path.dirname(path),
                        towers_file="unused")
        _, _, gray = wl.load_gray(cfg, path, [0, 0, 8, 8])
        self.assertTrue(all(v == 143 for v in gray))


class CommandLine(unittest.TestCase):
    def test_missing_settings_is_a_clear_error(self):
        env = {k: v for k, v in os.environ.items() if k not in ("FRAMES_DIR", "ANALYSIS_DIR")}
        got = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True)
        self.assertEqual(got.returncode, 2)
        self.assertIn("FRAMES_DIR", got.stderr)


if __name__ == "__main__":
    unittest.main()
