# capture.log rotates by size, like kernel.log (issue #27): logrotate is masked on the Pis.
section "capture: log rotates by size"
fresh_env; export CAPTURE_LOG_MAX_BYTES=200
head -c 300 /dev/zero | tr '\0' x > "$LOG_FILE"
capture
check "old log moved to .1" test "$(wc -c < "$LOG_FILE.1" | tr -d ' ')" = 300
check "new log has the ok line" grep -q ' ok$' "$LOG_FILE"
check "new log is small" test "$(wc -c < "$LOG_FILE" | tr -d ' ')" -lt 300
fresh_env; capture; capture
check "no rotation below the limit" test ! -e "$LOG_FILE.1" -a "$(grep -c ' ok$' "$LOG_FILE")" = 2
unset CAPTURE_LOG_MAX_BYTES
