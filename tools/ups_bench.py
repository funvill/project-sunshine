#!/usr/bin/env python3
"""Bench-test the UPS reader against the real OpenUPS2 before it goes on the CM4.

    sudo python3 tools/ups_bench.py --minutes 20
    sudo python3 tools/ups_bench.py --minutes 20 --low-cell 3.8      # make the low-battery event trip

Runs on Linux with the UPS on USB (on the PC: WSL with the UPS passed through by usbipd-win).
It runs pi/sunset-ups.py --run with bench settings, writing only into --dir (never ~/sunset or
/run), and never pauses any timer (UPS_PAUSE=0, so a low battery is only logged). While it runs,
unplug and replug the DC adapter or the USB lead to see the events. Ctrl+C stops it early.
At the end it prints a summary of the log: line counts, every event, and the cell, pack and
temperature ranges seen. It warns if a present cell is below 2.5 V (over-discharged Li-ion:
take it out, don't charge it).
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
READER = os.path.join(os.path.dirname(HERE), "pi", "sunset-ups.py")
DEAD_CELL_V = 2.5


def parse(line):
    """'<ts> TAG k=v k=v' -> (ts, tag, {k: v}). The tag is every word before the first k=v."""
    words = line.split()
    if not words:
        return None
    ts, rest = words[0], words[1:]
    tag, fields = [], {}
    for w in rest:
        if "=" in w and re.match(r"^[a-z_]+=", w):
            k, v = w.split("=", 1)
            fields[k] = v
        elif not fields:
            tag.append(w)
    return ts, " ".join(tag), fields


def log_lines(d):
    names = sorted((n for n in os.listdir(d) if n.startswith("ups.log")),
                   key=lambda n: -int(n.rsplit(".", 1)[1]) if n[-1].isdigit() else 0)
    for n in names:  # oldest rotated file first, live file last
        with open(os.path.join(d, n), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield line.rstrip("\n")


def num_list(v):
    try:
        return [float(x) for x in v.split(",")]
    except ValueError:
        return []


def summarise(d):
    counts, events, cells, packs, temps, warn = {}, [], [], [], [], {}
    for line in log_lines(d):
        p = parse(line)
        if not p:
            continue
        ts, tag, f = p
        kind = tag.split()[0] if tag else "?"
        counts[kind] = counts.get(kind, 0) + 1
        if kind in ("EVENT", "CHANGE"):
            events.append(line if kind == "EVENT" else "%s %s" % (ts, tag))
        present = f.get("present", "")
        cv = num_list(f.get("cells", ""))
        for i, v in enumerate(cv):
            if i < len(present) and present[i] == "1":
                cells.append(v)
                if v < DEAD_CELL_V and v < warn.get("ABC"[i], (99, ""))[0]:
                    warn["ABC"[i]] = (v, ts)
        if "vbat" in f:
            packs.append(float(f["vbat"]))
        temps += num_list(f.get("t", ""))

    print("\n== Summary of %s" % d)
    print("lines: " + ", ".join("%s %d" % kv for kv in sorted(counts.items())))
    print("events and changes:" if events else "events and changes: none")
    for e in events:
        print("  " + e)
    if cells:
        print("present cells: %.2f to %.2f V" % (min(cells), max(cells)))
    else:
        print("present cells: none seen")
    if packs:
        print("pack: %.2f to %.2f V" % (min(packs), max(packs)))
    if temps:
        print("temperatures: %d to %d C" % (min(temps), max(temps)))
    try:
        with open(os.path.join(d, "status.json")) as f:
            print("last status: " + f.read().strip())
    except OSError:
        pass
    for c, (v, ts) in sorted(warn.items()):
        print("WARNING: cell %s read %.2f V (%s), below %.1f V: over-discharged, take it out and don't charge it"
              % (c, v, ts, DEAD_CELL_V))
    return 1 if warn else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--minutes", type=float, default=10, help="how long to run (default 10)")
    ap.add_argument("--dir", default="/root/ups-bench", help="where the log and status go (emptied first)")
    ap.add_argument("--poll", type=float, default=2, help="seconds between readings (production: 10)")
    ap.add_argument("--keyframe", type=float, default=600, help="seconds between keyframes (production: 14400)")
    ap.add_argument("--low-cell", type=float, default=3.45, help="low-battery cell voltage (production: 3.45)")
    ap.add_argument("--summary-only", action="store_true", help="just summarise an earlier run in --dir")
    a = ap.parse_args(argv)

    if a.summary_only:
        return summarise(a.dir)
    if not sys.platform.startswith("linux"):
        sys.exit("run this on Linux (on the PC: in WSL, with the UPS attached by usbipd-win)")
    os.makedirs(a.dir, exist_ok=True)
    for n in os.listdir(a.dir):
        if n.startswith("ups.log") or n in ("status.json", "paused", "reader.out"):
            os.remove(os.path.join(a.dir, n))
    env = dict(os.environ,
               UPS_LOG_FILE=os.path.join(a.dir, "ups.log"),
               UPS_STATUS_FILE=os.path.join(a.dir, "status.json"),
               UPS_PAUSE_FLAG=os.path.join(a.dir, "paused"),
               UPS_PAUSE="0",
               UPS_POLL_S=str(a.poll), UPS_KEYFRAME_S=str(a.keyframe),
               UPS_LOW_CELL_V=str(a.low_cell))
    print("bench: %g min, poll %gs, keyframe %gs, low cell %.2f V, pause off, files in %s"
          % (a.minutes, a.poll, a.keyframe, a.low_cell, a.dir))
    print("unplug and replug the adapter or the USB lead now to see events; Ctrl+C stops early")
    with open(os.path.join(a.dir, "reader.out"), "w") as out:
        proc = subprocess.Popen([sys.executable, "-I", READER, "--run"], env=env, stdout=out, stderr=out)
        try:
            end = time.time() + a.minutes * 60
            while time.time() < end and proc.poll() is None:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            proc.wait(10)
    if proc.returncode not in (0, None, -signal.SIGTERM):
        with open(os.path.join(a.dir, "reader.out")) as f:
            print("reader exited with %s:\n%s" % (proc.returncode, f.read()))
    return summarise(a.dir)


if __name__ == "__main__":
    sys.exit(main())
