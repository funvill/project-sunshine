# Changelog

The history of Project Sunset, newest first: every change (code, settings, hardware, including changes made only on a Pi, marked **Pi**) and every event that affects the record (outages and lost frames, power cuts, camera moves, weather that matters, good sunsets, solstices, the moon, milestones). Dates are Vancouver local time; times are given in UTC and Vancouver. Decisions and their reasons are in `CLAUDE.md`.

## 2026-11-22

- **Decisions (Steven):** keep the sunset bracket (option E, `BRACKET=1`) for the real run; keep every Home Assistant sensor (batch B item 9, fewer UPS sensors, not done); the P2-to-MyPi UPS cable polarity is checked (#29). The temperature, humidity and light sensors stay dropped (#34 was already closed).
- **Simplification, batch B** (Steven chose items 1-8, 10 and 11 of the list on PR 55). About 6,700 lines out, 1,750 in (most of the additions are the old brief moved into this file). **Nothing changes on the Pi or in Home Assistant until it is deployed.**
  - **`CLAUDE.md` holds the current state and decisions only** (582 lines to 185). Its old sections from "Decisions made" to the backlog, which held most of the pilot's history before this file existed, are now the last section of this file, word for word.
  - **One timer for both cameras:** `sunset-capture` and `sunset-dense` run the capture script for `cm4wide`, then again with `--env sunset2.env` for `cm4city`, right after it instead of at :30. A failed first camera doesn't stop the second. The `sunset-capture2`/`sunset-dense2` units are gone; `install.sh` disables and removes them, since leaving them on would shoot `cm4city` twice a slot.
  - **One watchdog:** `sunset-netwatch.sh` and `sunset-camwatch.sh` are now `sunset-guard.sh` on `sunset-guard.timer` (every 2 min). Same checks, settings (`NETWATCH*`, `CAMWATCH*`), logs, state files and 6-hour reboot limits; at most one reboot a run. The camera check now runs every 2 minutes instead of 5.
  - **No DNG code:** the capture writes JPEG + JSON only. Gone: `SAVE_RAW`, `DISK_DROP_RAW_PCT`, `BRACKET_RAW_MIN`, the 85% disk step (95% still skips the night frame) and the sync's DNG-ends read-back (files over 8 MB are now checked by size only; JPEGs are a few MB). `raw=` is no longer in `capture.log` lines. The experiment runner's own dark, flat and moon programs still shoot DNGs.
  - **NAS jobs that never ran:** `nas/sunset-health.py`, `nas/sunset-verify.py`, the Docker image and its CI job, and the matching Home Assistant scripts and blocks (never installed in HA). `nas/sunset-daily.py` stays: `tools/build_video.py` runs it on the PC.
  - **Experiments:** the answered programs (night, settle, day, rate-night, night-sweep, sunset) and the nightly sunset run are gone; moon, dark, flat, checker and the weather log stay.
  - **Video tools:** `--fuse-run` (experiment runs), `--blend-weights` and `--fuse-until` are gone; `--fuse-production` with the 1:2:1 blend and the 5-12 min fade-out is the one path.
  - **Diag page:** the Pi health panel is gone (`tools/camera_check.py` does that).
  - **Archived (in git history):** `tools/ups_bench.py`, `register_day.py`, `sunset_stills.py`, `system_diagram.py` with `docs/system-diagram.svg` (it still showed `timelaps`), and `pi/sunset-focus.py`.
  - **`issue_blur.py`** takes its boxes from the camera's crop config by `SETUP_ID` instead of outlines drawn for `pilot-3`. The tools share one frame-name helper, `tools/frames.py`.
  - **Tests:** the whole suite passes (1,110 checks), and the OpenCV tests pass on Windows.
  - **Deployed to `sunshine` at 17:29 UTC (10:29 Vancouver)** at Steven's go-ahead, merged as PR 57 (41a7ee0). The Pi's files matched the repo before the copy (only the unit paths `install.sh` writes differed). Backup in `~/sunset/.bak-20261122-batchB/`, with the old scripts and units (`sunset-camwatch.sh`, `sunset-netwatch.sh`, `sunset-focus.py`, `experiments/sunset-nightly.sh`, the `*2`, camwatch and netwatch units) moved to its `retired/` folder rather than deleted. `sudo ./install.sh --enable --ups` disabled and removed the old units and started `sunset-guard.timer`; `sunset.env` and `sunset2.env` unchanged. Only `experiments/sunset-experiment.py` changed in `experiments/`. Home Assistant not touched (comments only; next HA deploy). First slot on the new units, 17:30 UTC: `cm4wide` 17:30:00, `cm4city` 17:30:05, both on the NAS, no `raw=` in the log.
- **`cm4wide` camera fault, 17:35-17:47 UTC (10:35-10:47 Vancouver), 3 frames lost.** Six minutes after the deploy, the `cm4wide` captures for 17:35, 17:40 and 17:45 timed out (`rc=124`, `Failed to queue buffer`, the kernel logging `unicam fe800000.csi: Failed to start media pipeline: -22` about 9,600 times a minute). `cm4city` kept capturing (its frames are named 17:36, 17:41 and 17:46 because it waited for the hung first camera). It is the same fault both cameras had on and off on Nov 19-20, and the new `sunset-guard` handled it as designed: at the third failure it rebooted the Pi (17:47:39 UTC, back at 17:47:51), kept the trusted clock, and both cameras captured cleanly from 17:50. Cause unknown; the guard only reads `capture.log` and never opens a camera. It had not happened since Nov 20 (2 days 10 h up), so a link to the deploy (the reload, or `cm4city` now starting right after `cm4wide` instead of 30 s later) is possible but unproven. If it recurs, try a pause between the two cameras. Cosmetic: the capture log's clock line still says "netwatch rebooted" after a camera reboot.

## 2026-11-21

- **Simplification, batch A** (Steven asked for a review aimed at simplifying the project; four reviewers, claims checked against the code; batch A is the part that needed no decision). About 1,500 lines out, 300 in. **Nothing changes on the Pi until it is deployed**, and then only options nobody sets go.
  - **Removed, already decided against:** the master render and the sunset-only cut in `nas/sunset-daily.py` (#21), with `REDO_MISSING_OUTPUTS`; the Home Assistant heartbeat package (#22, "no outside heartbeat"); the sunrise dense window and `DENSE_WINDOWS` (dropped 2026-11-16), so `sunset-sun.py dense` only answers `sunset`; `UPS_LOW_PCT`, which the board can never trip (it says 100% on battery).
  - **Removed, retired hardware:** `pi/hosts/timelaps.env`, the `--uc517`/`--uc517-cam0` install options (only `--cm4-two` is left; it still turns a plain `imx477` line into the cam0 one), the `timelaps` rebuild and image steps and the "Zero-specific limits" in `docs/setup.md`, the self-test's armv6 warning (it always fired on the CM4), and Zero wording in the scripts. `build_video.py` defaults to `--camera cm4wide`.
  - **Removed, dead code:** `CAPTURE_FAIL_REBOOT` (off, set nowhere; the camera watchdog does this), which leaves a warning after `CAPTURE_FAIL_WARN_N` failures in a row; the diag page's camera hand-back before each capture (`HandoverPolicy`, the dense-window note, its `SLOT_S`), since the diag unit stops the capture timers while it runs (the capture lock stays); `experiments/raw_value.py` (#38 answered), `experiments/analyse_frames.py` (set up for the `timelaps` framing) and `tests/test_windowlight.py` (tested a folder that isn't in the repo).
  - **Docs:** CLAUDE.md contradictions fixed (rotation, DNGs, sunrise, UPS cells and R20, the Zero RTC, NAS space, the 16 mm plan). The README's dated state table is now a short summary that points to CLAUDE.md, the issues and this file.
  - **Tests:** `bash tests/run.sh 17_ dense test_ups` runs only those; a case that uses another's helpers names it on a `# needs:` line and brings it along. The whole suite passes (1,226 checks).
  - **Pi (`sunshine`): deployed** (Steven's go-ahead, after PR 55 merged; 06:17:19 UTC Nov 22, 11:17 pm). `sunset-capture.sh`, `sunset-diag.py`, `sunset-sun.py`, `sunset-ups.py`, `sunset-selftest.sh`, `sunset-focus.py`, `install.sh`, `sunset.env.example` and the two dense units copied from `main` (a0e4690); before the copy the Pi's files matched the last deploy (78b36eb), except `install.sh`, which was older (the Pi doesn't run it). The installed dense units changed only in their description and comment; systemd reloaded. `sunset-ups.service` restarted. Old copies in `~/sunset/.bak-20261122-batchA/`. Neither `sunset.env` nor `sunset2.env` set any of the removed options, so nothing there changed. Diag was off. The first captures on the new script (06:20:16 cm4wide, 06:20:41 cm4city, night frames) and the 06:18 sync were clean, `throttled=0x0`. The sunset window on the new `sunset-sun.py` is first used live at tonight's sunset. Home Assistant: not touched; the only change there was removing the heartbeat package from the repo.
  - Batch B (Steven's decisions: the CLAUDE.md rule, one timer for both cameras, merging the watchdogs, the NAS jobs that never ran, DNG code, finished experiment programs, merge-tuning options, the diag health panel, fewer HA UPS sensors, one-off tools) is listed on the PR.
- **Code review, and fixes for its eight most serious findings** (Steven asked for a review by subagents; four reviewers, one per area, findings checked against the code before fixing). Nothing found deletes an unverified frame, names a frame with a wrong UTC time, or leaks the location. Fixed, each with tests:
  - **Capture:** a run deleted every file over an hour old in the shared `.partial`, so cm4wide could delete a cm4city frame stranded there by a power cut. Each camera now cleans only its own leftovers.
  - **UPS monitor:** a failed write to `ups.log` (SD full or read-only) crashed it in a loop, with no low-battery pause or resume. Write failures now go to the journal once and polling continues.
  - **Diag page and UPS pause:** ending diag restarted capture even during a low-battery pause, on battery. Now it adds its timers to the pause instead, and the UPS monitor starts them when mains returns (leaving the camera timers to diag if it is still on).
  - **Low-battery limit lowered from 3.45 V to 3.3 V a cell** (`UPS_LOW_CELL_V` default). With R20 unchanged the cells rest at about 3.5-3.6 V, so 3.45 V would have paused capture early in a short cut.
  - **Home Assistant:** `sunset_ups.sh` took the UPS state from the newest frame however old, so a power cut during a capture outage looked like "mains". A frame over an hour old now reads `unknown old_frame` (and no numbers), and the alert message says why.
  - **Camera watchdog:** `FAILED capture(empty jpg)` didn't count toward its reboot. It does now.
  - **Experiment runner:** it never passed `--camera`, so on the CM4 it shot CAM1 (cm4city) whatever the run said, and it ignored the second camera's :30 dense frames and its slot. It now picks the camera from `CAMERA` in `sunset.env` like the capture does (refusing to run if it doesn't match exactly one camera), keeps clear of :30 when `sunset-dense2.timer` is on (so shots over about 15 s wait for the night), waits 72 s after each slot (was 45 s), and treats `sunset-capture2`/`sunset-dense2` as busy.
  - **Config backup:** the password filter missed longer setting names (`NAS_PASSWORD=`, `IG_ACCESS_TOKEN=`); any name containing password, pass, secret or token now stops `sunset.env` being copied to the share.
  - **Pi (`sunshine`): deployed** (Steven's go-ahead; 18:45:33 UTC, 11:45 am). `sunset-capture.sh`, `sunset-sync.sh`, `sunset-ups.py`, `sunset-camwatch.sh` and `experiments/sunset-experiment.py` copied from `main` (78b36eb); the Pi's copies matched the repo before the fix, except the experiment runner, which was the older 22d9cde. The diag unit was reinstalled from the repo with the Pi's home folder (`/etc/systemd/system/sunset-diag.service`, and `~/sunset/systemd/`) and systemd reloaded. Old copies in `~/sunset/.bak-20261121-review/`. `sunset-ups.service` restarted at 18:45:40 UTC: on mains, limit 3.3 V, no restarts. The first captures on the new script (18:50:05 cm4wide, 18:50:35 cm4city) and the 18:46 sync were clean.
  - **Home Assistant: deployed** (18:46 UTC). The new `sunset_ups.sh` and HA's copy of `sunset.yaml` (made from the repo as before, with the phone), old copies as `sunset/*.bak-2026-11-21-review`. Configuration check passed; HA restarted, since the alert integration has no reload. Every Sunset alert idle afterwards, UPS `mains 100`.
  - Lower-priority findings (read-back treating two unreadable files as a match, `sunset-sun.py`'s temp file in `.partial`, `sunset2.env` not backed up, `sunset-verify.py` skipping the bracket frames, the per-folder blend marker in `fuse_sunset.py`, `build_video.py` also building the day before, `posted` reset by a failed redo) are listed on the PR for later.

## 2026-11-20

- **Home Assistant: CM4 CPU temperature sensor, and the Sunset sensors on the floor plan** (Steven asked; 23:00-23:20 UTC, 4:00-4:20 pm). `sunset_ups.sh --json` also gives `cpu_temp_c` from the same frame (`System.cpu_temp_c`), and `sensor.sunset_cm4_cpu_temperature` graphs it (first reading 38.5 °C). Installed by reloading the command-line and template integrations, not restarting HA. In HA only, not in the repo: the UPS, CM4 health, frame age and temperature sensors are in the Living Room area; the Floor plan dashboard has labels for UPS state, pack voltage, cell temperature (cell 2), CM4 health, CPU temperature and frame age next to the fireplace (old dashboard kept as `sunset/floor-plan.lovelace.bak-2026-11-20.json`); voltage sensors show 2 decimals, cells 3.
- **Home Assistant: the UPS values as numbers that can be graphed** (Steven asked; installed 22:26 UTC, 3:26 pm). `sunset_ups.sh` has a `--json` mode, `sensor.sunset_ups` keeps its state and carries every value as an attribute, and ten new sensors give charge %, input, output and pack voltage, and each cell's voltage and temperature, with units, so HA keeps their history. Input voltage stands in for the "mains percentage" Steven asked about, which the board doesn't report: about 15.2 V on mains, 0 on the cells. The board gives no discharge current or run time on battery, so there are no sensors for those. Old copies kept as `sunset/*.bak-2026-11-20-numbers` in HA's config; the configuration check passed and HA was restarted. First readings, on battery: cells 3.992, 3.988 and 3.987 V, 20-21 °C, pack 11.97 V, output 11.94 V.
- **Event: Home Assistant restarted at 21:46:16 UTC (2:46 pm)** (not by us). For 4 seconds `sensor.sunset_ups` had no reading yet and the on-battery alert fired with "the UPS reads 'unknown'", which Steven got. The power was fine. The alert message now says HA may have just restarted when there is no reading.
- **Event: the CM4's wired Ethernet unplugged** (Steven, about 22:00 UTC, 3 pm; time not recorded). `sunshine` is on its Wi-Fi dongle only. `tools/camera_check.py` hosts lines take `key=<address>` so the Wi-Fi address checks the host key known for the wired one, without editing `known_hosts`.
- **Event: runtime test on `sunshine`, stopped early** (Steven pulled the 15 V supply: `mains_lost` 21:33:14 UTC, 2:33 pm; plugged back in before sunset so as not to risk the evening's frames: `mains_back` 00:00:23 UTC Nov 21, 5:00 pm). **2 h 27 min on the cells with no frames lost and no pause**, so the runtime is at least that. Lowest cell every 10 min: 4.081 V (21:33), 4.061, 4.040, 4.021, 4.000, 3.987, 3.969, 3.958, 3.939, 3.931, ... 3.870 (23:43), 3.851 V (23:53): about 0.23 V a cell in 2 h 20 min, 0.4 V still above the 3.45 V pause. Pack 11.56 V at the end; output to the Pi 11.8-12.0 V throughout. The cells warmed from 20-21 °C to 26-28 °C. The board still said 100% and no run time. The cells now recharge only to the ~3.5-3.6 V charge stop (R20 unchanged), so a later test starts lower.
- **Event: power-cut test on `sunshine`** (Steven pulled the 15 V supply, 19:34:32 UTC, 12:34 pm). The UPS monitor logged `mains_lost` at once and the Pi kept running on the cells, output 12.2-12.3 V, with no capture lost. An earlier test the same day left no trace in `ups.log`. The monitor polls every 10 s, so a cut shorter than that can fall between reads.
  - **Over 24 min on battery** the cells fell from 4.135 to 4.085 V.
  - **No gauge on battery:** the board kept saying 100% charge, 0.00 A discharge and no run time (`rte_min` null), so it gives no current or runtime figure.
  - **So the low-battery pause rests on the cell voltage alone** (`UPS_LOW_CELL_V`, 3.45 V). `UPS_LOW_PCT` (10%) would never trip on this board.
  - Runtime has to come from the cell voltage over a longer cut.
- **Home Assistant reconfigured** (19:55 UTC, 12:55 pm). This covers both the HA install and the matching repo change (new `sunset_ups.sh`, sensor and alert in `sunset.yaml`, tests `82b_ups_status.sh` and `84_ha_yaml.sh`).
  - **Removed:** the `timelaps` frame-age alert, which had fired since the retirement, and its two entities from HA's entity registry.
  - **Added:** frame age for `cm4city`, camera health for both CM4 cameras, NAS free space, and a new **"CM4 is on battery"** alert. That alert's sensor, `sensor.sunset_ups`, reads `System.ups_source` and `ups_charge_pct` from the newest `cm4wide` frame via `homeassistant/sunset_ups.sh`.
  - **How:** the files were written with the File editor add-on. The old package and script are kept as `sunset/*.bak-2026-11-20` in HA's config. The configuration check passed and HA was restarted.
  - **Left out:** the daily video, archive check and daily health blocks, because their NAS jobs don't run (no `health/` folder on the share).
  - **Tested during the power cut:** the sensor read `battery 100`, and the alert fired at 19:57:59 UTC with its message.
  - **Found:** HA's copy had no phone notifier, so every alert so far went only to HA's notification list. **Fixed at 20:22 UTC (1:22 pm):** the Pixel 8 (`mobile_app_pixel_8`) was added to all six alerts, in HA's copy only. The old file is `sunset/sunset.yaml.bak-2026-11-20-phone`. HA was restarted and a test notification sent at 20:23 UTC.
  - HA is at `homeassistant.local` on port 80. Chrome could not resolve the name on 8123.
- **Event: foam hood fitted** (Steven; time not recorded). `cm4city` moved about 10 px left and 5 px down between 23:30 UTC Nov 19 and 16:00 UTC Nov 20 (3:30 pm Nov 19 to 8 am Nov 20). That comes from phase correlation of its daylight frames every 30 minutes against Nov 18 19:00 UTC; there is no daylight frame in between. `cm4wide` did not move: under 1 px at 19:00 UTC on Nov 18, 19 and 20.
- **Pi (`sunshine`): `SETUP_ID` changed for the hood** (19:16 UTC, 12:16 pm): `cm4-window-3` to `cm4-window-4` (`sunset.env`), and `cm4city-window-1` to `cm4city-window-2` (`sunset2.env`). Old copies are in `*.bak-20261120-hood`. Frames from the hood fitting to 19:15 UTC still carry the old ids. `nas/crop.cm4wide.json` has a `cm4-window-4` entry from Nov 20, carried over from `cm4-window-3` because the camera didn't move, and `tools/build_reports.py` has its horizon row. Both are to be rechecked on the next clear sunset.
- **Decisions (Steven):**
  - The sky score posting threshold stays at 60.
  - Steven posts to Instagram by hand on his personal account, so no automated publisher is needed (#2).
  - ToDo: the Instagram videos need open-source-licensed music added.
  - ToDo: the keyed mount is waiting on Steven's 3D printer (#35).
  - ToDo: the RTC coin cell.
  - The SHT4x/TSL2591 sensors and the dew heater are dropped (#34 closed).
- **UPS reviewed on `sunshine` (#29 stays open):** running and reporting since 07:24 UTC. Still open: a mains-cut test with the Pi as the load, the runtime, the low-battery thresholds and a Home Assistant alert. Details are on the issue.
- **Checked: the NAS video image's time zone.** `nas/Dockerfile` pins tzdata 2026f. The built image gives UTC-7 for Vancouver in Nov 2026, Jan and Jul 2027, and Dec 2031, so the video's 7:30 start and its overlay times are right. A CI step now checks this in the built image, because `test_daily.py` takes its expected times from the same tzdata.
- **Home Assistant: `timelaps` checks taken out of `homeassistant/sunset.yaml`.** That covers the `wide` frame age, health, archive check and daily health sensors, their binary sensors and alerts, and their lines in the re-arm automation. `docs/setup.md` says what to delete in an installed copy. HA itself is not yet changed.
- **Event: no weather forecast from 04:07 UTC Nov 17 (9:07 pm Nov 16) to 18:03 UTC Nov 20 (11:03 am)** (Steven saw "no forecast" in the report for Nov 17-19). The hourly forecast job (`exp-weather.timer`, experiment 17) ran on `timelaps` and stopped when that Pi was retired; it was never set up on `sunshine`. 85 hourly forecasts missed.
- **Pi (`sunshine`): forecast job installed** (18:03 UTC, 11:03 am). `exp-weather.service` and `.timer` from `experiments/systemd/`, with `User=sunshine` and its home, also copied to `~/sunset/experiments/systemd/`; `sunset-weather.py` there already matched the repo. A run by hand saved `forecast_20261120T180310Z.json` and copied it to `project_sunshine_experiments/weather/` on the NAS; the timer runs at :07 each hour. Nov 17-19 stay without a forecast in the report; from Nov 20 they're back.
- **Fixed: `tools/camera_check.py` printed Vancouver times an hour out on machines with tzdata older than 2026b** (found running the tests in WSL, whose Ubuntu has 2026a and still falls back to UTC-8 in winter). It now uses a fixed UTC-7, as `build_reports.py` does. Also: the `.gitignore` tests in `62_env_example.sh` now check the rules in a scratch repo, so they pass in a worktree under WSL. The suite now runs with no known failures (1,203 passed). Still open: `nas/sunset-daily.py`, `tools/build_video.py`, `tools/sunset_stills.py` and `pi/sunset-sun.py` read the machine's tzdata, so a host older than 2026b would put their local times an hour out in winter.
- **Pi (`sunshine`): the newer diag unit and `sunset-sun.py` from `main` deployed** (Steven, 16:20 UTC, 9:20 am). The old copies are in `~/sunset/.bak-20261120-diagsun/`. Nothing else on the Pi changed and no service was restarted. Before the copy, the Pi's `sunset-diag.py`, `diag`, `sunset-capture.sh` and `sunset-selftest.sh` were checked against `main` and matched.
  - **Diag unit:** `/etc/systemd/system/sunset-diag.service` (and the copy in `~/sunset/systemd/`) now pauses both cameras' capture and dense timers while the diag page is on, and starts them again when it stops, times out or fails. It also reads `/run/sunset-diag.env`, which sets the camera the page starts on. Until now the diag page on `sunshine` left capture running. Written through a temp file, then `daemon-reload`; `systemd-analyze verify` is clean. Not yet tried with the page on.
  - **`sunset-sun.py`:** adds the sun-in-view check (`view`, `view-calendar`, #32). No `VIEW_*` is set in either camera's env file, so frames are unchanged. The next-sunset output is the same as the old script's.
  - **Checked:** the next frames from both cameras (`cm4wide_20261120T162500Z`, `cm4city_20261120T162530Z`) logged `meta=ok`, have the same `Sun` fields as before, and mark nothing unavailable. All six timers are running and no unit has failed.
- **Pi (`sunshine`): the UPS monitor is installed and its status reaches the NAS** (Steven's go-ahead; issue #29). `sunset-ups.service` started at 07:24:52 UTC (00:24 am Nov 20) and is enabled. `sunset-ups.py`, `sunset-meta.py`, `sunset-sync.sh`, `install.sh`, `sunset.env.example` and two unit files were copied in (the old ones are in `~/sunset/.bak-20261120-ups/`). Nothing else on the Pi changed.
  - **First reading:** on mains, 100%; input 15.19 V, output 15.22 V; cells 4.13, 4.14 and 4.14 V; 17-19 °C; no charge or discharge current; firmware 1.6. So the board counts the 15 V supply as mains. The cells are still at their fitted 4.14 V, above the ~3.5-3.6 V charge stop, because they have not been cycled.
  - **Checked on the real thing:**
    - From 07:30 UTC every frame of both cameras has the UPS fields in its `System` block (`cm4wide_20261120T073000Z`, `cm4city_20261120T073030Z`), and nothing in them is marked unavailable.
    - The 07:29 UTC sync copied `ups.log` to `project_sunshine_config/sunshine/ups/ups-20261120T072452Z.log` on the share, matching byte for byte.
  - **What it adds:**
    - **Every frame:** `System.ups_source` and `System.ups_charge_pct` (the names decided on #29), and `System.ups` with:
      - the cell voltages and the three cell temperatures;
      - input, output and pack voltages, and charge and discharge current;
      - run time left, and which cells are present;
      - the charger and UPS states, flags and firmware.
      It is copied from the monitor's status in `/run` (RAM), so it adds no eMMC writes. A status over 120 s old shows as `ok: false, error: "stale"` with no readings. A Pi without the monitor (`timelaps`) gets no UPS fields.
    - **The log:** the sync copies `ups.log` and its rotated files to `project_sunshine_config/<host>/ups/`, each named after its first line, and copies a file again only when its size on the share differs.
    - **Low-battery pause covers both cameras:** the second camera's timers are now on the list. Only the timers that were running are stopped, and only those are started again when mains returns.
    - `install.sh --ups` installs and enables the unit. `tools/camera_check.py` shows a UPS line and its events, and warns on battery, stale status, cell imbalance or heat.
    - Documented in `docs/setup.md` ("UPS") and `sunset.env.example`.
- **Event: `cm4city` slot 07:25:30 UTC taken 23 s late; no frame lost** (00:25 am Nov 20).
  - **Cause:** a first `install.sh --ups` run stopped because `~/sunset/systemd/` on the Pi had no second-camera unit files (they had been installed straight into `/etc`). On its way out, its `> unit` redirect emptied `/etc/systemd/system/sunset-capture2.service`. The `daemon-reload` that followed for the UPS unit loaded the empty unit, and the 07:25:30 timer failed on it.
  - **Fix:** the unit was restored from the repo (identical to what was there) at 07:25:31 and the timer restarted. It ran the slot at once (frame at 07:25:53) and has kept to schedule since.
  - **So it can't happen again:** `install.sh` now writes each unit through a temp file and stops before touching anything if a source file is missing (new test in `61_install_lowwear.sh`). The four second-camera unit files and `sunset2.env.example` are now in `~/sunset/` on the Pi.
- **Found: `sunshine` ran older copies of two files than `main`:** the diag unit, which lacked the lines that pause capture while the page is on, and `sunset-sun.py`, which lacked the sun-in-view code. Both were deployed later the same day (above).
- **New: camera watchdog, `pi/sunset-camwatch.sh`** (Steven asked for a way to recover from camera failures, after the 16 hours of failures from 14:05 UTC Nov 19). Every 5 minutes, as root, it reads `capture.log`; if one camera has 3 or more failed captures since boot within 60 minutes, it reboots, at most once every 6 hours. Off unless `CAMWATCH=1` (set in the CM4's reference env). Steven suggested "x failures in a row"; the log showed the failures came scattered (`cm4wide`: 11 single failures, never two running; `cm4city`: at most 4 running), so "in a row" would never have caught `cm4wide`. Replayed on the real `capture.log`, the window rule reboots at 14:47 UTC Nov 19, 42 minutes in, and stays quiet on Nov 11-18 and after the reboot. Tests: `tests/cases/66b_camwatch.sh` (33 checks).
- **Pi (`sunshine`): camera watchdog installed** (Steven asked, 16:44 UTC, 9:44 am). Copied `sunset-camwatch.sh` and its two units in, added `CAMWATCH=1` to `~/sunset/sunset.env` (old copy `sunset.env.bak-20261120-camwatch`), enabled `sunset-camwatch.timer`. Its first run was quiet: no failed captures since the 06:53 UTC reboot. A dry run of the installed script on the Nov 19 log (14:00-15:00 UTC, with a test reboot mark so it could only hold back) found `cm4city` at 3 failures in 60 min and logged that it would have rebooted but for the mark. Nothing else on the Pi changed.
- **The `camera-check` skill now also updates the daily report** (Steven asked). After the check it runs `tools/build_reports.py`, which adds the new days and redoes the last two, and the reply gives each new day's sky score and frames and names any day at 60 or more. Committing the report is still only on Steven's word. The skill's note on network drops now says the new dongle has no baseline yet.

## 2026-11-19

- **Hardware: 15 V supply into the UPS** (Steven, about 06:20 UTC Nov 20, 11:20 pm Nov 19). It replaces the 24 V 1 A supply into the OpenUPS2, and was the fallback already on the shopping list.
  - **Why:** the 24 V supply read 24.24 V on the board, just over its 24 V input limit.
  - **Fits both boards:** 15 V is inside the UPS's 11-24 V input (13 V or more is recommended for Li-ion) and the MyPi XT's 9-28 V. The board counts it as mains (first reading under Nov 20).
  - Model and current rating of the new supply: not recorded.
  - The OpenUPS2 is now plugged into `sunshine` by USB.
- **Event and change (Pi): new Wi-Fi dongle on the CM4, an AIC8800D80, now working on 5 GHz** (Steven swapped it at about 06:05 UTC Nov 20, 11:05 pm Nov 19). The old Buffalo dongle ran at about 2.4 Mbit/s and dropped for 2 minutes about 1.4 times an hour (10 drops in 7 h on Nov 18-19).
  - **Outage:** from about 06:05 UTC there was no Wi-Fi: the new dongle came up as a USB disk (`a69c:5723`, "Aic MSC") with no Linux driver. Steven plugged in Ethernet at 06:13 UTC (11:13 pm). The NAS share had dropped with the network, so the syncs at 06:07 and 06:12 UTC failed ("share not mounted"). Opening the share at 06:16 UTC brought the automount back, and a sync then caught up (24 files). At 06:37 UTC (11:37 pm) the network watchdog rebooted the CM4 after 30 minutes without Wi-Fi, though Ethernet was up (it watches `wlan0` only).
  - **No frames lost:** `cm4wide` took every 5-minute slot. Capture is local-first, and the frames reached the NAS after each gap.
  - **Driver:** this dongle has the older MCU revision (`chip_id=7, chip_mcu_id=1`). Radxa's current AIC8800 driver uploaded the first firmware files, then stalled at `0x170400` every time ("bin upload fail: 170400, err:-32", 06:34 UTC), the failure in radxa-pkg/aic8800#49. What works is the matched V3 firmware set and loader from the `legacy-mcu1` branch of `shenmintao/aic8800d80` (D80 firmware byte-identical to Radxa's SDK V3). Built on the CM4 for the running kernel `6.12.109+rpt-rpi-v8` and installed with a udev rule that ejects the dongle's disk (`pi/sunset-aic-eject`, `pi/90-sunset-aic8800.rules`); steps in `docs/setup.md`. NetworkManager rejoined the saved Wi-Fi by itself at about 06:47 UTC (11:47 pm).
  - **Tested:** with Ethernet disconnected, a NAS read ran at about 88 Mbit/s (5,200 MHz, signal -37 dBm, sending at 180 Mbit/s), and a sync went through. A test reboot at 06:52 UTC (11:52 pm) came back in about 75 s with the dongle switched and Wi-Fi up by itself. Not tested yet: the watchdog's software replug of this dongle, and a full day on Wi-Fi alone.
  - **Installed on the CM4 for the build:** `gcc-aarch64-linux-gnu` (apt), the arm64 kernel headers unpacked by hand into `/usr/src/linux-headers-6.12.109+rpt-rpi-v8` (not registered with dpkg) with the `build` link to them, and the source in `~/aic-build`. A kernel update would need the modules rebuilt.
- **Event: capture failures on both cameras, 14:05 UTC Nov 19 to the reboot at 06:37 UTC Nov 20 (7:05 am to 11:37 pm Nov 19).** None from Nov 11 to the morning of Nov 19. At 14:05 UTC both cameras failed with "Pipeline handler in use by another process"; from 14:36 UTC captures kept failing with "Failed to queue buffer for Unicam Image" / "Device timeout", and the kernel logged "unicam: Failed to start media pipeline: -22" 17,063 times. Failures by UTC hour: 1 to 8, worst 00:00-04:00 UTC Nov 20. Counted in `capture.log`: `cm4wide` 16 failed captures, 11 of its 5-minute slots lost on Nov 19 (the report shows 277 of 288) plus some dense frames, including at 00:44-00:46 UTC, 17-19 min after sunset; `cm4city` 36 failed captures, at least the 05:00 UTC slot lost. Nothing else was using the cameras. The network watchdog's reboot at 06:37 UTC cleared it: no Unicam error and no failed capture since. Cause unknown. The flood also pushed everything before 21:11 local out of the two 1 MB `kernel.log` files, so the kernel's side of 14:05 UTC is gone. If it comes back: note the time, check `ps` for a stuck `rpicam-still`, and reboot.

## 2026-11-18

- **Fix: the `cm4-window-1` calibration was 2.2° off; re-fitted on the sun** (Steven asked, about 06:30 UTC Nov 19, 11:30 pm Nov 18). Steven asked whether the report thumbnails really show the sunset point. Checked on the frames:
  - **Time: right on every day.** The thumbnail frame is within 30 s of the calculated sunset (from the frames' `Sun` blocks). That is the sun about half a degree below a flat horizon, so the disc has usually just gone into the haze.
  - **Place: right for `cm4-window-3`, wrong for `cm4-window-1`.** The sun's disc in the ev-2 frames of the clear Nov 17 sunset (00:05-00:26 UTC Nov 18, 22 frames) gives a centre of 272.07°, 0.23° (8 px) from the 272.3° in `crop.cm4wide.json`, so that stays. The same measurement on Nov 16 (00:05-00:26 UTC Nov 17, 22 frames, elevation 2.8° to 0.1°) gives 263.94° (spread 263.76-264.11), not the 261.7° fitted to skyline landmarks on Nov 12: the sun was about 85 px left of where the calibration put it. The landmarks' bearings came from the wide camera's `pilot-3` estimate. The camera did not move sideways from Nov 12 to Nov 16 (phase correlation 0-2 px; it tilted 19-23 px vertically during Nov 16, between 12:00 and 20:00 UTC). The entry below that said the calibration put the sun within about 6 px on Nov 13 was wrong for `cm4-window-1`: before the bracket that frame is blown out around the sun. The Nov 12 frames are too blown out to settle it, but the brightest point at 00:28 UTC Nov 13 is nearer the new value.
  - **Changed:** the `cm4-window-1` fit in `nas/crop.cm4wide.json` is now the sun fit, 263.9° (f 1,880 px kept: the sun moved 122 px where the fit predicts 118). `reports/` rebuilt with `--redo`; the Nov 12-16 thumbnails moved about 85 px and now centre on the sunset glow. This also moves the bearing printed on any Nov 12-16 video rebuilt from now on (the centre of the crop, so about 2° higher); videos already made are unchanged. Not explained: `cm4-window-3` was carried over from the old 261.7° through a homography and still matches the sun, so the two don't agree on how far the camera turned on Nov 17.

- **New: `reports/`, a page of every day of `cm4wide`** (Steven asked for it). `tools/build_reports.py` (no AI) reads the frames on the NAS and writes `reports/index.html`, `reports/sky-scores.svg` (the daily sky score as a bar chart, with the posting threshold of 60), `reports/days.json` and one 100 x 100 thumbnail a day in `reports/thumbs/cm4wide/`. It is rebuilt whenever the project is updated, so it may be a few weeks behind; a run redoes only new days and the last two (`--redo` for all). Per day:
  - the thumbnail: the point where the sun meets the horizon, from the frame nearest sunset whatever the weather. Its column is from the `crop.cm4wide.json` calibration and its row from `HORIZON_Y` in the script (1300 px for `cm4-window-1`, 1310 px for `cm4-window-3`, measured on the sun's disc on the Nov 13 and Nov 18 00:22 UTC frames; the calibration put the sun within about 6 px of where it was). The blur boxes are applied first, the horizon sits 70% down so it is mostly sky, and no metadata is written. Thumbnails are the one kind of image allowed in the repo.
  - the sky score from the NAS job's own functions (Nov 12 48, Nov 13 2, Nov 14 2, Nov 15 19, Nov 16 71, Nov 17 41; the same as the video records where they exist), the sunset time to the minute and the bearing in whole degrees, the 5-minute slots taken and missed, the longest gap, dense, bracket and night frames, the Open-Meteo forecast for the hour of sunset, the Pi's highest CPU temperature, reboots, throttling, largest backlog and Wi-Fi signal from the frames' `System` blocks, the setup IDs, and the day's `**Event:**` entries from this changelog.
  - It starts on Nov 12 (`FIRST_DAY`): on Nov 11 the camera was on the desk, then upside down at the window, so that evening's score means nothing.
  - Tests: `tests/test_build_reports.py` (28, synthetic frames) and suite case `87_build_reports.sh`, which also checks that `reports/` holds no NAS path or LAN address. First real run: 6 days in about 2.5 minutes from the PC.
- **Found: the weather log stopped on Nov 17.** The newest forecast in `project_sunshine_experiments/weather/` is from 04:07 UTC Nov 17 (9:07 pm Nov 16), when `timelaps`, which ran `exp-weather.timer`, was shut down for the move. Nothing has logged the forecast since, so the reports show "no forecast" from Nov 17. Moving the timer to the CM4 is Steven's call.
- **Note: the Nov 12 sky score is now 48, not 67.** 67 was the best single frame on the camera's scale; the score is now the mean of the best five frames, which gives 48. The week-three blog post and the project page still say 67.
- The CM4's temporary wired address was taken out of `CLAUDE.md` and the Nov 17 entry below: LAN addresses live only in `tools/camera_check.hosts`.

- **Fix: the health check gave Vancouver times an hour early.** `tools/camera_check.py` used the old PST/PDT rule, so after Nov 1 it showed UTC-8; BC stays on UTC-7 all year (tzdata 2026b on). It now uses tzdata (`America/Vancouver`), or a fixed UTC-7 without it. Two Nov 17 entries below that took their local times from it are corrected (sunset 5:27 pm, not 4:27 pm; the network drops 9:01 pm to 8:50 am). Frame names, the NAS job and the video overlay were never affected.

## 2026-11-17

- **Event: clear sunset, the first one for the new aim** (Steven: "another amazing sunset"). Sunset 00:27:40 UTC Nov 18 (5:27 pm Nov 17), at about 238°. The sky was clear, with a thin warm band along the horizon and a few streaks of cloud.
  - **`cm4wide`:** the sun sets in frame, on the horizon just left of downtown (left third of the frame). There were no reflections, and the bracket and dense frames were taken every minute on both cameras.
  - **Sky scores** (provisional, from the original JPEGs over 23:52 to 00:52 UTC, the NAS job's own functions, run on the PC):
    - `cm4wide` **41, "some colour"** on its scale of 0.178 (best frame 00:22 UTC, 8.0% warm sky). The warm band is narrow and most of the sky is clear blue, so it scores lower than the cloudy Nov 8 and Nov 12 sunsets (67 to 69).
    - `cm4city` 100 (11.3% warm sky, top-5 mean). That is on the default scale of 0.10, which was never fitted to this camera, so it is not comparable.
  - **Sync lag:** the sync fell behind during the dense window, with 226 frames waiting on the Pi at 01:20 UTC and about 20 minutes per sync run on the Wi-Fi. Frames from 00:50 UTC reached the NAS at about 01:47 UTC. No frames were lost.
- **Daily video: the sky score is drawn on the video** (Steven, 2026-11-18). "Sky score NN" in small text, right-aligned on the location line, for the whole video. `nas/sunset-daily.py` 2026-11-18.1:
  - The score is now worked out before encoding.
  - The encoder gets the crop with `sky_score` added; the recorded crop is unchanged.
  - The sunset cut shows the score too.
  - A day with no score shows nothing, and `OVERLAY_SKY=0` turns it off.

  Tests in `tests/test_daily.py`: the text is drawn and its place checked, it shows on the last frame, there is no text without a score or with the option off, and on a real run the score is on the video but not in the record's crop. All 215 pass. Not yet run on the NAS; the Docker image has never been built.

- **Event: the CM4's network keeps dropping for about 2 minutes.** The network watchdog logged 17 "network back" lines from 04:01 to 15:50 UTC (9:01 pm Nov 16 to 8:50 am Nov 17), each after 2 minutes without the gateway (one after 4 minutes, 06:35 UTC). Seven were from 05:51 to 06:39 UTC, while the wired Ethernet was also connected. The wired address stopped answering by 15:30 UTC, so the CM4 is on the Wi-Fi dongle alone. Copying a 295 KB file over it took 42 s at 16:10 UTC. No frames were lost (local-first; nothing older than a few minutes waits for sync).
- **Health check: `tools/camera_check.py` and the `camera-check` skill** (`.claude/skills/camera-check/`; Steven asked for it, as he checks often). Read-only. Over ssh it reports per camera the 5-minute slots with no frame, the dense frames and every log line that isn't `ok`, plus throttling, temperature, disk, timers, the sync backlog and the network watchdog. It also copies each camera's newest frame, from the NAS when the PC can reach it, with brightness, clipping and sharpness numbers and a small copy to look at. Exits 1 with `WARN` lines if anything needs a look. The Pi's addresses and the NAS path are in the git-ignored `tools/camera_check.hosts`. Its first run (16:20 UTC) found:
  - every slot taken since the move, apart from the diag pauses during the re-aim (05:45 and 06:30 to 06:40 UTC on `cm4wide`)
  - `throttled=0x0`, 34 °C
  - two empty files from the Nov 16 freeze still in the CM4's outbox (`cm4wide_20261116T072500Z.jpg` and `_night.jpg`), which the sync skips

## 2026-11-16

- **Hardware and Pi (CM4): the 16 mm camera moved to the CM4's CAM1; `timelaps` retired from the window** (Steven, before 05:30 UTC Nov 17, about 10:30 pm Nov 16). The CM4 is on temporary wired Ethernet (address in `tools/camera_check.hosts`) as well as Wi-Fi. It came back up at 05:33 UTC and captured `cm4wide` frames from 05:33 to 05:40 UTC, still as `cm4-window-1` with `ROTATION=180`, while the wide camera now sits the other way up, so **those three frames are upside down and mislabelled**. `timelaps` (`wide`) has no frames after 04:10 UTC.
  - `dtoverlay=imx477,cam1` added to `config.txt` (backup `config.txt.bak-20261117-cam1`), rebooted at 05:41 UTC. Both cameras found. rpicam's numbering moved with it: camera 0 is now CAM1 (`i2c@1`, 16 mm) and camera 1 is CAM0 (`i2c@0`, wide), so capture without a choice would have used the 16 mm. Capture and dense timers stopped 05:43 to about 05:54 UTC; the 05:45 and 05:50 slots were not taken.
  - **New setting `CAMERA`** (`sunset-capture.sh`): the camera's port ID (matched in `--list-cameras`) or number; no match or several matches skips the frame; recorded as `camera` in `Capture.settings`. CM4 `sunset.env`: `CAMERA=i2c@0`, `ROTATION=0` (the wide camera is now upright), **`SETUP_ID=cm4-window-2`** from 05:52 UTC. Checked with one real capture (05:52 UTC night frame: upright, wide lens, `camera: i2c@0`).
  - **Diag page:** a button per camera to switch between them (`/camera?i=N`), and `diag start <camera> [0|180]` to start on one (`/run/sunset-diag.env`, read by the unit). Deployed with backups `*.bak-20261117-cam1`; switching checked on the page both ways. Started on the 16 mm for aligning at about 05:55 UTC; it is out of focus.
  - Tests written for both (`tests/cases/16b_camera_select.sh`, `CameraChoice` in `tests/test_diag.py`); the diag unit tests pass, the shell cases were not run (Steven asked to skip the suite for now). Note: `install.sh` rewrites every `dtoverlay=imx477` line to one value, so a reinstall would drop the CAM1 line. Not committed.
  - The 16 mm camera has no series name, `SETUP_ID` or capture yet. It could not be focused at infinity (iris works; at f/16 lights are still rings, so the lens sits too close or too far by more than the focus ring covers; the missing 5 mm C-to-CS spacer is the likely cause). Steven is putting the 6 mm back on that camera instead.
  - **New location: `SETUP_ID=cm4-window-3` from 06:51 UTC** (Steven: set up, settings stay as they are). Checked on full-resolution night frames at 06:49-06:50 UTC, with no room lights or LED spots showing in the glass on either camera:
    - **Wide (`cm4wide`, CAM0, 3.2 mm):** centre about 272.3° (target 271.2°), horizon within 26 px of before the move, about 1.5° roll against the Nov 16 frame, sharpness 1,098 against 1,074 before. In focus.
    - **Second camera (CAM1): the 6 mm lens, not the 16 mm.** Centre about 281.2° (downtown), horizon at about 43% from the top; against the `timelaps` 6 mm frame of Nov 16 (centre 268.2°, f 3,630 px). Sharp in the centre (the downtown skyline), softer at the edges, and the lower-left corner is smeared (cause not known; possibly the glass there). Not capturing yet: it has no series name, `SETUP_ID`, timers or alert.
  - **Second camera recording: series `cm4city`** (CM4 CAM1, UC-517 with the 6 mm lens, about 281°, `SETUP_ID=cm4city-window-1`), Steven's go-ahead. First frame 06:52:53 UTC (manual run), then on the timers from 06:55:30 UTC. New: `pi/sunset2.env.example` (installed as `~/sunset/sunset2.env`: `CAM_NAME=cm4city`, `CAMERA=i2c@1`, `ROTATION=0`, the 6 mm's `timelaps` night settings `NIGHT_LUX=5`, 4 s, gain 1, `NIGHT_AWB=2.25,2.40`), and `sunset-capture2`/`sunset-dense2` units and timers, which load `sunset.env` then `sunset2.env` and run 30 s after the first camera's (`*:00/5:30`, `*:*:30`). Both cameras share the capture lock, so only one shoots at a time. The sync already sends the whole outbox: `project_sunshine/cm4city/` on the NAS from the 06:59:37 UTC sync, read back and confirmed. The diag unit stops and restarts the second camera's timers too (checked). `cm4wide`'s `SETUP_NOTE` updated (B0240E, CAM0, upright). Home Assistant: `cm4city` frame-age and health sensors, binary sensors and alerts added to `homeassistant/sunset.yaml` (YAML parses; not installed in HA, which is a copy by hand). Not done: `install.sh` and `docs/setup.md` don't cover the second camera yet; the NAS daily video, archive check and daily health jobs don't run for `cm4city`; no offline tests for the new units.
  - **Repo follow-up (before commit):**
    - `pi/install.sh`: new `--cm4-two` writes `dtoverlay=imx477,cam0` and `,cam1`; `--uc517-cam0` now rewrites only a plain `dtoverlay=imx477` line (it used to rewrite every imx477 line, which would have dropped CAM1); installs the second camera's four units, and with `--enable` starts them only if `sunset2.env` exists. Tests in `tests/cases/61_install_lowwear.sh`.
    - `pi/hosts/cm4.env` brought up to the live file (read back from the Pi): `SETUP_ID=cm4-window-3`, `ROTATION=0`, `CAMERA=i2c@0`, `SAVE_RAW=0`, `BRACKET=1`, the new `SETUP_NOTE`.
    - `docs/setup.md` (CM4 hardware, overlays, rebuild steps, the diag camera switch and capture pause) and `CLAUDE.md` (the move's decisions).
    - The CM4's scripts and units match the repo by SHA-256, except `sunset-sun.py` (the Pi still has the version from before the #32 sun-in-view check, which does nothing without `VIEW_*`), a comment in the installed `sunset-sync.service`, and the UPS reader (not installed).
    - **Offline suite: 1,134 passed, 0 failed** (fuse tests OK), after fixes: `CAMERA` added to `sunset.env.example`; the `cm4city` Home Assistant names changed to match their IDs (`Sunset cm4city ...`); tests that assumed the old setup updated (`cm4.env` upright with `CAMERA=i2c@0`, three cameras with frame-age and health sensors); two of tonight's new tests corrected (the default-camera check and a diag link file left between tests).
    - **`nas/crop.cm4wide.json`: new calibration from 2026-11-17 for `cm4-window-3`.** Not a landmark fit: a homography between the Nov 16 06:00 and Nov 17 06:50 UTC night frames (534 matched points) carries the old fit over. Centre 272.3° (frame columns 1028 / 2028 / 3028 at 242.7° / 272.3° / 297.7°), f kept at 1,880 px (scale across the centre 0.996). Blur boxes moved through the same homography and checked on the frame; the far-left one is out of frame now. View top 100, height 2,400 (was 2,440) to keep the balcony rail out. `sky_full_warm` kept; recheck it and the bearings on a clear sunset. Nov 16 and earlier keep the old entry.
  - **Found: restarting the capture timers takes an extra frame.** When diag ends and its `ExecStopPost` starts the timers again, systemd 252 fired `sunset-capture.timer` at once, so `cm4wide` took an off-slot frame at 07:00:41 UTC besides the 07:00:00 one. Harmless to the series (names are the real time) but each diag session adds one. Not fixed.
  - `timelaps` is off, so the Home Assistant `wide` alerts (frames stale, camera health) will fire until they are removed or acknowledged.
  - **Capture paused for lens work** at Steven's request: capture and dense timers stopped at 06:27:50 UTC (last frame 06:25 UTC). Replaced at 06:28 UTC by a standing rule (Steven: pause capture whenever diagnostic mode is on): `sunset-diag.service` stops the capture and dense timers when it starts (`ExecStartPre=+`) and starts them again when it ends, by `diag stop`, the 30-minute limit or a crash (`ExecStopPost=+`). Checked on the CM4 with `diag stop` and `diag start`. Every diag session is now a gap in the series; sync keeps running. Not yet on `timelaps` (off). The offline tests were not run.
  - **Wide camera re-aimed and refocused for #4** (Steven, about 05:55-06:08 UTC, with the diag page). Measured on the 06:10 UTC night frame against Nov 16 06:00 UTC (SIFT homography, 476 inliers, old calibration f 1,880 px, centre 261.7°): centre now about **272.5°**, 10.8° right of before and 1.3° past the 271.2° target; centre row within 32 px of before; about 1.4° roll against the old frame; sharpness on the city band 1,126 against 1,069 before. Estimated frame about 225° to 320° (rectilinear, so the barrel lens is likely wider): about 8° spare past the Dec sunset and 11° past the June one. Frames from about 05:55 to 06:09 UTC were taken while it was being turned and focused. Still `cm4-window-2`.

- **Event: both Pis shut down for a move** (Steven). At about 04:12 UTC Nov 17 (9:12 pm Nov 16) every `sunset-*` and `exp-*` timer was stopped on both; a final sync left both outboxes empty (the CM4 keeps only the two 0-byte files from the Nov 16 freeze). Settings and logs were copied to `project_sunshine_config/<host>/shutdown-20261117/` and checked by SHA-256: `~/sunset` without the outbox (scripts, `sunset.env` and its backups, `capture.log`, `sync.log`, `kernel.log`, `netwatch.log`, the state files, experiment run logs), the systemd units, `fstab`, `config.txt`, `cmdline.txt`, the LED rule, crontab, the timer list, this boot's journal, `dmesg`, the package list. The NAS login file was not copied. Powered off at 04:17 UTC. The last frames are from 04:10 UTC (`wide` and `cm4wide`). The timers are still enabled, so capture restarts at boot; if the cameras' view changes, `SETUP_ID` must change too. The transient `exp-moon-1` to `-9` timers on `timelaps` (Nov 16-25) are gone, so experiment 18 needs scheduling again.

- **Pi (both): sync pacing deployed** at about 03:27 UTC Nov 17 (8:27 pm Nov 16) on `timelaps` and 03:28 UTC on the CM4, Steven's go-ahead. The new `sunset-sync.sh` (same SHA-256 as the repo) went in with an atomic move, and only `TimeoutStartSec` was changed in the installed unit (1800 to 3600; the user and paths stay as installed); old files kept as `*.bak-20261117-pacing`. `sync` before the CM4's `daemon-reload`, which went through with no freeze. The run already under way on the CM4 (old script, now with the 1-hour limit) finished at 03:38 UTC (`sync ok files=88`), and the first run of the new script at 03:42 UTC sent the rest (`sync ok files=24`), so the backlog was clear by 03:42 except the two 0-byte files. The `sync partial` stop has not happened live yet; the next evening bracket will show it.
- **Sync pacing (repo):** `pi/sunset-sync.sh` closes a batch at `SYNC_BATCH_MB` (32) as well as `SYNC_BATCH` files, and stops itself between batches after `SYNC_MAX_S` (1200 s), logging `sync partial confirmed=N pending=M kept=K`; the next timer run carries on. `TimeoutStartSec` in `sunset-sync.service` goes from 1800 to 3600, now only a backstop for a hung transfer. The cause, below: with 200-file batches each run spent its 30 minutes uploading and was killed before the read-back, so for hours nothing was confirmed and deleted.
- **Event (CM4): NAS copy behind after the first production bracket.** The sunset bracket (three JPEGs a minute for about 90 minutes) was more than the 2.4 Mbit/s Wi-Fi dongle could send and read back. Four sync runs in a row hit the unit's 30-minute limit (`sync interrupted`, 00:39 to 02:09 UTC Nov 17, 5:39-7:09 pm), with up to 340 files and 313 MB waiting on the card. No frames lost (local-first). The NAS had `cm4wide` frames only up to 01:03 UTC until the backlog drained after dark, so the Home Assistant CM4 alert probably fired. `timelaps` kept up. Two 0-byte files from the Nov 16 freeze (`cm4wide_20261116T072500Z.jpg` and `_night.jpg`) are still in the CM4's outbox; the sync leaves them on the card by design.
- **Event: first sunset with the production bracket** (00:27 UTC Nov 17, 5:27 pm), clear with broken cloud and a low bank over the mountains. Both cameras logged `bracket=2` on every frame in the window. **Sky score 71 on `cm4wide`** (13.6% warm sky at its best, 00:08 UTC / 5:08 pm), the best of the pilot so far and the first above the posting threshold of 60. The first `--fuse-production` build on real frames (90 ev0 and 90 ev-2 shots, 56 frames merged) held the sun's disc and the gold cloud from about 4:50 to 5:25 pm; after the merge fades out at 12 min past sunset, auto exposure turns the sky pale and washed out until about 5:55 pm, then the dusk is a deep blue. **New option `--fuse-until FROM,TO`** (`tools/build_video.py`; `fade_out` in `fuse_run`) moves the merge's fade-out. Rebuilt with `--fuse-until 30,40` (84 frames merged): from 5:40 to 5:55 pm the sky level is about 177 where it was 210-216, the orange horizon band stays, and the step into the dark blue at about 6 pm is smaller (sky 171 to 135, was 210 to 155). Repo only, not committed.
- **UPS (OpenUPS2), new cells, 5:46 pm (00:46 UTC Nov 17):** Steven fitted three charged Li-ion 18650s (4.167 V each, within 0.05 V), all facing + to the left as the board's slots are marked; the board joins them in series itself. Over USB alone the board showed 0 V for every cell until it was woken (the manual describes a ship mode that wakes on the P10 button or input power). With a 12 V 5 A supply on P1 (12.52 V measured) it ran from the cells: pack 12.49 V, cells 4.163, 4.164 and 4.165 V, 23-24 °C, output 12.43 V. The supply is too close to the pack voltage for the board to treat it as mains; Li-ion needs 13 V or more. Nothing charges, because the cells are above the board's charge limit until R20 is changed.
- Bench run of the UPS reader on those cells, 5:46 to 5:49 pm (00:46 to 00:49 UTC Nov 17), in WSL: it read the same values as the Mini-Box tool, and `source=battery`. With the low-battery limit raised to 4.25 V for the test, `low_battery` fired once and the timer pause was skipped as set (`UPS_PAUSE=0`). Cell noise (about 5 mV) and the charge moving 75 to 74% stayed inside the deadbands, so only keyframes were written. The real on-battery replies are now a test fixture (`tests/test_ups.py`, 26 tests). Mains lost and back not tested yet: it needs a supply of 13 V or more.
- UPS on a 24 V 1 A supply, about 8:40 pm (03:40 UTC Nov 17): the board switched to mains (`source=mains`, state 05), output following the input at 24.32 V, cells 4.157-4.163 V at 100% and not charging, 22-23 °C. But the board read the input as 24.24 V, and Steven's meter also put the supply over 24.0 V, above the board's 24 V input limit, so it was unplugged after one reading.
- **Decided by Steven, evening of Nov 16 (about 03:45 UTC Nov 17): keep the 24 V supply for the UPS**, although it reads just over the board's 24 V input limit (board 24.24 V). The 15 V supply stays on the shopping list as the fallback. Steven then ran the mains lost and back test by hand: with the adapter unplugged the output fell to 12.4 V (the pack, through to the output), and with it plugged back in it rose to 24.22 V. Both are inside the MyPi XT's 9-28 V input. - Reader bench run during a repeat, 8:48 to 8:56 pm (03:48 to 03:56 UTC Nov 17), in WSL on the 24 V supply: each switch logged once, no flapping. `mains_lost` at 03:52:07 (output 12.45 V on the cells), `mains_back` at 03:53:20 (input 24.26 V, output 24.33 V), `mains_lost` again at 03:53:53, with the adapter still out when the run ended. The input reading falling away after an unplug (3.62 V, then 0) was logged as a change of `vin` only, not as another event. Cells 4.16-4.17 V, 22-26 °C. Mains lost and back is now tested on the board and in the reader.
- The cells fitted on Nov 16 are rated 2,500 mAh each (from their labels, read by Steven about 8:55 pm, 03:55 UTC Nov 17). In series the pack is still 2,500 mAh, so the board's `CAPACITY` (set to 3400 for the old 34Ts) was changed to 2500 by Steven in the Mini-Box tool, about 8:57 pm (03:57 UTC Nov 17). Our reader doesn't read settings, so this is from the tool only.
- **Decided by Steven, about 9:00 pm (04:00 UTC Nov 17): R20 on the OpenUPS2 stays as fitted; the boards won't be modified.** With Li-ion firmware 1.6 and the original R20 the board stops charging at about 3.5-3.6 V per cell, so the cells (now 4.16 V) run down to that level and are held there: less runtime in an outage, longer cell life at a warm window. The reader's low-battery limit (3.45 V a cell) and the deadbands are to be checked against that level once the cells settle.

- **Video options for the dusk colour and the sunset flicker, repo only (`tools/build_video.py`, `tools/fuse_sunset.py`), off unless asked for.** `--dusk-gains R,B` re-colours frames after sunset as if shot with fixed colour gains, ramping in over `--dusk-ramp` (5 to 15 min after sunset), from each frame's own `ColourGains`. `--deflicker MIN` steadies the 1-a-minute frames area by area (a smooth low-resolution gain map towards the mean of MIN minutes either side, at most `SMOOTH_MAX_GAIN`). `--blend-weights` sets the neighbour blend (default 1,2,1). Rebuilt the best sunset so far, Nov 12 on `cm4wide` (sky score 48 against 10-21 on Nov 13-15), with `--dusk-gains 2.20,2.80 --deflicker 3`: the sky level from 00:10 to 00:22 UTC (5:10-5:22 pm) holds at 152-154 where it swung 146-164, the largest coarse frame-to-frame change from 00:00 to 00:30 UTC fell from 11.3 to 4.1, and the dusk from about 15 min after sunset is blue instead of teal. A grey-cyan stretch remains at about 6 to 12 min after sunset. Also found: on Nov 11 the CM4 frames scored 61 only because they were upside down (street lights in the top of the frame); rotated, 3.

- **Pi (both): a freeze can no longer leave an empty `system.json` on the NAS** (#37). Deployed at about 19:03 UTC (12:03 pm), `sunset-meta.py` and `sunset-sync.sh` only, old files kept as `*.bak-20261116-systemjson`. `sunset-meta.py` now flushes the day file and its state file to disk before renaming them into place. A day file that is present but empty or unreadable is written again from the state file on the next frame. The sync holds back an empty `system.json` (logged once, kept on the card) until that happens; other empty files still ship as before. On Nov 16 the empty file was synced at 07:28 UTC, two minutes before the next frame could have repaired it.
- **NAS: Nov 16's `cm4wide/2026/11/16/system.json` repaired** at about 18:54 UTC (11:54 am), Steven's go-ahead: the empty file was replaced with the CM4's state file for that day (4 records, 00:00 to 07:25 UTC, the eMMC wear from 05:05). Copied as is, checked identical.
- **Calibration programs (#12), repo only:** the experiment runner gains `dark` (lens capped: 5 frames each at 4 s and 8 s, gain 1, and 5 bias frames at 100 µs, all with DNG), `flat` (white diffuser: 9 auto frames with DNG) and `checker` (30 JPEGs, one every 4 s, while a checkerboard is moved), each one command. Smoke test on `timelaps` at about 18:18 UTC (11:18 am), one frame of each from a scratch copy, no cap or diffuser: exposures as asked (4.00 s, 8.00 s, 110 µs), uploaded to the experiments folder, then deleted again. Captures unaffected. The deployed runner is unchanged.
- **Test fix:** the dense-frame tests failed whenever the suite ran at minute :00 (0 is a multiple of any `SLOT_EVERY_MIN`, so dense mode exits quietly). A `date` test stub now pins the UTC minute, with a check that minute :00 gives no dense frame. No change to the capture script.
- **Fog scan labels glare (#33), repo only, no alert:** `tools/fog_scan.py` reads `Sun.azimuth_deg` too, and each low-clarity run gets a cause: `glare` when most of its frames have the sun low in front of the window (0-15° up, within 60° of west), otherwise `fog` (weather, condensation, smoke). Old per-day caches are re-read once. At 5-minute steps on Nov 15: `glare` 23:05-23:25 UTC on both cameras (clarity down to 0.22 on `wide`, 0.34 on `cm4wide`), and `fog` 16:10-16:25 UTC on `wide` only. At 15-minute steps Nov 10 stays `fog`.
- **Event, found 2026-11-16 (#33):** Nov 15, rain in the morning: wet streets and a grey, hazy distance, clarity down to 0.23 on `wide` at about 16:10-16:25 UTC (9:10-9:25 am).
- **Sun-in-view check (#32), repo only, nothing on the Pis:** `pi/sunset-sun.py view` and `view-calendar` tell whether, and on which days and times, the sun is inside a camera's view, from new `sunset.env` settings `VIEW_BEARING`, `VIEW_HFOV`, `VIEW_VFOV`, `VIEW_TILT` and `VIEW_MARGIN` (rectilinear lens, no roll). With `VIEW_BEARING` set, each frame's `Sun` block also gets `in_view`, `view_x_deg` and `view_y_deg`; unset, frames are unchanged. For the 16 mm lens's estimated aim (281° true, 22.2° x 16.8°, tilt 2°) the sun is in the frame from about Mar 19 to May 31 and Jul 11 to Sep 23, up to 70 min an evening and up to about 10° high. The aim is an estimate until the lens is on and measured. This does not protect the sensor: there is no shutter, so only the iris or an ND filter does that.
- **Home Assistant NAS free-space limit 350 → 100 GB (#7), repo only:** with no DNGs the two cameras use about 3 GB a day (0.76 GB in the 8 hours after 09:15 UTC, plus the sunset dense and bracket frames), so 100 GB is about a month. Not installed in HA yet (#37). The share had 385 GB free at about 17:30 UTC.

- **Pi (both): RAW off** (Steven, #38). `SAVE_RAW=0` in `sunset.env` at about 09:11 UTC (2:11 am Vancouver), backup `sunset.env.bak-20261116-noraw`. The 09:15 captures logged `raw=0`, and the night frames have no DNG either. This also stops the bracket's ev-2 DNG. The last DNGs are from 09:10 UTC. The reason: `experiments/raw_value.py`, run on 19 real DNG/JPEG pairs from both cameras, found the DNG holds only 0.3-0.6 stops more highlight than the JPEG and nothing in the shadows. At the good Nov 12 sunset the production frame's DNG still clipped 2.4% of the frame, where the ev-2 bracket JPEG clipped 1.1-1.3%. Results on #38.
- **NAS: every DNG deleted** at about 09:20 UTC, with Steven's go-ahead: 6,325 files, about 157 GB (`wide` 4,144, `cm4wide` 1,978, 2 more that synced during the count, and 201 in the experiments folder). JPEG and JSON untouched. Free space went from 241 GB to 387 GB. The 9 DNGs still waiting in the CM4's outbox were deleted there instead of being synced. One CM4 sync at 09:19:42 logged `FAILED read-back kept=1`: a DNG removed from the NAS while that sync was checking it. Frames before 09:15 UTC keep their DNG checksum in `Capture.files`, although the file is gone.

- **Fog measurement (#33), repo only, no alert:** `tools/fog_scan.py` measures each 5-minute frame's sharpness, contrast and brightness on the skyline band and gives it a clarity: its sharpness over the median of the same half hour on up to 7 earlier days with the same `SETUP_ID`. Run on every pilot day (every 15th minute): Nov 10 on `wide` reads 0.49 median in daylight, with clarity down to 0.23 (a real low-visibility day, rain or mist, skyline gone). Nov 15 at 23:15 UTC reads 0.27 (`wide`) and 0.37 (`cm4wide`), but that is low-sun flare through the glass, not fog. Clear days read 0.9-1.25. Tested on synthetic images and those real frames.
- **Event, found 2026-11-16 (#33):** Nov 10 (UTC) was a low-visibility day from about 18:00 to 21:45 UTC (10 am-1:45 pm): the downtown skyline is gone and the scene grey.
- **Pi (both), checked 2026-11-16 ~07:46 UTC:** a dense frame with the bracket pair takes 12.6 s on `timelaps` and 11.0 s on the CM4 (real camera, scratch folder, fake 20 min before sunset). At night ev+0 and ev-2 read the same exposure because 1 s is too short for auto exposure to move; at sunset the experiment's pairs show ev-2 at about 4x less exposure x gain, down to 52 lux.
- **Pi (both): production sunset bracket on** (#10, Steven's go-ahead), for a week beside production. At about 07:23 UTC (12:23 am Vancouver) `sunset-capture.sh` and `sunset-meta.py` from commit d2f256f were deployed (old files kept as `*.bak-20261116-bracket`), and `BRACKET=1` was added to `sunset.env` (backup `sunset.env.bak-20261116-bracket`). `exp-sunset.timer` is disabled on both, so the nightly experiment no longer runs; the moon and weather timers are unchanged. Before switching it on, one real capture per Pi went into a scratch folder with the window widened to cover the night: the pair and the ev-2 DNG were written, `Capture.kind` `bracket`, and the CM4 kept `rotation: 180`. The whole night capture with the pair took about 20 s (`timelaps`) and 22 s (CM4). The scratch files were removed. The first real bracket is the sunset of 00:27 UTC Nov 17 (5:27 pm Nov 16 Vancouver).
- **Event (CM4): froze and rebooted at about 07:26 UTC** (12:26 am Vancouver), while `sudo systemctl disable --now exp-sunset.timer` was running over SSH. The last kernel line was at 07:23:05 (a Wi-Fi reassociation) and there was nothing after it, consistent with the 15 s hardware watchdog resetting a hard freeze. Cause unproven: the systemd reload in that command is a suspect, so it was redone with `stop` and `disable --no-reload`, which went through. The `sunset.env` edit made seconds before the freeze was lost (the root file system commits every 60 s) and was made again, followed by `sync`. The deployed scripts survived. The 07:30 capture was ok (it logs `bracket=0`, so the setting is loaded). **Corrected 2026-11-16 (#37): one frame was lost.** The 07:25 capture logged `ok`, but its JPEGs and DNGs were still uncommitted when the CM4 froze, so they came back 0 bytes after the reboot; the sync skipped them, and only the two JSON files reached the NAS. The day's `system.json` on the NAS was written at the same moment and is also 0 bytes. The CM4's own state file kept it intact, so it isn't rewritten, and Nov 16 has no system record on the NAS. Nov 17's will be written fresh.

- **Production sunset bracket built (#10, option E). Repo only: off by default, nothing on the Pis.** `BRACKET=1` in `sunset.env` makes `pi/sunset-capture.sh` follow every frame (regular or dense) within `BRACKET_WINDOW_MIN` (45) of sunset with an ev+0 and an ev-2 shot, saved beside it as `<frame>_ev0.jpg/.json` and `<frame>_ev-2.jpg/.json` (`Capture.kind` `bracket`, with `ev`, `awb`, `bracket_of`). Daylight white balance until `BRACKET_AWB_HANDOVER_MIN` (10) after sunset, then auto; a DNG on the ev-2 shot within `BRACKET_RAW_MIN` (30) unless the disk guard drops DNGs. A failed bracket shot logs `WARN bracket` and never costs the frame. New `PROFILE_ID` setting, written as `Capture.profile_id`. `tools/fuse_sunset.py` reads the production pairs and `tools/build_video.py --fuse-production` merges them in place of an experiment run; the daily video and health jobs ignore the `_ev*` files. Tested offline only (stub camera, synthetic images); timing on the real cameras unmeasured. Estimated extra data per camera: about 180 JPEGs and 60 DNGs (~1.5 GB) a day.

- **Pi (both): merged code deployed** at about 05:00 UTC (Nov 15, 10:00 pm Vancouver): capture, sync, metadata, sun, diag, selftest and netwatch scripts and the experiment runner, the same as `main` after PR #31 and PR #36. Units and `sunset.env` unchanged; the UPS reader is not installed. Old files kept as `~/sunset-backup-20261116-deploy.tgz` on each Pi. Live from it: the read-back before delete, the `sunset.env` check, the config backup (first at 05:03:46 UTC to `project_sunshine_config/<host>/`), the capture hardening of #31. The 05:05 UTC captures were `ok` on both and reached the NAS with the new metadata (`Sun.algorithm` noaa-1, `Capture` schema 2). Home Assistant and the NAS jobs are not installed yet (#37). No frames lost.
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

## Archive: the brief before 2026-11-22

Until 2026-11-22 `CLAUDE.md` mixed the current state with the pilot's history, and much of the history
before 2026-11-15 was recorded only there. When `CLAUDE.md` was cut down to the current state and decisions
(batch B, Steven's decision), its sections from "Decisions made" to the backlog were moved here word for word.
They describe the project as it was on 2026-11-22; where they disagree with `CLAUDE.md` or the dated entries
above, those are current.

### Decisions made
- **The move of 2026-11-17 (Steven; details in `changelog.md`):**
  - **`timelaps` retired** from the window (last frame 04:10 UTC Nov 17). Its HA `wide` alerts will
    fire until removed. Everything now runs on the CM4 `sunshine`.
  - **Two cameras on the CM4.** CAM0: the 3.2 mm `cm4wide` (official series), now **upright,
    `ROTATION=0`** (replaces the #12 decision to keep it upside down), aimed for #4 at about 272°,
    `SETUP_ID=cm4-window-3`. CAM1: the UC-517 with the **6 mm** lens (the 16 mm could not reach
    infinity; most likely the 5 mm C-to-CS spacer is missing), series **`cm4city`**, about 281°
    (downtown), `SETUP_ID=cm4city-window-1`, from `~/sunset/sunset2.env` and the
    `sunset-capture2`/`sunset-dense2` units, 30 s after the first camera, sharing its lock.
  - **Cameras are chosen by port ID** (`CAMERA=i2c@0` / `i2c@1`): with both ports on, rpicam calls
    CAM1 camera 0. `install.sh --cm4-two` writes both overlays.
  - **Diag mode pauses capture** of both cameras while it is on; the page has a camera switch. Ending it during a UPS low-battery pause hands its timers to the pause instead of starting them (2026-11-21).
  - The CM4 is on Wi-Fi only from 2026-11-20 (Steven unplugged the temporary wired Ethernet); addresses only in the git-ignored `tools/camera_check.hosts`, whose `key=` word lets the Wi-Fi address use the wired one's host key.
  - **`nas/crop.cm4wide.json` re-fitted for the new heading** (new calibration from 2026-11-17).
- **Decisions of 2026-11-16 (Steven, walked through the open issues; details on each issue):**
  - **Storage (#5, #9), reversed the same day:** no DNGs. **`SAVE_RAW=0` on both Pis from 09:15 UTC
    2026-11-16, and all 6,325 DNGs on the NAS deleted (~157 GB; Steven, #38).** The test
    (`experiments/raw_value.py`, removed 2026-11-21, in git history) found the DNG holds only 0.3-0.6 stops more highlight than the JPEG,
    nothing in the shadows, and at sunset the ev-2 bracket JPEG keeps about twice as much sky. JPEG only
    is about 3.3 GB a day for both cameras. The script's default is still `SAVE_RAW=1`, so a rebuilt Pi
    needs `SAVE_RAW=0` in `sunset.env` (as in `sunset.env.example`). No second copy (#13). NAS space (#7):
    387 GB free after the delete; the rest of the 11 TB share is other data.
  - **Sunset profile (#10):** build option E into production (ev+0 + ev-2 each minute in the dense
    window, daylight white balance handing over at about +10 min), tested offline, a week beside
    production, live only with Steven's go-ahead. Until then the sunset program runs on both
    cameras every evening (`exp-sunset.timer`, 23:00 UTC, a unit file so it survives a reboot;
    runs `sunset-YYYYMMDD` / `cm4-sunset-YYYYMMDD`, from the evening of Nov 16). **Settings freeze Dec 14**, with a `PROFILE_ID` in `Capture`.
    **Live on both Pis from 2026-11-16 ~07:30 UTC (`BRACKET=1`, `exp-sunset.timer` disabled), for a
    week beside production; first sunset Nov 17 00:27 UTC.** `BRACKET=1` adds ev+0/ev-2 after every frame
    within 45 min of sunset (`<frame>_ev0.*`, `_ev-2.*`, `Capture.kind` `bracket`), daylight WB to +10 min,
    a DNG on ev-2 within 30 min; merged by `fuse_sunset.py` (`build_video.py --fuse-production`).
    Tested offline, plus one real night capture per Pi (~20 s with the pair); not yet at a real sunset.
  - **Series and setup (#12, #4):** the CM4 `cm4wide` is the official five-year series (the second,
    detailed view is now `cm4city`; `timelaps` retired Nov 17). Aim as in #4 (CM4 about 9.5° right,
    equinox sunset on the centre line; #11 closed into #4). Wired Ethernet to the CM4 before Dec 21.
    (The camera was upside down, `ROTATION=180`, until the move of Nov 17; it is upright now.)
  - **Video (#21, #20):** the daily video stays the whole day (no sunset-only main cut), no master
    render, and **the sunrise dense frames stop** (patched into both Pis' running capture script at
    about 04:45 UTC Nov 16; the `DENSE_WINDOWS` setting was removed on 2026-11-21). How the long film handles gaps is decided when it is edited.
  - **Instagram (#2):** public posts are fine with the towers blurred and no location tag; captions
    name the city only; posting starts only once the sky score gates it, at a threshold of **60**
    (**kept at 60, Steven 2026-11-20**). **Steven uploads by hand to his personal account (2026-11-20)**, so
    no automated publisher or login is needed. **ToDo: the Instagram videos need open-source-licensed
    music added** (was "a licensed music track").
  - **Monitoring (#22):** no outside heartbeat.
  - **UPS cells (#29):** Li-ion on firmware 1.6. **R20 stays as fitted (Steven, 2026-11-16: the boards won't be modified)**, so the board stops charging at about 3.5-3.6 V per cell.
- Capture every **5 min, 24/7**, day and night (changed from 15 min on 2026-11-07 at Steven's
  request). Dark slots still add the night frame. JPEG only since 2026-11-16 (`SAVE_RAW=0`), about
  3.3 GB a day for both cameras. `SLOT_S` in the experiment runner must match the timer (a test
  checks it).
- **Dense frames around sunset (decided 2026-11-07, starts 02:30 UTC 2026-11-09; the sunrise
  window was dropped 2026-11-16):**
  Steven chose 1 a minute after comparing daily videos at 15, 5, 3 and 1 min. Window: 60 min
  before sunset to the sun at -9°. On top of the 5-min frames, in the same
  folder and names, JPEG + JSON only, same auto exposure, `Capture.schedule: "dense"`. The regular
  slot always wins the camera. `sunset-dense.timer`; details in `docs/setup.md`. About 230 extra
  frames a day in November, roughly 1 GB a day more on the NAS. The ×3 bracket is not done.
- **Post only the good sunsets to Instagram (decided 2026-11-11):** the daily video is still made
  every day, but only a day whose sky scores above a set value is posted. Most grey, overcast
  sunsets aren't worth showing. The score is deterministic image maths on the sunset frames (no AI,
  no tokens); see backlog #11. Until it exists and is tuned, nothing posts anyway (`POST_ENABLED=0`).
- **Instagram video from the CM4 camera (2026-11-12, Steven's requests):** starts at 07:30 local
  (`VIDEO_START_LOCAL`), handle `@funvill`, and a small third line `Burnaby, BC, Canada   WSW 243°`
  (place and the bearing at the middle of the crop). The near towers get a light blur (`blur` boxes in
  `crop.json`). The caption still has no location. `cm4wide` is calibrated on the sun's disc in the ev-2 frames
  (`nas/crop.cm4wide.json`, f 1,880 px): `cm4-window-1` 263.9° at the centre (Nov 16; the skyline-landmark
  fit of 261.7° was 2.2° off), `cm4-window-3` 272.3°, checked on the Nov 17 sun (272.07°). Build
  a day with `tools/build_video.py`, no AI. The crop `view` is top 100, height 2440 (2026-11-13): as
  tall as it can be without the lower balcony in the corner (2,560 showed a sliver of rail). Steven
  said the merged sunset exposure (`fuse_sunset.py`, option E) looks better, so it is the way the
  sunset video is made. Jitter at the sunset was from fused frames held or lost where the bracket had
  gaps, plus the bracket's exposure hunting; both fixed. What is left is real cloud flicker. **Raw frames:** looked at and not adopted for now. The DNG
  clips where the JPEG does (0.2% either way at sunset), so the sunset fix is exposure (the ev-2
  merge, experiment 19), not raw; dense frames have no DNG; a raw pipeline needs `rawpy` and a grade.
  #5 is decided: no DNGs (`SAVE_RAW=0`, 2026-11-16).
- **Two cameras** (both live since 2026-11-17): one wide (all sunsets), one tight (downtown).
- Hidden, compact setup. DSLR/mirrorless considered and set aside for size/visibility,
  though a used Sony a6300/a6400 tethered via gphoto2 remains the image-quality upgrade path.
- Save **JPEG + per-frame metadata** (the DNG was dropped 2026-11-16). Filenames in **UTC**. Layout
  unchanged: `outbox/<cam>/YYYY/MM/DD/<cam>_<UTC>.{jpg,json}` (+ `_night.*`). Frames are staged in
  `outbox/.partial/` and moved into place when complete; the sync ignores dot-directories.
- **Clock policy (decided in review, change if you disagree):** the CM4's RTC has no coin cell, so
  it does not keep time through a power cut. Capture
  refuses to run until NTP has synced once since boot (`SKIPPED` in `capture.log`, exit 1), then
  keeps going through later NTP outages. A gap is preferred to frames with a wrong UTC name.
  `REQUIRE_TIME_SYNC=0` turns it off. A DS3231 RTC would remove the gap after power cuts
  (not bought; your call).
- **Disk guard:** ≥85% full drops the DNG, ≥95% skips the night frame, <100 MB free skips the
  capture. All logged. Does not change the 5-min schedule.
- **Per-frame sun data:** each `.json` gets a `Sun` block (true-north azimuth, elevation, nearest
  sunset, minutes from sunset). Site coordinates live in `sunset.env` (`SITE_LAT`/`SITE_LON`,
  currently approximate Burnaby, **set the real ones**) and are not written into frame files.
  But the `Sun` block itself locates the site to about 30 m (#25), so **frame JSON is private:
  any path that publishes JSON must strip `Sun` first** (decided 2026-11-16).
- **Per-frame `Capture` and `System` blocks, daily `system.json` (2026-11-04):** `sunset-meta.py`
  adds how the frame was taken and the machine's state at that moment, including image checksums,
  CPU temperature and disk space. What rarely changes (model, OS, kernel, versions, SD card, setup
  note) goes in one `system.json` in each UTC day folder, and `Capture.system_id` links the two.
  Frames before 20:15 UTC that day have no blocks; those from 20:15 to 21:30 UTC carry everything
  on the frame (`schema_version` 1). It never touches the NAS path, and it leaves out anything
  identifying (see `docs/setup.md`). **Change `SETUP_ID` in `sunset.env` whenever the camera, lens,
  focus, iris, mount or hood changes**, including at the bracket move.
- **Local-first storage**, rsync to NAS, delete local only after confirmed copy: on the mounted share the
  sync reads the NAS copy back first (size, SHA-256 up to 8 MB, the DNG's ends; 2026-11-16, #13). Capture
  refuses to run without `sunset.env` (`REQUIRE_ENV_FILE`, #23), and the sync backs up `sunset.env`, `fstab`
  and `config.txt` to `project_sunshine_config/<host>/` on the share.
  (Writing straight to the NAS was rejected: a prior year-long Pi project lost frames when the
  NAS share didn't return after a power cut.)
- Monitoring: **Home Assistant alerts on the age of the newest file on the NAS** (> ~1 h).
- **Freeze recovery (2026-11-05):** `install.sh` sets systemd's hardware watchdog to 15 s, so a hard
  freeze should reboot the Pi, and the capture and sync timers come back by themselves. Tested with
  a deliberate kernel panic: back on the network in 44 s. A partial freeze that leaves systemd
  running won't trigger it, and a reboot clears any transient `exp-*` timers. `sunset-kernlog.service` keeps kernel
  messages in `~/sunset/kernel.log` (up to two 1 MB files), flushed per line, because system logs
  are in RAM and are lost on reboot.
- **Camera failure recovery (2026-11-20, Steven asked):** `sunset-camwatch.sh` (`CAMWATCH=1`) reboots
  when one camera fails 3 captures within 60 minutes since boot, at most every 6 h. A window, not
  "in a row": the Nov 19 failures were scattered. A reboot is the only fix known to work so far.
  Live on `sunshine` from 16:44 UTC 2026-11-20; it logs to `~/sunset/camwatch.log` only when it acts.
- Freeze software once stable: pinned OS, no auto-updates, full SD image saved on the NAS.
- Mount: 3D printed in **PETG or ASA** (not PLA — sun heat), stuck to glass with **3M VHB**
  (no suction cups), **keyed two-part design** so a replacement camera returns to the same framing,
  **black foam hood sealed against the glass** to kill reflections, camera square to the glass.

### Current phase: pilot on a Pi 3 B+ (decision changed 2026-11-03)
- **Pilot moved from the Pi Zero W to a Pi 3 B+ Rev 1.3**, hostname `timelaps`, user `funvill`,
  because that is the setup where the UC-517 is known to work. Raspberry Pi OS Bookworm 32-bit
  (armv7l), not reflashed. On its built-in Wi-Fi (no Ethernet link since about Nov 5). Clock zone is America/Vancouver (changed from America/Adak 2026-11-04;
  `tzdata` 2026c gives UTC-7 all year, shown as `MST`); filenames are UTC and nothing depends on the zone.
- **Camera: Arducam UC-517** in the CAMERA port, `camera_auto_detect=0` + `dtoverlay=imx477`
  (auto-detect does not find it). Manually focused on the distant view.
- 5-min captures, plus 1-a-minute dense frames around sunset (sunrise too until Nov 16) from the sunset of
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
- **NAS:** SMB share `camera` on the NAS (host name kept out of the repo), folder `project_sunshine`, its own NAS user, not
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
  **Undervoltage again on 2026-11-12, 00:16-00:19 UTC** (three warnings, `throttled=0xd0000`), while the cameras
  were being moved: likely a moved cable or a brief extra load. None before or since on the new supply.
- **Freeze (2026-11-05):** `timelaps` froze at about 01:26 UTC during an experiment run: red light
  on, no green, no network, until a power-cycle at about 06:04 UTC. 19 production frames lost. Cause
  unproven because the logs were in RAM; undervoltage is the leading suspect, with 7 warnings in the
  first 7 minutes after the reboot. Not ruled out: a kernel or camera-stack bug.
- **Timers on (2026-11-04), before the new supply:** Steven's other tools read the frames on the NAS,
  so sync and capture are enabled despite the undervoltage. Expect possible gaps until it's fixed.
- **NAS space:** the share had 126 GB free on 2026-11-16, and 387 GB after the DNGs were deleted the
  same day. JPEG only, both cameras use about 3.3 GB a day (#7, #9).
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
- **CM4 experiments (2026-11-12, plan on #3):** 20, a night sweep (`cm4-sweep-1`, Nov 12 04:00-14:00 UTC); 21, the sunset
  options alongside experiment 19 (`cm4-sunset-1` to `-3`, Nov 12-14); 22, the lens geometry from the sun on clear
  evenings; 23, vignetting and sharpness; 24, Wi-Fi sync health; 25, the room-light glow (needs Steven). The runner
  reads `ROTATION`. These are transient timers on the CM4, so a reboot clears them.
  **Experiment 20 result (night sweep, Nov 12):** the CM4's 3.2 mm lens gets about 1.3 stops less light than
  the 6 mm one (its 4 s night sky is 40-43 where `timelaps` gives 67-73 on the same night). Gain 1 is still best.
  **Applied 2026-11-12 22:15 UTC at Steven's go-ahead**, CM4 only: `NIGHT_SHUTTER_US=8000000` (most downtown detail, less noise, 2.8%
  clipped) and `NIGHT_AWB=2.20,2.80`. This board passes less blue: at 2.25/2.40 its sky is yellow-brown (B/G 0.70),
  and 2.20/2.80 matches `timelaps`' neutral sky (1.05, 0.97). Denoise, contrast, saturation, sharpness: defaults.
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
  runs hourly at :07 from `exp-weather.timer` (on `sunshine` from 2026-11-20 18:03 UTC; it ran on
  `timelaps` until that Pi was retired, so there is no forecast from 04:07 UTC Nov 17 to then; a unit file, not a transient timer, so it survives a
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
- **Home Assistant alert (2026-11-05):** installed from `homeassistant/`. HA reads the NAS share
  directly at `/share/camera`, with its own copy of the `camera` login, and alerts about 70 to 75
  minutes after the last frame. **Reconfigured 2026-11-20:** the `timelaps` checks removed, and frame
  age, camera health for both CM4 cameras, NAS free space and **"CM4 on battery"** (`sunset_ups.sh`)
  installed. The NAS-job alerts are left out because those jobs don't run yet. HA is at
  `homeassistant.local` on port 80 (not 8123), and its config is edited with the File editor add-on.
  HA's copy had no phone notifier (found 2026-11-20). **The Pixel 8 (`mobile_app_pixel_8`) was added to all six
  alerts at 20:22 UTC Nov 20**, in HA's copy only (the repo keeps the placeholder).
- **Not done yet:** confirming the new supply over several days, final mounting and framing (keyed mount
  waiting on Steven's 3D printer, #35). **Foam hood fitted** (between 23:30 UTC Nov 19 and 16:00 UTC Nov 20;
  `SETUP_ID` `cm4-window-4` / `cm4city-window-2` from 19:16 UTC Nov 20).
- **To do: heatsink on `timelaps` (2026-11-08).** SoC temperature at capture is 54.8 to 58.5 °C,
  and the Pi 3 B+ soft limit is 60 °C (`throttled=0x80000`: reached since boot). It runs close to
  the limit while experiments add load, and summer sun through the window will add more. On the
  sunny afternoon of Nov 8, with the diag stream running, it reached 61.8 °C and the soft limit was
  active (`0x80008`, CPU held at 1.2 GHz); captures were unaffected. A small
  stick-on heatsink is enough to start with (a buying decision, Steven's call).

#### Pilot goals
1. Window reflections with the foam hood, day and night (double-glazing ghosts).
2. Night exposure: tune `NIGHT_LUX`, `NIGHT_SHUTTER_US`, `NIGHT_GAIN`.
3. Condensation on cold winter glass.
4. Pi performance: capture time, memory, Wi-Fi or Ethernet reliability. First results on the
   Pi 3 B+: ~7 s day shot and ~12 s night shot, each with DNG; DNG 24.8 MB.
5. NAS sync + Home Assistant alert end to end.
6. Confirm framing/FOV of the chosen lens against the sunset swing.

### Hardware inventory (on hand)
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
  kernel 6.12.109-v8. rpicam-apps 1.9.0, libcamera 0.5.
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
  is no coin cell in the RTC holder yet** (ToDo, Steven), so it only keeps time through a
  reboot, not a power cut. Don't depend on it: capture keeps waiting for NTP (`REQUIRE_TIME_SYNC=1`). One test
  capture through `sunset-capture.service` (2026-11-11 23:44 UTC) went through cleanly and synced to
  `project_sunshine/cm4wide/`.
  **At the window from 2026-11-12 ~00:30 UTC** (`SETUP_ID=cm4-window-1`), on Wi-Fi through an old
  Buffalo 2.4 GHz USB dongle (about 2.4 Mbit/s to the NAS). **Replaced 2026-11-20 by an AIC8800D80
  dongle on 5 GHz (about 88 Mbit/s)**, which needs an out-of-tree driver built for the running kernel
  (`docs/setup.md`, "AIC8800 Wi-Fi dongle"); Ethernet is going away, so Wi-Fi is the CM4's only link. **Capturing since
  2026-11-12 00:35 UTC** (Steven's go-ahead): the 5-minute, dense and sync timers, same schedule as
  `timelaps`. HA has a separate CM4 alert (`cm4wide`) from 2026-11-12, same 60-minute limit, also
  sent to the phone.
  **Wi-Fi outage 2026-11-13, 02:48-04:35 UTC:** the dongle dropped off and never rejoined until Steven power-cycled
  it. No frames lost (local-first), the HA alert fired, the backlog synced. Cause unproven (dongle or driver hang
  suspected). **Network watchdog added the same night** (`sunset-netwatch.sh`, `NETWATCH=1` on the CM4 only):
  resets the dongle after 10 min without the gateway, reboots after 30 min (at most every 6 h). Tested live:
  the dongle rejoined in 6 s. Wired Ethernet would still be better.
  **Until 2026-11-17 the camera was mounted upside down** (upright since the move). `ROTATION=180` in its `sunset.env` (new setting, 2026-11-12)
  makes rpicam flip the readout, so frames from **01:08 UTC** on are upright, DNG included, and say
  `rotation: 180` in `Capture.settings`. Frames from 00:35 to 01:07 UTC are upside down. `timelaps`
  runs the same script with the setting left at its default of 0 (both Pis on the same code since 2026-11-13). It points down more than `timelaps`: the horizon is about 44% from the top, with the
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
- **UPS: Mini-Box OpenUPS2** (USB `04D8:D005`, identified 2026-11-15), 11-24 V in, 12-24 V out, 3S 18650.
  For the CM4 `sunshine` (MyPi XT, 9-28 V in), not `timelaps`. Built for LiFePO4; the three 18650-34T
  Li-ion cells need R20 changed to 576k plus Li-ion firmware 1.6 to charge fully. **Decided 2026-11-15: run
  the 34T Li-ion cells with the R20 change and firmware 1.6**, charge temperatures limited to 5-45 °C. As found,
  the board was unconfigured LiFePO4 firmware v1.1; flashed to v1.6 Li-ion on 2026-11-15 (R20 not yet changed),
  then set `CAPACITY` 3400 mAh (2500 from Nov 17, for the new cells) and `CHG_TEMP_WARM`/`HOT` 40/45 °C.
  **Integration decided 2026-11-16 (plan on #29):** status read by our own stdlib Python reader over
  `/dev/hidraw` (Mini-Box's `0x81`/`0x83` status messages, read-only), not NUT; `~/sunset/ups.log`
  written only when a value changes beyond its deadband, on events, and a keyframe every 4 h (minimal SD
  writes; live status only in `/run`), rotated by the script daily or at 256 KB, 14 files kept;
  tested on the bench before it goes on `sunshine`; on low battery pause the capture/dense/sync timers rather than halt
  (a halted Pi stays off if mains returns before the UPS cuts out); HA "on battery" alert installed 2026-11-20; `ups_source` and
  `ups_charge_pct` in each frame's `System` block after the pending `sunset-meta.py` work merges. The flasher (`HIDBootLoader.exe`) comes from
  Mini-Box's OpenUPS (v1) firmware pack; never flash that pack's hex files. **Reader built 2026-11-16; installed on `sunshine` 2026-11-20 07:24 UTC (`install.sh --ups`), its status on the NAS in every frame's `System.ups`/`ups_source`/`ups_charge_pct` and as `project_sunshine_config/sunshine/ups/*.log`:** `pi/sunset-ups.py` (`--once`, `--raw`, `--run`), `pi/systemd/sunset-ups.service` (root, installed by `install.sh`), `tests/test_ups.py`. Bench-tested on the PC in WSL (USB passed through with usbipd-win, busid 1-14) against the real board: steady values wrote only keyframes, and an unplug wrote one lost and one found line. Settings are `UPS_*` in `sunset.env` (defaults in the script). Bench runs: `tools/ups_bench.py` (WSL as root; summarises the log, warns on cells under 2.5 V).
  **Cells fitted 2026-11-16 (5:46 pm, 00:46 UTC Nov 17):** three charged Li-ion 18650s (4.17 V, matched; rated 2,500 mAh each, model not recorded; `CAPACITY` set to 2500, 03:57 UTC Nov 17), so the Li-ion route stands (firmware 1.6). **R20 stays unchanged (decided 2026-11-16)**: the cells start full and settle at the board's ~3.5-3.6 V charge stop, trading runtime for cell life. The board wakes from ship mode on P10 or input power; a 12 V supply is too low to count as mains, so it runs from the cells. Reader bench-tested on battery (values match the tool, `low_battery` fires). **15 V supply from 2026-11-20 06:20 UTC** (Steven), replacing the 24 V 1 A one that read just over the 24 V input limit (board 24.24 V); the board counts 15 V as mains. Mains lost/back by hand: the output goes 24.2 V on mains, 12.4 V on cells (both inside the MyPi XT's 9-28 V). The reader logged each switch once (`mains_lost`/`mains_back`, no flapping; bench run 03:48-03:56 UTC Nov 17).
  **Runtime test 2026-11-20:** 2 h 27 min on the cells (21:33 to 00:00 UTC) without reaching the low-battery limit; lowest cell 4.081 to 3.851 V. The board's charge % stays at 100 on battery, so only `UPS_LOW_CELL_V` (3.3 V since 2026-11-21) decides. Installed, in the frame `System` block, and alerted in HA. **Still open (#29):** the P2-to-MyPi cable polarity check and the deadband tuning. (The 34T cells were over-discharged and recycled on 2026-11-16; the R20 change was decided against the same day.)
- **Wyze Cam v2** ×several — not for this project (no RAW/manual control). Possible Home Assistant
  cameras via Thingino firmware.
- Sony NEX-5 and Samsung NX200: rejected (no USB remote control, mechanical shutter only).

### Hardware plan for the real run (not yet bought)
Pi 5 prices are ~$250 due to the RAM shortage, so the plan shifted to reusing Pi 3/Zero:
- **Two-camera plan (decided 2026-11-09):** both cameras on the CM4 + MyPi XT board, both IMX477 so
  they share one set of settings. **Wide (sunset):** the new Arducam B0240E + 3.2 mm lens.
  **Tight (downtown):** the UC-517, planned with the 16 mm lens but fitted with the 6 mm (the 16 mm
  could not reach infinity). Both live on the CM4 since 2026-11-17.
- **Sunset (wide) camera, earlier options:** IMX477 + ~3–4 mm lens on the **Pi 3**, or Camera Module 3 Wide (~102°).
  Upgrade path: used **Sony a6300** (has true silent/electronic shutter; must verify silent works
  over USB PC Remote with gphoto2) + wide lens (e.g. Sony 10–18 mm).
- Sensors (SHT4x, TSL2591, dew heater): **dropped, Steven 2026-11-20** (#34 closed). Condensation is
  watched from the frames only (`tools/fog_scan.py`, #33).
- 64 GB High Endurance SD cards, small UPS, spare camera of each type, ND filter for the 16 mm lens.
- IP cameras considered: UniFi G6 Bullet (US$199, 1/1.8") and G6 Pro Bullet (US$479 / ~CA$685,
  1/1.2", 2.36× zoom, ~114°–45.5° H). Good as an always-on backup record, but no RAW and heavy
  processing. If used: disable IR and white LEDs (they reflect off the glass).

### Risks and mitigations
| Risk | Mitigation |
|---|---|
| Silent failure | HA alert on newest NAS file age; `capture.log` on the Pi |
| NAS/Wi-Fi outage | Local-first capture, rsync catch-up |
| Condensation | Low-contrast "fog" frame detection (no sensors: dropped 2026-11-20) |
| Software rot | Frozen OS image on NAS |
| SD wear | `sunset-lowwear.sh` for OS writes; High Endurance card for the real run; frames are the main wear |
| Bumps when watering plants | Keyed mount, post-alignment against the tower |
| Sun damage on telephoto | Skip/short-expose frames when the sun is in the 16 mm FOV; ND filter |
| Heat | PETG/ASA mount, temperature logging |

### Next session: fix the sunset flicker before anything posts (notes from 2026-11-12, late)
Steven reviewed the Nov 12 `cm4wide` video (07:30 to dark, tighter crop, merged exposure) and said it is
**not good enough to post: it still flickers around sunset.** Nothing posts until that is fixed. State:
- **Fixed already:** frozen then jumping frames (bracket gaps filled by copying pictures; now a gain
  transfer) and the bracket's exposure hunting (brightness smoothed). Merged exposure looks better, and the
  crop is right (top 100, height 2440). Rebuild command in `README.md`.
- **What is left:** between about 00:12 and 00:19 UTC (5:12-5:19 pm local, 15 to 20 min before sunset) the
  frame-to-frame difference stays at 10 to 15 where it is 2 to 5 elsewhere. The sun disc and its glow
  brighten and dim from one minute to the next. The unprocessed production frames do the same (9 to 13),
  so it is in the source, not the merge. No camera shift (phase correlation 0.0 px).
- **Questions to answer first:** (1) **Answered 2026-11-15: real cloud, not auto exposure.** The worst
  minutes (00:14, 00:17, 00:18 UTC) are the same on both cameras, each with its own lens and auto exposure; the
  mean sky brightness barely moved while pixels changed by about 10 (cloud crossing the glow). ev-2 roughly halves
  the worst flicker. So locking exposure at capture (d) would not fix it. The 3-frame blend (b) is in `fuse_sunset.py` (`blend_run`,
  1:2:1, on by default): Nov 12 worst change 17 to 11, sun and cloud edges a little softer. Steven to judge. Also
  found: the 5-minute frames in the merge window aren't real merges (runner skips that minute). Numbers on #3. (2) Is it the double-glazing
  flare, whose ripple bands move with the sun? Look at the ev-2 frames alone. (3) **Answered 2026-11-13:** the
  7-minute holes in the CM4 bracket (00:19-00:25 and 00:49-00:55 UTC) were the runner's half-hourly NAS upload
  blocking the camera on the slow Wi-Fi. The upload now runs in the background (`Run.upload`), from `sunset-5`/`cm4-sunset-2`.
- **Ideas, cheapest first:** (a) a measured flicker number: mean absolute change of the sky region frame to
  frame in the sunset window, printed by `tools/build_video.py` next to the sky score, so every fix is
  checked by number and not by eye; (b) a light temporal blend (3 frames, ffmpeg `tmix`, or a weighted
  mean in `fuse_sunset.py`) limited to the dense window, trading a faint ghost for calm; (c) normalise the
  brightness of the sun region separately from the rest of the frame; (d) stop the cause at capture: lock
  the exposure in the sunset window (a ramp of fixed shutter times from the Lux curve) instead of auto, or
  shoot a proper 3-frame bracket in production (backlog #3), which also removes the need for the
  experiment frames; (e) use the experiment's `ev-2` frames alone for the sun, if (c) is not enough.
- **More data on the way:** `cm4-sunset-2` and `-3` and `sunset-5` and `-6` shoot the Nov 13 and Nov 14
  sunsets; compare their flicker with Nov 12's before choosing. Check the weather first: a clear sunset is
  the best test and a flat grey one the worst.
- **Also open:** the tower blur boxes and the calibration were not rechecked on a clear sunset, the sky
  score threshold is Steven's call (`sky` block, backlog #11), and `crop.cm4wide.json` is not yet on the NAS.

### Backlog for Claude Code
1. ~~Disk-space guard~~ **Done** (`sunset-capture.sh`, tested in `tests/`).
2. ~~Sun-position module~~ **Done**: `sunset-sun.py` (stdlib NOAA formula, no network). Writes the
   `Sun` block per frame; `sunset-sun.py sunset [--epoch|--json]` gives the next sunset for burst
   scheduling (backlog #3).
3. **Sunset burst mode**: 1/min done (dense frames, from 2026-11-09). The 3-shot bracket is not.
4. **Sensor protection** for the telephoto camera (#32). Sun-in-view check built (`sunset-sun.py view`,
   `view-calendar`, `VIEW_*` in `sunset.env`, `Sun.in_view`); estimate: in the 16 mm frame Mar 19-May 31 and
   Jul 11-Sep 23. Software can't protect the sensor (no shutter): the iris or an ND filter is Steven's call.
5. **Fog detection**: flag low-contrast frames (#33).
6. Port capture to **Picamera2** if finer control is needed than `rpicam-still` gives.
7. ~~SHT4x + TSL2591 logging (#34)~~ **Dropped** (Steven, 2026-11-20).
8. ~~Home Assistant config for the stale-file alert~~ **Done** (`homeassistant/`, steps in `docs/setup.md`).
9. Mount design: start from Printables model 250692 or design a keyed plate + foam hood (#35).
10. Post-processing pipeline: deflicker, stabilisation, "sunset along the horizon" sequence
    (frame nearest each sunset), time slices, sky calendar (#20, #21).

11. **Sky score to pick sunsets worth posting. Built 2026-11-12, provisional; the threshold and the
    tuning wait for more good sunsets.** Deterministic, no AI (stdlib plus ffmpeg, in
    `nas/sunset-daily.py`): the best frame from 35 min before to 25 min after sunset, by the share of
    the top 40% of the frame that is bright and warm (red over blue, at least 77/255). Score = that share
    over 10%, as a percent, capped at 100 (`sky_full_warm` in `crop.json` sets a camera's own scale).
    Bands: under 20 grey, 20 to 59 some colour, 60 and up colourful. It goes in each daily record as a
    `sky` block and `tools/build_video.py` prints it. On the pilot so far (wide camera): grey evenings
    5 to 13 (Nov 4-7, 9, 10), a part-clearing one 40 (Nov 11), the good ones Nov 8 and Nov 12 about 69 and 67.
    The CM4 camera read 11.9% warm sky on Nov 12 against the wide camera's 6.7%, so it has its own
    scale (0.178) that gives it 67 as well. The posting threshold is 60 (Steven, kept 2026-11-20);
    Steven posts by hand, and retune once there are more good and grey sunsets. The saturation
    of blue overcast rules out saturation as a signal. Needs a recheck after any lens or camera change.
