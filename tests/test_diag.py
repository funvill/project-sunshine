"""Tests for sunset-diag.py: python3 tests/test_diag.py"""
import calendar
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sunset_diag", os.path.join(os.path.dirname(HERE), "pi", "sunset-diag.py"))
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def epoch(text):
    return calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))


NOW = epoch("2026-11-04T12:00:00Z")
JPEG_A = b"\xff\xd8AAAA\xff\xd9"
JPEG_B = b"\xff\xd8BB\xff\xd9"
FAR_TIMER = '[{"next":9999999999000000}]'


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

    def test_age_is_whole_seconds_with_a_fractional_clock(self):
        self.assertIsInstance(diag.summarize_capture_log(self.LINES, NOW + 0.5)["last_ok_age_s"], int)

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

    def test_one_capture_problem_reads_properly(self):
        s = healthy(); s["capture"]["problems_24h"] = 1
        self.assertWarns_(s, "1 capture problem in")

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


class RunCommand(unittest.TestCase):
    def test_keeps_output_of_a_nonzero_exit(self):
        # `systemctl is-enabled` prints "disabled" and exits 1.
        cmd = [sys.executable, "-c", "import sys; print('disabled'); sys.exit(1)"]
        self.assertEqual(diag.run_command(cmd).strip(), "disabled")

    def test_missing_command(self):
        self.assertIsNone(diag.run_command(["no-such-command-here"]))


class FrameSplitter(unittest.TestCase):
    def test_whole_frames(self):
        s = diag.FrameSplitter()
        self.assertEqual(s.feed(JPEG_A + JPEG_B), [JPEG_A, JPEG_B])

    def test_frame_across_chunks(self):
        s = diag.FrameSplitter()
        self.assertEqual(s.feed(JPEG_A[:3]), [])
        self.assertEqual(s.feed(JPEG_A[3:]), [JPEG_A])

    def test_marker_split_between_chunks(self):
        s = diag.FrameSplitter()
        self.assertEqual(s.feed(JPEG_A[:-1]), [])
        self.assertEqual(s.feed(JPEG_A[-1:]), [JPEG_A])

    def test_garbage_before_a_frame_is_dropped(self):
        self.assertEqual(diag.FrameSplitter().feed(b"junk" + JPEG_A), [JPEG_A])

    def test_endless_garbage_does_not_grow_without_limit(self):
        s = diag.FrameSplitter(max_bytes=1000)
        for _ in range(10):
            s.feed(b"\xff\xd8" + b"x" * 900)
        self.assertLessEqual(s.buffered(), 2000)


class StreamCommand(unittest.TestCase):
    def test_full_view(self):
        c = diag.stream_command("full", 1280, 960)
        self.assertEqual(c[0], "rpicam-vid")
        for flag in ("--codec", "mjpeg", "-n", "1280", "960"):
            self.assertIn(flag, c)
        self.assertEqual(c[c.index("-o") + 1], "-")
        self.assertEqual(c[c.index("-t") + 1], "0")
        self.assertNotIn("--roi", c)

    def test_focus_view_crops_the_centre_at_full_sensor_resolution(self):
        c = diag.stream_command("focus", 1280, 960)
        self.assertEqual(c[c.index("--roi") + 1], "0.4,0.4,0.2,0.2")
        self.assertEqual(c[c.index("--mode") + 1], "4056:3040")


class NextCapture(unittest.TestCase):
    # Format from `systemctl list-timers --output=json` on the pilot Pi (systemd 252), with a time
    # off the quarter hour so that the fallback cannot pass these by accident.
    RUNNING = ('[{"next":1793774760000000,"left":1793774760000000,"last":0,"passed":0,'
               '"unit":"sunset-capture.timer","activates":"sunset-capture.service"}]\n')

    def test_reads_the_timer(self):
        self.assertEqual(diag.parse_next_capture(self.RUNNING, 1793774285), 1793774760)

    def test_a_time_already_passed_is_not_used(self):
        self.assertEqual(diag.parse_next_capture(self.RUNNING, 1793774761), (1793774761 // 900 + 1) * 900)

    def test_timer_stopped_falls_back_to_the_quarter_hour(self):
        self.assertEqual(diag.parse_next_capture("[]\n", epoch("2026-11-04T12:07:30Z")), epoch("2026-11-04T12:15:00Z"))

    def test_unexpected_json_falls_back(self):
        self.assertEqual(diag.parse_next_capture('[{"next":null}]', epoch("2026-11-04T12:07:30Z")), epoch("2026-11-04T12:15:00Z"))
        self.assertEqual(diag.parse_next_capture('{"a":1}', epoch("2026-11-04T12:07:30Z")), epoch("2026-11-04T12:15:00Z"))

    def test_timer_disabled_falls_back_to_the_quarter_hour(self):
        # A timer change must never remove the protection.
        self.assertEqual(diag.parse_next_capture("\n", epoch("2026-11-04T12:07:30Z")), epoch("2026-11-04T12:15:00Z"))
        self.assertEqual(diag.parse_next_capture(None, epoch("2026-11-04T12:15:00Z")), epoch("2026-11-04T12:30:00Z"))
        self.assertEqual(diag.parse_next_capture("n/a", epoch("2026-11-04T12:59:59Z")), epoch("2026-11-04T13:00:00Z"))


SLOT = epoch("2026-11-04T12:15:00Z")
NEXT = SLOT + 900


class Handover(unittest.TestCase):
    def setUp(self):
        self.p = diag.HandoverPolicy(margin_s=20, settle_s=5)

    def test_streams_when_far_from_a_capture(self):
        self.assertFalse(self.p.should_pause(SLOT - 60, SLOT, False))

    def test_pauses_before_the_slot(self):
        self.assertTrue(self.p.should_pause(SLOT - 20, SLOT, False))

    def test_stays_paused_after_the_timer_moves_on_before_the_service_starts(self):
        self.p.should_pause(SLOT - 20, SLOT, False)
        self.assertTrue(self.p.should_pause(SLOT + 1, NEXT, False))

    def test_stays_paused_while_the_capture_runs(self):
        self.p.should_pause(SLOT - 20, SLOT, False)
        self.assertTrue(self.p.should_pause(SLOT + 60, NEXT, True))

    def test_resumes_once_the_capture_has_finished(self):
        self.p.should_pause(SLOT - 20, SLOT, False)
        self.p.should_pause(SLOT + 1, NEXT, True)
        self.assertFalse(self.p.should_pause(SLOT + 12, NEXT, False))

    def test_a_capture_started_by_hand_pauses_too(self):
        self.assertTrue(self.p.should_pause(SLOT - 300, SLOT, True))


FAKE_CAMERA = """
import sys, time
frame = b"\\xff\\xd8" + b"frame" + b"\\xff\\xd9"
while True:
    sys.stdout.buffer.write(frame)
    sys.stdout.buffer.flush()
    time.sleep(0.02)
"""
CRASHING_CAMERA = "import sys; sys.stderr.write('ERROR: *** no cameras available ***\\n'); sys.exit(1)"


def wait_until(condition, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


class CameraTests(unittest.TestCase):
    def camera(self, source=FAKE_CAMERA, **kw):
        cam = diag.Camera(lambda view: [sys.executable, "-c", source], **kw)
        self.addCleanup(cam.stop)
        return cam

    def test_does_not_touch_the_camera_without_a_viewer(self):
        cam = self.camera()
        cam.tick(NOW, wanted=False, paused=False)
        self.assertFalse(cam.running())
        self.assertEqual(cam.state(), "idle")

    def test_streams_frames_when_wanted(self):
        cam = self.camera()
        cam.tick(NOW, wanted=True, paused=False)
        self.assertTrue(wait_until(lambda: cam.latest()[1] is not None))
        self.assertEqual(cam.latest()[1], b"\xff\xd8frame\xff\xd9")
        self.assertEqual(cam.state(), "streaming")

    def test_releases_the_camera_when_paused(self):
        cam = self.camera()
        cam.tick(NOW, wanted=True, paused=False)
        cam.tick(NOW + 1, wanted=True, paused=True)
        self.assertFalse(cam.running())
        self.assertEqual(cam.state(), "paused for capture")

    def test_resumes_after_a_pause(self):
        cam = self.camera()
        cam.tick(NOW, wanted=True, paused=True)
        self.assertFalse(cam.running())
        cam.tick(NOW + 1, wanted=True, paused=False)
        self.assertTrue(cam.running())

    def test_stops_when_the_last_viewer_leaves(self):
        cam = self.camera()
        cam.tick(NOW, wanted=True, paused=False)
        cam.tick(NOW + 1, wanted=False, paused=False)
        self.assertFalse(cam.running())

    def test_changing_view_restarts_with_the_new_command(self):
        views = []

        def build(view):
            views.append(view)
            return [sys.executable, "-c", FAKE_CAMERA]

        cam = diag.Camera(build)
        self.addCleanup(cam.stop)
        cam.tick(NOW, wanted=True, paused=False)
        cam.set_view("focus")
        cam.tick(NOW + 1, wanted=True, paused=False)
        self.assertEqual(views, ["full", "focus"])

    def test_crash_is_reported_and_retried_with_a_delay(self):
        starts = []

        def build(view):
            starts.append(view)
            return [sys.executable, "-c", CRASHING_CAMERA]

        cam = diag.Camera(build, retry_s=5)
        self.addCleanup(cam.stop)
        cam.tick(NOW, wanted=True, paused=False)
        self.assertTrue(wait_until(lambda: not cam.running() and "no cameras" in (cam.error() or "")))
        cam.tick(NOW + 1, wanted=True, paused=False)
        self.assertEqual(len(starts), 1)
        self.assertEqual(cam.state(), "camera error")
        cam.tick(NOW + 6, wanted=True, paused=False)
        self.assertEqual(len(starts), 2)

    def test_a_process_ignoring_terminate_is_killed(self):
        class Stuck:
            killed = False

            def poll(self):
                return 0 if self.killed else None

            def terminate(self):
                pass

            def kill(self):
                self.killed = True

            def wait(self, timeout=None):
                if not self.killed:
                    raise subprocess.TimeoutExpired("x", timeout)

        stuck = Stuck()
        cam = self.camera(kill_after_s=0.01)
        cam._proc = stuck
        cam.stop()
        self.assertTrue(stuck.killed)


class CaptureSlotEndToEnd(unittest.TestCase):
    def test_camera_is_free_for_every_capture(self):
        cam = diag.Camera(lambda view: [sys.executable, "-c", FAKE_CAMERA])
        self.addCleanup(cam.stop)
        policy = diag.HandoverPolicy(margin_s=20, settle_s=5)
        for t in range(SLOT - 30, SLOT + 40, 2):
            capture_active = SLOT <= t < SLOT + 12
            next_capture = SLOT if t < SLOT else NEXT
            cam.tick(t, wanted=True, paused=policy.should_pause(t, next_capture, capture_active))
            if capture_active:
                self.assertFalse(cam.running(), "camera busy during capture at +%ds" % (t - SLOT))
        self.assertTrue(cam.running(), "stream did not come back")


def diag_config():
    d = tempfile.mkdtemp()
    return diag.Config(out_root=os.path.join(d, "outbox"), capture_log=os.path.join(d, "c.log"),
                       sync_log=os.path.join(d, "s.log"), nas_target="", sun_script="x", mountinfo="/nonexistent")


class Service(unittest.TestCase):
    def service(self, deadline=NOW + 1800):
        cam = diag.Camera(lambda view: [sys.executable, "-c", FAKE_CAMERA])
        self.addCleanup(cam.stop)
        return diag.Service(diag_config(), cam, deadline=deadline, run=lambda cmd: None)

    def test_stops_at_the_deadline(self):
        svc = self.service(deadline=NOW + 10)
        self.assertTrue(svc.step(NOW))
        self.assertFalse(svc.step(NOW + 10))

    def test_camera_only_runs_with_a_viewer(self):
        svc = self.service()
        svc.step(NOW + 60)
        self.assertFalse(svc.camera.running())
        svc.viewer_joined()
        svc.step(NOW + 61)
        self.assertTrue(svc.camera.running())

    def test_status_shows_camera_state_and_time_left(self):
        svc = self.service(deadline=NOW + 600)
        s = svc.status(NOW)
        self.assertEqual(s["diag"]["seconds_left"], 600)
        self.assertEqual(s["diag"]["camera"], "idle")

    def test_viewer_grace_period(self):
        svc = self.service()
        svc.viewer_joined()
        svc.step(NOW + 60)
        svc.viewer_left(NOW + 60)
        svc.step(NOW + 62)
        self.assertTrue(svc.camera.running(), "a page reload should not restart the camera")
        svc.step(NOW + 70)
        self.assertFalse(svc.camera.running())


class Http(unittest.TestCase):
    def setUp(self):
        self.cam = diag.Camera(lambda view: [sys.executable, "-c", FAKE_CAMERA])
        # The clock here is real: a far-off timer keeps the test from landing in a capture window.
        self.svc = diag.Service(diag_config(), self.cam, deadline=time.time() + 1800,
                                run=lambda cmd: FAR_TIMER)
        self.server = diag.make_server(self.svc, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.addCleanup(self.cam.stop)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path, method="GET"):
        req = urllib.request.Request(self.base + path, method=method)
        return urllib.request.urlopen(req, timeout=5)

    def status_of(self, path, method="GET"):
        try:
            return self.get(path, method).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_page_needs_no_key(self):
        self.assertEqual(self.status_of("/"), 200)
        self.assertEqual(self.status_of("/status.json"), 200)
        self.assertEqual(self.status_of("/camera.json"), 200)
        self.assertEqual(self.status_of("/view?mode=focus", "POST"), 204)

    def test_page_does_not_ask_for_a_key(self):
        self.assertNotIn("key", self.get("/").read().decode().replace("keep", ""))

    def test_page_loads(self):
        r = self.get("/")
        body = r.read().decode()
        self.assertIn("stream.mjpg", body)
        self.assertIn("no-store", r.headers["Cache-Control"])

    def test_status_json(self):
        data = json.load(self.get("/status.json"))
        self.assertIn("warnings", data)
        self.assertIn("diag", data)

    def test_camera_state_runs_no_commands(self):
        # The page checks this often, so it must cost the Pi nothing.
        calls = []
        self.svc.run = lambda cmd: calls.append(cmd)
        data = json.load(self.get("/camera.json"))
        self.assertEqual(data["camera"], "idle")
        self.assertEqual(calls, [])

    def test_view_is_a_post_and_validates_the_mode(self):
        self.assertEqual(self.status_of("/view?mode=focus", "POST"), 204)
        self.assertEqual(self.cam.view(), "focus")
        self.assertEqual(self.status_of("/view?mode=focus"), 405)
        self.assertEqual(self.status_of("/view?mode=nope", "POST"), 400)

    def test_unknown_path(self):
        self.assertEqual(self.status_of("/nope"), 404)

    def test_stream_sends_jpeg_frames(self):
        r = self.get("/stream.mjpg")
        self.assertIn("multipart/x-mixed-replace", r.headers["Content-Type"])
        self.assertTrue(wait_until(lambda: self.svc.viewers() == 1))
        self.svc.step(time.time())
        self.assertIn(b"\xff\xd8frame\xff\xd9", r.read(300))
        r.close()
        self.assertTrue(wait_until(lambda: self.svc.viewers() == 0, 10))


class UrlFile(unittest.TestCase):
    def test_written_private(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "url")
            diag.write_url_file(p, "http://x/")
            with open(p) as f:
                self.assertEqual(f.read().strip(), "http://x/")
            if os.name == "posix":
                self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)

    def test_no_directory_is_not_fatal(self):
        diag.write_url_file("/nonexistent/dir/url", "http://x/")


if __name__ == "__main__":
    unittest.main(verbosity=1)
