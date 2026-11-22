#!/usr/bin/env python3
"""Turn each day's frames into a vertical video, from dark to dark. Runs on a PC,
from tools/build_video.py (and tools/build_reports.py for the sky score).

Python standard library plus ffmpeg. It only reads frames and writes to DAILY_DIR, so
the Pi and the frame layout don't change. It posts nothing: publishing is a later step.

Each video ends on the first dark frame after sunset, and the next starts on the frame
after that, so together they show every frame once. Night is a larger share of a winter
video and day of a summer one.

A run does nothing until a frame shows the sky has gone dark after sunset, and a day is
never done twice, because `DAILY_DIR/<local date>.json` is written last and marks that
day as finished.

Settings come from the environment; see nas/README.md.
"""
import collections
import dataclasses
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import date, datetime, timedelta, timezone

# Change SCRIPT_VERSION with every change to what this script makes; it goes in each record.
SCRIPT_VERSION = "2026-11-18.1"   # YYYY-MM-DD.N; version_key compares them
RECORD_SCHEMA_VERSION = 2       # 1: records from before 2026-11-15, which have no schema_version

UTC = timezone.utc
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FRAME_NAME = re.compile(r"^[A-Za-z0-9-]+_(\d{8}T\d{6}Z)\.jpg$")

DARK_ELEVATION_DEG = -9.0      # measured: on 2026-11-04 the camera's Lux stopped falling near here
WINDOW = timedelta(hours=24)   # a first video, with none before it to continue from
AZIMUTH_RATE_DEG_PER_MIN = 0.19   # sun's azimuth rate at sunset here; varies 0.188-0.191 over a year
AZIMUTH_MAX_MINUTES = 60          # frames further from sunset than this say little about it
AZIMUTH_STEP_LIMIT_DEG = 1.0      # the true seasonal change is at most about 0.61 deg/day
EXPECTED_FRAMES = 288            # regular frames in 24 hours: capture is every 5 minutes
REGULAR_SLOT_MIN = 5             # frames with no Capture block are regular when their minute is a slot
MAX_GAP_MIN = 60                 # a longer stretch with no frame skips the day (MAX_GAP_MIN)
MAX_SUNSET_GAP_MIN = 20          # the same from an hour before sunset to the end (MAX_SUNSET_GAP_MIN)
GAP_SUNSET_BEFORE_MIN = 60       # where the tighter limit starts: the 1-minute frames start here
FRAME_SECONDS = 1.0 / 12.0       # every frame, sunset included: the 1-minute frames slow sunset down
OUTPUT_FPS = 24
VIDEO_FRAME_SLACK = 2            # frames the encoded count may differ from the expected one
DROPPED_LIST_MAX = 50            # names of left-out frames kept in the record
LOCK_STALE_SECONDS = 6 * 3600     # longer than any real run; a crash must not stop the job for good
DEFAULT_TAGS = "#sunset #timelapse #raspberrypi"

# Sky score: how much of the sky is lit warm, at its best from 35 min before to 25 min after sunset.
# Provisional: tuned on the pilot so far (wide camera, Nov 4-12: grey evenings 0.5-1.3% warm, the
# two good ones, Nov 8 and Nov 12, 6.9% and 6.7%). The scale and the bands are estimates to tune
# with more good and grey sunsets. A camera needs its own scale: on the same Nov 12 sunset the
# CM4 camera read 11.9% to the wide camera's 6.7%, so crop.json can set "sky_full_warm".
SKY_BEFORE_MIN, SKY_AFTER_MIN = 35, 25
SKY_ROWS = 0.40                 # the top share of the frame is sky, above the skyline (crop.json "sky_rows")
SKY_FULL_SCORE_WARM = 0.10      # this share of warm sky scores 100 (crop.json "sky_full_warm")
SKY_WARM_RATIO = 1.2            # red over blue
SKY_WARM_MIN_BRIGHT = 77        # of 255: a dim brown is not a sunset
SKY_SIZE = (160, 120)           # frames are shrunk to this for the count
# The score is the mean of the best SKY_TOP_FRAMES frames, so one odd frame can't set it (it was the
# best frame alone until 2026-11-15; that is still in the record as score_best_frame). Under
# SKY_MIN_FRAMES readable frames there is no score (crop.json "sky_min_frames").
SKY_TOP_FRAMES = 5
SKY_MIN_FRAMES = 6

# Text drawn on the video, in 1080x1920 pixels, 140 px above the bottom edge. Instagram's
# caption may cover it in the Reels feed; that was accepted (2026-11-07).
OVERLAY_TITLE = "Project Sunshine"
OVERLAY_HANDLE = "@funvill"
DEFAULT_LOCATION = "Burnaby, BC, Canada"   # small text under the date; OVERLAY_LOCATION="" turns it off
DEFAULT_FONT_FILE = "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"   # Alpine's font-dejavu
TEXT_X = 60
TITLE_Y, TITLE_SIZE = 1604, 46
TIME_Y, TIME_SIZE = 1670, 64
LOC_Y, LOC_SIZE = 1746, 34      # the last line still ends 140 px above the bottom edge
# The day's sky score, right-aligned on the location line (Steven, 2026-11-18). OVERLAY_SKY=0 drops it.
SKY_TEXT = "Sky score %d"
SKY_TEXT_RIGHT = 60             # px from the right edge, the same margin as TEXT_X on the left
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
BLUR_SIGMA = 5                  # pixels of the full frame; windows go, the outline and decks stay
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# source: the original, if jpg is a fused copy. capture: the frame's Capture block, if it has one.
Frame = collections.namedtuple("Frame", "time jpg sun source capture", defaults=(None, None))

# Settings that can sit inside a calibration entry, since they belong to one camera position.
# The top level of crop.json is the fallback for each, so older files keep working.
DAY_SETTINGS = {"setup_id": None, "offset_px": 0, "mask": [], "view": None, "blur": None,
                "blur_sigma": BLUR_SIGMA, "sky_rows": SKY_ROWS, "sky_full_warm": SKY_FULL_SCORE_WARM,
                "sky_min_frames": SKY_MIN_FRAMES}


class EncodeError(Exception):
    """ffmpeg or ffprobe failed. The day gets a failed record, and runs within LOOKBACK_DAYS retry it."""


@dataclasses.dataclass
class Config:
    frames_dir: str
    daily_dir: str
    crop_file: str
    tz: object
    start_date: date
    crop_center_x: object = None
    tags: str = DEFAULT_TAGS
    expected_frames: int = EXPECTED_FRAMES
    min_fraction: float = 0.7
    lookback_days: int = 2
    font_file: str = DEFAULT_FONT_FILE
    start_local: object = None      # "HH:MM" local: start each video then, not after the last one
    location: str = DEFAULT_LOCATION
    overlay_sky: bool = True        # the day's sky score on the video, right of the location line
    fused_dir: object = None        # frames here replace the same-named ones (see tools/fuse_sunset.py)
    max_gap_min: float = MAX_GAP_MIN
    max_sunset_gap_min: float = MAX_SUNSET_GAP_MIN
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    # Redoing finished days, off unless asked for.
    redo_older_than: object = None      # a SCRIPT_VERSION: redo records made by an older one
    redo_from: object = None            # local dates: redo within these instead of LOOKBACK_DAYS
    redo_to: object = None


def log(message):
    print("%s %s" % (datetime.now(UTC).strftime(TIME_FORMAT), message), flush=True)


def parse_utc(text):
    try:
        return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def parse_frame_time(name):
    """UTC time from a normal frame's file name. None for anything else, including _night."""
    match = FRAME_NAME.match(name)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def read_frame_json(jpg_path):
    """(Sun block, Capture block) from the frame's JSON, each None if missing or unreadable."""
    try:
        with open(os.path.splitext(jpg_path)[0] + ".json") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    sun, capture = data.get("Sun"), data.get("Capture")
    return (sun if isinstance(sun, dict) else None), (capture if isinstance(capture, dict) else None)


def read_sun(jpg_path):
    return read_frame_json(jpg_path)[0]


def jpeg_ok(path):
    """True if the file starts and ends like a whole JPEG (FFD8 ... FFD9). A zero-byte, missing or
    cut-off file makes ffmpeg stop reading the list there, so it is left out instead."""
    try:
        with open(path, "rb") as f:
            head = f.read(2)
            f.seek(0, os.SEEK_END)
            if f.tell() < 4:
                return False
            f.seek(-2, os.SEEK_END)
            tail = f.read(2)
    except OSError:
        return False
    return head == b"\xff\xd8" and tail == b"\xff\xd9"


def is_regular(frame):
    """A 5-minute frame, not an extra 1-a-minute one. From Capture.schedule when the frame has it;
    older frames (before 2026-11-04) have no Capture block, so their minute decides."""
    schedule = (frame.capture or {}).get("schedule")
    if schedule:
        return schedule != "dense"
    return frame.time.minute % REGULAR_SLOT_MIN == 0


def check_frames(frames):
    """(frames that can be encoded, names left out). A bad fused copy falls back to its original."""
    good, dropped = [], []
    for frame in frames:
        if jpeg_ok(frame.jpg):
            good.append(frame)
        elif frame.source and jpeg_ok(frame.source):
            good.append(frame._replace(jpg=frame.source, source=None))
        else:
            dropped.append(os.path.basename(frame.source or frame.jpg))
    return good, dropped


def frame_gaps(times, sunset, end):
    """The longest time between two frames in `times` (sorted), and the longest that reaches into
    the stretch from GAP_SUNSET_BEFORE_MIN before sunset to `end`. Minutes. A video that starts
    late has no jump in time, so frames missing before the first one are left to the frame count."""
    sunset_from = sunset - timedelta(minutes=GAP_SUNSET_BEFORE_MIN)
    largest, at, largest_sunset = 0.0, None, 0.0
    previous = None
    for t in times:
        if previous is None:
            previous = t
            continue
        gap = (t - previous).total_seconds() / 60.0
        if gap > largest:
            largest, at = gap, previous
        if t > sunset_from and previous < end and gap > largest_sunset:
            largest_sunset = gap
        previous = t
    return {"largest_gap_min": round(largest, 1),
            "largest_gap_at_utc": at.strftime(TIME_FORMAT) if at else None,
            "largest_sunset_gap_min": round(largest_sunset, 1)}


def list_frames(frames_dir, start, end):
    """Normal frames with start <= time <= end, oldest first, from <dir>/YYYY/MM/DD."""
    frames = []
    day = start.date()
    while day <= end.date():
        folder = os.path.join(frames_dir, "%04d" % day.year, "%02d" % day.month, "%02d" % day.day)
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        for name in names:
            t = parse_frame_time(name)
            if t is not None and start <= t <= end:
                path = os.path.join(folder, name)
                sun, capture = read_frame_json(path)
                frames.append(Frame(t, path, sun, None, capture))
        day += timedelta(days=1)
    return sorted(frames, key=lambda f: f.time)


def use_fused(frames, fused_dir):
    """Swap in the picture from `fused_dir` for any frame with a file of the same name there.
    The frame's time and Sun data are the original's."""
    if not fused_dir:
        return frames
    swapped = []
    for frame in frames:
        path = os.path.join(fused_dir, os.path.basename(frame.jpg))
        swapped.append(frame._replace(jpg=path, source=frame.jpg) if os.path.exists(path) else frame)
    return swapped


def warm_fraction(rgb, width, rows, x0=0, x1=None):
    """Share of the top `rows` (0-1) of an rgb24 picture that is bright and warm: red over blue.
    Only columns x0 to x1 (default all) count."""
    height = len(rgb) // (3 * width)
    x1 = width if x1 is None else x1
    count = warm = 0
    for y in range(max(1, int(height * rows))):
        for i in range((y * width + x0) * 3, (y * width + x1) * 3, 3):
            r, b = rgb[i], rgb[i + 2]
            count += 1
            if max(r, rgb[i + 1], b) >= SKY_WARM_MIN_BRIGHT and r > SKY_WARM_RATIO * b:
                warm += 1
    return warm / count if count else 0.0


def crop_columns(crop, frame_w, width=SKY_SIZE[0]):
    """The posted crop's columns in a picture shrunk to `width`: [first, end)."""
    x0 = max(0, min(width - 1, int(math.floor(crop["x"] * width / frame_w))))
    x1 = max(x0 + 1, min(width, int(math.ceil((crop["x"] + crop["width"]) * width / frame_w))))
    return x0, x1


def sky_score_value(fraction, full=SKY_FULL_SCORE_WARM):
    return int(round(100 * min(1.0, fraction / full)))


def sky_label(score):
    return "colourful" if score >= 60 else "some colour" if score >= 20 else "grey"


def sky_pixels(cfg, path):
    width, height = SKY_SIZE
    out = subprocess.run([cfg.ffmpeg, "-loglevel", "error", "-i", path, "-vf", "scale=%d:%d:flags=area" % SKY_SIZE,
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    if len(out) != width * height * 3:
        raise ValueError("unexpected picture size")
    return out


def sky_frames_scored(cfg, window, sunset, rows, columns=None, read_pixels=sky_pixels):
    """[(full-width warm share, crop-columns warm share or None, name)] for the readable frames
    from SKY_BEFORE_MIN before to SKY_AFTER_MIN after sunset. Originals, not fused copies."""
    scored = []
    for frame in window:
        minutes = (frame.time - sunset).total_seconds() / 60.0
        if not -SKY_BEFORE_MIN <= minutes <= SKY_AFTER_MIN:
            continue
        path = frame.source or frame.jpg
        try:
            rgb = read_pixels(cfg, path)
        except (OSError, subprocess.CalledProcessError, ValueError):
            continue
        in_crop = warm_fraction(rgb, SKY_SIZE[0], rows, *columns) if columns else None
        scored.append((warm_fraction(rgb, SKY_SIZE[0], rows), in_crop, os.path.basename(path)))
    return scored


def top_mean(values, n=SKY_TOP_FRAMES):
    best = sorted(values, reverse=True)[:n]
    return sum(best) / len(best)


def sky_score(cfg, window, sunset, rows=SKY_ROWS, full=SKY_FULL_SCORE_WARM, crop=None, frame_w=None,
              min_frames=SKY_MIN_FRAMES, read_pixels=None):
    """The day's sky score, no AI: the mean warm-sky share of the best SKY_TOP_FRAMES frames in
    the sunset window, on the same scale as before. With a crop and the frame width, the same
    over the posted crop's columns goes in "crop". None under `min_frames` readable frames."""
    columns = crop_columns(crop, frame_w) if crop and frame_w else None
    scored = sky_frames_scored(cfg, window, sunset, rows, columns, read_pixels or sky_pixels)
    return sky_from_scored(scored, full, min_frames, columns)


def sky_from_scored(scored, full=SKY_FULL_SCORE_WARM, min_frames=SKY_MIN_FRAMES, columns=None):
    """The sky block from sky_frames_scored's list; None under `min_frames` frames."""
    if not scored or len(scored) < min_frames:
        return None
    best = max(scored, key=lambda s: s[0])
    mean = top_mean([s[0] for s in scored])
    score = sky_score_value(mean, full)
    sky = {"score": score, "out_of": 100, "label": sky_label(score),
           "warm_sky_percent": round(best[0] * 100, 2), "best_frame": best[2], "frames_scored": len(scored),
           "provisional": True, "method": "top%d_mean" % SKY_TOP_FRAMES, "top_frames": min(SKY_TOP_FRAMES, len(scored)),
           "warm_sky_percent_top_mean": round(mean * 100, 2), "score_best_frame": sky_score_value(best[0], full)}
    if columns:
        crop_mean = top_mean([s[1] for s in scored])
        crop_score = sky_score_value(crop_mean, full)
        sky["crop"] = {"score": crop_score, "label": sky_label(crop_score),
                       "warm_sky_percent_top_mean": round(crop_mean * 100, 2), "columns": list(columns)}
    return sky


def frame_sunset(frame):
    return parse_utc(frame.sun.get("nearest_sunset_utc")) if frame.sun else None


def dark_after_sunset(frame):
    if not frame.sun:
        return False
    minutes, elevation = frame.sun.get("minutes_from_sunset"), frame.sun.get("elevation_deg")
    return (minutes is not None and elevation is not None
            and minutes > 0 and elevation <= DARK_ELEVATION_DEG)


def due_sunsets(frames):
    """Sunsets, oldest first, that some frame shows the sky has gone dark after."""
    due = {frame_sunset(f) for f in frames if dark_after_sunset(f)}
    return sorted(due - {None})


def day_end(frames, sunset):
    """The time of the first dark frame after this sunset, which is the video's last."""
    for frame in frames:
        if frame_sunset(frame) == sunset and dark_after_sunset(frame):
            return frame.time
    return None


def select_window(frames, start, end):
    """Frames after start, up to and including end. Start is the last video's final frame."""
    return [f for f in frames if start < f.time <= end]


def nearest_frame(frames, sunset):
    return min(frames, key=lambda f: abs((f.time - sunset).total_seconds()))


def sunset_azimuth(frames, sunset):
    """(azimuth at sunset, how it was worked out), or (None, None).

    The nearest frame alone can be 1.4 deg out and jump 3 deg between days on a
    15-minute schedule, so interpolate between the frames either side when both exist.
    """
    points = []
    for frame in frames:
        if frame_sunset(frame) != sunset:
            continue
        minutes, az = frame.sun.get("minutes_from_sunset"), frame.sun.get("azimuth_deg")
        if minutes is not None and az is not None and abs(minutes) <= AZIMUTH_MAX_MINUTES:
            points.append((minutes, az))
    before = max((p for p in points if p[0] <= 0), default=None)
    after = min((p for p in points if p[0] > 0), default=None)
    if before and after:
        share = -before[0] / (after[0] - before[0])
        return before[1] + (after[1] - before[1]) * share, "interpolated"
    single = before or after
    if single:
        return single[1] - AZIMUTH_RATE_DEG_PER_MIN * single[0], "single_frame"
    return None, None


def azimuth_step_flagged(azimuth, previous):
    if azimuth is None or previous is None:
        return False
    return abs(azimuth - previous) > AZIMUTH_STEP_LIMIT_DEG


def calibration_entry(crop_config, day):
    """The calibrations entry in force on `day` (the last one started by then), or None."""
    in_force = None
    for entry in crop_config.get("calibrations", []):
        if date.fromisoformat(entry["start"]) <= day:
            in_force = entry
    return in_force


def day_settings(crop_config, day):
    """The DAY_SETTINGS for `day`: from the calibration entry in force, else the top level of
    crop.json, else the default. Blur boxes, the view and the sky scale belong to one camera
    position, so they go in the entry with its setup_id (issue #19)."""
    entry = calibration_entry(crop_config, day) or {}
    return {key: entry[key] if key in entry else crop_config.get(key, default)
            for key, default in DAY_SETTINGS.items()}


def active_calibration(crop_config, day):
    """The calibration in force on `day`: the average of its monthly fits up to that day.

    A new entry in the list means the camera physically moved, so fits are never averaged
    across entries. A fit with no values records a month with no clear day.
    """
    in_force = calibration_entry(crop_config, day)
    if in_force is None:
        return None
    fits = [f for f in in_force.get("fits", [])
            if "f_px" in f and "az0_deg" in f and date.fromisoformat(f["date"]) <= day]
    if not fits:
        return None
    return {"cx": in_force["cx"],
            "f_px": sum(f["f_px"] for f in fits) / len(fits),
            "az0_deg": sum(f["az0_deg"] for f in fits) / len(fits),
            "fits_used": len(fits)}


def crop_for_day(frame_w, frame_h, azimuth, calibration, fixed_center, offset_px=0, previous_center=None,
                 view=None):
    """Where the 9:16 window goes: one position for the whole video. At full height unless
    `view` ({"top", "height"} in full-frame pixels) asks for a tighter window, which is
    scaled up to the same 1080x1920."""
    height, top = frame_h, 0
    if view:
        height = max(2, min(frame_h, int(view["height"]) // 2 * 2))
        top = max(0, min(frame_h - height, int(view["top"])))
    width = int(height * 9 / 16) // 2 * 2
    sun_x = None
    if calibration is None:
        center, source = (frame_w // 2 if fixed_center is None else fixed_center), "fixed"
    elif azimuth is not None:
        tangent = math.tan(math.radians(azimuth - calibration["az0_deg"]))
        sun_x = int(round(calibration["cx"] + calibration["f_px"] * tangent))
        center, source = sun_x + offset_px, "azimuth"
    elif previous_center is not None:
        center, source = previous_center, "previous_day"
    else:
        center, source = (frame_w // 2 if fixed_center is None else fixed_center), "fixed"
    wanted = int(center) - width // 2
    x = max(0, min(frame_w - width, wanted))
    return {"x": x, "y": top, "width": width, "height": height, "center_x": x + width // 2,
            "source": source, "clamped": x != wanted, "sun_x": sun_x}


def local_date(sunset, tz):
    """The date a viewer would give this sunset. Its UTC date is always one day later here."""
    return sunset.astimezone(tz).date()


def local_start(day, text, tz):
    """The UTC time of `text` (HH:MM, local) on local date `day`. ValueError if it isn't a time."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text or "")
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise ValueError("%r is not a time like 07:30" % (text,))
    local = datetime(day.year, day.month, day.day, int(match.group(1)), int(match.group(2)), tzinfo=tz)
    return local.astimezone(UTC)


def compass_name(azimuth):
    return COMPASS[int(((azimuth % 360) + 11.25) // 22.5) % 16]


def view_label(azimuth):
    """Where the camera looks, as the video says it: 'WSW 243°'."""
    degrees = int(round(azimuth)) % 360
    return "%s %d\u00b0" % (compass_name(degrees), degrees)


def center_azimuth(crop, calibration, sunset_azimuth):
    """The bearing at the middle of the crop. With a calibration, the lens model says;
    without one the best guess is the sunset, which the crop is aimed at."""
    if calibration is not None:
        return calibration["az0_deg"] + math.degrees(
            math.atan((crop["center_x"] - calibration["cx"]) / calibration["f_px"]))
    return sunset_azimuth


def build_caption(sunset, tz, start_date, tags=DEFAULT_TAGS):
    local = sunset.astimezone(tz)
    when = "%d %s %d, %d:%02d %s" % (local.day, local.strftime("%B"), local.year,
                                     local.hour % 12 or 12, local.minute,
                                     "am" if local.hour < 12 else "pm")
    day_number = (local.date() - start_date).days + 1
    line = "Day %d, looking west." % day_number if day_number >= 1 else "Looking west."
    return "Sunset, %s\n%s\n\n%s" % (when, line, tags)


def concat_list(frames):
    """An ffmpeg concat list: 12 frames a second."""
    lines = []
    for frame in frames:
        path = frame.jpg.replace("\\", "/").replace("'", "'\\''")
        lines += ["file '%s'" % path, "duration %.6f" % FRAME_SECONDS]
    lines.append(lines[-2])   # concat ignores the last duration unless the file is repeated
    return "\n".join(lines) + "\n"


def overlay_time(t, tz):
    """The frame's local time as YYYY-MMM-DD HH:MM, in English whatever the locale."""
    local = t.astimezone(tz)
    return "%d-%s-%02d %02d:%02d" % (local.year, MONTHS[local.month - 1], local.day, local.hour, local.minute)


def filter_quote(text):
    """Quote a value for an ffmpeg filter option. Our text and font paths have no quotes."""
    return "'%s'" % text.replace("\\", "/").replace("'", "").replace(":", "\\:")


def drawtext(cfg, text, y, size, enable=None, right=None):
    """Text at TEXT_X from the left, or ending `right` px from the right edge."""
    x = "x=%d" % TEXT_X if right is None else "x=w-tw-%d" % right
    args = ["fontfile=" + filter_quote(cfg.font_file), "expansion=none", "text=" + filter_quote(text),
            x, "y=%d" % y, "fontsize=%d" % size, "fontcolor=white",
            "borderw=3", "bordercolor=black@0.6"]
    if enable:
        args.append("enable=" + filter_quote(enable))
    return "drawtext=" + ":".join(args)


def overlay_filters(cfg, frames, azimuth=None, sky_score=None):
    """The title line, the location (small, with the view direction), the day's sky score (small,
    right-aligned on the location line, the whole video) and one timestamp per frame, each shown
    only while its frame is. Frames reach these filters one each, at the times concat_list gives them."""
    chain = [drawtext(cfg, "%s   %s" % (OVERLAY_TITLE, OVERLAY_HANDLE), TITLE_Y, TITLE_SIZE)]
    if cfg.location:
        place = cfg.location if azimuth is None else "%s   %s" % (cfg.location, view_label(azimuth))
        chain.append(drawtext(cfg, place, LOC_Y, LOC_SIZE))
    if sky_score is not None and cfg.overlay_sky:
        chain.append(drawtext(cfg, SKY_TEXT % sky_score, LOC_Y, LOC_SIZE, right=SKY_TEXT_RIGHT))
    start = 0.0
    for i, frame in enumerate(frames):
        end = start + FRAME_SECONDS
        # Half a frame of slack each side; the last one also covers concat's repeated last file.
        enable = "gte(t,%.4f)" % (start - FRAME_SECONDS / 2)
        if i < len(frames) - 1:
            enable += "*lt(t,%.4f)" % (end - FRAME_SECONDS / 2)
        chain.append(drawtext(cfg, overlay_time(frame.time, cfg.tz), TIME_Y, TIME_SIZE, enable))
        start = end
    return chain


def blur_filters(crop):
    """Light blurs over the boxes in crop["blur"], in full-frame pixels, before the crop. Each
    box is cut out, blurred and put back, so the rest of the frame is untouched."""
    sigma = crop.get("blur_sigma", BLUR_SIGMA)
    parts = []
    for i, (x, y, w, h) in enumerate(crop.get("blur") or []):
        parts.append("split[a%d][b%d];[b%d]crop=%d:%d:%d:%d,gblur=sigma=%g[c%d];[a%d][c%d]overlay=%d:%d"
                     % (i, i, i, w, h, x, y, sigma, i, i, i, x, y))
    return parts


def mask_filters(mask):
    return ["drawbox=x=%d:y=%d:w=%d:h=%d:color=black:t=fill" % tuple(box) for box in mask]


def run_tool(args):
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        detail = getattr(e, "stderr", "") or str(e)
        raise EncodeError("%s failed: %s" % (args[0], detail.strip()[-500:]))


def encode_video(cfg, frames, crop, mask, out):
    """Encode to the Reel format in the issue. The mask goes on before the crop, in
    full-frame coordinates, so it stays on the same part of the scene as the crop moves.
    The filters go in a file: one timestamp per frame is too long for a command line."""
    work = os.path.dirname(out)
    fd, list_path = tempfile.mkstemp(prefix=".concat-", suffix=".txt", dir=work)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(concat_list(frames))
    fd, filter_path = tempfile.mkstemp(prefix=".filters-", suffix=".txt", dir=work)
    try:
        chain = mask_filters(mask) + blur_filters(crop) + [
            "crop=%d:%d:%d:%d" % (crop["width"], crop["height"], crop["x"], crop.get("y", 0)),
            # JPEGs are BT.601 full range; the video is BT.709 limited range, converted here and
            # tagged so Instagram's transcoder doesn't have to guess (issue #27).
            "scale=1080:1920:flags=lanczos:in_color_matrix=bt601:in_range=pc:out_color_matrix=bt709:out_range=tv",
            "format=yuv420p",
            "setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709"]
        chain += overlay_filters(cfg, frames, crop.get("center_azimuth_deg"), crop.get("sky_score")) + [
            "fps=%d" % OUTPUT_FPS,
            "format=yuv420p"]
        with os.fdopen(fd, "w", encoding="utf-8") as f:   # ffmpeg reads UTF-8: the degree sign
            f.write(",\n".join(chain))
        # -xerror: an unreadable file in the list is an error, not a quietly shorter video.
        run_tool([cfg.ffmpeg, "-y", "-loglevel", "error", "-xerror", "-f", "concat", "-safe", "0", "-i", list_path,
                  "-filter_script:v", filter_path, "-an", "-sn", "-map_metadata", "-1",
                  "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "25M", "-bufsize", "50M",
                  "-flags", "+cgop", "-g", "48", "-use_editlist", "0", "-movflags", "+faststart",
                  "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                  "-f", "mp4", out])
    finally:
        os.remove(list_path)
        os.remove(filter_path)
    check_frame_count(cfg, out, len(frames))


def expected_video_frames(count):
    """Frames in the video for `count` pictures: each is 1/12 s at 24 fps, plus concat's repeated last one."""
    return int(round(count * FRAME_SECONDS * OUTPUT_FPS)) + 1


def count_video_frames(cfg, path):
    out = run_tool([cfg.ffprobe, "-v", "error", "-count_packets", "-select_streams", "v:0",
                    "-show_entries", "stream=nb_read_packets", "-of", "json", path])
    try:
        return int(json.loads(out)["streams"][0]["nb_read_packets"])
    except (ValueError, KeyError, IndexError, TypeError):
        raise EncodeError("ffprobe gave no frame count for %s" % path)


def check_frame_count(cfg, path, count):
    """EncodeError unless the video has the frames `count` pictures should give."""
    got, want = count_video_frames(cfg, path), expected_video_frames(count)
    if abs(got - want) > VIDEO_FRAME_SLACK:
        raise EncodeError("the video has %d frames, expected %d for %d pictures" % (got, want, count))


def probe_frame_size(cfg, path):
    out = run_tool([cfg.ffprobe, "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height", "-of", "json", path])
    stream = json.loads(out)["streams"][0]
    return stream["width"], stream["height"]


def write_check_image(cfg, sunset_frame, crop, mask, out):
    """A small full frame with the crop and predicted sun drawn on it, to compare against
    the real sun. Any mask is applied here too, since this is the whole view."""
    frame_w = probe_frame_size(cfg, sunset_frame.jpg)[0]
    thick = max(2, frame_w // 200)
    chain = mask_filters(mask) + blur_filters(crop) + ["drawbox=x=%d:y=%d:w=%d:h=%d:color=lime:t=%d"
                                  % (crop["x"], crop.get("y", 0), crop["width"], crop["height"], thick)]
    if crop["sun_x"] is not None:
        chain.append("drawbox=x=%d:y=0:w=%d:h=ih:color=red:t=fill" % (crop["sun_x"], thick))
    chain.append("scale=1000:-2")
    run_tool([cfg.ffmpeg, "-y", "-loglevel", "error", "-i", sunset_frame.jpg, "-vf", ",".join(chain),
              "-map_metadata", "-1", "-frames:v", "1", "-q:v", "3", "-update", "1", "-f", "image2", out])


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def read_record(cfg, day):
    try:
        with open(os.path.join(cfg.daily_dir, day.isoformat() + ".json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_crop_config(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def file_sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def ffmpeg_version(cfg):
    """The first line of `ffmpeg -version`, or None if it can't be run."""
    try:
        out = subprocess.run([cfg.ffmpeg, "-version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out.splitlines()[0].strip() if out.strip() else None


def post_blockers(record):
    """Why this day must not be posted, as short codes. Empty means nothing here stops it (the
    sky score threshold is a separate decision, not made yet)."""
    blockers = []
    if record.get("status") != "encoded":
        blockers.append("not_encoded")
    if record.get("setup_mismatch"):
        blockers.append("setup_mismatch")
    if record.get("status") == "encoded" and not record.get("sky"):
        blockers.append("no_sky_score")
    return blockers


def finish_record(record):
    record["post_blockers"] = post_blockers(record)
    record["post_ok"] = not record["post_blockers"]
    return record


def version_key(text):
    """A SCRIPT_VERSION ("2026-11-15.2") as something to compare. Missing or unreadable is oldest."""
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.(\d+)", text or "")
    if not match:
        return ("", 0)
    return (match.group(1), int(match.group(2)))


def redo_reason(cfg, record):
    """Why a finished record should be made again under REDO_* settings, or None."""
    version = (record.get("provenance") or {}).get("script_version")
    if cfg.redo_older_than and version_key(version) < version_key(cfg.redo_older_than):
        return "made by script version %s, older than %s" % (version, cfg.redo_older_than)
    return None


def in_redo_range(cfg, day):
    return (cfg.redo_from is None or day >= cfg.redo_from) and (cfg.redo_to is None or day <= cfg.redo_to)


def process_sunset(cfg, sunset, frames, crop_config, encode, get_size, check_image, record=None, context=None,
                   carry=None):
    """Make one day's video and write its record. `record` is filled in as the work goes, so a
    failed record can say how far it got. `carry` is put into the record last (a redo's note and
    the posting state)."""
    record = {} if record is None else record
    context = context or {}
    carry = carry or {}
    day = local_date(sunset, cfg.tz)
    previous = read_record(cfg, day - timedelta(days=1)) or {}
    end = day_end(frames, sunset)
    if cfg.start_local:   # a fixed time of day: videos are not chained, so a frame can be in two
        start = local_start(day, cfg.start_local, cfg.tz)
    else:
        start = parse_utc(previous.get("end_utc")) or end - WINDOW
    listed = select_window(frames, start - timedelta(seconds=1) if cfg.start_local else start, end)
    window, dropped = check_frames(listed)
    regular = sum(1 for f in window if is_regular(f))
    expected = round((end - start) / (WINDOW / cfg.expected_frames))   # dusk drifts, so 288 give or take
    gaps = frame_gaps([f.time for f in window], sunset, end)
    settings = day_settings(crop_config, day)
    record.update({"schema_version": RECORD_SCHEMA_VERSION, "local_date": day.isoformat(),
                   "sunset_utc": sunset.strftime(TIME_FORMAT), "start_utc": start.strftime(TIME_FORMAT),
                   "end_utc": end.strftime(TIME_FORMAT), "frames": len(window), "expected_frames": expected,
                   "regular_frames": regular, "dense_frames": len(window) - regular,
                   "dropped_frames": len(dropped), "dropped": dropped[:DROPPED_LIST_MAX], "posted": False})
    record.update(gaps)
    record["provenance"] = {"script_version": SCRIPT_VERSION, "ffmpeg": context.get("ffmpeg"),
                            "crop_config_sha256": context.get("crop_config_sha256"),
                            "frames_by_kind": {"regular": regular, "dense": len(window) - regular,
                                               "fused": sum(1 for f in window if f.source),
                                               "dropped": len(dropped)}}
    json_path = os.path.join(cfg.daily_dir, day.isoformat() + ".json")
    if dropped:
        log("%s WARN left out %d unreadable frame(s): %s" % (day, len(dropped), ", ".join(dropped[:5])))

    reason = None
    if not window:
        reason = "no readable frames"
    elif regular < expected * cfg.min_fraction:
        reason = "only %d of %d expected regular frames" % (regular, expected)
    elif gaps["largest_gap_min"] > cfg.max_gap_min:
        reason = "a %g-minute gap with no frames from %s (limit %g)" % (
            gaps["largest_gap_min"], gaps["largest_gap_at_utc"], cfg.max_gap_min)
    elif gaps["largest_sunset_gap_min"] > cfg.max_sunset_gap_min:
        reason = "a %g-minute gap with no frames around sunset (limit %g)" % (
            gaps["largest_sunset_gap_min"], cfg.max_sunset_gap_min)
    if reason:
        record.update(status="skipped", reason=reason)
        record.update(carry)
        write_atomic(json_path, json.dumps(finish_record(record), indent=2) + "\n")
        log("%s skipped: %s" % (day, reason))
        return

    previous_crop = previous.get("crop") or {}
    azimuth, method = sunset_azimuth(frames, sunset)
    sunset_frame = nearest_frame(window, sunset)
    frame_setup = (sunset_frame.capture or {}).get("setup_id")
    expected_setup = settings["setup_id"]
    record.update(setup_id_expected=expected_setup, setup_id_frame=frame_setup,
                  setup_mismatch=None if not (expected_setup and frame_setup) else expected_setup != frame_setup)
    if record["setup_mismatch"]:
        log("%s WARN the sunset frame is from setup %s, crop.json is for %s: do not post"
            % (day, frame_setup, expected_setup))
    frame_w, frame_h = get_size(sunset_frame.jpg)
    calibration = active_calibration(crop_config, day)
    crop = crop_for_day(frame_w, frame_h, azimuth, calibration,
                        cfg.crop_center_x, settings["offset_px"], previous_crop.get("center_x"),
                        settings["view"])
    view = center_azimuth(crop, calibration, azimuth)
    crop.update(azimuth_deg=None if azimuth is None else round(azimuth, 2), azimuth_method=method,
                azimuth_step_flag=azimuth_step_flagged(azimuth, previous_crop.get("azimuth_deg")),
                center_azimuth_deg=None if view is None else round(view, 2))
    if settings["blur"]:
        crop.update(blur=settings["blur"], blur_sigma=settings["blur_sigma"])
    mask = settings["mask"] or []

    # Scored before encoding, so the video can show it (originals, not fused copies).
    scored = sky_frames_scored(cfg, window, sunset, settings["sky_rows"], crop_columns(crop, frame_w))
    sky = sky_from_scored(scored, settings["sky_full_warm"], settings["sky_min_frames"], crop_columns(crop, frame_w))
    # What the encoder draws: the crop plus the score. Only the encoder sees it; the record keeps `crop`.
    video_crop = dict(crop, sky_score=sky["score"]) if sky else crop

    video = day.isoformat() + ".mp4"
    tmp_video = os.path.join(cfg.daily_dir, ".%s.tmp" % video)
    try:
        encode(cfg, window, video_crop, mask, tmp_video)
        os.replace(tmp_video, os.path.join(cfg.daily_dir, video))
    finally:
        if os.path.exists(tmp_video):
            os.remove(tmp_video)

    caption = build_caption(sunset, cfg.tz, cfg.start_date, cfg.tags)
    write_atomic(os.path.join(cfg.daily_dir, day.isoformat() + ".txt"), caption + "\n")
    try:
        check_image(cfg, sunset_frame, crop, mask, os.path.join(cfg.daily_dir, day.isoformat() + "_check.jpg"))
    except EncodeError as e:
        log("%s WARN no check image: %s" % (day, e))

    record.update(status="encoded", video=video, caption=caption, sunset_frame=os.path.basename(sunset_frame.jpg),
                  crop=crop, sky=sky)
    if sky is None:
        record["sky_note"] = "no sky score: %d readable frame(s) from %d min before to %d min after sunset, need %d" % (
            len(scored), SKY_BEFORE_MIN, SKY_AFTER_MIN, settings["sky_min_frames"])

    record.update(carry)
    write_atomic(json_path, json.dumps(finish_record(record), indent=2) + "\n")   # last: this marks the day done
    log("%s encoded: %d frames, crop x=%d (%s)" % (day, len(window), crop["x"], crop["source"]))


def write_failed(cfg, sunset, record, error, previous, carry=None):
    """A trace of a day that failed. Runs within LOOKBACK_DAYS try it again; success replaces it."""
    day = local_date(sunset, cfg.tz)
    record = dict(record)
    record.setdefault("local_date", day.isoformat())
    record.setdefault("sunset_utc", sunset.strftime(TIME_FORMAT))
    record.setdefault("schema_version", RECORD_SCHEMA_VERSION)
    record.update(status="failed", error=error, failed_utc=datetime.now(UTC).strftime(TIME_FORMAT),
                  attempts=int((previous or {}).get("attempts", 0)) + 1, posted=False)
    for key in ("video", "caption", "sky", "sky_note", "reason"):
        record.pop(key, None)
    record.update(carry or {})
    try:
        write_atomic(os.path.join(cfg.daily_dir, day.isoformat() + ".json"),
                     json.dumps(finish_record(record), indent=2) + "\n")
    except OSError as e:
        log("%s could not write the failed record: %s" % (day, e))


def acquire_lock(path):
    """True if this run holds the lock. Encoding can outlast the gap between scheduled runs."""
    try:
        if time.time() - os.path.getmtime(path) > LOCK_STALE_SECONDS:
            os.remove(path)
    except OSError:
        pass
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except FileExistsError:
        return False


def run(cfg, now, encode=encode_video, frame_size=None, check_image=write_check_image):
    """Process every due sunset without a finished record (a failed one is tried again while it
    is within LOOKBACK_DAYS). A finished record is made again only under the REDO_* settings
    (redo_reason), within LOOKBACK_DAYS or the REDO_FROM/REDO_TO range. Returns the process exit
    code: 1 if any day failed."""
    get_size = frame_size or (lambda path: probe_frame_size(cfg, path))
    os.makedirs(cfg.daily_dir, exist_ok=True)
    lock = os.path.join(cfg.daily_dir, ".lock")
    if not acquire_lock(lock):
        log("another run is in progress")
        return 0
    try:
        try:
            crop_config = load_crop_config(cfg.crop_file)
        except ValueError as e:
            log("FAILED: %s is not valid JSON: %s" % (cfg.crop_file, e))
            return 1
        context = {"crop_config_sha256": file_sha256(cfg.crop_file)}
        oldest = now - timedelta(days=cfg.lookback_days)
        ranged = cfg.redo_from is not None or cfg.redo_to is not None
        list_from = oldest
        if cfg.redo_from is not None:
            first = datetime(cfg.redo_from.year, cfg.redo_from.month, cfg.redo_from.day, tzinfo=cfg.tz)
            list_from = min(oldest, first.astimezone(UTC))
        frames = use_fused(list_frames(cfg.frames_dir, list_from - WINDOW - timedelta(hours=1), now), cfg.fused_dir)
        rc = 0
        for sunset in due_sunsets(frames):
            day = local_date(sunset, cfg.tz)
            existing = read_record(cfg, day)
            in_scope = in_redo_range(cfg, day) if ranged else sunset >= oldest
            carry = None
            if existing is None or existing.get("status") == "failed":
                if sunset < oldest and not (ranged and in_scope):
                    continue
            else:   # finished: never redone unless a REDO_* setting asks for it
                why = redo_reason(cfg, existing) if in_scope else None
                if not why:
                    continue
                carry = {key: value for key, value in existing.items() if key.startswith("posted")}
                carry["redo"] = {"reason": why, "previous_status": existing.get("status"),
                                 "previous_script_version": (existing.get("provenance") or {}).get("script_version")}
                log("%s redo: %s" % (day, why))
            if "ffmpeg" not in context:
                context["ffmpeg"] = ffmpeg_version(cfg)
            record = {}
            try:
                process_sunset(cfg, sunset, frames, crop_config, encode, get_size, check_image, record, context, carry)
            except EncodeError as e:
                log("%s FAILED: %s" % (day, e))
                write_failed(cfg, sunset, record, str(e), existing, carry)
                rc = 1
            except Exception as e:   # one bad day must not stop the other days, now or in later runs
                log("%s FAILED: %s\n%s" % (day, e, traceback.format_exc()))
                write_failed(cfg, sunset, record, "%s: %s" % (type(e).__name__, e), existing, carry)
                rc = 1
        return rc
    finally:
        os.remove(lock)


def env_date(env, name):
    return date.fromisoformat(env[name]) if env.get(name) else None


def config_from_env(env):
    """The Config from environment settings (nas/README.md). FRAMES_DIR and DAILY_DIR must be set."""
    from zoneinfo import ZoneInfo
    daily_dir = env["DAILY_DIR"]
    center = env.get("CROP_CENTER_X")
    return Config(frames_dir=env["FRAMES_DIR"], daily_dir=daily_dir,
                  crop_file=env.get("CROP_FILE", os.path.join(daily_dir, "crop.json")),
                  tz=ZoneInfo(env.get("SITE_TZ", "America/Vancouver")),
                  start_date=date.fromisoformat(env.get("START_DATE", "2026-12-21")),
                  crop_center_x=int(center) if center else None,
                  tags=env.get("CAPTION_TAGS", DEFAULT_TAGS),
                  expected_frames=int(env.get("EXPECTED_FRAMES", str(EXPECTED_FRAMES))),
                  min_fraction=float(env.get("MIN_FRAME_FRACTION", "0.7")),
                  lookback_days=int(env.get("LOOKBACK_DAYS", "2")),
                  font_file=env.get("FONT_FILE") or DEFAULT_FONT_FILE,
                  start_local=env.get("VIDEO_START_LOCAL") or None,
                  location=env.get("OVERLAY_LOCATION", DEFAULT_LOCATION),
                  overlay_sky=env.get("OVERLAY_SKY", "1") != "0",
                  fused_dir=env.get("FUSED_DIR") or None,
                  max_gap_min=float(env.get("MAX_GAP_MIN", str(MAX_GAP_MIN))),
                  max_sunset_gap_min=float(env.get("MAX_SUNSET_GAP_MIN", str(MAX_SUNSET_GAP_MIN))),
                  redo_older_than=env.get("REDO_OLDER_THAN_VERSION") or None,
                  redo_from=env_date(env, "REDO_FROM"), redo_to=env_date(env, "REDO_TO"))


def main():
    missing = [name for name in ("FRAMES_DIR", "DAILY_DIR") if not os.environ.get(name)]
    if missing:
        print("sunset-daily: set %s" % " and ".join(missing), file=sys.stderr)
        return 2
    return run(config_from_env(os.environ), datetime.now(UTC))


if __name__ == "__main__":
    sys.exit(main())
