# needs: 51_sync_hardening
# Sync pacing on a slow link (CM4 on 2.4 Mbit/s Wi-Fi, 2026-11-17): the evening bracket left a
# backlog that each run spent its 30 minutes uploading, killed by systemd before any read-back,
# so nothing was confirmed or deleted for hours. Batches are now capped by size as well as by
# count, so each batch is read back and deleted within minutes, and the run stops itself
# between batches at SYNC_MAX_S, before systemd's limit. Uses mkfile and share_target from 51.
big_file() { # big_file <path> <age> <KB>
  mkdir -p "$(dirname "$1")"; head -c "$(( $3 * 1024 ))" /dev/zero | tr '\0' 'p' > "$1"; touch -d "$2" "$1"
}
pace_env() {
  fresh_env; share_target
  unset SYNC_BATCH SYNC_BATCH_MB SYNC_MAX_S STUB_RSYNC_SLEEP
  export SYNC_CONFIG_BACKUP=0
  d="$OUT_ROOT/cm4wide/2026/01/01"
}

section "sync pacing: a batch closes at SYNC_BATCH_MB"
pace_env; export SYNC_BATCH_MB=1
big_file "$d/a.jpg" '30 minutes ago' 600
big_file "$d/b.jpg" '20 minutes ago' 600
big_file "$d/c.jpg" '10 minutes ago' 300
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "600+600 KB is over 1 MB: two rsync runs" test "$(rsync_calls | wc -l | tr -d ' ')" = 2
check "second batch holds b and c (600+300 KB)" test "$(grep -c '^list:' "$STUB_CALLS")" = 3
check "all shipped" test "$(find "$W/nas" -type f | wc -l | tr -d ' ')" = 3
check "all removed locally" test -z "$(frames)"
check "ok logged" grep -q 'sync ok files=3' "$SYNC_LOG_FILE"

section "sync pacing: a file bigger than the size cap still goes, on its own"
pace_env; export SYNC_BATCH_MB=1
big_file "$d/huge.jpg" '30 minutes ago' 1500
big_file "$d/small.jpg" '20 minutes ago' 10
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "two rsync runs" test "$(rsync_calls | wc -l | tr -d ' ')" = 2
check "both shipped" test "$(find "$W/nas" -type f | wc -l | tr -d ' ')" = 2

section "sync pacing: the file count still caps a batch of small files"
pace_env; export SYNC_BATCH=2 SYNC_BATCH_MB=100
for i in 1 2 3; do mkfile "$d/f$i.json" "$((40 - i)) minutes ago"; done
sync_
check "3 files in batches of 2 is 2 runs" test "$(rsync_calls | wc -l | tr -d ' ')" = 2

section "sync pacing: SYNC_MAX_S stops the run cleanly between batches"
pace_env; export SYNC_BATCH=1 SYNC_MAX_S=1 STUB_RSYNC_SLEEP=1.2
mkfile "$d/a.jpg" '30 minutes ago'
mkfile "$d/b.jpg" '20 minutes ago'
mkfile "$d/c.jpg" '10 minutes ago'
sync_; rc=$?
check "exits 0 (not a failure)" test "$rc" = 0
check "stopped after the first batch" test "$(rsync_calls | wc -l | tr -d ' ')" = 1
check "the oldest is confirmed and removed" test ! -e "$d/a.jpg"
check "the rest wait on the Pi" test -e "$d/b.jpg" -a -e "$d/c.jpg"
check "partial logged with confirmed and pending" grep -q 'sync partial confirmed=1 pending=2' "$SYNC_LOG_FILE"
check "no ok line" bash -c "! grep -q 'sync ok' '$SYNC_LOG_FILE'"
check "no interrupted line" bash -c "! grep -q 'sync interrupted' '$SYNC_LOG_FILE'"
unset STUB_RSYNC_SLEEP SYNC_MAX_S   # the follow-up run has the default limit: 1 s can be too short on a slow CI runner
sync_; rc=$?
check "next run sends the rest" test "$rc" = 0 -a -z "$(frames)"
check "next run logs ok" grep -q 'sync ok files=2' "$SYNC_LOG_FILE"

section "sync pacing: SYNC_MAX_S=0 means no time limit"
pace_env; export SYNC_BATCH=1 SYNC_MAX_S=0 STUB_RSYNC_SLEEP=0.2
mkfile "$d/a.jpg" '30 minutes ago'
mkfile "$d/b.jpg" '20 minutes ago'
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "all sent" test -z "$(frames)"
unset STUB_RSYNC_SLEEP

section "sync pacing: the systemd limit is a backstop above SYNC_MAX_S"
unit_s="$(sed -n 's/^TimeoutStartSec=//p' "$SRC/systemd/sunset-sync.service")"
max_s="$(sed -n 's/^MAX_S="\${SYNC_MAX_S:-\([0-9]*\)}".*/\1/p' "$SRC/sunset-sync.sh")"
check "default SYNC_MAX_S found" test -n "$max_s"
check "unit limit is at least SYNC_MAX_S + 30 min (one slow batch)" test "$unit_s" -ge "$(( max_s + 1800 ))"
unset SYNC_BATCH SYNC_BATCH_MB SYNC_MAX_S SYNC_CONFIG_BACKUP
