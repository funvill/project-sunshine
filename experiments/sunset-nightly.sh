#!/usr/bin/env bash
# Experiments 19 and 21, every evening: the sunset program (ev+0 and ev-2 with daylight white
# balance, ev-2 auto) for 45 minutes either side of tonight's sunset, so no sunset is shot
# without the ev-2 frame until production has the bracket (#10, decided 2026-11-16).
# Started by exp-sunset.timer at 23:00 UTC, before the earliest window of the year; it sleeps
# until 2 minutes before the window, so it doesn't hold the experiment lock all evening.
# Run names: sunset-YYYYMMDD on timelaps, cm4-sunset-YYYYMMDD on the CM4 (UTC date of sunset).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${NIGHTLY_ENV_FILE:-$HERE/../sunset.env}"
SUN_PY="${SUN_PY:-$HERE/../sunset-sun.py}"
RUNNER="${NIGHTLY_RUNNER:-$HERE/sunset-experiment.py}"
WINDOW_S=$((45 * 60))   # matches SUNSET_WINDOW_S in sunset-experiment.py
LEAD_S=120
MAX_AHEAD_S=$((6 * 3600))

set -a; source "$ENV_FILE"; set +a   # SITE_LAT / SITE_LON for the sun script, CAM_NAME
now="${NIGHTLY_NOW:-$(date +%s)}"
sunset="$(python3 "$SUN_PY" sunset --epoch)"
[[ "$sunset" =~ ^[0-9]+$ ]] || { echo "sunset-nightly: no sunset time from $SUN_PY: '$sunset'" >&2; exit 1; }
if (( sunset - now > MAX_AHEAD_S )); then
  echo "sunset-nightly: next sunset is $(( (sunset - now) / 60 )) min away, so tonight's window has passed; nothing to do"
  exit 0
fi
prefix=""; [[ "${CAM_NAME:-}" == cm4wide ]] && prefix="cm4-"
run="${prefix}sunset-$(date -u -d "@$sunset" +%Y%m%d)"
start=$(( sunset - WINDOW_S - LEAD_S ))
if [[ "${NIGHTLY_SLEEP:-1}" == 1 ]] && (( start > now )); then
  echo "sunset-nightly: $run, sleeping $(( (start - now) / 60 )) min until the window"
  sleep $(( start - now ))
fi
exec python3 "$RUNNER" sunset --run "$run" --sunset "$sunset" --until $(( sunset + WINDOW_S + 60 ))
