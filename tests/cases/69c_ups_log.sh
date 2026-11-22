# needs: 69_sync_readback
# The UPS log (issue #29) copied to the share by sunset-sync.sh, next to the config backup.
# Uses rb_env, rb_file and cfg_dir from 69_sync_readback.sh.
ups_line() { # ups_line <utc> <tag>
  printf '%s %s src=mains pct=88 rte=- vbat=10.70 cells=3.57,3.56,3.57 t=24,24,25 vin=15.10 vout=15.00 ichg=0.00 idchg=0.00 ups=03 chg=0f present=111 flags=002000 fw=1.6\n' "$1" "$2"
}
ups_dir() { echo "$(cfg_dir)/ups"; }
ups_copies() { grep -c 'ups log backup ok' "$SYNC_LOG_FILE" 2>/dev/null || echo 0; }

section "ups log: live and rotated files copied, named by their first line"
rb_env
ups_line 2026-11-20T06:30:00Z KEY > "$W/ups.log"
ups_line 2026-11-19T00:00:05Z KEY > "$W/ups.log.1"
ups_line 2026-11-19T04:00:05Z KEY >> "$W/ups.log.1"
ups_line 2026-11-18T00:00:05Z KEY > "$W/ups.log.13"
rb_file "$d/a.jpg"
sync_; rc=$?
U="$(ups_dir)"
check "exits 0" test "$rc" = 0
check "live file copied" cmp -s "$W/ups.log" "$U/ups-20261120T063000Z.log"
check "rotated file copied" cmp -s "$W/ups.log.1" "$U/ups-20261119T000005Z.log"
check "two-digit rotated file copied" cmp -s "$W/ups.log.13" "$U/ups-20261118T000005Z.log"
check "only those three, no temp files" test "$(find "$U" -type f | wc -l | tr -d ' ')" = 3
check "logged once" test "$(ups_copies)" = 1
check "frames still synced" test -e "$n/a.jpg" -a ! -e "$d/a.jpg"

section "ups log: copied again only when it grew"
sync_
check "unchanged: not copied, not logged" test "$(ups_copies)" = 1
ups_line 2026-11-20T07:00:00Z "EVENT mains_lost" >> "$W/ups.log"
sync_
check "grew: copied" cmp -s "$W/ups.log" "$U/ups-20261120T063000Z.log"
check "grew: logged" test "$(ups_copies)" = 2
# The monitor rotates: the live file becomes ups.log.1 under the same name on the share.
mv "$W/ups.log.1" "$W/ups.log.2"; mv "$W/ups.log" "$W/ups.log.1"
ups_line 2026-11-21T00:00:01Z KEY > "$W/ups.log"
sync_
check "after rotation: the new live file is added" test -e "$U/ups-20261121T000001Z.log"
check "after rotation: the old ones are not copied again" test "$(grep 'ups log backup ok' "$SYNC_LOG_FILE" | tail -n1 | grep -c 'files=1')" = 1
check "after rotation: four files" test "$(find "$U" -type f | wc -l | tr -d ' ')" = 4

section "ups log: runs when no frames are waiting"
rb_env
ups_line 2026-11-20T06:30:00Z KEY > "$W/ups.log"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "copied" test -e "$(ups_dir)/ups-20261120T063000Z.log"

section "ups log: none on a Pi without the UPS, and not off the mounted share"
rb_env
rb_file "$d/a.jpg"
sync_
check "no ups log: no ups folder" test ! -e "$(ups_dir)"
check "no ups log: nothing logged" bash -c "! grep -q 'ups log' '$SYNC_LOG_FILE'"
rb_env; ups_line 2026-11-20T06:30:00Z KEY > "$W/ups.log"; rm -rf "$W/share"
sync_
check "share missing: nothing created" test ! -e "$W/share"
rb_env; ups_line 2026-11-20T06:30:00Z KEY > "$W/ups.log"; export SYNC_CONFIG_BACKUP=0
sync_
check "SYNC_CONFIG_BACKUP=0: not copied" test ! -e "$(ups_dir)"
unset SYNC_CONFIG_BACKUP

section "ups log: a file with no timestamp is left alone, the rest copied"
rb_env
printf 'garbage\n' > "$W/ups.log.1"
ups_line 2026-11-20T06:30:00Z KEY > "$W/ups.log"
sync_; rc=$?
check "exits 0" test "$rc" = 0
check "good one copied" test -e "$(ups_dir)/ups-20261120T063000Z.log"
check "bad one skipped" test "$(find "$(ups_dir)" -type f | wc -l | tr -d ' ')" = 1

section "ups log: explicit paths"
rb_env
ups_line 2026-11-20T06:30:00Z KEY > "$W/other-ups.log"
export SYNC_UPS_LOG="$W/other-ups.log" SYNC_UPS_DIR="$W/share/upsx"
sync_
check "SYNC_UPS_LOG and SYNC_UPS_DIR honoured" cmp -s "$W/other-ups.log" "$W/share/upsx/ups-20261120T063000Z.log"
unset SYNC_UPS_LOG SYNC_UPS_DIR
