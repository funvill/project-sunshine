# needs: 80_frame_age
# The evening's sky score for Home Assistant (2026-11-22): homeassistant/sunset_sky.sh, under sh and
# busybox sh. It reads the newest result pi/sunset-sky.py wrote to project_sunshine_sky/<camera>/.
SH="$HA/sunset_sky.sh"
fresh_sky() { W="$(mktemp -d)"; export SKY_BASE="$W"; mkdir -p "$W/cm4wide"; }
result() { printf '%s\n' "$2" > "$W/cm4wide/$1.json"; }

section "sky: the newest evening's score"
fresh_sky
result 2026-11-21 '{"score": 7, "label": "grey", "sunset_utc": "2026-11-22T00:23:00Z", "frames_scored": 61, "warm_sky_percent": 1.5, "best_frame": "cm4wide_20261122T000000Z.jpg"}'
result 2026-11-22 '{"score": 71, "label": "colourful", "sunset_utc": "2026-11-23T00:22:00Z", "frames_scored": 60, "warm_sky_percent": 14.2, "best_frame": "cm4wide_20261123T001500Z.jpg", "Sun": {"azimuth_deg": 1}}'
ha_out "score, date and details; nothing else from the file" \
  '{"best_frame": "cm4wide_20261123T001500Z.jpg", "date": "2026-11-22", "frames_scored": 60, "label": "colourful", "state": 71, "sunset_utc": "2026-11-23T00:22:00Z", "warm_sky_percent": 14.2}' \
  "$SH" cm4wide

section "sky: no score that evening"
fresh_sky
result 2026-11-22 '{"score": null, "label": "none", "frames_scored": 2, "reason": "2 readable frames, 6 needed"}'
ha_out "too few frames is none" \
  '{"best_frame": null, "date": "2026-11-22", "frames_scored": 2, "label": "none", "state": "none", "sunset_utc": null, "warm_sky_percent": null}' \
  "$SH" cm4wide
fresh_sky
result 2026-11-22 '{"score": 250, "label": "colourful"}'
ha_out "an impossible score is none, never a good sunset" \
  '{"best_frame": null, "date": "2026-11-22", "frames_scored": null, "label": "none", "state": "none", "sunset_utc": null, "warm_sky_percent": null}' \
  "$SH" cm4wide

section "sky: unreadable or missing"
fresh_sky
result 2026-11-21 '{"score": 40, "label": "some colour"}'
printf 'half a file' > "$W/cm4wide/2026-11-22.json"
ha_out "a broken newest file falls back to the one before" \
  '{"best_frame": null, "date": "2026-11-21", "frames_scored": null, "label": "some colour", "state": 40, "sunset_utc": null, "warm_sky_percent": null}' \
  "$SH" cm4wide
fresh_sky
: > "$W/cm4wide/.2026-11-22.json.tmp"
ha_fails "no result yet: unknown" "$SH" cm4wide
fresh_sky; rmdir "$W/cm4wide"
ha_fails "no folder: unknown" "$SH" cm4wide
ha_fails "bad camera name" "$SH" '../x'
unset SKY_BASE
