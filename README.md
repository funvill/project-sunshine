# Project Sunset

A five-year time-lapse of the western sky from a 23rd-floor window in Burnaby, BC, looking toward
downtown Vancouver. **Sunset is the subject.** Real capture starts on the winter solstice,
**2026-12-21**. Until then a pilot runs on a Raspberry Pi 3 B+ to tune the camera, the sync and the
daily video.

This README is the handoff: it says what exists, what state it is in, and where to start. The full
brief, with every decision and the reason for it, is [`CLAUDE.md`](CLAUDE.md). Changes are listed by
date in [`changelog.md`](changelog.md). Where this file and `CLAUDE.md` disagree, `CLAUDE.md` is
more likely to be current.

## How it works

1. **Capture (Pi):** a frame every 5 minutes, day and night, plus one a minute around sunrise and
   sunset. Each regular frame is a JPEG, a DNG and a JSON metadata file; a 4 s night frame is added
   when it is dark. Frames are written to the SD card first.
2. **Sync (Pi to NAS):** frames are copied to an SMB share on the NAS and deleted from the SD card
   only once the copy is confirmed, so a NAS or network outage loses nothing.
3. **Alert (Home Assistant):** warns when the newest frame on the NAS is more than about an hour old.
4. **Daily video (NAS):** after dark, a job turns the day's frames into a vertical video for
   Instagram. It posts nothing yet.

Frame layout on the NAS, with UTC names:

```
project_sunshine/wide/YYYY/MM/DD/wide_<UTC>.{jpg,dng,json}   (+ wide_<UTC>_night.*)
```

Each `.json` holds the camera settings, a `Sun` block (azimuth, elevation, minutes from sunset), a
`Capture` block (how and why the frame was taken) and a `System` block (temperature, disk, checksums).
A `system.json` in each day folder holds what rarely changes.

## Current state (2026-11-08)

| Part | State |
|---|---|
| Capture on the pilot Pi | Running: 5-minute frames and, from 2026-11-09, 1-a-minute frames at sunrise and sunset |
| Sync to the NAS | Running |
| Home Assistant alert | Installed and working |
| Daily video job | On `main`, tested on real frames from a PC. **Never run on the NAS**; the Docker image has never been built |
| Instagram posting | Not started: no account, Meta app or publishing code |
| Pilot experiments | Running on the Pi between captures; results on issue #3 |
| Final mount, foam hood, wide lens | Not done |

Known problems:

- **Lens too narrow.** The camera has the official Pi 6 mm CS lens, about 58° wide. The sunset swings
  about 75° over a year, so it is predicted to be out of frame from about Nov 21 to Jan 19 and from
  about May 7 to Aug 4. That includes the solstice start. See issue #4.
- **Power:** the Pi had undervoltage and one hard freeze. A new supply went in on 2026-11-08 with no
  warnings since; keep watching before calling it fixed.
- **Heat:** the Pi runs at 55 to 60 °C at capture, at its soft limit. A heatsink is on the to-do list.
- **No clear sunset yet.** Every afternoon of the pilot has been overcast, so framing, the 9° dusk
  cut-off and sunset exposure haven't been checked against a real sun.

## Open issues

| Issue | What it is | Waiting on |
|---|---|---|
| [#2](https://github.com/funvill/project-sunshine/issues/2) | Daily sunset video to Instagram. Its latest comment is the handoff for that work | Owner decisions on login and public posting; the NAS run |
| [#3](https://github.com/funvill/project-sunshine/issues/3) | Pilot experiments: night exposure, capture rate, sunset, direct sun | Clear evenings |
| [#4](https://github.com/funvill/project-sunshine/issues/4) | The 6 mm lens can't see both ends of the sunset swing | A lens choice (buying decision) |
| [#5](https://github.com/funvill/project-sunshine/issues/5) | Keep the DNG files or not | Owner decision |

Other owner decisions not yet made: a High Endurance SD card for the real run, an RTC, the heatsink,
and the final mount and hood. The longer backlog is at the end of `CLAUDE.md`.

## Layout

| Folder | What is in it | Read |
|---|---|---|
| `pi/` | Everything that runs on the Pi: capture, sync, metadata, sun position, self-test, focus and diagnostics page, systemd units. Copied flat into `~/sunset` | [Pi setup guide](docs/setup.md) |
| `nas/` | The daily sunset video job (Python + ffmpeg in Docker) | [nas/README.md](nas/README.md) |
| `experiments/` | Pilot experiment runner and the hourly weather log. Not part of production capture | Issue #3 |
| `tools/` | `issue_blur.py`: blurs and labels the nearby buildings in images posted to GitHub issues. Runs on a PC | |
| `homeassistant/` | The stale-frame alert, copied into Home Assistant by hand | [Pi setup guide](docs/setup.md#home-assistant-alert) |
| `tests/` | Offline tests with a stubbed camera and NAS | Below |
| `docs/` | Pi setup guide and hardware notes | [hardware notes](docs/hardware/README.md) |

## Getting started

**To work on the code:** no Pi or NAS is needed. Run the tests:

```bash
bash tests/run.sh
```

```bash
python3 tests/test_daily.py
```

They need bash, coreutils and Python 3. The video tests also need ffmpeg and are skipped without it.
Write a failing test first, then the change.

**To set up a Pi:** follow [docs/setup.md](docs/setup.md). Copy `pi/sunset.env.example` to
`~/sunset/sunset.env` and set the real site coordinates there. On the pilot Pi,
`./sunset-selftest.sh` checks the camera, clock, disk, memory, capture time, IR-cut filter and NAS.

**To run the daily video:** see [nas/README.md](nas/README.md). Build the image, then schedule it every
30 minutes through the afternoon and evening.

## Rules

- **Never commit frames, `sunset.env` or credentials.** The repo is public. `sunset.env` holds the
  real coordinates, and the NAS login lives only in a root-only file on the Pi.
- **Frame files carry no site coordinates**, in case they are ever published. Captions carry no
  location details either.
- **Filenames are UTC.** The frame layout doesn't change.
- **Change `SETUP_ID` in `sunset.env`** whenever the camera, lens, focus, mount or hood changes.
- **Add a `changelog.md` entry with every change**, including changes made only on the Pi.
- **Commits by an AI agent** are authored as `SWS-Chipkin <sws-dev@chipkin.com>`.
- Capture-schedule and camera-setting changes on the Pi are production changes: ask the owner first.

## Hardware

Pilot: Raspberry Pi 3 B+ (`timelaps`), Arducam UC-517 (IMX477 sensor, the same as the Pi HQ camera)
with the Pi 6 mm CS lens, sitting loose on a shelf behind the glass. The plan for the real run is a
wider lens, a 3D-printed keyed mount stuck to the glass, a black foam hood against reflections, and
later a second, tighter camera on downtown. Details and the shopping list are in `CLAUDE.md` and
[docs/hardware/README.md](docs/hardware/README.md).
