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

section "capture every 5 minutes"
check "capture timer fires every 5 minutes" grep -qx 'OnCalendar=\*:00/5' "$SRC/systemd/sunset-capture.timer"
check "dense mode skips the same slot minutes" grep -q 'SLOT_EVERY_MIN="${SLOT_EVERY_MIN:-5}"' "$SRC/sunset-capture.sh"

section "LEDs off (reflections in the window)"
R="$SRC/90-sunset-leds.rules"
check "rule turns off every LED as it appears" \
  grep -qx 'ACTION=="add", SUBSYSTEM=="leds", ATTR{trigger}="none", ATTR{brightness}="0"' "$R"
check "install.sh installs the LED rule" grep -q '90-sunset-leds.rules" /etc/udev/rules.d/' "$SRC/install.sh"
check "install.sh applies it without a reboot" grep -q 'udevadm trigger --subsystem-match=leds' "$SRC/install.sh"
