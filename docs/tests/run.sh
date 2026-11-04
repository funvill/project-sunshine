#!/usr/bin/env bash
# Offline tests for the capture/sync scripts, using stub rpicam-still/rsync/df/etc.
# Runs anywhere with bash + coreutils + python3 (no Pi needed):  bash tests/run.sh
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SRC:-$(dirname "$HERE")}"
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
  export PATH="$HERE/stubs:$PATH"
  unset STUB_SAME_FS STUB_RPICAM STUB_LUX STUB_NTP STUB_DF_PCT STUB_DF_FREE_MB STUB_RSYNC
  unset SAVE_RAW SITE_LAT SITE_LON NAS_TARGET NIGHT_LUX CAPTURE_TIMEOUT_S REQUIRE_TIME_SYNC
  mkdir -p "$W/nas"
}
capture() { bash "$SRC/sunset-capture.sh"; }
sync_()   { bash "$SRC/sunset-sync.sh"; }
frames()  { find "$OUT_ROOT" -type f -not -path '*/.partial/*' | sort; }
count()   { find "$OUT_ROOT" -type f -not -path '*/.partial/*' -name "$1" | wc -l | tr -d ' '; }

for t in "$HERE"/cases/*.sh; do
  [[ -e "$t" ]] || continue
  # shellcheck disable=SC1090
  source "$t"
done

echo
echo "passed=$PASS failed=$FAIL"
[[ $FAIL -eq 0 ]]
