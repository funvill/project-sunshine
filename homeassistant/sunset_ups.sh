#!/bin/sh
# The UPS state (issue #29) from the newest frame's JSON on the NAS: System.ups_source and
# System.ups_charge_pct, which pi/sunset-meta.py copies from the UPS monitor's status on the Pi.
# Prints one line:
#   mains 100      on mains, with the charge in percent (left out if the board didn't give one)
#   battery 87     on the cells
#   unknown <why>  the frame has no usable source: <why> is the monitor's error (e.g. stale), the
#                  unrecognised source, or "none"
# Prints nothing and exits 1 if there is no readable frame JSON in the last two UTC days or python3 is
# missing: Home Assistant shows that as unknown. The alert treats anything but "mains" as bad.
# Runs in Home Assistant's container: POSIX sh, with python3 (which that container has) for the JSON.
# Arguments: the camera name whose frames carry the UPS fields (cm4wide; cm4city has them too), and
# optionally --json: one JSON line for Home Assistant's graphs, with "state" (the line above) and the
# numbers: power (mains or battery), charge_pct, input_v, output_v, pack_v, cell1_v..cell3_v, cell1_c..cell3_c, from
# System.ups. A value the frame doesn't have is null, never 0, so a graph shows a gap, not a false drop.
CAM="${1:-cm4wide}"
MODE="${2:-}"
case "$CAM" in *[!A-Za-z0-9_-]*|"") echo "bad camera name: $CAM" >&2; exit 2 ;; esac
case "$MODE" in ""|--json) ;; *) echo "unknown option: $MODE" >&2; exit 2 ;; esac
ROOT="${FRAME_ROOT:-${FRAME_BASE:-/share/camera/project_sunshine}/$CAM}"
command -v python3 >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }
exec python3 -I - "$ROOT" "$CAM" "$MODE" <<'PY'
import json, os, re, sys, time

root, cam, mode = sys.argv[1], sys.argv[2], sys.argv[3]
now = float(os.environ.get("SUNSET_NOW") or time.time())
pattern = re.compile(r"^%s_(\d{8}T\d{6}Z)(_night)?\.json$" % re.escape(cam))
found = []
for t in (now, now - 86400):
    folder = os.path.join(root, time.strftime("%Y/%m/%d", time.gmtime(t)))
    try:
        names = os.listdir(folder)
    except OSError:
        continue
    found += [(m.group(1), bool(m.group(2)), folder, n) for n in names for m in [pattern.match(n)] if m]
found.sort(reverse=True)

data = None
for entry in found[:3]:     # the newest file can be half copied: try the next one
    try:
        with open(os.path.join(entry[2], entry[3]), "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict):
        break
    data = None
if data is None:
    sys.exit(1)

system = data.get("System") if isinstance(data.get("System"), dict) else {}
src = system.get("ups_source")
pct = system.get("ups_charge_pct")
pct = pct if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None
ups = system.get("ups") if isinstance(system.get("ups"), dict) else {}
if src in ("mains", "battery"):
    state = src if pct is None else "%s %g" % (src, pct)
else:
    why = src if isinstance(src, str) and src else ups.get("error") or "none"
    state = "unknown %s" % re.sub(r"\s+", "_", str(why))
if mode != "--json":
    print(state)
    sys.exit(0)


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def item(name, i):
    values = ups.get(name)
    return number(values[i]) if isinstance(values, list) and i < len(values) else None


ok = ups.get("ok") is True
out = {"state": state, "power": src if src in ("mains", "battery") else None, "charge_pct": pct,
       "input_v": number(ups.get("vin")) if ok else None,
       "output_v": number(ups.get("vout")) if ok else None,
       "pack_v": number(ups.get("vbat")) if ok else None}
for i in range(3):
    out["cell%d_v" % (i + 1)] = item("cells", i) if ok else None
for i in range(3):
    out["cell%d_c" % (i + 1)] = item("temps", i) if ok else None
print(json.dumps(out))
PY
