#!/usr/bin/env python3
"""Live focus meter for setting the lens by hand. Stdlib only, so it runs on the Zero.

    python3 sunset-focus.py [--count N] [--roi X,Y,W,H]

Repeatedly grabs a small crop from the middle of the frame and prints a sharpness
score. Aim at something distant with fine detail, turn the focus ring slowly, and
stop at the highest score. The score only compares frames of the same scene in the
same light; it has no absolute meaning. Stop the capture timer first: only one
program can use the camera at a time. Ctrl-C to quit.
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile


def read_bmp_green(path):
    """Return (width, height, green channel as bytes) from a 24/32-bit BMP."""
    with open(path, "rb") as f:
        d = f.read()
    off, = struct.unpack_from("<I", d, 10)
    w, h = struct.unpack_from("<ii", d, 18)
    bpp, = struct.unpack_from("<H", d, 28)
    if bpp not in (24, 32):
        raise ValueError("unsupported BMP depth %d" % bpp)
    h = abs(h)
    step = bpp // 8
    row = (w * step + 3) // 4 * 4
    green = bytearray()
    for y in range(h):
        start = off + y * row + 1  # BGR(A): green is the second byte
        green += d[start:start + w * step:step]
    return w, h, bytes(green)


def sharpness(w, h, g):
    """Squared difference between neighbouring pixels, scaled to ignore brightness."""
    total = 0
    for y in range(h - 1):
        row = g[y * w:(y + 1) * w]
        below = g[(y + 1) * w:(y + 2) * w]
        for x in range(w - 1):
            total += (row[x] - row[x + 1]) ** 2 + (row[x] - below[x]) ** 2
    mean = sum(g) / float(len(g))
    if mean < 1:
        return 0.0
    return 100000.0 * total / (2.0 * (w - 1) * (h - 1) * mean * mean)


def grab(path, roi):
    subprocess.run(["rpicam-still", "-n", "-t", "700", "--roi", roi,
                    "--width", "320", "--height", "240", "-e", "bmp", "-o", path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--count", type=int, default=0, help="stop after N readings (default: run until Ctrl-C)")
    p.add_argument("--roi", default="0.4,0.4,0.2,0.2", help="crop as fractions of the frame: X,Y,W,H")
    args = p.parse_args(argv)
    best = 0.0
    n = 0
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "focus.bmp")
        try:
            while args.count == 0 or n < args.count:
                try:
                    grab(path, args.roi)
                except subprocess.CalledProcessError as exc:
                    print("camera error: %s" % exc.stderr.decode(errors="replace").strip()[-200:], file=sys.stderr)
                    return 1
                except (OSError, subprocess.TimeoutExpired) as exc:
                    print("camera error: %s" % exc, file=sys.stderr)
                    return 1
                try:
                    score = sharpness(*read_bmp_green(path))
                except (OSError, ValueError, struct.error) as exc:
                    print("could not read frame: %s" % exc, file=sys.stderr)
                    return 1
                best = max(best, score)
                n += 1
                bar = "#" * int(40 * score / best) if best else ""
                print("%8.2f  best %8.2f  %s" % (score, best, bar), flush=True)
        except KeyboardInterrupt:
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
