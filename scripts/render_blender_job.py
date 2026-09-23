"""Run one immutable remote Cycles job inside Blender and resume validated frames."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

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


def configure_device(requested):
    if requested not in {"CUDA", "OPTIX"}:
        raise ValueError("device must be CUDA or OPTIX")
    preferences = bpy.context.preferences.addons["cycles"].preferences
    preferences.compute_device_type = requested
    preferences.get_devices()
    enabled = []
    for device in preferences.devices:
        use = device.type == requested
        device.use = use
        if use:
            enabled.append({"name": device.name, "type": device.type, "id": device.id})
    if not enabled:
        raise ValueError(f"No {requested} GPU is available to Blender")
    return enabled


def validate_frame(path, width, height):
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 64:
        raise ValueError(f"Rendered frame is missing or too small: {path.name}")
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        dimensions = tuple(int(value) for value in image.size)
    finally:
        bpy.data.images.remove(image)
    if dimensions != (width, height):
        raise ValueError(f"Unexpected dimensions for {path.name}: {dimensions}, expected {(width, height)}")
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path),
            "width": width, "height": height}


def probe(device):
    enabled = configure_device(device)
    result = {"blender_version": bpy.app.version_string, "requested_device": device, "enabled_devices": enabled}
    print("RENDER_DEVICE_PROBE=" + json.dumps(result, separators=(",", ":"), ensure_ascii=False))


def render(job_dir):
    job_dir = Path(job_dir).resolve()
    job_path = job_dir / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if job.get("job_id") != job_dir.name or len(job_dir.name) != 64:
        raise ValueError("Job directory does not match the immutable job ID")
    semantic = job["semantic"]
    profile = semantic["profile"]
    scene_path = job_dir / semantic["scene_file"]
    if sha256_file(scene_path) != semantic["scene_sha256"]:
        raise ValueError("Bundled scene hash differs from the submitted contract")
    if bpy.app.version_string != semantic["blender_version"]:
        raise ValueError(f"Blender version mismatch: {bpy.app.version_string} != {semantic['blender_version']}")

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    enabled = [] if profile["device"] == "CPU_TEST" else configure_device(profile["device"])
    scene.cycles.device = "CPU" if profile["device"] == "CPU_TEST" else "GPU"
    scene.cycles.samples = profile["samples"]
    scene.render.resolution_x = profile["resolution_x"]
    scene.render.resolution_y = profile["resolution_y"]
    scene.render.resolution_percentage = profile["resolution_percentage"]
    width = profile["resolution_x"] * profile["resolution_percentage"] // 100
    height = profile["resolution_y"] * profile["resolution_percentage"] // 100
    output_format = profile["output_format"]
    if output_format == "PNG16":
        extension = ".png"
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_depth = "16"
        scene.render.image_settings.color_mode = "RGBA"
    elif output_format == "OPEN_EXR_HALF":
        extension = ".exr"
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.color_depth = "16"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.image_settings.exr_codec = "ZIP"
    else:
        raise ValueError("output_format must be PNG16 or OPEN_EXR_HALF")
    scene.render.use_file_extension = True

    frames_dir = job_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    requested_frames = list(range(profile["frame_start"], profile["frame_end"] + 1, profile["frame_step"]))
    progress_path = job_dir / "progress.json"
    prior_progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
    if prior_progress and prior_progress.get("job_id") != job["job_id"]:
        raise ValueError("Progress ledger belongs to a different job")
    prior_records = {record["name"]: record for record in prior_progress.get("frames", [])}
    completed = []
    started = time.time()
    for index, frame in enumerate(requested_frames):
        final = frames_dir / f"{frame:06d}{extension}"
        if final.exists():
            record = validate_frame(final, width, height)
            registered = prior_records.get(final.name)
            if not registered or any(record[key] != registered.get(key) for key in ("bytes", "sha256", "width", "height")):
                raise ValueError(f"Existing frame is not registered to this job's progress ledger: {final.name}")
            completed.append(record)
        else:
            temporary = frames_dir / f"{frame:06d}.writing-{os.getpid()}{extension}"
            if temporary.exists():
                raise ValueError(f"Stale partial frame needs inspection: {temporary.name}")
            scene.frame_set(frame)
            scene.render.filepath = str(temporary)
            bpy.ops.render.render(write_still=True)
            rendered = validate_frame(temporary, width, height)
            if final.exists():
                raise ValueError(f"Completed frame appeared concurrently: {final.name}")
            temporary.rename(final)
            rendered["name"] = final.name
            completed.append(rendered)
        atomic_json(progress_path, {
            "job_id": job["job_id"],
            "status": "running",
            "completed_frames": len(completed),
            "total_frames": len(requested_frames),
            "last_frame": frame,
            "frames": completed,
        })
    result = {
        "schema_version": 1,
        "job_id": job["job_id"],
        "status": "complete",
        "elapsed_seconds": round(time.time() - started, 3),
        "blender_version": bpy.app.version_string,
        "device": profile["device"],
        "enabled_devices": enabled,
        "frames": completed,
    }
    atomic_json(job_dir / "result.json", result)
    atomic_json(progress_path, {
        "job_id": job["job_id"], "status": "complete", "completed_frames": len(completed),
        "total_frames": len(requested_frames), "frames": completed,
    })
    print("RENDER_JOB_RESULT=" + json.dumps(result, separators=(",", ":"), ensure_ascii=False))


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--job-dir")
    group.add_argument("--probe-device", choices=["CUDA", "OPTIX"])
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    if args.probe_device:
        probe(args.probe_device)
    else:
        render(args.job_dir)
