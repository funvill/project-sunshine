"""Tests for nas/sunset-health.py: python3 tests/test_health.py

Fixture trees under a temp folder, no NAS. Expected numbers are worked out by hand.
"""
import atexit
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "nas", "sunset-health.py")
spec = importlib.util.spec_from_file_location("sunset_health", SCRIPT)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)

UTC = timezone.utc
DAY = datetime(2026, 11, 10, tzinfo=UTC)
NOW = "2026-11-11T02:00:00Z"            # the day after: DAY is finished


def ts(dt):
    return dt.strftime("%Y%m%dT%H%M%SZ")


class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "wide")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def folder(self, day):
        return os.path.join(self.root, day.strftime("%Y/%m/%d"))

    def frame(self, when, schedule="regular", night=False, dng=True, sun=True, capture=True, system=True,
              setup_id="pilot-4", temp=50.0, throttled="0x0", outbox=2, disk=40.0, jpg=b"jpeg", lux=1000,
              night_lux=10, broken=False):
        """One frame: the JSON and its images. Returns the stem."""
        stem = "wide_%s%s" % (ts(when), "_night" if night else "")
        folder = self.folder(when)
        os.makedirs(folder, exist_ok=True)
        data = {"Lux": lux}
        if sun:
            data["Sun"] = {"azimuth_deg": 200.0, "elevation_deg": 10.0}
        if capture:
            data["Capture"] = {"schema_version": 2, "kind": "night" if night else "auto", "schedule": schedule,
                               "setup_id": setup_id, "files": {},
                               "settings": {"night_lux": night_lux, "raw": 1 if dng else 0}}
        if system:
            data["System"] = {"cpu_temp_c": temp, "throttled": throttled, "disk": {"used_pct": disk},
                              "outbox_pending": {"files": outbox, "bytes": 1}, "unavailable": []}
        with open(os.path.join(folder, stem + ".json"), "w") as f:
            f.write("{broken" if broken else json.dumps(data))
        if jpg is not None:
            with open(os.path.join(folder, stem + ".jpg"), "wb") as f:
                f.write(jpg)
        if dng:
            with open(os.path.join(folder, stem + ".dng"), "wb") as f:
                f.write(b"dng")
        return stem

    _template = None

    def full_day(self, day=DAY, **kw):
        """288 regular frames (24 when options are given). The plain day is built once and hard-linked into each test's tree (Windows
        file creation is slow); no test rewrites one of its files, so sharing them is safe."""
        if kw or day != DAY:       # tests passing options only look at the fields they set: 2 hours is enough
            for i in range(24 if kw else 288):
                self.frame(day + timedelta(minutes=5 * i), **kw)
            return
        if Tree._template is None:
            Tree._template = tempfile.mkdtemp()
            atexit.register(shutil.rmtree, Tree._template, True)
            saved, self.root = self.root, os.path.join(Tree._template, "wide")
            for i in range(288):
                self.frame(day + timedelta(minutes=5 * i))
            self.root = saved
        shutil.copytree(os.path.join(Tree._template, "wide", "2026"), os.path.join(self.root, "2026"),
                        copy_function=os.link, dirs_exist_ok=True)

    def run_health(self, *extra, day="2026-11-10", now=NOW):
        rc = health.main([self.root, "--day", day, "--now", now, "--out", self.out, "--min-jpg-bytes", "2"]
                         + list(extra))
        self.assertEqual(rc, 0)
        with open(os.path.join(self.out, day + ".json")) as f:
            return json.load(f)


class GoodDay(Tree):
    def test_full_day_is_ok(self):
        self.full_day()
        r = self.run_health()
        self.assertEqual(r["problems"], [])
        self.assertTrue(r["ok"])
        self.assertTrue(r["complete"])
        self.assertEqual(r["frames"]["regular"], {"present": 288, "expected": 288})
        self.assertEqual(r["frames"]["dng"], {"present": 288, "expected": 288})
        self.assertEqual(r["frames"]["night"], {"present": 0, "expected": 0})
        self.assertEqual(r["frames"]["dense"]["expected"], None)
        self.assertEqual(r["largest_gap_min"], 5.0)
        self.assertEqual(r["max_cpu_temp_c"], 50.0)
        self.assertEqual(r["throttled_seen"], "0x0")
        self.assertEqual(r["max_outbox_pending_files"], 2)
        self.assertEqual(r["max_disk_used_pct"], 40.0)
        self.assertEqual(r["min_jpg_bytes"], 4)
        self.assertEqual(r["setup_ids"], ["pilot-4"])
        self.assertEqual(r["setup_id_changes"], [])

    def test_latest_json_written_for_a_finished_day_only_and_never_goes_backwards(self):
        self.full_day()
        self.run_health()
        latest = os.path.join(self.out, "latest.json")
        with open(latest) as f:
            self.assertEqual(json.load(f)["day_utc"], "2026-11-10")
        self.frame(datetime(2026, 11, 9, 12, tzinfo=UTC))
        self.run_health(day="2026-11-09")
        with open(latest) as f:
            self.assertEqual(json.load(f)["day_utc"], "2026-11-10")      # the older day did not replace it
        self.run_health(day="2026-11-11", now="2026-11-11T03:00:00Z")    # today: not finished
        with open(latest) as f:
            self.assertEqual(json.load(f)["day_utc"], "2026-11-10")

    def test_partial_day_expects_only_the_slots_so_far(self):
        for i in range(25):      # 00:00 to 02:00 inclusive
            self.frame(DAY + timedelta(minutes=5 * i))
        r = self.run_health(day="2026-11-10", now="2026-11-10T02:00:00Z")
        self.assertFalse(r["complete"])
        self.assertEqual(r["frames"]["regular"], {"present": 25, "expected": 25})
        self.assertNotIn("regular_low", r["problems"])


class Gaps(Tree):
    def test_missing_frames_and_largest_gap(self):
        for i in range(288):
            t = DAY + timedelta(minutes=5 * i)
            if timedelta(hours=12) < t - DAY < timedelta(hours=13):   # 12:05 to 12:55 lost: 11 frames
                continue
            self.frame(t)
        r = self.run_health()
        self.assertEqual(r["frames"]["regular"]["present"], 277)
        self.assertEqual(r["largest_gap_min"], 60.0)
        self.assertEqual(r["largest_gap_start_utc"], "2026-11-10T12:00:00Z")
        self.assertIn("gap", r["problems"])
        self.assertNotIn("regular_low", r["problems"])       # 277 of 288 is over 90%

    def test_half_a_day_is_regular_low_and_the_end_of_the_day_counts_as_a_gap(self):
        for i in range(144):
            self.frame(DAY + timedelta(minutes=5 * i))
        r = self.run_health()
        self.assertIn("regular_low", r["problems"])
        self.assertEqual(r["largest_gap_min"], 725.0)         # 11:55 to the end of the day: 12 h and 5 min

    def test_no_frames(self):
        os.makedirs(self.root)
        r = self.run_health()
        self.assertEqual(r["problems"], ["no_frames"])
        self.assertIsNone(r["largest_gap_min"])


class Blocks(Tree):
    def test_missing_blocks_counted(self):
        self.full_day()
        self.frame(DAY + timedelta(minutes=1), schedule="dense", capture=False, sun=False, system=False)
        self.frame(DAY + timedelta(minutes=2), schedule="dense", system=False)
        r = self.run_health()
        self.assertEqual(r["missing_blocks"], {"no_sun": 1, "no_capture": 1, "no_system": 2, "unreadable_json": 0,
                                           "bad_rpicam_metadata": 0, "no_sha256": 0})
        self.assertIn("no_meta", r["problems"])

    def test_lost_camera_metadata_and_missing_checksum_are_counted(self):
        self.full_day()
        stem = self.frame(DAY + timedelta(minutes=1), schedule="dense")
        path = os.path.join(self.folder(DAY), stem + ".json")
        with open(path) as f:
            data = json.load(f)
        data["rpicam_metadata"] = "invalid"
        data["Capture"]["unavailable"] = ["sha256"]
        with open(path, "w") as f:
            json.dump(data, f)
        r = self.run_health()
        self.assertEqual(r["missing_blocks"]["bad_rpicam_metadata"], 1)
        self.assertEqual(r["missing_blocks"]["no_sha256"], 1)
        self.assertIn("camera_metadata", r["problems"])
        self.assertIn("no_checksum", r["problems"])

    def test_old_frames_without_capture_use_the_minute_to_tell_regular_from_dense(self):
        for minute in (0, 1, 2, 5):
            self.frame(DAY + timedelta(minutes=minute), capture=False, system=False, sun=False)
        r = self.run_health(day="2026-11-10", now="2026-11-10T00:30:00Z")
        self.assertEqual(r["frames"]["regular"]["present"], 2)
        self.assertEqual(r["frames"]["dense"]["present"], 2)

    def test_unreadable_json(self):
        self.full_day()
        self.frame(DAY + timedelta(minutes=1), schedule="dense", broken=True)
        r = self.run_health()
        self.assertEqual(r["missing_blocks"]["unreadable_json"], 1)
        self.assertIn("unreadable_json", r["problems"])


class SetupChange(Tree):
    def test_setup_id_change_is_recorded_not_alarmed(self):
        for i in range(288):
            self.frame(DAY + timedelta(minutes=5 * i), setup_id="pilot-3" if i < 100 else "pilot-4")
        r = self.run_health()
        self.assertEqual(r["setup_ids"], ["pilot-3", "pilot-4"])
        self.assertEqual(r["setup_id_changes"], [{"at_utc": "2026-11-10T08:20:00Z", "from": "pilot-3", "to": "pilot-4"}])
        self.assertEqual(r["problems"], [])


class SystemBlock(Tree):
    def test_throttle_temperature_outbox_disk(self):
        self.full_day()
        self.frame(DAY + timedelta(minutes=1), schedule="dense", throttled="0x50005", temp=78.4, outbox=120, disk=91.0)
        r = self.run_health()
        self.assertEqual(r["throttled_seen"], "0x50005")
        self.assertEqual(r["throttled_flags"], ["undervoltage", "throttled", "undervoltage_occurred", "throttled_occurred"])
        self.assertEqual(r["max_cpu_temp_c"], 78.4)
        self.assertEqual(r["max_outbox_pending_files"], 120)
        self.assertEqual(r["max_disk_used_pct"], 91.0)
        for p in ("throttled", "hot", "outbox", "disk"):
            self.assertIn(p, r["problems"])

    def test_history_bits_alone_do_not_alarm(self):
        self.full_day(throttled="0x80000")
        r = self.run_health()
        self.assertEqual(r["throttled_flags"], ["soft_temp_limit_occurred"])
        self.assertNotIn("throttled", r["problems"])

    def test_small_jpeg_from_disk_not_json(self):
        self.full_day(jpg=b"x" * 10)
        self.frame(DAY + timedelta(minutes=1), schedule="dense", jpg=b"")
        r = self.run_health()
        self.assertEqual(r["min_jpg_bytes"], 0)
        self.assertIn("small_jpeg", r["problems"])

    def test_floor_default_is_applied(self):
        self.full_day(jpg=b"x" * 10)
        rc = health.main([self.root, "--day", "2026-11-10", "--now", NOW, "--out", self.out])
        with open(os.path.join(self.out, "2026-11-10.json")) as f:
            self.assertIn("small_jpeg", json.load(f)["problems"])


class FrameTypes(Tree):
    def test_dense_expected_is_derived_from_the_windows(self):
        self.full_day()
        # Window 10:01 to 10:09: dense minutes are 1,2,3,4,6,7,8,9 = 8. Frames at 3 and 7 are lost.
        for m in (1, 2, 4, 6, 8, 9):
            self.frame(DAY + timedelta(hours=10, minutes=m), schedule="dense", dng=False)
        # A second window in the evening, complete: 20:01 to 20:04, four frames.
        for m in (1, 2, 3, 4):
            self.frame(DAY + timedelta(hours=20, minutes=m), schedule="dense", dng=False)
        r = self.run_health()
        d = r["frames"]["dense"]
        self.assertEqual((d["present"], d["expected"]), (10, 12))
        self.assertEqual(d["scheduled_basis"], "frames")
        self.assertEqual([(w["present"], w["expected"]) for w in d["windows"]], [(6, 8), (4, 4)])
        self.assertEqual(r["frames"]["dng"], {"present": 288, "expected": 288})    # dense never has a DNG
        self.assertIn("dense_low", r["problems"])                                   # 10 of 12 is 83%, under 90%

    def test_dense_low_when_too_many_lost(self):
        self.full_day()
        for m in (1, 4, 9):
            self.frame(DAY + timedelta(hours=10, minutes=m), schedule="dense", dng=False)
        r = self.run_health()
        self.assertEqual(r["frames"]["dense"]["expected"], 8)
        self.assertIn("dense_low", r["problems"])

    def test_no_dense_frames_and_none_the_day_before_is_not_scheduled(self):
        self.full_day()
        r = self.run_health()
        self.assertIsNone(r["frames"]["dense"]["expected"])
        self.assertIsNone(r["frames"]["dense"]["scheduled_basis"])
        self.assertNotIn("dense_stopped", r["problems"])

    def test_dense_stopping_is_flagged_from_the_day_before(self):
        prev = DAY - timedelta(days=1)
        for m in (1, 2):
            self.frame(prev + timedelta(hours=10, minutes=m), schedule="dense", dng=False)
        self.run_health(day="2026-11-09", now="2026-11-10T02:00:00Z")
        self.full_day()
        r = self.run_health()
        self.assertEqual(r["frames"]["dense"]["scheduled_basis"], "previous_day")
        self.assertIn("dense_stopped", r["problems"])

    def test_night_frames_expected_where_lux_was_under_the_limit(self):
        for i in range(288):
            dark = i < 10                       # the first 10 slots were dark
            when = DAY + timedelta(minutes=5 * i)
            self.frame(when, lux=2 if dark else 500, night_lux=10)
            if dark and i != 3:                 # the 4th night frame failed
                self.frame(when, night=True)
        r = self.run_health()
        self.assertEqual(r["frames"]["night"], {"present": 9, "expected": 10})
        self.assertIn("night_missing", r["problems"])
        self.assertEqual(r["frames"]["regular"]["present"], 288)

    def test_dropped_dng_is_flagged(self):
        for i in range(288):
            self.frame(DAY + timedelta(minutes=5 * i), dng=(i % 100 != 0))
        r = self.run_health()
        self.assertEqual(r["frames"]["dng"], {"present": 285, "expected": 288})
        self.assertIn("dng_missing", r["problems"])

    def test_raw_off_everywhere_expects_no_dng(self):
        self.full_day(dng=False)
        r = self.run_health()
        self.assertEqual(r["frames"]["dng"], {"present": 0, "expected": 0})
        self.assertNotIn("dng_missing", r["problems"])

    def test_json_without_jpeg(self):
        self.full_day()
        self.frame(DAY + timedelta(minutes=1), schedule="dense", jpg=None, dng=False)
        r = self.run_health()
        self.assertEqual(r["frames"]["jpg_missing"], 1)
        self.assertIn("jpg_missing", r["problems"])


class Cli(Tree):
    def test_backfill_days_and_default_out_folder(self):
        for d in (9, 10):
            self.frame(datetime(2026, 11, d, 12, tzinfo=UTC))
        health.main([self.root, "--day", "2026-11-10", "--days", "2", "--now", NOW])
        base = os.path.join(self.tmp, "health", "wide")
        self.assertTrue(os.path.exists(os.path.join(base, "2026-11-09.json")))
        self.assertTrue(os.path.exists(os.path.join(base, "2026-11-10.json")))
        with open(os.path.join(base, "latest.json")) as f:
            self.assertEqual(json.load(f)["day_utc"], "2026-11-10")
        self.assertEqual([n for n in os.listdir(base) if n.endswith(".tmp")], [])

    def test_yesterday_is_the_default(self):
        self.frame(datetime(2026, 11, 10, 12, tzinfo=UTC))
        health.main([self.root, "--now", "2026-11-11T02:00:00Z", "--out", self.out])
        self.assertTrue(os.path.exists(os.path.join(self.out, "2026-11-10.json")))

    def test_bad_folder_and_bad_day(self):
        self.assertEqual(health.main([os.path.join(self.tmp, "nope")]), 2)
        os.makedirs(self.root)
        self.assertEqual(health.main([self.root, "--day", "banana"]), 2)

    def test_nothing_reads_images_or_changes_frames(self):
        self.full_day()
        before = sorted((n, os.path.getmtime(os.path.join(self.folder(DAY), n))) for n in os.listdir(self.folder(DAY)))
        self.run_health()
        after = sorted((n, os.path.getmtime(os.path.join(self.folder(DAY), n))) for n in os.listdir(self.folder(DAY)))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
