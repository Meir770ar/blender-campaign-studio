# Campaign technique library

`scripts/campaign_techniques.py` turns three bounded, reviewed inputs into editable Blender 5.1 scenes, recoverable 16-bit PNG sequences and content-bound manifests. These are shot-building tools, not automatic art direction or VFX certification.

## Techniques

- `planar-screen-replacement` applies a supplied, ordered four-corner track to local plate and insert images. It validates non-collapsed corners and complete frame coverage; it does not solve a track from footage, remove occlusions or infer reflections.
- `environment-product-integration` imports an exact GLB, normalizes and grounds it, then applies a reviewed floor/world/light/camera contract. It supplies contact, reflection and hierarchy controls; it does not infer a real plate's lighting, repair materials or certify brand color.
- `camera-projection-2_5d` places three to twelve deliberately separated PNG/WebP layers at ordered depths and performs a restrained camera move with a settled hold. It does not invent depth or license flattened artwork.

Start from the matching file in `templates/`, replace every `REPLACE:` value and define observable acceptance criteria. Render to a new revision:

```powershell
& 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe' --background --factory-startup --disable-autoexec --python-exit-code 1 --python scripts/campaign_techniques.py -- --spec PROJECT/planning/technique.json --out-dir PROJECT/renders/technique-v001 --render
```

Inspect the complete motion at normal speed and an ordered all-frame contact sheet. Record the media hash, frame range, aspect, engine, render time, each acceptance finding and known limitation. A successful manifest is `render-verified`; only an explicit visual report can promote it to `visually-verified`. Production use with a real approved brand/product shot is required for `production-proven`.

Normal fixtures cover all three techniques at 320x180/24 frames. The camera-projection boundary fixture covers 180x320/12 frames and deliberately uses oversized authored layers so the portrait camera does not reveal edges. Failed revisions remain evidence and are never overwritten.
