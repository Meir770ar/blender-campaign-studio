"""Antigravity layer for the campaign studio: script writing and semantic video analysis.

Antigravity is Google AI Pro through the user's subscription (no API key) — Gemini 3.5 Flash via
`agy-cloudcode.mjs`, which this bridge calls through `agy_call.mjs` (prompt on stdin, result on
stdout). It adds two things the deterministic pipeline lacks:

  script   turn a brief into a structured, story-first script (feeds the storyboard/plan)
  analyze  semantic video understanding of a rendered shot, or of the finished master, before delivery

Every call consumes subscription quota, so the bridge is invoked explicitly and never loops. The
analysis output is advisory evidence, never creative acceptance — a human still watches and listens.

Commands:
  script   --brief FILE --out FILE [--duration N]
  analyze  --media MP4 --kind shot|master --out FILE [--brief FILE] [--context TEXT]
  check    --media MP4 (--avoid ITEM ... | --request REQUEST.json) --out FILE [--context TEXT]
           closed yes/no questions: is each excluded item visibly present in the clip? Runs before the
           human review of a generated shot; "clear" is not acceptance, "flagged" is a reason to look.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from campaign_common import now, sha256_file
from studio import load_json, write_new

SKILL_ROOT = Path(__file__).resolve().parent.parent
AGY_CALL = Path(__file__).resolve().parent / 'agy_call.mjs'
ENGINE = 'Antigravity / Google AI Pro (Gemini 3.5 Flash)'
MODEL = 'gemini-3-flash-preview'


def _client_path():
    """Path to agy-cloudcode.mjs from connections.json (antigravity.cli), with a default."""
    path = SKILL_ROOT / 'connections.json'
    default = str(Path.home() / '.grok-claui' / 'agy-cloudcode.mjs')
    if not path.is_file():
        return default
    entry = (load_json(path).get('antigravity') or {})
    return entry.get('cli') or default


def _read_text(path):
    p = Path(path)
    if not p.is_file():
        raise ValueError(f'file not found: {p}')
    return p.read_text(encoding='utf-8-sig')


def call_agy(mode, prompt, media=None, timeout=600):
    """Run one Antigravity call. Returns the model's text; raises ValueError on failure."""
    if not AGY_CALL.is_file():
        raise ValueError(f'agy_call.mjs missing: {AGY_CALL}')
    argv = ['node', str(AGY_CALL), mode]
    if mode == 'video':
        if not (media and Path(media).is_file()):
            raise ValueError(f'analyze needs an existing media file: {media}')
        argv.append(str(Path(media).resolve()))
    env = dict(os.environ, AGY_CLOUDCODE=_client_path())
    proc = subprocess.run(argv, input=prompt.encode('utf-8'), capture_output=True, timeout=timeout, env=env)
    out = proc.stdout.decode('utf-8', 'replace').strip()
    if proc.returncode or not out:
        err = proc.stderr.decode('utf-8', 'replace')[-600:]
        raise ValueError(f'Antigravity call failed (exit {proc.returncode}): {err or "no output"}')
    return out


def extract_json(text):
    """Pull the first JSON object out of a model reply (fenced ```json block or first {...})."""
    fence = text.find('```')
    if fence != -1:
        rest = text[fence + 3:]
        if rest[:4].lower() == 'json':
            rest = rest[4:]
        end = rest.find('```')
        if end != -1:
            try:
                return json.loads(rest[:end].strip())
            except json.JSONDecodeError:
                pass
    start = text.find('{')
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None


SCRIPT_DOCTRINE = (
    'אתה תסריטאי-במאי לפרסומות בעברית. כתוב תסריט לפי הבריף בלבד; אל תמציא עובדות על המותג או המוצר.\n'
    'עקרונות בימוי מחייבים:\n'
    '- סיפור ראשון: בכל רגע קבע מה הצופה מבין, למה הוא שם לב, ומה הוא מרגיש.\n'
    '- בלי מילות מילוי כמו "קולנועי", "אפי", "פרימיום", "ויראלי" — אלה תוצאות להדגים, לא הוראות בימוי.\n'
    '- עברית תקנית ו-RTL, קצר וקונקרטי; כל שוט משרת את הסיפור.\n'
    '- לכל סצנה: מטרה בסיפור, ויזואל, פעולה, קריינות או דיאלוג, טקסט על המסך, וסאונד.\n'
    'החזר אך ורק JSON תקין, בלי טקסט מסביב, בפורמט:\n'
    '{"logline": "...", "duration_target_sec": <int>, "beats": ["..."], '
    '"scenes": [{"id": "S1", "purpose": "...", "visual": "...", "action": "...", '
    '"narration": "...", "on_screen_text": "...", "sound": "..."}]}'
)

TOOL_DIVISION = (
    'הנחיות הביצוע חייבות להיות קונקרטיות ומחולקות לפי כלי:\n'
    '- בלנדר (edit_blender): מקור תלת-ממד, קומפוזיטינג ואפקטים, שכבות טקסט עברי כ-PNG '
    '(render_text.py / captions.py, לעולם לא Text+), והרכבת VSE. ציין פעולות/פרמטרים ממשיים.\n'
    '- דה וינצי (edit_davinci): חיתוך וקיצור על הטיימליין, גרייד והתאמת צבע בין שוטים (nodes/LUT/CDL), '
    'מיקס Fairlight ואיזון לאודנס, ורינדור מסירה. ציין את הדף/הכלי והפעולה.\n'
    'לכל פגם תן המלצת תיקון מקצועית עם סיבה ועדיפות, ונתב אותה לכלי הנכון.'
)

ANALYZE_SHOT_DOCTRINE = (
    'אתה עורך-קולוריסט-מבקר מקצועי. נתח את השוט המצורף מול מטרתו. תאר מה באמת נראה ונשמע, לא מה שהיה אמור להיות.\n'
    'בדוק: התאמה לבריף, רציפות, קריאוּת הטקסט על המסך, מובנוּת האודיו, ופגמים (ריצוד, עיוות, פריימים חסרים, סנכרון).\n'
    + TOOL_DIVISION + '\n'
    'זו חוות דעת מייעצת בלבד, לא אישור יצירתי. החזר אך ורק JSON:\n'
    '{"summary": "...", "matches_brief": true, "continuity": "...", "emotional_read": "...", '
    '"text_readability": "...", "audio_intelligible": true, "defects": ["..."], '
    '"fixes": [{"issue": "...", "why": "...", "priority": "high"}], '
    '"edit_blender": ["..."], "edit_davinci": ["..."], '
    '"recommendation": "keep", "notes": "..."}'
)

ANALYZE_MASTER_DOCTRINE = (
    'אתה מפיק-קולוריסט-מבקר. עבור על הסרטון המוגמר לפני מסירה. שפוט את היצירה כולה מול הבריף.\n'
    'בדוק: בהירות הסיפור, קצב ומשך, סיום מותגי ברור, נכונות וקריאוּת הטקסט העברי, מובנוּת ואיזון האודיו, וקריאה לפעולה.\n'
    + TOOL_DIVISION + '\n'
    'זו חוות דעת מייעצת בלבד, לא אישור למסירה. החזר אך ורק JSON:\n'
    '{"summary": "...", "story_clear": true, "pacing": "...", "brand_ending": "...", '
    '"hebrew_text_ok": true, "audio_ok": true, "defects": ["..."], '
    '"fixes": [{"issue": "...", "why": "...", "priority": "high"}], '
    '"edit_blender": ["..."], "edit_davinci": ["..."], '
    '"recommendation": "deliver", "notes": "..."}'
)


def _provenance(kind, advisory, **extra):
    p = {'engine': ENGINE, 'model': MODEL, 'generated_utc': now(), 'kind': kind, 'ai_advisory': advisory}
    p.update(extra)
    return p


def write_script(brief_path, out_path, duration=None):
    brief = _read_text(brief_path).strip()
    prompt = SCRIPT_DOCTRINE
    if duration:
        prompt += f'\nמשך יעד: {int(duration)} שניות.'
    prompt += '\n\nהבריף:\n' + brief
    reply = call_agy('text', prompt)
    parsed = extract_json(reply)
    result = {'script': parsed, 'raw': None if parsed else reply,
              'provenance': _provenance('script', False, brief=str(Path(brief_path).resolve()),
                                        brief_sha256=sha256_file(brief_path),
                                        parsed=bool(parsed))}
    write_new(out_path, result)
    return result


def analyze_video(media_path, kind, out_path, brief_path=None, context=None):
    if kind not in ('shot', 'master'):
        raise ValueError("kind must be 'shot' or 'master'")
    doctrine = ANALYZE_SHOT_DOCTRINE if kind == 'shot' else ANALYZE_MASTER_DOCTRINE
    prompt = doctrine
    if context:
        prompt += f'\n\nהקשר/מטרה: {context}'
    if brief_path:
        prompt += '\n\nהבריף:\n' + _read_text(brief_path).strip()
    reply = call_agy('video', prompt, media=media_path)
    parsed = extract_json(reply)
    result = {'analysis': parsed, 'raw': None if parsed else reply,
              'provenance': _provenance(f'analyze-{kind}', True,
                                        media=str(Path(media_path).resolve()),
                                        media_sha256=sha256_file(media_path),
                                        brief=str(Path(brief_path).resolve()) if brief_path else None,
                                        parsed=bool(parsed))}
    write_new(out_path, result)
    return result


CHECK_DOCTRINE = (
    'You are a literal visual QA inspector for a commercial. Watch the whole clip. For each listed item decide '
    'whether it is VISIBLY PRESENT anywhere in the clip (not implied, not stylistic intent). Answer ONLY with JSON: '
    '{"items":[{"item":"<the item text>","present":true|false,"confidence":0..1,"evidence":"one sentence: what and where in the frame/time"}],'
    '"notes":"anything else a producer should look at, or empty"}. Do not add prose outside the JSON.'
)


def check_shot(media_path, items, out_path, context=None):
    """Closed-question vision check of a generated shot against its exclusion list (advisory)."""
    items = [item.strip() for item in (items or []) if isinstance(item, str) and item.strip()]
    if not 1 <= len(items) <= 12:
        raise ValueError('check needs 1-12 items (the request avoid list, or --avoid entries)')
    prompt = CHECK_DOCTRINE + '\n\nItems to check:\n' + '\n'.join(f'- {item}' for item in items)
    if context:
        prompt += f'\n\nShot context: {context}'
    reply = call_agy('video', prompt, media=media_path)
    parsed = extract_json(reply)
    answers = parsed.get('items', []) if isinstance(parsed, dict) else []
    flagged = [a for a in answers if isinstance(a, dict) and a.get('present') is True]
    verdict = 'unparsed' if not isinstance(parsed, dict) or not answers else ('flagged' if flagged else 'clear')
    result = {'verdict': verdict, 'flagged': flagged, 'items': items, 'check': parsed, 'raw': None if parsed else reply,
              'provenance': _provenance('check-shot', True, media=str(Path(media_path).resolve()),
                                        media_sha256=sha256_file(media_path), parsed=bool(parsed))}
    write_new(out_path, result)
    return result


def items_from_request(request_path):
    request = load_json(request_path)
    items = request.get('avoid') or []
    if not items:
        raise ValueError(f'{Path(request_path).name} has no avoid list')
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    scr = sub.add_parser('script', help='brief -> structured story-first script (feeds the storyboard)')
    scr.add_argument('--brief', required=True)
    scr.add_argument('--out', required=True, help='output JSON path (must not exist)')
    scr.add_argument('--duration', type=int, help='target duration in seconds')
    ana = sub.add_parser('analyze', help='semantic video analysis of a rendered shot or the finished master')
    ana.add_argument('--media', required=True)
    ana.add_argument('--kind', required=True, choices=('shot', 'master'))
    ana.add_argument('--out', required=True, help='output JSON path (must not exist)')
    ana.add_argument('--brief', help='brief file to judge against')
    ana.add_argument('--context', help='shot purpose / free-text context')
    chk = sub.add_parser('check', help='closed yes/no vision check of a shot against its exclusion list')
    chk.add_argument('--media', required=True)
    chk.add_argument('--avoid', action='append', help='item that must not be visible (repeatable)')
    chk.add_argument('--request', help='provider request JSON whose avoid list is the checklist')
    chk.add_argument('--context', help='shot purpose / free-text context')
    chk.add_argument('--out', required=True, help='output JSON path (must not exist)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'script':
            r = write_script(args.brief, args.out, args.duration)
            s = r['script'] or {}
            print(json.dumps({'parsed': bool(r['script']), 'scenes': len(s.get('scenes', []) if isinstance(s, dict) else []),
                              'out': str(Path(args.out).resolve())}, ensure_ascii=False))
        elif args.command == 'check':
            items = list(args.avoid or []) + (items_from_request(args.request) if args.request else [])
            r = check_shot(args.media, items, args.out, args.context)
            print(json.dumps({'verdict': r['verdict'], 'flagged': [x.get('item') for x in r['flagged']],
                              'parsed': r['verdict'] != 'unparsed', 'ai_advisory': True,
                              'out': str(Path(args.out).resolve())}, ensure_ascii=False))
        else:
            r = analyze_video(args.media, args.kind, args.out, args.brief, args.context)
            a = r['analysis'] if isinstance(r['analysis'], dict) else {}
            print(json.dumps({'parsed': bool(r['analysis']), 'kind': args.kind,
                              'recommendation': a.get('recommendation'),
                              'fixes': len(a.get('fixes', [])), 'edit_blender': len(a.get('edit_blender', [])),
                              'edit_davinci': len(a.get('edit_davinci', [])), 'ai_advisory': True,
                              'out': str(Path(args.out).resolve())}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
