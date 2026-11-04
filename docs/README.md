# Project Sunset — Pi setup

> **The pilot now runs on a Pi 3 B+ (`timelaps`), not a Zero.** See `CLAUDE.md`. Where this guide
> says `pi`, use your own user; `install.sh` handles that for the systemd units.

One IMX477 camera (Pi HQ or Arducam UC-517) on a Raspberry Pi.
Captures every 15 minutes to the SD card, then syncs to the NAS every 5 minutes.
Local-first, so a NAS or Wi-Fi outage never loses frames.

## 1. Hardware
- Pi Zero W v1.1, high-endurance microSD (64 GB+), 5 V 2.5 A supply.
- Pi Zero camera cable (22-pin end into the Zero, 15-pin end into the camera).
- Lens focus locked at infinity, iris taped. UC-517: keep the IR-cut filter in day mode.

## 2. OS
- Flash Raspberry Pi OS Lite (32-bit). In Imager set hostname `sunshine`, Wi-Fi (2.4 GHz), SSH (key) and user `pi`.
  Then `ssh pi@sunshine.local`.
- `sudo apt update && sudo apt install -y rpicam-apps-lite rsync python3`
- `/boot/firmware/config.txt`:
  - Official Pi HQ: leave `camera_auto_detect=1`.
  - Arducam UC-517: set `camera_auto_detect=0` and add `dtoverlay=imx477`.
- Reboot and test: `rpicam-still -n -t 3000 -o test.jpg`
  - Allocation errors at full resolution → change the KMS line to
    `dtoverlay=vc4-kms-v3d,cma-128`.
- Check NTP is on: `timedatectl status`. Files are named in UTC.

## 3. NAS access
**SMB share (what the pilot uses).** Put the login in a root-only file, then automount the share and
set `NAS_TARGET=/mnt/nas-camera/project_sunshine/`:
```
sudo install -m 600 -o root -g root /dev/null /etc/sunset-nas.cred
sudo nano /etc/sunset-nas.cred      # username=...  and  password=...
sudo mkdir -p /mnt/nas-camera
# add to /etc/fstab (uid/gid are your user's), then: sudo systemctl daemon-reload
//chipkin_nas.local/camera /mnt/nas-camera cifs credentials=/etc/sunset-nas.cred,vers=3.0,uid=1000,gid=1000,file_mode=0664,dir_mode=0775,nofail,_netdev,x-systemd.automount,x-systemd.idle-timeout=300,x-systemd.mount-timeout=30 0 0
```
The target folder must already exist on the share. The sync refuses to run if it is missing or on
the SD card, so an absent mount keeps frames local instead of filling the card.

**Or rsync over SSH:**
```
ssh-keygen -t ed25519        # no passphrase
ssh-copy-id sunset@nas.local
ssh sunset@nas.local         # must log in with no prompt
```
The NAS user only needs write access to the project share (rsync over SSH enabled).

## 4. Install
```
mkdir -p ~/sunset && cd ~/sunset
# copy sunset-capture.sh, sunset-sync.sh, sunset-sun.py, sunset-selftest.sh,
# sunset.env.example and systemd/ here
chmod +x *.sh
cp sunset.env.example sunset.env      # edit NAS_TARGET, CAM_NAME, SITE_LAT, SITE_LON
sudo ./install.sh --uc517    # installs units for your user; --uc517 sets the camera overlay
sudo reboot                  # only needed if the camera config changed
sudo systemctl enable --now sunset-capture.timer sunset-sync.timer
```
Run the self-test first (camera, clock, disk, memory, capture time, IR-cut, NAS):
`./sunset-selftest.sh` (`--quick` skips the timed captures, `--no-nas` skips the NAS).

Test immediately: `sudo systemctl start sunset-capture.service && ls -R outbox`
Check schedule: `systemctl list-timers 'sunset*'`

## 5. Freeze it
After a week of clean running: disable unattended upgrades and save a full
SD card image to the NAS. That image is the recovery plan.

## Output (layout unchanged)
```
outbox/<cam>/YYYY/MM/DD/<cam>_YYYYMMDDTHHMMSSZ.jpg   # auto exposure
                                              .dng   # RAW (SAVE_RAW=1)
                                              .json  # exposure, gain, lux, colour gains
                                         _night.*    # extra long exposure when dark
capture.log                                          # one line per capture (see below)
sync.log                                             # one line per sync run
```
`.json` also carries a `Sun` block: true-north azimuth, elevation, nearest sunset and
minutes from it, computed offline by `sunset-sun.py` from `SITE_LAT`/`SITE_LON`.
The site coordinates themselves are not written into the frame files.

Frames are written to `outbox/.partial/` and moved into place when complete; the
sync ignores dot-directories, so it can never ship a half-written frame.

`capture.log` line: `<utc> cam=wide lux=... soc=... disk=NN% raw=1 night=0 sun=az=...,el=... ok`,
or `FAILED ...` / `SKIPPED ...` / `DISK ...` lines explaining what was dropped and why.

### Safeguards
- **Clock:** the Zero has no RTC, so after a power cut it boots with a stale clock.
  Capture refuses to run (`SKIPPED: clock not synced`) until NTP has synced once this
  boot; later NTP outages do not stop it. `REQUIRE_TIME_SYNC=0` disables this.
- **Disk:** at 85% full or more the DNG is dropped, at 95% or more the night frame is
  skipped, and with under 100 MB free nothing is captured. Tune with `DISK_DROP_RAW_PCT`,
  `DISK_SKIP_NIGHT_PCT`, `DISK_MIN_FREE_MB`.
- **Camera hang:** each `rpicam-still` call is limited to `CAPTURE_TIMEOUT_S` (60 s).

### Next sunset, for scheduling
```
python3 sunset-sun.py sunset            # next sunset after now, UTC ISO
python3 sunset-sun.py sunset --epoch    # Unix seconds
python3 sunset-sun.py sunset --json     # plus sunset azimuth
python3 sunset-sun.py position          # sun now
```

### Setting focus
With a monitor on the Pi, in a terminal on the Pi itself, for a live view zoomed 5x into the centre:
`rpicam-hello -t 0 --roi 0.4,0.4,0.2,0.2`
Over SSH with no monitor: `python3 sunset-focus.py` prints a sharpness score per reading; aim at
something distant with fine detail and stop at the highest score. Either way, stop the capture
timer first, since only one program can use the camera at a time.

### Tests (no Pi needed)
`bash tests/run.sh` runs the scripts against stub `rpicam-still`/`rsync`/`df`/`ssh`.

## Zero-specific limits
- 12 MP JPEG + DNG takes several seconds: fine at 15 min, too slow for bracketed
  1-per-minute sunset bursts (move to a Pi 3 or newer for that).
- Night: if reported lux < `NIGHT_LUX`, a second fixed long exposure is taken.
  Tune `NIGHT_*` during the pilot.
- Home Assistant alert on the newest NAS file's age catches a dead camera, dead
  Wi-Fi or a stuck sync. `capture.log` shows whether capture itself is running.
