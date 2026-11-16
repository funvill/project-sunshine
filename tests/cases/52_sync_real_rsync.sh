# The sync against the REAL rsync binary (issue #13): the stub is all-or-nothing, so partial
# transfers (rc 23) were never exercised. Skipped, with a message, when rsync is not installed.
# Everything else still comes from the stubs (stat, df, ...); only rsync is the real one.
section "sync with the real rsync"
real_rsync="$(PATH="${PATH//$HERE\/stubs:/}" command -v rsync 2>/dev/null || true)"
if [[ -z "$real_rsync" ]]; then
  echo "  SKIP: no real rsync installed (apt install rsync); the real-rsync checks did not run"
else
  _saved_path="$PATH"
  _real_fsync=no; "$real_rsync" --help 2>&1 | grep -q -- '--fsync' && _real_fsync=yes
  echo "  using $real_rsync ($("$real_rsync" --version | head -n1)); supports --fsync: $_real_fsync"
  real_env() { # fresh sandbox with the real rsync first on PATH and a mounted-share style target
    fresh_env
    mkdir -p "$W/realbin"; ln -sf "$real_rsync" "$W/realbin/rsync"
    export PATH="$W/realbin:$_saved_path"
    export NAS_TARGET="$W/mnt/share/"; mkdir -p "$NAS_TARGET"
    d="$OUT_ROOT/wide/2026/01/01"
  }
  real_file() { mkdir -p "$(dirname "$1")"; printf '%s' "${3-data-$(basename "$1")}" > "$1"; touch -d "${2:-10 minutes ago}" "$1"; }
  on_share() { test -e "$NAS_TARGET/$1"; }

  section "real rsync: normal run"
  real_env
  real_file "$d/a.jpg"; real_file "$d/a.json"; real_file "$d/a.dng"
  sync_; rc=$?
  check "exits 0" test "$rc" = 0
  check "all three arrived" test "$(find "$NAS_TARGET" -type f | wc -l | tr -d ' ')" = 3
  check "content intact" cmp -s <(printf '%s' data-a.jpg) "$NAS_TARGET/wide/2026/01/01/a.jpg"
  check "local copies removed" test -z "$(frames)"
  check "ok logged" grep -q 'sync ok files=3' "$SYNC_LOG_FILE"

  section "real rsync: batches of 1 still ship everything"
  real_env; export SYNC_BATCH=1
  real_file "$d/a.jpg" '30 minutes ago'; real_file "$d/b.jpg" '20 minutes ago'; real_file "$d/c.jpg" '10 minutes ago'
  sync_; rc=$?
  check "exits 0" test "$rc" = 0
  check "three arrived" test "$(find "$NAS_TARGET" -type f | wc -l | tr -d ' ')" = 3
  check "none left" test -z "$(frames)"
  unset SYNC_BATCH

  section "real rsync: partial failure (an unreadable file) exits 23, removes only what was sent"
  real_env
  real_file "$d/a.jpg"; real_file "$d/b.jpg"; real_file "$d/c.jpg"
  chmod 000 "$d/b.jpg"
  if [[ -r "$d/b.jpg" ]]; then
    echo "  SKIP: file permissions are not enforced here (root, or a filesystem without them); the partial-failure checks did not run"
  else
    sync_; rc=$?
    check "exits 23" test "$rc" = 23
    check "readable files arrived" test "$(find "$NAS_TARGET" -type f | wc -l | tr -d ' ')" = 2
    check "a.jpg on the share" on_share wide/2026/01/01/a.jpg
    check "c.jpg on the share" on_share wide/2026/01/01/c.jpg
    check "unreadable file not on the share" test ! -e "$NAS_TARGET/wide/2026/01/01/b.jpg"
    check "unreadable file still local" test -e "$d/b.jpg"
    check "transferred files removed locally" test ! -e "$d/a.jpg" -a ! -e "$d/c.jpg"
    check "failure logged with rc and the pending count" grep -q 'sync FAILED rc=23 pending=3' "$SYNC_LOG_FILE"
    chmod 644 "$d/b.jpg"
    sync_; rc=$?
    check "next run, readable again: exits 0" test "$rc" = 0
    check "next run ships it" on_share wide/2026/01/01/b.jpg
  fi

  section "real rsync: zero-length image"
  real_env
  real_file "$d/a.jpg" '10 minutes ago' ""
  real_file "$d/b.jpg"; real_file "$d/b.json"
  sync_; rc=$?
  check "exits 0" test "$rc" = 0
  check "good frame shipped" on_share wide/2026/01/01/b.jpg
  check "empty image not shipped" test ! -e "$NAS_TARGET/wide/2026/01/01/a.jpg"
  check "empty image left in place" test -e "$d/a.jpg"
  check "skip logged" grep -q 'zero-length image' "$SYNC_LOG_FILE"

  section "real rsync: read-back catches a bad copy that rsync's quick check skips (#13)"
  # A copy already on the share with the same size and time but other bytes: rsync sees nothing
  # to send and exits 0. The read-back must keep the frame, remove the bad copy, and the next
  # run must send the real one.
  real_env
  real_file "$d/a.jpg" '10 minutes ago' "good-bytes"
  mkdir -p "$NAS_TARGET/wide/2026/01/01"
  printf 'evil-bytes' > "$NAS_TARGET/wide/2026/01/01/a.jpg"; touch -r "$d/a.jpg" "$NAS_TARGET/wide/2026/01/01/a.jpg"
  sync_; rc=$?
  check "exits non-zero" test "$rc" != 0
  check "frame kept on the Pi" test -e "$d/a.jpg"
  check "mismatch logged" grep -q 'readback kept ./wide/2026/01/01/a.jpg: sha256' "$SYNC_LOG_FILE"
  check "bad copy removed from the share" test ! -e "$NAS_TARGET/wide/2026/01/01/a.jpg"
  sync_; rc=$?
  check "next run exits 0" test "$rc" = 0
  check "next run: the right bytes on the share" test "$(cat "$NAS_TARGET/wide/2026/01/01/a.jpg")" = good-bytes
  check "next run: frame removed locally" test ! -e "$d/a.jpg"

  section "real rsync: a share path that is not there keeps every frame"
  real_env; rm -rf "$NAS_TARGET"
  real_file "$d/a.jpg"
  sync_; rc=$?
  check "exits non-zero" test "$rc" != 0
  check "frame kept" test -e "$d/a.jpg"

  export PATH="$_saved_path"
fi
