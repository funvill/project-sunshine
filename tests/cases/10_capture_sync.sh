section "capture: normal frame"
fresh_env
capture; rc=$?
check "exits 0" test "$rc" = 0
check "jpg+dng+json in UTC day dir" test "$(count 'wide_*Z.*')" = 3
check "path matches wide/YYYY/MM/DD/wide_TS" bash -c "find '$OUT_ROOT' -path '*/wide/20??/??/??/wide_20??????T??????Z.jpg' | grep -q ."
check "no night frame in daylight" test "$(count '*_night.*')" = 0
check "nothing left in .partial" test -z "$(find "$OUT_ROOT/.partial" -type f ! -name .last-error)"
check "log has ok line" grep -q ' ok$' "$LOG_FILE"

section "capture: dark scene adds night frame"
fresh_env; export STUB_LUX=1
capture
check "night jpg+dng+json" test "$(count '*_night.*')" = 3
check "night=1 logged" grep -q 'night=1' "$LOG_FILE"

section "capture: camera missing"
fresh_env; export STUB_RPICAM=fail
capture; rc=$?
check "exits non-zero" test "$rc" != 0
check "failure logged with reason" grep -q 'FAILED capture.*no cameras' "$LOG_FILE"
check "no frames published" test -z "$(frames)"

section "capture: hung camera is bounded"
fresh_env; export STUB_RPICAM=hang CAPTURE_TIMEOUT_S=1
capture; rc=$?
check "exits non-zero" test "$rc" != 0
check "timeout rc=124 logged" grep -q 'FAILED capture rc=124' "$LOG_FILE"

section "capture: clock not synced"
fresh_env; export STUB_NTP=no
capture; rc=$?
check "refuses to capture" test "$rc" != 0
check "skip logged" grep -q 'SKIPPED: clock not synced' "$LOG_FILE"
check "no frames" test -z "$(frames)"
export STUB_NTP=yes; capture
check "captures once synced" test "$(count '*.jpg')" = 1
export STUB_NTP=no; sleep 1; capture
check "later NTP outage does not stop capture (sentinel)" test "$(count '*.jpg')" = 2
fresh_env; export STUB_NTP=no REQUIRE_TIME_SYNC=0
capture
check "REQUIRE_TIME_SYNC=0 overrides" test "$(count '*.jpg')" = 1

section "sync: moves old files, keeps young and partial ones"
fresh_env; capture
old="$(frames | head -n1)"; touch -d '10 minutes ago' $(frames)
mkdir -p "$OUT_ROOT/.partial"; echo x > "$OUT_ROOT/.partial/half.jpg"; touch -d '10 minutes ago' "$OUT_ROOT/.partial/half.jpg"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "frames arrived on NAS" test "$(find "$W/nas" -type f | wc -l | tr -d ' ')" = 4
check "daily system.json arrived too" test -n "$(find "$W/nas" -name system.json)"
check "local copies removed" test -z "$(frames)"
check ".partial untouched" test -e "$OUT_ROOT/.partial/half.jpg"
check "sync ok logged" grep -q 'sync ok files=4' "$SYNC_LOG_FILE"
fresh_env; capture; sync_
check "files under 2 min old are not synced" test "$(count '*.jpg')" = 1

section "sync: NAS down keeps everything"
fresh_env; capture; touch -d '10 minutes ago' $(frames)
export STUB_RSYNC=fail; sync_; rc=$?
check "exits non-zero" test "$rc" != 0
check "frames still local" test "$(count '*')" = 4
check "failure logged" grep -q 'sync FAILED' "$SYNC_LOG_FILE"
export STUB_RSYNC=ok; sync_
check "catches up when NAS returns" test "$(find "$W/nas" -type f | wc -l | tr -d ' ')" = 4

section "sync: first boot, no outbox yet"
fresh_env
sync_; rc=$?
check "exits 0" test "$rc" = 0

section "capture: night frame settings"
fresh_env; export STUB_LUX=1
capture
night_call="$(grep -- '_night.jpg' "$STUB_CALLS")"
check "default night shutter is 4 s" grep -q -- '--shutter 4000000' <<<"$night_call"
check "default night gain is 1" grep -q -- '--gain 1 ' <<<"$night_call"
check "default colour gains are the measured ones" grep -q -- '--awbgains 2.07,2.28' <<<"$night_call"
fresh_env; export STUB_LUX=1 NIGHT_AWB=2.5,2.0
capture
check "NIGHT_AWB overrides the colour gains" grep -q -- '--awbgains 2.5,2.0' "$STUB_CALLS"
check "the colour gains used are recorded on the frame" grep -rq 'awbgains=2.5,2.0\|"awbgains": "2.5,2.0"' "$OUT_ROOT"
unset NIGHT_AWB
