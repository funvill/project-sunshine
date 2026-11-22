# Production sunset bracket (#10, option E): with BRACKET=1, every frame within BRACKET_WINDOW_MIN
# of sunset is followed by an ev+0 and an ev-2 shot, daylight white balance until
# BRACKET_AWB_HANDOVER_MIN after sunset. JPEG and JSON only, like every frame.
# The sun wrapper answers "dense" from STUB_DENSE and "annotate" with STUB_MINUTES from sunset,
# so the tests don't depend on today's sun.
bracket_env() {
  fresh_env
  export SITE_LAT=49.25 SITE_LON=-122.98 SLOT_EVERY_MIN=1000 STUB_DENSE=sunset STUB_MINUTES=-20 BRACKET=1
  cat > "$W/sun_wrap.py" <<'PY'
import json, os, sys
cmd = sys.argv[1:2]
if cmd == ["dense"]:
    w = os.environ.get("STUB_DENSE", "none"); print(w); sys.exit(0 if w != "none" else 1)
if cmd == ["annotate"]:
    path = sys.argv[2]
    try:
        data = json.load(open(path))
    except (OSError, ValueError):
        data = {}
    data["Sun"] = {"azimuth_deg": 240.0, "elevation_deg": 1.0, "minutes_from_sunset": float(os.environ["STUB_MINUTES"])}
    json.dump(data, open(path, "w"))
    print("az=240.0 el=1.0"); sys.exit(0)
sys.exit(2)
PY
  export SUN_PY="$W/sun_wrap.py"
}
dense() { bash "$SRC/sunset-capture.sh" --dense; }
jget() { python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(eval(sys.argv[2]))" "$1" "$2"; }
one() { find "$OUT_ROOT" -name "$1" | head -n1; }
shots() { grep -v -- '^--version' "$STUB_CALLS"; }   # camera shots, not sunset-meta.py's version probe
nshots() { shots | wc -l | tr -d ' '; }
call() { shots | sed -n "${1}p"; }
has_call() { call "$1" | grep -q -- "$2"; }   # has_call <n> <text>: the nth camera call has text

section "bracket: off unless BRACKET=1"
bracket_env; unset BRACKET
dense
check "only the dense frame" test "$(count '*.jpg')" = 1
check "one camera call" test "$(nshots)" = 1

section "bracket: a dense frame 20 min before sunset gets the pair"
bracket_env
dense; rc=$?
frame="$(one 'wide_*Z.jpg')"; stem="$(basename "$frame" .jpg)"
check "exits 0" test "$rc" = 0
check "frame plus ev0 and ev-2" test "$(count 'wide_*Z.jpg')" = 1 -a "$(count 'wide_*Z_ev0.jpg')" = 1 -a "$(count 'wide_*Z_ev-2.jpg')" = 1
check "each has a JSON" test "$(count 'wide_*Z_ev0.json')" = 1 -a "$(count 'wide_*Z_ev-2.json')" = 1
check "same name and folder as the frame" test -e "$(dirname "$frame")/${stem}_ev-2.jpg"
check "three camera calls" test "$(nshots)" = 3
check "ev+0: 1 s settle" has_call 2 '-t 1000'
check "ev+0: --ev 0" has_call 2 '--ev 0'
check "ev+0: daylight white balance" has_call 2 '--awb daylight'
check "ev-2: --ev -2" has_call 3 '--ev -2'
check "ev-2: daylight white balance" has_call 3 '--awb daylight'
check "no DNG anywhere" test "$(count '*.dng')" = 0
check "--raw never passed" bash -c "! grep -q -- '--raw' '$STUB_CALLS'"
j="$(one '*_ev-2.json')"
check "Capture.kind is bracket" test "$(jget "$j" "d['Capture']['kind']")" = bracket
check "settings: ev -2, daylight, no raw" test "$(jget "$j" "(d['Capture']['settings']['ev'], d['Capture']['settings']['awb'], 'raw' in d['Capture']['settings'])")" = "(-2, 'daylight', False)"
check "bracket_of names the frame" test "$(jget "$j" "d['Capture']['settings']['bracket_of']")" = "$stem"
check "schedule stays dense" test "$(jget "$j" "d['Capture']['schedule']")" = dense
check "has the Sun block" test "$(jget "$j" "d['Sun']['minutes_from_sunset']")" = -20.0
check "checksum of the JPEG, nothing else in files" test "$(jget "$j" "(sorted(d['Capture']['files']), 'sha256' in d['Capture']['files']['jpg'])")" = "(['jpg'], True)"
check "logged with bracket=2" grep -q 'dense window=sunset .*bracket=2.* ok$' "$LOG_FILE"

section "bracket: auto white balance after the hand-over"
bracket_env; export STUB_MINUTES=15
dense
check "pair taken" test "$(count '*_ev-2.jpg')" = 1
check "no daylight white balance" bash -c "! grep -q -- '--awb daylight' '$STUB_CALLS'"
check "awb recorded as auto" test "$(jget "$(one '*_ev0.json')" "d['Capture']['settings']['awb']")" = auto

section "bracket: the pair 40 min before sunset"
bracket_env; export STUB_MINUTES=-40
dense
check "pair taken" test "$(count '*_ev-2.jpg')" = 1

section "bracket: nothing outside BRACKET_WINDOW_MIN"
bracket_env; export STUB_MINUTES=-50
dense
check "only the dense frame" test "$(count '*.jpg')" = 1

section "bracket: the regular frame in the window gets the pair too"
bracket_env; export STUB_LUX=1000
capture; rc=$?
check "exits 0" test "$rc" = 0
check "frame and the pair" test "$(count 'wide_*Z.jpg')" = 1 -a "$(count '*_ev0.jpg')" = 1 -a "$(count '*_ev-2.jpg')" = 1
check "schedule regular on the pair" test "$(jget "$(one '*_ev0.json')" "d['Capture']['schedule']")" = regular

section "bracket: after the night frame when dark"
bracket_env; export STUB_LUX=1 STUB_MINUTES=30
capture
check "night frame and pair" test "$(count '*_night.jpg')" = 1 -a "$(count '*_ev-2.jpg')" = 1
check "night frame second" has_call 2 '--shutter'
check "pair after it" has_call 3 '--ev 0'

section "bracket: a failed pair shot never costs the frame"
bracket_env; export STUB_RPICAM=failev
dense; rc=$?
check "exits 0" test "$rc" = 0
check "frame kept" test "$(count 'wide_*Z.jpg')" = 1
check "no pair files left" test "$(count '*_ev*')" = 0
check "warning logged" grep -q 'WARN bracket ev0 failed' "$LOG_FILE"
check "frame line still ok, bracket=0" grep -q 'bracket=0.* ok$' "$LOG_FILE"

section "bracket: rescue picks up a pair left in .partial"
bracket_env
mkdir -p "$OUT_ROOT/.partial"
for f in jpg json; do printf x > "$OUT_ROOT/.partial/wide_20261116T001500Z_ev-2.$f"; done
touch -d '5 minutes ago' "$OUT_ROOT/.partial/"wide_20261116T001500Z_ev-2.*
export STUB_MINUTES=-200; capture
check "rescued into its day folder" test -e "$OUT_ROOT/wide/2026/11/16/wide_20261116T001500Z_ev-2.jpg"

section "PROFILE_ID goes into Capture"
fresh_env; export PROFILE_ID=sunset-e-1
capture
check "profile_id" test "$(jget "$(one 'wide_*Z.json')" "d['Capture']['profile_id']")" = sunset-e-1
