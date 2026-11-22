# needs: 80_frame_age
# The daily video record and the NAS job results, as Home Assistant reads them:
# homeassistant/sunset_daily_status.sh and homeassistant/sunset_result.sh, under sh and busybox sh.
fresh_ha() { W="$(mktemp -d)"; export FRAME_BASE="$W" SUNSET_NOW="$(date -u -d '2026-11-15 12:00:00' +%s)"; mkdir -p "$W/daily" "$W/health/wide" "$W/health/cm4wide"; }
daily() { printf '%s\n' "$2" > "$W/daily/$1.json"; }   # daily <date> <json text>
DS="$HA/sunset_daily_status.sh"
RS="$HA/sunset_result.sh"

section "daily video status: the newest record's status and age"
fresh_ha
daily 2026-11-14 '{"local_date":"2026-11-14","status":"encoded","posted":false,"schema_version":2}'
ha_out "encoded is ok" "ok 2026-11-14 1d" "$DS"
daily 2026-11-14 '{"status":"skipped","reason":"only 100 of 288 expected frames"}'
ha_out "skipped is reported" "skipped 2026-11-14 1d" "$DS"
daily 2026-11-14 '{"status":"failed","reason":"ffmpeg exited 1"}'
ha_out "failed is reported" "failed 2026-11-14 1d" "$DS"
daily 2026-11-14 '{"status":"published"}'
ha_out "a status nobody has taught the script is bad" "unknown_status_published 2026-11-14 1d" "$DS"
daily 2026-11-14 '{"status":"we do; rm -rf /"}'
ha_out "an odd status is cleaned up, not echoed" "unknown_status_wedorm-rf 2026-11-14 1d" "$DS"
daily 2026-11-13 '{"status":"encoded"}'
daily 2026-11-14 '{"status":"failed"}'
ha_out "the newest record wins" "failed 2026-11-14 1d" "$DS"

section "daily video status: age and unreadable records"
fresh_ha
daily 2026-11-13 '{"status":"encoded"}'
ha_out "two days old is still normal" "ok 2026-11-13 2d" "$DS"
daily 2026-11-12 '{"status":"encoded"}'; rm "$W/daily/2026-11-13.json"
ha_out "three days old is stale" "stale 2026-11-12 3d" "$DS"
export MAX_AGE_DAYS=5
ha_out "the limit is a setting" "ok 2026-11-12 3d" "$DS"
unset MAX_AGE_DAYS
fresh_ha
printf 'not json' > "$W/daily/2026-11-14.json"
ha_out "not JSON" "unreadable 2026-11-14 1d" "$DS"
daily 2026-11-14 '[1,2]'
ha_out "not an object" "unreadable 2026-11-14 1d" "$DS"
daily 2026-11-14 '{"frames":5}'
ha_out "no status" "unreadable 2026-11-14 1d" "$DS"
daily 2026-11-14 '{"status":7}'
ha_out "status that is not text" "unreadable 2026-11-14 1d" "$DS"
: > "$W/daily/2026-11-14.json"
ha_out "empty file" "unreadable 2026-11-14 1d" "$DS"

section "daily video status: other files, and no answer"
fresh_ha
daily 2026-11-14 '{"status":"encoded"}'
: > "$W/daily/2026-11-14.mp4"; : > "$W/daily/2026-11-14.txt"; : > "$W/daily/2026-11-14_check.jpg"
printf '{"status":"failed"}' > "$W/daily/crop.json"; printf '{"status":"failed"}' > "$W/daily/2026-11-15.json.tmp"
ha_out "only date-named records count" "ok 2026-11-14 1d" "$DS"
rm "$W/daily/2026-11-14.json"
ha_fails "no record yet" "$DS"
rm -r "$W/daily"
ha_fails "no daily folder" "$DS"

section "job results: the archive verifier"
fresh_ha
vjson() { printf '{"last_run_utc":"%s","ok":%s,"problem_counts":%s}\n' "$1" "$2" "$3" > "$W/health/${4:-wide}/verify.json"; }
vjson 2026-11-15T02:00:00Z true '{"missing":0,"mismatched":0,"zero_length":0,"unreadable_json":0,"other":0}'
ha_out "clean" ok "$RS" verify wide
vjson 2026-11-15T02:00:00Z false '{"missing":1,"mismatched":2,"zero_length":0,"unreadable_json":0,"other":0}'
ha_out "bad, with the counts that are not zero" "bad missing=1 mismatched=2" "$RS" verify wide
vjson 2026-11-12T02:00:00Z true '{"missing":0}'
ha_out "not run for 3 days is stale" stale "$RS" verify wide
ha_out "the age limit is an argument" ok "$RS" verify wide 96
vjson 2026-11-15T02:00:00Z true '{"missing":0}' cm4wide
ha_out "each camera has its own file" ok "$RS" verify cm4wide
printf 'garbage' > "$W/health/wide/verify.json"
ha_out "not JSON" unreadable "$RS" verify wide
printf '{"last_run_utc":"2026-11-15T02:00:00Z","problem_counts":{}}' > "$W/health/wide/verify.json"
ha_out "no ok field" unreadable "$RS" verify wide
printf '{"last_run_utc":"yesterday","ok":true,"problem_counts":{}}' > "$W/health/wide/verify.json"
ha_out "a time that does not parse" unreadable "$RS" verify wide
printf '{"last_run_utc":"2026-11-15T02:00:00Z","ok":"yes","problem_counts":{}}' > "$W/health/wide/verify.json"
ha_out "ok that is not a boolean" unreadable "$RS" verify wide
rm "$W/health/wide/verify.json"
ha_fails "no result yet" "$RS" verify wide

section "job results: the daily health record"
fresh_ha
hjson() { printf '{"generated_utc":"%s","day_utc":"2026-11-14","problems":%s}\n' "$1" "$2" > "$W/health/${3:-wide}/latest.json"; }
hjson 2026-11-15T02:00:00Z '[]'
ha_out "no problems" ok "$RS" health wide
hjson 2026-11-15T02:00:00Z '["regular_low","gap"]'
ha_out "problem names" "regular_low gap" "$RS" health wide
hjson 2026-11-12T02:00:00Z '[]'
ha_out "no new record for 3 days is stale, even if it was clean" stale "$RS" health wide
printf '{"generated_utc":"2026-11-15T02:00:00Z","problems":"none"}' > "$W/health/wide/latest.json"
ha_out "problems that is not a list" unreadable "$RS" health wide
rm "$W/health/wide/latest.json"
ha_fails "no record yet" "$RS" health wide
ha_fails "an unknown kind" "$RS" nonsense wide
ha_fails "a bad camera name" "$RS" health 'a/../b'
ha_fails "a bad age" "$RS" health wide 'x; rm'
unset FRAME_BASE SUNSET_NOW
