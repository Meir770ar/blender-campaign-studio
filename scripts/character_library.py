"""Versioned local character cards, backed by existing verified HeyGen looks."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
from campaign_common import atomic_json, digest_json, lock, now, sha256_file
from studio import load_json, source_path
from heygen_bridge import cli

ROOT = Path(__file__).resolve().parent.parent
ENGINES = {'iv-fast', 'iv-quality', 'iv-video', 'v'}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise ValueError('Character and provider identifiers must contain letters, digits, underscores or hyphens')
    return value


def description(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValueError(f'{field} requires a concrete nonempty description')
    return value.strip()


def validate(card, base, connection):
    allowed = {'id', 'name', 'kind', 'heygen_group_id', 'looks', 'voice', 'continuity', 'references', 'consent_evidence'}
    if not isinstance(card, dict) or set(card) - allowed:
        raise ValueError('Unexpected character card fields')
    card = json.loads(json.dumps(card))
    identifier(card.get('id')); identifier(card.get('heygen_group_id'))
    description(card.get('name'), 'name')
    if card.get('kind') not in ('real-person', 'designed-character'):
        raise ValueError('kind must be real-person or designed-character')
    if card['kind'] == 'real-person':
        description(card.get('consent_evidence'), 'existing personal consent evidence')
    voice = card.get('voice', {})
    if not isinstance(voice, dict) or set(voice) != {'provider', 'id', 'language'} or voice.get('provider') not in ('heygen', 'elevenlabs'):
        raise ValueError('voice requires provider, id and language')
    identifier(voice['id']); description(voice['language'], 'voice language')
    continuity = card.get('continuity', {})
    if not isinstance(continuity, dict) or set(continuity) != {'wardrobe', 'lighting', 'framing', 'voice_direction'}:
        raise ValueError('continuity requires wardrobe, lighting, framing and voice_direction')
    for key, value in continuity.items():
        description(value, key)
    looks = card.get('looks', [])
    if not isinstance(looks, list) or not 1 <= len(looks) <= 100:
        raise ValueError('A character requires between one and 100 existing looks')
    seen = set()
    for look in looks:
        if not isinstance(look, dict) or set(look) - {'id', 'label', 'engine', 'motion_reference'}:
            raise ValueError('Each look requires id, label, engine and optional motion_reference')
        identifier(look.get('id')); description(look.get('label'), 'look label')
        if look.get('engine') not in ENGINES or look['id'] in seen:
            raise ValueError('Unsupported engine or duplicate look')
        seen.add(look['id'])
        args = ['avatar-engines', '--id', look['id']]
        if look.get('motion_reference'):
            args += ['--motion-reference', identifier(look['motion_reference'])]
        live = cli(connection, args)
        if live.get('groupId') != card['heygen_group_id'] or not any(e.get('engine') == look['engine'] and e.get('available') for e in live.get('engines', [])):
            raise ValueError('Look identity or engine eligibility does not match this character')
    refs = card.get('references', [])
    if not isinstance(refs, list) or len(refs) > 20:
        raise ValueError('references must be a list of at most 20 local approved images')
    card['references'] = []
    for value in refs:
        path = source_path(value, base)
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            raise ValueError('Character references must be supported local images')
        card['references'].append({'path': str(path), 'sha256': sha256_file(path)})
    return card


def save(path, library, connection):
    path, library = Path(path).resolve(), Path(library).resolve()
    card = validate(load_json(path), path.parent, connection)
    semantic = json.loads(json.dumps(card))
    for ref in semantic['references']:
        ref.pop('path')
    revision = digest_json(semantic)
    folder = library / card['id']
    folder.mkdir(parents=True, exist_ok=True)
    with lock(folder / '.lock'):
        for ref in card['references']:
            source = Path(ref['path'])
            target = folder / 'references' / (ref['sha256'] + source.suffix.lower())
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                with source.open('rb') as inp, target.open('xb') as out:
                    shutil.copyfileobj(inp, out)
            if sha256_file(target) != ref['sha256']:
                raise ValueError('Character reference changed during copying; current revision was not replaced')
            ref['path'] = str(target)
        revisions = folder / 'revisions'; revisions.mkdir(exist_ok=True)
        target = revisions / (revision + '.json')
        if not target.exists():
            atomic_json(target, {**card, 'revision': revision, 'verified_at': now(), 'generation_tested': False})
        atomic_json(folder / 'current.json', {'id': card['id'], 'revision': revision, 'card': str(target)})
    return {'id': card['id'], 'revision': revision, 'card': str(target), 'provider_mutated': False}


def read(library, character_id):
    folder = Path(library).resolve() / identifier(character_id)
    pointer = load_json(folder / 'current.json')
    revision = pointer.get('revision', '')
    if not re.fullmatch(r'[0-9a-f]{64}', revision):
        raise ValueError('Invalid character revision')
    return load_json(folder / 'revisions' / (revision + '.json'))


def make_request(card, look_id, audio, title, out):
    look = next((look for look in card['looks'] if look['id'] == look_id), None)
    if not look:
        raise ValueError('The requested look is not part of the selected character')
    audio = source_path(str(audio), Path.cwd())
    payload = {'provider': 'heygen', 'operation': 'create', 'character': {'id': card['id'], 'revision': card['revision']}, 'options': {'avatar': look_id, 'engine': look['engine'],
               'audio-json': str(audio), 'name': description(title, 'video title'), 'resolution': '1080p'}}
    if look.get('motion_reference'):
        payload['options']['motion-reference'] = look['motion_reference']
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    return {'request': str(out), 'character_id': card['id'], 'character_revision': card['revision'], 'submitted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library')
    sub = parser.add_subparsers(dest='command', required=True)
    q = sub.add_parser('save'); q.add_argument('--file', required=True)
    q = sub.add_parser('show'); q.add_argument('--id', required=True)
    sub.add_parser('list')
    q = sub.add_parser('request')
    for key in ('id', 'look', 'audio-json', 'title', 'out'):
        q.add_argument('--' + key, required=True)
    args = parser.parse_args()
    connection = load_json(ROOT / 'connections.json')['heygen']
    library = Path(args.library or connection['character_library'])
    if args.command == 'save':
        result = save(args.file, library, connection)
    elif args.command == 'show':
        result = read(library, args.id)
    elif args.command == 'list':
        result = [load_json(path) for path in sorted(library.glob('*/current.json'))] if library.exists() else []
    else:
        result = make_request(read(library, args.id), args.look, args.audio_json, args.title, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
