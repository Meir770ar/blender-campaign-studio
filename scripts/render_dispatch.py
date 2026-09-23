"""Prepare, submit, monitor, collect and verify content-addressed Blender render jobs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile


SCRIPT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONNECTIONS = SCRIPT_ROOT.parent / "connections.json"


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest_json(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + f".writing-{os.getpid()}-{uuid.uuid4().hex}")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def load_station(path=DEFAULT_CONNECTIONS):
    connections = read_json(path)
    station = connections.get("render_station")
    required = ("ssh_alias", "root", "incoming_root", "outgoing_root", "python", "worker", "config")
    if not isinstance(station, dict) or any(not station.get(key) for key in required):
        raise ValueError("connections.json has no complete render_station configuration")
    return station


def run(command, timeout=300, log=None):
    completed = subprocess.run([str(part) for part in command], capture_output=True, timeout=timeout)
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if log:
        Path(log).write_text(stdout + "\n" + stderr, encoding="utf-8")
    if completed.returncode:
        raise ValueError(f"{Path(command[0]).name} failed ({completed.returncode}): {(stdout + stderr)[-1800:]}")
    return stdout


def blender_version(executable):
    output = run([executable, "--version"], timeout=30)
    first = output.splitlines()[0].strip()
    if not first.startswith("Blender "):
        raise ValueError("Could not parse Blender version")
    return first.removeprefix("Blender ")


def profile_from(defaults, args):
    profile = {
        "frame_start": defaults["frame_start"] if args.frame_start is None else args.frame_start,
        "frame_end": defaults["frame_end"] if args.frame_end is None else args.frame_end,
        "frame_step": defaults["frame_step"] if args.frame_step is None else args.frame_step,
        "resolution_x": defaults["resolution_x"] if args.resolution_x is None else args.resolution_x,
        "resolution_y": defaults["resolution_y"] if args.resolution_y is None else args.resolution_y,
        "resolution_percentage": defaults["resolution_percentage"] if args.resolution_percentage is None else args.resolution_percentage,
        "samples": defaults["samples"] if args.samples is None else args.samples,
        "device": args.device,
        "output_format": "PNG16" if args.output_format == "png16" else "OPEN_EXR_HALF",
    }
    integer(profile["frame_start"], "frame_start", -1000000, 1000000)
    integer(profile["frame_end"], "frame_end", -1000000, 1000000)
    integer(profile["frame_step"], "frame_step", 1, 100000)
    if profile["frame_end"] < profile["frame_start"]:
        raise ValueError("frame_end must be at or after frame_start")
    if len(range(profile["frame_start"], profile["frame_end"] + 1, profile["frame_step"])) > 100000:
        raise ValueError("A job cannot contain more than 100,000 frames")
    integer(profile["resolution_x"], "resolution_x", 16, 32768)
    integer(profile["resolution_y"], "resolution_y", 16, 32768)
    integer(profile["resolution_percentage"], "resolution_percentage", 1, 100)
    integer(profile["samples"], "samples", 1, 1000000)
    return profile


def deterministic_zip(path, root, members):
    path = Path(path)
    root = Path(root).resolve()
    if path.exists():
        raise ValueError(f"Archive output already exists: {path}")
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for member in sorted((Path(item).resolve() for item in members), key=lambda item: item.relative_to(root).as_posix()):
            if not member.is_file() or not member.is_relative_to(root):
                raise ValueError(f"Unsafe bundle member: {member}")
            relative = member.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            package.writestr(info, member.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)


def prepare(args):
    scene = Path(args.scene).resolve()
    project = Path(args.project).resolve()
    if not scene.is_file() or scene.suffix.lower() != ".blend":
        raise ValueError("scene must be an existing .blend file")
    if not project.is_dir():
        raise ValueError("project must be an existing production directory")
    jobs_root = project / "render-jobs"
    jobs_root.mkdir(exist_ok=True)
    stage = jobs_root / f".prepare-{uuid.uuid4().hex}"
    stage.mkdir(exist_ok=False)
    bundle_dir = stage / "bundle"
    bundle_dir.mkdir()
    report_path = bundle_dir / "bundle-report.json"
    bundled_scene = bundle_dir / "scene.blend"
    blender = args.blender or _find_blender()
    version = blender_version(blender)
    log = stage / "bundle.log"
    command = [blender, "--background", "--factory-startup", "--disable-autoexec", str(scene),
               "--python-exit-code", "1", "--python", str(SCRIPT_ROOT / "blender_bundle.py"), "--",
               "--output", str(bundled_scene), "--report", str(report_path)]
    try:
        run(command, timeout=args.timeout, log=log)
        report = read_json(report_path)
        if report["blender_version"] != version:
            raise ValueError("Bundler version differs from the selected executable")
        profile = profile_from(report["defaults"], args)
        semantic = {
            "schema_version": 1,
            "blender_version": version,
            "scene_file": "bundle/scene.blend",
            "scene_sha256": report["scene_sha256"],
            "dependencies": report["dependencies"],
            "profile": profile,
        }
        job_id = digest_json(semantic)
        job = {"schema_version": 1, "job_id": job_id, "semantic": semantic, "prepared_utc": now()}
        atomic_json(stage / "job.json", job)
        target = jobs_root / job_id
        if target.exists():
            existing = read_json(target / "job.json")
            if existing["semantic"] != semantic:
                raise ValueError("Content-addressed job collision")
            if not (target / "submission.zip").is_file() or not (target / "dispatch.json").is_file():
                raise ValueError("Existing job directory is incomplete; inspect it instead of overwriting")
            shutil.rmtree(stage)
            return {"job_id": job_id, "job_dir": str(target), "archive": str(target / "submission.zip"),
                    "idempotent": True, "profile": profile}
        members = [stage / "job.json"] + [path for path in (stage / "bundle").rglob("*") if path.is_file()]
        deterministic_zip(stage / "submission.zip", stage, members)
        atomic_json(stage / "dispatch.json", {"schema_version": 1, "job_id": job_id, "status": "prepared",
                                               "updated_utc": now()})
        stage.rename(target)
        return {"job_id": job_id, "job_dir": str(target), "archive": str(target / "submission.zip"),
                "archive_sha256": sha256_file(target / "submission.zip"), "idempotent": False, "profile": profile}
    except Exception:
        # Keep the exact preparation directory and log for diagnosis; never overwrite another attempt.
        raise


def _find_blender():
    direct = shutil.which("blender")
    if direct:
        return direct
    expected = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Blender Foundation/Blender 5.1/blender.exe"
    if expected.is_file():
        return str(expected)
    raise ValueError("Blender 5.1 was not found; pass --blender")


def remote_worker(station, arguments, timeout=300):
    command = ["ssh", station["ssh_alias"], station["python"], station["worker"], "--config", station["config"], *arguments]
    output = run(command, timeout=timeout)
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise ValueError(f"Remote worker returned invalid JSON: {output[-1000:]}") from error


def submit_remote(args):
    job_dir = Path(args.job_dir).resolve()
    job = read_json(job_dir / "job.json")
    archive = job_dir / "submission.zip"
    if sha256_file(job_dir / job["semantic"]["scene_file"]) != job["semantic"]["scene_sha256"]:
        raise ValueError("Local bundled scene changed after preparation")
    station = load_station(args.connections)
    remote_archive = station["incoming_root"].rstrip("/\\") + "/" + f"{job['job_id']}-{uuid.uuid4().hex}.zip"
    run(["scp", str(archive), f"{station['ssh_alias']}:{remote_archive}"], timeout=args.timeout)
    result = remote_worker(station, ["submit", "--archive", remote_archive] + (["--start"] if args.start else []),
                           timeout=args.timeout)
    atomic_json(job_dir / "dispatch.json", {"schema_version": 1, "job_id": job["job_id"],
                                             "status": result["status"], "remote": result, "updated_utc": now()})
    return result


def remote_status(args):
    station = load_station(args.connections)
    result = remote_worker(station, ["status", "--job", args.job], timeout=args.timeout)
    if args.job_dir:
        job_dir = Path(args.job_dir).resolve()
        job = read_json(job_dir / "job.json")
        if job["job_id"] != args.job:
            raise ValueError("job-dir does not match the queried job ID")
        atomic_json(job_dir / "dispatch.json", {"schema_version": 1, "job_id": args.job,
                                                 "status": result["status"], "remote": result, "updated_utc": now()})
    return result


def remote_start(args):
    station = load_station(args.connections)
    arguments = ["start", "--job", args.job]
    if args.reconciled:
        arguments.append("--reconciled")
    return remote_worker(station, arguments, timeout=args.timeout)


def validate_zip_names(package):
    seen = set()
    for info in package.infolist():
        name = info.filename.replace("\\", "/")
        pure = PurePosixPath(name)
        mode = info.external_attr >> 16
        if pure.is_absolute() or ".." in pure.parts or name in seen or (mode and stat.S_ISLNK(mode)):
            raise ValueError(f"Unsafe result archive entry: {name}")
        seen.add(name)
    return seen


def verify_result_archive(path, expected_job=None):
    path = Path(path).resolve()
    with zipfile.ZipFile(path) as package:
        names = validate_zip_names(package)
        required = {"collection-manifest.json", "job.json", "result.json", "state.json"}
        if not required.issubset(names):
            raise ValueError("Result archive is missing required metadata")
        manifest = json.loads(package.read("collection-manifest.json").decode("utf-8-sig"))
        job = json.loads(package.read("job.json").decode("utf-8-sig"))
        result = json.loads(package.read("result.json").decode("utf-8-sig"))
        job_id = job.get("job_id")
        if expected_job and job_id != expected_job:
            raise ValueError("Collected result belongs to a different job")
        if digest_json(job.get("semantic")) != job_id or result.get("job_id") != job_id or result.get("status") != "complete":
            raise ValueError("Result metadata does not match a complete immutable job")
        records = {item["name"]: item for item in manifest.get("files", [])}
        if names != set(records) | {"collection-manifest.json"}:
            raise ValueError("Result archive contains unmanifested or missing members")
        for name, record in records.items():
            if name not in names:
                raise ValueError(f"Manifest member is missing: {name}")
            payload = package.read(name)
            if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
                raise ValueError(f"Manifest verification failed: {name}")
        expected_frames = list(range(job["semantic"]["profile"]["frame_start"],
                                     job["semantic"]["profile"]["frame_end"] + 1,
                                     job["semantic"]["profile"]["frame_step"]))
        if len(result.get("frames", [])) != len(expected_frames):
            raise ValueError("Result frame count differs from the job contract")
        for frame_number, record in zip(expected_frames, result["frames"]):
            extension = ".png" if job["semantic"]["profile"]["output_format"] == "PNG16" else ".exr"
            expected_name = f"{frame_number:06d}{extension}"
            if record.get("name") != expected_name or f"frames/{expected_name}" not in records:
                raise ValueError(f"Missing or out-of-order frame: {expected_name}")
            if records[f"frames/{expected_name}"]["sha256"] != record.get("sha256"):
                raise ValueError(f"Frame hash disagreement: {expected_name}")
    return {"valid": True, "job_id": job_id, "frames": len(expected_frames), "archive_sha256": sha256_file(path)}


def collect(args):
    station = load_station(args.connections)
    package = remote_worker(station, ["package-result", "--job", args.job], timeout=args.timeout)
    output = Path(args.out_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    archive = output / f"{args.job}-result.zip"
    remote_archive = package["archive"].replace("\\", "/")
    run(["scp", f"{station['ssh_alias']}:{remote_archive}", str(archive)], timeout=args.timeout)
    verification = verify_result_archive(archive, args.job)
    with zipfile.ZipFile(archive) as zipped:
        validate_zip_names(zipped)
        zipped.extractall(output)
    atomic_json(output / "verification.json", verification)
    return {**verification, "output": str(output), "archive": str(archive)}


def doctor_remote(args):
    station = load_station(args.connections)
    return remote_worker(station, ["doctor", "--device", args.device], timeout=args.timeout)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--scene", required=True)
    prep.add_argument("--project", required=True)
    prep.add_argument("--blender")
    prep.add_argument("--frame-start", type=int)
    prep.add_argument("--frame-end", type=int)
    prep.add_argument("--frame-step", type=int)
    prep.add_argument("--resolution-x", type=int)
    prep.add_argument("--resolution-y", type=int)
    prep.add_argument("--resolution-percentage", type=int)
    prep.add_argument("--samples", type=int)
    prep.add_argument("--device", choices=["CUDA", "OPTIX", "CPU_TEST"], default="CUDA")
    prep.add_argument("--output-format", choices=["png16", "openexr-half"], default="png16")
    prep.add_argument("--timeout", type=int, default=1800)
    submission = commands.add_parser("submit")
    submission.add_argument("--job-dir", required=True)
    submission.add_argument("--start", action="store_true")
    submission.add_argument("--connections", default=str(DEFAULT_CONNECTIONS))
    submission.add_argument("--timeout", type=int, default=3600)
    query = commands.add_parser("status")
    query.add_argument("--job", required=True)
    query.add_argument("--job-dir")
    query.add_argument("--connections", default=str(DEFAULT_CONNECTIONS))
    query.add_argument("--timeout", type=int, default=120)
    starter = commands.add_parser("start")
    starter.add_argument("--job", required=True)
    starter.add_argument("--reconciled", action="store_true",
                         help="Allow UNKNOWN only after manual process/lock/frame/log reconciliation")
    starter.add_argument("--connections", default=str(DEFAULT_CONNECTIONS))
    starter.add_argument("--timeout", type=int, default=120)
    gathering = commands.add_parser("collect")
    gathering.add_argument("--job", required=True)
    gathering.add_argument("--out-dir", required=True)
    gathering.add_argument("--connections", default=str(DEFAULT_CONNECTIONS))
    gathering.add_argument("--timeout", type=int, default=3600)
    verify = commands.add_parser("verify")
    verify.add_argument("--archive", required=True)
    verify.add_argument("--job")
    health = commands.add_parser("doctor")
    health.add_argument("--device", choices=["CUDA", "OPTIX"], default="CUDA")
    health.add_argument("--connections", default=str(DEFAULT_CONNECTIONS))
    health.add_argument("--timeout", type=int, default=180)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        result = prepare(args)
    elif args.command == "submit":
        result = submit_remote(args)
    elif args.command == "status":
        result = remote_status(args)
    elif args.command == "start":
        result = remote_start(args)
    elif args.command == "collect":
        result = collect(args)
    elif args.command == "verify":
        result = verify_result_archive(args.archive, args.job)
    else:
        result = doctor_remote(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return result


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile,
            subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
