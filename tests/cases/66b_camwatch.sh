# sunset-camwatch.sh: reboots when a camera keeps failing (both CM4 cameras, 14:05 UTC 2026-11-19
# to the reboot at 06:37 UTC 2026-11-20; a reboot cleared it). Times are fixed with CAMWATCH_NOW
# (epoch) and CAMWATCH_UPTIME (s), so the log lines below are relative to NOW.
NOW=1795165200   # 2026-11-20T07:00:00Z
cam_env() {
  fresh_env
  export CAMWATCH=1 CAMWATCH_LOG="$W/camwatch.log" CAMWATCH_CAPTURE_LOG="$W/capture.log"
  export CAMWATCH_REBOOT_MARK="$W/.camwatch-reboot" CAMWATCH_NOW=$NOW CAMWATCH_UPTIME=86400
  export CAMWATCH_STATE="$W/run"
  unset CAMWATCH_FAILS CAMWATCH_WINDOW_MIN CAMWATCH_REBOOT_GAP_H
  : > "$W/capture.log"
}
camwatch() { bash "$SRC/sunset-camwatch.sh"; }
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

section "camwatch: units"
check "service runs the script as root" grep -qx 'ExecStart=/home/pi/sunset/sunset-camwatch.sh' "$SRC/systemd/sunset-camwatch.service"
check "service has no User= (needs root)" sh -c "! grep -q '^User=' '$SRC/systemd/sunset-camwatch.service'"
check "service reads sunset.env" grep -qx 'EnvironmentFile=-/home/pi/sunset/sunset.env' "$SRC/systemd/sunset-camwatch.service"
check "service logs next to the frames" grep -qx 'Environment=CAMWATCH_LOG=/home/pi/sunset/camwatch.log' "$SRC/systemd/sunset-camwatch.service"
check "service reads the capture log" grep -qx 'Environment=CAMWATCH_CAPTURE_LOG=/home/pi/sunset/capture.log' "$SRC/systemd/sunset-camwatch.service"
check "timer every 5 minutes" grep -qx 'OnUnitActiveSec=5min' "$SRC/systemd/sunset-camwatch.timer"
check "install.sh installs the units" grep -q 'sunset-camwatch.service sunset-camwatch.timer' "$SRC/install.sh"
check "install.sh enables the timer (the script does nothing without CAMWATCH=1)" grep -q 'enable --now sunset-camwatch.timer' "$SRC/install.sh"
check "the CM4's reference env turns it on" grep -qx 'CAMWATCH=1' "$SRC/hosts/cm4.env"
unset CAMWATCH CAMWATCH_LOG CAMWATCH_CAPTURE_LOG CAMWATCH_REBOOT_MARK CAMWATCH_STATE CAMWATCH_NOW CAMWATCH_UPTIME CAMWATCH_FAILS CAMWATCH_WINDOW_MIN STUB_NTP
