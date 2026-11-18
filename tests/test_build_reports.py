"""Offline tests for tools/build_reports.py (thumbnail and day tests skipped without Pillow): the per-day summary, the sunset thumbnail, the sky
score graph and the report page. Synthetic frames in a temporary folder; no NAS, no ffmpeg."""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import build_reports as br  # noqa: E402

try:
    from PIL import Image  # noqa: E402
except ImportError:          # the tool runs on the PC; elsewhere only the parts without images are tested
    Image = None
NEEDS_PIL = unittest.skipIf(Image is None, "needs Pillow")

UTC = dt.timezone.utc
DAY = dt.date(2026, 11, 17)
SUNSET = dt.datetime(2026, 11, 18, 0, 27, 40, tzinfo=UTC)   # 5:27 pm Nov 17, Vancouver
CROP = {"calibrations": [{
    "start": "2026-11-11", "setup_id": "cm4-window-3", "cx": 2028, "blur": [[0, 0, 300, 300]], "blur_sigma": 5,
    "sky_full_warm": 0.178, "fits": [{"date": "2026-11-11", "f_px": 1880.0, "az0_deg": 272.3}]}]}


def frame_json(t, schedule="regular", setup="cm4-window-3", temp=45.0, uptime=1000, throttled="0x0", pending=0):
    minutes = (t - SUNSET).total_seconds() / 60.0
    return {"Lux": 100.0,
            "Sun": {"azimuth_deg": 240.0 + minutes * 0.2, "elevation_deg": -minutes * 0.15,
                    "nearest_sunset_utc": SUNSET.strftime("%Y-%m-%dT%H:%M:%SZ"), "minutes_from_sunset": minutes},
            "Capture": {"schedule": schedule, "setup_id": setup, "kind": "auto"},
            "System": {"cpu_temp_c": temp, "uptime_s": uptime, "throttled": throttled,
                       "outbox_pending": {"files": pending, "bytes": pending * 1000},
                       "network": {"wlan0": {"state": "up", "signal_dbm": -55}}}}


class Frames:
    """A camera folder with frames for one local day."""

    def __init__(self, root, camera="cm4wide"):
        self.dir = os.path.join(root, camera)

    def add(self, t, suffix="", size=(64, 48), colour=(90, 90, 90), **meta):
        folder = os.path.join(self.dir, t.strftime("%Y"), t.strftime("%m"), t.strftime("%d"))
        os.makedirs(folder, exist_ok=True)
        name = "cm4wide_%s%s" % (t.strftime("%Y%m%dT%H%M%SZ"), suffix)
        Image.new("RGB", size, colour).save(os.path.join(folder, name + ".jpg"))
        with open(os.path.join(folder, name + ".json"), "w") as f:
            json.dump(frame_json(t, **meta), f)
        return os.path.join(folder, name + ".jpg")


def local_midnight(day):
    return dt.datetime(day.year, day.month, day.day, tzinfo=br.VAN_TZ).astimezone(UTC)


class TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.frames = Frames(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)


class Changelog(unittest.TestCase):
    TEXT = """# Changelog

## 2026-11-18

- **Fix: the health check gave Vancouver times an hour early.** More text.

## 2026-11-17

- **Event: clear sunset, the first one for the new aim** (Steven). Sunset 00:27 UTC.
  - **`cm4wide`:** a sub-bullet, not an event.
- **Daily video: the sky score is drawn on the video** (Steven).
- **Event: the CM4's network keeps dropping for about 2 minutes.** Details.
"""

    def test_events_by_local_date(self):
        events = br.changelog_events(self.TEXT)
        self.assertEqual(events[dt.date(2026, 11, 17)],
                         ["clear sunset, the first one for the new aim",
                          "the CM4's network keeps dropping for about 2 minutes"])

    def test_days_without_events_are_left_out(self):
        self.assertNotIn(dt.date(2026, 11, 18), br.changelog_events(self.TEXT))


class SunPoint(unittest.TestCase):
    def test_column_from_calibration_and_row_from_setup(self):
        x, y = br.sun_point(CROP, DAY, "cm4-window-3", 239.82)
        self.assertAlmostEqual(x, 831, delta=2)       # measured on the Nov 17 frame: about 825
        self.assertEqual(y, br.HORIZON_Y["cm4-window-3"])

    def test_unknown_setup_has_no_point(self):
        self.assertIsNone(br.sun_point(CROP, DAY, "cm4-desk-1", 239.8))

    def test_no_calibration_has_no_point(self):
        self.assertIsNone(br.sun_point({"calibrations": []}, DAY, "cm4-window-3", 239.8))


@NEEDS_PIL
class Thumbnail(TempDir):
    def test_at_most_100_px_with_the_point_centred_and_low(self):
        src = os.path.join(self.tmp, "f.jpg")
        img = Image.new("RGB", (4056, 3040), (20, 20, 80))
        img.paste((255, 0, 0), (800, 1280, 860, 1340))          # a red "sun" at (830, 1310)
        img.save(src)
        out = os.path.join(self.tmp, "t.jpg")
        br.make_thumbnail(src, out, (830, 1310), blur=[], sigma=5)
        thumb = Image.open(out)
        self.assertLessEqual(max(thumb.size), 100)
        # Mostly sky above the horizon: the point sits 70% of the way down, not in the middle.
        r, g, b = thumb.convert("RGB").getpixel((thumb.size[0] // 2, int(thumb.size[1] * br.THUMB_HORIZON_AT)))
        self.assertEqual(br.THUMB_HORIZON_AT, 0.7)
        self.assertGreater(r, 200)
        self.assertLess(b, 80)

    def test_point_near_the_edge_stays_inside_the_frame(self):
        src = os.path.join(self.tmp, "f.jpg")
        Image.new("RGB", (4056, 3040), (20, 20, 80)).save(src)
        out = os.path.join(self.tmp, "t.jpg")
        br.make_thumbnail(src, out, (10, 10), blur=[], sigma=5)
        self.assertEqual(Image.open(out).size, (100, 100))

    def test_blur_boxes_are_blurred_first(self):
        src = os.path.join(self.tmp, "f.jpg")
        img = Image.new("RGB", (4056, 3040), (0, 0, 0))
        for x in range(600, 1100, 8):                            # fine stripes inside a blur box
            img.paste((255, 255, 255), (x, 1100, x + 4, 1500))
        img.save(src)
        sharp, soft = os.path.join(self.tmp, "a.jpg"), os.path.join(self.tmp, "b.jpg")
        br.make_thumbnail(src, sharp, (830, 1310), blur=[], sigma=5)
        br.make_thumbnail(src, soft, (830, 1310), blur=[[500, 1000, 700, 600]], sigma=40)

        def spread(path):
            px = list(Image.open(path).convert("L").getdata())
            return max(px) - min(px)
        self.assertLess(spread(soft), spread(sharp))

    def test_no_metadata_in_the_thumbnail(self):
        src = os.path.join(self.tmp, "f.jpg")
        Image.new("RGB", (4056, 3040)).save(src, exif=b"Exif\x00\x00II*\x00\x08\x00\x00\x00\x00\x00")
        out = os.path.join(self.tmp, "t.jpg")
        br.make_thumbnail(src, out, (830, 1310), blur=[], sigma=5)
        self.assertNotIn("exif", Image.open(out).info)


class FirstDay(unittest.TestCase):
    def test_wide_camera_starts_on_its_first_full_day_at_the_window(self):
        self.assertEqual(br.FIRST_DAY["cm4wide"], dt.date(2026, 11, 12))


@NEEDS_PIL
class DaySummary(TempDir):
    def build_day(self):
        start = local_midnight(DAY)
        for i in range(288):
            t = start + dt.timedelta(minutes=5 * i)
            if 100 <= i < 103:                                   # three missing slots
                continue
            self.frames.add(t, temp=40.0 + (i % 10), uptime=1000 + i * 300 if i < 200 else (i - 200) * 300 + 60)
        for m in (26, 27, 28, 29):                               # dense frames near sunset, off the 5-minute slots
            self.frames.add(SUNSET.replace(minute=m, second=0), schedule="dense", uptime=2800 + m)
        sunset_slot = SUNSET.replace(minute=25, second=0)
        self.frames.add(sunset_slot, suffix="_ev0")
        self.frames.add(sunset_slot, suffix="_ev-2")
        self.frames.add(start + dt.timedelta(hours=3), suffix="_night")

    def summary(self, sky=None):
        return br.day_summary(self.frames.dir, DAY, CROP, events=["clear sunset"],
                              sky_fn=lambda frames, sunset, settings: sky)

    def test_counts(self):
        self.build_day()
        s = self.summary()
        self.assertEqual(s["frames"]["regular"], 285)
        self.assertEqual(s["frames"]["expected"], 288)
        self.assertEqual(s["frames"]["missing_slots"], 3)
        self.assertEqual(s["frames"]["dense"], 4)
        self.assertEqual(s["frames"]["bracket_pairs"], 1)
        self.assertEqual(s["frames"]["night"], 1)
        self.assertEqual(s["frames"]["largest_gap_min"], 20.0)

    def test_sunset_local_time_and_whole_degree_bearing(self):
        self.build_day()
        s = self.summary()
        self.assertEqual(s["sunset_local"], "17:27")
        self.assertIsInstance(s["sunset_bearing_deg"], int)
        self.assertEqual(s["sunset_bearing_deg"], 240)

    def test_pi_health(self):
        self.build_day()
        s = self.summary()
        self.assertEqual(s["pi"]["cpu_max_c"], 49.0)
        self.assertEqual(s["pi"]["reboots"], 1)
        self.assertFalse(s["pi"]["throttled"])

    def test_sky_and_events_and_setup(self):
        self.build_day()
        s = self.summary(sky={"score": 41, "label": "some colour", "warm_sky_percent": 8.0})
        self.assertEqual(s["sky"]["score"], 41)
        self.assertEqual(s["events"], ["clear sunset"])
        self.assertEqual(s["setup_ids"], ["cm4-window-3"])

    def test_thumbnail_frame_is_the_regular_or_dense_frame_nearest_sunset(self):
        self.build_day()
        s = self.summary()
        self.assertEqual(os.path.basename(s["thumbnail_source"]), "cm4wide_20261118T002800Z.jpg")

    def test_nothing_that_locates_the_site(self):
        self.build_day()
        text = json.dumps(br.public_day(self.summary()))
        for key in ("azimuth_deg", "elevation_deg", "nearest_sunset_utc", "minutes_from_sunset", "thumbnail_source"):
            self.assertNotIn(key, text)

    def test_empty_day(self):
        s = br.day_summary(self.frames.dir, DAY, CROP, events=[], sky_fn=lambda *a: None)
        self.assertEqual(s["frames"]["regular"], 0)
        self.assertIsNone(s["sunset_local"])
        self.assertIsNone(s["sky"])


class Weather(TempDir):
    def write(self, fetched, hours, cloud):
        folder = os.path.join(self.tmp, "w", fetched.strftime("%Y/%m/%d"))
        os.makedirs(folder, exist_ok=True)
        hourly = {"time": [h.strftime("%Y-%m-%dT%H:00") for h in hours],
                  "cloud_cover_best_match": cloud, "cloud_cover_low_best_match": [10] * len(hours),
                  "cloud_cover_mid_best_match": [20] * len(hours), "cloud_cover_high_best_match": [30] * len(hours),
                  "visibility_best_match": [24000] * len(hours), "precipitation_best_match": [0.0] * len(hours)}
        with open(os.path.join(folder, "forecast_%s.json" % fetched.strftime("%Y%m%dT%H%M%SZ")), "w") as f:
            json.dump({"fetched_utc": fetched.strftime("%Y-%m-%dT%H:%M:%SZ"), "forecast": {"hourly": hourly}}, f)

    def test_latest_forecast_before_sunset_at_the_nearest_hour(self):
        hours = [dt.datetime(2026, 11, 17, 22, tzinfo=UTC) + dt.timedelta(hours=i) for i in range(4)]
        self.write(dt.datetime(2026, 11, 17, 20, 7, tzinfo=UTC), hours, [90, 90, 90, 90])
        self.write(dt.datetime(2026, 11, 17, 23, 7, tzinfo=UTC), hours, [5, 6, 7, 8])    # hour 00 -> 7
        self.write(dt.datetime(2026, 11, 18, 1, 7, tzinfo=UTC), hours, [50, 50, 50, 50])  # after sunset
        w = br.weather_at(os.path.join(self.tmp, "w"), SUNSET)
        self.assertEqual(w["cloud_pct"], 7)
        self.assertEqual(w["low_pct"], 10)
        self.assertEqual(w["visibility_km"], 24)

    def test_no_forecast(self):
        self.assertIsNone(br.weather_at(os.path.join(self.tmp, "none"), SUNSET))


def sample_days():
    return [
        {"date": "2026-11-16", "sky": {"score": 71, "label": "colourful"}, "sunset_local": "17:28"},
        {"date": "2026-11-17", "sky": {"score": 41, "label": "some colour"}, "sunset_local": "17:27"},
        {"date": "2026-11-18", "sky": None, "sunset_local": "17:26"},
    ]


class Graph(unittest.TestCase):
    def test_valid_svg_with_a_bar_per_scored_day(self):
        svg = br.score_svg(sample_days())
        root = ET.fromstring(svg)
        ns = "{http://www.w3.org/2000/svg}"
        self.assertEqual(root.tag, ns + "svg")
        bars = [r for r in root.iter(ns + "rect") if r.get("class") == "bar"]
        self.assertEqual(len(bars), 2)
        titles = [t.text for t in root.iter(ns + "title")]
        self.assertTrue(any("71" in t and "Nov 16" in t for t in titles))

    def test_posting_threshold_and_missing_day_shown(self):
        svg = br.score_svg(sample_days())
        self.assertIn("posting threshold", svg)
        self.assertIn("no score", svg)

    def test_dark_mode_colours(self):
        self.assertIn("prefers-color-scheme: dark", br.score_svg(sample_days()))

    def test_no_days(self):
        ET.fromstring(br.score_svg([]))


class Page(unittest.TestCase):
    def days(self):
        days = sample_days()
        for d in days:
            d.update({"weekday": "Mon", "sunset_bearing_deg": 240, "thumbnail": "thumbs/cm4wide/%s.jpg" % d["date"],
                      "frames": {"regular": 288, "expected": 288, "missing_slots": 0, "dense": 90,
                                 "bracket_pairs": 80, "night": 150, "largest_gap_min": 5.0},
                      "pi": {"cpu_max_c": 50.0, "reboots": 0, "throttled": False, "outbox_max_files": 300},
                      "weather": None, "setup_ids": ["cm4-window-3"], "events": ["<b>clear</b> & calm"]})
        return days

    def test_every_day_newest_first_with_its_thumbnail(self):
        html = br.render_html(self.days(), generated=dt.datetime(2026, 11, 18, 22, 0, tzinfo=UTC), camera="cm4wide")
        body = html[html.index("<tbody>"):]
        self.assertLess(body.index("2026-11-18"), body.index("2026-11-16"))
        for d in self.days():
            self.assertIn('src="%s"' % d["thumbnail"], html)
        self.assertIn('width="100" height="100"', html)
        self.assertIn('src="sky-scores.svg"', html)

    def test_text_is_escaped(self):
        html = br.render_html(self.days(), generated=dt.datetime(2026, 11, 18, tzinfo=UTC), camera="cm4wide")
        self.assertIn("&lt;b&gt;clear&lt;/b&gt; &amp; calm", html)

    def test_says_when_it_was_made(self):
        html = br.render_html(self.days(), generated=dt.datetime(2026, 11, 18, 22, 0, tzinfo=UTC), camera="cm4wide")
        self.assertIn("2026-11-18 15:00", html)        # Vancouver, UTC-7


class Clock(unittest.TestCase):
    def test_vancouver_is_utc_minus_7_without_tzdata(self):
        self.assertEqual(br.VAN_TZ.utcoffset(None), dt.timedelta(hours=-7))
        self.assertEqual(br.local_bounds(dt.date(2027, 1, 15))[0], dt.datetime(2027, 1, 15, 7, tzinfo=UTC))


class Cache(TempDir):
    def test_finished_days_are_kept_and_recent_ones_redone(self):
        cached = {"2026-11-10": {"date": "2026-11-10", "kept": True}, "2026-11-16": {"date": "2026-11-16", "kept": True}}
        todo = br.days_to_build([dt.date(2026, 11, 10), dt.date(2026, 11, 16), dt.date(2026, 11, 17)], cached,
                                today=dt.date(2026, 11, 18), redo=False)
        self.assertEqual(todo, [dt.date(2026, 11, 16), dt.date(2026, 11, 17)])

    def test_redo_builds_every_day(self):
        days = [dt.date(2026, 11, 10), dt.date(2026, 11, 11)]
        self.assertEqual(br.days_to_build(days, {"2026-11-10": {}, "2026-11-11": {}}, dt.date(2026, 11, 30), True), days)


if __name__ == "__main__":
    unittest.main()
