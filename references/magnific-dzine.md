# Magnific and Dzine — controlled production connections

User routing update, 2026-09-06. These connectors supplement the existing production workflow; successful assets and approved shot contracts remain the starting point. Their availability does not justify replacing good media or paying for a connection test.

## Preferred route and model selection

1. `magnific`: official OAuth MCP, preferred connection for an appropriate advanced video/processing task. Inspect the live model catalog and settings, choose against the scene's action, identity/reference needs, duration, aspect, resolution and audio requirements. Do not assume that the most expensive model is always the best match.
2. `magnific-rest`: existing official API client when direct endpoint control is needed. It shares the plan credit pool; it is not a free fallback or separate retry allowance.
3. `dzine`: existing Creator website account through the installed session-HTTP connector. Use only an occasional, individually controlled request when its model fits the scene. No batch, parallel generation, continuous processing or automatic retries. The official Dzine API uses a separate paid wallet and must not silently replace this subscription route.

New still-image generation remains Codex-only. Do not use Magnific/Dzine image generation or character-sheet generation without a new explicit user instruction. If Magnific's video planner suggests generated still references, create/reuse those through Codex instead. Existing-image processing, including Upscale/Transform/Retouch/Expand, is a credit-consuming production decision, never a smoke test or a way to bypass the still-image rule.

## Read before spending

- Magnific: `account_balance`; creation search/history and status as needed for this production. `unlimitedAppliesHere` is the session signal; website Unlimited entitlement does not make external MCP generation free. For this installed session it is false.
- Before Magnific `video_generate`, use `video_plan`, validate its model against `video_models_list`, and obtain a concrete `simulate_cost` for the exact target tool and arguments. Planning recommendations cannot override the user's Codex-only still rule or existing budget/approval.
- Dzine: `dzine_status`; `dzine_projects` only when needed to identify the relevant existing work. Do not enumerate unrelated projects/history.
- Never call Generate, Video, Upscale or Transform to test connectivity. A read-only connection check is distinct from successful generation or artistic quality.

## Concrete authorization and one-attempt record

The registered MCP tools are called directly by the agent. `provider_jobs.py` currently implements the older providers; do not pass an unsupported provider to it or claim that it automatically guards these new MCP calls.

Before a paid call, save a per-operation JSON record under the production's `external-jobs/` containing:

- provider/transport, target tool or endpoint, exact model/settings and scene purpose;
- normalized request, prompt and source-file content hashes, with no credentials;
- cost quote and unit, live balance before, approved cap and actual current-task authorization evidence;
- state `prepared`, then `submitting` and an attempt timestamp **before** the network call, with maximum submissions 1.

Check existing records for the same semantic inputs before submission. Save the complete non-secret provider receipt and task/creation identifiers immediately, then query the original task until a terminal state. Register the exact downloaded output with a hash. For Magnific, use the appropriate creation show/wait/get flow and an actual asset identifier/URL for chained media, never a human-facing webUrl as an input file.

On failure or UNKNOWN, reconcile the original task and diagnose before any new paid attempt. Never change transport, model or a cosmetic prompt field to escape the attempt guard. A paid retry requires new approval. Read-only polling of the existing task is not a generation retry; keep polling bounded and continue other useful work between checks.

After every paid operation, record and report the tool, model, created/processed asset and balance before/after. If other account activity makes the balance delta ambiguous, report that limitation instead of attributing all usage to this one task.

## Existing tools and CLIs

MCP names: `magnific`, `magnific-rest`, `dzine`. Reuse the user's installed credentials; never ask for or print keys/cookies/tokens, copy them into this skill, or read the profile files for routine work.

```powershell
# Read-only official API access
node <magnific-cli>/magnific.mjs get --path /v1/resources?limit=1
# Authorized concrete write only; do not run as a test
node <magnific-cli>/magnific.mjs request --method POST --path /v1/... --json-file request.json --confirm-write --confirm-credit-use
node <magnific-cli>/magnific.mjs wait --path /v1/ai/<service>/<task-id>

node <dzine-cli>/dzine.mjs status
node <dzine-cli>/dzine.mjs projects
# One authorized request using a currently verified endpoint/payload only
node <dzine-cli>/dzine.mjs request --host proxy --path /api/v1/... --method POST --json-file request.json --confirm-write --confirm-credit-use --acknowledge-unsupported-api
```

The endpoint placeholders above are documentation, not runnable generation recipes. Resolve the exact supported endpoint and schema before authoring a request. Every Magnific write requires confirm-write; AI calls also require confirm-credit-use. Every Dzine write requires all three confirmations. Flags record intent at the transport layer; they do not create user authorization.

Dzine's session route is unofficial and may break or conflict with its service restrictions; follow the user's explicit low-volume limits. Do not repair authentication by exposing tokens. If the registered tools are missing in a future session, preserve the production checkpoint and tell the user to refresh/reopen Codex; do not abandon local editing that can continue without them.

## Verification, 2026-09-06

All three registered MCP connections were visible in the live session. Read-only calls confirmed Magnific Premium, available 115,514, unlimitedAppliesHere false; Dzine Creator, total/subscription 24,000, no top-up credits; Magnific REST GET /v1/resources?limit=1 returned HTTP 200. These are dated observations, not fixed balances. No generation, upscale or transformation was performed for verification.
