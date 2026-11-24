#!/bin/sh
# One camera's health from the newest frame's JSON on the NAS (the System and Capture blocks that
# pi/sunset-meta.py writes). Prints "ok", or the problems separated by spaces:
#   undervoltage freq_capped throttled soft_temp_limit   throttled bits 0-3 right now (vcgencmd get_throttled)
#   temp=N       cpu_temp_c above TEMP_LIMIT_C (default 75; the Pi 3 B+ soft limit is 60, the hard one 80)
#   outbox=N     more than OUTBOX_MAX (default 150) files waiting on the Pi for the sync, both cameras together
#   disk=N%      outbox disk use above DISK_MAX_PCT (default 80; the Pi skips night frames at 95)
#   small_jpeg=N the JPEG on the NAS is under JPEG_MIN_BYTES (default 400000, an estimate to tune)
#   repeat_frame the newest JPEG has the same checksum as the one before it of its kind (a frozen readout)
#   no_meta      the frame has no Capture or System block (sunset-meta.py failed)
#   camera_metadata  the frame's rpicam metadata was lost (rpicam_metadata is "missing" or "invalid")
#   no_checksum  Capture.unavailable says the SHA-256 was not written, so the verifier can't check it
# Prints nothing and exits 1 if there is no frame JSON in the last two UTC days, it can't be read, or
# python3 is missing: Home Assistant shows that as unknown, and the alert treats unknown as bad.
# A reading that is null in the JSON (one probe failed) is skipped, not reported.
# Runs in Home Assistant's container: POSIX sh, with python3 (which that container has) for the JSON.
# Argument: the camera name (CAM_NAME on that Pi), wide if left out.
CAM="${1:-wide}"
case "$CAM" in *[!A-Za-z0-9_-]*|"") echo "bad camera name: $CAM" >&2; exit 2 ;; esac
ROOT="${FRAME_ROOT:-${FRAME_BASE:-/share/camera/project_sunshine}/$CAM}"
command -v python3 >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }
exec python3 -I - "$ROOT" "$CAM" <<'PY'
import json, os, re, sys, time

root, cam = sys.argv[1], sys.argv[2]
env = os.environ.get
now = float(env("SUNSET_NOW") or time.time())
temp_limit = float(env("TEMP_LIMIT_C") or 75)
outbox_max = float(env("OUTBOX_MAX") or 150)
disk_max = float(env("DISK_MAX_PCT") or 80)
jpeg_min = int(env("JPEG_MIN_BYTES") or 400000)

pattern = re.compile(r"^%s_(\d{8}T\d{6}Z)(_night)?\.json$" % re.escape(cam))
found = []
for t in (now, now - 86400):
    folder = os.path.join(root, time.strftime("%Y/%m/%d", time.gmtime(t)))
    try:
        names = os.listdir(folder)
    except OSError:
        continue
    for name in names:
        m = pattern.match(name)
        if m:
            found.append((m.group(1), bool(m.group(2)), folder, name))
found.sort(reverse=True)    # newest first; at the same second the night frame is the later one
if not found:
    sys.exit(1)


def load(entry):
    try:
        with open(os.path.join(entry[2], entry[3]), "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


newest = data = None
for entry in found[:3]:     # the newest file can be half copied: try the next one
    data = load(entry)
    if data is not None:
        newest = entry
        break
if data is None:
    sys.exit(1)


def num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


problems = []
capture, system = data.get("Capture"), data.get("System")
if not isinstance(capture, dict) or not isinstance(system, dict):
    problems.append("no_meta")
else:
    try:
        bits = int(str(system.get("throttled")), 16)
    except ValueError:
        bits = 0
    for bit, name in ((0, "undervoltage"), (1, "freq_capped"), (2, "throttled"), (3, "soft_temp_limit")):
        if bits & (1 << bit):
            problems.append(name)
    temp = num(system.get("cpu_temp_c"))
    if temp is not None and temp > temp_limit:
        problems.append("temp=%g" % temp)
    pending = system.get("outbox_pending")
    files = num(pending.get("files")) if isinstance(pending, dict) else None
    if files is not None and files > outbox_max:
        problems.append("outbox=%d" % files)
    disk = system.get("disk")
    used = num(disk.get("used_pct")) if isinstance(disk, dict) else None
    if used is not None and used > disk_max:
        problems.append("disk=%g%%" % used)

if isinstance(data.get("rpicam_metadata"), str):
    problems.append("camera_metadata")
if isinstance(capture, dict) and "sha256" in (capture.get("unavailable") or []):
    problems.append("no_checksum")

jpg = os.path.join(newest[2], newest[3][:-len(".json")] + ".jpg")
try:
    size = os.path.getsize(jpg)
    if size < jpeg_min:
        problems.append("small_jpeg=%d" % size)
except OSError:
    pass        # the JPEG can lag the JSON by a moment during the sync: the frame-age sensor covers a missing one


def jpg_hash(d):
    files = (d.get("Capture") or {}).get("files") if isinstance(d.get("Capture"), dict) else None
    entry = files.get("jpg") if isinstance(files, dict) else None
    return entry.get("sha256") if isinstance(entry, dict) else None


here = jpg_hash(data)
if here:
    for entry in found[found.index(newest) + 1:]:
        if entry[1] == newest[1]:       # the frame before it of the same kind (day or night)
            before = load(entry)
            if before is not None and jpg_hash(before) == here:
                problems.append("repeat_frame")
            break

print(" ".join(problems) if problems else "ok")
PY
