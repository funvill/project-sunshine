# Hardware references

## Arducam UC-517 (IMX477 IR-CUT) cable orientation

`uc517-cable-orientation.webp` is the vendor's product photo, kept as a reference for how
the 22-pin cable goes between a Pi Zero and the UC-517. Source:
https://robotools.in/wp-content/uploads/2022/09/Arducam-High-Quality-IR-CUT-Camera-for-Raspberry-Pi-12.3MP-12.3-Inch-IMX477-HQ-Camera-Module-with-6mm-CS-Lens-for-Pi-4B-3B-2B-3A-Pi-Zero-and-more-b0270-5.jpg

What it shows: a flat, untwisted ribbon with the blue stiffener facing up at BOTH ends,
i.e. metal contacts down toward the board at the Pi Zero and at the camera. This matches
Arducam support's advice in
https://forum.arducam.com/t/pi-zero-w-cant-find-new-ir-cut-camera/5679
("metal contacts face the board, not the blue plastic side").

The photo is Arducam's / the retailer's, so it is not committed to this (public) repo.
Pi 3 end: use a 22-to-15-pin cable (Adafruit #3157).

## Pilot findings (2026-11-03)
- UC-517 not detected on 2 Pi Zero W + 2 Pi 3B, several cables, both orientations at the
  camera end, clean power: `imx477 10-001a: failed to read chip id 477, with error -121`.
- Camera Module v1 (known good elsewhere) also not detected on the Pi 3 with auto-detect:
  the shared factor (Pi-end cable orientation, Pi 3 camera port, or the SD card config) is
  still unresolved.
