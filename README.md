# Blender Campaign Studio

[![tests](https://github.com/Meir770ar/blender-campaign-studio/actions/workflows/tests.yml/badge.svg)](https://github.com/Meir770ar/blender-campaign-studio/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An agent skill for **Claude Code** and **Codex CLI** that directs, produces and edits Hebrew commercials, brand films and campaign videos end to end: adaptive interview and brief, direction and per-shot contracts, generated shots, narration with directed pauses, music and sound design, right-to-left Hebrew typography, assembly in **Blender 5.1**, finishing in **DaVinci Resolve Studio**, technical QA and delivery.

The skill is opinionated about one thing above all: every paid generation needs an explicit approval recorded in a ledger, nothing retries on its own, and every shot is watched and listened to by a human before it is called done.

## Status

Used daily by the author on Windows 11 for real productions. The unit suite (Python and Node) runs in CI on Windows. External services (video and voice generators, subscription CLIs) change without notice: run the `probe` commands before every production and treat the documented capabilities as the state at the last verification date in `references/verification.md`.

## Features

- **Direction as data.** Brief, direction and shot contracts in JSON (`templates/`) checked by `creative_gates.py` at each stage: direction, styleframes, paid motion, rough cut.
- **Narration.** ElevenLabs v3 with word timestamps; a script written as segments with `pause_after`, rendered as one request and cut by word timestamps (`narration_plan.py`); Hebrew captions with brand-colored words (`captions.py`).
- **Sound.** Suno music (including clip extension for a planned change of character), a licensed library, per-track gain envelopes, speech-driven ducking and two-pass loudness (`audio_finish.py`), Foley event contracts and edit audits.
- **Shots.** Grok Imagine Video 1.5 through an OpenClaw gateway, Genspark, Magnific and Dzine, HeyGen avatars with a versioned character library; still images through Codex. One ledger per job: prepare, approve, execute once, collect (`provider_jobs.py`), with batch approvals, a shared cap and a pilot.
- **Assembly.** Timeline JSON v1 to the Blender VSE: motion presets, transform keyframes, image sequences with alpha, freeze frames, Hebrew PNG typography (`studio.py`, `sequence_tools.py`, `render_text.py`).
- **3D and compositing.** Product stages, camera projection, planar screen replacement, a controlled product reveal (`shot_templates.py`, `campaign_techniques.py`, `premium_product.py`), remote Cycles rendering on a GPU station.
- **Finishing.** FCP7 XML hand-off with verified import into DaVinci Resolve Studio (`davinci_bridge.py`), Tesseract kinetic Hebrew titles, semantic shot and master analysis plus closed-question vision checks through Gemini (`antigravity.py`).
- **QA and delivery.** Encoded-file checks bound to the mix loudness targets (`delivery_qa.py`), compressed viewing copies, optional WhatsApp self-delivery with a receipt ledger.

`references/long-form-commercial.md` is a complete recipe for a 150-second commercial with 30-45 generated shots.

## Requirements

**Machine.** Windows 11, a modern CPU (AVX2), an NVIDIA GPU with 12 GB VRAM or more, 32 GB RAM, a fast SSD.

**Software.** Python 3.11+ with `playwright` (then `playwright install chromium`) and `fontTools`; Node.js 20+; FFmpeg (full build) on PATH; Blender 5.1.0 exactly; DaVinci Resolve Studio 21.1 with its official MCP server (and the community MCP for the compound workflows); Tesseract (`tsrct`) for kinetic Hebrew titles; a local Whisper / ivrit.ai stack for transcribing footage with speech; one licensed Hebrew font (the skill refuses to substitute a free font).

**Accounts.** Claude (Claude Code) and/or ChatGPT (Codex CLI, also used for stills); one video generator (Magnific, Genspark, or Grok through an OpenClaw gateway); ElevenLabs; Suno; HeyGen; Google AI Pro (Antigravity: script, analysis and vision check); Magnific; a licensed music/SFX library.

**Not required.** WAHA (automatic WhatsApp self-delivery; send the file by hand instead), Dzine, Genspark as a second video route, and the OpenClaw gateway unless you want the direct Grok route.

**Not included.** The user-side clients this skill drives: `suno-cli`, `heygen-cli`, `@genspark/cli`, `agy-cloudcode.mjs`, the Magnific and Dzine clients, and the OpenClaw runtime. Point `connections.json` at your own installations.

## Installation

```powershell
git clone https://github.com/Meir770ar/blender-campaign-studio.git "$env:USERPROFILE\.codex\skills\blender-campaign-studio"
# expose the same folder to Claude Code (junction, not a copy)
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\blender-campaign-studio" -Target "$env:USERPROFILE\.codex\skills\blender-campaign-studio"
cd "$env:USERPROFILE\.codex\skills\blender-campaign-studio"
pip install -r requirements.txt
playwright install chromium
Copy-Item connections.example.json connections.json   # then edit paths, hosts and ids
python scripts/studio.py doctor
```

`connections.json` is git-ignored. It holds locations and model choices, never secrets; credentials stay with the clients that own them.

## Quick start

```powershell
python scripts/studio.py init --project <productions>/my-film --idea "the idea in the user's words"
python scripts/creative_gates.py --direction <productions>/my-film/planning/direction-v1.json --stage direction --out <productions>/my-film/planning/direction-gate-v001.json
python scripts/studio.py validate --plan <productions>/my-film/plan-v001.json
python scripts/studio.py assemble --plan <productions>/my-film/plan-v001.json --out-dir <productions>/my-film/render-v001 --render
python scripts/delivery_qa.py --video <productions>/my-film/render-v001/preview.mp4 --plan <productions>/my-film/plan-v001.json --out <productions>/my-film/delivery-qa-v001.json
```

In Claude Code or Codex, a Hebrew request such as "בוא נכין סרטון לעסק שלי" activates the skill; `SKILL.md` carries the production doctrine the agent follows.

## Repository layout

| Path | Contents |
|---|---|
| `SKILL.md` | The skill entry point (Hebrew): doctrine, workflow, which reference to read when |
| `references/` | Contracts and guides: providers, editorial, sound, Hebrew typography, Resolve, render station, verification records |
| `scripts/` | The executable pipeline (Python 3.11, a few Node bridges) and its unit tests (`test_*.py`, `test_*.mjs`) |
| `templates/` | JSON contracts to copy into a production: direction, shots, narration, mix, character sheet, techniques |
| `agents/` | Codex interface metadata |
| `connections.example.json` | Every route the skill can use, with placeholders |
| `_verification/20260909-provider-expansion/` | The OpenClaw xAI video-provider patch package (before/after) that `activate_grok_patch.py` applies; see `THIRD_PARTY_NOTICES.md` |

## Testing

```powershell
python -m unittest discover -s scripts -p "test_*.py"
node --test scripts/test_grok_activation.mjs scripts/test_grok_native.mjs
ruff check scripts
```

The unit suite needs FFmpeg on PATH and Node; it never calls a provider, never renders in Blender and never sends a message. `scripts/verify_local.py` runs the real FFmpeg, Chromium and Blender paths on synthetic media when you want an end-to-end local check.

## Safety model

- A provider job is prepared, approved with recorded evidence and a cap, executed once, then collected. `unknown` is reconciled, never retried.
- Batch approvals carry a shared cap and an optional pilot that holds the remaining jobs until a review is recorded.
- Style rules travel as positive constraints with at most three exclusions, folded into every prompt of a series; a vision check asks closed questions about each collected shot.
- Hebrew text is rendered to PNG by Chromium with a licensed font; it is never typed into Resolve Text+.
- Rendered frames, meters and hashes are technical evidence. Creative acceptance is a human watching and listening.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and [SECURITY.md](SECURITY.md) for reporting a vulnerability.

## License

MIT, see [LICENSE](LICENSE). Third-party code and its license are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## תקציר בעברית

סקיל להפקת פרסומות וסרטוני תדמית בעברית מקצה לקצה: ראיון ובריף, בימוי וחוזי שוטים, קריינות עם השהיות מבוימות, מוזיקה וסאונד, כתוביות RTL בצבעי מותג, הרכבה ב-Blender 5.1, גימור ב-DaVinci Resolve Studio, בדיקות ומסירה. כל הוצאה בתשלום דורשת אישור רשום, אין ניסיונות חוזרים אוטומטיים, וכל שוט נצפה ונשמע לפני שהוא מוכרז גמור. הוראות ההפעלה המלאות ב-`SKILL.md`; המתכון לסרטון של 150 שניות ב-`references/long-form-commercial.md`.
