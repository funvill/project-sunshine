# experiments/sunset-nightly.sh: the sunset bracket every evening until production has it (#10).
# It reads tonight's sunset from the sun script and hands the runner a window of 45 min either side.
nightly_env() {
  fresh_env
  NIGHTLY="$(dirname "$SRC")/experiments/sunset-nightly.sh"
  printf 'CAM_NAME=wide\nSITE_LAT="1.5"\nSITE_LON=-2.5\n' > "$W/sunset.env"
  cat > "$W/sun.py" <<'PY'
import os, sys
assert sys.argv[1:] == ["sunset", "--epoch"], sys.argv
assert os.environ.get("SITE_LAT") == "1.5" and os.environ.get("SITE_LON") == "-2.5"
print(os.environ["FAKE_SUNSET"])
PY
  cat > "$W/runner.py" <<'PY'
import sys
open(sys.argv[0] + ".args", "w").write(" ".join(sys.argv[1:]))
PY
  export NIGHTLY_ENV_FILE="$W/sunset.env" SUN_PY="$W/sun.py" NIGHTLY_RUNNER="$W/runner.py"
  export NIGHTLY_SLEEP=0 NIGHTLY_NOW=1794870000 FAKE_SUNSET=1794875329
}

section "sunset-nightly: runs tonight's sunset window"
nightly_env
bash "$NIGHTLY"; rc=$?
args="$(cat "$W/runner.py.args" 2>/dev/null)"
check "exits 0" test "$rc" = 0
check "sunset program, dated run name" test "$args" = "sunset --run sunset-20261117 --sunset 1794875329 --until $((1794875329 + 2700 + 60))"

section "sunset-nightly: the CM4 gets its own run names"
nightly_env; printf 'CAM_NAME=cm4wide\nSITE_LAT="1.5"\nSITE_LON=-2.5\n' > "$W/sunset.env"
bash "$NIGHTLY"
check "cm4- prefix" grep -q -- '--run cm4-sunset-20261117 ' "$W/runner.py.args"

section "sunset-nightly: a late start skips tonight"
nightly_env; export NIGHTLY_NOW=$((1794875329 - 6 * 3600 - 1))
bash "$NIGHTLY"; rc=$?
check "exits 0" test "$rc" = 0
check "runner not started when the next sunset is over 6 h away" test ! -e "$W/runner.py.args"

section "sunset-nightly: a failing sun script fails the unit"
nightly_env; export FAKE_SUNSET=
bash "$NIGHTLY" 2>/dev/null; rc=$?
check "exits non-zero" test "$rc" != 0
check "runner not started" test ! -e "$W/runner.py.args"
