---
name: camera-check
description: Health check of the Project Sunset capture Pi and its cameras. Use when Steven asks to "check camera", "check the cameras", "health check", "are the cameras OK", "is it still capturing", or similar.
---

# Camera check

Read-only. Never change settings, restart units or pause capture as part of a check: report, and
ask before fixing anything.

1. Run the script (from the repo root). The data part is deterministic and costs no tokens:

   ```
   python tools/camera_check.py            # last 12 hours; --hours 24 for a day
   ```

   It tries the hosts in `tools/camera_check.hosts` in order (git-ignored, LAN addresses never go in
   the repo). If none answers, say so and stop. An ssh "host key changed" error is Steven's to
   resolve: don't edit `known_hosts`.

2. Look at each camera's `*_small.jpg` the script names (Read the file). Check:
   - framing as expected (cm4wide: towers centre-left, downtown small near the middle;
     cm4city: downtown between the two tower pairs) — a bump shows as a shifted skyline
   - focus (distant skyline crisp for the light), no reflections, room lights or LED spots,
     no condensation or fog on the glass, no blank or green frame
   - sharpness and mean from the script depend on the light; compare only against frames at a
     similar time of day.

3. Reply in a few short sections: capture (slots per camera, any gaps with times in UTC and
   Vancouver), Pi health (throttled, temperature, disk, uptime), sync and network, the pictures.
   Lead with any `WARN` lines. A gap that matches a diag session or a known event in
   `changelog.md` is expected; say which. Known, no need to raise again: the two empty
   `cm4wide_20261116T072500Z` files in the outbox (Nov 16 freeze), and the Wi-Fi dropping for
   2 minutes about once an hour (changelog 2026-11-17) unless the rate goes up.

4. If something affects the record (gap, outage, bump, undervoltage, weather on the glass) and it
   isn't in `changelog.md` yet, offer to add it (CLAUDE.md: record events with UTC and Vancouver
   times).
