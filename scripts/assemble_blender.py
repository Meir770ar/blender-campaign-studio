"""Invoked by studio.py inside Blender; local VSE assembly and optional preview."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy

# Default amounts for the motion presets: a fraction of the frame (rise/slide/pan travel) or of the
# fitted scale (zoom). `motion_amount` in the plan overrides them per clip.
MOTION_AMOUNTS = {'fade-rise': .04, 'slide-down': .04, 'slide-left': .04, 'slide-right': .04,
                  'push-in': .06, 'zoom-in': .06, 'zoom-out': .06, 'pan-left': .04, 'pan-right': .04}


def keyframe(strip, field, value, frame):
    setattr(strip, field, value)
    strip.keyframe_insert(data_path=field, frame=frame)


def apply_motion(strip, clip, plan, start, duration, fade_in):
    """Motion presets on a visual strip (interpolation is Blender's default ease, which reads as a
    settled camera move rather than a mechanical slide)."""
    motion = clip.get('motion', 'none')
    if motion == 'none':
        return
    amount = clip.get('motion_amount', MOTION_AMOUNTS[motion])
    last = start + duration - 1
    settle = min(duration - 1, fade_in or max(1, round(plan['fps'] * 0.4)))
    width, height = plan['width'], plan['height']
    initial_x, initial_y = strip.transform.scale_x, strip.transform.scale_y
    if motion == 'fade-rise':                      # enters from below and settles
        keyframe(strip.transform, 'offset_y', -height * amount, start)
        keyframe(strip.transform, 'offset_y', 0, start + settle)
    elif motion == 'slide-down':                   # enters from above and settles
        keyframe(strip.transform, 'offset_y', height * amount, start)
        keyframe(strip.transform, 'offset_y', 0, start + settle)
    elif motion in ('slide-left', 'slide-right'):  # slide-left travels leftward into place (enters from the right)
        travel = width * amount * (1 if motion == 'slide-left' else -1)
        keyframe(strip.transform, 'offset_x', travel, start)
        keyframe(strip.transform, 'offset_x', 0, start + settle)
    elif motion in ('push-in', 'zoom-in', 'zoom-out'):
        near = (initial_x * (1 + amount), initial_y * (1 + amount))
        first, second = ((initial_x, initial_y), near) if motion != 'zoom-out' else (near, (initial_x, initial_y))
        for axis, a, b in (('scale_x', first[0], second[0]), ('scale_y', first[1], second[1])):
            keyframe(strip.transform, axis, a, start)
            keyframe(strip.transform, axis, b, last)
    elif motion in ('pan-left', 'pan-right'):
        # Overscale so the pan never reveals the frame edge, then travel across the whole clip.
        # pan-left: the camera travels left over the picture (the picture drifts right on screen).
        strip.transform.scale_x = initial_x * (1 + 2 * amount)
        strip.transform.scale_y = initial_y * (1 + 2 * amount)
        travel = width * amount
        a, b = (-travel, travel) if motion == 'pan-left' else (travel, -travel)
        keyframe(strip.transform, 'offset_x', a, start)
        keyframe(strip.transform, 'offset_x', b, last)


def apply_transform_keys(strip, keys, start):
    """Explicit keyframes: scale multiplies the fitted size, offsets are output pixels, rotation degrees.
    A field first mentioned in a later key starts from its rest value at the first key (so
    {"frame":0,"scale":1},{"frame":95,"offset_x":30} moves 0 -> 30 instead of holding 30 throughout);
    a field omitted from a later key holds its last keyed value through Blender's interpolation."""
    initial_x, initial_y = strip.transform.scale_x, strip.transform.scale_y
    animated = {field for key in keys for field in key if field != 'frame'}
    rest = {'scale': 1, 'offset_x': 0, 'offset_y': 0, 'rotation': 0}
    keys = [{**{field: rest[field] for field in animated}, **keys[0]}] + list(keys[1:])
    for key in keys:
        frame = start + key['frame']
        if 'scale' in key:
            keyframe(strip.transform, 'scale_x', initial_x * key['scale'], frame)
            keyframe(strip.transform, 'scale_y', initial_y * key['scale'], frame)
        for axis in ('offset_x', 'offset_y'):
            if axis in key:
                keyframe(strip.transform, axis, key[axis], frame)
        if 'rotation' in key:
            keyframe(strip.transform, 'rotation', math.radians(key['rotation']), frame)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    plan_path = Path(args.plan).resolve()
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    output = Path(args.out_dir).resolve()
    blend = output / 'project.blend'
    movie = output / 'preview.mp4'
    if blend.exists() or movie.exists():
        raise RuntimeError('Refusing to overwrite an existing Blender project or preview')
    if bpy.app.version[:2] != (5, 1):
        raise RuntimeError('This assembly helper is validated for Blender 5.1; verify API on another version before adapting')
    scene = bpy.context.scene
    scene.name = 'Campaign'
    scene.frame_start = 1
    scene.frame_end = plan['frames']
    scene.render.fps = plan['fps']
    scene.render.fps_base = 1.0
    scene.render.resolution_x = plan['width']
    scene.render.resolution_y = plan['height']
    scene.render.resolution_percentage = 100
    scene.render.use_sequencer = True
    scene.render.use_compositing = False
    # Use an explicit SDR transform for already graded footage and browser-rendered titles.
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    editor = scene.sequence_editor_create()
    collection = editor.strips
    for clip in plan['clips']:
        start, duration, channel = clip['start'], clip['duration'], clip['channel']
        kind = clip['kind']
        if kind == 'image':
            strip = collection.new_image(clip['id'], clip['path'], channel, start, fit_method='FIT')
            strip.frame_final_duration = duration
        elif kind == 'image-sequence':
            files = clip['sequence_files']
            strip = collection.new_image(clip['id'], files[0], channel, start, fit_method='FIT')
            for extra in files[1:]:
                strip.elements.append(Path(extra).name)
            strip.frame_final_duration = duration
            if len(strip.elements) != duration:
                raise RuntimeError(f'Image sequence element count mismatch for {clip["id"]}')
        else:
            first = clip.get('source_start', 0)
            if kind == 'movie':
                strip = collection.new_movie(clip['id'], clip['path'], channel, start - first, fit_method='FIT')
            else:
                strip = collection.new_sound(clip['id'], clip['path'], channel, start - first)
            strip.frame_offset_start = first
            strip.frame_final_duration = duration
        if int(strip.frame_final_start) != start or int(strip.frame_final_end) != start + duration:
            raise RuntimeError(f'Trim invariant failed for {clip["id"]}')
        if kind == 'sound':
            strip.volume = clip.get('volume', 1)
            for offset, volume in clip.get('volume_keys', []):
                keyframe(strip, 'volume', volume, start + offset)
            continue
        strip.blend_type = 'ALPHA_OVER'
        if kind in ('image', 'image-sequence'):
            strip.alpha_mode = 'STRAIGHT'
        opacity = clip.get('opacity', 1)
        strip.blend_alpha = opacity
        fade_in, fade_out = clip.get('fade_in', 0), clip.get('fade_out', 0)
        if fade_in:
            keyframe(strip, 'blend_alpha', 0, start)
            keyframe(strip, 'blend_alpha', opacity, start + fade_in)
        if fade_out:
            keyframe(strip, 'blend_alpha', opacity, start + duration - 1 - fade_out)
            keyframe(strip, 'blend_alpha', 0, start + duration - 1)
        apply_motion(strip, clip, plan, start, duration, fade_in)
        if clip.get('transform_keys'):
            apply_transform_keys(strip, clip['transform_keys'], start)
        if clip.get('text_source'):
            source = Path(clip['text_source'])
            text_block = bpy.data.texts.new(clip['id'] + '-text-source.json')
            text_block.write(source.read_text(encoding='utf-8-sig'))
    stored_plan = bpy.data.texts.new('production-plan.json')
    stored_plan.write(json.dumps(plan, ensure_ascii=False, indent=2))
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'MEDIUM'
    scene.render.ffmpeg.ffmpeg_preset = 'GOOD'
    scene.render.ffmpeg.audio_codec = 'AAC' if any(c['kind'] == 'sound' for c in plan['clips']) else 'NONE'
    scene.render.ffmpeg.audio_bitrate = 192
    scene.render.filepath = str(movie)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    if args.render:
        bpy.ops.render.render(animation=True)
    print('CAMPAIGN_ASSEMBLY_COMPLETE')


if __name__ == '__main__':
    main()
