# Changelog

Changes to Project Sunset by date, newest first. Dates are Vancouver local time. Entries marked **Pi** were made on the pilot Pi (`timelaps`) and may have no commit of their own. Decisions and their reasons are in `CLAUDE.md`.

## 2026-11-09

### Capture
- **Pi:** the dense frames never started. The one-off job meant to switch on `sunset-dense.timer` at 7:32 pm Nov 8 (02:32 UTC Nov 9) ran as the normal user and was refused ("Interactive authentication required"), so the sunrise window on Nov 9 got no 1-a-minute frames. Switched on by hand at 10:12 am (17:12 UTC); the first check ran cleanly, and the first dense window is the sunset on Nov 9 from about 4:38 pm.

### Experiments
- Analysed the first clear sunset (Nov 8, `day-5`), with results on #3 and #4. The sun enters the frame at about 238.4°, 1° further left than the landmark estimate, because the lens has some barrel distortion. The sunset is off the left edge from Nov 24 to Jan 16 instead of Nov 21 to Jan 19. Auto exposure blows 7-12% of the sky through the sunset; ev-2 recovers almost all of it, and ev+2 adds nothing. Auto white balance pulls the sunset towards blue, and daylight white balance keeps it warm. Nothing changed in production.
- Steven ranked the sunset options from the comparison page: best E (ev+0 and ev-2 merged, daylight white balance), then B (ev-2 alone), then D; worst F, A and C. Added a `sunset` program to the experiment runner (experiment 19) that shoots the real inputs for E, B and D every minute from 45 minutes before sunset to 45 minutes after, plus ev-3 and the direct-sun shots every 5 minutes.
- The experiment runner no longer starts a shot in the first 12 seconds of a minute or one that would run into the next minute, and treats a running dense capture as the camera being busy. Before this, an experiment shot at the end of a minute could have made that minute's dense frame skip itself.
- **Pi:** deployed, and scheduled `sunset-1` to `sunset-6` for the sunsets of Nov 9 to Nov 14 (from about 4:51 pm each day). They are transient timers, so a reboot clears them.

## 2026-11-08

### Daily video
- `EXPECTED_FRAMES` now defaults to 288, the regular frames in a day at 5-minute capture. At 96 the too-few-frames check would have passed a day that lost two thirds of its frames. Test added.
- `nas/README.md` gives the video length for 5-minute plus 1-minute frames (about 40 to 45 s a day, estimated) instead of the 15-minute figures.

### Docs
- Rewrote `README.md` as a handoff: how the parts fit, current state, known problems, open issues, where to start and the rules.

### Experiments
- The experiment runner now keeps taking the fixed 100 µs and 500 µs direct-sun shots (experiment 7) every 5 minutes inside the 45 minutes before sunset, until sunset. At the `pilot-3` framing the sun only enters the frame in that window. **Pi:** deployed, and `day-5` restarted on it into the same folder.
- **Pi:** `stream-day-3` repeated the daylight diag handover test (experiment 8) on the 5-minute schedule.
- Experiment 10 (deflicker prototype) and experiment 11 (timing, power and storage) were run on the PC from logged data, with results on #3. Nothing changed in production.
- Added experiment 17, `experiments/sunset-weather.py`: once an hour it saves Open-Meteo's forecast (cloud layers, visibility, humidity, sunlight, from two models) and air quality, to check later whether the forecast predicts the right camera settings. The request uses the site position rounded to 0.1°, and the saved files have no position in them. Results go to `project_sunshine_experiments/weather/` on the NAS. Capture doesn't depend on it. **Pi:** installed `exp-weather.timer` as a unit file at 5:22 pm (00:22 UTC Nov 9), so it survives a reboot; first fetch saved and copied.
- Added a `moon` program to the experiment runner (experiment 18): while the moon is in frame, a 50 µs to 4 ms ladder at gain 1 with daylight white balance the minute after each capture (DNG kept at 250 µs and 1 ms), and one 1 ms shot in each other minute to track its position. Plan and the reasons are on #3. **Pi:** deployed, with a 4-minute test run at 7:40 pm (02:40 UTC Nov 9) and nine runs, `moon-1` to `moon-9`, on the passes from Nov 16 to Nov 25, each ending before the dawn dense frames. They are transient timers, so a reboot clears them.

### Capture
- Added a test that the disk guard also stops the 1-a-minute dense frames when the SD card is nearly full. The guard itself (85% drops the DNG, 95% skips the night frame, under 100 MB free skips the capture) was already in place.

### To do
- A heatsink for `timelaps`: the SoC runs at 55 to 60 °C at capture, against the Pi 3 B+ soft limit of 60 °C (added to `CLAUDE.md`).

## 2026-11-07

### Hardware
- **Pi:** Steven refocused the lens and replaced the power supply at about 10:35 pm (05:35 UTC Nov 8). `SETUP_ID` changed from `pilot-2` to `pilot-3` in `sunset.env` (at 2:19 am Nov 8, so frames in between still say `pilot-2`). Night frames are about 3x sharper. The camera also turned about 10° right: the skyline moved about 650 px left and 200 px up. No undervoltage warnings in the first 3.5 hours on the new supply.
- Estimated the frame's bearings from skyline landmarks: about 239° to 298° true with a ~5.6 mm lens, so the Dec 21 sunset (233.7°) is about 6° out of frame on the left and the Jun 21 sunset (308.8°) about 11° out on the right. Not yet checked against a real sunset. Opened issue #4 about it. **Pi:** `SETUP_NOTE` now names the official Pi 6 mm CS lens instead of an unlabelled one.

### Schedule
- Regular frames are now taken every 5 minutes instead of every 15, at Steven's request, still with the DNG and the night frame when dark. That is about 3x the data on the NAS. The experiment runner and the diag page now leave the camera free on the 5-minute slots, and the runner's hourly day sweep moved from :20 to :21 past the hour, and its 5- and 10-minute extras to the minute after a slot, so they don't land on a slot. **Pi:** timer changed and the running experiment restarted on the new code.

### Capture and metadata
- Added dense frames: one a minute from the sun at -9° until 60 minutes after sunrise, and from 60 minutes before sunset until the sun is at -9°, on top of the 15-minute frames. Steven chose 1 a minute from the daily-video comparison. JPEG and JSON only, with the regular frame's auto exposure, marked `Capture.schedule: "dense"`. The regular frame always gets the camera first. Run by `sunset-dense.timer`.
- Each frame's `Capture` block now has `schedule`: `regular` or `dense`.
- `sunset-sun.py` now works out sunrise, using the same sun height as sunset, and has a `dense` command that says whether a time is in a dense window.

### Diagnostics
- The diag page now has focus peaking: sharp edges painted over the live view, with sensitivity and colour settings and the share of the image outlined. It also has a graph of the last minute of sharpness, and the focus view can be pointed anywhere by clicking the full frame, not just the centre. **Pi:** installed and the page restarted.

### Daily video
- Removed the 1.5 s hold on the frame closest to sunset. With 1-minute frames around sunset, the slow-down already gives it time, and the hold looked like a stall. A 15-minute day's video is now 8 s.
- Moved the title and timestamp down so the timestamp ends 140 px above the bottom edge of the video, at Steven's request, accepting that Instagram's caption may cover them.
- Each frame of the daily video now shows its local time (`2026-Nov-06 16:45`) at the bottom left, with "Project Sunshine   @FUNVILL" above it, placed clear of Instagram's caption and buttons. The Docker image now installs a font for it (`font-dejavu`), and `FONT_FILE` can point to another one.
- The daily video's ffmpeg filters now go in a file instead of on the command line. With one timestamp per frame, a day of 1-minute frames would not fit on a command line.
- Fixed two degree signs in `nas/README.md` that were saved as Latin-1 instead of UTF-8.

## 2026-11-06

### Capture and metadata
- Night colour gains are now 2.25/2.40 instead of 2.07/2.28, which left the sky green. Chosen from the first night sweep (experiment 14), which also confirmed 4 s at gain 1. **Pi:** set in `sunset.env`.

## 2026-11-05

### Monitoring
- Added a Home Assistant alert for when no new production frame has reached the NAS for an hour (`homeassistant/`, steps in `docs/setup.md`).
- **Home Assistant:** installed the alert. Connected the NAS share as `camera`, added the File editor add-on and turned on packages in `configuration.yaml`. Tested by lowering the limit to 1 minute: the alert fired at 11:32 am.

### Capture and metadata
- Night frame is now 4 s at gain 1 with colour gains 2.07/2.28, instead of 8 s at gain 4 with 1.6/1.8, which was washing out. The gains are now a setting, `NIGHT_AWB`. This is the best result so far and may change when the settings search finishes. **Pi:** set in `sunset.env`.

### Experiments
- Added a settings search to the experiment runner: a night sweep every 2 hours that covers every setting across a range (experiment 14, 152 shots), an hourly day sweep (15), and sunset and sunrise settings with a dawn exposure ladder (16).
- The experiment runner now leaves the camera alone for 30 minutes after 3 failed shots in a row, then tries one shot. Before this, it kept retrying a dead camera and held it during real capture slots.

### Reliability
- **Pi:** the camera stopped sending frames at 12:16 am. Production captures failed from 12:30 am. A driver reload, a reboot and a power-cycle did not fix it. The sensor still answers on its control bus.
- **Pi:** reseating the ribbon cable at both ends brought the camera back. The first good frame was at 10:36 am. Production slots from 12:30 am to 10:30 am were missed, 41 frames.
- **Pi:** the camera now points about 1,400 px to the right of where it did before the reseat, so `SETUP_ID` is now `pilot-2`. It sits loose on a shelf and can't be put back exactly, so testing continues from this position until the new supply arrives.
- **Pi:** stopped the day-2 experiment during the outage, then restarted it and rebuilt the other experiment timers once the camera worked.

## 2026-11-04

### Capture and metadata
- Added per-frame `Capture` and `System` blocks to each frame's `.json`, and a daily `system.json` in each UTC day folder for what rarely changes.
- **Pi:** set the clock zone to America/Vancouver. Filenames stay in UTC.
- **Pi:** turned the capture and sync timers on before the new power supply arrives, because other tools read the frames on the NAS.

### Diagnostics
- `diag` full view now shows the whole sensor.

### Experiments
- Added the pilot experiment runner, `experiments/sunset-experiment.py`. Its results go to their own NAS folder, separate from production frames.
- Added a dusk exposure ladder to the day program (experiment 13).

### Reliability
- `install.sh` now sets a 15 s hardware watchdog, so a hard freeze should reboot the Pi. Tested with a deliberate kernel panic: back on the network in 44 s.
- Added `sunset-kernlog.service`, which keeps kernel messages in `~/sunset/kernel.log` on the SD card.
- **Pi:** the Pi froze at 6:26 pm and needed a power-cycle at about 11:04 pm, losing 19 production frames. The cause is unproven; undervoltage is the leading suspect. The watchdog and kernel log were added in response.

### Docs
- Brought `CLAUDE.md` up to date with the pilot Pi.

## 2026-11-03

### Pilot hardware
- Moved the pilot from the Pi Zero W to the Pi 3 B+ (`timelaps`).
- Recorded the first UC-517 detection on a Pi 3 B+, the first real image and capture time, and focused test frame results.
- Added hardware notes on the UC-517, then corrected the cable orientation notes and the supply rating.
- Recorded the undervoltage on the pilot Pi.
- **Pi:** upgraded the OS and removed the desktop and other unneeded packages.

### Capture and sync
- Sync now refuses to run against a share that isn't mounted.
- Documented the SMB share as the pilot's NAS path.
- Made the capture service's 300 s timeout take effect.
- Added `sunset-focus.py`, a focus meter for setting the lens.
- Added `sunset-lowwear.sh` to cut SD card writes from the OS.
- Recorded the decision to keep frames SD-first.

### Diagnostics
- Added the diagnostics page: Pi health data, the live camera stream, the `diag` command and its service.
- Documented it in the setup guide.
- Removed the access key from the page.
- Fixed how the page reads the next capture time.

### Repo
- Laid out the repo as `pi/`, `tests/` and `docs/`, and added a top-level README.
- Stopped tracking compiled Python, and ignored `sunset.env`.
- Kept `keep-packages.txt` in LF line endings.
- Fixed a test failure that only appeared from a long clone path.
- Noted the tidied home folder on the pilot Pi.

## 2026-11-02

- Imported the project brief and the Pi Zero pilot scripts.
- Fixed capture and sync edge cases found in review, and added offline tests.
- Added a disk-space guard to capture.
- Added offline sun position and sunset time.
- Added a Pi self-test script, and documented safeguards and decisions.
- Recorded the pilot hostname.
- Made paths user-agnostic, and added `install.sh` for the systemd units.
