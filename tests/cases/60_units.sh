section "systemd units"
# systemd has no trailing comments: "Key=value # note" is taken as the value and, for a
# setting like TimeoutStartSec, rejected and silently ignored.
check "no comment after a setting" \
  sh -c "! grep -nE '^[A-Za-z]+=.*[[:space:]]#' '$SRC'/systemd/*"
check "capture service timeout is set" grep -qx 'TimeoutStartSec=300' "$SRC/systemd/sunset-capture.service"

section "sunset-lowwear.sh"
check "parses" bash -n "$SRC/sunset-lowwear.sh"

section "dense units"
check "dense timer fires every minute" grep -qx 'OnCalendar=\*:\*:00' "$SRC/systemd/sunset-dense.timer"
check "dense timer is precise" grep -qx 'AccuracySec=1s' "$SRC/systemd/sunset-dense.timer"
check "dense service runs capture in dense mode" grep -qx 'ExecStart=/home/pi/sunset/sunset-capture.sh --dense' "$SRC/systemd/sunset-dense.service"
check "dense service reads sunset.env" grep -qx 'EnvironmentFile=-/home/pi/sunset/sunset.env' "$SRC/systemd/sunset-dense.service"
check "dense service timeout is set" grep -qx 'TimeoutStartSec=120' "$SRC/systemd/sunset-dense.service"
check "install.sh installs the dense units" grep -q 'sunset-dense.service sunset-dense.timer' "$SRC/install.sh"
check "install.sh enables the dense timer" grep -q 'enable --now sunset-capture.timer sunset-sync.timer sunset-dense.timer' "$SRC/install.sh"

section "second camera: its own units, 30 s after the first"
# Back from one combined run on 2026-11-23: with cm4city starting the moment cm4wide finished,
# cm4wide's capture failed about one slot in three (Unicam "Failed to queue buffer").
check "capture2 timer 30 s after the first" grep -qx 'OnCalendar=\*:00/5:30' "$SRC/systemd/sunset-capture2.timer"
check "dense2 timer at :30" grep -qx 'OnCalendar=\*:\*:30' "$SRC/systemd/sunset-dense2.timer"
for u in capture dense; do
  check "$u: first camera's unit takes one camera" test "$(grep -c '^ExecStart=' "$SRC/systemd/sunset-$u.service")" = 1
  check "$u: first camera's unit doesn't read sunset2.env" bash -c "! grep -q sunset2.env '$SRC/systemd/sunset-$u.service'"
  check "${u}2: reads sunset2.env over sunset.env" bash -c "grep '^EnvironmentFile' '$SRC/systemd/sunset-${u}2.service' | tail -n1 | grep -qx 'EnvironmentFile=/home/pi/sunset/sunset2.env'"
done
check "diag stops the second camera's timers" grep -qx 'ExecStartPre=-+/bin/systemctl stop sunset-capture2.timer sunset-dense2.timer' "$SRC/systemd/sunset-diag.service"
check "diag starts them again" grep -q 'systemctl start sunset-capture2.timer sunset-dense2.timer' "$SRC/systemd/sunset-diag.service"

section "capture every 5 minutes"
check "capture timer fires every 5 minutes" grep -qx 'OnCalendar=\*:00/5' "$SRC/systemd/sunset-capture.timer"
check "dense mode skips the same slot minutes" grep -q 'SLOT_EVERY_MIN="${SLOT_EVERY_MIN:-5}"' "$SRC/sunset-capture.sh"

section "LEDs off (reflections in the window)"
R="$SRC/90-sunset-leds.rules"
check "rule turns off every LED as it appears" \
  grep -qx 'ACTION=="add", SUBSYSTEM=="leds", ATTR{trigger}="none", ATTR{brightness}="0"' "$R"
check "install.sh installs the LED rule" grep -qF '90-sunset-leds.rules" "$ROOT/etc/udev/rules.d/' "$SRC/install.sh"
check "install.sh applies it without a reboot" grep -q 'udevadm trigger --subsystem-match=leds' "$SRC/install.sh"
