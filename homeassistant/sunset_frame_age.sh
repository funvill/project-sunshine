#!/bin/sh
# Prints the age in minutes of the newest production frame on the NAS, from its UTC filename.
# Prints nothing and exits 1 if there is no frame in the last two UTC day folders or the share
# can't be read, which Home Assistant shows as unknown and the alert treats as stale.
# Runs in Home Assistant's container, so POSIX sh and BusyBox tools only.
# Optional argument: the camera name (CAM_NAME on that Pi), wide if left out.
CAM="${1:-wide}"
case "$CAM" in *[!A-Za-z0-9_-]*|"") echo "bad camera name: $CAM" >&2; exit 2 ;; esac
ROOT="${FRAME_ROOT:-${FRAME_BASE:-/share/camera/project_sunshine}/$CAM}"
now="${FRAME_AGE_NOW:-$(date -u +%s)}"

newest=""
for day in "$now" "$((now - 86400))"; do
  dir="$ROOT/$(date -u -d "@$day" +%Y/%m/%d)"
  newest=$(ls "$dir" 2>/dev/null | grep -E "^${CAM}_"'[0-9]{8}T[0-9]{6}Z(_night)?\.jpg$' | sort | tail -n 1)
  [ -n "$newest" ] && break
done
[ -n "$newest" ] || exit 1

then=$(date -u -d "$(echo "${newest#"${CAM}_"}" | sed -E 's/^(....)(..)(..)T(..)(..)(..)Z.*/\1-\2-\3 \4:\5:\6/')" +%s) || exit 1
age=$(((now - then) / 60))
[ "$age" -lt 0 ] && age=0
echo "$age"
