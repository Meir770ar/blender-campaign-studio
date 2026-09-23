# Runtime contract: Claude Code and Codex

The same production workflow runs under either agent. Read this at activation, before choosing tools. Follow the current host's system instructions and permissions. Do not assume a tool exists because another host exposed it.

## One shared installation

Install the skill once (for example under `~/.codex/skills/blender-campaign-studio`) and expose it to the other host with a directory junction or symlink (for example `~/.claude/skills/blender-campaign-studio`). Edits through either path then update the same files, references, templates and scripts. Do not keep two independent copies.

Claude Code can invoke `/blender-campaign-studio`; the description also supports automatic selection for matching Hebrew requests when skill discovery is enabled. If a session does not list it, start a fresh session and check the personal installation and that session's skill visibility settings. Do not rewrite global settings or enable unrelated skills to fix discovery.

Resolve `references/`, `templates/`, `connections.json` and `scripts/` relative to the loaded SKILL.md, not the user's current working directory. Use absolute script and production paths when invoking from another directory. For example, this local help check neither creates a production nor calls a provider:

```powershell
python "<skill-root>/scripts/studio.py" --help
```

On a different machine locate the installed skill and prerequisites; the configured local clients, fonts, SSH identities and Blender are not portable merely because the Markdown is.

## Capability preflight

- Use the host's actual file-reading, editing and shell tools for local Python/Node/Blender work. Use supported browser tools only when exposed, following their own instructions. Tool names in older production evidence are not a runnable API contract for the new host.
- Ask interview questions in normal chat if a structured question tool is absent or disallowed. Do not require Codex-specific orchestration or spawn another agent merely to load this skill.
- Inspect `connections.json` as route metadata. Never print or copy provider credentials. Local CLI adapters can be invoked from either host if their dependencies and existing credential owners are accessible. MCP server names describe intended integrations, not proof that those servers are connected in this session.
- Magnific OAuth owned by Codex is not a Claude Code login. Use an already available, approved route documented in `magnific-dzine.md`, or report the missing connection; do not migrate tokens or silently switch accounts/providers. A host change does not permit a new paid submission or a retry.
- DaVinci Resolve Studio finishing runs on the VIDEO STATION (RTX A5000) by default, because renders are far faster there than on the laptop. Run `python scripts/davinci_bridge.py doctor --host station` before promising a Resolve step; it checks the station's Resolve over the `ai-station` SSH alias and the `davinci-resolve-station` MCP. Media must be mirrored to the station first (`studio.py archive-push`), and Resolve Studio must be open on the station desktop with a named, saved project (`davinci_bridge.py project --host station --create`). The bridge remaps the sequence.xml media paths to the station and imports/verifies over SSH; agentic finishing uses the `davinci-resolve-station` MCP so `run_script` drives the station. The laptop route (`--host laptop`, MCP `davinci-resolve-studio`) stays as an offline fallback; the community server is installed but off by default. See `davinci-resolve.md` for the hand-off contract and the per-domain Resolve skills to read on demand.
- Confirm actual full-speed motion viewing and audio listening capability before production. Without it, arrange the agreed human review and keep perceptual acceptance pending. Frame extraction and numerical audio analysis do not become listening when run under another agent.

## New stills remain Codex-only

This is the user's production policy, not a claim that Claude Code has a built-in image generator. In Codex, load the imagegen skill and invoke the exposed built-in image tool under its instructions. In Claude Code, reuse supplied/approved assets or prepare an image handoff in the current production containing the exact prompt, reference paths, output requirements, request/job identity and existing approval evidence. Ask the user to run the image step in Codex when no authorized bridge is actually available. Do not launch another agent automatically, substitute another image provider, or add an API-key fallback.

Do not call the image job's `execute` from Claude Code merely to discover the tool is missing: leave it prepared until the image-generating session can make the actual call. That session owns the single submission and receipt; register the returned asset against the same job. If it is already submitting/unknown, reconcile it before doing anything else. Continue independent planning/editing while images are pending; do not claim the dependent shot is complete.

## Continue across hosts without resetting state

Use the exact existing production directory and first run `studio.py production-status --project` with its absolute path. Read that production's brief, latest user feedback, artifacts and job/review ledgers only. Do not import another chat's transcripts, reset budgets, duplicate jobs, reissue uncertain submissions or promote rejected outputs. Confirm current-task authority before any external action; prior recorded approval is evidence to inspect, not blanket permission in a new task.

Installation, local CLI tests, provider connectivity, actual generation and creative acceptance are separate verification levels. State precisely which were checked.

Claude Code discovery reference: [official skills documentation](https://code.claude.com/docs/en/skills).
