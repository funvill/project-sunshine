"""Tests for sunset-focus.py: python3 tests/test_focus.py"""
import importlib.util
import os
import struct
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sunset_focus", os.path.join(os.path.dirname(HERE), "sunset-focus.py"))
focus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(focus)

W, H = 64, 48


def checker(lo, hi):
    return bytes(hi if (x // 2 + y // 2) % 2 else lo for y in range(H) for x in range(W))


def blur(g):
    out = bytearray(g)
    for y in range(H):
        for x in range(1, W - 1):
            out[y * W + x] = (g[y * W + x - 1] + g[y * W + x] + g[y * W + x + 1]) // 3
    for y in range(1, H - 1):
        for x in range(W):
            out[y * W + x] = (out[(y - 1) * W + x] + out[y * W + x] + out[(y + 1) * W + x]) // 3
    return bytes(out)


def write_bmp(path, w, h, pixel, bpp=24):
    step = bpp // 8
    row = (w * step + 3) // 4 * 4
    px = bytearray()
    for y in range(h):
        line = b"".join(pixel(x, y) + b"\0" * (step - 3) for x in range(w))
        px += line + b"\0" * (row - len(line))
    hdr = b"BM" + struct.pack("<IHHI", 54 + len(px), 0, 0, 54)
    hdr += struct.pack("<IiiHHIIiiII", 40, w, h, 1, bpp, 0, len(px), 0, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(hdr + bytes(px))


class Sharpness(unittest.TestCase):
    def test_sharp_scores_higher_than_blurred(self):
        g = checker(50, 200)
        self.assertGreater(focus.sharpness(W, H, g), 2 * focus.sharpness(W, H, blur(g)))

    def test_flat_scene_scores_zero(self):
        self.assertEqual(focus.sharpness(W, H, bytes([100]) * (W * H)), 0.0)

    def test_black_frame_does_not_divide_by_zero(self):
        self.assertEqual(focus.sharpness(W, H, bytes(W * H)), 0.0)

    def test_score_ignores_brightness(self):
        a = focus.sharpness(W, H, checker(20, 80))
        b = focus.sharpness(W, H, checker(40, 160))
        self.assertAlmostEqual(a, b, delta=a * 0.01)


class Bmp(unittest.TestCase):
    def check(self, bpp):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bmp")
            write_bmp(p, 5, 3, lambda x, y: bytes([1, 10 * x + y, 200]), bpp)
            w, h, g = focus.read_bmp_green(p)
            self.assertEqual((w, h, len(g)), (5, 3, 15))
            self.assertEqual(list(g[:5]), [0, 10, 20, 30, 40])

    def test_24_bit_with_row_padding(self):
        self.check(24)

    def test_32_bit(self):
        self.check(32)


if __name__ == "__main__":
    unittest.main(verbosity=1)
