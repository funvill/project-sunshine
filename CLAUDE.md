# Project Sunset — handoff for Claude Code

Five-year time-lapse of the western sky from Steven's 23rd-floor window in Burnaby, BC,
looking toward downtown Vancouver. **Sunset is the subject.** Start date: **winter solstice,
2026-12-21**. Pilot should run by late November 2026.

This file is the project brief. `docs/setup.md` is the Pi setup guide. `changelog.md` lists changes
by date: add an entry with every change, including changes made only on the Pi.

## Repo layout
- `pi/`: everything that runs on the Pi. Copied flat into `~/sunset`; the systemd units expect that path.
- `tests/`: offline tests with a stubbed camera and NAS. No Pi needed.
- `experiments/`: pilot experiment runner (#3). Not part of the production capture.
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
- Capture every **15 min, 24/7**, day and night.
- **Denser capture around sunset** (~1/min for the hour around sunset, bracketed ×3) —
  needs a faster Pi than the Zero; deferred to the real build.
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
  capture. All logged. Does not change the 15-min schedule.
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
- 15-min captures only for now: burst mode (backlog #3) still needs a schedule decision.
- The Zero W path is no longer the target. The scripts have no Zero-specific code, but this camera
  has not been shown working on a Zero. See `docs/hardware/README.md`.
- **OS (2026-11-03):** upgraded to kernel 6.12.109, rpicam-apps 1.9.0, libcamera 0.5. Desktop and
  everything else not on `pi/keep-packages.txt` removed: 1,624 to 362 packages, 6.5 GB to 1.4 GB used.
  `sunset-lowwear.sh` applied. `cmdline.txt` had been empty for many boots (firmware defaults, no
  `fsck.repair`); it is now set. Kernels kept: v7 (this Pi) and v6 (Zero).
- **SD card:** a 32 GB card (ID `SH32G`, manufacturer ID 0x03, which is normally SanDisk, dated
  07/2021) with ~26 GB free, about 10 days of frames
  if the NAS is down, fewer with night frames. Run a write test and replace with a High Endurance
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
  the SD card dropping out (unproven; those logs were in RAM). Still needs a 5.1 V 2.5 A supply.
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
- **Camera will move slightly** when the bracket and supply arrive: redo anything tied to framing.
- **Not done yet:** a suitable power supply, final mounting and framing, foam hood, Home Assistant
  alert.

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
- **Arducam UC-517 Rev.D3** — IMX477 (same sensor as Pi HQ) with a switchable **IR-cut filter**.
  Keep IR-cut in day mode always; verify its state after power loss. Per Arducam's product
  page the filter is switched automatically by a photoresistor on the camera PCB, so there is no
  software state to read (a forum user wired GPIO after removing the photoresistor; unverified
  for this board). `sunset-selftest.sh` therefore judges it from image colour (heuristic). Has a
  22-pin connector, not the 15-pin one on the official HQ camera. Needs
  `camera_auto_detect=0` + `dtoverlay=imx477`. Known detection issues reported on Pi 3 + Bookworm 64-bit.
  Has an **unlabelled CS/C-mount lens** with iris ring; identify by measuring:
  focal length (mm) ≈ 6.29 × distance ÷ visible width.
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
- **Sunset (wide) camera:** IMX477 + ~3–4 mm lens on the **Pi 3**, or Camera Module 3 Wide (~102°).
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
| Privacy (tight camera into neighbours' windows) | Frame to avoid, or blur before publishing |

## Backlog for Claude Code
1. ~~Disk-space guard~~ **Done** (`sunset-capture.sh`, tested in `tests/`).
2. ~~Sun-position module~~ **Done**: `sunset-sun.py` (stdlib NOAA formula, no network). Writes the
   `Sun` block per frame; `sunset-sun.py sunset [--epoch|--json]` gives the next sunset for burst
   scheduling (backlog #3).
3. **Sunset burst mode** (1/min, 3-shot bracket) — for the Pi 3, not the Zero.
4. **Sensor protection** for the telephoto camera based on sun azimuth vs. its FOV.
5. **Fog detection**: flag low-contrast frames.
6. Port capture to **Picamera2** if finer control is needed than `rpicam-still` gives.
7. SHT4x + TSL2591 logging.
8. Home Assistant config for the stale-file alert.
9. Mount design: start from Printables model 250692 or design a keyed plate + foam hood.
10. Post-processing pipeline: deflicker, stabilisation, "sunset along the horizon" sequence
    (frame nearest each sunset), time slices, sky calendar.

## Creative outputs (later)
- Long time-lapse video (deflicker + stabilise).
- **Key piece:** the sun swinging along the horizon between solstices, frame nearest each sunset.
- Time slices (straight, curved, radial). Sky calendar (row = day, column = time of day).
- Data overlays from temp/humidity/lux logs plus historical weather pulled later.
- Prior art: Eirik Solheim (year in one image), Dan Marker-Moore, Richard Silver, Fong Qi Wei,
  Miska Knapek (slit-scan), Wendy Liu (Python/ImageMagick time slices),
  github.com/pconwell/rpi-long-timelapse (year-long Pi run lessons).

## Testing
`bash tests/run.sh` (offline, stubbed camera/NAS) and `python3 tests/test_sun.py`. On the Pi,
`./sunset-selftest.sh` checks camera, clock, disk, memory, capture time, IR-cut and NAS.
Its thresholds (30 s slow capture, 60 MB low memory, R/G 1.25 for IR-cut) are estimates to tune
from pilot data.

## Unverified numbers
Sunset azimuths, magnetic declination, lens FOVs and per-frame sizes above were estimated, not
measured. Confirm during the pilot before printing the mount or buying lenses.

## Related
- A project doc also exists as a Claude Docs artifact titled "Project Sunset" (overview + shopping list).
