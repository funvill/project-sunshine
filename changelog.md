# Changelog

Changes to Project Sunset by date, newest first. Dates are Vancouver local time. Entries marked **Pi** were made on the pilot Pi (`timelaps`) and may have no commit of their own. Decisions and their reasons are in `CLAUDE.md`.

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
