# needs: 80_frame_age
# Per-camera health from the newest frame's JSON (issue #22): homeassistant/sunset_camera_health.sh,
# under sh and busybox sh. Field names are the ones pi/sunset-meta.py writes (System.throttled,
# System.cpu_temp_c, System.disk.used_pct, System.outbox_pending.files, Capture.files.jpg.sha256).
SH="$HA/sunset_camera_health.sh"
# hframe <camera> <UTC stamp> <throttled> <temp> <outbox files> <disk %> <jpeg bytes> <sha> [night]
hframe() {
  local cam="$1" t="$2" thr="$3" temp="$4" box="$5" disk="$6" size="$7" sha="$8" night="${9:-}"
  local dir="$W/$cam/${t:0:4}/${t:4:2}/${t:6:2}" stem="${cam}_${t}${night:+_night}" jb="$7"
  [ "$7" = missing ] && jb=500000      # "missing": the JSON names a JPEG that has not arrived
  mkdir -p "$dir"
  printf '{"Lux":100,"Capture":{"kind":"auto","files":{"jpg":{"bytes":%s,"sha256":"%s"}}},"System":{"cpu_temp_c":%s,"throttled":%s,"disk":{"used_pct":%s},"outbox_pending":{"files":%s,"bytes":1}}}\n' \
    "$jb" "$sha" "$temp" "$thr" "$disk" "$box" > "$dir/$stem.json"
  [ "$size" = missing ] || head -c "$size" /dev/zero > "$dir/$stem.jpg"
}
fresh_health() { W="$(mktemp -d)"; export FRAME_BASE="$W" SUNSET_NOW="$(date -u -d '2026-11-05 18:00:00' +%s)"; }

section "camera health: a healthy frame"
fresh_health
hframe wide 20261105T175500Z '"0x0"' 50.0 2 40.0 500000 aaa
ha_out "all good" ok "$SH" wide

section "camera health: throttled bits 0-3 now, history ignored"
fresh_health
hframe wide 20261105T175500Z '"0x50005"' 50.0 2 40.0 500000 aaa
ha_out "0x50005 is undervoltage and throttled" "undervoltage throttled" "$SH" wide
hframe wide 20261105T175500Z '"0x80000"' 50.0 2 40.0 500000 aaa
ha_out "bit 19 alone (soft limit reached since boot) is only history" ok "$SH" wide
hframe wide 20261105T175500Z '"0x8"' 50.0 2 40.0 500000 aaa
ha_out "bit 3 is the soft temperature limit now" soft_temp_limit "$SH" wide
hframe wide 20261105T175500Z '"0xf"' 50.0 2 40.0 500000 aaa
ha_out "all four bits, in bit order" "undervoltage freq_capped throttled soft_temp_limit" "$SH" wide
hframe wide 20261105T175500Z null 50.0 2 40.0 500000 aaa
ha_out "a throttled probe that failed (null) is skipped" ok "$SH" wide

section "camera health: limits"
fresh_health
hframe wide 20261105T175500Z '"0x0"' 75.0 50 80.0 400000 aaa
ha_out "exactly at every limit is fine" ok "$SH" wide
hframe wide 20261105T175500Z '"0x0"' 78.4 51 80.1 399999 aaa
ha_out "just past every limit" "temp=78.4 outbox=51 disk=80.1% small_jpeg=399999" "$SH" wide
hframe wide 20261105T175500Z '"0x0"' null 2 null 500000 aaa
ha_out "null temperature and disk are skipped" ok "$SH" wide
hframe wide 20261105T175500Z '"0x0"' 61.0 2 40.0 500000 aaa
export TEMP_LIMIT_C=60 OUTBOX_MAX=1 DISK_MAX_PCT=30 JPEG_MIN_BYTES=600000
ha_out "limits are settings" "temp=61 outbox=2 disk=40% small_jpeg=500000" "$SH" wide
unset TEMP_LIMIT_C OUTBOX_MAX DISK_MAX_PCT JPEG_MIN_BYTES
hframe wide 20261105T175500Z '"0x0"' 50.0 2 40.0 missing aaa
ha_out "a JPEG that has not arrived yet is not a small JPEG" ok "$SH" wide

section "camera health: a frozen readout"
fresh_health
hframe wide 20261105T175000Z '"0x0"' 50.0 2 40.0 500000 same
hframe wide 20261105T175500Z '"0x0"' 50.0 2 40.0 500000 same
ha_out "same checksum as the frame before" repeat_frame "$SH" wide
hframe wide 20261105T175500Z '"0x0"' 50.0 2 40.0 500000 other
ha_out "different checksum" ok "$SH" wide
hframe wide 20261105T175500Z '"0x0"' 50.0 2 40.0 500000 same
hframe wide 20261105T175500Z '"0x0"' 50.0 2 40.0 500000 same night
ha_out "a night frame is only compared with night frames" ok "$SH" wide
hframe wide 20261105T175000Z '"0x0"' 50.0 2 40.0 500000 nightsame night
hframe wide 20261105T175500Z '"0x0"' 50.0 2 40.0 500000 nightsame night
ha_out "the newest night frame matching the earlier night frame" repeat_frame "$SH" wide

section "camera health: frames without the blocks"
fresh_health
mkdir -p "$W/wide/2026/11/05"
printf '{"Lux":100}\n' > "$W/wide/2026/11/05/wide_20261105T175500Z.json"
head -c 500000 /dev/zero > "$W/wide/2026/11/05/wide_20261105T175500Z.jpg"
ha_out "no Capture or System block" no_meta "$SH" wide

section "camera health: lost camera metadata, missing checksum"
fresh_health
hframe wide 20261105T175500Z '"0x0"' 50.0 2 40.0 500000 aaa
sed -i 's/{"Lux":100,/{"rpicam_metadata":"invalid","Lux":100,/; s/"Capture":{"kind":"auto",/"Capture":{"unavailable":["sha256"],"kind":"auto",/' "$W/wide/2026/11/05/wide_20261105T175500Z.json"
ha_out "rpicam_metadata flag and Capture.unavailable" "camera_metadata no_checksum" "$SH" wide

section "camera health: the newest file half copied"
fresh_health
hframe wide 20261105T175000Z '"0x8"' 50.0 2 40.0 500000 aaa
printf '{"Lux":10' > "$W/wide/2026/11/05/wide_20261105T175500Z.json"
ha_out "falls back to the one before" soft_temp_limit "$SH" wide

section "camera health: no answer is unknown"
fresh_health
ha_fails "share missing" "$SH" wide
hframe wide 20261102T120000Z '"0x0"' 50.0 2 40.0 500000 aaa
ha_fails "frames older than two days" "$SH" wide
fresh_health
hframe wide 20261104T235500Z '"0x0"' 50.0 2 40.0 500000 aaa
ha_out "yesterday's folder counts" ok "$SH" wide
fresh_health
mkdir -p "$W/wide/2026/11/05"
printf '{broken' > "$W/wide/2026/11/05/wide_20261105T175500Z.json"
ha_fails "only unreadable JSON" "$SH" wide
ha_fails "a bad camera name" "$SH" 'a/../b'
fresh_health
hframe cm4wide 20261105T175500Z '"0x1"' 50.0 2 40.0 500000 aaa
ha_out "another camera by name, with its own folder" undervoltage "$SH" cm4wide
ha_fails "wide does not see the cm4 folder" "$SH" wide
check "python3 missing is unknown, not a crash" bash -c "[ -z \"\$(env PATH=/nonexistent '$(command -v sh)' '$SH' cm4wide 2>/dev/null)\" ] && ! env PATH=/nonexistent '$(command -v sh)' '$SH' cm4wide >/dev/null 2>&1"
unset FRAME_BASE SUNSET_NOW
