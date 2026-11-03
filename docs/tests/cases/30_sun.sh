section "sun: written into each frame's JSON"
fresh_env; export SITE_LAT=49.25 SITE_LON=-122.98 STUB_LUX=1
capture
json="$(find "$OUT_ROOT" -name 'wide_*Z.json' ! -name '*_night*' | head -n1)"
night="$(find "$OUT_ROOT" -name '*_night.json' | head -n1)"
check "day json has Sun block" grep -q '"azimuth_deg"' "$json"
check "night json has Sun block" grep -q '"azimuth_deg"' "$night"
check "rpicam fields preserved" grep -q '"ExposureTime"' "$json"
check "json still valid" python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$json"
check "sun in ok line" grep -Eq 'sun=az=[0-9.]+,el=-?[0-9.]+ ok$' "$LOG_FILE"
check "no site coordinates in frame json" bash -c "! grep -q '49.25' '$json'"

section "sun: failure never costs the frame"
fresh_env; export SITE_LAT=banana SITE_LON=-122.98
capture; rc=$?
check "capture still succeeds" test "$rc" = 0
check "frame published" test "$(count 'wide_*Z.jpg')" = 1
check "sun=err logged" grep -q 'sun=err' "$LOG_FILE"

section "sun: no site configured"
fresh_env
capture; rc=$?
check "capture still succeeds" test "$rc" = 0
check "sun=nosite logged" grep -q 'sun=nosite' "$LOG_FILE"

section "sun module unit tests"
check "tests/test_sun.py" python3 -I "$HERE/test_sun.py"
