"""Tests for tools/fuse_sunset.py: python3 tests/test_fuse_sunset.py (skipped without numpy and OpenCV)"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

try:
    import cv2
    import numpy as np
except ImportError:
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))
UTC = timezone.utc
SUNSET = datetime(2026, 11, 13, 0, 33, 47, tzinfo=UTC)


def load():
    spec = importlib.util.spec_from_file_location("fuse_sunset", os.path.join(os.path.dirname(HERE), "tools", "fuse_sunset.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class Weight(unittest.TestCase):
    def setUp(self):
        self.fs = load()

    def test_full_strength_in_the_middle_of_the_window(self):
        self.assertEqual(self.fs.fuse_weight(-30, 20), 1.0)
        self.assertEqual(self.fs.fuse_weight(4.9, 60), 1.0)

    def test_fades_in_over_the_first_five_minutes_of_the_run(self):
        self.assertEqual(self.fs.fuse_weight(-45, 0), 0.0)
        self.assertAlmostEqual(self.fs.fuse_weight(-43, 2), 0.4)

    def test_fades_out_between_5_and_12_minutes_after_sunset(self):
        # daylight white balance turns the sky brown once the city lights the cloud
        self.assertAlmostEqual(self.fs.fuse_weight(8.5, 60), 0.5)
        self.assertEqual(self.fs.fuse_weight(12, 60), 0.0)
        self.assertEqual(self.fs.fuse_weight(30, 60), 0.0)


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class Pixels(unittest.TestCase):
    def setUp(self):
        self.fs = load()

    def test_blend_goes_from_the_production_frame_to_the_fused_one(self):
        prod, fused = np.full((4, 4, 3), 100, np.uint8), np.full((4, 4, 3), 200, np.uint8)
        self.assertTrue((self.fs.blend(prod, fused, 0.0) == 100).all())
        self.assertTrue((self.fs.blend(prod, fused, 1.0) == 200).all())
        self.assertTrue((self.fs.blend(prod, fused, 0.5) == 150).all())

    def test_fusing_a_clipped_frame_with_a_dark_one_keeps_more_of_the_highlights(self):
        bright = np.zeros((40, 40, 3), np.uint8)
        bright[:, :20] = 255                 # a blown-out half
        bright[:, 20:] = 90
        dark = (bright * 0.25).astype(np.uint8)
        dark[:, :20] = 80                    # the sun half has detail in the dark shot
        dark[:, :20] += np.arange(20, dtype=np.uint8)[None, :, None]
        fused = self.fs.fuse(bright, dark)
        self.assertEqual(fused.shape, bright.shape)
        self.assertLess((fused[:, :20] >= 250).mean(), 0.5)
        self.assertGreater(fused[:, :20].std(), 1, "the detail from the dark shot comes through")

    def test_identical_frames_fuse_to_about_the_same_picture(self):
        img = np.random.RandomState(1).randint(40, 200, (30, 30, 3)).astype(np.uint8)
        self.assertLess(np.abs(self.fs.fuse(img, img).astype(int) - img).mean(), 6)


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class Run(unittest.TestCase):
    def setUp(self):
        self.fs = load()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.run_dir = os.path.join(self.dir, "run")
        self.frames = os.path.join(self.dir, "cam")
        self.out = os.path.join(self.dir, "out")
        os.makedirs(self.run_dir)

    def stamp(self, t):
        return t.strftime("%Y%m%dT%H%M%SZ")

    def add_minute(self, t, bright=200, dark=60, prod=120, pair=True):
        """An experiment pair 14 s and 12 s into minute `t` (unless pair is False), and the
        production frame at `t`."""
        for name, dt, value in (("ev+0-daylight", 14, bright), ("ev-2-daylight", 12, dark)):
            if pair:
                cv2.imwrite(os.path.join(self.run_dir, "%s_%s.jpg" % (name, self.stamp(t + timedelta(seconds=dt)))),
                            np.full((8, 8, 3), value, np.uint8))
        folder = os.path.join(self.frames, t.strftime("%Y/%m/%d"))
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, "cam_%s" % self.stamp(t))
        cv2.imwrite(base + ".jpg", np.full((8, 8, 3), prod, np.uint8))
        minutes = (t - SUNSET).total_seconds() / 60
        with open(base + ".json", "w") as f:
            json.dump({"Sun": {"minutes_from_sunset": round(minutes, 1), "nearest_sunset_utc":
                               SUNSET.strftime("%Y-%m-%dT%H:%M:%SZ")}}, f)

    def test_writes_one_fused_frame_per_minute_named_like_the_production_frame(self):
        start = SUNSET - timedelta(minutes=40)
        for i in range(10):
            self.add_minute(start + timedelta(minutes=i))
        made = self.fs.fuse_run(self.run_dir, self.frames, self.out)
        self.assertEqual(made, 9, "the very first minute has no weight, so the production frame stays")
        self.assertEqual(sorted(os.listdir(self.out)),
                         ["cam_%s.jpg" % self.stamp(start + timedelta(minutes=i)) for i in range(1, 10)])

    def test_the_first_minutes_are_mostly_the_production_frame_and_later_ones_the_fusion(self):
        start = SUNSET - timedelta(minutes=45)
        for i in range(10):
            self.add_minute(start + timedelta(minutes=i), prod=60)   # fusing 200 and 60 gives 130
        self.fs.fuse_run(self.run_dir, self.frames, self.out)
        first = cv2.imread(os.path.join(self.out, "cam_%s.jpg" % self.stamp(start + timedelta(minutes=1)))).mean()
        later = cv2.imread(os.path.join(self.out, "cam_%s.jpg" % self.stamp(start + timedelta(minutes=8)))).mean()
        self.assertAlmostEqual(first, 60 + 0.2 * 70, delta=4, msg="a fifth of the way in")
        self.assertAlmostEqual(later, 130, delta=4, msg="fully fused")

    def out_mean(self, t):
        return cv2.imread(os.path.join(self.out, "cam_%s.jpg" % self.stamp(t))).mean()

    def test_a_minute_with_no_bracket_is_filled_from_the_minutes_either_side(self):
        # The runner skips the first minute of every 5-minute slot, so one frame in five has no pair;
        # left as the production frame it would flash against the fused ones around it.
        start = SUNSET - timedelta(minutes=30)
        for i in range(10):
            self.add_minute(start + timedelta(minutes=i), bright=200 if i < 5 else 220, pair=(i != 5))
        self.fs.fuse_run(self.run_dir, self.frames, self.out)
        before, gap, after = (self.out_mean(start + timedelta(minutes=i)) for i in (4, 5, 6))
        self.assertTrue(min(before, after) - 0.5 <= gap <= max(before, after) + 0.5, (before, gap, after))
        self.assertNotAlmostEqual(gap, 120, delta=5, msg="not the production frame")

    def test_a_long_hole_follows_the_fusion_from_one_side_then_gives_up(self):
        start = SUNSET - timedelta(minutes=30)
        for i in range(24):
            self.add_minute(start + timedelta(minutes=i), pair=(i < 3 or i > 19))
        self.fs.fuse_run(self.run_dir, self.frames, self.out)
        held = self.out_mean(start + timedelta(minutes=5))      # 3 minutes from the pair at 2, 15 from the next
        self.assertNotAlmostEqual(held, 120, delta=5)
        self.assertFalse(os.path.exists(os.path.join(self.out, "cam_%s.jpg" % self.stamp(start + timedelta(minutes=11)))),
                         "9 minutes from either side is too far")

    def test_a_filled_frame_keeps_its_own_picture_not_a_copy_of_its_neighbours(self):
        # Production frames differ minute to minute (clouds, sun). A copied picture froze the video.
        start = SUNSET - timedelta(minutes=30)
        for i in range(8):
            self.add_minute(start + timedelta(minutes=i), prod=100 + 4 * i, pair=(i != 3))
        self.fs.fuse_run(self.run_dir, self.frames, self.out)
        means = [self.out_mean(start + timedelta(minutes=i)) for i in (2, 3, 4)]
        self.assertGreater(means[1], means[0] + 1, "it still follows the rising production frames")
        self.assertGreater(means[2], means[1] + 1)

    def test_exposure_hunting_from_minute_to_minute_is_smoothed_out(self):
        # The bracket's auto exposure swung the fused brightness by about 7 a minute at the real
        # sunset, which read as jitter. Alternating 200 and 240 fuse to about 130 and 150.
        start = SUNSET - timedelta(minutes=30)
        for i in range(16):
            self.add_minute(start + timedelta(minutes=i), bright=200 if i % 2 else 240)
        self.fs.fuse_run(self.run_dir, self.frames, self.out, smooth=0)
        raw = [self.out_mean(start + timedelta(minutes=i)) for i in range(8, 12)]
        shutil.rmtree(self.out)
        self.fs.fuse_run(self.run_dir, self.frames, self.out)
        smooth = [self.out_mean(start + timedelta(minutes=i)) for i in range(8, 12)]
        swing = lambda xs: max(abs(a - b) for a, b in zip(xs, xs[1:]))
        self.assertGreater(swing(raw), 15)
        self.assertLess(swing(smooth), swing(raw) / 2)

    def test_smoothing_leaves_a_steady_change_alone(self):
        start = SUNSET - timedelta(minutes=30)
        for i in range(16):
            self.add_minute(start + timedelta(minutes=i), bright=150 + 5 * i)
        self.fs.fuse_run(self.run_dir, self.frames, self.out, smooth=0)
        raw = [self.out_mean(start + timedelta(minutes=i)) for i in (7, 8, 9)]
        shutil.rmtree(self.out)
        self.fs.fuse_run(self.run_dir, self.frames, self.out)
        smooth = [self.out_mean(start + timedelta(minutes=i)) for i in (7, 8, 9)]
        for a, b in zip(raw, smooth):
            self.assertAlmostEqual(a, b, delta=2)

    def test_minutes_past_the_fade_out_are_left_alone(self):
        late = SUNSET + timedelta(minutes=20)
        for i in range(3):
            self.add_minute(late + timedelta(minutes=i))
        # a run that starts earlier, so the fade-in is not what zeroes these
        self.add_minute(SUNSET - timedelta(minutes=45))
        self.fs.fuse_run(self.run_dir, self.frames, self.out)
        self.assertFalse(any(self.stamp(late) in n for n in os.listdir(self.out)))


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class TemporalBlend(unittest.TestCase):
    """Thin cloud crossing the glow changes the sky by 10 to 19 a minute (Nov 12, both cameras),
    which reads as flicker. A 1:2:1 blend of each minute with the minutes either side calms it."""

    stamp, add_minute, out_mean = Run.stamp, Run.add_minute, Run.out_mean

    def setUp(self):
        Run.setUp(self)
        self.start = SUNSET - timedelta(minutes=30)

    def minutes(self, values, pair=True):
        for i, v in enumerate(values):
            self.add_minute(self.start + timedelta(minutes=i), prod=v, pair=pair)

    def at(self, i):
        return self.start + timedelta(minutes=i)

    def test_a_jump_in_one_minute_is_spread_over_its_neighbours(self):
        self.minutes([100, 100, 100, 200, 100, 100, 100])
        made = self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(6))
        self.assertEqual(made, 5, "the first and last minutes have no neighbour on one side")
        self.assertAlmostEqual(self.out_mean(self.at(3)), 150, delta=3)    # (100 + 2*200 + 100) / 4
        self.assertAlmostEqual(self.out_mean(self.at(2)), 125, delta=3)
        self.assertAlmostEqual(self.out_mean(self.at(1)), 100, delta=3)

    def test_the_ends_of_the_window_are_left_alone(self):
        self.minutes([100, 100, 100, 100])
        self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(3))
        for i in (0, 3):
            self.assertFalse(os.path.exists(os.path.join(self.out, "cam_%s.jpg" % self.stamp(self.at(i)))))

    def test_uses_the_fused_frame_where_there_is_one(self):
        self.minutes([100, 100, 100, 100, 100])
        os.makedirs(self.out)
        cv2.imwrite(os.path.join(self.out, "cam_%s.jpg" % self.stamp(self.at(2))), np.full((8, 8, 3), 180, np.uint8))
        self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(4))
        self.assertAlmostEqual(self.out_mean(self.at(2)), 140, delta=3)     # (100 + 2*180 + 100) / 4
        self.assertAlmostEqual(self.out_mean(self.at(1)), 120, delta=3)     # its neighbour sees the fused frame too

    def test_frames_five_minutes_apart_are_not_blended(self):
        # outside the dense window there is one frame every 5 minutes: too far apart to mix
        for i in range(5):
            self.add_minute(self.start + timedelta(minutes=5 * i), prod=100 + 50 * (i % 2))
        made = self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(20))
        self.assertEqual(made, 0)

    def test_running_it_twice_does_not_blend_twice(self):
        self.minutes([100, 100, 200, 100, 100])
        self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(4))
        once = self.out_mean(self.at(2))
        self.assertEqual(self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(4)), 0)
        self.assertAlmostEqual(self.out_mean(self.at(2)), once, delta=0.5)

    def test_undo_removes_what_the_blend_wrote_so_it_can_be_redone(self):
        self.minutes([100, 100, 200, 100, 100])
        self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(4))
        self.fs.undo_blend(self.out)
        self.assertEqual([n for n in os.listdir(self.out)], [])
        self.assertEqual(self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(4)), 3)

    def test_undo_puts_back_the_fused_frames_it_blended(self):
        self.minutes([100, 100, 100, 100, 100])
        os.makedirs(self.out)
        fused = os.path.join(self.out, "cam_%s.jpg" % self.stamp(self.at(2)))
        cv2.imwrite(fused, np.full((8, 8, 3), 180, np.uint8))
        self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(4))
        self.fs.undo_blend(self.out)
        self.assertEqual(os.listdir(self.out), [os.path.basename(fused)], "only the fused frame, nothing else")
        self.assertAlmostEqual(cv2.imread(fused).mean(), 180, delta=1, msg="as it was before the blend")

    def crash_after(self, writes):
        """Run blend_minutes over minutes 0 to 4, failing on JPEG write number `writes` + 1."""
        real, count = cv2.imwrite, [0]

        def imwrite(path, *a, **k):
            if path.endswith(".jpg"):
                count[0] += 1
                if count[0] > writes:
                    raise KeyboardInterrupt("power cut")
            return real(path, *a, **k)

        with mock.patch.object(self.fs.cv2, "imwrite", side_effect=imwrite):
            with self.assertRaises(KeyboardInterrupt):
                self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(4))

    def with_fused_middle(self):
        self.minutes([100, 100, 100, 100, 100])
        os.makedirs(self.out)
        cv2.imwrite(os.path.join(self.out, "cam_%s.jpg" % self.stamp(self.at(2))), np.full((8, 8, 3), 180, np.uint8))

    def test_a_blend_cut_off_part_way_is_not_blended_twice_when_run_again(self):
        # The crash comes after minute 2 (the fused frame) was overwritten with its blend. Reading that
        # back as the source would blend it a second time: (100 + 2*140 + 100) / 4 = 120, not 140.
        self.with_fused_middle()
        self.crash_after(2)
        self.fs.blend_minutes(self.frames, self.out, self.at(0), self.at(4))
        self.assertAlmostEqual(self.out_mean(self.at(2)), 140, delta=3)
        self.assertAlmostEqual(self.out_mean(self.at(1)), 120, delta=3)
        self.assertAlmostEqual(self.out_mean(self.at(3)), 120, delta=3)

    def test_undo_after_a_blend_cut_off_part_way_restores_the_fused_frame(self):
        self.with_fused_middle()
        self.crash_after(2)
        self.fs.undo_blend(self.out)
        name = "cam_%s.jpg" % self.stamp(self.at(2))
        self.assertEqual(os.listdir(self.out), [name])
        self.assertAlmostEqual(self.out_mean(self.at(2)), 180, delta=1)

    def test_blend_run_covers_the_bracket_and_15_minutes_either_side(self):
        for i in range(30):
            self.add_minute(self.start + timedelta(minutes=i), prod=100 + 20 * (i % 2), pair=(10 <= i < 15))
        made = self.fs.blend_run(self.run_dir, self.frames, self.out)
        self.assertEqual(made, 28, "minutes 1 to 28: the bracket (10 to 14) is well inside 15 minutes")
        with open(os.path.join(self.out, self.fs.BLEND_MARK)) as f:
            self.assertEqual(len(json.load(f)["blended"]), 28)


def load_build_video():
    spec = importlib.util.spec_from_file_location("build_video", os.path.join(os.path.dirname(HERE), "tools", "build_video.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class Redo(unittest.TestCase):
    """tools/build_video.py --redo after a change to the merge code: the fused frames must be made
    again, not reused (it printed "fused 0 frames" and encoded the old pictures)."""

    stamp, add_minute, out_mean = Run.stamp, Run.add_minute, Run.out_mean

    def setUp(self):
        Run.setUp(self)
        self.bv = load_build_video()
        self.start = SUNSET - timedelta(minutes=30)
        for i in range(12):
            self.add_minute(self.start + timedelta(minutes=i))

    def prepare(self, redo):
        return self.bv.prepare_fused(self.fs, self.run_dir, self.frames, self.out, redo=redo)

    def new_merge(self):
        return mock.patch.object(self.fs, "fuse", lambda bright, dark: np.full_like(bright, 250))

    def test_without_redo_the_frames_already_made_are_kept(self):
        made, blended = self.prepare(False)
        self.assertGreater(made, 0)
        self.assertGreater(blended, 0)
        before = self.out_mean(self.start + timedelta(minutes=7))
        with self.new_merge():
            self.assertEqual(self.prepare(False), (0, 0))
        self.assertAlmostEqual(self.out_mean(self.start + timedelta(minutes=7)), before, delta=0.5)

    def test_redo_makes_the_fused_frames_again_with_the_new_merge(self):
        self.prepare(False)
        with self.new_merge():
            made, blended = self.prepare(True)
        self.assertGreater(made, 0)
        self.assertGreater(blended, 0, "and blends them again")
        self.assertAlmostEqual(self.out_mean(self.start + timedelta(minutes=7)), 250, delta=3)

    def test_redo_twice_gives_the_same_frames(self):
        self.prepare(False)
        self.prepare(True)
        once = [self.out_mean(self.start + timedelta(minutes=i)) for i in range(2, 11)]
        self.prepare(True)
        twice = [self.out_mean(self.start + timedelta(minutes=i)) for i in range(2, 11)]
        for a, b in zip(once, twice):
            self.assertAlmostEqual(a, b, delta=0.5)

    def test_redo_drops_fused_frames_the_new_merge_does_not_make(self):
        # A narrower merge window would leave the old build's frames outside it, still swapped in.
        self.prepare(False)
        stray = os.path.join(self.out, "cam_%s.jpg" % self.stamp(self.start - timedelta(minutes=60)))
        cv2.imwrite(stray, np.full((8, 8, 3), 7, np.uint8))
        other = os.path.join(self.out, "notes.txt")
        open(other, "w").close()
        self.prepare(True)
        self.assertFalse(os.path.exists(stray))
        self.assertTrue(os.path.exists(other), "only frame-named JPEGs are removed")

    def test_no_blend_leaves_the_fused_frames_unblended(self):
        made, blended = self.bv.prepare_fused(self.fs, self.run_dir, self.frames, self.out, blend=False)
        self.assertGreater(made, 0)
        self.assertEqual(blended, 0)
        self.assertFalse(os.path.exists(os.path.join(self.out, self.fs.BLEND_MARK)))


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class ProductionBracket(unittest.TestCase):
    """With BRACKET=1 the capture script saves the pair beside each frame in the sunset window:
    <cam>_<UTC>_ev0.jpg and <cam>_<UTC>_ev-2.jpg in the frame's own day folder (#10)."""

    stamp = Run.stamp

    def setUp(self):
        Run.setUp(self)
        self.start = SUNSET - timedelta(minutes=40)

    def add_minute(self, t, bright=200, dark=60, prod=120, pair=True):
        folder = os.path.join(self.frames, t.strftime("%Y/%m/%d"))
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, "cam_%s" % self.stamp(t))
        cv2.imwrite(base + ".jpg", np.full((8, 8, 3), prod, np.uint8))
        if pair:
            cv2.imwrite(base + "_ev0.jpg", np.full((8, 8, 3), bright, np.uint8))
            cv2.imwrite(base + "_ev-2.jpg", np.full((8, 8, 3), dark, np.uint8))
        minutes = (t - SUNSET).total_seconds() / 60
        for path in (base + ".json",) + ((base + "_ev0.json", base + "_ev-2.json") if pair else ()):
            with open(path, "w") as f:
                json.dump({"Sun": {"minutes_from_sunset": round(minutes, 1)}}, f)

    def window(self):
        return SUNSET - timedelta(hours=2), SUNSET + timedelta(hours=2)

    def test_lists_the_pairs_at_their_frame_time(self):
        for i in range(3):
            self.add_minute(self.start + timedelta(minutes=i))
        brights, darks = self.fs.production_bracket(self.frames, *self.window())
        self.assertEqual([t for t, _ in brights], [self.start + timedelta(minutes=i) for i in range(3)])
        self.assertEqual([t for t, _ in darks], [t for t, _ in brights])
        self.assertTrue(all(p.endswith("_ev0.jpg") for _, p in brights))
        self.assertTrue(all(p.endswith("_ev-2.jpg") for _, p in darks))

    def test_pairs_are_not_taken_for_production_frames(self):
        self.add_minute(self.start)
        found = self.fs.production_frames(self.frames, *self.window())
        self.assertEqual([os.path.basename(p) for _, p in found], ["cam_%s.jpg" % self.stamp(self.start)])

    def test_pairs_either_side_of_midnight_utc(self):
        # the Vancouver sunset is about 00:20 UTC, so its window spans two UTC day folders
        for i in range(0, 60, 5):
            self.add_minute(self.start + timedelta(minutes=i))
        brights, _ = self.fs.production_bracket(self.frames, *self.window())
        self.assertEqual({t.day for t, _ in brights}, {12, 13})

    def test_fuses_the_production_pairs_into_frames_named_like_the_production_frame(self):
        for i in range(10):
            self.add_minute(self.start + timedelta(minutes=i))
        made = self.fs.fuse_run(None, self.frames, self.out, brackets=self.fs.production_bracket(self.frames, *self.window()))
        self.assertEqual(made, 9, "the very first minute has no weight, so the production frame stays")
        self.assertEqual(sorted(os.listdir(self.out)),
                         ["cam_%s.jpg" % self.stamp(self.start + timedelta(minutes=i)) for i in range(1, 10)])

    def test_a_frame_without_its_pair_takes_the_change_from_its_neighbours(self):
        for i in range(10):
            self.add_minute(self.start + timedelta(minutes=i), pair=(i != 6))
        made = self.fs.fuse_run(None, self.frames, self.out, brackets=self.fs.production_bracket(self.frames, *self.window()))
        self.assertEqual(made, 9)

    def test_no_pairs_makes_nothing(self):
        self.add_minute(self.start, pair=False)
        self.assertEqual(self.fs.fuse_run(None, self.frames, self.out, brackets=self.fs.production_bracket(self.frames, *self.window())), 0)

    def test_blend_covers_the_production_pairs(self):
        for i in range(10):
            self.add_minute(self.start + timedelta(minutes=i))
        brackets = self.fs.production_bracket(self.frames, *self.window())
        self.fs.fuse_run(None, self.frames, self.out, brackets=brackets)
        self.assertGreater(self.fs.blend_run(None, self.frames, self.out, brights=brackets[0]), 0)

    def test_build_video_uses_the_production_pairs(self):
        for i in range(10):
            self.add_minute(self.start + timedelta(minutes=i))
        bv = load_build_video()
        made, blended = bv.prepare_fused(self.fs, None, self.frames, self.out,
                                         brackets=self.fs.production_bracket(self.frames, *self.window()))
        self.assertEqual(made, 9)
        self.assertGreater(blended, 0)

    def test_build_video_window_is_the_local_evening(self):
        from datetime import date
        bv = load_build_video()
        start, end = bv.evening_window(date(2026, 11, 12))
        self.assertLess(start, SUNSET - timedelta(hours=1))
        self.assertGreater(end, SUNSET + timedelta(hours=1))
        self.assertLess(end - start, timedelta(hours=24))


if __name__ == "__main__":
    unittest.main()
