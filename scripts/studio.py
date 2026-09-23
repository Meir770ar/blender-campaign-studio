"""Local production preparation and validated Blender assembly. No provider calls."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

RENDER_COMMANDS = ('render-prepare', 'render-submit', 'render-start', 'render-status', 'render-collect', 'render-verify', 'render-doctor')
ARCHIVE_COMMANDS = ('archive-push', 'archive-status', 'archive-doctor')
SEQUENCE_COMMANDS = ('still', 'alpha-sequence', 'alpha-movie')
MOTIONS = ('none', 'fade-rise', 'push-in', 'zoom-in', 'zoom-out', 'pan-left', 'pan-right',
           'slide-left', 'slide-right', 'slide-down')
TRANSFORM_FIELDS = {'frame', 'scale', 'offset_x', 'offset_y', 'rotation'}

IMAGE_TYPES = {'.png', '.jpg', '.jpeg', '.webp'}
VIDEO_TYPES = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}
AUDIO_TYPES = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg'}


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))


def integer(value, name, minimum=0, maximum=10000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
    return value


def number(value, name, minimum=0, maximum=100):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be finite and in [{minimum}, {maximum}]')
    return value


def source_path(value, base):
    if not isinstance(value, str) or not value.strip() or '://' in value:
        raise ValueError('Media must have a nonempty local file path')
    path = Path(value)
    if not path.is_absolute():
        path = Path(base) / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f'Media file missing: {path}')
    return path


def validate_transform_keys(keys, name, duration):
    """Explicit camera-move keyframes on a visual strip: a clip-relative frame plus any of scale
    (multiplies the fitted size), offset_x/offset_y (output pixels) and rotation (degrees)."""
    if not isinstance(keys, list) or len(keys) < 2:
        raise ValueError(f'{name}: transform_keys needs at least two keyframes')
    previous = -1
    for key in keys:
        if not isinstance(key, dict) or 'frame' not in key or not set(key) <= TRANSFORM_FIELDS or len(key) < 2:
            raise ValueError(f'{name}: each transform key is an object with frame and at least one of '
                             'scale, offset_x, offset_y, rotation')
        frame = integer(key['frame'], f'{name}.transform_keys.frame', 0, duration - 1)
        if frame <= previous:
            raise ValueError(f'{name}: transform key frames must strictly increase')
        previous = frame
        if 'scale' in key:
            number(key['scale'], f'{name}.transform_keys.scale', 0.05, 20)
        for axis in ('offset_x', 'offset_y'):
            if axis in key:
                number(key[axis], f'{name}.transform_keys.{axis}', -8192, 8192)
        if 'rotation' in key:
            number(key['rotation'], f'{name}.transform_keys.rotation', -360, 360)
    return keys


def sequence_files(first, duration, hold_last, name):
    """Frames of an image sequence: the first file and its siblings (same folder and extension,
    sorted by name) for `duration` frames. Fewer frames than the clip is an error unless hold_last
    freezes the final frame for the remainder."""
    siblings = sorted(p for p in first.parent.iterdir() if p.is_file() and p.suffix.lower() == first.suffix.lower())
    files = siblings[siblings.index(first):][:duration]
    if len(files) < duration:
        if not hold_last:
            raise ValueError(f'{name}: image sequence has {len(files)} frames from {first.name} but the clip lasts '
                             f'{duration}; render more frames or set hold_last:true')
        files = files + [files[-1]] * (duration - len(files))
    return [str(p) for p in files]


def ffprobe(path):
    tool = shutil.which('ffprobe')
    if not tool:
        raise ValueError('ffprobe is required for media validation; install FFmpeg or add it to PATH')
    result = subprocess.run([tool, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    if result.returncode:
        raise ValueError(f'Cannot inspect media {path.name}: {result.stderr.strip()[:400]}')
    data = json.loads(result.stdout)
    streams = []
    for stream in data.get('streams', []):
        streams.append({key: stream[key] for key in ('codec_type', 'codec_name', 'width', 'height',
                       'r_frame_rate', 'avg_frame_rate', 'sample_rate', 'channels', 'duration') if key in stream})
    return {'duration_seconds': data.get('format', {}).get('duration'), 'streams': streams}


def validate_plan(path, probe=True):
    path = Path(path).resolve()
    plan = load_json(path)
    if not isinstance(plan, dict) or plan.get('version') != 1:
        raise ValueError('Plan must be an object with version=1')
    integer(plan.get('width'), 'width', 16, 8192)
    integer(plan.get('height'), 'height', 16, 8192)
    if plan['width'] % 2 or plan['height'] % 2:
        raise ValueError('Width and height must be even for H.264 delivery')
    fps = integer(plan.get('fps'), 'fps', 1, 120)
    end = integer(plan.get('frames'), 'frames', 1, fps * 600)
    clips = plan.get('clips')
    if not isinstance(clips, list) or not clips:
        raise ValueError('Plan requires at least one clip')
    names, occupied, visuals, warnings = set(), {}, [], []
    for index, clip in enumerate(clips):
        if not isinstance(clip, dict):
            raise ValueError(f'Clip {index} must be an object')
        name = clip.get('id')
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError('Clip IDs must be unique nonempty strings')
        names.add(name)
        kind = clip.get('kind')
        if kind not in ('image', 'image-sequence', 'movie', 'sound'):
            raise ValueError(f'{name}: kind must be image, image-sequence, movie or sound')
        file = source_path(clip.get('path'), path.parent)
        types = IMAGE_TYPES if kind in ('image', 'image-sequence') else VIDEO_TYPES if kind == 'movie' else AUDIO_TYPES | VIDEO_TYPES
        if file.suffix.lower() not in types:
            raise ValueError(f'{name}: unsupported extension for {kind}')
        clip['path'] = str(file)
        start = integer(clip.get('start'), f'{name}.start', 1, end)
        duration = integer(clip.get('duration'), f'{name}.duration', 1, end)
        if start + duration - 1 > end:
            raise ValueError(f'{name}: clip exceeds timeline')
        channel = integer(clip.get('channel'), f'{name}.channel', 1, 128)
        for other_start, other_end in occupied.setdefault(channel, []):
            if start < other_end and other_start < start + duration:
                raise ValueError(f'{name}: overlaps another clip on channel {channel}')
        occupied[channel].append((start, start + duration))
        in_frame = integer(clip.get('source_start', 0), f'{name}.source_start')
        if kind in ('image', 'image-sequence') and in_frame:
            raise ValueError(f'{name}: image cannot have source_start')
        fade_in = integer(clip.get('fade_in', 0), f'{name}.fade_in', 0, duration - 1)
        fade_out = integer(clip.get('fade_out', 0), f'{name}.fade_out', 0, duration - 1)
        if fade_in + fade_out >= duration:
            raise ValueError(f'{name}: fades consume entire clip')
        if kind != 'sound':
            visuals.append((start, start + duration))
            number(clip.get('opacity', 1), f'{name}.opacity', 0, 1)
            motion = clip.get('motion', 'none')
            if motion not in MOTIONS:
                raise ValueError(f'{name}: unsupported motion; use one of {", ".join(MOTIONS)}')
            if 'motion_amount' in clip:
                number(clip['motion_amount'], f'{name}.motion_amount', 0.005, 0.5)
                if motion == 'none':
                    raise ValueError(f'{name}: motion_amount requires a motion preset')
            if 'transform_keys' in clip:
                if motion != 'none':
                    raise ValueError(f'{name}: use either a motion preset or transform_keys, not both')
                validate_transform_keys(clip['transform_keys'], name, duration)
            if kind == 'image-sequence':
                if type(clip.get('hold_last', False)) is not bool:
                    raise ValueError(f'{name}: hold_last must be true or false')
                clip['sequence_files'] = sequence_files(file, duration, clip.get('hold_last', False), name)
                if clip.get('resolve_movie') is not None:
                    movie = source_path(clip['resolve_movie'], path.parent)
                    if movie.suffix.lower() not in VIDEO_TYPES:
                        raise ValueError(f'{name}: resolve_movie must be a movie file')
                    clip['resolve_movie'] = str(movie)
            elif 'hold_last' in clip or 'resolve_movie' in clip:
                raise ValueError(f'{name}: hold_last/resolve_movie apply to image-sequence clips only')
            if 'volume' in clip or 'volume_keys' in clip:
                raise ValueError(f'{name}: audio must be an explicit sound strip')
        else:
            if clip.get('motion', 'none') != 'none' or 'motion_amount' in clip or 'transform_keys' in clip:
                raise ValueError(f'{name}: sound cannot have visual motion')
            if fade_in or fade_out:
                raise ValueError(f'{name}: use volume_keys for audio fades')
            number(clip.get('volume', 1), f'{name}.volume', 0, 4)
            keys = clip.get('volume_keys', [])
            if not isinstance(keys, list):
                raise ValueError(f'{name}: volume_keys must be a list')
            previous = -1
            for key in keys:
                if not isinstance(key, list) or len(key) != 2:
                    raise ValueError(f'{name}: volume key must be [relative_frame, volume]')
                integer(key[0], 'volume key frame', 0, duration - 1)
                number(key[1], 'volume key gain', 0, 4)
                if key[0] <= previous:
                    raise ValueError(f'{name}: volume key frames must strictly increase')
                previous = key[0]
        if clip.get('text_source'):
            clip['text_source'] = str(source_path(clip['text_source'], path.parent))
        if probe:
            info = ffprobe(file)
            expected = 'audio' if kind == 'sound' else 'video'
            if not any(s.get('codec_type') == expected for s in info['streams']):
                raise ValueError(f'{name}: required {expected} stream missing')
            picture = next((s for s in info['streams'] if s.get('codec_type') == 'video'), None)
            if kind != 'sound' and picture and picture.get('width') and picture.get('height'):
                enlarges = clip.get('motion', 'none') in ('push-in', 'zoom-in', 'zoom-out', 'pan-left', 'pan-right') or \
                    any(key.get('scale', 1) > 1 for key in clip.get('transform_keys', []))
                if enlarges and (picture['width'] < plan['width'] or picture['height'] < plan['height']):
                    warnings.append(f'{name}: source {picture["width"]}x{picture["height"]} is smaller than the '
                                    f'{plan["width"]}x{plan["height"]} timeline and its motion enlarges it further; '
                                    'expect softness (upscale the source or drop the motion)')
            if kind not in ('image', 'image-sequence'):
                matching = [s for s in info['streams'] if s.get('codec_type') == expected]
                available = matching[0].get('duration', info['duration_seconds'])
                if available is None:
                    raise ValueError(f'{name}: source duration unknown; normalize media before assembly')
                if (in_frame + duration) / fps > float(available) + 0.5 / fps:
                    raise ValueError(f'{name}: requested trim exceeds source duration')
                if kind == 'movie':
                    rate = matching[0].get('avg_frame_rate', '0/1')
                    top, bottom = rate.split('/')
                    if not float(bottom) or abs(float(top) / float(bottom) - fps) > 0.001:
                        raise ValueError(f'{name}: normalize movie to constant {fps} fps before assembly')
                    if matching[0].get('r_frame_rate') != rate:
                        warnings.append(f'{name}: possible variable frame rate; inspect or normalize it')
    visual_clips = [c for c in clips if c['kind'] != 'sound']
    moving = [c for c in visual_clips if c.get('motion', 'none') != 'none' or c.get('transform_keys')]
    if len(visual_clips) >= 5 and len(moving) > 0.6 * len(visual_clips):
        warnings.append(f'{len(moving)} of {len(visual_clips)} visual strips move; the doctrine is no automatic effect '
                        'per shot, keep motion where the story needs it')
    presets = sorted((c for c in visual_clips if c.get('motion', 'none') != 'none'), key=lambda c: (c['start'], c['channel']))
    for left, right in zip(presets, presets[1:]):
        if left['motion'] == right['motion']:
            warnings.append(f'{left["id"]} and {right["id"]} use the same motion preset back to back ({left["motion"]}); vary or remove one')
    cursor = 1
    for start, stop in sorted(visuals):
        if start > cursor:
            raise ValueError(f'No visual strip covers frames {cursor}..{start - 1}')
        cursor = max(cursor, stop)
    if cursor <= end:
        raise ValueError(f'No visual strip covers frames {cursor}..{end}')
    return plan, warnings


def find_blender(explicit=None):
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_file():
            raise ValueError('Supplied Blender executable does not exist')
        return str(path)
    direct = shutil.which('blender')
    if direct:
        return direct
    base = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Blender Foundation'
    candidates = sorted(base.glob('Blender */blender.exe')) if base.exists() else []
    if not candidates:
        raise ValueError('Blender not found; pass --blender with its executable path')
    supported = base / 'Blender 5.1' / 'blender.exe'
    if supported.is_file():
        return str(supported)
    found = ', '.join(sorted(c.parent.name for c in candidates))
    raise ValueError(f'Blender 5.1 not found (installed: {found}). Assembly is validated on 5.1 only; '
                     'install it or pass --blender to a build you have explicitly compatibility-checked')


def main(argv=None):
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] == 'production-status':
        from production_status import main as status_main
        return status_main(raw_args[1:])
    if raw_args and raw_args[0] in ARCHIVE_COMMANDS:
        from station_archive import main as archive_main
        return archive_main([raw_args[0].split('-', 1)[1], *raw_args[1:]])
    if raw_args and raw_args[0] in RENDER_COMMANDS:
        from render_dispatch import main as render_main
        return render_main([raw_args[0].removeprefix('render-'), *raw_args[1:]])
    if raw_args and raw_args[0] in SEQUENCE_COMMANDS:
        from sequence_tools import main as sequence_main
        return sequence_main(raw_args)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    status = sub.add_parser('production-status')
    status.add_argument('--project', required=True)
    sub.add_parser('doctor')
    init = sub.add_parser('init')
    init.add_argument('--project', required=True)
    idea = init.add_mutually_exclusive_group(required=True)
    idea.add_argument('--idea')
    idea.add_argument('--idea-file')
    inv = sub.add_parser('inventory')
    inv.add_argument('--source', required=True)
    inv.add_argument('--out', required=True)
    check = sub.add_parser('validate')
    check.add_argument('--plan', required=True)
    assemble = sub.add_parser('assemble')
    assemble.add_argument('--plan', required=True)
    assemble.add_argument('--out-dir', required=True)
    assemble.add_argument('--blender')
    assemble.add_argument('--render', action='store_true', help='Render MP4 after saving .blend')
    for name in RENDER_COMMANDS + ARCHIVE_COMMANDS + SEQUENCE_COMMANDS:
        routed = sub.add_parser(name, add_help=False)
        routed.add_argument('render_args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == 'production-status':
        raise AssertionError('Production status is routed before local argument parsing')
    if args.command in RENDER_COMMANDS:
        raise AssertionError('Render commands are routed before local argument parsing')
    if args.command == 'doctor':
        try:
            blender = find_blender()
        except ValueError:
            blender = None
        modules = {name: bool(importlib.util.find_spec(name)) for name in ['playwright', 'fontTools']}
        print(json.dumps({'blender': blender, 'ffmpeg': shutil.which('ffmpeg'), 'ffprobe': shutil.which('ffprobe'),
              'modules': modules, 'font_index': str(Path.home() / 'fonts-library/INDEX.md'),
              'note': 'Run a text render to verify the installed Chromium runtime.'}, ensure_ascii=False, indent=2))
    elif args.command == 'init':
        idea = args.idea if args.idea is not None else Path(args.idea_file).read_text(encoding='utf-8-sig')
        if not idea.strip():
            raise ValueError('The free-text idea cannot be empty')
        template_root = Path(__file__).resolve().parent.parent / 'templates'
        templates = [template_root / 'direction-v1.json', template_root / 'shots-v1.json']
        if not all(path.is_file() for path in templates):
            raise ValueError('Installed creative contract templates are missing')
        project = Path(args.project).resolve()
        project.mkdir(parents=True, exist_ok=False)
        for folder in ('assets', 'analysis', 'planning', 'typography', 'jobs', 'reviews',
                       'renders', 'revisions', 'deliveries'):
            (project / folder).mkdir()
        write_new(project / 'idea.txt', idea)
        write_new(project / 'interview.json', {'version': 1, 'status': 'intake', 'answers': [], 'assumptions': [], 'open_questions': []})
        write_new(project / 'production.json', {
            'version': 1,
            'status': 'intake',
            'required_artifacts': {
                'direction': ['brief.md', 'direction.md', 'planning/direction-v1.json'],
                'styleframes': ['storyboard.md', 'planning/shots-v1.json', 'planning/direction-gate.json'],
                'paid_motion': ['planning/paid-motion-gate.json', 'jobs/<semantic-hash>/job.json'],
                'rough_cut': ['planning/rough-cut-gate.json', 'reviews/<shot-revision>/review-report.json'],
                'delivery': ['delivery-qa.json', 'deliveries/<approved-master>'],
            },
            'external_actions_authorized_by_initialization': [],
        })
        for template in templates:
            shutil.copyfile(template, project / 'planning' / template.name.replace('.json', '.template.json'))
        print(str(project))
    elif args.command == 'inventory':
        source = Path(args.source).resolve()
        if not source.is_dir():
            raise ValueError('Source must be an existing folder')
        if Path(args.out).exists():
            raise ValueError('Inventory output exists; use a new revision path')
        entries = []
        for path in sorted(source.rglob('*')):
            if not path.is_file() or not path.resolve().is_relative_to(source):
                continue
            if path.suffix.lower() not in IMAGE_TYPES | VIDEO_TYPES | AUDIO_TYPES:
                continue
            item = {'path': str(path), 'bytes': path.stat().st_size}
            try:
                item.update(ffprobe(path))
            except ValueError as error:
                item['inspection_error'] = str(error)
            entries.append(item)
        write_new(args.out, {'source': str(source), 'media': entries})
        print(json.dumps({'media_count': len(entries), 'inspection_errors': sum('inspection_error' in e for e in entries)}))
    else:
        plan, warnings = validate_plan(args.plan)
        if args.command == 'validate':
            print(json.dumps({'valid': True, 'clips': len(plan['clips']), 'warnings': warnings}, ensure_ascii=False))
            return
        executable = find_blender(args.blender)
        output = Path(args.out_dir).resolve()
        output.mkdir(parents=True, exist_ok=False)
        resolved = output / 'resolved-plan.json'
        write_new(resolved, plan)
        script = Path(__file__).with_name('assemble_blender.py')
        command = [executable, '--background', '--factory-startup', '--python-exit-code', '1', '--python', str(script),
                   '--', '--plan', str(resolved), '--out-dir', str(output)]
        if args.render:
            command.append('--render')
        with (output / 'blender.log').open('w', encoding='utf-8') as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if completed.returncode:
            raise ValueError(f'Blender failed ({completed.returncode}); inspect {output / "blender.log"}. Use a new output directory after repair.')
        blend = output / 'project.blend'
        if not blend.is_file():
            raise ValueError('Blender returned without creating project.blend; inspect blender.log')
        report = {'blend': str(blend), 'warnings': warnings, 'plan_sha256': hashlib.sha256(resolved.read_bytes()).hexdigest()}
        if args.render:
            video = output / 'preview.mp4'
            report['video'] = str(video)
            report['media'] = ffprobe(video)
            if abs(float(report['media']['duration_seconds']) - plan['frames'] / plan['fps']) > 1 / plan['fps']:
                raise ValueError('Rendered duration differs from plan; inspect before delivery')
        write_new(output / 'verification.json', report)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
