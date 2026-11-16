"""Tests for experiments/raw_value.py: python3 tests/test_raw_value.py (skipped without numpy and OpenCV)"""
import importlib.util
import os
import shutil
import struct
import tempfile
import unittest

try:
    import cv2
    import numpy as np
except ImportError:
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    spec = importlib.util.spec_from_file_location("raw_value", os.path.join(os.path.dirname(HERE), "experiments", "raw_value.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_dng(path, cfa, black=256, white=4095, pattern=(2, 1, 1, 0), neutral=(0.5, 1.0, 0.75)):
    """A DNG laid out like rpicam-still's: a small IFD0 whose SubIFD holds the 16-bit CFA."""
    h, w = cfa.shape
    data = cfa.astype("<u2").tobytes()

    def rational(values):
        return b"".join(struct.pack("<II", int(round(v * 1000000)), 1000000) for v in values)

    def ifd_bytes(entries, start):
        """entries: (tag, type, count, payload bytes). Returns the IFD with payloads after it."""
        n = len(entries)
        extra_at = start + 2 + 12 * n + 4
        head, extra = struct.pack("<H", n), b""
        for tag, typ, count, payload in sorted(entries):
            if len(payload) <= 4:
                head += struct.pack("<HHI", tag, typ, count) + payload.ljust(4, b"\0")
            else:
                head += struct.pack("<HHII", tag, typ, count, extra_at + len(extra))
                extra += payload + (b"\0" if len(payload) % 2 else b"")
        return head + struct.pack("<I", 0) + extra

    raw_at = 8
    sub_at = raw_at + len(data)
    sub = ifd_bytes([
        (254, 4, 1, struct.pack("<I", 0)), (256, 3, 1, struct.pack("<H", w)), (257, 3, 1, struct.pack("<H", h)),
        (258, 3, 1, struct.pack("<H", 16)), (259, 3, 1, struct.pack("<H", 1)), (262, 3, 1, struct.pack("<H", 32803)),
        (273, 4, 1, struct.pack("<I", raw_at)), (277, 3, 1, struct.pack("<H", 1)), (279, 4, 1, struct.pack("<I", len(data))),
        (33421, 3, 2, struct.pack("<HH", 2, 2)), (33422, 1, 4, bytes(pattern)),
        (50714, 5, 4, rational([black] * 4)), (50717, 4, 1, struct.pack("<I", white)),
    ], sub_at)
    ifd0_at = sub_at + len(sub)
    ifd0 = ifd_bytes([(254, 4, 1, struct.pack("<I", 1)), (330, 13, 1, struct.pack("<I", sub_at)),
                      (50728, 5, 3, rational(neutral))], ifd0_at)
    with open(path, "wb") as f:
        f.write(b"II" + struct.pack("<HI", 42, ifd0_at) + data + sub + ifd0)


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class ReadDng(unittest.TestCase):
    def setUp(self):
        self.rv = load()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_reads_the_cfa_and_its_levels(self):
        cfa = (np.arange(8 * 6, dtype=np.uint16).reshape(6, 8) * 50 + 256)
        path = os.path.join(self.dir, "a.dng")
        write_dng(path, cfa)
        d = self.rv.read_dng(path)
        self.assertTrue((d["cfa"] == cfa).all())
        self.assertEqual((d["black"], d["white"], tuple(d["pattern"])), (256, 4095, (2, 1, 1, 0)))
        self.assertEqual([round(x, 3) for x in d["neutral"]], [0.5, 1.0, 0.75])

    def test_half_rgb_puts_each_bayer_site_in_its_channel(self):
        # BGGR: top-left blue, bottom-right red, the other two green
        cfa = np.zeros((4, 4), np.uint16)
        cfa[0::2, 0::2], cfa[0::2, 1::2], cfa[1::2, 0::2], cfa[1::2, 1::2] = 256 + 3839, 256, 256 + 3839 // 2, 256 + 3839 // 4
        path = os.path.join(self.dir, "b.dng")
        write_dng(path, cfa)
        rgb = self.rv.half_rgb(self.rv.read_dng(path))
        self.assertEqual(rgb.shape, (2, 2, 3))
        r, g, b = rgb[0, 0]
        self.assertAlmostEqual(float(r), 0.25, places=2)
        self.assertAlmostEqual(float(g), 0.25, places=2)      # the mean of the two greens: 0 and 0.5
        self.assertAlmostEqual(float(b), 1.0, places=2)


@unittest.skipIf(np is None, "needs numpy and OpenCV")
class Measure(unittest.TestCase):
    def setUp(self):
        self.rv = load()

    def scene(self, push):
        """Raw linear 0..1 ramp; the JPEG is the raw pushed `push` times, gamma'd and clipped."""
        ramp = np.linspace(0.0, 1.0, 400, dtype=np.float32)
        raw = np.repeat(np.repeat(ramp[None, :, None], 50, axis=0), 3, axis=2)
        jpeg = (np.clip(raw * push, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8)
        return jpeg, raw

    def test_headroom_is_how_far_the_raw_goes_past_the_jpeg_clip(self):
        jpeg, raw = self.scene(push=4.0)       # the JPEG clips at a quarter of the raw's full scale
        m = self.rv.measure(jpeg, raw)
        self.assertAlmostEqual(m["headroom_stops"], 2.0, delta=0.15)
        self.assertGreater(m["recoverable_hi_pct"], 60)
        self.assertLess(m["raw_clip_pct"], 3)

    def test_no_headroom_when_both_clip_together(self):
        jpeg, raw = self.scene(push=1.0)
        m = self.rv.measure(jpeg, raw)
        self.assertAlmostEqual(m["headroom_stops"], 0.0, delta=0.15)
        self.assertLess(m["recoverable_hi_pct"], 3)

    def test_crushed_shadows_with_raw_signal_count_as_recoverable(self):
        raw = np.full((10, 10, 3), 0.01, np.float32)      # ~38 DN above black: real signal
        jpeg = np.zeros((10, 10, 3), np.uint8)             # crushed to black in the JPEG
        m = self.rv.measure(jpeg, raw)
        self.assertEqual(m["jpeg_crushed_pct"], 100.0)
        self.assertEqual(m["recoverable_lo_pct"], 100.0)
        m = self.rv.measure(jpeg, np.zeros_like(raw))      # nothing there in the raw either
        self.assertEqual(m["recoverable_lo_pct"], 0.0)

    def test_channel_clipping_counts_any_channel(self):
        jpeg = np.full((10, 10, 3), 128, np.uint8)
        jpeg[:5, :, 0] = 255
        m = self.rv.measure(jpeg, np.full((10, 10, 3), 0.2, np.float32))
        self.assertEqual(m["jpeg_channel_clip_pct"], 50.0)


if __name__ == "__main__":
    unittest.main()
