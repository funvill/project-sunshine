# Sync hardening (issues #13, #27): --fsync only when rsync has it, zero-length images, no inert
# ssh option for a local target, oldest-first batches, a TERM trap, and sync.log rotation.
# Uses the rsync stub, which records its arguments and each file list in $STUB_CALLS.
mkfile() { # mkfile <path> <age> [content]; creates parent dirs
  mkdir -p "$(dirname "$1")"; printf '%s' "${3-data}" > "$1"; touch -d "$2" "$1"
}
rsync_calls() { grep "^rsync " "$STUB_CALLS" 2>/dev/null; }
nas_has() { test -e "$W/nas/$1"; }
no_ssh_opt() { grep -q '^rsync ' "$STUB_CALLS" && ! grep -q -- ' -e ' "$STUB_CALLS"; }
no_fsync() { grep -q '^rsync ' "$STUB_CALLS" && ! grep -q -- '--fsync' "$STUB_CALLS"; }
has_fsync() { grep '^rsync ' "$STUB_CALLS" | grep -q -- ' --fsync'; }
# The stub copies into a local target, so the share is the folder the checks look in.
share_target() { export NAS_TARGET="$W/nas/"; mkdir -p "$NAS_TARGET"; }

section "sync: --fsync only when rsync supports it"
fresh_env; share_target
mkfile "$OUT_ROOT/wide/2026/01/01/a.jpg" '10 minutes ago'
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "rsync with --fsync support gets --fsync" has_fsync
fresh_env; share_target; export STUB_RSYNC_NOFSYNC=1
mkfile "$OUT_ROOT/wide/2026/01/01/a.jpg" '10 minutes ago'
sync_; rc=$?
check "exits 0 without --fsync support" test "$rc" = 0
check "frame still shipped" nas_has wide/2026/01/01/a.jpg
check "older rsync is not given --fsync" no_fsync
unset STUB_RSYNC_NOFSYNC

section "sync: ssh option only for a remote target"
fresh_env; share_target
mkfile "$OUT_ROOT/wide/2026/01/01/a.jpg" '10 minutes ago'
sync_
check "mounted share: rsync ran, with no -e ssh" no_ssh_opt
fresh_env; export NAS_TARGET="sunset@nas.example:/volume1/x/"
mkfile "$OUT_ROOT/wide/2026/01/01/a.jpg" '10 minutes ago'
sync_; rc=$?
check "remote target still works" test "$rc" = 0
check "remote target: -e ssh with BatchMode" bash -c "grep '^rsync ' '$STUB_CALLS' | grep -q -- '-e ssh -o BatchMode=yes'"
check "remote target: target passed through" bash -c "grep '^rsync ' '$STUB_CALLS' | grep -q 'sunset@nas.example:/volume1/x/'"

section "sync: zero-length images are skipped, kept, and logged once"
fresh_env; share_target
d="$OUT_ROOT/wide/2026/01/01"
mkfile "$d/a.jpg" '10 minutes ago' ""        # empty JPEG: a power cut's leftover
mkfile "$d/a.dng" '10 minutes ago' ""        # empty DNG
mkfile "$d/a.json" '10 minutes ago' ""       # an empty JSON is not an image: ships as before
mkfile "$d/b.jpg" '10 minutes ago' "pixels"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "good image shipped" nas_has wide/2026/01/01/b.jpg
check "empty JPEG not shipped" test ! -e "$W/nas/wide/2026/01/01/a.jpg"
check "empty DNG not shipped" test ! -e "$W/nas/wide/2026/01/01/a.dng"
check "empty JPEG kept on the card" test -e "$d/a.jpg"
check "empty DNG kept on the card" test -e "$d/a.dng"
check "non-image empty file ships" nas_has wide/2026/01/01/a.json
check "skip logged for the JPEG" grep -q 'zero-length image ./wide/2026/01/01/a.jpg' "$SYNC_LOG_FILE"
check "skip logged for the DNG" grep -q 'zero-length image ./wide/2026/01/01/a.dng' "$SYNC_LOG_FILE"
check "sync ok counts only what shipped" grep -q 'sync ok files=2' "$SYNC_LOG_FILE"
sync_
check "second run does not log them again" test "$(grep -c 'zero-length image' "$SYNC_LOG_FILE")" = 2
sync_; rc=$?
check "third run, nothing to ship, exits 0" test "$rc" = 0
fresh_env; share_target
mkfile "$OUT_ROOT/wide/2026/01/01/only.jpg" '10 minutes ago' ""
sync_; rc=$?
check "only an empty image: exits 0" test "$rc" = 0
check "only an empty image: rsync not run" test "$(rsync_calls | wc -l | tr -d ' ')" = 0

section "sync: oldest files first, in batches"
fresh_env; share_target; export SYNC_BATCH=1
# Name order (camA before camB) is not time order: x is the oldest.
mkfile "$OUT_ROOT/camB/2026/01/01/x.jpg" '30 minutes ago'
mkfile "$OUT_ROOT/camA/2026/01/01/y.jpg" '20 minutes ago'
mkfile "$OUT_ROOT/camA/2026/01/01/z.jpg" '10 minutes ago'
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "one rsync run per batch" test "$(rsync_calls | wc -l | tr -d ' ')" = 3
check "oldest first" test "$(grep '^list:' "$STUB_CALLS" | tr '\n' ' ')" = "list: ./camB/2026/01/01/x.jpg list: ./camA/2026/01/01/y.jpg list: ./camA/2026/01/01/z.jpg "
check "all shipped" test "$(find "$W/nas" -type f | wc -l | tr -d ' ')" = 3
check "ok line counts every file" grep -q 'sync ok files=3' "$SYNC_LOG_FILE"
unset SYNC_BATCH
fresh_env; share_target; export SYNC_BATCH=2
for i in 1 2 3 4 5; do mkfile "$OUT_ROOT/wide/2026/01/01/f$i.jpg" "$((60 - i)) minutes ago"; done
export STUB_RSYNC=ok; sync_
check "5 files in batches of 2 is 3 runs" test "$(rsync_calls | wc -l | tr -d ' ')" = 3
check "5 files all shipped" test "$(find "$W/nas" -type f | wc -l | tr -d ' ')" = 5
unset SYNC_BATCH

section "sync: a hard failure stops after the first batch and keeps every frame"
fresh_env; share_target; export SYNC_BATCH=1 STUB_RSYNC=fail
mkfile "$OUT_ROOT/wide/2026/01/01/a.jpg" '30 minutes ago'
mkfile "$OUT_ROOT/wide/2026/01/01/b.jpg" '20 minutes ago'
sync_; rc=$?
check "exits with rsync's code" test "$rc" = 255
check "stopped at the first batch" test "$(rsync_calls | wc -l | tr -d ' ')" = 1
check "logged in the old format" grep -q 'sync FAILED rc=255 pending=2 err=' "$SYNC_LOG_FILE"
check "frames kept" test "$(count '*.jpg')" = 2
unset SYNC_BATCH; export STUB_RSYNC=ok

section "sync: TERM logs what was pending"
fresh_env; share_target; export STUB_RSYNC=hang STUB_RSYNC_PID="$W/rsync.pid"
for i in 1 2 3; do mkfile "$OUT_ROOT/wide/2026/01/01/f$i.jpg" '10 minutes ago'; done
bash "$SRC/sunset-sync.sh" & sp=$!
for _ in $(seq 1 50); do [[ -s "$W/rsync.pid" ]] && break; sleep 0.1; done
check "transfer is running" test -s "$W/rsync.pid"
kill -TERM "$sp" "$(cat "$W/rsync.pid" 2>/dev/null)" 2>/dev/null
wait "$sp"; rc=$?
check "exits 143" test "$rc" = 143
check "interrupted logged with the pending count" grep -q 'sync interrupted pending=3' "$SYNC_LOG_FILE"
check "frames still local" test "$(count '*.jpg')" = 3
unset STUB_RSYNC_PID; export STUB_RSYNC=ok

section "sync: sync.log rotates by size"
# The config backup (#23) is off here: its own log lines would rotate the log a second time.
fresh_env; share_target; export SYNC_LOG_MAX_BYTES=200 SYNC_CONFIG_BACKUP=0
head -c 300 /dev/zero | tr '\0' 'x' > "$SYNC_LOG_FILE"
mkfile "$OUT_ROOT/wide/2026/01/01/a.jpg" '10 minutes ago'
sync_
check "old log moved to sync.log.1" test "$(wc -c < "$SYNC_LOG_FILE.1" | tr -d ' ')" = 300
check "new log is small and has the entry" grep -q 'sync ok files=1' "$SYNC_LOG_FILE"
check "new log is under the cap" test "$(wc -c < "$SYNC_LOG_FILE" | tr -d ' ')" -lt 200
unset SYNC_LOG_MAX_BYTES SYNC_CONFIG_BACKUP
