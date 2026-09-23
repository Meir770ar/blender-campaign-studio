"""Create a self-contained Cycles render bundle without modifying the source .blend."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import bpy


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + f".writing-{os.getpid()}")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def external_path(block, value):
    if not value or value.startswith("<"):
        return None
    if "<UDIM>" in value or "####" in value:
        raise ValueError(f"Tiled or sequence asset requires explicit baking before remote render: {block.name}")
    return Path(bpy.path.abspath(value, library=getattr(block, "library", None))).resolve()


def collect_dependencies():
    problems = []
    dependencies = []

    if bpy.data.libraries:
        names = ", ".join(library.name for library in bpy.data.libraries)
        problems.append(f"linked libraries are not supported in render bundle v1: {names}")

    for font in bpy.data.fonts:
        path = external_path(font, font.filepath)
        if path:
            problems.append(
                f"external font is not copied automatically ({font.name}); convert it to curves or provision the licensed font explicitly"
            )

    for scene in bpy.data.scenes:
        editor = scene.sequence_editor
        strips = getattr(editor, "strips", None) or getattr(editor, "sequences_all", ()) if editor else ()
        file_strips = [strip.name for strip in strips if getattr(strip, "type", "") in {"MOVIE", "SOUND", "IMAGE"}]
        if file_strips:
            problems.append(f"file-backed VSE strips must stay in the local finishing project: {', '.join(file_strips)}")

    if bpy.data.movieclips:
        problems.append("movie clips cannot be packed safely for render bundle v1")
    if bpy.data.cache_files:
        problems.append("external cache files must be baked or externalized before remote render")

    collections = (
        ("image", bpy.data.images, "filepath"),
        ("sound", bpy.data.sounds, "filepath"),
        ("volume", bpy.data.volumes, "filepath"),
    )
    for kind, blocks, attribute in collections:
        for block in blocks:
            if kind == "image" and (block.source in {"GENERATED", "VIEWER"} or block.packed_file):
                continue
            path = external_path(block, getattr(block, attribute, ""))
            if not path:
                continue
            if not path.is_file():
                problems.append(f"missing {kind} asset: {block.name}")
                continue
            dependencies.append({
                "kind": kind,
                "name": block.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })

    if problems:
        raise ValueError("; ".join(problems))
    return sorted(dependencies, key=lambda item: (item["kind"], item["name"], item["sha256"]))


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(argv)


def main():
    args = parse_args()
    output = Path(args.output).resolve()
    report_path = Path(args.report).resolve()
    if output.exists() or report_path.exists():
        raise ValueError("Bundle output already exists; use a new preparation directory")
    output.parent.mkdir(parents=True, exist_ok=True)

    dependencies = collect_dependencies()
    source_scene = bpy.context.scene
    defaults = {
        "frame_start": int(source_scene.frame_start),
        "frame_end": int(source_scene.frame_end),
        "frame_step": int(source_scene.frame_step),
        "resolution_x": int(source_scene.render.resolution_x),
        "resolution_y": int(source_scene.render.resolution_y),
        "resolution_percentage": int(source_scene.render.resolution_percentage),
        "samples": int(source_scene.cycles.samples),
        "source_engine": source_scene.render.engine,
    }
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False, copy=True)
    if not output.is_file():
        raise ValueError("Blender returned without creating the bundled scene")
    report = {
        "schema_version": 1,
        "blender_version": bpy.app.version_string,
        "scene_name": source_scene.name,
        "scene_sha256": sha256_file(output),
        "dependencies": dependencies,
        "defaults": defaults,
    }
    atomic_json(report_path, report)
    print("RENDER_BUNDLE_REPORT=" + json.dumps(report, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"RENDER_BUNDLE_ERROR={error}", file=sys.stderr)
        raise
