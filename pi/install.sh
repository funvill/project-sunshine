#!/usr/bin/env bash
# Run ON THE PI with sudo, from the directory holding the scripts:
#   sudo ./install.sh [--cm4-two] [--enable] [--ups]
# Installs the systemd units for the user who invoked sudo (not hard-coded to "pi"),
# optionally sets the camera overlays for both CM4 ports (--cm4-two: dtoverlay=imx477,cam0 and
# dtoverlay=imx477,cam1), and does NOT enable the timers (and so does not start capturing)
# unless --enable is given. With --enable, the second camera's timers start too if
# ~/sunset/sunset2.env exists (copy it from sunset2.env.example). --ups enables and starts the
# OpenUPS2 monitor (sunset-ups.service, issue #29), for the Pi the UPS is plugged into by USB;
# without it the unit is installed but left off (and restarted on the new script if it is running).
#
# ROOT=<dir> (default empty) puts every file it touches under <dir>, for tests against
# fixture copies; it also takes the user from INSTALL_USER and INSTALL_HOME and does not need
# root. Leave it unset on a real Pi.
set -euo pipefail
ROOT="${ROOT:-}"
if [[ -z "$ROOT" ]]; then
  [[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
  RUN_USER="${SUDO_USER:?run via sudo from your normal user}"
  HOME_DIR="$(getent passwd "$RUN_USER" | cut -d: -f6)"
else
  RUN_USER="${INSTALL_USER:?ROOT is set (a test run): set INSTALL_USER}"
  HOME_DIR="${INSTALL_HOME:?ROOT is set (a test run): set INSTALL_HOME}"
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CM4_TWO=0; ENABLE=0; UPS=0
for a in "$@"; do case "$a" in
  --cm4-two) CM4_TWO=1 ;;
  --enable) ENABLE=1 ;;
  --ups) UPS=1 ;;
  *) echo "unknown option $a" >&2; exit 2 ;; esac; done

if (( CM4_TWO )); then
  CFG="$ROOT/boot/firmware/config.txt"
  cp -n "$CFG" "$CFG.sunset-backup"
  sed -i 's/^camera_auto_detect=.*/camera_auto_detect=0/' "$CFG"
  # A plain imx477 line (a one-camera setup) becomes the cam0 one. A cam1 line is never rewritten:
  # rewriting every imx477 line once turned a CM4's second camera off.
  sed -i 's/^dtoverlay=imx477$/dtoverlay=imx477,cam0/' "$CFG"
  if ! grep -qx 'dtoverlay=imx477,cam0' "$CFG"; then
    sed -i '0,/^\[all\]/s//[all]\ndtoverlay=imx477,cam0/' "$CFG"
    grep -qx 'dtoverlay=imx477,cam0' "$CFG" || echo "dtoverlay=imx477,cam0" >> "$CFG"
  fi
  # The cam1 line goes right after the cam0 one.
  grep -qx 'dtoverlay=imx477,cam1' "$CFG" ||
    sed -i '0,/^dtoverlay=imx477,cam0$/s//dtoverlay=imx477,cam0\ndtoverlay=imx477,cam1/' "$CFG"
  echo "camera: set camera_auto_detect=0 and dtoverlay=imx477,cam0 and cam1 (backup: $CFG.sunset-backup). Reboot to apply."
fi

mkdir -p "$ROOT/etc/systemd/system" "$ROOT/usr/local/bin" "$ROOT/etc/udev/rules.d"
for u in sunset-capture.service sunset-capture.timer sunset-sync.service sunset-sync.timer sunset-dense.service sunset-dense.timer sunset-diag.service sunset-kernlog.service sunset-guard.service sunset-guard.timer sunset-capture2.service sunset-capture2.timer sunset-dense2.service sunset-dense2.timer sunset-ups.service; do
  # Via a temp file: a plain "> unit" empties the live unit first, and a missing source then
  # leaves it empty (2026-11-20, the CM4's second camera lost one slot to that).
  [[ -f "$HERE/systemd/$u" ]] || { echo "missing $HERE/systemd/$u: copy all of pi/systemd first; nothing installed past this point" >&2; exit 1; }
  sed -e "s|^User=.*|User=$RUN_USER|" -e "s|/home/pi/|$HOME_DIR/|g" "$HERE/systemd/$u" > "$ROOT/etc/systemd/system/.$u.tmp"
  mv -f "$ROOT/etc/systemd/system/.$u.tmp" "$ROOT/etc/systemd/system/$u"
done
# The two watchdogs retired in batch B (2026-11-22), now sunset-guard.
for u in sunset-netwatch.timer sunset-camwatch.timer; do
  systemctl disable --now "$u" >/dev/null 2>&1 || true
done
for u in sunset-netwatch.service sunset-netwatch.timer sunset-camwatch.service sunset-camwatch.timer; do
  rm -f "$ROOT/etc/systemd/system/$u"
done
install -m 755 "$HERE/diag" "$ROOT/usr/local/bin/diag"
# LEDs off: they reflect in the window. Applies now and at every boot.
install -m 644 "$HERE/90-sunset-leds.rules" "$ROOT/etc/udev/rules.d/90-sunset-leds.rules"
udevadm control --reload
udevadm trigger --subsystem-match=leds --action=add
# Keeps a frozen Pi from staying frozen. Applies from the next reboot or systemctl daemon-reexec.
install -D -m 644 "$HERE/systemd/sunset-watchdog.conf" "$ROOT/etc/systemd/system.conf.d/sunset-watchdog.conf"
systemctl daemon-reload
# enable --now leaves an already-running service on its old script; this loads the new one.
systemctl try-restart sunset-kernlog.service
systemctl enable --now sunset-kernlog.service
# Does nothing unless NETWATCH=1 (resets a hung USB Wi-Fi dongle, reboots after 30 min without
# the network) or CAMWATCH=1 (reboots when a camera keeps failing) in sunset.env.
systemctl enable --now sunset-guard.timer
# The UPS monitor: a running one picks up the new script; --ups turns it on.
systemctl try-restart sunset-ups.service
if (( UPS )); then
  systemctl enable --now sunset-ups.service
fi
if (( ENABLE )); then
  systemctl enable --now sunset-capture.timer sunset-sync.timer sunset-dense.timer
  # The second camera only where it is set up: its units need sunset2.env (no "-" on that line).
  if [[ -s "$ROOT$HOME_DIR/sunset/sunset2.env" ]]; then
    systemctl enable --now sunset-capture2.timer sunset-dense2.timer
  fi
  systemctl list-timers 'sunset*' --no-pager
else
  echo "units installed for user $RUN_USER; timers NOT enabled. Enable with: sudo systemctl enable --now sunset-capture.timer sunset-sync.timer sunset-dense.timer"
fi
