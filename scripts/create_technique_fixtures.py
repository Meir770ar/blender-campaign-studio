"""Create original local assets for campaign-technique render verification."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

import bpy


WIDTH = 320
HEIGHT = 180


def image_file(output, name, pixel_function):
    image = bpy.data.images.new(name, width=WIDTH, height=HEIGHT, alpha=True)
    pixels = []
    for y in range(HEIGHT):
        v = y / max(1, HEIGHT - 1)
        for x in range(WIDTH):
            u = x / max(1, WIDTH - 1)
            pixels.extend(pixel_function(u, v))
    image.pixels.foreach_set(pixels)
    path = output / f"{name}.png"
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return path


def plate(u, v):
    base = (0.025 + .045 * v, 0.045 + .08 * v, 0.09 + .12 * v, 1)
    on_screen = .20 <= u <= .80 and .24 <= v <= .78
    on_border = .18 <= u <= .82 and .21 <= v <= .81
    on_desk = v < .18
    if on_screen:
        return (.012, .018, .03, 1)
    if on_border:
        return (.12, .15, .2, 1)
    if on_desk:
        return (.065 + .03 * u, .045, .04, 1)
    return base


def replacement(u, v):
    stripe = .12 if int((u + v) * 8) % 2 else 0
    glow = max(0, 1 - math.hypot(u - .5, v - .5) * 2)
    return (.92 - .45 * v, .22 + .5 * u + stripe, .08 + .75 * v + .15 * glow, 1)


def projection_background(u, v):
    horizon = max(0, 1 - abs(v - .45) * 3)
    return (.025 + .18 * horizon, .05 + .12 * v, .11 + .32 * v, 1)


def projection_middle(u, v):
    distance = math.hypot((u - .53) / .8, v - .5)
    if distance < .24:
        edge = min(1, max(0, (.24 - distance) * 30))
        return (.95, .28 + .35 * v, .08, edge)
    return (0, 0, 0, 0)


def projection_foreground(u, v):
    left = u < .18 + .08 * v
    right = u > .86 - .05 * v
    if left or right:
        fade = min(1, max(0, (v - .05) * 5))
        return (.02, .16 + .28 * v, .34 + .45 * v, .92 * fade)
    return (0, 0, 0, 0)


def fixture_product(output):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    material = bpy.data.materials.new("Fixture cobalt material")
    material.diffuse_color = (.025, .16, .48, 1)
    material.metallic = .25
    material.roughness = .22
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 1.05))
    body = bpy.context.object
    body.name = "Original fixture product body"
    body.scale = (.78, .42, 1.05)
    body.data.materials.append(material)
    bevel = body.modifiers.new("Readable product edges", "BEVEL")
    bevel.width = .12
    bevel.segments = 5
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    label_material = bpy.data.materials.new("Fixture warm label")
    label_material.diffuse_color = (.95, .32, .08, 1)
    label_material.metallic = .05
    label_material.roughness = .34
    bpy.ops.mesh.primitive_cube_add(location=(0, -.435, 1.05))
    label = bpy.context.object
    label.name = "Original fixture front label"
    label.scale = (.5, .025, .3)
    label.data.materials.append(label_material)
    cap_material = bpy.data.materials.new("Fixture cap")
    cap_material.diffuse_color = (.035, .045, .065, 1)
    cap_material.metallic = .5
    cap_material.roughness = .18
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=.52, depth=.22, location=(0, 0, 2.2))
    cap = bpy.context.object
    cap.name = "Original fixture cap"
    cap.data.materials.append(cap_material)
    bpy.ops.object.select_all(action="SELECT")
    path = output / "product-fixture.glb"
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_apply=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    output = Path(args.out_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    files = [
        image_file(output, "screen-plate", plate),
        image_file(output, "screen-insert", replacement),
        image_file(output, "projection-background", projection_background),
        image_file(output, "projection-middle", projection_middle),
        image_file(output, "projection-foreground", projection_foreground),
        fixture_product(output),
    ]
    print("\n".join(str(path) for path in files))


if __name__ == "__main__":
    main()
