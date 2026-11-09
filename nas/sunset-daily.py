#!/usr/bin/env python3
"""Turn each day's frames into a vertical video, from dark to dark. Runs on the NAS.

Python standard library plus ffmpeg. It only reads frames and writes to DAILY_DIR, so
the Pi and the frame layout don't change. It posts nothing: publishing is a later step.

Each video ends on the first dark frame after sunset, and the next starts on the frame
after that, so together they show every frame once. Night is a larger share of a winter
video and day of a summer one.

Run it on a schedule through the afternoon and evening. Each run does nothing until a
frame shows the sky has gone dark after sunset, and a day is never done twice, because
`DAILY_DIR/<local date>.json` is written last and marks that day as finished.

Settings come from the environment; see nas/README.md.
"""
import collections
import dataclasses
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FRAME_NAME = re.compile(r"^[A-Za-z0-9-]+_(\d{8}T\d{6}Z)\.jpg$")

DARK_ELEVATION_DEG = -9.0      # measured: on 2026-11-04 the camera's Lux stopped falling near here
WINDOW = timedelta(hours=24)   # a first video, with none before it to continue from
AZIMUTH_RATE_DEG_PER_MIN = 0.19   # sun's azimuth rate at sunset here; varies 0.188-0.191 over a year
AZIMUTH_MAX_MINUTES = 60          # frames further from sunset than this say little about it
AZIMUTH_STEP_LIMIT_DEG = 1.0      # the true seasonal change is at most about 0.61 deg/day
EXPECTED_FRAMES = 288            # regular frames in 24 hours: capture is every 5 minutes
FRAME_SECONDS = 1.0 / 12.0       # every frame, sunset included: the 1-minute frames slow sunset down
LOCK_STALE_SECONDS = 6 * 3600     # longer than any real run; a crash must not stop the job for good
DEFAULT_TAGS = "#sunset #timelapse #raspberrypi"

# Text drawn on the video, in 1080x1920 pixels, 140 px above the bottom edge. Instagram's
# caption may cover it in the Reels feed; that was accepted (2026-11-07).
OVERLAY_TITLE = "Project Sunshine"
OVERLAY_HANDLE = "@FUNVILL"
DEFAULT_FONT_FILE = "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"   # Alpine's font-dejavu
TEXT_X = 60
TITLE_Y, TITLE_SIZE = 1650, 46
TIME_Y, TIME_SIZE = 1716, 64
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

Frame = collections.namedtuple("Frame", "time jpg sun")


class EncodeError(Exception):
    """ffmpeg or ffprobe failed; the day stays unfinished and the next run tries again."""


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
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"


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


def read_sun(jpg_path):
    try:
        with open(os.path.splitext(jpg_path)[0] + ".json") as f:
            sun = json.load(f).get("Sun")
    except (OSError, ValueError, AttributeError):
        return None
    return sun if isinstance(sun, dict) else None


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
                frames.append(Frame(t, path, read_sun(path)))
        day += timedelta(days=1)
    return sorted(frames, key=lambda f: f.time)


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


def active_calibration(crop_config, day):
    """The calibration in force on `day`: the average of its monthly fits up to that day.

    A new entry in the list means the camera physically moved, so fits are never averaged
    across entries. A fit with no values records a month with no clear day.
    """
    in_force = None
    for entry in crop_config.get("calibrations", []):
        if date.fromisoformat(entry["start"]) <= day:
            in_force = entry
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


def crop_for_day(frame_w, frame_h, azimuth, calibration, fixed_center, offset_px=0, previous_center=None):
    """Where the 9:16 window goes: one position for the whole video, at full height."""
    width = int(frame_h * 9 / 16) // 2 * 2
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
    return {"x": x, "width": width, "height": frame_h, "center_x": x + width // 2,
            "source": source, "clamped": x != wanted, "sun_x": sun_x}


def local_date(sunset, tz):
    """The date a viewer would give this sunset. Its UTC date is always one day later here."""
    return sunset.astimezone(tz).date()


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


def drawtext(cfg, text, y, size, enable=None):
    args = ["fontfile=" + filter_quote(cfg.font_file), "expansion=none", "text=" + filter_quote(text),
            "x=%d" % TEXT_X, "y=%d" % y, "fontsize=%d" % size, "fontcolor=white",
            "borderw=3", "bordercolor=black@0.6"]
    if enable:
        args.append("enable=" + filter_quote(enable))
    return "drawtext=" + ":".join(args)


def overlay_filters(cfg, frames):
    """The title line, and one timestamp per frame, each shown only while its frame is.
    Frames reach these filters one each, at the times concat_list gives them."""
    chain = [drawtext(cfg, "%s   %s" % (OVERLAY_TITLE, OVERLAY_HANDLE), TITLE_Y, TITLE_SIZE)]
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
    with os.fdopen(fd, "w") as f:
        f.write(concat_list(frames))
    fd, filter_path = tempfile.mkstemp(prefix=".filters-", suffix=".txt", dir=work)
    try:
        chain = mask_filters(mask) + [
            "crop=%d:%d:%d:0" % (crop["width"], crop["height"], crop["x"]),
            "scale=1080:1920:flags=lanczos:out_range=tv"]   # JPEGs are full range; yuv420p is not
        chain += overlay_filters(cfg, frames) + [
            "fps=24",
            "format=yuv420p"]
        with os.fdopen(fd, "w") as f:
            f.write(",\n".join(chain))
        run_tool([cfg.ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list_path,
                  "-filter_script:v", filter_path, "-an", "-sn", "-map_metadata", "-1",
                  "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "25M", "-bufsize", "50M",
                  "-flags", "+cgop", "-g", "48", "-use_editlist", "0", "-movflags", "+faststart",
                  "-f", "mp4", out])
    finally:
        os.remove(list_path)
        os.remove(filter_path)


def probe_frame_size(cfg, path):
    out = run_tool([cfg.ffprobe, "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height", "-of", "json", path])
    stream = json.loads(out)["streams"][0]
    return stream["width"], stream["height"]


def write_check_image(cfg, sunset_frame, crop, mask, out):
    """A small full frame with the crop and predicted sun drawn on it, to compare against
    the real sun. The privacy mask is applied here too, since this is the whole view."""
    frame_w = probe_frame_size(cfg, sunset_frame.jpg)[0]
    thick = max(2, frame_w // 200)
    chain = mask_filters(mask) + ["drawbox=x=%d:y=0:w=%d:h=%d:color=lime:t=%d"
                                  % (crop["x"], crop["width"], crop["height"], thick)]
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


def process_sunset(cfg, sunset, frames, crop_config, encode, get_size, check_image):
    day = local_date(sunset, cfg.tz)
    previous = read_record(cfg, day - timedelta(days=1)) or {}
    end = day_end(frames, sunset)
    start = parse_utc(previous.get("end_utc")) or end - WINDOW
    window = select_window(frames, start, end)
    expected = round((end - start) / (WINDOW / cfg.expected_frames))   # dusk drifts, so 288 give or take
    record = {"local_date": day.isoformat(), "sunset_utc": sunset.strftime(TIME_FORMAT),
              "start_utc": start.strftime(TIME_FORMAT), "end_utc": end.strftime(TIME_FORMAT),
              "frames": len(window), "expected_frames": expected, "posted": False}
    json_path = os.path.join(cfg.daily_dir, day.isoformat() + ".json")

    if len(window) < expected * cfg.min_fraction:
        record.update(status="skipped", reason="only %d of %d expected frames" % (len(window), expected))
        write_atomic(json_path, json.dumps(record, indent=2) + "\n")
        log("%s skipped: %s" % (day, record["reason"]))
        return

    previous_crop = previous.get("crop") or {}
    azimuth, method = sunset_azimuth(frames, sunset)
    sunset_frame = nearest_frame(window, sunset)
    frame_w, frame_h = get_size(sunset_frame.jpg)
    crop = crop_for_day(frame_w, frame_h, azimuth, active_calibration(crop_config, day),
                        cfg.crop_center_x, crop_config.get("offset_px", 0), previous_crop.get("center_x"))
    crop.update(azimuth_deg=None if azimuth is None else round(azimuth, 2), azimuth_method=method,
                azimuth_step_flag=azimuth_step_flagged(azimuth, previous_crop.get("azimuth_deg")))
    mask = crop_config.get("mask", [])

    video = day.isoformat() + ".mp4"
    tmp_video = os.path.join(cfg.daily_dir, ".%s.tmp" % video)
    try:
        encode(cfg, window, crop, mask, tmp_video)
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
                  crop=crop)
    write_atomic(json_path, json.dumps(record, indent=2) + "\n")   # last: this marks the day done
    log("%s encoded: %d frames, crop x=%d (%s)" % (day, len(window), crop["x"], crop["source"]))


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
    """Process every due sunset without a record. Returns the process exit code."""
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
        oldest = now - timedelta(days=cfg.lookback_days)
        frames = list_frames(cfg.frames_dir, oldest - WINDOW - timedelta(hours=1), now)
        rc = 0
        for sunset in due_sunsets(frames):
            if sunset < oldest or read_record(cfg, local_date(sunset, cfg.tz)) is not None:
                continue
            try:
                process_sunset(cfg, sunset, frames, crop_config, encode, get_size, check_image)
            except EncodeError as e:
                log("%s FAILED: %s" % (local_date(sunset, cfg.tz), e))
                rc = 1
        return rc
    finally:
        os.remove(lock)


def main():
    missing = [name for name in ("FRAMES_DIR", "DAILY_DIR") if not os.environ.get(name)]
    if missing:
        print("sunset-daily: set %s" % " and ".join(missing), file=sys.stderr)
        return 2
    from zoneinfo import ZoneInfo
    env = os.environ
    daily_dir = env["DAILY_DIR"]
    center = env.get("CROP_CENTER_X")
    cfg = Config(frames_dir=env["FRAMES_DIR"], daily_dir=daily_dir,
                 crop_file=env.get("CROP_FILE", os.path.join(daily_dir, "crop.json")),
                 tz=ZoneInfo(env.get("SITE_TZ", "America/Vancouver")),
                 start_date=date.fromisoformat(env.get("START_DATE", "2026-12-21")),
                 crop_center_x=int(center) if center else None,
                 tags=env.get("CAPTION_TAGS", DEFAULT_TAGS),
                 expected_frames=int(env.get("EXPECTED_FRAMES", str(EXPECTED_FRAMES))),
                 min_fraction=float(env.get("MIN_FRAME_FRACTION", "0.7")),
                 lookback_days=int(env.get("LOOKBACK_DAYS", "2")),
                 font_file=env.get("FONT_FILE") or DEFAULT_FONT_FILE)
    return run(cfg, datetime.now(UTC))


if __name__ == "__main__":
    sys.exit(main())
