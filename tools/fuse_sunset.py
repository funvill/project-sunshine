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


def fuse_weight(minutes_from_sunset, minutes_into_run):
    """How much of the fused frame to use: 1 is all of it, 0 is the production frame."""
    fade_in = clamp(minutes_into_run / FADE_IN_MIN)
    fade_out = clamp((FADE_OUT_END - minutes_from_sunset) / (FADE_OUT_END - FADE_OUT_START))
    return min(fade_in, fade_out)


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
             smooth=SMOOTH_FRAMES):
    """Write the fused frames. Returns how many were written.

    The runner skips the first minute of every 5-minute slot, and sometimes loses a longer stretch,
    so some production frames have no bracket of their own. Such a frame keeps its own picture and
    takes the fusion's change in exposure and colour from the pairs either side (worked out as a
    smooth gain and interpolated in time, or held from the one side within FILL_MAX_MIN). Repeating
    or blending the neighbours' pictures instead froze the video, then jumped, at the sunset."""
    brights, darks = list_run(run_dir, bright_name), list_run(run_dir, dark_name)
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
        weight = fuse_weight(m, (t - first).total_seconds() / 60.0)
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


def blend_minutes(frames_dir, out_dir, start, end, weights=BLEND_WEIGHTS):
    """Blend each frame between start and end with the frames either side, 1:2:1. Returns how many
    were written.

    Thin cloud crossing the glow changes the sky by 10 to 19 a minute (Nov 12, both cameras, each
    with its own exposure), which reads as flicker. The blend cut the Nov 12 video's worst change
    from 17 to 11. Still things stay sharp; the sun and cloud edges soften a little.

    The picture for each minute is the fused one in out_dir if there is one, otherwise the production
    frame, and the result goes to out_dir under the production name. Only frames one minute apart
    are blended, so the 5-minute frames outside the dense window are left alone. Done once per
    out_dir: undo_blend() clears it to do it again."""
    mark = os.path.join(out_dir, BLEND_MARK)
    if os.path.exists(mark):
        return 0
    frames = production_frames(frames_dir, start, end)
    sources = []
    for t, path in frames:
        fused = os.path.join(out_dir, os.path.basename(path))
        sources.append((t, fused if os.path.exists(fused) else path))
    reach = len(weights) // 2
    originals = {}   # read before anything is overwritten, so a neighbour is never already blended

    def picture(i):
        if i not in originals:
            originals[i] = cv2.imread(sources[i][1])
        return originals[i]

    os.makedirs(out_dir, exist_ok=True)
    written = []
    for i, (t, _) in enumerate(sources):
        around = range(i - reach, i + reach + 1)
        if all(0 <= j < len(sources) for j in around) and all(
                abs((sources[j][0] - t).total_seconds() - 60 * (j - i)) <= BLEND_SPACING_S for j in around):
            images = [picture(j) for j in around]
            if all(img is not None and img.shape == images[reach].shape for img in images):
                mixed = sum(img.astype(np.float32) * w for img, w in zip(images, weights)) / float(sum(weights))
                name = os.path.basename(frames[i][1])
                cv2.imwrite(os.path.join(out_dir, name), np.clip(mixed + 0.5, 0, 255).astype(np.uint8),
                            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                written.append(name)
        originals.pop(i - reach, None)
    with open(mark, "w") as f:
        json.dump({"weights": list(weights), "blended": written}, f)
    return len(written)


def undo_blend(out_dir):
    """Remove the frames the blend wrote, and its mark. Fused frames it blended are removed too,
    so run fuse_run again (with force) before blending again."""
    mark = os.path.join(out_dir, BLEND_MARK)
    try:
        with open(mark) as f:
            names = json.load(f).get("blended", [])
    except (OSError, ValueError):
        return
    for name in names:
        try:
            os.remove(os.path.join(out_dir, name))
        except OSError:
            pass
    os.remove(mark)


def blend_run(run_dir, frames_dir, out_dir, bright_name="ev+0-daylight", weights=BLEND_WEIGHTS):
    """blend_minutes() over the experiment run's bracket and BLEND_MARGIN_MIN either side."""
    brights = list_run(run_dir, bright_name)
    if not brights:
        return 0
    margin = timedelta(minutes=BLEND_MARGIN_MIN)
    return blend_minutes(frames_dir, out_dir, brights[0][0] - margin, brights[-1][0] + margin, weights)


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
