# Read-back before delete (issue #13) and the config backup (issue #23), both in sunset-sync.sh.
# The rsync stub copies into the mounted-share target and can damage a copy while still exiting 0
# (STUB_RSYNC_TRUNCATE / _FLIP / _DROP), which is the case the read-back exists for.
rb_file() { # rb_file <path> [content] [age]
  mkdir -p "$(dirname "$1")"; printf '%s' "${2-data-$(basename "$1")}" > "$1"; touch -d "${3:-10 minutes ago}" "$1"
}
rb_env() { # fresh sandbox, mounted-share target, config backup pointed at an empty fixture root
  fresh_env
  unset SYNC_VERIFY SYNC_VERIFY_HASH_MAX_MB SYNC_CONFIG_BACKUP SYNC_CONFIG_DIR SYNC_CONFIG_ENV SYNC_CONFIG_ROOT
  unset STUB_RSYNC_TRUNCATE STUB_RSYNC_FLIP STUB_RSYNC_DROP STUB_RSYNC_HOLE
  export NAS_TARGET="$W/share/project_sunshine/"; mkdir -p "$NAS_TARGET" "$OUT_ROOT"
  export SYNC_CONFIG_ROOT="$W/root"; mkdir -p "$W/root"
  d="$OUT_ROOT/wide/2026/01/01"; n="$NAS_TARGET/wide/2026/01/01"
}
rsync_args() { grep '^rsync ' "$STUB_CALLS" 2>/dev/null; }

section "read-back: a confirmed copy is removed locally"
rb_env
rb_file "$d/a.jpg"; rb_file "$d/a.json"; rb_file "$d/a_night.jpg"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "all three on the share" test "$(find "$NAS_TARGET" -type f | wc -l | tr -d ' ')" = 3
check "local copies removed" test -z "$(frames)"
check "ok logged" grep -q 'sync ok files=3' "$SYNC_LOG_FILE"
check "mounted share: rsync does not delete, the read-back does" bash -c "grep -q '^rsync ' '$STUB_CALLS' && ! grep '^rsync ' '$STUB_CALLS' | grep -q -- --remove-source-files"
check "--fsync still passed" bash -c "grep '^rsync ' '$STUB_CALLS' | grep -q -- ' --fsync'"

section "read-back: remote (ssh) target keeps rsync's own delete"
rb_env; export NAS_TARGET="sunset@nas.example:/volume1/x/"
rb_file "$d/a.jpg"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "rsync given --remove-source-files" bash -c "grep '^rsync ' '$STUB_CALLS' | grep -q -- --remove-source-files"
check "local copy removed" test -z "$(frames)"

section "read-back: a short copy is kept, logged, and retried"
rb_env; export STUB_RSYNC_TRUNCATE=a_night.jpg
rb_file "$d/a.jpg"; rb_file "$d/a_night.jpg" "$(head -c 4000 /dev/zero | tr '\0' 'r')"
sync_; rc=$?
check "exits non-zero" test "$rc" != 0
check "short file kept on the Pi" test -e "$d/a_night.jpg"
check "good file still removed" test ! -e "$d/a.jpg"
check "kept file logged with the reason" grep -q 'readback kept ./wide/2026/01/01/a_night.jpg: size' "$SYNC_LOG_FILE"
check "summary logged as a sync failure" grep -q 'sync FAILED read-back kept=1 confirmed=1' "$SYNC_LOG_FILE"
check "no ok line" bash -c "! grep -q 'sync ok' '$SYNC_LOG_FILE'"
check "bad NAS copy removed, so the next run resends it" test ! -e "$n/a_night.jpg"
unset STUB_RSYNC_TRUNCATE
sync_; rc=$?
check "next run exits 0" test "$rc" = 0
check "next run: full copy on the share" cmp -s "$n/a_night.jpg" <(head -c 4000 /dev/zero | tr '\0' 'r')
check "next run: removed locally" test ! -e "$d/a_night.jpg"

section "read-back: same size, different bytes"
rb_env; export STUB_RSYNC_FLIP=a.jpg
rb_file "$d/a.jpg" "pixels-pixels"; rb_file "$d/a.json"
sync_; rc=$?
check "exits non-zero" test "$rc" != 0
check "file kept on the Pi" test -e "$d/a.jpg"
check "logged as a checksum mismatch" grep -q 'readback kept ./wide/2026/01/01/a.jpg: sha256' "$SYNC_LOG_FILE"
check "other file removed" test ! -e "$d/a.json"
unset STUB_RSYNC_FLIP
sync_; rc=$?
check "next run exits 0" test "$rc" = 0
check "next run: right bytes on the share" test "$(cat "$n/a.jpg")" = "pixels-pixels"
check "next run: removed locally" test ! -e "$d/a.jpg"

section "read-back: rsync says ok but the file is not there"
rb_env; export STUB_RSYNC_DROP=a.jpg
rb_file "$d/a.jpg"; rb_file "$d/b.jpg"
sync_; rc=$?
check "exits non-zero" test "$rc" != 0
check "missing file kept" test -e "$d/a.jpg"
check "logged" grep -q 'readback kept ./wide/2026/01/01/a.jpg: not on the NAS' "$SYNC_LOG_FILE"
check "other file removed" test ! -e "$d/b.jpg"
unset STUB_RSYNC_DROP

section "read-back: files above SYNC_VERIFY_HASH_MAX_MB get the size check only"
big() { rb_file "$d/big.jpg" "$(head -c 1200000 /dev/zero | tr '\0' 'q')"; }
rb_env; export STUB_RSYNC_HOLE=big.jpg SYNC_VERIFY_HASH_MAX_MB=1
big; rb_file "$d/small.jpg" "abc"
sync_; rc=$?
check "exits 0: same-size damage in a large file is not seen (the trade-off)" test "$rc" = 0
check "large file removed after the size check" test ! -e "$d/big.jpg"
rb_env; export STUB_RSYNC_TRUNCATE=big.jpg SYNC_VERIFY_HASH_MAX_MB=1
big
sync_; rc=$?
check "a short copy of a large file is caught" test "$rc" != 0
check "large file kept" test -e "$d/big.jpg"
check "logged" grep -q 'readback kept ./wide/2026/01/01/big.jpg: size' "$SYNC_LOG_FILE"
unset STUB_RSYNC_TRUNCATE
rb_env; export STUB_RSYNC_FLIP=small.jpg SYNC_VERIFY_HASH_MAX_MB=1
rb_file "$d/small.jpg" "abc"
sync_; rc=$?
check "small file is hashed: mismatch caught" test "$rc" != 0
check "small file kept" test -e "$d/small.jpg"
rb_env; export STUB_RSYNC_HOLE=big.jpg SYNC_VERIFY_HASH_MAX_MB=0
big
sync_; rc=$?
check "SYNC_VERIFY_HASH_MAX_MB=0: no file is hashed in full" test "$rc" = 0
rb_env; export STUB_RSYNC_HOLE=big.jpg SYNC_VERIFY_HASH_MAX_MB=100
big
sync_; rc=$?
check "a high limit hashes the file in full: middle damage caught" test "$rc" != 0
check "file kept" test -e "$d/big.jpg"
check "logged as a checksum mismatch" grep -q 'readback kept ./wide/2026/01/01/big.jpg: sha256' "$SYNC_LOG_FILE"
unset STUB_RSYNC_FLIP STUB_RSYNC_HOLE SYNC_VERIFY_HASH_MAX_MB

section "read-back: SYNC_VERIFY=0 trusts rsync as before"
rb_env; export SYNC_VERIFY=0 STUB_RSYNC_TRUNCATE=a.jpg
rb_file "$d/a.jpg"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "rsync given --remove-source-files" bash -c "grep '^rsync ' '$STUB_CALLS' | grep -q -- --remove-source-files"
check "file removed without a read-back" test ! -e "$d/a.jpg"
unset SYNC_VERIFY STUB_RSYNC_TRUNCATE

section "read-back: a copy already on the share (run cut short before the check) is confirmed"
rb_env
rb_file "$d/a.jpg"; mkdir -p "$n"; cp "$d/a.jpg" "$n/a.jpg"; touch -r "$d/a.jpg" "$n/a.jpg"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "local copy removed" test ! -e "$d/a.jpg"

section "read-back: partial and young files are untouched"
rb_env
rb_file "$OUT_ROOT/.partial/half.jpg"; rb_file "$d/new.jpg" "x" "now"; rb_file "$d/old.jpg"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check ".partial untouched" test -e "$OUT_ROOT/.partial/half.jpg"
check "young file untouched" test -e "$d/new.jpg"
check "old file shipped and removed" test ! -e "$d/old.jpg" -a -e "$n/old.jpg"

# ---- config backup (#23) ----
cfg_fixture() { # sunset.env next to the outbox, fstab and boot config under SYNC_CONFIG_ROOT
  printf 'CAM_NAME=wide\nSITE_LAT=49.98765\nSITE_LON=-122.12345\n' > "$W/sunset.env"
  mkdir -p "$W/root/etc" "$W/root/boot/firmware"
  printf '//nas/camera /mnt/nas-camera cifs credentials=/etc/sunset-nas.cred,_netdev 0 0\n' > "$W/root/etc/fstab"
  printf 'camera_auto_detect=0\ndtoverlay=imx477\n' > "$W/root/boot/firmware/config.txt"
  printf 'username=camera\npassword=SECRET-DO-NOT-COPY\n' > "$W/root/etc/sunset-nas.cred"
}
cfg_dir() { echo "$W/share/project_sunshine_config/$(hostname)"; }
cfg_copies() { grep -c 'config backup ok' "$SYNC_LOG_FILE" 2>/dev/null || echo 0; }

section "config backup: copies sunset.env, fstab and config.txt to a per-host folder"
rb_env; cfg_fixture
rb_file "$d/a.jpg"
sync_; rc=$?
C="$(cfg_dir)"
check "exits 0" test "$rc" = 0
check "default folder is <NAS root>/project_sunshine_config/<hostname>" test -d "$C"
check "sunset.env copied" cmp -s "$W/sunset.env" "$C/sunset.env"
check "fstab copied" cmp -s "$W/root/etc/fstab" "$C/fstab"
check "config.txt copied from /boot/firmware" cmp -s "$W/root/boot/firmware/config.txt" "$C/config.txt"
check "only those three files" test "$(find "$C" -type f | wc -l | tr -d ' ')" = 3
check "credential file never copied" bash -c "! grep -rq 'SECRET-DO-NOT-COPY' '$W/share'"
check "no .cred file on the share" test -z "$(find "$W/share" -name '*.cred')"
check "logged" grep -q 'config backup ok' "$SYNC_LOG_FILE"
check "sunset.env contents never logged" bash -c "! grep -qE '49\.98765|122\.12345|SITE_LAT|CAM_NAME' '$SYNC_LOG_FILE'"
check "frames still synced" test -e "$n/a.jpg" -a ! -e "$d/a.jpg"

section "config backup: only when changed, and at least once a day"
echo "marker" >> "$C/fstab"
sync_
check "unchanged: not copied again" test "$(cfg_copies)" = 1
check "unchanged: NAS copy left alone" grep -q marker "$C/fstab"
echo 'NIGHT_LUX=5' >> "$W/sunset.env"
sync_
check "changed: copied again" test "$(cfg_copies)" = 2
check "changed: new sunset.env on the share" cmp -s "$W/sunset.env" "$C/sunset.env"
check "changed: every file refreshed" bash -c "! grep -q marker '$C/fstab'"
echo "marker" >> "$C/fstab"
stamp="$(ls "$W"/sync.log.config 2>/dev/null)"
check "the change stamp lives next to sync.log" test -n "$stamp"
sed -i 's/^[0-9-]* /2000-01-01 /' "$W/sync.log.config"
sync_
check "new UTC day: copied again even if unchanged" test "$(cfg_copies)" = 3
check "new UTC day: NAS copy refreshed" bash -c "! grep -q marker '$C/fstab'"

section "config backup: runs when no frames are waiting"
rb_env; cfg_fixture
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "copied" test -e "$(cfg_dir)/sunset.env"

section "config backup: /boot/config.txt when there is no /boot/firmware"
rb_env; cfg_fixture; rm -rf "$W/root/boot/firmware"
printf 'old_layout=1\n' > "$W/root/boot/config.txt"
sync_
check "config.txt from /boot" cmp -s "$W/root/boot/config.txt" "$(cfg_dir)/config.txt"

section "config backup: a file holding a password is not copied"
rb_env; cfg_fixture
printf '//nas/camera /mnt/x cifs username=camera,password=hunter2 0 0\n' > "$W/root/etc/fstab"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "fstab not copied" test ! -e "$(cfg_dir)/fstab"
check "the others still copied" test -e "$(cfg_dir)/sunset.env" -a -e "$(cfg_dir)/config.txt"
check "skip logged" grep -q 'config backup skipped .*fstab.*password' "$SYNC_LOG_FILE"
check "password not logged" bash -c "! grep -q hunter2 '$SYNC_LOG_FILE'"
check "password not on the share" bash -c "! grep -rq hunter2 '$W/share'"

section "config backup: a secret under a longer setting name is caught too"
# The filter once needed a non-letter before the keyword, so NAS_PASSWORD= or IG_ACCESS_TOKEN= passed.
for secret in 'NAS_PASSWORD=hunter2' 'IG_ACCESS_TOKEN=hunter2' 'API_SECRET=hunter2' 'export SMB_PASS=hunter2' 'IG_TOKEN_2 = hunter2'; do
  rb_env; cfg_fixture
  printf 'CAM_NAME=wide
%s
' "$secret" > "$W/sunset.env"
  sync_
  check "$secret: sunset.env not copied" test ! -e "$(cfg_dir)/sunset.env"
  check "$secret: not on the share" bash -c "! grep -rq hunter2 '$W/share'"
done
rb_env; cfg_fixture
sync_
check "an ordinary sunset.env is still copied" test -e "$(cfg_dir)/sunset.env"

section "config backup: a missing sunset.env is logged, the rest copied"
rb_env; cfg_fixture; rm -f "$W/sunset.env"
sync_
check "missing logged" grep -q 'config backup: .*sunset.env missing' "$SYNC_LOG_FILE"
check "fstab still copied" test -e "$(cfg_dir)/fstab"

section "config backup: explicit paths and the off switch"
rb_env; cfg_fixture
printf 'X=1\n' > "$W/other.env"
export SYNC_CONFIG_ENV="$W/other.env" SYNC_CONFIG_DIR="$W/share/elsewhere"
sync_
check "SYNC_CONFIG_ENV and SYNC_CONFIG_DIR honoured" cmp -s "$W/other.env" "$W/share/elsewhere/sunset.env"
check "SYNC_CONFIG_ENV pointed at a .cred file is refused" bash -c "
  export SYNC_CONFIG_ENV='$W/root/etc/sunset-nas.cred' SYNC_CONFIG_DIR='$W/share/c2'
  bash '$SRC/sunset-sync.sh'; ! grep -rq SECRET-DO-NOT-COPY '$W/share'"
unset SYNC_CONFIG_ENV SYNC_CONFIG_DIR
rb_env; cfg_fixture; export SYNC_CONFIG_BACKUP=0
sync_
check "SYNC_CONFIG_BACKUP=0: nothing copied" test ! -e "$W/share/project_sunshine_config"
unset SYNC_CONFIG_BACKUP

section "config backup: never when the share is missing, on the SD card, or remote"
rb_env; cfg_fixture; rm -rf "$W/share"
rb_file "$d/a.jpg"
sync_
check "share missing: nothing created" test ! -e "$W/share"
rb_env; cfg_fixture; rm -rf "$W/share"
sync_
check "share missing, no frames: nothing created" test ! -e "$W/share"
rb_env; cfg_fixture; export STUB_SAME_FS=1
sync_
check "share on the SD card: no backup" test ! -e "$W/share/project_sunshine_config"
unset STUB_SAME_FS
rb_env; cfg_fixture; export NAS_TARGET="sunset@nas.example:/volume1/x/"
rb_file "$d/a.jpg"
sync_; rc=$?
check "remote target: sync still exits 0" test "$rc" = 0
check "remote target: no config backup logged" bash -c "! grep -q 'config backup ok' '$SYNC_LOG_FILE'"
