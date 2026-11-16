# Changelog

The history of Project Sunset, newest first: every change (code, settings, hardware, including changes made only on a Pi, marked **Pi**) and every event that affects the record (outages and lost frames, power cuts, camera moves, weather that matters, good sunsets, solstices, the moon, milestones). Dates are Vancouver local time; times are given in UTC and Vancouver. Decisions and their reasons are in `CLAUDE.md`.

## 2026-11-16

- **Repo hygiene (#26 closed):** the NAS host name and login user are out of the docs and `CLAUDE.md` (still in old commits); `tools/build_video.py` now reads the share path from `SUNSET_NAS` or `--nas` instead of a built-in host. The netwatch tests use a documentation address (192.0.2.1). Backlog items 4, 5, 7 and 9 are now issues #32-#35. Issues #5, #18 and #25 closed.
- **Pi (both): sunrise dense frames stopped** at about 04:45 UTC (Nov 15, 9:45 pm Vancouver), Steven's decision (#21). New setting `DENSE_WINDOWS` in `pi/sunset-capture.sh`, default `sunset`; `"sunrise sunset"` brings sunrise back. On the Pis only that hunk was patched into the running script (old file kept as `sunset-capture.sh.bak-20261116-dense`); the rest of the merged code is still not deployed. Checked on each Pi with a fake sun script answering "sunrise": no frame, nothing logged. The last sunrise dense frames were on the morning of Nov 15. The sunset dense frames are unchanged.
- **Pi (both): the sunset program every evening** (#10): `experiments/sunset-nightly.sh` from `exp-sunset.timer` at 23:00 UTC, which waits until 47 min before tonight's sunset and runs the sunset program for 45 min either side (runs `sunset-YYYYMMDD` on `timelaps`, `cm4-sunset-YYYYMMDD` on the CM4, by the UTC date of sunset). A unit file, so a reboot doesn't clear it. First run: the sunset of 00:28 UTC Nov 17 (5:28 pm Nov 16 Vancouver). Adds about 1-2 GB a day to the experiments folder.
- **Decisions (Steven), walking through the open issues; each answer is posted on its issue and summarised in `CLAUDE.md`.** Keep every DNG from both cameras and buy disks (#5, #9); no second copy (#13). Build the ev+0/ev-2 sunset profile into production, run a sunset experiment every evening until then, freeze settings on Dec 14 with a `PROFILE_ID` (#10). `cm4wide` is the official series; aim as in #4 (#11 closed into #4); wired Ethernet to the CM4; the CM4 camera stays upside down (#12). The daily video stays the whole day, no master render, sunrise dense frames to stop (#21); gap handling in the long film decided at edit time (#20). Instagram: public with towers blurred, city in the caption, a licensed track, posting gated by a sky score of 60, login still open (#2). Frame JSON is private: strip `Sun` before publishing (#25). No outside heartbeat (#22). UPS cells: name-brand Li-ion with the R20 change (#29). Nothing on the Pis has changed yet.
- **Issue loop (repo only, not committed, nothing deployed).**
  - **Sync read-back (#13):** on the mounted share the Pi's copy is deleted only after the NAS copy is read back: same size, the same SHA-256 for files up to `SYNC_VERIFY_HASH_MAX_MB` (8 MB: JPEG, JSON), the same first and last 64 KiB for the DNG. A file that fails stays on the Pi, its bad NAS copy is removed and it is sent again. Over SSH rsync still deletes. Not tried on the real CIFS share: whether dropping the page cache makes the read reach the NAS is unproven.
  - **Config backup (#23):** the sync copies `sunset.env`, `/etc/fstab` and the boot `config.txt` to `project_sunshine_config/<host>/` on the share when they change and once a UTC day (`SYNC_CONFIG_BACKUP`). It never copies a `.cred` file or a file with a password line. `sunset.env` holds the site coordinates; the share is private.
  - **Capture needs `sunset.env` (#23):** without it (missing or empty) the regular frame logs `SKIPPED` and exits 1, the dense frame exits quietly (`REQUIRE_ENV_FILE`, on unless the caller sets `OUT_ROOT`). A rebuilt CM4 can no longer write into the `wide` series.
  - **Sunset merge `--redo` (#18 part 1):** `tools/build_video.py --redo --fuse-run` now undoes the blend, removes every fused frame and fuses again; an interrupted blend keeps the pre-blend frames in `.preblend/` and can't blend a frame twice.
  - **`tools/register_day.py` checked on real frames (#20):** it now finds the Nov 5 reseat (scene −1,415 px) and the Nov 8 refocus (−687, −205, +2°), which it missed before (rotation search, response limit 0.10), and the Nov 12 nudge (−35); quiet days read under 2 px.
  - **README:** stale lines fixed (#26), and a power and data wiring diagram, `docs/system-diagram.svg`, drawn by `tools/system_diagram.py`, with the planned UPS (#29).
  - **Docs:** the CM4's LAN address removed from `CLAUDE.md` and this file (#26).
- **Event, found 2026-11-16 by `register_day.py`, camera moves nobody had recorded (`wide`):**
  - Nov 5, 23:15-23:30 UTC (3:15-3:30 pm): the scene moved +1,690, +185 px, the camera turned back left, about 280 px past where it was on Nov 4. Earlier that afternoon it crept about 20 px down after the reseat.
  - Nov 12, 00:30-00:35 UTC (Nov 11, 4:30-4:35 pm): the scene moved about 65 px down (camera tipped up), just after the recorded nudge; about 8 px more settling through Nov 12, including a ~6 px step at about 21:00-22:00 UTC (1-2 pm).
  - `cm4wide` on Nov 12 sits 9.6 px off its Nov 13 position.
- **Event:** the NAS share had 126 GB free (99% full) at about 00:45 UTC, about 5 days at 25 GB a day (#7).

- **Project review and fixes (issues #7 to #27). Repo only: nothing is on the Pis, the NAS or Home Assistant yet.** Merged to `main` with PR 28 at about 02:55 UTC (7:55 pm Nov 15 Vancouver), after a test fix: the clock-marker case raced on a fast CI runner (two frames in the same second).
  - **Capture (`pi/sunset-capture.sh`, `sunset-netwatch.sh`, `sunset-selftest.sh`):** a network-watchdog reboot no longer stops capture until NTP returns: netwatch leaves the time in `~/sunset/.clock-trusted` and the first capture after the boot trusts the clock if it reads within `CLOCK_TRUST_MAX_S` (900 s) of it (#8). `timeout -k`, the lock's file descriptor closed for children, an `ABORTED line N` log line on any unexpected exit, one retry for a quick camera failure, complete frames rescued from `.partial`, a warning for a missing DNG, and a failure counter with an optional reboot (`CAPTURE_FAIL_REBOOT`, off by default) (#15). A failing sun script now logs `WARN dense: sun script failed` instead of silently stopping dense frames (#16). The self-test takes the capture lock. `capture.log` and `netwatch.log` rotate by size.
  - **Camera lock (#14):** the experiment runner and the diag page take `.sunset-capture.lock` while they hold the camera; diag also yields to the 1-a-minute dense frames; the runner's shot timeout is its estimate plus 15 s.
  - **Sync (`pi/sunset-sync.sh`):** `--fsync` when rsync has it, zero-length images kept and logged instead of shipped, oldest-first batches (`SYNC_BATCH`), a line in `sync.log` when the unit timeout stops a sync, log rotation. It still deletes on rsync's word without reading the NAS copy back (#13, open).
  - **Metadata:** `sunset-meta.py` has an overall deadline (`META_DEADLINE_S`, 15 s), writes `Capture` before probing `System`, caches the daily version probes, and records eMMC `life_time` / `pre_eol_info`. A frame with no rpicam metadata still gets its `Sun` and `Capture` blocks, flagged `rpicam_metadata`. `Sun` gains `algorithm: "noaa-1"`; weather files gain `schema_version`.
  - **Daily video (`nas/sunset-daily.py`, record `schema_version` 2):** bad JPEGs are dropped and counted, ffmpeg runs with `-xerror` and the frame count is checked, only regular frames count towards "enough frames", days with a gap over 60 min (20 min near sunset) are skipped, failed days get a `failed` record and are retried (#17). Blur, view and sky settings live in each calibration entry with a `setup_id`; a mismatch with the frame sets `setup_mismatch` and `post_ok: false` (#19). `provenance` block. Sky score is the mean of the best 5 frames (the old value is kept as `score_best_frame`). Output is converted to and tagged BT.709. Dockerfile pinned by digest and package version. Optional, off by default: a sunset-only cut (`SUNSET_CUT=1`), a master render (`MASTER=1`) and opt-in redo rules (#21).
  - **New NAS jobs:** `nas/sunset-verify.py` checks JPEGs and DNGs against the SHA-256 in their JSON (#13); `nas/sunset-health.py` writes a daily health record per camera (#22). Not scheduled yet.
  - **Home Assistant (`homeassistant/`):** new sensors and alerts for NAS free space (#7), each Pi's health from its newest frame, the daily video's status, and the two NAS jobs' results; a frame named in the future no longer reads as fresh; acknowledged alerts re-arm after 12 hours; a separate heartbeat package. Not installed in Home Assistant yet (steps in `docs/setup.md`).
  - **New PC tools:** `tools/register_day.py` (how far the camera has moved against a reference, #20) and `tools/sunset_stills.py` (one still per evening for the horizon-swing piece, #21). Tested on synthetic images only. `tools/issue_blur.py` refuses a setup it has no outlines for.
  - **Install and recovery:** `install.sh --uc517-cam0` for the CM4, `try-restart` of the kernel log unit; reference settings per Pi in `pi/hosts/` (several values marked unverified); "Rebuild a Pi" and "Save and restore the frozen image" in `docs/setup.md` (#23). `pi/sunset.env.example` lists every setting; `.gitignore` covers `sunset.env*` and `*.cred` (#26).
  - **Tests and CI:** `.gitattributes` makes every text file LF; `tests/run.sh` runs every `tests/test_*.py`; a GitHub Actions workflow (not run yet) (#24). Linux: 887 passed, 0 failed (was 262 and 10).

- `pi/sunset-diag.py`: new **Centre lines** button on the diag page, for lining up the cameras. It draws the frame's centre lines over the live view (cyan, 50% opaque) with a ruler every 5% across and down, labelled every 10%. The full view is the whole sensor, so 50% is the middle of the frame; in the centre focus view only the cross shows, and on a picked spot nothing. **Pi (both):** installed at 00:35-00:50 UTC (Nov 15 17:35-17:50 Vancouver); old file kept as `~/sunset/sunset-diag.py.bak-20261116`. No capture change.

## 2026-11-15

- **Event:** clear and sunny afternoon; `timelaps` reached 63 °C at 23:35 UTC (4:35 pm) and its soft temperature limit (CPU slowed to 1.2 GHz), with captures on time.
- **Event:** the CM4's Wi-Fi dropped for about 2 minutes at 05:56 and 20:13 UTC (Nov 14 22:56 and Nov 15 13:13 Vancouver) and rejoined by itself; no frames lost.
- **Pi (both):** both Pis rebooted together at about 19:25 UTC (12:25 pm), probably a power cut. Each skipped one capture (clock not yet synced). The reboot cleared the transient moon timers; `moon-1` to `-9` and `cm4-moon-1` to `-9` were recreated at 23:4x UTC with the same times and arguments.
- Sunset runs Nov 12-14 analysed on both cameras with a new flicker number (mean minute-to-minute change of the sky band). The Nov 12 flicker is real cloud, not auto exposure; ev-2 roughly halves it. The CM4 runs since the background upload have no gaps. Results on issue #3.
- `tools/fuse_sunset.py`: new `blend_run`, a 1:2:1 blend of each sunset minute with the minutes either side, run by default after the merge (CLI and `tools/build_video.py --fuse-run`; `--no-blend` skips it). On Nov 12 it cut the video's worst minute-to-minute change from 17 to 11. Tests in `tests/test_fuse_sunset.py`.
- **UPS (OpenUPS2), evening of Nov 15:** Identified the UPS board as a Mini-Box **OpenUPS2** (USB `04D8:D005`, rev 0003, reports itself as `OPEN-UPS2`), read from Windows at about 7:10 pm (02:10 UTC Nov 16) with the board on USB. It takes 11-24 V in and gives 12-24 V out, so it goes on the CM4 `sunshine` (MyPi XT, 9-28 V in), not `timelaps`. It is built for LiFePO4 cells; the 18650-34T Li-ion cells need a resistor change (R20 to 576k) and Mini-Box's Li-ion firmware 1.6 to charge fully. Firmware version not read yet, nothing flashed. Downloaded Mini-Box's Windows configuration tool (`OpenUPS2-installer.zip`, official link, unsigned NSIS installer) to read it. Board, cells, firmware and the planned setup are documented in issue #29. The exported settings show an unconfigured LiFePO4 board (`CHG_BAT_TYPE` 1, charge stop 3.5 V per cell, write count 0) with charge temperature limits of -20 to 75 °C, older than the firmware 1.2 defaults.
- Decided: the UPS runs the three 18650-34T Li-ion cells, with R20 changed to 576k and Mini-Box's Li-ion firmware 1.6. Downloaded the firmware and the flasher (`HIDBootLoader.exe`, from Mini-Box's OpenUPS firmware pack) from Mini-Box's own site.
- Flashed the UPS from firmware v1.1 to v1.6 Li-ion at about 7:29 pm (02:29 UTC Nov 16), over USB with no cells or DC input; verified OK. It loaded the Li-ion defaults: 4.1 V per cell charge stop, 3.3 V / 3.0 V cut-offs, charging only between 5 and 55 °C. R20 is not changed yet, so the cells stay out until it is.
- Set the UPS's capacity to 3400 mAh and narrowed charging to below 40 °C (warm) and 45 °C (hot), at about 7:32 pm (02:32 UTC Nov 16). Written, restarted and checked against a fresh export.
- Planned the UPS integration on the CM4 (plan and decisions on #29): our own read-only Python reader for the UPS status (not NUT), events in `ups.log` written only on change with a keyframe every 4 hours and rotated daily, a bench test before the CM4, pause the capture on low battery instead of shutting down, a Home Assistant alert later, and the UPS state in each frame's metadata after the pending `sunset-meta.py` work merges. Nothing built yet.
- Wrote the UPS reader, `pi/sunset-ups.py` (standard library only, read-only), its offline tests (`tests/test_ups.py`, 25 pass) and `pi/systemd/sunset-ups.service`. Not installed on any Pi, and not yet in `install.sh`. It polls every 10 s and writes `ups.log` only when a value moves past its deadband, on events (mains lost or back, low battery, cell missing, over 40 °C, UPS lost or found) and every 4 hours; the live status goes to `/run/sunset-ups.json`. The log rotates daily or at 256 KB, 14 files kept. On battery with a cell under 3.45 V or 10% or less charge, it stops the capture, dense and sync timers and starts them again when mains returns.
- Bench-tested the reader on this PC against the real UPS (WSL, USB passed through with usbipd-win), 7:47 to 7:51 pm (02:47 to 02:51 UTC Nov 16). With the board steady (USB only, no cells), 75 polls wrote only keyframes; size rotation and a clean stop worked. Unplugging the UPS mid-run wrote one `ups_lost` line, then one `ups_found` line when it came back. Battery, low-battery and pause behaviour are tested offline only, until R20 is changed and the cells are in.
- Steven measured the three 18650-34T cells at about 8:10 pm (03:10 UTC Nov 16): 1.183, 1.144 and 1.166 V. That is deeply over-discharged for Li-ion (below 2.5 V), so they are not to be installed or charged. Remeasure directly on the cell terminals; if confirmed, recycle them and get a fresh matched set.
- Added `tools/ups_bench.py`: runs the UPS reader on the bench (WSL as root) with test settings, files only in its own folder, the timer pause off, then summarises the log and warns about any present cell below 2.5 V. Tried for 30 s against the real board.
- All of Steven's 18650 cells were found dead and recycled (Nov 15 evening). New cells are still to be chosen and bought. Recommended: LiFePO4, which means flashing the LiFePO4 firmware 1.5 back with no R20 change; name-brand Li-ion with the R20 change is the longer-runtime option. Options and next steps are on #29.
- Merged `main` (PR #28, the project review fixes) into the UPS branch with no conflicts.

## 2026-11-14

- **Event:** overcast with drizzle at sunset. The sunset runs `sunset-6` and `cm4-sunset-3` shot the full 84 minutes with no gaps.
- **Event:** the CM4's Wi-Fi dropped for about 2 minutes at 22:09 UTC (3:09 pm) and rejoined by itself.

## 2026-11-13

- **Event:** rain at sunset (1.4 mm forecast). The sunset runs `sunset-5` and `cm4-sunset-2` shot the full 84 minutes, the first CM4 run with no gaps.
- **Event:** the CM4's Wi-Fi dropped for about 2 minutes at 05:53 and 13:19 UTC (Nov 12 22:53 and Nov 13 06:19 Vancouver) and rejoined by itself.

### Same setup on both cameras
- **Pi (`timelaps`):** updated `sunset-capture.sh` and `sunset-diag.py` to the repo versions at 07:37 UTC (00:37 Vancouver), so both Pis run the same code. The only difference was the `ROTATION` setting, which defaults to 0. The 07:40 capture ran cleanly. Old files kept as `*.bak-2026-11-13`.
- **Pi (CM4):** scheduled the moon runs `cm4-moon-1` to `-9` (Nov 17-25 UTC) at the same times and with the same arguments as `moon-1` to `-9` on `timelaps`.
- Remaining differences between the two `sunset.env` files are deliberate: the CM4 night settings matched to its lens (`NIGHT_SHUTTER_US`, `NIGHT_AWB`, `NIGHT_LUX`), `ROTATION`, `SETUP_ID`/`SETUP_NOTE` and `NETWATCH`.
- `timelaps` has had no Ethernet link since about Nov 5 and is on its built-in Wi-Fi.

### Experiment runner: upload in the background
- The runner's half-hourly NAS upload blocked the camera. On the CM4's slow Wi-Fi each upload took about 7 minutes, so `cm4-sunset-1` lost 00:19-00:25 and 00:49-00:55 UTC, the first 15 to 9 minutes before sunset.
- `Run.upload` now copies in a background thread, sending only the files present when it is called (between shots, so none is half-written). The end of a run waits for everything. Tests in `tests/test_experiment.py` (`BackgroundUpload`).
- Last night's sunset analysed on both cameras (`sunset-4`, `cm4-sunset-1`), partly cloudy with a clear band at the horizon: E holds the glow before sunset on both, and daylight white balance turns the sky grey-brown by 30 minutes after, as on the overcast nights.

## 2026-11-12

- **Event:** a good sunset, partly cloudy with a clear band at the horizon: sky score 67 on both cameras, the second good one of the pilot (after Nov 8). Thin cloud crossing the glow 15 to 20 minutes before sunset is what made the video flicker.
- **Event:** one undervoltage warning on `timelaps` at 21:51 UTC (2:51 pm), the fourth since the new supply; no frames lost.

### Handoff update (Nov 13)
- Brought `README.md` up to date as the handoff: current state, the sunset flicker as the blocker, next steps, uncommitted work, the two cameras. `CLAUDE.md` has the detailed next-session notes.

### Notes for tomorrow (Nov 13)
- Steven said the Nov 12 video is not good enough to post because of flicker around sunset. Wrote the state, the questions to answer and the ideas into `CLAUDE.md` ("Next session"). No code changed.

### Instagram video, third round (00:10 Vancouver, Nov 13)
- **Crop:** the `view` in `nas/crop.cm4wide.json` is now top 100, height 2440 (was 1600): the whole scene with just the lower balcony cut off. 2,560 still showed a sliver of rail at the bottom left.
- **Exposure:** Steven said the merged sunset exposure looks better. Kept.
- **Jitter at sunset:** frame times were fine (a frame every minute, no camera shift). The cause was in `tools/fuse_sunset.py`: the bracket has gaps (one minute in five, and 7 minutes from 00:19 to 00:25 UTC), and gaps were filled by repeating a neighbour's picture, so the video froze for several frames and then jumped by 21 levels. Now an unpaired frame keeps its own picture and takes the fusion's gain (exposure and colour, worked out at 1/16 size) from the pairs within 8 minutes either side. The bracket's own auto exposure also hunted by up to 7 levels a minute, so the brightness of the full-strength fused frames is smoothed over 3 frames either side, at most 25%. Tests added first (14 in `tests/test_fuse_sunset.py`). Some flicker is left that is in the unprocessed frames too: the sun going in and out of thin cloud.

### Instagram video, second round (23:50 Vancouver)
- **Tighter crop:** `crop.json` `view` (`top`, `height`) makes the 9:16 window shorter than the full frame, scaled up to 1080x1920. `nas/crop.cm4wide.json` uses top 100, height 1600, which drops the foreground roofs and puts the horizon about 70% of the way down.
- **Sky score, no AI:** each record now has a `sky` block (score out of 100, label, warm-sky percent, best frame, `provisional`), and `tools/build_video.py` prints it. It is the best frame from 35 min before to 25 min after sunset, by the share of the top 40% that is bright and warm. Score = that share over 10%, capped at 100, so grey evenings read 5 to 13 and the Nov 8 and Nov 12 sunsets 67 to 69 on the wide camera. The CM4 camera read 11.9% to the wide camera's 6.7% on Nov 12, so `crop.cm4wide.json` has `sky_full_warm` 0.178. The Nov 12 CM4 video scores 67, colourful. Stdlib plus ffmpeg, so it runs in the NAS image. Posting only above a threshold is not built.
- **Exposure:** new `tools/fuse_sunset.py` merges the ev+0 and ev-2 daylight-white-balance pairs from experiment `cm4-sunset-1` (Steven's top-ranked option E) and blends them with the production frames (in over 5 min, full to 5 min after sunset, out by 12 min). Frames with no pair, one in five, are filled from the pairs either side so the video doesn't flash. The job takes the result through `FUSED_DIR` (`Frame.source` keeps the original for the sky score). Clipped pixels at the sunset frame fell from 2.5% to 1.4%, and the sun disc shows now. After +12 min the frames are the production ones again, with the auto white balance's blue sky.
- **Docs:** README and CLAUDE.md now describe `tools/build_video.py` and `tools/fuse_sunset.py`; `nas/README.md` has the sky score and exposure sections.
- Tests: 131 in `tests/test_daily.py`, 11 in the new `tests/test_fuse_sunset.py`, all pass.

### Instagram video from the CM4 camera (`cm4wide`), Steven's requests (23:20 Vancouver)
- **Calibration:** fitted the `cm4wide` lens (3.2 mm) to five skyline landmarks: two near towers, a third tower and two downtown spikes, with bearings taken from the `wide` camera's pilot-3 fit. Result: f = 1,880 px, 261.7° at the frame centre, residuals 8 px or less. It puts the Nov 12 sunset (243°) at x = 1,391, which matches the glow in the frames. Saved as `nas/crop.cm4wide.json`. The nearest landmark is 14° from the sunset, so check it against a clear sunset. The earlier video used a fixed guess for the centre.
- **Daily video job:** `VIDEO_START_LOCAL` (e.g. `07:30`) starts a video at a local time instead of after the last one. The handle is now `@funvill`. A small third line under the date gives the place and the bearing at the middle of the crop, e.g. `Burnaby, BC, Canada   WSW 243°` (`OVERLAY_LOCATION` changes or drops it). `crop.json` can have `blur` boxes, a light Gaussian over the near towers, applied before the crop to the video and the check image. The record keeps `crop.center_azimuth_deg`. The filter file is now written as UTF-8, because of the degree sign. Tests added first (117 pass).
- **`tools/build_video.py`:** builds one day's video on a PC with no AI: `python tools/build_video.py --camera cm4wide --date 2026-11-12 --start 07:30 --redo --crop nas/crop.cm4wide.json`.
- Built the Nov 12 video (07:30 to dark, 311 frames, 26 s). Not posted. The README rule about location now says the video, not the caption, shows the city.
- **Raw vs JPEG, checked on the 17:35 sunset frame:** the DNG is 12-bit, and its clipped share (0.2%) matches the JPEG's, so raw gives no highlight headroom when the exposure clips. Dense frames have no DNG, so a raw video would lose the 1-a-minute slowdown. Decode takes 0.4 s at half size with `rawpy`. Not adopted; see `CLAUDE.md`.

### Network watchdog (CM4, 05:09 UTC Nov 13 / 22:09 Vancouver)
- New `sunset-netwatch.sh` with `sunset-netwatch.service` and `.timer` (every 2 min, as root), off unless `NETWATCH=1`. It resets the USB Wi-Fi dongle after 10 min without the gateway, and reboots after 30 min, at most once every 6 h. `install.sh` installs and enables the timer; tests in `tests/cases/66_netwatch.sh`, with new `ping`, `ip` and `systemctl` stubs.
- **Pi (CM4):** installed and enabled, `NETWATCH=1` in `sunset.env` (old file kept as `sunset.env.bak-2026-11-13-netwatch`). Live test with an unreachable target: the dongle was reset at 05:09:53 UTC and rejoined 6 s later on the same address.
- Found while checking: the backlog sync after the outage was stopped by its 30-minute `TimeoutStartSec` at 05:07 UTC and wrote nothing to `sync.log`. Copied files were already removed from the Pi, so nothing was lost; the next run carries on.

### Experiment 20 results (CM4 night sweep, posted on #3 at 21:55 UTC / 14:55 Vancouver)
- 878 shots from 04:00 to 13:56 UTC, no failures. The CM4 needs about 1.3 stops more exposure than `timelaps` at night.
- **Pi (CM4):** set `NIGHT_SHUTTER_US=8000000` and `NIGHT_AWB=2.20,2.80` at 22:15 UTC (15:15 Vancouver) at Steven's go-ahead, old file kept as `sunset.env.bak-2026-11-12-night`. `timelaps` is unchanged (4 s, 2.25/2.40).
- **Pi:** `timelaps` logged three undervoltage warnings at 00:16-00:19 UTC, during the camera move. None since.
- **Pi (CM4):** the first 8 s night frame (01:05 UTC) came in bright twilight: its lux reads about 2.2x lower than `timelaps`' in the same light. Set `NIGHT_LUX=2.3` at 04:37 UTC Nov 13 (21:37 Vancouver) at Steven's go-ahead, old file kept as `sunset.env.bak-2026-11-13-lux`.
- Sunset temperature log, 00:19-01:45 UTC: `timelaps` 55.3-60.1 °C, at its soft limit for about 3.5 min; the CM4 39.4-43.3 °C. All 82 captures on each were on time.

### CM4 Wi-Fi outage (02:48-04:35 UTC Nov 13 / 19:48-21:35 Vancouver)
- The access point dropped the CM4 at 02:48:11 UTC. It reconnected, then disconnected itself 10 s later (`DEAUTH_LEAVING`) and made no further attempt for 1 h 45 min. The rsync of the 02:45 DNG broke off and the share went away.
- Capture kept going to local storage: no frames lost. The HA CM4 alert reached Steven's phone at about 03:52 UTC, as designed.
- Steven power-cycled the CM4 at about 04:35 UTC. On boot the dongle's driver logged register-access errors, then joined. Sync resumed with a 1.2 GB backlog.
- The reboot cleared the transient `exp-cm4-sunset-2` and `-3` timers; recreated them with the same times and arguments.
- Cause unproven: the journal was in RAM and lost. NetworkManager retries forever on this connection and Wi-Fi power saving is off, so a dongle or driver hang is the leading suspect.

### Hardware
- Steven moved both cameras, putting the CM4 at the window.
- **`timelaps`:**
  - Feature matching against the 20:00 UTC frame shows small nudges from 00:11 UTC and a shift of about 37 px (≈ 0.6°) at 00:18 UTC, during experiment run `sunset-3`.
  - Set `SETUP_ID=pilot-4` and added the nudge to `SETUP_NOTE` at 00:33 UTC (old file kept as `sunset.env.bak-pilot3`). Frames from 00:18 to 00:30 UTC still say `pilot-3`.
- **CM4:**
  - Set `SETUP_ID=cm4-window-1`. Its camera is mounted upside down.
  - Focus checked on 100% crops: sharp in the centre, even left to right, slightly softer at the edges.
  - Estimated its field of view by matching it against the 6 mm frame: centre ≈ 262° true, focal length ≈ 1,940 px, at least ~93° wide, probably more with the lens's barrel distortion. Not yet measured on the sun.
  - Started capturing at Steven's go-ahead: enabled `sunset-capture.timer`, `sunset-sync.timer` and `sunset-dense.timer` at 00:34 UTC. The first frame was 00:35 UTC; frames sync to `project_sunshine/cm4wide/`.

### Capture
- New `ROTATION` setting (0 or 180) for a camera mounted upside down.
  - `sunset-capture.sh` passes `--rotation 180` to every `rpicam-still` call, so the JPEG and DNG come out upright. It records `rotation: 180` in `Capture.settings`. Any other value logs a warning and takes the frame unrotated.
  - `sunset-diag.py` rotates its live view the same way. On the CM4, rpicam took the focus crop (`--roi`) in the rotated picture's coordinates, so the crop needs no change.
  - Documented in `sunset.env.example`. Tests: `tests/cases/16_rotation.sh`, plus two in `tests/test_diag.py`.
- Fixed a test that searched for the site latitude `49.25` as a regular expression. The capture script's new checksum contains `49725`, so it failed by chance; it now matches the literal text.
- Deployed `sunset-capture.sh` and `sunset-diag.py` to the CM4 and set `ROTATION=180` there. Frames are upright from 01:08 UTC; those from 00:35 to 01:07 UTC are upside down. `timelaps` keeps its current scripts, and the new setting defaults to 0 there anyway.

### Monitoring
- The Home Assistant alert can watch the CM4 too. `sunset_frame_age.sh` takes an optional camera name (default `wide`) and reads `project_sunshine/<name>/`, matching only that camera's file names. `sunset.yaml` adds `sensor.sunset_cm4_newest_frame_age` (`cm4wide`), `binary_sensor.sunset_cm4_frames_stale` and `alert.sunset_cm4_frames_stale`, sharing the 60-minute limit. Tests in `tests/cases/80_frame_age.sh`. Installed in Home Assistant at about 03:25 UTC (20:25 Vancouver) through the File editor app. The old files are kept as `/config/sunset/*.bak-2026-11-12`, and the phone notifier was kept and added to the CM4 alert as well. Config check valid; after a restart both age sensors read 7 minutes and both alerts are idle.

### Reflections (both cameras, 01:41 UTC / 18:41 Vancouver)
- Checked the night frames of both cameras for reflections in the window. To tell LEDs from the city, I took one 4 s night shot with each Pi's LEDs as they were and one with every software-controlled LED off, then put them back. The shots went to `/tmp`, not the outbox; no production frame was affected.
- **CM4:** two green spots and a group of red ones, each doubled by the two panes of the double glazing, sit over the buildings in the lower half of the frame. They are in every frame, day exposure included, and **all disappear with the LEDs off**: they are the board's and the Wi-Fi dongle's LEDs reflected in the glass. A large amber glow with a curved dark edge on the left side does **not** change with the LEDs off: it is a light in the room reflected in the glass (or something lit near the camera), and needs the hood or a black cover.
- **`timelaps`:** a faint red wash in the left sky disappears with the LEDs off: the Pi 3's red power LED. Much weaker than on the CM4.
- **Pi:** while restoring, the ACT LED's trigger came back as `none`; set back to `mmc0` on both Pis straight away. Nothing else changed on either Pi.
- **LEDs off (Steven's go-ahead):** new `pi/90-sunset-leds.rules`, a udev rule that sets every LED's trigger to `none` and brightness to 0 as it appears. `install.sh` installs it and applies it at once. Test in `tests/cases/60_units.sh`.
  - **Pi:** installed on both Pis at about 02:50 UTC (19:50 Vancouver), with the new `install.sh` copied to `~/sunset`. PWR, ACT and the board's `default-on` LED are off on both.
  - Rebooted the CM4 at 02:56 UTC to check the boot path; it was back on Wi-Fi by 02:57 and missed no 5-minute slot. The board's LEDs stayed off. The Wi-Fi dongle's driver turns its LEDs back on within seconds of connecting, so software can't keep those off.
  - The 03:00 UTC CM4 night frame has **none of the green and red spots**, with the dongle's LEDs still lit. So the spots were the CM4 board's own LEDs, and the dongle isn't visible in the glass. The amber room-light glow on the left is unchanged.
  - `timelaps` was not rebooted, because that would clear its scheduled experiment timers. The rule applies at its next boot anyway.

### Experiments
- Experiment 19, run `sunset-3` (Nov 11): overcast again. A clipped at most 1.1% of the sky; B, D and E at most about 0.35%. E's sky went brown after sunset again, R/B 1.5 at +32 minutes to 3.9 at +43, a little later than on Nov 9 and 10. Posted on #3.
- Confirmed the LED fix on `timelaps`: the left sky's extra redness dropped from about 3 (R minus B, against the neighbouring sky) to about 0.5 when the LEDs went off at 02:50 UTC.
- **Runner:** `sunset-experiment.py` reads `ROTATION` from `sunset.env` and adds `--rotation 180` to every shot, so experiments on the upside-down CM4 come out upright. Tests in `tests/test_experiment.py`. Copied to both Pis.
- **CM4 experiments 20 to 25**, at Steven's request; the plan is posted on #3. 20: night sweep; 21: sunset options alongside experiment 19; 22: lens geometry from the sun; 23: vignetting and sharpness; 24: Wi-Fi sync health; 25: the room-light glow, which needs Steven.
  - **Pi:** on the CM4, the runner is installed in `~/sunset/experiments/` with transient timers, run as root with `User=sunshine`. `exp-cm4-sweep-1` runs Nov 12 04:00 to 14:00 UTC (ending before the morning dense frames). `exp-cm4-sunset-1` to `-3` are set for the same windows as `sunset-4` to `-6`. Results go to `project_sunshine_experiments/cm4-*`.

## 2026-11-11

### Hardware
- Checked the CM4 on its old OS: the eMMC is 32 GB (29.1 GB in `lsblk`), not ~4 GB, and the boot EEPROM is dated 2023-01-11, so it needs no update for the board's USB and cameras. Corrected `CLAUDE.md`. The CM4 is not set up for the project yet.
- Steven reflashed the CM4 with Raspberry Pi OS Lite Bookworm 32-bit (hostname `sunshine`). On it, from about 23:05 UTC (16:05 Vancouver):
  - Installed `~/sunset` from `pi/` with `install.sh --uc517`, timers not enabled.
  - Its `sunset.env` is a copy of `timelaps`' with `CAM_NAME=cm4wide`, `SETUP_ID=cm4-desk-1` and a new `SETUP_NOTE`.
  - Added `dtoverlay=i2c-rtc,ds1307,addr=0x68` for the board's clock, and set the clock from NTP.
  - The camera is on CAM0, so the overlay is `dtoverlay=imx477,cam0`. With the default (CAM1), the driver found no sensor.
  - Self-test (no NAS): 14 pass, 1 warn (64-bit kernel). Day shot 4.3 s, night shot 6.2 s, each with DNG.
  - The first frame is fully out of focus. Started the diag page for focusing.
  - Later: Steven removed the C-to-CS adapter ring, and the lens now focuses. It isn't fixed in place yet.
  - The CM4 has no Wi-Fi: the module has no antenna, LK2 is open, and the kernel reports `mmc1: Failed to initialize`. It is on Ethernet only.
  - Installed `i2c-tools` and `lsof`, both on the keep list.
  - Trimmed the packages to the keep list, 615 to 383. Kept `linux-image-rpi-v7l` and `-v8`, because the keep list would have removed the kernel the CM4 boots. Also kept the USB Wi-Fi firmware and `usb-modeswitch`, for a USB Wi-Fi adapter. `docs/setup.md` now has the extra `apt-mark` line for a CM4.
  - Ran `sunset-lowwear.sh`. Added the same NAS line to `/etc/fstab` as on `timelaps`; it can't mount until Steven creates `/etc/sunset-nas.cred`.
  - Rebooted at 23:43 UTC. The RTC set the clock before NTP, and the kernel writes NTP time back to it. The RTC has no coin cell yet, so it doesn't keep time through a power cut; capture still waits for NTP.
  - Checked the first USB dongle from Steven's box: a Rocketfish RF-FLBTAD Bluetooth adapter (USB 0461:4d75, Broadcom BCM2046). Not Wi-Fi.
  - The second is Wi-Fi: a Buffalo WLI-UC-GNM (USB 0411:01a2, Ralink RT8070), 2.4 GHz only, driver `rt2800usb`. Its firmware is from `firmware-mediatek`, which the trim kept.
    - It joined the saved network once, at -69 dBm and 1-7 Mbit/s, but got only an IPv6 address and no DHCPv4 lease in 45 s.
    - Every reconnect after that failed the WPA handshake (`CONN_FAILED`).
    - For comparison, `timelaps` is on 5 GHz at -40 dBm and 200 Mbit/s.
    - Not usable as it is. A dual-band (5 GHz) adapter is the better candidate.
    - Steven then turned on 2.4 GHz for the network in UniFi (about 00:02 UTC Nov 12). The CM4 sees it on channel 6 at -67 to -69 dBm and joins it, but traffic goes only one way: router announcements arrive, but DHCPv4 gets no lease and IPv6 pings out over Wi-Fi lose 4 of 4. The AP probably doesn't hear the dongle through two walls.
    - After Steven moved the CM4 closer to the AP (Ethernet unplugged), it got an address over Wi-Fi at about 00:17 UTC. The CM4 reads -45 dBm at 57.8 Mbit/s; UniFi shows -62 dBm, "AP/Client Signal Balance: Poor" and a 2 Mbit/s Tx rate. Pings to the router lost 0 of 20. Copying a 27 MB file to the NAS took 91 s, about 2.4 Mbit/s. That keeps up with the capture (8-15 GB a day needs about 0.8-1.4 Mbit/s), but catching up after a NAS outage would be slow.
    - Set the saved Wi-Fi profile to reconnect forever (`connection.autoconnect-retries 0`) and turned off Wi-Fi power saving (`802-11-wireless.powersave 2`).
  - Copied `/etc/sunset-nas.cred` from `timelaps` to the CM4 at Steven's request, Pi to Pi, without displaying it (root, 600, same checksum). The share mounts: 230 GB free of 11 TB.
  - A sync at 23:47 UTC copied the test frame to `project_sunshine/cm4wide/2026/11/11/` on the NAS and removed it from the CM4.
  - A test capture with `sunset-capture.service` at 23:44 UTC wrote JPEG, DNG and JSON to `outbox/cm4wide/` in 4.5 s. Quick self-test: 10 pass, 1 warn (64-bit kernel). The timers are still off.

### Docs
- Recorded Steven's decision to post only good sunsets to Instagram, not every day, in `CLAUDE.md` and `README.md`. Added backlog #11 in `CLAUDE.md`: a deterministic sky score (warm-sky fraction, luminance spread, no AI) written into each daily record, with the publisher posting only days above a threshold. It's a todo until there are more clear sunsets. A first try on the Nov 4-10 frames gave a warm-sky fraction of 0.041 on the clear Nov 8 sunset and 0.001-0.013 on every other day. No code added.

### Experiments
- Analysed experiment 19 runs `sunset-1` and `sunset-2` (Nov 9 and 10, both overcast), with results on #3 and on the sunset comparison page. B, D and E all held a bright gap in the cloud that blew out up to 11% of the sky in the production frame. Daylight white balance turns the sky brown from about 15 minutes after sunset, when the cloud is lit by the city: R/B up to 4.6, against 0.5-1.0 with auto. So E only works up to about 10 minutes after sunset. Nothing changed in production. Runs 3 to 6 (Nov 11-14) still to come.

## 2026-11-09

### Hardware
- Recorded Steven's CM4 (eMMC) and MyPi Industrial IoT Integrator Board XT in `CLAUDE.md`'s inventory, with the board's features from its manual. Not in use yet.
- Steven ordered a second IMX477 camera (Arducam B0240E) and a 3.2 mm wide lens (Arducam LN05101), due Nov 12. Recorded the two-camera plan in `CLAUDE.md`: the new camera with the 3.2 mm lens as the wide sunset camera, and the current camera with the 16 mm lens on downtown, both on the CM4 board.

### Images posted to issues
- Removed the tower blur from the analysis images and the sunset comparison page, and the scratch script that made it. Removed the privacy notes about neighbours' windows from `README.md` and `CLAUDE.md`, and the word "privacy" from the NAS job's mask (the mask option itself is unchanged and unused).
- Added `tools/issue_blur.py`, only for images posted to GitHub issues: a light blur over the nearby buildings, so their outline and decks still show, with a "Blurred for privacy" label on each. Five styles; Steven chose style 1 (light Gaussian, 2.5 px at the posted size), which is the default. The building outlines are for framing `pilot-3`. Tests in `tests/test_issue_blur.py`.

### Capture
- **Pi:** the dense frames never started. The one-off job meant to switch on `sunset-dense.timer` at 7:32 pm Nov 8 (02:32 UTC Nov 9) ran as the normal user and was refused ("Interactive authentication required"), so the sunrise window on Nov 9 got no 1-a-minute frames. Switched on by hand at 10:12 am (17:12 UTC); the first check ran cleanly, and the first dense window is the sunset on Nov 9 from about 4:38 pm.

### Experiments
- Analysed the first clear sunset (Nov 8, `day-5`), with results on #3 and #4. The sun enters the frame at about 238.4°, 1° further left than the landmark estimate, because the lens has some barrel distortion. The sunset is off the left edge from Nov 24 to Jan 16 instead of Nov 21 to Jan 19. Auto exposure blows 7-12% of the sky through the sunset; ev-2 recovers almost all of it, and ev+2 adds nothing. Auto white balance pulls the sunset towards blue, and daylight white balance keeps it warm. Nothing changed in production.
- Steven ranked the sunset options from the comparison page: best E (ev+0 and ev-2 merged, daylight white balance), then B (ev-2 alone), then D; worst F, A and C. Added a `sunset` program to the experiment runner (experiment 19) that shoots the real inputs for E, B and D every minute from 45 minutes before sunset to 45 minutes after, plus ev-3 and the direct-sun shots every 5 minutes.
- The experiment runner no longer starts a shot in the first 12 seconds of a minute or one that would run into the next minute, and treats a running dense capture as the camera being busy. Before this, an experiment shot at the end of a minute could have made that minute's dense frame skip itself.
- **Pi:** deployed, and scheduled `sunset-1` to `sunset-6` for the sunsets of Nov 9 to Nov 14 (from about 4:51 pm each day). They are transient timers, so a reboot clears them.

## 2026-11-09

### Capture
- **Pi:** the dense frames never started. The one-off job meant to switch on `sunset-dense.timer` at 7:32 pm Nov 8 (02:32 UTC Nov 9) ran as the normal user and was refused ("Interactive authentication required"), so the sunrise window on Nov 9 got no 1-a-minute frames. Switched on by hand at 10:12 am (17:12 UTC); the first check ran cleanly, and the first dense window is the sunset on Nov 9 from about 4:38 pm.

### Window-light tracking
- Added `windowtracking/`, an anonymised NAS job (`sunset-windowlight.py` + `Dockerfile` + `README.md`) that measures how lit the towers in the centre of the view are, as aggregate signals only. For each tower it reports the share of windows lit per night frame (against a max-composite reference that counts windows without labelling any), the lit-window count per frame, and lit/unlit transitions per hour. No window IDs, floors or per-unit history. The plan is `windowtracking/plan.md`; it supersedes the earlier per-window occupancy idea.
- Added `tests/test_windowlight.py` for it. Detection and aggregation are tested on synthetic greys; the ffmpeg loader is tested with the real ffmpeg and skipped without it.

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
