"""Create a tiny deterministic Cycles scene for local/VIDEO STATION calibration."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def look_at(obj, point=(0.0, 0.0, 0.6)):
    obj.rotation_euler = ((Vector(point) - obj.location).to_track_quat("-Z", "Y").to_euler())


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--missing-image", action="store_true")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError("Calibration scene output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 192
    scene.render.resolution_y = 192
    scene.render.resolution_percentage = 100
    scene.frame_start = 1
    scene.frame_end = 3
    scene.frame_step = 1
    scene.render.film_transparent = False
    world = bpy.data.worlds.new("Calibration World")
    world.color = (0.012, 0.018, 0.03)
    scene.world = world

    bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, 0))
    plane = bpy.context.object
    ground = bpy.data.materials.new("Calibration Ground")
    ground.diffuse_color = (0.035, 0.05, 0.08, 1)
    ground.metallic = 0.15
    ground.roughness = 0.28
    plane.data.materials.append(ground)

    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=0.85, location=(0, 0, 1.0))
    hero = bpy.context.object
    hero.name = "Calibration Hero"
    material = bpy.data.materials.new("Calibration Copper")
    material.diffuse_color = (0.46, 0.085, 0.025, 1)
    material.metallic = 0.72
    material.roughness = 0.2
    hero.data.materials.append(material)
    hero.rotation_euler.z = 0
    hero.keyframe_insert(data_path="rotation_euler", frame=1)
    hero.rotation_euler.z = math.radians(24)
    hero.keyframe_insert(data_path="rotation_euler", frame=3)

    bpy.ops.object.light_add(type="AREA", location=(2.5, -2.0, 4.5))
    key = bpy.context.object
    key.name = "Key"
    key.data.energy = 900
    key.data.shape = "DISK"
    key.data.size = 3.0
    look_at(key)
    bpy.ops.object.light_add(type="AREA", location=(-3.0, 1.0, 2.7))
    rim = bpy.context.object
    rim.name = "Rim"
    rim.data.energy = 650
    rim.data.color = (0.16, 0.34, 1.0)
    rim.data.size = 2.0
    look_at(rim)

    bpy.ops.object.camera_add(location=(4.2, -4.2, 2.8))
    camera = bpy.context.object
    camera.data.lens = 58
    look_at(camera)
    scene.camera = camera
    if args.missing_image:
        missing_path = output.with_name("deliberately-missing-calibration-texture.png")
        generated = bpy.data.images.new("Temporary Calibration Asset", width=2, height=2)
        generated.filepath_raw = str(missing_path)
        generated.file_format = "PNG"
        generated.save()
        bpy.data.images.remove(generated)
        missing = bpy.data.images.load(str(missing_path), check_existing=False)
        missing.name = "Deliberately Missing Calibration Asset"
        missing.use_fake_user = True
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    if args.missing_image:
        missing_path.unlink()
    print(f"CALIBRATION_SCENE={output}")


if __name__ == "__main__":
    main()
