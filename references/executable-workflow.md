# Executable editorial and finishing workflow

Run Python commands from this skill directory, or use absolute script paths. Keep all project outputs outside the skill and outside the VS Code installation. Every render/conform/mix creates a new revision folder. JSON paths resolve relative to the input JSON unless explicitly documented. Generated examples below are input contracts; replace creative content with the actual production's decisions.

## 0. Initialize and pass creative gates

```powershell
python scripts/studio.py init --project PROJECT --idea "THE USER'S ORIGINAL IDEA"
Copy-Item PROJECT/planning/direction-v1.template.json PROJECT/planning/direction-v1.json
Copy-Item PROJECT/planning/shots-v1.template.json PROJECT/planning/shots-v1.json
```

Initialization creates neutral planning, analysis, job, review, render, revision and delivery folders. It grants no provider, sending or publishing authorization. The copied templates intentionally fail until every `REPLACE:` field is replaced by a real production decision. Keep `direction.md` and `storyboard.md` as readable treatments; their JSON counterparts are the executable contract.

At any point, derive the current phase and blockers without changing the project:

```powershell
python scripts/studio.py production-status --project PROJECT
```

The dashboard reads the latest creative gates, provider/render jobs, finalized shot reviews and delivery QA. It surfaces uncertain jobs and incomplete evidence; it does not infer authorization or mark work complete.

```powershell
python scripts/creative_gates.py --direction PROJECT/planning/direction-v1.json --stage direction --out PROJECT/planning/direction-gate-v001.json
python scripts/creative_gates.py --direction PROJECT/planning/direction-v1.json --shots PROJECT/planning/shots-v1.json --stage styleframes --out PROJECT/planning/styleframes-gate-v001.json
```

Before an approved paid video request, set the matching shot source to `styleframe-approved` and record `generation.provider`, `generation.semantic_fingerprint`, `generation.approval_ref` and `generation.max_attempts`, then run stage `paid-motion`. This catches missing creative and provenance fields only. `provider_jobs.py` separately validates the exact approval, request and content fingerprint and remains the spending authority.
For a series of shots (or narration segments) prepare every request first, then record one approval for all of them with
`provider_jobs.py approve-batch --jobs PROJECT/jobs --job ID ... --evidence "..." --limit TOTAL --unit UNIT [--per-job N]`;
each `execute` then checks the batch's running total before it submits, and `batch-status` shows what was spent. Add
`--pilot N` so only the first N jobs run until `batch-release --evidence "..."` records the pilot review. Copy
`direction.visual_system.style_constraints` and `exclusions` (at most three) into every generation request as
`style_constraints` / `avoid`; after collection run `antigravity.py check --media SHOT --request REQUEST.json --out ...`
(closed yes/no vision questions, advisory); see [providers.md](providers.md).

Before rough-cut assembly, set each actually chosen source to `selected` and run stage `rough-cut`. A gate file is immutable evidence for that revision; do not overwrite a failed report—correct the source contract and write the next version.

## 1. Understand sources

```powershell
python scripts/editorial.py analyze --source PROJECT/assets/interview.mp4 --cache PROJECT/analysis --transcribe
```

The analysis includes ffprobe metadata, source hash, scene-cut candidates, black/silence signals and timecoded inspection frames. `--transcribe` uses the installed local `whisper-local` and cached models with network downloads disabled. Omit it for nonspeech footage. Read words and inspect actual frames/audio. Cache hits reuse identical source/settings. Signals do not decide which performance or scene is good.

## 2. Build the editorial cut

```json
{"fps":24,"width":1920,"height":1080,"cuts":[
  {"source":"assets/interview.mp4","in":4.5,"out":9.25,"words_path":"analysis/interview-words.json","reason":"The speaker states the core problem clearly; retain the breath before the final clause","use_source_audio":true,"grade":{"brightness":0,"contrast":1,"saturation":1,"gamma":1}}
]}
```

```powershell
python scripts/editorial.py conform --edl PROJECT/edit-v001.json --out-dir PROJECT/conform-v001
```

Outputs normalized picture cuts, separate source audio, remapped word timing and `plan.json`. Known words cannot be cut halfway unless `allow_word_cut:true` and a concrete `word_cut_reason` are provided. Review transcript errors before treating word boundaries as truth. Cuts snap to frame boundaries. Default fitting preserves the whole picture with padding; for a fill/crop use an explicitly reviewed composition before conform. HDR/PQ/HLG/BT.2020 is rejected pending a deliberate transform. Unknown/log metadata requires manual source inspection; absence of an HDR flag does not establish SDR.

`grade` is a per-shot SDR correction, not automatic shot matching. Inspect adjacent frames and product/skin references before setting it. Preserve originals. More complex tracking, stabilization, rotoscoping or scene-specific VFX requires a separately authored and rendered Blender shot; there is no universal automatic VFX quality claim.

For J/L cuts, author picture and sound independently in the standard Blender plan: adjust `start`, `duration`, `source_start` in project-frame units, put overlapping sounds on different channels, and set `volume_keys` for crossfades. Ensure source audio has the required handles. The simple sequential EDL intentionally does not infer those editorial decisions.

**Camera moves and freeze frames.** Visual strips accept a motion preset (`motion`: `zoom-in`, `zoom-out`, `pan-left`,
`pan-right`, `slide-left`, `slide-right`, `slide-down`, `fade-rise`, `push-in`) with an optional `motion_amount`
(fraction of the frame or of the fitted scale; defaults 0.04 travel / 0.06 zoom), or explicit `transform_keys`
(`[{"frame":0,"scale":1},{"frame":95,"scale":1.15,"offset_x":-40,"rotation":1.5}]`, clip-relative frames; scale multiplies
the fitted size, offsets are output pixels, rotation is degrees; a field first mentioned in a later key starts from its
rest value at the first key, a field omitted later holds its last value). A freeze frame is a still extracted with
`python scripts/studio.py still --source SHOT.mp4 --time 4.9 --out PROJECT/assets/freeze.png` placed as a `kind:image` clip
on the frame after the movie strip ends. Pans overscale the picture slightly so no edge is revealed; watch the result.

## 3. Timed Hebrew emphasis

Style JSON:
```json
{"width":1920,"height":1080,"font_file":"<fonts-library>/<licensed-hebrew-font>.otf","font_size":72,"padding":100,"align":"center","vertical":"bottom","color":"#ffffff","highlight_color":"#ffd36a","max_words":5,"max_chars":40,"phrase_gap":0.5}
```
```powershell
python scripts/captions.py --words PROJECT/conform-v001/words.json --style PROJECT/caption-style.json --out-dir PROJECT/captions-v001 --fps 24
```

Produces logical RTL phrases, SRT, complete editable style JSONs and PNG states plus `overlays.json`. A phrase keeps the same layout as the active word changes color. `brand_words` (`{"מחוברים":"#1E88E5"}`) renders those words in their brand color in every state (punctuation around the word is ignored); `highlight_color: null` disables the spoken-word emphasis so each phrase is a single state. Merge its `clips` into the project plan on an unused channel. Validate after merging. For embedded Latin/numbers use isolated logical tokens where necessary; inspect their order visually. Set each aspect's safe area against the actual platform overlay. This is rendered editable-source typography, not native Blender text or arbitrary character-by-character 3D animation.

## 4. Sound finish

```json
{"duration":15,"target_lufs":-16,"true_peak_dbtp":-1.5,"lra":9,"voice_cleanup":true,"denoise":false,
 "duck":{"threshold":0.03,"ratio":6,"attack_ms":15,"release_ms":350},
 "tracks":[
   {"path":"assets/narration.mp3","role":"voice","at":0.4,"in":0,"duration":13.8,"gain_db":0},
   {"path":"assets/music.wav","role":"music","at":0,"in":12,"duration":15,"gain_db":-12,"fade_in":0.3,"fade_out":0.8},
   {"path":"assets/impact.wav","role":"sfx","at":9,"in":0,"duration":1,"gain_db":-9}
 ]}
```
```powershell
python scripts/audio_finish.py --spec PROJECT/mix-v001.json --out-dir PROJECT/audio-v001
```

Outputs voice/music/SFX stems, floating-point premaster, 48kHz/24-bit master and measured QA. Narration drives sidechain ducking. Any track may add `gain_keys`: `[[seconds_from_track_start, gain_db], ...]`, a linear-in-dB envelope evaluated per audio frame (swells into a transition, a dip under a key line, a lift at the end), applied after `gain_db` and before the fades; two music tracks with `fade_out`/`fade_in` and `gain_keys` are how a structural change (tense to uplifting at 0:45) is built. `templates/mix-long-form.template.json` is a complete 150-second example.

For narration with directed pauses, write the script as segments (`templates/narration-v1.template.json`). `python scripts/narration_plan.py split --script ... --out-dir ...` emits `request-single.json` (the whole script as one request, the recommended render: continuous tone and pace) plus one request per segment. After the single job completes, `narration_plan.py layout --mode single --script ... --jobs PROJECT/jobs --out-dir ...` cuts the render at the segment boundaries using the word timestamps (40/100 ms handles), inserts each `pause_after`, and writes `mix-tracks.json` (voice tracks for this spec), a merged `words.json` for captions and `end_of_speech_seconds`; the rendered text must equal the script word for word. `--mode segments` lays out per-segment renders instead (retake one segment; listen to every seam). Denoising is off unless needed; voice highpass can be disabled. Two-pass loudness uses the chosen target and checks the result. Replace the plan's old dialogue/music strips with the master when assembling delivery, while retaining stems for editing. Never play both original audio and the master together. Choose musical edit points and sound perspective by listening; automatic mixing does not do that directing work.

## 5. Reusable Blender shots

`shot_templates.py` runs inside Blender 5.1. Real input assets are required; missing files fail. It saves an editable, packed `.blend` with input JSON and renders an optional MP4.

Product stage uses a GLB, normalized placement, three soft lights, studio floor, camera orbit and depth of field. Calibrate framing, reflections, material color and focus on the actual product. Example contract:
```json
{"template":"product-stage","model":"assets/product.glb","width":1920,"height":1080,"fps":24,"frames":96,"samples":64,"lens_mm":65,"fstop":5.6,"radius":7,"orbit_start_deg":-15,"orbit_end_deg":15}
```

Artwork parallax requires deliberately separated transparent layers; no fake depth is inferred from a flat image. Preserve depth order and provide sufficient overscan to avoid revealing edges.
```json
{"template":"artwork-parallax","width":1920,"height":1080,"fps":24,"frames":72,"samples":32,"camera_distance":12,"travel":0.5,
 "layers":[{"image":"assets/background.png","depth":-1,"width":11},{"image":"assets/foreground.png","depth":1,"width":8}]}
```
```powershell
& 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe' --background --factory-startup --python-exit-code 1 --python scripts/shot_templates.py -- --spec PROJECT/shot-01.json --out-dir PROJECT/shot-01-v001 --render
```

Review the moving shot and insert its output as a movie strip. Product scene uses AgX; artwork uses Standard to preserve already rendered color. Treat the result as SDR encoded footage for VSE assembly; do not apply a second display transform.

For a hero product reveal whose story calls for a controlled approach and reflection sweep, use the stricter technique in [premium-blender-techniques.md](premium-blender-techniques.md):

```powershell
& 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe' --background --factory-startup --python-exit-code 1 --python scripts/premium_product.py -- --spec PROJECT/S04-product.json --out-dir PROJECT/renders/S04-preview-v001 --preview
```

Inspect the three preview states before `--render`. Full render creates numbered 16-bit PNG files plus an editable packed `.blend` and manifest. It does not encode a movie directly; conform the approved sequence for editorial and retain the sequence for recovery. This technique is not a default orbit, does not infer product truth and is not suitable for every beat.

### Animated overlays with alpha (logo, butterfly transition, Tesseract titles)

A movie that carries alpha (ProRes 4444 / PNG-in-MOV / VP9 alpha) becomes a PNG sequence for the VSE and a ProRes 4444
companion for Resolve:

```powershell
python scripts/studio.py alpha-sequence --source PROJECT/assets/butterfly.mov --out-dir PROJECT/assets/butterfly-seq
python scripts/studio.py alpha-movie --first PROJECT/assets/butterfly-seq/frame_00001.png --fps 24 --out PROJECT/assets/butterfly-resolve.mov
```

Plan clip: `{"kind":"image-sequence","path":"assets/butterfly-seq/frame_00001.png","start":1080,"duration":36,"channel":6,"hold_last":true,"resolve_movie":"assets/butterfly-resolve.mov"}`.
The sequence is the first file and its siblings (same folder and extension, sorted); fewer frames than the clip fails unless
`hold_last` freezes the final frame. `davinci_bridge.py export-xml` substitutes `resolve_movie` for the sequence and refuses
a sequence without one. Opaque movies can be sequenced with `--allow-opaque`.

## 6. Assemble and inspect delivery

```powershell
python scripts/studio.py validate --plan PROJECT/plan-v001.json
python scripts/studio.py assemble --plan PROJECT/plan-v001.json --out-dir PROJECT/render-v001 --render
python scripts/delivery_qa.py --video PROJECT/render-v001/preview.mp4 --plan PROJECT/plan-v001.json --out PROJECT/delivery-qa-v001.json
```

Watch the final file with sound and inspect timecoded defects against the brief. Metering, hashes and render success do not prove strong direction, speech clarity, continuity or factual accuracy. Export review and deliverable names appropriate to the current revision; the assembly helper's default filename is `preview.mp4` even when its contents are the final approved cut.

### 6a. Archive raw materials, renders and deliveries on the station

```powershell
python scripts/studio.py archive-doctor
python scripts/studio.py archive-push --project PROJECT            # add --dry-run to see the plan, --only assets,renders to restrict
python scripts/studio.py archive-status --project PROJECT --verify
```

Run after ingest, after each render or collected revision and after delivery. `push` uploads only new or changed files, verifies each by SHA-256 on the station and writes `PROJECT/archive/push-<utc>.json`; a mismatch is reported and not recorded. Nothing is deleted anywhere. `status --verify` re-hashes the archived files remotely and returns `fully_archived:true` only when every local file is on the station with a matching hash.

### 6b. Hand the cut to DaVinci Resolve Studio (optional finishing engine)

```powershell
python scripts/davinci_bridge.py doctor
python scripts/davinci_bridge.py export-xml --plan PROJECT/plan-v001.json --out-dir PROJECT/resolve/handoff-v001 --timeline-name "CUT_v001"
python scripts/davinci_bridge.py import --manifest PROJECT/resolve/handoff-v001/handoff-manifest.json --out PROJECT/resolve/handoff-v001/import-report.json
python scripts/delivery_qa.py --video PROJECT/renders/resolve-v001.mp4 --plan PROJECT/plan-v001.json --audio-qa PROJECT/audio-v001/qa.json --out PROJECT/delivery-qa-resolve-v001.json
```

`export-xml` validates the plan (same rules as `studio.py validate`), writes `sequence.xml` and a
hash-bound `handoff-manifest.json`, and lists every plan feature the XML cannot carry (`fade_in`,
`fade_out`, `motion`, `volume_keys`) with the Resolve technique to apply. `import` refuses the
never-saved default project, a timeline name that already exists and a changed `sequence.xml`; it
then checks each clip's track, start, duration, source in-point and media state and writes
`import-report.json`. Read [davinci-resolve.md](davinci-resolve.md) for the Hebrew rule, safety
rules and the Resolve domain skills.

For every rendered or generated shot, bind review evidence to the exact media bytes:

```powershell
python scripts/review_shot.py prepare --media PROJECT/renders/S04-v001.mp4 --shots PROJECT/planning/shots-v1.json --shot-id S04 --out-dir PROJECT/reviews/S04-v001
# Inspect review.html and the complete shot, then fill findings-template.json as findings.json.
python scripts/review_shot.py finalize --packet PROJECT/reviews/S04-v001/review-packet.json --findings PROJECT/reviews/S04-v001/findings.json --out PROJECT/reviews/S04-v001/review-report.json
```

`finalize` requires complete-motion review, one timecoded pass/fail/not-applicable result per acceptance criterion, and corrective actions for failures. A major issue or failed criterion derives `revise`; media with audio cannot derive `passed` until sound review is recorded. Any byte change invalidates the packet. The report contains no automatic aesthetic score.

## Local regression check

### Optional edit-boundary audit before delivery

Copy `templates/revision-contract.template.md` and `templates/edit-audit-v1.template.json` into the current production. Replace all illustrative paths/numbers with measured decisions; remove check arrays that do not apply. At least one check must remain. Paths resolve relative to the audit JSON. `target` is the exact final file, not a component preview.

```powershell
python scripts/edit_audit.py --spec PROJECT/revisions/edit-audit-v002.json --out PROJECT/reviews/edit-audit-v002.json
python scripts/delivery_qa.py --video PROJECT/delivery-copy-v002/viewing-sized.mp4 --plan PROJECT/copy-plan-v002.json --edit-audit PROJECT/reviews/edit-audit-v002.json --out PROJECT/reviews/copy-qa-v002.json
```

`clock_segments` are ordered non-overlapping zero-based `[timeline_start_frame,timeline_end_frame)` intervals for one declared source clock. `source_frames_per_frame` handles an explicit retime; `continues_previous:true` requires source/time adjacency. Export this mapping from the actual edit code and review it against the encoded frames; the helper does not parse Blender or infer motion.

`required_signals` measures the selected `in`/`duration` interval of each source; absent duration means through the decoded end. `min_peak` is a linear full-scale amplitude threshold (default zero). `audio_joins` measures both sides of `at` seconds with `window_ms` (default 10, maximum 1000); missing full windows fail. RMS transitions and sample steps yield review flags, never a claim of audible failure or success.

`pcm_preservation` compares canonical 48kHz stereo float PCM from `before` and `after`. Intervals use seconds, half-open `[start,end)`, rounded to sample frames. The frame count must match, all changed frames must be in `allowed_intervals`, and none may overlap `protected_intervals`. Use lossless stems/masters for exact checks; newly encoded AAC is not sample-identical. Empty allowed intervals require full PCM identity. Word intervals come from reviewed alignment; no automatic speech recognition runs here.

The report records target, contract and source hashes, errors and mandatory listening/motion review. With `--edit-audit`, delivery QA rejects a failed report, different target bytes, or changed/missing evidence sources, including a modified clock/repair contract. Existing callers without this option retain their previous behavior. Run an audit for each encoded target you need to bind; a master report cannot certify a different compressed file.

For audio mixing, SFX intervals are required to contain signal by default. `expect_signal:true` opts voice/music into the same check. A deliberately silent SFX uses `expect_signal:false` plus a concrete `silence_reason`; this exception is recorded in the source mix, not inferred from low volume. The test establishes signal presence, not musical or Foley quality.

`python -m unittest discover -s scripts -p 'test_*.py'` uses mocked provider transports and temporary local files. `verify_local.py --out-dir NEW_DIRECTORY --font LICENSED_FONT` explicitly runs FFmpeg, Chromium and Blender on synthetic calibration media. It verifies real edit identity, word timing, music attenuation and rendering of both templates. It consumes no provider credits and is not a creative portfolio film.
