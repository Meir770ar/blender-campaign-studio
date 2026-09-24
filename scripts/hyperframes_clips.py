"""Motion graphics from HTML with HyperFrames: one check gate, one render, one receipt. No provider calls.

  doctor   CLI version against connections.json (hyperframes.min_version) and local render readiness
  render   `hyperframes check` on the project, then one `hyperframes render` at the plan's fps into a new
           file, ffprobe verification and a receipt next to the output

The composition itself is authored with the hyperframes-core skill (HTML, GSAP, data-* timing). Hebrew
text keeps the rules of references/hebrew-and-blender.md: logical order, a licensed local font declared
with @font-face, and a human look at the frames. The rendered file enters plan.json as an ordinary movie
clip; a transparent WebM or MOV becomes an alpha sequence through `studio.py alpha-sequence`.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from campaign_common import now, sha256_file
from studio import ffprobe, load_json, write_new

ROOT = Path(__file__).resolve().parent.parent
QUALITIES = ('draft', 'standard', 'high')
FORMATS = {'mp4': '.mp4', 'webm': '.webm', 'mov': '.mov', 'png-sequence': ''}


def settings(connections=None):
    section = load_json(connections or ROOT / 'connections.json').get('hyperframes', {})
    return {'cli': section.get('cli', 'hyperframes'), 'min_version': section.get('min_version', '0.8.0')}


def run_cli(cfg, args, timeout, cwd=None):
    exe = shutil.which(cfg['cli'])
    if not exe:
        raise ValueError('hyperframes CLI not found on PATH; install it with `npm i -g hyperframes`')
    env = {**os.environ, 'HYPERFRAMES_SKIP_SKILLS': '1', 'NO_COLOR': '1', 'FORCE_COLOR': '0'}
    result = subprocess.run([exe, *args], capture_output=True, timeout=timeout, cwd=cwd, env=env)
    text = result.stdout.decode('utf-8', 'replace') + result.stderr.decode('utf-8', 'replace')
    return result.returncode, text


def version_tuple(text):
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', text)
    if not match:
        raise ValueError('Cannot read a hyperframes version from: ' + text.strip()[:120])
    return tuple(int(part) for part in match.groups())


def doctor(cfg):
    _, version_text = run_cli(cfg, ['--version'], 60)
    version = version_tuple(version_text)
    minimum = version_tuple(cfg['min_version'])
    _, report = run_cli(cfg, ['doctor'], 180)
    lines = [line.strip() for line in report.splitlines() if line.strip()]

    def ok(label):
        return any(line.startswith('✓') and label in line for line in lines)

    chrome, ffmpeg, node = ok('Chrome'), ok('FFmpeg'), ok('Node.js')
    result = {'version': '.'.join(map(str, version)), 'minimum': cfg['min_version'], 'version_ok': version >= minimum,
              'node': node, 'ffmpeg': ffmpeg, 'chrome_ready': chrome,
              'render_ready': version >= minimum and chrome and ffmpeg and node}
    if not chrome:
        result['fix'] = 'hyperframes browser ensure'
    if version < minimum:
        result['fix'] = 'npm i -g hyperframes@latest'
    return result


def render(cfg, project, out, fps, composition=None, quality='high', fmt='mp4', variables=None,
           skip_check_reason=None, plan=None):
    project = Path(project).resolve()
    out = Path(out).resolve()
    if not (project / 'index.html').is_file():
        raise ValueError('A HyperFrames project needs index.html (see the hyperframes-core skill)')
    if quality not in QUALITIES:
        raise ValueError('quality must be draft, standard or high')
    if fmt not in FORMATS:
        raise ValueError('format must be mp4, webm, mov or png-sequence')
    if fmt != 'png-sequence' and out.suffix.lower() != FORMATS[fmt]:
        raise ValueError(f'output for format {fmt} must end with {FORMATS[fmt]}')
    if out.exists():
        raise ValueError('Output exists; render into a new file or version folder')
    if type(fps) is not int or not 1 <= fps <= 240:
        raise ValueError('fps must be an integer frame rate')
    if plan is not None:
        plan_fps = load_json(plan).get('fps')
        if plan_fps != fps:
            raise ValueError(f'fps {fps} differs from the plan fps {plan_fps}; render at the plan rate')
    if composition is not None:
        target = (project / composition).resolve()
        if project not in target.parents or not target.is_file():
            raise ValueError('composition must be an existing file inside the project')
    if variables is not None:
        if not isinstance(json.loads(variables), dict):
            raise ValueError('variables must be a JSON object')
    if skip_check_reason is not None and not skip_check_reason.strip():
        raise ValueError('--skip-check-reason needs the accepted finding in words')
    health = doctor(cfg)
    if not health['render_ready']:
        raise ValueError('HyperFrames is not ready to render locally: ' + json.dumps(health))
    if skip_check_reason is None:
        code, report = run_cli(cfg, ['check', str(project)], 1200)
        check = {'exit_code': code, 'report_tail': report[-4000:]}
        if code:
            raise ValueError('hyperframes check failed; fix the findings or record the accepted finding with '
                             '--skip-check-reason:\n' + report[-2000:])
    else:
        check = {'skipped_reason': skip_check_reason.strip()}
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ['render', str(project), '--output', str(out), '--fps', str(fps), '--quality', quality,
            '--format', fmt, '--quiet', '--strict']
    if composition is not None:
        args += ['--composition', composition]
    if variables is not None:
        args += ['--variables', variables]
    code, log = run_cli(cfg, args, 7200)
    if code or not out.exists():
        raise ValueError('hyperframes render did not produce the output:\n' + log[-2000:])
    if fmt == 'png-sequence':
        frames = sorted(p for p in out.iterdir() if p.suffix.lower() == '.png')
        if not frames:
            raise ValueError('png-sequence produced no frames')
        media = {'frames': len(frames), 'first': str(frames[0]), 'sha256_first': sha256_file(frames[0])}
        digest = media['sha256_first']
    else:
        media = ffprobe(out)
        picture = next((s for s in media['streams'] if s.get('codec_type') == 'video'), None)
        if not picture:
            raise ValueError('Rendered file has no video stream')
        num, _, den = str(picture.get('r_frame_rate', '0/1')).partition('/')
        if abs(int(num) / int(den or 1) - fps) > 1e-6:
            raise ValueError(f'rendered frame rate {picture.get("r_frame_rate")} differs from {fps}')
        digest = sha256_file(out)
    receipt = {'version': 1, 'hyperframes': health['version'], 'project': str(project),
               'composition': composition or 'index.html', 'command': args, 'output': str(out), 'sha256': digest,
               'media': media, 'check': check, 'rendered_at': now(),
               'review': 'watch the motion at final size; check and snapshots are technical evidence only'}
    receipt_path = out / 'receipt.json' if fmt == 'png-sequence' else out.with_name(out.name + '.receipt.json')
    write_new(receipt_path, receipt)
    return receipt


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--connections', default=str(ROOT / 'connections.json'))
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    q = sub.add_parser('render')
    q.add_argument('--project', required=True, help='HyperFrames project directory (holds index.html)')
    q.add_argument('--out', required=True, help='new output file (mp4/webm/mov) or new directory (png-sequence)')
    q.add_argument('--fps', type=int, required=True, help='frame rate; must equal the plan fps')
    q.add_argument('--composition', help='composition file inside the project instead of index.html')
    q.add_argument('--quality', choices=QUALITIES, default='high')
    q.add_argument('--format', choices=tuple(FORMATS), default='mp4')
    q.add_argument('--variables', help='JSON object merged over the composition variables')
    q.add_argument('--plan', help='plan.json whose fps the render must match')
    q.add_argument('--skip-check-reason', help='skip the check gate and record the accepted finding')
    a = p.parse_args(argv)
    cfg = settings(a.connections)
    if a.command == 'doctor':
        result = doctor(cfg)
    else:
        result = render(cfg, a.project, a.out, a.fps, a.composition, a.quality, a.format, a.variables,
                        a.skip_check_reason, a.plan)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
