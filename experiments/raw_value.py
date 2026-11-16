#!/usr/bin/env python3
"""Does the RAW (DNG) hold anything the JPEG of the same capture doesn't? (issue #38)

rpicam-still --raw writes the DNG and the JPEG from one exposure, so the two can be compared pixel for
pixel. The DNG is read here with numpy alone (no rawpy): rpicam's layout is an IFD0 thumbnail whose
SubIFD holds the uncompressed 16-bit CFA (IMX477: BGGR, black 256, white 4095). It is reduced to
half size, one RGB pixel per 2x2 Bayer block (greens averaged), linear, 0 = black, 1 = white, with
no white balance; the JPEG is shrunk to the same size.

Per frame:
    jpeg_clip_pct         share of pixels with any JPEG channel >= 250
    raw_clip_pct          share with any raw channel >= 0.98 of full scale
    recoverable_hi_pct    clipped in the JPEG but not in the raw: sky the DNG could bring back
    headroom_stops        how much brighter than the JPEG's clip point the raw can go before it clips:
                          the raw level (brightest channel) at which half the pixels are JPEG-clipped,
                          as log2(1 / level). 0 means they clip together; 2 is what the ev-2 bracket gives.
    jpeg_channel_clip_pct share with any JPEG channel >= 254: white balance can't be fixed there later
    jpeg_crushed_pct      share with every JPEG channel <= 4
    recoverable_lo_pct    crushed in the JPEG but with raw signal (brightest channel >= 16 DN over black)

    python experiments/raw_value.py <frames>/2026/11/15/wide_20261115T200000Z.jpg ...
    python experiments/raw_value.py --compare <frame>.jpg <frame>_ev-2.jpg

Each JPEG needs its DNG beside it (same stem). Frames are only read. Needs numpy and OpenCV.
"""
import argparse
import math
import os
import struct
import sys

import cv2
import numpy as np

JPEG_CLIP = 250
JPEG_CHANNEL_CLIP = 254
RAW_CLIP = 0.98
CRUSHED = 4
SIGNAL_DN = 16           # about 4x the IMX477's read noise at gain 1 (estimate)
HEADROOM_BINS = 96       # log-spaced raw levels from 2^-10 to 1
HEADROOM_MIN_PIXELS = 20

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}


def _ifd(f, bo, offset):
    """{tag: (type, count, values or raw bytes)} of the IFD at offset."""
    f.seek(offset)
    n = struct.unpack(bo + "H", f.read(2))[0]
    entries = {}
    for i in range(n):
        f.seek(offset + 2 + 12 * i)
        tag, typ, count = struct.unpack(bo + "HHI", f.read(8))
        raw = f.read(4)
        size = TYPE_SIZE.get(typ, 1) * count
        if size > 4:
            f.seek(struct.unpack(bo + "I", raw)[0])
            raw = f.read(size)
        if typ == 3:
            value = struct.unpack(bo + "%dH" % count, raw[:2 * count])
        elif typ in (4, 13):
            value = struct.unpack(bo + "%dI" % count, raw[:4 * count])
        elif typ in (5, 10):
            fmt = bo + ("%di" if typ == 10 else "%dI") % (2 * count)
            nums = struct.unpack(fmt, raw[:8 * count])
            value = tuple(a / b if b else 0.0 for a, b in zip(nums[0::2], nums[1::2]))
        else:
            value = raw[:size]
        entries[tag] = value
    return entries


def read_dng(path):
    """{cfa: uint16 HxW, black, white, pattern: 4 colour indices (0 R, 1 G, 2 B), neutral: as-shot (R,G,B)}."""
    with open(path, "rb") as f:
        head = f.read(8)
        bo = "<" if head[:2] == b"II" else ">"
        ifd0 = _ifd(f, bo, struct.unpack(bo + "I", head[4:8])[0])
        candidates = [ifd0] + [_ifd(f, bo, o) for o in ifd0.get(330, ())]
        raw = next((d for d in candidates if d.get(254, (1,))[0] == 0 and d.get(262, (0,))[0] == 32803), None)
        if raw is None:
            raise ValueError("%s: no CFA image" % path)
        if raw.get(259, (1,))[0] != 1 or raw.get(258, (0,))[0] != 16:
            raise ValueError("%s: only uncompressed 16-bit CFA is read" % path)
        w, h = raw[256][0], raw[257][0]
        f.seek(raw[273][0])
        cfa = np.frombuffer(f.read(w * h * 2), dtype=np.dtype(np.uint16).newbyteorder(bo)).reshape(h, w)
    black = raw.get(50714, (0,))
    neutral = raw.get(50728) or ifd0.get(50728) or (1.0, 1.0, 1.0)
    return {"cfa": cfa.astype(np.uint16), "black": int(round(sum(black) / len(black))),
            "white": int(raw.get(50717, (65535,))[0]), "pattern": list(raw.get(33422, b"\0\1\1\2")),
            "neutral": [float(x) for x in neutral]}


def half_rgb(dng):
    """Linear RGB at half size, 0 black to 1 white, no white balance."""
    cfa = (dng["cfa"].astype(np.float32) - dng["black"]) / float(dng["white"] - dng["black"])
    h, w = cfa.shape[0] // 2 * 2, cfa.shape[1] // 2 * 2
    sites = [cfa[0:h:2, 0:w:2], cfa[0:h:2, 1:w:2], cfa[1:h:2, 0:w:2], cfa[1:h:2, 1:w:2]]
    rgb = np.zeros(sites[0].shape + (3,), np.float32)
    count = [0, 0, 0]
    for site, colour in zip(sites, dng["pattern"]):
        rgb[..., colour] += site
        count[colour] += 1
    for c in range(3):
        rgb[..., c] /= max(count[c], 1)
    return np.clip(rgb, 0.0, 1.0)


def headroom(jpeg_clipped, raw_level):
    """log2(1 / the lowest raw level at which at least half the pixels are JPEG-clipped), or None."""
    edges = np.logspace(-10, 0, HEADROOM_BINS + 1, base=2.0)
    idx = np.clip(np.searchsorted(edges, raw_level, side="right") - 1, 0, HEADROOM_BINS - 1)
    for b in range(HEADROOM_BINS):
        sel = idx == b
        n = int(sel.sum())
        if n >= HEADROOM_MIN_PIXELS and jpeg_clipped[sel].mean() >= 0.5:
            return max(0.0, math.log2(1.0 / edges[b]))
    return None


def measure(jpeg_rgb, raw_rgb, white_dn=3839):
    """The numbers in the module docstring. jpeg_rgb uint8 and raw_rgb float, both HxWx3, same size."""
    jmax = jpeg_rgb.max(axis=2)
    rmax = raw_rgb.max(axis=2)
    j_clip = jmax >= JPEG_CLIP
    r_clip = rmax >= RAW_CLIP
    crushed = jmax <= CRUSHED
    signal = rmax >= SIGNAL_DN / float(white_dn)
    pct = lambda m: round(100.0 * float(m.mean()), 3)
    stops = headroom(j_clip, rmax)
    return {"jpeg_clip_pct": pct(j_clip), "raw_clip_pct": pct(r_clip), "recoverable_hi_pct": pct(j_clip & ~r_clip),
            "headroom_stops": None if stops is None else round(stops, 2),
            "jpeg_channel_clip_pct": pct(jmax >= JPEG_CHANNEL_CLIP),
            "jpeg_crushed_pct": pct(crushed), "recoverable_lo_pct": pct(crushed & signal)}


def load_pair(jpg_path):
    dng = read_dng(os.path.splitext(jpg_path)[0] + ".dng")
    raw = half_rgb(dng)
    jpeg = cv2.imread(jpg_path, cv2.IMREAD_COLOR)
    if jpeg is None:
        raise ValueError("%s: can't read" % jpg_path)
    jpeg = cv2.cvtColor(cv2.resize(jpeg, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    return jpeg, raw, dng


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("frames", nargs="*", help="JPEGs with their DNG beside them")
    ap.add_argument("--compare", nargs=2, metavar=("FRAME", "EV2"),
                    help="a frame with its DNG, and the ev-2 JPEG of the same minute: which keeps more highlight")
    a = ap.parse_args(argv)
    for path in a.frames:
        jpeg, raw, dng = load_pair(path)
        m = measure(jpeg, raw, dng["white"] - dng["black"])
        print("%s  %s" % (os.path.basename(path), "  ".join("%s=%s" % kv for kv in m.items())))
    if a.compare:
        jpeg, raw, dng = load_pair(a.compare[0])
        frame = measure(jpeg, raw, dng["white"] - dng["black"])
        ev2 = cv2.imread(a.compare[1], cv2.IMREAD_COLOR)
        ev2_clip = round(100.0 * float((ev2.max(axis=2) >= JPEG_CLIP).mean()), 3)
        print("%s: JPEG clips %.3f%%, its DNG %.3f%% (headroom %s stops); the ev-2 JPEG clips %.3f%%" % (
            os.path.basename(a.compare[0]), frame["jpeg_clip_pct"], frame["raw_clip_pct"], frame["headroom_stops"], ev2_clip))
    return 0


if __name__ == "__main__":
    sys.exit(main())
