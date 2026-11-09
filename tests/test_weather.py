#!/usr/bin/env python3
"""Offline tests for the forecast logger (experiment 17). No network, Pi or NAS needed."""
import importlib.util
import json
import pathlib
import tempfile
import unittest
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("sunset_weather", ROOT / "experiments" / "sunset-weather.py")
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)

LAT, LON = 49.24681, -122.98765  # made up, near enough to be realistic
NOW = 1794187200  # 2026-11-09T01:20:00Z


def query(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)


def fake_fetch(responses):
    def fetch(url):
        for key, body in responses.items():
            if key in url:
                return dict(body)
        raise OSError("no route")
    return fetch


FORECAST = {"latitude": 49.25, "longitude": -122.99, "elevation": 40.0, "timezone": "GMT",
            "hourly": {"time": ["2026-11-09T00:00"], "cloud_cover_low_best_match": [12]}}
AIR = {"latitude": 49.2, "longitude": -123.0, "elevation": 40.0,
       "hourly": {"time": ["2026-11-09T00:00"], "pm2_5": [3.1]}}


class ReadSite(unittest.TestCase):
    def test_reads_plain_and_quoted_values(self):
        env = 'SETUP_ID=pilot-3\nSITE_LAT="49.24681"\nSITE_LON=-122.98765\n'
        self.assertEqual(w.read_site(env), (49.24681, -122.98765))

    def test_ignores_comments(self):
        env = "# SITE_LAT=1\nSITE_LAT=49.1\nSITE_LON=-123.2\n"
        self.assertEqual(w.read_site(env), (49.1, -123.2))

    def test_missing_coordinates_is_an_error(self):
        with self.assertRaises(ValueError):
            w.read_site("SETUP_ID=pilot-3\n")


class Urls(unittest.TestCase):
    def test_requests_use_the_position_rounded_to_a_tenth_of_a_degree(self):
        for url in w.build_urls(LAT, LON).values():
            q = query(url)
            self.assertEqual(q["latitude"], ["49.2"])
            self.assertEqual(q["longitude"], ["-123.0"])
            self.assertNotIn("49.24", url)
            self.assertNotIn("122.98", url)

    def test_forecast_asks_for_cloud_layers_from_both_models_in_utc(self):
        q = query(w.build_urls(LAT, LON)["forecast"])
        for field in ("cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "visibility",
                      "dew_point_2m", "direct_radiation"):
            self.assertIn(field, q["hourly"][0].split(","))
        self.assertEqual(q["models"], ["best_match,gem_seamless"])
        self.assertEqual(q["timezone"], ["UTC"])

    def test_air_quality_asks_for_smoke_and_haze(self):
        q = query(w.build_urls(LAT, LON)["air_quality"])
        self.assertIn("pm2_5", q["hourly"][0].split(","))
        self.assertIn("aerosol_optical_depth", q["hourly"][0].split(","))


class OutPath(unittest.TestCase):
    def test_utc_day_folders_and_utc_name(self):
        p = w.out_path(pathlib.Path("/r"), NOW)
        self.assertEqual(p.as_posix(), "/r/2026/11/09/forecast_20261109T012000Z.json")


class Fetch(unittest.TestCase):
    def run_once(self, fetch):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        code = w.fetch_and_save(LAT, LON, root, NOW, fetch)
        return code, sorted(root.rglob("*.json"))

    def test_saves_both_responses_without_any_position(self):
        code, files = self.run_once(fake_fetch({"/v1/forecast": FORECAST,
                                                "/v1/air-quality": AIR}))
        self.assertEqual(code, 0)
        self.assertEqual(len(files), 1)
        text = files[0].read_text()
        saved = json.loads(text)
        self.assertEqual(saved["fetched_utc"], "2026-11-09T01:20:00Z")
        self.assertEqual(saved["forecast"]["hourly"]["cloud_cover_low_best_match"], [12])
        self.assertEqual(saved["air_quality"]["hourly"]["pm2_5"], [3.1])
        for block in (saved["forecast"], saved["air_quality"]):
            for key in ("latitude", "longitude", "elevation"):
                self.assertNotIn(key, block)
        for leak in ("49.2", "122.9", "123.0", "-123"):
            self.assertNotIn(leak, text)

    def test_air_quality_failure_still_saves_the_forecast(self):
        code, files = self.run_once(fake_fetch({"/v1/forecast": FORECAST}))
        self.assertEqual(code, 0)
        saved = json.loads(files[0].read_text())
        self.assertIn("forecast", saved)
        self.assertIn("error", saved["air_quality"])

    def test_no_network_saves_nothing_and_fails(self):
        code, files = self.run_once(fake_fetch({}))
        self.assertEqual(code, 1)
        self.assertEqual(files, [])

    def test_no_partial_file_left_behind(self):
        code, _ = self.run_once(fake_fetch({"/v1/forecast": FORECAST, "/v1/air-quality": AIR}))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        w.fetch_and_save(LAT, LON, root, NOW, fake_fetch({"/v1/forecast": FORECAST}))
        self.assertEqual([p.name for p in root.rglob("*.tmp")], [])


class Timer(unittest.TestCase):
    def test_runs_hourly_clear_of_the_capture_slots(self):
        text = (ROOT / "experiments" / "systemd" / "exp-weather.timer").read_text()
        spec = [l.split("=", 1)[1].strip() for l in text.splitlines() if l.startswith("OnCalendar=")][0]
        minute = int(spec.split(":")[1])
        self.assertNotEqual(minute % 5, 0, "would share a minute with a regular capture")
        self.assertNotEqual(minute % 5, 1, "would share a minute with the experiment extras")
        self.assertIn("Persistent=true", text)


if __name__ == "__main__":
    unittest.main()
