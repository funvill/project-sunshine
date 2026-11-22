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
    """The boxes must belong to the camera position the frame was taken at (issue #19): they come
    from the calibration in the crop config whose setup_id is the frame's."""

    CALIBRATIONS = [
        {"start": "2026-11-11", "setup_id": "cm4-window-1", "blur": [[0, 0, 10, 10]], "blur_sigma": 5},
        {"start": "2026-11-17", "setup_id": "cm4-window-3", "blur": [[100, 50, 100, 200], [300, 60, 50, 50]]},
        {"start": "2026-11-20", "setup_id": "cm4-window-4", "blur": []},
    ]

    def setUp(self):
        self.ib = load()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.frame = os.path.join(self.dir, "cm4wide_20261118T003000Z.jpg")
        import cv2
        cv2.imwrite(self.frame, np.full((300, 400, 3), 128, np.uint8))
        self.config = os.path.join(self.dir, "crop.json")
        with open(self.config, "w") as f:
            json.dump({"calibrations": self.CALIBRATIONS}, f)

    def write_json(self, setup_id, path=None):
        data = {"Sun": {}, "Capture": {"schedule": "regular"}}
        if setup_id:
            data["Capture"]["setup_id"] = setup_id
        with open(path or os.path.splitext(self.frame)[0] + ".json", "w") as f:
            json.dump(data, f)

    def test_setup_comes_from_the_frames_json(self):
        self.write_json("cm4-window-3")
        self.assertEqual(self.ib.frame_setup(self.frame), "cm4-window-3")
        self.assertEqual(self.ib.choose_boxes(None, "cm4-window-3", self.CALIBRATIONS), self.CALIBRATIONS[1]["blur"])

    def test_boxes_become_rectangles(self):
        self.assertEqual(self.ib.box_outlines([[100, 50, 100, 200]]), [[(100, 50), (200, 50), (200, 250), (100, 250)]])

    def test_a_setup_with_no_calibration_is_refused(self):
        with self.assertRaises(self.ib.SetupError) as e:
            self.ib.choose_boxes(None, "pilot-4", self.CALIBRATIONS)
        self.assertIn("pilot-4", str(e.exception))

    def test_a_calibration_with_no_blur_boxes_is_refused(self):
        with self.assertRaises(self.ib.SetupError):
            self.ib.choose_boxes(None, "cm4-window-4", self.CALIBRATIONS)

    def test_no_setup_anywhere_is_refused(self):
        self.assertIsNone(self.ib.frame_setup(self.frame))
        with self.assertRaises(self.ib.SetupError):
            self.ib.choose_boxes(None, None, self.CALIBRATIONS)

    def test_a_setup_argument_that_disagrees_with_the_frame_is_refused(self):
        with self.assertRaises(self.ib.SetupError):
            self.ib.choose_boxes("cm4-window-3", "cm4-window-1", self.CALIBRATIONS)

    def test_the_default_config_is_the_cameras_in_nas(self):
        self.assertEqual(os.path.basename(self.ib.default_config(self.frame)), "crop.cm4wide.json")
        self.assertIsNone(self.ib.default_config(os.path.join(self.dir, "photo.jpg")))

    def test_every_calibration_in_the_checked_in_config_has_boxes(self):
        # the issue images and the video blur the same boxes, so a camera position with none is a gap in both
        calibrations = self.ib.read_config(os.path.join(os.path.dirname(HERE), "nas", "crop.cm4wide.json"))
        for c in calibrations:
            with self.subTest(setup=c.get("setup_id")):
                self.assertTrue(self.ib.choose_boxes(None, c["setup_id"], calibrations))

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, self.frame, os.path.join(self.dir, "out.jpg"),
                               "--config", self.config] + list(args), capture_output=True, text=True)

    def test_command_line_refuses_an_unknown_setup_with_a_clear_message(self):
        self.write_json("pilot-4")
        got = self.run_cli()
        self.assertNotEqual(got.returncode, 0)
        self.assertIn("no calibration for setup 'pilot-4'", got.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "out.jpg")))

    def test_command_line_works_for_a_known_setup_from_the_json(self):
        self.write_json("cm4-window-3")
        got = self.run_cli("--width", "200")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "out.jpg")))

    def test_command_line_reads_a_json_given_by_path(self):
        other = os.path.join(self.dir, "other.json")
        self.write_json("cm4-window-4", other)
        got = self.run_cli("--json", other)
        self.assertNotEqual(got.returncode, 0)
        self.assertIn("cm4-window-4", got.stderr)


def cv2_resize(img, width):
    import cv2
    return cv2.resize(img, (width, round(img.shape[0] * width / img.shape[1])), interpolation=cv2.INTER_AREA)


if __name__ == "__main__":
    unittest.main()
