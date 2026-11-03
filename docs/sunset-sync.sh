#!/usr/bin/env bash
# Move captured frames to the NAS; delete locally only after a confirmed copy.
# If the NAS is down, frames pile up locally and catch up on the next run.
set -euo pipefail

OUT_ROOT="${OUT_ROOT:-$HOME/sunset/outbox}"
NAS_TARGET="${NAS_TARGET:-sunset@nas.local:/volume1/project-sunset/}"   # edit in sunset.env
LOG_FILE="${SYNC_LOG_FILE:-$(dirname "$OUT_ROOT")/sync.log}"
LOCK_FILE="${SYNC_LOCK_FILE:-$(dirname "$OUT_ROOT")/.sunset-sync.lock}"

log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG_FILE" 2>/dev/null || true; }

# First boot: the sync timer can fire before the first capture has created the outbox.
[[ -d "$OUT_ROOT" ]] || exit 0

# One sync at a time (a manual run must not overlap the timer).
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || { log "sync skipped: another sync is running"; exit 0; }
fi

LIST="$(mktemp)"
ERR="$(mktemp)"
trap 'rm -f "$LIST" "$ERR"' EXIT

# Skip files modified in the last 2 minutes (a capture may still be writing), and
# anything under a dot-directory (.partial holds captures that are not finished).
cd "$OUT_ROOT"
find . -type f -mmin +2 -not -path './.*' -print0 > "$LIST"
if [[ ! -s "$LIST" ]]; then
  exit 0
fi
PENDING="$(tr -cd '\0' < "$LIST" | wc -c)"

# -rt, not -a: the NAS user usually cannot set owner/group/perms, and a failed
# chown makes rsync exit 23 even though the data arrived.
# --remove-source-files only removes a file after rsync has transferred it and
# verified it with its whole-file checksum, so a failed copy is never deleted.
if rsync -rt --from0 --files-from="$LIST" --remove-source-files \
     --timeout=120 -e "ssh -o BatchMode=yes -o ConnectTimeout=15" \
     ./ "$NAS_TARGET" 2>"$ERR"; then
  log "sync ok files=$PENDING"
else
  RC=$?
  log "sync FAILED rc=$RC pending=$PENDING err=$(tail -n 2 "$ERR" | tr '\n' '|')"
  exit "$RC"
fi

# Prune empty day directories, but not brand-new ones: a capture may have just
# created today's directory and be about to move its frame into it.
find "$OUT_ROOT" -mindepth 1 -type d -empty -mmin +10 -not -path "$OUT_ROOT/.*" -delete
