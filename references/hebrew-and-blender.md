# Hebrew typography and executable Blender workflow

## Runtime

Python 3.11+, FFmpeg/ffprobe, Python packages playwright and fontTools, an installed Playwright Chromium runtime, and Blender 5.1. Run `python scripts/studio.py doctor`. The helper prefers the tested Blender 5.1 installation; another version requires an explicit compatibility check. Missing dependencies must be reported, not bypassed. Typography and Blender assembly run locally without paid generation. Separate provider and WhatsApp helpers perform the explicitly authorized network operations documented in their references.

## Hebrew invariants

- Keep original strings in Unicode logical order; never reverse Hebrew strings. Use UTF-8 JSON and lang=he / dir=rtl for generated documents.
- Read `<fonts-library>/INDEX.md` before selecting a font. Use the actual licensed OTF/TTF file (other machines need their own supplied font). Never silently substitute a Google Hebrew font.
- Chromium performs bidi and shaping; fontTools checks coverage first. `render_text.py` rejects unsupported glyphs and text outside the safe area. A screenshot QA report is technical evidence, not a substitute for reading the frame.
- Mix Hebrew, English, prices, percentages, phone numbers, parentheses and punctuation in the typography test. For an ambiguous embedded LTR phrase, use Unicode LRI U+2066 and PDI U+2069 around that phrase and visually verify. Do not inject direction controls around the entire paragraph blindly.
- In label lists mixing Hebrew, Latin and numbers, isolate each intended LTR item individually (e.g. `עברית • \u2066Blender\u2069 • \u20662026\u2069` in JSON). Bidi can otherwise group adjacent Latin/numeric items in an unintended order even though every glyph renders correctly. Inspect semantic order as well as glyphs.
- Correct line breaks and font sizes deliberately. Never clip, distort text, reverse words, or shrink everything to hide overflow. Check reading duration at final phone size and on each output aspect.
- Word/letter animation needs shaping-aware segmentation and preservation of combining marks. `captions.py` creates word-timed emphasis while retaining full-phrase browser layout. Whole-layer animation is supported in VSE. For separate moving words, author reviewed shaped layers; do not split code points or reverse their order.
- Transparent PNG layers retain source JSON. Regenerate after content changes. Blender stores the source specification as a Text datablock, but native text extrusion is a separate, unimplemented path requiring correct shaping/outlines and a render test.

## Commands

For advanced community-film layouts, see [community-film-editing.md](community-film-editing.md). Center visible glyph bounds rather than transparent canvas bounds; select a licensed companion font explicitly if a Hebrew face lacks Latin/numeric glyphs. Stable card/tile geometry and independent image crop/pan prevent a moving collage from drifting. Track phone overlays only on the visible front display and retain occlusion/reflection layers. These are composition/review rules; the generic text renderer does not implement optical centering, auto-tracking or automatic occlusion.

Run from this skill directory, or use absolute script paths. Use quoted paths with spaces in PowerShell. Replace example project paths with the user's chosen directory.

```powershell
python scripts/studio.py doctor
python scripts/studio.py init --project '<productions>/my-film' --idea 'הרעיון המקורי של המשתמש'
python scripts/studio.py inventory --source 'C:/footage' --out '<productions>/my-film/inventory.json'
python scripts/render_text.py --spec '<productions>/my-film/typography/title.json' --out '<productions>/my-film/typography/title.png'
python scripts/studio.py validate --plan '<productions>/my-film/plan.json'
python scripts/studio.py assemble --plan '<productions>/my-film/plan.json' --out-dir '<productions>/my-film/renders/v001' --render
python scripts/test_studio.py
```

Omit --render to save only the .blend. Outputs reject existing files/directories; create a new revision. The .blend depends on original media paths, so prepare and verify a separate portable bundle when requested. No font redistribution is automatic.

## Typography JSON

Required: text (logical order), font_file (existing local file), width, height, font_size.
Optional: padding=64, line_height=1.3, align=right (right/center/left), vertical=center (top/center/bottom), color=#ffffff, background=transparent. Use an explicit newline for a deliberate line break. Dimensions are in pixels; specify the final output size. Output is full-canvas RGBA PNG and `.qa.json`.

## Timeline JSON v1

Root: version=1, width/height (even pixels), fps (integer), frames (total), clips (nonempty array). Timeline starts at frame 1; duration is a count, not an inclusive end frame. Helper supports SDR delivery up to 10 minutes, 8192 pixels per dimension and 120 fps. It does not claim HDR support.

Each clip: unique id, kind=image/image-sequence/movie/sound, path, start, duration, channel. An image-sequence clip names its first frame; the frames are that file and its siblings (same folder and extension, sorted by name) for `duration` frames, `hold_last:true` freezes the final frame when fewer exist, and `resolve_movie` names the ProRes 4444 companion the DaVinci hand-off uses instead (see `studio.py alpha-sequence` / `alpha-movie`). Local source paths can be relative to the plan or absolute. Source files are read, not changed. No network URLs.

Optional fields:
- source_start: frames to skip in the source, zero-based, measured at project fps; only movie/sound.
- opacity: 0..1 for visuals; motion: none/fade-rise/push-in/zoom-in/zoom-out/pan-left/pan-right/slide-left/slide-right/slide-down, with optional motion_amount (0.005..0.5; defaults 0.06 for zooms, 0.04 of the frame for travel). Zooms run over the whole clip; rise/slide settle within fade_in frames (or 0.4 s); pans overscale by twice the amount and travel across the whole clip. transform_keys (mutually exclusive with a preset) are explicit clip-relative keyframes with any of scale (multiplier of the fitted size), offset_x/offset_y (output pixels) and rotation (degrees); a field first mentioned in a later key starts from its rest value at the first key, and a field omitted from a later key holds. These are helper defaults, not a compulsory campaign style; the keyframes stay editable in the .blend.
- fade_in/fade_out: visual fade length in frames; combined length must be less than clip duration. Endpoints are on start, start+fade_in, start+duration-1-fade_out and start+duration-1.
- text_source: path to the source typography JSON stored inside .blend.
- volume: sound gain 0..4. volume_keys: increasing [relative_frame, gain] pairs within the clip; gains are absolute. Use this for fades/ducking, planned against narration timings.

Separate sound strips are explicit, including source movie audio; adding a movie alone does not add its sound. Use a distinct channel for every overlapping strip. Validator checks missing files, media types, trims, duration, visual coverage, overlap, fps and envelope bounds. Normalize movies to project CFR before assembly; average fps alone cannot prove CFR, so inspect VFR sources. Transparency may still reveal black even with visual coverage; inspect the rendered result.

The .blend contains production-plan.json and the text specifications. Output also contains resolved-plan.json, blender.log, verification.json and preview.mp4 when requested. The verification records rendered duration and streams. Review pacing, appearance and sound separately.

Primary references: [Blender API](https://docs.blender.org/api/5.1/), [Blender VSE](https://docs.blender.org/manual/en/5.1/video_editing/index.html), [Playwright screenshots](https://playwright.dev/python/docs/screenshots).

## Initial assembly verification on 2026-09-06

- Skill validator and UTF-8 Hebrew UI metadata passed; all four workflow references resolve.
- 13 contract tests passed, including original-idea preservation, refusal to overwrite, missing files, timeline gaps/overlaps, invalid values and fade boundaries.
- Chromium rendered the actual Almoni Neue Bold AAA font: Hebrew, niqqud, Latin, prices, percentages, phone number and punctuation. Font loaded, no overflow; frames visually inspected. Separate overflow and missing-glyph cases were rejected without creating an image.
- Blender 5.1 rendered a 72-frame, 640x360, 24fps test with a trimmed movie, transparent Hebrew layer, fade-rise, push-in and an explicit sound strip with envelope. Output has H.264 and stereo AAC; video duration is 3.000s, container 3.008s due to audio. The .blend reopened with three strips and its embedded source-text specification. Audio presence/levels were measured; this was a quiet synthetic tone, not a reviewed narration/music mix.
- Media inventory of the test output completed without inspection errors.
- Evidence: <productions>/blender-skill-validation-20260906/. Latest preview: render-v003/preview.mp4. This is a technical validation fixture, not a commercial-quality showcase.
- No paid provider was invoked. This initial assembly check predates the provider, editorial, finishing and delivery helpers. For the expanded verification see [verification.md](verification.md); actual artistic quality and provider generation still require checks in the real production.
