#!/usr/bin/env bash
# Move captured frames to the NAS; delete locally only after a confirmed copy.
# If the NAS is down, frames pile up locally and catch up on the next run.
set -euo pipefail

OUT_ROOT="${OUT_ROOT:-$HOME/sunset/outbox}"
NAS_TARGET="${NAS_TARGET:-sunset@nas.local:/volume1/project-sunset/}"   # edit in sunset.env
LOG_FILE="${SYNC_LOG_FILE:-$(dirname "$OUT_ROOT")/sync.log}"
LOCK_FILE="${SYNC_LOCK_FILE:-$(dirname "$OUT_ROOT")/.sunset-sync.lock}"
LOG_MAX_BYTES="${SYNC_LOG_MAX_BYTES:-1048576}"   # rotate sync.log to sync.log.1 at this size
BATCH="${SYNC_BATCH:-200}"                       # files per rsync run, oldest first

# Same approach as sunset-kernlog.sh: one old file kept, so the log stays under about 2x the cap.
log() {
  if [[ -f "$LOG_FILE" ]] && (( $(wc -c < "$LOG_FILE" 2>/dev/null || echo 0) >= LOG_MAX_BYTES )); then
    mv -f "$LOG_FILE" "$LOG_FILE.1" 2>/dev/null || true
  fi
  echo "$(date -u +%FT%TZ) $*" >> "$LOG_FILE" 2>/dev/null || true
}

# First boot: the sync timer can fire before the first capture has created the outbox.
[[ -d "$OUT_ROOT" ]] || exit 0

# One sync at a time (a manual run must not overlap the timer).
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || { log "sync skipped: another sync is running"; exit 0; }
fi

ALL="$(mktemp)"
LIST="$(mktemp)"
ERR="$(mktemp)"
trap 'rm -f "$ALL" "$LIST" "$ERR" "$LIST.batch" "$LIST.rest"' EXIT
REMAINING=0
# systemd sends TERM when the unit times out (a long backlog on a slow link). Say so, and how
# much was left; the files already confirmed are gone from the outbox, the rest go next run.
trap 'log "sync interrupted pending=$REMAINING"; exit 143' TERM

# Skip files modified in the last 2 minutes (a capture may still be writing), and
# anything under a dot-directory (.partial holds captures that are not finished).
# Oldest first, so a sync that is cut short has moved the files that have waited longest.
cd "$OUT_ROOT"
find . -type f -mmin +2 -not -path './.*' -printf '%T@ %s %p\0' | sort -z -n > "$ALL"

# A zero-length image is a file a power cut left behind (the filesystem committed the name but
# not the data). Do not ship it, and do not delete it either: it stays on the card. Each name
# is logged once.
ZERO_SEEN="$LOG_FILE.zero"
: > "$LIST"
PENDING=0
while IFS= read -r -d '' rec; do
  rest="${rec#* }"; size="${rest%% *}"; path="${rest#* }"
  if [[ "$size" == 0 ]] && [[ "$path" == *.[jJ][pP][gG] || "$path" == *.[dD][nN][gG] ]]; then
    if ! grep -qxF -- "$path" "$ZERO_SEEN" 2>/dev/null; then
      echo "$path" >> "$ZERO_SEEN" 2>/dev/null || true
      log "sync skipped zero-length image $path"
    fi
    continue
  fi
  printf '%s\0' "$path" >> "$LIST"
  PENDING=$((PENDING + 1))
done < "$ALL"
if (( PENDING == 0 )); then
  exit 0
fi
REMAINING="$PENDING"

# A mounted share (NAS_TARGET=/mnt/...): if the mount is missing, that path is just a
# directory on the SD card, and rsync would "succeed" and delete the local copies. Only
# sync when the target exists already and is on a different filesystem from the outbox.
if [[ "$NAS_TARGET" == /* ]]; then
  if [[ ! -d "$NAS_TARGET" ]]; then
    log "sync FAILED: $NAS_TARGET not available (share not mounted?) pending=$PENDING"
    exit 1
  fi
  if [[ "$(stat -c %d "$NAS_TARGET")" == "$(stat -c %d "$OUT_ROOT")" ]]; then
    log "sync FAILED: $NAS_TARGET is on the same disk as the outbox (share not mounted?) pending=$PENDING"
    exit 1
  fi
fi

# -rt, not -a: the NAS user usually cannot set owner/group/perms, and a failed
# chown makes rsync exit 23 even though the data arrived.
# --remove-source-files only removes a file after rsync has transferred it and
# verified it with its whole-file checksum, so a failed copy is never deleted.
OPTS=(-rt --from0 --remove-source-files --timeout=120)
# --fsync (rsync 3.2.4+) makes the receiver flush each file before it counts as done; matters
# on the CIFS mount, where "written" only means "handed to the NAS". Older rsync rejects it.
HELP="$(rsync --help 2>&1 || true)"
[[ "$HELP" == *--fsync* ]] && OPTS+=(--fsync)
# ssh only means something for user@host:/path; a local path or a mounted share has no remote shell.
if [[ "$NAS_TARGET" != /* && "$NAS_TARGET" == *:* ]]; then
  OPTS+=(-e "ssh -o BatchMode=yes -o ConnectTimeout=15")
fi

# Send in batches of the oldest files. rsync sorts a file list by name on its own, so batching
# is what makes "oldest first" real. A hard failure (rc 255, link gone) stops here; a partial
# one (rc 23/24: some files unreadable or vanished) goes on with the next batch.
RC=0
FAILED_RC=0
while (( REMAINING > 0 )); do
  head -z -n "$BATCH" "$LIST" > "$LIST.batch"
  N="$(tr -cd '\0' < "$LIST.batch" | wc -c)"
  if rsync "${OPTS[@]}" --files-from="$LIST.batch" ./ "$NAS_TARGET" 2>"$ERR"; then
    :
  else
    RC=$?
    (( FAILED_RC )) || FAILED_RC="$RC"
    log "sync FAILED rc=$RC pending=$PENDING err=$(tail -n 2 "$ERR" | tr '\n' '|')"
    [[ "$RC" == 23 || "$RC" == 24 ]] || { rm -f "$LIST.batch"; exit "$RC"; }
  fi
  tail -z -n +$((N + 1)) "$LIST" > "$LIST.rest"
  mv -f "$LIST.rest" "$LIST"
  REMAINING=$((REMAINING - N))
  rm -f "$LIST.batch"
done
(( FAILED_RC == 0 )) || exit "$FAILED_RC"
log "sync ok files=$PENDING"

# Prune empty day directories, but not brand-new ones: a capture may have just
# created today's directory and be about to move its frame into it.
find "$OUT_ROOT" -mindepth 1 -type d -empty -mmin +10 -not -path "$OUT_ROOT/.*" -delete
