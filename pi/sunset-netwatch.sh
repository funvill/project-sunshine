#!/usr/bin/env bash
# Bring the Pi back onto the network when its Wi-Fi hangs. On 2026-11-13 the CM4's USB dongle
# dropped off and never rejoined until a power-cycle (1 h 45 min, frames piled up on the Pi).
# Runs every 2 minutes as root from sunset-netwatch.timer, and does nothing unless NETWATCH=1.
#   - pings the default gateway through NETWATCH_IFACE (wlan0)
#   - down 10 min: unbinds and rebinds the interface's USB device, once per outage (a software replug)
#   - down 30 min: reboots, at most once every 6 hours, so a router outage can't cause a reboot loop.
#     A reboot costs about one capture and clears transient experiment timers (exp-*).
#     With a trusted clock it first leaves the time in CLOCK_TRUST_FILE on the SD card, so
#     sunset-capture.sh keeps capturing after the reboot although NTP still can't answer.
# State lives in /run (RAM). It writes to the SD card only when it acts.
set -u
[[ "${NETWATCH:-0}" == 1 ]] || exit 0

IFACE="${NETWATCH_IFACE:-wlan0}"
STATE="${NETWATCH_STATE:-/run/sunset-netwatch}"
LOG="${NETWATCH_LOG:-$HOME/sunset/netwatch.log}"
SYSFS="${NETWATCH_SYSFS:-/sys}"
MARK="${NETWATCH_REBOOT_MARK:-$(dirname "$LOG")/.netwatch-reboot}"
RESET_MIN="${NETWATCH_RESET_MIN:-10}"
REBOOT_MIN="${NETWATCH_REBOOT_MIN:-30}"
REBOOT_GAP_H="${NETWATCH_REBOOT_GAP_H:-6}"
SETTLE_S="${NETWATCH_SETTLE_S:-3}"
UPTIME="${NETWATCH_UPTIME:-$(cut -d. -f1 /proc/uptime)}"   # monotonic, unlike the clock
CLOCK_OK_FILE="${CLOCK_OK_FILE:-/dev/shm/sunset-clock-ok}"  # sunset-capture.sh's "synced this boot" flag
CLOCK_TRUST_FILE="$(dirname "$LOG")/.clock-trusted"           # read once by sunset-capture.sh after the reboot
LOG_MAX_BYTES="${NETWATCH_LOG_MAX_BYTES:-1048576}"         # then netwatch.log moves to netwatch.log.1

log() {
  if [[ -f "$LOG" ]] && (( $(wc -c < "$LOG" 2>/dev/null || echo 0) >= LOG_MAX_BYTES )); then
    mv -f "$LOG" "$LOG.1"
  fi
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"
}

online() {
  local gw="${NETWATCH_TARGET:-$(ip route show default 2>/dev/null | awk '{print $3; exit}')}"
  [[ -n "$gw" ]] && ping -c 3 -W 3 -I "$IFACE" "$gw" >/dev/null 2>&1
}

reset_dongle() {
  local dev usb
  dev="$(cd "$SYSFS/class/net/$IFACE/device" 2>/dev/null && pwd -P)" || { log "reset skipped: no device for $IFACE"; return; }
  usb="$(basename "$(dirname "$dev")")"
  [[ "$usb" =~ ^[0-9]+-[0-9.]+$ ]] || { log "reset skipped: $IFACE is not a USB device"; return; }
  echo "$usb" > "$SYSFS/bus/usb/drivers/usb/unbind" 2>/dev/null
  sleep "$SETTLE_S"
  echo "$usb" > "$SYSFS/bus/usb/drivers/usb/bind" 2>/dev/null
  log "no network for $1 min: reset the Wi-Fi dongle (USB $usb)"
}

if online; then
  if [[ -f "$STATE" ]]; then
    read -r since _ < "$STATE"
    log "network back after $(( (UPTIME - since) / 60 )) min"
    rm -f "$STATE"
  fi
  exit 0
fi

[[ -f "$STATE" ]] || { echo "$UPTIME 0" > "$STATE"; exit 0; }
read -r since reset_done < "$STATE"
down=$(( (UPTIME - since) / 60 ))

if (( down >= RESET_MIN && reset_done == 0 )); then
  reset_dongle "$down"
  echo "$since 1" > "$STATE"
fi

if (( down >= REBOOT_MIN )); then
  if [[ -n "$(find "$MARK" -mmin -$(( REBOOT_GAP_H * 60 )) 2>/dev/null)" ]]; then
    exit 0
  fi
  log "rebooting: no network for $down min"
  touch "$MARK"
  # NTP won't answer after the reboot either, so capture would wait for the network. Leave the
  # time for it, but only if the clock is trusted now (sunset-capture.sh reads it once, then deletes it).
  if [[ -e "$CLOCK_OK_FILE" || "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" == yes ]]; then
    now="$(date +%s)"
    echo "$now" > "$CLOCK_TRUST_FILE"
    log "clock trusted at $now: kept for the capture after the reboot"
  fi
  sync
  systemctl reboot
fi
exit 0
