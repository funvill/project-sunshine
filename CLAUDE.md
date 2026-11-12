# Project Sunset — handoff for Claude Code

Five-year time-lapse of the western sky from Steven's 23rd-floor window in Burnaby, BC,
looking toward downtown Vancouver. **Sunset is the subject.** Start date: **winter solstice,
2026-12-21**. Pilot should run by late November 2026.

This file is the project brief. `docs/setup.md` is the Pi setup guide. `changelog.md` lists changes
by date: add an entry with every change, including changes made only on the Pi.

## Repo layout
- `pi/`: everything that runs on the Pi. Copied flat into `~/sunset`; the systemd units expect that path.
- `nas/`: the daily sunset video job, which runs on the NAS in Docker. See `nas/README.md`.
- `tests/`: offline tests with a stubbed camera and NAS. No Pi needed.
- `experiments/`: pilot experiment runner (#3). Not part of the production capture.
- `homeassistant/`: stale-frame alert, copied into Home Assistant by hand. Steps in `docs/setup.md`.
- `tools/`: PC-side helpers. `issue_blur.py` blurs and labels the nearby buildings in images posted
  to GitHub issues, and nothing else. Style 1 (light Gaussian) is the default, chosen by Steven 2026-11-09.
- `docs/`: setup guide and hardware notes.

Frames never go in this repo, and neither does `sunset.env`, which holds the real site coordinates.

## Owner context
- Steven: maker/hacker, CTO at a building-automation company. Comfortable with Linux,
  networking, Home Assistant, 3D printing. Prefers direct, technically precise answers and
  concrete deliverables; iterates and corrects incrementally.
- Has a NAS (plenty of space), Home Assistant, a UniFi router, and a 3D printer.
- Plans to stay at this address 5+ years. Budget ~CA$1,000 total.

## Site
- Window faces **due west** (confirmed). Double-glazed, doesn't open well.
- Shooting **through the glass from inside**. Deck has power but nothing to mount to; indoor chosen.
- Blinds stay open (plants nearby — also a humidity source for condensation).
- Tall tower on the right of the view blocks some summer sunsets. **Accepted**; it doubles as a
  fixed alignment reference.
- Sun sets near the downtown skyline in autumn. Downtown is ~10–12 km away; the far
  horizon mountains are 50 km+ (haze-limited).

### Sun geometry (approximate, from memory — verify before relying on it)
- Sunset azimuth ~233° (Dec solstice) to ~306° (Jun solstice): ~73° swing, centred on west.
  `sunset-sun.py` (NOAA equations, upper limb incl. refraction, ~49.25 N) gives **233.6°** and
  **308.8°**: a ~75° swing, so the wide camera needs ≥ ~80° H FOV with margin. Still a
  calculation, not a measurement: check it against the real sunset in the pilot.
- Wide camera needs ≥ ~75° horizontal FOV, ideally ~90°+ for margin.
- Magnetic declination in Vancouver ~16° E (phone compass must use true north).

## Decisions made
- Capture every **5 min, 24/7**, day and night (changed from 15 min on 2026-11-07 at Steven's
  request). Every frame keeps its DNG, and dark slots still add the night frame, so this is
  about 3x the data: an estimated 8-15 GB a day on the NAS, and a full SD card now holds about
  2-3 days if the NAS is down, not 10. `SLOT_S` in the experiment runner and the diag page must
  match the timer (a test checks it).
- **Dense frames around sunrise and sunset (decided 2026-11-07, starts 02:30 UTC 2026-11-09):**
  Steven chose 1 a minute after comparing daily videos at 15, 5, 3 and 1 min. Windows: sun at -9°
  to 60 min after sunrise, and 60 min before sunset to -9°. On top of the 5-min frames, in the same
  folder and names, JPEG + JSON only, same auto exposure, `Capture.schedule: "dense"`. The regular
  slot always wins the camera. `sunset-dense.timer`; details in `docs/setup.md`. About 230 extra
  frames a day in November, roughly 1 GB a day more on the NAS. The ×3 bracket is not done.
- **Post only the good sunsets to Instagram (decided 2026-11-11):** the daily video is still made
  every day, but only a day whose sky scores above a set value is posted. Most grey, overcast
  sunsets aren't worth showing. The score is deterministic image maths on the sunset frames (no AI,
  no tokens); see backlog #11. Until it exists and is tuned, nothing posts anyway (`POST_ENABLED=0`).
- **Two cameras eventually**: one wide (all sunsets), one tight (downtown or another subject).
- Hidden, compact setup. DSLR/mirrorless considered and set aside for size/visibility,
  though a used Sony a6300/a6400 tethered via gphoto2 remains the image-quality upgrade path.
- Save **RAW (DNG) + JPEG + per-frame metadata**. Filenames in **UTC**. Layout unchanged:
  `outbox/<cam>/YYYY/MM/DD/<cam>_<UTC>.{jpg,dng,json}` (+ `_night.*`). Frames are staged in
  `outbox/.partial/` and moved into place when complete; the sync ignores dot-directories.
- **Clock policy (decided in review, change if you disagree):** the Zero has no RTC. Capture
  refuses to run until NTP has synced once since boot (`SKIPPED` in `capture.log`, exit 1), then
  keeps going through later NTP outages. A gap is preferred to frames with a wrong UTC name.
  `REQUIRE_TIME_SYNC=0` turns it off. A DS3231 RTC would remove the gap after power cuts
  (not bought; your call).
- **Disk guard:** ≥85% full drops the DNG, ≥95% skips the night frame, <100 MB free skips the
  capture. All logged. Does not change the 5-min schedule.
- **Per-frame sun data:** each `.json` gets a `Sun` block (true-north azimuth, elevation, nearest
  sunset, minutes from sunset). Site coordinates live in `sunset.env` (`SITE_LAT`/`SITE_LON`,
  currently approximate Burnaby, **set the real ones**) and are deliberately NOT written into
  frame files, in case frames are ever published.
- **Per-frame `Capture` and `System` blocks, daily `system.json` (2026-11-04):** `sunset-meta.py`
  adds how the frame was taken and the machine's state at that moment, including image checksums,
  CPU temperature and disk space. What rarely changes (model, OS, kernel, versions, SD card, setup
  note) goes in one `system.json` in each UTC day folder, and `Capture.system_id` links the two.
  Frames before 20:15 UTC that day have no blocks; those from 20:15 to 21:30 UTC carry everything
  on the frame (`schema_version` 1). It never touches the NAS path, and it leaves out anything
  identifying (see `docs/setup.md`). **Change `SETUP_ID` in `sunset.env` whenever the camera, lens,
  focus, iris, mount or hood changes**, including at the bracket move.
- **Local-first storage**, rsync to NAS, delete local only after confirmed copy.
  (Writing straight to the NAS was rejected: a prior year-long Pi project lost frames when the
  NAS share didn't return after a power cut.)
- Monitoring: **Home Assistant alerts on the age of the newest file on the NAS** (> ~1 h).
- **Freeze recovery (2026-11-05):** `install.sh` sets systemd's hardware watchdog to 15 s, so a hard
  freeze should reboot the Pi, and the capture and sync timers come back by themselves. Tested with
  a deliberate kernel panic: back on the network in 44 s. A partial freeze that leaves systemd
  running won't trigger it, and a reboot clears any transient `exp-*` timers. `sunset-kernlog.service` keeps kernel
  messages in `~/sunset/kernel.log` (up to two 1 MB files), flushed per line, because system logs
  are in RAM and are lost on reboot.
- Freeze software once stable: pinned OS, no auto-updates, full SD image saved on the NAS.
- Mount: 3D printed in **PETG or ASA** (not PLA — sun heat), stuck to glass with **3M VHB**
  (no suction cups), **keyed two-part design** so a replacement camera returns to the same framing,
  **black foam hood sealed against the glass** to kill reflections, camera square to the glass.

## Current phase: pilot on a Pi 3 B+ (decision changed 2026-11-03)
- **Pilot moved from the Pi Zero W to a Pi 3 B+ Rev 1.3**, hostname `timelaps`, user `funvill`,
  because that is the setup where the UC-517 is known to work. Raspberry Pi OS Bookworm 32-bit
  (armv7l), not reflashed. On Ethernet and Wi-Fi. Clock zone is America/Vancouver (changed from America/Adak 2026-11-04;
  `tzdata` 2026c gives UTC-7 all year, shown as `MST`); filenames are UTC and nothing depends on the zone.
- **Camera: Arducam UC-517** in the CAMERA port, `camera_auto_detect=0` + `dtoverlay=imx477`
  (auto-detect does not find it). Manually focused on the distant view.
- 5-min captures, plus 1-a-minute dense frames around sunrise and sunset from the sunset of
  2026-11-09 (the scheduled 02:32 UTC start failed: a transient unit run as the normal user can't
  enable a timer; run such jobs as root).
- The Zero W path is no longer the target. The scripts have no Zero-specific code, but this camera
  has not been shown working on a Zero. See `docs/hardware/README.md`.
- **OS (2026-11-03):** upgraded to kernel 6.12.109, rpicam-apps 1.9.0, libcamera 0.5. Desktop and
  everything else not on `pi/keep-packages.txt` removed: 1,624 to 362 packages, 6.5 GB to 1.4 GB used.
  `sunset-lowwear.sh` applied. `cmdline.txt` had been empty for many boots (firmware defaults, no
  `fsck.repair`); it is now set. Kernels kept: v7 (this Pi) and v6 (Zero).
- **SD card:** a 32 GB card (ID `SH32G`, manufacturer ID 0x03, which is normally SanDisk, dated
  07/2021) with ~26 GB free, about 2-3 days of frames at 5-minute captures
  if the NAS is down (it was about 10 days at 15 minutes). Run a write test and replace with a High Endurance
  card for the real run (a buying decision).
- **SD writes, measured:** idle OS 584 KB per 10 min before `sunset-lowwear.sh`, 108 KB after
  (~16 MB/day). Each capture writes ~27 MB, ~52 MB with a night frame, so frames are an estimated
  ~2.5-5 GB/day and over 99% of all writes. **Decided 2026-11-03: frames stay SD-first** and are
  removed from the SD as soon as they are confirmed on the NAS, accepting that wear. Staging in RAM
  was rejected. Holding writes in RAM until the sync was tried and failed: the frame reached the SD
  in 3 of 3 captures.
- This Pi previously ran `~/capture_and_sync.sh` from cron (30-min frames to `~/Pictures`, NAS sync
  commented out; its newest frame before today was from 2025-05-27). That job is disabled in cron,
  not deleted. Its frames and the empty desktop folders in the home folder are gone. `~/readme.md`
  on the Pi explains what is there.
- **NAS:** SMB share `//chipkin_nas.local/camera`, folder `project_sunshine`, user `camera`, not
  rsync over SSH (decision changed 2026-11-03). Automounted at `/mnt/nas-camera` via `/etc/fstab`;
  login in the root-only `/etc/sunset-nas.cred` on the Pi (never in this repo). Guest login was
  refused by the NAS. `sunset-sync.sh` refuses to run if the share is missing or on the SD card.
- **Power (2026-11-03): undervoltage on `timelaps`, not fixed.** The Pi restart-looped until its USB
  cable was changed. With the replacement cable and the camera connected, the kernel still reported
  undervoltage three times in the first two minutes, with almost nothing running
  (`throttled=0x50005`). In the same period the shell lost `ls` and `sudo` and SSH failed, probably
  the SD card dropping out (unproven; those logs were in RAM).
- **New power supply (2026-11-08, about 05:40 UTC):** Steven replaced the supply (model and rating
  not recorded here). The last undervoltage warning was at 05:30 UTC, just before the swap; in the
  first 3.5 hours after it there were none (`throttled=0x80000`: only the soft temperature limit,
  no undervoltage bits). Keep watching for a few days before calling it fixed.
- **Freeze (2026-11-05):** `timelaps` froze at about 01:26 UTC during an experiment run: red light
  on, no green, no network, until a power-cycle at about 06:04 UTC. 19 production frames lost. Cause
  unproven because the logs were in RAM; undervoltage is the leading suspect, with 7 warnings in the
  first 7 minutes after the reboot. Not ruled out: a kernel or camera-stack bug.
- **Timers on (2026-11-04), before the new supply:** Steven's other tools read the frames on the NAS,
  so sync and capture are enabled despite the undervoltage. Expect possible gaps until it's fixed.
- **NAS space (2026-11-04):** the share reports 311 GB free of 11 TB (98% full). Steven can clear
  10 TB when needed and is handling it, so space doesn't limit the capture plan.
- **Experiments (#3):** `experiments/sunset-experiment.py`, copied to `~/sunset/experiments/`, shoots
  between the real captures. Results go to `project_sunshine_experiments/` on the NAS, never the outbox
  or the production folder. Scheduled by transient systemd timers (`exp-*`), which a reboot clears.
- **Camera outage (2026-11-05):** the camera stopped delivering frames at about 07:17 UTC, and
  41 production slots were lost. A driver reload, a reboot and a power-cycle didn't help; reseating
  the ribbon at both ends did. The reason it failed is unknown. The reseat moved the camera about
  1,400 px right, so `SETUP_ID` was `pilot-2`.
- **Refocus (2026-11-08, about 05:35 UTC):** Steven refocused using the diag page's focus peaking,
  during the same power-off as the supply swap. `SETUP_ID` is now `pilot-3` (set at 09:19 UTC, so
  frames from about 05:45 to 09:15 UTC still say `pilot-2`). Night frames are about 3x sharper by
  Laplacian variance on the city band (about 48 before, 155 after), and lit windows that were blobs
  now show their frames. The camera also turned: the skyline moved about 650 px left and 200 px up
  (about 10° to the right, same scale), measured by matching skyline patches across the refocus.
- **Nudged (2026-11-12, 00:11-00:18 UTC):** Steven moved both cameras, putting the CM4 at the window. The
  `timelaps` view shifted about 37 px left (≈ 0.6° to the right) by 00:18, with smaller nudges from
  00:11. `SETUP_ID` is now `pilot-4` (set at 00:33 UTC, so frames from 00:18 to 00:30 still say
  `pilot-3`). Experiment run `sunset-3` was running at the time.
- **Framing vs the sunset swing (estimate, 2026-11-08):** fitting skyline landmarks (downtown
  Vancouver, Oakridge) with known bearings gives a rectilinear lens of about 5.6 mm (f ≈ 3,630 px,
  ~58° horizontal). At `pilot-3` the frame spans about 239° to 298° true. Predicted: the sunset is
  out of frame on the left from about Nov 21 to Jan 19 (Dec solstice 233.7° is ~6° past the edge)
  and on the right from about May 7 to Aug 4 (June solstice 308.8° is ~11° past). The near towers
  hide it for about a week each around Feb 23-Mar 3 / Oct 10-18, Mar 9-18 / Sep 24-Oct 3 and
  Apr 28-May 6 / Aug 5-14. This lens cannot cover the 75° swing at any heading.
  **Measured on the first clear sunset (Nov 8):** the left edge is at about 238.4°, not 239.5°.
  The lens has some barrel distortion: near the edge the sun moves ~60 px per degree, where a
  rectilinear lens would give ~80. So the left gap is Nov 24-Jan 16 (Dec 21 still ~4.7° out). The
  right edge is not measured; if it gains the same, it is ~299°, with the gap ~May 12-Jul 30.
- **First clear sunset (Nov 8, experiment 5):** auto exposure blows 7-12% of the sky through the
  sunset, ev-2 keeps it (only the disc and its halo clip), and ev+2 adds nothing. Auto white
  balance pulls the glow towards blue (R/B 0.7 vs 1.4 for daylight). Proposed for Steven, not
  done: bracket {ev+0, ev-2} and fixed daylight white balance in the sunset window. Wants another
  clear sunset and an overcast one first.
- **Steven's ranking of the sunset options (2026-11-09, from the comparison page):** best E (ev+0 +
  ev-2 merged, daylight white balance), then B (ev-2 alone), then D (the merge, auto WB); worst F
  (daylight alone), A (today's frame), C (ev-1 alone). He prefers a held-back sky over a bright city.
  E was simulated, so experiment 19 (`sunset` program, `sunset-1` to `-6`, Nov 9-14) shoots the real
  inputs. No production change yet. The runner now keeps out of the first 12 s and last 3 s of every
  minute, so it can't take the camera from a dense frame.
  **Runs 1-2 (Nov 9-10, both overcast):** the real E, B and D held a bright cloud gap that clipped
  11% of the sky in A. But daylight white balance turns the sky brown from ~15 min after sunset,
  when the city lights the cloud (R/B up to 4.6). So E would hand over to auto, or to `NIGHT_AWB`, at
  about +10 min. Still needs a clear sunset (runs 3-6, Nov 11-14).
- **Settings search (decided 2026-11-05):** Steven asked for wide experiments over a few days and for
  me to choose the best settings for night, day, sunset and sunrise, posting the evidence on #3.
  Night is 4 s gain 1 (confirmed by the first night sweep, 2026-11-06), with fixed colour gains
  2.25/2.40 (`NIGHT_AWB`), which give a neutral grey sky. 2.07/2.28 left it green and auto white
  balance drifted through the night. Nights 2 and 3 can still change this. Focus was adjusted on
  2026-11-08 (`pilot-3`), so sharpness-dependent results from before then don't carry over. The foam hood is about 3 weeks away, so
  reflections get rechecked after that too.
- **Weather forecast (experiment 17, from 2026-11-09 00:22 UTC):** Steven asked about adapting
  settings to the weather. Plan agreed: record the forecast for at least two weeks first, then check
  whether it predicts which settings work, before it changes anything. `experiments/sunset-weather.py`
  runs hourly at :07 from `exp-weather.timer` (a unit file, not a transient timer, so it survives a
  reboot). It saves Open-Meteo forecast (best match and GEM) and air quality to
  `project_sunshine_experiments/weather/` on the NAS, requested with the position rounded to 0.1°
  and with no position saved. The likely end state: measured scene data sets exposure, and the
  forecast only decides when to bracket and when to expect condensation. A `Weather` block in
  frame files would be a production change (Steven's call).
- **Moon (experiment 18, estimate 2026-11-08):** at `pilot-3` the moon is in frame on about 41% of
  nights over the five years; 57% of moonsets fall inside the frame's bearings (low-precision moon
  calculation, not measured). `moon-1` to `moon-9` (transient timers, Nov 16-25) shoot a short-exposure
  ladder and a 1-a-minute track, for exposure, double-glazing ghosts (repeat after the hood), a
  night-time check of the field-of-view fit, and focus. Ideas left for Steven: a per-frame `Moon` block
  and 1-a-minute frames during full-moon sets (both production changes).
- **Reflections (checked 2026-11-12, LEDs on/off A/B at night):** on the CM4, the board's and the
  Wi-Fi dongle's LEDs show as green and red spots (doubled by the double glazing) in every frame, and
  a light in the room shows as a large amber glow on the left; the LED spots go with the LEDs off,
  the glow doesn't. On `timelaps`, the red power LED adds a faint red wash to the left sky.
  **Decided 2026-11-12: all LEDs off** with `pi/90-sunset-leds.rules` (udev, installed by
  `install.sh`), on both Pis. The CM4's spots are gone; they were the board's LEDs. The dongle's driver
  relights its own LEDs, but they don't show in the glass. The room-light glow needs the hood.
- **Camera position (decided 2026-11-05):** it sits loose on a shelf and can't be put back exactly, so
  testing continues from the new position until the new supply arrives.
- **Camera will move again** when the bracket and supply arrive: redo anything tied to framing, and
  change `SETUP_ID`.
- **Home Assistant alert (2026-11-05):** installed from `homeassistant/`. HA reads the NAS share
  directly at `/share/camera`, with its own copy of the `camera` login, and alerts about 70 to 75
  minutes after the last frame. The phone notifier is set only in HA's copy of `sunset.yaml`.
- **Not done yet:** confirming the new supply over several days, final mounting and framing, foam hood.
- **To do: heatsink on `timelaps` (2026-11-08).** SoC temperature at capture is 54.8 to 58.5 °C,
  and the Pi 3 B+ soft limit is 60 °C (`throttled=0x80000`: reached since boot). It runs close to
  the limit while experiments add load, and summer sun through the window will add more. On the
  sunny afternoon of Nov 8, with the diag stream running, it reached 61.8 °C and the soft limit was
  active (`0x80008`, CPU held at 1.2 GHz); captures were unaffected. A small
  stick-on heatsink is enough to start with (a buying decision, Steven's call).

### Pilot goals
1. Window reflections with the foam hood, day and night (double-glazing ghosts).
2. Night exposure: tune `NIGHT_LUX`, `NIGHT_SHUTTER_US`, `NIGHT_GAIN`.
3. Condensation on cold winter glass.
4. Pi performance: capture time, memory, Wi-Fi or Ethernet reliability. First results on the
   Pi 3 B+: ~7 s day shot and ~12 s night shot, each with DNG; DNG 24.8 MB.
5. NAS sync + Home Assistant alert end to end.
6. Confirm framing/FOV of the chosen lens against the sunset swing.

## Hardware inventory (on hand)
- **Raspberry Pi 3 Model B+ Rev 1.3** (`timelaps`), the pilot Pi. 1 GB. Has Ethernet.
- **Raspberry Pi Zero W v1.1** ×3 (spares; one was the original pilot). 512 MB, 2.4 GHz Wi-Fi only,
  ARMv6. No power LED, only the green activity LED.
- **Raspberry Pi 3 Model B v1.2** ×1 (HDMI + one USB port marked "X" — may be dead; fine headless).
  Planned for the sunset camera later (Ethernet, enough CPU for bursts).
- **Raspberry Pi 2 Model B** (on DIN bracket) — not recommended.
- **Raspberry Pi CM4 with 32 GB eMMC** (`lsblk` 29.1 GB, 2026-11-11; boot EEPROM dated 2023-01-11,
  newer than the 2021-07-06 the board vendor asks for) on an **Embedded Micro Technology MyPi Industrial IoT Integrator Board XT**
  (2026-11-09). Board: two 22-pin camera connectors, 9-28 V DC input, battery-backed DS1338 RTC
  (I2C 0x68, `dtoverlay=i2c-rtc,ds1307,addr=0x68`), 60 s external watchdog on GPIO16/17 (jumpers
  LK5-LK7), EMC2301 fan controller, Gigabit + 10/100 Ethernet, 2x USB 2.0, a microSD slot wired
  over USB, a mini PCIe slot wired over USB only (for a 4G modem), TPM, 28 GPIO on the IO slot,
  125 x 142 mm, -20 to +80 °C. No M.2 and no NVMe: PCIe is not used. The vendor's dual-camera
  notes use the legacy `dt-blob.bin` stack, but libcamera works without it (below). Moving the
  pilot to it is Steven's call.
  **Set up 2026-11-11 (on a desk, not at the window):** hostname `sunshine`, user `sunshine`, 8 GB
  RAM. Reflashed with Raspberry Pi OS Lite Bookworm 32-bit (armhf userland), which boots the 64-bit
  kernel 6.12.109-v8, so the self-test warns about the Zero path. rpicam-apps 1.9.0, libcamera 0.5.
  **No Wi-Fi: this CM4 is a model without wireless** (no antenna or U.FL socket on the module; LK2
  is open; the kernel reports `mmc1: Failed to initialize`). Ethernet only, unless a USB Wi-Fi
  adapter is added (a buying decision). `~/sunset` installed with `CAM_NAME=cm4wide` and `SETUP_ID=cm4-desk-1`, so its
  frames can't mix with `wide`. **Timers off, no NAS mount yet** (Steven makes `/etc/sunset-nas.cred`).
  The new Arducam IMX477 with the 3.2 mm lens is on **CAM0**: `dtoverlay=imx477,cam0`. Nothing
  answered on CAM1. The RTC works with `dtoverlay=i2c-rtc,ds1307,addr=0x68`, set from NTP once.
  Self-test 14 pass, 1 warn (64-bit kernel): day shot 4.3 s and night shot 6.2 s, each with DNG,
  against ~7 s and ~12 s on `timelaps`. Focus: the camera's C-to-CS adapter ring had to come off, and
  focus is set with the camera's (very stiff) back-focus ring, since the lens has no focus ring of its
  own. Rough focus done at the desk; final focus is at the window. The external watchdog isn't
  resetting the board (up >20 min), so LK5-LK7 don't need changing.
  Packages trimmed to the keep list (615 to 383), keeping the v7l/v8 kernels and USB Wi-Fi firmware
  (see `docs/setup.md`). `sunset-lowwear.sh` applied. NAS mounted as on `timelaps`, using a copy of its
  login file (copied Pi to Pi on 2026-11-11, never displayed). Frames sync to `project_sunshine/cm4wide/`;
  `timelaps` and the CM4 have separate HA alerts, so CM4 frames can't hide a `timelaps` outage.
  The RTC sets the clock at boot and the kernel writes NTP time back to it every 11 min, but **there
  is no coin cell in the RTC holder yet** (Steven will add one later), so it only keeps time through a
  reboot, not a power cut. Don't depend on it: capture keeps waiting for NTP (`REQUIRE_TIME_SYNC=1`). One test
  capture through `sunset-capture.service` (2026-11-11 23:44 UTC) went through cleanly and synced to
  `project_sunshine/cm4wide/`.
  **At the window from 2026-11-12 ~00:30 UTC** (`SETUP_ID=cm4-window-1`), on Wi-Fi through an old
  Buffalo 2.4 GHz USB dongle (192.168.3.60, about 2.4 Mbit/s to the NAS). **Capturing since
  2026-11-12 00:35 UTC** (Steven's go-ahead): the 5-minute, dense and sync timers, same schedule as
  `timelaps`. HA has a separate CM4 alert (`cm4wide`) from 2026-11-12, same 60-minute limit, also
  sent to the phone.
  **The camera is mounted upside down.** `ROTATION=180` in its `sunset.env` (new setting, 2026-11-12)
  makes rpicam flip the readout, so frames from **01:08 UTC** on are upright, DNG included, and say
  `rotation: 180` in `Capture.settings`. Frames from 00:35 to 01:07 UTC are upside down. `timelaps`
  still runs the previous capture script (no change for it: the setting defaults to 0). It points down more than `timelaps`: the horizon is about 44% from the top, with the
  street and the deck railing (lower left, out of focus) below. Focus is good: sharp in the centre and
  even left to right (no tilt), a little softer towards the edges.
  **Field of view, estimated by matching features against the 6 mm frame (not measured on the sun):**
  scale 0.534 in the centre, so f ≈ 1,940 px (≈ 3.0 mm). The CM4's centre is about 7° left of
  `timelaps`' centre, so roughly 262° true. A rectilinear lens with that f would span about 93°
  (≈ 216° to 308°); this lens is sold as 120° and has barrel distortion, so the real span is likely
  wider. That should cover the 233.6° to 308.8° sunset swing, but the right (June) end is tight on
  this estimate: measure it on clear sunsets.
- **Ordered 2026-11-09, due Nov 12 (Amazon.ca):** a second IMX477 camera, **Arducam B0240E**
  (sold by UCTRONICS, CAD 68.57; C/CS mount, 15-15 and 15-22 pin cables included; some buyers got
  a board marked UC-517, so check the marking and whether its IR filter is fixed or switches), and
  an **Arducam LN05101 3.2 mm CS lens** (CAD 62.62; F2.0 fixed iris, 1/1.7" format, Arducam says
  120° H on the IMX477, not measured; reviews say the focus ring is stiff until the locking post is
  loosened). Steven chose these over the official HQ camera, the Camera Module 3 Wide and a
  SainSmart 152° IMX708 module.
- **Arducam UC-517 Rev.D3** — IMX477 (same sensor as Pi HQ) with a switchable **IR-cut filter**.
  Keep IR-cut in day mode always; verify its state after power loss. Per Arducam's product
  page the filter is switched automatically by a photoresistor on the camera PCB, so there is no
  software state to read (a forum user wired GPIO after removing the photoresistor; unverified
  for this board). `sunset-selftest.sh` therefore judges it from image colour (heuristic). Has a
  22-pin connector, not the 15-pin one on the official HQ camera. Needs
  `camera_auto_detect=0` + `dtoverlay=imx477`. Known detection issues reported on Pi 3 + Bookworm 64-bit.
  **Currently fitted with the official Pi 6 mm CS lens** (Steven, 2026-11-08); the skyline fit gives
  about 5.6 mm and ~58° H, consistent with it. Too narrow for the sunset swing: see issue #4.
- **Pi HQ Camera lenses (Adafruit):** 6 mm wide (#4563, ~55° H) and 16 mm telephoto (#4562, ~22° H).
  Neither alone covers the 73° sunset swing. A ~3–4 mm CS lens (~90°) is the cheap fix.
  Unclear whether an official Pi HQ camera body is owned or only the UC-517.
- Cables: Pi Zero camera cable (Adafruit #3157, 22-pin — also fits Pi 5), standard 15-pin ribbon.
- SD cards: SanDisk Ultra 16 GB A1 (pilot), ADATA 32 GB (backup choice), Kingston SDCS 16 GB
  (spare/images), Kingston SDC10G2 16 GB (retire).
- **Wyze Cam v2** ×several — not for this project (no RAW/manual control). Possible Home Assistant
  cameras via Thingino firmware.
- Sony NEX-5 and Samsung NX200: rejected (no USB remote control, mechanical shutter only).

## Hardware plan for the real run (not yet bought)
Pi 5 prices are ~$250 due to the RAM shortage, so the plan shifted to reusing Pi 3/Zero:
- **Two-camera plan (decided 2026-11-09):** both cameras on the CM4 + MyPi XT board, both IMX477 so
  they share one set of settings. **Wide (sunset):** the new Arducam B0240E + 3.2 mm lens.
  **Tight (downtown):** the current camera + the 16 mm lens. Both 6 mm lenses become spares.
  Moving the pilot to the CM4 board, and when, is still Steven's call; it means a new `SETUP_ID`.
- **Sunset (wide) camera, earlier options:** IMX477 + ~3–4 mm lens on the **Pi 3**, or Camera Module 3 Wide (~102°).
  Upgrade path: used **Sony a6300** (has true silent/electronic shutter; must verify silent works
  over USB PC Remote with gphoto2) + wide lens (e.g. Sony 10–18 mm).
- **Tight (downtown) camera:** IMX477 + 16 mm lens on a **Pi Zero W** (~180 px/degree — best
  distant detail of any option considered).
- Sensors: SHT4x temp/humidity at the glass, TSL2591 lux sensor, MOSFET + dew-heater strip on GPIO.
- 64 GB High Endurance SD cards, small UPS, spare camera of each type, ND filter for the 16 mm lens.
- IP cameras considered: UniFi G6 Bullet (US$199, 1/1.8") and G6 Pro Bullet (US$479 / ~CA$685,
  1/1.2", 2.36× zoom, ~114°–45.5° H). Good as an always-on backup record, but no RAW and heavy
  processing. If used: disable IR and white LEDs (they reflect off the glass).

## Risks and mitigations
| Risk | Mitigation |
|---|---|
| Silent failure | HA alert on newest NAS file age; `capture.log` on the Pi |
| NAS/Wi-Fi outage | Local-first capture, rsync catch-up |
| Condensation | Humidity sensor, low-contrast "fog" frame detection, dew heater |
| Software rot | Frozen OS image on NAS |
| SD wear | `sunset-lowwear.sh` for OS writes; High Endurance card for the real run; frames are the main wear |
| Bumps when watering plants | Keyed mount, post-alignment against the tower |
| Sun damage on telephoto | Skip/short-expose frames when the sun is in the 16 mm FOV; ND filter |
| Heat | PETG/ASA mount, temperature logging |

## Backlog for Claude Code
1. ~~Disk-space guard~~ **Done** (`sunset-capture.sh`, tested in `tests/`).
2. ~~Sun-position module~~ **Done**: `sunset-sun.py` (stdlib NOAA formula, no network). Writes the
   `Sun` block per frame; `sunset-sun.py sunset [--epoch|--json]` gives the next sunset for burst
   scheduling (backlog #3).
3. **Sunset burst mode**: 1/min done (dense frames, from 2026-11-09). The 3-shot bracket is not.
4. **Sensor protection** for the telephoto camera based on sun azimuth vs. its FOV.
5. **Fog detection**: flag low-contrast frames.
6. Port capture to **Picamera2** if finer control is needed than `rpicam-still` gives.
7. SHT4x + TSL2591 logging.
8. ~~Home Assistant config for the stale-file alert~~ **Done** (`homeassistant/`, steps in `docs/setup.md`).
9. Mount design: start from Printables model 250692 or design a keyed plate + foam hood.
10. Post-processing pipeline: deflicker, stabilisation, "sunset along the horizon" sequence
    (frame nearest each sunset), time slices, sky calendar.

11. **Sky score to pick sunsets worth posting. TODO once there are more good sunsets (needs
    more than the one clear sunset so far, Nov 8, to set thresholds).** A deterministic score per day,
    no AI: take the best frame in the window from 35 min before to 25 min after sunset, look at the sky
    above the skyline, and compute the warm-sky fraction (bright pixels with red clearly above blue),
    plus the luminance spread, maybe a cloud-texture measure. Saturation is useless (blue overcast is
    also saturated). First try on Nov 4-10 frames: warm fraction 0.041 on the clear Nov 8 sunset vs
    0.001-0.013 on every other day. Plan: a tested helper in `nas/` that writes a `sky` block (score
    and label: clear and colourful / partly cloudy / overcast) into each daily record; the publisher
    posts only days above a threshold set by Steven. Needs a fixed mask for the near towers, and a
    recheck after any lens or camera change.

## Creative outputs (later)
- Long time-lapse video (deflicker + stabilise).
- **Key piece:** the sun swinging along the horizon between solstices, frame nearest each sunset.
- Time slices (straight, curved, radial). Sky calendar (row = day, column = time of day).
- Data overlays from temp/humidity/lux logs plus historical weather pulled later.
- Prior art: Eirik Solheim (year in one image), Dan Marker-Moore, Richard Silver, Fong Qi Wei,
  Miska Knapek (slit-scan), Wendy Liu (Python/ImageMagick time slices),
  github.com/pconwell/rpi-long-timelapse (year-long Pi run lessons).

## Testing
`bash tests/run.sh` (offline, stubbed camera/NAS) and `python3 tests/test_sun.py`.
`tests/test_daily.py` covers the NAS job; its encoding tests use the real ffmpeg and are skipped
without it. On the Pi,
`./sunset-selftest.sh` checks camera, clock, disk, memory, capture time, IR-cut and NAS.
Its thresholds (30 s slow capture, 60 MB low memory, R/G 1.25 for IR-cut) are estimates to tune
from pilot data.

## Unverified numbers
Sunset azimuths, magnetic declination, lens FOVs and per-frame sizes above were estimated, not
measured. Confirm during the pilot before printing the mount or buying lenses.

## Related
- A project doc also exists as a Claude Docs artifact titled "Project Sunset" (overview + shopping list).
