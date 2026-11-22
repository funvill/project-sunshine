#!/usr/bin/env bash
# Offline tests for the capture/sync scripts, using stub rpicam-still/rsync/df/etc.
# Runs anywhere with bash + coreutils + python3 (no Pi needed):  bash tests/run.sh
# Give names to run only some: each is a substring or glob of a file name in cases/ or of a
# tests/test_*.py, e.g.  bash tests/run.sh 17_ dense test_ups
set -u
FILTERS=("$@"); set --   # the cases are sourced, so clear the arguments they would see
selected() { # selected <file name>: true with no filters, or when one matches
  (( ${#FILTERS[@]} == 0 )) && return 0
  local f
  for f in "${FILTERS[@]}"; do [[ "$1" == $f || "$1" == *"$f"* ]] && return 0; done
  return 1
}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SRC:-$(dirname "$HERE")/pi}"
HA="$(dirname "$SRC")/homeassistant"   # the Home Assistant files (cases 80-85)
export PATH="$HERE/stubs:$PATH"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL: $*"; }
check() { # check <description> <command...>
  local d="$1"; shift
  if "$@" >/dev/null 2>&1; then ok; else bad "$d"; fi
}
section() { echo "== $*"; }

# fresh_env: new sandbox; sets W (work dir) and the env the scripts read.
fresh_env() {
  W="$(mktemp -d)"
  export OUT_ROOT="$W/outbox" LOG_FILE="$W/capture.log" LOCK_FILE="$W/.cap.lock"
  export SYNC_LOG_FILE="$W/sync.log" SYNC_LOCK_FILE="$W/.sync.lock"
  export CLOCK_OK_FILE="$W/clock-ok" STUB_NAS_DIR="$W/nas" CAM_NAME=wide
  export STUB_CALLS="$W/calls.txt"
  # The sync backs up /etc/fstab and the boot config: point it at an empty folder, never this machine's.
  export SYNC_CONFIG_ROOT="$W/sysroot"; mkdir -p "$W/sysroot"
  unset STUB_SAME_FS STUB_RPICAM STUB_LUX STUB_NTP STUB_DF_PCT STUB_DF_FREE_MB STUB_RSYNC
  unset SITE_LAT SITE_LON NAS_TARGET NIGHT_LUX CAPTURE_TIMEOUT_S REQUIRE_TIME_SYNC
  unset SUN_PY SLOT_EVERY_MIN STUB_DENSE STUB_UTC_MINUTE DENSE_TIMEOUT_S ROTATION CAMERA STUB_CAMERA_LIST
  unset BRACKET BRACKET_WINDOW_MIN BRACKET_AWB_HANDOVER_MIN STUB_MINUTES PROFILE_ID
  mkdir -p "$W/nas"
}
capture() { bash "$SRC/sunset-capture.sh"; }
sync_()   { bash "$SRC/sunset-sync.sh"; }
frames()  { find "$OUT_ROOT" -type f -not -path '*/.partial/*' | sort; }
count()   { find "$OUT_ROOT" -type f -not -path '*/.partial/*' -name "$1" | wc -l | tr -d ' '; }

# A case that uses another's helpers names it on a "# needs: <case>" line; picked by name, it
# brings those cases with it.
NEEDED=" "
for t in "$HERE"/cases/*.sh; do
  [[ -e "$t" ]] && selected "$(basename "$t")" || continue
  for n in $(sed -n 's/^# needs: *//p' "$t"); do NEEDED+="$n.sh "; done
done
for t in "$HERE"/cases/*.sh; do
  [[ -e "$t" ]] || continue
  selected "$(basename "$t")" || [[ "$NEEDED" == *" $(basename "$t") "* ]] || continue
  # shellcheck disable=SC1090
  source "$t"
done

# Every tests/test_*.py that no case already runs (a case runs one by naming "$HERE/test_x.py").
# A test that needs OpenCV or numpy is skipped with a message when they are missing; ffmpeg-only
# parts skip themselves inside the test file.
section "python tests"
have_py_mods() { python3 -I -c "import $1" >/dev/null 2>&1; }
command -v ffmpeg >/dev/null 2>&1 || echo "  note: ffmpeg not found; encoding tests inside the Python files will skip themselves"
for t in "$HERE"/test_*.py; do
  [[ -e "$t" ]] || continue
  name="$(basename "$t")"
  selected "$name" || continue
  # In a full run, a test that a case already runs is not run twice. Picked by name, it runs here.
  if (( ${#FILTERS[@]} == 0 )) && grep -qs "HERE/$name" "$HERE"/cases/*.sh; then continue; fi
  case "$name" in
    test_fuse_sunset.py|test_issue_blur.py|test_fog_scan.py)
      if ! have_py_mods cv2 || ! have_py_mods numpy; then
        echo "  SKIP: tests/$name (needs OpenCV and numpy: pip install numpy opencv-python-headless)"
        continue
      fi ;;
  esac
  check "tests/$name" python3 -I "$t"
done

echo
echo "passed=$PASS failed=$FAIL"
[[ $FAIL -eq 0 ]]
