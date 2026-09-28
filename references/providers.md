# Provider execution contract

Use `scripts/provider_jobs.py`; connection locations and model choices are in `connections.json`, with no secrets. Read-only `probe PROVIDER` is permitted while setting up a production. A config entry is not a successful generation. Every actual generation uses a concrete reviewed request and current-task approval for cost/quota, including subscription attempts. Reuse existing authorization; do not ask again when it already covers the exact planned work.

## Routes

Before using these routes under either host, apply [agent-runtime.md](agent-runtime.md). Claude Code can orchestrate the local adapters, but it does not inherit Codex conversation tools or OAuth. For new stills it prepares a handoff to Codex and must not mark a job submitted before a generating session is ready. Preserve the same job and approval ledger across hosts.

| Need | Selected route | Important execution detail |
|---|---|---|
| Images | Codex built-in `image_gen.imagegen` | Load the imagegen skill. Invoke the actual tool from the agent; the local script emits arguments and records the result but cannot invoke a Codex conversation tool itself. No OpenAI API-key fallback. |
| Video | Existing Grok/OpenClaw subscription configuration | Native SDK/OAuth `video_generate`, explicit model/mode, isolated session and idempotency key. Model 1.5 supports 1080p text/single-first-frame, up to seven references plus first/last frame at 720p, and dedicated edit/extend routes. Requires the verified native expansion; see [avatar-and-ai-production.md](avatar-and-ai-production.md). No browser generation or API-key substitution. |
| Speaking character | Existing HeyGen website subscription CLI | Avatar IV/V, photo/video avatar creation, motion direction, local versioned character library and authoritative CLI receipts. `probe heygen`, prepare/approve/execute/status, then `collect-heygen` for rendered videos. Real Digital Twins require personal consent verification. |
| Video (Genspark) | Existing Genspark website account + `@genspark/cli` | Primary route since 2026-09-23 when the native Grok gateway is unavailable: `{"provider":"genspark","prompt":...,"duration_seconds":5,"aspect_ratio":"16:9","resolution":"1080P"}` is text-to-video (Grok Imagine 1.5 on Genspark credits; 1080P is text-to-video only, one first frame keeps 720P). The CLI is synchronous and returns the task receipt; `collect-genspark` downloads the one returned URL. Measured 2026-09-23: 5 s 16:9 text-to-video at 1080P cost about 610 credits, at 720P about 460. As a Grok fallback (`fallback_for`) it keeps the original contract: see [genspark-fallback.md](genspark-fallback.md). A CLI call interrupted mid-transport leaves the job `submitting`/`unknown`: reconcile through the website's video history before any new attempt; the CLI has no task listing for videos. |
| fal.ai staged alternatives | Queue API, fixed starter models: FLUX.1 schnell image, Wan 2.2 A14B text-to-video, MiniMax Speech-02 HD, ACE-Step prompt-to-audio | `provider: fal`, `stage: image|video|voice|music`. Each POST is a `provider_jobs.py` approved single-attempt job. Submit, poll existing task ID, save result JSON. Uses `FAL_KEY` from environment, not a credential in the config or job. No reference-image upload in this first pass. |
| Kie.ai staged alternatives | Market createTask: Seedream v4 text-to-image, Kling 2.6 text-to-video, ElevenLabs multilingual v2 TTS; Suno V5 for instrumental music | `provider: kie`, same stages. Uses `KIE_API_KEY` from environment. Suno needs an HTTPS callback URL even for later polling. No unapproved automatic retries. |
| Original music | Existing `<suno-cli>` client | Reuses its own login. Requires a successful explicit CAPTCHA-not-required response. Does not solve CAPTCHA, warm sessions or retry a generation. Downloads are registered after using an account-approved download route. |
| Narration | Existing ElevenLabs key and professional Hebrew voice | Voice `<voice-id>`, model `eleven_v3`, timing endpoint. Saves original audio and alignment before timing checks. Never regenerate good speech just to repair captions. |
| Advanced video/processing | Official Magnific OAuth MCP (`magnific`) | Agent-orchestrated. Read balance/history first; use `video_plan` + model validation + `simulate_cost`, then one approved paid submission. |
| Direct Magnific API control | Installed official REST client (`magnific-rest`) | Agent-orchestrated. Exact `/v1/...` schema; writes require transport confirmations and current-task cost approval. |
| Isolated Dzine request | Installed Creator session connector (`dzine`) | Agent-orchestrated and unofficial. Single low-volume request only; no batch, parallelism, continuous processing or automatic retry. |
| Script writing + semantic video analysis | Existing Antigravity / Google AI Pro subscription | Orchestrated by `scripts/antigravity.py` (not provider_jobs.py): `script` turns brief.md into a story-first script that feeds the storyboard; `analyze --kind shot\|master` returns advisory JSON with professional fixes and per-tool editing guidance (`edit_blender`, `edit_davinci`). Gemini 3.5 Flash via `agy-cloudcode.mjs`, OAuth no key, consumes subscription quota; explicit one-shot, never a loop. Analysis is advisory, never creative acceptance. See `connections.json` `antigravity`. |

For music, check musiclib to understand available material, but honor a request for original Suno music. Do not substitute stock music to bypass a connection issue without explaining the choice.

## fal/Kie first-pass workflow

Copy the fal/Kie entries in `connections.example.json` into local `connections.json`; set the named key in the environment. The model names in those entries are documented starter contracts, not arbitrary drop-in model names: changing a model's request schema requires code and tests. Example request: `{"provider":"fal","stage":"image","prompt":"Product on a clean neutral desk"}`. For video, add `duration_seconds` and `aspect_ratio`; for voice use `text` and a configured `voice_id`; for music use `prompt` and optional `instrumental` (Kie requires `title` and supports only instrumental in this route, using custom mode). `probe fal|kie` reports configured stages, not live access or a balance. Use the usual `prepare`, `approve`, `execute --estimated-usage` and `status` flow; for a completed task, `collect-aggregator --job JOB` saves the remote result as `aggregator-result.json` and marks `ready_to_download`. Inspect and download the returned media with an account-approved, safe URL workflow, verify the media, then fit it into the production. This first pass does not auto-download, transcribe, force-align or render media; `ready_to_download` is not a finished asset.

For voice, the downstream `narration_plan.py` / captions pipeline expects ElevenLabs `words.json` with word timings. These two alternative TTS routes return audio without that verified timing contract and cannot be substituted into subtitle assembly until a local forced-alignment step is supplied and reviewed. This is deliberate rather than inventing timestamps. fal Wan uses 16 FPS and `num_frames = duration_seconds * 16 + 1`, not a `duration` string; this request is a frame-count target, not a guarantee of final duration after interpolation. Kie Suno V5 uses `customMode:true`, with `prompt` as `style` and a required `title`; non-custom mode does not honor the instrumental setting. No image-to-video input upload, Kie Suno extension, arbitrary model schema, or migration of existing Antigravity/Magnific/Dzine routes is included. The estimate in the ledger is a cap on attempts/estimated usage, not a live provider price guarantee: verify current prices and available balance manually before approval. `probe` only checks local configuration and `execute` checks the key is present, not its balance or current price. The 45-second HTTP submission timeout or a missing task ID may mean the provider accepted and charged a task while the local job is `unknown`; reconcile the account's task history before any new submission. Result URLs may expire, and collection only saves JSON, not downloaded/verified media.

API references: [fal queue](https://fal.ai/docs/documentation/model-apis/inference/queue), [fal FLUX](https://fal.ai/models/fal-ai/flux/schnell/api), [fal Wan](https://fal.ai/models/fal-ai/wan/v2.2-a14b/text-to-video/api), [fal MiniMax](https://fal.ai/models/fal-ai/minimax/speech-02-hd/api), [fal ACE-Step](https://fal.ai/models/fal-ai/ace-step/prompt-to-audio/api), [Kie Seedream](https://docs.kie.ai/market/seedream/seedream-v4-text-to-image), [Kie Kling](https://docs.kie.ai/market/kling/text-to-video), [Kie TTS](https://docs.kie.ai/market/elevenlabs/text-to-speech-multilingual-v2), [Kie Suno](https://docs.kie.ai/suno-api/generate-music), [Kie task details](https://docs.kie.ai/market/common/get-task-detail).

## Additional preferred and controlled connections

The user's newer routing update adds official Magnific OAuth MCP as the preferred fitting connection, `magnific-rest` for direct official API control, and the Creator-session Dzine connector for isolated requests only. Read [magnific-dzine.md](magnific-dzine.md) for exact routes, live preflight, model/cost planning, still-image restrictions and the one-attempt record. These agent-orchestrated MCP paths do not use `provider_jobs.py`; keep its supported-provider lifecycle below separate. Never regenerate an existing successful shot simply because a new model is available.

## Concrete request files

Paths in these examples are project inputs, not files provided by the skill. Write actual prompts from the approved direction and shot contract.

```json
{"provider":"images","prompt":"Full approved image direction","references":["assets/product-reference.png"]}
```
```json
{"provider":"grok","prompt":"Approved visible action, camera movement and continuity constraints","references":["assets/shot-01-first-frame.png"],"duration_seconds":6,"aspect_ratio":"16:9","resolution":"720P","audio":false,"avoid":["heavy shadows","saturated neon colors","text baked into the image"]}
```

`style_constraints` (1-12 positive rules, from `direction.visual_system.style_constraints`) and `avoid` (at most 3, from
`visual_system.exclusions`) apply to images, grok and genspark. None of these models has a negative-prompt parameter and a
long "do not show" clause primes them toward what it names, so the rules are folded into the prompt at prepare time as
"Style constraints: ..." plus a short "Avoid: ..."; the folded prompt is what the job identity and any fallback compare.
Keep the same lists on every shot of a series, and run `antigravity.py check --request` on each collected shot.

Suno extension: `{"provider":"suno","style":"builds into uplifting strings","instrumental":true,"extend_clip_id":"<clip id>","extend_at_seconds":45}`
continues an existing clip from that second with a new style, inheriting key and tempo (the client's `continue_clip_id` /
`continue_at` / `task:extend`); both fields are required together. This is the route for a planned change of musical
character (tense to uplifting at 0:45) instead of gluing two unrelated tracks.
```json
{"provider":"suno","style":"Instrumental chamber strings and restrained warm piano; sparse arrangement leaves room for narration; gentle opening, purposeful lift, resolved ending","instrumental":true,"title":"Campaign music","lyrics":""}
```
```json
{"provider":"elevenlabs","text":"הטקסט המדויק שאושר לקריינות.","stability":0.5,"similarity_boost":0.75,"style":0,"speed":1}
```

Keep spoken text separate from visual numeric/brand formatting. Audition a short, representative passage within the approved budget, listen, then synthesize coherent paragraphs. v3 delivery tags require judgment; no indiscriminate fillers or SSML breaks. The voice is a starting point; preserve another voice if the user selected one. Directed pauses are silence placed between separately rendered segments: `narration_plan.py split` writes one request per segment from a `narration-v1` script and `layout` places the rendered takes with their `pause_after` on the mix clock (see [executable-workflow.md](executable-workflow.md) §4). A segment that needs a retake is regenerated alone.

## Lifecycle

1. `python scripts/provider_jobs.py prepare --request PROJECT/request.json --jobs PROJECT/jobs`
2. Read the normalized `job.json`, estimated provider usage and known account limits. The semantic identity includes model/settings, prompt and reference image bytes; moving a reference does not create permission for another attempt.
3. Once the user has authorized this request in the current task, record that actual approval: `approve --job JOB --evidence "Exact current-task approval context" --limit NUMBER --unit "credits / characters / subscription attempts"`. This records evidence; it does not create user authorization. Suno may return two music variants per request: quote the actual batch cost. Never invent an estimate when account usage is unknown.
3b. For a series (shots of one campaign, narration segments), `approve-batch --jobs JOBS --job ID --job ID ... --evidence "..." --limit TOTAL --unit UNIT [--per-job N] [--pilot N]` records one approval on every listed prepared job of the same provider under a shared cap. `execute` refuses a job whose estimate would push the batch's running total past the cap, without submitting; with `--pilot N` it also refuses any job beyond the first N listed until `batch-release --jobs JOBS --batch ID --evidence "what the pilot review found"` is recorded after those N were attempted. `batch-status` lists states, pilot/release and the remaining estimate. It replaces 35 separate approvals, not the review of 35 results.
4. `execute --job JOB --estimated-usage NUMBER`. The estimate must use the same unit and fit the approved cap. The script enforces one submitted request; the provider's final billing is not controlled by a local estimate. Track the total across jobs in the production budget before each attempt. An approval for one job is not an approval for a whole campaign.
5. Images: inspect local references first, call the emitted `image_gen.imagegen` arguments once, then `register --job JOB --asset PATH --receipt "tool result / selected output"`. Persist the tool result if execution is interrupted. Never rerun to repair bookkeeping.
6. Grok/Suno: `status --job JOB` checks the existing work. Grok `collect-grok --job JOB` collects only returned/verified media paths. Suno: review completed clip IDs and obtain the selected music through the user's approved download route, then `register`. Keep additional unselected variants in the receipt; do not pay to recreate them.
7. ElevenLabs saves `narration.mp3`, `alignment.json`, `words.json`. If timing validation fails, use preserved audio with local transcription/forced timing repair. No new synthesis is needed for that repair.
8. HeyGen: prepare typed CLI options and input-file hashes; the CLI preview fingerprint binds the workspace and exact request. Execute uses the existing CLI ledger and reads its receipt back. `status` reconciles that receipt even if the orchestration process lost its response. `collect-heygen` downloads an existing rendered video. Character/audio/workflow creation returns its actual identifier for the next step.

`received_needs_review` preserves downloaded media that failed the requested dimensions, duration, shape or audio check; it blocks delivery. It is not a retry signal. Technical collection passes leave creative review pending.

`unknown` and `submitting` are reconciliation states, never retry signals. Inspect the exact provider receipt/session/account for the original job. An inactive Grok status does not prove failure. A Suno preflight result explicitly reporting `submitted:false` can resume after login/CAPTCHA is resolved; this is distinct from repeating a submitted request. Preserve lock files after a crashed process until checking that process; do not automatically delete a lock held by another task.

## Current installation evidence (2026-09-06)

This historical section describes the earlier setup. For the 2026-09-09 expansion, use [avatar-and-ai-production.md](avatar-and-ai-production.md), the verification package and fresh probes. The native patch is not active merely because it is prepared locally. `connection_verified` reports OAuth/context/tool readiness; `native_expansion_active` and `ready_to_submit` also require the current SDK contract/capabilities. No new provider generation was used to test the expansion.

- Codex's built-in image tool is exposed in the current session. No image quota was spent on connection testing.
- ElevenLabs read-only voice lookup succeeds. Subscription balance lookup was denied by the key's scope; do not report the key as invalid or claim known remaining credits. Speech generation has not been tested in this setup task.
- Suno login was initially missing and is now available in the existing client's `_profile/cookie.txt`. A fresh read-only probe returned HTTP 200, authenticated, with 9,755 credits at verification time. The user identified Infisical `SUNO_CLIENT_COOKIE` as the source of truth and the local file as its copy. Reuse the existing client without duplicating this secret into the skill. Credit balance can change; probe again before budgeting. Premier tier/session expiry were supplied by the user, not independently verified by this balance probe. No music generation was performed.
- Grok gateway responds and the selected `lastGood.xai` profile is OAuth with a refresh credential. The native resolver's agent directory matches the requested `meir` agent. The corrected live probe returns `ready_to_submit:true`; xai's API-key discovery still reports `configured:false`, which is not an OAuth failure. The user independently confirmed successful video generation with automatic refresh today. This setup task verified the code path and non-generating probe; it did not generate another video to repeat that evidence.

## Grok OAuth and agent context

The main `/home/node/.openclaw/auth-profiles.json` store owns the credential. Read metadata only for preflight: select `lastGood.xai`, recognize `type:oauth`, and allow an expired/expiring access token when refresh is available. Never copy access/refresh values into local connection JSON, job receipts or stdout. `ready_to_submit` means the route/profile/tool checks passed; it does not estimate remaining subscription quota or guarantee a future provider request.

Keep the existing native generation route. Installed xai `generateVideo` calls `resolveApiKeyForProvider`, which fills a nonempty `agentDir` from `resolveDefaultAgentDir(cfg)` when the gateway did not pass one. It then calls `resolveApiKeyForProfile` and `resolveOAuthAccess`: adopt the newer main credential, apply the 300-second refresh margin, refresh under lock if necessary, write back through the native store, and return the bearer credential. The campaign adapter verifies that the requested agent's native directory equals that default resolver directory and keeps `agentId` plus an isolated matching session key in the gateway request. A different agent context must be handled explicitly rather than silently borrowing another workspace's auth.

Do not gate OAuth on `isProviderApiKeyConfigured` or the list action's `configured` field. In this installed xai video provider, discovery calls that helper without a `profileTypes` restriction; the missing `agentDir` already makes it return false. Other call sites can additionally filter credential types. Neither replaces actual OAuth resolution. The adapter still blocks missing/unrefreshable credentials, a mismatched agent context, a missing tool/provider, an API-key route or a configured paid fallback.

Source inspection on the installed OpenClaw 2026.7.1 confirmed this chain in `extensions/xai/video-generation-provider.ts`, `dist/model-auth-*.js`, `dist/oauth-*.js`, `dist/credential-state-*.js` and the gateway tool-construction modules. No remote runtime/config or credential store was edited for this correction; refresh implementation remains owned by OpenClaw.

These are installation checks, not timeless capabilities. Run probes again in a later production. The Suno client uses an internal account API rather than an official public integration. Consult current provider documentation/terms when the chosen download/usage path matters; do not promise commercial rights merely because a CDN file can be fetched.

Primary technical references: [ElevenLabs timestamps](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps), [ElevenLabs delivery guidance](https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices), [Suno terms](https://suno.com/terms-of-service). OpenClaw implementation and CLI were inspected locally on the installed 2026.7.1 gateway; do not assume another release has the same schema.
