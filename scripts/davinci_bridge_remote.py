"""Station-side DaVinci Resolve helper. Deployed by davinci_bridge.py to <station_archive.root>/_bin.

Runs under the station's own Python (3.10) inside an SSH session and talks to the DaVinci Resolve
Studio open on the VIDEO STATION desktop through Blackmagic's scripting API (fusionscript). Standard
library only: the laptop copies this single file, so it must not import the studio package. Every
command reads its arguments as JSON on stdin (Hebrew and spaces never travel through the SSH command
line) and answers with one JSON object on stdout.

Commands:
  doctor    {"scripting": {...}}                      -> scripting paths, product, version, page, project, timelines
  project   {"name": ..., "create": bool}             -> load (or create and save) the named project on the station
  import    {"manifest": ..., "xml": ..., "out": ...} -> import sequence.xml into the open project and verify

The helper never deletes projects, timelines, bins or media, and never modifies source files.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading

UNSAVED_DEFAULT_PROJECT = 'Untitled Project'
DEFAULT_SCRIPTING = {
    'script_api': 'C:/ProgramData/Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting',
    'script_lib': 'C:/Program Files/Blackmagic Design/DaVinci Resolve/fusionscript.dll',
    'modules': 'C:/ProgramData/Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting/Modules',
}
EDITION_REQUIRED = 'DaVinci Resolve Studio'


# --- small stdlib stand-ins for campaign_common / studio -----------------------------------------

def now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new(path, value):
    """Write JSON to a path that must not exist yet (reports are never overwritten)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))


def read_payload(args):
    """Prefer the base64 argv payload (robust through nested SSH); fall back to stdin JSON."""
    if getattr(args, 'payload_b64', None):
        return json.loads(base64.b64decode(args.payload_b64).decode('utf-8'))
    raw = sys.stdin.buffer.read()
    return json.loads(raw.decode('utf-8')) if raw.strip() else {}


# --- connection ----------------------------------------------------------------------------------

def scripting_config(overrides=None):
    config = dict(DEFAULT_SCRIPTING)
    config.update({key: value for key, value in (overrides or {}).items() if key in DEFAULT_SCRIPTING and value})
    config['edition_required'] = (overrides or {}).get('edition_required', EDITION_REQUIRED)
    return config


def connect(config=None, timeout=20):
    """Return the live `resolve` object or raise ValueError with an actionable reason."""
    config = scripting_config(config)
    modules = Path(config['modules'])
    if not modules.is_dir():
        raise ValueError(f'Resolve scripting modules missing on the station: {modules}. Install DaVinci Resolve Studio there or fix connections.json davinci.station.modules')
    if not Path(config['script_lib']).is_file():
        raise ValueError(f'fusionscript library missing on the station: {config["script_lib"]}')
    os.environ['RESOLVE_SCRIPT_API'] = str(Path(config['script_api']))
    os.environ['RESOLVE_SCRIPT_LIB'] = str(Path(config['script_lib']))
    if str(modules) not in sys.path:
        sys.path.append(str(modules))
    result = {}

    def worker():
        try:
            import DaVinciResolveScript as dvr  # type: ignore[import-not-found]
            result['resolve'] = dvr.scriptapp('Resolve')
        except Exception as error:  # the binding raises generic errors; keep the text
            result['error'] = f'{type(error).__name__}: {error}'

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise ValueError(f'Resolve on the station did not answer within {timeout}s. Is it open on the station desktop, and is Preferences > General > External scripting set to Local?')
    if 'error' in result:
        raise ValueError(f'Resolve scripting import failed on the station: {result["error"]}')
    resolve = result.get('resolve')
    if resolve is None:
        raise ValueError('Resolve on the station refused the connection: open DaVinci Resolve Studio on the station desktop and enable External scripting (Local).')
    product = resolve.GetProductName()
    if config.get('edition_required') and product != config['edition_required']:
        raise ValueError(f'{product} detected on the station; external scripting requires {config["edition_required"]}')
    return resolve


def resolve_state(resolve):
    project = resolve.GetProjectManager().GetCurrentProject()
    return {'product': resolve.GetProductName(), 'version': resolve.GetVersionString(), 'page': resolve.GetCurrentPage(),
            'project': project.GetName() if project else None, 'timelines': int(project.GetTimelineCount() or 0) if project else 0}


# --- commands ------------------------------------------------------------------------------------

def doctor(payload=None, resolve=None):
    payload = payload or {}
    config = scripting_config(payload.get('scripting'))
    report = {'checked_at': now(), 'python': sys.version.split()[0],
              'scripting': {key: {'path': config[key], 'exists': Path(config[key]).exists()} for key in DEFAULT_SCRIPTING},
              'errors': []}
    for key, value in report['scripting'].items():
        if not value['exists']:
            report['errors'].append(f'station scripting {key} missing: {value["path"]}')
    if not report['errors']:
        try:
            resolve = resolve or connect(config)
            report['resolve'] = resolve_state(resolve)
            if report['resolve']['project'] in (None, UNSAVED_DEFAULT_PROJECT):
                report['errors'].append('Open or create a named, saved project on the station before importing (davinci_bridge.py project --host station --create); the never-saved default project silently ignores imports')
        except ValueError as error:
            report['errors'].append(str(error))
    report['ready'] = not report['errors']
    return report


def open_project(name, create=False, resolve=None):
    """Load the named project in the current Resolve database folder, creating it only when asked."""
    if not isinstance(name, str) or not name.strip() or name.strip() != name or name == UNSAVED_DEFAULT_PROJECT:
        raise ValueError('project name must be a nonempty string without surrounding spaces and not the unsaved default project')
    resolve = resolve or connect()
    manager = resolve.GetProjectManager()
    current = manager.GetCurrentProject()
    if current and current.GetName() == name:
        manager.SaveProject()
        project, action = current, 'already-open'
    else:
        if current and current.GetName() != UNSAVED_DEFAULT_PROJECT:
            manager.SaveProject()  # never lose the previously open project's work when switching
        existing = list(manager.GetProjectListInCurrentFolder() or [])
        if name in existing:
            project, action = manager.LoadProject(name), 'loaded'
        elif create:
            project, action = manager.CreateProject(name), 'created'
        else:
            raise ValueError(f'project {name!r} is not in the current Resolve database folder; pass --create to create it')
        if not project:
            raise ValueError(f'Resolve could not open project {name!r} ({action})')
        if not manager.SaveProject():
            raise ValueError(f'Resolve did not save project {name!r}')
    return {'action': action, **resolve_state(resolve), 'database': manager.GetCurrentDatabase()}


def timeline_ids(project):
    ids = {}
    for index in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline:
            ids[str(timeline.GetUniqueId())] = timeline
    return ids


def verify_timeline(timeline, manifest):
    """Compare the created timeline with the manifest. Returns a report; never edits Resolve."""
    errors, items = [], []
    start = int(timeline.GetStartFrame())
    span = int(timeline.GetEndFrame()) - start
    if timeline.GetName() != manifest['timeline_name']:
        errors.append(f'timeline name is {timeline.GetName()!r}, expected {manifest["timeline_name"]!r}')
    if span != manifest['frames']:
        errors.append(f'timeline spans {span} frames, plan has {manifest["frames"]}')
    counts = {'video': int(timeline.GetTrackCount('video')), 'audio': int(timeline.GetTrackCount('audio'))}
    if counts['video'] != manifest['video_tracks']:
        errors.append(f'{counts["video"]} video tracks, expected {manifest["video_tracks"]}')
    if counts['audio'] < manifest['audio_tracks']:
        errors.append(f'{counts["audio"]} audio tracks, expected at least {manifest["audio_tracks"]}')
    offset = start - manifest['timeline_start_frame']
    for record in manifest['expected_items']:
        kind, index = record['track_kind'], record['track_index']
        candidates = timeline.GetItemListInTrack(kind, index) or [] if index <= counts[kind] else []
        wanted_start = record['timeline_start'] + offset
        match = next((i for i in candidates if int(i.GetStart()) == wanted_start), None)
        entry = {'clip': record['id'], 'track': f'{kind[0].upper()}{index}', 'expected_start': wanted_start,
                 'expected_duration': record['duration'], 'found': bool(match)}
        if not match:
            errors.append(f'{record["id"]}: no item starts at frame {wanted_start} on {entry["track"]}')
        else:
            entry['duration'] = int(match.GetDuration())
            entry['left_offset'] = int(match.GetLeftOffset())
            entry['online'] = match.GetMediaPoolItem() is not None
            if entry['duration'] != record['duration']:
                errors.append(f'{record["id"]}: duration {entry["duration"]}, expected {record["duration"]}')
            if record['kind'] != 'image' and entry['left_offset'] != record['source_start']:
                errors.append(f'{record["id"]}: source in {entry["left_offset"]}, expected {record["source_start"]}')
            if not entry['online']:
                errors.append(f'{record["id"]}: media offline in Resolve (is the media on the station under the archive root?)')
        items.append(entry)
    return {'timeline_id': str(timeline.GetUniqueId()), 'timeline_name': timeline.GetName(), 'start_frame': start,
            'span_frames': span, 'tracks': counts, 'items': items, 'errors': errors, 'technical_pass': not errors,
            'creative_review_required': True}


def _setting_number(value):
    """Resolve returns settings as strings ('24.0', '1920'); compare them as numbers."""
    try:
        number = float(str(value).split()[0])
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def import_sequence(manifest_path, out_path, resolve=None, xml_path=None, config=None):
    """Import the hand-off sequence into the open project and verify it. `xml_path` overrides the
    manifest's sequence path because the manifest was written on the laptop with station paths."""
    manifest_path = Path(manifest_path).resolve()
    manifest = load_json(manifest_path)
    xml_path = Path(xml_path or manifest['sequence_xml'])
    if not xml_path.is_file():
        raise ValueError(f'sequence.xml missing on the station: {xml_path}')
    if sha256_file(xml_path) != manifest['sequence_sha256']:
        raise ValueError('sequence.xml changed after export; re-run export-xml so the manifest matches the imported bytes')
    resolve = resolve or connect(config)
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None or project.GetName() == UNSAVED_DEFAULT_PROJECT:
        raise ValueError(f'Open a named, saved project first; Resolve ignores imports into {UNSAVED_DEFAULT_PROJECT!r} without an error')
    before = timeline_ids(project)
    if any(t.GetName() == manifest['timeline_name'] for t in before.values()):
        raise ValueError(f'timeline {manifest["timeline_name"]!r} already exists; choose a new revision name (Resolve returns the old timeline for a repeated name)')
    options = {'timelineName': manifest['timeline_name'], 'importSourceClips': True}
    imported = project.GetMediaPool().ImportTimelineFromFile(str(xml_path), options)
    if not imported:
        created = [t for uid, t in timeline_ids(project).items() if uid not in before]
        imported = created[0] if len(created) == 1 else None
    if not imported:
        raise ValueError('Resolve created no timeline. Check that every media path exists on the station and that the project is saved; see handoff-manifest.json media list')
    settings_applied = {}
    wanted = {'timelineResolutionWidth': manifest['width'], 'timelineResolutionHeight': manifest['height'],
              'timelineFrameRate': manifest['fps']}
    current = {key: _setting_number(imported.GetSetting(key)) for key in wanted}
    if any(current[key] != wanted[key] for key in wanted):
        imported.SetSetting('useCustomSettings', '1')
        for key, value in wanted.items():
            if current[key] != value:
                settings_applied[key] = bool(imported.SetSetting(key, str(value)))
        current = {key: _setting_number(imported.GetSetting(key)) for key in wanted}
    resolve.GetProjectManager().SaveProject()
    report = verify_timeline(imported, manifest)
    report.update({'imported_at': now(), 'host': 'station', 'project': project.GetName(), 'manifest': str(manifest_path),
                   'manifest_sha256': sha256_file(manifest_path), 'sequence_xml': str(xml_path),
                   'sequence_sha256': manifest['sequence_sha256'],
                   'timeline_settings': current, 'settings_applied': settings_applied, 'unmapped': manifest['unmapped'],
                   'resolve': {'product': resolve.GetProductName(), 'version': resolve.GetVersionString()}})
    for key, value in wanted.items():
        if current.get(key) != value:
            report['errors'].append(f'timeline {key} is {current.get(key)}, plan needs {value}')
    report['technical_pass'] = not report['errors']
    if out_path:
        write_new(out_path, report)
    return report


# --- CLI (stdin JSON -> stdout JSON) -------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('doctor', 'project', 'import'))
    parser.add_argument('--payload-b64', dest='payload_b64', help='base64-encoded JSON arguments (preferred over stdin)')
    args = parser.parse_args(argv)
    try:
        payload = read_payload(args)
        scripting = scripting_config(payload.get('scripting'))
        if args.command == 'doctor':
            result = doctor(payload)
        elif args.command == 'project':
            result = open_project(payload.get('name'), bool(payload.get('create')), resolve=connect(scripting))
        else:
            for key in ('manifest', 'xml', 'out'):
                if not payload.get(key):
                    raise ValueError(f'import needs {key} in the JSON payload')
            result = import_sequence(payload['manifest'], payload['out'], xml_path=payload['xml'], config=scripting)
    except (ValueError, OSError) as error:
        sys.stdout.buffer.write(json.dumps({'error': str(error)}, ensure_ascii=False).encode('utf-8'))
        return 1
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
