#!/usr/bin/env python3
"""Sun position and sunset time with no network and no dependencies (stdlib only).

Uses the NOAA solar calculator equations (Meeus-based), good to roughly a minute
for sunset and a fraction of a degree for position at this latitude. Azimuth is
degrees clockwise from TRUE north (not magnetic). Elevation includes atmospheric
refraction. "Sunset" is the upper limb touching the horizon (zenith 90.833 deg).

    sunset-sun.py position  [--time T]
    sunset-sun.py sunset    [--after T] [--epoch|--json]
    sunset-sun.py annotate  FRAME.json [FRAME2.json ...] [--time T]
                                          a missing or unreadable FRAME.json is started
                                          from {} with "rpicam_metadata": "missing"/"invalid"
    sunset-sun.py dense     [--time T]    exit 0 and "sunrise"/"sunset" inside a
                                          1-a-minute window, exit 1 and "none" outside
    sunset-sun.py view      [--time T]    exit 0 and "in ..." if the sun is in the camera's view
                                          (plus VIEW_MARGIN), exit 1 and "out ..." if not
    sunset-sun.py view-calendar [--from YYYY-MM-DD] [--days N]
                                          each day the sun is in view: first and last minute,
                                          in UTC and Vancouver time, and its elevation

The view (#32) comes from VIEW_BEARING (true degrees at the frame centre), VIEW_HFOV and
VIEW_VFOV (degrees), VIEW_TILT (degrees up at the centre, default 0) and VIEW_MARGIN (degrees
added on every side, default 3), as a rectilinear lens with no roll. With VIEW_BEARING set,
annotate also writes Sun.in_view and the sun's offset from the centre (view_x_deg right,
view_y_deg up; null when it is behind the camera). Unset, nothing changes. The sun only counts
as in view above the horizon (elevation > 0). This says when; it does not protect the sensor,
which has the sun on it whenever the sun is in view, whether or not a frame is being taken.

Site comes from --lat/--lon or the SITE_LAT / SITE_LON environment variables
(sunset.env). T is ISO 8601 (2026-12-21T16:00:00Z) or the filename form
(20261221T160000Z); default is now. "sunset" prints the NEXT sunset after T, which
is what a burst scheduler wants; run it before sunset for "tonight's".
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
SUNSET_ZENITH = 90.833
DENSE_DARK_DEG = -9.0      # dense windows reach out to the sun at this elevation
DENSE_DAY_MIN = 60         # and this far into the day from sunrise / sunset
# Names the formula behind the Sun block. Change it whenever the numbers a frame would get change
# (formula, sunset zenith, refraction), so frames from before and after can be told apart.
ALGORITHM = "noaa-1"


def parse_time(text):
    """Parse 2026-12-21T16:00:00Z, 20261221T160000Z or an offset form; returns aware UTC."""
    if text is None:
        return datetime.now(UTC)
    t = text.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(t, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    try:  # offsets like +00:00 (Python < 3.11 cannot parse a trailing Z itself)
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ValueError("unrecognised time %r" % text)
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)


def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def julian_day(dt):
    dt = dt.astimezone(UTC)
    y, m = dt.year, dt.month
    day = dt.day + (dt.hour + (dt.minute + (dt.second + dt.microsecond / 1e6) / 60.0) / 60.0) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + b - 1524.5


def solar_declination_eqtime(jd):
    """Return (declination deg, equation of time minutes) for a Julian day."""
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
         + math.sin(3 * mr) * 0.000289)
    omega = 125.04 - 1934.136 * t
    app_long = l0 + c - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    seconds = 21.448 - t * (46.8150 + t * (0.00059 - t * 0.001813))
    eps = 23.0 + (26.0 + seconds / 60.0) / 60.0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(app_long))))
    y = math.tan(math.radians(eps / 2.0)) ** 2
    l0r = math.radians(l0)
    eqtime = 4.0 * math.degrees(
        y * math.sin(2 * l0r) - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    return decl, eqtime


def refraction_deg(elev):
    """Atmospheric refraction (NOAA approximation), degrees to add to geometric elevation."""
    if elev > 85.0:
        return 0.0
    te = math.tan(math.radians(elev))
    if elev > 5.0:
        sec = 58.1 / te - 0.07 / te ** 3 + 0.000086 / te ** 5
    elif elev > -0.575:
        sec = 1735.0 + elev * (-518.2 + elev * (103.4 + elev * (-12.79 + elev * 0.711)))
    else:
        sec = -20.772 / te
    return sec / 3600.0


def sun_position(dt, lat, lon):
    """Return (azimuth, elevation) in degrees; lon is east-positive (Vancouver ~ -123)."""
    dt = dt.astimezone(UTC)
    decl, eqtime = solar_declination_eqtime(julian_day(dt))
    minutes = dt.hour * 60.0 + dt.minute + dt.second / 60.0 + dt.microsecond / 6e7
    hour_angle = ((minutes + eqtime + 4.0 * lon) % 1440.0) / 4.0 - 180.0
    latr, declr, har = math.radians(lat), math.radians(decl), math.radians(hour_angle)
    cos_zen = math.sin(latr) * math.sin(declr) + math.cos(latr) * math.cos(declr) * math.cos(har)
    cos_zen = max(-1.0, min(1.0, cos_zen))
    zen = math.degrees(math.acos(cos_zen))
    sin_zen = math.sin(math.radians(zen))
    if sin_zen < 1e-9:
        az = 180.0
    else:
        cos_az = (math.sin(latr) * cos_zen - math.sin(declr)) / (math.cos(latr) * sin_zen)
        az_ref = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
        az = (az_ref + 180.0) % 360.0 if hour_angle > 0 else (540.0 - az_ref) % 360.0
    elev = 90.0 - zen
    return az, elev + refraction_deg(elev)


def _sunset_for_noon_day(day, lat, lon, sign=1):
    """Sunset (sign=1) or sunrise (sign=-1) of the solar day whose noon falls on UTC date `day`
    (datetime at 00:00Z). Both use the same sun height, so they match each other."""
    minutes = 720.0 - 4.0 * lon
    for _ in range(4):  # decl/eqtime move slowly; 3-4 passes converge to seconds
        decl, eqtime = solar_declination_eqtime(julian_day(day + timedelta(minutes=minutes)))
        latr, declr = math.radians(lat), math.radians(decl)
        cos_h = ((math.cos(math.radians(SUNSET_ZENITH)) - math.sin(latr) * math.sin(declr))
                 / (math.cos(latr) * math.cos(declr)))
        if cos_h < -1.0 or cos_h > 1.0:
            return None  # polar day / night
        h = math.degrees(math.acos(cos_h))
        minutes = 720.0 - 4.0 * lon - eqtime + sign * 4.0 * h
    return day + timedelta(minutes=minutes)


def sunsets_around(dt, lat, lon, span=2, sign=1):
    midnight = dt.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for d in range(-span, span + 1):
        s = _sunset_for_noon_day(midnight + timedelta(days=d), lat, lon, sign)
        if s is not None:
            out.append(s)
    return sorted(out)


def next_sunrise(after, lat, lon):
    for s in sunsets_around(after, lat, lon, sign=-1):
        if s > after:
            return s
    return None


def dense_window(dt, lat, lon):
    """"sunrise" from the sun at DENSE_DARK_DEG until DENSE_DAY_MIN after sunrise, "sunset" from
    DENSE_DAY_MIN before sunset until the sun is down to DENSE_DARK_DEG, otherwise None."""
    if sun_position(dt, lat, lon)[1] < DENSE_DARK_DEG:
        return None
    day = timedelta(minutes=DENSE_DAY_MIN)
    dark = timedelta(hours=3)   # the sun reaches -9 deg well within this of sunrise/sunset here
    for rise in sunsets_around(dt, lat, lon, span=1, sign=-1):
        if rise - dark <= dt <= rise + day:
            return "sunrise"
    for sset in sunsets_around(dt, lat, lon, span=1):
        if sset - day <= dt <= sset + dark:
            return "sunset"
    return None


def next_sunset(after, lat, lon):
    for s in sunsets_around(after, lat, lon):
        if s > after:
            return s
    return None


def nearest_sunset(dt, lat, lon):
    cands = sunsets_around(dt, lat, lon)
    return min(cands, key=lambda s: abs((s - dt).total_seconds())) if cands else None


VIEW_DEFAULT_MARGIN = 3.0
VIEW_MIN_ELEVATION = 0.0    # at or below this the sun is behind the ground or the far horizon


def view_offset(az, el, bearing, tilt):
    """(right, up) angles in degrees of the direction (az, el) as seen by a camera aimed at
    (bearing, tilt) with no roll, for a rectilinear lens; None if it is behind the camera."""
    def vec(a, e):
        a, e = math.radians(a), math.radians(e)
        return (math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e))   # east, north, up

    def dot(p, q):
        return p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
    s, f = vec(az, el), vec(bearing, tilt)
    b = math.radians(bearing)
    r = (math.cos(b), -math.sin(b), 0.0)                                   # level, to the right
    u = (r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0])   # r x f
    depth = dot(s, f)
    if depth <= 1e-9:
        return None
    return math.degrees(math.atan(dot(s, r) / depth)), math.degrees(math.atan(dot(s, u) / depth))


def in_view(az, el, view):
    """True if the sun at (az, el) is above the horizon and inside the view plus its margin."""
    if el <= VIEW_MIN_ELEVATION:
        return False
    off = view_offset(az, el, view["bearing"], view["tilt"])
    if off is None:
        return False
    return (abs(off[0]) <= view["hfov"] / 2.0 + view["margin"]
            and abs(off[1]) <= view["vfov"] / 2.0 + view["margin"])


def view_from_env(env=None):
    """The camera's view from the VIEW_* settings, or None when VIEW_BEARING is unset."""
    env = os.environ if env is None else env
    if env.get("VIEW_BEARING", "") == "":
        return None

    def num(name, default=None, lo=None, hi=None):
        text = env.get(name, "")
        if text == "" and default is not None:
            return default
        try:
            value = float(text)
        except ValueError:
            raise ValueError("%s must be a number, not %r" % (name, text))
        if math.isnan(value) or value < lo or value > hi:
            raise ValueError("%s=%s is out of range (%g to %g)" % (name, text, lo, hi))
        return value
    return {"bearing": num("VIEW_BEARING", lo=0, hi=360), "hfov": num("VIEW_HFOV", lo=0.1, hi=179),
            "vfov": num("VIEW_VFOV", lo=0.1, hi=179), "tilt": num("VIEW_TILT", 0.0, -90, 90),
            "margin": num("VIEW_MARGIN", VIEW_DEFAULT_MARGIN, 0, 45)}


def vancouver(dt):
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/Vancouver"))
    except Exception:       # no tz database: UTC-7, Vancouver's offset all year since 2026
        return dt.astimezone(timezone(timedelta(hours=-7)))


def view_calendar(start, days, lat, lon, view, step_min=1):
    """One dict per day from start (a date) with the minutes the sun is in view, scanned from 16:00
    UTC that day to 16:00 UTC the next (morning to morning in Vancouver, so an evening is one day)."""
    out = []
    for i in range(days):
        day = start + timedelta(days=i)
        t0 = datetime(day.year, day.month, day.day, 16, 0, tzinfo=UTC)
        hits = []
        for m in range(0, 24 * 60, step_min):
            t = t0 + timedelta(minutes=m)
            az, el = sun_position(t, lat, lon)
            if in_view(az, el, view):
                hits.append((t, el))
        row = {"date": day.isoformat(), "minutes": len(hits) * step_min}
        if hits:
            row.update(first_utc=iso(hits[0][0]), last_utc=iso(hits[-1][0]),
                       min_el=round(min(e for _, e in hits), 2), max_el=round(max(e for _, e in hits), 2))
        out.append(row)
    return out


def sun_block(dt, lat, lon, view=None):
    """The dict stored under "Sun" in each frame's JSON.

    It holds no lat/lon, but its exact angles and times locate the site to about 30 m (#25),
    so frame JSON is private: strip this block before publishing any JSON.
    """
    az, el = sun_position(dt, lat, lon)
    block = {"azimuth_deg": round(az, 2), "elevation_deg": round(el, 2),
             "azimuth_ref": "true_north", "computed_for_utc": iso(dt), "algorithm": ALGORITHM}
    near = nearest_sunset(dt, lat, lon)
    if near is not None:
        block["nearest_sunset_utc"] = iso(near)
        block["minutes_from_sunset"] = round((dt - near).total_seconds() / 60.0, 1)
    if view is not None:
        off = view_offset(az, el, view["bearing"], view["tilt"])
        block["in_view"] = in_view(az, el, view)
        block["view_x_deg"] = None if off is None else round(off[0], 2)
        block["view_y_deg"] = None if off is None else round(off[1], 2)
    return block


def load_frame_json(path):
    """rpicam's metadata for a frame, and None or why it could not be used: "missing" or "invalid".
    The Sun and Capture blocks don't need it, so a frame without it still gets a JSON file."""
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}, "missing"
    except ValueError:      # includes a half-written file
        return {}, "invalid"
    if not isinstance(data, dict):
        return {}, "invalid"
    return data, None


def annotate(path, dt, lat, lon, view=None):
    data, problem = load_frame_json(path)
    if problem:
        data["rpicam_metadata"] = problem
    data["Sun"] = sun_block(dt, lat, lon, view)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=4)
        f.write("\n")
    os.replace(tmp, path)
    return data["Sun"], data.get("rpicam_metadata")


def site(args):
    lat = args.lat if args.lat is not None else os.environ.get("SITE_LAT")
    lon = args.lon if args.lon is not None else os.environ.get("SITE_LON")
    if lat in (None, "") or lon in (None, ""):
        raise ValueError("site not set: pass --lat/--lon or set SITE_LAT/SITE_LON in sunset.env")
    lat, lon = float(lat), float(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("site out of range: lat=%s lon=%s" % (lat, lon))
    return lat, lon


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float, help="east-positive, so Burnaby is negative")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("position")
    sp.add_argument("--time")
    ss = sub.add_parser("sunset")
    ss.add_argument("--after")
    g = ss.add_mutually_exclusive_group()
    g.add_argument("--epoch", action="store_true", help="print Unix seconds")
    g.add_argument("--json", action="store_true")
    sd = sub.add_parser("dense")
    sd.add_argument("--time")
    sa = sub.add_parser("annotate")
    sa.add_argument("files", nargs="+")
    sa.add_argument("--time")
    sv = sub.add_parser("view")
    sv.add_argument("--time")
    sc = sub.add_parser("view-calendar")
    sc.add_argument("--from", dest="start", help="YYYY-MM-DD, default today (UTC)")
    sc.add_argument("--days", type=int, default=365)
    args = p.parse_args(argv)
    try:
        lat, lon = site(args)
        if args.cmd == "position":
            dt = parse_time(args.time)
            az, el = sun_position(dt, lat, lon)
            print(json.dumps({"time_utc": iso(dt), "azimuth_deg": round(az, 2),
                              "elevation_deg": round(el, 2)}))
        elif args.cmd == "sunset":
            after = parse_time(args.after)
            s = next_sunset(after, lat, lon)
            if s is None:
                print("no sunset found", file=sys.stderr)
                return 1
            if args.epoch:
                print(int(s.timestamp()))
            elif args.json:
                az, _ = sun_position(s, lat, lon)
                print(json.dumps({"sunset_utc": iso(s), "epoch": int(s.timestamp()),
                                  "azimuth_deg": round(az, 2), "after_utc": iso(after)}))
            else:
                print(iso(s))
        elif args.cmd in ("view", "view-calendar"):
            view = view_from_env()
            if view is None:
                raise ValueError("no view set: VIEW_BEARING, VIEW_HFOV and VIEW_VFOV in sunset.env")
            if args.cmd == "view":
                dt = parse_time(args.time)
                az, el = sun_position(dt, lat, lon)
                off = view_offset(az, el, view["bearing"], view["tilt"])
                inside = in_view(az, el, view)
                xy = "x=na y=na" if off is None else "x=%.1f y=%.1f" % off
                print("%s az=%.1f el=%.1f %s" % ("in" if inside else "out", az, el, xy))
                return 0 if inside else 1
            start = (datetime.strptime(args.start, "%Y-%m-%d").date() if args.start
                     else datetime.now(UTC).date())
            rows = [r for r in view_calendar(start, args.days, lat, lon, view) if r["minutes"]]
            print("# view: bearing %(bearing)g, %(hfov)g x %(vfov)g deg, tilt %(tilt)g, margin %(margin)g" % view)
            print("# %d of %d days have the sun in view" % (len(rows), args.days))
            for r in rows:
                a, b = parse_time(r["first_utc"]), parse_time(r["last_utc"])
                print("%s  %s-%s UTC  %s-%s Vancouver  %3d min  el %.1f to %.1f" % (
                    r["date"], a.strftime("%H:%M"), b.strftime("%H:%M"), vancouver(a).strftime("%H:%M"),
                    vancouver(b).strftime("%H:%M"), r["minutes"], r["min_el"], r["max_el"]))
        elif args.cmd == "dense":
            window = dense_window(parse_time(args.time), lat, lon)
            print(window or "none")
            return 0 if window else 1
        else:
            dt = parse_time(args.time)
            problems = []
            view = view_from_env()
            for path in args.files:
                b, problem = annotate(path, dt, lat, lon, view)
                if problem and problem not in problems:
                    problems.append(problem)
            # One short line for the capture log.
            print("az=%.1f el=%.1f" % (b["azimuth_deg"], b["elevation_deg"])
                  + "".join(" rpicam=%s" % p for p in problems))
    except (ValueError, OSError) as exc:
        print("sunset-sun.py: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
