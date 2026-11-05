#!/usr/bin/env bash
# Project Sunset - single capture for Pi Zero W + IMX477 (Pi HQ / Arducam UC-517)
# Captures locally first; sunset-sync.sh moves frames to the NAS.
set -euo pipefail

CAM_NAME="${CAM_NAME:-wide}"                     # wide | tight
OUT_ROOT="${OUT_ROOT:-$HOME/sunset/outbox}"
LOG_FILE="${LOG_FILE:-$(dirname "$OUT_ROOT")/capture.log}"
LOCK_FILE="${LOCK_FILE:-$(dirname "$OUT_ROOT")/.sunset-capture.lock}"
NIGHT_LUX="${NIGHT_LUX:-5}"                       # below this lux, add a long exposure
NIGHT_SHUTTER_US="${NIGHT_SHUTTER_US:-8000000}"   # 8 s
NIGHT_GAIN="${NIGHT_GAIN:-4}"
SAVE_RAW="${SAVE_RAW:-1}"                         # 1 = also save DNG
CAPTURE_TIMEOUT_S="${CAPTURE_TIMEOUT_S:-60}"      # per rpicam-still call
REQUIRE_TIME_SYNC="${REQUIRE_TIME_SYNC:-1}"       # 1 = refuse to capture until the clock has synced this boot
CLOCK_OK_FILE="${CLOCK_OK_FILE:-/dev/shm/sunset-clock-ok}"   # tmpfs: cleared on every boot
DISK_DROP_RAW_PCT="${DISK_DROP_RAW_PCT:-85}"      # at/above this % full, stop saving DNG
DISK_SKIP_NIGHT_PCT="${DISK_SKIP_NIGHT_PCT:-95}"  # at/above this % full, skip the night frame
DISK_MIN_FREE_MB="${DISK_MIN_FREE_MB:-100}"       # below this, skip everything (keep the OS and log writable)

log() { echo "$(date -u +%FT%TZ) cam=$CAM_NAME $*" >> "$LOG_FILE" 2>/dev/null || true; }

mkdir -p "$(dirname "$LOG_FILE")" "$OUT_ROOT"

# Never run two captures at once (camera is exclusive; a slow run must not collide).
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || { log "skipped: previous capture still running"; exit 0; }
fi

# Clock. The Zero has no RTC: after a power cut it boots with the time fake-hwclock
# last saved, which is hours or days wrong until NTP answers. UTC filenames from a
# wrong clock are worse than a gap, so wait for the first sync of this boot. After
# that, later NTP outages are fine (the kernel flags "unsynced" within hours, but a
# crystal drifts only seconds per day), so remember the sync instead of re-asking.
clock_synced() {
  [[ -e "$CLOCK_OK_FILE" ]] && return 0
  command -v timedatectl >/dev/null 2>&1 || return 0   # cannot tell; trust the clock
  if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)" == "yes" ]]; then
    : > "$CLOCK_OK_FILE" 2>/dev/null || true
    return 0
  fi
  return 1
}
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
find "$STAGE" -type f -mmin +60 -delete 2>/dev/null || true   # leftovers from a killed capture
BASE="$STAGE/$NAME"
ERR_FILE="$STAGE/.last-error"

# Disk guard. Percent is df's own "Use%" for the outbox filesystem, i.e. what the
# non-root pi user can actually still write. Space is shed in order: DNG first
# (biggest, JPEG+JSON still tell the story), then the night frame, then everything.
disk_used_pct() { df -P "$OUT_ROOT" | awk 'NR==2{gsub("%","",$5); print $5+0}'; }
disk_free_mb()  { df -Pm "$OUT_ROOT" | awk 'NR==2{print $4+0}'; }

DISK_PCT="$(disk_used_pct)"
FREE_MB="$(disk_free_mb)"
if (( FREE_MB < DISK_MIN_FREE_MB )); then
  log "SKIPPED: disk full (${DISK_PCT}% used, ${FREE_MB} MB free < ${DISK_MIN_FREE_MB} MB) - nothing captured"
  exit 1
fi

RAW_ARGS=()
RAW=0
if [[ "$SAVE_RAW" == "1" ]]; then
  if (( DISK_PCT >= DISK_DROP_RAW_PCT )); then
    log "DISK ${DISK_PCT}% >= ${DISK_DROP_RAW_PCT}%: dropping DNG for this frame"
  else
    RAW_ARGS=(--raw); RAW=1
  fi
fi

# run_cam <rpicam-still args...>: bounded, stderr kept for the log.
run_cam() {
  local rc=0
  timeout "$CAPTURE_TIMEOUT_S" rpicam-still "$@" 2>"$ERR_FILE" || rc=$?
  return "$rc"
}

fail() { # fail <what> <rc>
  log "FAILED $1 rc=$2 err=$(tail -n 2 "$ERR_FILE" 2>/dev/null | tr '\n' '|')"
  rm -f "$BASE".* "${BASE}_night".* 2>/dev/null || true
  exit 1
}

# Add sun azimuth/elevation (true north) and minutes from sunset to a frame's JSON.
# Pure arithmetic, no network. A failure here must never cost the frame.
SUN_PY="${SUN_PY:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sunset-sun.py}"
SUN="na"
add_sun() { # add_sun <json>
  local out
  if [[ -z "${SITE_LAT:-}" || -z "${SITE_LON:-}" ]]; then
    SUN="nosite"; return 0
  fi
  if out="$(python3 "$SUN_PY" annotate "$1" --time "$TS" 2>"$ERR_FILE")"; then
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
  local args=(annotate "$json" --kind "$kind" --camera "$CAM_NAME" --slot "$TS"
    --started "$started" --finished "$finished" --outbox "$OUT_ROOT"
    --script "${BASH_SOURCE[0]}" --decision-lux "$lux"
    --setup-id "${SETUP_ID:-}" --setup-note "${SETUP_NOTE:-}"
    --nas-target "${NAS_TARGET:-}" --sync-log "${SYNC_LOG_FILE:-$(dirname "$OUT_ROOT")/sync.log}")
  for setting in "$@"; do args+=(--set "$setting"); done
  [[ "${FRAME_CHECKSUMS:-1}" == "1" ]] || args+=(--no-checksums)
  if ! timeout 30 python3 "$META_PY" "${args[@]}" 2>"$ERR_FILE"; then
    META="err"
    log "WARN meta annotate failed: $(tail -n 1 "$ERR_FILE" 2>/dev/null)"
  fi
}

# Move one finished set of files from .partial to the day directory.
publish() { # publish <prefix-glob-base>
  mkdir -p "$DAY_DIR"
  mv -f "$1".* "$DAY_DIR/"
}

# 1) Auto-exposure shot; -t gives AE/AWB time to settle on the slow Zero.
RC=0
SHOT_START="$(date +%s.%N)"
run_cam -n -t 3000 ${RAW_ARGS[@]+"${RAW_ARGS[@]}"} \
  --metadata "$BASE.json" --metadata-format json \
  -o "$BASE.jpg" || RC=$?
SHOT_END="$(date +%s.%N)"
[[ "$RC" == 0 ]] || fail "capture" "$RC"
[[ -s "$BASE.jpg" ]] || fail "capture(empty jpg)" 0
add_sun "$BASE.json"
add_meta "$BASE.json" auto "$SHOT_START" "$SHOT_END" "" settle_ms=3000 "raw=$RAW" "night_lux=$NIGHT_LUX"
publish "$BASE"
RAW_DAY="$RAW"

# 2) Read the scene lux the camera reported (9999 = unknown, so no night shot).
LUX="$(sed -n 's/.*"Lux"[[:space:]]*:[[:space:]]*\([0-9.eE+-]*\).*/\1/p' "$DAY_DIR/$NAME.json" 2>/dev/null | head -n 1)"
LUX="${LUX:-9999}"

# 3) Too dark? Add a fixed long exposure (Pi auto-exposure underexposes at night).
NIGHT=0
DARK=0
awk -v l="$LUX" -v n="$NIGHT_LUX" 'BEGIN{exit !(l+0 < n+0)}' && DARK=1
if (( DARK )); then
  DISK_PCT="$(disk_used_pct)"            # the day frame just used some space
fi
if (( DARK )) && (( DISK_PCT >= DISK_SKIP_NIGHT_PCT )); then
  log "DISK ${DISK_PCT}% >= ${DISK_SKIP_NIGHT_PCT}%: skipping night frame"
elif (( DARK )); then
  if [[ "$RAW" == 1 ]] && (( DISK_PCT >= DISK_DROP_RAW_PCT )); then
    RAW_ARGS=(); RAW=0
    log "DISK ${DISK_PCT}% >= ${DISK_DROP_RAW_PCT}%: dropping DNG for night frame"
  fi
  RC=0
  SHOT_START="$(date +%s.%N)"
  run_cam -n -t 1000 ${RAW_ARGS[@]+"${RAW_ARGS[@]}"} \
    --shutter "$NIGHT_SHUTTER_US" --gain "$NIGHT_GAIN" --awbgains 1.6,1.8 \
    --metadata "${BASE}_night.json" --metadata-format json \
    -o "${BASE}_night.jpg" || RC=$?
  SHOT_END="$(date +%s.%N)"
  if [[ "$RC" == 0 && -s "${BASE}_night.jpg" ]]; then
    add_sun "${BASE}_night.json"
    add_meta "${BASE}_night.json" night "$SHOT_START" "$SHOT_END" "$LUX" settle_ms=1000 "raw=$RAW" \
      "shutter_us=$NIGHT_SHUTTER_US" "gain=$NIGHT_GAIN" awbgains=1.6,1.8 "night_lux=$NIGHT_LUX"
    publish "${BASE}_night"
    NIGHT=1
  else
    # The day frame is already safe; just record that the night one is missing.
    log "FAILED night rc=$RC err=$(tail -n 2 "$ERR_FILE" 2>/dev/null | tr '\n' '|')"
    rm -f "${BASE}_night".* 2>/dev/null || true
  fi
fi

# 4) Log SoC temperature and capture status for the long-term data layer.
TEMP="$( (vcgencmd measure_temp 2>/dev/null || true) | cut -d= -f2)"
log "lux=$LUX soc=${TEMP:-na} disk=${DISK_PCT}% raw=$RAW_DAY night=$NIGHT meta=$META sun=$SUN ok"
