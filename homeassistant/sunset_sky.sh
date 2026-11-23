#!/bin/sh
# The evening's sky score (2026-11-22), for the good-sunset notification: the newest result that
# pi/sunset-sky.py wrote to the share, project_sunshine_sky/<camera>/<local date>.json, about 40
# minutes after each sunset.
# Prints one JSON line: "state" is the score (0-100), or "none" when there were too few frames to
# score; then date (local), label (grey, some colour, colourful, none), sunset_utc, frames_scored,
# warm_sky_percent and best_frame. Prints nothing and exits 1 if there is no readable result, so
# Home Assistant shows unknown (no notification).
# Runs in Home Assistant's container: POSIX sh, with python3 (which that container has) for the JSON.
# Argument: the camera name (cm4wide). SKY_BASE overrides the folder holding the camera folders.
CAM="${1:-cm4wide}"
case "$CAM" in *[!A-Za-z0-9_-]*|"") echo "bad camera name: $CAM" >&2; exit 2 ;; esac
ROOT="${SKY_BASE:-/share/camera/project_sunshine_sky}/$CAM"
command -v python3 >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }
exec python3 -I - "$ROOT" <<'PY'
import json, os, re, sys

root = sys.argv[1]
try:
    names = sorted((n for n in os.listdir(root) if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", n)), reverse=True)
except OSError:
    sys.exit(1)
for name in names:
    try:
        with open(os.path.join(root, name), "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        continue
    if isinstance(data, dict):
        break
else:
    sys.exit(1)

score = data.get("score")
score = score if isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 100 else None
out = {"state": score if score is not None else "none", "date": name[:-5],
       "label": data.get("label") if score is not None else "none"}
for key in ("sunset_utc", "frames_scored", "warm_sky_percent", "best_frame"):
    value = data.get(key)
    out[key] = value if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None
print(json.dumps(out, sort_keys=True))
PY
