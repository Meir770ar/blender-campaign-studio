# Blender Campaign Studio

An agent skill (Claude Code / Codex CLI) that directs, produces and edits Hebrew commercials, brand films and campaign videos end to end: adaptive interview and brief, direction and shot contracts, generated shots, narration, music and sound design, right-to-left Hebrew typography, assembly in Blender 5.1, optional finishing in DaVinci Resolve Studio, technical QA and delivery.

The skill is opinionated about one thing above all: every paid generation needs an explicit approval recorded in a ledger, nothing retries on its own, and every shot is watched and listened to by a human before it is called done.

## What it does

- Interview, brief, direction and storyboard with executable JSON contracts (`templates/`) and creative gates.
- Narration: ElevenLabs v3 with word timestamps, directed pauses (`narration_plan.py`), Hebrew captions with brand colors (`captions.py`).
- Music and sound: Suno (including extension of a clip for a planned change of character), a licensed library, per-track envelopes, speech-driven ducking, two-pass loudness (`audio_finish.py`).
- Shots: Grok Imagine Video through an OpenClaw gateway, Genspark, Magnific/Dzine, HeyGen avatars; still images through Codex; batch approvals with a pilot and a shared cap (`provider_jobs.py`).
- Assembly: Timeline JSON v1 to Blender VSE with motion presets, transform keyframes, image sequences with alpha, freeze frames (`studio.py`, `sequence_tools.py`).
- Finishing: FCP7 XML hand-off and verified import into DaVinci Resolve Studio (`davinci_bridge.py`), Tesseract kinetic titles, remote Cycles rendering on a GPU station (`render_dispatch.py`).
- QA and delivery: encoded-file checks, loudness gates, compressed viewing copies, optional WhatsApp self-delivery.

Read `SKILL.md` (Hebrew) for the production doctrine and `references/` for every contract. `references/long-form-commercial.md` is a complete recipe for a 150-second commercial.

## Requirements

Minimum machine: Windows 11, a modern CPU (AVX2), an NVIDIA GPU with 12 GB VRAM or more, 32 GB RAM, a fast SSD.

Software: Python 3.11+ with `playwright` (run `playwright install chromium`) and `fontTools`; Node.js 20+; FFmpeg (full build) on PATH; Blender 5.1.0 exactly; DaVinci Resolve Studio 21.1 with its official MCP server (and the community MCP for the compound workflows); Tesseract (`tsrct`) for kinetic Hebrew titles; a local Whisper / ivrit.ai stack for transcribing footage with speech; one licensed Hebrew font (the skill refuses to substitute a free font).

Accounts: Claude (Claude Code) and/or ChatGPT (Codex CLI, also used for stills); one video generator (Magnific, Genspark, or Grok through an OpenClaw gateway); ElevenLabs; Suno; HeyGen; Google AI Pro (Antigravity: script, analysis and vision check); Magnific; a licensed music/SFX library.

Not required: WAHA (automatic WhatsApp self-delivery; send the file by hand instead), Dzine, Genspark as a second video route, and the OpenClaw gateway unless you want the direct Grok route.

Not included: the user-side CLI clients this skill drives (`suno-cli`, `heygen-cli`, `@genspark/cli`, `agy-cloudcode.mjs`, the Magnific/Dzine clients, the OpenClaw xAI video patch). Point `connections.json` at your own installations.

## Install

1. Copy this folder to your skills directory, e.g. `~/.codex/skills/blender-campaign-studio`, and junction/symlink it into `~/.claude/skills/` if you use both hosts.
2. `pip install -r requirements.txt && playwright install chromium`
3. `cp connections.example.json connections.json` and fill in your paths, hosts and ids. `connections.json` is git-ignored; it holds locations, never secrets.
4. `python scripts/studio.py doctor` and `python -m unittest discover -s scripts -p "test_*.py"`.

## Quick start

```powershell
python scripts/studio.py init --project <productions>/my-film --idea "the idea in the user's words"
python scripts/creative_gates.py --direction <productions>/my-film/planning/direction-v1.json --stage direction --out <productions>/my-film/planning/direction-gate-v001.json
python scripts/studio.py validate --plan <productions>/my-film/plan-v001.json
python scripts/studio.py assemble --plan <productions>/my-film/plan-v001.json --out-dir <productions>/my-film/render-v001 --render
python scripts/delivery_qa.py --video <productions>/my-film/render-v001/preview.mp4 --plan <productions>/my-film/plan-v001.json --out <productions>/my-film/delivery-qa-v001.json
```

## Safety rules baked into the code

- A provider job is prepared, approved with recorded evidence and a cap, executed once, then collected; `unknown` is reconciled, never retried.
- Batch approvals carry a shared cap and an optional pilot that holds the rest until a review is recorded.
- Hebrew text is rendered to PNG by Chromium with a licensed font; it is never typed into Resolve Text+.
- Rendered frames, meters and hashes are technical evidence; creative acceptance is a human watching and listening.

## Hebrew summary / תקציר

סקיל להפקת פרסומות וסרטוני תדמית בעברית מקצה לקצה: ראיון ובריף, בימוי וחוזי שוטים, קריינות עם השהיות מבוימות, מוזיקה וסאונד, כתוביות RTL בצבעי מותג, הרכבה ב-Blender 5.1, גימור ב-DaVinci Resolve Studio, בדיקות ומסירה. כל הוצאה בתשלום דורשת אישור רשום, אין ניסיונות חוזרים אוטומטיים, וכל שוט נצפה ונשמע לפני שהוא מוכרז גמור.

## License

MIT. See `LICENSE`.
