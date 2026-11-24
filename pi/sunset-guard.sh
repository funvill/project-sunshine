#!/usr/bin/env bash
# The Pi's two watchdogs in one script, run every 2 minutes as root from sunset-guard.timer
# (until batch B, 2026-11-22, these were sunset-netwatch.sh and sunset-camwatch.sh, each on its
# own timer; their settings and files keep their names). Each check does nothing unless it is on.
#
# Network (NETWATCH=1): brings the Pi back onto the network when its Wi-Fi hangs. On 2026-11-13
# the CM4's USB dongle dropped off and never rejoined until a power-cycle (1 h 45 min, frames
# piled up on the Pi).
#   - pings the default gateway through NETWATCH_IFACE (wlan0); if that fails, through each of
#     NETWATCH_WIRED (default eth0, "" for none). Reachable through any of them counts as online, so
#     a Wi-Fi outage while the wired link works is left alone (the CM4 is on Ethernet from 2026-11-24,
#     the dongle kept as a fallback route). A Pi with no cable on eth0 behaves as before.
#   - down 10 min: unbinds and rebinds the interface's USB device, once per outage (a software replug)
#   - down 30 min: reboots, at most once every 6 hours, so a router outage can't cause a reboot loop.
#     A reboot costs about one capture and clears transient experiment timers (exp-*).
#
# Camera (CAMWATCH=1): reboots when a camera keeps failing. From 14:05 UTC 2026-11-19 both CM4
# cameras failed captures on and off ("Failed to queue buffer for Unicam Image", "Device timeout")
# until the network watchdog happened to reboot the Pi at 06:37 UTC Nov 20, which cleared it:
# 16 hours, 11 slots lost. The failures were scattered (never more than one in a row on cm4wide),
# so this counts failures in a window rather than in a row. On that log, 3 in 60 minutes would
# have rebooted at 14:46 UTC.
#   - reads capture.log (both cameras log there, each line says cam=<name>)
#   - counts, per camera, failed captures (5-minute, dense, night, empty JPEG) since this boot within the
#     last CAMWATCH_WINDOW_MIN; "FAILED publish" (storage), skips and retried WARNs don't count
#   - CAMWATCH_FAILS or more: reboots, at most once every 6 hours, so a dead camera can't cause a
#     reboot loop.
#
# Each check keeps its own log and its own 6-hour reboot mark. Before either reboots with a trusted
# clock it leaves the time in .clock-trusted next to its log, so sunset-capture.sh keeps capturing
# after the reboot although NTP may not answer yet.
# State lives in /run (RAM). It writes to the SD card only when it acts.
set -u
[[ "${NETWATCH:-0}" == 1 || "${CAMWATCH:-0}" == 1 ]] || exit 0

CLOCK_OK_FILE="${CLOCK_OK_FILE:-/dev/shm/sunset-clock-ok}"  # sunset-capture.sh's "synced this boot" flag
PROC_UPTIME="$(cut -d. -f1 /proc/uptime 2>/dev/null)"       # monotonic, unlike the clock

log_to() { # log_to <file> <max bytes> <text...>: then <file> moves to <file>.1
  local f="$1" max="$2"; shift 2
  if [[ -f "$f" ]] && (( $(wc -c < "$f" 2>/dev/null || echo 0) >= max )); then
    mv -f "$f" "$f.1"
  fi
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> "$f"
}

recently_rebooted() { # recently_rebooted <mark> <hours>: true if the mark is newer than that
  [[ -n "$(find "$1" -mmin -$(( $2 * 60 )) 2>/dev/null)" ]]
}

reboot_pi() { # reboot_pi <mark> <log file> <log function> <why>: does not return
  local mark="$1" logfile="$2" say="$3" why="$4" now
  "$say" "rebooting: $why"
  touch "$mark"
  # NTP may not answer after the reboot, so capture would wait for it. Leave the time for it, but
  # only if the clock is trusted now (sunset-capture.sh reads it once, then deletes it).
  if [[ -e "$CLOCK_OK_FILE" || "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" == yes ]]; then
    now="$(date +%s)"
    echo "$now" > "$(dirname "$logfile")/.clock-trusted"
    "$say" "clock trusted at $now: kept for the capture after the reboot"
  fi
  sync
  systemctl reboot
  exit 0
}

# --- network -------------------------------------------------------------------------------------
NET_LOG="${NETWATCH_LOG:-$HOME/sunset/netwatch.log}"
net_log() { log_to "$NET_LOG" "${NETWATCH_LOG_MAX_BYTES:-1048576}" "$@"; }

net_online() {
  local gw="${NETWATCH_TARGET:-$(ip route show default 2>/dev/null | awk '{print $3; exit}')}"
  [[ -n "$gw" ]] && ping -c 3 -W 3 -I "$1" "$gw" >/dev/null 2>&1
}

net_wired_online() {
  local i
  for i in ${NETWATCH_WIRED-eth0}; do net_online "$i" && return 0; done
  return 1
}

net_reset_dongle() { # net_reset_dongle <iface> <minutes down>
  local sysfs="${NETWATCH_SYSFS:-/sys}" dev usb
  dev="$(cd "$sysfs/class/net/$1/device" 2>/dev/null && pwd -P)" || { net_log "reset skipped: no device for $1"; return; }
  usb="$(basename "$(dirname "$dev")")"
  [[ "$usb" =~ ^[0-9]+-[0-9.]+$ ]] || { net_log "reset skipped: $1 is not a USB device"; return; }
  echo "$usb" > "$sysfs/bus/usb/drivers/usb/unbind" 2>/dev/null
  sleep "${NETWATCH_SETTLE_S:-3}"
  echo "$usb" > "$sysfs/bus/usb/drivers/usb/bind" 2>/dev/null
  net_log "no network for $2 min: reset the Wi-Fi dongle (USB $usb)"
}

check_network() {
  local iface="${NETWATCH_IFACE:-wlan0}" state="${NETWATCH_STATE:-/run/sunset-netwatch}"
  local mark="${NETWATCH_REBOOT_MARK:-$(dirname "$NET_LOG")/.netwatch-reboot}"
  local uptime="${NETWATCH_UPTIME:-$PROC_UPTIME}" since reset_done down _
  if net_online "$iface" || net_wired_online; then
    if [[ -f "$state" ]]; then
      read -r since _ < "$state"
      net_log "network back after $(( (uptime - since) / 60 )) min"
      rm -f "$state"
    fi
    return
  fi
  [[ -f "$state" ]] || { echo "$uptime 0" > "$state"; return; }
  read -r since reset_done < "$state"
  down=$(( (uptime - since) / 60 ))
  if (( down >= ${NETWATCH_RESET_MIN:-10} && reset_done == 0 )); then
    net_reset_dongle "$iface" "$down"
    echo "$since 1" > "$state"
  fi
  if (( down >= ${NETWATCH_REBOOT_MIN:-30} )); then
    recently_rebooted "$mark" "${NETWATCH_REBOOT_GAP_H:-6}" && return
    reboot_pi "$mark" "$NET_LOG" net_log "no network for $down min"
  fi
}

# --- camera --------------------------------------------------------------------------------------
CAM_LOG="${CAMWATCH_LOG:-$HOME/sunset/camwatch.log}"
cam_log() { log_to "$CAM_LOG" "${CAMWATCH_LOG_MAX_BYTES:-1048576}" "$@"; }

check_cameras() {
  local capture_log="${CAMWATCH_CAPTURE_LOG:-$HOME/sunset/capture.log}"
  local state="${CAMWATCH_STATE:-/run/sunset-camwatch}"
  local mark="${CAMWATCH_REBOOT_MARK:-$(dirname "$CAM_LOG")/.camwatch-reboot}"
  local fails="${CAMWATCH_FAILS:-3}" window_min="${CAMWATCH_WINDOW_MIN:-60}" gap_h="${CAMWATCH_REBOOT_GAP_H:-6}"
  local now="${CAMWATCH_NOW:-$(date +%s)}" uptime="${CAMWATCH_UPTIME:-$PROC_UPTIME}"
  local since boot cutoff until worst count cam stamp
  [[ -r "$capture_log" ]] || return

  # Log lines start with an ISO UTC time, which sorts as text: count lines from the later of
  # "window start" and "boot", up to now.
  since=$(( now - window_min * 60 ))
  boot=$(( now - uptime ))
  (( boot > since )) && since=$boot
  cutoff="$(date -u -d "@$since" +%FT%TZ)"
  until="$(date -u -d "@$now" +%FT%TZ)"

  worst="$(tail -n 3000 "$capture_log" | awk -v cutoff="$cutoff" -v until="$until" '
    $1 >= cutoff && $1 <= until && $2 ~ /^cam=/ && / FAILED (capture|night)([ (]|$)/ { n[substr($2, 5)]++ }
    END { for (c in n) print n[c], c }' | sort -rn | head -n 1)"
  [[ -n "$worst" ]] || return
  read -r count cam <<< "$worst"
  (( count >= fails )) || return

  if recently_rebooted "$mark" "$gap_h"; then
    # Say so once per reboot mark, not every run.
    stamp="$(stat -c %Y "$mark" 2>/dev/null)"
    if [[ "$(cat "$state" 2>/dev/null)" != "$stamp" ]]; then
      cam_log "not rebooting: $cam failed $count captures in $window_min min, but the last reboot was less than $gap_h h ago"
      echo "$stamp" > "$state"
    fi
    return
  fi
  reboot_pi "$mark" "$CAM_LOG" cam_log "$cam failed $count captures in $window_min min"
}

[[ "${NETWATCH:-0}" == 1 ]] && check_network
[[ "${CAMWATCH:-0}" == 1 ]] && check_cameras
exit 0
