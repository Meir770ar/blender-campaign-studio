"""Read-only edit-boundary evidence. Numeric checks never certify listening or motion."""
from array import array
from contextlib import contextmanager
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

from campaign_common import run, sha256_file
from studio import load_json, write_new

RATE = 48000
CHANNELS = 2
FRAME_BYTES = 4 * CHANNELS


def finite(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{label} must be finite and >= {minimum}')
    return value


def resolve_file(value, root):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('An explicit media path is required')
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_file():
        raise ValueError(f'Media file missing: {path}')
    return path


@contextmanager
def pcm_file(path, start=0, duration=None):
    """Canonical interleaved float PCM, on disk to bound memory for long stems."""
    finite(start, 'audio in')
    if duration is not None:
        finite(duration, 'audio duration', 1 / RATE)
    with tempfile.TemporaryDirectory(prefix='campaign-edit-audit-') as folder:
        output = Path(folder) / 'decoded.f32'
        command = ['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:a:0', '-ss', str(start)]
        if duration is not None:
            command += ['-t', str(duration)]
        run(command + ['-ac', str(CHANNELS), '-ar', str(RATE), '-f', 'f32le', '-n', output], timeout=1800)
        if not output.stat().st_size or output.stat().st_size % FRAME_BYTES:
            raise ValueError('Selected audio interval has no complete PCM frames')
        yield output


def floats(raw):
    values = array('f')
    values.frombytes(raw)
    if sys.byteorder != 'little':
        values.byteswap()
    if any(not math.isfinite(v) for v in values):
        raise ValueError('Audio contains non-finite samples')
    return values


def signal_stats(path, start=0, duration=None):
    """Check the selected interval without cancelling antiphase stereo channels."""
    peak = energy = 0.0
    count = nonzero = 0
    with pcm_file(path, start, duration) as decoded, decoded.open('rb') as stream:
        for raw in iter(lambda: stream.read(65536), b''):
            values = floats(raw)
            count += len(values)
            nonzero += sum(v != 0 for v in values)
            peak = max(peak, max(map(abs, values)))
            energy += sum(v * v for v in values)
    frames = count // CHANNELS
    if duration is not None and abs(frames - round(duration * RATE)) > 1:
        raise ValueError('Selected audio interval exceeds decoded source duration')
    return {'frames': frames, 'sample_rate': RATE, 'channels': CHANNELS,
            'peak': peak, 'rms': math.sqrt(energy / count), 'nonzero_samples': nonzero}


def check_clocks(segments):
    results = []
    previous = None
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError('Each clock segment must be an object')
        start = finite(segment.get('timeline_start_frame'), 'timeline_start_frame')
        end = finite(segment.get('timeline_end_frame'), 'timeline_end_frame')
        source = finite(segment.get('source_start_frame'), 'source_start_frame')
        rate = finite(segment.get('source_frames_per_frame', 1), 'source_frames_per_frame', 1e-9)
        if start != int(start) or end != int(end) or end <= start or not segment.get('source_id'):
            raise ValueError('Clock segments need an explicit source_id and increasing integer timeline frames')
        continuous = segment.get('continues_previous', False)
        if not isinstance(continuous, bool):
            raise ValueError('continues_previous must be boolean')
        if previous and start < previous['timeline_end_frame']:
            raise ValueError('Clock segments overlap or are unordered; audit each source clock separately')
        delta = None
        passed = True
        if continuous:
            if previous is None:
                raise ValueError('First clock segment cannot continue a previous segment')
            expected = previous['source_start_frame'] + (previous['timeline_end_frame'] - previous['timeline_start_frame']) * previous.get('source_frames_per_frame', 1)
            delta = source - expected
            passed = (start == previous['timeline_end_frame'] and segment['source_id'] == previous['source_id'] and abs(delta) < 1e-6)
        results.append({'source_id': segment['source_id'], 'timeline_start_frame': start,
                        'continues_previous': continuous, 'source_jump_frames': delta, 'pass': passed})
        previous = segment
    return results


def join_stats(path, at, window_ms=10, jump_review_db=12, step_review=0.1):
    at = finite(at, 'join at')
    window = finite(window_ms, 'window_ms', 1000 / RATE) / 1000
    finite(jump_review_db, 'jump_review_db')
    finite(step_review, 'step_review')
    if window > 1 or at < window:
        raise ValueError('Join needs full windows on both sides; window_ms must be <= 1000')
    samples = round(window * RATE)
    with pcm_file(path, at - samples / RATE, 2 * samples / RATE) as decoded:
        values = floats(decoded.read_bytes())
    split = samples * CHANNELS
    if len(values) != split * 2:
        raise ValueError('Join window extends beyond decoded audio')
    left, right = values[:split], values[split:]
    rms_left = math.sqrt(sum(v * v for v in left) / len(left))
    rms_right = math.sqrt(sum(v * v for v in right) / len(right))
    jump = 20 * math.log10(rms_right / rms_left) if rms_left and rms_right else None
    step = max(abs(right[ch] - left[-CHANNELS + ch]) for ch in range(CHANNELS))
    signals = []
    if (jump is not None and abs(jump) >= jump_review_db) or bool(rms_left) != bool(rms_right):
        signals.append('energy_transition_requires_listening')
    if step >= step_review:
        signals.append('sample_step_requires_listening')
    return {'at': at, 'window_ms': samples / RATE * 1000, 'rms_before': rms_left, 'rms_after': rms_right,
            'rms_jump_db': jump, 'boundary_sample_step': step, 'review_signals': signals}


def intervals(value, label):
    if not isinstance(value, list):
        raise ValueError(f'{label} must be a list of [start, end] seconds')
    result = []
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f'{label} needs [start, end] pairs')
        start, end = [finite(v, label) for v in pair]
        if end <= start or round(end * RATE) <= round(start * RATE):
            raise ValueError(f'{label} end must be after start')
        result.append((round(start * RATE), round(end * RATE)))
    return result


def compare_pcm(before, after, allowed, protected=None):
    """Exact decoded f32 frame equality outside explicitly allowed half-open intervals."""
    allowed = intervals(allowed, 'allowed_intervals')
    protected = intervals(protected or [], 'protected_intervals')
    changed = outside = protected_count = 0
    ranges = []
    with pcm_file(before) as old, pcm_file(after) as new:
        same_length = old.stat().st_size == new.stat().st_size
        frame_count = new.stat().st_size // FRAME_BYTES
        if any(end > frame_count for _, end in allowed + protected):
            raise ValueError('Preservation intervals exceed decoded duration')
        with old.open('rb') as a, new.open('rb') as b:
            frame = 0
            while True:
                x, y = a.read(65536), b.read(65536)
                if not x and not y:
                    break
                if x != y:
                    for offset in range(0, max(len(x), len(y)), FRAME_BYTES):
                        if x[offset:offset + FRAME_BYTES] == y[offset:offset + FRAME_BYTES]:
                            continue
                        index = frame + offset // FRAME_BYTES
                        changed += 1
                        outside += not any(start <= index < end for start, end in allowed)
                        protected_count += any(start <= index < end for start, end in protected)
                        if ranges and ranges[-1][1] == index:
                            ranges[-1][1] = index + 1
                        elif len(ranges) < 20:
                            ranges.append([index, index + 1])
                frame += max(len(x), len(y)) // FRAME_BYTES
    return {'pass': same_length and outside == 0 and protected_count == 0, 'same_frame_count': same_length,
            'frames_after': frame_count, 'sample_rate': RATE, 'channels': CHANNELS, 'format': 'f32le',
            'changed_frames': changed, 'changed_outside_allowed': outside,
            'changed_in_protected': protected_count, 'first_changed_frame_ranges': ranges}


def audit(spec_path):
    spec_path = Path(spec_path).resolve()
    spec = load_json(spec_path)
    if spec.get('schema_version') != 1:
        raise ValueError('edit-audit schema_version must be 1')
    root = spec_path.parent
    target = resolve_file(spec.get('target'), root)
    spec_digest = sha256_file(spec_path)
    report = {'schema_version': 1, 'target': str(target), 'target_sha256': sha256_file(target),
              'spec': str(spec_path), 'spec_sha256': spec_digest,
              'files': {str(spec_path): spec_digest}, 'errors': [],
              'listening_and_motion_review_required': True, 'clock_map_is_declared_evidence': True}
    def source(value):
        path = resolve_file(value, root)
        report['files'][str(path)] = sha256_file(path)
        return path
    populated = False
    for key in ('clock_segments', 'required_signals', 'audio_joins', 'pcm_preservation'):
        if not isinstance(spec.get(key, []), list):
            raise ValueError(f'{key} must be a list')
        if any(not isinstance(item, dict) for item in spec.get(key, [])):
            raise ValueError(f'{key} entries must be objects')
        populated |= bool(spec.get(key))
    if not populated:
        raise ValueError('Declare at least one edit check')
    report['clocks'] = check_clocks(spec.get('clock_segments', []))
    if any(not item['pass'] for item in report['clocks']):
        report['errors'].append('Declared continuous source clock has a jump, gap or source change')
    report['signals'] = []
    for item in spec.get('required_signals', []):
        path = source(item.get('path'))
        stats = signal_stats(path, item.get('in', 0), item.get('duration'))
        threshold = finite(item.get('min_peak', 0), 'min_peak')
        stats.update(path=str(path), passed=stats['peak'] > threshold)
        report['signals'].append(stats)
        if not stats['passed']:
            report['errors'].append(f'Required audio interval is silent or below min_peak: {path.name}')
    report['audio_joins'] = []
    for item in spec.get('audio_joins', []):
        path = source(item.get('path', str(target)))
        report['audio_joins'].append(dict(path=str(path), **join_stats(path, item.get('at'),
            item.get('window_ms', 10), item.get('jump_review_db', 12), item.get('step_review', .1))))
    report['pcm_preservation'] = []
    for item in spec.get('pcm_preservation', []):
        before, after = source(item.get('before')), source(item.get('after'))
        result = compare_pcm(before, after, item.get('allowed_intervals'), item.get('protected_intervals'))
        report['pcm_preservation'].append(dict(before=str(before), after=str(after), **result))
        if not result['pass']:
            report['errors'].append('Decoded PCM changed outside the allowed repair or in protected content, or its length changed')
    report['technical_pass'] = not report['errors']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        result = audit(args.spec)
        write_new(args.out, result)
        print(json.dumps({'technical_pass': result['technical_pass'], 'report': str(Path(args.out).resolve())}))
        sys.exit(0 if result['technical_pass'] else 1)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
