#!/usr/bin/env python3
"""Temporary diagnostics page for the Pi. Stdlib only. Started by the `diag` command."""
import calendar
import json
import os
import shutil
import subprocess
import sys
import time
from collections import namedtuple

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
            out["last_ok_age_s"] = now - t
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
            if name.endswith(".json") and mtime > newest_json_time:
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
        out.append("%d capture problems in the last 24 hours." % cap["problems_24h"])
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
    """Output of a command, or None if it is missing, fails or hangs."""
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=True)
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
