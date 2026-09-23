"""Constrained Windows worker for immutable Blender render jobs."""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
import uuid
import zipfile


JOB_ID_LENGTH = 64
ALLOWED_ARCHIVE_PREFIXES = ("job.json", "bundle/")


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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".writing-{os.getpid()}-{uuid.uuid4().hex}")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def validate_job_id(value):
    if not isinstance(value, str) or len(value) != JOB_ID_LENGTH or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid job ID")
    return value


def confined(path, root, *, must_exist=False):
    path = Path(path).resolve()
    root = Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path is outside the configured worker root: {path}")
    if must_exist and not path.exists():
        raise ValueError(f"Required path does not exist: {path}")
    return path


def validated_archive(archive, max_bytes):
    archive = Path(archive)
    if not archive.is_file() or archive.stat().st_size > max_bytes:
        raise ValueError("Submission archive is missing or exceeds the configured size limit")
    with zipfile.ZipFile(archive) as package:
        infos = package.infolist()
        if not infos or len(infos) > 100000:
            raise ValueError("Submission archive has an invalid entry count")
        total = 0
        names = set()
        for info in infos:
            name = info.filename.replace("\\", "/")
            pure = PurePosixPath(name)
            mode = info.external_attr >> 16
            if (pure.is_absolute() or ".." in pure.parts or not pure.parts or
                    (mode and stat.S_ISLNK(mode))):
                raise ValueError(f"Unsafe archive entry: {name}")
            if name in names:
                raise ValueError(f"Duplicate archive entry: {name}")
            names.add(name)
            if not (name == "job.json" or name.startswith("bundle/")):
                raise ValueError(f"Unexpected archive entry: {name}")
            total += info.file_size
            if total > max_bytes:
                raise ValueError("Expanded submission exceeds the configured size limit")
        if "job.json" not in names or "bundle/scene.blend" not in names:
            raise ValueError("Submission must contain job.json and bundle/scene.blend")
        job = json.loads(package.read("job.json").decode("utf-8-sig"))
    job_id = validate_job_id(job.get("job_id"))
    if digest_json(job.get("semantic")) != job_id:
        raise ValueError("Job ID does not match the semantic contract")
    if job["semantic"].get("profile", {}).get("device") not in {"CUDA", "OPTIX"}:
        raise ValueError("Remote jobs must explicitly select CUDA or OPTIX")
    return job


def load_config(path):
    config_path = Path(path).resolve()
    config = read_json(config_path)
    required = ("root", "jobs_root", "incoming_root", "outgoing_root", "blender", "render_script")
    if config.get("schema_version") != 1 or any(not config.get(key) for key in required):
        raise ValueError("Worker configuration is incomplete or unsupported")
    root = Path(config["root"]).resolve()
    for key in ("jobs_root", "incoming_root", "outgoing_root", "render_script"):
        confined(config[key], root, must_exist=key == "render_script")
    confined(config["blender"], root, must_exist=True)
    config["max_archive_bytes"] = int(config.get("max_archive_bytes", 40 * 1024 ** 3))
    return config


def state_path(job_dir):
    return Path(job_dir) / "state.json"


def set_state(job_dir, status, **extra):
    existing = read_json(state_path(job_dir)) if state_path(job_dir).exists() else {"schema_version": 1}
    if status in {"queued", "running", "complete"}:
        existing.pop("error", None)
        existing.pop("previous_status", None)
    existing.update(extra)
    existing["status"] = status
    existing["updated_epoch"] = time.time()
    atomic_json(state_path(job_dir), existing)
    return existing


def process_alive(pid, expected_job=None):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        script = f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\"; if($null -eq $p){{exit 3}}; $p.CommandLine"
        checked = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        return checked.returncode == 0 and (not expected_job or expected_job in checked.stdout)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextmanager
def worker_lock(config, job_id):
    path = Path(config["root"]) / "worker.lock"
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "job_id": job_id, "started_epoch": time.time()}, stream)
    except FileExistsError as error:
        raise ValueError(f"Render worker is locked; inspect {path} before starting another job") from error
    try:
        yield
    finally:
        if path.exists():
            recorded = read_json(path)
            if recorded.get("pid") == os.getpid() and recorded.get("job_id") == job_id:
                path.unlink()


def submit(config, archive, start=False):
    incoming = confined(archive, config["incoming_root"], must_exist=True)
    job = validated_archive(incoming, config["max_archive_bytes"])
    job_id = job["job_id"]
    jobs_root = Path(config["jobs_root"])
    target = confined(jobs_root / job_id, jobs_root)
    archive_hash = sha256_file(incoming)
    if target.exists():
        installed = read_json(target / "job.json")
        if installed.get("job_id") != job_id or installed.get("semantic") != job.get("semantic"):
            raise ValueError("Job ID collision with a different immutable manifest")
        response = {"job_id": job_id, "idempotent": True, "status": read_json(state_path(target))["status"]}
    else:
        staging = confined(jobs_root / f".staging-{job_id}-{uuid.uuid4().hex}", jobs_root)
        staging.mkdir(parents=False, exist_ok=False)
        try:
            with zipfile.ZipFile(incoming) as package:
                package.extractall(staging)
            scene = staging / job["semantic"]["scene_file"]
            if not scene.is_file() or sha256_file(scene) != job["semantic"]["scene_sha256"]:
                raise ValueError("Bundled scene is missing or its hash differs from the contract")
            if sha256_file(incoming) != archive_hash:
                raise ValueError("Submission archive changed while it was being installed")
            atomic_json(staging / "submission.json", {"archive_sha256": archive_hash, "archive_bytes": incoming.stat().st_size})
            set_state(staging, "queued", job_id=job_id)
            staging.rename(target)
        except Exception:
            # Preserve the isolated staging directory as forensic evidence instead of deleting uncertain input.
            raise
        response = {"job_id": job_id, "idempotent": False, "status": "queued"}
    if start and response["status"] == "queued":
        response.update(start_job(config, job_id))
    return response


def launch_via_wmi(command, working_directory):
    command_line = subprocess.list2cmdline([str(part) for part in command])
    encoded = base64.b64encode(command_line.encode("utf-16-le")).decode("ascii")
    escaped_directory = str(working_directory).replace("'", "''")
    script = (
        f"$c=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('{encoded}'));"
        "$r=Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        f"-Arguments @{{CommandLine=$c;CurrentDirectory='{escaped_directory}'}};"
        "$r | Select-Object ProcessId,ReturnValue | ConvertTo-Json -Compress"
    )
    launched = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if launched.returncode:
        raise ValueError("WMI launcher failed: " + (launched.stdout + launched.stderr)[-1200:])
    try:
        result = json.loads(launched.stdout.strip())
    except json.JSONDecodeError as error:
        raise ValueError("WMI launcher returned invalid JSON") from error
    if result.get("ReturnValue") != 0 or type(result.get("ProcessId")) is not int:
        raise ValueError(f"WMI launcher rejected the process: {result}")
    return result["ProcessId"]


def start_job(config, job_id, reconciled=False):
    job_id = validate_job_id(job_id)
    job_dir = confined(Path(config["jobs_root"]) / job_id, config["jobs_root"], must_exist=True)
    state = read_json(state_path(job_dir))
    allowed = {"queued", "failed"}
    if state["status"] == "unknown" and reconciled:
        allowed.add("unknown")
    if state["status"] not in allowed:
        suffix = "; pass --reconciled only after inspecting processes, locks, frames and logs" if state["status"] == "unknown" else ""
        raise ValueError(f"Job cannot be started from status {state['status']}{suffix}")
    lock_path = Path(config["root"]) / "worker.lock"
    if lock_path.exists():
        raise ValueError(f"Render worker is already locked; job remains {state['status']}")
    command = [sys.executable, str(Path(__file__).resolve()), "--config", str(config["config_path"]),
               "execute", "--job", job_id]
    previous = state["status"]
    if previous == "unknown":
        set_state(job_dir, "queued", reconciled_from="unknown", reconciliation_epoch=time.time())
    try:
        pid = launch_via_wmi(command, config["root"])
    except Exception:
        if previous == "unknown":
            set_state(job_dir, "unknown", error="Reconciled launch failed before a new executor was created")
        raise
    atomic_json(job_dir / "executor.json", {"pid": pid, "started_epoch": time.time(), "launcher": "Win32_Process"})
    return {"started": True, "executor_pid": pid, "status": "queued", "launcher": "Win32_Process"}


def execute(config, job_id):
    job_id = validate_job_id(job_id)
    job_dir = confined(Path(config["jobs_root"]) / job_id, config["jobs_root"], must_exist=True)
    with worker_lock(config, job_id):
        set_state(job_dir, "running", worker_pid=os.getpid())
        try:
            job = read_json(job_dir / "job.json")
            scene = job_dir / job["semantic"]["scene_file"]
            log_dir = job_dir / "logs"
            log_dir.mkdir(exist_ok=True)
            command = [config["blender"], "--background", "--factory-startup", "--disable-autoexec", str(scene),
                       "--python-exit-code", "1", "--python", config["render_script"], "--", "--job-dir", str(job_dir)]
            with (log_dir / "blender.log").open("a", encoding="utf-8") as stream:
                completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
            result_path = job_dir / "result.json"
            if completed.returncode == 0 and result_path.is_file() and read_json(result_path).get("status") == "complete":
                set_state(job_dir, "complete", blender_returncode=0)
                return {"job_id": job_id, "status": "complete"}
            raise ValueError(f"Blender render failed with exit code {completed.returncode}")
        except Exception as error:
            returncode = completed.returncode if "completed" in locals() else None
            set_state(job_dir, "failed", blender_returncode=returncode,
                      error=f"Render execution failed: {error}. Inspect logs before any retry")
            raise


def status(config, job_id):
    job_id = validate_job_id(job_id)
    job_dir = confined(Path(config["jobs_root"]) / job_id, config["jobs_root"], must_exist=True)
    state = read_json(state_path(job_dir))
    executor_path = job_dir / "executor.json"
    executor = read_json(executor_path) if executor_path.exists() else {}
    if state["status"] in {"queued", "running"} and executor and not process_alive(executor.get("pid"), job_id):
        state = set_state(job_dir, "unknown", previous_status=state["status"],
                          error="Executor disappeared before recording a terminal result; reconcile before any retry")
    elif state["status"] == "complete" and ("error" in state or "previous_status" in state):
        state = set_state(job_dir, "complete")
    progress_path = job_dir / "progress.json"
    progress = read_json(progress_path) if progress_path.exists() else None
    if isinstance(progress, dict) and isinstance(progress.get("frames"), list):
        verified_frames = len(progress["frames"])
        progress = {key: value for key, value in progress.items() if key != "frames"}
        progress["verified_frames"] = verified_frames
    return {"job_id": job_id, **state, "progress": progress, "executor": executor or None}


def package_result(config, job_id):
    current = status(config, job_id)
    if current["status"] != "complete":
        raise ValueError(f"Cannot package a job in status {current['status']}")
    job_dir = confined(Path(config["jobs_root"]) / job_id, config["jobs_root"], must_exist=True)
    outgoing = confined(Path(config["outgoing_root"]) / f"{job_id}-result.zip", config["outgoing_root"])
    if outgoing.exists():
        return {"job_id": job_id, "archive": str(outgoing), "sha256": sha256_file(outgoing), "idempotent": True}
    result = read_json(job_dir / "result.json")
    members = [job_dir / "job.json", job_dir / "result.json", job_dir / "state.json"]
    members.extend(job_dir / "frames" / frame["name"] for frame in result["frames"])
    log = job_dir / "logs" / "blender.log"
    if log.is_file():
        members.append(log)
    manifest = {"schema_version": 1, "job_id": job_id, "files": []}
    for member in members:
        if not member.is_file() or not member.resolve().is_relative_to(job_dir):
            raise ValueError(f"Result member is missing or unsafe: {member}")
        manifest["files"].append({"name": member.relative_to(job_dir).as_posix(), "bytes": member.stat().st_size,
                                  "sha256": sha256_file(member)})
    temporary = outgoing.with_name(outgoing.name + f".writing-{os.getpid()}")
    with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        package.writestr("collection-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for member in members:
            package.write(member, member.relative_to(job_dir).as_posix())
    temporary.rename(outgoing)
    return {"job_id": job_id, "archive": str(outgoing), "sha256": sha256_file(outgoing), "idempotent": False}


def doctor(config, device):
    version = subprocess.run([config["blender"], "--version"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30)
    if version.returncode:
        raise ValueError("Configured Blender executable failed its version check")
    command = [config["blender"], "--background", "--factory-startup", "--disable-autoexec",
               "--python-exit-code", "1", "--python", config["render_script"], "--", "--probe-device", device]
    probe = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if probe.returncode:
        raise ValueError("GPU probe failed: " + (probe.stdout + probe.stderr)[-1200:])
    marker = next((line.split("=", 1)[1] for line in probe.stdout.splitlines() if line.startswith("RENDER_DEVICE_PROBE=")), None)
    if not marker:
        raise ValueError("GPU probe returned no structured result")
    return {"status": "ready", "version": version.stdout.splitlines()[0], "device": json.loads(marker),
            "root": config["root"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor")
    check.add_argument("--device", choices=["CUDA", "OPTIX"], default="CUDA")
    submission = commands.add_parser("submit")
    submission.add_argument("--archive", required=True)
    submission.add_argument("--start", action="store_true")
    starter = commands.add_parser("start")
    starter.add_argument("--job", required=True)
    starter.add_argument("--reconciled", action="store_true")
    runner = commands.add_parser("execute")
    runner.add_argument("--job", required=True)
    query = commands.add_parser("status")
    query.add_argument("--job", required=True)
    package = commands.add_parser("package-result")
    package.add_argument("--job", required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    config["config_path"] = str(Path(args.config).resolve())
    if args.command == "doctor":
        result = doctor(config, args.device)
    elif args.command == "submit":
        result = submit(config, args.archive, args.start)
    elif args.command == "start":
        result = start_job(config, args.job, args.reconciled)
    elif args.command == "execute":
        result = execute(config, args.job)
    elif args.command == "status":
        result = status(config, args.job)
    else:
        result = package_result(config, args.job)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile,
            subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
