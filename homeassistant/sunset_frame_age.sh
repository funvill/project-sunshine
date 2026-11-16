#!/bin/sh
# Prints the age in minutes of the newest production frame on the NAS, from its UTC filename.
# Prints nothing and exits 1 if there is no frame in the last two UTC day folders, the share
# can't be read, or the newest frame is named more than FUTURE_TOLERANCE_MIN (default 10) minutes
# ahead of this clock. A name in the future means one of the two clocks is wrong, and reading it as
# age 0 would hide a dead camera, so it counts as unknown, which the alert treats as stale.
# Runs in Home Assistant's container, so POSIX sh and BusyBox tools only.
# Optional argument: the camera name (CAM_NAME on that Pi), wide if left out.
CAM="${1:-wide}"
case "$CAM" in *[!A-Za-z0-9_-]*|"") echo "bad camera name: $CAM" >&2; exit 2 ;; esac
ROOT="${FRAME_ROOT:-${FRAME_BASE:-/share/camera/project_sunshine}/$CAM}"
now="${FRAME_AGE_NOW:-$(date -u +%s)}"
tolerance="${FUTURE_TOLERANCE_MIN:-10}"

newest=""
for day in "$now" "$((now - 86400))"; do
  dir="$ROOT/$(date -u -d "@$day" +%Y/%m/%d)"
  newest=$(ls "$dir" 2>/dev/null | grep -E "^${CAM}_"'[0-9]{8}T[0-9]{6}Z(_night)?\.jpg$' | sort | tail -n 1)
  [ -n "$newest" ] && break
done
[ -n "$newest" ] || exit 1

then=$(date -u -d "$(echo "${newest#"${CAM}_"}" | sed -E 's/^(....)(..)(..)T(..)(..)(..)Z.*/\1-\2-\3 \4:\5:\6/')" +%s) || exit 1
secs=$((now - then))
if [ "$secs" -lt $((-60 * tolerance)) ]; then
  echo "newest frame $newest is $((-secs / 60)) min ahead of this clock" >&2
  exit 1
fi
age=$((secs / 60))
[ "$age" -lt 0 ] && age=0
echo "$age"
