# sunset-guard.sh, the Pi's two watchdogs on one timer (batch B, 2026-11-22; until then
# sunset-netwatch.sh and sunset-camwatch.sh). 67_clock_marker uses the helpers here.
#
# Network check (NETWATCH=1): brings a hung Wi-Fi dongle back (CM4 outage, 2026-11-13).
# Fake sysfs: wlan0 is interface 1.0 of USB device 1-1.3.
net_env() {
  fresh_env
  export NETWATCH=1 NETWATCH_STATE="$W/run" NETWATCH_LOG="$W/netwatch.log" NETWATCH_SYSFS="$W/sys"
  export NETWATCH_REBOOT_MARK="$W/.netwatch-reboot" NETWATCH_SETTLE_S=0
  unset NETWATCH_IFACE NETWATCH_TARGET NETWATCH_WIRED STUB_GATEWAY STUB_PING_DOWN CAMWATCH
  export STUB_PING=ok
  mkdir -p "$W/sys/devices/usb1/1-1/1-1.3/1-1.3:1.0" "$W/sys/class/net/wlan0" "$W/sys/bus/usb/drivers/usb"
  # Git Bash copies instead of linking unless asked for a native link; ignored on Linux.
  MSYS=winsymlinks:nativestrict ln -s "$W/sys/devices/usb1/1-1/1-1.3/1-1.3:1.0" "$W/sys/class/net/wlan0/device"
  : > "$W/sys/bus/usb/drivers/usb/unbind"; : > "$W/sys/bus/usb/drivers/usb/bind"
}
netwatch() { NETWATCH_UPTIME="$1" bash "$SRC/sunset-guard.sh"; }  # uptime in seconds

section "netwatch: off unless NETWATCH=1"
net_env; export NETWATCH=0 STUB_PING=fail
netwatch 600; netwatch 4000
check "does nothing when off" test ! -s "$STUB_CALLS"
unset NETWATCH; netwatch 4000
check "off by default" test ! -s "$STUB_CALLS"

section "netwatch: network up"
net_env
netwatch 600; rc=$?
check "exits 0" test "$rc" = 0
check "pings the default gateway through wlan0" grep -q 'ping .*-I wlan0.* 192.0.2.1' "$STUB_CALLS"
check "writes nothing to the SD when all is well" test ! -e "$NETWATCH_LOG"

section "netwatch: short outage is left alone"
net_env; export STUB_PING=fail
netwatch 1000; netwatch 1300
check "no reset before 10 minutes" test ! -s "$W/sys/bus/usb/drivers/usb/unbind"
check "no reboot" sh -c "! grep -q reboot '$STUB_CALLS'"
export STUB_PING=ok; netwatch 1400
check "logs the recovery" grep -q 'network back after' "$NETWATCH_LOG"
check "clears its state" test ! -e "$NETWATCH_STATE"

section "netwatch: resets the dongle after 10 minutes"
net_env; export STUB_PING=fail
netwatch 1000; netwatch 1610
check "unbinds the dongle's USB device" grep -qx '1-1.3' "$W/sys/bus/usb/drivers/usb/unbind"
check "binds it again" grep -qx '1-1.3' "$W/sys/bus/usb/drivers/usb/bind"
check "logs the reset" grep -q 'reset the Wi-Fi dongle (USB 1-1.3)' "$NETWATCH_LOG"
: > "$W/sys/bus/usb/drivers/usb/unbind"; netwatch 1730
check "resets only once per outage" test ! -s "$W/sys/bus/usb/drivers/usb/unbind"

section "netwatch: no gateway counts as down"
net_env; export STUB_GATEWAY="" STUB_PING=ok
netwatch 1000; netwatch 1610
check "resets when there is no default route" grep -qx '1-1.3' "$W/sys/bus/usb/drivers/usb/unbind"

section "netwatch: Wi-Fi down while Ethernet works is left alone"
# The CM4 has been on wired Ethernet since 2026-11-24, with the dongle as a fallback route.
net_env; export STUB_PING_DOWN=wlan0
netwatch 1000; netwatch 1610; netwatch 5810
check "tries the gateway through eth0" grep -q 'ping .*-I eth0.* 192.0.2.1' "$STUB_CALLS"
check "no dongle reset" test ! -s "$W/sys/bus/usb/drivers/usb/unbind"
check "no reboot" sh -c "! grep -q reboot '$STUB_CALLS'"
check "writes nothing to the SD" test ! -e "$NETWATCH_LOG"
net_env; export STUB_PING_DOWN="wlan0 eth0"
netwatch 1000; netwatch 1610
check "both down: resets the dongle" grep -qx '1-1.3' "$W/sys/bus/usb/drivers/usb/unbind"
net_env; export STUB_PING_DOWN="wlan0 eth1" NETWATCH_WIRED="eth1 eth0"
netwatch 1000; netwatch 1610
check "any of NETWATCH_WIRED will do" test ! -s "$W/sys/bus/usb/drivers/usb/unbind"
net_env; export STUB_PING_DOWN=wlan0 NETWATCH_WIRED=""
netwatch 1000; netwatch 1610
check "NETWATCH_WIRED empty: Wi-Fi alone counts" grep -qx '1-1.3' "$W/sys/bus/usb/drivers/usb/unbind"

section "netwatch: reboots after 30 minutes, at most every 6 hours"
net_env; export STUB_PING=fail
netwatch 4000; netwatch 4000; netwatch 5810
check "reboots" grep -q 'systemctl reboot' "$STUB_CALLS"
check "logs why" grep -q 'rebooting: no network for 30 min' "$NETWATCH_LOG"
check "remembers the reboot on the SD" test -e "$NETWATCH_REBOOT_MARK"
: > "$STUB_CALLS"; rm -rf "$NETWATCH_STATE"
netwatch 4000; netwatch 5810
check "no second reboot within 6 hours" sh -c "! grep -q 'systemctl reboot' '$STUB_CALLS'"
touch -d '7 hours ago' "$NETWATCH_REBOOT_MARK"; netwatch 5900
check "reboots again after 6 hours" grep -q 'systemctl reboot' "$STUB_CALLS"

unset NETWATCH NETWATCH_STATE NETWATCH_LOG NETWATCH_SYSFS NETWATCH_REBOOT_MARK NETWATCH_SETTLE_S NETWATCH_WIRED STUB_PING STUB_PING_DOWN STUB_GATEWAY

# Camera check (CAMWATCH=1): reboots when a camera keeps failing (both CM4 cameras, 14:05 UTC 2026-11-19
# to the reboot at 06:37 UTC 2026-11-20; a reboot cleared it). Times are fixed with CAMWATCH_NOW
# (epoch) and CAMWATCH_UPTIME (s), so the log lines below are relative to NOW.
NOW=1795165200   # 2026-11-20T07:00:00Z
cam_env() {
  fresh_env
  export CAMWATCH=1 CAMWATCH_LOG="$W/camwatch.log" CAMWATCH_CAPTURE_LOG="$W/capture.log"
  export CAMWATCH_REBOOT_MARK="$W/.camwatch-reboot" CAMWATCH_NOW=$NOW CAMWATCH_UPTIME=86400
  export CAMWATCH_STATE="$W/run"
  unset CAMWATCH_FAILS CAMWATCH_WINDOW_MIN CAMWATCH_REBOOT_GAP_H NETWATCH
  : > "$W/capture.log"
}
camwatch() { bash "$SRC/sunset-guard.sh"; }
at() { date -u -d "@$(( NOW - $1 * 60 ))" +%FT%TZ; }   # at <minutes ago>
line() { echo "$(at "$1") cam=$2 $3" >> "$W/capture.log"; }   # line <minutes ago> <camera> <text>
fail() { line "$1" "$2" "FAILED capture rc=124 err=ERROR: Device timeout detected|"; }
okay() { line "$1" "$2" "lux=12 soc=40'C disk=6% raw=0 night=0 meta=ok sun=az=240,el=1 ok"; }

section "camwatch: off unless CAMWATCH=1"
cam_env; export CAMWATCH=0
fail 50 cm4city; fail 30 cm4city; fail 10 cm4city
camwatch
check "does nothing when off" sh -c "! grep -q reboot '$STUB_CALLS' 2>/dev/null"
unset CAMWATCH; camwatch
check "off by default" sh -c "! grep -q reboot '$STUB_CALLS' 2>/dev/null"

section "camwatch: healthy cameras"
cam_env
okay 20 cm4wide; okay 15 cm4city; okay 5 cm4wide
camwatch; rc=$?
check "exits 0" test "$rc" = 0
check "no reboot" sh -c "! grep -q reboot '$STUB_CALLS' 2>/dev/null"
check "writes nothing to the SD when all is well" test ! -e "$CAMWATCH_LOG"
cam_env; rm -f "$W/capture.log"; camwatch; rc=$?
check "no capture log is not an error" test "$rc" = 0

section "camwatch: scattered failures are left alone"
cam_env
fail 55 cm4city; okay 50 cm4city; fail 25 cm4city; okay 20 cm4city
fail 40 cm4wide
camwatch
check "two failures in the hour: no reboot" sh -c "! grep -q reboot '$STUB_CALLS' 2>/dev/null"
cam_env
fail 125 cm4city; fail 95 cm4city; fail 65 cm4city; fail 30 cm4city
camwatch
check "failures spread over hours: no reboot" sh -c "! grep -q reboot '$STUB_CALLS' 2>/dev/null"

section "camwatch: one camera failing 3 times within 60 minutes reboots"
cam_env
fail 50 cm4wide; okay 45 cm4wide; fail 30 cm4wide; okay 25 cm4wide; fail 5 cm4wide
okay 40 cm4city
camwatch
check "reboots" grep -q 'systemctl reboot' "$STUB_CALLS"
check "logs which camera and why" grep -q 'rebooting: cm4wide failed 3 captures in 60 min' "$CAMWATCH_LOG"
check "remembers the reboot on the SD" test -e "$CAMWATCH_REBOOT_MARK"

section "camwatch: the window ends now"
cam_env
fail -10 cm4city; fail -20 cm4city; fail -30 cm4city; fail 30 cm4city
camwatch
check "lines stamped after now don't count (a clock step, or replaying an old log)" sh -c "! grep -q reboot '$STUB_CALLS' 2>/dev/null"

section "camwatch: counts per camera, not both together"
cam_env
fail 50 cm4wide; fail 30 cm4city; fail 10 cm4wide
camwatch
check "two on one camera and one on the other: no reboot" sh -c "! grep -q reboot '$STUB_CALLS' 2>/dev/null"

section "camwatch: what counts as a failure"
cam_env
line 40 cm4city "dense window=sunset FAILED capture rc=124 err=Failed to queue buffer for Unicam Image|"
line 30 cm4city "FAILED night rc=124 err=Device timeout|"
fail 20 cm4city
camwatch
check "dense and night failures count" grep -q 'systemctl reboot' "$STUB_CALLS"
cam_env
line 40 cm4city "FAILED capture(empty jpg) rc=0 err=|"
line 30 cm4city "FAILED capture(empty jpg) rc=0 err=|"
line 20 cm4city "dense window=sunset FAILED capture(empty jpg) rc=0 err=|"
camwatch
check "empty-JPEG failures count" grep -q 'systemctl reboot' "$STUB_CALLS"
cam_env
line 40 cm4city "FAILED publish cm4city_x.jpg err=No space left|"
line 30 cm4city "FAILED publish cm4city_y.jpg err=No space left|"
line 20 cm4city "FAILED publish cm4city_z.jpg err=No space left|"
line 15 cm4city "dense window=sunset skipped: camera busy"
line 10 cm4city "WARN capture failed after 0 s rc=255: retrying err=failed to acquire camera"
camwatch
check "storage failures, skips and retried warnings don't count" sh -c "! grep -q reboot '$STUB_CALLS' 2>/dev/null"

section "camwatch: only failures since this boot count"
cam_env; export CAMWATCH_UPTIME=900   # booted 15 minutes ago
fail 50 cm4city; fail 30 cm4city; fail 20 cm4city; fail 5 cm4city
camwatch
check "failures from before the reboot are ignored" sh -c "! grep -q reboot '$STUB_CALLS' 2>/dev/null"
fail 4 cm4city; fail 3 cm4city
camwatch
check "three since boot still reboot" grep -q 'systemctl reboot' "$STUB_CALLS"

section "camwatch: at most one reboot every 6 hours"
cam_env
fail 50 cm4city; fail 30 cm4city; fail 10 cm4city
camwatch
: > "$STUB_CALLS"; camwatch
check "no second reboot within 6 hours" sh -c "! grep -q 'systemctl reboot' '$STUB_CALLS'"
check "says it is holding back, once" test "$(grep -c 'not rebooting' "$CAMWATCH_LOG")" = 1
camwatch
check "doesn't repeat the hold-back line every run" test "$(grep -c 'not rebooting' "$CAMWATCH_LOG")" = 1
touch -d '7 hours ago' "$CAMWATCH_REBOOT_MARK"; camwatch
check "reboots again after 6 hours" grep -q 'systemctl reboot' "$STUB_CALLS"

section "camwatch: settings"
cam_env; export CAMWATCH_FAILS=2 CAMWATCH_WINDOW_MIN=30
fail 25 cm4city; fail 10 cm4city
camwatch
check "CAMWATCH_FAILS and CAMWATCH_WINDOW_MIN are honoured" grep -q 'cm4city failed 2 captures in 30 min' "$CAMWATCH_LOG"

section "camwatch: leaves the clock for the capture after the reboot"
cam_env; export CLOCK_OK_FILE="$W/clock-ok"; : > "$CLOCK_OK_FILE"
fail 50 cm4city; fail 30 cm4city; fail 10 cm4city
camwatch
check "writes the clock-trust file next to the log" test -s "$W/.clock-trusted"
cam_env; export CLOCK_OK_FILE="$W/no-such-flag" STUB_NTP=no
fail 50 cm4city; fail 30 cm4city; fail 10 cm4city
camwatch
check "no clock-trust file without a trusted clock" test ! -e "$W/.clock-trusted"


section "guard: both checks in one run"
both_env() { # the network down, healthy cameras so far
  net_env; export STUB_PING=fail CAMWATCH=1 CAMWATCH_LOG="$W/camwatch.log" CAMWATCH_CAPTURE_LOG="$W/capture.log"
  export CAMWATCH_REBOOT_MARK="$W/.camwatch-reboot" CAMWATCH_STATE="$W/camrun" CAMWATCH_NOW=$NOW CAMWATCH_UPTIME=86400
  : > "$W/capture.log"
}
three_fails() { fail 50 cm4city; fail 30 cm4city; fail 10 cm4city; }
both_env; netwatch 1000; three_fails; netwatch 1610
check "the network check still resets the dongle" grep -qx '1-1.3' "$W/sys/bus/usb/drivers/usb/unbind"
check "and the camera check still reboots in the same run" grep -q 'rebooting: cm4city failed 3 captures' "$CAMWATCH_LOG"
both_env; netwatch 4000; three_fails; netwatch 5810
check "network and camera both due: one reboot, not two" test "$(grep -c 'systemctl reboot' "$STUB_CALLS")" = 1
check "the network check went first" grep -q 'rebooting: no network' "$NETWATCH_LOG"
check "  so the camera check did not run" test ! -e "$CAMWATCH_LOG"
both_env; touch "$NETWATCH_REBOOT_MARK"; netwatch 4000; three_fails; netwatch 5810
check "each check keeps its own 6-hour limit: the camera reboots" grep -q 'rebooting: cm4city failed' "$CAMWATCH_LOG"
check "  while the network one holds back" sh -c "! grep -q 'rebooting: no network' '$NETWATCH_LOG' 2>/dev/null"
check "  one reboot" test "$(grep -c 'systemctl reboot' "$STUB_CALLS")" = 1
unset CAMWATCH CAMWATCH_LOG CAMWATCH_CAPTURE_LOG CAMWATCH_REBOOT_MARK CAMWATCH_STATE CAMWATCH_NOW CAMWATCH_UPTIME

section "guard: off unless NETWATCH=1 or CAMWATCH=1"
fresh_env; unset NETWATCH CAMWATCH
bash "$SRC/sunset-guard.sh"; rc=$?
check "exits 0 and does nothing" test "$rc" = 0 -a ! -s "$STUB_CALLS"

section "guard: units"
G="$SRC/systemd/sunset-guard.service"
check "service runs the script as root" grep -qx 'ExecStart=/home/pi/sunset/sunset-guard.sh' "$G"
check "service has no User= (needs root)" sh -c "! grep -q '^User=' '$G'"
check "service reads sunset.env" grep -qx 'EnvironmentFile=-/home/pi/sunset/sunset.env' "$G"
check "network log next to the frames" grep -qx 'Environment=NETWATCH_LOG=/home/pi/sunset/netwatch.log' "$G"
check "camera log next to the frames" grep -qx 'Environment=CAMWATCH_LOG=/home/pi/sunset/camwatch.log' "$G"
check "service reads the capture log" grep -qx 'Environment=CAMWATCH_CAPTURE_LOG=/home/pi/sunset/capture.log' "$G"
check "timer every 2 minutes" grep -qx 'OnUnitActiveSec=2min' "$SRC/systemd/sunset-guard.timer"
check "install.sh installs the units" grep -q 'sunset-guard.service sunset-guard.timer' "$SRC/install.sh"
check "install.sh enables the timer (the script does nothing without NETWATCH=1 or CAMWATCH=1)" grep -q 'enable --now sunset-guard.timer' "$SRC/install.sh"
check "the old watchdog units are gone" test ! -e "$SRC/systemd/sunset-netwatch.timer" -a ! -e "$SRC/systemd/sunset-camwatch.timer"
check "the CM4's reference env turns the camera check on" grep -qx 'CAMWATCH=1' "$SRC/hosts/cm4.env"
unset NETWATCH NETWATCH_STATE NETWATCH_LOG NETWATCH_SYSFS NETWATCH_REBOOT_MARK NETWATCH_SETTLE_S NETWATCH_WIRED STUB_PING STUB_PING_DOWN STUB_GATEWAY
unset CAMWATCH CAMWATCH_LOG CAMWATCH_CAPTURE_LOG CAMWATCH_REBOOT_MARK CAMWATCH_STATE CAMWATCH_NOW CAMWATCH_UPTIME CAMWATCH_FAILS CAMWATCH_WINDOW_MIN STUB_NTP
