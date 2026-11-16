#!/bin/sh
# Prints the free space on the NAS share in whole GB (1 GB = 1024^3 bytes, as Windows shows it).
# Prints nothing and exits 1 if the share isn't there or df gives nothing usable, which Home
# Assistant shows as unknown and the alert treats as low.
# Runs in Home Assistant's container: POSIX sh, BusyBox df and awk. `df -Pk` is the portable form.
# FRAME_BASE is the project_sunshine folder on the share. It has to exist: if the share is unmounted,
# /share/camera may still be an empty folder on Home Assistant's own disk, and df would answer for that.
DIR="${FREE_PATH:-${FRAME_BASE:-/share/camera/project_sunshine}}"
DF="${DF:-df}"
[ -d "$DIR" ] || exit 1
kb=$($DF -Pk "$DIR" 2>/dev/null | awk 'NR == 2 { print $4 }')
case "$kb" in ""|*[!0-9]*) exit 1 ;; esac
echo $((kb / 1048576))
