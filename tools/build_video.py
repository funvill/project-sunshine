#!/usr/bin/env python3
"""Build one day's Instagram video on a PC, with no AI: runs the daily job (nas/sunset-daily.py) for a chosen day.

    python tools/build_video.py --camera cm4wide --date 2026-11-17 --start 07:30 --redo \
        --crop nas/crop.cm4wide.json --fuse-production

It reads frames from the NAS share, writes to --out, and posts nothing. The crop, the
calibration and the tower blur come from a crop.json: --crop, else <out>/crop.json. The
checked-in one for the CM4 camera is nas/crop.cm4wide.json (calibration, tower blur and the tighter
view). --fuse-production merges the sunset bracket first (tools/fuse_sunset.py) so the sunset isn't
blown out, and blends each sunset minute with its neighbours (--no-blend to skip). Fused frames
already in <out>/fused are reused; with --redo they are made again (the blend undone, then the merge
forced), so a change to the merge code shows up. Settings are in nas/README.md.
Needs ffmpeg and a font (--font).
"""
import argparse
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sunset_daily", HERE.parent / "nas" / "sunset-daily.py")
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)

# The share's address stays out of this public repo: set SUNSET_NAS once on the PC, or pass --nas.
NAS = os.environ.get("SUNSET_NAS", "")
FONTS = ("C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/Library/Fonts/Arial Bold.ttf", daily.DEFAULT_FONT_FILE)


sys.path.insert(0, str(HERE))
import frames as framenames  # noqa: E402  (tools/frames.py)


def parse_pair(text):
    """'2.20,2.80' -> (2.2, 2.8): two positive numbers."""
    parts = text.split(",")
    if len(parts) != 2:
        raise ValueError("expected two numbers like 2.20,2.80, not %r" % text)
    pair = tuple(float(p) for p in parts)
    if min(pair) <= 0:
        raise ValueError("both must be above 0: %r" % text)
    return pair


def prepare_fused(fuse, brackets, frames_dir, fused_dir, redo=False, blend=True, window=None,
                  dusk_gains=None, dusk_ramp=(5.0, 15.0), deflicker=0):
    """Merge the sunset bracket (the production pairs from fuse.production_bracket()) into fused_dir,
    then blend each minute with its neighbours. Returns (frames fused, frames blended). Without redo,
    frames already there are kept. With redo the blend is undone (fused frames put back, the rest
    removed) and every frame fused again, so the video never encodes pictures made by older merge code.

    Optional steps over `window` (UTC start, end), each off unless asked for:
    dusk_gains (red, blue): after the merge and before the blend, re-colour the frames after sunset
    as if shot with these fixed colour gains, ramping in over dusk_ramp minutes (fuse.dusk_colour).
    deflicker (minutes): after the blend, steady each 1-a-minute frame's brightness, area by area,
    towards that many minutes either side (fuse.deflicker_minutes). A step run before with other
    settings needs redo."""
    if redo:
        fuse.undo_blend(fused_dir)
        fuse.clear_marks(fused_dir)
        # Drop every fused frame, so frames the new merge no longer makes (a narrower window) are
        # not still swapped into the video. Only frame-named JPEGs at the top level are removed.
        if os.path.isdir(fused_dir):
            for name in os.listdir(fused_dir):
                frame = framenames.parse(name)
                if frame and frame[2] is None:   # a fused frame is named like a regular one
                    os.remove(os.path.join(fused_dir, name))
    made = fuse.fuse_bracket(brackets, frames_dir, fused_dir, force=redo)
    if dusk_gains:
        fuse.dusk_colour(frames_dir, fused_dir, window[0], window[1], dusk_gains, dusk_ramp)
    blended = 0
    if blend:
        blended = fuse.blend_bracket(brackets[0], frames_dir, fused_dir)
    if deflicker:
        fuse.deflicker_minutes(frames_dir, fused_dir, window[0], window[1], deflicker)
    return made, blended


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", default="cm4wide", help="folder under the NAS root: cm4wide or cm4city")
    ap.add_argument("--date", required=True, help="the local date of the sunset, YYYY-MM-DD")
    ap.add_argument("--nas", default=NAS, help="project_sunshine folder on the share, e.g. //<nas-host>/camera/project_sunshine (default: $SUNSET_NAS)")
    ap.add_argument("--out", help="output folder (default ~/Documents/sunset-daily-out/<camera>)")
    ap.add_argument("--crop", help="crop.json (default <out>/crop.json)")
    ap.add_argument("--start", help="start the video at this local time, e.g. 07:30 (default: dark to dark)")
    ap.add_argument("--location", default=daily.DEFAULT_LOCATION, help="small text under the date; '' for none")
    ap.add_argument("--expected", type=int, default=daily.EXPECTED_FRAMES)
    ap.add_argument("--font", help="bold TTF for the text")
    ap.add_argument("--fuse-production", action="store_true",
                    help="merge the sunset bracket (the _ev0/_ev-2 frames from BRACKET=1) into the sunset frames first")
    ap.add_argument("--fused", help="a folder of already-fused frames (what --fuse-production makes in <out>/fused)")
    ap.add_argument("--no-blend", action="store_true", help="with --fuse-production: skip the 1:2:1 blend of each sunset minute with its neighbours")
    ap.add_argument("--dusk-gains", type=parse_pair, metavar="R,B",
                    help="after sunset, re-colour frames as if shot with these colour gains (e.g. the camera's "
                         "NIGHT_AWB, 2.20,2.80 on cm4wide): fixes the teal dusk of auto white balance")
    ap.add_argument("--dusk-ramp", type=parse_pair, default=(5.0, 15.0), metavar="FROM,TO",
                    help="minutes after sunset over which --dusk-gains comes in (default 5,15)")
    ap.add_argument("--deflicker", type=int, default=0, metavar="MIN",
                    help="steady the brightness of the 1-a-minute frames, area by area, over this many minutes either side "
                         "(e.g. 3); off by default")
    ap.add_argument("--redo", action="store_true",
                    help="delete that day's record first, so it is built again; with --fuse-production, make the fused frames again too")
    args = ap.parse_args()
    if not args.nas:
        ap.error("set SUNSET_NAS (or pass --nas) to the project_sunshine folder on the share")

    from zoneinfo import ZoneInfo
    day = date.fromisoformat(args.date)
    out = Path(args.out) if args.out else Path.home() / "Documents" / "sunset-daily-out" / args.camera
    out.mkdir(parents=True, exist_ok=True)
    font = args.font or next((f for f in FONTS if os.path.exists(f)), daily.DEFAULT_FONT_FILE)
    cfg = daily.Config(frames_dir=str(Path(args.nas) / args.camera), daily_dir=str(out),
                       crop_file=args.crop or str(out / "crop.json"), tz=ZoneInfo("America/Vancouver"),
                       start_date=date.fromisoformat("2026-12-21"), expected_frames=args.expected,
                       lookback_days=2, font_file=font, start_local=args.start, location=args.location)
    if args.fuse_production:
        spec = importlib.util.spec_from_file_location("fuse_sunset", HERE / "fuse_sunset.py")
        fuse = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fuse)   # needs numpy and OpenCV, so only loaded when asked for
        args.fused = str(out / "fused")
        window = fuse.evening_window(day, cfg.tz)
        brackets = fuse.production_bracket(cfg.frames_dir, *window)
        print("production bracket: %d ev0, %d ev-2" % (len(brackets[0]), len(brackets[1])))
        made, blended = prepare_fused(fuse, brackets, cfg.frames_dir, args.fused, redo=args.redo,
                                      blend=not args.no_blend, window=window,
                                      dusk_gains=args.dusk_gains, dusk_ramp=args.dusk_ramp,
                                      deflicker=args.deflicker)
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
