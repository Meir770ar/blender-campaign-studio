# Premium directing and Blender research ledger

This ledger records what was actually inspected, what it contributes, and what still needs a render test. A title or search result is never treated as learned technique. Automatic captions are useful for coverage and timecodes, but exact UI names, values and version-specific behavior must be checked against Blender 5.1 and the visible result.

## Research method

1. Inspect the complete chapter map and original-language captions where legitimately available.
2. Classify each lesson by directing, composition, camera, blocking, lighting, look development, motion, simulation, compositing, edit, sound and delivery.
3. Extract principles and failure modes rather than copying a creator's scene, wording or assets.
4. Prefer official or practitioner-owned sources. Record the source and time range on every derived technique.
5. Rebuild an original, parameterized implementation in Blender 5.1. Inspect representative frames and the complete motion render.
6. Mark a technique `verified` only after normal and boundary cases render, the source license is compatible, and visual review passes. A tutorial-derived idea without that evidence remains `research-only`.

## Core Blender and commercial sources

### JB 3D Studio — product-animation course

- Source: [FREE COURSE: Blender Product Animation Course](https://www.youtube.com/watch?v=q3q3-iweRZ8), 10:14:49, published 2026-07-06.
- Coverage inspected: complete chapter map and original English captions, approximately 118,000 words.
- Projects: serum bottle 00:04:07–02:12:59; luxury watch 02:12:59–04:47:10; speaker 04:47:10–06:43:56; credit card 06:43:56–07:17:35; biscuits/liquid 07:17:35–08:13:56; perfume 08:13:56–09:06:16; water bottles 09:06:16–10:13:52.
- Strong reusable material: reference-driven dimensions; bevels and readable edge highlights; variable roughness and micro-detail; glass/transmission; reflection shaping; multiple shot setups per product; staggered action; Graph Editor cleanup; holds before a new action; camera and object counter-motion; image-sequence rendering; GPU/Cycles setup.
- Important limitation: this is a practical beginner/intermediate construction course, not a complete directing, editorial, sound or color-finishing curriculum. It contains virtually no sound direction, little compositing, no performance direction and no evidence-based final review. Statements that a setup is “perfect” are not acceptance evidence. Three-point lighting and a high-contrast view look are options, not premium defaults.

### Derek Elliott — complete phone commercial

- Source: [Product Animation in Blender: Phone](https://www.youtube.com/watch?v=lZPedlX6CMw), 01:15:15.
- Useful ranges: lighting and backdrop 00:31:42–00:37:09; first shot and music timing 00:37:09–00:41:04; depth of field 00:41:04–00:42:39; render planning 00:42:39–00:46:05; shape-key detail 00:46:05–00:49:05; exploded detail 00:49:05–00:55:04; variations 00:55:04–01:12:35.
- Strong reusable material: use few deliberate lights; preserve a common lighting language across shots; shape reflections instead of merely increasing brightness; frame with composition guides; time scene changes against actual audio structure; render handles; use a focus object; parent awkward multi-object moves to a controlled rig; vary one visual idea at a time.
- Limitation: Blender 2.8 UI and EEVEE settings are historical. Recreate principles and validate current APIs; do not port settings blindly.

### Jaleed Khan 3D — effects-oriented product shot

- Source: [How to Create Cinematic Product Commercials in Blender](https://www.youtube.com/watch?v=NflgzgwG4ro), 00:19:38, published 2026-01-22.
- Useful ranges: explode/particle ordering 00:01:01–00:04:13; drag and vortex control 00:04:13–00:08:57; fluid 00:08:57–00:16:42; background and light linking 00:16:42–00:18:38; compositor and camera 00:18:38–00:19:38.
- Strong reusable material: order dependent caches; short force windows; drag/vortex as art-directed motion; separate light control for label and glass; reflection-preserving highlights; subtle patterned background; restrained glare/color balance; capture wide and detail coverage.
- Limitation: effect construction does not establish whether the effect serves a campaign beat. Simulation cost, cache identity and retry policy need production controls not supplied by the tutorial.

### Blender Studio and official Blender 5.1 documentation

- [Blender Motion Graphics](https://studio.blender.org/training/motion-graphics/) covers workflow, camera, lighting, color, titles, compositing, rendering and farm concepts with source files. Some full material requires a subscription and some lessons predate Blender 5.1; do not access paid material or import project assets without authorization and license review.
- [Blender 5.1 cameras](https://docs.blender.org/manual/en/5.1/render/cameras.html): focal length, depth of field, focus objects and composition guides.
- [Blender 5.1 F-Curves](https://docs.blender.org/manual/en/5.1/editors/graph_editor/fcurves/properties.html): interpolation, easing and handle behavior.
- [Blender 5.1 F-Curve modifiers](https://docs.blender.org/manual/en/5.1/editors/graph_editor/fcurves/modifiers.html): non-destructive cycles, noise, limits and smoothing, including ordering/compatibility constraints.
- [Blender 5.1 Color Balance](https://docs.blender.org/manual/en/5.1/compositing/types/color/adjust/color_balance.html): lift/gamma/gain, ASC-CDL and white-point modes.
- [Blender 5.0 compositor migration](https://developer.blender.org/docs/release_notes/5.0/migration/compositor_migration/): the compositor became a `CompositorNodeTree` assigned through `scene.compositing_node_group`; output uses a group-output socket and many node options became named inputs. This migration remains applicable to the installed Blender 5.1.0 API and must replace pre-5.0 `scene.node_tree` examples.
- [Blender light linking](https://docs.blender.org/manual/en/latest/render/lights/light_linking.html): receiver/blocker collections and performance implications. The exact installed 5.1 API must be probed before scripting because the latest manual can describe a newer point release.

## Directing and composition sources

StudioBinder's examples are used as a terminology and shot-analysis source, not as a rigid rulebook:

- [Composition and framing](https://www.youtube.com/watch?v=hUmZldt0DTg), 00:17:49: focal points, lines, shapes, pattern, negative space, depth planes, balance, angle, color and tone.
- [Camera movement](https://www.youtube.com/watch?v=IiyBo-qLDeM), 00:29:09: static, pan, tilt, push/pull, zoom, tracking, arc, crane, handheld and composite moves, with narrative purpose.
- [Directing camera movement](https://www.youtube.com/watch?v=GbnYBmqBbKA), 00:06:36: handoffs of viewer attention and story-first movement.
- [Static shots](https://www.youtube.com/watch?v=eL_XaKA5qWM), 00:11:57: stillness makes blocking, production design, performance and cut timing carry the scene.
- [180-degree rule](https://www.youtube.com/watch?v=iW0bKUfvH2c), 00:05:45: screen orientation, deliberate line crossing, neutral resets and motivated crossing moves.
- [Blocking case study](https://www.youtube.com/watch?v=zLASrjAYjwg), 00:05:32: eyeline and performer handoffs through an uninterrupted shot.

Practitioner perspective:

- [What makes a cinematic image?](https://www.youtube.com/watch?v=52cqgBO_jqk), Cooke Optics: the consistent answer is not a preset look but choices that fit the story, point of view and staged action.
- [Steve Yedlin on cinematography](https://www.youtube.com/watch?v=Mb3ZzRBxAFc): camera and lens character should not distract from the director's scene; the photographic pipeline supports an already-directed idea.
- [John de Borman on composition](https://www.youtube.com/watch?v=W8V6GJdT_Bg): a frame should communicate emotional state and relationships, sometimes through depth, reflections and focus rather than extra coverage.

## Lighting sources

- [ARRI Lighting Handbook](https://www.arri.com/en/learn-help/lighting/lighting-handbook): light quality, direction, shaping, practical fixtures and example setups, including product and dramatic lighting. Treat equipment-specific examples as transferable light behavior rather than required brands.
- [Aputure: light placement](https://www.youtube.com/watch?v=nqMQZG68Wkc), 00:04:22: key/fill/back are functional roles; any count and placement can work if the role and image support the scene.
- [Aputure: high-key interior](https://www.youtube.com/watch?v=tYRD_Wu2N6Y), 00:07:15: inspect the complete frame, establish motivated ambient fill, retain background texture and add small corrections only where the image needs them.
- [Aputure: exposure against windows](https://www.youtube.com/watch?v=CNKA66C-PMM), 00:14:11: location/time planning, protect the exterior, then shape foreground contrast; when a planned bounce fails, change the method rather than forcing the recipe.
- [Cooke Optics: practicals and night](https://www.youtube.com/watch?v=nJcWcXN25CY), 00:05:13: control visible practicals separately from the light they motivate, build depth through layers and silhouettes, and avoid unmotivated saturated “moonlight.”

## Coverage gaps and routing

No one source covers a complete premium campaign. Route missing knowledge deliberately:

- Directing actors, interview performance and ethical quote editing: `interview.md`, `directing.md`, performance-focused practitioner sources and actual take review.
- Editorial rhythm and sound: `editorial.md`, real music/dialogue listening and a separate sound-design reference; the 10-hour Blender course is not evidence here.
- Color management: official Blender/OCIO and delivery documentation, not a creator's favorite contrast preset.
- Hebrew typography: `hebrew-and-blender.md` and licensed local fonts; Latin tutorial titles do not validate RTL.
- Rights: source ideas may inform an original implementation. Do not redistribute downloaded tutorial media, captions, paid project files, fonts, music or creator assets.
