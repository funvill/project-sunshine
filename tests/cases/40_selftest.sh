selftest() { bash "$SRC/sunset-selftest.sh" "$@"; }
st_env() {
  fresh_env
  export TMP_UNUSED=1 NAS_TARGET="sunset@nas.local:/volume1/project-sunset/" SITE_LAT=49.25 SITE_LON=-122.98
  unset STUB_CAMERA STUB_RGB STUB_SSH
}

section "selftest: healthy pi"
st_env; export STUB_LUX=1000
out="$(selftest 2>&1)"; rc=$?
check "exits 0" test "$rc" = 0
check "camera detected" grep -q 'PASS.*IMX477 detected' <<<"$out"
check "day + night capture timed" grep -c 'took' <<<"$out"
check "colour looks normal" grep -q 'PASS.*colour balance looks normal' <<<"$out"
check "NAS ok" grep -q 'PASS.*NAS.*writable' <<<"$out"
check "sunset reported" grep -q 'PASS.*next sunset 20' <<<"$out"
check "temp dir cleaned up" test ! -e "$W/selftest-tmp"
check "wrote nothing to the outbox" test -z "$(find "$OUT_ROOT" -type f 2>/dev/null)"

section "selftest: camera missing"
st_env; export STUB_CAMERA=none
out="$(selftest --no-nas 2>&1)"; rc=$?
check "exits 1" test "$rc" = 1
check "reports no camera" grep -q 'FAIL.*no camera detected' <<<"$out"
check "skips captures" grep -q 'skipped: no usable camera' <<<"$out"

section "selftest: wrong sensor"
st_env; export STUB_CAMERA=imx219
out="$(selftest --quick --no-nas 2>&1)"
check "warns not imx477" grep -q 'WARN.*not an imx477' <<<"$out"

section "selftest: NAS down / unwritable"
st_env; export STUB_SSH=fail
out="$(selftest --quick 2>&1)"; rc=$?
check "NAS down fails" bash -c "[[ $rc == 1 ]] && grep -q 'FAIL.*NAS.*not usable' <<<'$out'"
st_env; export STUB_SSH=notwritable
out="$(selftest --quick 2>&1)"
check "unwritable fails" grep -q 'FAIL.*not writable' <<<"$out"

section "selftest: red-heavy picture flags IR-cut"
st_env; export STUB_LUX=1000 STUB_RGB=200,120,100
out="$(selftest --no-nas 2>&1)"
check "IR-cut warning" grep -q 'WARN.*R/G=1.67' <<<"$out"

section "selftest: dark scene, clock unsynced, full disk, no site"
st_env; export STUB_LUX=1 STUB_NTP=no STUB_DF_PCT=96; unset SITE_LAT SITE_LON
out="$(selftest --no-nas 2>&1)"; rc=$?
check "exits 1" test "$rc" = 1
check "IR-cut check deferred to daylight" grep -q 'too dark' <<<"$out"
check "clock failure" grep -q 'FAIL.*clock NOT synchronized' <<<"$out"
check "disk failure" grep -q 'FAIL.*disk 96% full' <<<"$out"
check "site failure" grep -q 'FAIL.*SITE_LAT' <<<"$out"

section "selftest: shares the capture lock (issue #14)"
if command -v flock >/dev/null 2>&1; then
  st_env; export STUB_LUX=1000 LOCK_WAIT_S=1
  ( exec 8>"$LOCK_FILE"; flock 8; sleep 4 ) & holder=$!; sleep 0.5
  out="$(selftest --no-nas 2>&1)"; rc=$?
  check "camera busy is a failure, not a clash" bash -c "[[ $rc == 1 ]] && grep -q 'FAIL.*camera busy' <<<'$out'"
  check "did not touch the camera while a capture held it" bash -c "! grep -qv '^systemctl' '$STUB_CALLS'"
  wait "$holder"
  st_env; export STUB_LUX=1000; unset LOCK_WAIT_S
  ( exec 8>"$LOCK_FILE"; flock 8; sleep 2 ) & holder=$!; sleep 0.5
  start=$SECONDS; out="$(selftest --no-nas 2>&1)"; rc=$?
  check "waits for a running capture, then passes" test "$rc" = 0 -a $((SECONDS - start)) -ge 1
  wait "$holder"
  st_env; export STUB_LUX=1000 STUB_LOCK_PROBE="$LOCK_FILE"
  selftest --no-nas >/dev/null 2>&1
  check "holds the lock around every camera call" bash -c "test -s '$STUB_CALLS.lock' && ! grep -q free '$STUB_CALLS.lock'"
  unset STUB_LOCK_PROBE
else
  echo "  (flock not installed here: lock tests skipped)"
fi
unset LOCK_WAIT_S
