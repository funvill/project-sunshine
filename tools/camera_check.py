#!/usr/bin/env python3
"""Health check of the capture Pi: is every camera taking every frame, and is the Pi well?

    python tools/camera_check.py                 # last 12 hours
    python tools/camera_check.py --hours 24
    python tools/camera_check.py --host user@addr --no-images

Read-only. Over ssh it reads the logs, the timers and the machine's state, then copies the newest
regular frame of each camera to --out (default: sunset-camera-check in the temp folder; never this
repo, since frames don't go in it) with a quarter-size copy to look at. It prints one report and
exits 1 if anything needs a look (lines starting WARN), else 0.

Which Pi: --host, else SUNSET_SSH (comma-separated), else tools/camera_check.hosts, one user@host
per line, tried in order (e.g. wired first, then Wi-Fi). That file is git-ignored: the repo is
public and holds no LAN addresses.

Pictures come from the NAS share when the PC can reach it (--nas, else SUNSET_NAS, else a line
"nas <path>" in the hosts file: the PC's path to the folder that holds <cam>/YYYY/MM/DD), since the
Pi's Wi-Fi can be slow. A frame not on the NAS yet is copied from the Pi.

Per camera it counts the 5-minute slots in the window that have no frame (from the camera's first
frame in the window, so a camera started later isn't blamed), the dense frames, and every log line
that isn't "ok". A pause for the diag page shows as missing slots too; that is expected.
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTS_FILE = os.path.join(HERE, "camera_check.hosts")
SLOT_S = 300
UNITS = ["sunset-capture.timer", "sunset-dense.timer", "sunset-capture2.timer",
         "sunset-dense2.timer", "sunset-sync.timer", "sunset-diag.service"]

# Runs on the Pi. Prints sections that parse() splits on "### name".
REMOTE = r"""
S=~/sunset
echo "### now"; date -u +%Y-%m-%dT%H:%M:%SZ
echo "### uptime"; cut -d' ' -f1 /proc/uptime
echo "### units"; for u in UNITS; do echo "$u $(systemctl is-active $u 2>/dev/null) $(systemctl is-enabled $u 2>/dev/null)"; done
echo "### throttled"; vcgencmd get_throttled 2>/dev/null
echo "### temp"; vcgencmd measure_temp 2>/dev/null
echo "### disk"; df -P / | tail -n 1
# Only the window's lines: the Wi-Fi dongle can be slow (295 KB once took 42 s).
echo "### capture"; awk -v t="START" '$1 >= t' $S/capture.log 2>/dev/null
echo "### sync"; awk -v t="START" '$1 >= t' $S/sync.log 2>/dev/null
echo "### netwatch"; awk -v t="START" '$1 >= t' $S/netwatch.log 2>/dev/null
echo "### voltage"; grep -i 'under-voltage' $S/kernel.log 2>/dev/null | tail -n 3
echo "### pending"; find $S/outbox -path '*/.partial' -prune -o -type f -name '*.jpg' -size +0 -printf '%T@ %p\n' 2>/dev/null
echo "### empty"; find $S/outbox -path '*/.partial' -prune -o -type f -name '*.jpg' -size 0 -print 2>/dev/null
echo "### nas"; grep '^NAS_TARGET=' $S/sunset.env 2>/dev/null | cut -d= -f2-
echo "### newest"
# Newest regular frame still in the outbox, per camera (names are UTC, so it sorts last).
for c in $(awk -v t="START" '$1 >= t' $S/capture.log | grep -o 'cam=[A-Za-z0-9_-]*' | sort -u | cut -d= -f2); do
  f=$(find $S/outbox/$c -type f -name "${c}_*Z.jpg" -size +0 2>/dev/null | awk -F/ '{print $NF" "$0}' | sort | tail -n 1 | cut -d' ' -f2-)
  echo "$c $f"
done
""".replace("UNITS", " ".join(UNITS))


def parse(text):
    out, name = {}, None
    for line in text.splitlines():
        if line.startswith("### "):
            name = line[4:].strip()
            out[name] = []
        elif name:
            out[name].append(line)
    return out


def ts(word):
    try:
        return dt.datetime.strptime(word, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def capture_summary(lines, now, hours):
    """Per camera: regular and dense counts, missing 5-min slots, lines that aren't ok."""
    start = now - dt.timedelta(hours=hours)
    cams = {}
    for line in lines:
        w = line.split()
        if len(w) < 2 or not w[1].startswith("cam="):
            continue
        t = ts(w[0])
        if t is None or t < start:
            continue
        c = cams.setdefault(w[1][4:], {"slots": set(), "dense": 0, "bad": [], "first": t, "last": None})
        if not line.rstrip().endswith(" ok"):
            c["bad"].append(line.strip())
            continue
        if " dense " in line:
            c["dense"] += 1
        else:
            c["slots"].add(int(t.timestamp()) // SLOT_S)
            c["last"] = t
    for c in cams.values():
        first = int(c["first"].timestamp()) // SLOT_S
        # The current slot may not have been taken yet; don't count it.
        last = (int(now.timestamp()) - 60) // SLOT_S
        missing = [s for s in range(first, last + 1) if s not in c["slots"]]
        c["expected"] = max(0, last - first + 1)
        c["missing"] = runs(missing)
    return cams


def runs(slots):
    """[s, s+1, s+2, t] -> [(start, end, n)] as UTC datetimes."""
    out = []
    for s in slots:
        if out and s == out[-1][1] + 1:
            out[-1] = (out[-1][0], s, out[-1][2] + 1)
        else:
            out.append((s, s, 1))
    f = lambda s: dt.datetime.fromtimestamp(s * SLOT_S, dt.timezone.utc)
    return [(f(a), f(b), n) for a, b, n in out]


try:
    from zoneinfo import ZoneInfo
    VAN_TZ = ZoneInfo("America/Vancouver")
except Exception:                       # no tzdata on this machine
    VAN_TZ = None


def van(t):
    """UTC -> Vancouver wall time. BC is on UTC-7 all year from 2026 (tzdata 2026b on); without
    tzdata, a fixed UTC-7, which is right for the whole project (it starts after the change)."""
    if VAN_TZ is not None:
        return t.astimezone(VAN_TZ)
    return t.astimezone(dt.timezone(dt.timedelta(hours=-7)))


def hm(t):
    return "%s UTC (%s Vancouver)" % (t.strftime("%H:%M"), van(t).strftime("%H:%M"))


def image_stats(path, out_dir):
    try:
        import cv2
    except ImportError:
        return None
    im = cv2.imread(path)
    if im is None:
        return None
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    band = g[int(h * .3):int(h * .55), w // 4:3 * w // 4]
    small = os.path.join(out_dir, os.path.basename(path)[:-4] + "_small.jpg")
    cv2.imwrite(small, cv2.resize(im, (w // 4, h // 4)))
    return {"mean": g.mean(), "clip": (g >= 250).mean() * 100,
            "sharp": cv2.Laplacian(band, cv2.CV_64F).var(), "small": small}


def config():
    """(hosts, nas) from tools/camera_check.hosts: user@host lines, and an optional 'nas <path>'."""
    hosts, nas = [], None
    if os.path.exists(HOSTS_FILE):
        with open(HOSTS_FILE) as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith("#"):
                    continue
                if l.startswith("nas "):
                    nas = l[4:].strip()
                else:
                    hosts.append(l)
    return hosts, nas


def hosts(arg):
    if arg:
        return [arg]
    if os.environ.get("SUNSET_SSH"):
        return [h.strip() for h in os.environ["SUNSET_SSH"].split(",") if h.strip()]
    if config()[0]:
        return config()[0]
    sys.exit("No Pi to check: pass --host, set SUNSET_SSH, or list user@host lines in " + HOSTS_FILE)


def nas_newest(nas, cam, now):
    """Newest regular frame of cam on the NAS (today's or yesterday's UTC folder), or None."""
    pat = re.compile(r"^%s_\d{8}T\d{6}Z\.jpg$" % re.escape(cam))
    for day in (now, now - dt.timedelta(days=1)):
        d = os.path.join(nas, cam, day.strftime("%Y"), day.strftime("%m"), day.strftime("%d"))
        try:
            names = sorted(n for n in os.listdir(d) if pat.match(n))
        except OSError:
            continue
        if names:
            return os.path.join(d, names[-1])
    return None


SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host")
    ap.add_argument("--hours", type=float, default=12)
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "sunset-camera-check"))
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--nas", help="PC path to the NAS folder holding <cam>/YYYY/MM/DD")
    a = ap.parse_args()

    host, res = None, None
    for h in hosts(a.host):
        # Bytes, not text: on Windows text mode would send CRLF line ends to bash.
        start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=a.hours + 0.1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = subprocess.run(SSH + [h, "bash -s"], input=REMOTE.replace("START", start).encode(),
                           capture_output=True)
        out = r.stdout.decode("utf-8", "replace")
        if r.returncode == 0 and "### now" in out:
            host, res = h, out
            break
        err = r.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"]
        print("(no answer from %s: %s)" % (h, err[-1]))
    if not host:
        print("WARN cannot reach the Pi")
        return 1
    d = parse(res)
    now = ts(d["now"][0])
    warn = []
    print("Camera check  %s  via %s  (last %g h)" % (hm(now), host, a.hours))

    up = float(d["uptime"][0]) if d.get("uptime") else 0
    thr = (d.get("throttled") or ["?"])[0].replace("throttled=", "")
    temp = (d.get("temp") or ["?"])[0].replace("temp=", "")
    disk = (d.get("disk") or [""])[0].split()
    used = disk[4] if len(disk) > 4 else "?"
    print("\nPi: up %dh %02dm, throttled=%s, %s, disk %s" % (up // 3600, up % 3600 // 60, thr, temp, used))
    if thr not in ("0x0", "?"):
        warn.append("throttled=%s (bit 0 undervoltage now, 16 since boot; 2/18 throttled; 3/19 soft limit)" % thr)
    m = re.match(r"([\d.]+)", temp)
    if m and float(m.group(1)) >= 70:
        warn.append("SoC at %s" % temp)
    if used.rstrip("%").isdigit() and int(used.rstrip("%")) >= 80:
        warn.append("disk %s full" % used)
    for l in d.get("voltage", []):
        print("  kernel: " + l.strip())

    units = {}
    for l in d.get("units", []):
        w = l.split()
        if len(w) >= 2:
            units[w[0]] = (w[1], w[2] if len(w) > 2 else "")
    diag = units.get("sunset-diag.service", ("",))[0] == "active"
    print("Timers: " + ", ".join("%s %s" % (u.replace("sunset-", "").replace(".timer", ""), s)
                                  for u, (s, e) in units.items() if u.endswith(".timer") and e != "not-found"))
    if diag:
        warn.append("diag page is running, so capture is paused (`diag stop` to resume)")
    for u, (s, e) in units.items():
        if u.endswith(".timer") and e == "enabled" and s != "active" and not diag:
            warn.append("%s is enabled but %s" % (u, s))

    cams = capture_summary(d.get("capture", []), now, a.hours)
    print("\nCameras:")
    for name, c in sorted(cams.items()):
        got = c["expected"] - sum(n for _, _, n in c["missing"])
        age = (now - c["last"]).total_seconds() / 60 if c["last"] else None
        print("  %-8s %d/%d slots since %s, %d dense, newest %s" % (
            name, got, c["expected"], hm(c["first"]), c["dense"],
            "%.0f min ago" % age if age is not None else "none"))
        for a0, a1, n in c["missing"]:
            print("           missing %s to %s (%d)" % (hm(a0), a1.strftime("%H:%M"), n))
        for l in c["bad"][-5:]:
            print("           " + l)
        if c["missing"]:
            warn.append("%s missed %d slots" % (name, sum(n for _, _, n in c["missing"])))
        if c["bad"]:
            warn.append("%s has %d log lines that aren't ok" % (name, len(c["bad"])))
        if age is None or age > 11:
            warn.append("%s newest frame is %s" % (name, "missing" if age is None else "%.0f min old" % age))

    start = now - dt.timedelta(hours=a.hours)
    sync = [l for l in d.get("sync", []) if (ts(l.split()[0]) or start) > start] if d.get("sync") else []
    failed = [l for l in sync if "FAILED" in l]
    pend = []
    for l in d.get("pending", []):
        w = l.split(" ", 1)
        try:
            pend.append(float(w[0]))
        except ValueError:
            pass
    oldest = (now.timestamp() - min(pend)) / 60 if pend else 0
    print("\nSync: %d runs, %d failed; %d frames waiting on the Pi%s; last: %s" % (
        len(sync), len(failed), len(pend), ", oldest %.0f min" % oldest if pend else "",
        sync[-1] if sync else "none in window"))
    for l in failed[-3:]:
        print("  " + l[:200])
    if failed:
        warn.append("%d sync runs failed" % len(failed))
    empty = d.get("empty", [])
    if empty:
        print("  %d empty frame file(s) left on the Pi (sync skips them): %s" % (
            len(empty), ", ".join(os.path.basename(x) for x in empty[:4])))
    if oldest > 30:
        warn.append("oldest unsynced frame is %.0f min old" % oldest)

    net = [l for l in d.get("netwatch", []) if l.split() and (ts(l.split()[0]) or start) > start]
    print("Network watchdog: %d events" % len(net))
    for l in net[-6:]:
        t = ts(l.split()[0])
        print("  %s %s" % (hm(t) if t else "", l.split(" ", 1)[1] if " " in l else ""))
    drops = sum(1 for l in net if "network back" in l)
    if drops >= 4:
        warn.append("network dropped %d times (%.1f an hour)" % (drops, drops / a.hours))
    if any(re.search(r"reboot|reset", l) for l in net):
        warn.append("network watchdog reset the dongle or rebooted")

    if not a.no_images:
        import shutil
        nas = a.nas or os.environ.get("SUNSET_NAS") or config()[1]
        os.makedirs(a.out, exist_ok=True)
        print("\nNewest frames (copied to %s):" % a.out)
        for l in d.get("newest", []):
            w = l.split(" ", 1)
            cam, pi_path = w[0], (w[1].strip() if len(w) > 1 else "")
            on_nas = nas_newest(nas, cam, now) if nas else None
            # The NAS copy is at most a sync behind the Pi's newest, and much quicker to fetch.
            pick = ("NAS", on_nas) if on_nas else ("Pi", pi_path) if pi_path else None
            if not pick:
                print("  %s: no frame found" % cam)
                continue
            local = os.path.join(a.out, os.path.basename(pick[1]))
            if pick[0] == "NAS":
                shutil.copyfile(pick[1], local)
            else:
                r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "%s:%s" % (host, pick[1]), local],
                                   capture_output=True, text=True)
                if r.returncode:
                    print("  %s: copy failed: %s" % (cam, r.stderr.strip()))
                    continue
            s_ = image_stats(local, a.out)
            if s_:
                print("  %-8s %s (from %s)  mean %.0f, clipped %.1f%%, sharpness %.0f  -> %s" % (
                    cam, os.path.basename(local), pick[0], s_["mean"], s_["clip"], s_["sharp"], s_["small"]))
            else:
                print("  %-8s %s (from %s; no OpenCV, no stats)" % (cam, local, pick[0]))

    print()
    for x in warn:
        print("WARN " + x)
    print("All OK" if not warn else "%d to look at" % len(warn))
    return 1 if warn else 0


if __name__ == "__main__":
    sys.exit(main())
