# Dense mode: 1-a-minute frames around sunrise and sunset, on top of the 15-minute slots.
# sun_wrap answers "dense" from STUB_DENSE (sunrise|sunset|none) and hands everything
# else to the real sunset-sun.py, so the tests don't depend on today's sun.
dense_env() {
  fresh_env
  export SITE_LAT=49.25 SITE_LON=-122.98 SLOT_EVERY_MIN=1000 STUB_DENSE=sunset
  local real; real="$(cygpath -m "$SRC/sunset-sun.py" 2>/dev/null || echo "$SRC/sunset-sun.py")"
  cat > "$W/sun_wrap.py" <<EOF
import os, subprocess, sys
if sys.argv[1:2] == ["dense"]:
    w = os.environ.get("STUB_DENSE", "none")
    print(w)
    sys.exit(0 if w != "none" else 1)
sys.exit(subprocess.call([sys.executable, "$real"] + sys.argv[1:]))
EOF
  export SUN_PY="$W/sun_wrap.py"
}
dense() { bash "$SRC/sunset-capture.sh" --dense; }

section "dense: inside a window"
dense_env; export STUB_LUX=1
dense; rc=$?
json="$(find "$OUT_ROOT" -name 'wide_*Z.json' | head -n1)"
check "exits 0" test "$rc" = 0
check "one jpg + json, same name and layout" test "$(count 'wide_*Z.jpg')" = 1 -a "$(count 'wide_*Z.json')" = 1
check "path matches wide/YYYY/MM/DD/wide_TS" bash -c "find '$OUT_ROOT' -path '*/wide/20??/??/??/wide_20??????T??????Z.jpg' | grep -q ."
check "no DNG" test "$(count '*.dng')" = 0
check "no night frame even when dark" test "$(count '*_night.*')" = 0
check "auto exposure: no fixed shutter or gain" bash -c "! grep -qE -- '--shutter|--gain|--awbgains' '$STUB_CALLS'"
check "same settle time as the regular frame" grep -q -- '-t 3000' "$STUB_CALLS"
check "marked dense in Capture" python3 -c "import json,sys;assert json.load(open(sys.argv[1]))['Capture']['schedule']=='dense'" "$json"
check "has the Sun block" grep -q '"azimuth_deg"' "$json"
check "logged as dense" grep -q ' dense window=sunset .* ok$' "$LOG_FILE"

section "dense: outside the windows"
dense_env; export STUB_DENSE=none
dense; rc=$?
check "exits 0" test "$rc" = 0
check "no frames" test -z "$(frames)"
check "camera not touched" test ! -s "$STUB_CALLS"
check "nothing logged" test ! -s "$LOG_FILE"

section "dense: the regular slot minute is left to the regular capture"
dense_env; export SLOT_EVERY_MIN=1
dense; rc=$?
check "exits 0" test "$rc" = 0
check "no frames" test -z "$(frames)"
check "camera not touched" test ! -s "$STUB_CALLS"

section "dense: no site means no windows"
dense_env; unset SITE_LAT SITE_LON
dense; rc=$?
check "exits 0" test "$rc" = 0
check "no frames" test -z "$(frames)"

section "dense: clock not synced"
dense_env; export STUB_NTP=no
dense; rc=$?
check "exits 0 quietly" test "$rc" = 0 -a ! -s "$LOG_FILE"
check "no frames" test -z "$(frames)"

section "dense: shorter camera timeout"
dense_env; export STUB_RPICAM=hang DENSE_TIMEOUT_S=1
start=$SECONDS; dense; rc=$?
check "gives up on a hung camera" test "$rc" != 0 -a $((SECONDS - start)) -lt 10
check "failure logged as dense" grep -q 'dense window=sunset FAILED capture rc=124' "$LOG_FILE"

section "regular frames are marked regular"
fresh_env; capture
json="$(find "$OUT_ROOT" -name 'wide_*Z.json' | head -n1)"
check "Capture.schedule is regular" python3 -c "import json,sys;assert json.load(open(sys.argv[1]))['Capture']['schedule']=='regular'" "$json"

section "lock: the regular slot wins"
if command -v flock >/dev/null 2>&1; then
  dense_env
  ( exec 8>"$LOCK_FILE"; flock 8; sleep 3 ) & holder=$!; sleep 0.5
  dense
  check "dense skips while the camera is busy" test -z "$(frames)"
  capture; rc=$?
  check "regular waits for the lock, then captures" test "$rc" = 0 -a "$(count 'wide_*Z.jpg')" = 1
  wait "$holder"
else
  echo "  (flock not installed here: lock tests skipped)"
fi
