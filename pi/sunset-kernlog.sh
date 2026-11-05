#!/usr/bin/env bash
# Keep kernel messages on the SD card, so a freeze or crash leaves evidence. System logs live in
# RAM (see sunset-lowwear.sh) and are lost on reboot. Each line is flushed as it arrives, because
# root only commits every 60 s otherwise. Kernel messages are rare, so this adds few writes.
# A hard freeze may still log nothing: this only has what the kernel managed to say.
set -u

LOG="${KERNEL_LOG:-$HOME/sunset/kernel.log}"
MAX_BYTES="${KERNEL_LOG_MAX_BYTES:-1048576}"

add() {
  if [[ -f "$LOG" ]] && (( $(wc -c < "$LOG") >= MAX_BYTES )); then
    mv -f "$LOG" "$LOG.1"
  fi
  printf '%s\n' "$1" >> "$LOG"
  sync "$LOG"
}

add "=== log started $(date -u +%FT%TZ), boot $(cat /proc/sys/kernel/random/boot_id 2>/dev/null)"
while IFS= read -r line; do
  add "$line"
done < <(journalctl -k -f -n 0 -o short-iso --no-pager)
