#!/usr/bin/env python3
"""Temporary diagnostics page for the Pi. Stdlib only. Started by the `diag` command."""
import calendar
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque, namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

Config = namedtuple("Config", "out_root capture_log sync_log nas_target sun_script mountinfo")

# Estimates, to tune from pilot data.
STALE_CAPTURE_S = 20 * 60      # one missed 15-minute slot, plus some slack
STUCK_FRAMES_S = 60 * 60       # the sync normally clears a frame within about 7 minutes
DISK_WARN_PCT = 85             # the capture script starts dropping DNGs here

THROTTLE_BITS = {0: "undervoltage", 1: "frequency capped", 2: "throttled", 3: "soft temperature limit"}
SINCE_BOOT_OFFSET = 16


def parse_throttled(text):
    """Decode `vcgencmd get_throttled` into what is wrong now and what has happened since boot."""
    try:
        value = int(text.strip().split("=", 1)[1], 16)
    except (AttributeError, IndexError, ValueError):
        return None
    return {"now": [n for b, n in THROTTLE_BITS.items() if value >> b & 1],
            "since_boot": [n for b, n in THROTTLE_BITS.items() if value >> (b + SINCE_BOOT_OFFSET) & 1]}


def tail_lines(path, count, max_bytes=65536):
    """Last lines of a file, reading only its end. A missing file gives an empty list."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - max_bytes))
            return f.read().decode("utf-8", "replace").splitlines()[-count:]
    except OSError:
        return []


def _log_time(line):
    try:
        return calendar.timegm(time.strptime(line.split(" ", 1)[0], "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None


def summarize_capture_log(lines, now):
    """Age and lux of the last good capture, and FAILED or SKIPPED lines from the last 24 hours."""
    out = {"last_ok_age_s": None, "last_lux": None, "problems_24h": 0}
    for line in lines:
        t = _log_time(line)
        if t is None:
            continue
        if line.endswith(" ok"):
            out["last_ok_age_s"] = int(now - t)
            lux = [w for w in line.split() if w.startswith("lux=")]
            out["last_lux"] = lux[0][4:] if lux else None
        elif (" FAILED " in line or " SKIPPED" in line) and now - t < 86400:
            out["problems_24h"] += 1
    return out


def summarize_outbox(out_root, now):
    """Files waiting to sync, their oldest age, and the settings of the newest frame."""
    files = 0
    oldest = None
    newest_json = None
    newest_json_time = -1.0
    for root, dirs, names in os.walk(out_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            path = os.path.join(root, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue              # the sync removed it while we were looking
            files += 1
            oldest = mtime if oldest is None else min(oldest, mtime)
            if name.endswith(".json") and name != "system.json" and mtime > newest_json_time:
                newest_json, newest_json_time = path, mtime
    return {"files": files, "oldest_age_s": None if oldest is None else int(now - oldest),
            "newest_frame": _frame_settings(newest_json)}


def _frame_settings(path):
    if path is None:
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return {k: data.get(k) for k in ("Lux", "ExposureTime", "AnalogueGain")}
    except (OSError, ValueError, AttributeError):
        return None


def nas_state(target, mountinfo):
    """Describe the NAS from the mount table alone, so that looking never wakes the automount."""
    if not target:
        return "not configured"
    if not target.startswith("/"):
        return "rsync over ssh"
    types = set()
    for line in mountinfo.splitlines():
        fields = line.split()
        if " - " not in line or len(fields) < 5:
            continue
        point = fields[4]
        if point != "/" and (target == point or target.startswith(point.rstrip("/") + "/")):
            types.add(line.split(" - ", 1)[1].split()[0])
    if types - {"autofs"}:
        return "mounted"
    return "automount idle" if types else "not mounted"


def find_warnings(status):
    """Plain-language problems to show at the top of the page."""
    out = []
    cap, box, sysinfo = status["capture"], status["outbox"], status["system"]
    if cap.get("timer_enabled") != "enabled":
        out.append("Capture timer is %s: the Pi is NOT capturing." % (cap.get("timer_enabled") or "unknown"))
    age = cap.get("last_ok_age_s")
    if age is not None and age > STALE_CAPTURE_S:
        out.append("The last good capture was %d minutes ago." % (age // 60))
    if cap.get("problems_24h"):
        count = cap["problems_24h"]
        out.append("%d capture problem%s in the last 24 hours." % (count, "" if count == 1 else "s"))
    if (box.get("oldest_age_s") or 0) > STUCK_FRAMES_S:
        out.append("Frames have been waiting to sync for %d minutes." % (box["oldest_age_s"] // 60))
    if status["nas"].get("state") in ("not mounted", "not configured"):
        out.append("NAS share: %s." % status["nas"]["state"])
    if sysinfo.get("ntp_synced") is False:
        out.append("The clock is not synchronized.")
    if (sysinfo.get("disk_used_pct") or 0) >= DISK_WARN_PCT:
        out.append("The disk is %d%% full." % sysinfo["disk_used_pct"])
    throttled = sysinfo.get("throttled") or {}
    if throttled.get("now"):
        out.append("Power or heat problem now: %s." % ", ".join(throttled["now"]))
    if throttled.get("since_boot"):
        out.append("Power or heat problem since boot: %s." % ", ".join(throttled["since_boot"]))
    return out


def run_command(cmd, timeout=5):
    """Output of a command, or None if it is missing or hangs. A non-zero exit still counts:
    `systemctl is-enabled` reports a disabled timer that way."""
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        return r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None


def _disk_used_pct(path):
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return round(100 * usage.used / (usage.used + usage.free)) if usage.used + usage.free else None


def _read_text(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def _mem_available_mb():
    for line in _read_text("/proc/meminfo").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return None


def _uptime_s():
    try:
        return int(float(_read_text("/proc/uptime").split()[0]))
    except (IndexError, ValueError):
        return None


def _wifi_signal():
    """Signal level in dBm from /proc/net/wireless, or None when not on Wi-Fi."""
    lines = _read_text("/proc/net/wireless").splitlines()
    try:
        return float(lines[2].split()[3].rstrip("."))
    except (IndexError, ValueError):
        return None


def _load():
    try:
        return round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        return None


def _stripped(text):
    return text.strip() if text else None


def _sun(cfg, run):
    """Next sunset. The script prints azimuth and time, never the site coordinates."""
    text = run([sys.executable or "python3", cfg.sun_script, "sunset", "--json"])
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def collect_status(cfg, run, now):
    """Everything the page shows. Read-only, and every part may fail without breaking the rest."""
    capture_lines = tail_lines(cfg.capture_log, 400)
    sync_lines = tail_lines(cfg.sync_log, 8)
    capture = summarize_capture_log(capture_lines, now)
    capture["timer_enabled"] = _stripped(run(["systemctl", "is-enabled", "sunset-capture.timer"]))
    capture["recent"] = capture_lines[-8:]
    temp = _stripped(run(["vcgencmd", "measure_temp"]))
    ntp = _stripped(run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]))
    status = {
        "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "capture": capture,
        "outbox": summarize_outbox(cfg.out_root, now),
        "sync": {"recent": sync_lines},
        "nas": {"state": nas_state(cfg.nas_target, _read_text(cfg.mountinfo))},
        "sun": _sun(cfg, run),
        "system": {
            "temp": temp.split("=", 1)[-1] if temp else None,
            "throttled": parse_throttled(run(["vcgencmd", "get_throttled"])),
            "ntp_synced": None if ntp is None else ntp == "yes",
            "disk_used_pct": _disk_used_pct(cfg.out_root),
            "mem_available_mb": _mem_available_mb(),
            "uptime_s": _uptime_s(),
            "load_1m": _load(),
            "wifi_dbm": _wifi_signal(),
            "ips": (run(["hostname", "-I"]) or "").split(),
        },
    }
    status["warnings"] = find_warnings(status)
    return status


class FrameSplitter:
    """Cuts a stream of concatenated JPEGs into frames, without decoding them."""
    SOI = b"\xff\xd8"
    EOI = b"\xff\xd9"

    def __init__(self, max_bytes=8 * 1024 * 1024):
        self._buf = bytearray()
        self._max = max_bytes

    def buffered(self):
        return len(self._buf)

    def feed(self, chunk):
        self._buf += chunk
        frames = []
        while True:
            start = self._buf.find(self.SOI)
            if start < 0:
                # Keep a last byte that may be half of a start marker.
                del self._buf[:-1]
                break
            end = self._buf.find(self.EOI, start + 2)
            if end < 0:
                del self._buf[:start]
                if len(self._buf) > self._max:
                    self._buf.clear()
                break
            frames.append(bytes(self._buf[start:end + 2]))
            del self._buf[:end + 2]
        return frames


def stream_command(view, width, height):
    """rpicam-vid writing MJPEG to stdout. No preview, and it runs until stopped."""
    cmd = ["rpicam-vid", "-t", "0", "-n", "--codec", "mjpeg", "--quality", "60", "--framerate", "5", "-o", "-"]
    if view == "focus":
        # 20% of the sensor at its full resolution, so one screen pixel is one sensor pixel.
        return cmd + ["--mode", "4056:3040", "--roi", "0.4,0.4,0.2,0.2", "--width", "810", "--height", "608"]
    # A mode must be named: on its own the camera picks 1332x990, which crops to the centre 65%.
    return cmd + ["--mode", "2028:1520", "--width", str(width), "--height", str(height)]


def parse_next_capture(text, now):
    """Next capture from `systemctl list-timers --output=json`. If the timer has none, assume the
    15-minute schedule, so the camera is still released for a capture started some other way."""
    try:
        value = json.loads(text)[0]["next"] / 1000000
        if value > now:
            return value
    except (TypeError, ValueError, LookupError):
        pass
    return (int(now) // 900 + 1) * 900


class HandoverPolicy:
    """Decides when the stream must leave the camera free. A capture does not retry, so a busy
    camera would be a lost frame."""

    def __init__(self, margin_s=20, settle_s=5):
        self._margin = margin_s
        self._settle = settle_s
        self._hold_until = None

    def should_pause(self, now, next_capture, capture_active):
        if next_capture - now <= self._margin:
            # The timer moves on to the next slot the moment it fires, slightly before the
            # service shows as active, so hold on past the slot itself.
            self._hold_until = next_capture + self._settle
        if capture_active:
            return True
        return self._hold_until is not None and now < self._hold_until


class Camera:
    """Owns the rpicam-vid process and keeps only the newest frame, in memory."""

    def __init__(self, build_command, retry_s=5, kill_after_s=10):
        self._build = build_command
        self._retry_s = retry_s
        self._kill_after = kill_after_s
        self._proc = None
        self._view = "full"
        self._proc_view = None
        self._paused = False
        self._started_at = 0
        self._got_frame = False
        self._stderr = deque(maxlen=3)
        self._seq = 0
        self._frame = None
        self._ready = threading.Condition()

    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def view(self):
        return self._view

    def set_view(self, view):
        self._view = view

    def latest(self):
        with self._ready:
            return self._seq, self._frame

    def wait_frame(self, after_seq, timeout):
        with self._ready:
            self._ready.wait_for(lambda: self._seq != after_seq, timeout)
            return self._seq, self._frame

    def error(self):
        if self._proc is not None and self._proc.poll() is not None and self._stderr:
            return self._stderr[-1]
        return None

    def state(self):
        if self._paused:
            return "paused for capture"
        if self.running():
            return "streaming" if self._got_frame else "starting"
        return "camera error" if self._proc is not None else "idle"

    def tick(self, now, wanted, paused):
        self._paused = paused
        if paused or not wanted:
            self.stop()
            return
        if self.running():
            if self._proc_view == self._view:
                return
            self.stop()
        if self._proc is not None and now < self._started_at + self._retry_s:
            return                    # crashed; wait a little before trying again
        self._start(now)

    def _start(self, now):
        self._started_at = now
        self._got_frame = False
        self._stderr.clear()
        self._proc_view = self._view
        try:
            proc = subprocess.Popen(self._build(self._view), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            self._proc = _NeverStarted()
            self._stderr.append("cannot start camera: %s" % e)
            return
        self._proc = proc
        threading.Thread(target=self._read_frames, args=(proc,), daemon=True).start()
        threading.Thread(target=self._read_errors, args=(proc,), daemon=True).start()

    def _read_frames(self, proc):
        splitter = FrameSplitter()
        with proc.stdout:
            while True:
                chunk = proc.stdout.read1(65536)
                if not chunk:
                    return
                for frame in splitter.feed(chunk):
                    self._got_frame = True
                    with self._ready:
                        self._seq += 1
                        self._frame = frame
                        self._ready.notify_all()

    def _read_errors(self, proc):
        with proc.stderr:
            for line in proc.stderr:
                self._stderr.append(line.decode("utf-8", "replace").strip())

    def stop(self):
        """Returns only once the camera is free."""
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=self._kill_after)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


class _NeverStarted:
    """Stands in for a process when rpicam-vid could not even be launched."""

    def poll(self):
        return 1


CAPTURE_BUSY = ("active", "activating", "deactivating", "reloading")
VIEWER_GRACE_S = 5             # so reloading the page does not restart the camera
SECONDS_BETWEEN_STEPS = 2      # well inside the 20-second margin


class Service:
    def __init__(self, cfg, camera, deadline, run=run_command, policy=None):
        self.cfg = cfg
        self.camera = camera
        self.deadline = deadline
        self.run = run
        self.policy = policy or HandoverPolicy()
        self._viewers = 0
        self._last_left = None
        self._lock = threading.Lock()

    def viewers(self):
        return self._viewers

    def viewer_joined(self):
        with self._lock:
            self._viewers += 1

    def viewer_left(self, now):
        with self._lock:
            self._viewers -= 1
            self._last_left = now

    def step(self, now):
        """One pass of the control loop. Returns False when it is time to shut down."""
        if now >= self.deadline:
            return False
        next_capture = parse_next_capture(self.run(["systemctl", "list-timers", "sunset-capture.timer", "--all",
                                                    "--no-legend", "--output=json"]), now)
        busy = (self.run(["systemctl", "is-active", "sunset-capture.service"]) or "").strip() in CAPTURE_BUSY
        recent = self._last_left is not None and now - self._last_left < VIEWER_GRACE_S
        self.camera.tick(now, wanted=self._viewers > 0 or recent, paused=self.policy.should_pause(now, next_capture, busy))
        return True

    def camera_status(self, now):
        """Cheap enough for the page to ask often: runs no commands."""
        return {"seconds_left": int(self.deadline - now), "camera": self.camera.state(),
                "camera_error": self.camera.error(), "view": self.camera.view(), "viewers": self._viewers}

    def status(self, now):
        status = collect_status(self.cfg, self.run, now)
        status["diag"] = self.camera_status(now)
        return status


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass                          # the journal does not need a line per request

    def _route(self):
        url = urlsplit(self.path)
        self.query = parse_qs(url.query)
        return url.path

    def _send(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self._route()
        if path == "/":
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/status.json":
            self._send(json.dumps(self.server.service.status(time.time())).encode("utf-8"), "application/json")
        elif path == "/camera.json":
            self._send(json.dumps(self.server.service.camera_status(time.time())).encode("utf-8"), "application/json")
        elif path == "/stream.mjpg":
            self._stream()
        elif path == "/view":
            self.send_error(405)
        else:
            self.send_error(404)

    def do_POST(self):
        path = self._route()
        if path != "/view":
            self.send_error(404)
        elif self.query.get("mode", [""])[0] not in ("full", "focus"):
            self.send_error(400)
        else:
            self.server.service.camera.set_view(self.query["mode"][0])
            self.send_response(204)
            self.end_headers()

    def _stream(self):
        svc = self.server.service
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        svc.viewer_joined()
        seq = svc.camera.latest()[0]
        try:
            while True:
                new_seq, frame = svc.camera.wait_frame(seq, 1.0)
                if new_seq == seq or frame is None:
                    continue          # paused or starting; the browser keeps the last frame
                seq = new_seq
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame))
                self.wfile.write(frame + b"\r\n")
                self.wfile.flush()
        except OSError:
            pass                      # the viewer went away
        finally:
            svc.viewer_left(time.time())


def make_server(service, host, port):
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.service = service
    return server


def write_url_file(path, url):
    """Leaves the link where the `diag` command can read it. /run is in RAM, so no SD write."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(url + "\n")
    except OSError as e:
        print("cannot write %s: %s" % (path, e), file=sys.stderr)


def config_from_env():
    out_root = os.environ.get("OUT_ROOT") or os.path.expanduser("~/sunset/outbox")
    base = os.path.dirname(out_root)
    return Config(out_root=out_root,
                  capture_log=os.environ.get("LOG_FILE") or os.path.join(base, "capture.log"),
                  sync_log=os.environ.get("SYNC_LOG_FILE") or os.path.join(base, "sync.log"),
                  nas_target=os.environ.get("NAS_TARGET", ""),
                  sun_script=os.path.join(os.path.dirname(os.path.abspath(__file__)), "sunset-sun.py"),
                  mountinfo="/proc/self/mountinfo")


def main():
    port = int(os.environ.get("DIAG_PORT", "8080"))
    max_s = int(os.environ.get("DIAG_MAX_S", "1800"))
    width = int(os.environ.get("DIAG_WIDTH", "1280"))
    height = int(os.environ.get("DIAG_HEIGHT", "960"))
    url_file = os.environ.get("DIAG_URL_FILE", "/run/sunset-diag/url")

    camera = Camera(lambda view: stream_command(view, width, height))
    service = Service(config_from_env(), camera, time.time() + max_s)
    server = make_server(service, "0.0.0.0", port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))

    ips = (run_command(["hostname", "-I"]) or "").split()
    write_url_file(url_file, "http://%s:%d/" % (ips[0] if ips else socket.gethostname(), server.server_address[1]))
    try:
        while service.step(time.time()):
            time.sleep(SECONDS_BETWEEN_STEPS)
    finally:
        camera.stop()


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Sunset diagnostics</title>
<style>
:root { color-scheme: light dark; --bg: #f6f6f4; --panel: #fff; --text: #1d1d1b; --muted: #6a6a64; --line: #dcdcd6; --warn-bg: #fdecc8; --warn-text: #6b4300; --accent: #b4490f; }
@media (prefers-color-scheme: dark) { :root { --bg: #161615; --panel: #212120; --text: #ecece8; --muted: #a0a09a; --line: #383836; --warn-bg: #4a3510; --warn-text: #ffdf9e; --accent: #f08a4b; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.45 system-ui, sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 16px; }
header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 4px 16px; margin-bottom: 12px; }
h1 { font-size: 20px; margin: 0; }
h2 { font-size: 14px; margin: 0 0 8px; }
#left, .muted { color: var(--muted); }
#warnings { list-style: none; margin: 0 0 12px; padding: 0; }
#warnings li { background: var(--warn-bg); color: var(--warn-text); padding: 8px 12px; border-radius: 6px; margin-bottom: 6px; }
.view { position: relative; background: #000; border-radius: 8px; overflow: hidden; line-height: 0; min-height: 200px; }
.view img { width: 100%; height: auto; display: block; }
#state { position: absolute; top: 8px; left: 8px; background: rgba(0,0,0,.7); color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 13px; line-height: 1.5; }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin: 10px 0 16px; }
button { font: inherit; padding: 6px 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); color: var(--text); cursor: pointer; }
button[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); font-weight: 600; }
.score { font-variant-numeric: tabular-nums; }
.score b { font-size: 18px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 12px; }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-width: 0; }
dl { display: grid; grid-template-columns: auto 1fr; gap: 2px 12px; margin: 0; }
dt { color: var(--muted); }
dd { margin: 0; text-align: right; overflow-wrap: anywhere; }
pre { margin: 8px 0 0; font-size: 12px; line-height: 1.4; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--muted); }
</style>
</head>
<body>
<main>
<header><h1>Sunset diagnostics</h1><span id="left"></span></header>
<ul id="warnings"></ul>
<div class="view"><img id="cam" alt="Live camera view"><span id="state">connecting</span></div>
<div class="controls">
  <button id="full" type="button">Full frame</button>
  <button id="focus" type="button">Focus (centre, real pixels)</button>
  <span class="score">Sharpness <b id="now">-</b> &middot; best <b id="best">-</b></span>
  <button id="reset" type="button">Reset best</button>
  <span class="muted">Compare only within the same scene and light.</span>
</div>
<div class="grid">
  <section><h2>Capture</h2><dl id="capture"></dl><pre id="captureLog"></pre></section>
  <section><h2>Sync and NAS</h2><dl id="sync"></dl><pre id="syncLog"></pre></section>
  <section><h2>System</h2><dl id="system"></dl></section>
</div>
</main>
<script>
var cam = document.getElementById("cam");
cam.src = "stream.mjpg";

function $(id) { return document.getElementById(id); }

function ago(s) {
  if (s === null || s === undefined) return "none yet";
  if (s < 90) return s + " s ago";
  if (s < 5400) return Math.round(s / 60) + " min ago";
  return (s / 3600).toFixed(1) + " h ago";
}

function fill(id, rows) {
  var dl = $(id);
  dl.textContent = "";
  rows.forEach(function (r) {
    var dt = document.createElement("dt"), dd = document.createElement("dd");
    dt.textContent = r[0];
    dd.textContent = (r[1] === null || r[1] === undefined || r[1] === "") ? "unknown" : r[1];
    dl.appendChild(dt);
    dl.appendChild(dd);
  });
}

function showCamera(d) {
  var mins = Math.max(0, Math.ceil(d.seconds_left / 60));
  $("left").textContent = "Stops by itself in " + mins + " min";
  $("state").textContent = d.camera_error ? d.camera + ": " + d.camera_error : d.camera;
  $("full").setAttribute("aria-pressed", d.view === "full");
  $("focus").setAttribute("aria-pressed", d.view === "focus");
}

function show(s) {
  var c = s.capture, b = s.outbox, y = s.system, f = b.newest_frame || {};
  showCamera(s.diag);

  var w = $("warnings");
  w.textContent = "";
  s.warnings.forEach(function (t) {
    var li = document.createElement("li");
    li.textContent = t;
    w.appendChild(li);
  });

  fill("capture", [
    ["Timer", c.timer_enabled],
    ["Last good capture", ago(c.last_ok_age_s)],
    ["Problems, last 24 h", c.problems_24h],
    ["Last lux", c.last_lux],
    ["Newest frame", f.ExposureTime ? f.ExposureTime + " us, gain " + f.AnalogueGain : "none waiting"],
    ["Next sunset (UTC)", s.sun ? s.sun.sunset_utc : null]
  ]);
  $("captureLog").textContent = c.recent.join("\n");

  fill("sync", [
    ["NAS", s.nas.state],
    ["Files waiting", b.files],
    ["Oldest waiting", b.oldest_age_s === null ? "none" : ago(b.oldest_age_s)]
  ]);
  $("syncLog").textContent = s.sync.recent.join("\n");

  var t = y.throttled;
  fill("system", [
    ["Time (UTC)", s.time_utc],
    ["Clock synced", y.ntp_synced === null ? null : (y.ntp_synced ? "yes" : "NO")],
    ["Temperature", y.temp],
    ["Power and heat", !t ? null : (t.now.length ? t.now.join(", ") : (t.since_boot.length ? "earlier: " + t.since_boot.join(", ") : "ok"))],
    ["Disk used", y.disk_used_pct === null ? null : y.disk_used_pct + "%"],
    ["Memory free", y.mem_available_mb === null ? null : y.mem_available_mb + " MB"],
    ["Load", y.load_1m],
    ["Uptime", y.uptime_s === null ? null : (y.uptime_s / 3600).toFixed(1) + " h"],
    ["Wi-Fi signal", y.wifi_dbm === null ? "not on Wi-Fi" : y.wifi_dbm + " dBm"],
    ["IP", y.ips.join(", ")]
  ]);
}

function poll(path, then) {
  fetch(path).then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); }).then(then)
    .catch(function () { $("state").textContent = "diagnostics stopped or unreachable"; });
}
function pollCamera() { poll("camera.json", showCamera); }
function pollStatus() { poll("status.json", show); }
pollStatus();
setInterval(pollCamera, 2000);
setInterval(pollStatus, 15000);

function setView(mode) {
  best = 0;
  fetch("view?mode=" + mode, { method: "POST" }).then(pollCamera);
}
$("full").onclick = function () { setView("full"); };
$("focus").onclick = function () { setView("focus"); };
$("reset").onclick = function () { best = 0; };

// Same formula as sunset-focus.py, worked out here so the Pi does no extra work.
var best = 0, canvas = document.createElement("canvas"), ctx = canvas.getContext("2d", { willReadFrequently: true });
function sharpness() {
  if (!cam.naturalWidth) return null;
  var w = 320, h = 240;
  canvas.width = w;
  canvas.height = h;
  var sw = Math.min(cam.naturalWidth, w), sh = Math.min(cam.naturalHeight, h);
  ctx.drawImage(cam, (cam.naturalWidth - sw) / 2, (cam.naturalHeight - sh) / 2, sw, sh, 0, 0, sw, sh);
  var d = ctx.getImageData(0, 0, sw, sh).data, total = 0, sum = 0;
  for (var y = 0; y < sh; y++) {
    for (var x = 0; x < sw; x++) {
      var g = d[(y * sw + x) * 4 + 1];
      sum += g;
      if (x < sw - 1 && y < sh - 1) {
        var r = g - d[(y * sw + x + 1) * 4 + 1], b = g - d[((y + 1) * sw + x) * 4 + 1];
        total += r * r + b * b;
      }
    }
  }
  var mean = sum / (sw * sh);
  return mean < 1 ? 0 : 100000 * total / (2 * (sw - 1) * (sh - 1) * mean * mean);
}
setInterval(function () {
  var s = sharpness();
  if (s === null) return;
  best = Math.max(best, s);
  $("now").textContent = Math.round(s);
  $("best").textContent = Math.round(best);
}, 700);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
