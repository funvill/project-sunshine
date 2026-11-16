# The NAS jobs for monitoring (issues #13 and #22): nas/sunset-verify.py and nas/sunset-health.py,
# their Python tests, and one end to end run: the jobs write their results, and the Home Assistant
# script reads them, under sh and busybox sh.
NAS="$(dirname "$SRC")/nas"

section "NAS jobs: verifier and daily health (Python tests)"
check "tests/test_verify.py" python3 -I "$HERE/test_verify.py"
check "tests/test_health.py" python3 -I "$HERE/test_health.py"

section "NAS jobs: written results are what Home Assistant reads"
W="$(mktemp -d)"
# Three frames of the wide camera on 2026-11-14 (UTC), real SHA-256 in each JSON, files settled long ago.
python3 -I - "$W/project_sunshine/wide" <<'PY'
import hashlib, json, os, sys
root = sys.argv[1]
folder = os.path.join(root, "2026", "11", "14")
os.makedirs(folder)
for stamp in ("20261114T120000Z", "20261114T120500Z", "20261114T121000Z"):
    jpg, dng = b"jpeg-" + stamp.encode(), b"dng-" + stamp.encode()
    data = {"Lux": 1000, "Sun": {"azimuth_deg": 200.0},
            "Capture": {"schema_version": 2, "kind": "auto", "schedule": "regular", "setup_id": "t-1",
                        "files": {"jpg": {"bytes": len(jpg), "sha256": hashlib.sha256(jpg).hexdigest()},
                                  "dng": {"bytes": len(dng), "sha256": hashlib.sha256(dng).hexdigest()}},
                        "settings": {"night_lux": 10, "raw": 1}},
            "System": {"cpu_temp_c": 50.0, "throttled": "0x0", "disk": {"used_pct": 40.0},
                       "outbox_pending": {"files": 1, "bytes": 1}}}
    for ext, body in (("json", json.dumps(data).encode()), ("jpg", jpg), ("dng", dng)):
        path = os.path.join(folder, "wide_%s.%s" % (stamp, ext))
        with open(path, "wb") as f:
            f.write(body)
        os.utime(path, (1700000000, 1700000000))
PY
CAMDIR="$W/project_sunshine/wide"
export FRAME_BASE="$W/project_sunshine" SUNSET_NOW="$(date -u -d '2026-11-15 12:00:00' +%s)"

python3 -I "$NAS/sunset-verify.py" "$CAMDIR" --now 2026-11-15T12:00:00Z >/dev/null; rc=$?
check "verifier exits 0 on a good archive" test "$rc" = 0
check "verifier wrote its result beside the camera folder" test -f "$W/project_sunshine/health/wide/verify.json"
ha_out "Home Assistant reads: archive ok" ok "$HA/sunset_result.sh" verify wide

python3 -I "$NAS/sunset-health.py" "$CAMDIR" --day 2026-11-14 --now 2026-11-15T02:00:00Z >/dev/null; rc=$?
check "health exits 0 even when it finds problems" test "$rc" = 0
check "health wrote the day and latest" test -f "$W/project_sunshine/health/wide/latest.json" -a -f "$W/project_sunshine/health/wide/2026-11-14.json"
ha_out "Home Assistant reads: 3 frames is a poor day" "regular_low gap small_jpeg" "$HA/sunset_result.sh" health wide

printf 'tampered' > "$CAMDIR/2026/11/14/wide_20261114T120500Z.jpg"
touch -d '2023-11-14 22:13:20' "$CAMDIR/2026/11/14/wide_20261114T120500Z.jpg"
python3 -I "$NAS/sunset-verify.py" "$CAMDIR" --now 2026-11-15T13:00:00Z >/dev/null; rc=$?
check "verifier exits non-zero on a changed JPEG" test "$rc" = 1
ha_out "Home Assistant reads: bad, with the count" "bad mismatched=1" "$HA/sunset_result.sh" verify wide
check "the bad path is in the result" grep -q '2026/11/14/wide_20261114T120500Z.jpg' "$W/project_sunshine/health/wide/verify.json"
check "the bad file was left alone" test "$(cat "$CAMDIR/2026/11/14/wide_20261114T120500Z.jpg")" = tampered
unset FRAME_BASE SUNSET_NOW
