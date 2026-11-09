"""Tests for tools/issue_blur.py: python3 tests/test_issue_blur.py (skipped without numpy, OpenCV, Pillow)"""
import importlib.util
import os
import unittest

try:
    import cv2  # noqa: F401
    import numpy as np
    import PIL  # noqa: F401
except ImportError:
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))


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


def cv2_resize(img, width):
    import cv2
    return cv2.resize(img, (width, round(img.shape[0] * width / img.shape[1])), interpolation=cv2.INTER_AREA)


if __name__ == "__main__":
    unittest.main()
