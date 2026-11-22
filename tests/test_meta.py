#!/usr/bin/env python3
"""Offline tests for sunset-meta.py, against a fake /proc and /sys tree. No Pi needed."""
import hashlib
import importlib.util
import json
import os
import pathlib
import socket
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("sunset_meta", ROOT / "pi" / "sunset-meta.py")
meta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(meta)

TIMESYNC = """       Server: 203.0.113.9 (ntp.example)
         Leap: normal
       Offset: +499us
       Jitter: 6.765ms
"""
ANSWERS = {
    ("vcgencmd", "get_throttled"): "throttled=0x50005\n",
    ("vcgencmd", "measure_volts", "core"): "volt=1.2000V\n",
    ("vcgencmd", "measure_clock", "arm"): "frequency(48)=600064000\n",
    ("vcgencmd", "version"): "Sep 14 2026 14:50:41\nCopyright (c) 2012 Broadcom\nversion a8698392 (clean) (release) (start)\n",
    ("rpicam-still", "--version"): "rpicam-apps build: v1.9.0 abc 11-09-2025\nlibcamera build: v0.5.2+99-bfd68f78\n",
    ("timedatectl", "show", "-p", "NTPSynchronized"): "NTPSynchronized=yes\n",
    ("timedatectl", "timesync-status"): TIMESYNC,
}


def fake_run(cmd):
    return ANSWERS.get(tuple(cmd))


def write(base, rel, text):
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:  # newline: exact bytes, for the checksum tests on Windows
        f.write(text)


class Tree(unittest.TestCase):
    """A fake Pi: /proc, /sys, an outbox and a sync log."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        r = self.root = self._tmp.name
        write(r, "proc/device-tree/model", "Raspberry Pi 3 Model B Plus Rev 1.3\0")
        write(r, "proc/cpuinfo", "processor : 0\nRevision\t: a020d3\nSerial\t\t: 00000000deadbeef\n")
        write(r, "proc/version", "Linux version 6.12.109+rpt-rpi-v7 (x@y) #1 SMP\n")
        write(r, "proc/uptime", "47248.99 183671.35\n")
        write(r, "proc/loadavg", "0.10 0.12 0.09 1/151 9373\n")
        write(r, "proc/meminfo", "MemTotal: 943112 kB\nMemAvailable: 813096 kB\nSwapFree: 0 kB\n")
        write(r, "proc/mounts", "//nas/camera /mnt/nas cifs rw 0 0\n/dev/mmcblk0p2 / ext4 rw 0 0\n")
        write(r, "proc/net/wireless",
              "Inter-| sta-|   Quality\n face | tus | link level noise\n"
              " wlan0: 0000   64.  -46.  -256        0      0      0      0      0        0\n")
        write(r, "etc/timezone", "America/Vancouver\n")
        write(r, "etc/os-release", 'NAME="x"\nPRETTY_NAME="Raspbian GNU/Linux 12 (bookworm)"\n')
        write(r, "boot/firmware/config.txt",
              "camera_auto_detect=0\ndtoverlay=vc4-kms-v3d\ndtoverlay=imx477\n")
        write(r, "sys/class/thermal/thermal_zone0/temp", "52600\n")
        write(r, "sys/class/net/lo/operstate", "unknown\n")
        write(r, "sys/class/net/eth0/operstate", "down\n")
        write(r, "sys/class/net/eth0/address", "b8:27:eb:b2:c5:c9\n")
        write(r, "sys/class/net/wlan0/operstate", "up\n")
        write(r, "sys/block/mmcblk0/stat",
              "3158 2960 236506 19370 15409 8082 8975345 2112769 0 238060 2132140 0 0 0 0 0 0\n")
        for name, value in (("name", "SH32G"), ("manfid", "0x000003"), ("oemid", "0x5344"),
                            ("date", "07/2021"), ("serial", "0xcafef00d"), ("cid", "035344deadbeef")):
            write(r, "sys/block/mmcblk0/device/" + name, value + "\n")
        self.outbox = os.path.join(r, "home/outbox")
        write(self.outbox, "wide/2026/11/04/a.jpg", "12345")
        write(self.outbox, "wide/2026/11/04/a.json", "{}")
        write(self.outbox, ".partial/ignored.jpg", "x" * 100)
        self.sync_log = os.path.join(r, "home/sync.log")
        write(r, "home/sync.log",
              "2026-11-04T19:34:52Z sync ok files=3\n"
              "2026-11-04T19:50:03Z sync FAILED rc=1 pending=3 err=secret/path\n")

    def system(self):
        return meta.system_block(self.root, self.outbox, "/mnt/nas", self.sync_log, fake_run)


class UpsInSystemBlock(Tree):
    """The OpenUPS2 status from the monitor's file in /run (issue #29)."""
    NOW = 1794800000.0   # 2026-11-17T05:33:20Z

    def status(self, age=5, **over):
        doc = {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.NOW - age)), "ok": True,
               "fw": "1.6", "source": "mains", "vin": 15.1, "vout": 15.0, "vbat": 10.7,
               "cells": [3.57, 3.56, 3.57], "temps": [24, 24, 25], "ichg": 0.0, "idchg": 0.0,
               "flags": "002000", "cfg_switch": 0, "ups_state": "03", "chg_state": "0f", "pct": 88,
               "present": [True, True, True], "rte_min": None}
        doc.update(over)
        write(self.root, "run/sunset-ups.json", json.dumps(doc))

    def ups_system(self):
        return meta.system_block(self.root, self.outbox, "/mnt/nas", self.sync_log, fake_run,
                                 now=self.NOW)

    def test_no_ups_monitor_no_block_and_nothing_unavailable(self):
        s = self.ups_system()
        for k in ("ups", "ups_source", "ups_charge_pct"):
            self.assertNotIn(k, s)
        self.assertNotIn("ups", s["unavailable"])

    def test_current_status_is_copied(self):
        self.status()
        s = self.ups_system()
        self.assertEqual(s["ups_source"], "mains")
        self.assertEqual(s["ups_charge_pct"], 88)
        u = s["ups"]
        self.assertTrue(u["ok"])
        self.assertEqual(u["age_s"], 5)
        self.assertEqual(u["cells"], [3.57, 3.56, 3.57])
        self.assertEqual(u["temps"], [24, 24, 25])
        self.assertEqual(u["vin"], 15.1)
        for k in ("vout", "vbat", "ichg", "idchg", "present", "ups_state", "chg_state", "flags",
                  "fw", "rte_min"):
            self.assertIn(k, u)

    def test_on_battery(self):
        self.status(source="battery", vin=0.0, pct=41, idchg=0.6)
        s = self.ups_system()
        self.assertEqual(s["ups_source"], "battery")
        self.assertEqual(s["ups"]["idchg"], 0.6)

    def test_stale_status_is_not_passed_off_as_current(self):
        self.status(age=600)
        s = self.ups_system()
        self.assertIsNone(s["ups_source"])
        self.assertIsNone(s["ups_charge_pct"])
        self.assertEqual(s["ups"], {"age_s": 600, "ok": False, "error": "stale"})

    def test_monitor_cannot_read_the_board(self):
        write(self.root, "run/sunset-ups.json", json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.NOW)), "ok": False,
            "error": "[Errno 2] No such file or directory: '/dev/hidraw0'"}))
        u = self.ups_system()["ups"]
        self.assertFalse(u["ok"])
        self.assertNotIn("/dev", u["error"])
        self.assertIn("No such file", u["error"])
        self.assertNotIn("cells", u)

    def test_a_damaged_status_file_is_named_not_fatal(self):
        write(self.root, "run/sunset-ups.json", "{not json")
        s = self.ups_system()
        self.assertIn("ups", s["unavailable"])
        self.assertIsNone(s["ups"])
        self.assertIsNone(s["ups_source"])
        self.assertEqual(s["cpu_temp_c"], 52.6)

    def test_status_file_path_from_the_environment(self):
        other = os.path.join(self.root, "elsewhere.json")
        write(self.root, "elsewhere.json", json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.NOW)), "ok": True,
            "source": "usb", "pct": 0}))
        os.environ["UPS_STATUS_FILE"] = other
        self.addCleanup(os.environ.pop, "UPS_STATUS_FILE", None)
        self.assertEqual(self.ups_system()["ups_source"], "usb")


class SystemBlock(Tree):
    def test_cpu_temperature_and_power(self):
        s = self.system()
        self.assertEqual(s["cpu_temp_c"], 52.6)
        self.assertEqual(s["throttled"], "0x50005")
        self.assertEqual(s["core_volts"], 1.2)
        self.assertEqual(s["arm_clock_hz"], 600064000)

    def test_load_uptime_and_memory(self):
        s = self.system()
        self.assertEqual(s["uptime_s"], 47248)
        self.assertEqual(s["load"], [0.10, 0.12, 0.09])
        self.assertEqual(s["memory_available_mb"], 794)

    def test_disk_space_of_the_outbox_filesystem(self):
        d = self.system()["disk"]
        self.assertNotIn("total_bytes", d)
        self.assertGreaterEqual(d["free_bytes"], 0)
        self.assertTrue(0 <= d["used_pct"] <= 100)

    def test_counts_frames_not_yet_on_the_nas_and_skips_partial(self):
        self.assertEqual(self.system()["outbox_pending"], {"files": 2, "bytes": 7})

    def test_sd_card_writes(self):
        self.assertEqual(self.system()["sd_sectors"], {"read": 236506, "written": 8975345})

    def test_network_state_and_wifi_signal(self):
        n = self.system()["network"]
        self.assertEqual(n["eth0"], {"state": "down"})
        self.assertEqual(n["wlan0"], {"state": "up", "link_quality": 64, "signal_dbm": -46})
        self.assertNotIn("lo", n)

    def test_clock(self):
        c = self.system()["clock"]
        self.assertIs(c["ntp_synced"], True)
        self.assertNotIn("timezone", c)
        self.assertEqual(c["ntp_offset_ms"], 0.499)

    def test_nas_state_comes_from_the_mount_table_and_sync_log(self):
        n = self.system()["nas"]
        self.assertIs(n["mounted"], True)
        self.assertEqual(n["last_sync_ok_utc"], "2026-11-04T19:34:52Z")
        self.assertEqual(n["last_sync_utc"], "2026-11-04T19:50:03Z")
        self.assertEqual(n["last_sync_status"], "FAILED")

    def test_nas_unmounted(self):
        s = meta.system_block(self.root, self.outbox, "/mnt/other", self.sync_log, fake_run)
        self.assertIs(s["nas"]["mounted"], False)

    def test_never_touches_the_nas_path_itself(self):
        # A dead share can hang stat() for minutes, which must not stall a capture.
        touched = []
        real = {name: getattr(os.path, name) for name in ("exists", "isdir", "ismount")}
        for name, fn in real.items():
            def spy(path, _fn=fn):
                touched.append(str(path))
                return _fn(path)
            setattr(os.path, name, spy)
        try:
            self.system()
        finally:
            for name, fn in real.items():
                setattr(os.path, name, fn)
        self.assertNotIn("/mnt/nas", touched)

    def test_slow_changing_details_are_not_repeated_on_every_frame(self):
        s = self.system()
        for key in ("hostname", "model", "board_revision", "os", "kernel", "firmware", "python",
                    "rpicam_apps", "libcamera", "camera_overlays", "sd_card", "memory_mb"):
            self.assertNotIn(key, s)

    def test_leaves_out_what_could_identify_or_locate_the_site(self):
        text = json.dumps(self.system())
        for private in ("deadbeef", "cafef00d", "b8:27:eb", "203.0.113.9", "ntp.example",
                        "secret/path", self._tmp.name):
            self.assertNotIn(private, text)

    def test_a_missing_source_is_recorded_not_fatal(self):
        os.remove(os.path.join(self.root, "sys/class/thermal/thermal_zone0/temp"))
        s = meta.system_block(self.root, self.outbox, "/mnt/nas", self.sync_log, lambda cmd: None)
        self.assertIsNone(s["cpu_temp_c"])
        self.assertIsNone(s["throttled"])
        self.assertEqual(s["load"], [0.10, 0.12, 0.09])
        self.assertIn("cpu_temp_c", s["unavailable"])
        self.assertIn("throttled", s["unavailable"])

    def test_works_on_an_empty_tree(self):
        with tempfile.TemporaryDirectory() as empty:
            s = meta.system_block(empty, os.path.join(empty, "none"), "", "", lambda cmd: None)
        json.dumps(s)
        self.assertIn("cpu_temp_c", s["unavailable"])


class DailyFields(Tree):
    def fields(self, **over):
        values = dict(setup_id="pilot-1", setup_note="before the bracket", script=None)
        values.update(over)
        return meta.daily_fields(self.root, self.outbox, fake_run, **values)[0]

    def test_identifies_hardware_and_software(self):
        f = self.fields()
        self.assertEqual(f["hostname"], socket.gethostname())
        self.assertEqual(f["model"], "Raspberry Pi 3 Model B Plus Rev 1.3")
        self.assertEqual(f["board_revision"], "a020d3")
        self.assertEqual(f["kernel"], "6.12.109+rpt-rpi-v7")
        self.assertEqual(f["os"], "Raspbian GNU/Linux 12 (bookworm)")
        self.assertEqual(f["firmware"], "a8698392")
        self.assertIn("v1.9.0", f["rpicam_apps"])
        self.assertIn("v0.5.2", f["libcamera"])
        self.assertEqual(f["camera_overlays"], ["imx477"])
        self.assertEqual(f["timezone"], "America/Vancouver")
        self.assertEqual(f["memory_total_mb"], 921)
        self.assertGreater(f["disk_total_bytes"], 0)

    def test_sd_card_identity_without_serial(self):
        sd = self.fields()["sd_card"]
        self.assertEqual(sd["name"], "SH32G")
        self.assertEqual(sd["manfid"], "0x000003")
        self.assertNotIn("sectors_written", sd)

    def test_setup_and_script_version(self):
        script = os.path.join(self.root, "script.sh")
        write(self.root, "script.sh", "echo hi\n")
        f = self.fields(script=script)
        self.assertEqual(f["setup_id"], "pilot-1")
        self.assertEqual(f["setup_note"], "before the bracket")
        self.assertEqual(f["capture_script_sha256"], hashlib.sha256(b"echo hi\n").hexdigest())

    def test_leaves_out_what_could_identify_or_locate_the_site(self):
        text = json.dumps(self.fields(script=None))
        for private in ("deadbeef", "cafef00d", "b8:27:eb", "203.0.113.9", "ntp.example", self._tmp.name):
            self.assertNotIn(private, text)

    def test_a_failed_probe_is_named(self):
        fields, missing = meta.daily_fields(self.root, self.outbox, lambda cmd: None, None, None, None)
        self.assertIsNone(fields["firmware"])
        self.assertIn("firmware", missing)
        self.assertEqual(fields["kernel"], "6.12.109+rpt-rpi-v7")


class DailyFile(Tree):
    """system.json in the day's folder, which the sync removes from the outbox once copied."""

    DAY = "wide/2026/11/04/system.json"

    def update(self, slot="20261104T190000Z", **fields):
        values = dict(kernel="6.12", firmware="a", setup_note="x")
        values.update(fields)
        return meta.update_daily(self.outbox, "wide", slot, values, [])

    def daily(self, rel=None):
        with open(os.path.join(self.outbox, rel or self.DAY)) as f:
            return json.load(f)

    def test_first_frame_of_the_day_writes_it(self):
        system_id = self.update()
        d = self.daily()
        self.assertEqual(d["day_utc"], "2026-11-04")
        self.assertEqual(d["camera"], "wide")
        self.assertIsInstance(d["schema_version"], int)
        self.assertEqual(len(d["records"]), 1)
        self.assertEqual(d["records"][0]["system_id"], system_id)
        self.assertEqual(d["records"][0]["from_utc"], "2026-11-04T19:00:00Z")
        self.assertEqual(d["records"][0]["kernel"], "6.12")

    def test_not_written_again_when_nothing_changed(self):
        first = self.update()
        os.remove(os.path.join(self.outbox, self.DAY))       # as the sync does
        self.assertEqual(self.update(slot="20261104T191500Z"), first)
        self.assertFalse(os.path.exists(os.path.join(self.outbox, self.DAY)))

    def test_a_change_during_the_day_adds_a_record_and_keeps_the_first(self):
        first = self.update()
        os.remove(os.path.join(self.outbox, self.DAY))
        second = self.update(slot="20261104T210000Z", setup_note="on the bracket")
        self.assertNotEqual(first, second)
        records = self.daily()["records"]
        self.assertEqual([r["system_id"] for r in records], [first, second])
        self.assertEqual(records[1]["from_utc"], "2026-11-04T21:00:00Z")
        self.assertEqual(records[0]["setup_note"], "x")

    def test_each_utc_day_gets_its_own_file(self):
        self.update()
        self.update(slot="20261105T000000Z")
        self.assertEqual(len(self.daily("wide/2026/11/05/system.json")["records"]), 1)
        self.assertEqual(self.daily()["day_utc"], "2026-11-04")

    def test_a_probe_failing_once_keeps_the_last_value_and_adds_no_record(self):
        first = self.update()
        self.assertEqual(self.update(slot="20261104T191500Z", firmware=None), first)
        self.assertEqual(self.daily()["records"][0]["firmware"], "a")

    def test_a_damaged_state_file_starts_again(self):
        self.update()
        with open(os.path.join(self.root, "home/.system-state-wide.json"), "w") as f:
            f.write("{broken")
        self.update(slot="20261104T191500Z")
        self.assertEqual(len(self.daily()["records"]), 1)

    def test_an_empty_day_file_is_written_again_from_the_state(self):
        # A freeze can leave the day file 0 bytes while the state file survives (CM4, Nov 16).
        first = self.update()
        for damage in ("", "{broken"):
            with open(os.path.join(self.outbox, self.DAY), "w") as f:
                f.write(damage)
            self.assertEqual(self.update(slot="20261104T191500Z"), first)
            records = self.daily()["records"]
            self.assertEqual([r["system_id"] for r in records], [first])
            self.assertEqual(records[0]["from_utc"], "2026-11-04T19:00:00Z")

    def test_the_files_are_flushed_to_disk_before_they_replace_the_old_ones(self):
        calls = []
        real = meta.os.fsync
        meta.os.fsync = lambda fd: calls.append(fd)
        try:
            self.update()
        finally:
            meta.os.fsync = real
        self.assertGreaterEqual(len(calls), 2)       # the day file and the state file

    def test_leaves_no_temp_file_the_sync_could_ship(self):
        self.update()
        names = os.listdir(os.path.dirname(os.path.join(self.outbox, self.DAY)))
        self.assertEqual(sorted(names), ["a.jpg", "a.json", "system.json"])


class CaptureBlock(Tree):
    def setUp(self):
        super().setUp()
        self.d = os.path.join(self.root, "stage")
        write(self.d, "f.jpg", "jpegdata")
        self.json_path = os.path.join(self.d, "f.json")
        write(self.d, "f.json", json.dumps({"ExposureTime": 1000, "Lux": 2.5,
                                            "FrameWallClock": 1793818803664766720,
                                            "Sun": {"azimuth_deg": 1.0}}))

    def args(self, **over):
        values = dict(kind="night", camera="wide", slot="20261104T190000Z", started=1793818800.25,
                      finished=1793818812.75, setup_id="pilot-1", system_id="abc123",
                      settings=["shutter_us=8000000", "gain=4", "awbgains=1.6,1.8"],
                      decision_lux="2.5", checksums=True)
        values.update(over)
        return values

    def block(self, **over):
        return meta.capture_block(self.json_path, {"FrameWallClock": 1793818803664766720},
                                  **self.args(**over))

    def test_records_timing(self):
        c = self.block()
        self.assertEqual(c["slot_utc"], "2026-11-04T19:00:00Z")
        self.assertEqual(c["shot_seconds"], 12.5)
        self.assertEqual(c["shot_started_utc"], "2026-11-04T19:00:00Z")
        self.assertEqual(c["frame_wall_clock_utc"], "2026-11-04T19:00:03Z")

    def test_records_what_was_asked_for(self):
        c = self.block()
        self.assertEqual(c["kind"], "night")
        self.assertEqual(c["camera"], "wide")
        self.assertEqual(c["setup_id"], "pilot-1")
        self.assertEqual(c["system_id"], "abc123")
        self.assertEqual(c["settings"], {"shutter_us": 8000000, "gain": 4, "awbgains": "1.6,1.8"})
        self.assertEqual(c["decision_lux"], 2.5)
        self.assertIsInstance(c["schema_version"], int)

    def test_file_sizes_and_checksums_for_later_integrity_checks(self):
        files = self.block()["files"]
        self.assertEqual(files["jpg"], {"bytes": 8, "sha256": hashlib.sha256(b"jpegdata").hexdigest()})

    def test_checksums_can_be_turned_off_for_bursts(self):
        self.assertEqual(self.block(checksums=False)["files"]["jpg"], {"bytes": 8})

    def test_only_the_jpeg_is_listed(self):
        # No DNGs since 2026-11-16 (#38): a stray one beside the frame is not recorded.
        write(self.d, "f.dng", "dngdata")
        self.assertEqual(sorted(self.block()["files"]), ["jpg"])


class Annotate(CaptureBlock):
    def run_main(self, *extra):
        return meta.main(["annotate", self.json_path, "--kind", "auto", "--camera", "wide",
                          "--slot", "20261104T190000Z", "--started", "1793818800", "--finished", "1793818805",
                          "--outbox", self.outbox, "--root", self.root] + list(extra))

    def test_keeps_camera_and_sun_fields_and_adds_blocks(self):
        self.assertEqual(self.run_main(), 0)
        with open(self.json_path) as f:
            data = json.load(f)
        self.assertEqual(data["ExposureTime"], 1000)
        self.assertEqual(data["Lux"], 2.5)
        self.assertEqual(data["Sun"], {"azimuth_deg": 1.0})
        self.assertIn("Capture", data)
        self.assertIn("System", data)

    def test_links_the_frame_to_the_days_file(self):
        self.run_main()
        with open(self.json_path) as f:
            data = json.load(f)
        with open(os.path.join(self.outbox, "wide/2026/11/04/system.json")) as f:
            daily = json.load(f)
        self.assertEqual(data["Capture"]["system_id"], daily["records"][0]["system_id"])
        self.assertNotIn("kernel", data["System"])

    def test_system_file_failure_never_costs_the_frame(self):
        real = meta.update_daily
        def broken(*args):
            raise OSError("disk")
        meta.update_daily = broken
        try:
            self.assertEqual(self.run_main(), 0)
        finally:
            meta.update_daily = real
        with open(self.json_path) as f:
            data = json.load(f)
        self.assertIsNone(data["Capture"]["system_id"])
        self.assertIn("system_json", data["System"]["unavailable"])

    def test_leaves_nothing_a_publish_glob_would_move(self):
        self.run_main()
        self.assertEqual(sorted(os.listdir(self.d)), ["f.jpg", "f.json"])

    def test_regular_schedule_by_default(self):
        self.run_main()
        with open(self.json_path) as f:
            self.assertEqual(json.load(f)["Capture"]["schedule"], "regular")

    def test_dense_frames_are_marked(self):
        self.assertEqual(self.run_main("--schedule", "dense"), 0)
        with open(self.json_path) as f:
            self.assertEqual(json.load(f)["Capture"]["schedule"], "dense")

    def test_unknown_schedule_is_refused(self):
        with self.assertRaises(SystemExit):
            self.run_main("--schedule", "burst")

    def load(self):
        with open(self.json_path) as f:
            return json.load(f)

    def test_bad_json_starts_again_from_nothing_and_says_so(self):
        # #27: Capture and System don't need rpicam's metadata, so the frame still gets them.
        with open(self.json_path, "w") as f:
            f.write("{not json")
        self.assertEqual(self.run_main(), 0)
        data = self.load()
        self.assertEqual(data["rpicam_metadata"], "invalid")
        self.assertEqual(data["Capture"]["kind"], "auto")
        self.assertIn("System", data)

    def test_missing_metadata_file_still_gets_a_json(self):
        os.remove(self.json_path)
        self.assertEqual(self.run_main(), 0)
        data = self.load()
        self.assertEqual(data["rpicam_metadata"], "missing")
        self.assertIn("sha256", data["Capture"]["files"]["jpg"])
        self.assertNotIn("frame_wall_clock_utc", data["Capture"])

    def test_a_flag_from_the_sun_step_is_kept(self):
        with open(self.json_path, "w") as f:
            json.dump({"rpicam_metadata": "invalid", "Sun": {"azimuth_deg": 1.0}}, f)
        self.run_main()
        self.assertEqual(self.load()["rpicam_metadata"], "invalid")

    def test_good_metadata_is_not_flagged(self):
        self.run_main()
        self.assertNotIn("rpicam_metadata", self.load())

    def test_unknown_kind_is_still_an_argument_error(self):
        with self.assertRaises(SystemExit) as e:
            meta.main(["annotate", self.json_path, "--kind", "banana", "--camera", "wide",
                       "--slot", "20261104T190000Z", "--started", "1", "--finished", "2", "--outbox", self.outbox])
        self.assertEqual(e.exception.code, 2)

    def test_capture_is_on_disk_before_the_system_probes_run(self):
        # The capture kills this script after 30 s. Capture, with the checksums, must survive that.
        real = meta.system_block

        def killed(*args, **kw):
            raise SystemExit("killed by timeout")
        meta.system_block = killed
        try:
            with self.assertRaises(SystemExit):
                self.run_main()
        finally:
            meta.system_block = real
        data = self.load()
        self.assertEqual(data["Capture"]["files"]["jpg"]["sha256"], hashlib.sha256(b"jpegdata").hexdigest())
        self.assertNotIn("System", data)
        self.assertEqual(sorted(os.listdir(self.d)), ["f.jpg", "f.json"])

    def test_deadline_option(self):
        self.assertEqual(self.run_main("--deadline", "0"), 0)
        data = self.load()
        self.assertIn("Capture", data)
        self.assertTrue(data["System"]["cut_short"])
        self.assertIn("cpu_temp_c", data["System"]["unavailable"])


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Deadline(Tree):
    """#27: seven probes at up to 5 s each, inside the capture's 30 s kill. Stop in time instead."""

    def test_probes_after_the_deadline_are_skipped_and_named(self):
        clock = FakeClock()
        deadline = meta.Deadline(15, clock)
        calls = []

        def slow_run(cmd):
            calls.append(cmd)
            clock.t += 6                     # each command takes 6 s on a struggling Pi
            return fake_run(cmd)
        s = meta.system_block(self.root, self.outbox, "/mnt/nas", self.sync_log, slow_run, deadline=deadline)
        self.assertLessEqual(len(calls), 3)
        self.assertTrue(s["cut_short"])
        self.assertIn("clock", s["unavailable"])
        self.assertIsNone(s["clock"])
        self.assertEqual(s["cpu_temp_c"], 52.6)          # what ran before the deadline is kept

    def test_no_flag_when_everything_ran(self):
        s = meta.system_block(self.root, self.outbox, "/mnt/nas", self.sync_log, fake_run,
                              deadline=meta.Deadline(15))
        self.assertNotIn("cut_short", s)
        self.assertEqual(s["unavailable"], [])

    def test_expired_deadline_skips_checksums_but_keeps_sizes(self):
        d = os.path.join(self.root, "stage")
        write(d, "f.jpg", "jpegdata")
        block = meta.capture_block(os.path.join(d, "f.json"), {}, kind="auto", camera="wide",
                                   slot="20261104T190000Z", started=1, finished=2, setup_id=None,
                                   system_id=None, settings=[], decision_lux=None, checksums=True,
                                   deadline=meta.Deadline(0))
        self.assertEqual(block["files"]["jpg"], {"bytes": 8})
        self.assertEqual(block["unavailable"], ["sha256"])

    def test_commands_are_given_no_more_than_the_time_left(self):
        clock = FakeClock()
        deadline = meta.Deadline(3, clock)
        self.assertEqual(deadline.timeout(5), 3)
        clock.t += 10
        self.assertEqual(deadline.timeout(5), 0)
        self.assertTrue(deadline.expired())


class EmmcWear(Tree):
    """#22: the CM4's eMMC reports its own wear; an SD card does not have these files."""

    def test_emmc_wear_is_recorded_when_present(self):
        write(self.root, "sys/block/mmcblk0/device/life_time", "0x01 0x02\n")
        write(self.root, "sys/block/mmcblk0/device/pre_eol_info", "0x01\n")
        sd = meta.daily_fields(self.root, self.outbox, fake_run, None, None, None)[0]["sd_card"]
        self.assertEqual(sd["life_time"], "0x01 0x02")
        self.assertEqual(sd["pre_eol_info"], "0x01")
        self.assertEqual(sd["name"], "SH32G")

    def test_sd_card_without_them_has_no_such_keys(self):
        sd = meta.daily_fields(self.root, self.outbox, fake_run, None, None, None)[0]["sd_card"]
        self.assertNotIn("life_time", sd)
        self.assertNotIn("pre_eol_info", sd)

    def test_a_change_in_wear_starts_a_new_daily_record(self):
        write(self.root, "sys/block/mmcblk0/device/life_time", "0x01 0x01\n")
        first = meta.update_daily(self.outbox, "wide", "20261104T190000Z",
                                  *meta.daily_fields(self.root, self.outbox, fake_run, None, None, None))
        write(self.root, "sys/block/mmcblk0/device/life_time", "0x02 0x01\n")
        second = meta.update_daily(self.outbox, "wide", "20261104T191500Z",
                                   *meta.daily_fields(self.root, self.outbox, fake_run, None, None, None))
        self.assertNotEqual(first, second)


class DailyCache(CaptureBlock):
    """#27: `rpicam-still --version` and `vcgencmd version` ran on every frame (about 500 a day)
    while the capture held the camera lock. Once per UTC day and boot is enough."""

    SLOW = (("rpicam-still", "--version"), ("vcgencmd", "version"))

    def setUp(self):
        super().setUp()
        write(self.root, "proc/sys/kernel/random/boot_id", "boot-1\n")
        self.calls = []
        real = meta.run_command

        def counting(cmd, timeout=None):
            self.calls.append(tuple(cmd))
            return fake_run(cmd)
        meta.run_command = counting
        self.addCleanup(setattr, meta, "run_command", real)

    def annotate(self, slot="20261104T190000Z"):
        self.assertEqual(meta.main(["annotate", self.json_path, "--kind", "auto", "--camera", "wide",
                                    "--slot", slot, "--started", "1793818800", "--finished", "1793818805",
                                    "--outbox", self.outbox, "--root", self.root]), 0)

    def slow_calls(self):
        return [c for c in self.calls if c in self.SLOW]

    def daily(self):
        with open(os.path.join(self.outbox, "wide/2026/11/04/system.json")) as f:
            return json.load(f)["records"]

    def test_versions_are_probed_once_a_day(self):
        self.annotate()
        self.annotate("20261104T190500Z")
        self.annotate("20261104T191000Z")
        self.assertEqual(sorted(self.slow_calls()), sorted(self.SLOW))
        self.assertEqual(len(self.daily()), 1)
        self.assertEqual(self.daily()[0]["firmware"], "a8698392")
        self.assertIn("v1.9.0", self.daily()[0]["rpicam_apps"])

    def test_probed_again_on_a_new_utc_day(self):
        self.annotate()
        self.annotate("20261105T000000Z")
        self.assertEqual(len(self.slow_calls()), 4)

    def test_probed_again_after_a_reboot(self):
        self.annotate()
        write(self.root, "proc/sys/kernel/random/boot_id", "boot-2\n")
        self.annotate("20261104T190500Z")
        self.assertEqual(len(self.slow_calls()), 4)

    def test_a_failed_probe_is_not_cached(self):
        meta.run_command = lambda cmd, timeout=None: self.calls.append(tuple(cmd))
        self.annotate()
        meta.run_command = lambda cmd, timeout=None: (self.calls.append(tuple(cmd)), fake_run(cmd))[1]
        self.annotate("20261104T190500Z")
        self.assertEqual(len(self.slow_calls()), 4)
        self.assertEqual(self.daily()[-1]["firmware"], "a8698392")

    def test_cache_file_stays_out_of_the_outbox(self):
        self.annotate()
        names = [n for n in os.listdir(os.path.dirname(self.outbox)) if "cache" in n]
        self.assertEqual(names, [".meta-cache.json"])
        for folder, _, files in os.walk(self.outbox):
            self.assertFalse([f for f in files if "cache" in f], folder)


if __name__ == "__main__":
    unittest.main()
