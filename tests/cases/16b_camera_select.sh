# needs: 15_dense
# CAMERA: which camera to use when the Pi has more than one. rpicam numbers cameras in the order
# they are found, which changed on the CM4 when CAM1 was enabled (2026-11-17), so CAMERA is matched
# against the camera's ID in `rpicam-still --list-cameras` (e.g. i2c@0), not a fixed number.
# A plain number is still taken as the index. If it matches no camera, or more than one, the frame
# is skipped: a gap is better than the other camera's picture in this series.

TWO_CAMS='0 : imx477 [4056x3040 12-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx477@1a)
1 : imx477 [4056x3040 12-bit RGGB] (/base/soc/i2c0mux/i2c@0/imx477@1a)'

shots() { grep -v -- '--list-cameras' "$STUB_CALLS"; }

section "camera: default is rpicam's own choice"
fresh_env; unset CAMERA; export STUB_LUX=1
capture
check "no --camera on any shot" bash -c "! grep -q -- '--camera' '$STUB_CALLS'"
day="$(find "$OUT_ROOT" -name 'wide_*Z.json' | head -n1)"
check "not recorded on the frame" python3 -c "import json,sys;assert 'camera' not in json.load(open(sys.argv[1]))['Capture']['settings']" "$day"

section "camera: chosen by its ID"
fresh_env; export CAMERA='i2c@0' STUB_CAMERA_LIST="$TWO_CAMS" STUB_LUX=1
capture; rc=$?
check "exits 0" test "$rc" = 0
check "day shot uses camera 1" bash -c "grep -v -- '--list-cameras' '$STUB_CALLS' | grep -v _night.jpg | grep -q -- '--camera 1'"
check "night shot uses camera 1" bash -c "grep -- '_night.jpg' '$STUB_CALLS' | grep -q -- '--camera 1'"
day="$(find "$OUT_ROOT" -name 'wide_*Z.json' | head -n1)"
check "ID recorded on the frame" python3 -c "import json,sys;assert json.load(open(sys.argv[1]))['Capture']['settings']['camera']=='i2c@0'" "$day"

section "camera: the other one"
fresh_env; export CAMERA='i2c@1' STUB_CAMERA_LIST="$TWO_CAMS" STUB_LUX=1
capture
check "uses camera 0" bash -c "grep -v -- '--list-cameras' '$STUB_CALLS' | grep -q -- '--camera 0'"

section "camera: by number"
fresh_env; export CAMERA=1 STUB_CAMERA_LIST="$TWO_CAMS" STUB_LUX=1
capture
check "uses camera 1" bash -c "grep -v -- '--list-cameras' '$STUB_CALLS' | grep -q -- '--camera 1'"

section "camera: on a dense frame"
dense_env; export CAMERA='i2c@0' STUB_CAMERA_LIST="$TWO_CAMS"
dense
check "dense shot uses camera 1" bash -c "grep -v -- '--list-cameras' '$STUB_CALLS' | grep -q -- '--camera 1'"

section "camera: not found skips the frame"
fresh_env; export CAMERA='i2c@7' STUB_CAMERA_LIST="$TWO_CAMS" STUB_LUX=1
capture; rc=$?
check "exits 1" test "$rc" = 1
check "no frame" test "$(count 'wide_*Z.jpg')" = 0
check "no shot taken" bash -c "! grep -v -- '--list-cameras' '$STUB_CALLS' | grep -q -- '-o '"
check "logged" grep -q 'SKIPPED: CAMERA=i2c@7' "$LOG_FILE"

section "camera: more than one match skips the frame"
fresh_env; export CAMERA='imx477' STUB_CAMERA_LIST="$TWO_CAMS" STUB_LUX=1
capture; rc=$?
check "exits 1" test "$rc" = 1
check "no frame" test "$(count 'wide_*Z.jpg')" = 0

# --env FILE: the units take both cameras, the second run loading sunset2.env over sunset.env
# (batch B, 2026-11-22; until then a second unit with its own EnvironmentFile= line).
section "second camera: --env loads its settings over the environment"
fresh_env; export STUB_CAMERA_LIST="$TWO_CAMS" STUB_LUX=1 NIGHT_GAIN=1 SETUP_ID=cm4-window-3
printf '%s\n' '# second camera' 'CAM_NAME=cm4city' '  CAMERA=i2c@1' 'NIGHT_GAIN="2"' "SETUP_NOTE='6 mm lens, CAM1'" 'ROTATION=0' > "$W/sunset2.env"
bash "$SRC/sunset-capture.sh" --env "$W/sunset2.env"; rc=$?
check "exits 0" test "$rc" = 0
check "frames under the second camera's name" test "$(count 'cm4city_*Z.jpg')" -ge 1 -a "$(count 'wide_*Z.jpg')" = 0
check "its camera" bash -c "grep -v -- '--list-cameras' '$STUB_CALLS' | grep -q -- '--camera 0'"
check "quoted values unquoted, as systemd does" bash -c "grep -- '_night.jpg' '$STUB_CALLS' | grep -q -- '--gain 2'"
check "logged as the second camera" grep -q ' cam=cm4city ' "$LOG_FILE"
j="$(find "$OUT_ROOT" -name 'cm4city_*Z.json' | head -n1)"
check "settings it doesn't set come from sunset.env" python3 -c "import json,sys;assert 'cm4-window-3' in open(sys.argv[1]).read()" "$j"

section "second camera: dense frames take --env too"
dense_env; export STUB_CAMERA_LIST="$TWO_CAMS"
printf 'CAM_NAME=cm4city\nCAMERA=i2c@1\n' > "$W/sunset2.env"
bash "$SRC/sunset-capture.sh" --dense --env "$W/sunset2.env"; rc=$?
check "exits 0" test "$rc" = 0
check "dense frame under the second camera's name" test "$(count 'cm4city_*Z.jpg')" = 1

section "second camera: none on this Pi"
fresh_env; export STUB_LUX=1
bash "$SRC/sunset-capture.sh" --env "$W/no-such.env"; rc=$?
check "no sunset2.env: exits 0" test "$rc" = 0
check "  takes nothing and logs nothing" test -z "$(frames 2>/dev/null)" -a ! -s "$LOG_FILE" -a ! -s "$STUB_CALLS"
: > "$W/empty.env"
bash "$SRC/sunset-capture.sh" --env "$W/empty.env"; rc=$?
check "an empty one is the same" test "$rc" = 0 -a -z "$(frames 2>/dev/null)"
bash "$SRC/sunset-capture.sh" --env 2>/dev/null; rc=$?
check "--env without a file exits 2" test "$rc" = 2
unset CAMERA STUB_CAMERA_LIST NIGHT_GAIN SETUP_ID SETUP_NOTE
