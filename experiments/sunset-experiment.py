#!/usr/bin/env python3
"""Pilot experiments: extra test shots between the real captures.

Results go to experiments/runs/<run>/ and then to a NAS folder of their own, never to the outbox
or the production NAS folder, so the regular series and anything reading it are untouched. Real
captures always win: no shot starts unless it will finish before the next 5-minute slot, and
the runner waits while diag or a real capture has the camera. Each shot also holds production's
camera lock (~/sunset/.sunset-capture.lock, the file sunset-capture.sh flocks), taken without
waiting, so a shot that overruns makes a regular capture wait for it instead of failing, and a
dense frame skips with "camera busy". A shot is killed SHOT_TIMEOUT_MARGIN_S after its estimate.

The programs left are the questions still open. The night, settle, day, rate-night, night-sweep
and sunset programs were removed on 2026-11-22 once answered (night settings chosen, the sunset
bracket in production); git history has them.

    sunset-experiment.py moon --run moon-1 --until <epoch>

Before the mount is glued (#12), each needs someone at the camera:
    sunset-experiment.py dark --run calib-dark-1 [--count 5]      lens capped, room dark: 4 s and 8 s
                                                                   at gain 1, and bias frames, with DNG
    sunset-experiment.py flat --run calib-flat-1 [--count 9]      even white diffuser over the lens, daylight
    sunset-experiment.py checker --run calib-checker-1 [--count 30] [--every 4]
                                                                   move a printed checkerboard through the view
"""
import argparse
import contextlib
import csv
import dataclasses
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

try:
    import fcntl
except ImportError:  # Windows test runs: no locking, everything else works
    fcntl = None

HERE = pathlib.Path(__file__).resolve().parent
EXP_ROOT = HERE / "runs"
NAS_EXP_ROOT = "/mnt/nas-camera/project_sunshine_experiments/"
SUN_PY = HERE.parent / "sunset-sun.py"
ENV_FILE = HERE.parent / "sunset.env"
LOCK_FILE = HERE / ".experiment.lock"

SLOT_S = 300  # must match OnCalendar in pi/systemd/sunset-capture.timer
AFTER_SLOT_S = 72  # the real capture took 17 s with a night frame, and on the CM4 the second camera's
# starts 30 s after the slot and takes about 20 s more (review 2026-11-21; was 45)
BEFORE_SLOT_S = 5
NIGHT_AWB = "2.25,2.40"
MAX_SD_USED_PCT = 70  # no shots above this, well before production's own disk guard
MIN_SD_FREE_GB = 5  # and never below this much free, whatever the card size
SHOT_TIMEOUT_MARGIN_S = 15  # a shot is killed this long after its estimate (plus settle time)
UPLOAD_JOIN_S = 1800  # longest wait for a copy at the end of a run; the rsync itself allows 3600
MIN_NAS_FREE_GB = 50
UPLOAD_EVERY_S = 1800
MAX_FAILURES = 3  # failed shots in a row before the runner leaves the camera alone
HOLD_OFF_S = 1800
DENSE_AFTER_S = 12  # the production dense frame starts at :00 each minute in its windows
DENSE_BEFORE_S = 3  # and skips itself if the camera is busy, so stay clear of both ends
MINUTE_GUARD_MAX_S = 45  # longer shots are night exposures, only run outside the dense windows


def clear_to_start(now, est_s, period=60):
    """True if a shot taking est_s can start now and finish clear of the real captures. period is
    the gap between dense frames: 60 s with one camera, 30 s with the second camera on, whose dense
    frame starts at :30 (so a shot over about 15 s waits for the night outside the dense windows)."""
    phase = now % SLOT_S
    if phase < AFTER_SLOT_S:
        return False
    if est_s <= MINUTE_GUARD_MAX_S:
        second = now % period
        if second < DENSE_AFTER_S or second + est_s + DENSE_BEFORE_S >= period:
            return False
    return phase + est_s + BEFORE_SLOT_S < SLOT_S


def estimate_s(shutter_us):
    """Pessimistic shot time. Fixed long exposures take several frames at that shutter."""
    return 6 + 3 * (shutter_us or 0) / 1_000_000


def shot_timeout_s(shot):
    """When a shot counts as hung and is killed. Was 60 s plus 4x the shutter, long enough to run
    into the next regular capture."""
    return estimate_s(shot.shutter_us) + shot.settle_ms / 1000 + SHOT_TIMEOUT_MARGIN_S


def sd_low_reason(usage):
    """Why the SD card is too full for experiments, or None. `usage` is shutil.disk_usage()."""
    used_pct = 100.0 * usage.used / max(usage.used + usage.free, 1)   # as df's Use%
    if used_pct > MAX_SD_USED_PCT:
        return f"SD {used_pct:.0f}% used > {MAX_SD_USED_PCT}%"
    if usage.free < MIN_SD_FREE_GB * 1024 ** 3:
        return f"SD {usage.free / 1024 ** 3:.1f} GB free < {MIN_SD_FREE_GB} GB"
    return None


def capture_lock_path():
    """The production capture's lock file: $LOCK_FILE, else ~/sunset/.sunset-capture.lock (this file
    is in ~/sunset/experiments). Not $HOME: the runner may run as root."""
    if os.environ.get("LOCK_FILE"):
        return pathlib.Path(os.environ["LOCK_FILE"])
    return HERE.parent / ".sunset-capture.lock"


class CaptureLock:
    """Production's camera lock, held while a shot has the camera. Never waits for it."""

    def __init__(self, path):
        self.path = str(path)
        self._fd = None
        self.held = False

    def _open(self):
        try:
            return os.open(self.path, os.O_RDONLY)   # flock works on a read-only descriptor
        except FileNotFoundError:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o664)
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                # Run as root, the file must still be writable by the capture's user, whose
                # script opens it for writing (exec 9>) and would fail.
                st = os.stat(os.path.dirname(self.path) or ".")
                os.fchown(fd, st.st_uid, st.st_gid)
            return fd

    def acquire(self):
        """True if this process may use the camera now."""
        if fcntl is None:
            return True
        if self._fd is not None:
            return True
        try:
            fd = self._open()
        except OSError as e:
            print(f"cannot open the capture lock {self.path}: {e}; shooting without it", file=sys.stderr)
            return True
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        self.held = True
        return True

    def release(self):
        fd, self._fd = self._fd, None
        self.held = False
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


@contextlib.contextmanager
def experiment_lock(path):
    """One program at a time; a late start just waits."""
    path.touch()
    with path.open() as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


@dataclasses.dataclass
class Shot:
    label: str
    shutter_us: int = None
    gain: float = None
    raw: bool = False
    awbgains: str = None
    settle_ms: int = 1000
    extra: tuple = ()  # any other rpicam-still options, such as ("--awb", "tungsten")

    def command(self, base):
        cmd = ["rpicam-still", "-n", "-t", str(self.settle_ms)]
        if os.environ.get("CAM_INDEX", "").strip():   # from CAMERA in sunset.env, see camera_index
            cmd += ["--camera", os.environ["CAM_INDEX"].strip()]
        if os.environ.get("ROTATION", "").strip() == "180":  # camera mounted upside down
            cmd += ["--rotation", "180"]
        if self.shutter_us:
            cmd += ["--shutter", str(self.shutter_us)]
        if self.gain:
            cmd += ["--gain", str(self.gain)]
        if self.awbgains:
            cmd += ["--awbgains", self.awbgains]
        if self.raw:
            cmd += ["--raw"]
        cmd += list(self.extra)
        return cmd + ["--metadata", base + ".json", "--metadata-format", "json", "-o", base + ".jpg"]


CALIB_DARK_MS = (4000, 8000)   # the night exposures in use (timelaps 4 s, the CM4 8 s)
CALIB_BIAS_US = 100             # about the shortest shutter: the sensor's offset and read noise only
CHECKER_EVERY_S = 4


def dark_shots(count=5):
    """Lens capped, room dark (#12): the sensor's own dark level and hot pixels at the night
    exposures, plus bias frames, as a baseline to tell sensor ageing from scene change."""
    shots = []
    for ms in CALIB_DARK_MS:
        shots += [Shot(f"dark-{ms}ms-{i}", shutter_us=ms * 1000, gain=1, raw=True, awbgains=NIGHT_AWB)
                  for i in range(count)]
    shots += [Shot(f"bias-{i}", shutter_us=CALIB_BIAS_US, gain=1, raw=True, awbgains=NIGHT_AWB)
              for i in range(count)]
    return shots


def flat_shots(count=9):
    """An even white diffuser over the lens, in daylight (#12): vignetting and dust."""
    return [Shot(f"flat-{i}", raw=True, settle_ms=2000) for i in range(count)]


def checker_shots(count=30):
    """A printed checkerboard moved through the view (#12): the lens's distortion."""
    return [Shot(f"checker-{i:02d}") for i in range(count)]


MOON_LADDER_US = (50, 100, 250, 500, 1000, 2000, 4000)
MOON_RAW_US = (250, 1000)


def moon_shots(minute):
    """Experiment 18: a short-exposure ladder the minute after each slot, a track shot otherwise.
    Moonlight is sunlight, so daylight white balance. Scheduled only while the moon is in frame."""
    if minute % SLOT_S < 60:
        return []
    daylight = ("--awb", "daylight")
    if (minute - 60) % SLOT_S < 60:
        return [Shot(f"moon-{us}us", shutter_us=us, gain=1, raw=us in MOON_RAW_US, extra=daylight)
                for us in MOON_LADDER_US]
    return [Shot("moon-track", shutter_us=1000, gain=1, extra=daylight)]


def read_text(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def camera_index(camera, listing):
    """rpicam's index for CAMERA, as the production capture finds it (pi/sunset-capture.sh): a port
    ID such as i2c@0 matched against the --list-cameras lines, or a plain number. None if CAMERA is
    not set. No match, or more than one, raises ValueError: shooting the other camera would put its
    pictures in this camera's run (on the CM4, rpicam's camera 0 is CAM1, review 2026-11-21)."""
    camera = (camera or "").strip()
    if not camera:
        return None
    if camera.isdigit():
        return camera
    lines = [l for l in listing.splitlines() if re.match(r"^\s*\d+ : ", l) and camera in l]
    if len(lines) != 1:
        raise ValueError("CAMERA=%s matches %d cameras" % (camera, len(lines)))
    return re.match(r"^\s*(\d+) : ", lines[0]).group(1)


def camera_busy():
    for name in ("rpicam-vid", "rpicam-still"):
        if subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0:
            return True
    if read_text(["systemctl", "is-active", "sunset-diag.service"]) == "active":
        return True  # someone may be looking at the page; the stream comes first
    return any(read_text(["systemctl", "is-active", unit]) in ("active", "activating")
               for unit in ("sunset-capture.service", "sunset-dense.service"))


def load_site_env():
    """Coordinates for the sun data, and ROTATION. Coordinates stay in sunset.env, never in results."""
    try:
        lines = ENV_FILE.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line.startswith(("SITE_LAT=", "SITE_LON=", "ROTATION=", "CAMERA=")):
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
        self._upload_thread = None
        self.guard = FailureGuard()
        self.camera_lock = CaptureLock(capture_lock_path())

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
        low = sd_low_reason(shutil.disk_usage(self.dir))
        if low:
            self.record(utc=stamp, label=shot.label, status=f"skipped: SD low ({low})")
            return
        est = estimate_s(shot.shutter_us)
        # Both cameras' dense frames start at :00 from one service, one after the other;
        # camera_busy() sees that service while either is shooting.
        period = 60
        waited = time.time()
        while True:
            if not clear_to_start(time.time(), est, period) or camera_busy():
                reason = "camera not clear"
            elif self.camera_lock.acquire():
                break
            else:
                reason = "camera busy (capture lock)"
            if time.time() - waited > max_wait_s:
                self.record(utc=stamp, label=shot.label, status="skipped: " + reason)
                return
            time.sleep(2)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        base = str(self.dir / f"{shot.label}_{stamp}")
        started = time.time()
        try:
            rc = subprocess.run(shot.command(base), capture_output=True,
                                timeout=shot_timeout_s(shot)).returncode
            status = "ok" if rc == 0 else f"failed rc={rc}"
        except subprocess.TimeoutExpired:
            status = "failed timeout"   # subprocess.run has killed it, so the camera is free
        except OSError as e:
            status = f"failed {e.__class__.__name__}"
        finally:
            self.camera_lock.release()
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

    def _nas_ready(self):
        """True if the experiments share is mounted and has room. Raises OSError otherwise."""
        os.listdir("/mnt/nas-camera")  # wake the automount
        if os.stat("/mnt/nas-camera").st_dev == os.stat(self.dir).st_dev:
            raise OSError("share not mounted")
        if shutil.disk_usage("/mnt/nas-camera").free < MIN_NAS_FREE_GB * 1024 ** 3:
            raise OSError("NAS below the free-space floor, keeping results on the SD card")
        return True

    def uploading(self):
        return self._upload_thread is not None and self._upload_thread.is_alive()

    def finish_upload(self, timeout=None):
        """Wait for a running copy, at most `timeout` seconds. False if it is still running."""
        if self._upload_thread is not None:
            self._upload_thread.join(timeout)
            if self._upload_thread.is_alive():
                return False
            self._upload_thread = None
        return True

    def upload(self, wait=False):
        """Copy to the NAS, removing each frame only after rsync confirms it. Never fatal.

        Runs in the background so the camera keeps shooting: on the CM4's slow Wi-Fi a copy took
        about 7 minutes. Only the files already here when it is called are sent. It is called
        between shots, so none of them can be half-written. With wait=True (the end of a run) it
        first lets a running copy finish, then copies the rest and returns when done, waiting at
        most UPLOAD_JOIN_S each time. A copy still running then is left alone (results stay on
        the SD card), rather than starting a second rsync over the same files."""
        if wait:
            if not self.finish_upload(UPLOAD_JOIN_S):
                print("upload still running after the wait, not starting another", file=sys.stderr)
                return
        elif self.uploading():
            return
        self.last_upload = time.time()
        files = sorted(p.name for p in self.dir.iterdir() if p.is_file() and p.name != "manifest.csv")
        self._upload_thread = threading.Thread(target=self._transfer, args=(files,), daemon=True)
        self._upload_thread.start()
        if wait and not self.finish_upload(UPLOAD_JOIN_S):
            print("final upload still running, leaving it", file=sys.stderr)

    def _transfer(self, files):
        target = pathlib.Path(NAS_EXP_ROOT) / self.name
        listing = None
        try:
            self._nas_ready()
            target.mkdir(parents=True, exist_ok=True)
            if files:
                fd, listing = tempfile.mkstemp(prefix=".upload-", suffix=".lst")
                with os.fdopen(fd, "w") as f:
                    f.write("\0".join(files))
                subprocess.run(["rsync", "-rt", "--from0", f"--files-from={listing}", "--remove-source-files",
                                f"{self.dir}/", f"{target}/"], check=True, capture_output=True, timeout=3600)
            subprocess.run(["rsync", "-t", str(self.manifest), f"{target}/"], check=True,
                           capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"upload failed, results stay on the SD card: {e}", file=sys.stderr)
        finally:
            if listing:
                try:
                    os.unlink(listing)
                except OSError:
                    pass


def run_moon(run, until):
    while time.time() < until:
        minute = int(time.time()) // 60 * 60
        for shot in moon_shots(minute):
            if time.time() >= until:
                break
            run.take(shot, max_wait_s=30)
        if time.time() - run.last_upload > UPLOAD_EVERY_S:
            run.upload()
        time.sleep(max(0, min(until, minute + 60) - time.time()))


def run_program(run, args):
    if args.program == "moon":
        run_moon(run, args.until)
    else:
        make = {"dark": dark_shots, "flat": flat_shots, "checker": checker_shots}[args.program]
        shots = make(args.count) if args.count else make()
        for i, shot in enumerate(shots):
            if args.program == "checker" and i:
                time.sleep(args.every)          # time to move the board
            run.take(shot, max_wait_s=900)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("program", choices=["moon", "dark", "flat", "checker"])
    parser.add_argument("--run", required=True)
    parser.add_argument("--until", type=int, help="moon: when to stop (epoch seconds)")
    parser.add_argument("--count", type=int, help="dark, flat, checker: frames (dark: of each kind)")
    parser.add_argument("--every", type=float, default=CHECKER_EVERY_S, help="checker: seconds between frames")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    load_site_env()
    try:
        index = camera_index(os.environ.get("CAMERA", ""), read_text(["rpicam-still", "--list-cameras"])
                             if os.environ.get("CAMERA", "").strip() and not os.environ["CAMERA"].strip().isdigit() else "")
    except ValueError as e:
        sys.exit("not running: %s" % e)
    if index is not None:
        os.environ["CAM_INDEX"] = index
    with experiment_lock(LOCK_FILE):
        run = Run(args.run)
        run_program(run, args)
    # The last copy doesn't need the camera, so the next program may start meanwhile.
    run.upload(wait=True)


if __name__ == "__main__":
    main()
