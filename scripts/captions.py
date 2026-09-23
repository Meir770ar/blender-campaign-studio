"""Word-timed, phrase-stable Hebrew emphasis overlays rendered with Chromium shaping."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from editorial import checked_words
from campaign_common import new_directory
from studio import load_json, integer, number, write_new
from render_text import render

HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
WORD_PUNCTUATION = '.,!?;:"\'()[]{}«»“”„‚‘’…-–—'


def phrases(words, max_words=5, max_chars=40, gap=.5):
    result, current = [], []
    for word in words:
        if current and (len(current) >= max_words or
             len(' '.join(w['word'] for w in current+[word])) > max_chars or
             word['start']-current[-1]['end'] > gap or current[-1]['word'].endswith(('.', '?', '!'))):
            result.append(current); current = []
        current.append(word)
    if current: result.append(current)
    return result


def normalize_word(word):
    """Match key for brand words: surrounding punctuation stripped, case-folded, logical order kept."""
    return word.strip(WORD_PUNCTUATION).casefold()


def brand_colors(value):
    """`brand_words` style field: {"word": "#rrggbb"}. Those words render in their brand color in
    every caption state (the spoken-word emphasis never overrides a brand color)."""
    if value is None:
        return {}
    if not isinstance(value, dict) or not value:
        raise ValueError('brand_words must be an object mapping words to #rrggbb colors')
    result = {}
    for word, color in value.items():
        key = normalize_word(word) if isinstance(word, str) else ''
        if not key or not isinstance(color, str) or not HEX_COLOR.match(color):
            raise ValueError(f'brand_words entry {word!r} needs a nonempty word and a #rrggbb color')
        result[key] = color
    return result


def phrase_runs(group, active, base_color, emphasis, brand):
    """Color runs for one phrase state. Brand words keep their brand color; the spoken-word
    emphasis (when enabled) colors the other words while they are active."""
    runs = []
    for i, w in enumerate(group):
        key = normalize_word(w['word'])
        color = brand.get(key, base_color)
        if emphasis and i == active and key not in brand:
            color = emphasis
        runs.append({'text': w['word'] + (' ' if i < len(group)-1 else ''), 'color': color})
    return runs


def build(words_path, style_path, output, fps, channel):
    integer(fps, 'fps', 1, 120); integer(channel, 'channel', 2, 128)
    words = checked_words(load_json(words_path))
    style_path = Path(style_path).resolve()
    style = load_json(style_path)
    max_words = integer(style.pop('max_words', 5), 'max_words', 1, 15)
    max_chars = integer(style.pop('max_chars', 40), 'max_chars', 5, 160)
    gap = number(style.pop('phrase_gap', .5), 'phrase_gap', .05, 2)
    emphasis = style.pop('highlight_color', '#ffd36a')
    if emphasis is not None and (not isinstance(emphasis, str) or not HEX_COLOR.match(emphasis)):
        raise ValueError('highlight_color must be #rrggbb, or null to disable spoken-word emphasis')
    brand = brand_colors(style.pop('brand_words', None))
    base_color = style.get('color', '#ffffff')
    if 'font_file' in style:
        font = Path(style['font_file'])
        style['font_file'] = str((style_path.parent/font).resolve() if not font.is_absolute() else font)
    output = new_directory(output)
    clips, srt, phrase_specs = [], [], []
    brand_hits = 0
    for group_index, group in enumerate(phrases(words, max_words, max_chars, gap)):
        text = ' '.join(w['word'] for w in group)
        start, end = round(group[0]['start']*fps), round(group[-1]['end']*fps)
        if end <= start: continue
        brand_hits += sum(normalize_word(w['word']) in brand for w in group)
        # One stable layout per phrase, with color-only states. No resizing/reflow on emphasis.
        # Without spoken-word emphasis a phrase is a single state (brand colors only).
        boundaries = {start, end}
        if emphasis:
            for word in group:
                boundaries.update((max(start, round(word['start']*fps)), min(end, round(word['end']*fps))))
        boundaries = sorted(boundaries)
        cached = {}
        for a, b in zip(boundaries, boundaries[1:]):
            if b <= a: continue
            time = (a+b)/2/fps
            active = next((i for i, w in enumerate(group) if w['start'] <= time < w['end']), -1) if emphasis else -1
            if active not in cached:
                spec = {**style, 'text': text, 'runs': phrase_runs(group, active, base_color, emphasis, brand)}
                spec_path = output / f'phrase-{group_index+1:03d}-state-{active+1:02d}.json'
                png = spec_path.with_suffix('.png')
                write_new(spec_path, spec); render(spec_path, png)
                cached[active] = (png, spec_path)
            png, spec_path = cached[active]
            clips.append({'id': f'caption-{group_index+1}-{a}', 'kind': 'image', 'path': str(png),
                          'text_source': str(spec_path), 'start': a+1, 'duration': b-a, 'channel': channel})
        phrase_specs.append({'text': text, 'start': start/fps, 'end': end/fps})
        srt.append(f'{len(srt)+1}\n{srt_time(start/fps)} --> {srt_time(end/fps)}\n{text}\n')
    for left, right in zip(clips, clips[1:]):
        if left['start']+left['duration'] > right['start']:
            raise ValueError('Caption phrases overlap; review overlapping speakers before assembly')
    write_new(output / 'overlays.json', {'fps': fps, 'clips': clips})
    write_new(output / 'phrases.json', phrase_specs)
    write_new(output / 'captions.srt', '\n'.join(srt))
    return {'overlays': str(output / 'overlays.json'), 'states': len(clips), 'phrases': len(phrase_specs),
            'spoken_word_emphasis': bool(emphasis), 'brand_words_applied': brand_hits}


def srt_time(seconds):
    ms = round(seconds*1000)
    return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--words', required=True); p.add_argument('--style', required=True); p.add_argument('--out-dir', required=True)
    p.add_argument('--fps', type=int, required=True); p.add_argument('--channel', type=int, default=10)
    a = p.parse_args()
    try: print(json.dumps(build(a.words, a.style, a.out_dir, a.fps, a.channel)))
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr); sys.exit(1)
