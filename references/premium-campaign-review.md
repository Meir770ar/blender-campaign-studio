# Premium campaign review: story, product, motion, finish and sound

Use before paid shot creation and when a campaign is rejected. Translate critique into observable changes, not a list of effects or blanket brand claims. User rejection overrides technical PASS. Separate confirmed defects, listener observations, artistic preferences and claims needing a primary brand source.

For action mechanics, individual group performance and final micro-polish, use [performance-and-polish.md](performance-and-polish.md). Preserve version-specific positive listener feedback while tracking remaining contact defects; a lessons-only request updates the workflow without generating another film.

## Story and brand behavior

Write a one-sentence relationship arc and show its decisive action. If the idea is togetherness, show giving, receiving, shared attention and reciprocal reaction. A hero bringing several drinks then consuming alone can undermine that idea even when individual frames look attractive. Audit the whole sequence for unintended meaning.

For the current Coca-Cola rooftop revision, the requested direction is: arrival → cooler offered to the group → visible distribution/reaching together → opening → shared bottle toast and genuine mutual reaction → brand ending. A solo sensory detail may support this only after the sharing is established. Do not substitute a packshot for the social payoff or silently remove an explicitly required drinking action to hide a model failure; redesign coverage and explain any consequential change.

Lock product count, recipients, table positions, handedness, wardrobe and eyelines in the shot contract. Verify that bottles handed out are the same package shown in opening, toast and ending. Other campaigns need their own behavior audit, not this story imposed universally.

## Product truth and interaction

Select exact SKU/market/package from an approved reference before stills or motion. Glass contour bottles with crown caps are the user's creative choice for this revised rooftop concept; glass is not a universal rule for every premium campaign. Do not treat all glass bottles, volumes or labels as interchangeable. A package change invalidates the affected source frames, CG geometry, grip, opener action, SFX and continuity; it is not a material toggle on an existing plastic-bottle clip.

A crown-cap opening should show credible opener contact, leverage, release and retained/falling cap as actually staged. Build sound from that action. Do not add flying liquid/glass particles without a visible justified event. For any drinking shot inspect lips/rim contact, occlusion, hand grip, label stability, plausible liquid behavior and facial response throughout the action. A small sip need not show a measurable fill-level change; reject visibly impossible behavior rather than inventing a measurement requirement.

Keep exact logo and label assets traceable. Plan a dedicated product/brand ending using approved assets, safe areas, hierarchy and sufficient read time. Two to three seconds is a starting budget, not a universal brand rule. Official slogan and sonic identity require the actual approved, usable asset; never invent a five-note melody and call it official. Do not claim endorsement of an independent spec ad.

## Choose the Blender technique for the defect

| Defect / purpose | Appropriate route | Required acceptance evidence |
| --- | --- | --- |
| Depth in a deliberately still composition | Separated layers / restrained 2.5D camera projection | No doubled subject, exposed cutout edge, missing background, sliding contact shadow or cardboard silhouette across the move |
| Frozen walking, chair movement or hand action | Credible source motion, directed regeneration, or an actually animated/rigged action | Actual limb/body/cloth/object motion; camera zoom/parallax alone does not pass |
| Isolated accurate product shot | Reference-based native 3D packshot | Correct silhouette, dimensions, label, material, lighting and motion at delivery resolution |
| Replace a held moving bottle | Camera/object match-move plus roto/holdouts and compositing | Stable grip, finger occlusion, perspective, reflections, refraction, contact shadows, blur and label throughout the shot |
| Correct color / integrate already-valid elements | Shot matching and restrained optical finishing | Before/after comparison, product/skin protection and encoded review |

### 2.5D projection

Use clean masks and a reconstructed clean background, with separated foreground/middle/background where needed. Move a real camera only within the coverage of those layers. Follow `campaign-technique-library.md`; the existing runtime requires authored separated layers and does not infer depth. Check parallax and occlusion at the extreme camera positions. Camera projection cannot create a new walking cycle, mouth contact or plausible unseen side of a person.

Set physical scene scale, focal distance and aperture to the shot. F/1.8–2.8 is not a default: it can destroy label/face readability or exaggerate cutout edges. Set the focus object on the intended subject and review both ends of a rack. Optional low-amplitude, band-limited camera noise needs a directed reason, not an automatic handheld preset; preserve legibility and contact continuity.

### Glass, liquid and condensation

Use measured/reference-led dimensions, actual glass wall thickness, smooth manufactured normals, a separate liquid boundary and suitable absorption. Glass IOR around 1.5 and water-like liquid around 1.33 are starting approximations, not proof of realism. Avoid intersecting surfaces and validate refraction, fill and silhouette under the final lighting.

Geometry Nodes can distribute droplet instances, but uniform beads fail: use plausible physical size distribution, contact shape, clustering/exclusion masks, varied coverage, surface-normal orientation and restrained wetness. Droplets should adhere to the material and obey gravity when animated. They must not read as metallic beads, gems or floating spheres. Compare with the actual neighboring source shot before rendering a full sequence. Reject the insert if it still looks synthetic; do not keep it solely to demonstrate 3D work.

Tracking a hand marker gives a screen-space cue, not a full deforming hand/bottle solve. Plan enough stable features, camera/object motion, lens matching and manual correction where necessary. Rotoscope fingers/lips/occluders and preserve foreground holdouts. The existing supplied-corner planar-screen tool is not a bottle-in-hand replacement tool. Test the hardest grip/occlusion frame and a short motion segment before committing to a whole shot.

### Compositor finish

Match exposure/white balance across shots before a creative look. Warm mids/cool shadows are optional, not a mandatory teal/orange formula. Protect brand red, skin and highlight texture. Fog Glow should follow motivated bright sources; low thresholds that wash out linen/labels fail. Chromatic dispersion should be absent unless it serves the reference look; fixed 0.005–0.01 values are not universal. Use restrained temporally varying grain scaled to delivery resolution, inspected after compression.

Grade, glow, aberration, blur and grain cannot repair malformed fingers, changing logos, implausible grip or lip/bottle morphing. Do not hide an action defect with cosmetic processing. Preserve clear comparison evidence and keep a toggleable node graph.

### Typography and end board

Use the local licensed AAA Hebrew library and `hebrew-and-blender.md`. A licensed typeface can still be badly composed: evaluate size, hierarchy, line breaks, spacing, contrast, placement and phone readability. Avoid a blanket thin/serif font prescription. Native Blender Text is not the default Hebrew shaping path; use validated RTL artwork/outlined curves for 3D integration and inspect the actual glyph order. Bevel is scene-scale dependent, not a universal 0.01.

Animate only what supports the message, with a readable hold after easing. Budget the brand ending during the edit; use verified logo artwork and intended slogan. A centered white logo on red or on a separated background is an option, not a claim that every official campaign uses it. Do not add an unverified sonic logo.

## Sound architecture and acceptance

Keep four editorial buses: dialogue/VO, music, ambience, foreground Foley. If the current renderer groups ambience into SFX, preserve logical role tags or separate submixes; do not claim four native output buses unless actually implemented. Lay in appropriate room/roof ambience, then only sounds justified by visible action: footwear/material, cloth, cooler ice/water, actual cap type, glass contact and a restrained drink/breath. Do not force every listed sound into every shot.

Ducking is tuned by listening, not a fixed 3–4 dB recipe. In Blender volume is linear amplitude: a change of dB uses gain `10 ** (dB / 20)`. Align the relevant contact/attack, not automatically the file start or largest waveform peak; a bottle pressure release may precede visible cap separation. Follow the separate Foley gate in `editorial.md` and the reusable V2A trial workflow in `video-to-foley-tools.md`.

Deliver a short isolated problem-shot review and full-mix review. Review at 1x in the intended player, including voice ending cadence and music handoff. If actual listening is unavailable, record it as pending and present a concrete review to the user; numerical cross-correlation with an authored timeline cannot prove that the authored timeline matches the perceived action.

## Stop conditions and repair order

Reject on story contradiction, wrong package/brand asset, visible impossible interaction, unintelligible text, wrong-object Foley or perceived desynchronization. Fix story/blocking → source performance/product → integration → graphics/color → sound → encoded delivery. Preserve unaffected sources and version every change. Choose generation models by current tested ability on the hardest shot, not old model names or release marketing. New media, paid retries and external runs retain their existing authorization gates.

This guide is a decision/review workflow, not new automatic tracking, roto, simulation, listening or generation code. Only promote a technique after a real shot demonstrates it.
