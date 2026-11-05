frame_age() { FRAME_ROOT="$W/wide" FRAME_AGE_NOW="$NOW" sh "$HA/sunset_frame_age.sh"; }
frame() { mkdir -p "$W/wide/$1"; : > "$W/wide/$1/$2"; }
age_is() { [ "$(frame_age)" = "$1" ]; }

HA="$(dirname "$SRC")/homeassistant"
NOW=$(date -u -d "2026-11-05 18:00:00" +%s)

section "frame age: reads the newest frame's UTC name"
W="$(mktemp -d)"
frame 2026/11/05 wide_20261105T170000Z.jpg
frame 2026/11/05 wide_20261105T173000Z.jpg
check "minutes since the newest frame" age_is 30
frame 2026/11/05 wide_20261105T174500Z_night.jpg
check "a night frame counts" age_is 15

section "frame age: ignores what isn't a finished production frame"
W="$(mktemp -d)"
frame 2026/11/05 wide_20261105T173000Z.jpg
frame 2026/11/05 wide_20261105T175900Z.dng
frame 2026/11/05 wide_20261105T175900Z.json
frame 2026/11/05 .wide_20261105T175900Z.jpg.Ab12Cd
frame 2026/11/05 system.json
check "only finished JPEGs count" age_is 30

section "frame age: crosses UTC midnight"
W="$(mktemp -d)"
NOW=$(date -u -d "2026-11-06 00:10:00" +%s)
frame 2026/11/05 wide_20261105T234500Z.jpg
check "finds yesterday's folder when today has none" age_is 25
mkdir -p "$W/wide/2026/11/06"
check "an empty today folder does not hide yesterday" age_is 25

section "frame age: no answer means the alert should treat it as stale"
W="$(mktemp -d)"
NOW=$(date -u -d "2026-11-05 18:00:00" +%s)
frame_age >/dev/null 2>&1; rc=$?
check "share missing fails" test "$rc" != 0
check "share missing prints nothing" test -z "$(frame_age 2>/dev/null)"
frame 2026/11/02 wide_20261102T120000Z.jpg
frame_age >/dev/null 2>&1; rc=$?
check "frames older than two days fail" test "$rc" != 0

section "frame age: a frame named ahead of the clock is not a negative age"
W="$(mktemp -d)"
frame 2026/11/05 wide_20261105T180500Z.jpg
check "clamped to zero" age_is 0

section "Home Assistant package"
PKG="$HA/sunset.yaml"
check "package exists" test -f "$PKG"
check "runs the age script" grep -q 'sunset_frame_age.sh' "$PKG"
check "unknown age counts as stale" grep -q 'not is_number(age)' "$PKG"
check "alert watches the stale sensor" grep -q 'entity_id: binary_sensor.sunset_frames_stale' "$PKG"
check "threshold starts at an hour" grep -q 'initial: 60' "$PKG"
