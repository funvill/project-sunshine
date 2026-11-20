#!/usr/bin/env python3
"""Build reports/: a page of every day of one camera, with no AI.

    python tools/build_reports.py [--camera cm4wide] [--from 2026-11-12] [--to 2026-11-17] [--redo]

For each local (Vancouver) day it writes one row: a 100 x 100 thumbnail of the point where the
sun meets the horizon at sunset (taken from the frame nearest sunset, whatever the weather, with
the crop.json blur boxes applied first), the sky score worked out by the NAS job's own functions,
the sunset time and bearing, how many frames were taken and missed, the forecast at sunset, the
Pi's health and the day's events from changelog.md. Then the sky scores as an SVG graph.

Output, all in --out (default reports/ in the repo):
    index.html           the page
    sky-scores.svg       the graph, also used by the page
    days.json            the rows, so a later run only redoes new and recent days
    thumbs/<camera>/YYYY-MM-DD.jpg

Nothing in the output locates the site: the bearing is in whole degrees, the time to the minute,
no Sun block is copied, and the thumbnails carry no metadata. The frames are only read.

The frames folder is --frames, else the `nas` line of the git-ignored tools/camera_check.hosts
(never put that path in the repo). The sky score needs ffmpeg; the thumbnails need Pillow.
"""
import argparse
import datetime as dt
import html
import importlib.util
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
spec = importlib.util.spec_from_file_location("sunset_daily", REPO / "nas" / "sunset-daily.py")
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)

# BC has been on UTC-7 all year since before the first frame (no fall back on 2026-11-01), so a fixed
# offset is right for every day of the project, and doesn't depend on the machine's tzdata (2026a and
# older still say UTC-8 in winter).
VAN_TZ = dt.timezone(dt.timedelta(hours=-7), "Vancouver")
UTC = dt.timezone.utc

# The horizon's row at the sunset point, in full-frame pixels (4056 x 3040), by SETUP_ID.
# Measured on the sun's disc at the horizon. A new camera position needs its own row: a setup
# with none here gets no thumbnail, rather than one in the wrong place.
HORIZON_Y = {
    "cm4-window-1": 1300,    # Nov 13 00:05 UTC frame, skyline row at the sunset bearing
    "cm4-window-3": 1310,    # Nov 18 00:22 UTC, the sun's disc at 0.5 deg elevation
    "cm4-window-4": 1310,    # the foam hood, Nov 20: camera unmoved (under 1 px), so as cm4-window-3
}
THUMB_SIZE = 100             # pixels, square; the page shows it at this size
THUMB_REGION = 400           # full-frame pixels the thumbnail covers (about 12 deg on the 3.2 mm lens)
THUMB_HORIZON_AT = 0.7       # the sunset point sits this far down the thumbnail: sky above, few buildings
THUMB_MAX_MIN = 15           # the frame used must be this close to sunset
SLOT_MIN = 5
EXPECTED = 288
RECENT_DAYS = 2              # days this close to today are rebuilt every run (frames still arriving)
FORECAST_MAX_AGE_H = 12
POST_THRESHOLD = 60
# The first local day of each camera's reports: cm4wide was on a desk, then upside down for its
# first evening at the window (Nov 11), so its sky score that day means nothing.
FIRST_DAY = {"cm4wide": dt.date(2026, 11, 12)}
FRAME_RE = re.compile(r"^[A-Za-z0-9-]+_(\d{8}T\d{6}Z)(_ev0|_ev-2|_night)?\.jpg$")
EVENT_RE = re.compile(r"^- \*\*Event(?: \([^)]*\))?: (.+?)\*\*")


# ---------------------------------------------------------------- inputs

def changelog_events(text):
    """{local date: [event titles]} from changelog.md: top-level bullets that start **Event: ...**."""
    events, day = {}, None
    for line in text.splitlines():
        m = re.match(r"^## (\d{4}-\d{2}-\d{2})\s*$", line)
        if m:
            day = dt.date.fromisoformat(m.group(1))
            continue
        m = EVENT_RE.match(line)
        if m and day:
            events.setdefault(day, []).append(m.group(1).rstrip(".").strip())
    return events


def local_bounds(day):
    start = dt.datetime(day.year, day.month, day.day, tzinfo=VAN_TZ).astimezone(UTC)
    nxt = day + dt.timedelta(days=1)
    return start, dt.datetime(nxt.year, nxt.month, nxt.day, tzinfo=VAN_TZ).astimezone(UTC)


def read_json(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def list_day(frames_dir, day):
    """(frames, counts by suffix). Frames are the regular and dense ones of the local day, oldest
    first, as daily.Frame with the whole JSON kept in .source's place as `meta`."""
    start, end = local_bounds(day)
    frames, counts = [], {"_ev0": 0, "_ev-2": 0, "_night": 0}
    d = start.date()
    while d <= end.date():
        folder = os.path.join(frames_dir, "%04d" % d.year, "%02d" % d.month, "%02d" % d.day)
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        for name in names:
            m = FRAME_RE.match(name)
            if not m:
                continue
            t = dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            if not start <= t < end:
                continue
            if m.group(2):
                counts[m.group(2)] += 1
                continue
            path = os.path.join(folder, name)
            meta = read_json(os.path.splitext(path)[0] + ".json")
            sun, cap = meta.get("Sun"), meta.get("Capture")
            frames.append((daily.Frame(t, path, sun if isinstance(sun, dict) else None, None,
                                       cap if isinstance(cap, dict) else None), meta))
        d += dt.timedelta(days=1)
    frames.sort(key=lambda fm: fm[0].time)
    return frames, counts


def weather_at(weather_root, sunset):
    """The forecast for the hour nearest `sunset`, from the latest forecast fetched before it
    (and no more than FORECAST_MAX_AGE_H before). None if there is none."""
    if not weather_root or sunset is None:
        return None
    best = None
    for back in (0, 1):
        d = (sunset - dt.timedelta(days=back)).date()
        folder = os.path.join(weather_root, "%04d" % d.year, "%02d" % d.month, "%02d" % d.day)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            m = re.match(r"^forecast_(\d{8}T\d{6}Z)\.json$", name)
            if not m:
                continue
            fetched = dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            if fetched <= sunset and sunset - fetched <= dt.timedelta(hours=FORECAST_MAX_AGE_H):
                if best is None or fetched > best[0]:
                    best = (fetched, os.path.join(folder, name))
    if best is None:
        return None
    hourly = (read_json(best[1]).get("forecast") or {}).get("hourly") or {}
    hour = (sunset + dt.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
    key = hour.strftime("%Y-%m-%dT%H:00")
    times = hourly.get("time") or []
    if key not in times:
        return None
    i = times.index(key)

    def value(name):
        series = hourly.get(name + "_best_match") or []
        v = series[i] if i < len(series) else None
        return v if isinstance(v, (int, float)) else None

    vis = value("visibility")
    return {"cloud_pct": value("cloud_cover"), "low_pct": value("cloud_cover_low"),
            "mid_pct": value("cloud_cover_mid"), "high_pct": value("cloud_cover_high"),
            "visibility_km": None if vis is None else int(round(vis / 1000.0)),
            "precip_mm": value("precipitation"), "fetched_utc": best[0].strftime("%Y-%m-%dT%H:%MZ")}


# ---------------------------------------------------------------- the sunset point

def sun_point(crop_config, day, setup_id, azimuth):
    """(x, y) in full-frame pixels where the sun meets the horizon at `azimuth`, or None when the
    day has no calibration or the setup has no measured horizon."""
    if azimuth is None or setup_id not in HORIZON_Y:
        return None
    cal = daily.active_calibration(crop_config, day)
    if cal is None:
        return None
    x = cal["cx"] + cal["f_px"] * math.tan(math.radians(azimuth - cal["az0_deg"]))
    return int(round(x)), HORIZON_Y[setup_id]


def make_thumbnail(src, out, point, blur, sigma, region=THUMB_REGION, size=THUMB_SIZE):
    """A size x size JPEG of the `region`-pixel square with `point` across the middle and
    THUMB_HORIZON_AT of the way down, kept inside the frame,
    after blurring the crop.json boxes as the video does. No metadata is written."""
    from PIL import Image, ImageFilter
    img = Image.open(src).convert("RGB")
    for x, y, w, h in blur or []:
        box = (max(0, x), max(0, y), min(img.width, x + w), min(img.height, y + h))
        if box[2] > box[0] and box[3] > box[1]:
            img.paste(img.crop(box).filter(ImageFilter.GaussianBlur(sigma)), box[:2])
    side = min(region, img.width, img.height)
    x0 = max(0, min(img.width - side, int(point[0]) - side // 2))
    y0 = max(0, min(img.height - side, int(point[1]) - int(side * THUMB_HORIZON_AT)))
    thumb = img.crop((x0, y0, x0 + side, y0 + side)).resize((size, size), Image.LANCZOS)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    tmp = out + ".tmp"
    thumb.save(tmp, "JPEG", quality=85, optimize=True)
    os.replace(tmp, out)


# ---------------------------------------------------------------- one day

def pick_sunset(frames, day):
    """The sunset of local `day`, from the frames' Sun blocks."""
    for f, _ in frames:
        s = daily.frame_sunset(f)
        if s and s.astimezone(VAN_TZ).date() == day:
            return s
    return None


def frame_stats(frames, counts, day):
    start, end = local_bounds(day)
    regular = [f.time for f, _ in frames if daily.is_regular(f)]
    taken = {round((t - start).total_seconds() / 60.0 / SLOT_MIN) for t in regular}
    expected = int(round((end - start).total_seconds() / 60.0 / SLOT_MIN))
    edges = [start - dt.timedelta(minutes=SLOT_MIN)] + regular + [end]
    gap = max(((b - a).total_seconds() / 60.0 for a, b in zip(edges, edges[1:])), default=0.0)
    return {"regular": len(regular), "expected": expected,
            "missing_slots": len([i for i in range(expected) if i not in taken]),
            "dense": len(frames) - len(regular),
            "bracket_pairs": min(counts["_ev0"], counts["_ev-2"]), "night": counts["_night"],
            "largest_gap_min": round(gap, 1)}


def pi_stats(frames):
    temps, signals, pending, throttled, reboots, last_up = [], [], [], set(), 0, None
    for _, meta in frames:
        sysb = meta.get("System") if isinstance(meta.get("System"), dict) else {}
        if isinstance(sysb.get("cpu_temp_c"), (int, float)):
            temps.append(sysb["cpu_temp_c"])
        th = sysb.get("throttled")
        if isinstance(th, str):
            try:
                if int(th, 16):
                    throttled.add(th)
            except ValueError:
                pass
        up = sysb.get("uptime_s")
        if isinstance(up, (int, float)):
            if last_up is not None and up < last_up:
                reboots += 1
            last_up = up
        files = (sysb.get("outbox_pending") or {}).get("files")
        if isinstance(files, int):
            pending.append(files)
        wlan = ((sysb.get("network") or {}).get("wlan0") or {}).get("signal_dbm")
        if isinstance(wlan, (int, float)):
            signals.append(wlan)
    return {"cpu_max_c": max(temps) if temps else None, "reboots": reboots, "throttled": sorted(throttled),
            "outbox_max_files": max(pending) if pending else None,
            "wifi_dbm_median": int(statistics.median(signals)) if signals else None}


def day_summary(frames_dir, day, crop_config, events, sky_fn, weather_root=None):
    """Everything the report shows for one local day. `sky_fn(frames, sunset, settings)` gives
    the sky block (or None). The returned "thumbnail_source"/"thumbnail_point" are for making the
    thumbnail only and are left out of the public row (public_day)."""
    frames, counts = list_day(frames_dir, day)
    sunset = pick_sunset(frames, day)
    plain = [f for f, _ in frames]
    setups = sorted({(f.capture or {}).get("setup_id") for f in plain} - {None})
    row = {"date": day.isoformat(), "weekday": day.strftime("%a"),
           "frames": frame_stats(frames, counts, day), "pi": pi_stats(frames), "setup_ids": setups,
           "events": list(events or []), "sunset_local": None, "sunset_bearing_deg": None, "sky": None,
           "weather": None, "thumbnail": None, "thumbnail_note": None,
           "thumbnail_source": None, "thumbnail_point": None}
    if sunset is None:
        row["thumbnail_note"] = "no frames with sun data"
        return row
    row["sunset_local"] = sunset.astimezone(VAN_TZ).strftime("%H:%M")
    azimuth, _ = daily.sunset_azimuth(plain, sunset)
    row["sunset_bearing_deg"] = None if azimuth is None else int(round(azimuth))
    settings = daily.day_settings(crop_config, day)
    sky = sky_fn(plain, sunset, settings) if plain else None
    if sky:
        row["sky"] = {k: sky.get(k) for k in ("score", "label", "warm_sky_percent") if k in sky}
    row["weather"] = weather_at(weather_root, sunset)
    near = daily.nearest_frame(plain, sunset) if plain else None
    if near is None or abs((near.time - sunset).total_seconds()) > THUMB_MAX_MIN * 60:
        row["thumbnail_note"] = "no frame near sunset"
        return row
    setup = (near.capture or {}).get("setup_id")
    point = sun_point(crop_config, day, setup, azimuth)
    if point is None:
        row["thumbnail_note"] = ("no horizon measured for setup %s" % (setup or "unknown") if setup not in HORIZON_Y
                                 else "no calibration for this day" if azimuth is not None else "no sun bearing")
        return row
    if not 0 <= point[0] < 4056:
        row["thumbnail_note"] = "sun out of frame"
    row["thumbnail_source"], row["thumbnail_point"] = near.jpg, list(point)
    row["blur"], row["blur_sigma"] = settings.get("blur") or [], settings.get("blur_sigma")
    return row


def public_day(row):
    return {k: v for k, v in row.items() if k not in ("thumbnail_source", "thumbnail_point", "blur", "blur_sigma")}


def real_sky_fn(ffmpeg="ffmpeg"):
    cfg = SimpleNamespace(ffmpeg=ffmpeg)

    def sky(frames, sunset, settings):
        return daily.sky_score(cfg, frames, sunset, rows=settings["sky_rows"], full=settings["sky_full_warm"],
                               min_frames=settings["sky_min_frames"])
    return sky


def days_to_build(days, cached, today, redo):
    if redo:
        return list(days)
    recent = today - dt.timedelta(days=RECENT_DAYS)
    return [d for d in days if d.isoformat() not in cached or d >= recent]


# ---------------------------------------------------------------- output

def short_date(iso):
    d = dt.date.fromisoformat(iso)
    return "%s %d" % (d.strftime("%b"), d.day)


def score_svg(days):
    """The sky scores as a bar chart, one bar a day, with the posting threshold. Plain SVG with its
    own light and dark colours and a hover title on every day."""
    days = sorted(days, key=lambda d: d["date"])
    n = max(1, len(days))
    left, right, top, bottom = 44, 120, 34, 40     # the right margin holds the threshold's label
    step = max(12, min(80, 900 // n))
    width = left + right + step * n
    height = 260
    plot_h = height - top - bottom

    def y(v):
        return top + plot_h * (1 - v / 100.0)

    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
           'aria-labelledby="t">' % (width, height, width, height),
           '<title id="t">Sky score at sunset, one bar a day</title>',
           '<style>'
           ':root{--bg:#fcfcfa;--ink:#1f1f1f;--muted:#666;--grid:#e3e3df;--bar:#d9822b;--line:#7a7a7a}'
           '@media (prefers-color-scheme: dark){:root{--bg:#1b1b1d;--ink:#ececec;--muted:#a0a0a0;'
           '--grid:#333336;--bar:#f0a050;--line:#9a9a9a}}'
           'text{font:11px system-ui,sans-serif;fill:var(--muted)}.h{fill:var(--ink);font-size:13px}'
           '.bar{fill:var(--bar)}.grid{stroke:var(--grid)}.thr{stroke:var(--line);stroke-dasharray:4 3}'
           '.none{fill:none;stroke:var(--muted)}'
           '</style>',
           '<rect width="100%" height="100%" fill="var(--bg)"/>',
           '<text class="h" x="%d" y="18">Sky score at sunset (0 to 100), wide camera</text>' % left]
    for v in (0, 20, 40, 60, 80, 100):
        out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (left, width - right, y(v), y(v)))
        out.append('<text x="%d" y="%.1f" text-anchor="end">%d</text>' % (left - 6, y(v) + 4, v))
    out.append('<line class="thr" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (left, width - right, y(POST_THRESHOLD),
                                                                          y(POST_THRESHOLD)))
    out.append('<text x="%d" y="%.1f">posting threshold %d</text>'
               % (width - right + 6, y(POST_THRESHOLD) + 4, POST_THRESHOLD))
    bar_w = int(max(4, min(28, step * 0.6)))
    every = 1 if step >= 40 else 7
    for i, d in enumerate(days):
        x = left + i * step + (step - bar_w) / 2.0
        sky = d.get("sky")
        if sky and sky.get("score") is not None:
            s = sky["score"]
            label = "%s: %d (%s)" % (short_date(d["date"]), s, sky.get("label", ""))
            out.append('<g><title>%s</title><rect class="bar" x="%.1f" y="%.1f" width="%d" height="%.1f" rx="2"/></g>'
                       % (html.escape(label), x, y(s), bar_w, max(1.0, y(0) - y(s))))
        else:
            out.append('<g><title>%s: no score</title><circle class="none" cx="%.1f" cy="%.1f" r="3"/></g>'
                       % (html.escape(short_date(d["date"])), x + bar_w / 2.0, y(0) - 5))
        if i % every == 0:
            out.append('<text x="%.1f" y="%d" text-anchor="middle">%s</text>'
                       % (x + bar_w / 2.0, height - bottom + 16, html.escape(short_date(d["date"]))))
    out.append('<text x="%d" y="%d">Circles: no score that day (no frames or too few around sunset).</text>'
               % (left, height - 6))
    out.append('</svg>')
    return "\n".join(out) + "\n"


PAGE_CSS = """
:root{--bg:#fcfcfa;--card:#ffffff;--ink:#1f1f1f;--muted:#5f5f5f;--line:#e3e3df;--warm:#b35d12;--hi:#fff4e6}
@media (prefers-color-scheme: dark){:root{--bg:#161618;--card:#1f1f22;--ink:#ececec;--muted:#a3a3a3;
--line:#333336;--warm:#f0a050;--hi:#2c2418}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px}p{margin:6px 0}
.muted{color:var(--muted)}.stats{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:130px}
.stat b{display:block;font-size:22px}.graph{overflow-x:auto;background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:8px}.graph img{display:block;max-width:none}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{padding:8px 10px;border-bottom:1px solid var(--line);
text-align:left;vertical-align:top}th{position:sticky;top:0;background:var(--card);font-weight:600}
td.t{width:116px}td.t img{display:block;border-radius:4px}.score{font-size:20px;font-weight:600}
tr.good td{background:var(--hi)}.score.good{color:var(--warm)}.none{width:100px;height:100px;border:1px dashed var(--line);
border-radius:4px;display:flex;align-items:center;justify-content:center;text-align:center;font-size:11px;
color:var(--muted);padding:6px}ul{margin:0;padding-left:16px}.small{font-size:12px}
"""


def fmt(v, unit="", none="–"):
    return none if v is None else "%s%s" % (v, unit)


def render_row(d):
    e = html.escape
    sky = d.get("sky") or {}
    score = sky.get("score")
    good = score is not None and score >= POST_THRESHOLD
    thumb = ('<img src="%s" width="100" height="100" alt="Sunset point on %s">' % (e(d["thumbnail"]), e(d["date"]))
             if d.get("thumbnail") else '<div class="none">%s</div>' % e(d.get("thumbnail_note") or "no thumbnail"))
    f = d.get("frames") or {}
    p = d.get("pi") or {}
    w = d.get("weather")
    if w:
        weather = ("Cloud %s<br><span class=\"small muted\">low %s, mid %s, high %s<br>visibility %s, rain %s</span>"
                   % (fmt(w.get("cloud_pct"), "%"), fmt(w.get("low_pct"), "%"), fmt(w.get("mid_pct"), "%"),
                      fmt(w.get("high_pct"), "%"), fmt(w.get("visibility_km"), " km"), fmt(w.get("precip_mm"), " mm")))
    else:
        weather = '<span class="muted">no forecast</span>'
    sky_cell = ('<span class="score%s">%d</span><br><span class="small muted">%s, %s%% warm sky</span>'
                % (" good" if good else "", score, e(sky.get("label", "")), fmt(sky.get("warm_sky_percent")))
                if score is not None else '<span class="muted">no score</span>')
    frames = ("%s of %s<br><span class=\"small muted\">missing %s, longest gap %s min<br>dense %s, pairs %s, night %s</span>"
              % (fmt(f.get("regular")), fmt(f.get("expected")), fmt(f.get("missing_slots")),
                 fmt(f.get("largest_gap_min")), fmt(f.get("dense")), fmt(f.get("bracket_pairs")), fmt(f.get("night"))))
    pi = ("CPU max %s<br><span class=\"small muted\">reboots %s%s<br>backlog max %s files<br>Wi-Fi %s</span>"
          % (fmt(p.get("cpu_max_c"), " °C"), fmt(p.get("reboots")),
             (", throttled " + ", ".join(p["throttled"])) if p.get("throttled") else "",
             fmt(p.get("outbox_max_files")), fmt(p.get("wifi_dbm_median"), " dBm")))
    notes = "".join("<li>%s</li>" % e(x) for x in d.get("events") or [])
    setup = ", ".join(d.get("setup_ids") or []) or "–"
    if d.get("thumbnail") and d.get("thumbnail_note"):
        notes += "<li>%s</li>" % e(d["thumbnail_note"])
    sunset = ("%s<br><span class=\"small muted\">%s°</span>" % (e(d["sunset_local"]), fmt(d.get("sunset_bearing_deg")))
              if d.get("sunset_local") else '<span class="muted">–</span>')
    return ('<tr%s><td class="t">%s</td><td><b>%s</b><br><span class="small muted">%s</span></td><td>%s</td>'
            '<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><span class="small muted">%s</span>%s</td></tr>'
            % (' class="good"' if good else "", thumb, e(short_date(d["date"])), e(d.get("weekday", "") + " " + d["date"]),
               sunset, sky_cell, frames, weather, pi, e(setup), ("<ul>%s</ul>" % notes) if notes else ""))


def render_html(days, generated, camera):
    e = html.escape
    days = sorted(days, key=lambda d: d["date"], reverse=True)
    scores = [d["sky"]["score"] for d in days if d.get("sky") and d["sky"].get("score") is not None]
    missing = sum((d.get("frames") or {}).get("missing_slots") or 0 for d in days)
    regular = sum((d.get("frames") or {}).get("regular") or 0 for d in days)
    span = "%s to %s" % (days[-1]["date"], days[0]["date"]) if days else "no days"
    made = generated.astimezone(VAN_TZ).strftime("%Y-%m-%d %H:%M")
    stats = [("Days", len(days)), ("Frames (5-minute)", "{:,}".format(regular)), ("Missed slots", "{:,}".format(missing)),
             ("Days scored", len(scores)), ("Days at %d or more" % POST_THRESHOLD, sum(1 for s in scores if s >= POST_THRESHOLD)),
             ("Best score", max(scores) if scores else "–")]
    stat_html = "".join('<div class="stat"><span class="muted small">%s</span><b>%s</b></div>' % (e(k), e(str(v)))
                        for k, v in stats)
    rows = "\n".join(render_row(d) for d in days)
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Project Sunset reports</title>
<style>%s</style>
</head>
<body>
<main>
<h1>Project Sunset reports</h1>
<p class="muted">Camera <b>%s</b>, %s. Made %s Vancouver time by <code>tools/build_reports.py</code>, with no AI.
It is rebuilt when the project is updated, so it can be a few weeks behind.</p>
<div class="stats">%s</div>
<h2>Sky score</h2>
<p class="muted small">How much of the sky turns bright and warm in the hour around sunset (provisional; the posting threshold is %d).</p>
<div class="graph"><img src="sky-scores.svg" alt="Bar chart of the daily sky score"></div>
<h2>Every day</h2>
<p class="muted small">The thumbnail is the point where the sun meets the horizon, from the frame nearest sunset, whatever the weather.
Times are Vancouver time; bearings are degrees true. Weather is the Open-Meteo forecast for the hour of sunset.
Pi health is from the frames' own records. Events come from the changelog.</p>
<div class="wrap"><table>
<thead><tr><th>Sunset point</th><th>Day</th><th>Sunset</th><th>Sky score</th><th>Frames</th><th>Weather at sunset</th><th>Pi</th><th>Setup and events</th></tr></thead>
<tbody>
%s
</tbody></table></div>
</main>
</body>
</html>
""" % (PAGE_CSS, e(camera), e(span), e(made), stat_html, POST_THRESHOLD, rows)


# ---------------------------------------------------------------- main

def nas_from_hosts(path=HERE / "camera_check.hosts"):
    try:
        for line in open(path):
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] == "nas":
                return parts[1].strip()
    except OSError:
        pass
    return None


def first_day(frames_dir):
    """The earliest local day with a frame folder for this camera."""
    for y in sorted(os.listdir(frames_dir)):
        for m in sorted(os.listdir(os.path.join(frames_dir, y))):
            for d in sorted(os.listdir(os.path.join(frames_dir, y, m))):
                try:
                    utc = dt.datetime(int(y), int(m), int(d), 12, tzinfo=UTC)
                except ValueError:
                    continue
                return utc.astimezone(VAN_TZ).date()
    return None


def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", help="folder holding one folder per camera (default: the `nas` line of "
                                     "tools/camera_check.hosts)")
    ap.add_argument("--camera", default="cm4wide")
    ap.add_argument("--out", default=str(REPO / "reports"))
    ap.add_argument("--crop", help="crop.json (default nas/crop.<camera>.json)")
    ap.add_argument("--weather", help="forecast folder (default <frames>/../project_sunshine_experiments/weather)")
    ap.add_argument("--changelog", default=str(REPO / "changelog.md"))
    ap.add_argument("--from", dest="first", help="first local date (default: FIRST_DAY, else the camera's first)")
    ap.add_argument("--to", dest="last", help="last local date (default: yesterday)")
    ap.add_argument("--redo", action="store_true", help="rebuild every day, not just new and recent ones")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args(argv)

    root = args.frames or nas_from_hosts()
    if not root:
        sys.exit("no frames folder: pass --frames or add a `nas` line to tools/camera_check.hosts")
    frames_dir = os.path.join(root, args.camera)
    crop_path = args.crop or str(REPO / "nas" / ("crop.%s.json" % args.camera))
    crop_config = daily.load_crop_config(crop_path) if os.path.exists(crop_path) else {}
    weather = args.weather or os.path.join(os.path.dirname(root.rstrip("/\\")), "project_sunshine_experiments", "weather")
    try:
        events = changelog_events(open(args.changelog, encoding="utf-8").read())
    except OSError:
        events = {}

    today = dt.datetime.now(VAN_TZ).date()
    first = (dt.date.fromisoformat(args.first) if args.first
             else FIRST_DAY.get(args.camera) or first_day(frames_dir))
    last = dt.date.fromisoformat(args.last) if args.last else today - dt.timedelta(days=1)
    if first is None or first > last:
        sys.exit("no days to report")
    all_days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]

    out = args.out
    cache_path = os.path.join(out, "days.json")
    cached = {}
    if os.path.exists(cache_path):
        cached = {d["date"]: d for d in json.load(open(cache_path, encoding="utf-8")).get("days", [])
                  if d.get("camera", args.camera) == args.camera}
    sky_fn = real_sky_fn(args.ffmpeg)
    for day in days_to_build(all_days, cached, today, args.redo):
        row = day_summary(frames_dir, day, crop_config, events.get(day, []), sky_fn, weather)
        rel = "thumbs/%s/%s.jpg" % (args.camera, day.isoformat())
        if row["thumbnail_source"]:
            try:
                make_thumbnail(row["thumbnail_source"], os.path.join(out, rel), row["thumbnail_point"],
                               row.get("blur"), row.get("blur_sigma") or daily.BLUR_SIGMA)
                row["thumbnail"] = rel
            except OSError as err:
                row["thumbnail_note"] = "thumbnail failed: %s" % type(err).__name__
        row = public_day(row)
        row["camera"] = args.camera
        cached[day.isoformat()] = row
        sky = (row.get("sky") or {}).get("score")
        print("%s  sky %-4s frames %s/%s  thumb %s" % (row["date"], "-" if sky is None else sky,
              row["frames"]["regular"], row["frames"]["expected"], row["thumbnail"] or row["thumbnail_note"]))
    for day, row in cached.items():          # the changelog may have new events for old days
        row["events"] = events.get(dt.date.fromisoformat(day), [])
    days = [cached[d.isoformat()] for d in all_days if d.isoformat() in cached]
    generated = dt.datetime.now(UTC)
    write_text(cache_path, json.dumps({"camera": args.camera, "generated_utc": generated.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                       "days": days}, indent=1) + "\n")
    write_text(os.path.join(out, "sky-scores.svg"), score_svg(days))
    write_text(os.path.join(out, "index.html"), render_html(days, generated, args.camera))
    print("wrote %s (%d days)" % (os.path.join(out, "index.html"), len(days)))


if __name__ == "__main__":
    main()
