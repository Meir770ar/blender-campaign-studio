"""Shared local I/O primitives; no provider access or secret storage."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def digest_json(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    # Unique per attempt: a fixed temp name left behind by an interrupted write would block every
    # later write to this ledger with a bare FileExistsError.
    temporary = path.with_name(f'{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.writing')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def lock(path):
    path = Path(path)
    try:
        with path.open('x', encoding='ascii') as stream:
            stream.write(str(os.getpid()))
    except FileExistsError as error:
        raise ValueError(f'Operation locked: {path}. Inspect the recorded process before recovering a stale lock.') from error
    try:
        yield
    finally:
        path.unlink()


def run(command, *, timeout=120, log=None, env=None, input_bytes=None):
    result = subprocess.run([str(p) for p in command], input=input_bytes, capture_output=True,
                            timeout=timeout, env=env)
    stdout = result.stdout.decode('utf-8', errors='replace')
    stderr = result.stderr.decode('utf-8', errors='replace')
    if log:
        Path(log).write_text(stdout + '\n' + stderr, encoding='utf-8')
    if result.returncode:
        # Provider callers handle their own response bodies; this helper is for local media tools.
        raise ValueError(f'{Path(command[0]).name} failed ({result.returncode}): {stderr[-1400:]}')
    return stdout, stderr


def new_directory(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path
