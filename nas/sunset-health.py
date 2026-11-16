#!/usr/bin/env python3
"""Daily health record per camera and UTC day (issue #22, part 1).

    sunset-health.py CAMERA_ROOT [--day YYYY-MM-DD|yesterday|today] [--days N] [--out DIR]

CAMERA_ROOT is one camera's folder on the NAS (YYYY/MM/DD/<cam>_<UTC>.{jpg,dng,json}). Python standard
library only, no AI, read-only on the frames. For each day it writes DIR/<day>.json, and for a finished
day also DIR/latest.json (a copy, only when it is not older than the one already there), both atomically.
Home Assistant reads latest.json (homeassistant/sunset_result.sh). DIR defaults to
../health/<camera>/ beside the camera folder. The default day is yesterday (UTC), run after the sync has
caught up, for example at 02:00 UTC. --days N does the N days ending at --day, to backfill.

What the record holds, all counted from the frame JSON and file names:
  frames.regular    5-minute frames (Capture.schedule "regular", or without a Capture block: a minute
                    that is a multiple of 5) against 288 (--expected-regular). For a day that is not
                    over yet, the slots so far.
  frames.dense      the extra 1-a-minute frames (Capture.schedule "dense"). Expected is derived from the
                    data, never fixed: each run of dense frames (a gap over 10 minutes starts a new one) is
                    a window, and every minute in it that is not a regular slot minute is expected. A
                    missing frame at a window's edge cannot be seen this way. If the day has no dense
                    frame but the day before did, dense is flagged as stopped; with neither, it is not
                    scheduled and expected stays null.
  frames.night      the `_night` frames, against the regular frames whose reported Lux was under the
                    night_lux setting recorded on the frame (Capture.settings.night_lux).
  frames.dng        DNG files present beside the regular and night frames (dense frames never have
                    one), expected once any of them shows a DNG was meant to be taken.
  largest_gap_min   longest time between two frames of any kind (the day's start and end count for a
                    finished day).
  missing_blocks    frames without a Sun, Capture or System block, unreadable JSON, frames flagged
                    rpicam_metadata "missing"/"invalid" (the camera's own JSON was lost), and frames whose
                    Capture.unavailable says the SHA-256 was not written (the archive can't verify those).
  setup_ids / setup_id_changes   Capture.setup_id over the day, and where it changed (a note, not an alarm).
  max_cpu_temp_c, throttled_seen (bits OR-ed over the day) with named flags, max_outbox_pending_files,
  max_disk_used_pct, min_jpg_bytes (from the files on disk, not the JSON).
  problems          short names of anything past a limit; `ok` is true when it is empty.

Left out on purpose: image-content measures (sharpness, contrast, the skyline's offset from a reference
patch, fog). They need decoded pictures and a registration against a reference, and belong to a later
registration step, not to this file-and-JSON job.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

SCHEMA_VERSION = 1
FRAME_JSON = re.compile(r"^(?P<stem>[A-Za-z0-9_-]+_(?P<ts>\d{8}T\d{6}Z)(?P<night>_night)?)\.json$")
THROTTLE_BITS = {0: "undervoltage", 1: "arm_freq_capped", 2: "throttled", 3: "soft_temp_limit",
                 16: "undervoltage_occurred", 17: "arm_freq_capped_occurred", 18: "throttled_occurred",
                 19: "soft_temp_limit_occurred"}
CURRENT_THROTTLE_MASK = 0xF
DENSE_WINDOW_GAP_MIN = 10
UTC = timezone.utc


def parse_ts(ts):
    return datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def throttle_value(text):
    try:
        return int(str(text), 16)
    except (TypeError, ValueError):
        return None


def write_atomic(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, ".%s.tmp" % os.path.basename(path))
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_frames(folder):
    """Every frame JSON in a day folder: dict(stem, time, night, data or None)."""
    frames = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        m = FRAME_JSON.match(name)
        if not m:
            continue
        try:
            with open(os.path.join(folder, name), "rb") as f:
                raw = f.read()
            data = json.loads(raw.decode("utf-8")) if raw.strip() else None
            if not isinstance(data, dict):
                data = None
        except (OSError, ValueError):
            data = None
        frames.append({"stem": m.group("stem"), "time": parse_ts(m.group("ts")),
                       "night": bool(m.group("night")), "data": data})
    frames.sort(key=lambda fr: (fr["time"], fr["night"]))
    return frames


def schedule_of(frame):
    cap = (frame["data"] or {}).get("Capture")
    if isinstance(cap, dict) and cap.get("schedule") in ("regular", "dense"):
        return cap["schedule"]
    return "regular" if frame["time"].minute % 5 == 0 else "dense"


def dense_windows(times):
    windows = []
    for t in sorted(times):
        if windows and (t - windows[-1][1]) <= timedelta(minutes=DENSE_WINDOW_GAP_MIN):
            windows[-1][1] = t
            windows[-1][2] += 1
        else:
            windows.append([t, t, 1])
    out = []
    for start, end, present in windows:
        minute = start.replace(second=0, microsecond=0)
        expected = 0
        while minute <= end:
            if minute.minute % 5 != 0:
                expected += 1
            minute += timedelta(minutes=1)
        out.append({"start_utc": iso(start), "end_utc": iso(end), "present": present, "expected": expected})
    return out


def largest_gap(times, day_start, day_end, complete):
    points = sorted(set(times))
    if not points:
        return None, None
    if complete:
        points = [day_start] + points + [day_end]
    best, at = timedelta(0), None
    for a, b in zip(points, points[1:]):
        if b - a > best:
            best, at = b - a, a
    return round(best.total_seconds() / 60.0, 1), iso(at)


def build_record(root, camera, day, now, out_dir, a):
    folder = os.path.join(root, day.strftime("%Y"), day.strftime("%m"), day.strftime("%d"))
    day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    complete = now >= day_end
    frames = read_frames(folder)
    regular = [f for f in frames if not f["night"] and schedule_of(f) == "regular"]
    dense = [f for f in frames if not f["night"] and schedule_of(f) == "dense"]
    night = [f for f in frames if f["night"]]

    if complete:
        expected_regular = a.expected_regular
    else:
        slots = int((now - day_start).total_seconds() // (24 * 3600 / a.expected_regular)) + 1
        expected_regular = min(a.expected_regular, slots)

    def setting(frame, key):
        cap = (frame["data"] or {}).get("Capture")
        return ((cap or {}).get("settings") or {}).get(key) if isinstance(cap, dict) else None

    # Night frames expected: regular slots whose reported Lux was under that frame's own night_lux.
    night_expected = 0
    for f in regular:
        lux, limit = number((f["data"] or {}).get("Lux")), number(setting(f, "night_lux"))
        if lux is not None and limit is not None and lux < limit:
            night_expected += 1

    def has_dng(f):
        return os.path.exists(os.path.join(folder, f["stem"] + ".dng"))

    non_dense = regular + night
    dng_present = sum(1 for f in non_dense if has_dng(f))
    raw_meant = dng_present > 0 or any(setting(f, "raw") == 1 for f in non_dense)
    dng_expected = len(non_dense) if raw_meant else 0

    windows = dense_windows([f["time"] for f in dense])
    dense_expected = sum(w["expected"] for w in windows) if windows else None
    dense_basis = "frames" if windows else None
    prev_dense = False
    prev_path = os.path.join(out_dir, (day - timedelta(days=1)).strftime("%Y-%m-%d") + ".json")
    try:
        with open(prev_path, encoding="utf-8") as f:
            prev_dense = (json.load(f).get("frames", {}).get("dense", {}).get("present") or 0) > 0
    except (OSError, ValueError, AttributeError):
        pass
    if not windows and prev_dense:
        dense_basis = "previous_day"

    gap, gap_at = largest_gap([f["time"] for f in frames], day_start, day_end, complete)

    def has_block(f, name):
        return isinstance(f["data"], dict) and isinstance(f["data"].get(name), dict)

    blocks = {"no_sun": 0, "no_capture": 0, "no_system": 0, "unreadable_json": 0,
              "bad_rpicam_metadata": 0, "no_sha256": 0}
    setup_ids, changes, last_id = [], [], None
    temps, outbox, disks, thrown = [], [], [], 0
    for f in frames:
        if f["data"] is None:
            blocks["unreadable_json"] += 1
            continue
        for key, name in (("no_sun", "Sun"), ("no_capture", "Capture"), ("no_system", "System")):
            if not has_block(f, name):
                blocks[key] += 1
        if isinstance(f["data"].get("rpicam_metadata"), str):    # "missing" or "invalid": camera's own JSON was lost
            blocks["bad_rpicam_metadata"] += 1
        if has_block(f, "Capture") and "sha256" in (f["data"]["Capture"].get("unavailable") or []):
            blocks["no_sha256"] += 1                             # the checksum deadline passed on the Pi
        sid = (f["data"].get("Capture") or {}).get("setup_id") if has_block(f, "Capture") else None
        if sid:
            if sid not in setup_ids:
                setup_ids.append(sid)
            if last_id is not None and sid != last_id:
                changes.append({"at_utc": iso(f["time"]), "from": last_id, "to": sid})
            last_id = sid
        system = f["data"].get("System") if has_block(f, "System") else {}
        if number(system.get("cpu_temp_c")) is not None:
            temps.append(system["cpu_temp_c"])
        value = throttle_value(system.get("throttled"))
        if value is not None:
            thrown |= value
        pending = system.get("outbox_pending")
        if isinstance(pending, dict) and number(pending.get("files")) is not None:
            outbox.append(pending["files"])
        disk = system.get("disk")
        if isinstance(disk, dict) and number(disk.get("used_pct")) is not None:
            disks.append(disk["used_pct"])

    sizes = []
    for f in frames:
        path = os.path.join(folder, f["stem"] + ".jpg")
        if os.path.exists(path):
            sizes.append(os.path.getsize(path))
    jpg_missing = sum(1 for f in frames if not os.path.exists(os.path.join(folder, f["stem"] + ".jpg")))

    record = {
        "schema_version": SCHEMA_VERSION, "camera": camera, "day_utc": day.strftime("%Y-%m-%d"),
        "generated_utc": iso(now), "complete": complete,
        "frames": {
            "regular": {"present": len(regular), "expected": expected_regular},
            "dense": {"present": len(dense), "expected": dense_expected, "scheduled_basis": dense_basis,
                      "windows": windows},
            "night": {"present": len(night), "expected": night_expected},
            "dng": {"present": dng_present, "expected": dng_expected},
            "jpg_missing": jpg_missing,
        },
        "largest_gap_min": gap, "largest_gap_start_utc": gap_at,
        "missing_blocks": blocks,
        "setup_ids": setup_ids, "setup_id_changes": changes,
        "max_cpu_temp_c": max(temps) if temps else None,
        "throttled_seen": "0x%x" % thrown,
        "throttled_flags": [name for bit, name in sorted(THROTTLE_BITS.items()) if thrown & (1 << bit)],
        "max_outbox_pending_files": max(outbox) if outbox else None,
        "max_disk_used_pct": max(disks) if disks else None,
        "min_jpg_bytes": min(sizes) if sizes else None,
    }

    problems = []
    if not frames:
        problems.append("no_frames")
    if frames and len(regular) < a.min_regular_fraction * expected_regular:
        problems.append("regular_low")
    if dense_expected and len(dense) < a.min_regular_fraction * dense_expected:
        problems.append("dense_low")
    if dense_basis == "previous_day":
        problems.append("dense_stopped")
    if len(night) < night_expected:
        problems.append("night_missing")
    if dng_present < dng_expected:
        problems.append("dng_missing")
    if jpg_missing:
        problems.append("jpg_missing")
    if gap is not None and gap > a.max_gap_min:
        problems.append("gap")
    if blocks["unreadable_json"]:
        problems.append("unreadable_json")
    if blocks["no_capture"] or blocks["no_system"] or blocks["no_sun"]:
        problems.append("no_meta")
    if blocks["bad_rpicam_metadata"]:
        problems.append("camera_metadata")
    if blocks["no_sha256"]:
        problems.append("no_checksum")
    if thrown & CURRENT_THROTTLE_MASK:
        problems.append("throttled")
    if temps and max(temps) > a.max_temp_c:
        problems.append("hot")
    if outbox and max(outbox) > a.max_outbox:
        problems.append("outbox")
    if disks and max(disks) > a.max_disk_pct:
        problems.append("disk")
    if sizes and min(sizes) < a.min_jpg_bytes:
        problems.append("small_jpeg")
    record["problems"] = problems
    record["ok"] = not problems
    return record


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("root", help="one camera's folder on the NAS")
    p.add_argument("--day", default="yesterday", help="YYYY-MM-DD, yesterday or today (UTC)")
    p.add_argument("--days", type=int, default=1, help="how many days, ending at --day")
    p.add_argument("--out", help="folder for the records (default ../health/<camera> beside the camera folder)")
    p.add_argument("--camera", help="camera name (default: the camera folder's name)")
    p.add_argument("--now", help="pretend it is this UTC time, 2026-11-15T12:00:00Z (tests)")
    p.add_argument("--expected-regular", type=int, default=288)
    p.add_argument("--min-regular-fraction", type=float, default=0.9)
    p.add_argument("--max-gap-min", type=float, default=30)
    p.add_argument("--max-temp-c", type=float, default=75)
    p.add_argument("--max-outbox", type=int, default=50)
    p.add_argument("--max-disk-pct", type=float, default=80)
    p.add_argument("--min-jpg-bytes", type=int, default=400000,
                   help="estimate, tune from real frames (a black readout is far smaller than a sky)")
    a = p.parse_args(argv)

    root = os.path.abspath(a.root)
    if not os.path.isdir(root):
        print("sunset-health: not a folder: %s" % root, file=sys.stderr)
        return 2
    camera = a.camera or os.path.basename(root.rstrip("/\\"))
    out_dir = a.out or os.path.join(os.path.dirname(root), "health", camera)
    now = (datetime.strptime(a.now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) if a.now
           else datetime.now(UTC))
    today = now.date()
    if a.day == "yesterday":
        last = today - timedelta(days=1)
    elif a.day == "today":
        last = today
    else:
        try:
            last = datetime.strptime(a.day, "%Y-%m-%d").date()
        except ValueError:
            print("sunset-health: bad --day %r" % a.day, file=sys.stderr)
            return 2

    worst = 0
    for i in range(a.days - 1, -1, -1):
        day = last - timedelta(days=i)
        record = build_record(root, camera, day, now, out_dir, a)
        text = json.dumps(record, indent=2) + "\n"
        write_atomic(os.path.join(out_dir, day.strftime("%Y-%m-%d") + ".json"), text)
        if record["complete"]:
            latest = os.path.join(out_dir, "latest.json")
            try:
                with open(latest, encoding="utf-8") as f:
                    newest = json.load(f).get("day_utc", "")
            except (OSError, ValueError, AttributeError):
                newest = ""
            if record["day_utc"] >= newest:
                write_atomic(latest, text)
        print("sunset-health %s %s: regular %d/%d dense %d night %d gap %s min -> %s" % (
            camera, record["day_utc"], record["frames"]["regular"]["present"], record["frames"]["regular"]["expected"],
            record["frames"]["dense"]["present"], record["frames"]["night"]["present"], record["largest_gap_min"],
            "ok" if record["ok"] else "problems: " + ",".join(record["problems"])))
    return worst


if __name__ == "__main__":
    sys.exit(main())
