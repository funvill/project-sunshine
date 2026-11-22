"""Tests for sunset-ups.py (OpenUPS2 monitor): python3 tests/test_ups.py

No UPS needed. The two REAL_* replies were read from the board on the bench on 2026-11-16
(firmware 1.6, USB only, no cells, no DC input). The battery cases are built from them.
"""
import importlib.util
import os
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sunset_ups", os.path.join(os.path.dirname(HERE), "pi", "sunset-ups.py"))
ups = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ups)

REAL_82 = bytes.fromhex("82000000000000000000000000e401e601e601000000000000010000ff070016")
REAL_84 = bytes.fromhex("84008602ae02000000030f0032000000ffff0000000000000000200100000f01")
# Same board on 2026-11-17 with three charged Li-ion cells and a 12.5 V supply (too low for the
# board to call it mains), so running from the cells.
BATT_82 = bytes.fromhex("82ec308a30cc30431044104510e501e901ef010000000000c0310000c0070016")
BATT_84 = bytes.fromhex("84008602ae02000005060f044b00ff07ffff0000000000000000303300050f17")


def put16(b, i, v):
    b[i] = v & 0xFF
    b[i + 1] = (v >> 8) & 0xFF


def reply(source="mains", vin=19.0, cells=(4.05, 4.05, 4.05), temps_raw=(0x1E4, 0x1E6, 0x1E6),
          ichg=0.0, idchg=0.0, pct=90, present=(1, 1, 1), rte=0xFFFF):
    r82, r84 = bytearray(REAL_82), bytearray(REAL_84)
    put16(r82, 1, int(round(vin * 1000)))
    put16(r82, 3, int(round(max(vin, 12.0) * 1000)))
    put16(r82, 5, int(round(sum(cells) * 1000)))
    for i, c in enumerate(cells):
        put16(r82, 7 + 2 * i, int(round(c * 1000)))
    for i, t in enumerate(temps_raw):
        put16(r82, 13 + 2 * i, t)
    put16(r82, 19, int(round(ichg * 1000)))
    put16(r82, 21, int(round(idchg * 1000)))
    r82[24] = {"battery": 0x40, "mains": 0x20, "usb": 0x00}[source]
    r84[12] = pct
    r84[15] = sum(1 << i for i, p in enumerate(present) if p)
    put16(r84, 16, rte)
    return ups.decode(bytes(r82), bytes(r84))


class Cfg:
    poll_s = 10.0
    keyframe_s = 4 * 3600.0
    low_cell_v = 3.45
    warn_temp = 40
    pause = True
    pause_units = ["sunset-capture.timer", "sunset-dense.timer", "sunset-capture2.timer",
                   "sunset-dense2.timer", "sunset-sync.timer"]
    pause_flag = ""


class Clock:
    def __init__(self, t=1794800000.0):
        self.t = t

    def __call__(self):
        return self.t


def monitor(cfg=None, flag="", running=None):
    """running: the units systemd reports active (default: all the pause units; the diag page off)."""
    cfg = cfg or Cfg()
    cfg.pause_flag = flag
    lines, calls, clock = [], [], Clock()
    active = (lambda u: u != "sunset-diag.service") if running is None else (lambda u: u in running)
    m = ups.Monitor(cfg, lambda tag, s: lines.append(tag), run=lambda argv: calls.append(argv) or 0,
                    clock=clock, active=active)
    return m, lines, calls, clock


class Decode(unittest.TestCase):
    def test_real_bench_reply(self):
        s = ups.decode(REAL_82, REAL_84)
        self.assertEqual(s["fw"], "1.6")
        self.assertEqual(s["source"], "usb")
        self.assertEqual(s["temps"], [23, 23, 23])  # the Windows tool showed 23.00 for all three
        self.assertEqual(s["pct"], 50)
        self.assertEqual(s["ups_state"], "03")
        self.assertEqual(s["chg_state"], "0f")
        self.assertEqual(s["cfg_switch"], 7)
        self.assertEqual(s["present"], [False, False, False])
        self.assertIsNone(s["rte_min"])
        self.assertEqual(s["vin"], 0.0)

    def test_real_on_battery_reply(self):
        s = ups.decode(BATT_82, BATT_84)  # matches the Windows tool's screen at the same moment
        self.assertEqual(s["source"], "battery")
        self.assertEqual(s["cells"], [4.163, 4.164, 4.165])
        self.assertAlmostEqual(s["vbat"], 12.492)
        self.assertAlmostEqual(s["vin"], 12.524)
        self.assertAlmostEqual(s["vout"], 12.426)
        self.assertEqual(s["present"], [True, True, True])
        self.assertEqual(s["pct"], 75)
        self.assertEqual(s["ups_state"], "06")
        self.assertEqual(s["temps"], [23, 23, 24])

    def test_sources_and_values(self):
        s = reply("battery", vin=0.0, cells=(3.80, 3.81, 3.79), idchg=0.35, pct=60, rte=320)
        self.assertEqual(s["source"], "battery")
        self.assertEqual(s["cells"], [3.8, 3.81, 3.79])
        self.assertAlmostEqual(s["vbat"], 11.4, places=2)
        self.assertAlmostEqual(s["idchg"], 0.35)
        self.assertEqual(s["rte_min"], 320)
        self.assertEqual(reply("mains")["source"], "mains")

    def test_wrong_report_rejected(self):
        with self.assertRaises(ValueError):
            ups.decode(REAL_84, REAL_84)
        with self.assertRaises(ValueError):
            ups.decode(REAL_82, REAL_82[:10])

    def test_thermistor(self):
        self.assertEqual(ups.thermistor_c(0x10), -40)
        self.assertEqual(ups.thermistor_c(0x3FF), 125)
        self.assertEqual(ups.thermistor_c(0x200), 25)  # exact table point
        self.assertEqual(ups.thermistor_c(0x1CF), 20)
        self.assertEqual(ups.thermistor_c(0x1E4), 23)  # between points: rounded up like the C code


class Deadbands(unittest.TestCase):
    def test_noise_is_not_a_change(self):
        a = reply(cells=(4.050, 4.050, 4.050), pct=90)
        b = reply(cells=(4.070, 4.040, 4.060), pct=91)
        self.assertEqual(ups.changed(a, b), [])

    def test_real_moves_are_changes(self):
        a = reply(cells=(4.05, 4.05, 4.05), pct=90)
        self.assertIn("cells", ups.changed(a, reply(cells=(4.05, 4.00, 4.05), pct=90)))
        self.assertIn("pct", ups.changed(a, reply(cells=(4.05, 4.05, 4.05), pct=87)))
        self.assertIn("temps", ups.changed(a, reply(temps_raw=(0x22F, 0x1E6, 0x1E6))))
        self.assertIn("source", ups.changed(a, reply("battery")))

    def test_first_reading_is_a_change(self):
        self.assertEqual(ups.changed(None, reply()), ["all"])


class Writes(unittest.TestCase):
    def test_quiet_day_writes_only_keyframes(self):
        m, lines, _, clock = monitor()
        for _ in range(int(24 * 3600 / 10)):  # a day of polls every 10 s, nothing changing
            m.poll(reply())
            clock.t += 10
        self.assertEqual(lines, ["KEY"] * 6)  # one keyframe every 4 hours

    def test_noise_does_not_write(self):
        m, lines, _, clock = monitor()
        for i in range(500):
            m.poll(reply(cells=(4.05 + (i % 3) * 0.01, 4.05, 4.05), pct=90 + i % 2))
            clock.t += 10
        self.assertEqual(lines, ["KEY"])

    def test_change_writes_once(self):
        m, lines, _, clock = monitor()
        m.poll(reply(pct=90))
        clock.t += 10
        m.poll(reply(pct=80))
        clock.t += 10
        m.poll(reply(pct=80))
        self.assertEqual(lines, ["KEY", "CHANGE pct"])

    def test_slow_drift_is_caught(self):
        m, lines, _, clock = monitor()
        for i in range(20):  # 0.01 V per poll: below the deadband each time, not in total
            m.poll(reply(cells=(4.05 - 0.01 * i, 4.05, 4.05)))
            clock.t += 10
        self.assertTrue(any(l.startswith("CHANGE") and "cells" in l for l in lines))


class Events(unittest.TestCase):
    def test_power_cut_pause_and_resume(self):
        m, lines, calls, clock = monitor()
        m.poll(reply("mains", pct=95))
        m.poll(reply("battery", vin=0.0, cells=(3.90, 3.90, 3.90), pct=70))
        self.assertIn("EVENT mains_lost", lines)
        self.assertEqual(calls, [])
        m.poll(reply("battery", vin=0.0, cells=(3.44, 3.50, 3.50), pct=15))
        self.assertIn("EVENT low_battery", lines)
        self.assertIn("EVENT capture_paused units=" + ",".join(Cfg.pause_units), lines)
        self.assertEqual(calls[0], ["systemctl", "stop"] + Cfg.pause_units)
        self.assertEqual(calls[1], ["sync"])
        m.poll(reply("battery", vin=0.0, cells=(3.40, 3.45, 3.45), pct=8))
        self.assertEqual(len(calls), 2)  # paused once only
        m.poll(reply("mains", pct=9))
        self.assertIn("EVENT mains_back", lines)
        self.assertIn("EVENT capture_resumed", lines)
        self.assertEqual(calls[2], ["systemctl", "start"] + Cfg.pause_units)

    def test_default_units_cover_both_cameras_and_the_sync(self):
        for u in ("sunset-capture.timer", "sunset-dense.timer", "sunset-capture2.timer",
                  "sunset-dense2.timer", "sunset-sync.timer"):
            self.assertIn(u, ups.PAUSE_UNITS.split())

    def test_resume_starts_only_what_the_pause_stopped(self):
        running = {"sunset-capture.timer", "sunset-sync.timer"}  # say the second camera is off
        m, lines, calls, _ = monitor(running=running)
        m.poll(reply("battery", vin=0.0, cells=(3.40, 3.40, 3.40), pct=5))
        self.assertEqual(calls[0], ["systemctl", "stop", "sunset-capture.timer", "sunset-sync.timer"])
        m.poll(reply("mains", pct=6))
        self.assertEqual(calls[-1], ["systemctl", "start", "sunset-capture.timer", "sunset-sync.timer"])

    def test_nothing_running_stops_and_starts_nothing(self):
        m, lines, calls, _ = monitor(running=set())
        m.poll(reply("battery", vin=0.0, cells=(3.40, 3.40, 3.40), pct=5))
        self.assertIn("EVENT capture_paused units=none", lines)
        self.assertEqual(calls, [["sync"]])
        m.poll(reply("mains", pct=6))
        self.assertIn("EVENT capture_resumed", lines)
        self.assertEqual(calls, [["sync"]])

    def test_charge_percentage_is_not_used(self):
        # The board says 100% on battery until the end (2026-11-20), so only the cells decide.
        m, lines, calls, _ = monitor()
        m.poll(reply("battery", vin=0.0, cells=(3.70, 3.70, 3.70), pct=5))
        self.assertNotIn("EVENT low_battery", lines)
        self.assertEqual(calls, [])

    def test_low_cells_on_mains_do_not_pause(self):
        m, lines, calls, _ = monitor()
        m.poll(reply("mains", cells=(3.30, 3.30, 3.30), pct=5))
        self.assertNotIn("EVENT low_battery", lines)
        self.assertEqual(calls, [])

    def test_missing_cell_ignored_for_low_battery(self):
        m, lines, calls, _ = monitor()
        m.poll(reply("battery", vin=0.0, cells=(0.0, 3.90, 3.90), present=(0, 1, 1), pct=60))
        self.assertNotIn("EVENT low_battery", lines)

    def test_pause_disabled_only_logs(self):
        cfg = Cfg()
        cfg.pause = False
        m, lines, calls, _ = monitor(cfg)
        m.poll(reply("battery", vin=0.0, cells=(3.40, 3.40, 3.40), pct=5))
        self.assertIn("EVENT low_battery", lines)
        self.assertEqual(calls, [])

    def test_pause_survives_service_restart(self):
        with tempfile.TemporaryDirectory() as d:
            flag = os.path.join(d, "paused")
            m, _, calls, _ = monitor(flag=flag)
            m.poll(reply("battery", vin=0.0, cells=(3.40, 3.40, 3.40), pct=5))
            self.assertTrue(os.path.exists(flag))
            m2, lines2, calls2, _ = monitor(flag=flag)  # the service restarted
            m2.poll(reply("mains", pct=6))
            self.assertIn("EVENT capture_resumed", lines2)
            self.assertEqual(calls2[0], ["systemctl", "start"] + Cfg.pause_units)
            self.assertFalse(os.path.exists(flag))

    def test_restart_keeps_the_list_of_stopped_units(self):
        with tempfile.TemporaryDirectory() as d:
            flag = os.path.join(d, "paused")
            m, _, _, _ = monitor(flag=flag, running={"sunset-capture.timer"})
            m.poll(reply("battery", vin=0.0, cells=(3.40, 3.40, 3.40), pct=5))
            m2, _, calls2, _ = monitor(flag=flag, running=set())  # restarted; all stopped now
            m2.poll(reply("mains", pct=6))
            self.assertEqual(calls2, [["systemctl", "start", "sunset-capture.timer"]])

    def test_a_flag_from_the_older_version_restarts_the_whole_set(self):
        with tempfile.TemporaryDirectory() as d:
            flag = os.path.join(d, "paused")
            open(flag, "w").close()   # empty, as the first version wrote it
            m, _, calls, _ = monitor(flag=flag, running=set())
            m.poll(reply("mains", pct=6))
            self.assertEqual(calls, [["systemctl", "start"] + Cfg.pause_units])

    def test_cell_and_temperature_events(self):
        m, lines, _, _ = monitor()
        m.poll(reply())
        m.poll(reply(present=(1, 0, 1)))
        m.poll(reply(temps_raw=(0x2AE, 0x1E6, 0x1E6)))  # 0x2AE is 45 °C
        m.poll(reply())
        self.assertIn("EVENT cells_present_101", lines)
        self.assertIn("EVENT temp_high", lines)
        self.assertIn("EVENT temp_ok", lines)

    def test_device_lost_and_found_logged_once(self):
        m, lines, _, _ = monitor()
        m.poll(reply())
        m.lost_device("TimeoutError")
        m.lost_device("TimeoutError")
        m.poll(reply())
        self.assertEqual([l for l in lines if l.startswith("EVENT")], ["EVENT ups_lost TimeoutError", "EVENT ups_found"])


class Diag(unittest.TestCase):
    """The diag page stops the camera timers while it is on and starts them when it ends."""

    CAMS = ["sunset-capture.timer", "sunset-dense.timer", "sunset-capture2.timer", "sunset-dense2.timer"]

    def test_diag_ending_during_a_pause_hands_its_timers_to_the_resume(self):
        # Diag stopped the cameras, so the pause stopped only the sync. Diag ended while paused and
        # appended its timers to the flag instead of starting them (sunset-diag.service).
        with tempfile.TemporaryDirectory() as d:
            flag = os.path.join(d, "paused")
            m, _, calls, _ = monitor(flag=flag, running={"sunset-sync.timer"})
            m.poll(reply("battery", vin=0.0, cells=(3.20, 3.20, 3.20), pct=5))
            self.assertEqual(calls[0], ["systemctl", "stop", "sunset-sync.timer"])
            with open(flag, "a") as f:
                f.write("sunset-capture.timer\nsunset-dense.timer\n")
            m.active = lambda u: False   # diag is no longer running
            m.poll(reply("mains", pct=6))
            self.assertEqual(calls[-1], ["systemctl", "start", "sunset-sync.timer", "sunset-capture.timer", "sunset-dense.timer"])

    def test_diag_ending_after_a_pause_from_an_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            flag = os.path.join(d, "paused")
            m, _, calls, _ = monitor(flag=flag, running=set())
            m.poll(reply("battery", vin=0.0, cells=(3.20, 3.20, 3.20), pct=5))
            with open(flag, "a") as f:
                f.write("sunset-capture.timer\n")
            m.poll(reply("mains", pct=6))
            self.assertEqual(calls[-1], ["systemctl", "start", "sunset-capture.timer"])

    def test_resume_leaves_the_cameras_to_diag_while_it_is_on(self):
        # Mains returns with the diag page open: starting the camera timers would take the camera
        # from the page. Diag starts them itself when it ends (the flag is gone by then).
        m, lines, calls, _ = monitor(running=set(Cfg.pause_units))
        m.poll(reply("battery", vin=0.0, cells=(3.20, 3.20, 3.20), pct=5))
        m.active = lambda u: u == "sunset-diag.service"
        m.poll(reply("mains", pct=6))
        self.assertEqual(calls[-1], ["systemctl", "start", "sunset-sync.timer"])
        self.assertIn("EVENT capture_resumed", lines)

    def test_the_unit_file_checks_the_pause_flag(self):
        unit = open(os.path.join(os.path.dirname(HERE), "pi", "systemd", "sunset-diag.service")).read()
        stops = [l for l in unit.splitlines() if l.startswith("ExecStopPost=")]
        self.assertTrue(stops)
        for l in stops:
            self.assertIn("/run/sunset-ups.paused", l)
        for u in self.CAMS:
            self.assertIn(u, "".join(stops))


class Writer(unittest.TestCase):
    """A log that can't be written (SD full or read-only) must not stop the monitor."""

    def test_failed_write_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            log = ups.RotatingLog(os.path.join(d, "missing", "ups.log"), 1000, 2)
            err = []
            write = ups.log_writer(log, err.append)
            write("EVENT low_battery", reply("battery", vin=0.0, cells=(3.2, 3.2, 3.2), pct=5))
            write("EVENT capture_paused", None)
            self.assertEqual(len(err), 1)   # reported once per run of failures, not every line
            os.makedirs(os.path.join(d, "missing"))
            write("KEY", None)
            write("KEY", None)
            self.assertEqual(len(err), 1)

    def test_pause_still_happens_when_the_log_fails(self):
        with tempfile.TemporaryDirectory() as d:
            log = ups.RotatingLog(os.path.join(d, "missing", "ups.log"), 1000, 2)
            calls = []
            m = ups.Monitor(Cfg(), ups.log_writer(log, lambda msg: None),
                            run=lambda argv: calls.append(argv) or 0, clock=Clock(), active=lambda u: True)
            m.poll(reply("battery", vin=0.0, cells=(3.20, 3.20, 3.20), pct=5))
            self.assertEqual(calls[0], ["systemctl", "stop"] + Cfg.pause_units)


class Log(unittest.TestCase):
    def test_line_format(self):
        line = ups.fmt_line(0, "KEY", reply("battery", vin=0.0, cells=(3.8, 3.8, 3.8), pct=60, rte=300))
        self.assertTrue(line.startswith("1970-01-01T00:00:00Z KEY src=battery pct=60 rte=300 vbat=11.40 cells=3.80,3.80,3.80"))
        self.assertTrue(line.endswith("fw=1.6"))
        self.assertEqual(ups.fmt_line(0, "STOP", None), "1970-01-01T00:00:00Z STOP")

    def test_rotates_on_size_and_keeps_n(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ups.log")
            log = ups.RotatingLog(p, max_bytes=100, keep=3, clock=time.time)
            for i in range(40):
                log.write("line %02d %s" % (i, "x" * 20))
            names = sorted(os.listdir(d))
            self.assertEqual(names, ["ups.log", "ups.log.1", "ups.log.2"])
            self.assertTrue(all(os.path.getsize(os.path.join(d, n)) <= 130 for n in names))
            with open(p) as f:
                self.assertIn("line 39", f.read())

    def test_rotates_on_new_utc_day(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ups.log")
            clock = Clock(time.time())
            log = ups.RotatingLog(p, max_bytes=10 ** 6, keep=14, clock=clock)
            log.write("today")
            yesterday = clock.t - 86400
            os.utime(p, (yesterday, yesterday))
            log.write("next day")
            with open(p) as f:
                self.assertEqual(f.read(), "next day\n")
            with open(p + ".1") as f:
                self.assertEqual(f.read(), "today\n")

    def test_status_file_is_json(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            ups.write_status(p, reply(), 0)
            with open(p) as f:
                doc = json.load(f)
            self.assertTrue(doc["ok"])
            self.assertEqual(doc["source"], "mains")
            ups.write_status(p, None, 0, "no device")
            with open(p) as f:
                self.assertEqual(json.load(f)["error"], "no device")


class Discovery(unittest.TestCase):
    def test_settings_defaults(self):
        for k in list(os.environ):
            if k.startswith("UPS_"):
                del os.environ[k]
        c = ups.Settings()
        self.assertEqual(c.poll_s, 10.0)
        self.assertEqual(c.keyframe_s, 14400.0)
        self.assertEqual(c.log_keep, 14)
        self.assertEqual(c.log_max, 262144)
        self.assertTrue(c.pause)
        self.assertEqual(c.status_file, "/run/sunset-ups.json")
        # 3.45 V sat just under the ~3.5-3.6 V the cells rest at with R20 unchanged (review 2026-11-21).
        self.assertEqual(c.low_cell_v, 3.3)

    def test_hid_id(self):
        self.assertEqual(ups.HID_ID, "0003:000004D8:0000D005")


if __name__ == "__main__":
    unittest.main()
