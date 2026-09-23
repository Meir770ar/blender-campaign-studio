"""Render Hebrew typography locally using Chromium bidi/shaping and a licensed font."""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path
import sys
import unicodedata
from studio import integer, number, load_json, source_path, write_new


def render(spec_path, output):
    spec_path = Path(spec_path).resolve()
    spec = load_json(spec_path)
    if not isinstance(spec, dict):
        raise ValueError('Text specification must be an object')
    width = integer(spec.get('width'), 'width', 16, 8192)
    height = integer(spec.get('height'), 'height', 16, 8192)
    font_size = integer(spec.get('font_size'), 'font_size', 8, 1000)
    padding = integer(spec.get('padding', 64), 'padding', 0, min(width, height) // 2 - 1)
    line_height = number(spec.get('line_height', 1.3), 'line_height', 0.8, 3)
    align = spec.get('align', 'right')
    if align not in ('right', 'center', 'left'):
        raise ValueError('align must be right, center or left')
    vertical = spec.get('vertical', 'center')
    if vertical not in ('top', 'center', 'bottom'):
        raise ValueError('vertical must be top, center or bottom')
    text = spec.get('text')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('text must be a nonempty string in logical reading order')
    runs = spec.get('runs')
    if runs is not None:
        if not isinstance(runs, list) or not runs or any(not isinstance(r, dict) or not isinstance(r.get('text'), str) for r in runs):
            raise ValueError('runs must be nonempty text/color objects')
        if ''.join(r['text'] for r in runs) != text:
            raise ValueError('Styled runs must reproduce text exactly in logical order')
    font = source_path(spec.get('font_file'), spec_path.parent)
    if font.suffix.lower() not in ('.otf', '.ttf', '.woff', '.woff2'):
        raise ValueError('Use an OTF, TTF, WOFF or WOFF2 font')
    output = Path(output).resolve()
    if output.suffix.lower() != '.png':
        raise ValueError('Typography output must be a PNG')
    report_path = output.with_suffix('.qa.json')
    if output.exists() or report_path.exists():
        raise ValueError('Output already exists; choose a new revision')
    from fontTools.ttLib import TTFont
    from playwright.sync_api import sync_playwright
    with TTFont(str(font)) as face:
        cmap = face.getBestCmap() or {}
        missing = sorted({ord(char) for char in text if not char.isspace() and
                          unicodedata.category(char) != 'Cf' and ord(char) not in cmap})
    if missing:
        raise ValueError('Font lacks glyphs: ' + ', '.join(f'U+{code:04X}' for code in missing))
    payload = base64.b64encode(font.read_bytes()).decode('ascii')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': height}, device_scale_factor=1)
            page.route('**/*', lambda route: route.abort())
            page.set_content('<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"></head>'
                             '<body><main id="frame"><div id="copy" dir="rtl"></div></main></body></html>')
            metrics = page.evaluate('''async ({spec, payload, width, height, font_size, padding, line_height, align, vertical}) => {
                const face = new FontFace('CampaignFont', 'url(data:font/otf;base64,' + payload + ')');
                await face.load(); document.fonts.add(face); await document.fonts.ready;
                const color = spec.color || '#ffffff';
                const background = spec.background || 'transparent';
                if (!CSS.supports('color', color) || !CSS.supports('color', background))
                    throw new Error('Invalid text/background color');
                const body = document.body;
                Object.assign(body.style, {margin:'0', width:width+'px', height:height+'px', background});
                const frame = document.getElementById('frame');
                Object.assign(frame.style, {boxSizing:'border-box', width:'100%', height:'100%',
                    padding:padding+'px', display:'flex', flexDirection:'column',
                    justifyContent:({top:'flex-start',center:'center',bottom:'flex-end'})[vertical]});
                const copy = document.getElementById('copy');
                Object.assign(copy.style, {fontFamily:'CampaignFont', fontSize:font_size+'px', fontWeight:'400',
                    fontSynthesis:'none', lineHeight:String(line_height), textAlign:align, color,
                    direction:'rtl', unicodeBidi:'plaintext', whiteSpace:'pre-wrap', overflowWrap:'normal', flexShrink:'0'});
                if (spec.runs) {
                    for (const run of spec.runs) {
                        const span = document.createElement('span'); span.textContent = run.text;
                        if (run.color) {
                            if (!CSS.supports('color', run.color)) throw new Error('Invalid run color');
                            span.style.color = run.color;
                        }
                        copy.appendChild(span);
                    }
                } else copy.textContent = spec.text;
                const r = copy.getBoundingClientRect();
                const ink = document.createRange(); ink.selectNodeContents(copy);
                const boxes = Array.from(ink.getClientRects()).map(b => ({left:b.left, right:b.right, top:b.top, bottom:b.bottom}));
                const overflow = r.height > height - 2*padding + 0.5 || copy.scrollWidth > copy.clientWidth + 1 ||
                    boxes.some(b => b.left < padding - 1 || b.right > width - padding + 1 || b.top < 0 || b.bottom > height);
                return {overflow, bounds:{left:r.left,top:r.top,width:r.width,height:r.height},
                    direction:getComputedStyle(copy).direction, font_loaded:document.fonts.check(font_size+'px CampaignFont'),
                    text:copy.textContent, width, height};
            }''', {'spec': spec, 'payload': payload, 'width': width, 'height': height,
                   'font_size': font_size, 'padding': padding, 'line_height': line_height,
                   'align': align, 'vertical': vertical})
            if metrics['overflow']:
                raise ValueError('Text exceeds its safe area; shorten copy, reflow or explicitly adjust font_size/padding')
            if not metrics['font_loaded']:
                raise ValueError('Font did not load; no fallback output was rendered')
            image = page.screenshot(type='png', omit_background=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('xb') as stream:
                stream.write(image)
            metrics['font_file'] = str(font)
            metrics['source_spec'] = str(spec_path)
            metrics['visual_review_required'] = True
            write_new(report_path, metrics)
            return metrics
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(render(args.spec, args.out), ensure_ascii=False, indent=2))
    except (ValueError, OSError, ImportError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    main()
