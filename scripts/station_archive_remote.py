"""Station-side helper for the production archive. Deployed by station_archive.py to <root>/_bin.

Runs under the station's Python (3.10). Reads path lists as JSON on stdin so Hebrew and spaces never
travel through the SSH command line. It only creates directories, hashes files and reads/writes the
archive manifest; it never deletes or overwrites media.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

MANIFEST = 'archive-manifest.json'


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_stdin_json():
    raw = sys.stdin.buffer.read()
    return json.loads(raw.decode('utf-8')) if raw.strip() else None


def safe_join(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f'path escapes the archive root: {relative}')
    return target


def cmd_manifest(args):
    path = Path(args.root) / MANIFEST
    if not path.is_file():
        return {'exists': False, 'files': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    return {'exists': True, 'files': data.get('files', {}), 'updated_utc': data.get('updated_utc')}


def cmd_ensure_dirs(args):
    relatives = read_stdin_json() or []
    Path(args.root).mkdir(parents=True, exist_ok=True)
    created = 0
    for relative in relatives:
        target = safe_join(args.root, relative)
        if not target.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            created += 1
    return {'root': str(Path(args.root).resolve()), 'created': created}


def cmd_hash(args):
    relatives = read_stdin_json() or []
    out = {}
    for relative in relatives:
        target = safe_join(args.root, relative)
        if not target.is_file():
            out[relative] = None
            continue
        out[relative] = {'sha256': sha256_file(target), 'size': target.stat().st_size}
    return out


def cmd_write_manifest(args):
    manifest = read_stdin_json()
    if not isinstance(manifest, dict) or 'files' not in manifest:
        raise ValueError('manifest JSON with a files map is required on stdin')
    path = Path(args.root) / MANIFEST
    temporary = path.with_name(MANIFEST + '.writing')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(path)
    return {'manifest': str(path), 'files': len(manifest['files'])}


def cmd_free(args):
    import shutil
    Path(args.root).mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(args.root)
    return {'root': str(Path(args.root).resolve()), 'free_bytes': usage.free, 'total_bytes': usage.total}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('manifest', 'ensure-dirs', 'hash', 'write-manifest', 'free'):
        p = sub.add_parser(name)
        p.add_argument('--root', required=True)
    args = parser.parse_args(argv)
    handler = {'manifest': cmd_manifest, 'ensure-dirs': cmd_ensure_dirs, 'hash': cmd_hash,
               'write-manifest': cmd_write_manifest, 'free': cmd_free}[args.command]
    try:
        result = handler(args)
    except (ValueError, OSError) as error:
        sys.stdout.buffer.write(json.dumps({'error': str(error)}, ensure_ascii=False).encode('utf-8'))
        return 1
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
