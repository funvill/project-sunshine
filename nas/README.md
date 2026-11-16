# Daily sunset video

`sunset-daily.py` runs on the NAS and turns each day's frames into a vertical video. Every frame is
on screen for 1/12 s, sunset included, so the 1-minute frames at sunrise and sunset slow the video
down there. A full day of 5-minute frames plus the 1-minute frames is roughly 288 + 230 frames, about
40 to 45 seconds (estimated, not yet measured on a full day). It only reads frames and writes to its
own folder.

Each video runs from dark to dark. It ends on the first frame after sunset where the sun is at least
9° below the horizon, and the next video starts on the frame after that, so every frame appears once.
Night is a larger share of a winter video and day of a summer one. The 9° comes from one morning's
Lux readings (2026-11-04) and is the `DARK_ELEVATION_DEG` constant, so check it against real dusks.

The record's `start_utc` and `end_utc` give the range. With no record for the day before, the video
covers the 24 hours before its end.

Each frame carries three lines of text at the bottom left, the last 140 px above the bottom edge:
"Project Sunshine   @funvill", its local time as `2026-Nov-06 16:45`, and in small text
"Burnaby, BC, Canada   WSW 243°": the place and the compass bearing at the middle of the crop, which
is the sunset's bearing when the crop is aimed at it (from the calibration, or the sunset azimuth
without one). Instagram's caption may cover it in the Reels feed. Position, size and wording are
constants at the top of the script; `OVERLAY_LOCATION=""` drops the third line.

**Starting at a fixed time.** `VIDEO_START_LOCAL=07:30` starts each video at that local time on the
day of the sunset instead of after the previous video, and the day before is ignored. A frame can then
be in two videos. Without it the videos run dark to dark as above.

**Building one by hand, with no AI:** `python tools/build_video.py --camera cm4wide --date 2026-11-12
--start 07:30 --redo --crop nas/crop.cm4wide.json`. It runs this same job on a PC for a chosen
day, reads the NAS share and writes to `~/Documents/sunset-daily-out/<camera>`.

**It posts nothing.** Publishing to Instagram is a later step. See
[issue #2](https://github.com/funvill/project-sunshine/issues/2) for the plan and decisions.

## Running it

Build the image once and keep using that tag. The base image is pinned by digest and the packages by
version (see the comments in `Dockerfile`), so a later rebuild either gives the same image or fails. Save
the built image beside the Pi's SD images:

```bash
docker build -t sunset-daily:1 nas/
docker save sunset-daily:1 | gzip > sunset-daily-1.tar.gz
```

The image has ffmpeg 6.1.2 (Alpine 3.21). Every video so far was made with ffmpeg 7.1.1 on a PC, and the
image has not yet been built and run on real frames.

Schedule this every 30 minutes through the afternoon and evening. Dusk moves through the year, and
each run does nothing until a frame shows the sky has gone dark after sunset:

```bash
docker run --rm -v /path/to/project_sunshine:/data -e FRAMES_DIR=/data/wide -e DAILY_DIR=/data/daily sunset-daily:1
```

The exit code is 0 when there was nothing to do or the work succeeded, 1 when a day failed, and 2 when
a required setting is missing. A failed day gets a record with `"status": "failed"` and the error, and
every run within `LOOKBACK_DAYS` tries it again (`attempts` counts the tries); a success replaces the
record. An error in one day, of any kind, doesn't stop the other days.

## Settings

| Variable | Default | What it does |
|---|---|---|
| `FRAMES_DIR` | required | The camera's folder, holding `YYYY/MM/DD/` |
| `DAILY_DIR` | required | Where the job writes |
| `CROP_FILE` | `$DAILY_DIR/crop.json` | Calibration and mask; optional |
| `CROP_CENTER_X` | middle of the frame | Crop centre in full-frame pixels until a calibration exists |
| `SITE_TZ` | `America/Vancouver` | Names the day and the time in the caption |
| `START_DATE` | `2026-12-21` | Day 1. Earlier videos are dry runs with no day number |
| `CAPTION_TAGS` | `#sunset #timelapse #raspberrypi` | The last line of the caption |
| `EXPECTED_FRAMES` | `288` | Regular frames in a full 24 hours (5-minute capture). Only regular frames are counted against it: `Capture.schedule` in the frame's JSON, or, for frames with no Capture block (before 2026-11-04), a file name on a 5-minute slot. Change it if the capture interval changes |
| `MIN_FRAME_FRACTION` | `0.7` | Below this share of the regular frames expected between the video's start and end, the day is skipped. An estimate to tune |
| `MAX_GAP_MIN` | `60` | A longer stretch with no frame skips the day: every frame is 1/12 s, so a gap is a silent jump in time |
| `MAX_SUNSET_GAP_MIN` | `20` | The same, from an hour before sunset to the end of the video |
| `LOOKBACK_DAYS` | `2` | How far back a missed day is still caught up |
| `VIDEO_START_LOCAL` | unset | Local `HH:MM` to start each video at (see above). Unset means dark to dark |
| `FUSED_DIR` | unset | A folder of fused frames (from `tools/fuse_sunset.py`). A file with the same name as a frame replaces its picture; the frame's time and Sun data stay |
| `OVERLAY_LOCATION` | `Burnaby, BC, Canada` | Small text under the date. Empty for none |
| `FONT_FILE` | `/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf` | Font for the text on the video. The image installs this one |
| `SUNSET_CUT` | off | `1` makes the sunset-only cut as well (see below) |
| `SUNSET_CUT_BEFORE_MIN` | `60` | The cut starts this many minutes before sunset |
| `SUNSET_CUT_END_ELEVATION` | `-9` | The cut ends on the first frame after sunset with the sun at or below this, in degrees |
| `SUNSET_CUT_AFTER_MIN` | `60` | Where the cut ends instead when no frame has reached that elevation (for example, frames with no `elevation_deg`). An estimate: -9° comes about 45 to 70 minutes after sunset here |
| `SUNSET_CUT_MAX_GAP_MIN` | `MAX_SUNSET_GAP_MIN` | A longer stretch with no frame inside the cut skips the cut |
| `MASTER` | off | `1` makes the master render as well (see below) |
| `MASTER_CODEC` | `libx264` | ffmpeg encoder for the master. `libx265` for HEVC. One this ffmpeg lacks skips the master |
| `MASTER_CRF` | `14` | Quality, lower is better and bigger |
| `MASTER_PRESET` | `slow` | Encoder preset |
| `MASTER_WIDTH` | `3840` | The master is scaled to this width, never up |
| `MASTER_PIX_FMT` | `yuv420p` | `yuv420p10le` with `libx265` gives 10-bit HEVC |
| `REDO_OLDER_THAN_VERSION` | unset | Make finished days again if their record was made by an older `SCRIPT_VERSION` (see Redoing days) |
| `REDO_MISSING_OUTPUTS` | off | `1` makes encoded days again if they lack an output that is turned on, or it failed |
| `REDO_FROM`, `REDO_TO` | unset | Local dates (`YYYY-MM-DD`): redo within these instead of `LOOKBACK_DAYS`. Days in the range with no record are made too |

For the on/off settings, unset, empty and `0` mean off.

## Sunset-only cut (`SUNSET_CUT=1`)

A second video of the same day, made only from the frames from an hour before sunset until the sun
is 9° below the horizon, where the frames are one minute apart, so the speed doesn't change half way.
A frame's place comes from `Sun.minutes_from_sunset` in its JSON (from its time if it has none), and
the end from `Sun.elevation_deg`. Same crop, blur, mask and text as the daily video, and fused frames
when `FUSED_DIR` is set. Written beside it as `YYYY-MM-DD_sunset.mp4`.

It goes through the same checks as the daily video: unreadable frames are left out, the encoded frame
count is checked, and it is skipped with the reason when it has under `MIN_FRAME_FRACTION` of one frame a
minute or a gap over `SUNSET_CUT_MAX_GAP_MIN`. Days before the 1-minute frames (2026-11-09) have only
5-minute frames there, so they get no cut. A skipped or failed cut never affects the daily video.

It is only made when the daily video is: a day skipped for gaps or too few frames gets
`"sunset_cut": {"status": "skipped", ...}` and no cut, even if its sunset was complete.

## Master render (`MASTER=1`)

A second encode of the same frames as the daily video, for keeping and for later edits: no text, no
blur and no mask, at high quality (H.264 CRF 14, `slow`, by default). It is the full frame scaled to fit
`MASTER_WIDTH` (4,056 x 3,040 becomes 3,840 x 2,878), or, when the calibration entry in force has a
`master_view` box `{"x", "y", "width", "height"}` in full-frame pixels, that box (made even and kept inside
the frame), never scaled up. BT.709, converted and tagged like the daily video. Written as
`YYYY-MM-DD_master.mp4`.

It is made on days with a setup mismatch, since it has no blur boxes to misplace, but not on days skipped
for gaps or too few frames. An encoder this ffmpeg doesn't have (asked with `ffmpeg -encoders`) skips it
with the reason. 10-bit HEVC is `MASTER_CODEC=libx265 MASTER_PIX_FMT=yuv420p10le`, tagged `hvc1`; the
tests only run it where the ffmpeg has libx265. Encoders without `-crf` (hardware ones) fail.

A 4K master of a whole day at CRF 14 is far bigger and slower than the daily video. Not yet measured on
real frames or on the NAS. On 30 synthetic 4,056 x 3,040 frames with fresh noise in every frame (worse
than a real sky) on a 12-thread PC with ffmpeg 7.1.1, H.264 CRF 14 `slow` took 1.4 s and 4.3 MB per frame,
and 10-bit HEVC CRF 14 `slow` 4.1 s and 3.7 MB. For a ~500-frame day that is an estimate of up to about
2 GB and 12 minutes (H.264) or 35 minutes (HEVC) on that PC, and longer on a NAS CPU.

## Redoing days

A finished day is never redone by default, and turning an output on later doesn't change that. Two
settings ask for it, both limited to `LOOKBACK_DAYS` unless `REDO_FROM`/`REDO_TO` give a range:

- `REDO_OLDER_THAN_VERSION=2026-11-15.2` makes again every encoded or skipped day whose record was made by
  an older version (`provenance.script_version`; a record with none counts as older). Versions are
  `YYYY-MM-DD.N` and compare by date, then number.
- `REDO_MISSING_OUTPUTS=1` makes again every encoded day that lacks an output that is turned on, or whose
  output failed.

A redo makes the whole day again, daily video included, and replaces the record. The record gets a
`redo` block (`reason`, `previous_status`, `previous_script_version`), and keeps `posted` and any other
`posted...` field from the old record, so a redone day never looks unposted. If the redo fails, the day
gets a failed record like any other. With a range, frames are read from `REDO_FROM`, which takes a while
over months of frames on the share. Run it once by hand with the setting, not on the schedule.

## Archive checks

`sunset-verify.py` re-reads each camera's JPEG and DNG files and compares them with the SHA-256 in
their JSON. It never changes a frame. Run it once a day per camera, for example
`python3 sunset-verify.py /data/wide`. It reads new days and problem days first, then a rolling
slice of older days (`--cycle-days`, default 60), so the whole archive is re-read about every two
months. It writes `../health/<camera>/verify.json` beside the camera folder and exits 1 if any file
is missing, zero-length or does not match. Frames without a `Capture` block (early pilot frames)
count as unverifiable, not as errors.

`sunset-health.py` writes one record per camera and UTC day to `../health/<camera>/<day>.json`, and
`latest.json` for the newest finished day. Run it daily at about 02:00 UTC, after the sync has
caught up, for example `python3 sunset-health.py /data/wide`. It counts frames by type against what
the day's own data says to expect (288 regular, dense windows, night frames where the lux was low,
DNGs), the largest gap, frames missing metadata blocks, `SETUP_ID` changes, and the worst
temperature, throttle flags, `outbox_pending`, disk use and smallest JPEG. Image measures
(sharpness, skyline offset) are left to `tools/register_day.py`. Home Assistant reads `latest.json`
and `verify.json`.

Neither job is scheduled yet, and neither has run on the NAS.

## Sky score

Each record has a `sky` block: how good the sunset was, deterministically, with no AI. The job reads the
frames from 35 minutes before to 25 minutes after sunset (the originals, not fused copies), shrinks each
to 160x120 with ffmpeg, and counts the share of the top 40% that is bright (at least 77 of 255) with red
more than 1.2 times blue. **Score = the mean share of the best 5 frames divided by 10%, as a percent,
capped at 100** (`sky.method` is `top5_mean`). Bands: under 20 grey, 20 to 59 some colour, 60 and up
colourful. Under 6 readable frames (`sky_min_frames` in `crop.json`) there is no score: `sky` is `null`
and `sky_note` says why.

Until 2026-11-15 the score was the best frame alone, so one odd frame (the room-light glow, say) could
set it. That number is still in the record as `sky.score_best_frame`, with `warm_sky_percent` and
`best_frame`, and it is the one the pilot numbers below were measured with. The new score can only be
the same or lower; with 1-minute frames at sunset the best five are minutes apart, so a steady glow
should score about the same, and a single bright frame much less. Not yet checked on real frames.

`sky.crop` is the same score over only the columns of the posted crop (`columns`, in the 160-px-wide
picture), beside the full-width one. The full width is kept as the main score so it stays comparable.

`sky.provisional` is `true` until it's tuned on more sunsets: so far grey evenings score 5 to 13 and the
two good ones, Nov 8 and Nov 12, about 67 to 69 (wide camera, best frame). Blue overcast is also
saturated, so saturation isn't used. A camera sets its own scale with `sky_full_warm` in `crop.json` (the
CM4 camera has 0.178). Posting only days above a threshold is not built yet: that needs Steven's number.

## Sunset exposure (`tools/fuse_sunset.py`)

The camera's auto exposure blows out the sunset. The `sunset` experiment shoots ev+0 and ev-2 pairs, both
with daylight white balance, every minute around sunset. `tools/fuse_sunset.py` merges each pair
(exposure fusion), blends it with the production frame, and writes it under the production frame's name
into a folder, which `FUSED_DIR` points the job at. The blend fades in over the first 5 minutes of the
run, is full to 5 minutes after sunset, and fades out by 12 minutes (daylight white balance turns the sky
brown once the city lights the cloud). The runner skips the first minute of each 5-minute slot, and
sometimes loses longer stretches (7 minutes at the Nov 12 sunset), so some frames have no pair. Such a
frame keeps its own picture and takes the fusion's change in exposure and colour (a smooth gain) from the
pairs within 8 minutes either side. Copying or blending the neighbours' pictures instead froze the video,
then jumped. The bracket's auto exposure also hunted by several brightness levels a minute, so the
brightness of the fused frames is steadied against the frames around it (3 either side, at most 25%).
Flicker that is left comes from the sun going in and out of thin cloud. It needs numpy and OpenCV, so it runs on a PC, not in the
NAS image, until a production bracket exists.

## What it writes

For each day, named by the local date of the sunset:

| File | What it is |
|---|---|
| `YYYY-MM-DD.json` | The record, written last. If it exists, the day is finished and is never redone |
| `YYYY-MM-DD.mp4` | The video: 1080x1920, H.264, `yuv420p`, BT.709 (converted from the JPEGs' BT.601 and tagged), 24 fps, no audio |
| `YYYY-MM-DD.txt` | The caption |
| `YYYY-MM-DD_check.jpg` | The full view with the crop (green) and predicted sun (red) drawn on it |
| `YYYY-MM-DD_sunset.mp4` | The sunset-only cut, with `SUNSET_CUT=1`. Same format as the daily video |
| `YYYY-MM-DD_master.mp4` | The master, with `MASTER=1` |

A day with too few regular frames, or a gap longer than the limits, gets a record with
`"status": "skipped"` and the reason, and no video. A skipped day is not tried again. A failed day (see
above) is. To redo a day, delete its record, or see "Redoing days" above.

Before encoding, each JPEG is checked: it must start with `FFD8` and end with `FFD9`. A zero-byte,
missing or cut-off frame is left out (`dropped_frames`, and the names in `dropped`); a bad fused frame
falls back to its original. ffmpeg runs with `-xerror`, so a frame it still can't read fails the day
instead of quietly ending the video there, and the encoded frame count is checked with ffprobe.

The record also has:

| Field | What it is |
|---|---|
| `schema_version` | `2` (records from before 2026-11-15 have none) |
| `regular_frames`, `dense_frames` | Frames in the video by schedule. `frames` is both |
| `largest_gap_min`, `largest_gap_at_utc`, `largest_sunset_gap_min` | The longest time with no frame, from the video's start, and the longest from an hour before sunset |
| `setup_id_expected`, `setup_id_frame`, `setup_mismatch` | The calibration's `setup_id` and the sunset frame's `Capture.setup_id`. `true` when they differ, `null` when either is missing |
| `post_ok`, `post_blockers` | Whether anything here stops the day being posted: `not_encoded`, `setup_mismatch`, `no_sky_score`. The sky threshold is a separate check, not built yet |
| `provenance` | `script_version`, the `ffmpeg -version` line, the SHA-256 of `crop.json`, and frames by kind (regular, dense, fused, dropped) |
| `sunset_cut` | Only with `SUNSET_CUT=1`. `status` (`encoded`, `skipped` with `reason`, or `failed` with `error`), `video`, `frames`, `expected_frames` (one a minute over the window), `dropped_frames`, `dropped`, `largest_gap_min`, `largest_gap_at_utc`, and `window`: the settings (`before_min`, `end_elevation_deg`, `after_min_limit`), `end_by` (`elevation` or `minutes`) and what it covered (`first_utc`, `last_utc`, `first_minutes`, `last_minutes`) |
| `master` | Only with `MASTER=1`. `status` as above, `video`, `frames`, `codec`, `crf`, `preset`, `pix_fmt`, `width` and `height` of the video, `source` (the box used and `from`: `full_frame` or `master_view`), `color`, `overlay`, `blur` and `mask` (all `false`), `encode_seconds`, `size_bytes` |
| `redo` | Only on a redone day: `reason`, `previous_status`, `previous_script_version` |

A failed extra output gives the run exit code 1 but leaves the day encoded; `REDO_MISSING_OUTPUTS=1`
makes it again. With neither output on, the record and the files are the same as before these settings
existed (apart from `provenance.script_version`).

Sunset's UTC date is one day ahead of its local date here, all year. The sunset of 21 December is
named `2026-12-21`, but its frames are in the `2026/12/22` folder.

## crop.json

```json
{
  "calibrations": [
    {
      "start": "2026-12-21",
      "setup_id": "final-1",
      "offset_px": 0,
      "mask": [[400, 0, 100, 480]],
      "view": {"top": 100, "height": 2440},
      "blur": [[0, 290, 270, 2010]],
      "sky_full_warm": 0.178,
      "cx": 2028,
      "fits": [
        {"date": "2026-12-28", "f_px": 1900.0, "az0_deg": 270.5, "marks": 3, "az_min": 226.0, "az_max": 233.5},
        {"date": "2027-01-28", "note": "no clear day"}
      ]
    }
  ]
}
```

The values above are examples. All positions are in full-frame pixels.

**Everything tied to the camera position goes in its calibration entry:** `setup_id`, `offset_px`,
`mask`, `view`, `blur`, `blur_sigma`, `sky_rows`, `sky_full_warm`, `sky_min_frames` and the optional
`master_view` box for the master render (see above). The entry in
force on a day (the last one whose `start` is on or before it) is used, so rebuilding an old day uses
that day's boxes. Any of them can also be at the top level, which is used when the entry doesn't set
it; files from before 2026-11-15 have them there and still work.

- **`setup_id`:** the `SETUP_ID` the entry was made for. The job compares it with `Capture.setup_id` in
  the sunset frame's JSON and sets `setup_mismatch` and `post_ok: false` in the record if they differ.
  The video is still made. A mismatch means the camera moved: add a new entry.

- **`mask`:** black rectangles `[x, y, width, height]`, drawn before the crop, so they stay on the
  same part of the view as the crop moves. Masks are applied to the video and the check image.
- **`view`:** `{"top": 100, "height": 1600}` makes the window shorter than the full frame, still 9:16 and
  centred on the sun, then scales it up to 1080x1920. It crops the foreground roofs out. Without it the
  window is the full height. Positions are in full-frame pixels.
- **`sky_rows`, `sky_full_warm`:** the sky score's top share of the frame (default 0.40) and the share of
  warm sky that scores 100 (default 0.10). See below.
- **`blur`:** boxes `[x, y, width, height]` that get a light Gaussian blur (`blur_sigma`, default 5 px
  of the full frame), also before the crop, so they stay on the towers. The blur is a box, so keep the
  boxes tight to the buildings. Redo them when the camera moves. The video and the check image both
  have it.
- **`calibrations`:** the sun's position is `x = cx + f_px · tan(azimuth − az0_deg)`. The job
  averages the fits dated up to that day.
- **After a bump:** add a new calibration with its own `start` date. Fits are never averaged across
  calibrations, because they describe different camera positions.
- **`offset_px`:** moves the crop relative to the sun.

With no usable fit, the job uses the fixed centre.

### Monthly refit

Do this by hand every month, and add one entry to `fits`, including months with no clear day.

1. Measure `f_px` with `6.29 × distance ÷ visible width` for the focal length in mm, then divide by
   the pixel size of 0.00155 mm.
2. Open `_check.jpg` images from clear days and note where the sun really is.
3. Find `az0_deg` from those positions, using `azimuth_deg` in each frame's JSON.

December sun only reaches about 233°, near the south edge of the frame, so early fits rest on few
positions. Record `marks`, `az_min` and `az_max` so weak fits can be weighted later.

## Where the crop comes from

The record's `crop.source` says which one was used:

| Source | When |
|---|---|
| `azimuth` | There is a calibration and a sunset azimuth, from the frames either side of sunset (`interpolated`) or one frame corrected at 0.19°/min (`single_frame`) |
| `previous_day` | There is a calibration but no azimuth, so it reuses the day before |
| `fixed` | Nothing else is available |

`crop.clamped` means the window hit the frame edge, so the sun is off-centre.
`crop.azimuth_step_flag` means the azimuth moved over 1° from the day before, about 0.4° more than
the fastest seasonal change, which usually means bad frame data. It doesn't change the crop.
