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
# A batch also closes at this many MB (a bigger file still goes, on its own), so on a slow link
# each batch is read back and its files deleted within minutes. 0: no size cap.
BATCH_MB="${SYNC_BATCH_MB:-32}"
# Stop starting new batches after this many seconds and leave the rest for the next run (logged
# as "sync partial"), well before the unit's TimeoutStartSec kills it mid-batch. 0: no limit.
MAX_S="${SYNC_MAX_S:-1200}"
# Read-back before delete (issue #13), mounted share only. 1: a local file is deleted only after
# its NAS copy has been read back and matches; 0: trust rsync's exit code, as before.
VERIFY="${SYNC_VERIFY:-1}"
# Files up to this size are re-read from the NAS in full and compared by SHA-256 (JPEG, JSON).
# Larger ones get the size check only. 0: no full re-reads.
HASH_MAX_MB="${SYNC_VERIFY_HASH_MAX_MB:-8}"
# Config backup (issue #23), mounted share only: sunset.env, fstab and the boot config.txt
# go to a per-host folder next to the frames' folder, when they change and once a UTC day.
CONFIG_BACKUP="${SYNC_CONFIG_BACKUP:-1}"
CONFIG_ENV="${SYNC_CONFIG_ENV:-$(dirname "$OUT_ROOT")/sunset.env}"
CONFIG_ROOT="${SYNC_CONFIG_ROOT:-}"              # prefix for /etc and /boot (tests use a fixture)
CONFIG_DIR="${SYNC_CONFIG_DIR:-$(dirname "${NAS_TARGET%/}")/project_sunshine_config/$(hostname 2>/dev/null || uname -n)}"
CONFIG_STAMP="$LOG_FILE.config"                  # UTC day + hash of what was last backed up
# UPS log (issue #29), mounted share only, with the config backup: ups.log and its rotated files,
# written by sunset-ups.py on the CM4, go to <config folder>/ups/ as ups-<first line's UTC>.log.
UPS_LOG="${SYNC_UPS_LOG:-$(dirname "$OUT_ROOT")/ups.log}"
UPS_DIR="${SYNC_UPS_DIR:-$CONFIG_DIR/ups}"

# Same approach as sunset-kernlog.sh: one old file kept, so the log stays under about 2x the cap.
log() {
  if [[ -f "$LOG_FILE" ]] && (( $(wc -c < "$LOG_FILE" 2>/dev/null || echo 0) >= LOG_MAX_BYTES )); then
    mv -f "$LOG_FILE" "$LOG_FILE.1" 2>/dev/null || true
  fi
  echo "$(date -u +%FT%TZ) $*" >> "$LOG_FILE" 2>/dev/null || true
}

# A mounted share (NAS_TARGET=/mnt/...): if the mount is missing, that path is just a
# directory on the SD card, and rsync would "succeed" and the local copies would be deleted.
# Prints why the share is unusable, or nothing when it is fine.
share_problem() {
  if [[ ! -d "$NAS_TARGET" ]]; then
    echo "$NAS_TARGET not available (share not mounted?)"
  elif [[ "$(stat -c %d "$NAS_TARGET")" == "$(stat -c %d "$OUT_ROOT")" ]]; then
    echo "$NAS_TARGET is on the same disk as the outbox (share not mounted?)"
  fi
}

# Copy the Pi's live config to the share (issue #23). Cheap: the sources are hashed locally and
# compared with a stamp, so the share is written only when something changed or on a new UTC day.
# Never logs file contents (sunset.env holds the real site coordinates), never copies a
# credential file or any file with a password in it. A failure is logged and does not fail the sync.
backup_config() {
  [[ "$CONFIG_BACKUP" == 1 && "$NAS_TARGET" == /* ]] || return 0
  local boot="$CONFIG_ROOT/boot/firmware/config.txt"
  [[ -f "$boot" ]] || boot="$CONFIG_ROOT/boot/config.txt"
  local srcs=("$CONFIG_ENV" "$CONFIG_ROOT/etc/fstab" "$boot") names=(sunset.env fstab config.txt)
  local i src state="$CONFIG_DIR" copied="" failed=0
  for src in "${srcs[@]}"; do
    if [[ -f "$src" && -r "$src" ]]; then state+=" $(sha256sum < "$src" 2>/dev/null || echo unreadable)"
    else state+=" missing"; fi
  done
  state="$(date -u +%F) $(printf '%s' "$state" | sha256sum | cut -d' ' -f1)"
  [[ "$(cat "$CONFIG_STAMP" 2>/dev/null)" == "$state" ]] && return 0
  if ! mkdir -p "$CONFIG_DIR" 2>/dev/null; then
    log "config backup FAILED: cannot create $CONFIG_DIR"
    return 0
  fi
  for i in "${!srcs[@]}"; do
    src="${srcs[$i]}"
    if [[ "$src" == *.cred || "$src" == */sunset-nas.cred* ]]; then
      log "config backup skipped $src: a credential file"
    elif [[ ! -f "$src" || ! -r "$src" ]]; then
      log "config backup: $src missing"
    elif grep -Eiq '(password|passwd|pass|secret|token)[a-z0-9_]*[[:space:]]*=' "$src" 2>/dev/null; then
      log "config backup skipped $src: it holds a password"
    elif cp "$src" "$CONFIG_DIR/.${names[$i]}.tmp" 2>/dev/null &&
         mv -f "$CONFIG_DIR/.${names[$i]}.tmp" "$CONFIG_DIR/${names[$i]}" 2>/dev/null; then
      copied+="${copied:+,}${names[$i]}"
    else
      rm -f "$CONFIG_DIR/.${names[$i]}.tmp" 2>/dev/null || true
      failed=1
    fi
  done
  if (( failed )); then
    log "config backup FAILED dir=$CONFIG_DIR copied=${copied:-none}"
    return 0
  fi
  echo "$state" > "$CONFIG_STAMP" 2>/dev/null || true
  log "config backup ok dir=$CONFIG_DIR files=${copied:-none}"
}

# Copy the UPS log to the share (issue #29). A rotated file keeps its first line, so each file has
# one name on the share for life, and a copy is made only when its size there differs: the live
# file whenever the monitor has written to it, a rotated one once. Nothing is written on the Pi,
# and nothing is done on a Pi without a UPS log. A failure is logged and does not fail the sync.
backup_ups_log() {
  [[ "$CONFIG_BACKUP" == 1 && "$NAS_TARGET" == /* ]] || return 0
  local f first ts dst copied=0 failed=0
  for f in "$UPS_LOG" "$UPS_LOG".[0-9] "$UPS_LOG".[0-9][0-9]; do
    [[ -f "$f" && -r "$f" && -s "$f" ]] || continue
    IFS= read -r first < "$f" || true
    ts="${first%% *}"
    [[ "$ts" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || continue
    dst="$UPS_DIR/ups-${ts//[-:]/}.log"
    [[ "$(stat -c %s "$dst" 2>/dev/null)" == "$(stat -c %s "$f" 2>/dev/null)" ]] && continue
    if mkdir -p "$UPS_DIR" 2>/dev/null && cp "$f" "$dst.tmp" 2>/dev/null && mv -f "$dst.tmp" "$dst" 2>/dev/null; then
      copied=$((copied + 1))
    else
      rm -f "$dst.tmp" 2>/dev/null || true
      failed=$((failed + 1))
    fi
  done
  if (( failed )); then log "ups log backup FAILED dir=$UPS_DIR copied=$copied failed=$failed"
  elif (( copied )); then log "ups log backup ok dir=$UPS_DIR files=$copied"; fi
  return 0
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
  if [[ "$size" == 0 && "$path" == *.[jJ][pP][gG] ]]; then
    if ! grep -qxF -- "$path" "$ZERO_SEEN" 2>/dev/null; then
      echo "$path" >> "$ZERO_SEEN" 2>/dev/null || true
      log "sync skipped zero-length image $path"
    fi
    continue
  fi
  # An empty system.json is the same kind of leftover. The next frame's sunset-meta.py rewrites it
  # from its state file, and the sync sends it then. Other empty files (a frame's JSON) ship as before.
  if [[ "$size" == 0 && "$path" == */system.json ]]; then
    if ! grep -qxF -- "$path" "$ZERO_SEEN" 2>/dev/null; then
      echo "$path" >> "$ZERO_SEEN" 2>/dev/null || true
      log "sync skipped zero-length system.json $path"
    fi
    continue
  fi
  printf '%s\0' "$path" >> "$LIST"
  PENDING=$((PENDING + 1))
done < "$ALL"
if (( PENDING == 0 )); then
  # Nothing to send; still keep the config backup current, but quietly skip it if the share is
  # not there (no failure line every few minutes for a run that had nothing to do).
  if [[ "$NAS_TARGET" == /* && -z "$(share_problem)" ]]; then backup_config || true; backup_ups_log || true; fi
  exit 0
fi
REMAINING="$PENDING"

# Only sync to a mounted share when the target exists already and is on a different
# filesystem from the outbox.
if [[ "$NAS_TARGET" == /* ]]; then
  problem="$(share_problem)"
  if [[ -n "$problem" ]]; then
    log "sync FAILED: $problem pending=$PENDING"
    exit 1
  fi
  backup_config || true
  backup_ups_log || true
fi

# -rt, not -a: the NAS user usually cannot set owner/group/perms, and a failed
# chown makes rsync exit 23 even though the data arrived.
OPTS=(-rt --from0 --timeout=120)
# Who deletes the local copy. rsync's --remove-source-files deletes once its whole-file checksum
# matches, but on the CIFS mount that checksum covers the bytes rsync handed to the kernel, not
# what the NAS stored. So on a mounted share the read-back below deletes, after reading the NAS
# copy back. Over SSH the receiving rsync writes to the NAS's own disk, and rsync deletes as before.
READBACK=0
if [[ "$NAS_TARGET" == /* && "$VERIFY" == 1 ]]; then
  READBACK=1
else
  OPTS+=(--remove-source-files)
fi
# --fsync (rsync 3.2.4+) makes the receiver flush each file before it counts as done; matters
# on the CIFS mount, where "written" only means "handed to the NAS". Older rsync rejects it.
HELP="$(rsync --help 2>&1 || true)"
[[ "$HELP" == *--fsync* ]] && OPTS+=(--fsync)
# ssh only means something for user@host:/path; a local path or a mounted share has no remote shell.
if [[ "$NAS_TARGET" != /* && "$NAS_TARGET" == *:* ]]; then
  OPTS+=(-e "ssh -o BatchMode=yes -o ConnectTimeout=15")
fi

# Read back each file of the batch from the share and delete the local copy only if it matches:
# same size, and for files up to HASH_MAX_MB the same SHA-256 of the whole file. The NAS copy's
# pages are dropped from the Pi's cache first, so the read goes to the NAS rather than to what
# this Pi just wrote. A file that fails stays on the Pi, its bad NAS copy is removed (otherwise
# rsync would see the same size and time next run and skip it), and the next run sends it again. $1 is rsync's exit code for the batch: a file that
# is simply absent after a partial failure (23/24) is already covered by the FAILED line.
CONFIRMED=0
KEPT=0
drop_cache() { dd if="$1" iflag=nocache count=0 status=none 2>/dev/null || true; }
sha_of() { local h; h="$(sha256sum < "$1" 2>/dev/null)" || h=unreadable; echo "${h%% *}"; }
readback_batch() {
  local p dst ls ns why
  while IFS= read -r -d '' p; do
    [[ -f "$p" ]] || continue
    dst="${NAS_TARGET%/}/${p#./}"
    if [[ ! -f "$dst" ]]; then
      KEPT=$((KEPT + 1))
      [[ "$1" != 0 ]] || log "readback kept $p: not on the NAS"
      continue
    fi
    why=""
    drop_cache "$dst"
    ls="$(wc -c < "$p" 2>/dev/null)" || ls=-1
    ns="$(wc -c < "$dst" 2>/dev/null)" || ns=-1
    if [[ "$ls" != "$ns" ]]; then
      why="size $ls on the Pi, $ns on the NAS"
    elif (( HASH_MAX_MB > 0 && ls <= HASH_MAX_MB * 1048576 )); then
      [[ "$(sha_of "$p")" == "$(sha_of "$dst")" ]] || why="sha256 differs"
    fi
    if [[ -n "$why" ]]; then
      KEPT=$((KEPT + 1))
      log "readback kept $p: $why (bad NAS copy removed, resent next run)"
      rm -f "$dst" 2>/dev/null || true
      continue
    fi
    rm -f "$p"
    CONFIRMED=$((CONFIRMED + 1))
  done < "$LIST.batch"
}

# Send in batches of the oldest files. rsync sorts a file list by name on its own, so batching
# is what makes "oldest first" real. A hard failure (rc 255, link gone) stops here; a partial
# one (rc 23/24: some files unreadable or vanished) goes on with the next batch.
# A batch is the oldest files up to BATCH files or BATCH_MB, whichever comes first, and always
# at least one file. Sets N.
make_batch() {
  local p s bytes=0 cap=$(( BATCH_MB * 1048576 ))
  N=0
  : > "$LIST.batch"
  while IFS= read -r -d '' p; do
    s="$(wc -c < "$p" 2>/dev/null)" || s=0
    if (( N > 0 && (N >= BATCH || (cap > 0 && bytes + s > cap)) )); then break; fi
    printf '%s\0' "$p" >> "$LIST.batch"
    N=$((N + 1)); bytes=$((bytes + s))
  done < "$LIST"
}

RC=0
FAILED_RC=0
SECONDS=0
BATCHES=0
while (( REMAINING > 0 )); do
  # Out of time: stop here, between batches, so nothing is cut off mid-transfer. At least one
  # batch per run, so a run always moves something. The next timer run carries on.
  if (( MAX_S > 0 && SECONDS >= MAX_S && BATCHES > 0 )); then
    log "sync partial confirmed=$CONFIRMED pending=$REMAINING kept=$KEPT"
    (( FAILED_RC == 0 )) || exit "$FAILED_RC"
    (( KEPT == 0 )) || exit 1
    exit 0
  fi
  BATCHES=$((BATCHES + 1))
  make_batch
  BATCH_RC=0
  if rsync "${OPTS[@]}" --files-from="$LIST.batch" ./ "$NAS_TARGET" 2>"$ERR"; then
    :
  else
    RC=$?
    BATCH_RC="$RC"
    (( FAILED_RC )) || FAILED_RC="$RC"
    log "sync FAILED rc=$RC pending=$PENDING err=$(tail -n 2 "$ERR" | tr '\n' '|')"
    [[ "$RC" == 23 || "$RC" == 24 ]] || { rm -f "$LIST.batch"; exit "$RC"; }
  fi
  if (( READBACK )); then readback_batch "$BATCH_RC"
  elif [[ "$BATCH_RC" == 0 ]]; then CONFIRMED=$((CONFIRMED + N)); fi   # rsync deleted them itself
  tail -z -n +$((N + 1)) "$LIST" > "$LIST.rest"
  mv -f "$LIST.rest" "$LIST"
  REMAINING=$((REMAINING - N))
  rm -f "$LIST.batch"
done
(( FAILED_RC == 0 )) || exit "$FAILED_RC"
if (( KEPT > 0 )); then
  log "sync FAILED read-back kept=$KEPT confirmed=$CONFIRMED"
  exit 1
fi
log "sync ok files=$PENDING"

# Prune empty day directories, but not brand-new ones: a capture may have just
# created today's directory and be about to move its frame into it.
find "$OUT_ROOT" -mindepth 1 -type d -empty -mmin +10 -not -path "$OUT_ROOT/.*" -delete
