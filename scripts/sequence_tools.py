"""Freeze frames and alpha image sequences for Timeline JSON v1. Local FFmpeg only; no provider calls.

  still           extract one frame of a movie as a PNG (a freeze-frame / hold as a kind:image clip,
                  or an exact first frame for an image-to-video request)
  alpha-sequence  decode a movie that carries alpha (ProRes 4444, PNG-in-MOV, VP9 alpha) into PNG
                  frames for a kind:image-sequence clip in the Blender VSE (animated logo, butterfly
                  transition, Tesseract overlay)
  alpha-movie     encode PNG frames back into a ProRes 4444 .mov with alpha: the `resolve_movie`
                  companion the DaVinci hand-off needs for the same clip
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from campaign_common import new_directory, run, sha256_file
from studio import integer, number, write_new

ALPHA_PREFIXES = ('rgba', 'argb', 'abgr', 'bgra', 'yuva', 'gbrap', 'ya8', 'ya16')
FRAME_NAME = re.compile(r'^(.*?)(\d+)(\.[A-Za-z0-9]+)$')


def probe(path):
    out, _ = run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path], timeout=120)
    return json.loads(out)


def video_stream(info, path):
    stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not stream:
        raise ValueError(f'{Path(path).name} has no video stream')
    return stream


def has_alpha(pix_fmt):
    return bool(pix_fmt) and any(pix_fmt.startswith(prefix) for prefix in ALPHA_PREFIXES)


def frame_rate(stream):
    top, bottom = (stream.get('avg_frame_rate') or '0/1').split('/')
    return float(top) / float(bottom) if float(bottom) else 0.0


def still(source, seconds, out):
    source = Path(source).resolve()
    out = Path(out).resolve()
    if out.suffix.lower() != '.png':
        raise ValueError('Freeze frame output must be a PNG')
    if out.exists():
        raise ValueError('Output exists; choose a new revision path')
    info = probe(source)
    stream = video_stream(info, source)
    duration = float(stream.get('duration') or info.get('format', {}).get('duration') or 0)
    if duration <= 0:
        raise ValueError('Source duration unknown; normalize the movie first')
    seconds = number(seconds, 'seconds', 0, duration)
    out.parent.mkdir(parents=True, exist_ok=True)
    run(['ffmpeg', '-v', 'error', '-ss', f'{seconds:.6f}', '-i', source, '-frames:v', '1', '-update', '1', '-n', out], timeout=600)
    if not out.is_file():
        raise ValueError('FFmpeg wrote no frame; the time may be past the last decodable frame')
    return {'still': str(out), 'sha256': sha256_file(out), 'seconds': seconds, 'source': str(source),
            'source_sha256': sha256_file(source), 'width': stream.get('width'), 'height': stream.get('height'),
            'plan_clip': {'kind': 'image', 'path': str(out)},
            'note': 'Place it as a kind:image clip on the frame after the movie strip ends (freeze frame), '
                    'or use it as the exact first frame of an image-to-video request.'}


def alpha_sequence(source, out_dir, fps=None, allow_opaque=False):
    source = Path(source).resolve()
    info = probe(source)
    stream = video_stream(info, source)
    alpha = has_alpha(stream.get('pix_fmt'))
    if not alpha and not allow_opaque:
        raise ValueError(f'{source.name} pixel format {stream.get("pix_fmt")} carries no alpha; an overlay needs '
                         'ProRes 4444 / PNG-in-MOV / VP9 alpha. Pass --allow-opaque for an opaque sequence')
    native = frame_rate(stream)
    if fps is None:
        if native <= 0 or abs(native - round(native)) > 1e-3:
            raise ValueError(f'Source frame rate {native:.3f} is not an integer; pass --fps to match the plan')
        fps = int(round(native))
    integer(fps, 'fps', 1, 120)
    out = new_directory(out_dir)
    vf = f'fps={fps},format={"rgba" if alpha else "rgb24"}'
    run(['ffmpeg', '-v', 'error', '-i', source, '-vf', vf, '-start_number', '1', out / 'frame_%05d.png'],
        timeout=3600, log=out / 'ffmpeg.log')
    files = sorted(out.glob('frame_*.png'))
    if not files:
        raise ValueError('FFmpeg wrote no frames')
    report = {'first': str(files[0]), 'count': len(files), 'fps': fps, 'alpha': alpha, 'source': str(source),
              'source_sha256': sha256_file(source), 'width': stream.get('width'), 'height': stream.get('height'),
              'plan_clip': {'kind': 'image-sequence', 'path': str(files[0]), 'duration': len(files)}}
    write_new(out / 'sequence.json', report)
    return report


def alpha_movie(first, fps, out, count=None):
    first = Path(first).resolve()
    out = Path(out).resolve()
    if not first.is_file():
        raise ValueError(f'First frame missing: {first}')
    if out.suffix.lower() != '.mov':
        raise ValueError('The Resolve companion must be a .mov (ProRes 4444 with alpha)')
    if out.exists():
        raise ValueError('Output exists; choose a new revision path')
    integer(fps, 'fps', 1, 120)
    match = FRAME_NAME.match(first.name)
    if not match:
        raise ValueError('Sequence files must end with a frame number, e.g. frame_00001.png')
    prefix, digits, ext = match.groups()
    pattern = f'{prefix}%0{len(digits)}d{ext}'
    siblings = sorted(p for p in first.parent.iterdir() if p.is_file() and p.suffix.lower() == first.suffix.lower())
    available = len(siblings) - siblings.index(first)
    if count is None:
        count = available
    integer(count, 'count', 1, available)
    out.parent.mkdir(parents=True, exist_ok=True)
    run(['ffmpeg', '-v', 'error', '-framerate', str(fps), '-start_number', digits, '-i', first.parent / pattern,
         '-frames:v', str(count), '-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', '-n', out],
        timeout=3600)
    info = probe(out)
    stream = video_stream(info, out)
    if not has_alpha(stream.get('pix_fmt')):
        raise ValueError('Encoded movie lost its alpha channel; inspect the frames')
    frames = int(stream.get('nb_frames') or round(float(stream.get('duration') or 0) * fps))
    if frames != count:
        raise ValueError(f'Encoded {frames} frames, expected {count}')
    return {'movie': str(out), 'sha256': sha256_file(out), 'frames': frames, 'fps': fps, 'pix_fmt': stream.get('pix_fmt'),
            'first_frame': str(first), 'plan_field': {'resolve_movie': str(out)}}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('still'); q.add_argument('--source', required=True); q.add_argument('--time', type=float, required=True)
    q.add_argument('--out', required=True)
    q = sub.add_parser('alpha-sequence'); q.add_argument('--source', required=True); q.add_argument('--out-dir', required=True)
    q.add_argument('--fps', type=int); q.add_argument('--allow-opaque', action='store_true')
    q = sub.add_parser('alpha-movie'); q.add_argument('--first', required=True); q.add_argument('--fps', type=int, required=True)
    q.add_argument('--out', required=True); q.add_argument('--count', type=int)
    a = p.parse_args(argv)
    if a.command == 'still':
        result = still(a.source, a.time, a.out)
    elif a.command == 'alpha-sequence':
        result = alpha_sequence(a.source, a.out_dir, a.fps, a.allow_opaque)
    else:
        result = alpha_movie(a.first, a.fps, a.out, a.count)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
