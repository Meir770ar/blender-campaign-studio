"""Directed narration: one script, segments with pauses, two ways to render it, one layout.

eleven_v3 has no SSML <break>; a directed pause is silence *you* place between segments. The
script is written as segments with `pause_after`. Two render modes:

  single    (recommended) the whole script is one ElevenLabs request, so tone, energy and pace stay
            continuous; `layout --mode single` cuts the rendered audio at the segment boundaries using
            the returned word timestamps and inserts the pauses. A retake is a fresh single render.
  segments  one request per segment (retake one segment alone); adjacent segments can differ in
            energy because the model is not deterministic, so listen to every seam.

  split   narration-v1 JSON  ->  request-single.json plus one request per segment, and an index
  layout  rendered audio      ->  voice tracks with exact `at` times for audio_finish.py, one merged
                                  words.json (on the mix clock) for captions.py, end_of_speech

Nothing here calls a provider; every render is a provider_jobs.py job with its own approval.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from campaign_common import new_directory, run, sha256_file
from editorial import checked_words
from studio import ffprobe, load_json, number, write_new

SLUG = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')
VOICE_DEFAULTS = {'stability': .5, 'similarity_boost': .75, 'style': 0, 'speed': 1}
VOICE_RANGES = {'stability': (0, 1), 'similarity_boost': (0, 1), 'style': (0, 1), 'speed': (.7, 1.2)}
HEBREW_WORDS_PER_SECOND = 2.4   # planning estimate only; the rendered audio sets the real durations
SINGLE_LIMIT = 4500             # characters per ElevenLabs request (provider_jobs enforces the same)
HANDLE_BEFORE = 0.04            # seconds kept before a segment's first word when cutting a single render
HANDLE_AFTER = 0.10             # seconds kept after its last word (consonant tails, room)


def validate_script(script):
    if not isinstance(script, dict) or script.get('version') != 1:
        raise ValueError('Narration script must be an object with version=1')
    voice = script.get('voice', {})
    if not isinstance(voice, dict) or set(voice) - set(VOICE_DEFAULTS):
        raise ValueError('voice accepts only stability, similarity_boost, style and speed')
    for key, (lo, hi) in VOICE_RANGES.items():
        if key in voice:
            number(voice[key], f'voice.{key}', lo, hi)
    start_at = number(script.get('start_at', 0), 'start_at', 0, 600)
    segments = script.get('segments')
    if not isinstance(segments, list) or not segments:
        raise ValueError('segments must be a nonempty list')
    ids, normalized = set(), []
    for index, segment in enumerate(segments):
        location = f'segments[{index}]'
        if not isinstance(segment, dict):
            raise ValueError(f'{location} must be an object')
        identifier = segment.get('id')
        if not isinstance(identifier, str) or not SLUG.match(identifier):
            raise ValueError(f'{location}.id must be a short lowercase slug (e.g. s01, hook, cta)')
        if identifier in ids:
            raise ValueError(f'{location}.id {identifier!r} is duplicated')
        ids.add(identifier)
        text = segment.get('text')
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f'{location}.text is required')
        text = text.strip()
        if len(text) > SINGLE_LIMIT or '<break' in text.lower():
            raise ValueError(f'{location}.text must stay below {SINGLE_LIMIT} characters and use pause_after, not SSML breaks')
        pause = number(segment.get('pause_after', .6), f'{location}.pause_after', 0, 10)
        extra = set(segment) - {'id', 'text', 'pause_after', 'note'}
        if extra:
            raise ValueError(f'{location} has unknown fields: {", ".join(sorted(extra))}')
        normalized.append({'id': identifier, 'text': text, 'pause_after': pause, 'words': len(text.split()),
                           'note': segment.get('note', '')})
    return {'voice': {**VOICE_DEFAULTS, **voice}, 'start_at': start_at, 'segments': normalized}


def text_digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def single_text(script):
    """The whole script as one request: paragraph breaks between segments (natural phrasing)."""
    return '\n\n'.join(segment['text'] for segment in script['segments'])


def split(script_path, out_dir):
    script_path = Path(script_path).resolve()
    script = validate_script(load_json(script_path))
    out = new_directory(out_dir)
    index, total_words, total_pause = [], 0, 0.0
    for segment in script['segments']:
        request = {'provider': 'elevenlabs', 'text': segment['text'], **script['voice']}
        path = out / f'request-{segment["id"]}.json'
        write_new(path, request)
        index.append({'id': segment['id'], 'request': str(path), 'text_sha256': text_digest(segment['text']),
                      'words': segment['words'], 'pause_after': segment['pause_after'], 'note': segment['note']})
        total_words += segment['words']
        total_pause += segment['pause_after']
    joined = single_text(script)
    single = None
    if len(joined) <= SINGLE_LIMIT:
        single = out / 'request-single.json'
        write_new(single, {'provider': 'elevenlabs', 'text': joined, **script['voice']})
    estimate = script['start_at'] + total_words / HEBREW_WORDS_PER_SECOND + total_pause
    report = {'version': 1, 'script': str(script_path), 'script_sha256': sha256_file(script_path), 'segments': index,
              'single_request': str(single) if single else None,
              'single_text_sha256': text_digest(joined) if single else None,
              'recommended_mode': 'single' if single else 'segments',
              'total_words': total_words, 'total_pause_seconds': round(total_pause, 3),
              'estimated_seconds': round(estimate, 1),
              'next': ('render request-single.json as one job, listen, then `layout --mode single`; '
                       'or render the per-segment requests (approve-batch) and `layout --mode segments`'),
              'note': 'estimated_seconds is a planning figure (about 2.4 Hebrew words per second); layout measures the real audio'}
    if not single:
        report['single_note'] = (f'joined text is {len(joined)} characters, above the {SINGLE_LIMIT} limit; render per '
                                 'segment, or split the script into two scripts and lay them out in sequence')
    write_new(out / 'segments.json', report)
    return report


def find_rendered(jobs_root, text):
    """The single completed ElevenLabs job whose request text equals this text exactly."""
    matches = []
    for job_path in sorted(Path(jobs_root).resolve().glob('*/job.json')):
        job = load_json(job_path)
        request = job.get('request', {})
        if request.get('provider') == 'elevenlabs' and request.get('text') == text and job.get('state') == 'complete':
            matches.append(job_path.parent)
    if len(matches) != 1:
        raise ValueError(f'expected exactly one complete ElevenLabs job for the text, found {len(matches)}; '
                         'pass --audio ID=PATH to choose the take')
    return matches[0]


def parse_overrides(values):
    overrides = {}
    for value in values or []:
        if '=' not in value:
            raise ValueError('--audio takes ID=PATH (use the id "single" for a single render)')
        identifier, path = value.split('=', 1)
        overrides[identifier.strip()] = Path(path.strip()).resolve()
    return overrides


def segment_words(words, segments):
    """Assign the aligned words of a single render to the script segments by word count. Both sides
    tokenize on whitespace, so the counts match exactly when the rendered text is the script."""
    counts = [segment['words'] for segment in segments]
    if sum(counts) != len(words):
        raise ValueError(f'the single render has {len(words)} aligned words but the script has {sum(counts)}; '
                         'the rendered text and the script differ (make the script match what was rendered, word for word)')
    groups, index = [], 0
    for count in counts:
        groups.append(words[index:index + count])
        index += count
    return groups


def cut_audio(source, start, end, out):
    run(['ffmpeg', '-v', 'error', '-ss', f'{start:.3f}', '-i', source, '-t', f'{end - start:.3f}',
         '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s24le', '-n', out], timeout=600)


def _audio_duration(path):
    info = ffprobe(path)
    if not any(s.get('codec_type') == 'audio' for s in info['streams']):
        raise ValueError(f'{Path(path).name} has no audio stream')
    return float(info['duration_seconds'])


def layout_single(script, audio, out):
    words_path = audio.with_name('words.json')
    if not words_path.is_file():
        raise ValueError('single mode needs words.json next to the narration (the ElevenLabs alignment written by provider_jobs)')
    words = checked_words(load_json(words_path))
    groups = segment_words(words, script['segments'])
    total = _audio_duration(audio)
    clock = script['start_at']
    tracks, merged, placed = [], [], []
    for index, (segment, group) in enumerate(zip(script['segments'], groups)):
        previous_end = groups[index - 1][-1]['end'] if index else 0.0
        next_start = groups[index + 1][0]['start'] if index + 1 < len(groups) else total
        start = max(previous_end, group[0]['start'] - HANDLE_BEFORE, 0.0)
        end = min(next_start, group[-1]['end'] + HANDLE_AFTER, total)
        if end <= start:
            raise ValueError(f'segment {segment["id"]}: cut window collapsed ({start:.3f}-{end:.3f} s); check the alignment')
        piece = out / f'segment-{segment["id"]}.wav'
        cut_audio(audio, start, end, piece)
        duration = _audio_duration(piece)
        at = round(clock, 3)
        tracks.append({'path': str(piece), 'role': 'voice', 'at': at, 'in': 0, 'duration': round(duration, 3),
                       'gain_db': 0, 'segment': segment['id']})
        merged.extend({'word': w['word'], 'start': round(w['start'] - start + at, 3), 'end': round(w['end'] - start + at, 3)}
                      for w in group)
        placed.append({'id': segment['id'], 'at': at, 'end': round(clock + duration, 3), 'duration': round(duration, 3),
                       'pause_after': segment['pause_after'], 'source_in': round(start, 3), 'source_out': round(end, 3),
                       'natural_gap_before': round(group[0]['start'] - previous_end, 3) if index else None,
                       'audio': str(piece), 'audio_sha256': sha256_file(piece)})
        clock += duration + segment['pause_after']
    extra = {'mode': 'single', 'source_audio': str(audio), 'source_audio_sha256': sha256_file(audio),
             'source_words': len(words), 'segments_without_words': []}
    return tracks, merged, placed, clock, extra


def layout_segments(script, out, jobs_root, overrides):
    clock = script['start_at']
    tracks, merged, placed, without_words = [], [], [], []
    for segment in script['segments']:
        if segment['id'] in overrides:
            audio = overrides[segment['id']]
        elif jobs_root:
            audio = find_rendered(jobs_root, segment['text']) / 'narration.mp3'
        else:
            raise ValueError(f'segment {segment["id"]}: pass --jobs or --audio {segment["id"]}=PATH')
        if not audio.is_file():
            raise ValueError(f'segment {segment["id"]}: rendered audio missing at {audio}')
        duration = _audio_duration(audio)
        at = round(clock, 3)
        tracks.append({'path': str(audio), 'role': 'voice', 'at': at, 'in': 0, 'duration': round(duration, 3),
                       'gain_db': 0, 'segment': segment['id']})
        words_path = audio.with_name('words.json')
        if words_path.is_file():
            merged.extend({'word': w['word'], 'start': round(w['start'] + at, 3), 'end': round(w['end'] + at, 3)}
                          for w in checked_words(load_json(words_path)))
        else:
            without_words.append(segment['id'])
        placed.append({'id': segment['id'], 'at': at, 'end': round(clock + duration, 3), 'duration': round(duration, 3),
                       'pause_after': segment['pause_after'], 'audio': str(audio), 'audio_sha256': sha256_file(audio)})
        clock += duration + segment['pause_after']
    extra = {'mode': 'segments', 'segments_without_words': without_words,
             'seam_review': 'each segment is a separate render; listen to every seam for energy and pace continuity'}
    return tracks, merged, placed, clock, extra


def layout(script_path, out_dir, jobs_root=None, audio_overrides=None, mode='segments'):
    if mode not in ('segments', 'single'):
        raise ValueError("mode must be 'segments' or 'single'")
    script_path = Path(script_path).resolve()
    script = validate_script(load_json(script_path))
    overrides = audio_overrides or {}
    out = new_directory(out_dir)
    if mode == 'single':
        if 'single' in overrides:
            audio = overrides['single']
        elif jobs_root:
            audio = find_rendered(jobs_root, single_text(script)) / 'narration.mp3'
        else:
            raise ValueError('single mode: pass --jobs or --audio single=PATH')
        if not audio.is_file():
            raise ValueError(f'single render missing at {audio}')
        tracks, merged, placed, clock, extra = layout_single(script, audio, out)
    else:
        tracks, merged, placed, clock, extra = layout_segments(script, out, jobs_root, overrides)
    end_of_speech = round(clock - script['segments'][-1]['pause_after'], 3)
    report = {'version': 1, 'script': str(script_path), 'script_sha256': sha256_file(script_path),
              'start_at': script['start_at'], **extra, 'segments': placed, 'tracks': tracks,
              'end_of_speech_seconds': end_of_speech, 'suggested_mix_duration': math.ceil(end_of_speech + 1.5),
              'words_merged': len(merged), 'listening_review_required': True,
              'next': 'paste tracks into the mix spec (audio_finish.py), use words.json for captions.py, '
                      'and plan music/SFX cues against end_of_speech_seconds'}
    write_new(out / 'narration-layout.json', report)
    write_new(out / 'mix-tracks.json', tracks)
    if merged:
        write_new(out / 'words.json', {'words': merged, 'source': f'narration_plan_layout_{mode}'})
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('split'); q.add_argument('--script', required=True); q.add_argument('--out-dir', required=True)
    q = sub.add_parser('layout'); q.add_argument('--script', required=True); q.add_argument('--out-dir', required=True)
    q.add_argument('--mode', choices=('segments', 'single'), default='segments')
    q.add_argument('--jobs', help='provider_jobs folder holding the completed ElevenLabs job(s)')
    q.add_argument('--audio', action='append', help='ID=PATH override (segment id, or "single" for the single render); repeatable')
    a = p.parse_args(argv)
    if a.command == 'split':
        result = split(a.script, a.out_dir)
    else:
        result = layout(a.script, a.out_dir, a.jobs, parse_overrides(a.audio), a.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
