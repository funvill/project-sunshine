# The Home Assistant package beyond grep: homeassistant/sunset.yaml.
# Always: every script a command names exists, and every script is used. With PyYAML: the file parses
# (the !secret tag is accepted), alerts watch sensors that exist, the sensors read entities that exist,
# the re-arm automation covers every alert, ids are unique. With PyYAML and jinja2 as well: the binary
# sensors' templates and the alerts' messages are rendered with stand-in states() and is_number(), and
# the true/false answers are checked, so "unknown counts as bad" is tested, not just grepped.
section "Home Assistant package: scripts it names exist, and all are used"
used="$(grep -Eo 'sunset_[a-z_]+\.sh' "$HA/sunset.yaml" | sort -u)"
for s in $used; do check "$s exists" test -f "$HA/$s"; done
for f in "$HA"/*.sh; do
  check "$(basename "$f") is used by sunset.yaml" grep -q "$(basename "$f")" "$HA/sunset.yaml"
done
check "no phone notifier name in the package (placeholder only)" bash -c "! grep -E '^[[:space:]]*- mobile_app_' '$HA/sunset.yaml'"

section "Home Assistant package: parsed"
# Not -I: PyYAML and jinja2 often live in the user site-packages, which -I hides. cwd is homeassistant/, which holds no .py.
out="$(cd "$HA" && HA="$HA" python3 - <<'PY'
import os, re, sys
ha = os.environ["HA"]
try:
    import yaml
except ImportError:
    print("SKIP PyYAML is not installed: YAML structure checks skipped")
    sys.exit(0)


class Loader(yaml.SafeLoader):
    pass


Loader.add_multi_constructor("!", lambda loader, tag, node: "<%s %s>" % (tag, loader.construct_scalar(node)))


def load(name):
    with open(os.path.join(ha, name), encoding="utf-8") as f:
        return yaml.load(f, Loader)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def result(ok, text):
    print(("OK " if ok else "FAIL ") + text)


main = load("sunset.yaml")
result(isinstance(main, dict), "the file parses as a YAML mapping")

sensors = {}
for entry in main["command_line"]:
    s = entry["sensor"]
    sensors["sensor." + slug(s["name"])] = s
binaries = {}
for b in main["template"][0]["binary_sensor"]:
    binaries["binary_sensor." + slug(b["name"])] = b
numbers = {"input_number." + k: v for k, v in main["input_number"].items()}
alerts = main["alert"]

uids = [s["unique_id"] for s in sensors.values()] + [b["unique_id"] for b in binaries.values()]
result(len(uids) == len(set(uids)), "unique_ids are unique")
result(all(sc["unique_id"] == slug(sc["name"]) for sc in sensors.values()), "sensor unique_id matches its name")
result(all(b["unique_id"] == slug(b["name"]) for b in binaries.values()), "binary sensor unique_id matches its name")

cmd_ok = True
for eid, sc in sensors.items():
    m = re.match(r"^(?:[A-Z_]+=\S+ )*sh /config/sunset/(sunset_[a-z_]+\.sh)(?: (.*))?$", sc["command"])
    if not m or not os.path.isfile(os.path.join(ha, m.group(1))):
        cmd_ok = False
        print("FAIL command of %s: %s" % (eid, sc["command"]))
result(cmd_ok, "every sensor command is 'sh /config/sunset/<script that exists>'")
result(all("command_timeout" in s and "scan_interval" in s for s in sensors.values()), "every sensor has a timeout and a scan interval")

# Each camera has its own sensor of each kind. timelaps (wide) was retired on 2026-11-17 and its checks
# removed. The NAS archive check, daily health and daily video sensors were removed on 2026-11-22: those
# jobs never ran, and Home Assistant's installed copy already left them out.
for script in ("sunset_camera_health.sh", "sunset_frame_age.sh"):
    cams = [s["command"].split()[-1] for s in sensors.values() if script in s["command"]]
    result(sorted(cams) == ["cm4city", "cm4wide"], "%s has one sensor per camera (%s)" % (script, ",".join(cams)))

watched = set()
for key, a in alerts.items():
    watched.add(a["entity_id"])
    result(a["entity_id"] in binaries, "alert %s watches a binary sensor that exists" % key)
    result("persistent_notification" in a["notifiers"] and a.get("repeat"), "alert %s notifies and repeats" % key)
    result(a.get("can_acknowledge") is True, "alert %s can be acknowledged (re-armed by the automation)" % key)
result(watched == set(binaries), "every binary sensor has an alert")

reads_ok = True
for eid, b in binaries.items():
    for ref in re.findall(r"(?:binary_sensor|sensor|input_number)\.[a-z0-9_]+", b["state"]):
        if ref not in sensors and ref not in numbers:
            reads_ok = False
            print("FAIL %s reads %s, which is not defined" % (eid, ref))
    if "delay_on" not in b:
        reads_ok = False
        print("FAIL %s has no delay_on" % eid)
result(reads_ok, "binary sensors read defined entities and all have delay_on")

# The UPS numbers: template sensors reading attributes the UPS sensor really lists, with units.
ups_sensor = sensors["sensor.sunset_ups"]
result("--json" in ups_sensor["command"] and ups_sensor.get("value_template") == "{{ value_json.state }}",
       "the UPS sensor reads --json and keeps the plain line as its state")
numbers_t = [x for t in main["template"] for x in t.get("sensor", [])]
result(len(numbers_t) == 11, "eleven number sensors (UPS charge, 3 voltages, 3 cells x volts and temperature; CM4 CPU temperature)")
for t in numbers_t:
    attr = re.findall(r"state_attr\('sensor\.sunset_ups', '([a-z0-9_]+)'\)", t["state"])
    ok_attr = len(attr) == 1 and attr[0] in ups_sensor["json_attributes"] and attr[0] in t.get("availability", "")
    result(ok_attr and t.get("unit_of_measurement") and t.get("state_class") == "measurement"
           and t["unique_id"] == slug(t["name"]), "UPS number %s reads a listed attribute, has a unit, is graphed" % t["name"])
allids = uids + [t["unique_id"] for t in numbers_t]
result(len(allids) == len(set(allids)), "unique_ids are unique, the number sensors included")

auto = [a for a in main["automation"] if a["id"] == "sunset_unacknowledge_alerts"][0]
covered = set(auto["trigger"][0]["entity_id"])
result(covered == {"alert." + k for k in alerts}, "the re-arm automation covers every alert")
result(auto["trigger"][0]["to"] == "idle" and auto["trigger"][0]["for"] == "12:00:00", "re-arm after 12 h acknowledged")
result(auto["action"][0]["service"] == "alert.turn_on", "re-arm calls alert.turn_on")

result(main["input_number"]["sunset_min_free_gb"]["initial"] == 100, "free-space limit starts at 100 GB")
result(sorted(sensors) == ["sensor.sunset_cm4_camera_health", "sensor.sunset_cm4_newest_frame_age",
                           "sensor.sunset_cm4city_camera_health", "sensor.sunset_cm4city_newest_frame_age",
                           "sensor.sunset_nas_free_space", "sensor.sunset_ups"],
       "the command-line sensors are the installed set (frame age, health, NAS space, UPS)")

# ---- Templates, if jinja2 is here ----
try:
    import jinja2
except ImportError:
    print("SKIP jinja2 is not installed: template rendering checks skipped")
    sys.exit(0)

env = jinja2.Environment()


def render(template, states):
    def state(entity):
        return states.get(entity, "unknown")

    def is_number(value):
        try:
            float(value)
            return value not in ("nan", "inf")
        except (TypeError, ValueError):
            return False
    return env.from_string(template).render(states=state, is_number=is_number).strip()


def truth(entity, states):
    return render(binaries[entity]["state"], states) == "True"


limit = {"input_number.sunset_min_free_gb": "350.0", "input_number.sunset_max_frame_age": "60.0"}


def with_state(sensor, value):
    st = dict(limit)
    st[sensor] = value
    return st


free = "binary_sensor.sunset_nas_space_low"
for value, want in (("100", True), ("349", True), ("350", False), ("5000", False), ("unknown", True), ("unavailable", True), ("", True)):
    result(truth(free, with_state("sensor.sunset_nas_free_space", value)) is want, "NAS space low with free=%r is %s" % (value, want))
result(truth(free, limit) is True, "NAS space low when the sensor does not exist yet")

for entity, sensor in (("binary_sensor.sunset_cm4_camera_unhealthy", "sensor.sunset_cm4_camera_health"),
                       ("binary_sensor.sunset_cm4city_camera_unhealthy", "sensor.sunset_cm4city_camera_health")):
    for value, want in (("ok", False), ("undervoltage temp=80", True), ("stale", True), ("unreadable", True),
                        ("unknown", True), ("unavailable", True), ("OK", True), ("", True)):
        result(truth(entity, with_state(sensor, value)) is want, "%s with %r is %s" % (entity, value, want))

ups = "binary_sensor.sunset_ups_on_battery"
for value, want in (("mains 100", False), ("mains", False), ("battery 87", True), ("battery", True),
                    ("unknown stale", True), ("unknown none", True), ("unknown", True), ("unavailable", True), ("", True)):
    result(truth(ups, with_state("sensor.sunset_ups", value)) is want, "UPS on battery with %r is %s" % (value, want))
for value in ("battery 87", "battery", "unknown stale", "unknown"):
    text = render(alerts["sunset_ups_on_battery"]["message"], with_state("sensor.sunset_ups", value))
    result(("87%" in text) if value == "battery 87" else len(text) > 20, "UPS alert message for %r" % value)

for entity, sensor in (("binary_sensor.sunset_cm4_frames_stale", "sensor.sunset_cm4_newest_frame_age"),
                       ("binary_sensor.sunset_cm4city_frames_stale", "sensor.sunset_cm4city_newest_frame_age")):
    for value, want in (("0", False), ("60", False), ("61", True), ("unknown", True), ("unavailable", True)):
        result(truth(entity, with_state(sensor, value)) is want, "%s with age %r is %s" % (entity, value, want))

for key, a in alerts.items():
    for values in ({}, {"sensor.sunset_nas_free_space": "128", "sensor.sunset_cm4_newest_frame_age": "75"}):
        try:
            text = render(a["message"], dict(limit, **values))
            result(len(text) > 20, "alert %s message renders" % key)
        except jinja2.TemplateError as e:
            result(False, "alert %s message does not render: %s" % (key, e))
PY
)"
while IFS= read -r line; do
  case "$line" in
    "OK "*) ok ;;
    "FAIL "*) bad "${line#FAIL }" ;;
    "SKIP "*) echo "  SKIP: ${line#SKIP }" ;;
    "") ;;
    *) bad "unexpected output: $line" ;;
  esac
done <<< "$out"
check "the YAML checks produced results" test -n "$out"
