#!/usr/bin/env python3
"""Verify the archive's JPEG and DNG files against the SHA-256 in their frame JSON (issue #13).

    sunset-verify.py CAMERA_ROOT [--state FILE] [--cycle-days N] [--max-days N]
                     [--settle-min M] [--all] [--forget-missing]

CAMERA_ROOT is one camera's folder on the NAS (holds YYYY/MM/DD/<cam>_<UTC>.{jpg,dng,json}).
Python standard library only, no AI. It only reads frames; it never modifies or deletes one.
Its one output is the state file, written atomically (temp file in the same folder, then rename).

Which days are read on a run:
  1. days with a known problem (so a fixed file clears, and a bad one stays on the report),
  2. days never verified (new days; oldest first),
  3. a rolling slice of already-verified days, oldest verification first: ceil(days / N) of them,
     so with one run a day the whole archive is re-read about every N days (--cycle-days, default 60).
     --max-days caps the total per run (the first run over a big archive can be spread over several).
  --all reads every day.

What counts as a problem (each is listed with its path in the state file):
  missing       the JSON names an image (Capture.files) that is not in the folder
  mismatch      the image's SHA-256 (or byte count) differs from the JSON
  zero_length   an image is 0 bytes
  unreadable_json   the frame JSON is empty or is not a JSON object
  missing_day   a day that was verified before has no folder any more (--forget-missing drops it)
What is not a problem: a frame with no Capture block (the early pilot frames) or with no checksum
(FRAME_CHECKSUMS=0) is counted as "unverifiable". Files changed in the last --settle-min minutes (a sync
in progress) are skipped and their day is not marked verified, so it is read again next run.

Exit code: 0 when nothing is known to be bad, 1 when anything is (including problems found on earlier
runs and not yet cleared), 2 for a usage error such as a missing folder.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone

SCHEMA_VERSION = 1
FRAME_JSON = re.compile(r"^(?P<stem>[A-Za-z0-9_-]+_\d{8}T\d{6}Z(?:_night)?)\.json$")
IMAGE_EXTS = ("jpg", "dng")
PER_DAY_BAD_CAP = 50        # paths kept per day, and the count is still exact
RESULT_BAD_CAP = 200        # paths listed in the top-level result


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_days(root):
    """Every YYYY/MM/DD folder under root, as 'YYYY/MM/DD' strings, oldest first."""
    days = []
    for year in sorted(os.listdir(root)):
        if not re.fullmatch(r"\d{4}", year) or not os.path.isdir(os.path.join(root, year)):
            continue
        for month in sorted(os.listdir(os.path.join(root, year))):
            if not re.fullmatch(r"\d{2}", month):
                continue
            for day in sorted(os.listdir(os.path.join(root, year, month))):
                if re.fullmatch(r"\d{2}", day) and os.path.isdir(os.path.join(root, year, month, day)):
                    days.append("%s/%s/%s" % (year, month, day))
    return days


def check_frame(root, day, stem, now, settle_s):
    """Check one frame. Returns (counters, bad). counters keys: files, unverifiable, skipped_recent."""
    folder = os.path.join(root, day)
    counts = {"files": 0, "unverifiable": 0, "skipped_recent": 0}
    bad = []
    json_path = os.path.join(folder, stem + ".json")

    def rel(name):
        return "%s/%s" % (day, name)

    def recent(path):
        try:
            return now - os.path.getmtime(path) < settle_s
        except OSError:
            return True

    if recent(json_path):
        counts["skipped_recent"] += 1
        return counts, bad
    try:
        with open(json_path, "rb") as f:
            raw = f.read()
        data = json.loads(raw.decode("utf-8")) if raw.strip() else None
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (OSError, ValueError):
        bad.append({"path": rel(stem + ".json"), "problem": "unreadable_json"})
        return counts, bad

    files = (data.get("Capture") or {}).get("files") if isinstance(data.get("Capture"), dict) else None
    entries = files if isinstance(files, dict) else {}
    if not entries:
        counts["unverifiable"] += 1     # no Capture block: an older pilot frame
    for ext in IMAGE_EXTS:
        path = os.path.join(folder, "%s.%s" % (stem, ext))
        entry = entries.get(ext)
        if not isinstance(entry, dict):
            # Not in the JSON. Still catch the one obvious fault, an empty file.
            if ext == "jpg" and os.path.exists(path) and os.path.getsize(path) == 0 and not recent(path):
                bad.append({"path": rel(os.path.basename(path)), "problem": "zero_length"})
            continue
        counts["files"] += 1
        name = os.path.basename(path)
        if not os.path.exists(path):
            bad.append({"path": rel(name), "problem": "missing"})   # the JSON is old, so the sync is done
            continue
        if recent(path):
            counts["skipped_recent"] += 1
            continue
        size = os.path.getsize(path)
        if size == 0:
            bad.append({"path": rel(name), "problem": "zero_length"})
            continue
        want_bytes = entry.get("bytes")
        if isinstance(want_bytes, int) and want_bytes != size:
            bad.append({"path": rel(name), "problem": "mismatch"})
            continue
        want = entry.get("sha256")
        if not want:
            counts["unverifiable"] += 1
            continue
        try:
            got = sha256_file(path)
        except OSError:
            bad.append({"path": rel(name), "problem": "unreadable"})
            continue
        if got != want:
            bad.append({"path": rel(name), "problem": "mismatch"})
    return counts, bad


def verify_day(root, day, now, settle_s):
    folder = os.path.join(root, day)
    totals = {"frames": 0, "files": 0, "unverifiable": 0, "skipped_recent": 0}
    bad = []
    names = sorted(os.listdir(folder))
    stems = set()
    for name in names:
        m = FRAME_JSON.match(name)
        if m:
            stems.add(m.group("stem"))
    for stem in sorted(stems):
        counts, frame_bad = check_frame(root, day, stem, now, settle_s)
        totals["frames"] += 1
        for k in ("files", "unverifiable", "skipped_recent"):
            totals[k] += counts[k]
        bad.extend(frame_bad)
    # Images with no JSON at all are noted, not failed: the sync may have them half way.
    orphans = [n for n in names if re.match(r"^[A-Za-z0-9_-]+_\d{8}T\d{6}Z(?:_night)?\.(jpg|dng)$", n)
               and n.rsplit(".", 1)[0] not in stems]
    totals["orphan_images"] = len(orphans)
    return totals, bad


def write_atomic(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, ".%s.tmp" % os.path.basename(path))
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_state(path, camera):
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if isinstance(state, dict) and isinstance(state.get("days"), dict):
            return state
    except (OSError, ValueError):
        pass
    return {"schema_version": SCHEMA_VERSION, "camera": camera, "days": {}}


def summarise(state, run, now, started):
    """The top-level result fields, rebuilt from the per-day entries so old problems persist."""
    bad_files = []
    problem_days = 0
    counts = {"missing": 0, "mismatched": 0, "zero_length": 0, "unreadable_json": 0, "other": 0}
    names = {"missing": "missing", "mismatch": "mismatched", "zero_length": "zero_length",
             "unreadable_json": "unreadable_json"}
    for day, entry in sorted(state["days"].items()):
        if entry.get("bad_count"):
            problem_days += 1
        for item in entry.get("bad", []):
            bad_files.append(item)
        for item in entry.get("bad", []):
            counts[names.get(item["problem"], "other")] += 1
        extra = entry.get("bad_count", 0) - len(entry.get("bad", []))
        if extra > 0:
            counts["other"] += extra     # capped paths: counted but not listed
    verified = [e["verified_utc"] for e in state["days"].values() if e.get("verified_utc")]
    state.update(
        schema_version=SCHEMA_VERSION,
        last_started_utc=iso(started),
        last_run_utc=iso(now),
        run=run,
        archive={"days_known": len(state["days"]), "days_with_problems": problem_days,
                 "oldest_verified_utc": min(verified) if verified else None},
        problem_counts=counts,
        bad_files=bad_files[:RESULT_BAD_CAP],
        bad_files_truncated=len(bad_files) > RESULT_BAD_CAP,
        ok=not bad_files and not any(counts.values()))
    return state


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("root", help="one camera's folder on the NAS")
    p.add_argument("--state", help="state/result file (default: ../health/<camera>/verify.json beside the camera folder)")
    p.add_argument("--cycle-days", type=int, default=60, help="re-read the whole archive about this often (one run a day)")
    p.add_argument("--max-days", type=int, default=0, help="most days to read in one run (0 = no cap)")
    p.add_argument("--settle-min", type=float, default=10, help="skip files changed within this many minutes")
    p.add_argument("--all", action="store_true", help="read every day")
    p.add_argument("--forget-missing", action="store_true", help="drop days that were verified but have no folder now")
    p.add_argument("--now", help="pretend it is this UTC time, 2026-11-15T12:00:00Z (tests)")
    args = p.parse_args(argv)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("sunset-verify: not a folder: %s" % root, file=sys.stderr)
        return 2
    camera = os.path.basename(root.rstrip("/\\"))
    state_path = args.state or os.path.join(os.path.dirname(root), "health", camera, "verify.json")
    now = (datetime.strptime(args.now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
           if args.now else time.time())
    started = now
    settle_s = args.settle_min * 60

    state = load_state(state_path, camera)
    state["camera"] = camera
    days_on_disk = list_days(root)
    on_disk = set(days_on_disk)

    # A verified day whose folder is gone is a loss unless the owner says it was on purpose.
    for day in [d for d in state["days"] if d not in on_disk]:
        if args.forget_missing:
            del state["days"][day]
        else:
            state["days"][day] = {"verified_utc": state["days"][day].get("verified_utc"), "frames": 0, "files": 0,
                                  "bad_count": 1, "bad": [{"path": day, "problem": "missing_day"}]}

    known_bad = [d for d in days_on_disk if state["days"].get(d, {}).get("bad_count")]
    new = [d for d in days_on_disk if d not in state["days"]]
    clean = sorted((d for d in days_on_disk if d in state["days"] and d not in known_bad),
                   key=lambda d: state["days"][d].get("verified_utc") or "")
    if args.all:
        todo = days_on_disk
    else:
        quota = math.ceil(len(clean) / max(args.cycle_days, 1)) if clean else 0
        todo = known_bad + new + clean[:quota]
    if args.max_days > 0 and not args.all:
        todo = todo[:args.max_days]

    run = {"days_checked": 0, "frames": 0, "files_checked": 0, "unverifiable": 0, "skipped_recent": 0,
           "orphan_images": 0, "new_problems": 0}
    for day in todo:
        try:
            totals, bad = verify_day(root, day, time.time() if not args.now else now, settle_s)
        except OSError as e:
            totals = {"frames": 0, "files": 0, "unverifiable": 0, "skipped_recent": 0, "orphan_images": 0}
            bad = [{"path": day, "problem": "unreadable_day:%s" % e.__class__.__name__}]
        entry = {"frames": totals["frames"], "files": totals["files"], "unverifiable": totals["unverifiable"],
                 "bad_count": len(bad), "bad": bad[:PER_DAY_BAD_CAP]}
        if not totals["skipped_recent"]:
            entry["verified_utc"] = iso(time.time() if not args.now else now)   # complete: not read again until its turn
        else:
            entry["pending_recent"] = totals["skipped_recent"]   # no verified_utc: it counts as new next run
        before = state["days"].get(day, {}).get("bad_count", 0)
        if "verified_utc" not in entry:
            state["days"].pop(day, None)
            if bad:
                state["days"][day] = entry   # keep the problems visible even though the day is not finished
        else:
            state["days"][day] = entry
        run["days_checked"] += 1
        run["frames"] += totals["frames"]
        run["files_checked"] += totals["files"]
        run["unverifiable"] += totals["unverifiable"]
        run["skipped_recent"] += totals["skipped_recent"]
        run["orphan_images"] += totals["orphan_images"]
        run["new_problems"] += max(len(bad) - before, 0)
        write_atomic(state_path, json.dumps(summarise(state, run, now, started), indent=2) + "\n")

    finished = now if args.now else time.time()
    result = summarise(state, run, finished, started)
    run["seconds"] = round(finished - started, 1)
    write_atomic(state_path, json.dumps(result, indent=2) + "\n")
    c = result["problem_counts"]
    print("sunset-verify %s: %d days, %d files read, missing=%d mismatched=%d zero_length=%d unreadable_json=%d "
          "unverifiable=%d -> %s" % (camera, run["days_checked"], run["files_checked"], c["missing"], c["mismatched"],
                                      c["zero_length"], c["unreadable_json"], run["unverifiable"],
                                      "OK" if result["ok"] else "PROBLEMS"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
