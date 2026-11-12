# ROTATION: a camera mounted upside down. rpicam's --rotation 180 flips the sensor readout,
# so the JPEG and the DNG both come out upright. Only 0 and 180 are possible.

section "rotation: default is none"
fresh_env; unset ROTATION; export STUB_LUX=1
capture
check "no --rotation on any shot" bash -c "! grep -q -- '--rotation' '$STUB_CALLS'"
check "not recorded on the frame" bash -c "! grep -rq '\"rotation\"' '$OUT_ROOT'"

section "rotation: 180"
fresh_env; export ROTATION=180 STUB_LUX=1
capture; rc=$?
check "exits 0" test "$rc" = 0
check "day shot rotated" bash -c "grep -v -- '_night.jpg' '$STUB_CALLS' | grep -q -- '--rotation 180'"
check "night shot rotated" bash -c "grep -- '_night.jpg' '$STUB_CALLS' | grep -q -- '--rotation 180'"
day="$(find "$OUT_ROOT" -name 'wide_*Z.json' | head -n1)"
check "recorded on the frame" python3 -c "import json,sys;assert json.load(open(sys.argv[1]))['Capture']['settings']['rotation']==180" "$day"

section "rotation: 180 on a dense frame"
dense_env; export ROTATION=180
dense
check "dense shot rotated" grep -q -- '--rotation 180' "$STUB_CALLS"

section "rotation: a bad value still takes the frame"
fresh_env; export ROTATION=90
capture; rc=$?
check "exits 0" test "$rc" = 0
check "frame taken" test "$(count 'wide_*Z.jpg')" = 1
check "no --rotation passed" bash -c "! grep -q -- '--rotation' '$STUB_CALLS'"
check "warning logged" grep -q 'WARN ROTATION=90' "$LOG_FILE"
unset ROTATION
