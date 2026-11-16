#!/usr/bin/env python3
"""Add "Capture" and "System" blocks to a frame's JSON, and keep the day's system.json.
Stdlib only, no network.

    sunset-meta.py annotate FRAME.json --kind auto|night --camera wide --slot T \
        --started EPOCH --finished EPOCH --outbox DIR [--set key=value ...]

Capture says how this frame was taken. System says what state the machine was in at that
moment, so that a gap, a dark frame or a dead card can be explained years later.

What rarely changes (model, OS, kernel, versions, SD card, setup note) goes in one system.json
in the day's folder, not on every frame. Capture.system_id names the record there that applied.
The sync removes that file from the outbox once it is on the NAS, so the day's records are also
kept in a state file beside the outbox, and the file is written again only when something changes.

Rules:
- Every probe may fail on its own: its value becomes null and its name goes in
  System.unavailable. The caller also treats any failure here as non-fatal.
- One overall deadline (--deadline, default META_DEADLINE_S or 15 s), well inside the capture's
  `timeout 30`. Probes not started by then are skipped, named in System.unavailable, and
  System.cut_short is true. Capture is written to the file before System is probed, so a kill
  can't take the checksums with it.
- A missing or unreadable rpicam metadata file is started from {} and flagged with
  "rpicam_metadata": "missing" or "invalid"; the frame still gets Capture and System.
- The slow daily probes (`rpicam-still --version`, `vcgencmd version`) are cached beside the
  outbox in .meta-cache.json, once per UTC day and boot.
- Never touch the NAS path. A dead share can hang a stat() for minutes, and that would
  stall the capture. Its state comes only from /proc/mounts and the sync log.
- Nothing that locates or identifies the site or the owner: no coordinates, IP or MAC
  addresses, Wi-Fi name, NTP server, file paths, or board and SD card serial numbers.
  Weather, moon and anything else computable later from the time is left out too.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

SCHEMA_VERSION = 2
UTC = timezone.utc
RUN_TIMEOUT_S = 5
DEADLINE_S = 15            # whole script; the capture kills it at 30
CACHE_NAME = ".meta-cache.json"
CACHED_COMMANDS = (("rpicam-still", "--version"), ("vcgencmd", "version"))
SENSOR_OVERLAY = re.compile(r"^(imx|ov|arducam)", re.I)


def iso(epoch):
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_command(cmd, timeout=RUN_TIMEOUT_S):
    """Stdout of a short command, or None. Bounded, because a capture is waiting on it."""
    if timeout is not None and timeout <= 0:
        return None
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              timeout=timeout, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


class Deadline:
    """The time this script has left. Probes check it before they start; commands get no longer
    than what is left."""

    def __init__(self, seconds, clock=time.monotonic):
        self._clock = clock
        self._end = clock() + float(seconds)

    def remaining(self):
        return self._end - self._clock()

    def expired(self):
        return self.remaining() <= 0

    def timeout(self, most):
        return max(0, min(most, self.remaining()))


def read(root, rel):
    with open(os.path.join(root, rel), errors="replace") as f:
        return f.read()


def after_equals(text):
    return text.strip().split("=", 1)[1]


def meminfo_mb(root):
    values = {}
    for line in read(root, "proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        values[key] = int(rest.split()[0]) // 1024
    return {"total": values["MemTotal"], "available": values["MemAvailable"]}


def os_name(root):
    return re.search(r'^PRETTY_NAME="?([^"\n]*)', read(root, "etc/os-release"), re.M).group(1)


def camera_overlays(root):
    found = re.findall(r"^\s*dtoverlay=([^,\s]+)", read(root, "boot/firmware/config.txt"), re.M)
    return [name for name in found if SENSOR_OVERLAY.match(name)]


def disk(path):
    usage = shutil.disk_usage(path)
    out = {"free_bytes": usage.free,
           # Same sum as df's Use%: what a normal user can still write, not counting root's reserve.
           "used_pct": round(100.0 * usage.used / max(usage.used + usage.free, 1), 1)}
    if hasattr(os, "statvfs"):
        out["inodes_free"] = os.statvfs(path).f_favail
    return out


def outbox_pending(outbox):
    """Finished frames still waiting for the sync. Dot-directories hold unfinished ones."""
    if not os.path.isdir(outbox):
        raise FileNotFoundError(outbox)
    files = size = 0
    for folder, dirs, names in os.walk(outbox):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            files += 1
            size += os.path.getsize(os.path.join(folder, name))
    return {"files": files, "bytes": size}


def sd_sectors(root):
    fields = read(root, "sys/block/mmcblk0/stat").split()
    return {"read": int(fields[2]), "written": int(fields[6])}


def sd_card(root):
    out = {}
    # life_time and pre_eol_info: eMMC wear (the CM4), absent on an SD card. Never serial or cid.
    for name in ("name", "manfid", "oemid", "date", "hwrev", "fwrev", "life_time", "pre_eol_info"):
        try:
            out[name] = read(root, "sys/block/mmcblk0/device/" + name).strip()
        except OSError:
            pass
    if not out:
        raise FileNotFoundError("sd card")
    return out


def network(root):
    wireless = {}
    try:
        for line in read(root, "proc/net/wireless").splitlines()[2:]:
            name, _, rest = line.partition(":")
            parts = rest.split()
            wireless[name.strip()] = {"link_quality": int(float(parts[1])), "signal_dbm": int(float(parts[2]))}
    except OSError:
        pass
    out = {}
    base = os.path.join(root, "sys/class/net")
    for name in sorted(os.listdir(base)):
        if name != "lo":
            state = read(root, "sys/class/net/%s/operstate" % name).strip()
            out[name] = dict({"state": state}, **wireless.get(name, {}))
    return out


def ntp_offset_ms(text):
    match = re.search(r"Offset:\s*([+-]?[0-9.]+)(us|ms|s)\b", text)
    return round(float(match.group(1)) * {"us": 0.001, "ms": 1.0, "s": 1000.0}[match.group(2)], 3)


def clock(run):
    props = dict(line.split("=", 1) for line in run(["timedatectl", "show", "-p", "NTPSynchronized"]).split())
    out = {"ntp_synced": props.get("NTPSynchronized") == "yes"}
    try:
        out["ntp_offset_ms"] = ntp_offset_ms(run(["timedatectl", "timesync-status"]))
    except (AttributeError, TypeError):
        out["ntp_offset_ms"] = None
    return out


def timezone_name(root):
    """The system zone, without the 0.7 s that timedatectl takes on the throttled Pi."""
    target = os.path.realpath(os.path.join(root, "etc/localtime"))
    if "zoneinfo/" in target.replace(os.sep, "/"):
        return target.replace(os.sep, "/").split("zoneinfo/", 1)[1]
    return read(root, "etc/timezone").strip()


def nas_mounted(root, target):
    """From the mount table only; see the rule at the top of this file."""
    if not target.startswith("/"):
        return None
    target = target.rstrip("/") + "/"
    for line in read(root, "proc/mounts").splitlines():
        _, point, fstype = line.split()[:3]
        if point != "/" and fstype != "autofs" and target.startswith(point.rstrip("/") + "/"):
            return True
    return False


def sync_state(path):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(f.tell() - 16384, 0))
        lines = f.read().decode(errors="replace").splitlines()
    out = {"last_sync_utc": None, "last_sync_status": None, "last_sync_ok_utc": None}
    for line in lines:
        words = line.split()
        if len(words) >= 3 and words[1] == "sync":  # later words can hold paths and errors
            out["last_sync_utc"], out["last_sync_status"] = words[0], words[2]
            if words[2] == "ok":
                out["last_sync_ok_utc"] = words[0]
    return out


def versions(run):
    text = run(["rpicam-still", "--version"])
    found = dict(re.findall(r"^(rpicam-apps|libcamera) build:\s*(\S+)", text, re.M))
    return found.get("rpicam-apps"), found.get("libcamera")


def prober(missing, deadline=None, skipped=None):
    def probe(name, fn):
        if deadline is not None and deadline.expired():
            missing.append(name)
            if skipped is not None:
                skipped.append(name)
            return None
        try:
            return fn()
        except Exception:  # one bad source must not lose the others, or the frame
            missing.append(name)
            return None
    return probe


def system_block(root, outbox, nas_target, sync_log, run=run_command, deadline=None):
    """The machine at the moment of this frame. Slow-changing details are in daily_fields."""
    missing, skipped = [], []
    probe = prober(missing, deadline, skipped)

    def vc(*args):
        return run(["vcgencmd"] + list(args))

    nas = {"mounted": probe("nas_mounted", lambda: nas_mounted(root, nas_target))}
    nas.update(probe("sync_log", lambda: sync_state(sync_log)) or {})
    block = {
        "uptime_s": probe("uptime_s", lambda: int(float(read(root, "proc/uptime").split()[0]))),
        "load": probe("load", lambda: [float(v) for v in read(root, "proc/loadavg").split()[:3]]),
        "memory_available_mb": probe("memory_available_mb", lambda: meminfo_mb(root)["available"]),
        "cpu_temp_c": probe("cpu_temp_c", lambda: round(
            int(read(root, "sys/class/thermal/thermal_zone0/temp")) / 1000.0, 1)),
        "core_volts": probe("core_volts", lambda: float(after_equals(vc("measure_volts", "core")).rstrip("V"))),
        "arm_clock_hz": probe("arm_clock_hz", lambda: int(after_equals(vc("measure_clock", "arm")))),
        "throttled": probe("throttled", lambda: after_equals(vc("get_throttled"))),
        "disk": probe("disk", lambda: disk(outbox)),
        "outbox_pending": probe("outbox_pending", lambda: outbox_pending(outbox)),
        "sd_sectors": probe("sd_sectors", lambda: sd_sectors(root)),
        "network": probe("network", lambda: network(root)),
        "clock": probe("clock", lambda: clock(run)),
        "nas": nas,
        "unavailable": missing,
    }
    if skipped:
        block["cut_short"] = True   # the deadline passed; the probes in `unavailable` didn't run
    return block


def daily_fields(root, outbox, run, setup_id, setup_note, script, deadline=None):
    """What rarely changes, for system.json. Returns the fields and the probes that failed."""
    missing = []
    probe = prober(missing, deadline)
    rpicam, libcamera = probe("rpicam_apps", lambda: versions(run)) or (None, None)
    fields = {
        "hostname": probe("hostname", socket.gethostname),
        "model": probe("model", lambda: read(root, "proc/device-tree/model").strip("\0\n ")),
        "board_revision": probe("board_revision", lambda: re.search(
            r"^Revision\s*:\s*(\S+)", read(root, "proc/cpuinfo"), re.M).group(1)),
        "os": probe("os", lambda: os_name(root)),
        "kernel": probe("kernel", lambda: read(root, "proc/version").split()[2]),
        "firmware": probe("firmware", lambda: re.search(
            r"^version\s+(\S+)", run(["vcgencmd", "version"]), re.M).group(1)),
        "python": sys.version.split()[0],
        "rpicam_apps": rpicam,
        "libcamera": libcamera,
        "camera_overlays": probe("camera_overlays", lambda: camera_overlays(root)),
        "timezone": probe("timezone", lambda: timezone_name(root)),
        "memory_total_mb": probe("memory_total_mb", lambda: meminfo_mb(root)["total"]),
        "disk_total_bytes": probe("disk_total_bytes", lambda: shutil.disk_usage(outbox).total),
        "sd_card": probe("sd_card", lambda: sd_card(root)),
    }
    if setup_id:
        fields["setup_id"] = setup_id
    if setup_note:
        fields["setup_note"] = setup_note
    if script:
        fields["capture_script_sha256"] = probe("capture_script_sha256", lambda: sha256_file(script))
    return fields, missing


def boot_id(root):
    try:
        return read(root, "proc/sys/kernel/random/boot_id").strip()
    except OSError:
        return None


def cached_run(run, cache_path, key):
    """`run`, except that the slow daily commands are answered from the cache file when it was
    written for the same key (UTC day and boot). Only successful answers are kept."""
    try:
        with open(cache_path) as f:
            cache = json.load(f)
        if not isinstance(cache, dict) or cache.get("key") != key or not isinstance(cache.get("answers"), dict):
            raise ValueError("stale")
    except (OSError, ValueError):
        cache = {"key": key, "answers": {}}

    def run_cached(cmd):
        if tuple(cmd) not in CACHED_COMMANDS:
            return run(cmd)
        name = " ".join(cmd)
        if isinstance(cache["answers"].get(name), str):
            return cache["answers"][name]
        out = run(cmd)
        if out:
            cache["answers"][name] = out
            try:
                write_json(cache_path, cache, os.path.dirname(cache_path) or ".")
            except OSError:
                pass        # no cache costs a probe next frame, nothing more
        return out
    return run_cached


def write_json(path, data, tmp_folder):
    """Atomic. The temp file stays out of the day folder, where the sync could ship it."""
    os.makedirs(tmp_folder, exist_ok=True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = os.path.join(tmp_folder, ".%s.%d.tmp" % (os.path.basename(path), os.getpid()))
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
        f.write("\n")
        # On disk before the rename: a freeze on the CM4 (Nov 16) left system.json 0 bytes. These
        # files change a few times a day, so the extra writes are negligible.
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_state(path):
    try:
        with open(path) as f:
            state = json.load(f)
        if isinstance(state["records"], list) and all(isinstance(r, dict) for r in state["records"]):
            return state
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"records": []}


def update_daily(outbox, camera, slot, fields, missing):
    """Make sure today's system.json holds these fields, and return their system_id."""
    outbox = outbox.rstrip("/\\")
    state_path = os.path.join(os.path.dirname(outbox), ".system-state-%s.json" % camera)
    state = load_state(state_path)
    last = state["records"][-1] if state["records"] else {}
    # A probe failing once is not a change to the system.
    merged = {k: (last.get(k) if v is None else v) for k, v in fields.items()}
    system_id = hashlib.sha256(json.dumps(merged, sort_keys=True).encode()).hexdigest()[:12]
    day = "%s-%s-%s" % (slot[:4], slot[4:6], slot[6:8])
    if state.get("day_utc") != day:
        state = {"schema_version": SCHEMA_VERSION, "camera": camera, "day_utc": day, "records": []}
    day_path = os.path.join(outbox, camera, slot[:4], slot[4:6], slot[6:8], "system.json")
    partial = os.path.join(outbox, ".partial")
    if state["records"] and state["records"][-1].get("system_id") == system_id:
        # Absent means the sync has copied it. Present but empty or unreadable means a freeze cut
        # the write short (the sync holds an empty one back): write it again from the state.
        if os.path.exists(day_path) and load_state(day_path) != state:
            write_json(day_path, state, partial)
        return system_id
    record = {"system_id": system_id, "from_utc": slot_iso(slot)}
    record.update(merged)
    record["unavailable"] = [name for name in missing if merged.get(name) is None]
    state["records"].append(record)
    # This order, so a failure between the two is retried by the next frame.
    write_json(day_path, state, partial)
    write_json(state_path, state, partial)
    return system_id


def parse_value(text):
    for kind in (int, float):
        try:
            return kind(text)
        except (TypeError, ValueError):
            pass
    return text


def file_entry(path, checksums, deadline=None):
    entry = {"bytes": os.path.getsize(path)}
    if checksums:
        digest = sha256_file(path, deadline)
        if digest:
            entry["sha256"] = digest
    return entry


def sha256_file(path, deadline=None):
    """Hex digest, or None if the deadline passed first (a 25 MB DNG on a stalled SD card)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            if deadline is not None and deadline.expired():
                return None
            digest.update(chunk)
    return digest.hexdigest()


def slot_iso(slot):
    return datetime.strptime(slot, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%dT%H:%M:%SZ")


def capture_block(json_path, data, kind, camera, slot, started, finished, setup_id, system_id,
                  settings, decision_lux, checksums, schedule="regular", deadline=None, profile_id=None):
    base = json_path[:-len(".json")] if json_path.endswith(".json") else json_path
    # schedule: "regular" for the 5-minute slots, "dense" for the extra 1-a-minute frames.
    block = {"schema_version": SCHEMA_VERSION, "camera": camera, "kind": kind, "schedule": schedule}
    if setup_id:
        block["setup_id"] = setup_id
    if profile_id:
        block["profile_id"] = profile_id   # changes with any exposure or white-balance change (#10)
    block["system_id"] = system_id
    block["slot_utc"] = slot_iso(slot)
    block["shot_started_utc"] = iso(float(started))
    block["shot_seconds"] = round(float(finished) - float(started), 1)
    if data.get("FrameWallClock"):
        block["frame_wall_clock_utc"] = iso(data["FrameWallClock"] / 1e9)
    block["settings"] = {k: parse_value(v) for k, v in (s.split("=", 1) for s in settings or [])}
    if decision_lux not in (None, ""):
        block["decision_lux"] = parse_value(decision_lux)
    files = {}
    for ext in ("jpg", "dng"):
        if os.path.exists(base + "." + ext):
            files[ext] = file_entry(base + "." + ext, checksums, deadline)
    block["files"] = files
    if checksums and any("sha256" not in entry for entry in files.values()):
        block["unavailable"] = ["sha256"]     # the deadline passed before every file was hashed
    return block


def load_frame_json(path):
    """rpicam's metadata, and None or why it could not be used ("missing" or "invalid")."""
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}, "missing"
    except ValueError:
        return {}, "invalid"
    if not isinstance(data, dict):
        return {}, "invalid"
    return data, None


def annotate(args):
    deadline = Deadline(args.deadline)
    data, problem = load_frame_json(args.file)
    if problem:
        data.setdefault("rpicam_metadata", problem)
    outbox = args.outbox.rstrip("/\\")
    sync_log = args.sync_log or os.path.join(os.path.dirname(args.outbox.rstrip("/")), "sync.log")
    # Hidden name: the capture's "publish" moves every <frame>.* it can match.
    folder = os.path.dirname(args.file) or "."

    def run(cmd):
        return run_command(cmd, timeout=deadline.timeout(RUN_TIMEOUT_S))

    try:
        key = {"day_utc": args.slot[:8], "boot_id": boot_id(args.root)}
        daily_run = cached_run(run, os.path.join(os.path.dirname(outbox), CACHE_NAME), key)
        fields, missing = daily_fields(args.root, args.outbox, daily_run, args.setup_id,
                                       args.setup_note, args.script, deadline)
        system_id = update_daily(args.outbox, args.camera, args.slot, fields, missing)
    except Exception:  # the day's file must never cost the frame
        system_id = None
    data["Capture"] = capture_block(
        args.file, data, kind=args.kind, camera=args.camera, slot=args.slot, started=args.started,
        finished=args.finished, setup_id=args.setup_id, system_id=system_id, settings=args.set,
        decision_lux=args.decision_lux, checksums=not args.no_checksums, schedule=args.schedule,
        deadline=deadline, profile_id=args.profile_id)
    # Capture goes to disk first, so a kill while probing the system can't lose it.
    write_json(args.file, data, folder)
    data["System"] = system_block(args.root, args.outbox, args.nas_target or "", sync_log, run, deadline)
    if system_id is None:
        data["System"]["unavailable"].append("system_json")
    write_json(args.file, data, folder)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("annotate")
    a.add_argument("file")
    a.add_argument("--kind", required=True, choices=["auto", "night", "bracket"])
    a.add_argument("--camera", required=True)
    a.add_argument("--schedule", default="regular", choices=["regular", "dense"])
    a.add_argument("--slot", required=True, help="the frame's UTC filename time")
    a.add_argument("--started", required=True)
    a.add_argument("--finished", required=True)
    a.add_argument("--outbox", required=True)
    a.add_argument("--set", action="append", metavar="KEY=VALUE", help="a setting used for this shot")
    a.add_argument("--decision-lux", help="the auto shot's lux that triggered a night frame")
    a.add_argument("--setup-id")
    a.add_argument("--profile-id")
    a.add_argument("--setup-note")
    a.add_argument("--nas-target")
    a.add_argument("--sync-log")
    a.add_argument("--script", help="capture script, to record which version took the frame")
    a.add_argument("--no-checksums", action="store_true")
    a.add_argument("--root", default="/", help="for tests: where /proc and /sys are")
    a.add_argument("--deadline", type=float, default=None,
                   help="seconds for the whole script (default META_DEADLINE_S, else %d)" % DEADLINE_S)
    args = parser.parse_args(argv)
    if args.deadline is None:
        try:
            args.deadline = float(os.environ.get("META_DEADLINE_S") or DEADLINE_S)
        except ValueError:
            args.deadline = DEADLINE_S
    try:
        annotate(args)
    except (ValueError, OSError, KeyError) as exc:
        print("sunset-meta.py: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
