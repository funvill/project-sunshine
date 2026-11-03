#!/usr/bin/env python3
"""Sun position and sunset time with no network and no dependencies (stdlib only).

Uses the NOAA solar calculator equations (Meeus-based), good to roughly a minute
for sunset and a fraction of a degree for position at this latitude. Azimuth is
degrees clockwise from TRUE north (not magnetic). Elevation includes atmospheric
refraction. "Sunset" is the upper limb touching the horizon (zenith 90.833 deg).

    sunset-sun.py position  [--time T]
    sunset-sun.py sunset    [--after T] [--epoch|--json]
    sunset-sun.py annotate  FRAME.json [FRAME2.json ...] [--time T]

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


def _sunset_for_noon_day(day, lat, lon):
    """Sunset belonging to the solar day whose noon falls on UTC date `day` (datetime at 00:00Z)."""
    minutes = 720.0 - 4.0 * lon
    for _ in range(4):  # decl/eqtime move slowly; 3-4 passes converge to seconds
        decl, eqtime = solar_declination_eqtime(julian_day(day + timedelta(minutes=minutes)))
        latr, declr = math.radians(lat), math.radians(decl)
        cos_h = ((math.cos(math.radians(SUNSET_ZENITH)) - math.sin(latr) * math.sin(declr))
                 / (math.cos(latr) * math.cos(declr)))
        if cos_h < -1.0 or cos_h > 1.0:
            return None  # polar day / night
        h = math.degrees(math.acos(cos_h))
        minutes = 720.0 - 4.0 * lon - eqtime + 4.0 * h
    return day + timedelta(minutes=minutes)


def sunsets_around(dt, lat, lon, span=2):
    midnight = dt.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for d in range(-span, span + 1):
        s = _sunset_for_noon_day(midnight + timedelta(days=d), lat, lon)
        if s is not None:
            out.append(s)
    return sorted(out)


def next_sunset(after, lat, lon):
    for s in sunsets_around(after, lat, lon):
        if s > after:
            return s
    return None


def nearest_sunset(dt, lat, lon):
    cands = sunsets_around(dt, lat, lon)
    return min(cands, key=lambda s: abs((s - dt).total_seconds())) if cands else None


def sun_block(dt, lat, lon):
    """The dict stored under "Sun" in each frame's JSON. Deliberately no lat/lon in it."""
    az, el = sun_position(dt, lat, lon)
    block = {"azimuth_deg": round(az, 2), "elevation_deg": round(el, 2),
             "azimuth_ref": "true_north", "computed_for_utc": iso(dt)}
    near = nearest_sunset(dt, lat, lon)
    if near is not None:
        block["nearest_sunset_utc"] = iso(near)
        block["minutes_from_sunset"] = round((dt - near).total_seconds() / 60.0, 1)
    return block


def annotate(path, dt, lat, lon):
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("%s: top level is not a JSON object" % path)
    data["Sun"] = sun_block(dt, lat, lon)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=4)
        f.write("\n")
    os.replace(tmp, path)
    return data["Sun"]


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
    sa = sub.add_parser("annotate")
    sa.add_argument("files", nargs="+")
    sa.add_argument("--time")
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
        else:
            dt = parse_time(args.time)
            for path in args.files:
                b = annotate(path, dt, lat, lon)
            # One short line for the capture log.
            print("az=%.1f el=%.1f" % (b["azimuth_deg"], b["elevation_deg"]))
    except (ValueError, OSError) as exc:
        print("sunset-sun.py: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
