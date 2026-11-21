#!/usr/bin/env bash
# Reboot when a camera keeps failing. From 14:05 UTC 2026-11-19 both CM4 cameras failed captures
# on and off ("Failed to queue buffer for Unicam Image", "Device timeout") until the network
# watchdog happened to reboot the Pi at 06:37 UTC Nov 20, which cleared it: 16 hours, 11 slots lost.
# The failures were scattered (never more than one in a row on cm4wide), so this counts failures
# in a window rather than in a row. On that log, 3 in 60 minutes would have rebooted at 14:46 UTC.
# Runs every 5 minutes as root from sunset-camwatch.timer, and does nothing unless CAMWATCH=1.
#   - reads capture.log (both cameras log there, each line says cam=<name>)
#   - counts, per camera, failed captures (5-minute, dense, night, empty JPEG) since this boot within the
#     last CAMWATCH_WINDOW_MIN; "FAILED publish" (storage), skips and retried WARNs don't count
#   - CAMWATCH_FAILS or more: reboots, at most once every 6 hours, so a dead camera can't cause a
#     reboot loop. With a trusted clock it first leaves the time for the capture after the reboot,
#     as sunset-netwatch.sh does.
# State lives in /run (RAM). It writes to the SD card only when it acts.
set -u
[[ "${CAMWATCH:-0}" == 1 ]] || exit 0

CAPTURE_LOG="${CAMWATCH_CAPTURE_LOG:-$HOME/sunset/capture.log}"
LOG="${CAMWATCH_LOG:-$HOME/sunset/camwatch.log}"
STATE="${CAMWATCH_STATE:-/run/sunset-camwatch}"
MARK="${CAMWATCH_REBOOT_MARK:-$(dirname "$LOG")/.camwatch-reboot}"
FAILS="${CAMWATCH_FAILS:-3}"
WINDOW_MIN="${CAMWATCH_WINDOW_MIN:-60}"
REBOOT_GAP_H="${CAMWATCH_REBOOT_GAP_H:-6}"
NOW="${CAMWATCH_NOW:-$(date +%s)}"
UPTIME="${CAMWATCH_UPTIME:-$(cut -d. -f1 /proc/uptime)}"
CLOCK_OK_FILE="${CLOCK_OK_FILE:-/dev/shm/sunset-clock-ok}"  # sunset-capture.sh's "synced this boot" flag
CLOCK_TRUST_FILE="$(dirname "$LOG")/.clock-trusted"           # read once by sunset-capture.sh after the reboot
LOG_MAX_BYTES="${CAMWATCH_LOG_MAX_BYTES:-1048576}"         # then camwatch.log moves to camwatch.log.1

log() {
  if [[ -f "$LOG" ]] && (( $(wc -c < "$LOG" 2>/dev/null || echo 0) >= LOG_MAX_BYTES )); then
    mv -f "$LOG" "$LOG.1"
  fi
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"
}

[[ -r "$CAPTURE_LOG" ]] || exit 0

# Log lines start with an ISO UTC time, which sorts as text: count lines from the later of
# "window start" and "boot", up to now.
since=$(( NOW - WINDOW_MIN * 60 ))
boot=$(( NOW - UPTIME ))
(( boot > since )) && since=$boot
cutoff="$(date -u -d "@$since" +%FT%TZ)"
until="$(date -u -d "@$NOW" +%FT%TZ)"

worst="$(tail -n 3000 "$CAPTURE_LOG" | awk -v cutoff="$cutoff" -v until="$until" '
  $1 >= cutoff && $1 <= until && $2 ~ /^cam=/ && / FAILED (capture|night)([ (]|$)/ { n[substr($2, 5)]++ }
  END { for (c in n) print n[c], c }' | sort -rn | head -n 1)"
[[ -n "$worst" ]] || exit 0
read -r count cam <<< "$worst"
(( count >= FAILS )) || exit 0

if [[ -n "$(find "$MARK" -mmin -$(( REBOOT_GAP_H * 60 )) 2>/dev/null)" ]]; then
  # Say so once per reboot mark, not every 5 minutes.
  stamp="$(stat -c %Y "$MARK" 2>/dev/null)"
  if [[ "$(cat "$STATE" 2>/dev/null)" != "$stamp" ]]; then
    log "not rebooting: $cam failed $count captures in $WINDOW_MIN min, but the last reboot was less than $REBOOT_GAP_H h ago"
    echo "$stamp" > "$STATE"
  fi
  exit 0
fi

log "rebooting: $cam failed $count captures in $WINDOW_MIN min"
touch "$MARK"
if [[ -e "$CLOCK_OK_FILE" || "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" == yes ]]; then
  now="$(date +%s)"
  echo "$now" > "$CLOCK_TRUST_FILE"
  log "clock trusted at $now: kept for the capture after the reboot"
fi
sync
systemctl reboot
exit 0
