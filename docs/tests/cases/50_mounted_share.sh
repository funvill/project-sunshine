share_env() {
  fresh_env; unset STUB_SAME_FS
  export NAS_TARGET="$W/mnt/share/"
  capture; touch -d '10 minutes ago' $(frames)
}
nas_count() { find "$W/nas" -type f | wc -l | tr -d ' '; }

section "mounted share: normal sync"
share_env; mkdir -p "$NAS_TARGET"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "frames copied" test "$(nas_count)" = 3
check "local copies removed" test -z "$(frames)"

section "mounted share: target missing keeps every frame"
share_env
sync_; rc=$?
check "exits non-zero" test "$rc" != 0
check "nothing copied" test "$(nas_count)" = 0
check "frames still local" test "$(count '*')" = 3
check "logged" grep -q 'not available' "$SYNC_LOG_FILE"
check "does not create the target" test ! -e "$NAS_TARGET"

section "mounted share: unmounted path on the SD card keeps every frame"
share_env; mkdir -p "$NAS_TARGET"; export STUB_SAME_FS=1
sync_; rc=$?
check "exits non-zero" test "$rc" != 0
check "nothing copied" test "$(nas_count)" = 0
check "frames still local" test "$(count '*')" = 3
check "logged" grep -q 'same disk' "$SYNC_LOG_FILE"
unset STUB_SAME_FS

section "selftest: mounted share"
st_env; export NAS_TARGET="$W/mnt/share/"
out="$(selftest --quick 2>&1)"; rc=$?
check "missing share fails" grep -q 'FAIL.*not available' <<<"$out"
mkdir -p "$NAS_TARGET"; export STUB_SAME_FS=1
out="$(selftest --quick 2>&1)"
check "unmounted share fails" grep -q 'FAIL.*same disk' <<<"$out"
unset STUB_SAME_FS
out="$(selftest --quick 2>&1)"
check "mounted share passes" grep -q 'PASS.*mounted and writable' <<<"$out"
