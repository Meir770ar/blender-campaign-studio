"""Reusable Blender 5.1 campaign techniques with importable bounded contracts.

The module is importable in normal Python for contract tests. Scene construction is
loaded only inside Blender. It applies supplied creative/track decisions; it does not
auto-track footage, infer lighting from a plate or separate a flat image into layers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time


TECHNIQUES = {
    "planar-screen-replacement",
    "environment-product-integration",
    "camera-projection-2_5d",
}
WEAK_INTENTS = {
    "cinematic", "premium", "viral", "beautiful", "professional", "epic",
    "קולנועי", "פרימיום", "ויראלי", "יפה", "מקצועי", "אפי",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def finite(value, name, minimum, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be finite and in [{minimum}, {maximum}]")
    return float(value)


def integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def text(value, name, minimum=2):
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f"{name} must contain at least {minimum} characters")
    normalized = " ".join(value.lower().strip().split()).strip(".!?")
    if normalized in WEAK_INTENTS:
        raise ValueError(f"{name} must describe a visible narrative job, not an adjective")
    return value.strip()


def local_file(value, name, base, extensions):
    value = text(value, name, 1)
    if "://" in value:
        raise ValueError(f"{name} must be a local file")
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.is_file() or path.suffix.lower() not in extensions:
        allowed = ", ".join(sorted(extensions))
        raise ValueError(f"{name} must resolve to an existing {allowed} file: {path}")
    return str(path)


def rgba(value, name):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{name} must be an RGBA list")
    return [finite(item, f"{name}[{index}]", 0, 1) for index, item in enumerate(value)]


def rgb(value, name):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} must be an RGB list")
    return [finite(item, f"{name}[{index}]", 0, 1) for index, item in enumerate(value)]


def object_value(spec, key):
    value = spec.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def common_contract(spec):
    if not isinstance(spec, dict) or spec.get("version") != 1:
        raise ValueError("Spec must be an object with version=1")
    technique = spec.get("technique")
    if technique not in TECHNIQUES:
        raise ValueError(f"technique must be one of {sorted(TECHNIQUES)}")
    text(spec.get("shot_id"), "shot_id", 1)
    text(spec.get("intent"), "intent", 24)
    width = integer(spec.get("width"), "width", 64, 8192)
    height = integer(spec.get("height"), "height", 64, 8192)
    if width % 2 or height % 2:
        raise ValueError("width and height must be even for video delivery")
    integer(spec.get("fps"), "fps", 1, 120)
    integer(spec.get("frames"), "frames", 12, 3600)
    integer(spec.get("samples"), "samples", 1, 4096)
    acceptance = spec.get("acceptance")
    if not isinstance(acceptance, list) or not acceptance:
        raise ValueError("acceptance must be a nonempty list")
    seen = set()
    for index, item in enumerate(acceptance):
        if not isinstance(item, dict):
            raise ValueError(f"acceptance[{index}] must be an object")
        identifier = text(item.get("id"), f"acceptance[{index}].id", 2)
        if identifier in seen:
            raise ValueError("acceptance ids must be unique")
        seen.add(identifier)
        text(item.get("check"), f"acceptance[{index}].check", 16)
        text(item.get("evidence"), f"acceptance[{index}].evidence", 16)


def point(value, name):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must be [x, y]")
    return [finite(value[0], f"{name}[0]", 0, 1), finite(value[1], f"{name}[1]", 0, 1)]


def checked_corners(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    keys = ("upper_left", "upper_right", "lower_left", "lower_right")
    corners = {key: point(value.get(key), f"{name}.{key}") for key in keys}
    if corners["upper_left"][0] >= corners["upper_right"][0] or corners["lower_left"][0] >= corners["lower_right"][0]:
        raise ValueError(f"{name} left corners must remain left of right corners")
    if corners["upper_left"][1] <= corners["lower_left"][1] or corners["upper_right"][1] <= corners["lower_right"][1]:
        raise ValueError(f"{name} upper corners must remain above lower corners")
    ordered = [corners["upper_left"], corners["upper_right"], corners["lower_right"], corners["lower_left"]]
    area = abs(sum(ordered[i][0] * ordered[(i + 1) % 4][1] - ordered[(i + 1) % 4][0] * ordered[i][1]
                   for i in range(4))) / 2
    if area < 0.01:
        raise ValueError(f"{name} quadrilateral is collapsed or too small")
    return corners


def validate_screen(spec, source):
    spec["plate"] = local_file(spec.get("plate"), "plate", source.parent, IMAGE_EXTENSIONS)
    spec["replacement"] = local_file(spec.get("replacement"), "replacement", source.parent, IMAGE_EXTENSIONS)
    spec["insert_opacity"] = finite(spec.get("insert_opacity", 1), "insert_opacity", 0.05, 1)
    track = spec.get("track")
    if not isinstance(track, list) or len(track) < 2:
        raise ValueError("track must contain at least first and last corner keyframes")
    previous = 0
    normalized = []
    for index, entry in enumerate(track):
        if not isinstance(entry, dict):
            raise ValueError(f"track[{index}] must be an object")
        frame = integer(entry.get("frame"), f"track[{index}].frame", 1, spec["frames"])
        if frame <= previous:
            raise ValueError("track frames must be strictly increasing")
        previous = frame
        normalized.append({"frame": frame, "corners": checked_corners(entry.get("corners"), f"track[{index}].corners")})
    if normalized[0]["frame"] != 1 or normalized[-1]["frame"] != spec["frames"]:
        raise ValueError("track must cover frame 1 through the final frame")
    spec["track"] = normalized


def validate_product(spec, source):
    spec["model"] = local_file(spec.get("model"), "model", source.parent, {".glb"})
    environment = object_value(spec, "environment")
    environment["background_rgba"] = rgba(environment.get("background_rgba"), "environment.background_rgba")
    environment["floor_rgba"] = rgba(environment.get("floor_rgba"), "environment.floor_rgba")
    environment["floor_roughness"] = finite(environment.get("floor_roughness"), "environment.floor_roughness", 0.05, 1)
    environment["floor_metallic"] = finite(environment.get("floor_metallic"), "environment.floor_metallic", 0, 0.5)
    environment["world_strength"] = finite(environment.get("world_strength"), "environment.world_strength", 0, 1)
    lighting = object_value(spec, "lighting")
    text(lighting.get("match_reference"), "lighting.match_reference", 16)
    lighting["key_azimuth_deg"] = finite(lighting.get("key_azimuth_deg"), "lighting.key_azimuth_deg", -180, 180)
    lighting["key_elevation_deg"] = finite(lighting.get("key_elevation_deg"), "lighting.key_elevation_deg", 5, 85)
    lighting["key_energy"] = finite(lighting.get("key_energy"), "lighting.key_energy", 1, 100000)
    lighting["fill_energy"] = finite(lighting.get("fill_energy"), "lighting.fill_energy", 0, 100000)
    if lighting["fill_energy"] >= lighting["key_energy"]:
        raise ValueError("lighting.fill_energy must remain below key_energy for this matched hierarchy")
    lighting["key_size"] = finite(lighting.get("key_size"), "lighting.key_size", 0.1, 20)
    lighting["key_rgb"] = rgb(lighting.get("key_rgb"), "lighting.key_rgb")
    camera = object_value(spec, "camera")
    camera["lens_mm"] = finite(camera.get("lens_mm"), "camera.lens_mm", 24, 150)
    camera["distance"] = finite(camera.get("distance"), "camera.distance", 3, 20)
    camera["height_offset"] = finite(camera.get("height_offset"), "camera.height_offset", -1, 3)
    camera["travel_x"] = finite(camera.get("travel_x", 0), "camera.travel_x", -1, 1)
    camera["fstop"] = finite(camera.get("fstop"), "camera.fstop", 1.4, 22)
    motion = object_value(spec, "motion")
    motion["settle_fraction"] = finite(motion.get("settle_fraction"), "motion.settle_fraction", 0.5, 0.9)


def validate_projection(spec, source):
    layers = spec.get("layers")
    if not isinstance(layers, list) or not 3 <= len(layers) <= 12:
        raise ValueError("layers must contain 3 to 12 deliberately separated images")
    names = set()
    previous_depth = -math.inf
    normalized = []
    for index, raw in enumerate(layers):
        if not isinstance(raw, dict):
            raise ValueError(f"layers[{index}] must be an object")
        layer = dict(raw)
        name = text(layer.get("name"), f"layers[{index}].name", 2)
        if name in names:
            raise ValueError("layer names must be unique")
        names.add(name)
        layer["image"] = local_file(layer.get("image"), f"layers[{index}].image", source.parent, {".png", ".webp"})
        layer["depth"] = finite(layer.get("depth"), f"layers[{index}].depth", -4, 4)
        if layer["depth"] <= previous_depth:
            raise ValueError("layer depths must strictly increase from background to foreground")
        previous_depth = layer["depth"]
        layer["width"] = finite(layer.get("width"), f"layers[{index}].width", 2, 30)
        layer["x"] = finite(layer.get("x", 0), f"layers[{index}].x", -5, 5)
        layer["y"] = finite(layer.get("y", 0), f"layers[{index}].y", -5, 5)
        normalized.append(layer)
    spec["layers"] = normalized
    camera = object_value(spec, "camera")
    camera["lens_mm"] = finite(camera.get("lens_mm"), "camera.lens_mm", 24, 120)
    camera["distance"] = finite(camera.get("distance"), "camera.distance", 6, 30)
    camera["travel_x"] = finite(camera.get("travel_x"), "camera.travel_x", -2, 2)
    if camera["distance"] <= normalized[-1]["depth"] + 2:
        raise ValueError("camera.distance must remain at least two units in front of the nearest layer")
    motion = object_value(spec, "motion")
    motion["settle_fraction"] = finite(motion.get("settle_fraction"), "motion.settle_fraction", 0.5, 0.9)


def validate_spec(source_path):
    source = Path(source_path).resolve()
    spec = json.loads(source.read_text(encoding="utf-8-sig"))
    common_contract(spec)
    resolved = json.loads(json.dumps(spec, ensure_ascii=False))
    if resolved["technique"] == "planar-screen-replacement":
        validate_screen(resolved, source)
    elif resolved["technique"] == "environment-product-integration":
        validate_product(resolved, source)
    else:
        validate_projection(resolved, source)
    return resolved


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_assets(spec):
    if spec["technique"] == "planar-screen-replacement":
        return [spec["plate"], spec["replacement"]]
    if spec["technique"] == "environment-product-integration":
        return [spec["model"]]
    return [layer["image"] for layer in spec["layers"]]


def smoothstep(value):
    value = max(0.0, min(1.0, value))
    return value * value * value * (value * (value * 6 - 15) + 10)


def configure_scene(bpy, spec, engine):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = engine
    if engine == "CYCLES":
        scene.cycles.samples = spec["samples"]
        scene.cycles.use_denoising = True
    else:
        scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_x = spec["width"]
    scene.render.resolution_y = spec["height"]
    scene.render.resolution_percentage = 100
    scene.render.fps = spec["fps"]
    scene.frame_start = 1
    scene.frame_end = spec["frames"]
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "16"
    scene.render.film_transparent = False
    world = scene.world or bpy.data.worlds.new("Technique world")
    scene.world = world
    return scene


def aim(obj, target, Vector):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def dummy_camera(bpy, scene):
    data = bpy.data.cameras.new("Composite camera")
    data.type = "ORTHO"
    obj = bpy.data.objects.new("Composite camera", data)
    bpy.context.collection.objects.link(obj)
    obj.location = (0, 0, 10)
    scene.camera = obj


def interpolate_track(track, frame):
    for left, right in zip(track, track[1:]):
        if left["frame"] <= frame <= right["frame"]:
            span = right["frame"] - left["frame"]
            amount = 0 if not span else (frame - left["frame"]) / span
            return {key: [left["corners"][key][axis] +
                          (right["corners"][key][axis] - left["corners"][key][axis]) * amount
                          for axis in range(2)] for key in left["corners"]}
    return track[-1]["corners"]


def build_screen(bpy, spec):
    scene = configure_scene(bpy, spec, "BLENDER_EEVEE")
    dummy_camera(bpy, scene)
    plate = bpy.data.images.load(spec["plate"], check_existing=False)
    replacement = bpy.data.images.load(spec["replacement"], check_existing=False)
    if tuple(plate.size) != (spec["width"], spec["height"]):
        raise ValueError("plate pixel dimensions must match width and height")
    tree = bpy.data.node_groups.new("Tracked screen composite", "CompositorNodeTree")
    scene.compositing_node_group = tree
    scene.render.use_compositing = True
    nodes = tree.nodes
    plate_node = nodes.new("CompositorNodeImage")
    plate_node.name = "Original plate"
    plate_node.image = plate
    insert_node = nodes.new("CompositorNodeImage")
    insert_node.name = "Replacement artwork"
    insert_node.image = replacement
    pin = nodes.new("CompositorNodeCornerPin")
    pin.name = "Supplied planar corner track"
    over = nodes.new("CompositorNodeAlphaOver")
    over.inputs["Factor"].default_value = spec["insert_opacity"]
    output = nodes.new("NodeGroupOutput")
    tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    tree.links.new(insert_node.outputs["Image"], pin.inputs["Image"])
    tree.links.new(plate_node.outputs["Image"], over.inputs["Background"])
    tree.links.new(pin.outputs["Image"], over.inputs["Foreground"])
    tree.links.new(over.outputs["Image"], output.inputs["Image"])
    socket_names = {
        "upper_left": "Upper Left", "upper_right": "Upper Right",
        "lower_left": "Lower Left", "lower_right": "Lower Right",
    }
    for frame in range(1, spec["frames"] + 1):
        corners = interpolate_track(spec["track"], frame)
        for key, socket_name in socket_names.items():
            pin.inputs[socket_name].default_value = corners[key]
            pin.inputs[socket_name].keyframe_insert(data_path="default_value", frame=frame)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    return scene, spec["frames"]


def material(bpy, name, color_value, roughness, metallic=0):
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    shader = result.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color_value
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    return result


def area_light(bpy, Vector, name, location, energy, size, color_value, target):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color_value
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    aim(obj, target, Vector)
    return obj


def normalized_product(bpy, Vector, model):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=model)
    imported = set(bpy.data.objects) - before
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        raise ValueError("Product GLB contains no mesh objects")
    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    low = Vector([min(point[axis] for point in points) for axis in range(3)])
    high = Vector([max(point[axis] for point in points) for axis in range(3)])
    extent = high - low
    if max(extent) <= 1e-8:
        raise ValueError("Product GLB has zero spatial extent")
    scale = 2 / max(extent)
    root = bpy.data.objects.new("Integrated product root", None)
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
    return Vector((0, 0, extent.z * scale / 2)), extent * scale


def cyclorama(bpy, environment):
    width = 14
    profile = [(-7, 0), (1.5, 0), (2.0, .12), (2.5, .55), (2.75, 1.2), (2.8, 7)]
    vertices = []
    for x in (-width / 2, width / 2):
        vertices.extend((x, y, z) for y, z in profile)
    count = len(profile)
    faces = [(index, index + 1, count + index + 1, count + index) for index in range(count - 1)]
    mesh = bpy.data.meshes.new("Matched environment mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Matched floor and background", mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material(bpy, "Matched environment material",
                                       tuple(environment["floor_rgba"]), environment["floor_roughness"],
                                       environment["floor_metallic"]))
    for polygon in mesh.polygons:
        polygon.use_smooth = True


def build_product(bpy, Vector, spec):
    scene = configure_scene(bpy, spec, "CYCLES")
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "None"
    environment = spec["environment"]
    scene.world.use_nodes = True
    world_background = scene.world.node_tree.nodes.get("Background")
    world_background.inputs["Color"].default_value = tuple(environment["background_rgba"])
    world_background.inputs["Strength"].default_value = environment["world_strength"]
    cyclorama(bpy, environment)
    target, dimensions = normalized_product(bpy, Vector, spec["model"])
    lighting = spec["lighting"]
    azimuth = math.radians(lighting["key_azimuth_deg"])
    elevation = math.radians(lighting["key_elevation_deg"])
    radius = 6
    key_location = (radius * math.cos(elevation) * math.cos(azimuth),
                    radius * math.cos(elevation) * math.sin(azimuth),
                    target.z + radius * math.sin(elevation))
    area_light(bpy, Vector, "Matched key source", key_location, lighting["key_energy"],
               lighting["key_size"], tuple(lighting["key_rgb"]), target)
    fill_location = (-key_location[0] * .65, -3.5, target.z + 2.2)
    area_light(bpy, Vector, "Subordinate environment fill", fill_location, lighting["fill_energy"],
               lighting["key_size"] * 1.4, tuple(lighting["key_rgb"]), target)
    camera_data = bpy.data.cameras.new("Environment integration camera")
    camera_data.lens = spec["camera"]["lens_mm"]
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.dof.use_dof = True
    camera_data.dof.aperture_fstop = spec["camera"]["fstop"]
    focus = bpy.data.objects.new("Product focus", None)
    bpy.context.collection.objects.link(focus)
    focus.location = target
    camera_data.dof.focus_object = focus
    camera = bpy.data.objects.new("Environment integration camera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    action_end = max(2, round((spec["frames"] - 1) * spec["motion"]["settle_fraction"]) + 1)
    base_distance = spec["camera"]["distance"]
    for frame in range(1, spec["frames"] + 1):
        amount = smoothstep(min(1, (frame - 1) / max(1, action_end - 1)))
        x = spec["camera"]["travel_x"] * (amount - .5)
        camera.location = (x, -base_distance, target.z + spec["camera"]["height_offset"])
        aim(camera, target, Vector)
        camera.keyframe_insert(data_path="location", frame=frame)
        camera.keyframe_insert(data_path="rotation_euler", frame=frame)
    return scene, action_end, {"normalized_dimensions": list(dimensions)}


def image_material(bpy, image, name):
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    nodes = result.node_tree.nodes
    nodes.clear()
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    emission = nodes.new("ShaderNodeEmission")
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    output = nodes.new("ShaderNodeOutputMaterial")
    links = result.node_tree.links
    links.new(texture.outputs["Color"], emission.inputs["Color"])
    links.new(texture.outputs["Alpha"], mix.inputs[0])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(emission.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], output.inputs["Surface"])
    return result


def build_projection(bpy, spec):
    scene = configure_scene(bpy, spec, "BLENDER_EEVEE")
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    for layer in spec["layers"]:
        image = bpy.data.images.load(layer["image"], check_existing=False)
        bpy.ops.mesh.primitive_plane_add(size=2, location=(layer["x"], layer["y"], layer["depth"]))
        obj = bpy.context.object
        obj.name = layer["name"]
        obj.scale = (layer["width"] / 2, layer["width"] * image.size[1] / image.size[0] / 2, 1)
        obj.data.materials.append(image_material(bpy, image, f"{layer['name']} material"))
    camera_data = bpy.data.cameras.new("2.5D projection camera")
    camera_data.lens = spec["camera"]["lens_mm"]
    camera_data.sensor_fit = "HORIZONTAL"
    camera = bpy.data.objects.new("2.5D projection camera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    action_end = max(2, round((spec["frames"] - 1) * spec["motion"]["settle_fraction"]) + 1)
    distance = spec["camera"]["distance"]
    for frame in range(1, spec["frames"] + 1):
        amount = smoothstep(min(1, (frame - 1) / max(1, action_end - 1)))
        x = spec["camera"]["travel_x"] * (amount - .5)
        camera.location = (x, 0, distance)
        camera.rotation_euler = (0, math.atan2(x, distance), 0)
        camera.keyframe_insert(data_path="location", frame=frame)
        camera.keyframe_insert(data_path="rotation_euler", frame=frame)
    return scene, action_end


def render_scene(bpy, spec, output, mode):
    if bpy.app.version[:2] != (5, 1):
        raise ValueError(f"campaign_techniques.py is validated for Blender 5.1, found {bpy.app.version_string}")
    if spec["technique"] == "planar-screen-replacement":
        scene, action_end = build_screen(bpy, spec)
        details = {}
    elif spec["technique"] == "environment-product-integration":
        from mathutils import Vector
        scene, action_end, details = build_product(bpy, Vector, spec)
    else:
        scene, action_end = build_projection(bpy, spec)
        details = {}
    source_text = bpy.data.texts.new("campaign-technique-source.json")
    source_text.write(json.dumps(spec, ensure_ascii=False, indent=2))
    bpy.ops.file.pack_all()
    scene.frame_set(1)
    blend = output / "technique.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    rendered = []
    started = time.perf_counter()
    if mode == "preview":
        for frame in sorted({1, action_end, spec["frames"]}):
            scene.frame_set(frame)
            target = output / f"preview-{frame:04d}.png"
            scene.render.filepath = str(target)
            bpy.ops.render.render(write_still=True)
            rendered.append(str(target))
    elif mode == "render":
        frames = output / "frames"
        frames.mkdir()
        scene.render.filepath = str(frames / "frame_")
        bpy.ops.render.render(animation=True)
        files = sorted(frames.glob("frame_*.png"))
        if len(files) != spec["frames"]:
            raise ValueError(f"Expected {spec['frames']} rendered frames, found {len(files)}")
        rendered = [str(path) for path in files]
    elapsed = time.perf_counter() - started
    return {"blend": str(blend), "rendered": rendered, "action_end_frame": action_end,
            "render_seconds": elapsed, "blender_version": bpy.app.version_string, **details}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out-dir", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    spec = validate_spec(args.spec)
    output = Path(args.out_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    import bpy
    result = render_scene(bpy, spec, output, "render" if args.render else "preview" if args.preview else "scene")
    manifest = {
        "version": 1,
        "technique": spec["technique"],
        "state": "render-verified" if args.render else "implemented",
        "spec": spec,
        "assets": [{"path": path, "sha256": sha256_file(path)} for path in source_assets(spec)],
        **result,
        "review_required": True,
        "limits": "Render success does not certify tracking, light match, layer separation, rights or artistic quality.",
    }
    manifest_path = output / "render-manifest.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"manifest": str(manifest_path), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
