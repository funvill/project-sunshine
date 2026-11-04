# Project Sunset

A five-year time-lapse of the western sky through a window, with sunset as the subject. Real capture
starts on the winter solstice, 2026-12-21. A pilot runs first on a Raspberry Pi 3 B+ with an IMX477
camera.

The Pi takes a frame every 15 minutes and saves it to its SD card. A sync then copies each frame to a
NAS and removes the local copy once the copy succeeds, so a NAS or network outage does not lose
frames.

## Layout

| Folder | What is in it |
|---|---|
| `pi/` | Everything that runs on the Pi: capture, sync, self-test, focus helper, systemd units |
| `nas/` | The [daily sunset video](nas/README.md) job, which runs on the NAS |
| `tests/` | Offline tests with a stubbed camera and NAS; no Pi needed |
| `docs/` | [Pi setup guide](docs/setup.md) and [hardware notes](docs/hardware/README.md) |
| `CLAUDE.md` | Project brief: decisions, hardware, risks and backlog |

## Tests

```bash
bash tests/run.sh
```

Needs bash, coreutils and Python 3. The daily video's encoding tests also need ffmpeg, and are skipped
without it.
