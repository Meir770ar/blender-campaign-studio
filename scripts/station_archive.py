"""Archive a production (raw materials, renders, deliveries, plans) on the VIDEO STATION.

The laptop stays the working copy: Resolve and Blender edit local files. Every push mirrors the
production folder to <station_archive.root>/<slug>/ over the OS-owned SSH alias, verifies each
uploaded file by SHA-256 on the station, and only then records it in the station manifest. Nothing is
ever deleted, locally or remotely; a changed file is re-uploaded, a removed local file stays archived.
Hashes are cached locally by size+mtime so a push over a large production costs one hash per new file.

Commands:
  doctor   connection, archive root, free space, helper deployment
  push     upload new/changed files and verify (use --dry-run to see the plan)
  status   compare the local production with the station manifest (--verify re-hashes remotely)
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
import subprocess
import uuid

from campaign_common import now, sha256_file, atomic_json, run as _run
from studio import load_json, write_new

SKILL_ROOT = Path(__file__).resolve().parent.parent
HELPER = Path(__file__).resolve().parent / 'station_archive_remote.py'
CACHE_NAME = 'local-hash-cache.json'
EXCLUDED_SUFFIXES = ('.writing', '.tmp', '.part')
EXCLUDED_DIRS = {'__pycache__'}
SLUG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$')


def run(command, timeout=300, input_bytes=None):
    stdout, _ = _run(command, timeout=timeout, input_bytes=input_bytes)
    return stdout


def load_config(path=None):
    connections = load_json(path or SKILL_ROOT / 'connections.json')
    config = connections.get('station_archive')
    required = ('ssh_alias', 'root', 'python')
    if not isinstance(config, dict) or any(not config.get(key) for key in required):
        raise ValueError('connections.json has no complete station_archive configuration (ssh_alias, root, python)')
    if not SLUG_RE.match(Path(config['root']).name):
        raise ValueError('station_archive.root must end in an ASCII folder name')
    return config


def remote_path(root, *parts):
    return '/'.join([root.rstrip('/\\'), *parts])


def sftp_path(path):
    """Win32-OpenSSH sftp-server addresses drives as /D:/folder/file."""
    path = path.replace('\\', '/')
    return path if path.startswith('/') else '/' + path


def helper_call(config, command, root, payload=None, timeout=600):
    helper = remote_path(config['root'], '_bin', HELPER.name)
    output = run(['ssh', config['ssh_alias'], config['python'], helper, command, '--root', root],
                 timeout=timeout, input_bytes=json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else b'')
    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise ValueError(f'Station helper returned invalid JSON: {output[-800:]}') from error
    if isinstance(result, dict) and result.get('error'):
        raise ValueError(f'Station helper: {result["error"]}')
    return result


def deploy_helper(config):
    """Copy the helper to <root>/_bin every time; it is tiny and this keeps both sides in step."""
    bin_dir = remote_path(config['root'], '_bin')
    windows_dir = bin_dir.replace('/', '\\')
    run(['ssh', config['ssh_alias'], f'if not exist "{windows_dir}" mkdir "{windows_dir}"'], timeout=60)
    run(['scp', '-q', str(HELPER), f'{config["ssh_alias"]}:{remote_path(bin_dir, HELPER.name)}'], timeout=120)


# ─── local scan with hash cache ──────────────────────────────────────────────

def production_slug(project, explicit=None):
    slug = explicit or Path(project).name
    if not SLUG_RE.match(slug):
        raise ValueError(f'production folder name {slug!r} is not an ASCII slug; pass --slug with letters, digits, dot, dash or underscore')
    return slug


def scan_local(project, only=None, hasher=sha256_file):
    project = Path(project).resolve()
    if not project.is_dir():
        raise ValueError(f'production folder missing: {project}')
    archive_dir = project / 'archive'
    cache_path = archive_dir / CACHE_NAME
    cache = load_json(cache_path) if cache_path.is_file() else {}
    only_set = {o.strip().strip('/\\') for o in only if o.strip()} if only else None
    files, hashed, skipped = {}, 0, []
    for path in sorted(project.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(project).as_posix()
        top = relative.split('/', 1)[0]
        # archive/ holds the local hash cache and push reports: operational logs, not production content.
        if any(part in EXCLUDED_DIRS for part in path.parts) or relative.endswith(EXCLUDED_SUFFIXES) or top == 'archive':
            continue
        if only_set is not None and top not in only_set:
            skipped.append(relative)
            continue
        stat = path.stat()
        entry = cache.get(relative)
        if not entry or entry.get('size') != stat.st_size or entry.get('mtime_ns') != stat.st_mtime_ns:
            entry = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'sha256': hasher(path)}
            cache[relative] = entry
            hashed += 1
        files[relative] = {'sha256': entry['sha256'], 'size': stat.st_size}
    archive_dir.mkdir(exist_ok=True)
    atomic_json(cache_path, cache)
    return {'project': str(project), 'files': files, 'hashed_now': hashed, 'skipped_by_only': skipped}


def plan_upload(local_files, remote_files):
    upload, unchanged = [], []
    for relative, meta in local_files.items():
        remote = remote_files.get(relative)
        if remote and remote.get('sha256') == meta['sha256'] and remote.get('size') == meta['size']:
            unchanged.append(relative)
        else:
            upload.append(relative)
    archived_only = sorted(set(remote_files) - set(local_files))
    return {'upload': upload, 'unchanged': unchanged, 'archived_not_local': archived_only}


def sftp_batch(project, remote_dir, relatives):
    lines = []
    for relative in relatives:
        local = (Path(project) / relative).resolve()
        lines.append(f'put -p "{local.as_posix()}" "{sftp_path(remote_path(remote_dir, relative))}"')
    return '\n'.join(lines) + '\n'


# ─── commands ────────────────────────────────────────────────────────────────

def doctor(config=None):
    config = config or load_config()
    report = {'checked_at': now(), 'ssh_alias': config['ssh_alias'], 'root': config['root'], 'errors': []}
    try:
        deploy_helper(config)
        free = helper_call(config, 'free', config['root'], timeout=120)
        report['free_gb'] = round(free['free_bytes'] / 1e9, 1)
        report['total_gb'] = round(free['total_bytes'] / 1e9, 1)
        report['helper'] = 'deployed'
    except (ValueError, subprocess.TimeoutExpired) as error:
        report['errors'].append(str(error))
    report['ready'] = not report['errors']
    return report


def push(project, slug=None, only=None, dry_run=False, config=None, timeout=3600):
    config = config or load_config()
    project = Path(project).resolve()
    slug = production_slug(project, slug)
    remote_dir = remote_path(config['root'], slug)
    scan = scan_local(project, only)
    if not dry_run:
        deploy_helper(config)
    remote_manifest = helper_call(config, 'manifest', remote_dir, timeout=120) if not dry_run else {'exists': False, 'files': {}}
    plan = plan_upload(scan['files'], remote_manifest['files'])
    report = {'schema_version': 1, 'started_utc': now(), 'project': str(project), 'slug': slug, 'remote_dir': remote_dir,
              'local_files': len(scan['files']), 'hashed_now': scan['hashed_now'], 'skipped_by_only': len(scan['skipped_by_only']),
              'to_upload': len(plan['upload']), 'upload_bytes': sum(scan['files'][r]['size'] for r in plan['upload']),
              'unchanged': len(plan['unchanged']), 'archived_not_local': plan['archived_not_local'], 'dry_run': dry_run,
              'verified': [], 'mismatched': [], 'errors': []}
    if dry_run:
        report['planned_upload'] = plan['upload']
        return report
    archive_dir = project / 'archive'
    archive_dir.mkdir(exist_ok=True)
    if plan['upload']:
        dirs = sorted({str(Path(r).parent.as_posix()) for r in plan['upload'] if '/' in r})
        helper_call(config, 'ensure-dirs', remote_dir, payload=dirs, timeout=120)
        batch = archive_dir / f'sftp-batch-{uuid.uuid4().hex[:8]}.txt'
        batch.write_text(sftp_batch(project, remote_dir, plan['upload']), encoding='utf-8')
        try:
            run(['sftp', '-q', '-b', str(batch), config['ssh_alias']], timeout=timeout)
        finally:
            batch.unlink(missing_ok=True)
        hashes = helper_call(config, 'hash', remote_dir, payload=plan['upload'], timeout=timeout)
        for relative in plan['upload']:
            remote = hashes.get(relative)
            if remote and remote.get('sha256') == scan['files'][relative]['sha256']:
                report['verified'].append(relative)
            else:
                report['mismatched'].append({'file': relative, 'expected': scan['files'][relative]['sha256'],
                                             'remote': remote and remote.get('sha256')})
    merged = dict(remote_manifest['files'])
    stamp = now()
    for relative in report['verified']:
        merged[relative] = {**scan['files'][relative], 'archived_utc': stamp}
    for relative in plan['unchanged']:
        merged.setdefault(relative, {**scan['files'][relative], 'archived_utc': stamp})
    if report['verified'] or not remote_manifest['exists']:
        helper_call(config, 'write-manifest', remote_dir, payload={'schema_version': 1, 'slug': slug, 'updated_utc': stamp,
                                                                    'source': str(project), 'files': merged}, timeout=120)
    if report['mismatched']:
        report['errors'].append(f'{len(report["mismatched"])} file(s) did not verify on the station; they were not recorded, re-run push')
    report['archived_total'] = len(merged)
    report['finished_utc'] = now()
    report['technical_pass'] = not report['errors']
    write_new(archive_dir / f'push-{stamp.replace(":", "").replace("+00:00", "Z")}.json', report)
    return report


def status(project, slug=None, only=None, verify=False, config=None, timeout=3600):
    config = config or load_config()
    project = Path(project).resolve()
    slug = production_slug(project, slug)
    remote_dir = remote_path(config['root'], slug)
    scan = scan_local(project, only)
    deploy_helper(config)
    remote_manifest = helper_call(config, 'manifest', remote_dir, timeout=120)
    plan = plan_upload(scan['files'], remote_manifest['files'])
    report = {'checked_at': now(), 'project': str(project), 'slug': slug, 'remote_dir': remote_dir,
              'manifest_exists': remote_manifest['exists'], 'local_files': len(scan['files']),
              'archived_and_current': len(plan['unchanged']), 'not_archived_or_changed': plan['upload'],
              'archived_not_local': plan['archived_not_local']}
    if verify and plan['unchanged']:
        hashes = helper_call(config, 'hash', remote_dir, payload=plan['unchanged'], timeout=timeout)
        report['remote_verify_failed'] = [r for r in plan['unchanged']
                                         if not hashes.get(r) or hashes[r].get('sha256') != scan['files'][r]['sha256']]
    report['fully_archived'] = not plan['upload'] and not report.get('remote_verify_failed')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    for name in ('push', 'status'):
        p = sub.add_parser(name)
        p.add_argument('--project', required=True)
        p.add_argument('--slug', help='ASCII archive folder name when the production folder name is not one')
        p.add_argument('--only', help='comma-separated top-level folders, e.g. assets,renders,deliveries')
        p.add_argument('--timeout', type=int, default=3600)
        if name == 'push':
            p.add_argument('--dry-run', action='store_true')
        else:
            p.add_argument('--verify', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            report = doctor()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report['ready'] else 1
        only = args.only.split(',') if args.only else None
        if args.command == 'push':
            report = push(args.project, args.slug, only, args.dry_run, timeout=args.timeout)
            summary = {k: report[k] for k in ('slug', 'local_files', 'to_upload', 'upload_bytes', 'unchanged', 'dry_run')}
            summary['verified'] = len(report['verified']); summary['mismatched'] = len(report['mismatched']); summary['errors'] = report['errors']
            print(json.dumps(summary, ensure_ascii=False))
            return 0 if not report['errors'] else 1
        report = status(args.project, args.slug, only, args.verify, timeout=args.timeout)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['fully_archived'] else 1
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
