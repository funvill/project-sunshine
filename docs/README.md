# Project Sunset — Pi Zero W starter

One IMX477 camera (Pi HQ or Arducam UC-517) on a Pi Zero W v1.1.
Captures every 15 minutes to the SD card, then syncs to the NAS every 5 minutes.
Local-first, so a NAS or Wi-Fi outage never loses frames.

## 1. Hardware
- Pi Zero W v1.1, high-endurance microSD (64 GB+), 5 V 2.5 A supply.
- Pi Zero camera cable (22-pin end into the Zero, 15-pin end into the camera).
- Lens focus locked at infinity, iris taped. UC-517: keep the IR-cut filter in day mode.

## 2. OS
- Flash Raspberry Pi OS Lite (32-bit). In Imager set hostname, Wi-Fi, SSH and user `pi`.
- `sudo apt update && sudo apt install -y rpicam-apps-lite rsync python3`
- `/boot/firmware/config.txt`:
  - Official Pi HQ: leave `camera_auto_detect=1`.
  - Arducam UC-517: set `camera_auto_detect=0` and add `dtoverlay=imx477`.
- Reboot and test: `rpicam-still -n -t 3000 -o test.jpg`
  - Allocation errors at full resolution → change the KMS line to
    `dtoverlay=vc4-kms-v3d,cma-128`.
- Check NTP is on: `timedatectl status`. Files are named in UTC.

## 3. NAS access
```
ssh-keygen -t ed25519        # no passphrase
ssh-copy-id sunset@nas.local
ssh sunset@nas.local         # must log in with no prompt
```
The NAS user only needs write access to the project share (rsync over SSH enabled).

## 4. Install
```
mkdir -p /home/pi/sunset && cd /home/pi/sunset
# copy sunset-capture.sh, sunset-sync.sh, sunset.env.example, systemd/ here
chmod +x *.sh
cp sunset.env.example sunset.env      # edit NAS_TARGET, CAM_NAME
sudo cp systemd/* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sunset-capture.timer sunset-sync.timer
```
Test immediately: `sudo systemctl start sunset-capture.service && ls -R outbox`
Check schedule: `systemctl list-timers 'sunset*'`

## 5. Freeze it
After a week of clean running: disable unattended upgrades and save a full
SD card image to the NAS. That image is the recovery plan.

## Output
```
outbox/<cam>/YYYY/MM/DD/<cam>_YYYYMMDDTHHMMSSZ.jpg   # auto exposure
                                              .dng   # RAW (SAVE_RAW=1)
                                              .json  # exposure, gain, lux, colour gains
                                         _night.*    # extra long exposure when dark
capture.log                                          # one line per capture with lux + SoC temp
```

## Zero-specific limits
- 12 MP JPEG + DNG takes several seconds: fine at 15 min, too slow for bracketed
  1-per-minute sunset bursts (move to a Pi 3 or newer for that).
- Night: if reported lux < `NIGHT_LUX`, a second fixed long exposure is taken.
  Tune `NIGHT_*` during the pilot.
- Home Assistant alert on the newest NAS file's age catches a dead camera, dead
  Wi-Fi or a stuck sync. `capture.log` shows whether capture itself is running.
