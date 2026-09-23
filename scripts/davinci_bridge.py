"""DaVinci Resolve Studio hand-off for the campaign studio.

Converts a validated Timeline JSON v1 plan (the same contract `studio.py assemble` consumes)
into an FCP7 XML (xmeml) sequence, imports it into the currently open Resolve project through
the official scripting API, and verifies the created timeline against the plan. No provider
calls, no media modification, no network. Resolve receives the exact conformed cuts, rendered
Blender shots, Hebrew PNG typography layers and finished audio the Blender path already
produces; creative finishing then continues in Resolve or through the `davinci-resolve` MCP.

Commands:
  doctor      read-only: MCP registration in both hosts, scripting paths, live connection
  export-xml  offline: plan.json -> sequence.xml + handoff manifest (no Resolve needed)
  import      live: import sequence.xml into the open project and verify the timeline
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from urllib.parse import quote
from xml.sax.saxutils import escape

from campaign_common import now, sha256_file
from studio import load_json, validate_plan, write_new

SKILL_ROOT = Path(__file__).resolve().parent.parent
REMOTE_HELPER = Path(__file__).resolve().parent / 'davinci_bridge_remote.py'
# Non-interactive SSH: fail fast instead of hanging on an auth or host-key prompt when the bridge is
# itself driven over SSH (OpenClaw on the VPS -> laptop -> station). The station alias supplies the key.
SSH_OPTS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', '-o', 'StrictHostKeyChecking=accept-new']
UNSAVED_DEFAULT_PROJECT = 'Untitled Project'
DEFAULT_SCRIPTING = {
    'script_api': 'C:/ProgramData/Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting',
    'script_lib': 'C:/Program Files/Blackmagic Design/DaVinci Resolve/fusionscript.dll',
    'modules': 'C:/ProgramData/Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting/Modules',
}
# Plan features the xmeml hand-off deliberately does not translate. They are reported per clip so
# the editor applies them in Resolve (or keeps the Blender finish) instead of discovering silently
# missing behaviour on the timeline.
UNMAPPED_FIELDS = {
    'fade_in': 'visual fade: author as opacity keyframes or a Resolve transition',
    'fade_out': 'visual fade: author as opacity keyframes or a Resolve transition',
    'motion': 'motion preset (push-in/zoom/pan/slide/fade-rise): author with Transform keyframes or Fusion',
    'motion_amount': 'amount of the motion preset above (fraction of frame size / scale)',
    'transform_keys': 'camera move: author as Transform keyframes (zoom, position, rotation) on the clip',
    'volume_keys': 'audio envelope: author with clip volume keyframes or Fairlight automation',
}


# ─── connection metadata ─────────────────────────────────────────────────────

def connection_config():
    """Route metadata for Resolve from connections.json; defaults cover a standard Windows install."""
    path = SKILL_ROOT / 'connections.json'
    entry = {}
    if path.is_file():
        entry = load_json(path).get('davinci') or {}
    config = dict(DEFAULT_SCRIPTING)
    config.update({key: entry[key] for key in DEFAULT_SCRIPTING if entry.get(key)})
    config['mcp_server'] = entry.get('mcp_server', 'davinci-resolve')
    config['edition_required'] = entry.get('edition_required', 'DaVinci Resolve Studio')
    return config


def station_config():
    """Route metadata for finishing on the VIDEO STATION: the SSH alias and archive root come from
    the station_archive block (media is mirrored there); Resolve scripting on the station is a
    standard Windows install unless connections.json davinci.station overrides it."""
    path = SKILL_ROOT / 'connections.json'
    data = load_json(path) if path.is_file() else {}
    archive = data.get('station_archive') or {}
    for key in ('ssh_alias', 'root', 'python'):
        if not archive.get(key):
            raise ValueError('connections.json station_archive needs ssh_alias, root and python for the station finishing route')
    station = (data.get('davinci') or {}).get('station') or {}
    scripting = {key: station.get(key) or DEFAULT_SCRIPTING[key] for key in DEFAULT_SCRIPTING}
    return {'ssh_alias': archive['ssh_alias'], 'root': archive['root'], 'python': archive['python'],
            'scripting': scripting, 'mcp_server': station.get('mcp_server', 'davinci-resolve-station'),
            'edition_required': station.get('edition_required', 'DaVinci Resolve Studio')}


def _run_capture(argv, timeout):
    """Run a command with stdout/stderr redirected to temp files, not pipes, and stdin from NUL.
    Windows ssh.exe spawned under sshd (OpenClaw VPS -> laptop -> station) leaks its stdout pipe
    write handle to a child, so a piped read never sees EOF and subprocess.communicate hangs until the
    timeout even though the remote command already finished. Waiting on the process with file handles
    avoids that. Returns (returncode, stdout_text, stderr_text)."""
    with tempfile.TemporaryDirectory() as tmp:
        out_path, err_path = Path(tmp) / 'out', Path(tmp) / 'err'
        with open(out_path, 'wb') as out, open(err_path, 'wb') as err:
            proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=timeout)
        return proc.returncode, out_path.read_bytes().decode('utf-8', 'replace'), err_path.read_bytes().decode('utf-8', 'replace')


def _remote_path(root, *parts):
    return '/'.join([str(root).rstrip('/\\'), *parts])


def station_media_root(config, slug):
    """Where a production's media is mirrored on the station: <archive root>/<slug>."""
    return _remote_path(config['root'], slug)


def deploy_remote_helper(config):
    """Copy the station-side helper to <root>/_bin every run; it is tiny and keeps both sides in step."""
    bin_dir = _remote_path(config['root'], '_bin')
    windows_dir = bin_dir.replace('/', '\\')
    _run_capture(['ssh', *SSH_OPTS, config['ssh_alias'], f'if not exist "{windows_dir}" mkdir "{windows_dir}"'], 60)
    rc, _out, err = _run_capture(['scp', *SSH_OPTS, '-q', str(REMOTE_HELPER), f'{config["ssh_alias"]}:{_remote_path(bin_dir, REMOTE_HELPER.name)}'], 180)
    if rc:
        raise ValueError(f'could not deploy station helper: {err[-400:]}')
    return _remote_path(bin_dir, REMOTE_HELPER.name)


def remote_call(config, command, payload=None, timeout=900):
    """Run one station-helper command over SSH and read one JSON object back. The payload is passed as
    a base64 argv argument (not stdin), and output goes to files (not pipes), so nested SSH (OpenClaw
    VPS -> laptop -> station) never blocks on stdin EOF or the Windows ssh.exe pipe-handle leak. The
    JSON is read even on a non-zero exit so the helper's {'error': ...} survives."""
    helper = _remote_path(config['root'], '_bin', REMOTE_HELPER.name)
    b64 = base64.b64encode(json.dumps(payload or {}, ensure_ascii=False).encode('utf-8')).decode('ascii')
    rc, stdout, stderr = _run_capture(['ssh', *SSH_OPTS, '-n', config['ssh_alias'], config['python'], helper, command, '--payload-b64', b64], timeout)
    stdout = stdout.strip()
    try:
        result = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except (json.JSONDecodeError, IndexError) as error:
        raise ValueError(f'station helper returned no JSON (exit {rc}): {(stdout or stderr)[-500:]}') from error
    if isinstance(result, dict) and result.get('error'):
        raise ValueError(f'station: {result["error"]}')
    return result


def scp_to_station(config, local_path, remote_path):
    """Copy one file to the station, creating its parent directory first. Hebrew/space paths are
    quoted; the sftp-subsystem addresses drives as /D:/... but scp takes the Windows-style target."""
    remote_dir = remote_path.rsplit('/', 1)[0]
    _run_capture(['ssh', *SSH_OPTS, config['ssh_alias'], f'if not exist "{remote_dir.replace("/", chr(92))}" mkdir "{remote_dir.replace("/", chr(92))}"'], 60)
    rc, _out, err = _run_capture(['scp', *SSH_OPTS, '-q', str(local_path), f'{config["ssh_alias"]}:{remote_path}'], 600)
    if rc:
        raise ValueError(f'could not copy {Path(local_path).name} to the station: {err[-400:]}')


def scripting_environment(config):
    env = {
        'RESOLVE_SCRIPT_API': str(Path(config['script_api'])),
        'RESOLVE_SCRIPT_LIB': str(Path(config['script_lib'])),
    }
    return env


def connect(config=None, timeout=20):
    """Return the live `resolve` object or raise ValueError with an actionable reason."""
    config = config or connection_config()
    modules = Path(config['modules'])
    if not modules.is_dir():
        raise ValueError(f'Resolve scripting modules missing: {modules}. Install DaVinci Resolve Studio or fix connections.json davinci.modules')
    if not Path(config['script_lib']).is_file():
        raise ValueError(f'fusionscript library missing: {config["script_lib"]}')
    os.environ.update(scripting_environment(config))
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
        raise ValueError(f'Resolve did not answer within {timeout}s. Is it running, and is Preferences > General > External scripting set to Local?')
    if 'error' in result:
        raise ValueError(f'Resolve scripting import failed: {result["error"]}')
    resolve = result.get('resolve')
    if resolve is None:
        raise ValueError('Resolve refused the connection: start DaVinci Resolve Studio and enable External scripting (Local).')
    product = resolve.GetProductName()
    if config.get('edition_required') and product != config['edition_required']:
        raise ValueError(f'{product} detected; external scripting requires {config["edition_required"]}')
    return resolve


# ─── doctor ──────────────────────────────────────────────────────────────────

def read_claude_registration(server, home):
    path = Path(home) / '.claude.json'
    if not path.is_file():
        return {'configured': False, 'reason': f'{path} missing'}
    try:
        data = load_json(path)
    except ValueError as error:
        return {'configured': False, 'reason': f'unreadable {path.name}: {error}'}
    entry = (data.get('mcpServers') or {}).get(server)
    if not entry:
        return {'configured': False, 'reason': f'no user-scope mcpServers.{server} in {path.name}'}
    return {'configured': True, 'command': entry.get('command'), 'args': entry.get('args'),
            'command_exists': bool(entry.get('command')) and Path(entry['command']).is_file()}


def read_codex_registration(server, home):
    path = Path(os.environ.get('CODEX_HOME', Path(home) / '.codex')) / 'config.toml'
    if not path.is_file():
        return {'configured': False, 'reason': f'{path} missing'}
    header = f'[mcp_servers.{server}]'
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    if header not in [line.strip() for line in lines]:
        return {'configured': False, 'reason': f'no {header} in {path}'}
    command = None
    for index, line in enumerate(lines):
        if line.strip() == header:
            for follow in lines[index + 1:index + 6]:
                if follow.strip().startswith('command'):
                    raw = follow.split('=', 1)[1].strip()
                    # Codex writes TOML literal strings ('...') for paths with backslashes; basic strings ("...") escape them.
                    quote = raw[:1] if raw[:1] in ('"', "'") and raw[-1:] == raw[:1] else ''
                    command = raw[1:-1] if quote else raw
                    if quote == '"':
                        command = command.replace('\\\\', '\\')
            break
    return {'configured': True, 'command': command, 'command_exists': bool(command) and Path(command).is_file()}


def doctor(home=None, live=True):
    home = Path(home or Path.home())
    config = connection_config()
    report = {'checked_at': now(), 'mcp_server': config['mcp_server'],
              'claude_code': read_claude_registration(config['mcp_server'], home),
              'codex': read_codex_registration(config['mcp_server'], home),
              'scripting': {key: {'path': config[key], 'exists': Path(config[key]).exists()} for key in DEFAULT_SCRIPTING},
              'ffprobe': bool(shutil.which('ffprobe')), 'errors': []}
    for host in ('claude_code', 'codex'):
        if not report[host]['configured']:
            report['errors'].append(f'{host}: {report[host]["reason"]}')
        elif not report[host]['command_exists']:
            report['errors'].append(f'{host}: registered command does not exist: {report[host]["command"]}')
    for key, value in report['scripting'].items():
        if not value['exists']:
            report['errors'].append(f'scripting {key} missing: {value["path"]}')
    if not report['ffprobe']:
        report['errors'].append('ffprobe not on PATH; media characteristics cannot be read')
    if live and not report['errors']:
        try:
            resolve = connect(config)
            project = resolve.GetProjectManager().GetCurrentProject()
            report['resolve'] = {'product': resolve.GetProductName(), 'version': resolve.GetVersionString(),
                                 'page': resolve.GetCurrentPage(),
                                 'project': project.GetName() if project else None,
                                 'timelines': project.GetTimelineCount() if project else 0}
            if report['resolve']['project'] in (None, UNSAVED_DEFAULT_PROJECT):
                report['errors'].append('Open or create a named, saved project before importing; the never-saved default project silently ignores imports')
        except ValueError as error:
            report['errors'].append(str(error))
    report['ready'] = not report['errors']
    return report


# ─── station finishing route (renders run on the VIDEO STATION A5000) ─────────

def production_path_map(config, project):
    """(local production root, station media root, slug) for rewriting media paths to the station."""
    project = Path(project).resolve()
    if not project.is_dir():
        raise ValueError(f'production folder missing: {project}')
    slug = project.name
    if not re.match(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$', slug):
        raise ValueError(f'production folder name {slug!r} is not an ASCII slug; the station archive needs an ASCII folder name (rename or archive with --slug first)')
    target = station_media_root(config, slug)
    return project.as_posix(), target, slug


def station_doctor(home=None):
    """Read-only: station Resolve connection over SSH plus the station MCP registration for agents."""
    home = Path(home or Path.home())
    config = station_config()
    report = {'checked_at': now(), 'host': 'station', 'ssh_alias': config['ssh_alias'],
              'archive_root': config['root'], 'mcp_server': config['mcp_server'],
              'claude_code': read_claude_registration(config['mcp_server'], home),
              'codex': read_codex_registration(config['mcp_server'], home),
              'ffprobe': bool(shutil.which('ffprobe')), 'errors': []}
    if not report['ffprobe']:
        report['errors'].append('ffprobe not on PATH here; export-xml on the laptop needs it to describe media')
    try:
        deploy_remote_helper(config)
        station = remote_call(config, 'doctor', {'scripting': config['scripting']}, timeout=120)
        report['station'] = station
        report['errors'].extend(f'station: {error}' for error in station.get('errors', []))
    except (ValueError, subprocess.TimeoutExpired) as error:
        report['errors'].append(str(error))
    for host in ('claude_code', 'codex'):
        if not report[host].get('configured'):
            report['errors'].append(f'{host} MCP {config["mcp_server"]}: {report[host].get("reason")}')
    report['ready'] = not report['errors']
    return report


def station_open_project(name, create=False):
    config = station_config()
    deploy_remote_helper(config)
    return remote_call(config, 'project', {'name': name, 'create': bool(create), 'scripting': config['scripting']}, timeout=180)


def station_import(project, manifest_path, out_path):
    """Push the hand-off to the station and import it into the open station project over SSH."""
    config = station_config()
    manifest_path = Path(manifest_path).resolve()
    manifest = load_json(manifest_path)
    xml_path = Path(manifest['sequence_xml'])
    if manifest.get('finishing_host') != 'station' or not manifest.get('target_media_root'):
        raise ValueError('this manifest was exported for the laptop; re-run export-xml --host station so the media paths point at the station')
    local_root, station_root, slug = production_path_map(config, project)
    # The hand-off files live inside the production folder, so they map to the same place on the station.
    station_xml = remap_path(xml_path.as_posix(), (local_root, station_root))
    station_manifest = remap_path(manifest_path.as_posix(), (local_root, station_root))
    station_out = remap_path(Path(out_path).resolve().as_posix(), (local_root, station_root))
    if station_xml == xml_path.as_posix() or station_manifest == manifest_path.as_posix():
        raise ValueError(f'hand-off files are not under the production folder {local_root}; keep the handoff dir inside the production so it mirrors to the station')
    deploy_remote_helper(config)
    scp_to_station(config, xml_path, station_xml)
    scp_to_station(config, manifest_path, station_manifest)
    report = remote_call(config, 'import',
                         {'manifest': station_manifest, 'xml': station_xml, 'out': station_out, 'scripting': config['scripting']},
                         timeout=900)
    report['station_report'] = station_out
    write_new(out_path, report)  # keep a local copy of the verification next to the hand-off
    return report


# ─── plan -> xmeml ───────────────────────────────────────────────────────────

def probe_media(path):
    """Width/height/duration/channels from ffprobe. Raises ValueError when the file cannot be read."""
    tool = shutil.which('ffprobe')
    if not tool:
        raise ValueError('ffprobe is required to describe media for Resolve; install FFmpeg or add it to PATH')
    result = subprocess.run([tool, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    if result.returncode:
        raise ValueError(f'Cannot inspect media {Path(path).name}: {result.stderr.strip()[:400]}')
    data = json.loads(result.stdout)
    info = {'width': None, 'height': None, 'duration_seconds': None, 'audio_channels': 0, 'sample_rate': None}
    fmt_duration = data.get('format', {}).get('duration')
    for stream in data.get('streams', []):
        if stream.get('codec_type') == 'video' and info['width'] is None:
            info['width'], info['height'] = stream.get('width'), stream.get('height')
            info['duration_seconds'] = stream.get('duration', fmt_duration)
        if stream.get('codec_type') == 'audio' and not info['audio_channels']:
            info['audio_channels'] = int(stream.get('channels') or 0)
            info['sample_rate'] = stream.get('sample_rate')
            info['duration_seconds'] = info['duration_seconds'] or stream.get('duration', fmt_duration)
    info['duration_seconds'] = info['duration_seconds'] or fmt_duration
    return info


def remap_path(posix, path_map):
    """Rewrite a laptop production path to its station location. `path_map` is (local_root, target_root)
    as posix strings. Media outside the production root is left untouched; import then flags it offline."""
    if not path_map:
        return posix
    local_root, target_root = (str(p).replace('\\', '/').rstrip('/') for p in path_map)
    low = posix.lower()
    if low == local_root.lower():
        return target_root
    if low.startswith(local_root.lower() + '/'):
        return target_root + posix[len(local_root):]
    return posix


def path_url(path, path_map=None):
    posix = remap_path(Path(path).resolve().as_posix(), path_map)
    return 'file:///' + quote(posix.lstrip('/'), safe="/:")


def validate_timeline_name(name):
    if not isinstance(name, str) or not name.strip() or name.strip() != name:
        raise ValueError('timeline name must be a nonempty string without surrounding spaces')
    if any(ch in name for ch in '<>&"\\/'):
        raise ValueError('timeline name must not contain < > & " \\ or /')
    return name


def _rate(fps, indent):
    pad = ' ' * indent
    return f'{pad}<rate>\n{pad}    <timebase>{fps}</timebase>\n{pad}    <ntsc>FALSE</ntsc>\n{pad}</rate>\n'


def _file_element(file_id, clip_path, fps, media, indent, path_map=None):
    pad = ' ' * indent
    frames = media['frames']
    out = [f'{pad}<file id="{escape(file_id)}">\n', f'{pad}    <name>{escape(Path(clip_path).name)}</name>\n',
           f'{pad}    <pathurl>{escape(path_url(clip_path, path_map))}</pathurl>\n', _rate(fps, indent + 4),
           f'{pad}    <duration>{frames}</duration>\n', f'{pad}    <media>\n']
    if media['width']:
        out.append(f'{pad}        <video>\n{pad}            <duration>{frames}</duration>\n'
                   f'{pad}            <samplecharacteristics>\n{pad}                <width>{media["width"]}</width>\n'
                   f'{pad}                <height>{media["height"]}</height>\n{pad}            </samplecharacteristics>\n'
                   f'{pad}        </video>\n')
    if media['audio_channels']:
        out.append(f'{pad}        <audio>\n{pad}            <channelcount>{media["audio_channels"]}</channelcount>\n{pad}        </audio>\n')
    out.append(f'{pad}    </media>\n{pad}</file>\n')
    return ''.join(out)


def _clipitem(clip, item_id, file_id, file_xml, fps, media, timeline_start):
    pad = ' ' * 20
    start = clip['start'] - 1
    end = start + clip['duration']
    source_in = clip.get('source_start', 0)
    kind = clip['kind']
    out = [f'{pad}<clipitem id="{escape(item_id)}">\n', f'{pad}    <name>{escape(clip["id"])}</name>\n',
           f'{pad}    <duration>{media["frames"]}</duration>\n', _rate(fps, 24),
           f'{pad}    <start>{start}</start>\n', f'{pad}    <end>{end}</end>\n', f'{pad}    <enabled>TRUE</enabled>\n',
           f'{pad}    <in>{source_in}</in>\n', f'{pad}    <out>{source_in + clip["duration"]}</out>\n']
    out.append(file_xml if file_xml else f'{pad}    <file id="{escape(file_id)}"/>\n')
    if kind == 'sound':
        out.append(f'{pad}    <sourcetrack>\n{pad}        <mediatype>audio</mediatype>\n{pad}        <trackindex>1</trackindex>\n{pad}    </sourcetrack>\n')
        level = float(clip.get('volume', 1))
        out.append(f'{pad}    <filter>\n{pad}        <enabled>TRUE</enabled>\n{pad}        <start>0</start>\n{pad}        <end>{clip["duration"]}</end>\n'
                   f'{pad}        <effect>\n{pad}            <name>Audio Levels</name>\n{pad}            <effectid>audiolevels</effectid>\n'
                   f'{pad}            <effecttype>audiolevels</effecttype>\n{pad}            <mediatype>audio</mediatype>\n'
                   f'{pad}            <parameter>\n{pad}                <name>Level</name>\n{pad}                <parameterid>level</parameterid>\n'
                   f'{pad}                <value>{level:g}</value>\n{pad}            </parameter>\n{pad}        </effect>\n{pad}    </filter>\n')
    else:
        opacity = float(clip.get('opacity', 1)) * 100
        out.append(f'{pad}    <compositemode>normal</compositemode>\n')
        out.append(f'{pad}    <filter>\n{pad}        <enabled>TRUE</enabled>\n{pad}        <start>0</start>\n{pad}        <end>{clip["duration"]}</end>\n'
                   f'{pad}        <effect>\n{pad}            <name>Opacity</name>\n{pad}            <effectid>opacity</effectid>\n'
                   f'{pad}            <effecttype>motion</effecttype>\n{pad}            <mediatype>video</mediatype>\n'
                   f'{pad}            <parameter>\n{pad}                <name>opacity</name>\n{pad}                <parameterid>opacity</parameterid>\n'
                   f'{pad}                <value>{opacity:g}</value>\n{pad}            </parameter>\n{pad}        </effect>\n{pad}    </filter>\n')
    out.append(f'{pad}</clipitem>\n')
    return ''.join(out), {'id': clip['id'], 'kind': kind, 'track_kind': 'audio' if kind == 'sound' else 'video',
                          'timeline_start': timeline_start + start, 'duration': clip['duration'],
                          'source_start': source_in, 'path': clip['path']}


def _resolve_clip(clip):
    """Image sequences are a Blender VSE feature; Resolve receives the companion movie instead
    (`studio.py alpha-movie` renders a ProRes 4444 with alpha from the same frames)."""
    if clip['kind'] != 'image-sequence':
        return clip
    movie = clip.get('resolve_movie')
    if not movie:
        raise ValueError(f'{clip["id"]}: image-sequence needs resolve_movie (render it with `studio.py alpha-movie`) '
                         'for the Resolve hand-off')
    return {**clip, 'kind': 'movie', 'path': movie, 'source_start': clip.get('source_start', 0)}


def build_sequence(plan, timeline_name, probe=probe_media, timeline_start_frame=None, path_map=None):
    """Return (xml_text, manifest) for a validated plan. `probe` reads media characteristics.
    `path_map` (local_root, station_root) rewrites the media pathurls to the station finishing host;
    media is still hashed locally so the manifest verifies the same bytes on either machine."""
    validate_timeline_name(timeline_name)
    fps = plan['fps']
    start_frame = timeline_start_frame if timeline_start_frame is not None else 3600 * fps
    media_by_path, unmapped, expected = {}, [], []
    clips = [_resolve_clip(clip) for clip in plan['clips']]
    for clip in clips:
        for field, note in UNMAPPED_FIELDS.items():
            value = clip.get(field)
            if value not in (None, 0, 'none', []):
                unmapped.append({'clip': clip['id'], 'field': field, 'value': value, 'apply_in_resolve': note})
        if clip['path'] not in media_by_path:
            info = probe(clip['path'])
            if clip['kind'] == 'image':
                frames = clip['duration']
            else:
                if info.get('duration_seconds') is None:
                    raise ValueError(f'{clip["id"]}: source duration unknown; normalize media before hand-off')
                frames = max(1, int(round(float(info['duration_seconds']) * fps)))
            media_by_path[clip['path']] = {'frames': frames, 'width': info.get('width'), 'height': info.get('height'),
                                           'audio_channels': int(info.get('audio_channels') or 0), 'sha256': sha256_file(clip['path'])}
        else:
            media = media_by_path[clip['path']]
            if clip['kind'] == 'image':
                media['frames'] = max(media['frames'], clip['duration'])
    video_channels = sorted({c['channel'] for c in clips if c['kind'] != 'sound'})
    audio_channels = sorted({c['channel'] for c in clips if c['kind'] == 'sound'})
    emitted_files, counter = set(), 0

    def track_xml(kind, channel):
        nonlocal counter
        items = sorted((c for c in clips if c['channel'] == channel and ((c['kind'] == 'sound') == (kind == 'audio'))),
                       key=lambda c: c['start'])
        parts = ['                <track>\n']
        for clip in items:
            counter += 1
            file_id = f'file-{list(media_by_path).index(clip["path"]) + 1}'
            file_xml = None
            if file_id not in emitted_files:
                emitted_files.add(file_id)
                file_xml = _file_element(file_id, clip['path'], fps, media_by_path[clip['path']], 24, path_map)
            xml, record = _clipitem(clip, f'item-{counter}', file_id, file_xml, fps, media_by_path[clip['path']], start_frame)
            record['track_index'] = (video_channels if kind == 'video' else audio_channels).index(channel) + 1
            expected.append(record)
            parts.append(xml)
        parts.append('                </track>\n')
        return ''.join(parts)

    video_tracks = ''.join(track_xml('video', ch) for ch in video_channels)
    audio_tracks = ''.join(track_xml('audio', ch) for ch in audio_channels)
    hours, rem = divmod(start_frame // fps, 3600)
    minutes, seconds = divmod(rem, 60)
    timecode = f'{hours:02d}:{minutes:02d}:{seconds:02d}:{start_frame % fps:02d}'
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="5">\n    <sequence>\n'
        f'        <name>{escape(timeline_name)}</name>\n        <duration>{plan["frames"]}</duration>\n'
        + _rate(fps, 8)
        + f'        <timecode>\n            <string>{timecode}</string>\n            <frame>{start_frame}</frame>\n'
          f'            <displayformat>NDF</displayformat>\n{_rate(fps, 12)}        </timecode>\n'
          '        <media>\n            <video>\n                <format>\n                    <samplecharacteristics>\n'
        + _rate(fps, 24)
        + f'                        <width>{plan["width"]}</width>\n                        <height>{plan["height"]}</height>\n'
          '                    </samplecharacteristics>\n                </format>\n'
        + video_tracks + '            </video>\n'
        + ('            <audio>\n' + audio_tracks + '            </audio>\n' if audio_tracks else '')
        + '        </media>\n    </sequence>\n</xmeml>\n'
    )
    manifest = {'schema_version': 1, 'created_at': now(), 'timeline_name': timeline_name, 'fps': fps,
                'width': plan['width'], 'height': plan['height'], 'frames': plan['frames'],
                'timeline_start_frame': start_frame, 'video_tracks': len(video_channels), 'audio_tracks': len(audio_channels),
                'expected_items': expected, 'media': media_by_path, 'unmapped': unmapped,
                'finishing_host': 'station' if path_map else 'laptop',
                'target_media_root': str(path_map[1]).replace('\\', '/').rstrip('/') if path_map else None,
                'hebrew_note': 'Text layers are the PNG renders from render_text.py / captions.py; do not retype Hebrew into Text+.'}
    return xml, manifest


def export_xml(plan_path, out_dir, timeline_name, probe=probe_media, path_map=None):
    plan_path = Path(plan_path).resolve()
    plan, warnings = validate_plan(plan_path, probe=False)
    xml, manifest = build_sequence(plan, timeline_name, probe=probe, path_map=path_map)
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    xml_path = out / 'sequence.xml'
    xml_path.write_text(xml, encoding='utf-8')
    manifest.update({'plan': str(plan_path), 'plan_sha256': sha256_file(plan_path), 'plan_warnings': warnings,
                     'sequence_xml': str(xml_path), 'sequence_sha256': sha256_file(xml_path)})
    write_new(out / 'handoff-manifest.json', manifest)
    return manifest


# ─── live import + verification ──────────────────────────────────────────────

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
                errors.append(f'{record["id"]}: media offline in Resolve')
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


def import_sequence(manifest_path, out_path, resolve=None):
    manifest_path = Path(manifest_path).resolve()
    manifest = load_json(manifest_path)
    xml_path = Path(manifest['sequence_xml'])
    if not xml_path.is_file():
        raise ValueError(f'sequence.xml missing: {xml_path}')
    if sha256_file(xml_path) != manifest['sequence_sha256']:
        raise ValueError('sequence.xml changed after export; re-run export-xml so the manifest matches the imported bytes')
    resolve = resolve or connect()
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
        raise ValueError('Resolve created no timeline. Check that every media path exists on this machine and that the project is saved; see handoff-manifest.json media list')
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
    report = verify_timeline(imported, manifest)
    report.update({'imported_at': now(), 'project': project.GetName(), 'manifest': str(manifest_path),
                   'manifest_sha256': sha256_file(manifest_path), 'sequence_sha256': manifest['sequence_sha256'],
                   'timeline_settings': current, 'settings_applied': settings_applied, 'unmapped': manifest['unmapped'],
                   'resolve': {'product': resolve.GetProductName(), 'version': resolve.GetVersionString()}})
    for key, value in wanted.items():
        if current.get(key) != value:
            report['errors'].append(f'timeline {key} is {current.get(key)}, plan needs {value}')
    report['technical_pass'] = not report['errors']
    write_new(out_path, report)
    return report


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    doc = sub.add_parser('doctor', help='read-only registration and connection check')
    doc.add_argument('--host', choices=('laptop', 'station'), default='laptop', help='where Resolve finishing runs (default: laptop)')
    doc.add_argument('--no-live', action='store_true', help='skip the live Resolve connection (laptop only)')
    prj = sub.add_parser('project', help='open (or create) a named, saved Resolve project on the finishing host')
    prj.add_argument('--host', choices=('laptop', 'station'), default='station', help='where the project lives (default: station)')
    prj.add_argument('--name', required=True, help='project name, e.g. the production slug')
    prj.add_argument('--create', action='store_true', help='create it if the database folder has no such project')
    exp = sub.add_parser('export-xml', help='plan.json -> sequence.xml + handoff manifest')
    exp.add_argument('--host', choices=('laptop', 'station'), default='laptop', help='finishing host the media paths target (default: laptop)')
    exp.add_argument('--plan', required=True)
    exp.add_argument('--out-dir', required=True)
    exp.add_argument('--timeline-name', required=True, help='unique per revision, e.g. CUT_v001')
    exp.add_argument('--project', help='local production folder (required with --host station: media is remapped to <archive root>/<folder name>)')
    imp = sub.add_parser('import', help='import the exported sequence into the open Resolve project')
    imp.add_argument('--host', choices=('laptop', 'station'), default='laptop', help='where to import and verify (default: laptop)')
    imp.add_argument('--manifest', required=True, help='handoff-manifest.json from export-xml')
    imp.add_argument('--out', required=True, help='verification report path (must not exist)')
    imp.add_argument('--project', help='local production folder (required with --host station)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            report = station_doctor() if args.host == 'station' else doctor(live=not args.no_live)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report['ready'] else 1
        if args.command == 'project':
            if args.host == 'laptop':
                raise ValueError('the laptop project is opened by hand in Resolve; --host station opens it on the station over SSH')
            report = station_open_project(args.name, args.create)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if args.command == 'export-xml':
            path_map = None
            if args.host == 'station':
                if not args.project:
                    raise ValueError('export-xml --host station needs --project <local production folder> to remap media to the station')
                local_root, station_root, _ = production_path_map(station_config(), args.project)
                path_map = (local_root, station_root)
            manifest = export_xml(args.plan, args.out_dir, args.timeline_name, path_map=path_map)
            print(json.dumps({'sequence_xml': manifest['sequence_xml'], 'finishing_host': manifest['finishing_host'],
                              'target_media_root': manifest['target_media_root'], 'expected_items': len(manifest['expected_items']),
                              'unmapped': len(manifest['unmapped']), 'plan_warnings': manifest['plan_warnings']}, ensure_ascii=False))
            return 0
        if args.host == 'station':
            if not args.project:
                raise ValueError('import --host station needs --project <local production folder>')
            report = station_import(args.project, args.manifest, args.out)
        else:
            report = import_sequence(args.manifest, args.out)
        print(json.dumps({'host': args.host, 'technical_pass': report['technical_pass'], 'timeline': report['timeline_name'],
                          'errors': report['errors'], 'report': str(Path(args.out).resolve())}, ensure_ascii=False))
        return 0 if report['technical_pass'] else 1
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
