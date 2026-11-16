# Dense frames must not stop silently when the sun script breaks (issue #16).
# sunset-sun.py dense exits 1 with "none" outside the windows; anything else is a fault.
broken_sun() { # broken_sun <rc> <stderr line>: a sun script that fails the way a real fault would
  cat > "$W/sun_broken.py" <<EOF
import sys
print("$2", file=sys.stderr)
sys.exit($1)
EOF
  export SUN_PY="$W/sun_broken.py"
}

section "dense: sun script error is logged"
dense_env; broken_sun 2 "sunset-sun.py: latitude 492.5 out of range"
dense; rc=$?
check "exits 0 (dense never fails the unit)" test "$rc" = 0
check "no frames" test -z "$(frames)"
check "camera not touched" test ! -s "$STUB_CALLS"
check "warning with rc and reason" grep -q 'WARN dense: sun script failed rc=2: sunset-sun.py: latitude 492.5 out of range' "$LOG_FILE"
dense
check "rate-limited: one warning per 5 minutes" test "$(grep -c 'WARN dense' "$LOG_FILE")" = 1
touch -d '6 minutes ago' "$W/sunset-dense-warn"; dense
check "warns again after 5 minutes" test "$(grep -c 'WARN dense' "$LOG_FILE")" = 2

section "dense: a Python crash (exit 1 without \"none\") is an error too"
dense_env; broken_sun 1 "ModuleNotFoundError: No module named 'json'"
dense
check "warning logged" grep -q "WARN dense: sun script failed rc=1: ModuleNotFoundError" "$LOG_FILE"

section "dense: outside the windows stays quiet"
dense_env; export STUB_DENSE=none
dense; dense
check "nothing logged" test ! -s "$LOG_FILE"

section "dense: unset site is logged once"
dense_env; unset SITE_LAT SITE_LON
dense; dense; dense
check "one line" test "$(grep -c 'WARN dense: SITE_LAT/SITE_LON not set' "$LOG_FILE")" = 1
check "no frames" test -z "$(frames)"
