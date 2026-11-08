#!/usr/bin/env python3
"""Pilot experiments: extra test shots between the real captures.

Results go to experiments/runs/<run>/ and then to a NAS folder of their own, never to the outbox
or the production NAS folder, so the regular series and anything reading it are untouched. Real
captures always win: no shot starts unless it will finish before the next 5-minute slot, and
the runner waits while diag or a real capture has the camera.

    sunset-experiment.py night --run night-1
    sunset-experiment.py settle --run settle-night
    sunset-experiment.py day --run day-1 --sunset <epoch> --until <epoch> [--sunrise <epoch>] [--settle-at <epoch>]
    sunset-experiment.py rate-night --run rate-night-1 --until <epoch>
    sunset-experiment.py night-sweep --run sweep-1 --until <epoch>
"""
import argparse
import csv
import dataclasses
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
EXP_ROOT = HERE / "runs"
NAS_EXP_ROOT = "/mnt/nas-camera/project_sunshine_experiments/"
SUN_PY = HERE.parent / "sunset-sun.py"
ENV_FILE = HERE.parent / "sunset.env"
LOCK_FILE = HERE / ".experiment.lock"

SLOT_S = 300  # must match OnCalendar in pi/systemd/sunset-capture.timer
AFTER_SLOT_S = 45  # the real capture took 17 s with a night frame; leave it plenty of room
BEFORE_SLOT_S = 5
SUNSET_WINDOW_S = 45 * 60
SUN_LADDER_BEFORE_S = 5 * 3600
DUSK_FROM_S = 600
DUSK_EVERY_S = 300
DUSK_POINTS = 9  # +10 to +50 minutes after sunset
DUSK_MS = (250, 500, 1000, 2000, 4000)
DAY_SWEEP_MINUTE = 21  # past each hour, clear of the real captures
NIGHT_SWEEP_EVERY_S = 2 * 3600
NIGHT_AWB = "2.25,2.40"
MIN_SD_FREE_GB = 5
MIN_NAS_FREE_GB = 50
UPLOAD_EVERY_S = 1800
MAX_FAILURES = 3  # failed shots in a row before the runner leaves the camera alone
HOLD_OFF_S = 1800


def clear_to_start(now, est_s):
    """True if a shot taking est_s can start now and finish clear of the real captures."""
    phase = now % SLOT_S
    if phase < AFTER_SLOT_S:
        return False
    return phase + est_s + BEFORE_SLOT_S < SLOT_S


def estimate_s(shutter_us):
    """Pessimistic shot time. Fixed long exposures take several frames at that shutter."""
    return 6 + 3 * (shutter_us or 0) / 1_000_000


@dataclasses.dataclass
class Shot:
    label: str
    shutter_us: int = None
    gain: float = None
    raw: bool = False
    awbgains: str = None
    ev: int = None
    metering: str = None
    denoise: str = None
    settle_ms: int = 1000
    immediate: bool = False
    extra: tuple = ()  # any other rpicam-still options, such as ("--awb", "tungsten")

    def command(self, base):
        cmd = ["rpicam-still", "-n", "-t", str(self.settle_ms)]
        if self.immediate:
            cmd += ["--immediate"]
        if self.shutter_us:
            cmd += ["--shutter", str(self.shutter_us)]
        if self.gain:
            cmd += ["--gain", str(self.gain)]
        if self.awbgains:
            cmd += ["--awbgains", self.awbgains]
        if self.ev is not None:
            cmd += ["--ev", str(self.ev)]
        if self.metering:
            cmd += ["--metering", self.metering]
        if self.denoise:
            cmd += ["--denoise", self.denoise]
        if self.raw:
            cmd += ["--raw"]
        cmd += list(self.extra)
        return cmd + ["--metadata", base + ".json", "--metadata-format", "json", "-o", base + ".jpg"]


def night_shots():
    """How to expose the dark: ladder, colour gains, stack versus one long frame, denoise, EV."""
    shots = []
    for shutter_ms in (500, 1000, 2000, 4000, 8000):
        for gain in (1, 2, 4):
            shots.append(Shot(f"ladder-{shutter_ms}ms-g{gain}", shutter_us=shutter_ms * 1000,
                              gain=gain, raw=True, awbgains="2.07,2.28"))
    for gains in ("1.6,1.8", "2.07,2.28"):
        shots.append(Shot("colour-" + gains.replace(",", "-"), shutter_us=2_000_000, gain=2,
                          awbgains=gains))
    shots.append(Shot("colour-auto", shutter_us=2_000_000, gain=2))
    for i in range(8):
        shots.append(Shot(f"stack-{i}", shutter_us=1_000_000, gain=2, awbgains="2.07,2.28"))
    for mode in ("cdn_off", "cdn_hq"):
        shots.append(Shot("denoise-" + mode, shutter_us=2_000_000, gain=2, awbgains="2.07,2.28",
                          denoise=mode))
    for ev in (1, 2):
        shots.append(Shot(f"auto-ev+{ev}", ev=ev))
    return shots


def tuning_shots(prefix="", **fixed):
    """Contrast, saturation and sharpness above and below normal."""
    shots = []
    for option, values in (("contrast", ("0.8", "1.2")), ("saturation", ("0.8", "1.2")),
                           ("sharpness", ("0.5", "2"))):
        for value in values:
            shots.append(Shot(f"{prefix}{option}-{value}", extra=(f"--{option}", value), **fixed))
    return shots


NIGHT_SHUTTERS_MS = (100, 250, 500, 1000, 2000, 4000, 6000, 8000, 10000, 15000, 20000, 30000)
NIGHT_GAINS = (1, 1.5, 2, 3, 4, 6, 8)
NIGHT_RED_GAINS = ("1.6", "1.8", "2.0", "2.2", "2.4", "2.6")
NIGHT_BLUE_GAINS = ("1.6", "1.9", "2.2", "2.5", "2.8")
NIGHT_TUNING = (("contrast", ("0.6", "0.8", "1.0", "1.2", "1.4")),
                ("saturation", ("0.6", "0.8", "1.0", "1.2", "1.4")),
                ("sharpness", ("0", "0.5", "1.0", "1.5", "2.0")))


def night_sweep_shots():
    """Experiment 14: every setting across a range, so one night covers all of it."""
    shots = []
    for shutter_ms in NIGHT_SHUTTERS_MS:
        for gain in NIGHT_GAINS:
            raw = gain == 1 and shutter_ms in (4000, 8000)
            shots.append(Shot(f"ladder-{shutter_ms}ms-g{gain:g}", shutter_us=shutter_ms * 1000,
                              gain=gain, raw=raw, awbgains=NIGHT_AWB))
    base = {"shutter_us": 4_000_000, "gain": 1}
    for red in NIGHT_RED_GAINS:
        for blue in NIGHT_BLUE_GAINS:
            shots.append(Shot(f"gains-{red}-{blue}", awbgains=f"{red},{blue}", **base))
    shots.append(Shot("gains-" + NIGHT_AWB.replace(",", "-"), awbgains=NIGHT_AWB, **base))
    for mode in ("auto", "incandescent", "tungsten", "fluorescent", "indoor", "daylight", "cloudy"):
        shots.append(Shot(f"awb-{mode}", extra=("--awb", mode), **base))
    for mode in ("auto", "off", "cdn_off", "cdn_fast", "cdn_hq"):
        for seconds in (2, 4, 8):
            shots.append(Shot(f"denoise-{mode}-{seconds}s", shutter_us=seconds * 1_000_000, gain=1,
                              awbgains=NIGHT_AWB, denoise=mode))
    for option, values in NIGHT_TUNING:
        for value in values:
            shots.append(Shot(f"{option}-{value}", awbgains=NIGHT_AWB, extra=(f"--{option}", value),
                              **base))
    return shots


def sweep_due(now, last, every):
    return last is None or now - last >= every


def day_sweep_shots():
    """Experiment 15: one set of daylight settings, all on auto exposure."""
    shots = [Shot("sweep-ev-1", ev=-1), Shot("sweep-ev-0.5", ev=-0.5), Shot("sweep-ev+0.5", ev=0.5),
             Shot("sweep-meter-average", metering="average"), Shot("sweep-meter-spot", metering="spot"),
             Shot("sweep-awb-daylight", extra=("--awb", "daylight")),
             Shot("sweep-awb-cloudy", extra=("--awb", "cloudy")),
             Shot("sweep-denoise-off", denoise="off"), Shot("sweep-denoise-cdn_hq", denoise="cdn_hq")]
    return shots + tuning_shots(prefix="sweep-")


def settle_shots():
    """How steady is auto exposure, and how long must it settle? Five of each, same light."""
    shots = []
    for name, ms, immediate in (("immediate", 0, True), ("300", 300, False),
                                ("1000", 1000, False), ("3000", 3000, False)):
        for i in range(5):
            shots.append(Shot(f"settle-{name}-{i}", settle_ms=ms, immediate=immediate))
    return shots


def ladder_due(minute, moments):
    """True if this minute is the one a twilight ladder moment lands on."""
    for moment in moments:
        due = moment + (-moment % 60)
        if due % SLOT_S < 60:
            due += 60  # the real capture has this minute
        if due == minute:
            return True
    return False


def dusk_shots(minute, sunset):
    """Experiment 13: fixed exposures through the gap between auto's limit and the night frame."""
    moments = [sunset + DUSK_FROM_S + point * DUSK_EVERY_S for point in range(DUSK_POINTS)]
    if ladder_due(minute, moments):
        return [Shot(f"dusk-{ms}ms", shutter_us=ms * 1000, gain=1) for ms in DUSK_MS]
    return []


def dawn_shots(minute, sunrise):
    """Experiment 16: the same ladder through the gap before sunrise."""
    if sunrise is None:
        return []
    moments = [sunrise - DUSK_FROM_S - point * DUSK_EVERY_S for point in range(DUSK_POINTS)]
    if ladder_due(minute, moments):
        return [Shot(f"dawn-{ms}ms", shutter_us=ms * 1000, gain=1) for ms in DUSK_MS]
    return []


def day_shots(minute, sunset, sunrise=None):
    """What to take in one minute of the day program."""
    if minute % SLOT_S < 60:
        return []  # the real capture is this minute's frame
    twilight = dusk_shots(minute, sunset) + dawn_shots(minute, sunrise)
    near_sunrise = sunrise is not None and abs(minute - sunrise) <= SUNSET_WINDOW_S
    if abs(minute - sunset) <= SUNSET_WINDOW_S or near_sunrise:
        five = (minute - 60) % 300 < 60   # the minute after each regular capture
        shots = [Shot("ev-2", ev=-2), Shot("ev+0", ev=0, raw=five), Shot("ev+2", ev=2)]
        if five:
            shots += [Shot("meter-average", metering="average"),
                      Shot("meter-spot", metering="spot"),
                      Shot("ev-1", ev=-1),
                      Shot("awb-daylight", extra=("--awb", "daylight")),
                      Shot("awb-cloudy", extra=("--awb", "cloudy"))]
            if minute < sunset:
                # Experiment 7: at the pilot-3 framing the sun only enters the frame in the last
                # ~30 minutes, so the fixed short exposures carry on until it sets.
                shots += [Shot("sun-100us", shutter_us=100, gain=1),
                          Shot("sun-500us", shutter_us=500, gain=1)]
        return shots + twilight
    shots = [Shot("rate")]
    if sunset - SUN_LADDER_BEFORE_S <= minute < sunset - SUNSET_WINDOW_S and (minute - 60) % 600 < 60:
        half = minute % 1800 < 60
        shots += [Shot("sun-100us", shutter_us=100, gain=1),
                  Shot("sun-500us", shutter_us=500, gain=1),
                  Shot("sun-2ms", shutter_us=2000, gain=1, raw=half)]
    if minute % 3600 == DAY_SWEEP_MINUTE * 60:
        shots += day_sweep_shots()
    return shots + twilight


def night_rate_shots(minute):
    """One fixed frame a minute at night, at the night frame's setting."""
    if minute % SLOT_S < 60:
        return []
    return [Shot("rate-night", shutter_us=4_000_000, gain=1, awbgains=NIGHT_AWB)]


def read_text(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def camera_busy():
    for name in ("rpicam-vid", "rpicam-still"):
        if subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0:
            return True
    if read_text(["systemctl", "is-active", "sunset-diag.service"]) == "active":
        return True  # someone may be looking at the page; the stream comes first
    return read_text(["systemctl", "is-active", "sunset-capture.service"]) in ("active", "activating")


def load_site_env():
    """Coordinates for the sun data. They stay in the Pi's sunset.env, never in results."""
    try:
        lines = ENV_FILE.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line.startswith(("SITE_LAT=", "SITE_LON=")):
            key, value = line.split("=", 1)
            os.environ[key] = value.strip().strip("\"'")


class FailureGuard:
    """Stops retrying a camera that keeps failing. A hung shot holds the camera for a minute or
    more, long enough to take it away from a real capture, so it gets one try per hold-off."""

    def __init__(self):
        self.failures = 0
        self.hold_until = 0

    def allowed(self, now):
        return now >= self.hold_until

    def note(self, ok, now):
        self.failures = 0 if ok else self.failures + 1
        if self.failures >= MAX_FAILURES:
            self.hold_until = now + HOLD_OFF_S


class Run:
    def __init__(self, name):
        self.name = name
        self.dir = EXP_ROOT / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.dir / "manifest.csv"
        self.last_upload = time.time()
        self.guard = FailureGuard()

    def record(self, **row):
        fields = ["utc", "label", "status", "seconds", "bytes", "exposure_us", "analogue_gain",
                  "digital_gain", "lux", "colour_gains", "sun_az", "sun_el", "throttled", "temp"]
        new = not self.manifest.exists()
        with self.manifest.open("a", newline="") as f:
            writer = csv.DictWriter(f, fields)
            if new:
                writer.writeheader()
            writer.writerow(row)

    def take(self, shot, max_wait_s):
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        if not self.guard.allowed(time.time()):
            self.record(utc=stamp, label=shot.label, status="skipped: camera failing")
            return
        est = estimate_s(shot.shutter_us)
        waited = time.time()
        while not clear_to_start(time.time(), est) or camera_busy():
            if time.time() - waited > max_wait_s:
                self.record(utc=stamp, label=shot.label, status="skipped: camera not clear")
                return
            time.sleep(2)
        if shutil.disk_usage(self.dir).free < MIN_SD_FREE_GB * 1024 ** 3:
            self.record(utc=stamp, label=shot.label, status="skipped: SD low")
            return
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        base = str(self.dir / f"{shot.label}_{stamp}")
        started = time.time()
        try:
            rc = subprocess.run(shot.command(base), capture_output=True,
                                timeout=60 + 4 * (shot.shutter_us or 0) / 1e6).returncode
            status = "ok" if rc == 0 else f"failed rc={rc}"
        except subprocess.TimeoutExpired:
            status = "failed timeout"
        self.guard.note(status == "ok", time.time())
        seconds = round(time.time() - started, 1)
        meta, sun = {}, {}
        try:
            read_text(["python3", str(SUN_PY), "annotate", base + ".json", "--time", stamp])
            meta = json.loads(pathlib.Path(base + ".json").read_text())
            sun = meta.get("Sun") or {}
        except (OSError, ValueError):
            pass
        size = sum(p.stat().st_size for p in self.dir.glob(f"{shot.label}_{stamp}.*"))
        self.record(utc=stamp, label=shot.label, status=status, seconds=seconds, bytes=size,
                    exposure_us=meta.get("ExposureTime"), analogue_gain=meta.get("AnalogueGain"),
                    digital_gain=meta.get("DigitalGain"), lux=meta.get("Lux"),
                    colour_gains=meta.get("ColourGains"),
                    sun_az=sun.get("azimuth_deg"), sun_el=sun.get("elevation_deg"),
                    throttled=read_text(["vcgencmd", "get_throttled"]).split("=")[-1],
                    temp=read_text(["vcgencmd", "measure_temp"]).split("=")[-1])

    def upload(self):
        """Copy to the NAS, removing each frame only after rsync confirms it. Never fatal."""
        self.last_upload = time.time()
        root = pathlib.Path(NAS_EXP_ROOT)
        try:
            os.listdir("/mnt/nas-camera")  # wake the automount
            if os.stat("/mnt/nas-camera").st_dev == os.stat(self.dir).st_dev:
                raise OSError("share not mounted")
            if shutil.disk_usage("/mnt/nas-camera").free < MIN_NAS_FREE_GB * 1024 ** 3:
                raise OSError("NAS below the free-space floor, keeping results on the SD card")
            target = root / self.name
            target.mkdir(parents=True, exist_ok=True)
            subprocess.run(["rsync", "-rt", "--remove-source-files", "--exclude", "manifest.csv",
                            f"{self.dir}/", f"{target}/"], check=True, capture_output=True,
                           timeout=1800)
            subprocess.run(["rsync", "-t", str(self.manifest), f"{target}/"], check=True,
                           capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"upload failed, results stay on the SD card: {e}", file=sys.stderr)


def run_rate_night(run, until):
    while time.time() < until:
        minute = int(time.time()) // 60 * 60
        for shot in night_rate_shots(minute):
            run.take(shot, max_wait_s=30)
        if time.time() - run.last_upload > UPLOAD_EVERY_S:
            run.upload()
        time.sleep(max(0, minute + 60 - time.time()))


def run_night_sweep(run, until):
    last = None
    while time.time() < until:
        if sweep_due(time.time(), last, NIGHT_SWEEP_EVERY_S):
            last = time.time()
            for shot in night_sweep_shots():
                if time.time() >= until:
                    break
                run.take(shot, max_wait_s=900)
            run.upload()
        minute = int(time.time()) // 60 * 60
        for shot in night_rate_shots(minute):
            run.take(shot, max_wait_s=30)
        if time.time() - run.last_upload > UPLOAD_EVERY_S:
            run.upload()
        time.sleep(max(0, minute + 60 - time.time()))


def run_day(run, sunset, until, settle_at, sunrise=None):
    while time.time() < until:
        minute = int(time.time()) // 60 * 60
        if settle_at and time.time() >= settle_at:
            settle_at = None
            for shot in settle_shots():
                run.take(shot, max_wait_s=120)
        else:
            for shot in day_shots(minute, sunset, sunrise):
                run.take(shot, max_wait_s=30)
        if time.time() - run.last_upload > UPLOAD_EVERY_S:
            run.upload()
        time.sleep(max(0, minute + 60 - time.time()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", choices=["night", "settle", "day", "rate-night", "night-sweep"])
    parser.add_argument("--run", required=True)
    parser.add_argument("--sunset", type=int)
    parser.add_argument("--sunrise", type=int)
    parser.add_argument("--until", type=int)
    parser.add_argument("--settle-at", type=int)
    args = parser.parse_args()

    import fcntl  # Linux only; the scheduling above is tested on any machine

    load_site_env()
    LOCK_FILE.touch()
    with LOCK_FILE.open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one program at a time; a late start just waits
        run = Run(args.run)
        if args.program == "day":
            run_day(run, args.sunset, args.until, args.settle_at, args.sunrise)
        elif args.program == "rate-night":
            run_rate_night(run, args.until)
        elif args.program == "night-sweep":
            run_night_sweep(run, args.until)
        else:
            for shot in night_shots() if args.program == "night" else settle_shots():
                run.take(shot, max_wait_s=900)
        run.upload()


if __name__ == "__main__":
    main()
