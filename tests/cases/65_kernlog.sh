kernlog() { KERNEL_LOG="$W/kernel.log" KERNEL_LOG_MAX_BYTES="${1:-1048576}" bash "$SRC/sunset-kernlog.sh"; }

section "kernlog: keeps kernel messages on the SD"
fresh_env; export STUB_JOURNAL="$W/journal.txt"
printf 'Undervoltage detected!\nVoltage normalised\n' > "$STUB_JOURNAL"
kernlog; rc=$?
check "exits 0 when the source ends" test "$rc" = 0
check "first message kept" grep -q 'Undervoltage detected!' "$W/kernel.log"
check "last message kept" grep -q 'Voltage normalised' "$W/kernel.log"
check "marks where this boot starts" grep -q '=== log started' "$W/kernel.log"
# Root commits every 60 s, so without this the messages before a freeze never reach the card.
check "flushes every message to the card" test "$(grep -c "^sync $W/kernel.log" "$STUB_CALLS")" -ge 2

section "kernlog: follows only new kernel messages"
fresh_env; export STUB_JOURNAL="$W/journal.txt"; : > "$STUB_JOURNAL"
kernlog
check "kernel messages only" grep -q 'journalctl.* -k' "$STUB_CALLS"
check "follows" grep -q 'journalctl.* -f' "$STUB_CALLS"
check "no replay of old messages, which would rewrite them on every start" grep -q 'journalctl.* -n 0' "$STUB_CALLS"

section "kernlog: cannot grow without limit"
fresh_env; export STUB_JOURNAL="$W/journal.txt"
for i in $(seq 1 40); do echo "message number $i padded out to take up some room"; done > "$STUB_JOURNAL"
kernlog 500
check "older messages rotated" test -s "$W/kernel.log.1"
check "the newest message is in the live file" grep -q 'message number 40 ' "$W/kernel.log"
check "live file stays near the cap" test "$(wc -c < "$W/kernel.log")" -lt 600
check "only one old file is kept" test ! -e "$W/kernel.log.2"
unset STUB_JOURNAL

section "units: kernel log and watchdog are installed"
UNIT="$SRC/systemd/sunset-kernlog.service"
check "kernlog unit exists" test -f "$UNIT"
check "kernlog restarts if it dies" grep -q '^Restart=always' "$UNIT"
check "kernlog may read the journal" grep -q '^SupplementaryGroups=systemd-journal' "$UNIT"
check "kernlog starts at boot" grep -q '^WantedBy=multi-user.target' "$UNIT"
check "installer installs kernlog unit" grep -q 'sunset-kernlog.service' "$SRC/install.sh"
DOG="$SRC/systemd/sunset-watchdog.conf"
check "watchdog conf exists" test -f "$DOG"
check "watchdog under the BCM2835 limit of about 15 s" grep -q '^RuntimeWatchdogSec=15$' "$DOG"
check "installer installs watchdog conf" grep -q 'system.conf.d' "$SRC/install.sh"
