# Premium Blender technique system

This is the acceptance system for reusable Blender work. It complements `technique-research.md`: the source ledger establishes provenance, this document establishes what must exist before a technique becomes part of production.

## Technique states

- **research-only:** an inspected source or hypothesis; do not promise it in a production.
- **implemented:** an original Blender 5.1 scene/script exists and accepts bounded parameters.
- **render-verified:** normal and boundary fixtures render locally and the output can be reopened.
- **visually-verified:** representative frames and complete motion were inspected against explicit criteria.
- **production-proven:** used on an actual approved shot with recorded limitations and render cost.

Never promote a technique based only on a successful script exit, one still frame or a tutorial author's result. Record the exact Blender version; rerun render evidence after a version migration.

## Required technique package

Each reusable technique contains:

1. narrative purpose and cases where it should not be used;
2. a source ledger with creator, URL, time range, access/license notes and extracted principle;
3. original implementation with explicit inputs, bounds and actionable failures;
4. deterministic seed or cached simulation identity where randomness exists;
5. editable `.blend` output and embedded input manifest;
6. image-sequence or lossless intermediate output for expensive renders;
7. normal, aspect-ratio and timing boundary fixtures;
8. measured hardware, engine, samples, resolution and render time;
9. visual review packet and known limitations.

Customer assets, tutorial project files and licensed fonts are not silently bundled. Record their regeneration path and permissions.

## Current original pilot: controlled product reveal

`scripts/premium_product.py` implements the first verified candidate. Its creative role is a controlled hero reveal: the camera approaches a settled packshot while a narrow reflection source travels across the form and a stable soft source protects overall material readability. It deliberately avoids a default full orbit.

The contract requires a shot intent, a real local GLB, timing, camera/lens values, a reflection-sweep side and bounded colors/energies. It then:

- normalizes and grounds the imported object while preserving hierarchy;
- builds an off-camera cyclorama with contact shadow;
- creates broad key/fill and rim/reflection sources with named functions;
- frames and focuses on a stable target;
- samples a smooth approach/reveal and reserves a settled hold;
- uses Cycles, denoising and AgX in Blender 5.1;
- saves the editable scene and input JSON;
- renders selected preview frames or a recoverable PNG sequence.

The script does not repair incorrect product materials, infer the hero label, certify brand color or decide whether a reveal serves the story. Review the exact product and complete motion. For transparent packaging, liquid, simulations or isolated label lighting, author a shot-specific extension and verify it separately.

Example:

```json
{
  "version": 1,
  "shot_id": "S04-packshot",
  "intent": "Move attention from the quiet silhouette to the front label, then hold the verified packshot for the CTA cut.",
  "model": "assets/product.glb",
  "width": 1920,
  "height": 1080,
  "fps": 24,
  "frames": 96,
  "samples": 64,
  "camera": {"lens_mm": 70, "distance": 6.2, "framing_padding": 1.18, "height_offset": 0.15, "travel": 0.35, "yaw_start_deg": -7, "yaw_end_deg": 2, "fstop": 5.6},
  "motion": {"settle_fraction": 0.78, "sweep_side": "left"},
  "lighting": {"key_energy": 850, "fill_energy": 220, "rim_energy": 1000, "sweep_energy": 1250},
  "look": {"background_rgba": [0.018, 0.022, 0.032, 1], "floor_roughness": 0.42, "world_strength": 0.025, "glare": false}
}
```

```powershell
& 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe' --background --factory-startup --python-exit-code 1 --python scripts/premium_product.py -- --spec PROJECT/S04.json --out-dir PROJECT/S04-preview-v001 --preview
```

Use `--render` only after preview review. It writes numbered PNG frames, not a fragile directly encoded movie. Assemble or transcode the approved sequence separately and keep its manifest.

## Review thresholds are shot-specific

Acceptance criteria describe visible facts: “front label remains legible from frame 52 through the settled hold,” “left highlight never clips the embossed mark,” or “CTA-safe negative space remains clear in 9:16.” Avoid abstract criteria such as “looks premium.” Technical render checks can detect files, dimensions and duration; a reviewer must still judge hierarchy, truth, material response and motion.

`creative_gates.py` blocks incomplete direction contracts. `review_shot.py prepare` extracts timecoded evidence from the actual output; `review_shot.py finalize` requires an explicit result for every acceptance criterion and derives `passed` or `revise` without inventing an aesthetic score.

## Expansion order

Add techniques only when a real brief needs them. High-value next candidates are controlled label/glass light linking, masked RTL typography tied to geometry, cached particle/liquid reveals and reference-matched multi-shot product lighting. Each remains `research-only` until its own package and visual evidence exist. Do not convert a list of fashionable effects into the default production language.
