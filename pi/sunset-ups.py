#!/usr/bin/env python3
"""Mini-Box OpenUPS2 monitor for the CM4 `sunshine`. Standard library only.

    sudo python3 sunset-ups.py --once        # print the UPS status as JSON and exit
    sudo python3 sunset-ups.py --raw         # print the two raw status replies in hex (for test fixtures)
    sudo python3 sunset-ups.py --run         # poll forever (what sunset-ups.service runs)

Reads the UPS over its USB HID channel (/dev/hidrawN, USB 04D8:D005) with the two status
requests Mini-Box's own Linux tool uses (0x81 -> 0x82 and 0x83 -> 0x84; layout from
github.com/mini-box/ups src/lib/HIDOpenUPS2.cpp). It only reads: it never sends a
configuration write, a restart or the bootloader command.

Keeps SD-card writes to a minimum (decided 2026-11-16, issue #29):
  - polls every UPS_POLL_S seconds, but writes a line to ups.log only when something changed
    by more than its deadband (DEADBANDS), on an event, and as a keyframe every
    UPS_KEYFRAME_S seconds (4 h);
  - the live status goes to UPS_STATUS_FILE, which is in /run (RAM), every poll;
  - ups.log is rotated by this script: a new file each UTC day or at UPS_LOG_MAX_BYTES,
    keeping UPS_LOG_KEEP files.

Low battery (on battery and a cell below UPS_LOW_CELL_V or charge at or below UPS_LOW_PCT):
stops the capture, dense and sync timers (stop, not disable) and flushes the disks, then
starts them again if mains comes back. If it doesn't, the UPS cuts its own output and the
Pi boots when mains returns, with the timers still enabled. UPS_PAUSE=0 only logs.

Settings come from the environment (sunset.env via the systemd unit); defaults below.
"""
import argparse
import glob
import json
import os
import select
import signal
import subprocess
import sys
import time

VID, PID = 0x04D8, 0xD005
HID_ID = "0003:%08X:%08X" % (VID, PID)
REPORT_LEN = 32  # report ID + 31 data bytes, both directions

# Thermistor table: raw reading at -40, -35, ... 125 °C (5 °C steps), from Mini-Box's tool.
THERMISTOR = [
    0x31, 0x40, 0x53, 0x68, 0x82, 0xA0, 0xC3, 0xE9, 0x113, 0x13F, 0x16E, 0x19F,
    0x1CF, 0x200, 0x22F, 0x25C, 0x286, 0x2AE, 0x2D3, 0x2F4, 0x312, 0x32D, 0x345,
    0x35A, 0x36D, 0x37E, 0x38C, 0x399, 0x3A5, 0x3AF, 0x3B7, 0x3BF, 0x3C6, 0x3CC,
]

# A value counts as changed only if it moved by more than this (estimates, tune on the bench).
DEADBANDS = {
    "pct": 2, "vbat": 0.10, "cell": 0.03, "temp": 2, "vin": 0.5, "vout": 0.5,
    "ichg": 0.10, "idchg": 0.10,
}
# Any change in these is a change.
EXACT = ("source", "fw", "ups_state", "chg_state", "present", "flags")

PAUSE_UNITS = "sunset-capture.timer sunset-dense.timer sunset-sync.timer"


def env(name, default, cast=str):
    v = os.environ.get(name, "")
    if v == "":
        return default
    try:
        return cast(v)
    except ValueError:
        return default


class Settings:
    def __init__(self):
        home = os.path.dirname(os.path.abspath(__file__))
        self.hidraw = env("UPS_HIDRAW", "")
        self.poll_s = env("UPS_POLL_S", 10.0, float)
        self.keyframe_s = env("UPS_KEYFRAME_S", 4 * 3600.0, float)
        self.log_file = env("UPS_LOG_FILE", os.path.join(home, "ups.log"))
        self.log_max = env("UPS_LOG_MAX_BYTES", 262144, int)
        self.log_keep = max(1, env("UPS_LOG_KEEP", 14, int))
        self.status_file = env("UPS_STATUS_FILE", "/run/sunset-ups.json")
        self.low_cell_v = env("UPS_LOW_CELL_V", 3.45, float)
        self.low_pct = env("UPS_LOW_PCT", 10, int)
        self.warn_temp = env("UPS_WARN_TEMP_C", 40, int)
        self.pause = env("UPS_PAUSE", 1, int) == 1
        self.pause_units = env("UPS_PAUSE_UNITS", PAUSE_UNITS).split()
        # In /run: survives a restart of this service (so a pause is still undone when mains
        # returns) but not a reboot (after which the timers start by themselves).
        self.pause_flag = env("UPS_PAUSE_FLAG", "/run/sunset-ups.paused")


# ---------------------------------------------------------------- decoding

def u16(b, i):
    return b[i] | (b[i + 1] << 8)


def thermistor_c(raw):
    """Raw thermistor reading to whole °C, as Mini-Box's tool does it."""
    t = THERMISTOR
    if raw <= t[0]:
        return -40
    if raw >= t[-1]:
        return 125
    pos = max(i for i in range(len(t)) if raw >= t[i])
    t1 = pos * 5 - 40
    if raw == t[pos]:
        return t1
    d = (raw - t[pos]) * 5.0 / (t[pos + 1] - t[pos])
    whole = int(d)
    return t1 + (whole if d == whole else whole + 1)  # ceil, as the C code does


def decode(r82, r84):
    """Decode the 0x82 and 0x84 replies (32 bytes each, report ID first) into a dict."""
    if len(r82) < REPORT_LEN or r82[0] != 0x82:
        raise ValueError("not a 0x82 reply")
    if len(r84) < REPORT_LEN or r84[0] != 0x84:
        raise ValueError("not a 0x84 reply")
    flags24 = r82[24]
    if flags24 & 0x40:
        source = "battery"
    elif flags24 & 0x20:
        source = "mains"
    else:
        source = "usb"
    rte = u16(r84, 16)
    return {
        "fw": "%d.%d" % (r82[31] >> 4, r82[31] & 0x0F),
        "source": source,
        "vin": round(u16(r82, 1) * 0.001, 3),
        "vout": round(u16(r82, 3) * 0.001, 3),
        "vbat": round(u16(r82, 5) * 0.001, 3),
        "cells": [round(u16(r82, 7 + 2 * i) * 0.001, 3) for i in range(3)],
        "temps": [thermistor_c(u16(r82, 13 + 2 * i)) for i in range(3)],
        "ichg": round(u16(r82, 19) * 0.001, 3),
        "idchg": round(u16(r82, 21) * 0.001, 3),
        "flags": "%02x%02x%02x" % (r82[23], r82[24], r82[25]),
        "cfg_switch": r82[29],
        "ups_state": "%02x" % r84[9],
        "chg_state": "%02x" % r84[10],
        "pct": r84[12],
        "present": [bool((r84[15] >> i) & 1) for i in range(3)],
        "rte_min": None if rte == 0xFFFF else rte,
    }


# ---------------------------------------------------------------- device

def find_hidraw():
    for ue in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/uevent")):
        try:
            with open(ue) as f:
                if "HID_ID=" + HID_ID in f.read().upper():
                    return "/dev/" + ue.split("/")[4]
        except OSError:
            pass
    return None


class Device:
    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDWR)

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    def ask(self, req, want, timeout=2.0):
        """Send a request report; return the first reply with the wanted report ID.
        The board also sends its standard UPS reports (IDs 0x52, 0x60) on the same
        channel; those are skipped."""
        os.write(self.fd, bytes([req]) + bytes(REPORT_LEN - 1))
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                raise TimeoutError("no 0x%02x reply" % want)
            r, _, _ = select.select([self.fd], [], [], left)
            if r:
                b = os.read(self.fd, 64)
                if b and b[0] == want:
                    return b

    def read_raw(self):
        return self.ask(0x81, 0x82), self.ask(0x83, 0x84)


# ---------------------------------------------------------------- logic

def changed(old, new):
    """Names of the values that moved beyond their deadband (or changed at all, for EXACT)."""
    if old is None:
        return ["all"]
    out = [k for k in EXACT if old.get(k) != new.get(k)]
    for k in ("pct", "vbat", "vin", "vout", "ichg", "idchg"):
        if abs((new.get(k) or 0) - (old.get(k) or 0)) > DEADBANDS[k]:
            out.append(k)
    for k, band in (("cells", DEADBANDS["cell"]), ("temps", DEADBANDS["temp"])):
        if any(abs(a - b) > band for a, b in zip(old.get(k, []), new.get(k, []))):
            out.append(k)
    return out


def low_battery(s, cfg):
    if s["source"] != "battery":
        return False
    live = [v for v, p in zip(s["cells"], s["present"]) if p]
    return (bool(live) and min(live) < cfg.low_cell_v) or s["pct"] <= cfg.low_pct


class Monitor:
    """Decides what to write. Pure apart from the writer and runner it is given."""

    def __init__(self, cfg, write, run=None, clock=time.time):
        self.cfg, self.write, self.clock = cfg, write, clock
        self.run = run or (lambda argv: subprocess.call(argv))
        self.last_written = None  # status as last written to the log
        self.last = None          # status at the last poll
        self.last_key = None      # time of the last keyframe
        self.paused = bool(cfg.pause_flag) and os.path.exists(cfg.pause_flag)
        self.lost = False

    def set_paused(self, on):
        self.paused = on
        if not self.cfg.pause_flag:
            return
        try:
            if on:
                open(self.cfg.pause_flag, "w").close()
            elif os.path.exists(self.cfg.pause_flag):
                os.remove(self.cfg.pause_flag)
        except OSError:
            pass

    def event(self, name, s=None):
        self.write("EVENT " + name, s)

    def lost_device(self, why):
        if not self.lost:
            self.lost = True
            self.write("EVENT ups_lost " + why.replace(" ", "_"), None)

    def poll(self, s):
        now = self.clock()
        prev = self.last
        if self.lost:
            self.lost = False
            self.event("ups_found", s)
        if prev is not None:
            if prev["source"] != s["source"]:
                name = {"battery": "mains_lost", "mains": "mains_back"}.get(s["source"], "usb_only")
                self.event(name, s)
            if prev["present"] != s["present"]:
                self.event("cells_present_" + "".join("1" if p else "0" for p in s["present"]), s)
            hot_before = max(prev["temps"]) >= self.cfg.warn_temp
            hot_now = max(s["temps"]) >= self.cfg.warn_temp
            if hot_now != hot_before:
                self.event("temp_high" if hot_now else "temp_ok", s)
        if low_battery(s, self.cfg) and not self.paused:
            self.set_paused(True)
            self.event("low_battery", s)
            if self.cfg.pause:
                self.run(["systemctl", "stop"] + self.cfg.pause_units)
                self.run(["sync"])
                self.event("capture_paused", s)
            else:
                self.event("capture_pause_skipped_UPS_PAUSE=0", s)
        elif self.paused and s["source"] == "mains":
            self.set_paused(False)
            if self.cfg.pause:
                self.run(["systemctl", "start"] + self.cfg.pause_units)
                self.event("capture_resumed", s)
        self.last = s
        what = changed(self.last_written, s)
        if self.last_key is None or now - self.last_key >= self.cfg.keyframe_s:
            self.write("KEY", s)
            self.last_key = now
            self.last_written = s
        elif what:
            self.write("CHANGE " + ",".join(what), s)
            self.last_written = s


# ---------------------------------------------------------------- output

def fmt_line(ts, tag, s):
    t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
    if s is None:
        return "%s %s" % (t, tag)
    rte = "-" if s["rte_min"] is None else str(s["rte_min"])
    return ("%s %s src=%s pct=%d rte=%s vbat=%.2f cells=%s t=%s vin=%.2f vout=%.2f "
            "ichg=%.2f idchg=%.2f ups=%s chg=%s present=%s flags=%s fw=%s") % (
        t, tag, s["source"], s["pct"], rte, s["vbat"],
        ",".join("%.2f" % v for v in s["cells"]), ",".join(str(v) for v in s["temps"]),
        s["vin"], s["vout"], s["ichg"], s["idchg"], s["ups_state"], s["chg_state"],
        "".join("1" if p else "0" for p in s["present"]), s["flags"], s["fw"])


class RotatingLog:
    """Appends lines; starts a new file each UTC day or at max_bytes, keeping `keep` files."""

    def __init__(self, path, max_bytes, keep, clock=time.time):
        self.path, self.max_bytes, self.keep, self.clock = path, max_bytes, keep, clock

    def _rotate(self):
        for i in range(self.keep - 1, 0, -1):
            src = self.path if i == 1 else "%s.%d" % (self.path, i - 1)
            if os.path.exists(src):
                os.replace(src, "%s.%d" % (self.path, i))
        if self.keep == 1 and os.path.exists(self.path):
            os.remove(self.path)

    def due(self, now):
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return False
        day = time.strftime("%Y-%m-%d", time.gmtime(st.st_mtime))
        return st.st_size >= self.max_bytes or day != time.strftime("%Y-%m-%d", time.gmtime(now))

    def write(self, line):
        now = self.clock()
        if self.due(now):
            self._rotate()
        with open(self.path, "a") as f:
            f.write(line + "\n")


def write_status(path, s, ts, error=None):
    """The live status, in RAM (/run). Written every poll; never on the SD card."""
    if not path:
        return
    doc = {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)), "ok": s is not None}
    if s is not None:
        doc.update(s)
    if error:
        doc["error"] = error
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(doc, f)
        os.replace(tmp, path)
    except OSError:
        pass


# ---------------------------------------------------------------- main

def open_device(cfg):
    path = cfg.hidraw or find_hidraw()
    if not path:
        raise FileNotFoundError("no OpenUPS2 (USB %04x:%04x) hidraw device" % (VID, PID))
    return Device(path)


def run_forever(cfg):
    log = RotatingLog(cfg.log_file, cfg.log_max, cfg.log_keep)
    mon = Monitor(cfg, lambda tag, s: log.write(fmt_line(time.time(), tag, s)))
    stop = {"now": False}

    def on_term(*_):
        stop["now"] = True
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    log.write(fmt_line(time.time(), "START pid=%d poll=%gs keyframe=%gs" % (os.getpid(), cfg.poll_s, cfg.keyframe_s), None))
    dev = None
    while not stop["now"]:
        t0 = time.time()
        try:
            if dev is None:
                dev = open_device(cfg)
            s = decode(*dev.read_raw())
            mon.poll(s)
            write_status(cfg.status_file, s, t0)
        except (OSError, TimeoutError, ValueError) as e:
            if dev is not None:
                dev.close()
                dev = None
            mon.lost_device(type(e).__name__)
            write_status(cfg.status_file, None, t0, str(e))
        while not stop["now"] and time.time() - t0 < cfg.poll_s:
            time.sleep(0.5)
    if dev is not None:
        dev.close()
    log.write(fmt_line(time.time(), "STOP", None))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true", help="print the status as JSON and exit")
    g.add_argument("--raw", action="store_true", help="print the raw 0x82 and 0x84 replies in hex")
    g.add_argument("--run", action="store_true", help="poll and log until stopped")
    a = ap.parse_args(argv)
    cfg = Settings()
    if a.run:
        run_forever(cfg)
        return 0
    dev = open_device(cfg)
    try:
        r82, r84 = dev.read_raw()
    finally:
        dev.close()
    if a.raw:
        print(r82.hex())
        print(r84.hex())
    else:
        print(json.dumps(decode(r82, r84), indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, PermissionError, TimeoutError) as e:
        print("sunset-ups: %s" % e, file=sys.stderr)
        sys.exit(1)
