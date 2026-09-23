# Production orchestration

## Project state

Use a user project folder, or a new folder under ~/Documents/video-productions/<project-slug>/. Never use an application install directory as the production directory. Initialize with studio.py init; resume existing projects by reading their files, not reinitializing.

Keep idea.txt, interview.json, production.json, brief.md, direction.md, storyboard.md, planning/, assets/, analysis/, typography/, jobs/, reviews/, deliveries/, renders/ and revisions/ per production. `studio.py init` creates this neutral scaffold and copies intentionally invalid direction/shot templates into `planning/`; copy or rename them and replace every `REPLACE:` field only when an actual decision exists. Initialization grants no provider, delivery or publication authority. Record approvals with scope and conversation evidence; do not manufacture them in a manifest. Update the project CLAUDE.md for significant pipeline decisions.

## Storage: laptop works, station keeps

The laptop holds the working copy of every production because Resolve and Blender need local media. The VIDEO STATION (`ai-station`, drive `D:/video-productions-archive`, about 1.3 TB free on 2026-09-20) is the durable store for raw materials, renders and deliveries. After ingesting raw material, after every collected or rendered revision and after delivery, run `python scripts/studio.py archive-push --project PROJECT` (or `station_archive.py push`). The push mirrors the production folder to `<root>/<slug>/`, verifies each file by SHA-256 on the station and records it in the station manifest; unchanged files are skipped by a local size+mtime hash cache. `archive-status --verify` shows what is not yet archived. Tooling never deletes on either side: freeing laptop space is a human decision taken only after `fully_archived:true`, and the archived copy remains the recovery source. Do not edit media over the tailnet; copy back locally first.

Use provider_jobs.py to maintain jobs/<semantic-hash>/job.json. Keep an optional production index linking shot_id to those jobs, cost/units when known and selected assets; the per-job receipt is authoritative. Hash generation-relevant inputs and reference bytes. Filename changes do not justify regeneration. Persist state around each submission. A timeout means unknown; inspect provider status before retrying. Preserve successful assets and recheck timing if narration changes.

## Work sequence

1. Read supplied brand/reference materials. Inspect actual footage and sound. Inventory metadata is not semantic understanding; sample frames and listen/transcribe to select content.
2. Define palette, contrast, typography, lighting, movement and sound. Maintain consistent references and product/character identity.
3. Produce script and shot list with sources (existing/generated/blender). Mark provisional timings. Encode the chosen direction and observable shot contracts using the templates, then run the appropriate `creative_gates.py` stage. Review styleframes before expensive moving shots. Creative readiness never substitutes for the cost authorization enforced by the provider job ledger.
4. Time the narration and test Hebrew names/acronyms on a short sample. Let real speech timing inform the cut and I2V durations.
5. Stills use the available Codex imagegen skill/tool. I2V uses the selected Grok subscription route and narration uses a supplied recording or ElevenLabs voice. Use the exact adapters and live checks in providers.md; another skill's description does not prove readiness. Do not silently substitute another billed provider.
6. Read the local musiclib skill when selecting music and check that collection first. Choose permitted material by mood and structure. Commissioned music needs a concrete cost approval. Use volume envelopes/ducking; check source clipping as well as the master.
7. Use the editorial, caption, audio and Blender shot tools in executable-workflow.md. Assemble a rough cut, then author required 3D and compositing per shot. These tools execute the agent's direction and edit plan; they do not infer artistic choices, track arbitrary footage or certify premium VFX automatically.

Read existing ai-video/auteur resources only for a needed capability. Do not invoke a full alternate pipeline that bypasses this interview, changes Blender or duplicates paid media. No credentials in code. No paid fallback or publication without authorization.

## Review and delivery

Styleframes: brand/product accuracy, font choice, Hebrew, hierarchy and composition.
Rough cut: watch with audio; check silent comprehension if relevant, evidence, cuts, breaths, captions and CTA.
Final: inspect transitions, flicker/warping, missing frames, color intent, sync and intelligibility. Prepare a timecoded packet with `review_shot.py`, watch complete motion and sound, and finalize explicit evidence for every acceptance criterion. ffprobe verifies duration/streams. FFmpeg ebur128/astats can measure audio; choose delivery-specific targets rather than one loudness target for every campaign.

QA report records timestamp/shot, issue, impact, fix and verification. Artistic review is distinct from technical checks. Automatic scoring does not certify commercial quality. Limit reviews to budget/deadline and retain unresolved issues honestly.

Render previews before finals. Keep .blend plus assets and text source specs. Reopen from the delivery location to test portability; VSE movie files are not automatically embedded in .blend. Copy only assets permitted for delivery into a new bundle; keep originals intact and remap copied project paths. Proprietary font files are not bundled by default; retain the reference for authorized regeneration. Re-layout requested aspects with safe-area checks. Finish the user's requested compressed self-delivery using whatsapp-delivery.md. Other sending/uploading/publishing requires separate explicit task authorization.
