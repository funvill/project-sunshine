# Project Sunset — handoff for Claude Code

Five-year time-lapse of the western sky from Steven's 23rd-floor window in Burnaby, BC,
looking toward downtown Vancouver. **Sunset is the subject.** Start date: **winter solstice,
2026-12-21**. Until then a pilot tunes the cameras, the sync and the video.

This file is the project brief: **the current state and the decisions in force, nothing else**
(Steven, 2026-11-22). History, measurements and the reasons behind old choices go in `changelog.md`;
when something here changes, replace the line and record the change there. `docs/setup.md` is the Pi
setup guide, `docs/hardware/README.md` the hardware notes.

**`changelog.md` is the whole project history** (decided by Steven, 2026-11-15). Over five years it is the
one place that explains every gap, jump or change in the footage, so record both:
- **Changes:** code, settings, hardware, mounts, `SETUP_ID`, including changes made only on a Pi.
- **Events:** anything that affects the record. For example:
  - power cuts, reboots, freezes and outages (camera, Wi-Fi, NAS), with the frames lost
  - undervoltage or heat
  - camera bumps and moves
  - weather that matters: storms, smoke, snow, fog, condensation on the glass
  - notably good sunsets (with the sky score)
  - solstices and equinoxes
  - the moon or other sky events in frame
  - the start of the real run (2026-12-21)
  - milestones such as a year of frames

Give times in UTC and Vancouver. Add the entry when it happens, or as soon as it is found. The brief as it
was before 2026-11-22, with the pilot's early history, is the last section of `changelog.md`.

## Repo layout
- `pi/`: everything that runs on the Pi. Copied flat into `~/sunset`; the systemd units expect that path.
- `nas/`: `sunset-daily.py`, which makes a day's video and sky score, and the camera's `crop.cm4wide.json`.
  It runs on the PC from `tools/build_video.py` (it was never scheduled on the NAS). See `nas/README.md`.
- `tests/`: offline tests with a stubbed camera and NAS. No Pi needed.
- `experiments/`: the experiment runner (#3; moon, dark, flat and checker programs) and the hourly weather
  log. Not part of the production capture.
- `homeassistant/`: the alerts, copied into Home Assistant by hand. Steps in `docs/setup.md`.
- `tools/` (PC-side, no AI):
  - `build_video.py` builds one day's Instagram video, prints the sky score, posts nothing (command in `README.md`).
  - `fuse_sunset.py` merges the sunset bracket (ev+0 and ev-2) into the frames the video uses.
  - `camera_check.py` is the read-only health check behind the `camera-check` skill (use it when Steven asks
    to check the camera; hosts and NAS path in the git-ignored `tools/camera_check.hosts`).
  - `build_reports.py` rebuilds `reports/`: one row a day with a 100 px thumbnail of the sunset point, the sky
    score and its graph, frames, forecast, Pi health and changelog events. Run it whenever the project is
    updated (Steven, 2026-11-18); it may lag a few weeks. A new `SETUP_ID` needs its horizon row in `HORIZON_Y`.
  - `fog_scan.py` measures each frame's clarity against its time-of-day baseline (fog, condensation, #33; no alert).
  - `issue_blur.py` blurs and labels the nearby buildings in images posted to GitHub issues, and nothing else,
    using the blur boxes in the camera's crop config. Style 1 (light Gaussian) is the default (Steven, 2026-11-09).
  - `frames.py`: the frame-name helper the tools share.
- `docs/`: setup guide and hardware notes.

Frames never go in this repo, and neither does `sunset.env`, which holds the real site coordinates.
The one exception is `reports/thumbs/`: 100 x 100 crops of the sunset point, tower blur applied, no metadata
(Steven asked for them, 2026-11-18).

## Owner context
- Steven: maker/hacker, CTO at a building-automation company. Comfortable with Linux,
  networking, Home Assistant, 3D printing. Prefers direct, technically precise answers and
  concrete deliverables; iterates and corrects incrementally.
- Has a NAS (plenty of space), Home Assistant, a UniFi router, and a 3D printer.
- Plans to stay at this address 5+ years. Budget ~CA$1,000 total.

## Site
- Window faces **due west**. Double-glazed, doesn't open well. Shooting **through the glass from inside**.
- Blinds stay open (plants nearby — also a humidity source for condensation).
- Tall tower on the right of the view blocks some summer sunsets. **Accepted**; it doubles as a
  fixed alignment reference.
- Downtown is ~10–12 km away; the far horizon mountains are 50 km+ (haze-limited).
- Sunset azimuth, from `sunset-sun.py` (NOAA equations, upper limb incl. refraction): **233.6°** at the
  December solstice to **308.8°** in June, a ~75° swing. A calculation: check it against real sunsets.
- Magnetic declination in Vancouver ~16° E (phone compass must use true north).

## The system now
- **One Pi: a CM4 (`sunshine`, user `sunshine`, 8 GB, 32 GB eMMC) on a MyPi Industrial IoT Integrator
  Board XT**, Raspberry Pi OS Lite Bookworm 32-bit userland on the 64-bit kernel 6.12.109, rpicam-apps 1.9.0.
  **On wired Ethernet for good from 2026-11-24 05:11 UTC** (`eth0`, 1 Gbps, the default route and the NAS);
  the AIC8800D80 USB Wi-Fi dongle on 5 GHz (out-of-tree driver, `docs/setup.md`) stays up as a fallback
  route. Addresses only in `tools/camera_check.hosts`, whose `key=` word lets the Wi-Fi address use the
  wired one's host key.
- **Two cameras, both IMX477, chosen by port ID** (`CAMERA=i2c@0` / `i2c@1`; with both ports on, rpicam
  calls CAM1 camera 0; `install.sh --cm4-two` writes both overlays):
  - **CAM0 `cm4wide`, the official five-year series:** Arducam B0240E with the 3.2 mm lens, upright
    (`ROTATION=0`), centre about 272°, `SETUP_ID=cm4-window-4`. Calibrated on the sun's disc
    (`nas/crop.cm4wide.json`, f 1,880 px).
  - **CAM1 `cm4city`, the detailed downtown view:** Arducam UC-517 with the 6 mm lens, about 281°,
    `SETUP_ID=cm4city-window-2`, settings from `~/sunset/sunset2.env` over `sunset.env`. The 16 mm lens
    can't reach infinity (most likely the 5 mm C-to-CS spacer is missing).
  - Both loose behind the glass with the **foam hood fitted** (Nov 20). The keyed mount is waiting on
    Steven's 3D printer (#35).
- **Capture:** a frame every **5 minutes, 24/7**, plus **1 a minute from 60 min before sunset to the
  sun at -9°** (`Capture.schedule: "dense"`). Each camera has its own capture and dense timers,
  `cm4city` (`sunset-capture2`/`sunset-dense2`) 30 s after `cm4wide`, sharing the capture lock. (One
  combined run, `cm4city` straight after `cm4wide`, made `cm4wide` fail about one slot in three; rolled
  back 2026-11-23.) Dark slots add a long night frame (`_night`;
  `cm4wide`: `NIGHT_SHUTTER_US=8000000`, gain 1, `NIGHT_AWB=2.20,2.80`). **JPEG + JSON only**, no DNGs
  (Steven, 2026-11-16; the DNG code was removed 2026-11-22). About 3.3 GB a day for both cameras.
- **Sunset bracket (option E), kept (Steven, 2026-11-22):** `BRACKET=1` adds ev+0 and ev-2 after every frame
  within 45 min of sunset (`<frame>_ev0.*`, `_ev-2.*`, `Capture.kind` `bracket`), with daylight white balance
  to +10 min. `fuse_sunset.py` merges them (`build_video.py --fuse-production`), with a 1:2:1 blend of
  neighbouring minutes against cloud flicker.
- **Settings freeze Dec 14**, with a `PROFILE_ID` in `Capture`.
- **Frame files:** `outbox/<cam>/YYYY/MM/DD/<cam>_<UTC>.{jpg,json}` (+ `_night.*`, `_ev0.*`, `_ev-2.*`),
  filenames in **UTC**, staged in `outbox/.partial/` and moved into place when complete. Each JSON has
  `Sun`, `Capture` and `System` blocks (`sunset-meta.py`), and a `system.json` in each UTC day folder holds
  what rarely changes. **Change `SETUP_ID` whenever the camera, lens, focus, iris, mount or hood changes.**
- **Frame JSON is private:** the `Sun` block locates the site to about 30 m (#25), so anything that
  publishes JSON strips `Sun` first. Site coordinates live only in `sunset.env` (`SITE_LAT`/`SITE_LON`).
- **Local-first storage:** frames go to the Pi first; `sunset-sync.sh` copies them to the NAS SMB share
  (`camera`, folder `project_sunshine`, automounted at `/mnt/nas-camera`, login in the root-only
  `/etc/sunset-nas.cred`, never in this repo) and deletes the Pi's copy only after reading the NAS copy back
  (size, SHA-256 up to 8 MB). Writing straight to the NAS was rejected. It refuses to run if the share is
  missing or on the SD card, and backs up `sunset.env`, `fstab` and `config.txt` to
  `project_sunshine_config/<host>/`. Capture refuses to run without `sunset.env` (`REQUIRE_ENV_FILE`, #23).
- **Disk guard:** ≥95% full skips the night frame, <100 MB free skips the capture. All logged.
- **Clock:** the board's DS1338 RTC has **no coin cell yet** (Steven), so it keeps time through a reboot,
  not a power cut. Capture refuses to run until NTP has synced once since boot (`SKIPPED`), then keeps going
  through later NTP outages. A gap is preferred to frames with a wrong UTC name.
- **Recovery:** systemd's hardware watchdog (15 s) reboots a hard freeze. One watchdog unit
  (`sunset-guard`; `NETWATCH=1`, `CAMWATCH=1`) resets the Wi-Fi dongle after 10 min without the gateway
  over both `wlan0` and `eth0` (`NETWATCH_WIRED`; a Wi-Fi outage with the cable working is left alone) and
  reboots after 30, and reboots when one camera fails 3 captures within 60 minutes; at most one reboot every
  6 h. `sunset-kernlog.service` keeps kernel messages in `~/sunset/kernel.log`. All LEDs are off
  (`90-sunset-leds.rules`): they showed in the glass.
- **UPS: Mini-Box OpenUPS2**, three Li-ion 18650s (2,500 mAh), firmware 1.6, **R20 left as fitted**
  (Steven: the boards won't be modified), so the cells charge only to ~3.5-3.6 V. 15 V supply. Read by
  `pi/sunset-ups.py` over `/dev/hidraw` (read-only); `~/sunset/ups.log` only on changes and events. On low
  battery (any cell under `UPS_LOW_CELL_V`, 3.3 V; the board's charge % is useless) it pauses the capture,
  dense and sync timers rather than halting. Status in each frame's `System` block. Runtime measured at
  ≥ 2 h 27 min. P2-to-MyPi cable polarity checked (Steven, 2026-11-22). **Open (#29):** deadband tuning.
- **Diag page** (`diag start`): live view with focus peaking and a camera switch; it pauses capture of
  both cameras while on, and hands its timers to a UPS pause if one is in force when it ends.
- **Home Assistant** (`homeassistant.local`, port 80, config edited with the File editor add-on) reads
  the share at `/share/camera` and alerts on frame age (~70 min), each camera's health from its newest
  frame, NAS free space and the UPS (on battery, plus graphable values and CM4 CPU temperature). HA's copy
  is the repo's `homeassistant/` plus the phone notifier (`mobile_app_pixel_8`), which is in HA's copy only.
  **Keep all the sensors** (Steven, 2026-11-22). No outside heartbeat (#22).
- **Retired:** the Pi 3 B+ `timelaps` (camera `wide`, last frame 04:10 UTC Nov 17); its checks were taken out of HA
  on Nov 20. The temperature, humidity and light sensors were dropped (#34 closed).

## Video and Instagram
- The daily video covers the whole day from 07:30 local (`VIDEO_START_LOCAL`), from `cm4wide`, crop `view`
  top 100, height 2440, a light blur on the near towers (`blur` boxes in `crop.json`), handle `@funvill`
  and a third line `Burnaby, BC, Canada   WSW 243°`. No sunset-only cut, no master render. Built with
  `tools/build_video.py` on the PC.
- **Sky score** (deterministic, in `nas/sunset-daily.py`): the best frame from 35 min before to 25 min after
  sunset, by the share of the top of the frame that is bright and warm; `sky_full_warm` in `crop.json` sets
  the camera's scale (0.178 for `cm4wide`). Bands: under 20 grey, 20-59 some colour, 60+ colourful.
  Recheck after any lens or camera change.
- **Posting:** only days scoring **60** or more (Steven, kept 2026-11-20). **Steven uploads by hand** to his
  account, so there is no publisher. Public posts are fine with the towers blurred and no location tag;
  captions name the city only. **ToDo: open-source-licensed music.**
- **Good-sunset notification (2026-11-22):** `pi/sunset-sky.py` (`sunset-sky.timer`) scores each sunset
  on the Pi about 40 min after it, with the same maths (Pillow instead of ffmpeg for the shrink), and
  writes `project_sunshine_sky/cm4wide/<date>.json` to the share; Home Assistant (`sunset_sky.sh`,
  `sensor.sunset_sky_score`) notifies once an evening at the threshold
  (`input_number.sunset_sky_post_threshold`, 60). That is the cue to build the video and upload it.
- **Before anything posts:** the sunset flicker. It is real cloud crossing the glow (same minutes on both
  cameras), not exposure; the 1:2:1 blend roughly halves it. Steven to judge. Also: recheck the tower blur
  boxes and the calibration on a clear sunset, and copy `crop.cm4wide.json` to the NAS.
- How the long film handles gaps is decided when it is edited.

## Open items
- Before Dec 21: settings freeze (Dec 14, `PROFILE_ID`), keyed mount (#35) after the FOV and
  edges are measured (#4, experiment 22), RTC coin cell, the 16 mm spacer.
- Fog detection alerts (#33). Sun protection for a telephoto lens (#32: software can't protect the sensor;
  an iris or ND filter is Steven's call). Long-film post-processing (#20, #21).
- **Pending experiments (#3):** the moon (exposure, double-glazing ghosts, a night FOV check), vignetting
  and sharpness (dark, flat, checker), the room-light glow (needs Steven). Experiments run as transient
  `exp-*` timers (a reboot clears them) and write to `project_sunshine_experiments/` on the NAS, never the
  outbox. The hourly weather log (`exp-weather.timer`, a unit file) keeps running.
- Buying decisions are Steven's (High Endurance storage is moot on the eMMC; heatsink, ND filter, spare
  cameras). A used Sony a6300 over gphoto2 remains the image-quality upgrade path.

## Rules for working here
- Pi changes are production changes: Steven's go-ahead first, and check the Pi's files against the repo
  before overwriting.
- Deterministic scripts for anything repeatable, no AI each time.
- Mount: 3D printed in **PETG or ASA** (not PLA — sun heat), stuck to glass with **3M VHB**,
  **keyed two-part design** so a replacement camera returns to the same framing, foam hood sealed
  against the glass, camera square to the glass.
- Freeze software once stable: pinned OS, no auto-updates, a full image saved on the NAS.

## Testing
`bash tests/run.sh` runs everything offline (stubbed camera and NAS); `bash tests/run.sh 17_ dense test_ups`
runs only those (a case that uses another case's helpers names it on a `# needs:` line). The OpenCV tests
(`test_fuse_sunset`, `test_fog_scan`, `test_issue_blur`, `test_build_reports`) skip without cv2; on
Windows run them with `python -P tests/<file>.py`. On the Pi, `./sunset-selftest.sh` checks camera, clock,
disk, memory, capture time, IR-cut and NAS.

## Unverified numbers
Sunset azimuths, magnetic declination, lens FOVs and per-frame sizes are estimates until measured.
Confirm the FOV and edges (#4, experiment 22) before the mount is glued (#35).

## Related
- A project doc also exists as a Claude Docs artifact titled "Project Sunset" (overview + shopping list).
