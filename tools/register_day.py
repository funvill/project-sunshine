#!/usr/bin/env python3
"""Measure how far a camera has moved on one UTC day, against a reference frame, with no AI.

Issue #20, first step. The skyline and the near towers don't move; the sky changes completely,
and day and night look nothing alike. So the match is made only inside a band of the frame that
holds the skyline (rows 35% to 85% of the height by default), on the gradients of the log of the
brightness rather than the brightness itself (a darker or brighter frame has the same edges),
with the slow changes taken out. Several frames of the day are measured and the median is the
answer, so one odd frame can't set it:

    up to 6 daytime frames spread over the day (Sun.elevation_deg above 5 deg), and
    up to 4 _night frames, reported separately (against --night-reference if one is given).

Each frame is measured twice:

    phase correlation with a Hann window: dx, dy and a response (how sharp the peak is,
    0 to 1). Frames under --min-response are left out of the median.
    ORB features and a RANSAC similarity fit (a second opinion): dx, dy at the middle of the
    band, rotation and scale. Night frames rarely give it enough matches.

dx and dy are in full-resolution pixels: how far the scene has moved in the frame since the
reference (positive dx is to the right, positive dy is down). Rotation is in degrees,
counter-clockwise as seen in the frame. Scale above 1 means the scene looks bigger.

    python tools/register_day.py --make-reference <NAS>/project_sunshine/cm4wide/2026/11/14/cm4wide_20261114T200000Z.jpg \
        --reference refs/cm4wide-cm4-window-1.jpg
    python tools/register_day.py --frames <NAS>/project_sunshine/cm4wide --day 2026-11-14 [--to 2026-11-20] \
        --reference refs/cm4wide-cm4-window-1.jpg [--night-reference refs/cm4wide-night.jpg] --out registration/

--make-reference copies the frame (byte for byte) and writes REF.json beside it with the frame's
Capture.setup_id and the image's sha256. Each day goes to <out>/<camera>/<YYYY-MM-DD>.json
(written to a .tmp file, then renamed), and one line per day is printed. Frames are only read.

What has been checked, and what hasn't: only synthetic scenes (tests/test_register_day.py): a
random skyline with window grids, shifted by up to 600 px, sub-pixel shifts, turned up to 1 deg,
scaled by 1%, with the sky replaced by gradients, noise and blurred noise, the brightness changed
and a bright sun disc added. There a fractional shift came back within 0.3 px, a whole-pixel one
(up to 600 px) within 0.05 px, rotation within 0.05 deg and scale within 0.0005; an unrelated
skyline gave a response of 0.01 (the limit is 0.15) instead of a confident answer, and the
synthetic night frames 0.2 to 0.3. It has not been run on a real frame. Every threshold here (band, response, spread, the moved limits, the daytime
elevation) is an estimate to tune on real frames, and night against a daytime reference is
expected to be weak: double glazing, lit windows that change, and the 3.2 mm lens's barrel
distortion are not in the synthetic scenes. Needs numpy and OpenCV.
"""
import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta, timezone

import cv2
import numpy as np

TOOL_VERSION = "2026-11-15.1"
SCHEMA_VERSION = 1
UTC = timezone.utc
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FRAME = re.compile(r"^(?P<cam>[A-Za-z0-9-]+)_(?P<t>\d{8}T\d{6}Z)(?P<night>_night)?\.jpg$")


@dataclasses.dataclass
class Settings:
    band: tuple = (0.35, 0.85)      # rows to match, as fractions of the height: the skyline, not the sky
    columns: tuple = (0.0, 1.0)     # columns to match, the same way
    work_scale: float = 0.5         # frames are shrunk by this first; results are in full-size pixels
    day_min_elevation: float = 5.0  # Sun.elevation_deg above this is a daytime frame
    day_frames: int = 6
    night_frames: int = 4
    min_response: float = 0.15      # phase-correlation peak under this: the frame is left out
    min_used: int = 2               # frames needed for a reliable median
    max_spread_px: float = 2.0      # median absolute deviation of dx or dy above this: not reliable
    orb: bool = True
    orb_features: int = 4000
    orb_min_inliers: int = 40
    agree_px: float = 2.0           # phase and ORB further apart than this: flagged
    moved_px: float = 3.0           # |dx| or |dy| above this is a move
    moved_rotation_deg: float = 0.1
    moved_scale: float = 0.002      # |scale - 1| above this is a move


def utc_now():
    return datetime.now(UTC).strftime(TIME_FORMAT)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def frame_info(jpg_path):
    """(Sun.elevation_deg, Capture.setup_id) from the frame's JSON; each None if missing.
    Frames from before 2026-11-04 have no Capture block."""
    data = read_json(os.path.splitext(jpg_path)[0] + ".json") or {}
    sun = data.get("Sun") if isinstance(data.get("Sun"), dict) else {}
    capture = data.get("Capture") if isinstance(data.get("Capture"), dict) else {}
    elevation = sun.get("elevation_deg")
    return (float(elevation) if isinstance(elevation, (int, float)) else None), capture.get("setup_id")


def band_box(shape, settings):
    """(y0, y1, x0, x1) of the matching region in an image of this shape."""
    h, w = shape[:2]
    y0, y1 = int(round(h * settings.band[0])), int(round(h * settings.band[1]))
    x0, x1 = int(round(w * settings.columns[0])), int(round(w * settings.columns[1]))
    return y0, max(y1, y0 + 8), x0, max(x1, x0 + 8)


def shrink(gray, scale):
    if scale == 1.0:
        return gray
    h, w = gray.shape[:2]
    return cv2.resize(gray, (max(8, int(round(w * scale))), max(8, int(round(h * scale)))), interpolation=cv2.INTER_AREA)


def edges(gray_band):
    """What is matched: the gradient size of the log brightness, with slow changes taken out.
    A frame twice as bright has the same log gradients; a smooth sky gradient has almost none."""
    log = np.log1p(gray_band.astype(np.float32))
    log = cv2.GaussianBlur(log, (0, 0), 1.0)
    gx = cv2.Sobel(log, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(log, cv2.CV_32F, 0, 1)
    mag = cv2.magnitude(gx, gy)
    return mag - cv2.GaussianBlur(mag, (0, 0), 15.0)


def phase_shift(ref_small, img_small, settings):
    """Phase correlation of the band: dx, dy in full-size pixels and the peak response."""
    y0, y1, x0, x1 = band_box(ref_small.shape, settings)
    a, b = edges(ref_small[y0:y1, x0:x1]), edges(img_small[y0:y1, x0:x1])
    window = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    # Zero-padded to twice the size, so a shift of more than half the band (a camera knocked
    # 300 px up) isn't read as the same shift the other way round.
    h, w = a.shape
    a = cv2.copyMakeBorder(a * window, 0, h, 0, w, cv2.BORDER_CONSTANT, value=0)
    b = cv2.copyMakeBorder(b * window, 0, h, 0, w, cv2.BORDER_CONSTANT, value=0)
    (dx, dy), response = cv2.phaseCorrelate(a, b)
    s = settings.work_scale
    return {"dx_px": round(dx / s, 3), "dy_px": round(dy / s, 3), "response": round(float(response), 4)}


def orb_similarity(ref_small, img_small, settings):
    """ORB matches inside the band and a RANSAC similarity fit (rotation, scale, shift).
    dx, dy are where the middle of the band moved to, in full-size pixels."""
    y0, y1, x0, x1 = band_box(ref_small.shape, settings)
    mask = np.zeros(ref_small.shape[:2], np.uint8)
    mask[y0:y1, x0:x1] = 255
    clahe = cv2.createCLAHE(2.0, (8, 8))
    orb = cv2.ORB_create(settings.orb_features)
    ka, da = orb.detectAndCompute(clahe.apply(ref_small), mask)
    kb, db = orb.detectAndCompute(clahe.apply(img_small), mask)
    result = {"ok": False, "matches": 0, "inliers": 0}
    if da is None or db is None or len(ka) < 3 or len(kb) < 3:
        return result
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    result["matches"] = len(matches)
    if len(matches) < 3:
        return result
    pa = np.float32([ka[m.queryIdx].pt for m in matches])
    pb = np.float32([kb[m.trainIdx].pt for m in matches])
    cv2.setRNGSeed(0)   # RANSAC samples at random; the same seed gives the same answer every run
    m, inliers = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=2.0,
                                             maxIters=5000, confidence=0.999)
    if m is None:
        return result
    count = int(inliers.sum())
    s = settings.work_scale
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    px, py = (float(v) for v in m @ np.array([cx, cy, 1.0]))
    result.update(inliers=count, inlier_share=round(count / len(matches), 3),
                  dx_px=round((px - cx) / s, 3), dy_px=round((py - cy) / s, 3),
                  rotation_deg=round(-math.degrees(math.atan2(float(m[1, 0]), float(m[0, 0]))), 4),
                  scale=round(math.hypot(float(m[0, 0]), float(m[1, 0])), 5))
    result["ok"] = count >= settings.orb_min_inliers
    return result


def measure_pair(ref_gray, gray, settings):
    """One frame against the reference: both methods, whether it is used, whether they disagree."""
    if gray is None:
        return {"used": False, "error": "unreadable", "phase": None, "orb": None, "methods_disagree": None}
    if gray.shape[:2] != ref_gray.shape[:2]:
        return {"used": False, "error": "size %dx%d differs from the reference %dx%d" % (
            gray.shape[1], gray.shape[0], ref_gray.shape[1], ref_gray.shape[0]),
            "phase": None, "orb": None, "methods_disagree": None}
    ref_small, img_small = shrink(ref_gray, settings.work_scale), shrink(gray, settings.work_scale)
    phase = phase_shift(ref_small, img_small, settings)
    orb = orb_similarity(ref_small, img_small, settings) if settings.orb else None
    used = phase["response"] >= settings.min_response
    disagree = None
    if used and orb and orb["ok"]:
        disagree = bool(abs(orb["dx_px"] - phase["dx_px"]) > settings.agree_px
                        or abs(orb["dy_px"] - phase["dy_px"]) > settings.agree_px)
    return {"used": bool(used), "error": None, "phase": phase, "orb": orb, "methods_disagree": disagree}


def median(values):
    return float(np.median(values)) if values else None


def mad(values):
    if not values:
        return None
    mid = np.median(values)
    return float(np.median(np.abs(np.asarray(values) - mid)))


def summarise(measurements, settings):
    """The median of the frames that passed --min-response, how scattered they are, and whether
    the result can be trusted. Rotation and scale come from the frames whose ORB fit held."""
    used = [m for m in measurements if m.get("used")]
    dxs = [m["phase"]["dx_px"] for m in used]
    dys = [m["phase"]["dy_px"] for m in used]
    orbs = [m["orb"] for m in used if m.get("orb") and m["orb"].get("ok")]
    out = {"frames_measured": len(measurements), "frames_used": len(used),
           "dx_px": None, "dy_px": None, "spread_px": None, "response_median": None,
           "rotation_deg": None, "scale": None, "orb_frames": len(orbs),
           "orb_dx_px": None, "orb_dy_px": None, "methods_disagree": None,
           "confidence": 0.0, "reliable": False}
    if not used:
        return out
    dx, dy = median(dxs), median(dys)
    spread = max(mad(dxs), mad(dys))
    response = median([m["phase"]["response"] for m in used])
    out.update(dx_px=round(dx, 2), dy_px=round(dy, 2), spread_px=round(spread, 2), response_median=round(response, 4))
    if orbs:
        out.update(rotation_deg=round(median([o["rotation_deg"] for o in orbs]), 4),
                   scale=round(median([o["scale"] for o in orbs]), 5),
                   orb_dx_px=round(median([o["dx_px"] for o in orbs]), 2),
                   orb_dy_px=round(median([o["dy_px"] for o in orbs]), 2))
        out["methods_disagree"] = bool(abs(out["orb_dx_px"] - dx) > settings.agree_px
                                       or abs(out["orb_dy_px"] - dy) > settings.agree_px)
    # A relative 0-1 number for sorting days, not a probability: the peak's sharpness (0.5 or more
    # counts as full), times the share of frames used, cut down when the frames scatter.
    tight = 1.0 if spread <= settings.max_spread_px else settings.max_spread_px / spread
    out["confidence"] = round(min(1.0, response / 0.5) * len(used) / len(measurements) * tight, 3)
    # A single frame counts only when a single frame was asked for (--day-frames 1).
    out["reliable"] = bool(len(used) >= min(settings.min_used, len(measurements)) and spread <= settings.max_spread_px)
    return out


def is_moved(summary, settings):
    if summary["dx_px"] is None:
        return None
    if abs(summary["dx_px"]) > settings.moved_px or abs(summary["dy_px"]) > settings.moved_px:
        return True
    if summary["rotation_deg"] is not None and abs(summary["rotation_deg"]) > settings.moved_rotation_deg:
        return True
    if summary["scale"] is not None and abs(summary["scale"] - 1.0) > settings.moved_scale:
        return True
    return False


def decide_moved(day, night, settings):
    """(moved, from which group): the daytime result if it is reliable, else the night one, else
    (None, None): not known."""
    for name, summary in (("day", day), ("night", night)):
        if summary and summary["reliable"]:
            return is_moved(summary, settings), name
    return None, None


def spread_pick(items, n):
    """Up to n items spread evenly over the list (first and last included)."""
    if n <= 0 or not items:
        return []
    if len(items) <= n:
        return list(items)
    idx = sorted({int(round(i)) for i in np.linspace(0, len(items) - 1, n)})
    return [items[i] for i in idx]


def day_folder(frames_dir, day):
    return os.path.join(frames_dir, "%04d" % day.year, "%02d" % day.month, "%02d" % day.day)


def list_day(frames_dir, camera, day):
    """[(name, path, is_night, elevation, setup_id)] for the camera's frames in the UTC day folder."""
    folder = day_folder(frames_dir, day)
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out = []
    for name in names:
        m = FRAME.match(name)
        if not m or m.group("cam") != camera:
            continue
        path = os.path.join(folder, name)
        elevation, setup = frame_info(path)
        out.append((name, path, bool(m.group("night")), elevation, setup))
    return out


def reference_info(path):
    side = read_json(os.path.splitext(path)[0] + ".json") or {}
    digest = sha256_file(path)
    info = {"path": os.path.basename(path), "sha256": digest, "id": "%s:%s" % (os.path.basename(path), digest[:12]),
            "setup_id": side.get("setup_id"), "source_frame": side.get("source_frame")}
    if side.get("sha256") and side["sha256"] != digest:
        info["warning"] = "the image does not match the sha256 in its .json"
    return info


def load_gray(path):
    return cv2.imread(path, cv2.IMREAD_GRAYSCALE)


def register_day(frames_dir, camera, day, reference, out_dir, settings=None, night_reference=None):
    """Measure one UTC day and write <out_dir>/<camera>/<day>.json. Returns the record."""
    settings = settings or Settings()
    day = date.fromisoformat(day) if isinstance(day, str) else day
    ref_gray = load_gray(reference)
    if ref_gray is None:
        raise ValueError("can't read the reference %s" % reference)
    night_gray = load_gray(night_reference) if night_reference else ref_gray
    if night_gray is None:
        raise ValueError("can't read the night reference %s" % night_reference)
    frames = list_day(frames_dir, camera, day)
    setups = sorted({f[4] for f in frames if f[4]})
    daytime = [f for f in frames if not f[2] and f[3] is not None and f[3] > settings.day_min_elevation]
    nights = [f for f in frames if f[2]]
    measured = []
    for kind, chosen, ref in (("day", spread_pick(daytime, settings.day_frames), ref_gray),
                              ("night", spread_pick(nights, settings.night_frames), night_gray)):
        for name, path, _, elevation, setup in chosen:
            m = measure_pair(ref, load_gray(path), settings)
            t = datetime.strptime(FRAME.match(name).group("t"), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            measured.append(dict(frame=name, kind=kind, utc=t.strftime(TIME_FORMAT), elevation_deg=elevation,
                                 setup_id=setup, **m))
    day_summary = summarise([m for m in measured if m["kind"] == "day"], settings)
    night_summary = summarise([m for m in measured if m["kind"] == "night"], settings)
    moved, moved_from = decide_moved(day_summary, night_summary, settings)
    ref = reference_info(reference)
    record = {
        "schema_version": SCHEMA_VERSION, "tool": "register_day.py", "tool_version": TOOL_VERSION,
        "camera": camera, "day_utc": day.isoformat(), "created_utc": utc_now(),
        "reference": ref, "night_reference": reference_info(night_reference) if night_reference else None,
        "settings": {k: list(v) if isinstance(v, tuple) else v for k, v in dataclasses.asdict(settings).items()},
        "frames_in_folder": len(frames), "daytime_frames_in_folder": len(daytime), "night_frames_in_folder": len(nights),
        "setup_ids_seen": setups, "frames_without_setup_id": sum(1 for f in frames if not f[4]),
        "reference_setup_matches": (setups == [ref["setup_id"]]) if ref["setup_id"] and setups else None,
        "frames": measured, "day": day_summary, "night": night_summary,
        "moved": moved, "moved_from": moved_from,
    }
    folder = os.path.join(out_dir, camera)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, day.isoformat() + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return record


def summary_line(record):
    def part(name, s):
        if not s["frames_measured"]:
            return "%s: no frames" % name
        if s["dx_px"] is None:
            return "%s: no match (0/%d frames)" % (name, s["frames_measured"])
        rot = "" if s["rotation_deg"] is None else " rot=%+.2f deg" % s["rotation_deg"]
        flags = ("" if s["reliable"] else " UNRELIABLE") + (" METHODS DISAGREE" if s["methods_disagree"] else "")
        return "%s dx=%+.1f dy=%+.1f px%s (%d/%d frames, spread %.1f px, conf %.2f)%s" % (
            name, s["dx_px"], s["dy_px"], rot, s["frames_used"], s["frames_measured"], s["spread_px"],
            s["confidence"], flags)
    moved = {True: "YES", False: "no", None: "unknown"}[record["moved"]]
    return "%s %s: %s; %s; moved: %s (ref %s)" % (record["camera"], record["day_utc"], part("day", record["day"]),
                                                  part("night", record["night"]), moved, record["reference"]["id"])


def make_reference(frame, reference, force=False):
    """Copy a frame to `reference` and write reference.json with its setup_id and sha256."""
    if os.path.exists(reference) and not force:
        raise FileExistsError("%s exists (use --force to replace it)" % reference)
    if load_gray(frame) is None:
        raise ValueError("can't read %s as an image" % frame)
    os.makedirs(os.path.dirname(os.path.abspath(reference)), exist_ok=True)
    shutil.copyfile(frame, reference)
    elevation, setup = frame_info(frame)
    m = FRAME.match(os.path.basename(frame))
    side = {"schema_version": SCHEMA_VERSION, "source_frame": os.path.basename(frame),
            "camera": m.group("cam") if m else None,
            "frame_utc": datetime.strptime(m.group("t"), "%Y%m%dT%H%M%SZ").strftime(TIME_FORMAT) if m else None,
            "night": bool(m and m.group("night")), "setup_id": setup, "elevation_deg": elevation,
            "sha256": sha256_file(reference), "created_utc": utc_now(), "tool_version": TOOL_VERSION}
    path = os.path.splitext(reference)[0] + ".json"
    with open(path + ".tmp", "w") as f:
        json.dump(side, f, indent=2)
        f.write("\n")
    os.replace(path + ".tmp", path)
    return side


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--make-reference", metavar="FRAME", help="save FRAME as the reference given by --reference")
    ap.add_argument("--force", action="store_true", help="with --make-reference: replace an existing reference")
    ap.add_argument("--reference", required=True, help="the reference image (made with --make-reference)")
    ap.add_argument("--night-reference", help="a reference for the _night frames (default: --reference)")
    ap.add_argument("--frames", help="the camera's frame folder, holding YYYY/MM/DD/")
    ap.add_argument("--camera", help="camera name in the file names (default: the --frames folder's name)")
    ap.add_argument("--day", help="UTC day, YYYY-MM-DD")
    ap.add_argument("--to", help="last UTC day of a range (default: --day)")
    ap.add_argument("--out", help="output folder; each day goes to <out>/<camera>/<day>.json")
    d = Settings()
    ap.add_argument("--band", type=float, nargs=2, default=d.band, metavar=("TOP", "BOTTOM"),
                    help="rows to match, fractions of the height (default %s %s)" % d.band)
    ap.add_argument("--columns", type=float, nargs=2, default=d.columns, metavar=("LEFT", "RIGHT"))
    ap.add_argument("--work-scale", type=float, default=d.work_scale)
    ap.add_argument("--day-min-elevation", type=float, default=d.day_min_elevation)
    ap.add_argument("--day-frames", type=int, default=d.day_frames)
    ap.add_argument("--night-frames", type=int, default=d.night_frames)
    ap.add_argument("--min-response", type=float, default=d.min_response)
    ap.add_argument("--max-spread", type=float, default=d.max_spread_px)
    ap.add_argument("--moved-px", type=float, default=d.moved_px)
    ap.add_argument("--moved-rotation", type=float, default=d.moved_rotation_deg)
    ap.add_argument("--moved-scale", type=float, default=d.moved_scale)
    ap.add_argument("--no-orb", action="store_true", help="phase correlation only (faster, no rotation or scale)")
    args = ap.parse_args(argv)
    try:
        if args.make_reference:
            side = make_reference(args.make_reference, args.reference, args.force)
            print("reference %s from %s (setup %s)" % (args.reference, side["source_frame"], side["setup_id"]))
            return 0
        if not (args.frames and args.day and args.out):
            ap.error("--frames, --day and --out are needed (or --make-reference)")
        settings = Settings(band=tuple(args.band), columns=tuple(args.columns), work_scale=args.work_scale,
                            day_min_elevation=args.day_min_elevation, day_frames=args.day_frames,
                            night_frames=args.night_frames, min_response=args.min_response,
                            max_spread_px=args.max_spread, moved_px=args.moved_px,
                            moved_rotation_deg=args.moved_rotation, moved_scale=args.moved_scale, orb=not args.no_orb)
        camera = args.camera or os.path.basename(os.path.normpath(args.frames))
        first = date.fromisoformat(args.day)
        last = date.fromisoformat(args.to) if args.to else first
        day = first
        while day <= last:
            record = register_day(args.frames, camera, day, args.reference, args.out, settings, args.night_reference)
            print(summary_line(record), flush=True)
            day += timedelta(days=1)
    except (OSError, ValueError) as e:
        print("register_day.py: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
