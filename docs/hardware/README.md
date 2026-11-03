# Hardware references

## Arducam UC-517 (IMX477 IR-CUT) cable orientation

`uc517-cable-orientation.webp` is the vendor's product photo, kept as a reference for how
the 22-pin cable goes between a Pi Zero and the UC-517. Source:
https://robotools.in/wp-content/uploads/2022/09/Arducam-High-Quality-IR-CUT-Camera-for-Raspberry-Pi-12.3MP-12.3-Inch-IMX477-HQ-Camera-Module-with-6mm-CS-Lens-for-Pi-4B-3B-2B-3A-Pi-Zero-and-more-b0270-5.jpg

What it shows: the blue stiffener is visible at both ends, but the ribbon shows its plain face
near the Zero and its printed face near the camera, so it appears to loop out of frame. That
suggests stiffeners on opposite faces of the cable, not a flat ribbon. The camera is also lens-up
in the photo, so "blue up" there may not match a board lying connector-side up. Do not use
"blue up at both ends" as an instruction.

Orientation is unverified. Do not rely on trying both ways: a reversed 22-pin connection would
join the Pi's 3V3 (pin 22) to camera GND (pin 1), per the pinouts found so far (a related Arducam
board; not confirmed for the UC-517). Check with a multimeter, power off, before powering up:

| Probe (cable fitted at both ends, no power) | Near 0 ohm means |
|---|---|
| Camera `3V3` pad to Pi header pin 1 (3V3) | correct |
| Camera `GND` pad to Pi header pin 6 (GND) | correct |
| Camera `3V3` pad to Pi header pin 6 (GND) | **reversed: do not power up** |
| Neither `3V3` reading near 0 | no contact (would explain error -121) |

Forum report of this board and a cable-orientation fix:
https://forum.arducam.com/t/pi-zero-w-cant-find-new-ir-cut-camera/5679

The photo is Arducam's / the retailer's, so it is not committed to this (public) repo.
Pi 3 end: use a 22-to-15-pin cable (Adafruit #3157).

## Pilot findings (2026-11-03)
Working reference: Pi 3 B+ Rev 1.3, Raspberry Pi OS Bookworm 32-bit (armv7l), kernel 6.12, with
the UC-517 in the CAMERA port (between HDMI and the audio jack) and the Pi end oriented as that
Pi's working v1 camera cable was.
- Auto-detect does not find the UC-517. `camera_auto_detect=0` + `dtoverlay=imx477` does:
  `imx477 10-001a: Device found is imx477`, listed as 4056x3040 12-bit.
- Full-resolution JPEG + DNG took 18.2 s on the Pi 3 B+ (`-t 3000`). The DNG was 24.8 MB; the
  JPEG was 0.9 MB, but from a dark frame, so it is not a typical size.
- The test frame was black (Lux 1.2). Lens, iris or lens cap not yet checked, so image output
  is unverified.
- The DISPLAY port looks like the CAMERA port but does not work for cameras.
- Not yet shown on a Pi Zero W. Earlier Zero failures were not resolved; they were set aside
  when testing restarted.
- The Pi Zero W has no power LED, only the green activity LED.
