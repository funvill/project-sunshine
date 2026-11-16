# Project Sunset — Pi setup

> **Two Pis run this project:** `timelaps` (Pi 3 B+) and `sunshine` (CM4). Neither is a Zero. See
> `../CLAUDE.md`. Use your own user name where this guide shows one; `install.sh` handles that for
> the systemd units. Files named here are in the repo's `pi/` folder unless a path says otherwise.
> To rebuild a Pi that has died, go to "Rebuild a Pi" below.

One IMX477 camera (Pi HQ or Arducam) on each Raspberry Pi.
Captures every 5 minutes to the SD card, then syncs to the NAS every 5 minutes. Around sunrise
and sunset it adds a frame every minute (see "Dense frames" below).
Local-first, so a NAS or Wi-Fi outage never loses frames.

## 1. Hardware
- `timelaps`: Pi 3 B+ Rev 1.3, Arducam UC-517 in the CAMERA port, microSD card, 5 V supply. Hostname
  `timelaps`, user `funvill`.
- `sunshine`: Raspberry Pi CM4 (32 GB eMMC, 8 GB RAM, no Wi-Fi) on an Embedded Micro Technology MyPi
  Industrial IoT Integrator Board XT, Arducam IMX477 with a 3.2 mm lens on CAM0, USB Wi-Fi dongle.
  Hostname `sunshine`, user `sunshine`. Camera mounted upside down (`ROTATION=180`).
- Both: lens focus locked at infinity, iris taped. UC-517: keep the IR-cut filter in day mode.
- The Pi Zero W is not the target. The scripts have no Zero-specific code, but the camera has not
  been shown working on one. See `hardware/README.md`.

## 2. OS
- Flash Raspberry Pi OS Lite Bookworm (32-bit). In Imager set the hostname (`timelaps` or
  `sunshine`), the user (see section 1), Wi-Fi if the Pi has it, and SSH (key).
  Then `ssh <user>@<hostname>.local`.
- `sudo apt update && sudo apt install -y rpicam-apps-lite rsync python3`
- `/boot/firmware/config.txt`:
  - Official Pi HQ: leave `camera_auto_detect=1`.
  - Arducam UC-517: set `camera_auto_detect=0` and add `dtoverlay=imx477`.
  - CM4 with the camera on CAM0: `dtoverlay=imx477,cam0` instead (see "Rebuild a Pi").
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
//<nas-host>/camera /mnt/nas-camera cifs credentials=/etc/sunset-nas.cred,vers=3.0,uid=1000,gid=1000,file_mode=0664,dir_mode=0775,nofail,_netdev,x-systemd.automount,x-systemd.idle-timeout=300,x-systemd.mount-timeout=30 0 0
```
The target folder must already exist on the share. The sync refuses to run if it is missing or on
the SD card, so an absent mount keeps frames local instead of filling the card.

**Or rsync over SSH:**
```
ssh-keygen -t ed25519        # no passphrase
ssh-copy-id <nas-user>@<nas-host>
ssh <nas-user>@<nas-host>         # must log in with no prompt
```
The NAS user only needs write access to the project share (rsync over SSH enabled).

## 4. Install
```
mkdir -p ~/sunset && cd ~/sunset
# copy everything in the repo's pi/ folder here, keeping it flat (systemd/ stays a subfolder)
chmod +x *.sh
cp sunset.env.example sunset.env      # edit NAS_TARGET, CAM_NAME, SITE_LAT, SITE_LON
sudo ./install.sh --uc517    # installs units for your user; --uc517 sets the camera overlay
sudo reboot                  # only needed if the camera config changed
sudo systemctl enable --now sunset-capture.timer sunset-sync.timer sunset-dense.timer
```
Run the self-test first (camera, clock, disk, memory, capture time, IR-cut, NAS):
`./sunset-selftest.sh` (`--quick` skips the timed captures, `--no-nas` skips the NAS).

Test immediately: `sudo systemctl start sunset-capture.service && ls -R outbox`

### Dense frames
`sunset-dense.timer` runs `sunset-capture.sh --dense` every minute. It takes a frame only from the
sun at -9° until 60 minutes after sunrise, and from 60 minutes before sunset until the sun is at
-9° (`sunset-sun.py dense` decides, from `SITE_LAT`/`SITE_LON`). Outside those windows, and on the
regular slot minutes, it exits without touching the camera or the log.
- Same name, folder and auto exposure as the regular frame: `wide_<UTC>.jpg` + `.json`. No DNG and
  no night frame.
- `Capture.schedule` in the JSON is `"dense"` for these and `"regular"` for the 5-minute frames.
- The regular frame always wins: it waits up to `LOCK_WAIT_S` (90 s) for a dense frame to finish,
  a dense frame never waits, and a hung camera is given up after `DENSE_TIMEOUT_S` (30 s).
- Log lines start `dense window=sunrise` or `dense window=sunset`.
- Anything else that uses the camera (the experiment runner) must stay out of these windows.
- To stop them: `sudo systemctl disable --now sunset-dense.timer`.
Check schedule: `systemctl list-timers 'sunset*'`

## 5. Reduce SD card writes
Lite images already skip most of the desktop. A full desktop image can be cut down to
`keep-packages.txt` (the pilot Pi went from 1,624 packages to 362). Dry-run it and read the list
first: apt will take anything the keep list does not hold, so check nothing you need is on it.
```
sudo apt-mark auto $(apt-mark showmanual)
sudo apt-mark manual $(cat keep-packages.txt)
OPTS="-o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false"
sudo apt-get -s $OPTS autoremove --purge    # read this, then drop -s to run it
```
Do not remove `raspi-utils-eeprom`: on the pilot, that took `raspi-config` and `vcgencmd` with it.
On a CM4 (or any Pi 4), also run this before the dry-run. `keep-packages.txt` keeps only the Pi 3 and
Zero kernels, and the CM4 boots `kernel8.img`. The firmware and `usb-modeswitch` packages are for a
USB Wi-Fi adapter, because the CM4 in this project has no Wi-Fi of its own:
`sudo apt-mark manual linux-image-rpi-v7l linux-image-rpi-v8 firmware-realtek firmware-mediatek firmware-atheros usb-modeswitch usb-modeswitch-data`
This leaves `rpicam-apps-core` only, so there is no on-screen camera preview.

Then, once, and reboot: `sudo ./sunset-lowwear.sh`. System logs move to RAM (lost on reboot;
`capture.log` and `sync.log` stay on the SD), swap goes, and background jobs that write to the
card stop. Frames still go through the SD, and that is nearly all of the card's writes.

`install.sh` also adds two things for a Pi nobody is watching. A 15 s hardware watchdog should
reboot it after a hard freeze. Kernel messages are kept in `~/sunset/kernel.log`, the one system
log that survives a reboot, so look there first after a crash. The log may still be empty for a
hard freeze, since it only holds what the kernel managed to write.

**Wi-Fi dongle watchdog (`NETWATCH=1`).** For a Pi on a USB Wi-Fi dongle, such as the CM4. On
2026-11-13 the CM4's dongle dropped off and didn't rejoin until a power-cycle. `install.sh` enables
`sunset-netwatch.timer` on every Pi, but `sunset-netwatch.sh` does nothing unless `sunset.env` has
`NETWATCH=1`. Every 2 minutes, as root, it pings the default gateway through `wlan0`:

- After 10 minutes without an answer it unbinds and rebinds the dongle's USB device, once per
  outage. This is a software replug: tested on the CM4, the dongle rejoined in 6 s.
- After 30 minutes it reboots, at most once every 6 hours (marker `~/sunset/.netwatch-reboot`),
  so a router outage can't cause a reboot loop. A reboot costs about one capture and clears
  transient experiment timers (`exp-*`).
- It keeps its state in RAM (`/run/sunset-netwatch`) and writes `~/sunset/netwatch.log` only when it acts.
- Tune with `NETWATCH_IFACE`, `NETWATCH_RESET_MIN`, `NETWATCH_REBOOT_MIN`, `NETWATCH_REBOOT_GAP_H`.

## 6. Freeze it
After a week of clean running: disable unattended upgrades and save a full image of the card (or
eMMC). That image is the recovery plan. Commands, and where to record the date, are under "Save and
restore the frozen image" below.

## Output (layout unchanged)
```
outbox/<cam>/YYYY/MM/DD/<cam>_YYYYMMDDTHHMMSSZ.jpg   # auto exposure
                                              .dng   # RAW (SAVE_RAW=1)
                                              .json  # exposure, gain, lux, colour gains
                                         _night.*    # extra long exposure when dark
outbox/<cam>/YYYY/MM/DD/system.json                  # what rarely changes, one per UTC day
capture.log                                          # one line per capture (see below)
sync.log                                             # one line per sync run
.system-state-<cam>.json                             # the day's records, so the sync can't lose them
```
Each frame's `.json` holds rpicam-still's own camera fields at the top level, unchanged, plus these blocks:

| Block | Written by | Contents |
|---|---|---|
| `Sun` | `sunset-sun.py` | True-north azimuth, elevation, nearest sunset and minutes from it, from `SITE_LAT`/`SITE_LON` |
| `Capture` | `sunset-meta.py` | `schema_version`, camera, `kind` (`auto` or `night`), `setup_id`, `system_id`, slot and shot times, shot duration, settings asked for, the lux that triggered a night frame, size and SHA-256 of the JPEG and DNG |
| `System` | `sunset-meta.py` | The machine at that moment: uptime, load, free memory, CPU temperature, core voltage, ARM clock, `throttled`, free disk space, frames waiting to sync, SD sectors read and written, network state and Wi-Fi signal, NTP state, NAS mount and last sync |

`system.json` holds what rarely changes: hostname, Pi model, board revision, OS, kernel, firmware, Python, rpicam-apps and libcamera versions, camera overlay, time zone, total memory and disk, SD card identity, `setup_id`, `setup_note` and a hash identifying the capture script. It has a `records` list, normally with one entry. If something changes during the day, such as the setup at the bracket move, the file gains a record starting at that frame. A frame's `Capture.system_id` names the record that applied to it.

`System.throttled` is the raw value from `vcgencmd get_throttled`. Bits 0-3 are the state now: undervoltage, frequency capped, throttled, soft temperature limit. Bits 16-19 are the same four since boot.

- **Failures:** a source that can't be read becomes `null` and is named in `System.unavailable`. If `system.json` can't be written, `Capture.system_id` is `null` and the next frame tries again. If the whole step fails, the frame is kept and the log says `meta=err`.
- **NAS:** the capture never touches the NAS path, because a dead share could hang it. Its state comes from `/proc/mounts` and `sync.log`, so `System.nas` can lag by up to one sync.
- **Left out on purpose:** site coordinates, IP and MAC addresses, the Wi-Fi name, the NTP server, file paths, and the board and SD card serial numbers, in case frames are ever published.
- **Changing the setup:** change `SETUP_ID` in `sunset.env` whenever the camera, lens, focus, iris, mount or hood changes.
- **Verifying files:** `Capture.files` holds each image's SHA-256, so an archive can be checked for damage years later. `FRAME_CHECKSUMS=0` turns this off.
- **Tools reading the folders:** anything that globs `*.json` must skip `system.json`. Frames taken before 21:45 UTC on 2026-11-04 use the older format, `schema_version` 1 or no `Capture` block at all.

Frames are written to `outbox/.partial/` and moved into place when complete; the
sync ignores dot-directories, so it can never ship a half-written frame.

`capture.log` line: `<utc> cam=wide lux=... soc=... disk=NN% raw=1 night=0 meta=ok sun=az=...,el=... ok`,
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

### Diagnostics page and focus
Over SSH, type `diag`. It prints a link to a temporary page with a live camera view and the Pi's
health: capture and sync status, clock, disk, memory, temperature and power.

Focusing tools, all worked out in the browser so the Pi does no extra work:
- **Focus** shows the centre 20% of the sensor at full resolution, so one screen pixel is one sensor
  pixel. To look somewhere else, such as the downtown skyline, click that spot on the full frame.
- **Focus peaking** paints sharp edges in red (or yellow, white or cyan) over the image, as on a
  mirrorless camera. Sensitivity Low shows only the sharpest edges. Turn the ring until the
  outlines are thinnest and brightest. **Peaking %** is the share of the image that is outlined.
- **Sharpness** and its graph of the last minute: turn the lens slowly and stop at the peak. The
  dashed line is the best so far. Aim at something distant with fine detail, and compare only within
  the same scene and light. Switching view resets it.
```
diag          # on for 30 minutes; running it again restarts the clock
diag status   # is it on, and what is the link
diag stop     # off
```
It stops by itself and does not come back after a reboot. The camera only runs while the page is
open, and the view gives way to each scheduled capture so that the capture can use the camera. The
page may also give way to dense frames, or may hold the camera through one; either way you don't
need to stop the capture timers. Don't run `sunset-selftest.sh`, `sunset-focus.py` or a manual
capture while the page is open, because only one program can use the camera at a time.

The page has no password: while it's on, anyone on your LAN can see the camera, the logs and the
Pi's status, and switch the view. Don't forward its port through the router.

Without the page: `python3 sunset-focus.py` prints a sharpness score per reading, or with a monitor
on the Pi, `rpicam-hello -t 0 --roi 0.4,0.4,0.2,0.2` gives a live view zoomed 5x into the centre.
Stop the capture timer first for either of these.

### Tests (no Pi needed)
`bash tests/run.sh` runs the scripts against stub `rpicam-still`/`rsync`/`df`/`ssh`.

## Home Assistant alert
Alerts when no new production frame has reached the NAS for an hour. It reads the NAS rather than
the Pi, so it also catches a dead Pi, a dead camera or a stuck sync. Written for Home Assistant OS.

1. **Connect the share.** Settings > System > Storage > Add network storage. Name `camera`, usage
   **Share**, server `<nas-host>` (the NAS's name or address), protocol Samba, remote share `camera`, user `<nas-user>`.
   It appears in Home Assistant as `/share/camera`. The script has no setting at the top. It reads
   two environment variables: `FRAME_BASE` (the folder that holds one folder per camera, default
   `/share/camera/project_sunshine`) and `FRAME_ROOT` (one camera's whole folder; it overrides
   `FRAME_BASE` and the camera name). If you used another share name or usage, set `FRAME_BASE` in
   the sensor's `command:` in `sunset.yaml`, for example
   `FRAME_BASE=/share/other/project_sunshine sh /config/sunset/sunset_frame_age.sh`. Don't set
   `FRAME_ROOT` for a package with two cameras: both sensors would then read the same folder.
2. **Copy the files** into Home Assistant's config folder (Samba or File editor add-on):
   - `homeassistant/sunset_frame_age.sh` to `/config/sunset/sunset_frame_age.sh`
   - `homeassistant/sunset.yaml` to `/config/packages/sunset.yaml`
3. **Load packages.** In `configuration.yaml`, if it isn't already there:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
4. **Add your phone.** Replace the commented line under `notifiers` in `sunset.yaml`. Your phone's
   name is under Developer Tools > Actions: search for `notify.mobile_app`.
5. **Restart.** Developer Tools > YAML > Check configuration, then restart Home Assistant.
6. **Check the age.** `sensor.sunset_newest_frame_age` should show under 20 minutes within 5 minutes.
   The package also watches the CM4 (`cm4wide`) as `sensor.sunset_cm4_newest_frame_age`, with its
   own alert. For another camera, copy those three blocks and pass its `CAM_NAME` to the script.
   **Updating an installed copy:** HA's `sunset.yaml` holds your phone notifier, so don't overwrite
   it. Copy the new `sunset_frame_age.sh` over the old one, and paste the new CM4 blocks into HA's
   `sunset.yaml` (and your phone under the new alert's `notifiers`), then check and restart.
7. **Test that it fires and clears.** Capture keeps running. Set `input_number.sunset_max_frame_age`
   to 1 and wait up to 15 minutes for the notification, then set it back to 60: the "again" message
   should arrive straight away.

With the default settings, an alert comes 70 to 75 minutes after the last frame, then repeats every
6 hours until frames return or you acknowledge it.

### Monitoring beyond frame age

Not installed in Home Assistant yet. To install: copy `sunset_frame_age.sh`, `sunset_nas_free.sh`,
`sunset_camera_health.sh`, `sunset_daily_status.sh` and `sunset_result.sh` from `homeassistant/` to
`/config/sunset/`, and paste the new blocks from `sunset.yaml` into HA's copy. Don't overwrite HA's
copy: it holds the phone notifier. Add the phone line under each new alert's `notifiers`.

The new blocks add alerts for:
- NAS free space (default 100 GB, about a month of frames at about 3 GB a day with no DNGs);
- each Pi's health from its newest frame's JSON: undervoltage and throttle bits, temperature,
  frames waiting to sync, disk use, tiny or repeated JPEGs;
- the daily video job's status;
- the results of `nas/sunset-verify.py` and `nas/sunset-health.py` (see `nas/README.md`).

Anything unknown counts as bad. Python 3 is needed in HA's container. An alert you acknowledge is
re-armed after 12 hours.

For a check that Home Assistant itself is alive, choose a hosted heartbeat service, put its ping
URL in `secrets.yaml` as `sunset_heartbeat_url`, then copy `sunset_heartbeat.yaml` into
`/config/packages/`. Don't copy that file before the secret exists: it stops HA loading its
packages.

## Rebuild a Pi
For a dead SD card or eMMC, or a Pi that has to be reflashed. Each list goes from blank storage to a
verified first frame. Frames already on the NAS are not touched. Frames still on the dead card are
lost unless the card can be read, so try that first.

Before you start:
- Find the newest frozen image (see "Save and restore the frozen image"). Restoring it is faster
  than the lists below, but check the clock, `SETUP_ID` and `CAM_NAME` afterwards.
- If the old Pi still runs, save what exists only on it: `~/sunset/sunset.env`, `/etc/fstab`,
  `/boot/firmware/config.txt`, `/etc/sunset-nas.cred` (keep this one off any shared drive), and the
  list of transient timers from `systemctl list-timers 'exp-*'`. How those timers were started is
  not recorded here, so note their command lines before the Pi is wiped.
- The repo holds per-host reference copies of the settings in `pi/hosts/timelaps.env` and
  `pi/hosts/cm4.env`. They leave out the site coordinates and anything secret, so they are a start,
  not a full `sunset.env`. If the files are not there yet, use the old Pi's `sunset.env`, or
  `sunset.env.example` and the values in `../CLAUDE.md` and `../changelog.md`.

### `timelaps` (Pi 3 B+, SD card)
1. **Flash.** Raspberry Pi Imager, Raspberry Pi OS Lite Bookworm 32-bit, onto a card of at least 32 GB
   (High Endurance for the real run; frames are nearly all of the card's writes). In the Imager
   settings: hostname `timelaps`, user `funvill`, SSH with a key, Ethernet (and Wi-Fi if wanted).
   Time zone America/Vancouver.
2. **First boot.** `ssh funvill@timelaps.local`, then `sudo apt update && sudo apt full-upgrade`.
   The pilot ran kernel 6.12.109, rpicam-apps 1.9.0 and libcamera 0.5 (changelog, 2026-11-03).
3. **Camera overlay.** In `/boot/firmware/config.txt` set `camera_auto_detect=0` and add
   `dtoverlay=imx477`. The UC-517 is not found by auto-detect. Reboot.
4. **Camera check.** `rpicam-still -n -t 3000 -o test.jpg`. If it fails, reseat the ribbon at both
   ends before anything else: that fixed the outage of 2026-11-05.
5. **Packages.** `sudo apt install -y rpicam-apps-lite rsync python3 cifs-utils`. If the image was
   not Lite, trim it with the keep list (section 5).
6. **Copy `pi/` to `~/sunset`**, flat, with `systemd/` as a subfolder: from the PC,
   `scp -r pi/* funvill@timelaps.local:sunset/` (make the folder first). Then `chmod +x ~/sunset/*.sh`.
7. **Restore `sunset.env`.** Copy `pi/hosts/timelaps.env` to `~/sunset/sunset.env` and add
   `SITE_LAT` and `SITE_LON` (the real ones; they are never in the repo). Keep `CAM_NAME` as the
   host file has it. Set `SETUP_ID` to a new value if the camera, lens, focus or mount changed.
8. **NAS login and mount.** Create `/etc/sunset-nas.cred` (root-only, section 3) and add the
   `/etc/fstab` line from section 3. Then `sudo mkdir -p /mnt/nas-camera`, run
   `sudo systemctl daemon-reload`, and check `ls /mnt/nas-camera/project_sunshine`. `NAS_TARGET` in
   `sunset.env` must be `/mnt/nas-camera/project_sunshine/`.
9. **Install.** `cd ~/sunset && sudo ./install.sh`. It installs the units, the LED rules, the
   watchdog and the kernel log, and does not enable the capture timers yet. Do not pass `--enable`.
   Step 3 set the camera overlay by hand, so `--uc517` is not needed; if you use it, check
   `config.txt` afterwards.
10. **Low wear.** `sudo ./sunset-lowwear.sh`, then `sudo reboot`.
11. **Experiments.** `mkdir -p ~/sunset/experiments` and copy the repo's `experiments/` into it
    (the unit runs `~/sunset/experiments/sunset-weather.py`). For the weather log, copy
    `~/sunset/experiments/systemd/exp-weather.service` and `exp-weather.timer` to
    `/etc/systemd/system/`, change `User=` and the `/home/pi/` path in the service to your user and
    home, then `sudo systemctl daemon-reload` and `sudo systemctl enable --now exp-weather.timer`.
    Until production shoots the sunset bracket (#10), do the same for `exp-sunset.service` (replace
    `USER` and `HOME`) and `exp-sunset.timer`: it runs `sunset-nightly.sh` at 23:00 UTC, which waits
    for tonight's sunset window and survives a reboot. Once `BRACKET=1` is set in `sunset.env`
    (the production bracket, see `sunset.env.example`), disable it:
    `sudo systemctl disable --now exp-sunset.timer`, so the two don't fight over the camera.
    Re-create any other `exp-*` timers from the notes you made before the wipe. They are transient,
    so a reboot clears them, and they are not part of the production capture.
12. **Self-test.** `./sunset-selftest.sh`. It checks the camera, clock, disk, memory, capture time,
    IR-cut and NAS. Fix any FAIL before going on.
13. **Check `CAM_NAME` before the timers start.**
    `grep -E '^(CAM_NAME|ROTATION|SETUP_ID)' ~/sunset/sunset.env` must show `CAM_NAME=wide` and no
    `ROTATION` for this host. The units read `sunset.env` with `EnvironmentFile=-`, so a missing
    file is not an error: the script falls back to `wide` and its defaults.
14. **First frame.** `sudo systemctl start sunset-capture.service`, then `ls -R ~/sunset/outbox` and
    `tail ~/sunset/capture.log`. The log line should say `cam=wide` and end in `ok`. Run
    `sudo systemctl start sunset-sync.service` and confirm the frame appears under
    `project_sunshine/wide/` on the NAS.
15. **Start.** `sudo systemctl enable --now sunset-capture.timer sunset-sync.timer sunset-dense.timer`.
    Check `systemctl list-timers 'sunset*'`. The Home Assistant alert should stay quiet, or clear
    within about 75 minutes.
16. **Record it.** Add a `changelog.md` entry: date, what was restored, the new `SETUP_ID` if it
    changed, and the gap in frames.

### `sunshine` (CM4 on the MyPi board, eMMC)
The CM4's storage is on the module, so a blank eMMC cannot be flashed like a card. It has to be
exposed to the PC as a disk first. That step is the only part that differs.
1. **Expose the eMMC.** On the PC, install `rpiboot` (the Raspberry Pi `usbboot` tool). On the
   board, set the boot jumper or switch that stops the CM4 from booting from its own eMMC, and
   connect the board's USB port for this to the PC. Which jumper, which port and whether the board
   must be powered first: check the board manual (Embedded Micro Technology MyPi Industrial IoT
   Integrator Board XT). Then run `sudo rpiboot`. After a few seconds the eMMC shows up as a
   disk (`lsblk` on Linux; 29.1 GB on this module).
2. **Flash.** Raspberry Pi Imager: choose that disk, Raspberry Pi OS Lite Bookworm 32-bit, hostname
   `sunshine`, user `sunshine`, SSH with a key. This module has no Wi-Fi, so use Ethernet first.
   The 32-bit userland boots the 64-bit kernel (6.12.109-v8 was used), so the self-test warns
   about the Zero path. That warning is expected.
3. **Boot normally.** Unplug the USB cable, put the boot jumper back (check the board manual), power
   the board. `ssh sunshine@sunshine.local`, then `sudo apt update && sudo apt full-upgrade`.
4. **Overlays.** In `/boot/firmware/config.txt`:
   - `camera_auto_detect=0`
   - `dtoverlay=imx477,cam0` (the camera is on CAM0; nothing answered on CAM1)
   - `dtoverlay=i2c-rtc,ds1307,addr=0x68` (the board's DS1338 clock)

   Reboot. Let NTP set the clock once; the kernel then writes it back to the RTC every 11 minutes.
   There was no coin cell in the RTC holder on 2026-11-12 (whether one is fitted now: not recorded,
   check on the board), so the RTC only keeps time through a reboot, not a power cut.
5. **Camera check.** `rpicam-still -n -t 3000 -o test.jpg`. The image is upside down until
   `ROTATION=180` is set (step 7).
6. **Packages.** `sudo apt install -y rpicam-apps-lite rsync python3 cifs-utils`, and the CM4 notes
   in section 5 (`linux-image-rpi-v8`, USB Wi-Fi firmware) before any trimming. The pilot CM4 went
   from 615 to 383 packages.
7. **Copy `pi/` to `~/sunset`** as for `timelaps` (`scp -r pi/* sunshine@sunshine.local:sunset/`),
   then restore `sunset.env` from `pi/hosts/cm4.env` plus the real `SITE_LAT` and `SITE_LON`.
   It must set `CAM_NAME=cm4wide` and `ROTATION=180`, and `NETWATCH=1` if the Pi is on the USB
   Wi-Fi dongle. The other values the CM4 has used (night shutter, white balance, `SETUP_ID`) are
   in `../changelog.md`.
8. **Wi-Fi.** If the CM4 is on the dongle, join the network (`nmcli` or `raspi-config`). The dongle's
   firmware is in the kept packages. Dongle details beyond "old Buffalo 2.4 GHz USB": not recorded,
   check on the Pi.
9. **NAS login and mount.** As for `timelaps`: `/etc/sunset-nas.cred`, the fstab line, the mount
   point. The pilot copied the login file from `timelaps` Pi to Pi, without displaying it. Frames go
   to `project_sunshine/cm4wide/`.
10. **Install.** `cd ~/sunset && sudo ./install.sh`, with no `--enable`. Do not use plain `--uc517`
    on this board: it writes `dtoverlay=imx477` without `cam0`. For a cam0 option, run
    `./install.sh --help` or read the header of `install.sh` for the exact flag, and check
    `config.txt` afterwards. Step 4 already set the overlays, so the option is not required.
11. **Low wear.** `sudo ./sunset-lowwear.sh`, then reboot.
12. **Experiments and the weather units.** As in step 11 of the `timelaps` list, with this Pi's user
    and home.
13. **Self-test.** `./sunset-selftest.sh`.
14. **Check `CAM_NAME` before the timers start.**
    `grep -E '^(CAM_NAME|ROTATION|SETUP_ID|NETWATCH)' ~/sunset/sunset.env` must show
    `CAM_NAME=cm4wide` and `ROTATION=180`. A CM4 started from `sunset.env.example` has
    `CAM_NAME=wide` and no rotation: its upside-down frames would land in the `wide/` folder, ruin
    that series and keep the `wide` alert quiet while `timelaps` could be dead.
15. **First frame.** As for step 14 of the `timelaps` list. The log line must say `cam=cm4wide`, the
    JPEG must be upright, and the JSON `Capture.settings` must say `rotation: 180`. Check that the
    frame is under `cm4wide/` on the NAS and not in `wide/`.
16. **Start and record.** As for steps 15 and 16 of the `timelaps` list. The CM4 has its own Home
    Assistant alert (`cm4wide`).

## Save and restore the frozen image
Make an image after a week of clean running, and again after any change to the setup. Keep one copy
somewhere other than the NAS that holds the frames.

**SD card (`timelaps`).** With the Pi shut down (`sudo shutdown -h now`), put the card in a PC
running Linux. `lsblk` shows the device. Check it twice: `dd` overwrites without asking.
```
sudo dd if=/dev/sdX of=timelaps-YYYYMMDD.img bs=4M status=progress conv=fsync
sha256sum timelaps-YYYYMMDD.img > timelaps-YYYYMMDD.img.sha256
xz -T0 timelaps-YYYYMMDD.img            # optional, saves space
```
Restore to a card of the same size or larger. If you compressed it:
```
xz -dc timelaps-YYYYMMDD.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
```
Then boot and run steps 12 to 16 of the `timelaps` list. The clock is stale from the image, so
capture waits for NTP before it runs.

**eMMC (`sunshine`).** Expose the eMMC with `rpiboot` as in step 1 of the `sunshine` list. Then use
the same commands, with the disk `rpiboot` created as `/dev/sdX` and `sunshine-YYYYMMDD.img`. To
restore, expose a blank or damaged eMMC the same way and `dd` the image onto it. The image is the
size of the whole eMMC (about 29 GB), so it needs a device at least that big. Then run steps 13 to
16 of the `sunshine` list.

An image holds the `sunset.env` and `SETUP_ID` from the day it was taken. After a restore, compare
them with the live values you saved before the wipe.

**Last image.** Fill this in each time one is made, and add a `changelog.md` entry.

| Host | Date | Stored at | SHA-256 file | Notes |
|---|---|---|---|---|
| `timelaps` | none yet | not recorded | not recorded | |
| `sunshine` | none yet | not recorded | not recorded | |

## Zero-specific limits
- 12 MP JPEG + DNG takes several seconds: fine at 5 min, too slow for bracketed
  1-per-minute sunset bursts (move to a Pi 3 or newer for that).
- Night: if reported lux < `NIGHT_LUX`, a second fixed long exposure is taken.
  Tune `NIGHT_*` during the pilot.
- Home Assistant alert on the newest NAS file's age catches a dead camera, dead
  Wi-Fi or a stuck sync. `capture.log` shows whether capture itself is running.
