"""Blender 5.1 controlled product reveal with reflection-led motion.

Run this file inside Blender. Spec validation is deliberately importable in normal
Python so contract tests do not require Blender or render media.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


WEAK_INTENTS = {
    'cinematic', 'premium', 'viral', 'beautiful', 'professional', 'epic',
    'קולנועי', 'פרימיום', 'ויראלי', 'יפה', 'מקצועי', 'אפי',
}


def finite(value, name, minimum, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be finite and in [{minimum}, {maximum}]')
    return float(value)


def integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
    return value


def text(value, name, minimum=2):
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f'{name} must contain at least {minimum} characters')
    normalized = ' '.join(value.lower().strip().split()).strip('.!')
    if normalized in WEAK_INTENTS:
        raise ValueError(f'{name} must describe a visible narrative job, not an adjective')
    return value.strip()


def color(value, name):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f'{name} must be an RGBA list')
    return [finite(component, f'{name}[{index}]', 0, 1) for index, component in enumerate(value)]


def _object(spec, key):
    value = spec.get(key)
    if not isinstance(value, dict):
        raise ValueError(f'{key} must be an object')
    return value


def validate_spec(source_path):
    source = Path(source_path).resolve()
    spec = json.loads(source.read_text(encoding='utf-8-sig'))
    if not isinstance(spec, dict) or spec.get('version') != 1:
        raise ValueError('Spec must be an object with version=1')
    text(spec.get('shot_id'), 'shot_id', 1)
    text(spec.get('intent'), 'intent', 24)
    model_value = text(spec.get('model'), 'model', 1)
    if '://' in model_value:
        raise ValueError('model must be a local GLB path')
    model = Path(model_value)
    if not model.is_absolute():
        model = source.parent / model
    model = model.resolve()
    if not model.is_file() or model.suffix.lower() != '.glb':
        raise ValueError(f'model must resolve to an existing .glb file: {model}')

    width = integer(spec.get('width'), 'width', 64, 8192)
    height = integer(spec.get('height'), 'height', 64, 8192)
    if width % 2 or height % 2:
        raise ValueError('width and height must be even for video delivery')
    integer(spec.get('fps'), 'fps', 1, 120)
    frames = integer(spec.get('frames'), 'frames', 12, 3600)
    integer(spec.get('samples'), 'samples', 8, 4096)

    camera = _object(spec, 'camera')
    finite(camera.get('lens_mm'), 'camera.lens_mm', 24, 150)
    finite(camera.get('distance'), 'camera.distance', 3, 20)
    finite(camera.get('height_offset'), 'camera.height_offset', -2, 3)
    finite(camera.get('travel'), 'camera.travel', 0, 3)
    framing_padding = finite(camera.get('framing_padding', 1.18), 'camera.framing_padding', 1.02, 2)
    yaw_start = finite(camera.get('yaw_start_deg'), 'camera.yaw_start_deg', -45, 45)
    yaw_end = finite(camera.get('yaw_end_deg'), 'camera.yaw_end_deg', -45, 45)
    finite(camera.get('fstop'), 'camera.fstop', 1.4, 22)
    if abs(yaw_end - yaw_start) > 30:
        raise ValueError('camera yaw change must stay within 30 degrees for this controlled reveal')

    motion = _object(spec, 'motion')
    settle = finite(motion.get('settle_fraction'), 'motion.settle_fraction', 0.55, 0.9)
    if round(settle * (frames - 1)) >= frames - 2:
        raise ValueError('motion.settle_fraction must preserve at least two settled frames')
    if motion.get('sweep_side') not in {'left', 'right'}:
        raise ValueError('motion.sweep_side must be left or right')

    lighting = _object(spec, 'lighting')
    for name in ('key_energy', 'fill_energy', 'rim_energy', 'sweep_energy'):
        finite(lighting.get(name), f'lighting.{name}', 0, 100000)
    if lighting['key_energy'] <= lighting['fill_energy']:
        raise ValueError('lighting.key_energy must exceed fill_energy to preserve hierarchy')

    look = _object(spec, 'look')
    color(look.get('background_rgba'), 'look.background_rgba')
    finite(look.get('floor_roughness'), 'look.floor_roughness', 0.05, 1)
    finite(look.get('world_strength'), 'look.world_strength', 0, 1)
    if type(look.get('glare')) is not bool:
        raise ValueError('look.glare must be true or false')

    resolved = json.loads(json.dumps(spec, ensure_ascii=False))
    resolved['model'] = str(model)
    resolved['camera']['framing_padding'] = framing_padding
    return resolved


def _aim(obj, target, Vector):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def _material(bpy, name, rgba, roughness):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = rgba
    shader.inputs['Roughness'].default_value = roughness
    return material


def _area(bpy, Vector, name, location, energy, size, size_y, target, color_value=(1, 1, 1)):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy = energy
    data.shape = 'RECTANGLE'
    data.size = size
    data.size_y = size_y
    data.color = color_value
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    _aim(obj, target, Vector)
    return obj


def _cyclorama(bpy, background_rgba, roughness):
    width = 12.0
    profile = [(-6.0, 0.0), (1.25, 0.0), (1.75, 0.10), (2.15, 0.42),
               (2.42, 0.95), (2.52, 1.60), (2.52, 6.0)]
    vertices = []
    for x in (-width / 2, width / 2):
        vertices.extend((x, y, z) for y, z in profile)
    count = len(profile)
    faces = [(index, index + 1, count + index + 1, count + index) for index in range(count - 1)]
    mesh = bpy.data.meshes.new('Cyclorama mesh')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new('Cyclorama', mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(_material(bpy, 'Cyclorama material', background_rgba, roughness))
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    return obj


def _normalized_product(bpy, Vector, model):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=model)
    imported = set(bpy.data.objects) - before
    meshes = [obj for obj in imported if obj.type == 'MESH']
    if not meshes:
        raise ValueError('Product GLB contains no mesh objects')
    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    low = Vector([min(point[axis] for point in points) for axis in range(3)])
    high = Vector([max(point[axis] for point in points) for axis in range(3)])
    extent = high - low
    if max(extent) <= 1e-8:
        raise ValueError('Product GLB has zero spatial extent')
    scale = 2.0 / max(extent)
    root = bpy.data.objects.new('Product controlled root', None)
    bpy.context.collection.objects.link(root)
    for obj in imported:
        if obj.parent not in imported:
            world = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_world = world
    root.scale = (scale, scale, scale)
    root.location = (-(low.x + high.x) * scale / 2,
                     -(low.y + high.y) * scale / 2,
                     -low.z * scale)
    target = Vector((0, 0, extent.z * scale / 2))
    return root, target, {'normalized_width': extent.x * scale,
                          'normalized_depth': extent.y * scale,
                          'normalized_height': extent.z * scale}


def _smoothstep(value):
    value = max(0.0, min(1.0, value))
    return value * value * value * (value * (value * 6 - 15) + 10)


def build_scene(spec, output, preview=False, render=False):
    import bpy
    from mathutils import Vector

    if bpy.app.version[:2] != (5, 1):
        raise ValueError(f'premium_product.py is validated for Blender 5.1, found {bpy.app.version_string}')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = spec['samples']
    scene.cycles.use_denoising = True
    scene.render.resolution_x = spec['width']
    scene.render.resolution_y = spec['height']
    scene.render.resolution_percentage = 100
    scene.render.fps = spec['fps']
    scene.frame_start = 1
    scene.frame_end = spec['frames']
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '16'
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'None'

    world = scene.world or bpy.data.worlds.new('Product world')
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get('Background')
    background.inputs['Color'].default_value = tuple(spec['look']['background_rgba'])
    background.inputs['Strength'].default_value = spec['look']['world_strength']

    _cyclorama(bpy, tuple(spec['look']['background_rgba']), spec['look']['floor_roughness'])
    _, target, dimensions = _normalized_product(bpy, Vector, spec['model'])

    lighting = spec['lighting']
    _area(bpy, Vector, 'Shape key softbox', (3.2, -3.5, 4.2), lighting['key_energy'], 3.8, 5.2, target)
    _area(bpy, Vector, 'Controlled fill', (-3.8, -2.2, 2.6), lighting['fill_energy'], 4.8, 4.8, target)
    _area(bpy, Vector, 'Rear edge strip', (2.6, 2.0, 3.2), lighting['rim_energy'], 0.65, 4.0, target)
    side = -1 if spec['motion']['sweep_side'] == 'left' else 1
    sweep = _area(bpy, Vector, 'Animated reflection sweep', (side * 4.2, -0.7, 3.0),
                  lighting['sweep_energy'], 0.45, 4.5, target)

    camera_data = bpy.data.cameras.new('Directed product camera')
    camera_data.lens = spec['camera']['lens_mm']
    camera_data.sensor_fit = 'HORIZONTAL'
    camera_data.dof.use_dof = True
    camera_data.dof.aperture_fstop = spec['camera']['fstop']
    if hasattr(camera_data, 'show_composition_thirds'):
        camera_data.show_composition_thirds = True
    camera = bpy.data.objects.new('Directed product camera', camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    focus = bpy.data.objects.new('Product focus target', None)
    bpy.context.collection.objects.link(focus)
    focus.location = target
    camera_data.dof.focus_object = focus

    # Horizontal sensor fit makes vertical field of view aspect-dependent. Derive
    # a safe distance from the normalized bounds instead of trusting a preset
    # distance that can crop tall products in landscape delivery.
    aspect = spec['width'] / spec['height']
    half_sensor_width = camera_data.sensor_width / 2
    half_sensor_height = half_sensor_width / aspect
    vertical_distance = (dimensions['normalized_height'] / 2) * camera_data.lens / half_sensor_height
    horizontal_distance = (dimensions['normalized_width'] / 2) * camera_data.lens / half_sensor_width
    framing_distance = max(vertical_distance, horizontal_distance) * spec['camera']['framing_padding']
    base_distance = max(spec['camera']['distance'], framing_distance + spec['camera']['travel'] / 2)

    action_end = max(2, round((spec['frames'] - 1) * spec['motion']['settle_fraction']) + 1)
    for frame in range(1, spec['frames'] + 1):
        raw = min(1.0, (frame - 1) / max(1, action_end - 1))
        eased = _smoothstep(raw)
        angle = math.radians(spec['camera']['yaw_start_deg'] +
                             (spec['camera']['yaw_end_deg'] - spec['camera']['yaw_start_deg']) * eased)
        distance = base_distance + spec['camera']['travel'] * (0.5 - eased)
        camera.location = (distance * math.sin(angle), -distance * math.cos(angle),
                           target.z + spec['camera']['height_offset'])
        _aim(camera, target, Vector)
        camera.keyframe_insert(data_path='location', frame=frame)
        camera.keyframe_insert(data_path='rotation_euler', frame=frame)

        sweep_x = side * (4.2 - 6.2 * eased)
        sweep.location = (sweep_x, -0.7 + 0.25 * eased, 3.0)
        _aim(sweep, target, Vector)
        sweep.keyframe_insert(data_path='location', frame=frame)
        sweep.keyframe_insert(data_path='rotation_euler', frame=frame)

    if spec['look']['glare']:
        tree = bpy.data.node_groups.new('Restrained product composite', 'CompositorNodeTree')
        scene.compositing_node_group = tree
        scene.render.use_compositing = True
        nodes = tree.nodes
        layers = nodes.new('CompositorNodeRLayers')
        glare = nodes.new('CompositorNodeGlare')
        glare.inputs['Type'].default_value = 'Fog Glow'
        glare.inputs['Quality'].default_value = 'High'
        glare.inputs['Threshold'].default_value = 1.5
        glare.inputs['Strength'].default_value = 0.18
        glare.inputs['Size'].default_value = 0.35
        output_node = nodes.new('NodeGroupOutput')
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        tree.links.new(layers.outputs['Image'], glare.inputs['Image'])
        tree.links.new(glare.outputs['Image'], output_node.inputs['Image'])

    source_text = bpy.data.texts.new('premium-product-source.json')
    source_text.write(json.dumps(spec, ensure_ascii=False, indent=2))
    bpy.ops.file.pack_all()
    scene.frame_set(1)
    blend_path = output / 'premium-product.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    rendered = []
    if preview:
        preview_frames = sorted({1, action_end, spec['frames']})
        for frame in preview_frames:
            scene.frame_set(frame)
            path = output / f'preview-{frame:04d}.png'
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            rendered.append(str(path))
    if render:
        frames = output / 'frames'
        frames.mkdir()
        scene.render.filepath = str(frames / 'frame_')
        bpy.ops.render.render(animation=True)
        rendered.append(str(frames / 'frame_####.png'))
    return {'blend': str(blend_path), 'rendered': rendered, 'action_end_frame': action_end,
            'framing_distance': base_distance,
            'dimensions': dimensions, 'blender_version': bpy.app.version_string}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--out-dir', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--preview', action='store_true')
    mode.add_argument('--render', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    spec = validate_spec(args.spec)
    output = Path(args.out_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = build_scene(spec, output, preview=args.preview, render=args.render)
    manifest = {
        'version': 1,
        'technique': 'controlled-product-reveal',
        'spec': spec,
        **result,
        'review_required': True,
        'limits': 'A successful render does not certify brand accuracy, material truth, direction or premium quality.',
    }
    with (output / 'render-manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'manifest': str(output / 'render-manifest.json'), **result}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
