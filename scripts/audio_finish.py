"""Render voice/music/SFX stems, speech-driven ducking and measured two-pass loudness."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from campaign_common import new_directory, run
from studio import load_json, number, source_path, write_new
from editorial import inspect
from edit_audit import signal_stats


def gain_envelope(keys):
    """Piecewise-linear dB automation for one track as an FFmpeg volume expression.

    `keys` are [seconds_from_track_start, gain_db] points; the level holds before the first and
    after the last point and ramps linearly (in dB) between points. Evaluated per audio frame
    (~21 ms at 48 kHz), which is fine for swells, dips and transition lifts; it is not a
    sample-accurate fade (use fade_in/fade_out for edges)."""
    expr = f'({keys[-1][1]:.6g})'
    for (t0, g0), (t1, g1) in reversed(list(zip(keys, keys[1:]))):
        expr = (f'if(lt(t,({t1:.6g})),({g0:.6g})+(({g1:.6g})-({g0:.6g}))*(t-({t0:.6g}))/(({t1:.6g})-({t0:.6g})),'
                f'{expr})')
    expr = f'if(lt(t,({keys[0][0]:.6g})),({keys[0][1]:.6g}),{expr})'
    return f"volume='pow(10,({expr})/20)':eval=frame"


def checked_gain_keys(keys, length):
    if not isinstance(keys, list):
        raise ValueError('gain_keys must be a list of [seconds_from_track_start, gain_db] pairs')
    if len(keys) == 1:
        raise ValueError('gain_keys needs at least two points; use gain_db for a constant level')
    previous, result = -1, []
    for key in keys:
        if not isinstance(key, list) or len(key) != 2:
            raise ValueError('gain key must be [seconds_from_track_start, gain_db]')
        at = number(key[0], 'gain key time', 0, length)
        if at <= previous:
            raise ValueError('gain key times must strictly increase')
        previous = at
        result.append([at, number(key[1], 'gain key gain_db', -60, 12)])
    return result


def loudness(path, target, peak, lra):
    _, log = run(['ffmpeg', '-hide_banner', '-i', path, '-af',
                  f'loudnorm=I={target}:TP={peak}:LRA={lra}:print_format=json', '-f', 'null', '-'], timeout=1800)
    blocks = re.findall(r'\{\s*"input_i"[\s\S]*?\}', log)
    if not blocks:
        raise ValueError('Loudness measurement missing')
    result = json.loads(blocks[-1])
    if result['input_i'] == '-inf':
        raise ValueError('Mix is silent; cannot normalize')
    return result


def finish(spec_path, output):
    spec_path = Path(spec_path).resolve()
    spec = load_json(spec_path)
    duration = number(spec.get('duration'), 'duration', .1, 3600)
    target = number(spec.get('target_lufs', -16), 'target_lufs', -30, -9)
    peak = number(spec.get('true_peak_dbtp', -1.5), 'true_peak_dbtp', -9, -1)
    lra = number(spec.get('lra', 9), 'lra', 1, 20)
    tracks = spec.get('tracks')
    if not isinstance(tracks, list) or not tracks:
        raise ValueError('At least one explicit audio track is required')
    normalized, source_signal_checks = [], []
    for track in tracks:
        track = dict(track)
        if track.get('role') not in ('voice', 'music', 'sfx'):
            raise ValueError('Track role must be voice, music or sfx')
        source = source_path(track.get('path'), spec_path.parent)
        info = inspect(source)
        if not any(s['codec_type'] == 'audio' for s in info['streams']):
            raise ValueError('Track has no audio')
        total = float(info['format']['duration'])
        start = number(track.get('in', 0), 'in', 0, total)
        length = number(track.get('duration', total-start), 'track duration', .001, total-start)
        at = number(track.get('at', 0), 'at', 0, duration)
        if at+length > duration+.001:
            raise ValueError('Track exceeds mix duration; set an explicit trim')
        track.update(path=str(source), **{'in': start, 'duration': length, 'at': at})
        track['gain_db'] = number(track.get('gain_db', 0), 'gain_db', -60, 12)
        track['gain_keys'] = checked_gain_keys(track.get('gain_keys', []), length)
        expect_signal = track.get('expect_signal', track['role'] == 'sfx')
        if not isinstance(expect_signal, bool):
            raise ValueError('expect_signal must be boolean')
        reason = track.get('silence_reason')
        if track['role'] == 'sfx' and not expect_signal and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError('An intentionally silent SFX track requires silence_reason')
        if expect_signal:
            stats = signal_stats(source, start, length)
            source_signal_checks.append({'path': str(source), 'in': start, 'duration': length, **stats})
            if not stats['nonzero_samples']:
                raise ValueError(f'Required {track["role"]} interval is silent: {source.name}; replace the source or correct its trim')
        for key in ('fade_in', 'fade_out'):
            track[key] = number(track.get(key, .015 if track['role'] == 'voice' else 0), key, 0, length/2)
        normalized.append(track)
    duck = spec.get('duck', {})
    for key, default, lo, hi in [('threshold', .03, .000976, 1), ('ratio', 6, 1, 20),
                                ('attack_ms', 15, .01, 2000), ('release_ms', 350, .01, 9000)]:
        duck[key] = number(duck.get(key, default), key, lo, hi)
    output = new_directory(output)
    command = ['ffmpeg', '-v', 'error']
    filters, labels = [], {'voice': [], 'music': [], 'sfx': []}
    for i, t in enumerate(normalized):
        command += ['-i', t['path']]
        chain = f'aresample=48000,atrim=start_sample={round(t["in"]*48000)}:end_sample={round((t["in"]+t["duration"])*48000)},asetpts=N/SR/TB,aformat=channel_layouts=stereo'
        if t['role'] == 'voice' and spec.get('voice_cleanup', True):
            chain += ',highpass=f=70'
        if t['role'] == 'voice' and spec.get('denoise', False):
            chain += ',afftdn=nr=8:nf=-40'
        chain += f',volume={t["gain_db"]}dB'
        if t['gain_keys']:
            chain += ',' + gain_envelope(t['gain_keys'])
        if t['fade_in']: chain += f',afade=t=in:d={t["fade_in"]}'
        if t['fade_out']: chain += f',afade=t=out:st={t["duration"]-t["fade_out"]}:d={t["fade_out"]}'
        chain += f',adelay={round(t["at"]*48000)}S:all=1,apad,atrim=end_sample={round(duration*48000)},asetpts=N/SR/TB'
        filters.append(f'[{i}:a]{chain}[t{i}]')
        labels[t['role']].append(f'[t{i}]')
    for role, inputs in labels.items():
        if inputs:
            filters.append(''.join(inputs) + f'amix=inputs={len(inputs)}:normalize=0:dropout_transition=0[{role}]')
        else:
            filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={duration}[{role}]')
    for role in labels:
        filters.append(f'[{role}]asplit=2[{role}save][{role}mix]')
    if labels['voice'] and labels['music']:
        filters.append('[voicemix]asplit=2[voicefinal][control]')
        filters.append(f'[musicmix][control]sidechaincompress=threshold={duck["threshold"]}:ratio={duck["ratio"]}:attack={duck["attack_ms"]}:release={duck["release_ms"]}:makeup=1[ducked]')
        filters.append('[voicefinal][ducked][sfxmix]amix=inputs=3:normalize=0:dropout_transition=0[mixed]')
    else:
        filters.append('[voicemix][musicmix][sfxmix]amix=inputs=3:normalize=0:dropout_transition=0[mixed]')
    command += ['-filter_complex', ';'.join(filters)]
    for role in labels:
        command += ['-map', f'[{role}save]', '-c:a', 'pcm_f32le', '-n', str(output / f'{role}.wav')]
    command += ['-map', '[mixed]', '-c:a', 'pcm_f32le', '-n', str(output / 'premaster.wav')]
    run(command, timeout=1800, log=output / 'mix.log')
    measured = loudness(output / 'premaster.wav', target, peak, lra)
    normalized_filter = (f'loudnorm=I={target}:TP={peak}:LRA={lra}:measured_I={measured["input_i"]}:'
        f'measured_TP={measured["input_tp"]}:measured_LRA={measured["input_lra"]}:'
        f'measured_thresh={measured["input_thresh"]}:offset={measured["target_offset"]}:linear=true:print_format=json')
    run(['ffmpeg', '-hide_banner', '-i', output / 'premaster.wav', '-af', normalized_filter,
         '-ar', '48000', '-c:a', 'pcm_s24le', '-n', output / 'master.wav'], timeout=1800, log=output / 'master.log')
    final = loudness(output / 'master.wav', target, peak, lra)
    report = {'target_lufs': target, 'peak_limit': peak, 'before': measured, 'after': final,
              'duration': float(inspect(output / 'master.wav')['format']['duration']),
              'source_signal_checks': source_signal_checks, 'listening_review_required': True}
    report['pass'] = abs(float(final['input_i'])-target) <= 1 and float(final['input_tp']) <= peak+.2 and abs(report['duration']-duration) < .05
    write_new(output / 'qa.json', report)
    write_new(output / 'source-mix.json', spec)
    if not report['pass']:
        raise ValueError('Master outside loudness/peak/duration tolerance; inspect qa.json before delivery')
    return {'master': str(output / 'master.wav'), 'qa': report}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--spec', required=True); p.add_argument('--out-dir', required=True)
    a = p.parse_args()
    try: print(json.dumps(finish(a.spec, a.out_dir), indent=2))
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr); sys.exit(1)
