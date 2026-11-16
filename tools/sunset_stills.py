#!/usr/bin/env python3
"""Pick one full-resolution still per camera per evening at the same sun height, with no AI.

Issue #21, the horizon-swing still: the frame of each day where the sun stands at a fixed
elevation on the way down (+0.5 deg by default, just above the horizon), not at a fixed time,
so a row of them shows the sunset moving along the skyline through the year.

For each local date in the range and each camera:

    the evening's frames are found by their Sun block: Sun.nearest_sunset_utc on that local
    date and Sun.minutes_from_sunset within --window-min, so the morning crossing and the next
    evening never count. The evening runs past midnight UTC (sunset is about 00:10 to 04:20
    UTC here), so the UTC folders either side are both read.
    The frame whose Sun.elevation_deg is nearest the target is chosen. One further than
    --max-miss from it (a gap in the frames) gives no still for that day, and says so.
    Frames with no Sun block are left out of that. If no frame of the evening has one, the
    frame nearest sunset in time is used, with the sunset worked out by pi/sunset-sun.py from
    --lat/--lon (or SITE_LAT/SITE_LON); without them the day says why it has no still.
    _night frames are never chosen.

Then the best version of that frame is copied: a fused frame of the same name from a --fused
folder (tools/fuse_sunset.py), else an experiment frame labelled ev-2 (then ev-2-daylight)
within --ev2-seconds from an --experiments folder, else the production frame. Its JSON comes
with it (a fused frame has none of its own, so it gets the production frame's).

    python tools/sunset_stills.py --frames <NAS>/project_sunshine --from 2026-11-08 --to 2026-11-14 \
        --out stills/ [--camera cm4wide] [--fused fused/] \
        [--experiments cm4wide=<NAS>/project_sunshine_experiments] [--registration registration/]

--frames holds one folder per camera (<camera>/YYYY/MM/DD/). --fused and --experiments take a
folder, or CAMERA=FOLDER for one camera only; both can be given more than once. Experiment file
names don't say which camera took them, so give --experiments as CAMERA=FOLDER when both cameras'
runs are in the same place. An experiments folder is read along with the run folders directly in it.

Output, per camera: <out>/<camera>/<YYYY-MM-DD>.jpg and .json (the local date of the sunset), and
<out>/<camera>/index.json, one entry per day: where the still came from, the sun, the setup_id,
and dx/dy from tools/register_day.py when --registration has that UTC day. A day with no still
has an entry saying why. Running it again copies only days whose choice or source changed
(--redo copies every day again). It reads frames directly, not the daily records, so it works on
days whose video was skipped. Frames are only read. Standard library only.
"""
import argparse
import collections
import dataclasses
import importlib.util
import json
import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta, timezone

TOOL_VERSION = "2026-11-15.1"
SCHEMA_VERSION = 1
UTC = timezone.utc
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FRAME = re.compile(r"^(?P<cam>[A-Za-z0-9-]+)_(?P<t>\d{8}T\d{6}Z)\.jpg$")    # _night frames don't match
EXPERIMENT = re.compile(r"^(?P<label>.+)_(?P<t>\d{8}T\d{6}Z)\.jpg$")
SUN_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pi", "sunset-sun.py")


@dataclasses.dataclass
class Options:
    cameras: list = None              # default: every folder in --frames that holds a year folder
    target_elevation: float = 0.5     # degrees, on the way down
    max_miss: float = 1.0             # degrees: a chosen frame further than this from the target is refused
    window_min: float = 90.0          # frames this far either side of sunset are the evening's
    ev2_seconds: float = 90.0
    ev2_labels: tuple = ("ev-2", "ev-2-daylight")   # Steven's ranking (2026-11-09): B, ev-2 alone, above the rest
    fused: list = dataclasses.field(default_factory=list)        # [(camera or None, folder)]
    experiments: list = dataclasses.field(default_factory=list)  # [(camera or None, folder)]
    registration: str = None
    site: tuple = None                # (lat, lon), only for evenings with no Sun block at all
    tz: str = "America/Vancouver"
    redo: bool = False
    out: str = None                   # set by make_stills


def parse_stamp(text):
    return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def parse_utc(text):
    try:
        return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def iso(t):
    return t.astimezone(UTC).strftime(TIME_FORMAT)


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def read_json(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def jpeg_ok(path):
    """True if the file starts and ends like a whole JPEG (FFD8 ... FFD9), as nas/sunset-daily.py checks."""
    try:
        with open(path, "rb") as f:
            head = f.read(2)
            f.seek(0, os.SEEK_END)
            if f.tell() < 4:
                return False
            f.seek(-2, os.SEEK_END)
            return head == b"\xff\xd8" and f.read(2) == b"\xff\xd9"
    except OSError:
        return False


Frame = collections.namedtuple("Frame", "time path sun setup_id")


def list_frames(cam_dir, days):
    """Normal frames (not _night) in the UTC day folders `days`, with their Sun block and setup_id."""
    out = []
    for day in days:
        folder = os.path.join(cam_dir, "%04d" % day.year, "%02d" % day.month, "%02d" % day.day)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            m = FRAME.match(name)
            if not m:
                continue
            path = os.path.join(folder, name)
            data = read_json(os.path.splitext(path)[0] + ".json") or {}
            sun = data.get("Sun") if isinstance(data.get("Sun"), dict) else None
            capture = data.get("Capture") if isinstance(data.get("Capture"), dict) else {}   # none before 2026-11-04
            out.append(Frame(parse_stamp(m.group("t")), path, sun, capture.get("setup_id")))
    return sorted(out)


def load_sun_module():
    spec = importlib.util.spec_from_file_location("sunset_sun", SUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def site_sunset(day, tz, site):
    """The sunset on local date `day`, from pi/sunset-sun.py."""
    sun = load_sun_module()
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=tz).astimezone(UTC)
    for s in sun.sunsets_around(noon, site[0], site[1], span=1):
        if s.astimezone(tz).date() == day:
            return s
    return None


def find_sunset(frames, day, tz, site):
    """(sunset, where it came from) for local date `day`: the most common Sun.nearest_sunset_utc
    on that date among the frames, else the site's, else (None, None)."""
    seen = collections.Counter()
    for f in frames:
        s = parse_utc((f.sun or {}).get("nearest_sunset_utc"))
        if s is not None and s.astimezone(tz).date() == day:
            seen[s] += 1
    if seen:
        return seen.most_common(1)[0][0], "frames"
    if site:
        s = site_sunset(day, tz, site)
        if s is not None:
            return s, "site"
    return None, None


def choose_frame(frames, sunset, opts):
    """(frame, how, elevation miss) or (None, reason, None)."""
    window = timedelta(minutes=opts.window_min)
    near = [f for f in frames if abs(f.time - sunset) <= window and jpeg_ok(f.path)]
    if not near:
        return None, "no readable frame within %g min of sunset (%s)" % (opts.window_min, iso(sunset)), None

    def evening(f):
        s = parse_utc(f.sun.get("nearest_sunset_utc"))
        minutes = number(f.sun.get("minutes_from_sunset"))
        return (minutes is not None and abs(minutes) <= opts.window_min
                and (s is None or abs((s - sunset).total_seconds()) <= 120))

    rated = [f for f in near if f.sun and number(f.sun.get("elevation_deg")) is not None and evening(f)]
    if rated:
        best = min(rated, key=lambda f: (abs(number(f.sun["elevation_deg"]) - opts.target_elevation),
                                         abs((f.time - sunset).total_seconds())))
        miss = abs(number(best.sun["elevation_deg"]) - opts.target_elevation)
        if miss > opts.max_miss:
            return None, "the nearest frame (%s, %+.2f deg) is %.2f deg from the target %+.2f deg (limit %g)" % (
                os.path.basename(best.path), number(best.sun["elevation_deg"]), miss, opts.target_elevation,
                opts.max_miss), None
        return best, "elevation", round(miss, 3)
    best = min(near, key=lambda f: abs((f.time - sunset).total_seconds()))
    return best, "nearest_sunset_time", None


def folders_for(pairs, camera):
    return [folder for cam, folder in pairs if cam is None or cam == camera]


def experiment_frames(folders, labels):
    """[(time, label, path)] for the labelled frames in each folder and the run folders directly in it."""
    found = []
    for top in folders:
        try:
            entries = sorted(os.listdir(top))
        except OSError:
            continue
        dirs = [top] + [os.path.join(top, e) for e in entries if os.path.isdir(os.path.join(top, e))]
        for folder in dirs:
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                m = EXPERIMENT.match(name)
                if m and m.group("label") in labels:
                    found.append((parse_stamp(m.group("t")), m.group("label"), os.path.join(folder, name)))
    return sorted(found)


def choose_source(frame, fused_dirs, experiments, opts):
    """(kind, label, path, time, json path) of the version of `frame` to copy."""
    own_json = os.path.splitext(frame.path)[0] + ".json"
    own_json = own_json if os.path.exists(own_json) else None
    for folder in fused_dirs:
        path = os.path.join(folder, os.path.basename(frame.path))
        if jpeg_ok(path):
            return "fused", None, path, frame.time, own_json
    for label in opts.ev2_labels:
        near = [e for e in experiments if e[1] == label and jpeg_ok(e[2])
                and abs((e[0] - frame.time).total_seconds()) <= opts.ev2_seconds]
        if near:
            t, _, path = min(near, key=lambda e: (abs((e[0] - frame.time).total_seconds()), e[2]))
            exp_json = os.path.splitext(path)[0] + ".json"
            return "experiment", label, path, t, exp_json if os.path.exists(exp_json) else own_json
    return "production", None, frame.path, frame.time, own_json


def registration_for(folder, camera, frame_time):
    """dx/dy from tools/register_day.py for the chosen frame's UTC day: the daytime result if it
    is reliable, else the night one, else whichever has numbers."""
    if not folder:
        return None
    day = frame_time.date().isoformat()
    record = read_json(os.path.join(folder, camera, day + ".json"))
    if record is None:
        return None
    groups = [(name, record.get(name)) for name in ("day", "night") if isinstance(record.get(name), dict)]
    pick = next(((n, g) for n, g in groups if g.get("reliable")), None) or \
        next(((n, g) for n, g in groups if g.get("dx_px") is not None), (None, {}))
    name, group = pick
    return {"file": "%s/%s.json" % (camera, day), "day_utc": day, "from": name,
            "dx_px": group.get("dx_px"), "dy_px": group.get("dy_px"), "rotation_deg": group.get("rotation_deg"),
            "reliable": group.get("reliable"), "moved": record.get("moved")}


def copy_atomic(src, dst):
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def list_cameras(frames_root):
    try:
        names = sorted(os.listdir(frames_root))
    except OSError:
        return []
    return [n for n in names if os.path.isdir(os.path.join(frames_root, n)) and any(
        re.fullmatch(r"\d{4}", y) for y in os.listdir(os.path.join(frames_root, n)))]


def still_for_day(frames_root, camera, day, tz, opts, experiments, previous):
    """(index entry, what happened: "copied", "unchanged" or "none")."""
    cam_dir = os.path.join(frames_root, camera)
    frames = list_frames(cam_dir, [day - timedelta(days=1), day, day + timedelta(days=1)])
    sunset, sunset_from = find_sunset(frames, day, tz, opts.site)
    if sunset is None:
        reason = ("no frames in the UTC folders %s to %s" % (day - timedelta(days=1), day + timedelta(days=1))
                  if not frames else "no Sun data in any frame for this evening, and no --lat/--lon to work out sunset")
        return {"status": "none", "reason": reason}, "none"
    frame, how, miss = choose_frame(frames, sunset, opts)
    if frame is None:
        return {"status": "none", "reason": how, "sunset_utc": iso(sunset)}, "none"
    kind, label, src, src_time, src_json = choose_source(frame, folders_for(opts.fused, camera), experiments, opts)
    sun = frame.sun or {}
    st = os.stat(src)
    entry = {"status": "ok", "still": day.isoformat() + ".jpg", "source_path": os.path.abspath(src),
             "source_kind": kind, "source_label": label, "source_utc": iso(src_time),
             "source_json": os.path.abspath(src_json) if src_json else None,
             "source_size": st.st_size, "source_mtime": round(st.st_mtime, 3),
             "frame": os.path.basename(frame.path), "frame_utc": iso(frame.time),
             "sun_azimuth_deg": number(sun.get("azimuth_deg")), "sun_elevation_deg": number(sun.get("elevation_deg")),
             "minutes_from_sunset": number(sun.get("minutes_from_sunset")),
             "sunset_utc": iso(sunset), "sunset_from": sunset_from, "selected_by": how,
             "target_elevation_deg": opts.target_elevation, "elevation_miss_deg": miss,
             "setup_id": frame.setup_id,
             "registration": registration_for(opts.registration, camera, frame.time)}
    out_dir = os.path.join(opts.out, camera)
    still = os.path.join(out_dir, entry["still"])
    same = (previous and previous.get("status") == "ok"
            and all(previous.get(k) == entry[k] for k in ("source_path", "source_size", "source_mtime", "source_json"))
            and os.path.exists(still) and os.path.getsize(still) == st.st_size)
    if same and not opts.redo:
        entry["copied_utc"] = previous.get("copied_utc")
        return entry, "unchanged"
    copy_atomic(src, still)
    meta = os.path.join(out_dir, day.isoformat() + ".json")
    if src_json:
        copy_atomic(src_json, meta)
    elif os.path.exists(meta):
        os.remove(meta)
    entry["copied_utc"] = iso(datetime.now(UTC))
    return entry, "copied"


def make_stills(frames_root, first, last, out, opts=None, log=None):
    """Make the stills for local dates first..last (inclusive). Returns counts and one line per day."""
    from zoneinfo import ZoneInfo
    opts = opts or Options()
    opts.out = out
    tz = ZoneInfo(opts.tz)
    first = date.fromisoformat(first) if isinstance(first, str) else first
    last = date.fromisoformat(last) if isinstance(last, str) else last
    counts = {"copied": 0, "unchanged": 0, "none": 0, "lines": []}
    for camera in opts.cameras or list_cameras(frames_root):
        out_dir = os.path.join(out, camera)
        os.makedirs(out_dir, exist_ok=True)
        index_path = os.path.join(out_dir, "index.json")
        index = read_json(index_path) or {}
        days = index.get("days") if isinstance(index.get("days"), dict) else {}
        experiments = experiment_frames(folders_for(opts.experiments, camera), opts.ev2_labels)
        day = first
        while day <= last:
            previous = days.get(day.isoformat())
            entry, what = still_for_day(frames_root, camera, day, tz, opts, experiments, previous)
            if what == "none" and previous and previous.get("status") == "ok" and \
                    os.path.exists(os.path.join(out_dir, previous.get("still", ""))):
                # The frames may only be out of reach (NAS share, deleted after copying): keep the still.
                line = "%s %s: kept the earlier still (now: %s)" % (camera, day, entry["reason"])
                entry, what = previous, "unchanged"
            elif what == "none":
                line = "%s %s: none: %s" % (camera, day, entry["reason"])
            else:
                label = entry["source_kind"] + (" " + entry["source_label"] if entry["source_label"] else "")
                el = entry["sun_elevation_deg"]
                line = "%s %s: %s %s (el %s, %s min from sunset) %s" % (
                    camera, day, label, entry["frame"], "?" if el is None else "%+.2f" % el,
                    "?" if entry["minutes_from_sunset"] is None else "%+.1f" % entry["minutes_from_sunset"], what)
            days[day.isoformat()] = entry
            counts[what] += 1
            counts["lines"].append(line)
            if log:
                log(line)
            day += timedelta(days=1)
        index = {"schema_version": SCHEMA_VERSION, "tool": "sunset_stills.py", "tool_version": TOOL_VERSION,
                 "camera": camera, "days": dict(sorted(days.items()))}
        write_json_atomic(index_path, index)
    return counts


def folder_arg(text):
    """FOLDER or CAMERA=FOLDER. A drive letter (C:\\...) is not a camera name."""
    cam, sep, folder = text.partition("=")
    if sep and cam and re.fullmatch(r"[A-Za-z0-9-]+", cam) and folder:
        return cam, folder
    return None, text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", required=True, help="folder holding one folder per camera (<camera>/YYYY/MM/DD/)")
    ap.add_argument("--from", dest="first", required=True, help="first local date, YYYY-MM-DD")
    ap.add_argument("--to", dest="last", help="last local date (default: --from)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--camera", action="append", help="camera folder name (repeatable; default: all)")
    d = Options()
    ap.add_argument("--target-elevation", type=float, default=d.target_elevation, help="degrees (default %(default)s)")
    ap.add_argument("--max-miss", type=float, default=d.max_miss, help="degrees (default %(default)s)")
    ap.add_argument("--window-min", type=float, default=d.window_min)
    ap.add_argument("--fused", action="append", default=[], type=folder_arg, help="FOLDER or CAMERA=FOLDER")
    ap.add_argument("--experiments", action="append", default=[], type=folder_arg, help="FOLDER or CAMERA=FOLDER")
    ap.add_argument("--ev2-seconds", type=float, default=d.ev2_seconds)
    ap.add_argument("--ev2-labels", default=",".join(d.ev2_labels), help="in order of preference")
    ap.add_argument("--registration", help="tools/register_day.py output folder (<camera>/<UTC day>.json)")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float, help="east-positive; only used for evenings with no Sun block")
    ap.add_argument("--tz", default=d.tz)
    ap.add_argument("--redo", action="store_true", help="copy every day again")
    args = ap.parse_args(argv)
    lat = args.lat if args.lat is not None else os.environ.get("SITE_LAT")
    lon = args.lon if args.lon is not None else os.environ.get("SITE_LON")
    try:
        site = (float(lat), float(lon)) if lat not in (None, "") and lon not in (None, "") else None
        opts = Options(cameras=args.camera, target_elevation=args.target_elevation, max_miss=args.max_miss,
                       window_min=args.window_min, ev2_seconds=args.ev2_seconds,
                       ev2_labels=tuple(x.strip() for x in args.ev2_labels.split(",") if x.strip()),
                       fused=args.fused, experiments=args.experiments, registration=args.registration,
                       site=site, tz=args.tz, redo=args.redo)
        counts = make_stills(args.frames, args.first, args.last or args.first, args.out, opts,
                             log=lambda line: print(line, flush=True))
    except (OSError, ValueError, KeyError) as e:   # KeyError: an unknown --tz
        print("sunset_stills.py: %s" % e, file=sys.stderr)
        return 2
    print("%d copied, %d unchanged, %d with no still" % (counts["copied"], counts["unchanged"], counts["none"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
