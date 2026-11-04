"""Tests for sunset-diag.py: python3 tests/test_diag.py"""
import calendar
import importlib.util
import json
import os
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sunset_diag", os.path.join(os.path.dirname(HERE), "pi", "sunset-diag.py"))
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def epoch(text):
    return calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))


NOW = epoch("2026-11-04T12:00:00Z")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class Throttled(unittest.TestCase):
    def test_all_clear(self):
        self.assertEqual(diag.parse_throttled("throttled=0x0"), {"now": [], "since_boot": []})

    def test_current_undervoltage(self):
        self.assertIn("undervoltage", diag.parse_throttled("throttled=0x1")["now"])

    def test_past_throttling_is_not_reported_as_current(self):
        r = diag.parse_throttled("throttled=0x40000")
        self.assertEqual(r["now"], [])
        self.assertIn("throttled", r["since_boot"])

    def test_unreadable_output(self):
        self.assertIsNone(diag.parse_throttled(None))
        self.assertIsNone(diag.parse_throttled("garbage"))


class CaptureLog(unittest.TestCase):
    LINES = [
        "2026-11-03T06:00:03Z cam=wide lux=1 soc=48'C disk=5% raw=1 night=0 sun=na ok",     # over 24 h ago
        "2026-11-03T05:00:00Z cam=wide FAILED capture rc=1 err=old|",
        "2026-11-04T11:15:03Z cam=wide FAILED capture rc=1 err=camera busy|",
        "2026-11-04T11:30:03Z cam=wide SKIPPED: clock not synced since boot",
        "2026-11-04T11:45:03Z cam=wide DISK 85% >= 85%: dropping DNG for this frame",
        "2026-11-04T11:45:09Z cam=wide lux=13.4 soc=48.3'C disk=5% raw=1 night=0 sun=az=1,el=2 ok",
    ]

    def test_last_success_is_found(self):
        s = diag.summarize_capture_log(self.LINES, NOW)
        self.assertEqual(s["last_ok_age_s"], NOW - epoch("2026-11-04T11:45:09Z"))
        self.assertEqual(s["last_lux"], "13.4")

    def test_only_recent_problems_count(self):
        self.assertEqual(diag.summarize_capture_log(self.LINES, NOW)["problems_24h"], 2)

    def test_empty_log(self):
        s = diag.summarize_capture_log([], NOW)
        self.assertIsNone(s["last_ok_age_s"])
        self.assertEqual(s["problems_24h"], 0)

    def test_unparseable_line_is_ignored(self):
        self.assertEqual(diag.summarize_capture_log(["not a log line FAILED"], NOW)["problems_24h"], 0)


class TailLines(unittest.TestCase):
    def test_returns_last_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.log")
            write(p, "".join("line %d\n" % i for i in range(100)))
            self.assertEqual(diag.tail_lines(p, 2), ["line 98", "line 99"])

    def test_missing_file(self):
        self.assertEqual(diag.tail_lines("/nonexistent/x.log", 5), [])


class Outbox(unittest.TestCase):
    def test_counts_waiting_frames_and_skips_partial(self):
        with tempfile.TemporaryDirectory() as d:
            write(os.path.join(d, "wide/2026/11/04/a.jpg"), "x")
            write(os.path.join(d, "wide/2026/11/04/a.json"), json.dumps(
                {"Lux": 7.5, "ExposureTime": 1000, "AnalogueGain": 2.0}))
            write(os.path.join(d, ".partial/half.jpg"), "x")
            for name in ("a.jpg", "a.json"):
                os.utime(os.path.join(d, "wide/2026/11/04", name), (NOW - 600, NOW - 600))
            s = diag.summarize_outbox(d, NOW)
            self.assertEqual(s["files"], 2)
            self.assertEqual(s["oldest_age_s"], 600)
            self.assertEqual(s["newest_frame"]["AnalogueGain"], 2.0)
            self.assertEqual(s["newest_frame"]["Lux"], 7.5)

    def test_missing_outbox(self):
        s = diag.summarize_outbox("/nonexistent/outbox", NOW)
        self.assertEqual(s["files"], 0)
        self.assertIsNone(s["oldest_age_s"])
        self.assertIsNone(s["newest_frame"])

    def test_corrupt_json_does_not_break_the_page(self):
        with tempfile.TemporaryDirectory() as d:
            write(os.path.join(d, "wide/a.json"), "{not json")
            self.assertIsNone(diag.summarize_outbox(d, NOW)["newest_frame"])


class Nas(unittest.TestCase):
    MOUNTED = ("30 25 0:30 / /mnt/nas-camera rw - autofs systemd-1 rw\n"
               "31 30 0:31 / /mnt/nas-camera rw,relatime - cifs //nas/camera rw\n")
    IDLE = "30 25 0:30 / /mnt/nas-camera rw - autofs systemd-1 rw\n"
    NONE = "22 1 179:2 / / rw - ext4 /dev/mmcblk0p2 rw\n"

    def test_mounted_share(self):
        self.assertEqual(diag.nas_state("/mnt/nas-camera/project_sunshine/", self.MOUNTED), "mounted")

    def test_idle_automount_is_normal(self):
        self.assertEqual(diag.nas_state("/mnt/nas-camera/project_sunshine/", self.IDLE), "automount idle")

    def test_no_mount(self):
        self.assertEqual(diag.nas_state("/mnt/nas-camera/project_sunshine/", self.NONE), "not mounted")

    def test_similar_path_is_not_a_match(self):
        self.assertEqual(diag.nas_state("/mnt/nas-camera2/x/", self.MOUNTED), "not mounted")

    def test_ssh_target_hides_the_address(self):
        self.assertEqual(diag.nas_state("sunset@nas.local:/volume1/x/", self.NONE), "rsync over ssh")

    def test_unset(self):
        self.assertEqual(diag.nas_state("", self.NONE), "not configured")


def healthy():
    return {
        "capture": {"timer_enabled": "enabled", "last_ok_age_s": 300, "problems_24h": 0},
        "outbox": {"oldest_age_s": 60},
        "nas": {"state": "mounted"},
        "system": {"ntp_synced": True, "disk_used_pct": 5, "throttled": {"now": [], "since_boot": []}},
    }


class Warnings(unittest.TestCase):
    def test_healthy_has_no_warnings(self):
        self.assertEqual(diag.find_warnings(healthy()), [])

    def assertWarns_(self, status, word):
        self.assertTrue(any(word in w for w in diag.find_warnings(status)), diag.find_warnings(status))

    def test_disabled_timer(self):
        s = healthy(); s["capture"]["timer_enabled"] = "disabled"
        self.assertWarns_(s, "NOT capturing")

    def test_stale_capture(self):
        s = healthy(); s["capture"]["last_ok_age_s"] = 3600
        self.assertWarns_(s, "last good capture")

    def test_capture_problems(self):
        s = healthy(); s["capture"]["problems_24h"] = 3
        self.assertWarns_(s, "3 capture problems")

    def test_frames_stuck(self):
        s = healthy(); s["outbox"]["oldest_age_s"] = 7200
        self.assertWarns_(s, "waiting")

    def test_clock(self):
        s = healthy(); s["system"]["ntp_synced"] = False
        self.assertWarns_(s, "clock")

    def test_disk(self):
        s = healthy(); s["system"]["disk_used_pct"] = 85
        self.assertWarns_(s, "disk")

    def test_undervoltage_now(self):
        s = healthy(); s["system"]["throttled"]["now"] = ["undervoltage"]
        self.assertWarns_(s, "undervoltage")

    def test_nas_missing(self):
        s = healthy(); s["nas"]["state"] = "not mounted"
        self.assertWarns_(s, "NAS")


class CollectStatus(unittest.TestCase):
    def collect(self, d, run=None):
        cfg = diag.Config(out_root=os.path.join(d, "outbox"), capture_log=os.path.join(d, "capture.log"),
                          sync_log=os.path.join(d, "sync.log"), nas_target="/mnt/nas/x/",
                          sun_script="sunset-sun.py", mountinfo="/nonexistent")
        return diag.collect_status(cfg, run or (lambda cmd: None), NOW)

    def test_survives_every_command_failing(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.collect(d)
            self.assertIsNone(s["system"]["temp"])
            self.assertIsInstance(s["warnings"], list)
            json.dumps(s)

    def test_reports_timer_and_commands(self):
        answers = {"is-enabled": "enabled\n", "measure_temp": "temp=48.3'C\n", "get_throttled": "throttled=0x0\n",
                   "NTPSynchronized": "yes\n", "-I": "192.0.2.5 \n"}

        def run(cmd):
            for k, v in answers.items():
                if k in " ".join(cmd):
                    return v
            return None

        with tempfile.TemporaryDirectory() as d:
            s = self.collect(d, run)
            self.assertEqual(s["capture"]["timer_enabled"], "enabled")
            self.assertEqual(s["system"]["temp"], "48.3'C")
            self.assertTrue(s["system"]["ntp_synced"])
            self.assertEqual(s["system"]["ips"], ["192.0.2.5"])

    def test_never_includes_site_coordinates(self):
        old = {k: os.environ.get(k) for k in ("SITE_LAT", "SITE_LON")}
        os.environ.update(SITE_LAT="12.3456", SITE_LON="-98.7654")
        try:
            with tempfile.TemporaryDirectory() as d:
                text = json.dumps(self.collect(d))
            self.assertNotIn("12.3456", text)
            self.assertNotIn("98.7654", text)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main(verbosity=1)
