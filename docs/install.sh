#!/usr/bin/env bash
# Run ON THE PI with sudo, from the directory holding the scripts:
#   sudo ./install.sh [--uc517] [--enable]
# Installs the systemd units for the user who invoked sudo (not hard-coded to "pi"),
# optionally sets the camera overlay for the Arducam UC-517, and does NOT enable the
# timers (and so does not start capturing) unless --enable is given.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
RUN_USER="${SUDO_USER:?run via sudo from your normal user}"
HOME_DIR="$(getent passwd "$RUN_USER" | cut -d: -f6)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UC517=0; ENABLE=0
for a in "$@"; do case "$a" in --uc517) UC517=1 ;; --enable) ENABLE=1 ;; *) echo "unknown option $a" >&2; exit 2 ;; esac; done

if (( UC517 )); then
  CFG=/boot/firmware/config.txt
  cp -n "$CFG" "$CFG.sunset-backup"
  sed -i 's/^camera_auto_detect=.*/camera_auto_detect=0/' "$CFG"
  grep -q '^dtoverlay=imx477' "$CFG" || sed -i '0,/^\[all\]/s//[all]\ndtoverlay=imx477/' "$CFG"
  grep -q '^dtoverlay=imx477' "$CFG" || echo 'dtoverlay=imx477' >> "$CFG"
  echo "camera: set camera_auto_detect=0 and dtoverlay=imx477 (backup: $CFG.sunset-backup). Reboot to apply."
fi

for u in sunset-capture.service sunset-capture.timer sunset-sync.service sunset-sync.timer; do
  sed -e "s|^User=.*|User=$RUN_USER|" -e "s|/home/pi/|$HOME_DIR/|g" "$HERE/systemd/$u" > "/etc/systemd/system/$u"
done
systemctl daemon-reload
if (( ENABLE )); then
  systemctl enable --now sunset-capture.timer sunset-sync.timer
  systemctl list-timers 'sunset*' --no-pager
else
  echo "units installed for user $RUN_USER; timers NOT enabled. Enable with: sudo systemctl enable --now sunset-capture.timer sunset-sync.timer"
fi
