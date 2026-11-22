# needs: 80_frame_age
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

section "ups: an old frame says nothing about the power now"
# With captures failing (Nov 19-20) the newest frame can be hours old; its "mains" is no evidence.
fresh_ups
uframe cm4wide 20261120T163000Z '"mains"' 100
ha_out "a frame 90 minutes old is unknown" "unknown old_frame" "$SH" cm4wide
fresh_ups
uframe cm4wide 20261120T170100Z '"battery"' 80
ha_out "59 minutes is still read" "battery 80" "$SH" cm4wide
fresh_ups
uframe cm4wide 20261120T171500Z '"mains"' 100
export UPS_MAX_AGE_MIN=30
ha_out "the limit is a setting" "unknown old_frame" "$SH" cm4wide
unset UPS_MAX_AGE_MIN
fresh_ups
uframe cm4wide 20261120T163000Z '"battery"' 80 '"cpu_temp_c":40,"ups":{"ok":true,"vin":0.0,"cells":[3.9,3.9,3.9]}'
check "old frame: no numbers in --json" test "$(sh "$SH" cm4wide --json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['state'], d['power'], d['cell1_v'], d['cpu_temp_c'])")" = "unknown old_frame None None None"

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

section "ups: --json gives every value, for Home Assistant's graphs"
# json_field <field>: the field from the script's --json output, as Python prints it
json_field() { sh "$SH" cm4wide --json | python3 -c "import json,sys; print(json.load(sys.stdin).get('$1'))"; }
fresh_ups
uframe cm4wide 20261120T175500Z '"battery"' 87 '"cpu_temp_c":47.2,"ups":{"ok":true,"source":"battery","pct":87,"vin":0.0,"vout":12.132,"vbat":12.177,"cells":[4.061,4.062,4.055],"temps":[20,21,22],"ichg":0.0,"idchg":0.0}'
check "state is the plain line" test "$(json_field state)" = "battery 87"
check "power" test "$(json_field power)" = battery
check "charge %" test "$(json_field charge_pct)" = 87
check "input volts (mains)" test "$(json_field input_v)" = 0.0
check "output volts" test "$(json_field output_v)" = 12.132
check "pack volts" test "$(json_field pack_v)" = 12.177
check "cell 1 volts" test "$(json_field cell1_v)" = 4.061
check "cell 3 volts" test "$(json_field cell3_v)" = 4.055
check "cell 1 temperature" test "$(json_field cell1_c)" = 20
check "cell 3 temperature" test "$(json_field cell3_c)" = 22
check "CM4 CPU temperature from the same frame" test "$(json_field cpu_temp_c)" = 47.2
check "one JSON line" test "$(sh "$SH" cm4wide --json | wc -l | tr -d ' ')" = 1
fresh_ups
uframe cm4wide 20261120T175500Z null null '"ups":{"ok":false,"error":"stale"}'
check "stale: state says so" test "$(json_field state)" = "unknown stale"
check "stale: no numbers (null, not 0)" test "$(json_field cell1_v)" = None
check "stale: no charge" test "$(json_field charge_pct)" = None
check "no cpu_temp_c in the frame gives null" test "$(json_field cpu_temp_c)" = None
fresh_ups
uframe cm4wide 20261120T175500Z '"mains"' 100 '"ups":{"ok":true,"source":"mains","pct":100,"vin":15.2,"cells":[4.1,null],"temps":"bad"}'
check "short or bad lists give null, not an error" test "$(json_field cell2_v)/$(json_field cell3_v)/$(json_field cell1_c)" = "None/None/None"
check "a value that is there still comes through" test "$(json_field input_v)" = 15.2
fresh_ups
ha_fails "--json with no frame still prints nothing" "$SH" cm4wide --json
