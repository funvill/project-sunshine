"""Tests for tools/issue_blur.py: python3 tests/test_issue_blur.py (skipped without numpy, OpenCV, Pillow)"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

try:
    import cv2  # noqa: F401
    import numpy as np
    import PIL  # noqa: F401
except ImportError:
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "tools", "issue_blur.py")


def load():
    spec = importlib.util.spec_from_file_location("issue_blur", os.path.join(os.path.dirname(HERE), "tools", "issue_blur.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipIf(np is None, "needs numpy, OpenCV and Pillow")
class IssueBlur(unittest.TestCase):
    def setUp(self):
        self.ib = load()
        # 400 x 300 frame of fine stripes; one "building" in the middle third
        self.frame = np.zeros((300, 400, 3), np.uint8)
        self.frame[:, ::2] = 255
        self.building = [[(150, 50), (250, 50), (250, 280), (150, 280)]]

    def run_style(self, style):
        return self.ib.blur_for_issue(self.frame, self.building, style=style, width=400)

    def test_every_style_blurs_inside_and_leaves_outside(self):
        for style in self.ib.STYLES:
            with self.subTest(style=style):
                out = self.run_style(style).astype(int)
                self.assertTrue(np.array_equal(out[:, :140], self.frame[:, :140]), "left of the building changed")
                self.assertTrue(np.array_equal(out[:, 260:], self.frame[:, 260:]), "right of the building changed")
                inside = out[250:270, 170:230, 1]  # below the label
                self.assertLess(np.abs(np.diff(inside, axis=1)).mean(), 100, "stripes inside should be softened")

    def test_each_building_is_labelled(self):
        out = self.run_style(1)
        label_zone = out[100:180, 150:250]
        # the label is a dark box with white text: both extremes appear in its band
        self.assertGreater((label_zone.min(axis=2) > 230).sum(), 20)
        self.assertGreater((label_zone.max(axis=2) < 80).sum(), 200)

    def test_outlines_follow_the_crop_and_resize(self):
        out = self.ib.blur_for_issue(self.frame, self.building, style=2, width=200, crop=(100, 0, 400, 300))
        self.assertEqual(out.shape[1], 200)
        # building now at x 50-150 of the crop, scaled by 2/3: about 33-100
        self.assertTrue(np.array_equal(out[:, 110:], cv2_resize(self.frame[:, 100:400], 200)[:, 110:]))


@unittest.skipIf(np is None, "needs numpy, OpenCV and Pillow")
class SetupChoice(unittest.TestCase):
    """The outlines must belong to the camera position the frame was taken at (issue #19)."""

    def setUp(self):
        self.ib = load()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.frame = os.path.join(self.dir, "wide_20261112T003000Z.jpg")
        import cv2
        cv2.imwrite(self.frame, np.full((300, 400, 3), 128, np.uint8))

    def write_json(self, setup_id, path=None):
        data = {"Sun": {}, "Capture": {"schedule": "regular"}}
        if setup_id:
            data["Capture"]["setup_id"] = setup_id
        with open(path or os.path.splitext(self.frame)[0] + ".json", "w") as f:
            json.dump(data, f)

    def test_setup_comes_from_the_frames_json(self):
        self.write_json("pilot-3")
        self.assertEqual(self.ib.frame_setup(self.frame), "pilot-3")
        self.assertIs(self.ib.choose_outlines(None, "pilot-3"), self.ib.BUILDINGS["pilot-3"])

    def test_a_setup_with_no_outlines_is_refused(self):
        with self.assertRaises(self.ib.SetupError) as e:
            self.ib.choose_outlines(None, "pilot-4")
        self.assertIn("pilot-4", str(e.exception))

    def test_no_setup_anywhere_is_refused_rather_than_assuming_pilot_3(self):
        self.assertIsNone(self.ib.frame_setup(self.frame))
        with self.assertRaises(self.ib.SetupError):
            self.ib.choose_outlines(None, None)

    def test_a_setup_argument_that_disagrees_with_the_frame_is_refused(self):
        with self.assertRaises(self.ib.SetupError):
            self.ib.choose_outlines("pilot-3", "cm4-window-1")

    def test_explicit_outlines_need_no_setup(self):
        self.assertEqual(self.ib.choose_outlines(None, "pilot-4", [[(0, 0), (1, 0), (1, 1)]]), [[(0, 0), (1, 0), (1, 1)]])

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, self.frame, os.path.join(self.dir, "out.jpg")] + list(args),
                              capture_output=True, text=True)

    def test_command_line_refuses_an_unknown_setup_with_a_clear_message(self):
        self.write_json("pilot-4")
        got = self.run_cli()
        self.assertNotEqual(got.returncode, 0)
        self.assertIn("no building outlines for setup 'pilot-4'", got.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "out.jpg")))

    def test_command_line_works_for_a_known_setup_from_the_json(self):
        self.write_json("pilot-3")
        got = self.run_cli("--width", "200")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "out.jpg")))

    def test_command_line_reads_a_json_given_by_path(self):
        other = os.path.join(self.dir, "other.json")
        self.write_json("cm4-window-1", other)
        got = self.run_cli("--json", other)
        self.assertNotEqual(got.returncode, 0)
        self.assertIn("cm4-window-1", got.stderr)


def cv2_resize(img, width):
    import cv2
    return cv2.resize(img, (width, round(img.shape[0] * width / img.shape[1])), interpolation=cv2.INTER_AREA)


if __name__ == "__main__":
    unittest.main()
