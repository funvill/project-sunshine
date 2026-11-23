# Project Sunset

A five-year time-lapse of the western sky from a tower window in Burnaby, BC, looking toward
downtown Vancouver. **Sunset is the subject.** Real capture starts on the winter solstice,
**2026-12-21**. Until then a pilot runs on one Raspberry Pi CM4 with two cameras, to tune the cameras, the sync and the
daily video.

This README is the handoff: it says what exists, what state it is in, and where to start. The full
brief, with every decision and the reason for it, is [`CLAUDE.md`](CLAUDE.md). Changes are listed by
date in [`changelog.md`](changelog.md). Where this file and `CLAUDE.md` disagree, `CLAUDE.md` is
more likely to be current.

## How it works

1. **Capture (Pi):** a frame every 5 minutes, day and night, plus one a minute around sunset, on
   each camera. Each frame is a JPEG and a JSON metadata file (no DNG since 2026-11-16); a long night
   frame is added when it is dark. Frames are written to the Pi's own storage first.
2. **Sync (Pi to NAS):** frames are copied to an SMB share on the NAS and deleted from the SD card
   only once the copy is confirmed, so a NAS or network outage loses nothing.
3. **Alert (Home Assistant):** warns when the newest frame on the NAS is more than about an hour old.
4. **Daily video (PC):** `tools/build_video.py` turns a day's frames into a vertical video for
   Instagram ([how](#building-a-days-video-by-hand)). It posts nothing. Only good sunsets are posted,
   by hand: a deterministic sky score (0 to 100, no AI) rates each day, and days scoring 60 or more
   are worth posting.

Frame layout on the NAS, with UTC names:

```
project_sunshine/<camera>/YYYY/MM/DD/<camera>_<UTC>.{jpg,json}   (+ _night.*, and _ev0.* / _ev-2.* at sunset)
```

`<camera>` is `cm4wide` (3.2 mm lens, from 2026-11-12) or `cm4city` (6 mm lens, from 2026-11-17).
`wide` holds the retired Pi 3's frames (to 2026-11-17).

Each `.json` holds the camera settings, a `Sun` block (azimuth, elevation, minutes from sunset), a
`Capture` block (how and why the frame was taken) and a `System` block (temperature, disk, checksums).
A `system.json` in each day folder holds what rarely changes.

## Current state

One CM4 (`sunshine`) runs two cameras: `cm4wide` (3.2 mm, the five-year series) and `cm4city`
(6 mm, downtown). Each takes a frame every 5 minutes, adds one a minute around sunset, and brackets
the sunset (ev+0 and ev-2). Frames sync to the NAS, and Home Assistant alerts on stale frames and
on the UPS. The real run starts on the winter solstice, 2026-12-21.

What is decided and current is in [`CLAUDE.md`](CLAUDE.md). Open work is in the
[issues](https://github.com/funvill/project-sunshine/issues). Every event and change, with dates,
is in [`changelog.md`](changelog.md).

## Layout

| Folder | What is in it | Read |
|---|---|---|
| `pi/` | Everything that runs on the Pi: capture, sync, metadata, sun position, the evening sky score for the good-sunset notification, self-test, diagnostics page with focus peaking, systemd units. Copied flat into `~/sunset` | [Pi setup guide](docs/setup.md) |
| `nas/` | The daily sunset video job (Python + ffmpeg), run on the PC by `tools/build_video.py`, and the camera's `crop.cm4wide.json` | [nas/README.md](nas/README.md) |
| `experiments/` | Pilot experiment runner and the hourly weather log. Not part of production capture | Issue #3 |
| `tools/` | PC-side helpers: `build_video.py` (builds one day's Instagram video and prints its sky score, no AI), `fuse_sunset.py` (merges the sunset bracket so the sunset isn't blown out), `issue_blur.py` (blurs the nearby buildings in images posted to issues), `fog_scan.py` (measures how clear each frame is, to find fog or condensation, #33; measuring only, no alert) | [Building a video](#building-a-days-video-by-hand) |
| `reports/` | A page of every day of the wide camera: the sunset point as a 100 px thumbnail, the sky score (with an SVG graph), frames taken and missed, the forecast at sunset, the Pi's health and the day's events. Made by `tools/build_reports.py`; can be a few weeks behind | [Reports](#reports) |
| `homeassistant/` | The stale-frame alert, copied into Home Assistant by hand | [Pi setup guide](docs/setup.md#home-assistant-alert) |
| `tests/` | Offline tests with a stubbed camera and NAS | Below |
| `docs/` | Pi setup guide and hardware notes | [hardware notes](docs/hardware/README.md) |

## Getting started

**To work on the code:** no Pi or NAS is needed. Run the tests:

```bash
bash tests/run.sh            # all; or name some: bash tests/run.sh 17_ dense test_ups
```

```bash
python3 tests/test_daily.py
```

```bash
python3 tests/test_fuse_sunset.py
```

They need bash, coreutils and Python 3. The video tests also need ffmpeg and are skipped without it.
Write a failing test first, then the change.

**To set up a Pi:** follow [docs/setup.md](docs/setup.md). Copy `pi/sunset.env.example` to
`~/sunset/sunset.env` and set the real site coordinates there. On the pilot Pi,
`./sunset-selftest.sh` checks the camera, clock, disk, memory, capture time, IR-cut filter and NAS.

**To run the daily video:** see [nas/README.md](nas/README.md). Build the image, then schedule it every
30 minutes through the afternoon and evening.

### Building a day's video by hand

`tools/build_video.py` builds one day's video on a PC, with no AI and no tokens. It runs the daily
job (`nas/sunset-daily.py`) for a chosen sunset date, reads the frames from the NAS share and posts nothing:

```bash
python tools/build_video.py --camera cm4wide --date 2026-11-17 --start 07:30 --redo --crop nas/crop.cm4wide.json --fuse-production
```

Set `SUNSET_NAS` once on the PC to the `project_sunshine` folder on the share (for example `//<nas-host>/camera/project_sunshine`; the host is kept out of this repo), or pass `--nas`. It needs ffmpeg, and numpy and OpenCV for `--fuse-production`. It prints the video path and the **sky score**
(0 to 100, from how much of the sky is lit warm around sunset; provisional, see
[nas/README.md](nas/README.md#sky-score)). `--start 07:30` starts at that local time, `--fuse-production` merges the sunset bracket (the
`_ev0`/`_ev-2` frames that `BRACKET=1` saves beside each sunset frame, #10) first and blends each sunset
minute with its neighbours (1:2:1, to calm the cloud flicker; `--no-blend` to skip it), and `--redo` builds a day again. Optional fixes, off unless asked for: `--dusk-gains R,B`
re-colours the frames after sunset as if shot with fixed colour gains (on `cm4wide` its night gains
`2.20,2.80`, which turn auto white balance's teal dusk blue), coming in over `--dusk-ramp` minutes (5,15);
`--deflicker MIN` steadies the brightness of the 1-a-minute frames area by area over that many minutes
either side (3 calmed Nov 12's glow from a 147-164-146 swing to 152-154). The merge fades out 5 to 12
minutes after sunset. Changing any of them on a day already built needs `--redo`. The Nov 12
video with both: `--dusk-gains 2.20,2.80 --deflicker 3`. The camera's `crop.json`
(calibration, tighter view, tower blur) is `nas/crop.cm4wide.json`.

### Reports

`reports/index.html` is rebuilt by `tools/build_reports.py`, with no AI, whenever the project is updated, so
it can be a few weeks behind. It reads the frames on the NAS (the `nas` line of the git-ignored
`tools/camera_check.hosts`, or `--frames`) and only redoes new days and the last two:

```bash
python tools/build_reports.py            # --camera cm4wide by default; --redo rebuilds every day
```

One row a day, newest first: a 100 x 100 thumbnail of the point where the sun meets the horizon, from the
frame nearest sunset whatever the weather (its column from the calibration in `nas/crop.cm4wide.json`, its
row from `HORIZON_Y` in the script, the tower blur applied first), the sky score by the NAS job's own
functions, the sunset time and bearing, frames taken and missed, the Open-Meteo forecast at sunset, the
Pi's health from the frames' `System` blocks, and the `**Event:**` entries of that day in `changelog.md`.
`reports/sky-scores.svg` is the score graph. A new camera position needs its horizon row added to
`HORIZON_Y`, or its days get no thumbnail. Open the page through a local server
(`python -m http.server --directory reports`) or a browser; GitHub shows HTML as source.

## Rules

- **Never commit frames, `sunset.env` or credentials.** The repo is public. `sunset.env` holds the
  real coordinates, and the NAS login lives only in a root-only file on the Pi.
- **Frame files carry no site coordinates**, in case they are ever published. The caption carries no
  coordinates or location either. The video itself shows the city and the view direction, at Steven's
  request (2026-11-13), and the near towers get a light blur.
- **Filenames are UTC.** The frame layout doesn't change.
- **Change `SETUP_ID` in `sunset.env`** whenever the camera, lens, focus, mount or hood changes.
- **Add a `changelog.md` entry with every change**, including changes made only on the Pi.
- **Commits by an AI agent** are authored as `SWS-Chipkin <sws-dev@chipkin.com>`.
- Capture-schedule and camera-setting changes on the Pi are production changes: ask the owner first.

## Hardware

Two cameras, both IMX477, on one CM4 on a MyPi board: `cm4wide`, an Arducam B0240E with a 3.2 mm lens
(about 93° estimated, likely wider; sold as 120°), and `cm4city`, an Arducam UC-517 with the Pi 6 mm CS lens.
Both sit loose behind the glass under a black foam hood. The plan for the real run is a 3D-printed keyed
mount stuck to the glass. Details and the shopping list are in `CLAUDE.md` and
[docs/hardware/README.md](docs/hardware/README.md).
