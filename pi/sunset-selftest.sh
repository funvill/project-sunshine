#!/usr/bin/env bash
# Project Sunset - pilot self-test. Run on the Pi:  ./sunset-selftest.sh [--quick] [--no-nas]
#   --quick   skip the timed captures (camera list, clock, disk, memory, NAS only)
#   --no-nas  skip the NAS check
# Prints PASS / WARN / FAIL / INFO per check; exit status 1 if anything FAILed.
# Thresholds marked "estimate" are guesses to be tuned from pilot data, not facts.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$HERE/sunset.env" ]] && { set -a; . "$HERE/sunset.env"; set +a; }

CAM_NAME="${CAM_NAME:-wide}"
OUT_ROOT="${OUT_ROOT:-$HOME/sunset/outbox}"
LOG_FILE="${LOG_FILE:-$(dirname "$OUT_ROOT")/capture.log}"
NAS_TARGET="${NAS_TARGET:-sunset@nas.local:/volume1/project-sunset/}"
NIGHT_LUX="${NIGHT_LUX:-5}"
NIGHT_SHUTTER_US="${NIGHT_SHUTTER_US:-4000000}"
NIGHT_GAIN="${NIGHT_GAIN:-1}"
NIGHT_AWB="${NIGHT_AWB:-2.07,2.28}"
SAVE_RAW="${SAVE_RAW:-1}"
CAPTURE_TIMEOUT_S="${CAPTURE_TIMEOUT_S:-60}"
SUN_PY="${SUN_PY:-$HERE/sunset-sun.py}"
SLOW_CAPTURE_S="${SLOW_CAPTURE_S:-30}"           # estimate: WARN above this for the day shot
LOW_MEM_MB="${LOW_MEM_MB:-60}"                   # estimate: WARN if MemAvailable dips below this mid-capture
IRCUT_RG_WARN="${IRCUT_RG_WARN:-1.25}"           # estimate, uncalibrated: mean R / mean G above this looks IR-contaminated
TMP_ROOT="$(dirname "$OUT_ROOT")/selftest-tmp"

QUICK=0; NO_NAS=0
for a in "$@"; do
  case "$a" in
    --quick) QUICK=1 ;;
    --no-nas) NO_NAS=1 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

NPASS=0; NWARN=0; NFAIL=0
pass() { NPASS=$((NPASS+1)); printf '[PASS] %s\n' "$*"; }
warn() { NWARN=$((NWARN+1)); printf '[WARN] %s\n' "$*"; }
fail() { NFAIL=$((NFAIL+1)); printf '[FAIL] %s\n' "$*"; }
info() { printf '[INFO] %s\n' "$*"; }
head_() { printf '\n== %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
meminfo_mb() { awk -v k="$1:" '$1==k{printf "%d", $2/1024}' /proc/meminfo 2>/dev/null; }
json_num() { sed -n "s/.*\"$2\"[[:space:]]*:[[:space:]]*\([-0-9.eE+]*\).*/\1/p" "$1" | head -n1; }

cleanup() { rm -rf "$TMP_ROOT"; [[ -n "${SAMPLER_PID:-}" ]] && kill "$SAMPLER_PID" 2>/dev/null; return 0; }
trap cleanup EXIT

head_ "System"
MODEL="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)"
info "model: ${MODEL:-unknown}  arch: $(uname -m)  kernel: $(uname -r)"
[[ -r /etc/os-release ]] && info "os: $(. /etc/os-release; echo "$PRETTY_NAME")"
case "$(uname -m)" in
  armv6l|armv7l) pass "32-bit userland ($(uname -m))" ;;
  *) warn "arch is $(uname -m); the Zero path is 32-bit armv6l" ;;
esac
for t in rpicam-still rsync ssh python3 timeout awk; do
  if have "$t"; then pass "found $t"; else fail "missing $t"; fi
done
have flock || warn "flock missing: overlapping runs are not prevented"
if [[ -f /boot/firmware/config.txt ]]; then
  info "config.txt: $(grep -E '^(camera_auto_detect|dtoverlay=(imx477|vc4))' /boot/firmware/config.txt | tr '\n' ' ')"
fi

head_ "Clock"
if have timedatectl; then
  if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" == "yes" ]]; then
    pass "NTP synchronized ($(date -u +%FT%TZ))"
  else
    fail "clock NOT synchronized: sunset-capture.sh will refuse to capture (see timedatectl status)"
  fi
else
  warn "timedatectl not found; cannot verify clock"
fi

head_ "Camera"
CAMLIST="$(timeout 30 rpicam-still --list-cameras 2>&1 || true)"
if grep -qi 'imx477' <<<"$CAMLIST"; then
  pass "IMX477 detected: $(grep -i imx477 <<<"$CAMLIST" | head -n1 | sed 's/^ *//')"
elif grep -Eq '^ *[0-9]+ *:' <<<"$CAMLIST"; then
  warn "a camera is present but it is not an imx477: $(grep -E '^ *[0-9]+ *:' <<<"$CAMLIST" | head -n1)"
else
  fail "no camera detected (check ribbon cable, camera_auto_detect=0 + dtoverlay=imx477 for the UC-517): $(tail -n 1 <<<"$CAMLIST")"
fi

head_ "Storage and memory"
if [[ -d "$OUT_ROOT" ]] || mkdir -p "$OUT_ROOT" 2>/dev/null; then
  read -r PCT FREE < <(df -Pm "$OUT_ROOT" | awk 'NR==2{gsub("%","",$5); print $5, $4}')
  if (( PCT >= 95 )); then fail "disk ${PCT}% full (${FREE} MB free)"
  elif (( PCT >= 85 )); then warn "disk ${PCT}% full (${FREE} MB free): DNGs are already being dropped"
  else pass "disk ${PCT}% full (${FREE} MB free)"; fi
else
  fail "cannot create $OUT_ROOT"
fi
if [[ -r /proc/meminfo ]]; then
  info "memory: total $(meminfo_mb MemTotal) MB, available $(meminfo_mb MemAvailable) MB, swap free $(meminfo_mb SwapFree) MB"
  CMA="$(meminfo_mb CmaTotal)"
  [[ -n "$CMA" && "$CMA" != 0 ]] && info "CMA: total ${CMA} MB, free $(meminfo_mb CmaFree) MB (raise with dtoverlay=vc4-kms-v3d,cma-128 if captures fail to allocate)"
else
  warn "/proc/meminfo unreadable"
fi

head_ "Sun module"
if [[ -z "${SITE_LAT:-}" || -z "${SITE_LON:-}" ]]; then
  fail "SITE_LAT/SITE_LON not set in sunset.env: frames will have no sun data"
elif have python3; then
  T0=$(date +%s.%N)
  NS="$(python3 "$SUN_PY" sunset 2>&1)"; RC=$?
  T1=$(date +%s.%N)
  if (( RC == 0 )); then
    pass "next sunset $NS (python startup + calc $(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b-a}') s)"
  else
    fail "sunset-sun.py failed: $NS"
  fi
fi

# One timed capture, run exactly like sunset-capture.sh would. Sets CAP_* variables.
timed_shot() { # timed_shot <label> <rpicam args...>
  local label="$1"; shift
  local min_mem t0 t1 rc=0 samp
  mkdir -p "$TMP_ROOT"; rm -f "$TMP_ROOT"/*
  samp="$TMP_ROOT/.memmin"
  ( m=999999; while :; do v="$(meminfo_mb MemAvailable)"; [[ -n "$v" ]] && (( v < m )) && { m=$v; echo "$m" > "$samp"; }; sleep 0.25; done ) &
  SAMPLER_PID=$!
  t0=$(date +%s.%N)
  timeout "$CAPTURE_TIMEOUT_S" rpicam-still "$@" 2>"$TMP_ROOT/err" || rc=$?
  t1=$(date +%s.%N)
  kill "$SAMPLER_PID" 2>/dev/null; wait "$SAMPLER_PID" 2>/dev/null; SAMPLER_PID=""
  CAP_S="$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.1f", b-a}')"
  min_mem="$(cat "$samp" 2>/dev/null || echo '?')"
  if (( rc != 0 )); then
    fail "$label failed rc=$rc after ${CAP_S}s: $(tail -n 2 "$TMP_ROOT/err" | tr '\n' '|')"
    return 1
  fi
  local sizes
  sizes="$(cd "$TMP_ROOT" && for f in shot.*; do printf '%s=%s KB ' "${f##*.}" "$(( ($(wc -c < "$f") + 1023) / 1024 ))"; done)"
  info "$label: ${CAP_S}s, files: ${sizes}, lowest MemAvailable during capture: ${min_mem} MB"
  CAP_MINMEM="$min_mem"
  return 0
}

if (( QUICK )); then
  head_ "Captures"; info "skipped (--quick)"
elif ! have rpicam-still || ! grep -qi imx477 <<<"$CAMLIST"; then
  head_ "Captures"; warn "skipped: no usable camera"
else
  RAW_ARGS=(); [[ "$SAVE_RAW" == "1" ]] && RAW_ARGS=(--raw)

  if [[ "$SAVE_RAW" == "1" ]]; then FMT="JPEG + DNG"; else FMT="JPEG only"; fi
  head_ "Capture time: day shot (AE, $FMT)"
  if timed_shot "day shot" -n -t 3000 ${RAW_ARGS[@]+"${RAW_ARGS[@]}"} \
       --metadata "$TMP_ROOT/shot.json" --metadata-format json -o "$TMP_ROOT/shot.jpg"; then
    S="${CAP_S%.*}"
    if (( S >= CAPTURE_TIMEOUT_S )); then fail "day shot took ${CAP_S}s, at the ${CAPTURE_TIMEOUT_S}s timeout"
    elif (( S >= SLOW_CAPTURE_S )); then warn "day shot took ${CAP_S}s (estimate threshold ${SLOW_CAPTURE_S}s); fine at 15 min, but too slow for bursts"
    else pass "day shot took ${CAP_S}s"; fi
    if [[ "$CAP_MINMEM" != "?" ]] && (( CAP_MINMEM < LOW_MEM_MB )); then
      warn "MemAvailable fell to ${CAP_MINMEM} MB during capture (estimate threshold ${LOW_MEM_MB} MB): consider cma-128 / check swap"
    else
      pass "memory headroom during capture: ${CAP_MINMEM} MB lowest"
    fi
    LUX="$(json_num "$TMP_ROOT/shot.json" Lux)"
    EXP="$(json_num "$TMP_ROOT/shot.json" ExposureTime)"
    GAIN="$(json_num "$TMP_ROOT/shot.json" AnalogueGain)"
    info "scene: lux=${LUX:-?} exposure=${EXP:-?} us analogue_gain=${GAIN:-?} (NIGHT_LUX=$NIGHT_LUX)"
  fi

  head_ "Capture time: night shot (${NIGHT_SHUTTER_US} us, gain ${NIGHT_GAIN})"
  if timed_shot "night shot" -n -t 1000 ${RAW_ARGS[@]+"${RAW_ARGS[@]}"} \
       --shutter "$NIGHT_SHUTTER_US" --gain "$NIGHT_GAIN" --awbgains "$NIGHT_AWB" \
       --metadata "$TMP_ROOT/shot.json" --metadata-format json -o "$TMP_ROOT/shot.jpg"; then
    if (( ${CAP_S%.*} >= CAPTURE_TIMEOUT_S )); then fail "night shot took ${CAP_S}s, at the ${CAPTURE_TIMEOUT_S}s timeout"
    else pass "night shot took ${CAP_S}s (both shots must fit the service's TimeoutStartSec)"; fi
  fi

  head_ "IR-cut filter (heuristic)"
  info "The UC-517's IR-cut is switched by its own photoresistor, so there is no software state to read; this judges the picture instead."
  if [[ -n "${LUX:-}" ]] && awk -v l="$LUX" -v n="$NIGHT_LUX" 'BEGIN{exit !(l+0 < (n+0)*10)}'; then
    info "scene too dark (lux=$LUX) to judge IR-cut; re-run in daylight"
  elif timed_shot "colour probe" -n -t 2000 --width 160 --height 120 -e bmp -o "$TMP_ROOT/shot.bmp"; then
    RATIOS="$(python3 - "$TMP_ROOT/shot.bmp" <<'PY' 2>&1
import struct, sys
d = open(sys.argv[1], "rb").read()
off, = struct.unpack_from("<I", d, 10)
w, h = struct.unpack_from("<ii", d, 18)
bpp, = struct.unpack_from("<H", d, 28)
bytes_pp = bpp // 8
row = (w * bytes_pp + 3) // 4 * 4
sums = [0, 0, 0]
n = 0
for y in range(abs(h)):
    base = off + y * row
    for x in range(w):
        b, g, r = d[base + x * bytes_pp: base + x * bytes_pp + 3]
        sums[0] += r; sums[1] += g; sums[2] += b; n += 1
print("%.2f %.2f %.1f" % (sums[0] / sums[1], sums[2] / sums[1], sums[1] / n))
PY
)"
    if [[ "$RATIOS" =~ ^[0-9.]+\ [0-9.]+\ [0-9.]+$ ]]; then
      read -r RG BG GMEAN <<<"$RATIOS"
      info "mean R/G=$RG B/G=$BG (G mean $GMEAN/255)"
      if awk -v r="$RG" -v t="$IRCUT_RG_WARN" 'BEGIN{exit !(r+0 > t+0)}'; then
        warn "R/G=$RG > $IRCUT_RG_WARN (estimate): picture is red/magenta-heavy, the IR-cut may be OUT or stuck. Look at a daylight test frame."
      else
        pass "colour balance looks normal for IR-cut IN (R/G=$RG; threshold is an uncalibrated estimate: compare against a known-good frame)"
      fi
    else
      warn "could not analyse the colour probe: $RATIOS"
    fi
  fi
fi

head_ "NAS"
if (( NO_NAS )); then
  info "skipped (--no-nas)"
elif [[ "$NAS_TARGET" == /* ]]; then
  if [[ ! -d "$NAS_TARGET" ]]; then
    fail "NAS path $NAS_TARGET not available (share not mounted?): $(ls "$NAS_TARGET" 2>&1 | tail -n 1)"
  elif [[ "$(stat -c %d "$NAS_TARGET")" == "$(stat -c %d "$OUT_ROOT")" ]]; then
    fail "NAS path $NAS_TARGET is on the same disk as the outbox: the share is not mounted"
  elif [[ ! -w "$NAS_TARGET" ]]; then
    fail "NAS path $NAS_TARGET is mounted but not writable"
  else
    pass "NAS path $NAS_TARGET mounted and writable"
  fi
elif [[ "$NAS_TARGET" != *:* ]]; then
  fail "NAS_TARGET '$NAS_TARGET' is not user@host:/path"
else
  NAS_HOST="${NAS_TARGET%%:*}"; NAS_PATH="${NAS_TARGET#*:}"
  T0=$(date +%s.%N)
  OUT="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$NAS_HOST" "test -d '$NAS_PATH' && test -w '$NAS_PATH' && echo writable" 2>&1)"; RC=$?
  T1=$(date +%s.%N)
  MS="$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%d", (b-a)*1000}')"
  if (( RC == 0 )) && [[ "$OUT" == *writable* ]]; then
    pass "NAS $NAS_HOST reachable by key, $NAS_PATH writable (${MS} ms)"
  elif (( RC != 255 )); then   # ssh itself exits 255; anything else is the remote test failing
    fail "NAS reachable but $NAS_PATH is missing or not writable"
  else
    fail "NAS $NAS_HOST not usable (rc=$RC): $(tail -n 1 <<<"$OUT")"
  fi
  # No probe file is written: it would look like a fresh frame to the Home Assistant stale-file alert.
fi

head_ "Recent activity"
if [[ -s "$LOG_FILE" ]]; then
  info "last capture log line: $(tail -n 1 "$LOG_FILE")"
else
  info "no capture log yet ($LOG_FILE)"
fi
have systemctl && info "timers: $(systemctl list-timers 'sunset*' --no-legend 2>/dev/null | awk '{print $NF}' | tr '\n' ' ')"

printf '\nResult: %d pass, %d warn, %d fail\n' "$NPASS" "$NWARN" "$NFAIL"
(( NFAIL == 0 ))
