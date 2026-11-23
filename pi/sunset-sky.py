#!/usr/bin/env python3
"""The evening's sky score, for Home Assistant's good-sunset alert (2026-11-22).

Run by sunset-sky.timer every 15 minutes. It does something only once a sunset, from SKY_DELAY_MIN
(40) to SKY_GIVE_UP_H (6 hours) after it: it scores the sky in this camera's frames from 35 minutes
before to 25 minutes after sunset and writes

    <SKY_OUT>/<CAM_NAME>/<local date>.json      (SKY_OUT default: project_sunshine_sky next to NAS_TARGET)

which Home Assistant reads (homeassistant/sunset_sky.sh) and turns into a phone notification when
the score reaches its threshold (60). A day that has its file is never scored again; a run with the
share missing writes nothing and the next run tries again.

The score is the one in nas/sunset-daily.py (what tools/build_video.py and tools/build_reports.py
print): the share of the top SKY_ROWS of the frame that is bright and warm, as the mean of the best
5 frames, over SKY_FULL_WARM (cm4wide's scale, 0.178, from nas/crop.cm4wide.json), as a percent
capped at 100. Deterministic image maths, no AI. One difference: the frames are decoded and shrunk
with Pillow (python3-pil) here and with ffmpeg on the PC. On Nov 12-22 this read 0 to 4 points
warmer than the PC (Nov 12: 52 to 48, Nov 16: 72 to 71), from the colour conversion, not the size;
on the safe side for a notification.

The result has no Sun block and no coordinates (frame JSON is private; it locates the site).
Frames are read from the share and, for any not synced yet, the outbox. Regular and dense frames
only, not _night or the bracket. Nothing is written to the SD card except one line in SKY_LOG.
SUNSET_NOW (epoch seconds) sets the time, for the tests.
"""
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_VERSION = "2026-11-22.1"

# The sky score, as in nas/sunset-daily.py (tests/test_sky.py checks they stay the same).
SKY_BEFORE_MIN, SKY_AFTER_MIN = 35, 25
SKY_WARM_RATIO = 1.2
SKY_WARM_MIN_BRIGHT = 77
SKY_SIZE = (160, 120)
SKY_TOP_FRAMES = 5
SKY_MIN_FRAMES = 6
SKY_ROWS_DEFAULT = 0.40
SKY_FULL_WARM_DEFAULT = 0.178   # cm4wide's scale (nas/crop.cm4wide.json); the daily job's default is 0.10


def env_float(env, name, default, lo, hi):
    try:
        value = float(env.get(name, "") or default)
    except ValueError:
        return default
    return value if lo <= value <= hi else default


def settings(env=None):
    env = os.environ if env is None else env
    nas = env.get("NAS_TARGET", "")
    out_root = env.get("OUT_ROOT") or os.path.join(os.path.expanduser("~"), "sunset", "outbox")
    return {
        "cam": env.get("CAM_NAME", "wide"),
        "setup_id": env.get("SETUP_ID", ""),
        "nas": nas,
        "outbox": out_root,
        "out": env.get("SKY_OUT") or (os.path.join(os.path.dirname(nas.rstrip("/")), "project_sunshine_sky")
                                      if nas.startswith("/") else ""),
        "log": env.get("SKY_LOG") or os.path.join(os.path.dirname(out_root), "sky.log"),
        "rows": env_float(env, "SKY_ROWS", SKY_ROWS_DEFAULT, 0.05, 1.0),
        "full": env_float(env, "SKY_FULL_WARM", SKY_FULL_WARM_DEFAULT, 0.001, 1.0),
        "delay_min": env_float(env, "SKY_DELAY_MIN", 40, SKY_AFTER_MIN, 600),
        "give_up_h": env_float(env, "SKY_GIVE_UP_H", 6, 1, 23),
        "require_mount": env.get("SKY_REQUIRE_MOUNT", "1") != "0",   # 0 only for the tests
        "lat": env.get("SITE_LAT", ""),
        "lon": env.get("SITE_LON", ""),
    }


def load_sun():
    spec = importlib.util.spec_from_file_location("sunset_sun", os.path.join(HERE, "sunset-sun.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- the score

def warm_fraction(rgb, width, rows):
    """Share of the top `rows` (0-1) of an rgb24 picture that is bright and warm: red over blue."""
    height = len(rgb) // (3 * width)
    count = warm = 0
    for y in range(max(1, int(height * rows))):
        for i in range(y * width * 3, (y + 1) * width * 3, 3):
            r, b = rgb[i], rgb[i + 2]
            count += 1
            if max(r, rgb[i + 1], b) >= SKY_WARM_MIN_BRIGHT and r > SKY_WARM_RATIO * b:
                warm += 1
    return warm / count if count else 0.0


def score_value(fraction, full):
    return int(round(100 * min(1.0, fraction / full)))


def label(score):
    return "colourful" if score >= 60 else "some colour" if score >= 20 else "grey"


def read_pixels(path):
    """rgb24 bytes of the picture shrunk to SKY_SIZE. The JPEG is decoded at 1/4 size (draft: within a
    point of a full decode, and fast), then box-averaged, as ffmpeg's area scaling does on the PC."""
    from PIL import Image
    with Image.open(path) as im:
        im.draft("RGB", (SKY_SIZE[0] * 4, SKY_SIZE[1] * 4))
        return im.convert("RGB").resize(SKY_SIZE, Image.BOX).tobytes()


def score_frames(paths, rows, full, read=None):
    """The sky block for these frames, or a block with score None under SKY_MIN_FRAMES readable ones."""
    read = read or read_pixels
    scored = []
    for path in paths:
        try:
            rgb = read(path)
        except Exception:   # an unreadable or half-written JPEG is left out, as the daily job does
            continue
        if len(rgb) != SKY_SIZE[0] * SKY_SIZE[1] * 3:
            continue
        scored.append((warm_fraction(rgb, SKY_SIZE[0], rows), os.path.basename(path)))
    if len(scored) < SKY_MIN_FRAMES:
        return {"score": None, "label": "none", "frames_scored": len(scored),
                "reason": "%d readable frames, %d needed" % (len(scored), SKY_MIN_FRAMES)}
    best = max(scored)
    top = sorted((s[0] for s in scored), reverse=True)[:SKY_TOP_FRAMES]
    mean = sum(top) / len(top)
    score = score_value(mean, full)
    return {"score": score, "label": label(score), "frames_scored": len(scored),
            "warm_sky_percent": round(best[0] * 100, 2), "warm_sky_percent_top_mean": round(mean * 100, 2),
            "best_frame": best[1]}


# ---------------------------------------------------------------- the frames

def frame_paths(cfg, sunset):
    """The regular and dense JPEGs from SKY_BEFORE_MIN before to SKY_AFTER_MIN after `sunset`, oldest
    first. The share's copy is preferred; a frame still in the outbox is read from there."""
    pattern = re.compile(r"^%s_(\d{8}T\d{6})Z\.jpg$" % re.escape(cfg["cam"]))
    first = sunset - timedelta(minutes=SKY_BEFORE_MIN)
    last = sunset + timedelta(minutes=SKY_AFTER_MIN)
    days = sorted({first.strftime("%Y/%m/%d"), last.strftime("%Y/%m/%d")})
    found = {}
    for root in (cfg["outbox"], cfg["nas"]):   # the share last, so its copy wins
        if not root:
            continue
        for day in days:
            folder = os.path.join(root, cfg["cam"], day)
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                m = pattern.match(name)
                if not m:
                    continue
                t = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
                path = os.path.join(folder, name)
                try:
                    if first <= t <= last and os.path.getsize(path) > 0:
                        found[name] = (t, path)
                except OSError:   # moved by the sync between the listing and here
                    pass
    return [p for _, p in sorted(found.values())]


def share_problem(cfg):
    """Why the result can't be written to the share, or None."""
    if not cfg["out"]:
        return "no SKY_OUT, and NAS_TARGET is not a mounted share"
    nas = cfg["nas"]
    if nas.startswith("/"):
        if not os.path.isdir(nas):
            return "%s not available (share not mounted?)" % nas
        try:
            if cfg["require_mount"] and os.stat(nas).st_dev == os.stat(os.path.dirname(cfg["outbox"].rstrip("/")) or "/").st_dev:
                return "%s is on the same disk as the outbox (share not mounted?)" % nas
        except OSError:
            pass
    return None


# ---------------------------------------------------------------- the run

def local_date(t):
    return datetime.fromtimestamp(t.timestamp()).strftime("%Y-%m-%d")


def due_sunsets(sun, now, cfg):
    """Sunsets between SKY_GIVE_UP_H and SKY_DELAY_MIN ago, oldest first."""
    lat, lon = float(cfg["lat"]), float(cfg["lon"])
    early = now - timedelta(hours=cfg["give_up_h"])
    late = now - timedelta(minutes=cfg["delay_min"])
    # To the second, as the frames' Sun.nearest_sunset_utc that the daily job's window starts from.
    sunsets = [s.replace(microsecond=0) for s in sun.sunsets_around(now, lat, lon, span=1)]
    return [s for s in sunsets if early <= s <= late]


def result_path(cfg, day):
    return os.path.join(cfg["out"], cfg["cam"], day + ".json")


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def log(cfg, now, text):
    line = "%s cam=%s %s\n" % (now.strftime("%Y-%m-%dT%H:%M:%SZ"), cfg["cam"], text)
    try:
        with open(cfg["log"], "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    sys.stdout.write(line)


def run(env=None, read=None, sun=None):
    cfg = settings(env)
    now = datetime.fromtimestamp(float((env or os.environ).get("SUNSET_NOW") or time.time()), UTC)
    if not cfg["lat"] or not cfg["lon"]:
        log(cfg, now, "SKIPPED: SITE_LAT/SITE_LON not set")
        return 1
    sun = sun or load_sun()
    due = [s for s in due_sunsets(sun, now, cfg) if not os.path.exists(result_path(cfg, local_date(s)))]
    if not due:
        return 0
    problem = share_problem(cfg)
    if problem:
        log(cfg, now, "SKIPPED: %s; tries again next run" % problem)
        return 1
    for sunset in due:
        day = local_date(sunset)
        sky = score_frames(frame_paths(cfg, sunset), cfg["rows"], cfg["full"], read)
        data = dict(sky, schema_version=1, camera=cfg["cam"], setup_id=cfg["setup_id"], date_local=day,
                    sunset_utc=sunset.strftime("%Y-%m-%dT%H:%M:%SZ"), out_of=100, provisional=True,
                    full_warm=cfg["full"], sky_rows=cfg["rows"], method="top%d_mean" % SKY_TOP_FRAMES,
                    computed_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"), script_version=SCRIPT_VERSION)
        write_json(result_path(cfg, day), data)
        log(cfg, now, "date=%s score=%s %s frames=%d" % (day, sky["score"], sky["label"], sky["frames_scored"]))
    return 0


if __name__ == "__main__":
    sys.exit(run())
