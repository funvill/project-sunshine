# needs: 15_dense
# Issue #23: capture refuses to run when sunset.env is missing. The systemd units load it with
# EnvironmentFile=-, so a missing file is silently fine to systemd. A rebuilt CM4 started
# without one would default to CAM_NAME=wide with no ROTATION: its frames would land in the
# wide/ series and keep the wide alert fresh while the real wide camera might be dead.
# The file is the one next to the script (~/sunset/sunset.env on a Pi). The check is on by
# default only when the caller has not set OUT_ROOT, as on the Pis; the offline tests set
# OUT_ROOT and run the script from pi/, where there is no sunset.env. REQUIRE_ENV_FILE=0|1
# overrides it either way.

# prod_env: a copy of the scripts in $W/home/sunset, run as on a Pi (HOME=$W/home, no
# OUT_ROOT, LOG_FILE or LOCK_FILE from the caller, so the script's own defaults apply).
prod_env() {
  if [[ "${1:-}" == dense ]]; then dense_env; else fresh_env; fi   # dense_env: 15_dense.sh
  P="$W/home/sunset"
  mkdir -p "$P"
  cp "$SRC/sunset-capture.sh" "$SRC/sunset-sun.py" "$SRC/sunset-meta.py" "$P/"
  unset REQUIRE_ENV_FILE
}
prod_capture() { env -u OUT_ROOT -u LOG_FILE -u LOCK_FILE HOME="$W/home" bash "$P/sunset-capture.sh" "$@"; }
prod_frames()  { find "$P/outbox" -type f -not -path '*/.partial/*' 2>/dev/null | sort; }
PLOG() { echo "$W/home/sunset/capture.log"; }

section "env file: missing on a Pi"
prod_env
prod_capture; rc=$?
check "exits non-zero" test "$rc" != 0
check "no frame taken" test -z "$(prod_frames)"
check "camera not touched" test ! -s "$STUB_CALLS"
check "SKIPPED line names the file" grep -q "SKIPPED: .*/sunset/sunset.env missing or empty" "$(PLOG)"

section "env file: missing, dense frame"
prod_env dense
prod_capture --dense; rc=$?
check "dense exits 0 quietly (the regular frame logs it)" test "$rc" = 0
check "no dense frame inside a sunset window" test -z "$(prod_frames)"
check "nothing logged" bash -c "! grep -q 'sunset.env' '$(PLOG)' 2>/dev/null"
echo "CAM_NAME=wide" > "$P/sunset.env"
prod_capture --dense
check "with the file, the dense frame is taken" test -n "$(find "$P/outbox" -name 'wide_*Z.jpg' 2>/dev/null)"

section "env file: empty"
prod_env
: > "$P/sunset.env"
prod_capture; rc=$?
check "an empty file is refused too" test "$rc" != 0 -a -z "$(prod_frames)"
check "logged" grep -q "SKIPPED: .*sunset.env missing or empty" "$(PLOG)"

section "env file: present"
prod_env
echo "CAM_NAME=wide" > "$P/sunset.env"
prod_capture; rc=$?
check "captures" test "$rc" = 0
check "frame taken" test -n "$(find "$P/outbox" -name 'wide_*Z.jpg')"
check "no SKIPPED line" bash -c "! grep -q 'SKIPPED' '$(PLOG)'"

section "env file: REQUIRE_ENV_FILE overrides"
prod_env
REQUIRE_ENV_FILE=0 prod_capture; rc=$?
check "REQUIRE_ENV_FILE=0 captures without the file" test "$rc" = 0 -a -n "$(prod_frames)"
fresh_env
export REQUIRE_ENV_FILE=1
capture; rc=$?
check "REQUIRE_ENV_FILE=1 refuses even with OUT_ROOT set (no sunset.env in pi/)" test "$rc" != 0 -a -z "$(frames)"
check "logged" grep -q "SKIPPED: .*sunset.env missing or empty" "$LOG_FILE"
unset REQUIRE_ENV_FILE

section "env file: OUT_ROOT set by the caller (the offline tests)"
fresh_env
capture; rc=$?
check "not required: captures as before" test "$rc" = 0 -a "$(count 'wide_*Z.jpg')" = 1
