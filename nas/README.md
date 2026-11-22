# Daily sunset video

`sunset-daily.py` turns each day's frames into a vertical video. It runs on a PC, from
`tools/build_video.py` (see Running it). It was written as a Docker job for the NAS, but that was never
scheduled, and the Docker image was removed on 2026-11-22. Every frame is on screen for 1/12 s, sunset
included, so the 1-minute frames at sunrise and sunset slow the video down there. A full day of
5-minute frames plus the 1-minute frames is roughly 288 + 230 frames, about 40 to 45 seconds
(estimated, not yet measured on a full day). It only reads frames and writes to its own folder.

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
constants at the top of the script; `OVERLAY_LOCATION=""` drops the third line. The day's sky
score (provisional, see below) sits right-aligned on that line as "Sky score 72", for the whole
video; a day with no score shows none, and `OVERLAY_SKY=0` drops it.

**Starting at a fixed time.** `VIDEO_START_LOCAL=07:30` starts each video at that local time on the
day of the sunset instead of after the previous video, and the day before is ignored. A frame can then
be in two videos. Without it the videos run dark to dark as above.

**It posts nothing.** Publishing to Instagram is a later step. See
[issue #2](https://github.com/funvill/project-sunshine/issues/2) for the plan and decisions.

## Running it

With no AI, on a PC with ffmpeg and Python 3.9 or later, for a chosen day:

```bash
python tools/build_video.py --camera cm4wide --date 2026-11-17 --start 07:30 --redo \
    --crop nas/crop.cm4wide.json --fuse-production
```

It reads the NAS share (`SUNSET_NAS`, or `--nas`, set to the `project_sunshine` folder) and writes to
`~/Documents/sunset-daily-out/<camera>` (`--out`). `tools/build_reports.py` uses the same job for the sky
score in `reports/`.

`build_video.py` sets the settings below from its own options and runs the job as if it were the evening
after that sunset. The job returns 0 when there was nothing to do or the work succeeded, 1 when a day
failed, and 2 when a required setting is missing. A failed day gets a record with `"status": "failed"` and
the error, and a later run within `LOOKBACK_DAYS` tries it again (`attempts` counts the tries); a success
replaces the record. An error in one day, of any kind, doesn't stop the other days.

## Settings

These are environment variables when the script is run on its own (`python3 nas/sunset-daily.py`);
`tools/build_video.py` sets the same values from its options.

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
| `OVERLAY_SKY` | `1` | `0` leaves the day's sky score off the video (it stays in the record) |
| `FONT_FILE` | `/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf` | Font for the text on the video. `build_video.py` picks a bold system font instead (`--font`) |
| `REDO_OLDER_THAN_VERSION` | unset | Make finished days again if their record was made by an older `SCRIPT_VERSION` (see Redoing days) |
| `REDO_FROM`, `REDO_TO` | unset | Local dates (`YYYY-MM-DD`): redo within these instead of `LOOKBACK_DAYS`. Days in the range with no record are made too |

## Redoing days

A finished day is never redone by default. `REDO_OLDER_THAN_VERSION` asks for it, limited to
`LOOKBACK_DAYS` unless `REDO_FROM`/`REDO_TO` give a range:

- `REDO_OLDER_THAN_VERSION=2026-11-15.2` makes again every encoded or skipped day whose record was made by
  an older version (`provenance.script_version`; a record with none counts as older). Versions are
  `YYYY-MM-DD.N` and compare by date, then number.

A redo makes the whole day again, daily video included, and replaces the record. The record gets a
`redo` block (`reason`, `previous_status`, `previous_script_version`), and keeps `posted` and any other
`posted...` field from the old record, so a redone day never looks unposted. If the redo fails, the day
gets a failed record like any other. With a range, frames are read from `REDO_FROM`, which takes a while
over months of frames on the share.

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

The camera's auto exposure blows out the sunset. With `BRACKET=1` (#10) the capture saves an ev+0 and an
ev-2 shot beside each frame within 45 minutes of sunset (`<frame>_ev0.jpg`, `_ev-2.jpg`), with daylight
white balance to 10 minutes after sunset. `tools/fuse_sunset.py` merges each pair (exposure fusion),
blends it with the production frame, and writes it under the production frame's name into a folder,
which `FUSED_DIR` points the job at (`build_video.py --fuse-production` does all of this). The blend
fades in over the first 5 minutes of the bracket, is full to 5 minutes after sunset, and fades out by 12
minutes (daylight white balance turns the sky brown once the city lights the cloud). A frame whose pair
is missing keeps its own picture and takes the fusion's change in exposure and colour (a smooth gain)
from the pairs within 8 minutes either side. Copying or blending the neighbours' pictures instead froze
the video, then jumped (seen with the experiment bracket, Nov 12). The bracket's auto exposure also
hunted by several brightness levels a minute, so the brightness of the fused frames is steadied against
the frames around it (3 either side, at most 25%). Then each sunset minute is blended 1:2:1 with the
minutes either side (`--no-blend` skips it). Flicker that is left comes from the sun going in and out of
thin cloud. It needs numpy and OpenCV.

## What it writes

For each day, named by the local date of the sunset:

| File | What it is |
|---|---|
| `YYYY-MM-DD.json` | The record, written last. If it exists, the day is finished and is never redone |
| `YYYY-MM-DD.mp4` | The video: 1080x1920, H.264, `yuv420p`, BT.709 (converted from the JPEGs' BT.601 and tagged), 24 fps, no audio |
| `YYYY-MM-DD.txt` | The caption |
| `YYYY-MM-DD_check.jpg` | The full view with the crop (green) and predicted sun (red) drawn on it |

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
| `redo` | Only on a redone day: `reason`, `previous_status`, `previous_script_version` |

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
`mask`, `view`, `blur`, `blur_sigma`, `sky_rows`, `sky_full_warm` and `sky_min_frames`. The entry in
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
