#!/usr/bin/env python3
"""Build one day's Instagram video on a PC, with no AI: the same job the NAS runs, for a chosen day.

    python tools/build_video.py --camera cm4wide --date 2026-11-12 --start 07:30 --redo \
        --crop nas/crop.cm4wide.json --fuse-run cm4-sunset-1

It reads frames from the NAS share, writes to --out, and posts nothing. The crop, the
calibration and the tower blur come from a crop.json: --crop, else <out>/crop.json. The
checked-in one for the CM4 camera is nas/crop.cm4wide.json (calibration, tower blur and the tighter
view). --fuse-run merges the sunset bracket first (tools/fuse_sunset.py) so the sunset isn't blown
out, and blends each sunset minute with its neighbours (--no-blend to skip). Fused frames already in
<out>/fused are reused; with --redo they are made again (the blend undone, then the merge forced), so
a change to the merge code shows up. Settings are in nas/README.md.
Needs ffmpeg and a font (--font; the NAS image has its own).
"""
import argparse
import importlib.util
import json
import re
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sunset_daily", HERE.parent / "nas" / "sunset-daily.py")
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)

NAS = "//chipkin_nas.local/camera/project_sunshine"
FONTS = ("C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/Library/Fonts/Arial Bold.ttf", daily.DEFAULT_FONT_FILE)


FUSED_NAME = re.compile(r"^[A-Za-z0-9]+_\d{8}T\d{6}Z\.jpg$")   # a fused frame: <cam>_<UTC>.jpg


def prepare_fused(fuse, run_dir, frames_dir, fused_dir, redo=False, blend=True):
    """Merge the sunset bracket into fused_dir, then blend each minute with its neighbours.
    Returns (frames fused, frames blended). Without redo, frames already there are kept. With redo
    the blend is undone (fused frames put back, the rest removed) and every frame fused again, so
    the video never encodes pictures made by older merge code."""
    if redo:
        fuse.undo_blend(fused_dir)
        # Drop every fused frame, so frames the new merge no longer makes (a narrower window) are
        # not still swapped into the video. Only frame-named JPEGs at the top level are removed.
        if os.path.isdir(fused_dir):
            for name in os.listdir(fused_dir):
                if FUSED_NAME.match(name):
                    os.remove(os.path.join(fused_dir, name))
    made = fuse.fuse_run(run_dir, frames_dir, fused_dir, force=redo)
    blended = fuse.blend_run(run_dir, frames_dir, fused_dir) if blend else 0
    return made, blended


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", default="wide", help="folder under the NAS root: wide or cm4wide")
    ap.add_argument("--date", required=True, help="the local date of the sunset, YYYY-MM-DD")
    ap.add_argument("--nas", default=NAS, help="project_sunshine folder (default %(default)s)")
    ap.add_argument("--out", help="output folder (default ~/Documents/sunset-daily-out/<camera>)")
    ap.add_argument("--crop", help="crop.json (default <out>/crop.json)")
    ap.add_argument("--start", help="start the video at this local time, e.g. 07:30 (default: dark to dark)")
    ap.add_argument("--location", default=daily.DEFAULT_LOCATION, help="small text under the date; '' for none")
    ap.add_argument("--expected", type=int, default=daily.EXPECTED_FRAMES)
    ap.add_argument("--font", help="bold TTF for the text")
    ap.add_argument("--fuse-run", help="experiment run with the sunset bracket, e.g. cm4-sunset-1: merge it first")
    ap.add_argument("--fused", help="a folder of already-fused frames (what --fuse-run makes in <out>/fused)")
    ap.add_argument("--no-blend", action="store_true", help="with --fuse-run: skip the 1:2:1 blend of each sunset minute with its neighbours")
    ap.add_argument("--redo", action="store_true",
                    help="delete that day's record first, so it is built again; with --fuse-run, make the fused frames again too")
    args = ap.parse_args()

    from zoneinfo import ZoneInfo
    day = date.fromisoformat(args.date)
    out = Path(args.out) if args.out else Path.home() / "Documents" / "sunset-daily-out" / args.camera
    out.mkdir(parents=True, exist_ok=True)
    font = args.font or next((f for f in FONTS if os.path.exists(f)), daily.DEFAULT_FONT_FILE)
    cfg = daily.Config(frames_dir=str(Path(args.nas) / args.camera), daily_dir=str(out),
                       crop_file=args.crop or str(out / "crop.json"), tz=ZoneInfo("America/Vancouver"),
                       start_date=date.fromisoformat("2026-12-21"), expected_frames=args.expected,
                       lookback_days=2, font_file=font, start_local=args.start, location=args.location)
    if args.fuse_run:
        spec = importlib.util.spec_from_file_location("fuse_sunset", HERE / "fuse_sunset.py")
        fuse = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fuse)   # needs numpy and OpenCV, so only loaded when asked for
        run_dir = Path(args.nas).parent / "project_sunshine_experiments" / args.fuse_run
        args.fused = str(out / "fused")
        made, blended = prepare_fused(fuse, str(run_dir), cfg.frames_dir, args.fused, redo=args.redo,
                                      blend=not args.no_blend)
        print("fused %d frames" % made)
        if not args.no_blend:
            print("blended %d frames with their neighbours" % blended)
    cfg.fused_dir = args.fused
    if args.redo:
        for suffix in (".json", ".mp4", ".txt", "_check.jpg"):
            (out / (day.isoformat() + suffix)).unlink(missing_ok=True)
    # Run as if it were the evening after that sunset, so the job treats it as due.
    now = datetime(day.year, day.month, day.day, tzinfo=cfg.tz).astimezone(daily.UTC) + timedelta(days=1, hours=6)
    rc = daily.run(cfg, now)
    video = out / (day.isoformat() + ".mp4")
    print("video: %s" % video if video.exists() else "no video made (see the lines above)")
    try:
        with open(out / (day.isoformat() + ".json")) as f:
            record = json.load(f)
    except (OSError, ValueError):
        record = {}
    sky = record.get("sky")
    if sky:
        print("sky score: %d / %d (%s)   warm sky %.1f%% at its best, frame %s, %d frames scored%s"
              % (sky["score"], sky["out_of"], sky["label"], sky["warm_sky_percent"], sky["best_frame"],
                 sky["frames_scored"], "   [provisional: tuned on two good sunsets]" if sky.get("provisional") else ""))
    elif record.get("status") == "encoded":
        print("sky score: none (no readable frame within 35 min before to 25 min after sunset)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
