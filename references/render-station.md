# VIDEO STATION remote render

The laptop remains the production authority: direction, editing, VSE/audio, Hebrew typography, previews, collection and QA happen locally. The Windows VIDEO STATION behind the OS-owned SSH alias `ai-station` runs only heavy Blender Cycles frames under `C:/render-worker`. Its pinned executable is Blender 5.1.0 and the worker concurrency is one.

## Safety contract

- `render-prepare` opens a copy in Blender with auto-execution disabled, packs eligible resources and hashes the resulting scene. It rejects missing assets, linked libraries, external fonts, file-backed VSE strips, movie clips and cache files. Convert licensed text to curves or provision it deliberately; fonts are never copied implicitly.
- The job ID is SHA-256 of the semantic contract: bundled scene hash, dependency hashes, exact Blender version and render profile. `job.json` and `submission.zip` are immutable; `dispatch.json`, remote `state.json` and `progress.json` are separate mutable state.
- The worker accepts only a validated ZIP from its configured incoming directory, extracts only `job.json` and `bundle/*`, checks path traversal/symlinks/expanded size and verifies the scene hash. It has no free-shell command and never deletes or overwrites an existing job.
- A detached worker launched by the Windows WMI process service survives SSH disconnects. It writes each missing PNG16 or OpenEXR-Half frame to a unique `.writing-*` file, loads it back through Blender to verify dimensions, then atomically renames it. Resume skips only frames whose size, dimensions and hash also match that job's atomic progress ledger; an unregistered frame requires inspection.
- States are `prepared -> queued -> running -> complete|failed|unknown`. A missing executor becomes `unknown`; never resubmit or retry it until the station, output frames and logs have been reconciled. Failed jobs may be started again only after diagnosis; a changed profile creates a different job ID.
- Collection is permitted only from `complete`. The station creates an immutable result archive with per-file hashes. The laptop verifies job identity, manifest hashes, ordered frame count and per-frame hashes before extraction.

## Commands

Run from this skill directory. `studio.py` exposes the same commands with a `render-` prefix.

```powershell
python scripts/render_dispatch.py doctor --device CUDA
python scripts/render_dispatch.py prepare --scene C:/project/shot.blend --project C:/project --device CUDA --output-format png16
python scripts/render_dispatch.py submit --job-dir C:/project/render-jobs/<job-id> --start
python scripts/render_dispatch.py start --job <job-id> # deliberate start/restart only
python scripts/render_dispatch.py status --job <job-id> --job-dir C:/project/render-jobs/<job-id>
python scripts/render_dispatch.py collect --job <job-id> --out-dir C:/project/renders/<revision>
python scripts/render_dispatch.py verify --archive C:/project/renders/<revision>/<job-id>-result.zip --job <job-id>
```

Use `--frame-start`, `--frame-end`, `--frame-step`, `--resolution-x`, `--resolution-y`, `--resolution-percentage` and `--samples` to create an explicit render profile. Defaults come from the source scene. `--output-format openexr-half` is for compositing; encoding remains local. `CPU_TEST` exists only for a tiny deterministic calibration fixture and is not a production device.

After a fully inspected `UNKNOWN`, recovery requires the explicit `start --reconciled` flag. Record what was checked; do not use that flag as a retry shortcut.

## Production archive on the station

Besides rendering, the station is the durable store for whole productions: `scripts/station_archive.py` (`studio.py archive-doctor|archive-push|archive-status`) mirrors a production folder to `D:/video-productions-archive/<slug>/` over the same `ai-station` alias using `sftp` batches, deploys a small stdlib helper to `<root>/_bin/` (directory creation, remote SHA-256, manifest read/write; it never deletes), verifies every uploaded file by hash before recording it, and writes a `push-*.json` report under the production's `archive/` folder. Paths and Hebrew file names travel as JSON on stdin, not on the command line. A production folder name must be an ASCII slug or `--slug` must be given. Local hashes are cached by size+mtime in `archive/local-hash-cache.json`.

## Installation and recovery

Remote configuration is `C:/render-worker/config.json`; deployed scripts are under `C:/render-worker/bin`. SSH keys remain in Windows OpenSSH configuration and are never copied into this skill. A stale `worker.lock`, `.staging-*`, `.writing-*`, `failed` or `unknown` state is evidence: inspect it before any manual recovery. Do not remove or retry it automatically. The local render path remains the fallback when the station is unavailable.

## Acceptance evidence — 2026-09-06

- All 88 local regression/contract tests passed, including traversal, semantic-ID, tamper, manifest, concurrency-lock, idempotency, production-dashboard, compact status output and `UNKNOWN` boundaries. Completed status responses expose `verified_frames` without copying the full frame ledger into the CLI response; the stored ledger remains unchanged. After explicit user approval, the compact-status worker was deployed and local/remote SHA-256 matched at `FD6DA09B3895B20181C4708D0162A9E2A27E0F4E2A9FBBDF34900D2676E3C59D`. Live doctor returned ready and the completed production job returned `verified_frames: 288`.
- Remote doctor reported Blender 5.1.0 and one enabled CUDA device: NVIDIA RTX A5000. The worker was unlocked and no Blender process remained at handoff.
- The same bundled-scene hash and 192×192, 16-sample, three-frame Cycles calibration took 4.104 s on local CPU and 1.586 s on the station CUDA device (2.59× on this deliberately tiny workload). First frames compared at SSIM 1.000000 and PSNR 116.28 dB.
- PNG output decoded as 192×192 `rgba64be` (16-bit RGBA). A separate OpenEXR-Half job completed, collected and decoded as 192×192 `gbrapf16le`.
- A partial-resume fixture registered frame 1 in the job progress ledger; the remote Blender log saved only frame 2. The collected result verified, and a repeated submission returned `idempotent: true` without rendering.
- A real external image was removed after saving a test `.blend`; preparation stopped with `missing image asset` before creating or submitting a job.
