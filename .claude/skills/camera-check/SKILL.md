---
name: camera-check
description: Health check of the Project Sunset capture Pi and its cameras, then an update of the daily report in `reports/`. Use when Steven asks to "check camera", "check the cameras", "health check", "are the cameras OK", "is it still capturing", or similar.
---

# Camera check

Read-only on the Pi. Never change settings, restart units or pause capture as part of a check:
report, and ask before fixing anything. The one thing a check writes is the daily report in the
repo (step 4).

1. Run the script (from the repo root). The data part is deterministic and costs no tokens:

   ```
   python tools/camera_check.py            # last 12 hours; --hours 24 for a day
   ```

   It tries the hosts in `tools/camera_check.hosts` in order (git-ignored, LAN addresses never go in
   the repo). A line can add `key=<address>` to check the host key under another address of the same
   machine: the CM4's Wi-Fi address uses the key known for its wired one. If none answers, say so and stop. An ssh "host key changed" error is Steven's to
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
   `cm4wide_20261116T072500Z` files in the outbox (Nov 16 freeze). Network drops: the old dongle
   dropped for 2 minutes about 1.4 times an hour; the AIC8800 dongle (from 2026-11-20) has no
   baseline yet, so report its drop count.

4. Update the daily report (`reports/`, see README "Reports"). Deterministic, no AI:

   ```
   python tools/build_reports.py           # new days up to yesterday, and redoes the last two
   ```

   It reads the frames on the NAS, so it needs the NAS reachable from the PC; if it isn't, say so
   and skip this step. Do it on a branch off `origin/main` (`git status` first: another session may
   have uncommitted work in the checkout, so use a worktree if it isn't clean). In the reply, give
   each new day's sky score and frames taken, and say which days scored 60 or more (the posting
   threshold). A day still short of frames because sync was behind is corrected by the next run,
   so say so rather than call the frames missing. The report goes to GitHub only as a commit:
   commit, push and open a PR only when Steven asks (`git -c user.name="SWS-Chipkin"
   -c user.email="sws-dev@chipkin.com" commit`, pushed as `funvill`).

5. If something affects the record (gap, outage, bump, undervoltage, weather on the glass) and it
   isn't in `changelog.md` yet, offer to add it (CLAUDE.md: record events with UTC and Vancouver
   times).
