"""Validate executable direction and shot contracts without claiming aesthetic quality.

This tool performs local, deterministic checks only. It does not authorize provider
spend and it does not replace review of rendered pictures and sound.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


CAMERA_MODES = {
    'static', 'follow', 'reveal', 'emphasize', 'detach', 'transfer',
    'reorient', 'embody', 'transition',
}
SOURCE_KINDS = {
    'original-footage', 'existing-asset', 'codex-image', 'grok-video',
    'genspark-video', 'magnific-video', 'dzine-video', 'heygen-avatar', 'blender',
    'licensed-stock', 'client-supplied',
}
SOURCE_STATUSES = {'planned', 'styleframe-approved', 'ready', 'selected'}
PAID_MOTION_KINDS = {'grok-video', 'genspark-video', 'magnific-video', 'dzine-video', 'heygen-avatar'}
WEAK_ONLY = {
    'cinematic', 'premium', 'viral', 'beautiful', 'professional', 'epic',
    'dynamic', 'cool', 'luxury', 'קולנועי', 'פרימיום', 'ויראלי', 'יפה',
    'מקצועי', 'אפי', 'דינמי', 'יוקרתי',
}
PLACEHOLDERS = {'tbd', 'todo', 'unknown', 'later', 'n/a', '?', 'לא ידוע', 'אחר כך'}
PLACEHOLDER_PREFIXES = ('replace:', 'replace ', 'החלף:', 'החליפו:')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def _value(container, key, location, errors):
    if not isinstance(container, dict):
        errors.append(f'{location} must be an object')
        return None
    if key not in container:
        errors.append(f'{location}.{key} is required')
        return None
    return container[key]


def _text(container, key, location, errors, *, minimum=12):
    value = _value(container, key, location, errors)
    field = f'{location}.{key}'
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f'{field} must contain a concrete description of at least {minimum} characters')
        return None
    normalized = ' '.join(value.lower().strip().split()).strip('.!')
    if normalized in PLACEHOLDERS or normalized in WEAK_ONLY or normalized.startswith(PLACEHOLDER_PREFIXES):
        errors.append(f'{field} cannot be a placeholder or an aesthetic adjective by itself')
        return None
    if len(value.strip()) < minimum:
        errors.append(f'{field} must contain a concrete description of at least {minimum} characters')
        return None
    return value.strip()


def _integer(container, key, location, errors, minimum, maximum):
    value = _value(container, key, location, errors)
    field = f'{location}.{key}'
    if value is None:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        errors.append(f'{field} must be an integer in [{minimum}, {maximum}]')
        return None
    return value


def _enum(container, key, location, errors, choices):
    value = _value(container, key, location, errors)
    field = f'{location}.{key}'
    if value is None:
        return None
    if value not in choices:
        errors.append(f'{field} must be one of: {", ".join(sorted(choices))}')
        return None
    return value


def _object(container, key, location, errors):
    value = _value(container, key, location, errors)
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors.append(f'{location}.{key} must be an object')
        return {}
    return value


def _version(document, name, errors):
    if not isinstance(document, dict):
        errors.append(f'{name} must be a JSON object')
        return
    if document.get('version') != 1:
        errors.append(f'{name}.version must equal 1')


def validate_direction(direction):
    errors, warnings = [], []
    _version(direction, 'direction', errors)
    if not isinstance(direction, dict):
        return errors, warnings
    _text(direction, 'project', 'direction', errors, minimum=2)

    outcome = _object(direction, 'outcome', 'direction', errors)
    for field in ('audience', 'change', 'evidence', 'action'):
        _text(outcome, field, 'direction.outcome', errors)

    concept = _object(direction, 'concept', 'direction', errors)
    for field in ('governing_idea', 'point_of_view', 'hook', 'payoff'):
        _text(concept, field, 'direction.concept', errors)

    visual = _object(direction, 'visual_system', 'direction', errors)
    for field in ('attention', 'composition', 'camera', 'lighting', 'palette', 'materials', 'continuity'):
        _text(visual, field, 'direction.visual_system', errors)
    # Optional style exclusions: concrete things every generated image/clip must not show. The
    # generation models expose no negative-prompt parameter, so provider_jobs folds these into each
    # request through its `avoid` field; the gate only checks that they are concrete.
    exclusions = visual.get('exclusions', []) if isinstance(visual, dict) else []
    if not isinstance(exclusions, list):
        errors.append('direction.visual_system.exclusions must be a list of concrete visual exclusions')
    else:
        if len(exclusions) > 3:
            errors.append('direction.visual_system.exclusions lists at most 3 items; rewrite the rest as positive '
                          'style_constraints (what must be present), because a long "do not show" list primes the models')
        for index, item in enumerate(exclusions):
            location = f'direction.visual_system.exclusions[{index}]'
            if not isinstance(item, str) or len(item.strip()) < 3:
                errors.append(f'{location} must be a concrete phrase (e.g. "heavy shadows", "saturated neon colors")')
            elif item.strip().lower().startswith(PLACEHOLDER_PREFIXES) or item.strip().lower() in PLACEHOLDERS:
                errors.append(f'{location} is still a placeholder')
    constraints = visual.get('style_constraints', []) if isinstance(visual, dict) else []
    if not isinstance(constraints, list):
        errors.append('direction.visual_system.style_constraints must be a list of positive, concrete style rules')
    else:
        if len(constraints) > 12:
            errors.append('direction.visual_system.style_constraints lists at most 12 items')
        for index, item in enumerate(constraints):
            location = f'direction.visual_system.style_constraints[{index}]'
            if not isinstance(item, str) or len(item.strip()) < 3:
                errors.append(f'{location} must be a concrete phrase (e.g. "soft even daylight", "clean muted palette")')
            elif item.strip().lower().startswith(PLACEHOLDER_PREFIXES) or item.strip().lower() in PLACEHOLDERS:
                errors.append(f'{location} is still a placeholder')

    sound = _object(direction, 'sound_system', 'direction', errors)
    for field in ('voice', 'ambience', 'music', 'effects', 'silence'):
        _text(sound, field, 'direction.sound_system', errors)

    delivery = _value(direction, 'delivery', 'direction', errors)
    if delivery is not None:
        if not isinstance(delivery, list) or not delivery:
            errors.append('direction.delivery must be a nonempty list')
        else:
            seen = set()
            for index, target in enumerate(delivery):
                location = f'direction.delivery[{index}]'
                if not isinstance(target, dict):
                    errors.append(f'{location} must be an object')
                    continue
                name = _text(target, 'id', location, errors, minimum=1)
                if name in seen:
                    errors.append(f'{location}.id must be unique')
                seen.add(name)
                width = _integer(target, 'width', location, errors, 16, 8192)
                height = _integer(target, 'height', location, errors, 16, 8192)
                if width and width % 2:
                    errors.append(f'{location}.width must be even for video delivery')
                if height and height % 2:
                    errors.append(f'{location}.height must be even for video delivery')
                _text(target, 'platform', location, errors, minimum=2)
                _text(target, 'safe_areas', location, errors)

    decisions = direction.get('open_decisions', [])
    if not isinstance(decisions, list):
        errors.append('direction.open_decisions must be a list')
    else:
        for index, decision in enumerate(decisions):
            location = f'direction.open_decisions[{index}]'
            if not isinstance(decision, dict):
                errors.append(f'{location} must be an object')
                continue
            _text(decision, 'question', location, errors)
            _text(decision, 'owner', location, errors, minimum=2)
            if type(decision.get('blocking')) is not bool:
                errors.append(f'{location}.blocking must be true or false')
    return errors, warnings


def _validate_acceptance(items, location, errors):
    if not isinstance(items, list) or not items:
        errors.append(f'{location} must be a nonempty list of observable checks')
        return set()
    ids = set()
    for index, item in enumerate(items):
        current = f'{location}[{index}]'
        if not isinstance(item, dict):
            errors.append(f'{current} must be an object')
            continue
        identifier = _text(item, 'id', current, errors, minimum=1)
        _text(item, 'check', current, errors)
        _text(item, 'evidence', current, errors)
        if identifier in ids:
            errors.append(f'{current}.id must be unique within the shot')
        ids.add(identifier)
    return ids


def validate_shots(document, stage='styleframes'):
    errors, warnings = [], []
    _version(document, 'shots', errors)
    if not isinstance(document, dict):
        return errors, warnings, []
    fps = _integer(document, 'fps', 'shots', errors, 1, 120)
    shots = _value(document, 'shots', 'shots', errors)
    if not isinstance(shots, list) or not shots:
        errors.append('shots.shots must be a nonempty list')
        return errors, warnings, []
    ids, paid = set(), []
    for index, shot in enumerate(shots):
        location = f'shots.shots[{index}]'
        if not isinstance(shot, dict):
            errors.append(f'{location} must be an object')
            continue
        identifier = _text(shot, 'id', location, errors, minimum=1)
        if identifier in ids:
            errors.append(f'{location}.id must be unique')
        ids.add(identifier)
        for field in ('purpose', 'action', 'start_state', 'end_state'):
            _text(shot, field, location, errors)
        duration = _integer(shot, 'duration_frames', location, errors, 2, (fps or 120) * 120)

        attention = _object(shot, 'attention', location, errors)
        for field in ('start', 'path', 'end'):
            _text(attention, field, f'{location}.attention', errors)

        camera = _object(shot, 'camera', location, errors)
        mode = _enum(camera, 'mode', f'{location}.camera', errors, CAMERA_MODES)
        for field in ('reason', 'start_composition', 'end_composition', 'velocity'):
            _text(camera, field, f'{location}.camera', errors)
        settle = _integer(camera, 'settle_frames', f'{location}.camera', errors, 0, duration or 14400)
        handles = _integer(camera, 'handles_frames', f'{location}.camera', errors, 0, duration or 14400)
        if duration and settle is not None and handles is not None and settle + 2 * handles >= duration:
            errors.append(f'{location}.camera settle plus both handles must leave frames for the primary action')
        if mode == 'static' and camera.get('velocity', '').strip().lower() in {'linear', 'constant'}:
            errors.append(f'{location}.camera.velocity contradicts static mode')

        lighting = _object(shot, 'lighting', location, errors)
        for field in ('motivation', 'subject_priority', 'background', 'exposure_risk'):
            _text(lighting, field, f'{location}.lighting', errors)

        continuity = _object(shot, 'continuity', location, errors)
        for field in ('incoming', 'outgoing', 'screen_direction'):
            _text(continuity, field, f'{location}.continuity', errors)

        sound = _object(shot, 'sound', location, errors)
        for field in ('foreground', 'perspective', 'transition'):
            _text(sound, field, f'{location}.sound', errors)

        source = _object(shot, 'source', location, errors)
        kind = _enum(source, 'kind', f'{location}.source', errors, SOURCE_KINDS)
        status = _enum(source, 'status', f'{location}.source', errors, SOURCE_STATUSES)
        _text(source, 'description', f'{location}.source', errors)
        _validate_acceptance(shot.get('acceptance'), f'{location}.acceptance', errors)

        if kind in PAID_MOTION_KINDS:
            paid.append(identifier)
            generation = shot.get('generation')
            if stage in {'paid-motion', 'rough-cut'}:
                if not isinstance(generation, dict):
                    errors.append(f'{location}.generation is required before paid motion')
                else:
                    _text(generation, 'provider', f'{location}.generation', errors, minimum=2)
                    _text(generation, 'semantic_fingerprint', f'{location}.generation', errors, minimum=12)
                    _text(generation, 'approval_ref', f'{location}.generation', errors, minimum=4)
                    _integer(generation, 'max_attempts', f'{location}.generation', errors, 1, 20)
                if status not in {'styleframe-approved', 'ready', 'selected'}:
                    errors.append(f'{location}.source.status must record styleframe approval before paid motion')

        if stage == 'rough-cut' and status != 'selected':
            errors.append(f'{location}.source.status must be selected for rough-cut assembly')
    return errors, warnings, paid


def validate(direction, shots=None, stage='direction'):
    if stage not in {'direction', 'styleframes', 'paid-motion', 'rough-cut'}:
        raise ValueError('stage must be direction, styleframes, paid-motion or rough-cut')
    errors, warnings = validate_direction(direction)
    paid = []
    if stage != 'direction':
        if shots is None:
            errors.append(f'shots document is required for the {stage} stage')
        else:
            shot_errors, shot_warnings, paid = validate_shots(shots, stage)
            errors.extend(shot_errors)
            warnings.extend(shot_warnings)
    blocking = [item for item in direction.get('open_decisions', [])
                if isinstance(item, dict) and item.get('blocking') is True]
    if stage in {'paid-motion', 'rough-cut'} and blocking:
        errors.append(f'{len(blocking)} blocking direction decision(s) remain open')
    return {
        'version': 1,
        'stage': stage,
        'ready': not errors,
        'errors': errors,
        'warnings': warnings,
        'summary': {
            'shot_count': len(shots.get('shots', [])) if isinstance(shots, dict) else 0,
            'paid_motion_shots': paid,
            'blocking_open_decisions': len(blocking),
        },
        'limits': [
            'This report validates contract completeness, not artistic quality.',
            'Provider authorization and budget enforcement remain in provider_jobs.py.',
            'Rendered image and sound require timecoded human review.',
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--direction', required=True)
    parser.add_argument('--shots')
    parser.add_argument('--stage', choices=('direction', 'styleframes', 'paid-motion', 'rough-cut'), default='direction')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    direction = load_json(args.direction)
    shots = load_json(args.shots) if args.shots else None
    report = validate(direction, shots, args.stage)
    write_new(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ready'] else 2


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        sys.exit(main())
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
