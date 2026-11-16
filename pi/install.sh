#!/usr/bin/env bash
# Run ON THE PI with sudo, from the directory holding the scripts:
#   sudo ./install.sh [--uc517 | --uc517-cam0] [--enable]
# Installs the systemd units for the user who invoked sudo (not hard-coded to "pi"),
# optionally sets the camera overlay for the Arducam UC-517 (--uc517: dtoverlay=imx477;
# --uc517-cam0: dtoverlay=imx477,cam0, for a camera on the CM4's CAM0 port), and does NOT
# enable the timers (and so does not start capturing) unless --enable is given.
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
OVERLAY=""; ENABLE=0
for a in "$@"; do case "$a" in
  --uc517) OVERLAY=imx477 ;;
  --uc517-cam0) OVERLAY=imx477,cam0 ;;
  --enable) ENABLE=1 ;;
  *) echo "unknown option $a" >&2; exit 2 ;; esac; done

if [[ -n "$OVERLAY" ]]; then
  CFG="$ROOT/boot/firmware/config.txt"
  cp -n "$CFG" "$CFG.sunset-backup"
  sed -i 's/^camera_auto_detect=.*/camera_auto_detect=0/' "$CFG"
  # --uc517 leaves an overlay line that is already there; --uc517-cam0 rewrites a plain one
  # (and changes nothing the second time).
  [[ "$OVERLAY" == *cam0 ]] && sed -i "s/^dtoverlay=imx477.*/dtoverlay=$OVERLAY/" "$CFG"
  grep -q '^dtoverlay=imx477' "$CFG" || sed -i "0,/^\[all\]/s//[all]\ndtoverlay=$OVERLAY/" "$CFG"
  grep -q '^dtoverlay=imx477' "$CFG" || echo "dtoverlay=$OVERLAY" >> "$CFG"
  echo "camera: set camera_auto_detect=0 and dtoverlay=$OVERLAY (backup: $CFG.sunset-backup). Reboot to apply."
fi

mkdir -p "$ROOT/etc/systemd/system" "$ROOT/usr/local/bin" "$ROOT/etc/udev/rules.d"
for u in sunset-capture.service sunset-capture.timer sunset-sync.service sunset-sync.timer sunset-dense.service sunset-dense.timer sunset-diag.service sunset-kernlog.service sunset-netwatch.service sunset-netwatch.timer; do
  sed -e "s|^User=.*|User=$RUN_USER|" -e "s|/home/pi/|$HOME_DIR/|g" "$HERE/systemd/$u" > "$ROOT/etc/systemd/system/$u"
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
# Does nothing unless NETWATCH=1 in sunset.env (for a Pi on a USB Wi-Fi dongle).
systemctl enable --now sunset-netwatch.timer
if (( ENABLE )); then
  systemctl enable --now sunset-capture.timer sunset-sync.timer sunset-dense.timer
  systemctl list-timers 'sunset*' --no-pager
else
  echo "units installed for user $RUN_USER; timers NOT enabled. Enable with: sudo systemctl enable --now sunset-capture.timer sunset-sync.timer sunset-dense.timer"
fi
