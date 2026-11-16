#!/bin/sh
# Age and status of the newest daily video record (daily/YYYY-MM-DD.json, from nas/sunset-daily.py).
# Prints "<status> <date> <age>d", for example "ok 2026-11-14 1d". The first word is what matters:
#   ok       the record's status is "encoded"
#   skipped  the day had too few frames and made no video
#   failed   the job gave up on the day
#   stale    the newest record is more than MAX_AGE_DAYS (default 2) UTC days old: the job isn't running
#   unreadable    the record isn't a JSON object with a status
#   unknown_status_<x>   any other status. New statuses count as bad until this script learns them.
# Prints nothing and exits 1 if there is no record, the folder can't be read, or python3 is missing.
# The record is named by the local date of the sunset and is written about an hour after it, which is the
# next UTC day, so age 1 is normal in the morning and 2 only until the evening's job has run.
# Runs in Home Assistant's container: POSIX sh, with python3 for the JSON.
# DAILY_DIR is the daily folder (default: daily beside the cameras on the share).
DIR="${DAILY_DIR:-${FRAME_BASE:-/share/camera/project_sunshine}/daily}"
command -v python3 >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }
[ -d "$DIR" ] || exit 1
exec python3 -I - "$DIR" <<'PY'
import json, os, re, sys, time
from datetime import date

folder = sys.argv[1]
now = float(os.environ.get("SUNSET_NOW") or time.time())
max_age = int(os.environ.get("MAX_AGE_DAYS") or 2)
records = sorted(n for n in os.listdir(folder) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", n))
if not records:
    sys.exit(1)
name = records[-1]
day = name[:-5]
today = date(*time.gmtime(now)[:3])
age = (today - date.fromisoformat(day)).days
try:
    with open(os.path.join(folder, name), "rb") as f:
        record = json.loads(f.read().decode("utf-8"))
    status = record["status"] if isinstance(record, dict) else None
except (OSError, ValueError, KeyError):
    status = None
if not isinstance(status, str) or not status:
    word = "unreadable"
elif status == "encoded":
    word = "ok"
elif status in ("skipped", "failed"):
    word = status
else:
    word = "unknown_status_" + re.sub(r"[^A-Za-z0-9_-]", "", status)[:30]
if age > max_age:
    word = "stale"
print("%s %s %dd" % (word, day, age))
PY
