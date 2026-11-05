section "meta: written into each frame's JSON"
fresh_env; export SITE_LAT=49.25 SITE_LON=-122.98 STUB_LUX=1 SETUP_ID=pilot-1 SETUP_NOTE="test rig"
capture
json="$(find "$OUT_ROOT" -name 'wide_*Z.json' ! -name '*_night*' | head -n1)"
night="$(find "$OUT_ROOT" -name '*_night.json' | head -n1)"
field() { python3 -I -c "import json,sys;d=json.load(open(sys.argv[1]));print(eval(sys.argv[2],{'d':d}))" "$1" "$2"; }
check "day json has Capture and System" test "$(field "$json" "'Capture' in d and 'System' in d")" = True
check "night json has Capture and System" test "$(field "$night" "'Capture' in d and 'System' in d")" = True
check "camera fields kept" test "$(field "$json" "d['ExposureTime']")" = 1000
check "sun block kept" test "$(field "$json" "'azimuth_deg' in d['Sun']")" = True
check "day kind" test "$(field "$json" "d['Capture']['kind']")" = auto
check "night kind" test "$(field "$night" "d['Capture']['kind']")" = night
check "night records its settings" test "$(field "$night" "d['Capture']['settings']['shutter_us']")" = 8000000
check "night records the lux that triggered it" test "$(field "$night" "d['Capture']['decision_lux']")" = 1
check "image checksums" grep -Eq '"sha256": "[0-9a-f]{64}"' "$json"
check "dng recorded" test "$(field "$json" "d['Capture']['files']['dng']['bytes']")" = 7
check "setup id" test "$(field "$json" "d['Capture']['setup_id']")" = pilot-1
check "no site coordinates" bash -c "! grep -q '49.25' '$json'"
daily="$(dirname "$json")/system.json"
check "daily system.json next to the frames" test -s "$daily"
check "one record for both frames" test "$(grep -c '"system_id"' "$daily")" = 1
check "frame points at the daily record" test "$(field "$json" "d['Capture']['system_id']")" = "$(field "$daily" "d['records'][0]['system_id']")"
check "night frame points at it too" test "$(field "$night" "d['Capture']['system_id']")" = "$(field "$daily" "d['records'][0]['system_id']")"
check "setup note is in the daily file" test "$(field "$daily" "d['records'][0]['setup_note']")" = "test rig"
check "setup note is not on the frame" test "$(field "$json" "'setup_note' in d['Capture']")" = False
check "no coordinates in the daily file" bash -c "! grep -q '49.25' '$daily'"
check "meta=ok logged" grep -q ' meta=ok ' "$LOG_FILE"
check "log line still ends in ok" grep -Eq 'sun=az=[0-9.]+,el=-?[0-9.]+ ok$' "$LOG_FILE"
check "no temp files published" test -z "$(find "$OUT_ROOT" -name '*tmp*' -not -path '*/.partial/*')"
unset SETUP_ID SETUP_NOTE

section "meta: failure never costs the frame"
fresh_env; export META_PY="$W/does-not-exist.py"
capture; rc=$?
check "capture still succeeds" test "$rc" = 0
check "frame published" test "$(count 'wide_*Z.jpg')" = 1
check "json still valid" python3 -I -c "import json,sys;json.load(open(sys.argv[1]))" "$(find "$OUT_ROOT" -name 'wide_*Z.json' | head -n1)"
check "meta=err logged" grep -q ' meta=err ' "$LOG_FILE"
unset META_PY

section "meta: checksums can be turned off"
fresh_env; export FRAME_CHECKSUMS=0
capture
json="$(find "$OUT_ROOT" -name 'wide_*Z.json' | head -n1)"
check "no checksum" test "$(field "$json" "'sha256' in d['Capture']['files']['jpg']")" = False
unset FRAME_CHECKSUMS

section "meta module unit tests"
check "tests/test_meta.py" python3 -I "$HERE/test_meta.py"
