#!/bin/sh
# The newest result of a NAS job for one camera. Prints "ok", or what is wrong. Usage:
#   sunset_result.sh verify [camera] [max_age_hours]   nas/sunset-verify.py: health/<camera>/verify.json
#   sunset_result.sh health [camera] [max_age_hours]   nas/sunset-health.py:  health/<camera>/latest.json
# verify: "bad missing=1 mismatched=2 ..." when any file is known to be bad (the kinds with a count).
# health: the day's problem names, for example "regular_low gap", from the record's `problems`.
# Both print "stale" if the job hasn't written a result in max_age_hours (default 48), because a job that
# stopped running is as bad as one that finds problems, and "unreadable" if the file isn't what is expected.
# Prints nothing and exits 1 if there is no result file yet or python3 is missing: Home Assistant shows
# unknown, which the alert treats as bad.
# Runs in Home Assistant's container: POSIX sh, with python3 for the JSON.
KIND="${1:-}"
CAM="${2:-wide}"
MAX_H="${3:-48}"
case "$KIND" in verify|health) ;; *) echo "usage: sunset_result.sh verify|health [camera] [max_age_hours]" >&2; exit 2 ;; esac
case "$CAM" in *[!A-Za-z0-9_-]*|"") echo "bad camera name: $CAM" >&2; exit 2 ;; esac
case "$MAX_H" in *[!0-9]*|"") echo "bad max age: $MAX_H" >&2; exit 2 ;; esac
DIR="${RESULT_DIR:-${FRAME_BASE:-/share/camera/project_sunshine}/health/$CAM}"
command -v python3 >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }
if [ "$KIND" = verify ]; then FILE="$DIR/verify.json"; else FILE="$DIR/latest.json"; fi
[ -f "$FILE" ] || exit 1
exec python3 -I - "$KIND" "$FILE" "$MAX_H" <<'PY'
import json, os, sys, time
from datetime import datetime, timezone

kind, path, max_h = sys.argv[1], sys.argv[2], float(sys.argv[3])
now = float(os.environ.get("SUNSET_NOW") or time.time())
try:
    with open(path, "rb") as f:
        data = json.loads(f.read().decode("utf-8"))
    stamp = data["last_run_utc" if kind == "verify" else "generated_utc"]
    when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    if kind == "verify":
        ok, detail = data["ok"], data["problem_counts"]
        if not isinstance(ok, bool) or not isinstance(detail, dict):
            raise ValueError("shape")
    else:
        problems = data["problems"]
        if not isinstance(problems, list):
            raise ValueError("shape")
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    print("unreadable")
    sys.exit(0)
if now - when > max_h * 3600:
    print("stale")
elif kind == "verify":
    bits = ["%s=%s" % (k, v) for k, v in detail.items() if v]
    print("ok" if ok else " ".join(["bad"] + bits))
else:
    print(" ".join(str(p) for p in problems) if problems else "ok")
PY
