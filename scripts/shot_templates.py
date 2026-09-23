"""Run inside Blender 5.1: real GLB product stage or depth-separated artwork parallax."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector


def finite(value, name, lo, hi):
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{name} must be in [{lo}, {hi}]')
    return value


def local(value, base, extensions):
    path = (base / value).resolve()
    if not path.is_file() or path.suffix.lower() not in extensions:
        raise ValueError(f'Invalid source asset: {path}')
    return path


def aim(obj, target):
    obj.rotation_euler = (Vector(target)-obj.location).to_track_quat('-Z', 'Y').to_euler()


def area(name, location, energy, size, target):
    data = bpy.data.lights.new(name, 'AREA'); data.energy = energy; data.shape = 'DISK'; data.size = size
    obj = bpy.data.objects.new(name, data); bpy.context.collection.objects.link(obj); obj.location = location
    aim(obj, target)


def camera(scene, spec):
    data = bpy.data.cameras.new('Directed camera'); data.lens = finite(spec.get('lens_mm', 50), 'lens_mm', 18, 150)
    obj = bpy.data.objects.new('Directed camera', data); bpy.context.collection.objects.link(obj)
    scene.camera = obj
    return obj


def product(scene, spec, base):
    model = local(spec['model'], base, {'.glb'})
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(model))
    imported = set(bpy.data.objects)-before
    meshes = [o for o in imported if o.type == 'MESH']
    if not meshes:
        raise ValueError('Product model contains no meshes')
    points = [o.matrix_world @ Vector(v) for o in meshes for v in o.bound_box]
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    if max(high-low) <= 0:
        raise ValueError('Product model has zero extent')
    scale = 2/max(high-low)
    root = bpy.data.objects.new('Product placement', None); bpy.context.collection.objects.link(root)
    for obj in imported:
        if obj.parent not in imported:
            world = obj.matrix_world.copy(); obj.parent = root; obj.matrix_world = world
    root.scale = (scale,)*3
    root.location = (-(low.x+high.x)*scale/2, -(low.y+high.y)*scale/2, -low.z*scale)
    target = Vector((0, 0, (high.z-low.z)*scale/2))
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0,0,-.005))
    floor = bpy.context.object; floor.name = 'Studio floor'
    material = bpy.data.materials.new('Studio neutral'); material.diffuse_color = tuple(spec.get('floor_rgba', [.07,.08,.10,1]))
    floor.data.materials.append(material)
    area('Key softbox', (3,-4,5), 900, 4, target)
    area('Fill softbox', (-4,-2,3), 450, 5, target)
    area('Rim strip', (2,3,4), 1100, 2, target)
    cam = camera(scene, spec)
    focus = bpy.data.objects.new('Product focus', None); bpy.context.collection.objects.link(focus); focus.location = target
    cam.data.dof.use_dof = True; cam.data.dof.focus_object = focus
    cam.data.dof.aperture_fstop = finite(spec.get('fstop', 5.6), 'fstop', 1.4, 22)
    radius = finite(spec.get('radius', 6), 'radius', 3, 15)
    first = finite(spec.get('orbit_start_deg', -20), 'orbit start', -180, 180)
    last = finite(spec.get('orbit_end_deg', 20), 'orbit end', -180, 180)
    # Sample the arc each frame; interpolation cannot bow through the product.
    for frame in range(1, scene.frame_end+1):
        t = (frame-1)/max(1, scene.frame_end-1); t = t*t*(3-2*t)
        angle = math.radians(first+(last-first)*t)
        cam.location = (radius*math.sin(angle), -radius*math.cos(angle), target.z+1.2)
        aim(cam, target); cam.keyframe_insert(data_path='location', frame=frame); cam.keyframe_insert(data_path='rotation_euler', frame=frame)
    scene.view_settings.view_transform = 'AgX'


def parallax(scene, spec, base):
    layers = spec.get('layers')
    if not isinstance(layers, list) or len(layers) < 2:
        raise ValueError('Parallax requires at least two deliberately separated image layers')
    aspect = scene.render.resolution_x/scene.render.resolution_y
    for i, layer in enumerate(layers):
        image = bpy.data.images.load(str(local(layer['image'], base, {'.png', '.webp'})), check_existing=True)
        depth = finite(layer.get('depth', 0), 'depth', -3, 3)
        width = finite(layer.get('width', 10), 'layer width', 1, 40)
        bpy.ops.mesh.primitive_plane_add(size=2, location=(finite(layer.get('x',0),'layer x',-10,10),
                 finite(layer.get('y',0),'layer y',-10,10), depth))
        obj = bpy.context.object; obj.name = layer.get('name', f'Artwork {i+1}')
        obj.scale = (width/2, width*image.size[1]/image.size[0]/2, 1)
        mat = bpy.data.materials.new(obj.name); mat.use_nodes = True
        nodes = mat.node_tree.nodes; nodes.clear()
        texture = nodes.new('ShaderNodeTexImage'); texture.image = image
        emission = nodes.new('ShaderNodeEmission'); transparent = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader'); out = nodes.new('ShaderNodeOutputMaterial')
        links = mat.node_tree.links
        links.new(texture.outputs['Color'], emission.inputs['Color'])
        links.new(texture.outputs['Alpha'], mix.inputs[0]); links.new(transparent.outputs[0], mix.inputs[1]); links.new(emission.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs['Surface']); obj.data.materials.append(mat)
    cam = camera(scene, spec)
    distance = finite(spec.get('camera_distance', 12), 'camera_distance', 6, 30)
    travel = finite(spec.get('travel', .5), 'travel', -.9, .9)
    for frame, x in [(1, -travel/2), (scene.frame_end, travel/2)]:
        cam.location = (x, 0, distance)
        # Artwork planes lie in XY: preserve world-Y up, including an exact overhead view.
        cam.rotation_euler = (0, math.atan2(x, distance), 0)
        cam.keyframe_insert(data_path='location', frame=frame); cam.keyframe_insert(data_path='rotation_euler', frame=frame)
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'


def main():
    p = argparse.ArgumentParser(); p.add_argument('--spec', required=True); p.add_argument('--out-dir', required=True)
    p.add_argument('--render', action='store_true'); a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    source = Path(a.spec).resolve(); spec = json.loads(source.read_text(encoding='utf-8-sig'))
    if bpy.app.version[:2] != (5,1): raise ValueError('Templates validated for Blender 5.1')
    output = Path(a.out_dir).resolve(); output.mkdir(parents=True, exist_ok=False)
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'; scene.cycles.samples = int(finite(spec.get('samples', 32), 'samples', 8, 1024))
    scene.cycles.use_denoising = True; scene.render.film_transparent = False
    scene.render.resolution_x = int(finite(spec.get('width', 1920), 'width', 16, 8192))
    scene.render.resolution_y = int(finite(spec.get('height', 1080), 'height', 16, 8192))
    if scene.render.resolution_x%2 or scene.render.resolution_y%2: raise ValueError('Even video dimensions required')
    scene.render.resolution_percentage = 100; scene.render.fps = int(finite(spec.get('fps', 24),'fps',1,120))
    scene.frame_start = 1; scene.frame_end = int(finite(spec.get('frames', 72),'frames',2,3600))
    scene.world.color = (.04,.04,.04)
    if spec['template'] == 'product-stage': product(scene,spec,source.parent)
    elif spec['template'] == 'artwork-parallax': parallax(scene,spec,source.parent)
    else: raise ValueError('template must be product-stage or artwork-parallax')
    block = bpy.data.texts.new('shot-source.json'); block.write(json.dumps(spec,ensure_ascii=False,indent=2))
    bpy.ops.file.pack_all()
    scene.render.image_settings.media_type = 'VIDEO'; scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'; scene.render.ffmpeg.codec = 'H264'; scene.render.ffmpeg.constant_rate_factor = 'HIGH'
    scene.render.filepath = str(output/'shot.mp4'); scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(output/'shot.blend'))
    if a.render: bpy.ops.render.render(animation=True)


if __name__ == '__main__': main()
