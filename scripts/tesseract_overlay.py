"""Tesseract layer for the campaign studio: Hebrew kinetic-typography / title overlays on the station.

Tesseract (Mirage, `tsrct` CLI) is an agent-native motion-graphics engine. It renders Hebrew RTL
text with niqqud and bidi correctly (verified 2026-09-23). Two hard facts drive this bridge:

  1. RENDER RUNS ON THE VIDEO STATION ONLY. The laptop CPU (i7-9750H) crashes the renderer with an
     illegal instruction; the station (RTX A5000) renders fine. So authoring + font prep happen on the
     laptop, and every `tsrct` project/render call runs on the station over the OS-owned SSH alias.
  2. BRAND FONTS MUST BE NORMALIZED. The renderer's font matcher fails on family names with periods or
     spaces (e.g. "Almoni Tzar DL 4.0 AAA"), and only rasterizes TrueType outlines. This bridge
     normalizes any brand OTF/TTF to a clean ASCII-named TrueType before import; the visible glyphs are
     unchanged (Almoni renders as Almoni).

Output is a Hebrew title/overlay: an opaque MP4 or, with --overlay, a transparent ProRes 4444 MOV that
DaVinci or Blender composite over footage. Text layers stay editable in the `.tsrct`; this is a
supported-composition tool, not a replacement for Blender 3D or DaVinci grading/delivery.

Commands:
  prep-font  --file FONT --out-dir DIR                       normalize a brand font -> clean TrueType + family name
  title      --text T --font FONT --name NAME --out-dir DIR  build + render a Hebrew title/overlay on the station
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

from campaign_common import now, sha256_file
from studio import load_json, write_new

SKILL_ROOT = Path(__file__).resolve().parent.parent
SSH_OPTS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', '-o', 'StrictHostKeyChecking=accept-new']
DEFAULT_TSRCT = 'C:/Tesseract/bin/tsrct.cmd'  # override in connections.json (tesseract.tsrct)
DEFAULT_ALIAS = 'ai-station'
DEFAULT_WORKROOT = 'C:/tesseract-work'  # override in connections.json (tesseract.work_root)


# ─── station config ──────────────────────────────────────────────────────────

def station_config():
    path = SKILL_ROOT / 'connections.json'
    entry = (load_json(path).get('tesseract') if path.is_file() else None) or {}
    return {'ssh_alias': entry.get('ssh_alias', DEFAULT_ALIAS),
            'tsrct': entry.get('tsrct', DEFAULT_TSRCT),
            'work_root': entry.get('work_root', DEFAULT_WORKROOT)}


def _run(argv, timeout, input_bytes=None):
    """Run a command with output to temp files (Windows ssh.exe under a pipe can hang). Returns
    (returncode, stdout, stderr)."""
    with tempfile.TemporaryDirectory() as tmp:
        op, ep = Path(tmp) / 'o', Path(tmp) / 'e'
        with open(op, 'wb') as out, open(ep, 'wb') as err:
            proc = subprocess.run(argv, input=input_bytes,
                                  stdin=(None if input_bytes is not None else subprocess.DEVNULL),
                                  stdout=out, stderr=err, timeout=timeout)
        return proc.returncode, op.read_bytes().decode('utf-8', 'replace'), ep.read_bytes().decode('utf-8', 'replace')


def ssh_ps(config, powershell, timeout=300):
    """Run one PowerShell script on the station and return its stdout. The script is passed as a
    base64 -EncodedCommand so a complex multi-statement script survives ssh -> cmd -> powershell
    without any quoting problems."""
    b64 = base64.b64encode(powershell.encode('utf-16-le')).decode('ascii')
    rc, out, err = _run(['ssh', *SSH_OPTS, config['ssh_alias'], 'powershell', '-NoProfile', '-EncodedCommand', b64], timeout)
    if rc:
        raise ValueError(f'station command failed (exit {rc}): {(err or out)[-500:]}')
    return out


def scp_to_station(config, local_path, remote_path, timeout=600):
    win_dir = remote_path.rsplit('/', 1)[0].replace('/', '\\')
    _run(['ssh', *SSH_OPTS, config['ssh_alias'], f'if not exist "{win_dir}" mkdir "{win_dir}"'], 60)
    rc, _o, err = _run(['scp', *SSH_OPTS, '-q', str(local_path), f'{config["ssh_alias"]}:{remote_path}'], timeout)
    if rc:
        raise ValueError(f'could not copy {Path(local_path).name} to the station: {err[-300:]}')


def scp_from_station(config, remote_path, local_path, timeout=600):
    rc, _o, err = _run(['scp', *SSH_OPTS, '-q', f'{config["ssh_alias"]}:{remote_path}', str(local_path)], timeout)
    if rc:
        raise ValueError(f'could not fetch {remote_path} from the station: {err[-300:]}')


# ─── brand-font normalization (the fix Tesseract needs) ───────────────────────

def clean_family(name):
    """A clean ASCII family Tesseract's matcher accepts: letters/digits only, no periods or spaces."""
    ascii_name = re.sub(r'[^A-Za-z0-9]', '', name)
    return ascii_name or 'BrandFont'


def prepare_font(font_path, out_dir):
    """Return {family, style, ttf}. Convert CFF/OTF outlines to TrueType and rename the family to a
    clean ASCII name so the renderer resolves it; glyphs are unchanged."""
    from fontTools.ttLib import TTFont  # local import: only needed for the Tesseract path
    font_path = Path(font_path).resolve()
    if not font_path.is_file():
        raise ValueError(f'font not found: {font_path}')
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    font = TTFont(str(font_path))
    orig_family = font['name'].getDebugName(1) or font_path.stem
    orig_style = font['name'].getDebugName(2) or 'Regular'
    family = clean_family(orig_family)
    style = 'Regular'  # a single face per file; the renderer matches family/style, keep it simple
    if 'CFF ' in font and 'glyf' not in font:
        # The renderer rasterizes only TrueType outlines; convert CFF->glyf with the installed otf2ttf.
        exe = shutil.which('otf2ttf') or str(Path(sys.executable).parent / 'Scripts' / 'otf2ttf.exe')
        if not Path(exe).is_file():
            raise ValueError('otf2ttf is required to convert an OTF brand font to TrueType; pip install otf2ttf cu2qu')
        converted = out_dir / f'{family}-truetype.ttf'
        proc = subprocess.run([exe, '-o', str(converted), str(font_path)], capture_output=True)
        if proc.returncode or not converted.is_file():
            raise ValueError('OTF->TTF conversion failed: ' + proc.stderr.decode('utf-8', 'replace')[-300:])
        font = TTFont(str(converted))
    for nid, value in ((1, family), (2, style), (4, family), (6, f'{family}-{style}'), (16, family), (17, style)):
        font['name'].setName(value, nid, 3, 1, 0x409)
        font['name'].setName(value, nid, 1, 0, 0)
    ttf = out_dir / f'{family}.ttf'
    font.save(str(ttf))
    return {'family': family, 'style': style, 'ttf': str(ttf), 'source': str(font_path),
            'source_family': orig_family, 'source_style': orig_style}


# ─── title / overlay authoring ────────────────────────────────────────────────

def _text_action(text, family, style, font_size, canvas, fill):
    w, h = canvas
    margin = int(w * 0.06)
    box_w, box_h = w - 2 * margin, int(h * 0.5)
    top = int(h * 0.36)
    return [{
        'type': 'createFxTextLayer', 'compositionId': 'main', 'insertIndex': 0, 'layerId': 1,
        'name': 'Hebrew title', 'activeRange': {'start': 0, 'duration': 3000},
        'transform': {'anchorPoint': [0, 0], 'position': [margin, top], 'scale': [100, 100], 'rotation': 0, 'opacity': 100},
        'sourceText': {'text': text, 'fontFamily': family, 'fontStyle': style, 'fontSize': font_size,
                       'fillColor': list(fill), 'justification': 'center', 'boxText': True,
                       'boxPosition': [0, 0], 'boxSize': [box_w, box_h]},
    }]


def make_title(text, font_path, name, out_dir, canvas=(1080, 1920), duration=3.0, font_size=130,
               fill=(1, 1, 1, 1), overlay=False, config=None):
    """Normalize the font, build a Hebrew title `.tsrct` on the station, render a preview PNG and export
    an MP4 (or a transparent ProRes MOV with `overlay=True`), and pull the results into `out_dir`."""
    if not re.match(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,64}$', name):
        raise ValueError('name must be an ASCII slug (letters, digits, dot, dash, underscore)')
    config = config or station_config()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    prep_dir = out_dir / 'fonts'
    font = prepare_font(font_path, prep_dir)

    actions = _text_action(text, font['family'], font['style'], font_size, canvas, fill)
    actions_local = out_dir / f'{name}-actions.json'
    write_new(actions_local, actions)

    remote = f"{config['work_root']}/{name}"
    proj = f'{remote}/{name}.tsrct'
    scp_to_station(config, font['ttf'], f"{remote}/{Path(font['ttf']).name}")
    scp_to_station(config, actions_local, f'{remote}/actions.json')

    tsrct = config['tsrct']
    W, H = canvas
    # Overlay: export only the title layer (composition 'main', layerId 1 from _text_action) as a
    # transparent ProRes 4444 MOV, no audio. Otherwise a normal opaque MP4.
    export_name = f'{name}.mov' if overlay else f'{name}.mp4'
    export_flags = '--format prores --fx-solo main:1 ' if overlay else ''
    # `project create` already makes a 1080x1920 / 3s composition; only round-trip the document JSON
    # to resize when the request differs (the round-trip is avoided in the common case).
    resize = ''
    if (W, H) != (1080, 1920) or abs(duration - 3.0) > 1e-6:
        resize = (
            f"& '{tsrct}' project checkout --project '{proj}' --output ed.json | Out-Null; "
            f"$d = Get-Content ed.json -Raw | ConvertFrom-Json; $d.duration = {duration}; "
            f"$d.dimensions.width = {W}; $d.dimensions.height = {H}; "
            f"$d | ConvertTo-Json -Depth 40 | Set-Content -Encoding utf8 ed.json; "
            f"& '{tsrct}' project commit --project '{proj}' --file ed.json | Out-Null; "
        )
    ps = (
        f"cd '{remote.replace('/', chr(92))}'; "
        f"& '{tsrct}' project create --project '{proj}' | Out-Null; "
        + resize +
        f"& '{tsrct}' project import-font --project '{proj}' --file '{remote}/{Path(font['ttf']).name}' | Out-Null; "
        f"& '{tsrct}' project apply --project '{proj}' --actions actions.json 2>&1 | Write-Output; "
        f"& '{tsrct}' preview --project '{proj}' --time 1 --output '{name}-preview.png' 2>&1 | Write-Output; "
        f"& '{tsrct}' export {export_flags}--project '{proj}' --output '{export_name}' 2>&1 | Write-Output; "
        f"if(Test-Path '{name}-preview.png'){{ Write-Output ('PREVIEW ' + (Get-Item '{name}-preview.png').Length) }}; "
        f"if(Test-Path '{export_name}'){{ Write-Output ('EXPORT ' + (Get-Item '{export_name}').Length) }}"
    )
    out = ssh_ps(config, ps, timeout=600)
    if 'missing_fonts' in out:
        raise ValueError(f'station reported missing_fonts even after normalization: {out[-300:]}')

    preview_local = out_dir / f'{name}-preview.png'
    export_local = out_dir / export_name
    scp_from_station(config, f'{remote}/{name}-preview.png', preview_local)
    scp_from_station(config, f'{remote}/{export_name}', export_local)

    report = {'name': name, 'host': 'station', 'engine': 'Tesseract (Mirage tsrct 0.2.0)',
              'text': text, 'font': font, 'canvas': [W, H], 'duration': duration,
              'overlay': overlay, 'preview': str(preview_local), 'export': str(export_local),
              'export_kind': 'ProRes 4444 MOV (alpha)' if overlay else 'H.264 MP4',
              'preview_sha256': sha256_file(preview_local) if preview_local.is_file() else None,
              'export_sha256': sha256_file(export_local) if export_local.is_file() else None,
              'ai_advisory': False, 'note': 'editable title overlay; composite in Blender/DaVinci. Watch the frame — a render is not creative acceptance.',
              'generated_utc': now()}
    write_new(out_dir / f'{name}-tesseract.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    pf = sub.add_parser('prep-font', help='normalize a brand OTF/TTF to a clean TrueType Tesseract resolves')
    pf.add_argument('--file', required=True)
    pf.add_argument('--out-dir', required=True)
    ti = sub.add_parser('title', help='render a Hebrew title/overlay on the station')
    ti.add_argument('--text', required=True, help='Hebrew title text (\\n for line breaks)')
    ti.add_argument('--font', required=True, help='brand OTF/TTF file')
    ti.add_argument('--name', required=True, help='ASCII slug for the output files')
    ti.add_argument('--out-dir', required=True)
    ti.add_argument('--canvas', default='1080x1920', help='WxH (default 1080x1920)')
    ti.add_argument('--duration', type=float, default=3.0)
    ti.add_argument('--font-size', type=int, default=130)
    ti.add_argument('--fill', default='1,1,1,1', help='r,g,b,a in 0..1')
    ti.add_argument('--overlay', action='store_true', help='export a transparent ProRes 4444 MOV instead of MP4')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prep-font':
            r = prepare_font(args.file, args.out_dir)
            print(json.dumps(r, ensure_ascii=False))
            return 0
        canvas = tuple(int(x) for x in args.canvas.lower().split('x'))
        fill = tuple(float(x) for x in args.fill.split(','))
        text = args.text.replace('\\n', '\n')
        r = make_title(text, args.font, args.name, args.out_dir, canvas=canvas, duration=args.duration,
                       font_size=args.font_size, fill=fill, overlay=args.overlay)
        print(json.dumps({'name': r['name'], 'family': r['font']['family'], 'preview': r['preview'],
                          'export': r['export'], 'export_kind': r['export_kind']}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
