"""Tests for tools/frames.py, the frame file names the tools share: python3 tests/test_frames.py"""
import importlib.util
import os
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("frames", os.path.join(os.path.dirname(HERE), "tools", "frames.py"))
frames = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frames)
T = datetime(2026, 11, 18, 0, 22, 14, tzinfo=timezone.utc)


class Parse(unittest.TestCase):
    def test_a_regular_frame(self):
        self.assertEqual(frames.parse("cm4wide_20261118T002214Z.jpg"), ("cm4wide", T, None))

    def test_the_kinds(self):
        for kind in ("night", "ev0", "ev-2"):
            with self.subTest(kind=kind):
                self.assertEqual(frames.parse("cm4city_20261118T002214Z_%s.jpg" % kind), ("cm4city", T, kind))

    def test_the_time_is_utc(self):
        self.assertEqual(frames.parse("wide_20261118T002214Z.jpg")[1].utcoffset().total_seconds(), 0)

    def test_other_files_are_not_frames(self):
        for name in ("cm4wide_20261118T002214Z.json", "cm4wide_20261118T002214Z.dng", "cm4wide_20261118T002214Z_ev+2.jpg",
                     "cm4wide_20261118T0022Z.jpg", "_20261118T002214Z.jpg", "a b_20261118T002214Z.jpg", "crop.json"):
            with self.subTest(name=name):
                self.assertIsNone(frames.parse(name))


if __name__ == "__main__":
    unittest.main()
