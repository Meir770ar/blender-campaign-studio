# Cinematography and lighting operating guide

Use this guide after the story beat and blocking are known. Cinematography translates those decisions into viewpoint, exposure, shape, depth and continuity. It does not decorate an undecided scene. The source ledger and version caveats are in `research-sources.md`.

## Start from the image's job

Before choosing a lens or light, write four short statements:

1. what the viewer must notice first and last;
2. what physical or emotional change happens during the shot;
3. what must remain accurate: face, product geometry, label, color, texture or environment;
4. what the next shot must inherit in direction, brightness, color and motion.

If these cannot be answered, the scene is not ready for lighting. “Luxury,” “cinematic,” “high key,” “three point” and “anamorphic” are references to investigate, not an image plan.

## Exposure and contrast

- Decide which detail must survive in highlights and shadows. Protect that information before applying a look.
- Establish the broad ambient level first, then add or remove light for hierarchy. More fixtures do not imply greater control.
- Judge the complete frame. A correctly exposed subject can still fail when a window, practical, reflection or background patch wins attention.
- Separate capture correction from creative contrast. Match adjacent shots in a neutral state before applying a shared look.
- Check the intended display and a normal phone display. Retain deliberate blacks, but do not confuse crushed information with richness.
- Treat HDR, log and wide-gamut sources explicitly. Do not infer SDR merely because metadata is absent, and do not stack display transforms.

Useful checks are waveform distribution, clipping, neutral/product references and adjacent-frame comparison. They inform judgment; no single numeric range defines a premium image.

## Light by function

Name every source by what it does in the frame:

- **exposure or environment:** establishes the believable ambient field;
- **shape:** creates readable planes, edges and volume;
- **separation:** distinguishes subject from background without outlining everything;
- **material description:** places controlled reflections on glass, metal, gloss or liquid;
- **attention:** makes the story focal point win over competing elements;
- **motivation:** appears to come from a window, practical, screen, sky or other credible cause;
- **correction:** solves one local problem without changing the entire image.

Key/fill/back are possible roles, not a required three-light recipe. Begin with the fewest sources that express the beat. Add a source only when its function can be stated and its side effects are inspected.

## Quality, direction and shaping

- Source size relative to the subject controls softness. Distance also changes falloff, apparent size and reflection placement.
- Direction reveals or hides form. A frontal source can clarify a label but flatten geometry; grazing light can reveal texture but exaggerate defects.
- Flags and negative fill are lighting tools. Removing spill can be more effective than adding brightness.
- In Blender, area-light geometry is visible through its reflection even when the lamp itself is off camera. Shape and place the reflection, not just the illumination.
- Keep shadow direction, softness and ambient color consistent with the motivated environment unless a visible story change explains the break.

## Products, glass and labels

Build a reflection plan before increasing samples:

1. identify the hero silhouette and material transitions;
2. place broad cards/area sources to draw long readable gradients;
3. add a narrow edge or sweep only where it reveals form;
4. protect the label/logo with a controlled source or separate receiver relationship when the installed Blender API is verified;
5. inspect black reflections, floor contact and the environment outside the camera frame;
6. review product color and label geometry against an approved reference.

A bright outline around every edge looks diagrammatic. Leave some surfaces quiet so the reveal has progression. Glass needs something to reflect and refract; increasing transmission alone does not describe it. Liquid, packaging and transparent layers require correct normals, thickness, index-of-refraction intent and enough render samples for the chosen motion.

## Faces and performance

- Light the blocking, not a mark that the performer cannot leave. Test head turns and gestures through the complete take.
- Preserve eyes and expression when they carry meaning; allow concealment only when it is part of the direction.
- Match skin tone and key direction across editorially adjacent coverage. Do not erase natural texture with denoising, blur or aggressive grading.
- Visible practicals should be controlled separately from the illumination they motivate. A clipped bulb does not automatically create believable room light.
- For interviews, background depth and tonal separation should support the speaker rather than advertise the setup.

## Lens, distance and camera height

Choose perspective first. Focal length and camera distance work together:

- closer/wider exaggerates depth, near/far scale and movement;
- farther/longer compresses layers and can feel more observed or graphic;
- camera height and tilt determine dominance, horizon behavior and product-top visibility;
- sensor fit and output aspect change framing, so record them with lens and distance.

Do not solve framing by changing focal length when perspective continuity matters. Move or redesign the set, then select the lens that preserves the intended relationship. In Blender, use composition guides for diagnosis and a focus object for repeatability; still inspect the actual depth-of-field transition.

## Movement and focus

For a moving shot, define start frame, end frame and the information gained between them. Record:

- movement purpose from the director grammar;
- start/end composition and focal path;
- acceleration, peak speed, deceleration and settling time;
- foreground/background parallax and edge clearance;
- focus target, focus transition and acceptable sharpness;
- edit handles before and after the primary action.

Avoid linear interpolation by default. Use deliberate Bezier/easing or frame-sampled motion, then watch the complete shot for mechanical starts, mid-move drift and abrupt stops. A rack focus is an attention handoff, not a generic polish effect.

## Background and depth

Design foreground, subject plane and background as one exposure. Texture or pattern in the background should remain subordinate and should not alias, flicker or intersect the silhouette. Use haze, falloff, focus and tonal separation only when they clarify spatial relationships. A seamless sweep needs credible contact shadow and enough off-camera geometry to survive the camera move.

## Color pipeline

- Record source color space and any transform. Unknown is a review item, not permission to guess.
- In Blender 5.1, use AgX for scene-referred CG unless a tested production transform requires otherwise. Choose the available installed look only after viewing; local 5.1 may expose a smaller look set than tutorials show.
- Render CG to an image sequence for recoverability and compositing. Preserve sufficient bit depth for grading where the production needs it.
- Match exposure, white balance, contrast and saturation across shots before creative treatment.
- Use compositor glare, color balance and sharpening sparingly and at viewing resolution. Effects must not alter product/logo truth or create unstable highlights in motion.

## Practical review loop

Review at least the first, transition/peak and settled/end states, plus the full moving render:

- Is the focal path unambiguous at normal playback speed?
- Does the product/face remain accurate through motion and denoising?
- Do reflections describe form without hiding copy?
- Are clipping, noise, fireflies, banding, aliasing or temporal artifacts visible?
- Does the camera settle before the cut, and are useful handles present?
- Does the shot match its neighbors in direction, screen geography and exposure?
- Does it still work in the target aspect and underneath platform overlays?

Use `creative_gates.py` to validate that these decisions exist before expensive motion. Use `review_shot.py` to create timecoded evidence and record pass/fail findings after a real render. Neither tool assigns an aesthetic score or grants provider-cost approval.

## Source basis and limits

The functional-lighting method and whole-frame checks are synthesized from the ARRI Lighting Handbook and the Aputure light-placement, high-key and window-exposure sources listed in `research-sources.md`. Story-fit cinematography, composition and practical-light motivation draw from the listed Cooke Optics interviews. Camera/attention grammar draws from the listed StudioBinder analyses. Product reflection, focus and motion practices draw from the inspected JB 3D Studio, Derek Elliott and Jaleed Khan material.

These sources support principles, not copyable scenes. Older Blender demonstrations must be rebuilt against Blender 5.1. Equipment examples do not mandate a brand, and tutorial beauty frames are not evidence that a parameterized technique works on a new product.
