"""Inspect footage, cache local transcription, and conform a reasoned EDL to Blender media."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from campaign_common import atomic_json, digest_json, new_directory, run, sha256_file
from studio import load_json, integer, number, source_path, write_new, validate_plan


def inspect(path):
    out, _ = run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path])
    return json.loads(out)


def analyze(source, cache, transcribe=False, language='he'):
    source = Path(source).resolve()
    key = digest_json({'sha256': sha256_file(source), 'version': 1, 'transcribe': transcribe, 'language': language})
    folder = Path(cache).resolve() / key
    if (folder / 'analysis.json').exists():
        return load_json(folder / 'analysis.json')
    folder.mkdir(parents=True, exist_ok=True)
    data = inspect(source)
    duration = float(data['format']['duration'])
    video = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
    audio = any(s['codec_type'] == 'audio' for s in data['streams'])
    report = {'source': str(source), 'source_sha256': sha256_file(source), 'media': data,
              'duration': duration, 'signals_are_review_candidates': True}
    if video:
        _, log = run(['ffmpeg', '-hide_banner', '-i', source, '-an', '-vf',
                     "select='gt(scene,0.3)',showinfo", '-fps_mode', 'vfr', '-f', 'null', '-'], timeout=1800)
        report['scene_candidates'] = [float(x) for x in re.findall(r'pts_time:([\d.]+)', log)]
        _, black = run(['ffmpeg', '-hide_banner', '-i', source, '-an', '-vf', 'blackdetect=d=0.15:pix_th=0.10',
                        '-f', 'null', '-'], timeout=1800)
        report['black_intervals'] = [{'start': float(a), 'end': float(b)} for a, b in
            re.findall(r'black_start:([\d.]+) black_end:([\d.]+)', black)]
        points = sorted(set([min(duration - .04, duration * i / 11) for i in range(12)] + report['scene_candidates'][:24]))
        frames = []
        for i, seconds in enumerate(points):
            target = folder / f'frame-{i:03d}.png'
            if not target.exists():
                run(['ffmpeg', '-v', 'error', '-ss', str(max(0, seconds)), '-i', source, '-frames:v', '1',
                     '-vf', 'scale=640:-2', '-n', target])
            frames.append({'time': seconds, 'path': str(target)})
        report['frames'] = frames
    if audio:
        _, log = run(['ffmpeg', '-hide_banner', '-i', source, '-vn', '-af', 'silencedetect=noise=-35dB:d=0.25',
                      '-f', 'null', '-'], timeout=1800)
        report['silence_events'] = [{'event': k, 'time': float(t)} for k, t in
                                    re.findall(r'silence_(start|end): ([\d.]+)', log)]
    if transcribe:
        if not audio:
            raise ValueError('Cannot transcribe media without audio')
        env = dict(os.environ, HF_HUB_OFFLINE='1')
        target = folder / 'transcript.srt'
        run(['whisper-local', '-i', source, '-o', target, '-l', language, '-q', 'high', '--json'],
            env=env, timeout=7200, log=folder / 'transcription.log')
        words_path = target.with_name(target.stem + '_transcript.json')
        if not words_path.exists():
            raise ValueError('Transcriber did not produce word JSON; inspect transcription.log')
        report['words_path'] = str(words_path)
    atomic_json(folder / 'analysis.json', report)
    return report


def checked_words(data):
    words = data.get('words')
    if not isinstance(words, list):
        raise ValueError('Transcript requires words array')
    previous = 0
    for word in words:
        if not isinstance(word.get('word'), str) or not word['word'].strip():
            raise ValueError('Transcript word must be nonempty')
        start = number(word.get('start'), 'word start', 0, 36000)
        end = number(word.get('end'), 'word end', start, 36000)
        if start < previous or end <= start:
            raise ValueError('Words must have positive duration and ordered starts')
        previous = start
    return words


def map_words(words, start, end, at, allow_word_cut=False):
    selected = []
    for w in words:
        if w['end'] <= start or w['start'] >= end:
            continue
        if (w['start'] < start - .02 or w['end'] > end + .02) and not allow_word_cut:
            raise ValueError(f'Edit cuts through word at {w["start"]:.3f}s; move the edit or explicitly justify word cut')
        selected.append({**w, 'start': max(start, w['start']) - start + at,
                         'end': min(end, w['end']) - start + at})
    return selected


def conform(edl_path, output):
    edl_path = Path(edl_path).resolve()
    edl = load_json(edl_path)
    fps = integer(edl.get('fps'), 'fps', 1, 120)
    width = integer(edl.get('width'), 'width', 16, 8192)
    height = integer(edl.get('height'), 'height', 16, 8192)
    if width % 2 or height % 2 or not edl.get('cuts'):
        raise ValueError('Even delivery dimensions and a nonempty cuts list are required')
    cuts, cursor = [], 0
    for i, raw in enumerate(edl['cuts']):
        cut = dict(raw)
        if not isinstance(cut.get('reason'), str) or not cut['reason'].strip():
            raise ValueError('Every cut needs an editorial reason based on inspected content')
        source = source_path(cut.get('source'), edl_path.parent)
        info = inspect(source)
        video = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
        if not video:
            raise ValueError('EDL cuts require video; use image strips for stills')
        if video.get('color_transfer') in ('smpte2084', 'arib-std-b67') or video.get('color_primaries') == 'bt2020':
            raise ValueError('HDR/wide gamut requires a reviewed explicit SDR conversion before conform')
        total = float(info['format']['duration'])
        start = number(cut.get('in'), 'in', 0, total)
        end = number(cut.get('out'), 'out', start, total)
        # All edits share integer frame boundaries; no cumulative sub-frame drift.
        start, end = round(start * fps) / fps, round(end * fps) / fps
        frames = round((end - start) * fps)
        if frames < 1 or end > total + .5 / fps:
            raise ValueError('Empty cut or source boundary exceeded')
        cut.update(source=str(source), **{'in': start, 'out': end, 'frames': frames, 'at': cursor / fps})
        if cut.get('allow_word_cut') and not cut.get('word_cut_reason'):
            raise ValueError('A deliberate word cut requires word_cut_reason')
        cut['words'] = []
        if cut.get('words_path'):
            transcript = source_path(cut['words_path'], edl_path.parent)
            cut['words'] = map_words(checked_words(load_json(transcript)), start, end, cursor / fps,
                                     bool(cut.get('allow_word_cut')))
        grade = cut.get('grade', {})
        for name, default, lo, hi in [('brightness', 0, -1, 1), ('contrast', 1, .1, 3), ('saturation', 1, 0, 3), ('gamma', 1, .1, 3)]:
            grade[name] = number(grade.get(name, default), name, lo, hi)
        cut['grade'] = grade
        cut['has_audio'] = any(s['codec_type'] == 'audio' for s in info['streams'])
        cuts.append(cut)
        cursor += frames
    output = new_directory(output)
    clips, all_words, position = [], [], 1
    for i, cut in enumerate(cuts):
        movie = output / f'cut-{i+1:03d}.mp4'
        grade = cut['grade']
        color = ':'.join(f'{k}={v}' for k, v in grade.items())
        vf = f'setpts=PTS-STARTPTS,fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,eq={color},format=yuv420p'
        run(['ffmpeg', '-v', 'error', '-i', cut['source'], '-ss', str(cut['in']), '-t', str(cut['out']-cut['in']),
             '-an', '-vf', vf, '-frames:v', str(cut['frames']), '-c:v', 'libx264', '-crf', '16', '-preset', 'medium',
             '-movflags', '+faststart', '-n', movie], timeout=1800, log=output / f'cut-{i+1:03d}.log')
        clips.append({'id': f'cut-{i+1}', 'kind': 'movie', 'path': str(movie), 'start': position,
                      'duration': cut['frames'], 'channel': 1})
        if cut['has_audio'] and cut.get('use_source_audio', True):
            sound = output / f'cut-{i+1:03d}.wav'
            run(['ffmpeg', '-v', 'error', '-i', cut['source'], '-ss', str(cut['in']), '-t', str(cut['out']-cut['in']),
                 '-vn', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s24le', '-n', sound], timeout=1800)
            clips.append({'id': f'cut-{i+1}-audio', 'kind': 'sound', 'path': str(sound), 'start': position,
                          'duration': cut['frames'], 'channel': 2})
        all_words.extend(cut['words'])
        position += cut['frames']
    plan = {'version': 1, 'width': width, 'height': height, 'fps': fps, 'frames': cursor, 'clips': clips}
    write_new(output / 'plan.json', plan)
    write_new(output / 'words.json', {'words': all_words})
    write_new(output / 'resolved-edl.json', {**edl, 'cuts': cuts})
    validate_plan(output / 'plan.json')
    return {'plan': str(output / 'plan.json'), 'words': str(output / 'words.json'), 'duration': cursor/fps}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('analyze'); q.add_argument('--source', required=True); q.add_argument('--cache', required=True)
    q.add_argument('--transcribe', action='store_true'); q.add_argument('--language', default='he')
    q = sub.add_parser('conform'); q.add_argument('--edl', required=True); q.add_argument('--out-dir', required=True)
    a = p.parse_args()
    result = analyze(a.source, a.cache, a.transcribe, a.language) if a.command == 'analyze' else conform(a.edl, a.out_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try: main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr); sys.exit(1)
