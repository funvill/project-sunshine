# needs: 66_guard 15_dense
# Issue #8: netwatch's reboot must not stop the capture until the network returns. Before it
# reboots with a trusted clock, netwatch leaves a "clock trusted at <epoch>" marker on the SD
# card; the first capture after the reboot accepts it once, if the time is at or just after it.
# The clock-ok flag lives on tmpfs in production; here "rebooting" is deleting it.
reboot_pi() { rm -f "$CLOCK_OK_FILE" "$NETWATCH_STATE"; }

section "netwatch reboot + capture clock gate"
net_env; export STUB_PING=fail; marker="$W/.clock-trusted"
capture
check "captures with NTP before the outage" test "$(count 'wide_*Z.jpg')" = 1
netwatch 4000; netwatch 5810
check "netwatch reboots" grep -q 'systemctl reboot' "$STUB_CALLS"
check "leaves the clock marker on the SD" test -s "$marker"
check "marker holds the epoch" bash -c "[[ \$(cat '$marker') =~ ^[0-9]+\$ ]]"
check "says so in its log" grep -q 'clock trusted at [0-9]*: kept for the capture after the reboot' "$NETWATCH_LOG"
# Frame names are to the second: wait one, or a fast machine names both frames alike.
reboot_pi; export STUB_NTP=no; sleep 1
capture; rc=$?
check "first capture after the reboot runs without NTP" test "$rc" = 0 -a "$(count 'wide_*Z.jpg')" = 2
check "logged" grep -q 'clock trusted without NTP: netwatch rebooted [0-9]* s ago' "$LOG_FILE"
check "marker consumed" test ! -e "$marker"
sleep 1; capture
check "later captures in the same boot keep going" test "$(count 'wide_*Z.jpg')" = 3
reboot_pi; sleep 1; capture; rc=$?
check "a later cold boot cannot reuse it" test "$rc" != 0 -a "$(count 'wide_*Z.jpg')" = 3
check "that boot is skipped as before" grep -q 'SKIPPED: clock not synced' "$LOG_FILE"

section "clock marker: no marker without a trusted clock"
net_env; export STUB_PING=fail STUB_NTP=no; marker="$W/.clock-trusted"
netwatch 4000; netwatch 5810
check "reboots anyway" grep -q 'systemctl reboot' "$STUB_CALLS"
check "but leaves no marker" test ! -e "$marker"

section "clock marker: too old, from the future, or garbage"
net_env; export STUB_NTP=no; marker="$W/.clock-trusted"
echo $(( $(date +%s) - 1000 )) > "$marker"
capture; rc=$?
check "older than 15 min is refused" test "$rc" != 0 -a -z "$(frames)"
check "and removed" test ! -e "$marker"
check "refusal logged" grep -q "WARN clock: ignored netwatch's reboot marker" "$LOG_FILE"
echo $(( $(date +%s) + 120 )) > "$marker"
capture; rc=$?
check "a clock behind the marker is refused" test "$rc" != 0 -a -z "$(frames)"
echo junk > "$marker"
capture; rc=$?
check "garbage is refused" test "$rc" != 0 -a -z "$(frames)" -a ! -e "$marker"
echo $(( $(date +%s) - 1000 )) > "$marker"; export CLOCK_TRUST_MAX_S=2000
capture; rc=$?
check "CLOCK_TRUST_MAX_S widens the bound" test "$rc" = 0
unset CLOCK_TRUST_MAX_S

section "clock marker: NTP sync clears a leftover marker"
net_env; marker="$W/.clock-trusted"; date +%s > "$marker"
capture
check "removed once NTP vouches for the clock" test ! -e "$marker"

section "clock marker: dense frames accept it too"
dense_env; export STUB_NTP=no; date +%s > "$W/.clock-trusted"
dense
check "dense frame taken" test "$(count 'wide_*Z.jpg')" = 1

section "netwatch: log rotates by size"
net_env; export STUB_PING=fail NETWATCH_LOG_MAX_BYTES=200
head -c 300 /dev/zero | tr '\0' x > "$NETWATCH_LOG"
netwatch 1000; netwatch 1610
check "old log moved to .1" test "$(wc -c < "$NETWATCH_LOG.1" | tr -d ' ')" = 300
check "new log has the event" grep -q 'reset the Wi-Fi dongle' "$NETWATCH_LOG"
unset NETWATCH_LOG_MAX_BYTES STUB_PING STUB_NTP NETWATCH NETWATCH_STATE NETWATCH_LOG NETWATCH_SYSFS NETWATCH_REBOOT_MARK NETWATCH_SETTLE_S
