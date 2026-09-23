# Genspark video fallback

Grok/OpenClaw remains the primary subscription route. The user selected the existing Genspark account as the backup when that quota is exhausted. Genspark can expose the same Grok Imagine Video model through its own credits; provider billing route and video model are different concepts. Images remain Codex-only, narration ElevenLabs, music Suno and editing Blender.

## Verify the usable route

Latest same-session verification: the installed CLI subsequently returned `credit_balance:10000`, `account credit` confirmed 10,000 usable personal credits, and model-info succeeded. The cause of the earlier zero/rejection is not established. The selected transport is now `existing_cli`; prefer it over browser automation. Do not permanently cache the earlier rejection.

For the CLI transport, prepare/approve the exact bound fallback as below, then `execute`. The adapter checks live CLI balance before submission, writes the attempt before calling the official installed CLI with a JSON args file, and preserves the full generated-video receipt before downloading. Use `collect-genspark --job JOB` to obtain the one returned URL via the account download command and register its hash. Timeouts are unknown and must not be resubmitted. `status` reads the stored job; it does not pretend an unsupported media poll endpoint exists. If the CLI returns a nonterminal task, reconcile that exact task/output through the returned UI URL rather than invoking video generation again.

Use `browser_existing_account` only when CLI access is currently unavailable and the website has verified usable quota. Changing transport for a prepared request requires a newly bound request and marking the old one superseded without submission; never change transport for an unknown attempt. The browser procedure below describes that secondary path.

`python scripts/provider_jobs.py probe genspark` reads the installed CLI's identity/credit response without displaying credentials or auto-updating the CLI. It does not generate media. A zero CLI balance is not proof the website has zero credits. On 2026-09-06 the same Plus account returned 0 from `login-info` and `Insufficient credits` from account/model-info calls, while the signed-in website account menu displayed 10,000 credits. The cause of this discrepancy is unverified. Do not copy cookies, use hidden browser APIs or retry a rejected CLI generation. Use native browser controls for the existing account when its website balance is verified.

Use the available CUA/browser tool, following its live documentation. Reuse the same production tab. Navigate from All Agents → AI Video, or the observed URL `https://www.genspark.ai/agents?type=video_generation_agent`. Read the signed-in account menu and remaining credits. Never infer usable quota from the subscription plan name. Keep screenshots/evidence in the production only when needed; never copy credentials into receipts.

## Bind the exact missing shot

1. Reconcile the original Grok job. Only `failed`, or `blocked` with explicit `submitted:false`, is eligible. `unknown`, `submitting`, pending work and any successful asset must be reconciled/reused first.
2. Prepare a request with `provider:genspark`, the original prompt/reference/settings and `fallback_for` pointing to that original `job.json`. The normalized identity binds parent ID and image bytes; moving files cannot create a new paid attempt.
3. Check the live UI model/settings/cost. Use the original model where available. Any consequential model/quality change needs a deliberate decision. Set one output, first-frame mode, exact duration/aspect/resolution, and disable auto-prompt rewriting. Preserve the original narration/music plan. If the model adds audio, exclude it in the final mix.
4. Record fresh website evidence with `browser-check --job JOB --credits NUMBER --evidence "Observed account/website balance and settings"`. This expires after 15 minutes. It records observed facts, not permission.
5. Record the current task's existing authorization with `approve`. Use actual credit estimates when the UI publishes them; otherwise explicitly state that price is unavailable and bind a small, concrete first-attempt count within the user's authorized scope. Never invent a credit price. Read remaining website credits before/after the first shot. Purchase/top-up and additional attempts are separate actions.
6. `execute --job JOB --estimated-usage NUMBER` reserves the one authorized attempt before the browser submission and emits the exact native browser workflow. It deliberately cannot submit UI actions from Python. Once reserved, never run `execute` again even if a response is missing.
7. In the browser, upload the exact first-frame image, verify the attachment and settings, paste the emitted prompt and click Generate once. Record the observed task URL immediately: `record-browser --job JOB --task-url URL --outcome submitted --receipt "Observed task/card ID and current status"`. Inspect only that task to poll completion. If the UI/transport becomes ambiguous use outcome `unknown`; don't create another request.
8. Download the completed task through its visible download control. Inspect real duration, dimensions, motion and image integrity; `register --job JOB --asset LOCAL_MP4 --receipt "Task URL and selected completed output"` records its hash and preserves the original. Never register a thumbnail, screenshot, error page or old result as generated footage.
9. Continue the standard analyze → motivated EDL → captions → sound/color → Blender → delivery QA → compressed WhatsApp self-delivery pipeline. A successful request or render is not full quality review.

The CLI accepts structured `--args-file` inputs and local image files, but its current credit rejection prevents claiming CLI generation is operational. Do not switch to an external paid API. If CLI usability is later restored, inspect the installed model schema, submission/status/download contract and test the authorized route before implementing a CLI transport.

## Quota renewal

Real production validation on 2026-09-06: six first-attempt 6-second 720p 9:16 Grok Imagine Video requests through Genspark completed successfully and were collected via official wrapper URLs. Website/CLI opening balance 10,000; after the first request 9,538; after six 7,228. The observed 462-credit per-request change is a point-in-time observation, not a quoted permanent tariff. The current model-info response did not publish a credit price. 53 automated contract tests passed; no generation was performed merely as a connection test.

Record renewal claims per production with source and date, not as a recurring scheduler or universal fixed interval. User reported on 2026-09-06 that Grok quota renews in three days: approximately 2026-09-09, exact time unverified. Re-probe/reconcile before returning to Grok. A renewal date does not authorize recreating already completed Genspark shots.

Installed primary references: `@genspark/cli/skills/gsk-video-generation/SKILL.md`, `gsk-shared/SKILL.md`, live `genspark video --help`, and the signed-in AI Video UI. Genspark's own tool schemas distinguish first-frame input from reference mode; do not substitute one for the other.
