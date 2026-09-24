# HyperFrames: motion graphics from HTML

HyperFrames (HeyGen, MIT, `npm i -g hyperframes`) renders a seekable HTML + GSAP composition to video with a
headless Chrome it manages itself. In this skill it is a **local source of motion clips**: kinetic titles,
infographics, data-driven timelines, lower thirds and overlays, slideshow decks, ports of Remotion
compositions. It does not replace the plan: the rendered file enters `plan.json` like any movie, the
captions still come from `captions.py`, and the delivery still goes through `studio.py` and `delivery_qa.py`.

## When to reach for it

| Need | Route |
|---|---|
| Static or whole-layer animated Hebrew title | `render_text.py` PNG layer + VSE motion preset (unchanged default) |
| Kinetic typography, counters, charts, UI mockups, animated diagrams, decks | HyperFrames composition rendered by `hyperframes_clips.py` |
| Hebrew kinetic titles with niqqud on the station | `tesseract_overlay.py` (unchanged) |
| An existing Remotion project | port it with the `remotion-to-hyperframes` skill, then render here |

Authoring is the `hyperframes-core` skill (composition contract), `hyperframes-animation` (GSAP, Lottie,
Three.js adapters), `hyperframes-audio` (mixing inside a composition) and `hyperframes-studio` (timeline
layout for people). They are installed for Claude Code and Codex by `hyperframes skills update`.

## Commands

```powershell
python scripts/hyperframes_clips.py doctor
python scripts/hyperframes_clips.py render --project PROJECT/motion/opening-title --out PROJECT/motion/opening-title-v001.mp4 --fps 24 --plan PROJECT/plan-v001.json --quality high
python scripts/hyperframes_clips.py render --project PROJECT/motion/lower-third --out PROJECT/motion/lower-third-v001.webm --fps 24 --format webm --variables '{"name":"..."}'
```

`render` refuses an existing output, checks the CLI version against `connections.json` (`hyperframes.min_version`)
and the managed Chrome, runs `hyperframes check` (lint, runtime, layout, motion, contrast) and stops on any
finding unless `--skip-check-reason` records the accepted finding in words, then renders once with `--strict`
at the requested fps (which must equal the plan fps when `--plan` is given), verifies the file with ffprobe
and writes `<output>.receipt.json` (CLI version, command, sha256, media, check report tail). Watch the result at
final size; the receipt is technical evidence only.

Plan clip: `{"kind":"movie","path":"motion/opening-title-v001.mp4","start":0,"duration":72,"channel":4}`.
Transparent overlays: render `--format webm` (VP9 alpha) or `--format mov`, then `studio.py alpha-sequence`
and the `image-sequence` clip described in executable-workflow.md; `png-sequence` renders RGBA frames directly
into a new directory with `receipt.json` inside.

## Hebrew inside a composition

Chromium does the bidi and shaping, the same engine as `render_text.py`, so Hebrew is safe when the file
follows [hebrew-and-blender.md](hebrew-and-blender.md): keep strings in logical order, set `lang="he"` and
`dir="rtl"` on the text container, declare the licensed local font with an in-file `@font-face` (the lint
rule `font_family_without_font_face` fails otherwise; never fall back to a Google Hebrew font), isolate embedded
Latin or numbers with U+2066 / U+2069, and review `hyperframes snapshot --at ...` frames as well as the
final render. Word-by-word Hebrew emphasis stays with `captions.py`; a composition animates whole lines.

## Determinism and sizing

One paused GSAP timeline registered at `window.__timelines["<composition-id>"]`, timing only through
`data-start` / `data-duration`, no wall-clock code. Root `data-width` / `data-height` set the canvas
(1920x1080 for the campaign plans, 1080x1920 for vertical cuts); the root `data-fps` is overridden by
`--fps`. Media inside the composition is framework-owned (`<video>` / `<audio>` with ids), and the CLI
extracts frames at the render fps, so a 24 fps plan gets 24 fps clips without resampling.

## What changed between 0.7.66 and 0.8.67 (verified 2026-09-24)

- Render: `render --resume` and `--keep-segments` for long renders, HLS output, motion blur (`motionBlur`),
  transparent GIF, speed ramps, `--strict` / `--strict-all` lint gates, `--variables`, `check` replaces the
  deprecated `validate` / `inspect` / `layout`, and `snapshot --against <reference video>`.
- Audio: audio FX rack (EQ, compressor, limiter, automation lanes), groups and submix buses, voiceover carve on
  by default, typed audio values and clip fades, `normalize-audio`, real peak and loudness meters in Studio.
- Timeline and Studio: `hyperframes timeline` and timeline editing verbs in the CLI, keyframe lanes and
  retiming, ease editor, magnetic main track, clip groups, rulers and safe margins, dockable layout, WebMCP so
  agents can see the frame and edit text, styles and motion live.
- Skills: `hyperframes-audio`, `hyperframes-studio`, `motion-graphics`, `media-use`, creator editing recipes,
  Remotion porting taught as sub-compositions (no CLI importer exists; the port is authored).
- Breaking: Plan v2 is the default for Lambda / Cloud Run renders (redeploy the cloud side first); the Studio
  "hear only this" control and `window.__hf.setAudioSolo` were removed; `consumeFileWriteReceipt` became
  `identifyFileWrite`; `init` scaffolds a new starter and the default render quality is now `looks`.
- Not used here: the built-in `tts` (Kokoro, no Hebrew) and `transcribe` (whisper.cpp, not installed);
  narration and word timing stay with the provider routes in providers.md.
