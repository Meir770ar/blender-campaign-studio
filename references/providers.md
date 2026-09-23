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
| Original music | Existing `<suno-cli>` client | Reuses its own login. Requires a successful explicit CAPTCHA-not-required response. Does not solve CAPTCHA, warm sessions or retry a generation. Downloads are registered after using an account-approved download route. |
| Narration | Existing ElevenLabs key and professional Hebrew voice | Voice `<voice-id>`, model `eleven_v3`, timing endpoint. Saves original audio and alignment before timing checks. Never regenerate good speech just to repair captions. |
| Advanced video/processing | Official Magnific OAuth MCP (`magnific`) | Agent-orchestrated. Read balance/history first; use `video_plan` + model validation + `simulate_cost`, then one approved paid submission. |
| Direct Magnific API control | Installed official REST client (`magnific-rest`) | Agent-orchestrated. Exact `/v1/...` schema; writes require transport confirmations and current-task cost approval. |
| Isolated Dzine request | Installed Creator session connector (`dzine`) | Agent-orchestrated and unofficial. Single low-volume request only; no batch, parallelism, continuous processing or automatic retry. |
| Script writing + semantic video analysis | Existing Antigravity / Google AI Pro subscription | Orchestrated by `scripts/antigravity.py` (not provider_jobs.py): `script` turns brief.md into a story-first script that feeds the storyboard; `analyze --kind shot\|master` returns advisory JSON with professional fixes and per-tool editing guidance (`edit_blender`, `edit_davinci`). Gemini 3.5 Flash via `agy-cloudcode.mjs`, OAuth no key, consumes subscription quota; explicit one-shot, never a loop. Analysis is advisory, never creative acceptance. See `connections.json` `antigravity`. |

For music, check musiclib to understand available material, but honor a request for original Suno music. Do not substitute stock music to bypass a connection issue without explaining the choice.

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
