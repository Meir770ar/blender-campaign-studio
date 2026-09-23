"""Prepare and finalize evidence-based review packets for rendered shots.

The prepare step extracts timecoded frames from the actual media. The finalize
step requires an explicit finding for every shot acceptance criterion and derives
the disposition without assigning a synthetic quality score.
"""
from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

from campaign_common import sha256_file
from creative_gates import validate_shots


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        if isinstance(value, str):
            stream.write(value)
        else:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def finite(value, name, minimum=0, maximum=86400):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be finite and in [{minimum}, {maximum}]')
    return float(value)


def probe_media(path):
    executable = shutil.which('ffprobe')
    if not executable:
        raise ValueError('ffprobe is required to prepare a shot review')
    result = subprocess.run(
        [executable, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
    )
    if result.returncode:
        raise ValueError(f'Cannot inspect review media: {result.stderr.strip()[:500]}')
    raw = json.loads(result.stdout)
    video = next((item for item in raw.get('streams', []) if item.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError('Review media has no video stream')
    duration = video.get('duration') or raw.get('format', {}).get('duration')
    if duration is None:
        raise ValueError('Review media duration is unknown')
    rate = video.get('avg_frame_rate') or video.get('r_frame_rate') or '0/1'
    try:
        top, bottom = rate.split('/')
        fps = float(top) / float(bottom)
    except (ValueError, ZeroDivisionError):
        fps = 0
    if fps <= 0:
        raise ValueError('Review media frame rate is unknown')
    return {
        'duration_seconds': finite(float(duration), 'duration_seconds', 0.001),
        'fps': fps,
        'width': int(video.get('width', 0)),
        'height': int(video.get('height', 0)),
        'codec': video.get('codec_name'),
        'has_audio': any(item.get('codec_type') == 'audio' for item in raw.get('streams', [])),
    }


def sample_times(duration, fps, count):
    finite(duration, 'duration', 0.001)
    finite(fps, 'fps', 0.001, 1000)
    if type(count) is not int or not 3 <= count <= 9:
        raise ValueError('sample_count must be an integer in [3, 9]')
    last = max(0, duration - 1 / fps)
    if count == 1:
        return [0.0]
    return [round(last * index / (count - 1), 6) for index in range(count)]


def select_shot(document, shot_id):
    errors, _, _ = validate_shots(document, 'styleframes')
    if errors:
        raise ValueError('Shot contract is incomplete: ' + '; '.join(errors[:8]))
    matches = [shot for shot in document['shots'] if shot.get('id') == shot_id]
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one shot with id {shot_id!r}')
    return matches[0]


def _review_html(packet):
    shot = packet['shot']
    cards = []
    for frame in packet['evidence_frames']:
        src = html.escape(Path(frame['path']).name, quote=True)
        label = html.escape(f"{frame['time_seconds']:.3f}s · frame {frame['frame_number']}")
        cards.append(f'<figure><img src="{src}" alt="Review evidence at {label}"><figcaption>{label}</figcaption></figure>')
    criteria = ''.join(
        f"<li><strong>{html.escape(item['id'])}</strong>: {html.escape(item['check'])}<br>Evidence required: {html.escape(item['evidence'])}</li>"
        for item in shot['acceptance']
    )
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shot review · {html.escape(shot['id'])}</title>
<style>body{{font:16px/1.45 system-ui;margin:24px;background:#111;color:#eee}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}figure{{margin:0;background:#1d1d1d;padding:10px;border-radius:8px}}img{{width:100%;height:auto;display:block}}figcaption{{padding-top:8px;color:#bbb}}li{{margin:.65em 0;max-width:80ch}}</style></head>
<body><h1>{html.escape(shot['id'])}</h1><p>{html.escape(shot['purpose'])}</p>
<div class="grid">{''.join(cards)}</div><h2>Acceptance criteria</h2><ol>{criteria}</ol>
<p>Inspect the complete moving shot with sound when present. Sampled frames do not establish motion quality, sync or transient artifacts.</p></body></html>'''


def prepare(media_path, shots_path, shot_id, out_dir, sample_count=5):
    media = Path(media_path).resolve()
    if not media.is_file():
        raise ValueError(f'Review media is missing: {media}')
    shots_document = load_json(shots_path)
    shot = select_shot(shots_document, shot_id)
    info = probe_media(media)
    output = Path(out_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    times = sample_times(info['duration_seconds'], info['fps'], sample_count)
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('ffmpeg is required to extract shot review frames')
    evidence = []
    for index, time_seconds in enumerate(times, start=1):
        frame = output / f'evidence-{index:02d}-{time_seconds:010.3f}s.png'
        result = subprocess.run(
            [ffmpeg, '-v', 'error', '-ss', f'{time_seconds:.6f}', '-i', str(media),
             '-frames:v', '1', '-an', '-n', str(frame)],
            capture_output=True, timeout=120,
        )
        if result.returncode or not frame.is_file():
            message = result.stderr.decode('utf-8', errors='replace')[-500:]
            raise ValueError(f'Frame extraction failed at {time_seconds:.3f}s: {message}')
        evidence.append({
            'time_seconds': time_seconds,
            'frame_number': round(time_seconds * info['fps']),
            'path': str(frame),
            'sha256': sha256_file(frame),
        })
    packet = {
        'version': 1,
        'shot': shot,
        'media': {'path': str(media), 'sha256': sha256_file(media), **info},
        'evidence_frames': evidence,
        'review_requirements': [
            'Watch the complete moving shot at normal speed.',
            'Inspect every acceptance criterion against the named evidence.',
            'Listen on the intended delivery path when an audio stream is present.',
            'Record timecoded defects and the exact corrective action.',
        ],
        'limits': 'Extracted frames support review but do not certify direction, motion, continuity, sound or brand accuracy.',
    }
    packet_path = output / 'review-packet.json'
    write_new(packet_path, packet)
    template = {
        'version': 1,
        'packet': str(packet_path),
        'reviewer': '',
        'reviewed_complete_motion': False,
        'reviewed_with_sound': False,
        'criteria': [
            {'id': criterion['id'], 'status': 'pending', 'evidence_time_seconds': None, 'note': ''}
            for criterion in shot['acceptance']
        ],
        'issues': [],
        'overall_note': '',
    }
    write_new(output / 'findings-template.json', template)
    write_new(output / 'review.html', _review_html(packet))
    return packet


def _meaningful(value, name, minimum=4):
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f'{name} must contain at least {minimum} characters')
    return value.strip()


def finalize(packet_path, findings_path, out_path):
    packet_file = Path(packet_path).resolve()
    packet = load_json(packet_file)
    findings = load_json(findings_path)
    if packet.get('version') != 1 or findings.get('version') != 1:
        raise ValueError('Packet and findings must use version 1')
    referenced = Path(findings.get('packet', ''))
    if not referenced.is_absolute():
        referenced = (Path(findings_path).resolve().parent / referenced).resolve()
    if referenced != packet_file:
        raise ValueError('Findings reference a different review packet')
    media = Path(packet['media']['path'])
    if not media.is_file() or sha256_file(media) != packet['media']['sha256']:
        raise ValueError('Reviewed media is missing or changed after evidence extraction')
    reviewer = _meaningful(findings.get('reviewer'), 'reviewer', 2)
    if type(findings.get('reviewed_complete_motion')) is not bool:
        raise ValueError('reviewed_complete_motion must be true or false')
    if type(findings.get('reviewed_with_sound')) is not bool:
        raise ValueError('reviewed_with_sound must be true or false')
    if not findings['reviewed_complete_motion']:
        raise ValueError('Complete motion must be watched before finalizing a shot review')

    expected = {item['id']: item for item in packet['shot']['acceptance']}
    entries = findings.get('criteria')
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise ValueError('Findings must contain exactly one result per acceptance criterion')
    observed, failed = set(), []
    normalized_criteria = []
    duration = float(packet['media']['duration_seconds'])
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f'criteria[{index}] must be an object')
        identifier = entry.get('id')
        if identifier not in expected or identifier in observed:
            raise ValueError(f'criteria[{index}].id is unknown or duplicated')
        observed.add(identifier)
        status = entry.get('status')
        if status not in {'pass', 'fail', 'not-applicable'}:
            raise ValueError(f'{identifier}.status must be pass, fail or not-applicable')
        evidence = finite(entry.get('evidence_time_seconds'), f'{identifier}.evidence_time_seconds', 0, duration)
        note = _meaningful(entry.get('note'), f'{identifier}.note', 8)
        if status == 'not-applicable' and len(note) < 16:
            raise ValueError(f'{identifier}.note must explain why the criterion is not applicable')
        if status == 'fail':
            failed.append(identifier)
        normalized_criteria.append({
            'id': identifier,
            'status': status,
            'evidence_time_seconds': evidence,
            'note': note,
            'required_evidence': expected[identifier]['evidence'],
        })
    if observed != set(expected):
        raise ValueError('Findings omit one or more acceptance criteria')

    issues = findings.get('issues')
    if not isinstance(issues, list):
        raise ValueError('issues must be a list')
    normalized_issues, severe = [], []
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            raise ValueError(f'issues[{index}] must be an object')
        severity = issue.get('severity')
        if severity not in {'blocker', 'major', 'minor', 'note'}:
            raise ValueError(f'issues[{index}].severity is invalid')
        time_seconds = finite(issue.get('time_seconds'), f'issues[{index}].time_seconds', 0, duration)
        description = _meaningful(issue.get('description'), f'issues[{index}].description', 8)
        action = _meaningful(issue.get('action'), f'issues[{index}].action', 8)
        normalized_issues.append({'severity': severity, 'time_seconds': time_seconds,
                                  'description': description, 'action': action})
        if severity in {'blocker', 'major'}:
            severe.append(index)
    if failed and not issues:
        raise ValueError('A failed criterion requires at least one timecoded issue and corrective action')

    sound_missing = packet['media']['has_audio'] and not findings['reviewed_with_sound']
    disposition = 'revise' if failed or severe else 'needs-sound-review' if sound_missing else 'passed'
    report = {
        'version': 1,
        'shot_id': packet['shot']['id'],
        'media': packet['media'],
        'reviewer': reviewer,
        'reviewed_complete_motion': True,
        'reviewed_with_sound': findings['reviewed_with_sound'],
        'criteria': normalized_criteria,
        'issues': normalized_issues,
        'disposition': disposition,
        'overall_note': _meaningful(findings.get('overall_note'), 'overall_note', 8),
        'limits': 'This is recorded reviewer evidence, not an automatic aesthetic score.',
    }
    write_new(out_path, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--media', required=True)
    prep.add_argument('--shots', required=True)
    prep.add_argument('--shot-id', required=True)
    prep.add_argument('--out-dir', required=True)
    prep.add_argument('--sample-count', type=int, default=5)
    final = commands.add_parser('finalize')
    final.add_argument('--packet', required=True)
    final.add_argument('--findings', required=True)
    final.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        result = prepare(args.media, args.shots, args.shot_id, args.out_dir, args.sample_count)
        summary = {'packet': str(Path(args.out_dir).resolve() / 'review-packet.json'),
                   'evidence_frames': len(result['evidence_frames'])}
    else:
        result = finalize(args.packet, args.findings, args.out)
        summary = {'report': str(Path(args.out).resolve()), 'disposition': result['disposition']}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        sys.exit(main())
    except (ValueError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
