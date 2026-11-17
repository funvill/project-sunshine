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
    0 to 1). If the plain peak is under 0.3 (Settings.search_below), turns of the camera up to
    --search-max-rotation (5 deg) either way are tried as well, since a turn smears the peak
    away (the real reseat and refocus turned the camera 1 and 2 deg). Frames under
    --min-response are left out of the median.
    ORB features and a RANSAC similarity fit (a second opinion): dx, dy at the middle of the
    band, rotation and scale. Night frames rarely give it enough matches.

Signs: dx and dy are in full-resolution pixels and say how the SCENE has moved in the frame
since the reference: positive dx is to the right, positive dy is down. So a camera that turns
right (pans right) gives a negative dx, and one that tips up gives a positive dy. Rotation is in
degrees, counter-clockwise as seen in the frame. Scale above 1 means the scene looks bigger.

    python tools/register_day.py --make-reference <NAS>/project_sunshine/cm4wide/2026/11/14/cm4wide_20261114T200000Z.jpg \
        --reference refs/cm4wide-cm4-window-1.jpg
    python tools/register_day.py --frames <NAS>/project_sunshine/cm4wide --day 2026-11-14 [--to 2026-11-20] \
        --reference refs/cm4wide-cm4-window-1.jpg [--night-reference refs/cm4wide-night.jpg] --out registration/

--make-reference copies the frame (byte for byte) and writes REF.json beside it with the frame's
Capture.setup_id and the image's sha256. Each day goes to <out>/<camera>/<YYYY-MM-DD>.json
(written to a .tmp file, then renamed), and one line per day is printed. Frames are only read.

What has been checked, and what hasn't (2026-11-15, issue #20): synthetic scenes
(tests/test_register_day.py) and real frames of the wide camera, Nov 4 to 14, against the known
moves. Every known move was found, with the sign above, and quiet days read under 2 px:

    reseat, Nov 5 ~07:17      camera turned right    dx -1415  dy +74   rot -1.0 deg  (day)
    refocus, Nov 8 ~05:35     skyline 650 left, 200 up  dx -687  dy -205  rot +1.9 deg  (day and night)
    nudge, Nov 12 00:11-00:18 view 37 px left       dx -35   dy -5    (00:05 against 00:25)
    quiet days Nov 9-11, 13-14                     |dx|, |dy| under 2 px; rot under 0.02 deg

They also found moves nobody had written down (signs as above, scene motion): at Nov 5
23:15-23:30 UTC the scene went ~1,690 px right and ~185 px down (the camera turned back left,
~280 px past where it started on Nov 4); at Nov 12 00:30-00:35, just after the nudge, ~65 px down
(the camera tipped up), so Nov 11 against Nov 12 at midday reads dx -32 dy +65; then ~8 px more
over Nov 12, with a step of ~6 px at about 21:00-22:00. After the Nov 5 reseat the scene crept
~20 px down through the afternoon (the camera was loose on the shelf). Before the rotation
search the reseat and refocus days came out "unknown" (peaks of 0.015 to 0.07). The searched
turn is only good to 0.3-0.6 deg on real frames (the peak is flat in the turn, and the near
towers shift against the skyline when the camera itself moves); ORB's rotation is the finer one. cm4wide against a
Nov 13 20:00 reference: Nov 13 and 14 read under 0.3 px by day, but Nov 12 reads dx -9.6 by day
and -8.2 at night (a move or settling nobody wrote down), and the Nov 14 night frames read
dy +4.1 against +0.1 by day (not explained). Not checked: cm4wide against a known move (it has
had none since it was turned upright), the moves above at night
against a night reference before the move except the refocus, fog, condensation and snow.
Needs numpy and OpenCV.
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

TOOL_VERSION = "2026-11-15.2"
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
    min_response: float = 0.10      # phase-correlation peak under this: the frame is left out
    search_below: float = 0.3       # plain peak under this: also try turns of the camera
    search_max_deg: float = 5.0     # turns tried, either way (0: no search)
    search_step_deg: float = 0.25
    search_gain: float = 2.0        # a searched turn is taken only if its peak is this many times the plain one
    min_used: int = 2               # frames needed for a reliable median
    max_spread_px: float = 2.0      # median absolute deviation of dx or dy above this: not reliable
    orb: bool = True
    orb_features: int = 4000
    orb_min_inliers: int = 40
    agree_px: float = 2.0           # phase and ORB further apart than this (plus agree_share): flagged
    agree_share: float = 0.01       # ... plus this share of the shift: a turn found to ~0.3 deg moves the band middle
    moved_px: float = 3.0           # |dx| or |dy| above this is a move
    moved_rotation_deg: float = 0.1
    moved_scale: float = 0.002      # |scale - 1| above this is a move
    clear_move_spreads: float = 3.0  # an unreliable day still moved if its shift is over moved_px + this many spreads


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


def correlate(a, b):
    """Phase correlation of two equal-size edge images with a Hann window: (dx, dy, response).
    Zero-padded to twice the size, so a shift of more than half the band (a camera knocked
    300 px up) isn't read as the same shift the other way round."""
    h, w = a.shape
    window = cv2.createHanningWindow((w, h), cv2.CV_32F)
    a = cv2.copyMakeBorder(a * window, 0, h, 0, w, cv2.BORDER_CONSTANT, value=0)
    b = cv2.copyMakeBorder(b * window, 0, h, 0, w, cv2.BORDER_CONSTANT, value=0)
    (dx, dy), response = cv2.phaseCorrelate(a, b)
    return dx, dy, float(response)


def turned_shift(ref_small, img_small, settings, rotation_deg, tx, ty):
    """Undo a guessed move (a turn of rotation_deg about the middle of the band, then a shift of
    tx, ty, in the pixels of these images), match what is left, and return the corrected shift
    and the response. Only the part of the band that both images cover is matched."""
    y0, y1, x0, x1 = band_box(ref_small.shape, settings)
    h, w = img_small.shape[:2]
    m = cv2.getRotationMatrix2D(((x0 + x1) / 2.0, (y0 + y1) / 2.0), rotation_deg, 1.0)
    m[0, 2] += tx
    m[1, 2] += ty
    back = cv2.warpAffine(img_small, m, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)
    covered = cv2.warpAffine(np.ones((h, w), np.uint8), m, (w, h), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    covered = cv2.erode(covered, np.ones((9, 9), np.uint8))[y0:y1, x0:x1].astype(np.float32)
    covered = cv2.GaussianBlur(covered, (0, 0), 4.0)
    dx, dy, response = correlate(edges(ref_small[y0:y1, x0:x1]) * covered, edges(back[y0:y1, x0:x1]) * covered)
    # The residual is measured in the turned-back image; turn it forward again.
    rx, ry = m[:, :2] @ np.array([dx, dy])
    return tx + float(rx), ty + float(ry), response


def phase_shift(ref_small, img_small, settings):
    """Phase correlation of the band: dx, dy in full-size pixels, the peak response, and the turn.

    A plain match first. If its peak is under settings.search_below, the camera may have turned
    as well as moved (the reseat on 2026-11-05 turned it 1 deg, the refocus on 2026-11-08 2 deg),
    and a turn smears the peak away: then turns up to settings.search_max_deg either way are
    tried on images half the size, and the best is refined at full working size. rotation_deg
    is that turn (counter-clockwise as seen in the frame). The peak is flat in the turn, so it is
    only good to about 0.15 deg on the synthetic scenes and 0.3 to 0.6 deg on real frames: ORB's
    rotation_deg is the finer one. dx, dy are then where the middle of the band moved to, as
    for ORB."""
    s = settings.work_scale
    y0, y1, x0, x1 = band_box(ref_small.shape, settings)
    dx, dy, response = correlate(edges(ref_small[y0:y1, x0:x1]), edges(img_small[y0:y1, x0:x1]))
    out = {"dx_px": round(dx / s, 3), "dy_px": round(dy / s, 3), "response": round(response, 4),
           "rotation_deg": 0.0, "searched": False}
    if response >= settings.search_below or settings.search_max_deg <= 0:
        return out
    out["searched"] = True
    ref_half, img_half = shrink(ref_small, 0.5), shrink(img_small, 0.5)
    step = settings.search_step_deg
    turns = np.arange(-settings.search_max_deg, settings.search_max_deg + step / 2, step)
    best = max((turned_shift(ref_half, img_half, settings, float(t), 0.0, 0.0) + (float(t),) for t in turns),
               key=lambda r: r[2])
    tx, ty, _, turn = best
    fine = max((turned_shift(ref_small, img_small, settings, t, 2 * tx, 2 * ty) + (t,)
                for t in (turn - step / 2, turn, turn + step / 2)), key=lambda r: r[2])
    # Taken only when the peak is clearly sharper than the plain one: a weak match of a still
    # camera can score a hair higher at some small turn by chance (real moves: 0.02-0.07 plain,
    # 0.17-0.29 searched).
    if fine[2] > settings.search_gain * response:
        out.update(dx_px=round(fine[0] / s, 3), dy_px=round(fine[1] / s, 3), response=round(fine[2], 4),
                   rotation_deg=round(fine[3], 3))
    return out


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
        disagree = methods_disagree(phase["dx_px"], phase["dy_px"], orb["dx_px"], orb["dy_px"], settings)
    return {"used": bool(used), "error": None, "phase": phase, "orb": orb, "methods_disagree": disagree}


def methods_disagree(dx, dy, orb_dx, orb_dy, settings):
    """Phase and ORB further apart than agree_px plus agree_share of the shift, in x or y."""
    limit = settings.agree_px + settings.agree_share * math.hypot(dx, dy)
    return bool(abs(orb_dx - dx) > limit or abs(orb_dy - dy) > limit)


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
           "rotation_deg": None, "scale": None, "phase_rotation_deg": None, "frames_searched": 0,
           "orb_frames": len(orbs),
           "orb_dx_px": None, "orb_dy_px": None, "methods_disagree": None,
           "confidence": 0.0, "reliable": False}
    if not used:
        return out
    dx, dy = median(dxs), median(dys)
    spread = max(mad(dxs), mad(dys))
    response = median([m["phase"]["response"] for m in used])
    out.update(dx_px=round(dx, 2), dy_px=round(dy, 2), spread_px=round(spread, 2), response_median=round(response, 4),
               phase_rotation_deg=round(median([m["phase"].get("rotation_deg", 0.0) for m in used]), 3),
               frames_searched=sum(1 for m in used if m["phase"].get("searched")))
    if orbs:
        out.update(rotation_deg=round(median([o["rotation_deg"] for o in orbs]), 4),
                   scale=round(median([o["scale"] for o in orbs]), 5),
                   orb_dx_px=round(median([o["dx_px"] for o in orbs]), 2),
                   orb_dy_px=round(median([o["dy_px"] for o in orbs]), 2))
        out["methods_disagree"] = methods_disagree(dx, dy, out["orb_dx_px"], out["orb_dy_px"], settings)
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
    # ORB's rotation where it held; else the turn the phase search found (only searched frames
    # have one; a searched turn is only kept when it at least doubles the peak, so a still
    # camera with a weak match doesn't gain one by chance).
    rotation = summary["rotation_deg"]
    if rotation is None:
        rotation = summary.get("phase_rotation_deg")
    if rotation is not None and abs(rotation) > settings.moved_rotation_deg:
        return True
    if summary["scale"] is not None and abs(summary["scale"] - 1.0) > settings.moved_scale:
        return True
    return False


def clearly_moved(summary, settings):
    """A day too scattered to be reliable can still have plainly moved: enough frames, and the
    median shift further from 0 than moved_px plus clear_move_spreads times their spread. On
    2026-11-05 the reseat put the frames ~1,415 px over, but the loose camera sagged ~10 px
    through the afternoon (spread 5.6 px)."""
    if not summary or summary["dx_px"] is None or summary["frames_used"] < settings.min_used:
        return False
    shift = max(abs(summary["dx_px"]), abs(summary["dy_px"]))
    return shift > settings.moved_px + settings.clear_move_spreads * summary["spread_px"]


def decide_moved(day, night, settings):
    """(moved, from which group): the daytime result if it is reliable, else the night one; else
    a group that has clearly moved even though it isn't reliable; else (None, None): not known."""
    for name, summary in (("day", day), ("night", night)):
        if summary and summary["reliable"]:
            return is_moved(summary, settings), name
    for name, summary in (("day", day), ("night", night)):
        if clearly_moved(summary, settings):
            return True, name
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
    ap.add_argument("--search-max-rotation", type=float, default=d.search_max_deg,
                    help="turns tried when the plain match is poor, degrees either way (0: none; default %s)"
                    % d.search_max_deg)
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
                            moved_rotation_deg=args.moved_rotation, moved_scale=args.moved_scale, orb=not args.no_orb,
                            search_max_deg=args.search_max_rotation)
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
