section "disk guard: below 85% keeps DNG"
fresh_env; export STUB_DF_PCT=84
capture
check "dng saved" test "$(count '*.dng')" = 1
check "raw=1 logged" grep -q 'raw=1' "$LOG_FILE"

section "disk guard: 85% drops DNG, keeps jpg+json"
fresh_env; export STUB_DF_PCT=85
capture; rc=$?
check "still succeeds" test "$rc" = 0
check "no dng" test "$(count '*.dng')" = 0
check "jpg+json kept" test "$(count 'wide_*Z.jpg')$(count 'wide_*Z.json')" = 11
check "no --raw passed to camera" bash -c "! grep -q -- '--raw' '$STUB_CALLS'"
check "drop logged" grep -q 'DISK 85% >= 85%: dropping DNG' "$LOG_FILE"
check "raw=0 in ok line" grep -q 'raw=0' "$LOG_FILE"

section "disk guard: SAVE_RAW=0 is not reported as a drop"
fresh_env; export STUB_DF_PCT=90 SAVE_RAW=0
capture
check "no drop message" bash -c "! grep -q dropping '$LOG_FILE'"

section "disk guard: 95% skips night frame only"
fresh_env; export STUB_DF_PCT=95 STUB_LUX=1
capture; rc=$?
check "succeeds" test "$rc" = 0
check "day frame kept" test "$(count 'wide_*Z.jpg')" = 1
check "night frame skipped" test "$(count '*_night.*')" = 0
check "skip logged" grep -q 'DISK 95% >= 95%: skipping night frame' "$LOG_FILE"

section "disk guard: 90% night frame without DNG"
fresh_env; export STUB_DF_PCT=90 STUB_LUX=1
capture
check "night jpg present" test "$(count '*_night.jpg')" = 1
check "night dng absent" test "$(count '*_night.dng')" = 0

section "disk guard: nearly full skips everything"
fresh_env; export STUB_DF_PCT=99 STUB_DF_FREE_MB=50
capture; rc=$?
check "exits non-zero" test "$rc" != 0
check "nothing captured" test -z "$(frames)"
check "logged" grep -q 'SKIPPED: disk full' "$LOG_FILE"
