"""Offline tests for tools/camera_check.py: log parsing, missing slots, Vancouver times."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import camera_check as cc  # noqa: E402

UTC = dt.timezone.utc


def t(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


LOG = """\
2026-11-17T10:00:05Z cam=a lux=1 soc=30'C disk=5% raw=0 night=0 bracket=0 meta=ok ok
2026-11-17T10:00:35Z cam=b lux=1 soc=30'C disk=5% raw=0 night=0 bracket=0 meta=ok ok
2026-11-17T10:01:05Z cam=a dense window=sunset soc=30'C meta=ok ok
2026-11-17T10:05:05Z cam=a lux=1 soc=30'C disk=5% raw=0 night=0 bracket=0 meta=ok ok
2026-11-17T10:05:35Z cam=b SKIPPED: CAMERA=i2c@1 matches 0 cameras
2026-11-17T10:20:05Z cam=a lux=1 soc=30'C disk=5% raw=0 night=0 bracket=0 meta=ok ok
2026-11-17T10:20:35Z cam=b lux=1 soc=30'C disk=5% raw=0 night=0 bracket=0 meta=ok ok
2026-11-17T10:21:00Z sync ok files=4
""".splitlines()


class Summary(unittest.TestCase):
    def setUp(self):
        self.c = cc.capture_summary(LOG, t("2026-11-17T10:23:00Z"), 1)

    def test_counts(self):
        self.assertEqual(self.c["a"]["dense"], 1)
        self.assertEqual(len(self.c["a"]["slots"]), 3)

    def test_missing_slots_are_runs(self):
        self.assertEqual([(x.strftime("%H:%M"), y.strftime("%H:%M"), n) for x, y, n in self.c["a"]["missing"]],
                         [("10:10", "10:15", 2)])

    def test_bad_line_is_a_gap_and_reported(self):
        self.assertEqual(len(self.c["b"]["bad"]), 1)
        self.assertEqual(sum(n for _, _, n in self.c["b"]["missing"]), 3)   # 10:05, 10:10, 10:15

    def test_current_slot_not_counted(self):
        c = cc.capture_summary(LOG, t("2026-11-17T10:25:30Z"), 1)
        self.assertNotIn("10:25", [x.strftime("%H:%M") for x, _, _ in c["a"]["missing"]])

    def test_window_drops_old_lines(self):
        c = cc.capture_summary(LOG, t("2026-11-17T12:00:00Z"), 1)
        self.assertEqual(c, {})


class Vancouver(unittest.TestCase):
    def test_utc_minus_7_all_year(self):
        # BC stays on UTC-7 all year (tzdata 2026b/c): no fall back on Nov 1, 2026.
        self.assertEqual(cc.van(t("2026-11-17T16:00:00Z")).hour, 9)
        self.assertEqual(cc.van(t("2026-07-01T16:00:00Z")).hour, 9)
        self.assertEqual(cc.van(t("2026-11-01T09:00:00Z")).hour, 2)
        self.assertEqual(cc.van(t("2027-01-15T16:00:00Z")).hour, 9)

    def test_fallback_without_tzdata_is_utc_minus_7(self):
        saved = cc.VAN_TZ
        try:
            cc.VAN_TZ = None
            self.assertEqual(cc.van(t("2026-11-18T00:27:00Z")).hour, 17)
        finally:
            cc.VAN_TZ = saved


class Parse(unittest.TestCase):
    def test_sections(self):
        d = cc.parse("### now\n2026-11-17T10:00:00Z\n### empty\n### newest\na /x/a_1.jpg\n")
        self.assertEqual(d["now"], ["2026-11-17T10:00:00Z"])
        self.assertEqual(d["empty"], [])
        self.assertEqual(d["newest"], ["a /x/a_1.jpg"])


class Ups(unittest.TestCase):
    NOW = t("2026-11-20T07:00:00Z")
    GOOD = ('{"time": "2026-11-20T06:59:55Z", "ok": true, "source": "mains", "pct": 88, "vin": 15.1, '
            '"vout": 15.0, "cells": [3.57, 3.56, 3.57], "temps": [24, 24, 25], "ichg": 0.0, '
            '"idchg": 0.0, "present": [true, true, true], "fw": "1.6"}')

    def test_no_ups_no_lines(self):
        self.assertEqual(cc.ups_summary([""], [], self.NOW), ([], []))

    def test_good(self):
        out, warn = cc.ups_summary([self.GOOD], [], self.NOW)
        self.assertEqual(warn, [])
        self.assertIn("mains, 88% charge, in 15.1 V", out[0])
        self.assertIn("3.57/3.56/3.57", out[0])

    def test_on_battery_and_events(self):
        st = self.GOOD.replace('"mains"', '"battery"')
        log = ["2026-11-20T06:40:00Z EVENT mains_lost src=battery pct=88"]
        out, warn = cc.ups_summary([st], log, self.NOW)
        self.assertIn("UPS on battery, not mains", warn)
        self.assertTrue(any("mains_lost" in w for w in warn))
        self.assertTrue(any("EVENT mains_lost" in l for l in out))

    def test_stale_unreadable_and_missing(self):
        old = self.GOOD.replace("06:59:55", "06:00:00")
        self.assertIn("UPS status is 60 min old", cc.ups_summary([old], [], self.NOW)[1])
        bad = '{"time": "2026-11-20T06:59:55Z", "ok": false, "error": "no device"}'
        self.assertIn("UPS not readable", cc.ups_summary([bad], [], self.NOW)[1])
        log = ["2026-11-20T06:40:00Z EVENT ups_lost OSError"]
        self.assertIn("UPS monitor status missing", cc.ups_summary([""], log, self.NOW)[1])

    def test_cell_imbalance_and_heat(self):
        st = self.GOOD.replace("[3.57, 3.56, 3.57]", "[3.57, 3.40, 3.57]").replace("[24, 24, 25]", "[24, 41, 25]")
        warn = cc.ups_summary([st], [], self.NOW)[1]
        self.assertIn("UPS cells differ by 0.17 V", warn)
        self.assertIn("UPS cells at 41 °C", warn)


if __name__ == "__main__":
    unittest.main()
