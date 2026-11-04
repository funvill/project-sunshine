section "diagnostics page unit tests"
check "tests/test_diag.py" python3 -I "$HERE/test_diag.py"

section "diag command"
DIAG_W="$(mktemp -d)"
mkdir -p "$DIAG_W/bin"
cat > "$DIAG_W/bin/sudo" <<'EOF'
#!/usr/bin/env bash
exec "$@"
EOF
# Stand-in for systemctl. The real service writes the link file once it is up.
cat > "$DIAG_W/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$DIAG_CALLS"
case "$1" in
  restart) [[ -n "${STUB_NO_URL:-}" ]] || echo "http://192.0.2.5:8080/?key=abc" > "$DIAG_URL_FILE" ;;
  stop) rm -f "$DIAG_URL_FILE" ;;
  is-active) [[ -e "$DIAG_URL_FILE" ]] && { echo active; exit 0; } || { echo inactive; exit 3; } ;;
esac
EOF
chmod +x "$DIAG_W/bin/sudo" "$DIAG_W/bin/systemctl"
diag_cmd() {
  PATH="$DIAG_W/bin:$PATH" DIAG_CALLS="$DIAG_W/calls" DIAG_URL_FILE="$DIAG_W/url" DIAG_WAIT_TRIES=2 \
    bash "$SRC/diag" "$@"
}

out="$(diag_cmd status 2>&1)"; rc=$?
check "status when off" grep -q 'off' <<<"$out"
check "status when off exits 3" test "$rc" = 3

out="$(diag_cmd 2>&1)"; rc=$?
check "start prints the link" grep -q 'http://192.0.2.5:8080/?key=abc' <<<"$out"
check "start exits 0" test "$rc" = 0
check "start restarts, so the clock starts again" grep -qx 'restart sunset-diag.service' "$DIAG_W/calls"

out="$(diag_cmd status 2>&1)"; rc=$?
check "status when on prints the link" grep -q 'key=abc' <<<"$out"
check "status when on exits 0" test "$rc" = 0

out="$(diag_cmd stop 2>&1)"; rc=$?
check "stop stops the service" grep -qx 'stop sunset-diag.service' "$DIAG_W/calls"
check "stop exits 0" test "$rc" = 0

out="$(STUB_NO_URL=1 diag_cmd start 2>&1)"; rc=$?
check "failed start exits 1" test "$rc" = 1
check "failed start says where to look" grep -q 'journalctl' <<<"$out"

out="$(diag_cmd banana 2>&1)"; rc=$?
check "unknown option exits 2" test "$rc" = 2
rm -rf "$DIAG_W"

section "diag service"
DIAG_UNIT="$SRC/systemd/sunset-diag.service"
check "cannot start at boot" sh -c "! grep -q '^\[Install\]' '$DIAG_UNIT'"
check "does not restart by itself" sh -c "! grep -qE '^Restart=(always|on-)' '$DIAG_UNIT'"
check "has a time limit" grep -q '^RuntimeMaxSec=' "$DIAG_UNIT"
check "link file is in RAM" grep -qx 'RuntimeDirectory=sunset-diag' "$DIAG_UNIT"
check "install.sh installs the unit" grep -q 'sunset-diag.service' "$SRC/install.sh"
check "install.sh installs the command" grep -q '/usr/local/bin/diag' "$SRC/install.sh"
check "install.sh does not enable it" sh -c "! grep -q 'enable.*sunset-diag' '$SRC/install.sh'"
