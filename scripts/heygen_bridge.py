"""Production adapter using the existing website CLI and its authoritative receipts."""
from pathlib import Path
import json
import subprocess
import re
from campaign_common import sha256_file, digest_json
from studio import source_path, load_json

OPERATIONS = {'create', 'speak', 'transcribe', 'create-from-prompt', 'render-workflow', 'render-text-draft',
              'avatar-photo-upload', 'avatar-footage-upload', 'avatar-photo-create', 'avatar-video-create', 'avatar-motion-suggest', 'avatar-consent-submit'}
FILES = {'text-file', 'audio-json', 'motion-file', 'file'}


def cli(connection, args, timeout=330):
    result = subprocess.run(['node', connection['cli_entry'], *args, '--json'], capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError('HeyGen CLI did not complete; inspect the saved CLI receipt before any retry')
    try:
        return json.loads(result.stdout.decode('utf-8-sig'))
    except (UnicodeError, ValueError):
        raise ValueError('HeyGen CLI returned no structured result; reconcile its local receipt') from None


def arguments(request):
    args = [request['operation']]
    for key, value in sorted(request['options'].items()):
        if value is False:
            continue
        args.append('--' + key)
        if value is not True:
            args.append(str(value))
    return args


def validate(request, base, connection):
    r = dict(request)
    if r.get('operation') not in OPERATIONS or not isinstance(r.get('options'), dict):
        raise ValueError('Choose a supported HeyGen production operation and an options object')
    options = dict(r['options'])
    if any(key in options for key in ('execute', 'allow-credits', 'out', 'json', 'help')):
        raise ValueError('Execution, credit permission and output paths belong to the production controller')
    if any(not isinstance(k, str) or not isinstance(v, (str, int, float, bool)) for k, v in options.items()):
        raise ValueError('HeyGen options must contain named scalar CLI arguments')
    files = []
    for key in FILES.intersection(options):
        path = source_path(options[key], base)
        files.append({'option': key, 'path': str(path), 'sha256': sha256_file(path)})
        options[key] = str(path)
    r.update(options=options, files=files)
    validate_character(r, connection)
    preview = cli(connection, arguments(r))
    if not preview.get('preview') or not preview.get('fingerprint'):
        raise ValueError('HeyGen operation did not return a preview with a submission fingerprint')
    r['cli_fingerprint'] = preview['fingerprint']
    r['may_consume_credits'] = bool(preview.get('mayConsumeCredits'))
    return r


def preflight(request, connection):
    validate_character(request, connection)
    for ref in request['files']:
        if sha256_file(ref['path']) != ref['sha256']:
            raise ValueError('HeyGen input changed after approval')
    preview = cli(connection, arguments(request))
    if preview.get('fingerprint') != request['cli_fingerprint']:
        raise ValueError('HeyGen workspace or semantic request changed after approval')


def validate_character(request, connection):
    binding = request.get('character')
    if binding is None:
        return
    if not isinstance(binding, dict) or set(binding) != {'id', 'revision'} or \
       not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', str(binding.get('id', ''))) or \
       not re.fullmatch(r'[a-f0-9]{64}', str(binding.get('revision', ''))):
        raise ValueError('Character binding requires its ID and exact revision')
    root = connection.get('character_library')
    if not root:
        raise ValueError('The shared character library is not configured')
    card = load_json(Path(root) / binding['id'] / 'revisions' / (binding['revision'] + '.json'))
    semantic = {k: v for k, v in card.items() if k not in ('revision', 'verified_at', 'generation_tested')}
    semantic = json.loads(json.dumps(semantic))
    for ref in semantic.get('references', []):
        ref.pop('path')
    if digest_json(semantic) != binding['revision']:
        raise ValueError('Character revision was altered; do not submit an unreviewed identity')
    options = request['options']
    look = next((x for x in card['looks'] if x['id'] == options.get('avatar')), None)
    if request['operation'] != 'create' or not look or look['engine'] != options.get('engine', 'iv-fast') or \
       look.get('motion_reference') != options.get('motion-reference'):
        raise ValueError('HeyGen request differs from the approved character look/engine')


def submit(request, connection):
    args = arguments(request) + ['--execute']
    if request['may_consume_credits']:
        args.append('--allow-credits')
    output = cli(connection, args, timeout=1800)
    receipt = cli(connection, ['job', '--id', request['cli_fingerprint']])
    return {'cli_output': output, 'cli_receipt': receipt}


def status(request, connection):
    receipt = cli(connection, ['job', '--id', request['cli_fingerprint']])
    result = receipt.get('result') or {}
    response = {'cli_receipt': receipt}
    if result.get('video_id'):
        response['video'] = cli(connection, ['video', '--id', result['video_id']])
    elif result.get('group_id'):
        response['avatar'] = cli(connection, ['avatar-group', '--id', result['group_id']])
    elif result.get('workflow_id'):
        response['workflow'] = cli(connection, ['avatar-workflow', '--id', result['workflow_id']])
    return response
