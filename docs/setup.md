# Project Sunset — Pi setup

> **One Pi runs this project:** `sunshine` (CM4, two cameras). The Pi 3 `timelaps` was retired on
> 2026-11-17. See `../CLAUDE.md`. Use your own user name where this guide shows one; `install.sh` handles that for
> the systemd units. Files named here are in the repo's `pi/` folder unless a path says otherwise.
> To rebuild a Pi that has died, go to "Rebuild a Pi" below.

Two IMX477 cameras on the CM4.
Captures every 5 minutes to local storage, then syncs to the NAS every 5 minutes. Around sunset
it adds a frame every minute (see "Dense frames" below).
Local-first, so a NAS or Wi-Fi outage never loses frames.

## 1. Hardware
- `sunshine`: Raspberry Pi CM4 (32 GB eMMC, 8 GB RAM, no Wi-Fi) on an Embedded Micro Technology MyPi
  Industrial IoT Integrator Board XT, USB Wi-Fi dongle. Hostname `sunshine`, user `sunshine`.
  Two cameras from 2026-11-17: Arducam IMX477 (B0240E) with the 3.2 mm lens on CAM0 (`cm4wide`,
  upright, `ROTATION=0`), and the UC-517 with the 6 mm lens on CAM1 (`cm4city`). `timelaps` is retired.
- Both cameras: lens focus locked at infinity, iris taped. UC-517: keep the IR-cut filter in day mode.

## 2. OS
- Flash Raspberry Pi OS Lite Bookworm (32-bit). In Imager set the hostname (`sunshine`), the user (see section 1), Wi-Fi if the Pi has it, and SSH (key).
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
sudo ./install.sh --cm4-two  # installs units for your user; --cm4-two sets both camera overlays
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
- Same name, folder and auto exposure as the regular frame: `<cam>_<UTC>.jpg` + `.json`, no night
  frame.
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

**Watchdog: `sunset-guard.sh` (`NETWATCH=1`, `CAMWATCH=1`).** `install.sh` enables
`sunset-guard.timer` on every Pi. Every 2 minutes, as root, it runs two checks, each off unless
`sunset.env` turns it on. Each keeps its state in RAM (`/run/sunset-netwatch`, `/run/sunset-camwatch`)
and writes its log (`~/sunset/netwatch.log`, `camwatch.log`) only when it acts. At most one reboot
happens per run, and each check reboots at most once every 6 hours (markers `~/sunset/.netwatch-reboot`,
`.camwatch-reboot`), so neither a router outage nor a dead camera can cause a reboot loop. Before a
reboot it leaves the trusted time for the capture after it. A reboot costs about one capture and
clears transient experiment timers (`exp-*`).

- **Network (`NETWATCH=1`)**, for a Pi on a USB Wi-Fi dongle such as the CM4 (on 2026-11-13 its dongle
  dropped off and didn't rejoin until a power-cycle). It pings the default gateway through `wlan0`.
  After 10 minutes without an answer it unbinds and rebinds the dongle's USB device, once per outage (a
  software replug: the dongle rejoined in 6 s). After 30 minutes it reboots. If `wlan0` gets no answer
  it tries again through `eth0` (`NETWATCH_WIRED`, space-separated, empty for none), and an answer
  through either counts as online: with the cable working, a Wi-Fi outage is left alone. Until
  2026-11-24 it watched `wlan0` only, and rebooted on 2026-11-20 with Ethernet up while the new dongle
  had no driver. Tune with `NETWATCH_IFACE`, `NETWATCH_WIRED`, `NETWATCH_RESET_MIN`,
  `NETWATCH_REBOOT_MIN`, `NETWATCH_REBOOT_GAP_H`.
- **Cameras (`CAMWATCH=1`).** From 14:05 UTC 2026-11-19 both CM4 cameras failed captures on and off
  ("Failed to queue buffer for Unicam Image", "Device timeout") for 16 hours, until a reboot cleared
  it. It reads `capture.log` and counts, per camera, failed captures (5-minute, dense and night; not
  "FAILED publish", skips or retried warnings) since this boot within the last 60 minutes; 3 or more
  reboots. The failures came scattered, not in a row, which is why it counts within a window. Tune
  with `CAMWATCH_FAILS`, `CAMWATCH_WINDOW_MIN`, `CAMWATCH_REBOOT_GAP_H`.

**AIC8800 Wi-Fi dongle (CM4, from 2026-11-20).** The CM4's dongle is an AIC8800D80 (USB
`a69c:5723` at power-up, a69c:8d81 once running), on 5 GHz. Its driver isn't in the kernel, and this
unit has the older MCU revision (`chip_id=7, chip_mcu_id=1` in `dmesg`): with the current AIC
firmware the upload stalls at `0x170400` ("bin upload fail: 170400, err:-32", radxa-pkg/aic8800#49).
It needs the older V3 firmware set and the loader that matches it, from the `legacy-mcu1` branch of
`github.com/shenmintao/aic8800d80` (its D80 firmware is byte-identical to Radxa's SDK V3, commit
`254d47e`; `fmacfw_8800d80_u02.bin` is 327,037 bytes, SHA-256 `1ec680c2b63d...`). What is on the CM4:

1. The disk eject: `pi/sunset-aic-eject` in `/usr/local/sbin/` (mode 755) and
   `pi/90-sunset-aic8800.rules` in `/etc/udev/rules.d/`. Without them the dongle stays a disk.
2. The firmware: the branch's `fw/aic8800D80/` copied to `/lib/firmware/aic8800D80/`.
3. The modules `aic_load_fw.ko` and `aic8800_fdrv.ko` in
   `/lib/modules/6.12.109+rpt-rpi-v8/updates/aic8800/`, then `depmod -a 6.12.109+rpt-rpi-v8`. They
   load by themselves when the dongle appears. The branch's `aic_zlp_quirk` (a Bluetooth fix that
   hooks the kernel with kprobes) and `aic_btusb` are not installed.
4. NetworkManager's saved Wi-Fi connection, which it already had from the old dongle.

Building the modules (the CM4 runs the 64-bit kernel on 32-bit userland, so it cross-builds on
itself): `apt-get install gcc-aarch64-linux-gnu make`; `apt-get download
linux-headers-6.12.109+rpt-rpi-v8:arm64` and unpack it with `dpkg -x` (installing it wants an arm64
`gcc-12`, which can't be installed here), copy its `usr/src/linux-headers-6.12.109+rpt-rpi-v8` to
`/usr/src/` and link `/lib/modules/6.12.109+rpt-rpi-v8/build` to it (its `scripts` link uses the
installed 32-bit `linux-kbuild-6.12.109+rpt`, which works for any target); then in the branch's
`drivers/aic8800`: `make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
KDIR=/lib/modules/6.12.109+rpt-rpi-v8/build` (about 3 minutes; `nice -n 19` keeps capture unaffected).
A new kernel needs the modules rebuilt the same way, which is one more reason not to update it.
Not yet tested: the network watchdog's software replug (a USB unbind and rebind of the running dongle).

## 6. Freeze it
After a week of clean running: disable unattended upgrades and save a full image of the card (or
eMMC). That image is the recovery plan. Commands, and where to record the date, are under "Save and
restore the frozen image" below.

## Output (layout unchanged)
```
outbox/<cam>/YYYY/MM/DD/<cam>_YYYYMMDDTHHMMSSZ.jpg   # auto exposure
                                              .json  # exposure, gain, lux, colour gains
                                         _night.*    # extra long exposure when dark
outbox/<cam>/YYYY/MM/DD/system.json                  # what rarely changes, one per UTC day
capture.log                                          # one line per capture (see below)
sync.log                                             # one line per sync run
.system-state-<cam>.json                             # the day's records, so the sync can't lose them
ups.log, ups.log.1 ...                               # UPS monitor, CM4 only (see "UPS" below)
```
The sync sends the oldest files first, in batches of up to `SYNC_BATCH` files or `SYNC_BATCH_MB` (32),
and reads each batch back before deleting it. After `SYNC_MAX_S` (20 min) it stops between batches
and logs `sync partial confirmed=N pending=M`; the next run, at most 5 minutes later, carries on.
The unit's 60-minute `TimeoutStartSec` only catches a hung transfer (`sync interrupted`). On the
CM4's slow Wi-Fi the evening bracket leaves a backlog that drains over the next hour or two.
Each frame's `.json` holds rpicam-still's own camera fields at the top level, unchanged, plus these blocks:

| Block | Written by | Contents |
|---|---|---|
| `Sun` | `sunset-sun.py` | True-north azimuth, elevation, nearest sunset and minutes from it, from `SITE_LAT`/`SITE_LON` |
| `Capture` | `sunset-meta.py` | `schema_version`, camera, `kind` (`auto` or `night`), `setup_id`, `system_id`, slot and shot times, shot duration, settings asked for, the lux that triggered a night frame, size and SHA-256 of the JPEG |
| `System` | `sunset-meta.py` | The machine at that moment: uptime, load, free memory, CPU temperature, core voltage, ARM clock, `throttled`, free disk space, frames waiting to sync, SD sectors read and written, network state and Wi-Fi signal, NTP state, NAS mount and last sync; on the CM4 also the UPS (`ups_source`, `ups_charge_pct` and an `ups` block, see "UPS" below) |

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
- **Clock:** the CM4's RTC has no coin cell (as of 2026-11-12), so after a power cut it boots with a stale clock.
  Capture refuses to run (`SKIPPED: clock not synced`) until NTP has synced once this
  boot; later NTP outages do not stop it. `REQUIRE_TIME_SYNC=0` disables this.
- **Disk:** at 95% full or more the night frame is skipped, and with under 100 MB free nothing
  is captured. Tune with `DISK_SKIP_NIGHT_PCT`, `DISK_MIN_FREE_MB`.
- **Camera hang:** each `rpicam-still` call is limited to `CAPTURE_TIMEOUT_S` (60 s).

### UPS (`sunshine` only, issue #29)
The CM4 runs from a Mini-Box OpenUPS2, plugged into it by USB. `sunset-ups.service` (root, runs
`sunset-ups.py --run`) reads the board every 10 s over `/dev/hidraw`, read-only. Install it with
`sudo ./install.sh --ups`; `sudo python3 sunset-ups.py --once` prints one reading.

How it reaches the NAS, without extra writes to the eMMC:
- **Every frame:** `sunset-meta.py` copies the live status from `/run/sunset-ups.json` (RAM) into
  the frame's `System` block: `ups_source` (`mains`, `battery` or `usb`) and `ups_charge_pct`, plus
  `System.ups` with everything the board reports: `ok`, `age_s`, `source`, `pct`, `rte_min` (run
  time left, null when the board gives none; units unchecked), `vin`, `vout`, `vbat`, `cells` (V,
  three), `temps` (°C, three), `ichg`, `idchg` (A), `present` (which cells the board sees),
  `ups_state`, `chg_state`, `flags` (raw hex) and `fw`. A status older than 120 s (the monitor
  stopped) gives `ok: false, error: "stale"` and no readings, and `ups_source`/`ups_charge_pct` are
  null; so does a monitor that can't read the board (`error` says why). A Pi without the monitor
  has no UPS fields at all.
- **The log:** `ups.log` (a line on each change beyond its deadband, on each event such as
  `mains_lost`, `mains_back`, `low_battery`, `temp_high`, `ups_lost`, and a keyframe every 4 h;
  rotated daily or at 256 KB, 14 kept) is copied by the sync, with the config backup, to
  `project_sunshine_config/<host>/ups/ups-<UTC of its first line>.log`. A file is copied again only
  when its size on the share differs.

On battery with a cell under `UPS_LOW_CELL_V` (3.3 V; 3.45 V until 2026-11-21, which sat just
under where the cells rest with R20 unchanged; the board keeps saying 100% charge on battery, so
the cell voltage is the only test), it stops whichever of the
capture, dense (both cameras) and sync timers are running, flushes the disks and logs
`capture_paused units=...`; when mains returns it starts the same ones again. It never halts the
Pi. If the diag page ends during a pause, it adds its camera timers to the pause
(`/run/sunset-ups.paused`) instead of starting them on battery; while diag is on when mains
returns, the camera timers are left for diag to start. A full or read-only SD card no longer stops
the monitor: the failure goes to the journal once and polling continues. Settings: `UPS_*` in
`sunset.env.example`. Home Assistant's on-battery alert is described under "Monitoring beyond
frame age".

### Next sunset, for scheduling
```
python3 sunset-sun.py sunset            # next sunset after now, UTC ISO
python3 sunset-sun.py sunset --epoch    # Unix seconds
python3 sunset-sun.py sunset --json     # plus sunset azimuth
python3 sunset-sun.py position          # sun now
```

### Good-sunset notification (sky score)
`sunset-sky.py` (from `sunset-sky.timer`, every 15 minutes) scores each sunset once, about 40 minutes
after it: the same sky score as `tools/build_video.py` and the reports, on the `cm4wide` frames from
35 minutes before to 25 after sunset, read from the share (and the outbox for any not synced yet). It
writes `project_sunshine_sky/cm4wide/<local date>.json` next to `project_sunshine/` on the share, with
the score, its label, the best frame's name and the sunset time, and no `Sun` block or coordinates.
One line a day goes to `~/sunset/sky.log`. Home Assistant reads the newest file and notifies when the
score reaches `input_number.sunset_sky_post_threshold` (60): see "Monitoring beyond frame age".
It needs Pillow: `sudo apt-get install --no-install-recommends python3-pil` (16 packages, in
`keep-packages.txt`). Settings, all optional: `SKY_FULL_WARM` (the camera's scale, 0.178 for
`cm4wide`, as in `nas/crop.cm4wide.json`), `SKY_ROWS`, `SKY_DELAY_MIN`, `SKY_GIVE_UP_H`, `SKY_OUT`,
`SKY_LOG`. Run it by hand with `python3 ~/sunset/sunset-sky.py` (with `sunset.env` loaded): it does
nothing outside 40 minutes to 6 hours after a sunset, or when that evening already has its file.
The Pi decodes with Pillow where the PC uses ffmpeg, and on Nov 12-22 it read 0 to 4 points higher
than the PC's score for the same frames (most on colourful evenings), so a borderline day can notify
at 60 and show 57 in `build_video.py`.

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
diag                    # on for 30 minutes; running it again restarts the clock
diag start i2c@1        # start on another camera (port ID or number); add 180 to rotate it
diag status             # is it on, and what is the link
diag stop               # off
```
It stops by itself and does not come back after a reboot. On a Pi with two cameras the page has a
button for each (above "Full frame"); production's camera is shown with its `ROTATION`, another one
as read. **Capture pauses while the page is on** (from 2026-11-17): starting it stops the capture
and dense timers of both cameras, and they start again when it ends, by `diag stop`, the time limit
or a crash. Each session is a gap in the series, and restarting the timers takes one extra frame
straight away (systemd 252). The camera only runs while the page is open. Don't run `sunset-selftest.sh` or a manual
capture while the page is open, because only one program can use the camera at a time.

The page has no password: while it's on, anyone on your LAN can see the camera and the logs, and
switch the view. It shows no Pi health (removed 2026-11-22); `tools/camera_check.py` does that. Don't forward its port through the router.

Without the page, with a monitor on the Pi, `rpicam-hello -t 0 --roi 0.4,0.4,0.2,0.2` gives a live view zoomed 5x into the centre.
Stop the capture timer first.

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
6. **Check the age.** `sensor.sunset_cm4_newest_frame_age` (`cm4wide`) and
   `sensor.sunset_cm4city_newest_frame_age` should show under 20 minutes within 5 minutes. Each camera
   has its own sensor, binary sensor and alert. For another camera, copy those three blocks and pass its
   `CAM_NAME` to the script. The Pi 3 `timelaps` (`wide`) was retired on 2026-11-17, and its blocks
   were taken out of the package on 2026-11-20: in an installed copy, delete the `Sunset newest frame
   age` sensor, the `Sunset frames stale` binary sensor and the `sunset_frames_stale` alert (and the
   `wide` health, archive and daily-health blocks, if installed), plus their lines in the re-arm
   automation.
   **Updating an installed copy:** HA's `sunset.yaml` holds your phone notifier, so don't overwrite
   it. Copy the new `sunset_frame_age.sh` over the old one, and paste the new CM4 blocks into HA's
   `sunset.yaml` (and your phone under the new alert's `notifiers`), then check and restart.
7. **Test that it fires and clears.** Capture keeps running. Set `input_number.sunset_max_frame_age`
   to 1 and wait up to 15 minutes for the notification, then set it back to 60: the "again" message
   should arrive straight away.

With the default settings, an alert comes 70 to 75 minutes after the last frame, then repeats every
6 hours until frames return or you acknowledge it.

### Monitoring beyond frame age

**Installed 2026-11-20.** HA's copy (`/homeassistant/packages/sunset.yaml`, written with the File
editor add-on; HA is on port 80) is the repo's `sunset.yaml`. The scripts are in `/config/sunset/`:
`sunset_frame_age.sh`, `sunset_nas_free.sh`, `sunset_camera_health.sh` and `sunset_ups.sh`. HA's copy
adds the phone (`mobile_app_pixel_8`, from 2026-11-20) under every alert's `notifiers`; the repo keeps
the placeholder. To update, copy the
scripts over and re-make HA's `sunset.yaml` from the repo's (keeping any phone lines), check the
configuration, restart.

The package alerts on:
- each CM4 camera's frame age (`cm4wide`, `cm4city`);
- NAS free space (default 100 GB, about a month of frames at about 3 GB a day with no DNGs);
- each camera's health from its newest frame's JSON: undervoltage and throttle bits, temperature,
  frames waiting to sync, disk use, tiny or repeated JPEGs;
- **the CM4 on battery** (`sensor.sunset_ups`, from `System.ups_source` and `ups_charge_pct` in the
  newest `cm4wide` frame; `homeassistant/sunset_ups.sh`): anything but `mains` for 2 minutes, which
  includes a stale UPS status, and a newest frame over `UPS_MAX_AGE_MIN` (60) minutes old
  (`unknown old_frame`: with captures failing, an old "mains" says nothing about the power now),
  repeating hourly. A power cut shows up within about 5 to 10 minutes
  (the next frame, then the 2-minute scan). Tested with a real cut on 2026-11-20. Just after HA
  restarts the sensor is `unknown` for up to 2 minutes, and the alert can fire once in that time;
  its message says so;
- **UPS numbers for graphs** (2026-11-20): `sensor.sunset_ups` runs `sunset_ups.sh cm4wide --json`
  and carries every value as an attribute, and ten template sensors turn them into numbers HA records
  and graphs: charge %, input, output and pack voltage, each cell's voltage and temperature
  (`sensor.sunset_ups_cell_1_voltage` and so on). Input voltage stands in for "mains": about 15.2 V on
  mains, 0 on the cells. The board reports no discharge current or run time, so there are no sensors
  for those. A value the frame lacks (stale UPS status) is a gap in the graph, never a 0. The same
  script also gives the CM4's CPU temperature from that frame (`sensor.sunset_cm4_cpu_temperature`);
- **a good sunset** (2026-11-22): `sensor.sunset_sky_score` (`homeassistant/sunset_sky.sh cm4wide`)
  is the newest evening's score from the Pi's `sunset-sky.py` ("none" when too few frames), with the
  date, label, sunset time and best frame as attributes. The `sunset_good_sunset_notify` automation
  sends one notification an evening when the score reaches `input_number.sunset_sky_post_threshold`
  (60), and only within 12 hours of that sunset; `input_text.sunset_sky_notified_date` remembers the
  last evening announced. It is an automation, not an alert, so the phone goes in its `action` list
  (a commented example is there), not under `notifiers`. Lower the threshold briefly to test it on an
  evening that has a score, then set it back. Building and posting the video stay by hand;

Anything unknown counts as bad. Python 3 is needed in HA's container. An alert you acknowledge is
re-armed after 12 hours.

There is no outside heartbeat for Home Assistant itself (decided on #22).

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
- The repo holds a reference copy of the CM4's settings in `pi/hosts/cm4.env`. It leaves out the
  site coordinates and anything secret, so it is a start, not a full `sunset.env`. If it is not
  there, use the old Pi's `sunset.env`, or
  `sunset.env.example` and the values in `../CLAUDE.md` and `../changelog.md`.

### `sunshine` (CM4 on the MyPi board, eMMC)
The CM4's storage is on the module, so a blank eMMC cannot be flashed like a card. It has to be
exposed to the PC as a disk first. (The retired Pi 3 `timelaps` had its own list; it is in git
history before 2026-11-21.)
1. **Expose the eMMC.** On the PC, install `rpiboot` (the Raspberry Pi `usbboot` tool). On the
   board, set the boot jumper or switch that stops the CM4 from booting from its own eMMC, and
   connect the board's USB port for this to the PC. Which jumper, which port and whether the board
   must be powered first: check the board manual (Embedded Micro Technology MyPi Industrial IoT
   Integrator Board XT). Then run `sudo rpiboot`. After a few seconds the eMMC shows up as a
   disk (`lsblk` on Linux; 29.1 GB on this module).
2. **Flash.** Raspberry Pi Imager: choose that disk, Raspberry Pi OS Lite Bookworm 32-bit, hostname
   `sunshine`, user `sunshine`, SSH with a key. This module has no Wi-Fi, so use Ethernet first.
   The 32-bit userland boots the 64-bit kernel (6.12.109-v8 was used).
3. **Boot normally.** Unplug the USB cable, put the boot jumper back (check the board manual), power
   the board. `ssh sunshine@sunshine.local`, then `sudo apt update && sudo apt full-upgrade`.
4. **Overlays.** In `/boot/firmware/config.txt`:
   - `camera_auto_detect=0`
   - `dtoverlay=imx477,cam0` and `dtoverlay=imx477,cam1` (both cameras; `install.sh --cm4-two`
     writes both). rpicam then numbers CAM1 as camera 0 and CAM0 as camera 1, which is why each
     camera's settings name it by port (`CAMERA=i2c@0`, `CAMERA=i2c@1`), never by number.
   - `dtoverlay=i2c-rtc,ds1307,addr=0x68` (the board's DS1338 clock)

   Reboot. Let NTP set the clock once; the kernel then writes it back to the RTC every 11 minutes.
   There was no coin cell in the RTC holder on 2026-11-12 (whether one is fitted now: not recorded,
   check on the board), so the RTC only keeps time through a reboot, not a power cut.
5. **Camera check.** `rpicam-hello --list-cameras` must list two imx477, one on `i2c@0` (CAM0)
   and one on `i2c@1` (CAM1). Then `rpicam-still -n --camera 1 -t 3000 -o test.jpg` for CAM0.
6. **Packages.** `sudo apt install -y rpicam-apps-lite rsync python3 cifs-utils`, and the CM4 notes
   in section 5 (`linux-image-rpi-v8`, USB Wi-Fi firmware) before any trimming. The pilot CM4 went
   from 615 to 383 packages.
7. **Copy `pi/` to `~/sunset`**, flat, with `systemd/` as a subfolder: from the PC,
   `scp -r pi/* sunshine@sunshine.local:sunset/` (make the folder first), then
   `chmod +x ~/sunset/*.sh`. Restore `sunset.env` from `pi/hosts/cm4.env` plus the real `SITE_LAT` and `SITE_LON`.
   It must set `CAM_NAME=cm4wide`, `CAMERA=i2c@0` and `ROTATION=0`, and `NETWATCH=1` if the Pi is
   on the USB Wi-Fi dongle. For the second camera, `cp sunset2.env.example sunset2.env`
   (`CAM_NAME=cm4city`, `CAMERA=i2c@1`, its own `SETUP_ID` and night settings). The other values the CM4 has used (night shutter, white balance, `SETUP_ID`) are
   in `../changelog.md`.
8. **Wi-Fi.** If the CM4 is on the dongle, join the network (`nmcli` or `raspi-config`). The dongle's
   firmware is in the kept packages. Dongle details beyond "old Buffalo 2.4 GHz USB": not recorded,
   check on the Pi.
9. **NAS login and mount.** Create `/etc/sunset-nas.cred` (root-only, section 3) and add the
   `/etc/fstab` line from section 3. Then `sudo mkdir -p /mnt/nas-camera`, run
   `sudo systemctl daemon-reload`, and check `ls /mnt/nas-camera/project_sunshine`. `NAS_TARGET` in
   `sunset.env` must be `/mnt/nas-camera/project_sunshine/`. Frames go to
   `project_sunshine/cm4wide/` and `project_sunshine/cm4city/`.
10. **Install.** `cd ~/sunset && sudo ./install.sh --cm4-two --ups`, with no `--enable`
    (`--ups` starts the UPS monitor; see "UPS" above). It writes the
    cam0 and cam1 overlays (and changes nothing if step 4 already did). It installs the second camera's
    units too (`sunset-capture2`, `sunset-dense2`, 30 s after the first camera's); with `--enable` it
    starts them only if `sunset2.env` exists.
11. **Low wear.** `sudo ./sunset-lowwear.sh`, then reboot.
12. **Experiments and the weather units.** `mkdir -p ~/sunset/experiments` and copy the repo's
    `experiments/` into it (the unit runs `~/sunset/experiments/sunset-weather.py`). For the weather
    log, copy `~/sunset/experiments/systemd/exp-weather.service` and `exp-weather.timer` to
    `/etc/systemd/system/`, change `User=` and the `/home/pi/` path in the service to this Pi's user
    and home, then `sudo systemctl daemon-reload` and `sudo systemctl enable --now exp-weather.timer`.
    Re-create any `exp-*` timers from the notes you made before the wipe. They are transient, so a
    reboot clears them, and they are not part of the production capture.
13. **Self-test.** `./sunset-selftest.sh`.
14. **Check `CAM_NAME` before the timers start.**
    `grep -E '^(CAM_NAME|CAMERA|ROTATION|SETUP_ID|NETWATCH)' ~/sunset/sunset.env` must show
    `CAM_NAME=cm4wide`, `CAMERA=i2c@0` and `ROTATION=0`, and `sunset2.env` must show
    `CAM_NAME=cm4city` and `CAMERA=i2c@1`. The units read `sunset.env` with `EnvironmentFile=-`,
    so a missing file falls back to the script defaults (`CAM_NAME=wide`) and the frames would land
    in the wrong folder.
15. **First frame.** `sudo systemctl start sunset-capture.service`, then `ls -R ~/sunset/outbox`,
    `tail ~/sunset/capture.log` and `sudo systemctl start sunset-sync.service`. The log line must
    end in `ok` and say `cam=cm4wide`, the
    JPEG must be upright, and the JSON `Capture.settings` must say `camera: i2c@0`. Check that the
    frame is under `cm4wide/` on the NAS and not in `wide/`. Then `sudo systemctl start
    sunset-capture2.service`: `cam=cm4city`, `camera: i2c@1`, frames under `cm4city/`.
16. **Start.** `sudo systemctl enable --now sunset-capture.timer sunset-sync.timer
    sunset-dense.timer sunset-capture2.timer sunset-dense2.timer sunset-guard.timer`, and check
    `systemctl list-timers 'sunset*'`. Each camera has its own Home Assistant alerts (`cm4wide`,
    `cm4city`); they should stay quiet, or clear within about 75 minutes.
17. **Record it.** Add a `changelog.md` entry: date, what was restored, the new `SETUP_ID` if it
    changed, and the gap in frames.

## Save and restore the frozen image
Make an image after a week of clean running, and again after any change to the setup. Keep one copy
somewhere other than the NAS that holds the frames.

**eMMC (`sunshine`).** Expose the eMMC with `rpiboot` as in step 1 of the `sunshine` list. Then use
these commands, with the disk `rpiboot` created as `/dev/sdX`. Check the device twice: `dd`
overwrites without asking.
```
sudo dd if=/dev/sdX of=sunshine-YYYYMMDD.img bs=4M status=progress conv=fsync
sha256sum sunshine-YYYYMMDD.img > sunshine-YYYYMMDD.img.sha256
xz -T0 sunshine-YYYYMMDD.img            # optional, saves space
``` To
restore, expose a blank or damaged eMMC the same way and `dd` the image onto it
(`xz -dc sunshine-YYYYMMDD.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync`). The image is the
size of the whole eMMC (about 29 GB), so it needs a device at least that big. Then run steps 13 to
16 of the `sunshine` list.

An image holds the `sunset.env` and `SETUP_ID` from the day it was taken. After a restore, compare
them with the live values you saved before the wipe.

**Last image.** Fill this in each time one is made, and add a `changelog.md` entry.

| Host | Date | Stored at | SHA-256 file | Notes |
|---|---|---|---|---|
| `sunshine` | none yet | not recorded | not recorded | |
