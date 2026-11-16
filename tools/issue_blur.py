#!/usr/bin/env python3
"""Blur the nearby buildings in a frame before it is posted to a GitHub issue.

Only for images posted to issues. Frames, videos and everything else are left as they are.
The blur is light: the outline of the building and its decks stay visible, the detail goes.
Each building gets a "Blurred for privacy" label, so nobody mistakes it for a bad photo.

The frame is resized to the posted width first, so a style looks the same at any size.

    python3 tools/issue_blur.py frame.jpg out.jpg [--width 1200] [--style 1]
            [--crop x0 y0 x1 y1] [--setup ID | --json frame.json | --buildings buildings.json]

The outlines must match the camera position the frame was taken at. The setup is read from
Capture.setup_id in the frame's JSON (frame.json beside frame.jpg, or --json), or given with
--setup. A setup with no outlines here is refused rather than blurred in the wrong place: draw
its outlines and add them to BUILDINGS, or pass --buildings.

Runs on a PC, not the Pi: it needs numpy, OpenCV and Pillow.
"""
import argparse
import json
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Outlines of the nearby buildings in full-frame pixels (4056 x 3040), by SETUP_ID.
# Redo these whenever the camera moves (SETUP_ID changes). Only pilot-3 has been drawn: pilot-4
# (timelaps since 2026-11-12) and cm4-window-1 (the CM4) have none yet, so they are refused.
BUILDINGS = {
    "pilot-3": [
        [(1180, 775), (1300, 765), (1535, 800), (1535, 2215), (1190, 2215)],  # left tower
        [(1725, 425), (1990, 380), (2045, 370), (2060, 735), (2145, 735), (2135, 2395), (1735, 2395)],  # centre tower
        [(3675, 925), (3780, 900), (3945, 905), (3960, 1395), (4056, 1395), (4056, 2220), (3685, 2220)],  # right tower
        [(145, 1845), (400, 1845), (405, 2330), (145, 2330)],  # low tower, far left
    ],
}
LABEL = ("Blurred", "for privacy")
FONTS = ("arialbd.ttf", "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


class SetupError(Exception):
    """No outlines that are known to fit this frame."""


def frame_setup(frame_path, json_path=None):
    """Capture.setup_id from the frame's JSON: `json_path`, else the .json beside the frame.
    None if there is no such file or it has no setup_id. A `json_path` that can't be read is an error."""
    path = json_path or os.path.splitext(frame_path)[0] + ".json"
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        if json_path:
            raise SetupError("can't read %s" % json_path)
        return None
    except (OSError, ValueError) as e:
        raise SetupError("can't read %s: %s" % (path, e))
    capture = data.get("Capture") if isinstance(data, dict) else None
    return capture.get("setup_id") if isinstance(capture, dict) else None


def choose_outlines(setup_arg, json_setup, buildings=None):
    """The polygons to blur. `buildings` (explicit outlines) wins; otherwise the setup, which
    must agree between --setup and the frame's JSON and must have outlines in BUILDINGS."""
    if buildings is not None:
        return buildings
    if setup_arg and json_setup and setup_arg != json_setup:
        raise SetupError("--setup %s but the frame's JSON says %s" % (setup_arg, json_setup))
    setup = setup_arg or json_setup
    if not setup:
        raise SetupError("the frame has no JSON with Capture.setup_id: pass --setup, --json or --buildings")
    if setup not in BUILDINGS:
        raise SetupError("no building outlines for setup %r (outlines exist for: %s). Draw them and add "
                         "them to BUILDINGS, or pass --buildings" % (setup, ", ".join(sorted(BUILDINGS))))
    return BUILDINGS[setup]


def gaussian(img, sigma):
    return cv2.GaussianBlur(img, (0, 0), sigma)


def smear(img):
    """Blur along the decks, not across them: keeps the floor lines, loses the windows."""
    return cv2.blur(cv2.blur(img, (21, 1)), (1, 3))


def mosaic(img, block=6):
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(1, w // block), max(1, h // block)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def frosted(img):
    """Like frosted glass: a light blur, washed out towards grey."""
    b = gaussian(img, 3).astype(np.float32)
    grey = b.mean(axis=2, keepdims=True)
    return np.clip(0.55 * b + 0.25 * grey + 0.2 * 200, 0, 255).astype(np.uint8)


# Strengths are in pixels of the posted image.
STYLES = {
    1: ("Light Gaussian (2.5 px)", lambda im: gaussian(im, 2.5)),
    2: ("Medium Gaussian (4 px)", lambda im: gaussian(im, 4)),
    3: ("Smear along the decks", smear),
    4: ("Mosaic (6 px blocks)", mosaic),
    5: ("Frosted glass", frosted),
}


def load_font(size):
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def building_mask(shape, polygons, scale, offset):
    mask = np.zeros(shape[:2], np.uint8)
    for poly in polygons:
        pts = np.array([((x - offset[0]) * scale, (y - offset[1]) * scale) for x, y in poly], np.float32)
        cv2.fillPoly(mask, [np.round(pts).astype(np.int32)], 255)
    return mask


def label(img, polygons, scale, offset):
    """Two-line label on each building, sized to fit its width, a third of the way down."""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).convert("RGBA")
    layer = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    h, w = img.shape[:2]
    for poly in polygons:
        xs = [(x - offset[0]) * scale for x, _ in poly]
        ys = [(y - offset[1]) * scale for _, y in poly]
        x0, x1 = max(0, min(xs)), min(w, max(xs))
        y0, y1 = max(0, min(ys)), min(h, max(ys))
        if x1 - x0 < 20 or y1 - y0 < 20:
            continue  # outside the crop or too small to label
        size = 40
        while size > 7:
            font = load_font(size)
            widths = [draw.textbbox((0, 0), t, font=font)[2] for t in LABEL]
            if max(widths) <= 0.86 * (x1 - x0):
                break
            size -= 1
        line_h = draw.textbbox((0, 0), "Hg", font=font)[3]
        block_h = line_h * len(LABEL) + 4
        cx, top = (x0 + x1) / 2, y0 + (y1 - y0) / 3 - block_h / 2
        pad = max(2, size // 4)
        draw.rounded_rectangle((cx - max(widths) / 2 - pad, top - pad, cx + max(widths) / 2 + pad, top + block_h + pad),
                               radius=pad, fill=(0, 0, 0, 150))
        for i, (text, tw) in enumerate(zip(LABEL, widths)):
            draw.text((cx - tw / 2, top + i * (line_h + 4)), text, font=font, fill=(255, 255, 255, 235))
    out = Image.alpha_composite(pil, layer).convert("RGB")
    return cv2.cvtColor(np.asarray(out), cv2.COLOR_RGB2BGR)


def blur_for_issue(frame, polygons, style=1, width=1200, crop=None):
    """frame: BGR array at full size. Returns the posted image: cropped, resized, blurred, labelled."""
    offset = (0, 0)
    if crop:
        x0, y0, x1, y1 = crop
        frame, offset = frame[y0:y1, x0:x1], (x0, y0)
    scale = width / frame.shape[1]
    img = cv2.resize(frame, (width, round(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    mask = building_mask(img.shape, polygons, scale, offset)
    soft = gaussian(mask, 1.2).astype(np.float32)[..., None] / 255  # keeps the edge, hides the seam
    blurred = STYLES[style][1](img)
    img = (blurred * soft + img * (1 - soft)).astype(np.uint8)
    return label(img, polygons, scale, offset)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("frame")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=1200, help="posted width in pixels (default 1200)")
    ap.add_argument("--style", type=int, default=1, choices=sorted(STYLES), help="1 is the chosen style (default)")
    ap.add_argument("--crop", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"), help="full-frame pixels")
    ap.add_argument("--setup", help="framing the outlines belong to (default: Capture.setup_id in the frame's JSON)")
    ap.add_argument("--json", help="the frame's JSON, if it isn't beside the frame")
    ap.add_argument("--buildings", help="JSON list of polygons [[x, y], ...] in full-frame pixels, instead of --setup")
    a = ap.parse_args()
    try:
        buildings = None
        if a.buildings:
            with open(a.buildings) as f:
                buildings = json.load(f)
        polygons = choose_outlines(a.setup, None if buildings else frame_setup(a.frame, a.json), buildings)
    except SetupError as e:
        raise SystemExit("issue_blur: %s" % e)
    frame = cv2.imread(a.frame)
    if frame is None:
        raise SystemExit("can't read " + a.frame)
    out = blur_for_issue(frame, polygons, a.style, a.width, a.crop)
    cv2.imwrite(a.out, out, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(os.path.abspath(a.out))


if __name__ == "__main__":
    main()
