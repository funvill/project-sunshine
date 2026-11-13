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
   Instagram. It posts nothing yet. Only good sunsets will be posted: a deterministic sky score
   (0 to 100, no AI) rates each day and is in its record; the threshold is Steven's to set and the
   publisher is not written. You can build any day's video on a PC with `tools/build_video.py`
   ([how](#building-a-days-video-by-hand)).

Frame layout on the NAS, with UTC names:

```
project_sunshine/<camera>/YYYY/MM/DD/<camera>_<UTC>.{jpg,dng,json}   (+ <camera>_<UTC>_night.*)
```

`<camera>` is `wide` (Pi 3 B+ with the 6 mm lens) or `cm4wide` (CM4 with the 3.2 mm lens, since 2026-11-11).

Each `.json` holds the camera settings, a `Sun` block (azimuth, elevation, minutes from sunset), a
`Capture` block (how and why the frame was taken) and a `System` block (temperature, disk, checksums).
A `system.json` in each day folder holds what rarely changes.

## Current state (2026-11-13)

| Part | State |
|---|---|
| Capture, two cameras | Running: `wide` (Pi 3 B+, 6 mm lens) and `cm4wide` (CM4, 3.2 mm lens), 5-minute frames plus 1-a-minute frames at sunrise and sunset |
| Sync to the NAS | Running |
| Home Assistant alert | Installed and working |
| Daily video job | Tested on real frames from a PC; **never run on the NAS**, the Docker image has never been built. Changes since 2026-11-12 (committed 2026-11-13): tighter crop (`view`), tower blur, 07:30 start, location text, sky score, `FUSED_DIR`, `tools/build_video.py`, `tools/fuse_sunset.py` |
| Sunset video quality | **Not good enough to post.** The Nov 12 `cm4wide` video still flickers around sunset (about 15 to 20 min before). See "Next steps" |
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
- **Sunset flicker (blocks posting).** Between about 00:12 and 00:19 UTC on Nov 12 the sun and its glow
  brighten and dim minute to minute, in the raw frames too. Not a camera shift, not missing frames.
- **Few clear sunsets.** Nov 8 and Nov 12 were the good ones. The 9° dusk cut-off, the `cm4wide`
  calibration and the tower blur boxes haven't been checked on a clear sunset yet.

## Next steps (from 2026-11-13)

1. **Fix the sunset flicker** before anything posts. The full notes, questions and ideas are in
   `CLAUDE.md` under "Next session". Start by measuring it (a flicker number printed by
   `tools/build_video.py`) and by plotting each frame's exposure, gain and Lux from its JSON against the
   sun's brightness, to tell cloud from auto-exposure hunting. Compare with the Nov 13 and Nov 14 sunsets
   (experiments `cm4-sunset-2`/`-3`, `sunset-5`/`-6`).
2. **Look at the 7-minute hole** in the sunset bracket at 00:19 to 00:25 UTC on Nov 12 (runner log on the CM4).
3. **Commit the video work** (see git status below) on a branch, and put `nas/crop.cm4wide.json` on the NAS
   as `daily/crop.json` when the NAS job is set up.
4. **Steven's calls:** the sky score threshold for posting; Instagram login and public posting (issue #2);
   DNG yes or no (issue #5); a production sunset bracket (backlog #3), which removes the dependency on
   experiment frames for the merged exposure.
5. **Later:** build the Docker image and run the job on the NAS, the publisher, the heatsink and the final
   mount, hood and wide-lens decisions.

Uncommitted at the time of writing: the video work above, plus the Pi network watchdog (`pi/sunset-netwatch.*`,
`tests/cases/66_netwatch.sh`, the stubs it uses), `docs/setup.md` and `pi/install.sh` edits.

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
| `tools/` | PC-side helpers: `build_video.py` (builds one day's Instagram video and prints its sky score, no AI), `fuse_sunset.py` (merges the sunset bracket so the sunset isn't blown out), `issue_blur.py` (blurs the nearby buildings in images posted to issues) | [Building a video](#building-a-days-video-by-hand) |
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

`tools/build_video.py` builds one day's video on a PC, with no AI and no tokens. It runs the same
job as the NAS for a chosen sunset date, reads the frames from the NAS share and posts nothing:

```bash
python tools/build_video.py --camera cm4wide --date 2026-11-12 --start 07:30 --redo --crop nas/crop.cm4wide.json --fuse-run cm4-sunset-1
```

It needs ffmpeg, and numpy and OpenCV for `--fuse-run`. It prints the video path and the **sky score**
(0 to 100, from how much of the sky is lit warm around sunset; provisional, see
[nas/README.md](nas/README.md#sky-score)). `--start 07:30` starts at that local time, `--fuse-run` merges
that experiment run's sunset bracket first, and `--redo` builds a day again. The camera's `crop.json`
(calibration, tighter view, tower blur) is `nas/crop.cm4wide.json`.

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

Two cameras, both IMX477: `wide` is a Raspberry Pi 3 B+ (`timelaps`) with an Arducam UC-517 and the Pi
6 mm CS lens, and `cm4wide` is a CM4 on a MyPi board with an Arducam B0240E and a 3.2 mm lens (about 94°
on the lens model, much wider), both loose behind the glass. The plan for the real run is a 3D-printed
keyed mount stuck to the glass, a black foam hood against reflections, and the CM4 camera as the wide
sunset camera with the other as the tighter downtown one. Details and the shopping list are in `CLAUDE.md` and
[docs/hardware/README.md](docs/hardware/README.md).
