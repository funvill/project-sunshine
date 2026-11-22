# install.sh and sunset-lowwear.sh against fixture copies of config.txt, cmdline.txt and fstab
# (ROOT= prefix; issue #23). systemctl and udevadm are stubs that record their calls.
fix_root() { # fresh fixture tree in $R, stub commands first on PATH
  fresh_env; R="$W/root"
  mkdir -p "$R/boot/firmware" "$R/etc" "$R/etc/cron.hourly" "$R/etc/cron.daily" "$W/bin"
  printf '%s\n' \
    '# For more options see the documentation' \
    'dtparam=audio=on' \
    'camera_auto_detect=1' \
    'display_auto_detect=1' \
    'dtoverlay=vc4-kms-v3d' \
    '' \
    '[cm4]' \
    'otg_mode=1' \
    '' \
    '[all]' \
    'enable_uart=1' > "$R/boot/firmware/config.txt"
  printf '%s\n' 'console=serial0,115200 console=tty1 root=PARTUUID=abcd1234-02 rootfstype=ext4 rootwait' > "$R/boot/firmware/cmdline.txt"
  printf '%s\n' \
    'proc            /proc           proc    defaults          0       0' \
    'PARTUUID=abcd1234-01  /boot/firmware  vfat    defaults          0       2' \
    'PARTUUID=abcd1234-02  /               ext4    defaults,noatime  0       1' > "$R/etc/fstab"
  printf '#!/bin/sh\necho "udevadm $*" >> "${STUB_CALLS:-/dev/null}"\n' > "$W/bin/udevadm"; chmod +x "$W/bin/udevadm"
  export PATH="$W/bin:$PATH"
  export INSTALL_USER=tester INSTALL_HOME=/home/tester
}
inst() { ROOT="$R" bash "$SRC/install.sh" "$@" >"$W/install.out" 2>&1; }
low()  { ROOT="$R" bash "$SRC/sunset-lowwear.sh" >"$W/low.out" 2>&1; }
cfg="boot/firmware/config.txt"
n_overlay() { grep -c '^dtoverlay=imx477' "$R/$cfg"; }
# Run each fixture under a private PATH so the stub dir from one case does not pile up.
_path0="$PATH"
fix_root_() { PATH="$_path0"; fix_root; }

section "install.sh: units rewritten for the user and home"
fix_root_; inst; rc=$?
check "exits 0" test "$rc" = 0
U="$R/etc/systemd/system"
check "capture service runs as the user" grep -qx 'User=tester' "$U/sunset-capture.service"
check "capture service uses the user's home" grep -qx 'ExecStart=-/home/tester/sunset/sunset-capture.sh' "$U/sunset-capture.service"
check "second camera's env file in the user's home" grep -qx 'ExecStart=-/home/tester/sunset/sunset-capture.sh --env /home/tester/sunset/sunset2.env' "$U/sunset-capture.service"
check "env file path rewritten" grep -qx 'EnvironmentFile=-/home/tester/sunset/sunset.env' "$U/sunset-sync.service"
check "no unit still says /home/pi" bash -c "! grep -l '/home/pi' '$U'/sunset-*.service '$U'/sunset-*.timer"
check "no unit keeps User=pi" bash -c "! grep -l '^User=pi' '$U'/sunset-*.service"
check "all eleven units installed" test "$(ls "$U"/sunset-*.service "$U"/sunset-*.timer | wc -l | tr -d ' ')" = 11
check "ups unit installed for the user's home" grep -qx 'Environment=UPS_LOG_FILE=/home/tester/sunset/ups.log' "$U/sunset-ups.service"
check "ups monitor runs as root (it reads /dev/hidraw)" bash -c "! grep -q '^User=' '$U/sunset-ups.service'"
check "ups monitor not enabled without --ups" bash -c "! grep -q 'enable --now sunset-ups.service' '$STUB_CALLS'"
check "a running ups monitor picks up the new script" grep -q 'systemctl try-restart sunset-ups.service' "$STUB_CALLS"
check "watchdogs enabled" grep -q 'systemctl enable --now sunset-guard.timer' "$STUB_CALLS"
check "diag installed" test -x "$R/usr/local/bin/diag"
check "LED rule installed" test -f "$R/etc/udev/rules.d/90-sunset-leds.rules"
check "watchdog setting installed" test -f "$R/etc/systemd/system.conf.d/sunset-watchdog.conf"
check "no backup made without a camera option" test ! -e "$R/$cfg.sunset-backup"
check "config.txt untouched without a camera option" grep -qx 'camera_auto_detect=1' "$R/$cfg"
check "timers not enabled without --enable" bash -c "! grep -q 'enable --now sunset-capture.timer' '$STUB_CALLS'"

section "install.sh: kernlog restarted after daemon-reload"
r="$(grep -n 'systemctl daemon-reload' "$STUB_CALLS" | head -n1 | cut -d: -f1)"
t="$(grep -n 'systemctl try-restart sunset-kernlog.service' "$STUB_CALLS" | head -n1 | cut -d: -f1)"
check "daemon-reload called" test -n "$r"
check "try-restart sunset-kernlog.service called" test -n "$t"
check "try-restart comes after daemon-reload" test "${t:-0}" -gt "${r:-99}"

section "install.sh --enable"
fix_root_; inst --enable
check "capture, sync and dense timers enabled" grep -q 'systemctl enable --now sunset-capture.timer sunset-sync.timer sunset-dense.timer' "$STUB_CALLS"
check "no second-camera timers enabled" bash -c "! grep -q 'enable.*sunset-capture2.timer' '$STUB_CALLS'"

section "install.sh: retires the units replaced in batch B"
fix_root_; U="$R/etc/systemd/system"; mkdir -p "$U"
for u in sunset-capture2.service sunset-capture2.timer sunset-dense2.service sunset-dense2.timer sunset-netwatch.service sunset-netwatch.timer sunset-camwatch.service sunset-camwatch.timer; do echo old > "$U/$u"; done
inst; rc=$?
check "exits 0" test "$rc" = 0
for t in sunset-capture2 sunset-dense2 sunset-netwatch sunset-camwatch; do
  check "$t.timer disabled and stopped" grep -qx "systemctl disable --now $t.timer" "$STUB_CALLS"
  check "$t units removed" test ! -e "$U/$t.service" -a ! -e "$U/$t.timer"
done
check "removed before daemon-reload" test "$(grep -n 'disable --now sunset-camwatch.timer' "$STUB_CALLS" | cut -d: -f1)" -lt "$(grep -n 'daemon-reload' "$STUB_CALLS" | cut -d: -f1)"
fix_root_; inst; rc=$?
check "nothing to retire is fine" test "$rc" = 0

section "install.sh --ups (issue #29)"
fix_root_; inst --ups; rc=$?
check "exits 0" test "$rc" = 0
check "ups monitor enabled and started" grep -q 'systemctl enable --now sunset-ups.service' "$STUB_CALLS"
check "--ups alone does not start capturing" bash -c "! grep -q 'enable --now sunset-capture.timer' '$STUB_CALLS'"

section "install.sh: a missing unit file never empties the live one"
fix_root_; inst; mkdir -p "$W/pi-copy"; cp -r "$SRC"/. "$W/pi-copy/"; rm "$W/pi-copy/systemd/sunset-dense.service"
live="$R/etc/systemd/system/sunset-dense.service"; before="$(cat "$live")"
ROOT="$R" bash "$W/pi-copy/install.sh" >"$W/install.out" 2>&1; rc=$?
check "exits 1" test "$rc" = 1
check "says which file is missing" grep -q 'missing .*sunset-dense.service' "$W/install.out"
check "live unit unchanged" test "$(cat "$live")" = "$before"
check "no temp unit left" test -z "$(find "$R/etc/systemd/system" -name '.*.tmp')"

section "install.sh: unknown option and missing user"
fix_root_; inst --bogus; rc=$?
check "unknown option exits 2" test "$rc" = 2
fix_root_; unset INSTALL_USER; inst; rc=$?
check "ROOT without INSTALL_USER refuses" test "$rc" != 0

section "install.sh --cm4-two: both CM4 camera ports (2026-11-17)"
fix_root_; inst --cm4-two; rc=$?
check "exits 0" test "$rc" = 0
check "camera_auto_detect=0" grep -qx 'camera_auto_detect=0' "$R/$cfg"
check "cam0 line" grep -qx 'dtoverlay=imx477,cam0' "$R/$cfg"
check "cam1 line" grep -qx 'dtoverlay=imx477,cam1' "$R/$cfg"
check "exactly two imx477 lines" test "$(n_overlay)" = 2
check "added under [all]" bash -c "awk '/^\[all\]/{f=1;next} f&&/^dtoverlay=imx477,cam0/{ok=1} END{exit !ok}' '$R/$cfg'"
check "cam1 right after cam0" bash -c "grep -A1 -x 'dtoverlay=imx477,cam0' '$R/$cfg' | grep -qx 'dtoverlay=imx477,cam1'"
check "other lines kept" grep -qx 'dtoverlay=vc4-kms-v3d' "$R/$cfg"
check "backup of the original" grep -qx 'camera_auto_detect=1' "$R/$cfg.sunset-backup"
first="$(cksum < "$R/$cfg")"
inst --cm4-two
check "second run: no change" test "$(cksum < "$R/$cfg")" = "$first"
check "second run keeps the first backup" grep -qx 'camera_auto_detect=1' "$R/$cfg.sunset-backup"
fix_root_; sed -i 's/^\[all\]$/[all]\ndtoverlay=imx477/' "$R/$cfg"
inst --cm4-two
check "a plain overlay becomes cam0, not duplicated" test "$(grep -c '^dtoverlay=imx477,cam0$' "$R/$cfg")$(n_overlay)" = 12
check "no plain line left" bash -c "! grep -qx 'dtoverlay=imx477' '$R/$cfg'"
fix_root_; sed -i 's/^\[all\]$/[all]\ndtoverlay=imx477,cam1/' "$R/$cfg"
inst --cm4-two
check "an existing cam1 line is kept, not doubled" test "$(grep -c '^dtoverlay=imx477,cam1$' "$R/$cfg")$(n_overlay)" = 12
fix_root_; sed -i '/^\[all\]/,$d' "$R/$cfg"
inst --cm4-two
check "no [all] section: both lines appended" test "$(n_overlay)" = 2

section "sunset-lowwear.sh: fstab, cmdline and files"
fix_root_
cp "$R/etc/fstab" "$W/fstab.orig"; cp "$R/boot/firmware/cmdline.txt" "$W/cmdline.orig"
low; rc=$?
check "exits 0" test "$rc" = 0
check "root gets commit=60" grep -qE '^PARTUUID=abcd1234-02[[:space:]]+/[[:space:]]+ext4[[:space:]]+defaults,noatime,commit=60[[:space:]]' "$R/etc/fstab"
check "boot partition gets noatime" grep -qE '^PARTUUID=abcd1234-01[[:space:]]+/boot/firmware[[:space:]]+vfat[[:space:]]+defaults,noatime[[:space:]]' "$R/etc/fstab"
check "proc line unchanged" grep -qE '^proc[[:space:]]+/proc[[:space:]]+proc[[:space:]]+defaults[[:space:]]+0[[:space:]]+0$' "$R/etc/fstab"
for m in /tmp /var/tmp /var/log; do
  check "tmpfs for $m" grep -qE "^tmpfs[[:space:]]+$m[[:space:]]+tmpfs[[:space:]]" "$R/etc/fstab"
done
check "fstab backup is the original" cmp -s "$R/etc/fstab.before-lowwear" "$W/fstab.orig"
check "cmdline gets fsck.repair=yes once" test "$(grep -o 'fsck.repair=yes' "$R/boot/firmware/cmdline.txt" | wc -l | tr -d ' ')" = 1
check "cmdline keeps its other arguments" grep -q 'root=PARTUUID=abcd1234-02 rootfstype=ext4 rootwait' "$R/boot/firmware/cmdline.txt"
check "cmdline stays one line" test "$(wc -l < "$R/boot/firmware/cmdline.txt" | tr -d ' ')" = 1
check "cmdline backup is the original" cmp -s "$R/boot/firmware/cmdline.txt.before-lowwear" "$W/cmdline.orig"
check "journal in RAM" grep -qx 'Storage=volatile' "$R/etc/systemd/journald.conf.d/sunset-lowwear.conf"
check "tmpfiles entry written" test -s "$R/etc/tmpfiles.d/sunset-lowwear.conf"
check "logrotate timer masked" grep -q 'systemctl mask logrotate.timer' "$STUB_CALLS"
check "apt-daily timer disabled" grep -q 'systemctl disable --now apt-daily.timer' "$STUB_CALLS"
check "swap not touched in a ROOT run" bash -c "! grep -q swap '$STUB_CALLS'"
f1="$(cksum < "$R/etc/fstab")"; c1="$(cksum < "$R/boot/firmware/cmdline.txt")"
low; rc=$?
check "second run exits 0" test "$rc" = 0
check "second run: fstab unchanged" test "$(cksum < "$R/etc/fstab")" = "$f1"
check "second run: cmdline unchanged" test "$(cksum < "$R/boot/firmware/cmdline.txt")" = "$c1"
check "second run: fstab backup still the original" cmp -s "$R/etc/fstab.before-lowwear" "$W/fstab.orig"
check "second run: one tmpfs line per path" test "$(grep -c '^tmpfs' "$R/etc/fstab")" = 3

section "sunset-lowwear.sh: empty cmdline.txt and the fake-hwclock job"
fix_root_; : > "$R/boot/firmware/cmdline.txt"; echo '#!/bin/sh' > "$R/etc/cron.hourly/fake-hwclock"
low
check "empty cmdline rebuilt with the root device from fstab" grep -qx 'console=tty1 root=PARTUUID=abcd1234-02 rootfstype=ext4 fsck.repair=yes rootwait' "$R/boot/firmware/cmdline.txt"
check "fake-hwclock moved to daily" test -e "$R/etc/cron.daily/fake-hwclock" -a ! -e "$R/etc/cron.hourly/fake-hwclock"
fix_root_; low
check "root line is not given commit= twice" bash -c "! grep -q 'commit=60,commit' '$R/etc/fstab'"

section "refuse without root when ROOT is unset"
if [[ "$(id -u)" != 0 ]]; then
  out="$(env -u ROOT bash "$SRC/sunset-lowwear.sh" 2>&1)"; rc=$?
  check "lowwear exits 1" test "$rc" = 1
  check "lowwear says to use sudo" grep -q 'run with sudo' <<<"$out"
  out="$(env -u ROOT -u SUDO_USER bash "$SRC/install.sh" 2>&1)"; rc=$?
  check "install.sh also refuses" test "$rc" = 1
else
  echo "  SKIP: running as root; the refuse-without-root checks did not run"
fi
PATH="$_path0"
