# Verification record (latest first)

## DaVinci hand-off and audit fixes — 2026-09-20 (see below the 09-23 entry)

## 2026-09-23 demo production (bcs-demo-45s) and Genspark primary route

- `provider_jobs.py` now accepts Genspark as a primary route (`test_genspark_primary.py`, 2 tests; 222 total pass): text-to-video
  (0 references, up to 1080P) or one first frame (720P), `mode` recorded; the fallback contract with `fallback_for` is unchanged.
- Live: the demo narration (409 characters) rendered as ONE ElevenLabs v3 request and `narration_plan.py layout --mode single` cut
  it into six segments by the returned word timestamps; pauses were retuned afterwards without re-rendering. Suno returned
  `captcha_required` and stayed blocked (fail-closed, nothing submitted). Genspark: batch of 8 approved with `--pilot 2`; S01 (1080P,
  5 s, 16:9) generated and collected (1920x1088 H.264, 24 fps, 5.04 s; the 1088 rows are encoder padding, crop to 1080 on
  conform); S02's CLI call was killed mid-transport when the session ended, leaving the job `submitting` with no receipt, and the
  account balance moved 5352.5 -> 4280 (about 610 for S01, the rest consistent with S02 having been charged). No resubmission;
  reconciliation needs the website's video history.
- Lesson recorded in the Genspark test and docs: never run a paid CLI call in a background shell that can be torn down; run it
  in the foreground with its own timeout, and treat an interrupted call as `unknown`.

## 2026-09-23 round 2: fixes chosen by council + Jev verdict (F1, F7, F5, F8, F4, F3)

- **220 Python tests pass** (13 new in `test_long_form.py`): single-render narration cut at segment boundaries by word
  timestamps with 40/100 ms handles, pauses inserted, merged words on the mix clock, word-count mismatch refused;
  `split` writes `request-single.json`; Suno extension fields validated together and the bridge forwards
  `continue_clip_id` / `continue_at` / `task:extend` to a fake client (and null without them); validator warnings for a
  1280x720 source under `zoom-in` in a 1080p plan (ffprobe patched), motion density over 60 percent and repeated
  presets back to back; `approve-batch --pilot 2` holds the third job until `batch-release`, which refuses before the
  pilot ran and after it was released; `style_constraints` + `avoid` (max 3) fold once, gate mirrors both;
  `antigravity.py check` flags present items from a mocked Gemini reply, reads the request's avoid list, and reports
  `unparsed` on prose. `ruff --select F` clean.
- No provider call, no Blender render and no Resolve import were needed for this round (all changes are contracts,
  cutting by FFmpeg, and ledgers). The single-narration cut was exercised on a synthetic 3 s tone with a hand-written
  alignment; the first real ElevenLabs single render will be the first listening test of the seams-free route.
- Originals of the round-2 edited files: `_backups/20260923-150s-upgrade/round2/`.

## 2026-09-23 long-form commercial upgrade (150 s requirements)

- **207 Python tests pass** (`python -B -m unittest discover -s scripts -p 'test_*.py'`, 20 s): the 192 existing plus
  `test_long_form.py` (15): gain-envelope validation and a measured -20 dB -> 0 dB music lift on the rendered stem;
  brand-word captions and the single-state (no karaoke) path with the renderer mocked; plan validation for the motion
  presets, `motion_amount`, `transform_keys`, `image-sequence` (+`hold_last`, `resolve_movie`); the Resolve hand-off
  substituting the companion movie and refusing a sequence without one; `avoid` folding once; `approve-batch` cap enforced
  across three prepared image jobs (third `execute` refused before transport, state stays `prepared`) and batch rules;
  `narration_plan` split/layout with real WAV durations and merged word offsets, plus job lookup by exact text;
  `sequence_tools` still / alpha-sequence / alpha-movie round trip on FFmpeg-generated ProRes 4444; the optional
  `visual_system.exclusions` gate.
- **Live Blender 5.1 assembly** in `<productions>/blender-longform-validation-20260923/`:
  a 96-frame 640x360 plan with a movie under `zoom-in` (amount 0.08), a `still` freeze frame on the last second, a
  50%-opacity layer driven by `transform_keys` (scale 1 -> 1.2, offset_x 0 -> 30, rotation 0 -> 3 deg), a 12-frame
  alpha `image-sequence` held to 24 frames (`hold_last`), a title with `slide-left` and fades, a `pan-left` layer and a
  sound strip with `volume_keys`. `render-v002/project.blend` reopened with all seven strips at the planned frames; the
  image sequence has 24 elements; the stored keyframes match the plan (bg scale 1 -> 1.08 over 72 frames, title
  offset_x 25.6 -> 0 with 4 alpha keys, pan offset_x -25.6 -> 25.6, tk four animated fields, music volume 0.2 -> 0.8).
  `preview.mp4` decodes (4.01 s container, 4.000 s picture); four frames and a contact sheet were inspected: overlays,
  slide, pan overscale (no edge reveal) and the freeze frame appear as planned. `delivery_qa.py` passes the same plan
  without loudness targets; with targets it correctly fails on the un-mastered synthetic tone (-24.6 LUFS), which is the
  gate working, not a defect.
- **Resolve hand-off (offline)**: `export-xml` wrote `CUT_v001` with the image sequence replaced by
  `butterfly-resolve.mov` (the PNG path does not appear in the XML) and listed `motion`, `motion_amount`,
  `transform_keys`, fades and `volume_keys` per clip as unmapped. No live Resolve import was run for this change; the
  station import path is unchanged from 2026-09-22.
- A first render exposed that a `transform_keys` field first mentioned in a later key held that value for the whole
  clip; `apply_transform_keys` now seeds the rest value at the first key (verified in render-v002: offset_x 0 -> 30).
- No provider generation, no WhatsApp send, no creative acceptance. Originals of every edited file and the patch scripts
  are in `_backups/20260923-150s-upgrade/`.


- **159 Python tests pass** (`python -B -m unittest discover -s scripts -p 'test_*.py'`, 15 s) and **10 Node tests pass** (`node --test --test-reporter=tap scripts/test_grok_*.mjs`). New: `test_davinci_bridge.py` (10, offline xmeml/verify/guards) and `test_delivery_qa_targets.py` (5, loudness gate binding). `ruff --select F` reports only two intentionally kept unused locals (`edit_audit.rate`, `shot_templates.aspect`).
- **Live**: `davinci_bridge.py` imported a four-item plan into a temporary Resolve Studio 21.1.0.14 project and verified every item; the temporary project was deleted afterwards. Headless `claude -p` reached the `davinci-resolve` MCP after raising `MCP_TIMEOUT` (server cold start measured at 12.5 s; the 30 s default timed out under load). Evidence: `<productions>/davinci-bridge-smoke-20260920/handoff-v002/`.
- **Audit fixes applied** (read-only audit of scripts/ by a subagent, then fixes): unique temp names in `atomic_json`; `subprocess.TimeoutExpired` handled at every CLI boundary; long-source audio extraction timeout 1800 s; `find_blender` refuses unvalidated non-5.1 builds; `delivery_qa.py --audio-qa` binds the mix targets (previously the gate was a silent opt-in); ten unused imports removed. Deferred and documented in CLAUDE.md: triplicated I/O primitives, hard-coded VPS host in `whatsapp_delivery.py`, unused `aspect`.
- **Station archive (same day, after the user set the storage policy)**: 168 Python tests pass including `test_station_archive.py` (9, fake station transport). Live: `archive-doctor` deployed the helper and reported 1338 GB free on `D:/video-productions-archive`; `archive-push` mirrored the smoke production (10 files, 0.9 MB, Hebrew folder and file names) and every file verified by SHA-256 on the station; `archive-status --verify` returned `fully_archived:true`; a second push uploaded nothing. Nothing was deleted on either side.
- These are technical checks. No provider generation, no WhatsApp send, no creative acceptance.

# Editing retrospective verification — 2026-09-09

- **123 unit/behavioral tests pass** with `python -B -m unittest discover -s scripts -p 'test_*.py' -q` (29.835 seconds in the final run). Nineteen new tests cover continuous/retimed/broken source clocks, malformed boundaries, silent selected audio and antiphase stereo, expected SFX silence rejection and intentional silence, energy jumps without sample clicks, exact PCM preservation/protected intervals and changed length, stale encoded/source/contract hashes, and uncertain WhatsApp reconciliation. Provider and WhatsApp transports were mocked; no video was sent by these tests.
- **Observed and fixed during this audit:** initially an edited audit contract could still reuse the previous report while target bytes were unchanged. A regression reproduced the incorrect PASS. The report now includes the contract in its checked hash manifest, and the test rejects that stale evidence. This binds a declaration to the report; it still does not prove that Blender executed the declaration.
- **Actual V25/V26 read-only integration passed** under `<productions>/the-org-year-summary-5786/reviews/skill-retrospective-20260909/verified-v2/`. The audit covers 178 supplied aligned word intervals; all four compared PCM buses have 4,320,000 frames at 48kHz stereo. Voice/mix change only inside 14.610–14.650 seconds, with zero changed frames in protected words or outside the allowed repair; music/SFX remain identical. The historical clock map with a 72-frame jump and the all-zero `typing-16.wav` each fail as expected. Actual compressed-copy decode/stream/audio measurement and audit hash binding passed.
- **Boundary evidence:** the old voice's 10ms RMS jump is +25.7459dB with zero boundary sample step; V26 is -0.2440dB. Encoded-copy windows are +13.4308dB before and -0.7007dB after. These are measurements, not a new listening acceptance claim. The picture-clock evidence is the recorded map, not automatic motion analysis.
- **Skill metadata validates**, and the Claude Code entry remains a junction to the canonical Codex skill. Reference links, template JSON and changed-file hashes are checked locally. Original edited skill files are retained in the production's `before/` backup with hashes. No new media generation, provider request, deployment or delivery was performed for this retrospective.

These additions provide bounded checks and reusable editing rules, not automatic optical centering, screen tracking/occlusion, speech recognition, subjective review or a universal edit-repair engine. See [community-film-editing.md](community-film-editing.md) and [executable-workflow.md](executable-workflow.md). The earlier installation snapshots below remain historical evidence.

# Expanded installation verification — 2026-09-06

## What was implemented

Director treatment and shot contracts, reasoned editorial workflow, local footage analysis/transcription routing, normalized EDL conform with word remapping, stable RTL word emphasis, measured sound finishing, two actual Blender shot templates, provider-specific job adapters, encoded-delivery QA, and compressed personal WhatsApp handoff. These are included in the normal SKILL.md workflow and documented with executable input contracts.

## Verified evidence

- **101 unit/behavioral tests pass** via `python -B -m unittest discover -s scripts -p 'test_*.py' -q`. This includes original assembly boundaries, exact request authorization, semantic duplicate detection, changed references, uncertain submission blocking, Suno CAPTCHA preflight, acceptance of refreshable expired Grok OAuth despite API-key discovery returning false, rejection of missing credentials/provider or mismatched agentDir, explicit gateway agent/session binding, preserved narration after alignment failure, word-boundary protection, self-recipient validation and WhatsApp receipt/duplicate handling. Premium tests exercise direction/shot gates, placeholder rejection, paid-motion references without granting authorization, product-spec bounds, immutable review-media hashes, explicit dispositions and real FFmpeg evidence extraction. The additional 13 technique-library tests cover bounded planar tracks, non-collapsed corner geometry, exact asset validation, explicit light hierarchy and ordered licensed 2.5D layers. Remote-render tests cover archive traversal, semantic IDs, device restrictions, tamper detection, idempotency, global locking, compact status responses that preserve the stored frame ledger and explicit `UNKNOWN` reconciliation. Production-dashboard tests cover phase derivation, uncertain jobs, review evidence and completion. Provider and send transports were mocked.
- **Skill metadata validates** using `python -X utf8 <codex-skills>/.system/skill-creator/scripts/quick_validate.py <skill-root>`. Windows' default cp1255 fails on Unicode symbols; use explicit UTF-8 for this validator, not a lossy file conversion.
- **Actual local integration passes** in `<productions>/blender-studio-premium-validation-20260906-v003/verification.json`: known scene change detected, blue/red footage reordered and pixel-verified, words mapped to the new timeline, Hebrew/numeric emphasis rendered with the licensed Almoni font, measured speech-driven music attenuation, separate stems, 24-bit master, both original shot templates, the controlled-product preview and its 9:16/glare boundary in Blender 5.1. No provider credits were used.
- **Controlled-product technique rendered and corrected:** the first calibration preview exposed an aspect-dependent vertical crop that unit tests could not reveal. `premium_product.py` now derives a safe camera distance from normalized product bounds, lens, horizontal sensor fit, delivery aspect and explicit padding. The first 9:16/glare boundary then exposed the removed pre-5.0 `scene.node_tree` API; the implementation now creates a 5.1 `CompositorNodeTree`, uses named glare inputs and returns through a group-output socket. Both corrected paths are in the v003 integration above. A separate complete 24-frame, 16-bit PNG render is in `<productions>/blender-studio-premium-validation-20260906-v001/premium-product-v003-full/`; all frames were inspected as an ordered contact sheet and show the reflection/camera progression followed by the settled hold without edge cropping. This low-poly sphere is render/framing evidence, not commercial art-direction evidence for a customer product.
- **Three campaign-technique packages are visually verified on local original fixtures:** tracked-corner screen replacement, environment-grounded product integration and layered camera projection each produced an editable Blender 5.1 scene, 24-frame PNG16 sequence, encoded inspection clip, all-frame contact sheet and content-bound manifest under `<productions>/blender-technique-library-20260906-v001/`. A 12-frame 180x320 boundary first exposed a clipped 2.5D subject; the retained v001 failure was corrected in v002 by separating opaque overscan from subject scale. These fixtures prove bounded implementation and aspect behavior, not automatic tracking/light matching, rights or customer-ready direction.
- **Loudness fixture:** target -18 LUFS, measured -18.05 LUFS after normalization, true peak -12.16 dBTP under the -1.5 ceiling, exact 4.0-second WAV. This is synthetic sound; it does not test acting, musical taste or intelligibility.
- **Actual Blender assembly:** 96 frames, 320×180, 24fps, H.264 + AAC; picture duration 4.000s and container 4.010s. The final encoded file passed decode/stream/duration QA in `delivery-qa.json`. A Hebrew caption frame was visually inspected.
- **Both Blender templates rendered:** product-stage from a calibration GLB and artwork-parallax from separated image layers. Visual review caught overhead-camera roll in the initial parallax render. The camera was corrected, rerendered in `parallax-v002/shot.mp4`, and its upright Hebrew output was visually inspected. The corrected output supersedes the first technical parallax result in the initial integration report.
- **WhatsApp compression:** 4.01-second viewing copy at 74,796 bytes, with master preserved and successful decode. A separate 10-second 1280×720 stress fixture exercised the two-pass size branch: 969,482 bytes against a 1,048,576-byte budget. No test video was sent.
- **Read-only live connections:** ElevenLabs selected voice accessible; WAHA personal session WORKING and exact self identity matched. Suno's initially missing login was subsequently supplied through the existing local client file: the fresh probe authenticated with HTTP 200 and reported 9,755 credits. No cookie was printed or copied into the skill. The corrected Grok probe finds selected OAuth, refresh available, matching `/home/node/.openclaw/agents/meir/agent`, no xai API key/fallback, and `ready_to_submit:true`. The native source confirms that generation supplies a nonempty agentDir to profile resolution, then handles adoption, a five-minute refresh margin and locked refresh/store writeback. API-key capability discovery's false result is diagnostic only. The user independently reported a successful real video with automatic renewal; that production was not rerun here.
- **VIDEO STATION remote render:** Blender 5.1.0 and NVIDIA RTX A5000 CUDA doctor pass. Content-addressed transfer, WMI launch surviving SSH disconnect, validated PNG16/OpenEXR-Half collection, strict partial resume, duplicate submission and missing-asset rejection were exercised. Detailed evidence and limitations are in `render-station.md`.

## Practical limits

No paid/subscription generation occurred in this setup task. Thus real Suno music, Grok I2V, Codex image output, ElevenLabs narration and actual WhatsApp video delivery were not new end-to-end production tests performed here. Suno authentication is verified and Grok's erroneous local OAuth readiness block is corrected. Its native renewal code was inspected, not replaced or force-refreshed. Account quotas and actual shot results remain checks for the authorized production.

The fixtures establish executable behavior, not international commercial quality. Semantic take selection, pronunciation, performance, lighting decisions, product accuracy, music edit, color matching and the final story must be reviewed in the actual production. Arbitrary advanced tracking/roto/simulation is authored per shot; the two reusable templates are not a universal VFX library. Local word transcription uses the existing installed CLI but no real speech transcription was exercised in this synthetic integration check.

Do not rerun the entire suite for a documentation-only change. Recheck affected behavior after code changes and run real production acceptance checks within the user's approved budget.
