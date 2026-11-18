# sunset.env.example, the per-host reference copies and .gitignore (issues #23, #26).
# The example must list every setting the scripts read, so a Pi rebuilt from it has none missing.
REPO="$(dirname "$SRC")"
EX="$SRC/sunset.env.example"
# Names set in the example, active or commented out (#NAME=value).
example_keys() { sed -nE 's/^#?[[:space:]]*([A-Z][A-Z0-9_]*)=.*/\1/p' "$EX" | sort -u; }
host_keys()    { sed -nE 's/^([A-Z][A-Z0-9_]*)=.*/\1/p' "$1" | sort -u; }
script_vars()  { grep -ohE '\$\{[A-Z][A-Z0-9_]*:-' "$SRC"/*.sh | sed -E 's/^\$\{//; s/:-$//' | sort -u; }

section "pi/hosts: reference copies"
for h in timelaps cm4; do
  f="$SRC/hosts/$h.env"
  check "$h.env exists" test -s "$f"
  missing="$(comm -23 <(host_keys "$f") <(example_keys) | tr '\n' ' ')"
  check "$h.env: every key exists in sunset.env.example (missing: ${missing:-none})" test -z "$missing"
  check "$h.env says it is a reference copy, not the live file" grep -qi 'REFERENCE COPY' "$f"
  check "$h.env says it is not the live file" grep -q 'NOT the live file' "$f"
  check "$h.env: coordinates are placeholders" grep -qx 'SITE_LAT=REPLACE_WITH_REAL_LATITUDE' "$f"
  check "$h.env: longitude is a placeholder" grep -qx 'SITE_LON=REPLACE_WITH_REAL_LONGITUDE' "$f"
  check "$h.env: no numeric coordinates anywhere" bash -c "! grep -E '[-]?[0-9]{2,3}\.[0-9]{3,}' '$f'"
  check "$h.env: no LAN address, password or token" bash -c "! grep -Eiq '([0-9]{1,3}\.){3}[0-9]{1,3}|(password|passwd|token|secret)[[:space:]]*=' '$f'"
  check "$h.env: no trailing comment after a value (systemd would keep it in the value)" \
    bash -c "! grep -E '^[A-Z][A-Z0-9_]*=[^\"]*[[:space:]]#' '$f'"
  check "$h.env: sets CAM_NAME, SETUP_ID, NAS_TARGET" bash -c "grep -q '^CAM_NAME=' '$f' && grep -q '^SETUP_ID=' '$f' && grep -q '^NAS_TARGET=/' '$f'"
done
check "timelaps is the wide camera" grep -qx 'CAM_NAME=wide' "$SRC/hosts/timelaps.env"
check "cm4 is not in the wide series" grep -qx 'CAM_NAME=cm4wide' "$SRC/hosts/cm4.env"
# Upright from 2026-11-17 (ROTATION=180 from 2026-11-12); chosen by port, not number.
check "cm4 is upright" grep -qx 'ROTATION=0' "$SRC/hosts/cm4.env"
check "cm4 names its camera by port" grep -qx 'CAMERA=i2c@0' "$SRC/hosts/cm4.env"
check "second camera example names CAM1" grep -qx 'CAMERA=i2c@1' "$SRC/sunset2.env.example"
check "second camera has its own name" grep -qx 'CAM_NAME=cm4city' "$SRC/sunset2.env.example"
check "cm4 has the dongle watchdog on" grep -qx 'NETWATCH=1' "$SRC/hosts/cm4.env"
check "cm4 night settings for its lens" grep -qx 'NIGHT_SHUTTER_US=8000000' "$SRC/hosts/cm4.env"
check "cm4 night colour gains" grep -qx 'NIGHT_AWB=2.20,2.80' "$SRC/hosts/cm4.env"
check "timelaps is upright" bash -c "! grep -q '^ROTATION=' '$SRC/hosts/timelaps.env'"
check "values not confirmed on the Pi are marked unverified" grep -qi 'unverified' "$SRC/hosts/cm4.env" "$SRC/hosts/timelaps.env"

section "sunset.env.example: every setting the scripts read"
# Not settings: variables the scripts read only as scratch values or test hooks (a path or a
# command to swap for a stub). Add to this list on purpose, with a reason; anything else must be
# in the example.
IGNORE=" \
  EXP GAIN LUX MODEL SAMPLER_PID TEMP \
  ROOT LOG_FILE LOCK_FILE CLOCK_OK_FILE SUN_PY META_PY SYNC_LOG_FILE SYNC_LOCK_FILE KERNEL_LOG \
  NETWATCH_STATE NETWATCH_LOG NETWATCH_SYSFS NETWATCH_REBOOT_MARK NETWATCH_UPTIME "
unlisted=""
for v in $(script_vars); do
  [[ "$IGNORE" == *" $v "* ]] && continue
  grep -qx "$v" <(example_keys) || unlisted="$unlisted $v"
done
check "no setting is missing from the example (missing:${unlisted:- none})" test -z "$unlisted"
for v in REQUIRE_TIME_SYNC CAPTURE_TIMEOUT_S NETWATCH NETWATCH_RESET_MIN NETWATCH_REBOOT_MIN NETWATCH_REBOOT_GAP_H NETWATCH_IFACE NETWATCH_TARGET; do
  check "example lists $v" grep -qx "$v" <(example_keys)
done
stale=""
for v in $IGNORE; do script_vars | grep -qx "$v" || stale="$stale $v"; done
check "the ignore list names only variables the scripts read (stale:${stale:- none})" test -z "$stale"
check "example NAS_TARGET is the mounted share" grep -qx 'NAS_TARGET=/mnt/nas-camera/project_sunshine/' "$EX"
check "example still shows the SSH form as an alternative" grep -q '^#NAS_TARGET=.*@' "$EX"
check "example has no secrets or LAN addresses" bash -c "! grep -Eiq '([0-9]{1,3}\.){3}[0-9]{1,3}|password|token' '$EX'"

section ".gitignore"
ign() { git -c safe.directory='*' -C "$REPO" check-ignore -q --no-index "$1"; }
check "sunset.env is ignored" ign pi/sunset.env
check "sunset.env backups are ignored" ign pi/sunset.env.bak-2026-11-13-netwatch
check "sunset.env.bak-pilot3 is ignored" ign pi/sunset.env.bak-pilot3
check "credential files are ignored" ign sunset-nas.cred
check "a credential file in a subfolder is ignored" ign pi/x/my.cred
check "the example is not ignored" bash -c "! git -c safe.directory='*' -C '$REPO' check-ignore -q --no-index pi/sunset.env.example"
check "pi/hosts/timelaps.env is not ignored" bash -c "! git -c safe.directory='*' -C '$REPO' check-ignore -q --no-index pi/hosts/timelaps.env"
check "pi/hosts/cm4.env is not ignored" bash -c "! git -c safe.directory='*' -C '$REPO' check-ignore -q --no-index pi/hosts/cm4.env"
