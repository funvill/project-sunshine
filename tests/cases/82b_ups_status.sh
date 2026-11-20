# The UPS state for Home Assistant (issue #29): homeassistant/sunset_ups.sh, under sh and busybox sh.
# It reads System.ups_source and System.ups_charge_pct from the newest frame's JSON, which
# pi/sunset-meta.py copies from the UPS monitor's status (null when that status is stale or missing).
SH="$HA/sunset_ups.sh"
# uframe <camera> <UTC stamp> <ups_source JSON> <ups_charge_pct JSON> [extra System JSON]
uframe() {
  local cam="$1" t="$2" dir="$W/$1/${2:0:4}/${2:4:2}/${2:6:2}"
  mkdir -p "$dir"
  printf '{"Capture":{"kind":"auto"},"System":{"ups_source":%s,"ups_charge_pct":%s%s}}\n' \
    "$3" "$4" "${5:+,$5}" > "$dir/${cam}_${t}.json"
}
fresh_ups() { W="$(mktemp -d)"; export FRAME_BASE="$W" SUNSET_NOW="$(date -u -d '2026-11-20 18:00:00' +%s)"; }

section "ups: on mains"
fresh_ups
uframe cm4wide 20261120T175500Z '"mains"' 100
ha_out "mains and the charge" "mains 100" "$SH" cm4wide

section "ups: on battery"
fresh_ups
uframe cm4wide 20261120T175500Z '"mains"' 100
uframe cm4wide 20261120T180000Z '"battery"' 87
ha_out "the newest frame wins" "battery 87" "$SH" cm4wide

section "ups: status not available counts as unknown, never as mains"
fresh_ups
uframe cm4wide 20261120T175500Z null null '"ups":{"ok":false,"error":"stale"}'
ha_out "stale monitor status" "unknown stale" "$SH" cm4wide
fresh_ups
uframe cm4wide 20261120T175500Z null null
ha_out "null source, no ups block" "unknown none" "$SH" cm4wide
fresh_ups
uframe cm4wide 20261120T175500Z '"mains"' null
ha_out "a charge that failed to read is left out" "mains" "$SH" cm4wide
fresh_ups
uframe cm4wide 20261120T175500Z '"elsewhere"' 50
ha_out "a source it doesn't know is unknown" "unknown elsewhere" "$SH" cm4wide
fresh_ups
d="$W/cm4wide/2026/11/20"; mkdir -p "$d"
printf '{"Capture":{"kind":"auto"},"System":{"cpu_temp_c":40}}\n' > "$d/cm4wide_20261120T175500Z.json"
ha_out "a frame from before the UPS fields (no ups_source)" "unknown none" "$SH" cm4wide

section "ups: nothing to read"
fresh_ups
ha_fails "no frame in two days" "$SH" cm4wide
fresh_ups
uframe cm4wide 20261118T120000Z '"mains"' 100
ha_fails "a frame older than yesterday" "$SH" cm4wide
fresh_ups
d="$W/cm4wide/2026/11/20"; mkdir -p "$d"
printf 'not json' > "$d/cm4wide_20261120T175500Z.json"
ha_fails "only an unreadable frame" "$SH" cm4wide
fresh_ups
uframe cm4wide 20261120T175000Z '"battery"' 60
printf '{"Captu' > "$W/cm4wide/2026/11/20/cm4wide_20261120T175500Z.json"
ha_out "a half-copied newest frame falls back to the one before" "battery 60" "$SH" cm4wide
ha_fails "a bad camera name" "$SH" 'cm4wide/../x'
