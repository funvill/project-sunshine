section "systemd units"
# systemd has no trailing comments: "Key=value # note" is taken as the value and, for a
# setting like TimeoutStartSec, rejected and silently ignored.
check "no comment after a setting" \
  sh -c "! grep -nE '^[A-Za-z]+=.*[[:space:]]#' '$SRC'/systemd/*"
check "capture service timeout covers both cameras" grep -qx 'TimeoutStartSec=600' "$SRC/systemd/sunset-capture.service"

section "sunset-lowwear.sh"
check "parses" bash -n "$SRC/sunset-lowwear.sh"

section "dense units"
check "dense timer fires every minute" grep -qx 'OnCalendar=\*:\*:00' "$SRC/systemd/sunset-dense.timer"
check "dense timer is precise" grep -qx 'AccuracySec=1s' "$SRC/systemd/sunset-dense.timer"
check "dense service runs capture in dense mode" grep -qx 'ExecStart=-/home/pi/sunset/sunset-capture.sh --dense' "$SRC/systemd/sunset-dense.service"
check "dense service reads sunset.env" grep -qx 'EnvironmentFile=-/home/pi/sunset/sunset.env' "$SRC/systemd/sunset-dense.service"
check "dense service timeout covers both cameras" grep -qx 'TimeoutStartSec=240' "$SRC/systemd/sunset-dense.service"
check "install.sh installs the dense units" grep -q 'sunset-dense.service sunset-dense.timer' "$SRC/install.sh"
check "install.sh enables the dense timer" grep -q 'enable --now sunset-capture.timer sunset-sync.timer sunset-dense.timer' "$SRC/install.sh"

section "one capture and one dense unit for both cameras (batch B)"
for u in capture dense; do
  f="$SRC/systemd/sunset-$u.service"
  check "$u: first camera, then the second from sunset2.env" bash -c "grep '^ExecStart=' '$f' | sed -n 2p | grep -q -- '--env /home/pi/sunset/sunset2.env\$'"
  check "$u: exactly two cameras" test "$(grep -c '^ExecStart=' "$f")" = 2
  check "$u: a failed first camera does not stop the second" bash -c "! grep '^ExecStart=' '$f' | grep -qv '^ExecStart=-'"
  check "$u: no EnvironmentFile for sunset2.env (it would apply to both lines)" bash -c "! grep -q 'sunset2.env' <(grep '^EnvironmentFile' '$f')"
done
check "no second-camera units left" bash -c "! ls '$SRC'/systemd/sunset-*2.* 2>/dev/null | grep -q ."
check "diag stops the two capture timers" grep -qx 'ExecStartPre=+/bin/systemctl stop sunset-capture.timer sunset-dense.timer' "$SRC/systemd/sunset-diag.service"
check "no unit names a *2 timer" bash -c "! grep -l 'capture2\|dense2' '$SRC'/systemd/*"

section "capture every 5 minutes"
check "capture timer fires every 5 minutes" grep -qx 'OnCalendar=\*:00/5' "$SRC/systemd/sunset-capture.timer"
check "dense mode skips the same slot minutes" grep -q 'SLOT_EVERY_MIN="${SLOT_EVERY_MIN:-5}"' "$SRC/sunset-capture.sh"

section "LEDs off (reflections in the window)"
R="$SRC/90-sunset-leds.rules"
check "rule turns off every LED as it appears" \
  grep -qx 'ACTION=="add", SUBSYSTEM=="leds", ATTR{trigger}="none", ATTR{brightness}="0"' "$R"
check "install.sh installs the LED rule" grep -qF '90-sunset-leds.rules" "$ROOT/etc/udev/rules.d/' "$SRC/install.sh"
check "install.sh applies it without a reboot" grep -q 'udevadm trigger --subsystem-match=leds' "$SRC/install.sh"
