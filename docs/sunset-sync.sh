#!/usr/bin/env bash
# Move captured frames to the NAS; delete locally only after a confirmed copy.
# If the NAS is down, frames pile up locally and catch up on the next run.
set -euo pipefail

OUT_ROOT="${OUT_ROOT:-/home/pi/sunset/outbox}"
NAS_TARGET="${NAS_TARGET:-sunset@nas.local:/volume1/project-sunset/}"   # edit in sunset.env
LIST="$(mktemp)"
trap 'rm -f "$LIST"' EXIT

# Skip files modified in the last 2 minutes (a capture may still be writing).
cd "$OUT_ROOT"
find . -type f -mmin +2 -print0 > "$LIST"
[[ -s "$LIST" ]] || exit 0

rsync -a --from0 --files-from="$LIST" --remove-source-files \
  --timeout=120 -e "ssh -o BatchMode=yes -o ConnectTimeout=15" \
  ./ "$NAS_TARGET"

find "$OUT_ROOT" -mindepth 1 -type d -empty -delete
