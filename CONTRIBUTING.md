# Contributing

Thank you for helping. This project is a production tool, so the bar is: a change ships with its test, its documentation and no new way to spend money or send a message without an explicit approval.

## Set up

```powershell
pip install -r requirements.txt ruff
playwright install chromium          # only needed for the typography renderer
Copy-Item connections.example.json connections.json
python scripts/studio.py doctor
```

FFmpeg (full build) and Node.js 20+ must be on PATH. Blender 5.1.0 is needed only for the assembly and technique scripts, not for the unit suite.

## Run the checks

```powershell
python -m unittest discover -s scripts -p "test_*.py"
node --test scripts/test_grok_activation.mjs scripts/test_grok_native.mjs
ruff check scripts
```

All three run in CI on every push and pull request.

## Rules of the codebase

- **No provider call in a test.** Transports are mocked; media is synthesized with FFmpeg. A test that needs a subscription is not a unit test.
- **No secrets, ever.** `connections.json` is git-ignored and holds locations only. Credentials stay with the clients that own them (ElevenLabs env file, Suno cookie, HeyGen profile, OpenClaw auth store). Never print or copy them, never add an API-key fallback for a subscription route.
- **Ledgers are append-only evidence.** Jobs, approvals, batches, reviews and deliveries are JSON files written once; a changed request is a new job. Do not add code that resubmits an `unknown` attempt.
- **Hebrew is rendered, not typed.** Text layers come from `render_text.py` / `captions.py` (Chromium, licensed font, logical order). Do not introduce a path that types Hebrew into Resolve Text+ or Blender text objects.
- **Contracts fail loudly.** Every JSON contract is validated with explicit `ValueError` messages that say what to change. Placeholders (`REPLACE:`) must fail the gates.
- **Documentation is part of the change.** A new field, command or route is documented in the matching file under `references/` (and in `SKILL.md` when the agent needs to know it exists), with the verification level stated honestly: contract test, local integration, live provider, creative acceptance.

## Adding a provider or route

1. Add the request contract and validation in `scripts/provider_jobs.py` (or a dedicated `*_contract.py` / `*_bridge.py` module).
2. Add the route metadata to `connections.example.json` without values that identify you.
3. Add tests with a mocked transport covering: semantic identity, approval before execute, `unknown` never retried, collection QA.
4. Document the route in `references/providers.md`, including limits you verified and the date.

## Pull requests

- One topic per PR, with the test that proves it.
- Keep the existing line endings and formatting; do not reformat files you did not change.
- Describe what was verified and at which level (see `references/verification.md` for the wording used).
- Do not commit production folders, renders, media or ledgers.
