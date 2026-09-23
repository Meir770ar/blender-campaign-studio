# DaVinci Resolve Studio hand-off and finishing

Blender stays the engine for what it does best: original 3D/product shots, camera-projection and
compositing techniques, and the pixel-exact Hebrew typography layers rendered by `render_text.py`
and `captions.py`. DaVinci Resolve Studio is the finishing NLE: cutting and trimming on a real
timeline, shot matching and grading, Fairlight mixing, and delivery renders. The plan contract does
not change: the same validated Timeline JSON v1 that `studio.py assemble` consumes is what
`davinci_bridge.py` hands to Resolve. Choose the finishing engine per production and record it in
`production.json`; do not run both on the same revision and present either as the other.

## Finishing host: the VIDEO STATION (default)

Resolve finishing and delivery renders run on the VIDEO STATION (`ai-station`, RTX A5000), not the
laptop. The A5000 is far faster than the laptop's i7-9750H for GPU grading, effects and delivery
encodes, so `davinci_bridge.py` defaults to `--host station`. The laptop route (`--host laptop`)
stays as an offline fallback and is otherwise unchanged.

How it works: the production's media is already mirrored to the station by the archive
(`studio.py archive-push`, at `D:/video-productions-archive/<slug>/`). `export-xml --host station`
rewrites the sequence.xml `pathurl`s from the local production root to that station media root; the
media is still hashed locally so the manifest verifies the same bytes on either machine.
`import --host station` copies the hand-off to the station and imports it into the station's open
project over SSH (the OS-owned `ai-station` alias), then verifies every clip. The station-side helper
is `scripts/davinci_bridge_remote.py` (stdlib only, deployed to `<archive root>/_bin`). Because the
timeline then lives in the station's Resolve, every render runs on the A5000.

Preconditions specific to the station route:
- Resolve Studio must be **open on the station desktop** with External scripting = Local. The bridge
  never launches it remotely (the MCP's `launch_resolve` starts it in the wrong service session); open
  it in RDP or ask the user.
- The media must be on the station first: run `studio.py archive-push --project PROJECT` before
  importing, and keep the hand-off dir inside the production folder so it mirrors too.
- The production folder name must be an ASCII slug (the archive root uses it); pass a `--slug` to the
  archive if the folder name is not one.

```powershell
python scripts/davinci_bridge.py doctor --host station                              # station Resolve + MCP registration
python scripts/davinci_bridge.py project --host station --name PROJECT --create      # open/create a saved project on the station
python scripts/studio.py archive-push --project PROJECT                              # mirror media to the station
python scripts/davinci_bridge.py export-xml --host station --project PROJECT --plan PROJECT/plan-v001.json --out-dir PROJECT/resolve/handoff-v001 --timeline-name "CUT_v001"
python scripts/davinci_bridge.py import --host station --project PROJECT --manifest PROJECT/resolve/handoff-v001/handoff-manifest.json --out PROJECT/resolve/handoff-v001/import-report.json
```

Verified live on 2026-09-22: the smoke plan imported into a throwaway project on the station's
Resolve Studio 21.1.0.14 with all four items online (media resolved under the archive root); the
temporary project was deleted and the station restored afterwards.

For agentic finishing, the station's official MCP is registered as `davinci-resolve-station`
(Claude Code user scope and Codex): it runs the station's `ResolveMCP.exe` over SSH, so `run_script`
drives the station's Resolve, not the laptop's.

## Prerequisites and preflight

- DaVinci Resolve **Studio** (external scripting is a Studio feature). Measured on 21.1.0.14,
  Windows 11, Python 3.11 (laptop) / 3.10 (station). Preferences > General > External scripting = Local.
- Resolve must be running with a **named, saved project** open. Importing into the never-saved
  `Untitled Project` is silently ignored by Resolve; the bridge refuses it.
- **Official MCP (default).** Resolve Studio 21.1 ships its own MCP server (`ResolveMCP.exe`). Two
  registrations exist: `davinci-resolve-station` drives the station's Resolve over SSH (the default
  finishing host, Claude Code user scope and Codex), and `davinci-resolve-studio` drives the laptop's
  Resolve locally (fallback). 14 tools, 12 KB of schema, starts in under a second: `get_resolve_status`,
  `run_script` (sandboxed Python 3.14 with `resolve`/`project` pre-injected, no filesystem),
  `run_script_unsafe` (same with OS access, only when media files must be touched),
  `search_scripting_api` / `get_scripting_api` / `get_scripting_docs` (always current for the
  running build), `get_whats_new`, and LUT/DCTL authoring. Work through `run_script`: search the
  API first, then write a short script that sets `result`. Blackmagic maintains it with each
  release, so prefer it over any wrapper.
- **Community MCP (on, station).** samuelgursky/davinci-resolve-mcp 4.8.15 is installed on the
  station at `<station>/davinci-resolve-mcp` (own venv, Python 3.10.11) and registered live
  as `davinci-resolve-community-station` for Claude Code (user scope) and Codex — it drives the
  station's Resolve over SSH through `<station>/resolve-community-mcp.cmd`. The user asked
  (2026-09-22) for its ready compound workflows to be available at any moment: rough cut from raw
  footage, media analysis with transcription, offline .drp/.drt/.drx editing, conform QC, and a
  destructive-op safety trap that archives the timeline before mutating. Cost: 37 compound tools,
  ~142 KB of schema per session; disable it per-project if a non-video session feels heavy. Verified
  live 2026-09-22: `resolve_control(action="get_version")` returned Resolve Studio 21.1.0.14 from the
  station. The domain skills listed below are written for this server's tool names. (A laptop copy at
  `<davinci-resolve-mcp>`, v4.8.13, drives the laptop's Resolve and is not registered live.)

  **Load its tools contextually (Tool Search), do not resident-load all 37.** `ENABLE_TOOL_SEARCH`
  is on, so these tools are deferred: they appear as a names-only list in a system-reminder and cost
  almost nothing until used. Do not pull the whole server. Read the user's request, decide the Resolve
  domain, and `ToolSearch` for just the compound tool(s) that domain needs, then call them. This keeps
  the session lean. Domain → compound tools to search for:

  | The request is about | Search for / load |
  |---|---|
  | Cut, trim, tracks, assemble, import a timeline | `timeline`, `edit_engine`, `timeline_versioning` |
  | A specific clip on the timeline (transform, speed, keyframes, retime) | `timeline_item`, `timeline_item_takes` |
  | Markers / flags / playhead | `timeline_markers`, `timeline_item_markers`, `media_pool_item_markers` |
  | Colour grade, LUT/CDL, node graph, versions | `timeline_item_color`, `graph`, `color_group`, `lut`, `dctl`, `gallery_stills` |
  | Fusion titles / motion graphics / VFX | `timeline_item_fusion`, `fusion_comp`, `fuse_plugin` |
  | Media: browse, import, media pool, bins, clips | `media_storage`, `media_pool`, `folder`, `media_pool_item` |
  | Reading footage / transcription / analysis | `media_analysis`, `timeline_ai`, `timeline_frame` |
  | Render / delivery / codecs / presets | `render`, `render_presets` |
  | Project / database / settings / app state | `project_manager`, `project_settings`, `resolve_control`, `layout_presets` |

  Probe first with the cheap reads (`resolve_control` action `get_version`, `project_manager` action
  `get_current`) before assuming Resolve is open on the station.
- A listed MCP is not proof that Resolve is open; run the preflight.

```powershell
python scripts/davinci_bridge.py doctor            # registrations, scripting paths, live connection, open project
python scripts/davinci_bridge.py doctor --no-live  # same without touching Resolve
```

`doctor` is read-only and returns `ready:true` only when both hosts are registered, the scripting
library exists, ffprobe is on PATH and Resolve answers with a named project.

## Hand-off flow

1. Build the plan as usual: `editorial.py conform` (cuts, source audio, remapped words),
   `captions.py` / `render_text.py` (PNG typography), `audio_finish.py` (stems + master), Blender
   shot renders. Merge into one `plan.json` and run `studio.py validate`.
2. Export the sequence. The timeline name must be unique per revision; Resolve returns the *old*
   timeline for a repeated name and reports success, so the bridge refuses a name that already exists.

```powershell
python scripts/davinci_bridge.py export-xml --plan PROJECT/plan-v001.json --out-dir PROJECT/resolve/handoff-v001 --timeline-name "CUT_v001"
python scripts/davinci_bridge.py import --manifest PROJECT/resolve/handoff-v001/handoff-manifest.json --out PROJECT/resolve/handoff-v001/import-report.json
```

3. Read `import-report.json`. `technical_pass:true` means every plan clip was found on the expected
   track at the expected frame with the expected duration and source in-point, media is online, and
   the timeline format equals the plan. It is placement evidence only; watch the timeline.
4. Read `unmapped` in the manifest and apply those decisions inside Resolve (or keep the Blender
   finish for that revision). The xmeml hand-off carries picture placement, source in/out, track
   layering by channel, static opacity and static clip volume. It does **not** carry `fade_in`/
   `fade_out`, `motion` presets (with `motion_amount`), `transform_keys` or `volume_keys`; each is
   listed per clip with the Resolve technique to use. An `image-sequence` clip is exported as its
   `resolve_movie` companion (ProRes 4444 with alpha from `studio.py alpha-movie`); a sequence
   without one is refused. Floating UI and phone-screen inserts that need real tracking are done
   here with the Fusion Planar Tracker (community MCP `timeline_item_fusion` / `fusion_comp`) on
   the PNG layers the Blender path rendered; the bridge does not automate that.
5. Finish through the official MCP from either host: `run_script` against the scripting API
   (timeline items, grades, Fairlight, render jobs); use `search_scripting_api` before guessing a
   method. Render to the production's `renders/` folder with a revision name.
6. QA the encoded render exactly as before: `delivery_qa.py --video ... --plan ... --audio-qa
   PROJECT/audio-v001/qa.json` binds the loudness/true-peak targets of the mix to the final file.
   `review_shot.py` and the listening/motion review remain mandatory. Delivery to WhatsApp follows
   `whatsapp-delivery.md` unchanged.

Outputs per hand-off: `sequence.xml`, `handoff-manifest.json` (plan hash, sequence hash, media
hashes, expected items, unmapped list) and `import-report.json` (timeline id, per-item checks,
timeline settings, Resolve build). Keep them with the revision; a manifest whose `sequence.xml`
bytes changed is refused at import.

## Hebrew in Resolve

Hebrew text layers are the PNG renders from `render_text.py` and `captions.py`, placed as stills on
their own tracks. Do not retype Hebrew into Text+ or Fusion text: Resolve's bidi handling of mixed
Hebrew/Latin/number runs and niqqud is not reliable, and the licensed AAA fonts and shaping checks
live in the Chromium renderer. `captions.srt` may be imported as a Resolve subtitle track for a
timing review only; final typography stays rendered. To change a title, regenerate the PNG and
replace the still; do not paint over frames.

## Safety rules (in addition to the studio's own)

- Source media is never modified, transcoded, relinked or proxied by the bridge. Resolve imports
  the files in place (`importSourceClips`), and the media pool grows by exactly the plan's files.
- One timeline per revision, never overwrite; do not delete projects, timelines or bins the user
  did not ask to remove. The bridge never deletes anything.
- Do not import into `Untitled Project`; do not switch or create projects silently. A production
  gets its own Resolve project named after the production folder.
- Resolve renders are technical outputs until watched and listened to; `technical_pass` from the
  bridge or from `delivery_qa.py` is not creative acceptance.
- The scripting API changes per patch release. Before promising a Resolve capability call
  `get_resolve_status` and `search_scripting_api` (or `get_whats_new`) through the official MCP;
  facts remembered from an older build are priors, not findings.

## Domain guidance to load on demand

The community MCP repository ships operating skills written for its tool names; they apply when
that server is enabled, and their craft guidance (order of operations, gotchas) is worth reading
even when working through `run_script`. Do not link them globally (context cost). All under
`<davinci-resolve-mcp>/.claude/skills/`:

| Task | Read |
|---|---|
| Start of any Resolve session: connect, edition, build gates, project and timeline state | `resolve-session/SKILL.md` |
| Map of all domains and the live-vs-offline servers | `resolve-mcp/SKILL.md` |
| Cutting, trimming, ranges, variants, changelists | `resolve-edit/SKILL.md` |
| Grading, shot match, looks, LUT/CDL/DRX | `resolve-color/SKILL.md` |
| Fairlight tracks, buses, loudness, voice isolation, subtitles | `resolve-audio/SKILL.md` |
| Titles, motion graphics and VFX in Fusion | `resolve-fusion/SKILL.md` |
| Render jobs, deliverable QC, provenance | `resolve-delivery/SKILL.md` |
| Reading footage: ffprobe, frames, optional Whisper (`language: "he"`) | `resolve-media-analysis/SKILL.md` |
| Social rough cut from raw footage / tightening one long take | `resolve-rough-cut/SKILL.md`, `resolve-tighten-recording/SKILL.md` |

Two reviewer agents in the same repository are worth reusing after a Resolve finish:
`.claude/agents/cut-reviewer.md` (pacing, order, coverage from rendered frames) and
`grade-match-verifier.md` (numerical shot-match check from rendered frames). They report evidence;
they do not replace the user's viewing.

Whisper on this machine: the `whisper` CLI (openai-whisper, system Python) is on PATH and the MCP
passes `language`. For Hebrew speech prefer the ivrit.ai transcription stack on the render station
and hand the words to `editorial.py`/`captions.py`; base Whisper models are weak on Hebrew.

## Verification record

- 2026-09-20: `davinci_bridge.py` unit tests (10, offline) pass. Live smoke on Resolve Studio
  21.1.0.14 in a temporary project: a plan with two movie cuts (one with a source in-point), a
  Hebrew-named PNG title with opacity 0.8 on a second track, and a WAV music strip at volume 0.5
  imported as `SMOKE_v002`; all four items verified at the expected frames, durations, in-points
  and online; timeline 640x360 @ 24 matched the plan; the duplicate-name guard refused a second
  import; the original project was restored and the temporary project deleted. Evidence:
  `<productions>/davinci-bridge-smoke-20260920/handoff-v002/`. This is a
  placement test with synthetic media, not a creative or color acceptance.
