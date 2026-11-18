#!/usr/bin/env python3
"""Merge the sunset bracket into fused frames for the daily video, with no AI.

The `sunset` experiment shoots a pair every minute around sunset: ev+0 and ev-2, both with
daylight white balance. Steven ranked the merge of the two best (2026-11-09): it keeps the sky
the camera blows out, and holds the glow warm. This tool merges each pair (Mertens exposure
fusion) and blends the result with the production frame of the same minute, so the video
slides into and out of it instead of jumping:

    full strength from 40 min before sunset to 5 min after, fading in over the first 5 minutes
    of the run and out between +5 and +12 minutes, when daylight white balance turns the
    sky brown as the city lights the cloud.

The output files are named like the production frames, so the video job swaps them in:

    python tools/fuse_sunset.py --run <NAS>/project_sunshine_experiments/cm4-sunset-1 \
        --frames <NAS>/project_sunshine/cm4wide --out fused/
    FUSED_DIR=fused/ ...   (or tools/build_video.py --fuse-run cm4-sunset-1)

Then each sunset minute is blended 1:2:1 with the minutes either side (blend_run), which calms
thin cloud crossing the glow; --no-blend skips it, and --force redoes both.

It changes nothing on the NAS. Needs numpy and OpenCV.
"""
import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

UTC = timezone.utc
NAME = re.compile(r"^(?P<prefix>.+)_(?P<t>\d{8}T\d{6}Z)\.jpg$")
FADE_IN_MIN = 5.0          # of the run, so the first fused frames are mostly the production frame
FADE_OUT_START = 5.0       # minutes after sunset
FADE_OUT_END = 12.0
PAIR_SECONDS = 5           # the two shots of a minute are about 2 s apart
MATCH_SECONDS = 40         # to the production frame of that minute
FILL_MAX_MIN = 8           # a frame with no pair uses the pairs either side, if they are this close
JPEG_QUALITY = 92


def clamp(x):
    return max(0.0, min(1.0, x))


def fuse_weight(minutes_from_sunset, minutes_into_run, fade_out=(FADE_OUT_START, FADE_OUT_END)):
    """How much of the fused frame to use: 1 is all of it, 0 is the production frame. fade_out:
    the minutes after sunset over which the merge hands back to the production frame."""
    start, end = fade_out
    fade_in = clamp(minutes_into_run / FADE_IN_MIN)
    out = clamp((end - minutes_from_sunset) / (end - start)) if end > start else float(minutes_from_sunset < end)
    return min(fade_in, out)


def fuse(bright, dark):
    """Mertens exposure fusion of two 8-bit BGR pictures, back to 8-bit."""
    merged = cv2.createMergeMertens(1.0, 1.0, 1.0).process([bright, dark])
    return np.clip(merged * 255.0 + 0.5, 0, 255).astype(np.uint8)


def blend(production, fused, weight):
    mixed = production.astype(np.float32) * (1.0 - weight) + fused.astype(np.float32) * weight
    return np.clip(mixed + 0.5, 0, 255).astype(np.uint8)


def parse_time(text):
    return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def list_run(run_dir, prefix):
    """(time, path) of every `prefix_<UTC>.jpg` in the experiment folder, oldest first."""
    found = []
    for name in os.listdir(run_dir):
        m = NAME.match(name)
        if m and m.group("prefix") == prefix:
            found.append((parse_time(m.group("t")), os.path.join(run_dir, name)))
    return sorted(found)


def nearest(items, t, seconds):
    best = min(items, key=lambda item: abs((item[0] - t).total_seconds()), default=None)
    return best if best and abs((best[0] - t).total_seconds()) <= seconds else None


def production_frames(frames_dir, start, end):
    """(time, path) of the normal frames, not night, between start and end, from <dir>/YYYY/MM/DD."""
    found, day = [], start.date()
    while day <= end.date():
        folder = os.path.join(frames_dir, "%04d" % day.year, "%02d" % day.month, "%02d" % day.day)
        for name in (os.listdir(folder) if os.path.isdir(folder) else []):
            m = NAME.match(name)
            if m and "night" not in name and start <= parse_time(m.group("t")) <= end:
                found.append((parse_time(m.group("t")), os.path.join(folder, name)))
        day += timedelta(days=1)
    return sorted(found)


BRACKET_NAME = re.compile(r"^(?P<prefix>.+)_(?P<t>\d{8}T\d{6}Z)_(?P<ev>ev0|ev-2)\.jpg$")


def production_bracket(frames_dir, start, end):
    """(brights, darks) from the production bracket (BRACKET=1 in sunset.env, #10): the ev+0 and ev-2
    shots saved beside each frame in the sunset window as <cam>_<UTC>_ev0.jpg and _ev-2.jpg, timed
    by the frame they belong to. Same shape as list_run() gives for an experiment run."""
    found, day = {"ev0": [], "ev-2": []}, start.date()
    while day <= end.date():
        folder = os.path.join(frames_dir, "%04d" % day.year, "%02d" % day.month, "%02d" % day.day)
        for name in (os.listdir(folder) if os.path.isdir(folder) else []):
            m = BRACKET_NAME.match(name)
            if m and start <= parse_time(m.group("t")) <= end:
                found[m.group("ev")].append((parse_time(m.group("t")), os.path.join(folder, name)))
        day += timedelta(days=1)
    return sorted(found["ev0"]), sorted(found["ev-2"])


def minutes_from_sunset(jpg_path):
    try:
        with open(os.path.splitext(jpg_path)[0] + ".json") as f:
            return float(json.load(f)["Sun"]["minutes_from_sunset"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


SMOOTH_FRAMES = 3          # brightness is smoothed over this many fused frames either side
SMOOTH_MAX_GAIN = 1.25     # and never moved by more than 25%
RATIO_SCALE = 16           # the tone map is worked out at 1/16 size
RATIO_OFFSET = 8.0         # keeps dark areas from blowing the ratio up


def ratio_map(production, fused):
    """How the fusion changed a production frame: a smooth per-pixel, per-channel gain at 1/16 size."""
    h, w = production.shape[:2]
    size = (max(1, w // RATIO_SCALE), max(1, h // RATIO_SCALE))
    p = cv2.resize(production, size, interpolation=cv2.INTER_AREA).astype(np.float32) + RATIO_OFFSET
    f = cv2.resize(fused, size, interpolation=cv2.INTER_AREA).astype(np.float32) + RATIO_OFFSET
    return cv2.GaussianBlur(f / p, (0, 0), 2)


def apply_ratio(production, ratio):
    """Give another production frame the same change. The picture stays its own (clouds and sun
    where they really were that minute); only the exposure and colour follow the fusion."""
    h, w = production.shape[:2]
    gain = cv2.resize(ratio, (w, h), interpolation=cv2.INTER_LINEAR)
    out = (production.astype(np.float32) + RATIO_OFFSET) * gain - RATIO_OFFSET
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def fuse_run(run_dir, frames_dir, out_dir, bright_name="ev+0-daylight", dark_name="ev-2-daylight", force=False,
             smooth=SMOOTH_FRAMES, brackets=None, fade_out=(FADE_OUT_START, FADE_OUT_END)):
    """Write the fused frames. Returns how many were written.

    The runner skips the first minute of every 5-minute slot, and sometimes loses a longer stretch,
    so some production frames have no bracket of their own. Such a frame keeps its own picture and
    takes the fusion's change in exposure and colour from the pairs either side (worked out as a
    smooth gain and interpolated in time, or held from the one side within FILL_MAX_MIN). Repeating
    or blending the neighbours' pictures instead froze the video, then jumped, at the sunset.

    brackets: (brights, darks) from production_bracket(), used instead of the experiment run.
    fade_out: minutes after sunset over which the merge fades back to the production frame (5 to
    12 by default, for the experiment's daylight-only bracket, whose sky turns brown after about
    +15). The production bracket switches to auto white balance at +10, so it can go later."""
    brights, darks = brackets if brackets else (list_run(run_dir, bright_name), list_run(run_dir, dark_name))
    if not brights or not darks:
        return 0
    first, last = brights[0][0], brights[-1][0]
    production = production_frames(frames_dir, first - timedelta(minutes=1), last + timedelta(minutes=1))
    prod_path = {t: p for t, p in production}
    pairs = {}      # production frame time -> (bright path, dark path)
    for t, bright_path in brights:
        dark, prod = nearest(darks, t, PAIR_SECONDS), nearest(production, t, MATCH_SECONDS)
        if dark and prod:
            pairs[prod[0]] = (bright_path, dark[1])
    paired = sorted(pairs)
    cache, ratios = {}, {}

    def fused_for(t):
        if t not in cache:
            if len(cache) >= 2:
                cache.pop(next(iter(cache)))
            bright, dark = (cv2.imread(p) for p in pairs[t])
            cache[t] = fuse(bright, dark) if bright is not None and dark is not None else None
        return cache[t]

    def ratio_for(t):
        if t not in ratios:
            fused, image = fused_for(t), cv2.imread(prod_path[t])
            ok = fused is not None and image is not None and image.shape == fused.shape
            ratios[t] = ratio_map(image, fused) if ok else None
        return ratios[t]

    def fill_ratio(t):
        before = max((p for p in paired if p < t), default=None)
        after = min((p for p in paired if p > t), default=None)
        gb = (t - before).total_seconds() / 60 if before else None
        ga = (after - t).total_seconds() / 60 if after else None
        near_b = gb is not None and gb <= FILL_MAX_MIN
        near_a = ga is not None and ga <= FILL_MAX_MIN
        if near_b and near_a:
            rb, ra = ratio_for(before), ratio_for(after)
            if rb is not None and ra is not None and rb.shape == ra.shape:
                share = gb / (gb + ga)
                return rb * (1.0 - share) + ra * share
        if near_b or near_a:
            return ratio_for(before if near_b and (not near_a or gb <= ga) else after)
        return None

    os.makedirs(out_dir, exist_ok=True)
    made, written = 0, []
    for t, path in production:
        m = minutes_from_sunset(path)
        if m is None or not first - timedelta(seconds=MATCH_SECONDS) <= t <= last + timedelta(seconds=MATCH_SECONDS):
            continue
        weight = fuse_weight(m, (t - first).total_seconds() / 60.0, fade_out)
        out = os.path.join(out_dir, os.path.basename(path))
        if weight <= 0 or (os.path.exists(out) and not force):
            continue
        image = cv2.imread(path)
        if image is None:
            continue
        if t in pairs:
            fused = fused_for(t)
        else:
            gain = fill_ratio(t)
            fused = apply_ratio(image, gain) if gain is not None else None
        if fused is None or image.shape != fused.shape:
            continue
        cv2.imwrite(out, blend(image, fused, weight), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if weight >= 0.999:   # the fade-in and fade-out are meant to change, so they are left out
            written.append(out)
        made += 1
    if smooth:
        smooth_brightness(written, smooth)
    return made


def smooth_brightness(paths, radius):
    """Steady the exposure from frame to frame. The bracket's auto exposure hunts by several levels a
    minute, which shows as jitter; each frame is scaled towards the average of the frames around it,
    by at most SMOOTH_MAX_GAIN. A steady change over time is left alone, and so is the shape of the picture."""
    if len(paths) < 3:
        return
    means = []
    for path in paths:
        image = cv2.imread(path)
        means.append(float(image.mean()) if image is not None else 0.0)
    for i, path in enumerate(paths):
        reach = min(radius, i, len(paths) - 1 - i)   # a window that is the same either side, so the ends don't lean
        around = [m for m in means[i - reach:i + reach + 1] if m > 0]
        if means[i] <= 0 or not around:
            continue
        gain = max(1.0 / SMOOTH_MAX_GAIN, min(SMOOTH_MAX_GAIN, (sum(around) / len(around)) / means[i]))
        if abs(gain - 1.0) < 0.005:
            continue
        image = cv2.imread(path)
        if image is not None:
            cv2.imwrite(path, np.clip(image.astype(np.float32) * gain + 0.5, 0, 255).astype(np.uint8),
                        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])


BLEND_WEIGHTS = (1, 2, 1)  # each minute with the minutes either side
BLEND_MARGIN_MIN = 15      # blended this far either side of the bracket, which covers the dense frames
BLEND_SPACING_S = 20       # a neighbour must be one minute away, give or take this
BLEND_MARK = ".blended"    # what the blend wrote, so it is never blended twice
BLEND_SAVED = ".preblend"  # the fused frames as they were before the blend, read from here and put back by undo


def write_mark(mark, record):
    """Write the blend's mark in one step (a temporary file, then a rename), so it is never half written."""
    tmp = mark + ".tmp"
    with open(tmp, "w") as f:
        json.dump(record, f)
    os.replace(tmp, mark)


def read_mark(mark):
    try:
        with open(mark) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def blend_minutes(frames_dir, out_dir, start, end, weights=BLEND_WEIGHTS):
    """Blend each frame between start and end with the frames either side, 1:2:1. Returns how many
    were written.

    Thin cloud crossing the glow changes the sky by 10 to 19 a minute (Nov 12, both cameras, each
    with its own exposure), which reads as flicker. The blend cut the Nov 12 video's worst change
    from 17 to 11. Still things stay sharp; the sun and cloud edges soften a little.

    The picture for each minute is the fused one in out_dir if there is one, otherwise the production
    frame, and the result goes to out_dir under the production name. Only frames one minute apart
    are blended, so the 5-minute frames outside the dense window are left alone. Done once per
    out_dir: undo_blend() clears it to do it again.

    A run cut off part way can't blend anything twice. Before anything is overwritten, the fused
    frames in the window are copied to out_dir/.preblend and read from there, and the mark (saying
    "not complete") names each frame just before it is written. Run again, it undoes the part-done
    blend (putting the fused frames back) and starts over."""
    mark = os.path.join(out_dir, BLEND_MARK)
    if os.path.exists(mark):
        record = read_mark(mark)
        if record is not None and record.get("complete", True):   # marks from before 2026-11-15 were only written when done
            return 0
        undo_blend(out_dir)
        if os.path.exists(mark):   # an unreadable mark: what was blended is unknown, so leave it
            return 0
    frames = production_frames(frames_dir, start, end)
    saved_dir = os.path.join(out_dir, BLEND_SAVED)
    os.makedirs(out_dir, exist_ok=True)
    shutil.rmtree(saved_dir, ignore_errors=True)   # with no mark, nothing in out_dir was overwritten yet
    os.makedirs(saved_dir)
    sources, saved = [], []
    for t, path in frames:
        name = os.path.basename(path)
        fused = os.path.join(out_dir, name)
        if os.path.exists(fused):
            shutil.copy2(fused, os.path.join(saved_dir, name))
            saved.append(name)
            sources.append((t, os.path.join(saved_dir, name)))
        else:
            sources.append((t, path))
    record = {"weights": list(weights), "complete": False, "saved": saved, "blended": []}
    write_mark(mark, record)
    reach = len(weights) // 2
    originals = {}   # the sources are never overwritten; this only saves reading each one three times

    def picture(i):
        if i not in originals:
            originals[i] = cv2.imread(sources[i][1])
        return originals[i]

    for i, (t, _) in enumerate(sources):
        around = range(i - reach, i + reach + 1)
        if all(0 <= j < len(sources) for j in around) and all(
                abs((sources[j][0] - t).total_seconds() - 60 * (j - i)) <= BLEND_SPACING_S for j in around):
            images = [picture(j) for j in around]
            if all(img is not None and img.shape == images[reach].shape for img in images):
                mixed = sum(img.astype(np.float32) * w for img, w in zip(images, weights)) / float(sum(weights))
                name = os.path.basename(frames[i][1])
                record["blended"].append(name)
                write_mark(mark, record)   # named before it is written, so undo always knows about it
                cv2.imwrite(os.path.join(out_dir, name), np.clip(mixed + 0.5, 0, 255).astype(np.uint8),
                            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        originals.pop(i - reach, None)
    record["complete"] = True
    write_mark(mark, record)
    return len(record["blended"])


def undo_blend(out_dir):
    """Undo the blend, finished or cut off part way: put back the fused frames it blended (from
    .preblend), remove the frames it made from production frames, then its mark. Safe to repeat if
    it is itself cut off. Marks from before 2026-11-15 saved no fused frames, so those are removed;
    run fuse_run again (with force) before blending again."""
    mark = os.path.join(out_dir, BLEND_MARK)
    saved_dir = os.path.join(out_dir, BLEND_SAVED)
    record = read_mark(mark)
    if record is None:
        if not os.path.exists(mark):
            shutil.rmtree(saved_dir, ignore_errors=True)   # left by a blend cut off before its mark
        return
    saved = set(record.get("saved", []))
    for name in saved:
        copy = os.path.join(saved_dir, name)
        if os.path.exists(copy):   # gone if an earlier undo already put it back
            os.replace(copy, os.path.join(out_dir, name))
    for name in record.get("blended", []):
        if name not in saved:
            try:
                os.remove(os.path.join(out_dir, name))
            except OSError:
                pass
    shutil.rmtree(saved_dir, ignore_errors=True)
    os.remove(mark)


def blend_run(run_dir, frames_dir, out_dir, bright_name="ev+0-daylight", weights=BLEND_WEIGHTS, brights=None):
    """blend_minutes() over the bracket (the experiment run's, or `brights` from production_bracket())
    and BLEND_MARGIN_MIN either side."""
    brights = brights if brights is not None else list_run(run_dir, bright_name)
    if not brights:
        return 0
    margin = timedelta(minutes=BLEND_MARGIN_MIN)
    return blend_minutes(frames_dir, out_dir, brights[0][0] - margin, brights[-1][0] + margin, weights)


GAMMA = 2.2                # JPEG to roughly linear light, for re-colouring
DUSK_MARK = ".dusk"
DEFLICKER_MARK = ".deflickered"


def _checked_mark(mark, settings):
    """True if this step already ran with these settings; ValueError if with others (use --redo)."""
    if not os.path.exists(mark):
        return False
    done = read_mark(mark)
    if done is not None and done.get("settings") == settings and done.get("complete"):
        return True
    raise ValueError("%s was made with other settings %s, or cut off: run again with --redo"
                     % (os.path.basename(mark), None if done is None else done.get("settings")))


def _picture(out_dir, path):
    """The fused (or already processed) picture for a production frame if there is one, else the frame."""
    own = os.path.join(out_dir, os.path.basename(path))
    return cv2.imread(own if os.path.exists(own) else path)


def regain(image, from_gains, to_gains, weight=1.0):
    """A BGR picture re-rendered as if taken with colour gains to_gains (red, blue) instead of
    from_gains, `weight` of the way (0 none, 1 all), in roughly linear light. Approximate: the
    camera's colour matrix and tone curve come after the gains, and clipped areas stay clipped."""
    lin = (image.astype(np.float32) / 255.0) ** GAMMA
    lin[..., 2] *= (to_gains[0] / from_gains[0]) ** weight
    lin[..., 0] *= (to_gains[1] / from_gains[1]) ** weight
    return np.clip(np.clip(lin, 0.0, 1.0) ** (1.0 / GAMMA) * 255.0 + 0.5, 0, 255).astype(np.uint8)


def frame_gains(jpg_path):
    try:
        with open(os.path.splitext(jpg_path)[0] + ".json") as f:
            gains = json.load(f)["ColourGains"]
        r, b = float(gains[0]), float(gains[1])
        return (r, b) if r > 0 and b > 0 else None
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None


def dusk_colour(frames_dir, out_dir, start, end, gains, ramp=(5.0, 15.0)):
    """Re-colour the frames after sunset as if shot with fixed colour gains (red, blue), for example
    the camera's NIGHT_AWB. Auto white balance turns the CM4's dusk sky teal (Nov 12: red x3.2, blue
    x1.5 against 2.20/2.80 at night), and the merge's daylight balance hands over to it within a few
    minutes. From ramp[0] to ramp[1] minutes after sunset (Sun.minutes_from_sunset in the frame's
    JSON) it goes from the frame's own gains to `gains`, then stays there. Each frame's own gains
    come from its JSON (ColourGains); one without them is left alone. The picture used is the fused
    one in out_dir if there is one. Writes to out_dir; returns how many. Done once per out_dir."""
    mark = os.path.join(out_dir, DUSK_MARK)
    settings = {"gains": list(gains), "ramp": list(ramp)}
    if _checked_mark(mark, settings):
        return 0
    os.makedirs(out_dir, exist_ok=True)
    record = {"settings": settings, "complete": False, "written": []}
    write_mark(mark, record)
    for t, path in production_frames(frames_dir, start, end):
        minutes = minutes_from_sunset(path)
        own = frame_gains(path)
        if minutes is None or own is None or minutes < ramp[0]:
            continue
        weight = clamp((minutes - ramp[0]) / max(ramp[1] - ramp[0], 1e-6))
        image = _picture(out_dir, path)
        if image is None:
            continue
        name = os.path.basename(path)
        record["written"].append(name)
        write_mark(mark, record)
        cv2.imwrite(os.path.join(out_dir, name), regain(image, own, gains, weight), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    record["complete"] = True
    write_mark(mark, record)
    return len(record["written"])


def deflicker_minutes(frames_dir, out_dir, start, end, radius, max_gain=SMOOTH_MAX_GAIN):
    """Steady the brightness of 1-a-minute frames, area by area: each area of a frame is pulled
    towards the same area's mean over the `radius` minutes either side (a window the same size each
    side, so a steady change is left alone), by at most max_gain, through a smooth gain map at
    1/RATIO_SCALE size, so detail and moving cloud stay sharp. For the glow's swell of Nov 12,
    00:13-00:19 UTC: the sky level went 147-164-146 while the city stayed put. Frames not one minute
    from their neighbours (the 5-minute frames) are left alone. Uses the fused picture where there is
    one; writes to out_dir."""
    mark = os.path.join(out_dir, DEFLICKER_MARK)
    settings = {"radius": radius, "max_gain": max_gain, "local": True}
    if _checked_mark(mark, settings):
        return 0
    os.makedirs(out_dir, exist_ok=True)
    frames = production_frames(frames_dir, start, end)
    # contiguous runs of frames one minute apart
    runs, current = [], []
    for t, path in frames:
        if current and abs((t - current[-1][0]).total_seconds() - 60) > BLEND_SPACING_S:
            runs.append(current)
            current = []
        current.append((t, path))
    runs.append(current)
    # Worked out locally, at 1/RATIO_SCALE size and blurred, like the merge's tone map: the glow
    # around the sun can swell while the city below stays put, and a gain for the whole frame then
    # hardly moves. Each area is pulled towards the same area in the minutes around it.
    plan = []
    for run in runs:
        if len(run) < 3:
            continue
        small = []
        for _, path in run:
            image = _picture(out_dir, path)
            if image is None:
                small.append(None)
                continue
            h, w = image.shape[:2]
            size = (max(1, w // RATIO_SCALE), max(1, h // RATIO_SCALE))
            small.append(cv2.resize(image, size, interpolation=cv2.INTER_AREA).astype(np.float32) + RATIO_OFFSET)
        for i, (_, path) in enumerate(run):
            reach = min(radius, i, len(run) - 1 - i)
            around = [s for s in small[i - reach:i + reach + 1] if s is not None and s.shape == getattr(small[i], "shape", None)]
            if small[i] is None or reach == 0 or len(around) < 2:
                continue
            ratio = cv2.GaussianBlur(sum(around) / len(around) / small[i], (0, 0), 2)
            ratio = np.clip(ratio, 1.0 / max_gain, max_gain)
            if float(np.abs(ratio - 1.0).max()) >= 0.005:
                plan.append((path, ratio))
    record = {"settings": settings, "complete": False, "written": []}
    write_mark(mark, record)
    for path, ratio in plan:
        image = _picture(out_dir, path)
        if image is None:
            continue
        name = os.path.basename(path)
        record["written"].append(name)
        write_mark(mark, record)
        cv2.imwrite(os.path.join(out_dir, name), apply_ratio(image, ratio), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    record["complete"] = True
    write_mark(mark, record)
    return len(record["written"])


def clear_marks(out_dir):
    """Forget the dusk and deflicker steps (for a redo, which also removes the frames they wrote)."""
    for name in (DUSK_MARK, DEFLICKER_MARK):
        try:
            os.remove(os.path.join(out_dir, name))
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="experiment folder, e.g. .../project_sunshine_experiments/cm4-sunset-1")
    ap.add_argument("--frames", required=True, help="the camera's frame folder, holding YYYY/MM/DD/")
    ap.add_argument("--out", required=True, help="where the fused frames go")
    ap.add_argument("--bright", default="ev+0-daylight")
    ap.add_argument("--dark", default="ev-2-daylight")
    ap.add_argument("--force", action="store_true", help="redo frames that already exist")
    ap.add_argument("--no-blend", action="store_true", help="skip the 1:2:1 blend of each minute with its neighbours")
    args = ap.parse_args()
    if args.force:
        undo_blend(args.out)
    made = fuse_run(args.run, args.frames, args.out, args.bright, args.dark, args.force)
    print("%d fused frames in %s" % (made, args.out))
    if not args.no_blend:
        print("%d frames blended with their neighbours" % blend_run(args.run, args.frames, args.out, args.bright))
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
