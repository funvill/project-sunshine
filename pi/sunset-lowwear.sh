#!/usr/bin/env bash
# Run ON THE PI with sudo, once, then reboot:  sudo ./sunset-lowwear.sh
# Cuts SD card writes from the OS. Safe to run again. Backups: <file>.before-lowwear
#
# Trade-off: system logs live in RAM and are lost on reboot. capture.log and sync.log stay on
# the SD. Frames still go through the SD; this only removes the OS's own writes.
#
# Tried and dropped: holding writes in RAM (vm.dirty_expire_centisecs=60000, commit=600) so a
# frame could reach the NAS and be deleted before reaching the SD. On the Pi 3 B+ the frame
# reached the SD anyway in 3 of 3 captures, so it cost power-cut safety and saved nothing.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

FSTAB=/etc/fstab
CMDLINE=/boot/firmware/cmdline.txt
cp -n "$FSTAB" "$FSTAB.before-lowwear"
cp -n "$CMDLINE" "$CMDLINE.before-lowwear"

# System journal in RAM, capped.
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/sunset-lowwear.conf <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=32M
EOF

# Root: commit the ext4 journal every 60 s, not 5 s. A power cut can lose up to a minute of
# small file changes such as log lines. Boot partition: no access-time writes.
awk 'BEGIN{OFS="\t"}
  $1 !~ /^#/ && $2 == "/" && $4 !~ /commit=/ { $4 = $4 ",commit=60" }
  $1 !~ /^#/ && $2 == "/boot/firmware" && $4 !~ /noatime/ { $4 = $4 ",noatime" }
  { print }' "$FSTAB" > "$FSTAB.new"
mv "$FSTAB.new" "$FSTAB"

# Scratch space and system logs in RAM.
add_tmpfs() { # add_tmpfs <path> <options>
  grep -qE "^tmpfs[[:space:]]+$1[[:space:]]" "$FSTAB" || printf 'tmpfs\t%s\ttmpfs\t%s\t0\t0\n' "$1" "$2" >> "$FSTAB"
}
add_tmpfs /tmp     defaults,noatime,nosuid,nodev,mode=1777,size=128M
add_tmpfs /var/tmp defaults,noatime,nosuid,nodev,mode=1777,size=16M
add_tmpfs /var/log defaults,noatime,nosuid,nodev,mode=0755,size=32M
# Packages expect these under /var/log.
echo 'd /var/log/apt 0755 root root -' > /etc/tmpfiles.d/sunset-lowwear.conf

# Background jobs that write to the card and that a frozen OS does not need.
# fstrim stays: telling the card which blocks are free reduces its internal wear.
for u in apt-daily.timer apt-daily-upgrade.timer dpkg-db-backup.timer e2scrub_all.timer \
         e2scrub_reap.service logrotate.timer man-db.timer; do
  systemctl disable --now "$u" 2>/dev/null || true
  systemctl mask "$u" 2>/dev/null || true
done

# Clock save: daily instead of hourly. Capture waits for NTP after boot in any case.
if [[ -e /etc/cron.hourly/fake-hwclock ]]; then
  mv /etc/cron.hourly/fake-hwclock /etc/cron.daily/fake-hwclock
fi

# No swap: ~900 MB of RAM, ~700 MB free while capturing.
if command -v dphys-swapfile >/dev/null 2>&1; then
  dphys-swapfile swapoff || true
  systemctl disable --now dphys-swapfile 2>/dev/null || true
fi
if [[ -e /var/swap ]] && ! /usr/sbin/swapon --show=NAME --noheadings | grep -qx /var/swap; then
  rm -f /var/swap
fi

# Boot command line. Unattended, fsck.repair=yes lets a boot fix the filesystem after a power cut.
ROOT_DEV="$(awk '$1 !~ /^#/ && $2 == "/" {print $1}' "$FSTAB")"
if [[ ! -s "$CMDLINE" ]]; then
  echo "console=tty1 root=$ROOT_DEV rootfstype=ext4 fsck.repair=yes rootwait" > "$CMDLINE"
elif ! grep -q 'fsck.repair=' "$CMDLINE"; then
  sed -i '1s/$/ fsck.repair=yes/' "$CMDLINE"
fi

# Old on-disk logs. The journal moves to RAM above, so nothing reads these any more.
systemctl restart systemd-journald
rm -rf /var/log/journal

systemctl daemon-reload
echo "done. Reboot to apply."
