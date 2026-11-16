#!/usr/bin/env python3
"""Measure how clear each frame is, to find fog, condensation, smoke or a closed blind (issue #33).

A fogged or misted window still gives a fresh frame every 5 minutes, so the frame-age alert stays
green. This tool measures the picture instead, with no AI. Measure first: nothing alerts from it yet.

For each 5-minute frame (every --every minutes of them), on the skyline band (rows 35% to 85% of
the height, as in register_day.py; the sky above has nothing sharp in it):

    sharpness   variance of the Laplacian of log(1 + grey), at quarter size. The log makes a darker
                frame (evening, cloud) read about as sharp as a bright one; fog, mist and a soft
                focus read lower.
    contrast    RMS contrast: the standard deviation of the grey level over its mean.
    mean        mean grey level of the band (0-255).
    lux, elevation, setup_id   from the frame's JSON (Lux, Sun.elevation_deg, Capture.setup_id).

clarity is a frame's sharpness over the camera's baseline for the same time of day: the median
sharpness of the same --slot-min slot (UTC) on up to --baseline-days earlier days with the same
setup_id. About 1 is a normal frame; fog or condensation shows as a run of daylight frames well
under it. A camera move or refocus changes setup_id (or should), which starts a new baseline; one
nobody recorded shows as a step that stays. Night frames get a clarity too, but street lights and
lit windows make it a different measure; low_runs() only looks at daylight (sun above
--day-min-elevation).

    python tools/fog_scan.py --frames <NAS>/project_sunshine/wide --day 2026-11-04 --to 2026-11-16 --out fog/

Each finished UTC day's measurements are cached in <out>/<camera>/<day>.csv, so a rerun only reads
the new days. <out>/<camera>/clarity.csv has every frame with its clarity, and one line per day is
printed: the median daylight clarity, the lowest frame, and any run under --threshold.
Frames are only read. Needs numpy and OpenCV.
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys
from datetime import date, datetime, timedelta, timezone

import cv2
import numpy as np

UTC = timezone.utc
FRAME = re.compile(r"^(?P<cam>[A-Za-z0-9]+)_(?P<t>\d{8}T\d{6}Z)\.jpg$")   # regular frames only: no _night, _ev*
BAND = (0.35, 0.85)
FIELDS = ["time", "sharpness", "contrast", "mean", "lux", "elevation", "setup_id"]


def measure(gray, band=BAND):
    """sharpness, contrast and mean of the band of a grey picture (2-D uint8)."""
    h = gray.shape[0]
    part = gray[int(round(h * band[0])):int(round(h * band[1]))]
    log = np.log1p(part.astype(np.float32))
    lap = cv2.Laplacian(log, cv2.CV_32F)
    mean = float(part.mean())
    return {"sharpness": float(lap.var()) * 1000.0, "contrast": float(part.std()) / max(mean, 1.0), "mean": mean}


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def list_frames(frames_dir, camera, first, last, every_min=5):
    """The regular frames of the UTC days first..last whose minute is a multiple of every_min."""
    found, day = [], first
    while day <= last:
        folder = os.path.join(frames_dir, "%04d" % day.year, "%02d" % day.month, "%02d" % day.day)
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            m = FRAME.match(name)
            if not m or m.group("cam") != camera:
                continue
            t = datetime.strptime(m.group("t"), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            if t.second > 30 or t.minute % every_min:      # dense frames are taken ~12 s or more into the minute
                continue
            path = os.path.join(folder, name)
            meta = read_json(path[:-4] + ".json")
            found.append({"time": t, "path": path, "lux": number(meta.get("Lux")),
                          "elevation": number((meta.get("Sun") or {}).get("elevation_deg")),
                          "setup_id": str((meta.get("Capture") or {}).get("setup_id") or "")})
        day += timedelta(days=1)
    return found


def measure_frame(path):
    gray = cv2.imread(path, cv2.IMREAD_REDUCED_GRAYSCALE_4)
    return measure(gray) if gray is not None else None


def write_rows(path, rows, every_min):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        f.write("# every_min=%d\n" % every_min)
        w = csv.DictWriter(f, FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(dict(r, time=r["time"].strftime("%Y-%m-%dT%H:%M:%SZ")))
    os.replace(tmp, path)


def read_rows(path, every_min):
    try:
        with open(path, encoding="utf-8") as f:
            if f.readline().strip() != "# every_min=%d" % every_min:
                return None
            rows = []
            for r in csv.DictReader(f):
                rows.append({"time": datetime.strptime(r["time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC),
                             "sharpness": float(r["sharpness"]), "contrast": float(r["contrast"]),
                             "mean": float(r["mean"]), "lux": number(r["lux"]), "elevation": number(r["elevation"]),
                             "setup_id": r["setup_id"]})
            return rows
    except (OSError, ValueError, KeyError):
        return None


def scan(frames_dir, camera, first, last, out_dir, every_min=5, today=None):
    """Measured rows for the days first..last, from the cache where a finished day has one."""
    today = today or datetime.now(UTC).date()
    cache_dir = os.path.join(out_dir, camera)
    os.makedirs(cache_dir, exist_ok=True)
    rows, day = [], first
    while day <= last:
        cache = os.path.join(cache_dir, day.isoformat() + ".csv")
        cached = read_rows(cache, every_min) if day < today else None
        if cached is None:
            cached = []
            for f in list_frames(frames_dir, camera, day, day, every_min):
                m = measure_frame(f["path"])
                if m:
                    cached.append(dict(f, **m))
            if day < today:
                write_rows(cache, cached, every_min)
        rows.extend(cached)
        day += timedelta(days=1)
    return rows


def add_clarity(rows, baseline_days=7, slot_min=30, min_baseline=3):
    """Set row["clarity"]: sharpness over the median of the same time-of-day slot on earlier days
    with the same setup_id (None with fewer than min_baseline of them)."""
    slots = {}
    for r in rows:
        key = (r["setup_id"], (r["time"].hour * 60 + r["time"].minute) // slot_min)
        slots.setdefault(key, []).append(r)
    for group in slots.values():
        for r in group:
            day = r["time"].date()
            base = [o["sharpness"] for o in group if day - timedelta(days=baseline_days) <= o["time"].date() < day]
            r["clarity"] = r["sharpness"] / statistics.median(base) if len(base) >= min_baseline and statistics.median(base) > 0 else None
    return rows


def low_runs(rows, threshold=0.5, min_frames=3, day_min_elevation=5.0):
    """Runs of at least min_frames daylight frames in a row with clarity under threshold."""
    runs, current = [], []
    daylight = [r for r in sorted(rows, key=lambda r: r["time"])
                if r.get("clarity") is not None and r["elevation"] is not None and r["elevation"] > day_min_elevation]
    for r in daylight + [None]:
        if r is not None and r["clarity"] < threshold and (not current or r["time"] - current[-1]["time"] <= timedelta(hours=2)):
            current.append(r)
            continue
        if len(current) >= min_frames:
            runs.append({"start": current[0]["time"], "end": current[-1]["time"], "frames": len(current),
                         "min_clarity": min(c["clarity"] for c in current)})
        current = [r] if r is not None and r["clarity"] < threshold else []
    return runs


def day_line(camera, day, rows, runs, day_min_elevation):
    mine = [r for r in rows if r["time"].date() == day and r.get("clarity") is not None]
    lit = [r for r in mine if r["elevation"] is not None and r["elevation"] > day_min_elevation]
    if not lit:
        return "%s %s: %d frames, no daylight baseline yet" % (camera, day, len([r for r in rows if r["time"].date() == day]))
    low = min(lit, key=lambda r: r["clarity"])
    mine_runs = [x for x in runs if x["start"].date() == day]
    return "%s %s: %d daylight frames, median clarity %.2f, lowest %.2f at %s%s" % (
        camera, day, len(lit), statistics.median(r["clarity"] for r in lit), low["clarity"],
        low["time"].strftime("%H:%M"),
        "".join(" | low %s-%s (%d frames, min %.2f)" % (x["start"].strftime("%H:%M"), x["end"].strftime("%H:%M"),
                                                       x["frames"], x["min_clarity"]) for x in mine_runs))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", required=True, help="the camera's frame folder, holding YYYY/MM/DD/")
    ap.add_argument("--camera", help="camera name in the file names (default: the --frames folder's name)")
    ap.add_argument("--day", required=True, help="first UTC day, YYYY-MM-DD")
    ap.add_argument("--to", help="last UTC day (default: --day)")
    ap.add_argument("--out", required=True, help="output folder; files go to <out>/<camera>/")
    ap.add_argument("--every", type=int, default=5, help="use the frames whose minute is a multiple of this (5 = all)")
    ap.add_argument("--baseline-days", type=int, default=7)
    ap.add_argument("--slot-min", type=int, default=30)
    ap.add_argument("--threshold", type=float, default=0.5, help="clarity under this is low (an estimate, to tune)")
    ap.add_argument("--min-frames", type=int, default=3, help="this many low daylight frames in a row make a run")
    ap.add_argument("--day-min-elevation", type=float, default=5.0)
    a = ap.parse_args(argv)
    camera = a.camera or os.path.basename(os.path.normpath(a.frames))
    first = date.fromisoformat(a.day)
    last = date.fromisoformat(a.to) if a.to else first
    # the baseline needs the days before the first one asked for
    rows = scan(a.frames, camera, first - timedelta(days=a.baseline_days), last, a.out, a.every)
    add_clarity(rows, a.baseline_days, a.slot_min)
    runs = low_runs(rows, a.threshold, a.min_frames, a.day_min_elevation)
    out = os.path.join(a.out, camera, "clarity.csv")
    with open(out + ".tmp", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS + ["clarity"], extrasaction="ignore")
        w.writeheader()
        for r in rows:
            if r["time"].date() >= first:
                w.writerow(dict(r, time=r["time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                                clarity="" if r["clarity"] is None else "%.3f" % r["clarity"]))
    os.replace(out + ".tmp", out)
    day = first
    while day <= last:
        print(day_line(camera, day, rows, runs, a.day_min_elevation))
        day += timedelta(days=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
