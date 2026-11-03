#!/usr/bin/env bash
# Project Sunset - single capture for Pi Zero W + IMX477 (Pi HQ / Arducam UC-517)
# Captures locally first; sunset-sync.sh moves frames to the NAS.
set -euo pipefail

CAM_NAME="${CAM_NAME:-wide}"                     # wide | tight
OUT_ROOT="${OUT_ROOT:-/home/pi/sunset/outbox}"
NIGHT_LUX="${NIGHT_LUX:-5}"                       # below this lux, add a long exposure
NIGHT_SHUTTER_US="${NIGHT_SHUTTER_US:-8000000}"   # 8 s
NIGHT_GAIN="${NIGHT_GAIN:-4}"
SAVE_RAW="${SAVE_RAW:-1}"                         # 1 = also save DNG

TS="$(date -u +%Y%m%dT%H%M%SZ)"                   # UTC: no DST gaps or duplicates
DAY_DIR="$OUT_ROOT/$CAM_NAME/$(date -u +%Y/%m/%d)"
mkdir -p "$DAY_DIR"
BASE="$DAY_DIR/${CAM_NAME}_${TS}"

RAW_ARGS=()
[[ "$SAVE_RAW" == "1" ]] && RAW_ARGS=(--raw)

# 1) Auto-exposure shot; -t gives AE/AWB time to settle on the slow Zero.
rpicam-still -n -t 3000 "${RAW_ARGS[@]}" \
  --metadata "$BASE.json" --metadata-format json \
  -o "$BASE.jpg"

# 2) Read the scene lux the camera reported.
LUX="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("Lux",9999))' "$BASE.json")"

# 3) Too dark? Add a fixed long exposure (Pi auto-exposure underexposes at night).
if python3 -c 'import sys;sys.exit(0 if float(sys.argv[1])<float(sys.argv[2]) else 1)' "$LUX" "$NIGHT_LUX"; then
  rpicam-still -n -t 1000 "${RAW_ARGS[@]}" \
    --shutter "$NIGHT_SHUTTER_US" --gain "$NIGHT_GAIN" --awbgains 1.6,1.8 \
    --metadata "${BASE}_night.json" --metadata-format json \
    -o "${BASE}_night.jpg"
fi

# 4) Log SoC temperature and capture status for the long-term data layer.
TEMP="$(vcgencmd measure_temp 2>/dev/null | cut -d= -f2 || echo na)"
echo "$(date -u +%FT%TZ) cam=$CAM_NAME lux=$LUX soc=$TEMP ok" >> "$OUT_ROOT/../capture.log"
