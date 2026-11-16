# ---- Helpers for the Home Assistant scripts (cases 80 to 85 use them) ----
# Home Assistant runs these under BusyBox sh, so each one is checked under the machine's `sh` and,
# when there is one, under `busybox sh`: a native busybox, or the one in WSL on a Windows PC
# (the repo is then read through /mnt/c). With neither, only the plain sh runs and that is said once.
HA_VARS="FRAME_BASE FRAME_ROOT FRAME_AGE_NOW FUTURE_TOLERANCE_MIN DAILY_DIR RESULT_DIR FREE_PATH DF SUNSET_NOW TEMP_LIMIT_C OUTBOX_MAX DISK_MAX_PCT JPEG_MIN_BYTES MAX_AGE_DAYS"
HA_BB=""
if [ -n "${HA_NO_BUSYBOX:-}" ]; then   # HA_NO_BUSYBOX=1: skip the (slow, 0.3 s a call) WSL variant
  :
elif command -v busybox >/dev/null 2>&1 && busybox sh -c true >/dev/null 2>&1; then
  HA_BB=native
elif command -v wsl >/dev/null 2>&1 && command -v cygpath >/dev/null 2>&1 \
     && MSYS_NO_PATHCONV=1 wsl -e busybox sh -c true >/dev/null 2>&1 \
     && MSYS_NO_PATHCONV=1 wsl -e python3 -c 1 >/dev/null 2>&1; then
  HA_BB=wsl
fi
[ -n "$HA_BB" ] || echo "  note: no busybox here (native or in WSL, or HA_NO_BUSYBOX is set): Home Assistant scripts checked under plain sh only"
HA_SHELLS="sh${HA_BB:+ busybox}"

# Turn a Git Bash path into the one WSL sees. Only /tmp/... and /c/... paths are rewritten.
ha_wslword() {
  case "$1" in
    /tmp/*) cygpath -m "$1" | sed -E 's#^([A-Za-z]):#/mnt/\L\1#' ;;
    /[a-z]/*) printf '/mnt%s\n' "$1" ;;
    *) printf '%s\n' "$1" ;;
  esac
}
ha_wslvalue() { # every word of a value, so DF="sh /tmp/x/df" works too
  local out="" w
  set -f
  for w in $1; do out="$out $(ha_wslword "$w")"; done
  set +f
  printf '%s' "${out# }"
}
ha_busybox() { # ha_busybox <script> [args]: the HA_VARS that are set go through to the script
  if [ "$HA_BB" = native ]; then busybox sh "$@"; return; fi
  local envs=() args=() name arg
  for name in $HA_VARS; do
    [ -n "${!name+x}" ] && envs+=("$name=$(ha_wslvalue "${!name}")")
  done
  for arg in "$@"; do args+=("$(ha_wslvalue "$arg")"); done
  MSYS_NO_PATHCONV=1 wsl -e env ${envs[@]+"${envs[@]}"} busybox sh "${args[@]}"
}
ha_run() { # ha_run <sh|busybox> <script> [args]
  local which="$1"; shift
  if [ "$which" = busybox ]; then ha_busybox "$@"; else sh "$@"; fi
}
# ha_out <description> <expected output> <script> [args]: same output under every shell, exit 0
ha_out() {
  local d="$1" want="$2" shell got; shift 2
  for shell in $HA_SHELLS; do
    got="$(ha_run "$shell" "$@" 2>/dev/null)"
    if [ "$got" = "$want" ]; then ok; else bad "$d [$shell]: got '$got', wanted '$want'"; fi
  done
}
# ha_fails <description> <script> [args]: prints nothing and exits non-zero under every shell
ha_fails() {
  local d="$1" shell got rc; shift
  for shell in $HA_SHELLS; do
    got="$(ha_run "$shell" "$@" 2>/dev/null)"; rc=$?
    if [ "$rc" != 0 ] && [ -z "$got" ]; then ok; else bad "$d [$shell]: rc=$rc out='$got'"; fi
  done
}

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

section "frame age: another camera by name"
W="$(mktemp -d)"
NOW=$(date -u -d "2026-11-05 18:00:00" +%s)
mkdir -p "$W/cm4wide/2026/11/05"
: > "$W/cm4wide/2026/11/05/cm4wide_20261105T175000Z.jpg"
: > "$W/cm4wide/2026/11/05/wide_20261105T175900Z.jpg"
check "reads that camera's folder and names" \
  test "$(FRAME_BASE="$W" FRAME_AGE_NOW="$NOW" sh "$HA/sunset_frame_age.sh" cm4wide)" = 10
frame 2026/11/05 wide_20261105T173000Z.jpg
check "no name still means wide" \
  test "$(FRAME_BASE="$W" FRAME_AGE_NOW="$NOW" sh "$HA/sunset_frame_age.sh")" = 30
FRAME_BASE="$W" FRAME_AGE_NOW="$NOW" sh "$HA/sunset_frame_age.sh" 'wide/../x' >/dev/null 2>&1; rc=$?
check "a name with a path in it is refused" test "$rc" != 0

section "Home Assistant package: the CM4"
check "CM4 age sensor runs the script for cm4wide" grep -q 'sunset_frame_age.sh cm4wide' "$PKG"
check "CM4 stale sensor" grep -q 'unique_id: sunset_cm4_frames_stale' "$PKG"
check "CM4 alert watches it" grep -q 'entity_id: binary_sensor.sunset_cm4_frames_stale' "$PKG"
check "CM4 unknown age counts as stale" test "$(grep -c 'not is_number(age)' "$PKG")" = 2

section "frame age: a frame named in the future (issue #22)"
W="$(mktemp -d)"
NOW=$(date -u -d "2026-11-05 18:00:00" +%s)
export FRAME_BASE="$W" FRAME_AGE_NOW="$NOW"
frame 2026/11/05 wide_20261105T173000Z.jpg
ha_out "a normal frame reads its age" 30 "$HA/sunset_frame_age.sh"
frame 2026/11/05 wide_20261105T180800Z.jpg
ha_out "a few minutes of clock skew still reads 0" 0 "$HA/sunset_frame_age.sh"
frame 2026/11/05 wide_20261105T190000Z.jpg
ha_fails "an hour ahead is unknown, not age 0" "$HA/sunset_frame_age.sh"
export FUTURE_TOLERANCE_MIN=120
ha_out "the tolerance is a setting" 0 "$HA/sunset_frame_age.sh"
unset FUTURE_TOLERANCE_MIN
mkdir -p "$W/cm4wide/2026/11/05"
: > "$W/cm4wide/2026/11/05/cm4wide_20261105T175000Z.jpg"
ha_out "another camera by name" 10 "$HA/sunset_frame_age.sh" cm4wide
ha_fails "a bad camera name" "$HA/sunset_frame_age.sh" 'x/../y'
unset FRAME_BASE FRAME_AGE_NOW

section "frame age: the script files are LF and POSIX"
for f in "$HA"/*.sh; do
  check "$(basename "$f") has no CR" bash -c "! grep -q \$'\r' '$f'"
  check "$(basename "$f") is not bash-only" bash -c "! grep -Eq '\[\[|<<<|\bdeclare\b|\blocal\b|\\$\{[A-Za-z_]+//|\bsource\b' <(grep -v '^#' '$f')"
done
