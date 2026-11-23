#!/usr/bin/env bash
# Project Sunset - single capture for an IMX477 camera (Arducam B0240E or UC-517) on the CM4
# Captures locally first; sunset-sync.sh moves frames to the NAS.
#   sunset-capture.sh           the regular 5-minute frame (+ night frame when dark)
#   sunset-capture.sh --dense   an extra 1-a-minute frame around sunset:
#                               same auto exposure as the regular frame
# Every frame is a JPEG and its JSON. No DNGs (decided 2026-11-16, #38).
# With BRACKET=1, any frame near sunset is followed by an ev+0 and an ev-2 shot (<name>_ev0,
# <name>_ev-2): the sunset bracket that tools/fuse_sunset.py merges (#10, option E).
set -eEuo pipefail

SCHEDULE=regular
for arg in "$@"; do
  case "$arg" in
    --dense) SCHEDULE=dense ;;
    *) echo "sunset-capture.sh: unknown option $arg" >&2; exit 2 ;;
  esac
done

CAM_NAME="${CAM_NAME:-wide}"                     # wide | tight
OUT_ROOT_GIVEN="${OUT_ROOT:+1}"                   # the caller chose the outbox (the offline tests do)
OUT_ROOT="${OUT_ROOT:-$HOME/sunset/outbox}"
LOG_FILE="${LOG_FILE:-$(dirname "$OUT_ROOT")/capture.log}"
LOCK_FILE="${LOCK_FILE:-$(dirname "$OUT_ROOT")/.sunset-capture.lock}"
NIGHT_LUX="${NIGHT_LUX:-5}"                       # below this lux, add a long exposure
NIGHT_SHUTTER_US="${NIGHT_SHUTTER_US:-4000000}"   # 4 s
NIGHT_GAIN="${NIGHT_GAIN:-1}"
NIGHT_AWB="${NIGHT_AWB:-2.25,2.40}"               # red,blue colour gains, measured at night
CAPTURE_TIMEOUT_S="${CAPTURE_TIMEOUT_S:-60}"      # per rpicam-still call
CAPTURE_KILL_S="${CAPTURE_KILL_S:-10}"            # then SIGKILL, if rpicam-still ignored the SIGTERM
REQUIRE_TIME_SYNC="${REQUIRE_TIME_SYNC:-1}"       # 1 = refuse to capture until the clock has synced this boot
CLOCK_OK_FILE="${CLOCK_OK_FILE:-/dev/shm/sunset-clock-ok}"   # tmpfs: cleared on every boot
CLOCK_TRUST_FILE="$(dirname "$OUT_ROOT")/.clock-trusted"   # left by sunset-guard.sh before its reboot
CLOCK_TRUST_MAX_S="${CLOCK_TRUST_MAX_S:-900}"     # accept that marker only this long after it was written
DISK_SKIP_NIGHT_PCT="${DISK_SKIP_NIGHT_PCT:-95}"  # at/above this % full, skip the night frame
DISK_MIN_FREE_MB="${DISK_MIN_FREE_MB:-100}"       # below this, skip everything (keep the OS and log writable)
SLOT_EVERY_MIN="${SLOT_EVERY_MIN:-5}"             # regular slot spacing; dense mode leaves these minutes alone
LOCK_WAIT_S="${LOCK_WAIT_S:-90}"                  # a regular capture waits this long for a dense one to finish
DENSE_TIMEOUT_S="${DENSE_TIMEOUT_S:-30}"          # per rpicam-still call in dense mode, so a hang ends early
SUN_PY="${SUN_PY:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sunset-sun.py}"
ROTATION="${ROTATION:-0}"                         # 180 = camera mounted upside down (only 0 or 180)
CAMERA="${CAMERA:-}"                              # which camera, when there are two: its ID (e.g. i2c@0) or number
BRACKET="${BRACKET:-0}"                           # 1 = the sunset bracket: ev+0 and ev-2 after each frame near sunset
BRACKET_WINDOW_MIN="${BRACKET_WINDOW_MIN:-45}"    # within this many minutes either side of sunset
BRACKET_AWB_HANDOVER_MIN="${BRACKET_AWB_HANDOVER_MIN:-10}"  # daylight white balance until this long after sunset, then auto
BRACKET_SETTLE_MS="${BRACKET_SETTLE_MS:-1000}"    # settle time of each bracket shot, as in the experiment pair
CAPTURE_RETRY_UNDER_S="${CAPTURE_RETRY_UNDER_S:-15}"   # a regular day shot that fails faster than this is tried once more
CAPTURE_RETRY_WAIT_S="${CAPTURE_RETRY_WAIT_S:-5}"      # pause before that retry
CAPTURE_FAIL_WARN_N="${CAPTURE_FAIL_WARN_N:-6}"        # warn after this many regular failures in a row (6 = 30 minutes)
RUN_DIR="$(dirname "$CLOCK_OK_FILE")"                  # tmpfs: counters that should reset on boot
CAPTURE_FAIL_FILE="$RUN_DIR/sunset-capture-failures"
CAPTURE_LOG_MAX_BYTES="${CAPTURE_LOG_MAX_BYTES:-10485760}"   # then capture.log moves to capture.log.1 (logrotate is masked)
ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sunset.env"   # what the systemd units load
if [[ -n "$OUT_ROOT_GIVEN" ]]; then ENV_DEFAULT=0; else ENV_DEFAULT=1; fi
REQUIRE_ENV_FILE="${REQUIRE_ENV_FILE:-$ENV_DEFAULT}"   # 1 = refuse to capture without sunset.env next to this script

TAG=""
log() {
  if [[ -f "$LOG_FILE" ]] && (( $(wc -c < "$LOG_FILE" 2>/dev/null || echo 0) >= CAPTURE_LOG_MAX_BYTES )); then
    mv -f "$LOG_FILE" "$LOG_FILE.1" 2>/dev/null || true
  fi
  echo "$(date -u +%FT%TZ) cam=$CAM_NAME ${TAG}$*" >> "$LOG_FILE" 2>/dev/null || true
}
# Anything set -e stops on that isn't handled below still leaves a line in the log.
trap 'log "ABORTED line $LINENO rc=$?"' ERR

# rpicam's --rotation flips the sensor readout, so the JPEG comes out upright.
# A bad value must not cost the frame: warn and take it unrotated.
ROT_ARGS=(); ROT_SET=()
case "$ROTATION" in
  0) ;;
  180) ROT_ARGS=(--rotation 180); ROT_SET=(rotation=180) ;;
  *) log "WARN ROTATION=$ROTATION is not 0 or 180: not rotating"; ROTATION=0 ;;
esac

mkdir -p "$(dirname "$LOG_FILE")" "$OUT_ROOT"

# CAMERA: rpicam numbers cameras in the order it finds them, and that order changed on the CM4
# when CAM1 was enabled (2026-11-17). So CAMERA is matched against each camera's line of
# --list-cameras (its port ID, e.g. i2c@0); a plain number is taken as the index. No match, or
# more than one, skips the frame: a gap is better than the other camera's picture in this series.
if [[ -n "$CAMERA" ]]; then
  if [[ "$CAMERA" =~ ^[0-9]+$ ]]; then
    CAM_INDEX="$CAMERA"
  else
    CAM_MATCHES="$(timeout 30 rpicam-still --list-cameras 2>/dev/null 9>&- | grep -E '^[[:space:]]*[0-9]+ : ' | grep -F -- "$CAMERA" || true)"
    if [[ "$(grep -c . <<<"$CAM_MATCHES")" != 1 || -z "$CAM_MATCHES" ]]; then
      [[ "$SCHEDULE" == dense ]] && exit 0
      log "SKIPPED: CAMERA=$CAMERA matches $(grep -c . <<<"$CAM_MATCHES") cameras"
      exit 1
    fi
    CAM_INDEX="$(sed -E 's/^[[:space:]]*([0-9]+) : .*/\1/' <<<"$CAM_MATCHES")"
  fi
  ROT_ARGS+=(--camera "$CAM_INDEX"); ROT_SET+=("camera=$CAMERA")
fi

# Site settings (issue #23). The units load sunset.env with EnvironmentFile=-, so systemd
# runs this happily without it. A Pi rebuilt without the file would then default to
# CAM_NAME=wide with no ROTATION: its frames would join the wide/ series, and keep the wide
# alert fresh while the real wide camera might be dead. A gap is better. Required by default
# only when the caller has not set OUT_ROOT (the Pis never do; the offline tests do).
# The dense frame exits quietly: the regular frame logs it every 5 minutes.
if [[ "$REQUIRE_ENV_FILE" == "1" && ! -s "$ENV_FILE" ]]; then
  [[ "$SCHEDULE" == dense ]] && exit 0
  log "SKIPPED: $ENV_FILE missing or empty (CAM_NAME would default to wide; restore it, or set REQUIRE_ENV_FILE=0)"
  exit 1
fi

# Clock. With no RTC coin cell, after a power cut the Pi boots with the time fake-hwclock
# last saved, which is hours or days wrong until NTP answers. UTC filenames from a
# wrong clock are worse than a gap, so wait for the first sync of this boot. After
# that, later NTP outages are fine (the kernel flags "unsynced" within hours, but a
# crystal drifts only seconds per day), so remember the sync instead of re-asking.
# One exception: when sunset-guard.sh reboots for a dead network, NTP can't answer
# afterwards either. It leaves the time it rebooted in CLOCK_TRUST_FILE, and the first
# run after the boot trusts the clock if it reads at or just after that time (a clean
# reboot keeps the time through fake-hwclock or the RTC; it loses about the length of
# the reboot on a Pi with no RTC). The marker is removed when read, so a later cold
# boot can't use it.
clock_synced() {
  [[ -e "$CLOCK_OK_FILE" ]] && return 0
  command -v timedatectl >/dev/null 2>&1 || return 0   # cannot tell; trust the clock
  if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)" == "yes" ]]; then
    : > "$CLOCK_OK_FILE" 2>/dev/null || true
    rm -f "$CLOCK_TRUST_FILE" 2>/dev/null || true
    return 0
  fi
  if [[ -e "$CLOCK_TRUST_FILE" ]]; then
    local at now
    at="$(head -n 1 "$CLOCK_TRUST_FILE" 2>/dev/null || true)"
    now="$(date +%s)"
    rm -f "$CLOCK_TRUST_FILE" 2>/dev/null || true
    if [[ -e "$CLOCK_TRUST_FILE" ]]; then
      log "WARN clock: cannot remove $CLOCK_TRUST_FILE, so not trusting it"
    elif [[ "$at" =~ ^[0-9]+$ ]] && (( now >= at && now - at <= CLOCK_TRUST_MAX_S )); then
      : > "$CLOCK_OK_FILE" 2>/dev/null || true
      log "clock trusted without NTP: the guard rebooted $(( now - at )) s ago with a synced clock"
      return 0
    else
      log "WARN clock: ignored netwatch's reboot marker (written at ${at:-?}, clock now $now)"
    fi
  fi
  return 1
}

# At most once every 5 minutes, so a broken sun script is seen but doesn't fill the log.
DENSE_WARN_MIN=5
DENSE_WARN_FILE="$RUN_DIR/sunset-dense-warn"
dense_warn() {
  [[ -n "$(find "$DENSE_WARN_FILE" -mmin -"$DENSE_WARN_MIN" 2>/dev/null)" ]] && return 0
  : > "$DENSE_WARN_FILE" 2>/dev/null || true
  log "WARN dense: $*"
}

# Dense mode runs every minute, so everything that rules it out exits quietly: an
# unsynced clock (the regular capture already logs that), a regular slot minute, and
# any minute outside the sunset window. A fault is logged instead
# (rate-limited): no site, or a sun script that fails, would otherwise stop every
# dense frame while the 5-minute frames, and so the Home Assistant alert, carry on.
if [[ "$SCHEDULE" == dense ]]; then
  [[ "$REQUIRE_TIME_SYNC" == "1" ]] && ! clock_synced && exit 0
  MINUTE="$(date -u +%M)"
  (( 10#$MINUTE % SLOT_EVERY_MIN == 0 )) && exit 0
  if [[ -z "${SITE_LAT:-}" || -z "${SITE_LON:-}" ]]; then
    if [[ ! -e "$RUN_DIR/sunset-dense-nosite" ]]; then
      : > "$RUN_DIR/sunset-dense-nosite" 2>/dev/null || true
      log "WARN dense: SITE_LAT/SITE_LON not set in sunset.env: no dense frames this boot"
    fi
    exit 0
  fi
  # sunset-sun.py dense prints "sunset" and exits 0 inside the window, or prints "none" and
  # exits 1 outside it. Anything else (exit 2, a Python traceback) is a fault.
  SUN_RC=0
  SUN_OUT="$(python3 "$SUN_PY" dense 2>&1)" || SUN_RC=$?
  SUN_OUT="${SUN_OUT//$'\r'/}"
  WINDOW="${SUN_OUT##*$'\n'}"
  if [[ "$SUN_RC" == 1 && "$WINDOW" == none ]]; then
    exit 0
  elif [[ "$SUN_RC" != 0 || "$WINDOW" != sunset ]]; then
    [[ -n "$WINDOW" ]] || WINDOW="no output"
    dense_warn "sun script failed rc=$SUN_RC: $WINDOW"
    exit 0
  fi
  TAG="dense window=$WINDOW "
  CAPTURE_TIMEOUT_S="$DENSE_TIMEOUT_S"
fi

# Repeated regular failures: a count in tmpfs (so a reboot clears it) and a warning at the
# threshold. Rebooting on camera failures is sunset-guard.sh's job (CAMWATCH=1).
count_failure() {
  [[ "$SCHEDULE" == regular ]] || return 0
  local n=0
  [[ -f "$CAPTURE_FAIL_FILE" ]] && read -r n < "$CAPTURE_FAIL_FILE" 2>/dev/null || true
  [[ "$n" =~ ^[0-9]+$ ]] || n=0
  n=$(( n + 1 ))
  echo "$n" > "$CAPTURE_FAIL_FILE" 2>/dev/null || true
  (( n == CAPTURE_FAIL_WARN_N )) && log "WARN $n capture failures in a row"
  return 0
}

# Never run two captures at once (the camera is exclusive). The regular frame always
# wins: it waits for a dense frame to finish, and a dense frame never waits.
# sunset-selftest.sh takes the same lock. Children are started with 9>&- so a stuck
# one can't keep holding the lock after this script has gone.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if [[ "$SCHEDULE" == dense ]]; then
    flock -n 9 || { log "skipped: camera busy"; exit 0; }
  else
    flock -w "$LOCK_WAIT_S" 9 || { log "skipped: previous capture still running"; count_failure; exit 0; }
  fi
fi

if [[ "$REQUIRE_TIME_SYNC" == "1" ]] && ! clock_synced; then
  log "SKIPPED: clock not synced since boot (not capturing with an unverified UTC clock)"
  exit 1
fi

# One timestamp for both the directory and the filename, so a capture that starts
# at 23:59:59 cannot end up in tomorrow's directory.
TS="$(date -u +%Y%m%dT%H%M%SZ)"                   # UTC: no DST gaps or duplicates
DAY_DIR="$OUT_ROOT/$CAM_NAME/${TS:0:4}/${TS:4:2}/${TS:6:2}"
NAME="${CAM_NAME}_${TS}"

# Write into .partial and move finished files into place, so sunset-sync.sh can never
# pick up a half-written frame. (Dot-directories are ignored by the sync.)
STAGE="$OUT_ROOT/.partial"
mkdir -p "$STAGE"

# A run that died after its shot (killed, publish failed, power cut) leaves its files
# here. We hold the camera lock, so nothing is still writing them: move every complete
# set (a non-empty JPEG and its JSON, older than a minute) into place, and delete what
# is left once it is an hour old.
rescue_partial() {
  local f base name ts dir
  for f in "$STAGE/${CAM_NAME}"_*.jpg; do
    [[ -f "$f" ]] || continue
    base="${f%.jpg}"; name="${base##*/}"
    [[ "$name" =~ ^${CAM_NAME}_([0-9]{8}T[0-9]{6}Z)(_night|_ev0|_ev-2)?$ ]] || continue
    ts="${BASH_REMATCH[1]}"
    [[ -s "$f" && -s "$base.json" ]] || continue
    [[ -n "$(find "$f" -mmin +1 2>/dev/null)" ]] || continue
    dir="$OUT_ROOT/$CAM_NAME/${ts:0:4}/${ts:4:2}/${ts:6:2}"
    if mkdir -p "$dir" 2>/dev/null && mv -f "$base".* "$dir/" 2>/dev/null; then
      log "rescued $name from .partial"
    else
      log "WARN could not rescue $name from .partial"
    fi
  done
}
rescue_partial
# Incomplete leftovers from a killed capture, this camera's only: the two CM4 cameras share .partial,
# and the other camera's unpublished frame is for its own next run to rescue (review, 2026-11-21).
find "$STAGE" -maxdepth 1 -type f \( -name "${CAM_NAME}_*" -o -name ".${CAM_NAME}_*" \) -mmin +60 -delete 2>/dev/null || true
BASE="$STAGE/$NAME"
ERR_FILE="$STAGE/.last-error"

# Disk guard. Percent is df's own "Use%" for the outbox filesystem, i.e. what the
# non-root pi user can actually still write. Space is shed in order: the night frame
# first, then everything. If df gives no answer, take the frame rather than lose it.
disk_used_pct() { df -P "$OUT_ROOT" 2>/dev/null | awk 'NR==2{gsub("%","",$5); print $5+0}' || true; }
disk_free_mb()  { df -Pm "$OUT_ROOT" 2>/dev/null | awk 'NR==2{print $4+0}' || true; }

DISK_PCT="$(disk_used_pct)"
FREE_MB="$(disk_free_mb)"
DISK_KNOWN=1
if [[ ! "$DISK_PCT" =~ ^[0-9]+$ || ! "$FREE_MB" =~ ^[0-9]+$ ]]; then
  DISK_KNOWN=0; DISK_PCT=na
  log "WARN disk usage unknown (df gave no answer for $OUT_ROOT): no disk guard for this frame"
elif (( FREE_MB < DISK_MIN_FREE_MB )); then
  log "SKIPPED: disk full (${DISK_PCT}% used, ${FREE_MB} MB free < ${DISK_MIN_FREE_MB} MB) - nothing captured"
  exit 1
fi

# run_cam <rpicam-still args...>: bounded (SIGKILL if SIGTERM is ignored), stderr kept for the log.
run_cam() {
  local rc=0
  timeout -k "$CAPTURE_KILL_S" "$CAPTURE_TIMEOUT_S" rpicam-still ${ROT_ARGS[@]+"${ROT_ARGS[@]}"} "$@" \
    2>"$ERR_FILE" 9>&- || rc=$?
  return "$rc"
}

fail() { # fail <what> <rc>
  log "FAILED $1 rc=$2 err=$(tail -n 2 "$ERR_FILE" 2>/dev/null | tr '\n' '|')"
  rm -f "$BASE".* "${BASE}_night".* 2>/dev/null || true
  count_failure
  exit 1
}

# Add sun azimuth/elevation (true north) and minutes from sunset to a frame's JSON.
# Pure arithmetic, no network. A failure here must never cost the frame.
SUN="na"
add_sun() { # add_sun <json>
  local out
  if [[ -z "${SITE_LAT:-}" || -z "${SITE_LON:-}" ]]; then
    SUN="nosite"; return 0
  fi
  if out="$(python3 "$SUN_PY" annotate "$1" --time "$TS" 2>"$ERR_FILE" 9>&-)"; then
    SUN="${out// /,}"
  else
    SUN="err"
    log "WARN sun annotate failed: $(tail -n 1 "$ERR_FILE" 2>/dev/null)"
  fi
}

# Add how the frame was taken and the state of the machine to its JSON, including
# checksums of the image files. Bounded, and a failure here must never cost the frame.
META_PY="${META_PY:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sunset-meta.py}"
META="ok"
add_meta() { # add_meta <json> <auto|night> <started> <finished> <decision lux or ""> <key=value>...
  local json="$1" kind="$2" started="$3" finished="$4" lux="$5" setting
  shift 5
  local args=(annotate "$json" --kind "$kind" --camera "$CAM_NAME" --schedule "$SCHEDULE" --slot "$TS"
    --started "$started" --finished "$finished" --outbox "$OUT_ROOT"
    --script "${BASH_SOURCE[0]}" --decision-lux "$lux"
    --setup-id "${SETUP_ID:-}" --setup-note "${SETUP_NOTE:-}" --profile-id "${PROFILE_ID:-}"
    --nas-target "${NAS_TARGET:-}" --sync-log "${SYNC_LOG_FILE:-$(dirname "$OUT_ROOT")/sync.log}")
  for setting in "$@"; do args+=(--set "$setting"); done
  [[ "${FRAME_CHECKSUMS:-1}" == "1" ]] || args+=(--no-checksums)
  if ! timeout -k 5 30 python3 "$META_PY" "${args[@]}" 2>"$ERR_FILE" 9>&-; then
    META="err"
    log "WARN meta annotate failed: $(tail -n 1 "$ERR_FILE" 2>/dev/null)"
  fi
}

# Move one finished set of files from .partial to the day directory. If that fails (disk
# full, read-only after an SD error), the files stay in .partial for the next run to rescue.
publish() { # publish <prefix-glob-base>
  if ! { mkdir -p "$DAY_DIR" && mv -f "$1".* "$DAY_DIR/"; } 2>"$ERR_FILE"; then
    log "FAILED publish ${1##*/} err=$(tail -n 2 "$ERR_FILE" 2>/dev/null | tr '\n' '|') (kept in .partial)"
    count_failure
    exit 1
  fi
}

# The sunset bracket (#10, option E). After a frame within BRACKET_WINDOW_MIN of sunset, an ev+0
# and an ev-2 shot, daylight white balance until BRACKET_AWB_HANDOVER_MIN after sunset (it turns
# the sky brown later, as the city lights the cloud), then auto. The frame is already
# published: a failed bracket shot is logged, never fatal.
BRACKET_N=0
frame_minutes() { # frame_minutes <json>: Sun.minutes_from_sunset, or nothing
  python3 -c 'import json,sys; print(float(json.load(open(sys.argv[1]))["Sun"]["minutes_from_sunset"]))' "$1" \
    2>/dev/null 9>&- | tr -d '\r' || true
}
within() { awk -v m="$1" -v w="$2" 'BEGIN{exit !(m >= -w && m <= w)}'; }   # within <minutes> <limit>
bracket_pair() { # bracket_pair <published json of the frame>
  [[ "$BRACKET" == 1 ]] || return 0
  local mins sun_was="$SUN" ev b rc start end awb=daylight
  mins="$(frame_minutes "$1")"
  [[ -n "$mins" ]] && within "$mins" "$BRACKET_WINDOW_MIN" || return 0
  local awb_args=(--awb daylight)
  awk -v m="$mins" -v h="$BRACKET_AWB_HANDOVER_MIN" 'BEGIN{exit !(m > h)}' && { awb=auto; awb_args=(); }
  for ev in 0 -2; do
    b="${BASE}_ev${ev}"
    rc=0
    start="$(date +%s.%N)"
    run_cam -n -t "$BRACKET_SETTLE_MS" --ev "$ev" ${awb_args[@]+"${awb_args[@]}"} \
      --metadata "$b.json" --metadata-format json -o "$b.jpg" || rc=$?
    end="$(date +%s.%N)"
    if [[ "$rc" != 0 || ! -s "$b.jpg" ]]; then
      log "WARN bracket ev$ev failed rc=$rc err=$(tail -n 2 "$ERR_FILE" 2>/dev/null | tr '\n' '|')"
      rm -f "$b".* 2>/dev/null || true
      break
    fi
    add_sun "$b.json"
    add_meta "$b.json" bracket "$start" "$end" "" "settle_ms=$BRACKET_SETTLE_MS" "ev=$ev" "awb=$awb" \
      "bracket_of=$NAME" ${ROT_SET[@]+"${ROT_SET[@]}"}
    if ! { mkdir -p "$DAY_DIR" && mv -f "$b".* "$DAY_DIR/"; } 2>"$ERR_FILE"; then
      log "WARN bracket ev$ev publish failed (kept in .partial)"
      break
    fi
    BRACKET_N=$(( BRACKET_N + 1 ))
  done
  SUN="$sun_was"
}
bracket_note() { [[ "$BRACKET" == 1 ]] && echo " bracket=$BRACKET_N" || true; }

# 1) Auto-exposure shot; -t gives AE/AWB time to settle.
#    A regular shot that fails quickly (another program holding the camera, say) is
#    tried once more; a timeout is not, since a second one wouldn't fit the slot.
day_shot() {
  RC=0
  SHOT_START="$(date +%s.%N)"
  run_cam -n -t 3000 \
    --metadata "$BASE.json" --metadata-format json \
    -o "$BASE.jpg" || RC=$?
  SHOT_END="$(date +%s.%N)"
}
T0=$SECONDS
day_shot
if [[ "$RC" != 0 && "$SCHEDULE" == regular && "$RC" != 124 && "$RC" != 137 ]] \
   && (( SECONDS - T0 < CAPTURE_RETRY_UNDER_S )); then
  log "WARN capture failed after $(( SECONDS - T0 )) s rc=$RC: retrying err=$(tail -n 1 "$ERR_FILE" 2>/dev/null)"
  rm -f "$BASE".* 2>/dev/null || true
  sleep "$CAPTURE_RETRY_WAIT_S"
  day_shot
fi
[[ "$RC" == 0 ]] || fail "capture" "$RC"
[[ -s "$BASE.jpg" ]] || fail "capture(empty jpg)" 0
add_sun "$BASE.json"
add_meta "$BASE.json" auto "$SHOT_START" "$SHOT_END" "" settle_ms=3000 "night_lux=$NIGHT_LUX" \
  ${ROT_SET[@]+"${ROT_SET[@]}"}
publish "$BASE"
rm -f "$CAPTURE_FAIL_FILE" 2>/dev/null || true

# A dense frame is only this one shot: no night frame, so it stays short.
if [[ "$SCHEDULE" == dense ]]; then
  bracket_pair "$DAY_DIR/$NAME.json"
  TEMP="$( (vcgencmd measure_temp 2>/dev/null 9>&- || true) | cut -d= -f2)"
  log "soc=${TEMP:-na} disk=${DISK_PCT}%$(bracket_note) meta=$META sun=$SUN ok"
  exit 0
fi

# 2) Read the scene lux the camera reported (9999 = unknown, so no night shot).
LUX="$(sed -n 's/.*"Lux"[[:space:]]*:[[:space:]]*\([0-9.eE+-]*\).*/\1/p' "$DAY_DIR/$NAME.json" 2>/dev/null | head -n 1 || true)"
LUX="${LUX:-9999}"

# 3) Too dark? Add a fixed long exposure (Pi auto-exposure underexposes at night).
NIGHT=0
DARK=0
awk -v l="$LUX" -v n="$NIGHT_LUX" 'BEGIN{exit !(l+0 < n+0)}' && DARK=1
if (( DARK )) && [[ "$DISK_KNOWN" == 1 ]]; then
  DISK_PCT="$(disk_used_pct)"            # the day frame just used some space
  [[ "$DISK_PCT" =~ ^[0-9]+$ ]] || { DISK_KNOWN=0; DISK_PCT=na; log "WARN disk usage unknown: night frame without the disk guard"; }
fi
if (( DARK )) && [[ "$DISK_KNOWN" == 1 ]] && (( DISK_PCT >= DISK_SKIP_NIGHT_PCT )); then
  log "DISK ${DISK_PCT}% >= ${DISK_SKIP_NIGHT_PCT}%: skipping night frame"
elif (( DARK )); then
  RC=0
  SHOT_START="$(date +%s.%N)"
  run_cam -n -t 1000 \
    --shutter "$NIGHT_SHUTTER_US" --gain "$NIGHT_GAIN" --awbgains "$NIGHT_AWB" \
    --metadata "${BASE}_night.json" --metadata-format json \
    -o "${BASE}_night.jpg" || RC=$?
  SHOT_END="$(date +%s.%N)"
  if [[ "$RC" == 0 && -s "${BASE}_night.jpg" ]]; then
    add_sun "${BASE}_night.json"
    add_meta "${BASE}_night.json" night "$SHOT_START" "$SHOT_END" "$LUX" settle_ms=1000 \
      "shutter_us=$NIGHT_SHUTTER_US" "gain=$NIGHT_GAIN" "awbgains=$NIGHT_AWB" "night_lux=$NIGHT_LUX" \
      ${ROT_SET[@]+"${ROT_SET[@]}"}
    publish "${BASE}_night"
    NIGHT=1
  else
    # The day frame is already safe; just record that the night one is missing.
    log "FAILED night rc=$RC err=$(tail -n 2 "$ERR_FILE" 2>/dev/null | tr '\n' '|')"
    rm -f "${BASE}_night".* 2>/dev/null || true
  fi
fi

# 4) The sunset bracket, after the night frame.
bracket_pair "$DAY_DIR/$NAME.json"

# 5) Log SoC temperature and capture status for the long-term data layer.
TEMP="$( (vcgencmd measure_temp 2>/dev/null 9>&- || true) | cut -d= -f2)"
log "lux=$LUX soc=${TEMP:-na} disk=${DISK_PCT}% night=$NIGHT$(bracket_note) meta=$META sun=$SUN ok"
