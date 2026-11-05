#!/usr/bin/env python3
"""Measure experiment JPEGs off the Pi (needs Pillow and numpy; not for the Pi itself).

    analyse_frames.py <folder of .jpg> [--csv out.csv]

Regions are fractions of the frame and depend on the framing, so check them after the camera moves:
sky is the open area right of the towers, far is the distant skyline, and the whole frame is used
for clipping.
"""
import argparse
import csv
import json
import pathlib

import numpy as np
from PIL import Image

SKY = (0.66, 0.15, 0.95, 0.45)  # left, top, right, bottom
FAR = (0.72, 0.52, 0.95, 0.60)


def crop(a, box):
    h, w = a.shape[:2]
    left, top, right, bottom = box
    return a[int(top * h):int(bottom * h), int(left * w):int(right * w)]


def fine_noise(gray):
    """Noise estimate that ignores gradual brightness: spread of neighbouring-pixel differences."""
    diff = gray[:, 1:].astype(float) - gray[:, :-1].astype(float)
    return float(1.4826 * np.median(np.abs(diff - np.median(diff))) / np.sqrt(2))


def measure(path):
    a = np.asarray(Image.open(path).convert("RGB"))
    gray = a.mean(axis=2)
    sky = crop(a, SKY)
    sky_gray = sky.mean(axis=2)
    far = crop(gray, FAR)
    r, g, b = [float(np.median(sky[:, :, i])) for i in range(3)]
    row = {
        "file": path.name,
        "clipped_pct": round(float((a.max(axis=2) >= 250).mean() * 100), 2),
        "sky_median": round(float(np.median(sky_gray)), 1),
        "sky_rgb": f"{r:.0f}/{g:.0f}/{b:.0f}",
        "green_excess": round(g - (r + b) / 2, 1),
        "sky_noise": round(fine_noise(sky_gray), 2),
        "far_contrast": round(float(np.percentile(far, 99) - np.percentile(far, 50)), 1),
        "mean": round(float(gray.mean()), 1),
    }
    meta = path.with_suffix(".json")
    if meta.exists():
        data = json.loads(meta.read_text())
        row["exposure_ms"] = round(data.get("ExposureTime", 0) / 1000, 2)
        row["gain"] = round(data.get("AnalogueGain", 0), 2)
        row["lux"] = round(data.get("Lux", 0), 2)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=pathlib.Path)
    parser.add_argument("--csv", type=pathlib.Path)
    args = parser.parse_args()
    rows = [measure(p) for p in sorted(args.folder.glob("*.jpg"))]
    keys = list(rows[0]) if rows else []
    for key in ("exposure_ms", "gain", "lux"):
        if key not in keys:
            keys.append(key)
    if args.csv:
        with args.csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, keys)
            writer.writeheader()
            writer.writerows(rows)
    print("\t".join(keys))
    for row in rows:
        print("\t".join(str(row.get(k, "")) for k in keys))


if __name__ == "__main__":
    main()
