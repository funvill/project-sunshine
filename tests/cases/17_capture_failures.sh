# Capture failure handling (issues #15 and #14): a stuck camera is killed, aborts are logged,
# finished frames left in .partial are rescued, repeated failures escalate, a quick failure is
# retried once. CAPTURE_FAIL_REBOOT is off by default; the tests that turn it on rely on the
# systemctl and sudo stubs, so nothing here can reboot the machine.
fail_env() {
  fresh_env
  unset CAPTURE_KILL_S CAPTURE_RETRY_WAIT_S CAPTURE_RETRY_UNDER_S CAPTURE_FAIL_REBOOT
  unset CAPTURE_FAIL_REBOOT_N CAPTURE_FAIL_REBOOT_GAP_H
  unset STUB_DF LOCK_WAIT_S STUB_ORPHAN_S
  export CAPTURE_RETRY_WAIT_S=0
}

section "capture: a camera that ignores SIGTERM is killed"
fail_env; export STUB_RPICAM=hang_term CAPTURE_TIMEOUT_S=1 CAPTURE_KILL_S=1
start=$SECONDS; capture; rc=$?
check "exits non-zero" test "$rc" != 0
check "gives up within seconds, not when the child chooses" test $((SECONDS - start)) -lt 15
check "failure logged" grep -q 'FAILED capture rc=' "$LOG_FILE"
check "nothing published" test -z "$(frames)"

section "capture: a quick failure is retried once"
fail_env; export STUB_RPICAM=failonce
capture; rc=$?
check "exits 0" test "$rc" = 0
check "frame taken on the retry" test "$(count 'wide_*Z.jpg')" = 1
check "camera asked twice for the day shot" test "$(grep -c -- '-t 3000' "$STUB_CALLS")" = 2
check "retry logged" grep -q 'WARN capture failed after .* rc=1: retrying' "$LOG_FILE"
check "ok line" grep -q ' ok$' "$LOG_FILE"

section "capture: a failure that persists is retried only once"
fail_env; export STUB_RPICAM=fail
capture; rc=$?
check "exits non-zero" test "$rc" != 0
check "two attempts, no more" test "$(wc -l < "$STUB_CALLS" | tr -d ' ')" = 2
check "failure logged as before" grep -q 'FAILED capture rc=1 err=.*no cameras' "$LOG_FILE"

section "capture: a timeout is not retried"
fail_env; export STUB_RPICAM=hang CAPTURE_TIMEOUT_S=1
capture
check "one attempt" test "$(wc -l < "$STUB_CALLS" | tr -d ' ')" = 1

section "dense: no retry"
dense_env; export STUB_RPICAM=fail CAPTURE_RETRY_WAIT_S=0
dense
check "one attempt" test "$(wc -l < "$STUB_CALLS" | tr -d ' ')" = 1
unset CAPTURE_RETRY_WAIT_S

section "capture: missing JSON still finishes the run"
fail_env; export STUB_RPICAM=nojson STUB_LUX=1
capture; rc=$?
check "exits 0" test "$rc" = 0
check "jpg published" test "$(count 'wide_*Z.jpg')" = 1
check "ok line with unknown lux" grep -q 'lux=9999 .* ok$' "$LOG_FILE"
check "no abort" bash -c "! grep -q ABORTED '$LOG_FILE'"

section "capture: missing DNG is logged"
fail_env; export STUB_RPICAM=nodng
capture; rc=$?
check "exits 0 (the JPEG is still a frame)" test "$rc" = 0
check "warning logged" grep -q 'WARN no DNG from the camera (raw=1)' "$LOG_FILE"
check "ok line says raw=0" grep -q 'raw=0 .* ok$' "$LOG_FILE"
check "frame says raw=0" grep -rq '"raw": 0\|raw=0' "$OUT_ROOT"/wide
fail_env; export STUB_RPICAM=nodng SAVE_RAW=0
capture
check "no warning when DNG is off" bash -c "! grep -q 'no DNG' '$LOG_FILE'"

section "capture: healthy run logs no abort"
fail_env; export STUB_LUX=1
capture
check "no ABORTED line" bash -c "! grep -q ABORTED '$LOG_FILE'"
check "no WARN line" bash -c "! grep -q WARN '$LOG_FILE'"

section "capture: an unexpected failure is logged, not silent"
fail_env; mkdir -p "$OUT_ROOT"; : > "$OUT_ROOT/.partial"   # a file where the staging dir goes
capture; rc=$?
check "exits non-zero" test "$rc" != 0
check "abort logged with line and rc" grep -Eq 'ABORTED line [0-9]+ rc=[1-9]' "$LOG_FILE"

section "capture: publish failure keeps the frame for the next run"
fail_env; mkdir -p "$OUT_ROOT"; : > "$OUT_ROOT/wide"            # day dir cannot be made
capture; rc=$?
check "exits non-zero" test "$rc" != 0
check "publish failure logged" grep -q 'FAILED publish' "$LOG_FILE"
check "finished frame still in .partial" test -n "$(find "$OUT_ROOT/.partial" -name 'wide_*Z.jpg')"
rm -f "$OUT_ROOT/wide"; touch -d '5 minutes ago' "$OUT_ROOT/.partial"/wide_*
sleep 1; capture; rc=$?    # a new second, so the new frame doesn't share the rescued one's name
check "next run exits 0" test "$rc" = 0
check "rescue logged" grep -q 'rescued wide_.*Z from .partial' "$LOG_FILE"
check "both frames published" test "$(count 'wide_*Z.jpg')" = 2 -a "$(count 'wide_*Z.dng')" = 2
check ".partial empty" test -z "$(find "$OUT_ROOT/.partial" -type f ! -name .last-error)"

section "capture: incomplete leftovers are not rescued"
fail_env; mkdir -p "$OUT_ROOT/.partial"
printf x > "$OUT_ROOT/.partial/wide_20261101T000000Z.jpg"              # no JSON: incomplete
printf '{}' > "$OUT_ROOT/.partial/wide_20261101T000500Z.json"; : > "$OUT_ROOT/.partial/wide_20261101T000500Z.jpg"   # empty jpg
touch -d '2 hours ago' "$OUT_ROOT/.partial"/*
capture
check "only today's frame published" test "$(count 'wide_*Z.jpg')" = 1
check "old incomplete leftovers deleted" test -z "$(find "$OUT_ROOT/.partial" -name 'wide_20261101*')"
fail_env; mkdir -p "$OUT_ROOT/.partial"
printf x > "$OUT_ROOT/.partial/wide_20261101T001000Z.jpg"; printf '{}' > "$OUT_ROOT/.partial/wide_20261101T001000Z.json"
touch -d '2 hours ago' "$OUT_ROOT/.partial"/*
capture
check "an old complete set is rescued, not deleted" test -e "$OUT_ROOT/wide/2026/11/01/wide_20261101T001000Z.jpg"

section "capture: df gives nothing"
fail_env; export STUB_DF=empty
capture; rc=$?
check "still takes the frame" test "$rc" = 0 -a "$(count 'wide_*Z.jpg')" = 1
check "drops the DNG to be safe" test "$(count '*.dng')" = 0
check "warning logged" grep -q 'WARN disk usage unknown' "$LOG_FILE"
check "no abort" bash -c "! grep -q ABORTED '$LOG_FILE'"
unset STUB_DF

section "capture: repeated failures warn, reboot only when enabled"
fail_env; export STUB_RPICAM=fail CAPTURE_FAIL_REBOOT_N=3
capture; capture; capture
check "warns at the threshold" grep -q 'WARN 3 capture failures in a row' "$LOG_FILE"
check "no reboot by default" bash -c "! grep -q reboot '$STUB_CALLS'"
fail_env; export STUB_RPICAM=fail CAPTURE_FAIL_REBOOT=1 CAPTURE_FAIL_REBOOT_N=3
capture; capture
check "no reboot before the threshold" bash -c "! grep -q reboot '$STUB_CALLS'"
capture
check "reboots at the threshold" grep -q 'systemctl reboot' "$STUB_CALLS"
check "logs why" grep -q 'rebooting: 3 capture failures in a row' "$LOG_FILE"
check "remembers the reboot on the SD" test -e "$W/.capture-reboot"
: > "$STUB_CALLS"; rm -f "$W/sunset-capture-failures"
capture; capture; capture
check "no second reboot within 6 hours" bash -c "! grep -q 'systemctl reboot' '$STUB_CALLS'"
touch -d '7 hours ago' "$W/.capture-reboot"; capture
check "reboots again after 6 hours" grep -q 'systemctl reboot' "$STUB_CALLS"
fail_env; export STUB_RPICAM=fail CAPTURE_FAIL_REBOOT=1 CAPTURE_FAIL_REBOOT_N=3
capture; capture; export STUB_RPICAM=ok; capture; export STUB_RPICAM=fail; capture
check "a good frame resets the count" bash -c "! grep -q reboot '$STUB_CALLS'"
fail_env; export STUB_NTP=no CAPTURE_FAIL_REBOOT=1 CAPTURE_FAIL_REBOOT_N=2
capture; capture; capture
check "clock skips do not count (a reboot cannot fix them)" bash -c "! grep -q reboot '$STUB_CALLS'"

section "lock: children do not inherit it"
if command -v flock >/dev/null 2>&1; then
  fail_env; export STUB_RPICAM=orphan STUB_ORPHAN_S=6 LOCK_WAIT_S=1
  capture
  export STUB_RPICAM=ok; sleep 1; capture; rc=$?
  check "a leftover child does not hold the lock" test "$rc" = 0 -a "$(count 'wide_*Z.jpg')" = 2
  check "no busy skip" bash -c "! grep -q 'still running' '$LOG_FILE'"
  sleep 5
  fail_env; export CAPTURE_FAIL_REBOOT=1 CAPTURE_FAIL_REBOOT_N=2 LOCK_WAIT_S=1
  ( exec 8>"$LOCK_FILE"; flock 8; sleep 6 ) & holder=$!; sleep 0.5
  capture; capture
  check "a stuck lock counts as a failure" grep -q 'systemctl reboot' "$STUB_CALLS"
  wait "$holder"
else
  echo "  (flock not installed here: lock tests skipped)"
fi
unset CAPTURE_KILL_S CAPTURE_RETRY_WAIT_S CAPTURE_FAIL_REBOOT CAPTURE_FAIL_REBOOT_N LOCK_WAIT_S STUB_ORPHAN_S
