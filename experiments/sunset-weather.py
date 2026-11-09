#!/usr/bin/env python3
"""Experiment 17: log the weather forecast next to the frames, to test whether it predicts settings.

Once an hour, fetch Open-Meteo's hourly forecast (two models) and air quality for yesterday,
today and tomorrow, and save it as one JSON file in experiments/runs/weather/YYYY/MM/DD/. Then
copy to the NAS experiments folder, removing each file only after rsync confirms it. Standard
library only. Capture does not depend on this: a failed fetch is logged and skipped.

The request uses the site position from sunset.env rounded to 0.1 degrees, and the saved files
have the position fields removed, so they can't place the window.

    sunset-weather.py            fetch, save and upload
    sunset-weather.py --no-upload
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ENV_FILE = HERE.parent / "sunset.env"
OUT_ROOT = HERE / "runs" / "weather"
NAS_ROOT = pathlib.Path("/mnt/nas-camera/project_sunshine_experiments/weather")
MIN_NAS_FREE_GB = 50
TIMEOUT_S = 30

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
FORECAST_FIELDS = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
                   "visibility", "relative_humidity_2m", "dew_point_2m", "temperature_2m",
                   "precipitation", "precipitation_probability", "weather_code",
                   "shortwave_radiation", "direct_radiation", "diffuse_radiation")
AIR_FIELDS = ("pm2_5", "pm10", "aerosol_optical_depth", "dust")
LOCATION_KEYS = ("latitude", "longitude", "elevation")


def read_site(env_text):
    """(lat, lon) from sunset.env text."""
    vals = {}
    for line in env_text.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        vals[key.strip()] = value.strip().strip("'\"")
    try:
        return float(vals["SITE_LAT"]), float(vals["SITE_LON"])
    except (KeyError, ValueError):
        raise ValueError("SITE_LAT and SITE_LON must be set in sunset.env")


def build_urls(lat, lon):
    common = {"latitude": f"{round(lat, 1):.1f}", "longitude": f"{round(lon, 1):.1f}",
              "timezone": "UTC", "past_days": "1", "forecast_days": "2"}
    forecast = dict(common, hourly=",".join(FORECAST_FIELDS), models="best_match,gem_seamless")
    air = dict(common, hourly=",".join(AIR_FIELDS))
    return {"forecast": FORECAST_URL + "?" + urllib.parse.urlencode(forecast, safe=","),
            "air_quality": AIR_URL + "?" + urllib.parse.urlencode(air, safe=",")}


def out_path(root, epoch):
    t = time.gmtime(epoch)
    return root / time.strftime("%Y/%m/%d", t) / time.strftime("forecast_%Y%m%dT%H%M%SZ.json", t)


def http_fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "project-sunshine-timelapse"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.load(r)


def fetch_and_save(lat, lon, root, now, fetch=http_fetch):
    """Fetch both, save one file. 0 if the forecast was saved, 1 if nothing was."""
    saved = {"fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
             "source": "open-meteo", "position": "site rounded to 0.1 degrees, not stored"}
    for name, url in build_urls(lat, lon).items():
        try:
            body = fetch(url)
            for key in LOCATION_KEYS:
                body.pop(key, None)
            saved[name] = body
        except (OSError, ValueError) as e:
            saved[name] = {"error": str(e)}
            print(f"{name} fetch failed: {e}", file=sys.stderr)
    if "error" in saved["forecast"]:
        return 1
    path = out_path(root, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(saved, separators=(",", ":")))
    os.replace(tmp, path)
    print(f"saved {path}")
    return 0


def upload(root):
    """Copy everything waiting to the NAS, removing each file only after rsync confirms it."""
    try:
        os.listdir("/mnt/nas-camera")  # wake the automount
        if os.stat("/mnt/nas-camera").st_dev == os.stat(root).st_dev:
            raise OSError("share not mounted")
        if shutil.disk_usage("/mnt/nas-camera").free < MIN_NAS_FREE_GB * 1024 ** 3:
            raise OSError("NAS below the free-space floor, keeping files on the SD card")
        NAS_ROOT.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rsync", "-rt", "--remove-source-files", "--exclude", "*.tmp",
                        f"{root}/", f"{NAS_ROOT}/"], check=True, capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"upload failed, files stay on the SD card: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    args = ap.parse_args()
    lat, lon = read_site(ENV_FILE.read_text())
    code = fetch_and_save(lat, lon, OUT_ROOT, time.time())
    if not args.no_upload and OUT_ROOT.exists():
        upload(OUT_ROOT)
    return code


if __name__ == "__main__":
    sys.exit(main())
