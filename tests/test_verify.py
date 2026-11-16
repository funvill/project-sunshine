"""Tests for nas/sunset-verify.py: python3 tests/test_verify.py

Fixture trees under a temp folder, no NAS. Every expected number is worked out by hand.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "nas", "sunset-verify.py")
spec = importlib.util.spec_from_file_location("sunset_verify", SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

NOW = "2026-11-15T12:00:00Z"
OLD = 1700000000        # mtime far enough in the past to count as settled


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "wide")
        self.state = os.path.join(self.tmp, "verify.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, data):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        os.utime(path, (OLD, OLD))
        return path

    def frame(self, day, ts, jpg=b"jpegdata", dng=b"dngdata", capture=True, checksums=True, night=False):
        stem = "wide_%s%s" % (ts, "_night" if night else "")
        folder = day
        meta = {"Lux": 100}
        if capture:
            files = {}
            if jpg is not None:
                files["jpg"] = {"bytes": len(jpg)}
                if checksums:
                    files["jpg"]["sha256"] = sha(jpg)
            if dng is not None:
                files["dng"] = {"bytes": len(dng)}
                if checksums:
                    files["dng"]["sha256"] = sha(dng)
            meta["Capture"] = {"schema_version": 2, "files": files}
        self.write("%s/%s.json" % (folder, stem), json.dumps(meta).encode())
        if jpg is not None:
            self.write("%s/%s.jpg" % (folder, stem), jpg)
        if dng is not None:
            self.write("%s/%s.dng" % (folder, stem), dng)
        return stem

    def run_verify(self, *extra):
        return verify.main([self.root, "--state", self.state, "--now", NOW] + list(extra))

    def result(self):
        with open(self.state) as f:
            return json.load(f)


class GoodDay(Tree):
    def test_clean_day_passes(self):
        self.frame("2026/11/10", "20261110T120000Z")
        self.frame("2026/11/10", "20261110T120000Z", night=True)
        self.assertEqual(self.run_verify(), 0)
        r = self.result()
        self.assertTrue(r["ok"])
        self.assertEqual(r["run"]["files_checked"], 4)
        self.assertEqual(r["run"]["frames"], 2)
        self.assertEqual(r["bad_files"], [])
        self.assertEqual(r["last_run_utc"], NOW)
        self.assertIn("2026/11/10", r["days"])

    def test_system_json_is_not_a_frame(self):
        self.frame("2026/11/10", "20261110T120000Z")
        self.write("2026/11/10/system.json", b'{"records": []}')
        self.assertEqual(self.run_verify(), 0)
        self.assertEqual(self.result()["run"]["frames"], 1)

    def test_never_modifies_frames(self):
        self.frame("2026/11/10", "20261110T120000Z", dng=b"changed-after-hash")
        # corrupt the DNG so there is a problem to report
        with open(os.path.join(self.root, "2026/11/10/wide_20261110T120000Z.dng"), "wb") as f:
            f.write(b"XXXXXXXXXXXXXXXXXX")
        folder = os.path.join(self.root, "2026/11/10")

        def snapshot():
            out = {}
            for n in os.listdir(folder):
                with open(os.path.join(folder, n), "rb") as f:
                    out[n] = (f.read(), os.path.getmtime(os.path.join(folder, n)))
            return out
        before = snapshot()
        self.run_verify()
        self.assertEqual(before, snapshot())


class Problems(Tree):
    def paths(self):
        return {(b["path"], b["problem"]) for b in self.result()["bad_files"]}

    def test_missing_file(self):
        self.frame("2026/11/10", "20261110T120000Z")
        os.remove(os.path.join(self.root, "2026/11/10/wide_20261110T120000Z.dng"))
        self.assertEqual(self.run_verify(), 1)
        self.assertEqual(self.paths(), {("2026/11/10/wide_20261110T120000Z.dng", "missing")})
        self.assertEqual(self.result()["problem_counts"]["missing"], 1)

    def test_hash_mismatch_same_size(self):
        self.frame("2026/11/10", "20261110T120000Z", jpg=b"AAAAAAAA")
        self.write("2026/11/10/wide_20261110T120000Z.jpg", b"BBBBBBBB")
        self.assertEqual(self.run_verify(), 1)
        self.assertEqual(self.paths(), {("2026/11/10/wide_20261110T120000Z.jpg", "mismatch")})
        self.assertEqual(self.result()["problem_counts"]["mismatched"], 1)

    def test_size_mismatch(self):
        self.frame("2026/11/10", "20261110T120000Z")
        self.write("2026/11/10/wide_20261110T120000Z.jpg", b"short")
        self.assertEqual(self.run_verify(), 1)
        self.assertEqual(self.result()["problem_counts"]["mismatched"], 1)

    def test_zero_length(self):
        self.frame("2026/11/10", "20261110T120000Z")
        self.write("2026/11/10/wide_20261110T120000Z.jpg", b"")
        self.assertEqual(self.run_verify(), 1)
        self.assertEqual(self.paths(), {("2026/11/10/wide_20261110T120000Z.jpg", "zero_length")})
        self.assertEqual(self.result()["problem_counts"]["zero_length"], 1)

    def test_zero_length_jpg_without_capture_block_is_still_flagged(self):
        self.frame("2026/11/10", "20261110T120000Z", capture=False, jpg=b"", dng=None)
        self.assertEqual(self.run_verify(), 1)

    def test_empty_and_broken_json(self):
        self.write("2026/11/10/wide_20261110T120000Z.json", b"")
        self.write("2026/11/10/wide_20261110T120500Z.json", b"{not json")
        self.assertEqual(self.run_verify(), 1)
        self.assertEqual(self.result()["problem_counts"]["unreadable_json"], 2)

    def test_problem_stays_on_the_report_until_fixed(self):
        self.frame("2026/11/10", "20261110T120000Z", jpg=b"AAAAAAAA")
        self.write("2026/11/10/wide_20261110T120000Z.jpg", b"BBBBBBBB")
        self.assertEqual(self.run_verify(), 1)
        self.assertEqual(self.run_verify(), 1)       # a second run does not forget it
        self.write("2026/11/10/wide_20261110T120000Z.jpg", b"AAAAAAAA")
        self.assertEqual(self.run_verify(), 0)       # the bad day is re-read first, and clears
        self.assertEqual(self.result()["bad_files"], [])

    def test_vanished_day_is_a_problem(self):
        self.frame("2026/11/10", "20261110T120000Z")
        self.assertEqual(self.run_verify(), 0)
        shutil.rmtree(os.path.join(self.root, "2026/11/10"))
        self.frame("2026/11/11", "20261111T120000Z")
        self.assertEqual(self.run_verify(), 1)
        self.assertEqual(self.paths(), {("2026/11/10", "missing_day")})
        self.assertEqual(self.run_verify("--forget-missing"), 0)

    def test_many_bad_files_are_capped_but_counted(self):
        for i in range(60):
            self.frame("2026/11/10", "20261110T12%02d00Z" % i, jpg=b"")
        self.assertEqual(self.run_verify(), 1)
        r = self.result()
        self.assertEqual(r["problem_counts"]["zero_length"] + r["problem_counts"]["other"], 60)


class Unverifiable(Tree):
    def test_frame_without_capture_block_is_not_an_error(self):
        self.frame("2026/11/04", "20261104T120000Z", capture=False)
        self.assertEqual(self.run_verify(), 0)
        r = self.result()
        self.assertTrue(r["ok"])
        self.assertEqual(r["run"]["unverifiable"], 1)
        self.assertEqual(r["run"]["files_checked"], 0)

    def test_no_checksum_is_unverifiable_but_size_still_checked(self):
        self.frame("2026/11/10", "20261110T120000Z", checksums=False)
        self.assertEqual(self.run_verify(), 0)
        self.assertEqual(self.result()["run"]["unverifiable"], 2)
        self.write("2026/11/10/wide_20261110T120000Z.jpg", b"different length!")
        self.assertEqual(self.run_verify(), 1)


class RecentFiles(Tree):
    def test_file_still_arriving_is_skipped_and_day_not_marked_done(self):
        stem = self.frame("2026/11/15", "20261115T115500Z")
        recent = os.path.join(self.root, "2026/11/15", stem + ".jpg")
        # half-copied JPEG that changed 1 minute before NOW
        with open(recent, "wb") as f:
            f.write(b"half")
        t = verify.datetime.strptime(NOW, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=verify.timezone.utc).timestamp() - 60
        os.utime(recent, (t, t))
        self.assertEqual(self.run_verify(), 0)
        r = self.result()
        self.assertEqual(r["run"]["skipped_recent"], 1)
        self.assertNotIn("2026/11/15", r["days"])           # read again next run
        os.utime(recent, (OLD, OLD))
        self.write("2026/11/15/%s.jpg" % stem, b"jpegdata")
        self.assertEqual(self.run_verify(), 0)
        self.assertIn("2026/11/15", self.result()["days"])


class Selection(Tree):
    def test_new_days_then_rolling_slice(self):
        for d in range(1, 7):
            self.frame("2026/11/%02d" % d, "202611%02dT120000Z" % d)
        self.assertEqual(self.run_verify("--cycle-days", "3"), 0)
        self.assertEqual(self.result()["run"]["days_checked"], 6)      # all new
        self.assertEqual(self.run_verify("--cycle-days", "3"), 0)
        self.assertEqual(self.result()["run"]["days_checked"], 2)      # ceil(6 / 3)
        stamps = sorted(e["verified_utc"] for e in self.result()["days"].values())
        self.assertTrue(stamps)

    def test_rolling_slice_reaches_every_day(self):
        for d in range(1, 5):
            self.frame("2026/11/%02d" % d, "202611%02dT120000Z" % d)
        self.run_verify("--cycle-days", "2")
        seen = set()
        # Make the verified times distinct and ordered so oldest-first is observable.
        st = self.result()
        for i, day in enumerate(sorted(st["days"])):
            st["days"][day]["verified_utc"] = "2026-11-0%dT00:00:00Z" % (i + 1)
        with open(self.state, "w") as f:
            json.dump(st, f)
        # Damage the file of the oldest-verified day; the first rolling run must reach it.
        self.write("2026/11/01/wide_20261101T120000Z.jpg", b"BBBBBBBB")
        self.assertEqual(self.run_verify("--cycle-days", "2"), 1)
        seen = {b["path"] for b in self.result()["bad_files"]}
        self.assertEqual(seen, {"2026/11/01/wide_20261101T120000Z.jpg"})

    def test_all_reads_everything(self):
        for d in range(1, 4):
            self.frame("2026/11/%02d" % d, "202611%02dT120000Z" % d)
        self.run_verify()
        self.run_verify("--all")
        self.assertEqual(self.result()["run"]["days_checked"], 3)

    def test_max_days_caps_a_run(self):
        for d in range(1, 6):
            self.frame("2026/11/%02d" % d, "202611%02dT120000Z" % d)
        self.run_verify("--max-days", "2")
        self.assertEqual(self.result()["run"]["days_checked"], 2)
        self.run_verify("--max-days", "2")
        self.run_verify("--max-days", "2")
        self.assertEqual(len(self.result()["days"]), 5)


class Output(Tree):
    def test_state_is_written_atomically_with_no_temp_left(self):
        self.frame("2026/11/10", "20261110T120000Z")
        self.run_verify()
        leftovers = [n for n in os.listdir(self.tmp) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_missing_folder_is_a_usage_error(self):
        self.assertEqual(verify.main([os.path.join(self.tmp, "nope"), "--state", self.state]), 2)

    def test_default_state_path_is_beside_the_camera_folder(self):
        self.frame("2026/11/10", "20261110T120000Z")
        verify.main([self.root, "--now", NOW])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "health", "wide", "verify.json")))


if __name__ == "__main__":
    unittest.main()
