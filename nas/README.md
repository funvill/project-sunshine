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

Build the image once and keep using that tag:

```bash
docker build -t sunset-daily:1 nas/
```

Schedule this every 30 minutes through the afternoon and evening. Dusk moves through the year, and
each run does nothing until a frame shows the sky has gone dark after sunset:

```bash
docker run --rm -v /path/to/project_sunshine:/data -e FRAMES_DIR=/data/wide -e DAILY_DIR=/data/daily sunset-daily:1
```

The exit code is 0 when there was nothing to do or the work succeeded, 1 when a day failed and will
be retried by the next run, and 2 when a required setting is missing.

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
| `EXPECTED_FRAMES` | `288` | Regular frames in a full 24 hours (5-minute capture). The 1-minute frames only add to the count. Change it if the capture interval changes |
| `MIN_FRAME_FRACTION` | `0.7` | Below this share of the frames expected between the video's start and end, the day is skipped. An estimate to tune |
| `LOOKBACK_DAYS` | `2` | How far back a missed day is still caught up |
| `VIDEO_START_LOCAL` | unset | Local `HH:MM` to start each video at (see above). Unset means dark to dark |
| `FUSED_DIR` | unset | A folder of fused frames (from `tools/fuse_sunset.py`). A file with the same name as a frame replaces its picture; the frame's time and Sun data stay |
| `OVERLAY_LOCATION` | `Burnaby, BC, Canada` | Small text under the date. Empty for none |
| `FONT_FILE` | `/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf` | Font for the text on the video. The image installs this one |

## Sky score

Each record has a `sky` block: how good the sunset was, deterministically, with no AI. The job reads the
frames from 35 minutes before to 25 minutes after sunset (the originals, not fused copies), shrinks each
to 160x120 with ffmpeg, and counts the share of the top 40% that is bright (at least 77 of 255) with red
more than 1.2 times blue. The best frame wins. **Score = that share divided by 10%, as a percent, capped
at 100.** Bands: under 20 grey, 20 to 59 some colour, 60 and up colourful. `sky.provisional` is `true`
until it's tuned on more sunsets: so far grey evenings score 5 to 13 and the two good ones, Nov 8 and
Nov 12, about 67 to 69 (wide camera). Blue overcast is also saturated, so saturation isn't used. A camera
sets its own scale with `sky_full_warm` in `crop.json` (the CM4 camera has 0.178). Posting only days above
a threshold is not built yet: that needs Steven's number.

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
| `YYYY-MM-DD.mp4` | The video: 1080x1920, H.264, `yuv420p`, 24 fps, no audio |
| `YYYY-MM-DD.txt` | The caption |
| `YYYY-MM-DD_check.jpg` | The full view with the crop (green) and predicted sun (red) drawn on it |

A day with too few frames gets a record with `"status": "skipped"` and the reason, and no video.
To redo a day, delete its record.

Sunset's UTC date is one day ahead of its local date here, all year. The sunset of 21 December is
named `2026-12-21`, but its frames are in the `2026/12/22` folder.

## crop.json

```json
{
  "offset_px": 0,
  "mask": [[400, 0, 100, 480]],
  "calibrations": [
    {
      "start": "2026-12-21",
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
