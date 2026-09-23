"""Staged, single-attempt provider jobs. No credentials are written to jobs or stdout."""
from __future__ import annotations
import argparse
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from campaign_common import atomic_json, digest_json, lock, now, sha256_file
from studio import load_json, number, source_path
import grok_contract
import heygen_bridge

ROOT = Path(__file__).resolve().parent.parent


def validate_request(value, base, config):
    if not isinstance(value, dict):
        raise ValueError('Provider request must be a JSON object')
    r = dict(value)
    provider = r.get('provider')
    if provider not in ('images', 'suno', 'grok', 'genspark', 'elevenlabs', 'heygen'):
        raise ValueError('provider must be images, suno, grok, genspark, elevenlabs or heygen')
    allowed = {
        'images': {'prompt', 'references', 'avoid', 'style_constraints'},
        'suno': {'style', 'lyrics', 'title', 'instrumental', 'extend_clip_id', 'extend_at_seconds'},
        'grok': {'prompt', 'references', 'duration_seconds', 'aspect_ratio', 'resolution', 'audio', 'model', 'mode', 'video_url', 'source_duration_seconds', 'avoid', 'style_constraints'},
        'genspark': {'prompt', 'references', 'duration_seconds', 'aspect_ratio', 'resolution', 'audio', 'fallback_for', 'avoid', 'style_constraints'},
        'elevenlabs': {'text', 'stability', 'similarity_boost', 'style', 'speed'},
        'heygen': {'operation', 'options', 'character'},
    }[provider] | {'provider'}
    if set(r) - allowed:
        raise ValueError('Unknown request fields: ' + ', '.join(sorted(set(r) - allowed)))
    for field in ({'images': ['prompt'], 'grok': ['prompt'], 'genspark': ['prompt'], 'suno': ['style'], 'elevenlabs': ['text'], 'heygen': []}[provider]):
        if not isinstance(r.get(field), str) or not r[field].strip():
            raise ValueError(f'{field} is required')
    if 'avoid' in r or 'style_constraints' in r:
        r['prompt'] = fold_style(r['prompt'], r.get('style_constraints'), r.get('avoid'))
        if 'style_constraints' in r:
            r['style_constraints'] = [item.strip() for item in r['style_constraints']]
        if 'avoid' in r:
            r['avoid'] = [item.strip() for item in r['avoid']]
    if provider == 'grok':
        r = grok_contract.validate(r, base, config[provider])
    if provider == 'heygen':
        r = heygen_bridge.validate(r, base, config[provider])
    if provider in ('images', 'genspark'):
        refs = r.get('references', [])
        if not isinstance(refs, list) or len(refs) > (5 if provider == 'images' else 1):
            raise ValueError('Too many references for the selected route')
        r['references'] = []
        for value in refs:
            path = source_path(value, base)
            if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
                raise ValueError('Reference must be a supported image')
            r['references'].append({'path': str(path), 'sha256': sha256_file(path)})
    if provider == 'genspark':
        duration = r.get('duration_seconds', 6)
        if type(duration) is not int or not 1 <= duration <= 15:
            raise ValueError('duration_seconds must be an integer from 1 to 15; confirm live capabilities')
        r['duration_seconds'] = duration
        r.setdefault('aspect_ratio', '16:9')
        r.setdefault('resolution', '720P')
        r.setdefault('audio', False)
        if r['aspect_ratio'] not in ('16:9', '9:16', '1:1') or r['resolution'] not in ('480P', '720P', '1080P'):
            raise ValueError('Unsupported aspect ratio or resolution for the subscription preset')
        if type(r['audio']) is not bool:
            raise ValueError('audio must be boolean')
    if provider == 'genspark':
        if r.get('fallback_for') is None:
            # Primary route (2026-09-23): Grok Imagine on Genspark credits, text-to-video or one first
            # frame. The CLI documents 1080P output for text-to-video; a first frame keeps 720P.
            if len(r['references']) > 1:
                raise ValueError('A Genspark request takes at most one first-frame image')
            if r['resolution'] == '1080P' and r['references']:
                raise ValueError('1080P on Genspark is text-to-video only; with a first frame use 720P')
            r['mode'] = 'image-to-video' if r['references'] else 'text-to-video'
        else:
            if len(r['references']) != 1:
                raise ValueError('Genspark fallback requires one preserved first-frame image')
            if r['resolution'] == '1080P':
                raise ValueError('A Genspark fallback keeps the original shot contract; 1080P is not part of it')
            parent = source_path(r.get('fallback_for'), base)
            original = load_json(parent)
            r['fallback_for'] = {'path': str(parent), 'id': original['id']}
            validate_fallback(r)
            r['mode'] = 'fallback'
    if provider == 'suno':
        r.setdefault('instrumental', True)
        r.setdefault('lyrics', '')
        r.setdefault('title', '')
        if type(r['instrumental']) is not bool or not all(isinstance(r[k], str) for k in ('lyrics', 'title')):
            raise ValueError('Invalid Suno lyrics/title/instrumental')
        if r['instrumental'] and r['lyrics'].strip():
            raise ValueError('Instrumental request cannot contain lyrics')
        if ('extend_clip_id' in r) != ('extend_at_seconds' in r):
            raise ValueError('A Suno extension needs both extend_clip_id and extend_at_seconds')
        if 'extend_clip_id' in r:
            # Extension inherits key and tempo from the source clip: the way to change character at a
            # planned second without gluing two unrelated tracks.
            if not isinstance(r['extend_clip_id'], str) or not re.fullmatch(r'[A-Za-z0-9-]{8,}', r['extend_clip_id']):
                raise ValueError('extend_clip_id must be the id of an existing Suno clip')
            number(r['extend_at_seconds'], 'extend_at_seconds', 1, 600)
    if provider == 'elevenlabs':
        if len(r['text']) > 4500 or '<break' in r['text'].lower():
            raise ValueError('Split narration below 4500 characters; v3 uses delivery tags, not SSML breaks')
        for key, default, lo, hi in [('stability', .5, 0, 1), ('similarity_boost', .75, 0, 1),
                                    ('style', 0, 0, 1), ('speed', 1, .7, 1.2)]:
            r[key] = number(r.get(key, default), key, lo, hi)
        if r['stability'] not in (0, .5, 1):
            raise ValueError('eleven_v3 stability must be 0, 0.5 or 1')
    # Secret values are never part of this binding; routes/models/account locations are.
    return {'request': r, 'connection': config[provider], 'version': 1}


STYLE_MARKER = '\n\nStyle constraints: '
AVOID_MARKER = '\n\nAvoid: '


def _phrases(value, name, maximum):
    if not isinstance(value, list) or not value or len(value) > maximum or \
            any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f'{name} must be a list of 1-{maximum} nonempty phrases')
    return [item.strip() for item in value]


def fold_style(prompt, constraints, avoid):
    """No generation model here has a negative-prompt parameter, and a bare "do not show X" clause
    primes some models toward X. Style rules therefore travel as positive constraints (what must be
    present) with at most three short exclusions, folded into the prompt once so every shot of a
    series carries the same rules and the job identity covers them."""
    if STYLE_MARKER.strip() in prompt or AVOID_MARKER.strip() in prompt:
        raise ValueError('prompt already contains a style/avoid clause; pass them only through style_constraints and avoid')
    text = prompt.rstrip()
    if constraints is not None:
        text += STYLE_MARKER + '; '.join(_phrases(constraints, 'style_constraints', 12)) + '.'
    if avoid is not None:
        text += AVOID_MARKER + '; '.join(_phrases(avoid, 'avoid', 3)) + '.'
    return text


def prepare(request_path, jobs, config):
    spec = validate_request(load_json(request_path), Path(request_path).resolve().parent, config)
    semantic = json.loads(json.dumps(spec))
    for ref in semantic['request'].get('references', []):
        ref.pop('path')  # Same bytes moved locally must not become a fresh paid request.
    for ref in semantic['request'].get('files', []):
        ref.pop('path')
        semantic['request']['options'][ref['option']] = {'sha256': ref['sha256']}
    if semantic['request'].get('fallback_for'):
        semantic['request']['fallback_for'].pop('path')
    job_id = digest_json(semantic)
    folder = Path(jobs).resolve() / job_id
    folder.mkdir(parents=True, exist_ok=True)
    with lock(folder / '.lock'):
        path = folder / 'job.json'
        if not path.exists():
            atomic_json(path, {'id': job_id, 'created_at': now(), 'state': 'prepared', **spec})
    return folder


def authorize(folder, evidence, limit, unit):
    if not evidence.strip() or not unit.strip():
        raise ValueError('Record the current task user approval and its cost/quota unit')
    number(limit, 'limit', 0, 1000000)
    folder = Path(folder)
    with lock(folder / '.lock'):
        job = load_json(folder / 'job.json')
        if job['state'] != 'prepared':
            raise ValueError('Only an unsubmitted request can receive approval')
        job['approval'] = {'request_id': job['id'], 'evidence': evidence, 'limit': limit,
                           'unit': unit, 'max_submissions': 1, 'at': now()}
        atomic_json(folder / 'job.json', job)


def batches_root(jobs_root):
    return Path(jobs_root).resolve() / '_batches'


def authorize_batch(jobs_root, job_ids, evidence, limit, unit, per_job=None, pilot=None):
    """One current-task approval that covers several prepared jobs of the same provider under a
    shared usage cap (a 35-shot campaign is one decision, not 35). Each job still submits once;
    execute() adds the running total of the batch to its own checks. With `pilot`, only the first
    N jobs (in the listed order) may execute until batch-release records the pilot review: one
    approval, a circuit breaker in the middle."""
    if not evidence.strip() or not unit.strip():
        raise ValueError('Record the current task user approval and its cost/quota unit')
    number(limit, 'limit', 0, 1000000)
    if per_job is not None:
        number(per_job, 'per_job', 0, limit)
    ids = list(dict.fromkeys(job_ids))
    if len(ids) < 2:
        raise ValueError('A batch approval covers at least two prepared jobs; use approve for a single job')
    if pilot is not None and (type(pilot) is not int or not 1 <= pilot < len(ids)):
        raise ValueError('pilot must be an integer from 1 to one less than the number of jobs')
    root = Path(jobs_root).resolve()
    providers = set()
    for job_id in ids:
        folder = root / job_id
        if not (folder / 'job.json').is_file():
            raise ValueError(f'{job_id}: no prepared job under {root}')
        job = load_json(folder / 'job.json')
        if job['state'] != 'prepared' or job.get('approval'):
            raise ValueError(f'{job_id}: only an unapproved, unsubmitted request can join a batch')
        providers.add(job['request']['provider'])
    if len(providers) != 1:
        raise ValueError('A batch approval covers one provider so its usage unit is comparable across jobs')
    batch_id = digest_json({'jobs': sorted(ids), 'evidence': evidence, 'limit': limit, 'unit': unit})[:24]
    record = batches_root(root) / f'{batch_id}.json'
    if record.exists():
        raise ValueError('This batch approval already exists; inspect it with batch-status instead of re-approving')
    record.parent.mkdir(parents=True, exist_ok=True)
    per_job_limit = per_job if per_job is not None else limit
    atomic_json(record, {'id': batch_id, 'provider': providers.pop(), 'jobs': ids, 'evidence': evidence,
                         'limit': limit, 'unit': unit, 'per_job_limit': per_job_limit, 'at': now(),
                         'pilot': pilot, 'released': pilot is None})
    for job_id in ids:
        folder = root / job_id
        with lock(folder / '.lock'):
            job = load_json(folder / 'job.json')
            if job['state'] != 'prepared' or job.get('approval'):
                raise ValueError(f'{job_id}: state changed while approving the batch; inspect it and re-approve the rest individually')
            job['approval'] = {'request_id': job['id'], 'evidence': evidence, 'limit': per_job_limit, 'unit': unit,
                               'max_submissions': 1, 'batch': batch_id, 'batch_limit': limit, 'at': now()}
            atomic_json(folder / 'job.json', job)
    return {'batch': batch_id, 'jobs': len(ids), 'limit': limit, 'unit': unit, 'per_job_limit': per_job_limit,
            'pilot': pilot, 'record': str(record)}


def batch_release(jobs_root, batch_id, evidence):
    """Record the pilot review and release the remaining jobs of a piloted batch."""
    if not evidence.strip():
        raise ValueError('Record what was reviewed in the pilot (what passed, what changed) before releasing the rest')
    root = Path(jobs_root).resolve()
    with lock(batches_root(root) / f'{batch_id}.lock'):
        record = load_json(batches_root(root) / f'{batch_id}.json')
        if not record.get('pilot'):
            raise ValueError('This batch has no pilot; nothing to release')
        if record.get('released'):
            raise ValueError('This batch was already released')
        pending = []
        for job_id in record['jobs'][:record['pilot']]:
            path = root / job_id / 'job.json'
            job = load_json(path) if path.is_file() else {}
            if not job.get('attempted_at'):
                pending.append(job_id)
        if pending:
            raise ValueError('Pilot jobs not yet attempted: ' + ', '.join(pending) + '; execute and review them first')
        record.update(released=True, release_evidence=evidence, released_at=now())
        atomic_json(batches_root(root) / f'{batch_id}.json', record)
    return {'batch': batch_id, 'released': True, 'remaining_jobs': record['jobs'][record['pilot']:]}


def batch_usage(jobs_root, batch_id, exclude=None):
    record = load_json(batches_root(jobs_root) / f'{batch_id}.json')
    rows, spent = [], 0.0
    for job_id in record['jobs']:
        path = Path(jobs_root).resolve() / job_id / 'job.json'
        job = load_json(path) if path.is_file() else {'id': job_id, 'state': 'missing'}
        attempted = bool(job.get('attempted_at'))
        usage = float(job.get('estimated_usage', 0) or 0) if attempted else 0.0
        if attempted and job_id != exclude:
            spent += usage
        rows.append({'id': job_id, 'state': job.get('state'), 'attempted': attempted,
                     'estimated_usage': usage if attempted else None})
    return record, rows, spent


def batch_status(jobs_root, batch_id):
    record, rows, spent = batch_usage(jobs_root, batch_id)
    return {'batch': record['id'], 'provider': record['provider'], 'unit': record['unit'], 'limit': record['limit'],
            'pilot': record.get('pilot'), 'released': record.get('released', True),
            'spent_estimated': spent, 'remaining_estimated': record['limit'] - spent, 'jobs': rows,
            'note': "estimates recorded at execute time; the provider's own receipts remain the billing truth"}


@contextmanager
def batch_guard(folder, approval, estimated_usage):
    """Hold the batch ledger lock while checking the running total and persisting this attempt."""
    batch_id = approval.get('batch')
    if not batch_id:
        yield
        return
    jobs_root = Path(folder).resolve().parent
    with lock(batches_root(jobs_root) / f'{batch_id}.lock'):
        record, _, spent = batch_usage(jobs_root, batch_id, exclude=Path(folder).name)
        if record.get('pilot') and not record.get('released') and Path(folder).name not in record['jobs'][:record['pilot']]:
            raise ValueError(f'Batch {batch_id} pilot: only its first {record["pilot"]} jobs may execute until '
                             'batch-release records the pilot review; no generation submitted')
        if spent + estimated_usage > float(record['limit']) + 1e-9:
            raise ValueError(f'Batch {batch_id} would exceed its approved cap: {spent:g} already estimated + '
                             f'{estimated_usage:g} > {record["limit"]:g} {record["unit"]}; no generation submitted')
        yield


def secret(config):
    key = os.environ.get('ELEVENLABS_API_KEY')
    if not key:
        for line in Path(config['env_file']).read_text(encoding='utf-8-sig').splitlines():
            match = re.match(r'^\s*(?:export\s+)?ELEVENLABS_API_KEY\s*=\s*(.*?)\s*$', line)
            if match:
                key = match[1].strip('"\'')
                break
    if not key:
        raise ValueError('ElevenLabs key missing in configured environment')
    return key


def eleven_http(config, endpoint, body=None):
    req = urllib.request.Request('https://api.elevenlabs.io/v1/' + endpoint,
          data=json.dumps(body).encode() if body is not None else None,
          headers={'xi-api-key': secret(config), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ValueError(f'ElevenLabs HTTP {error.code}; response body withheld') from None


def suno(command, config, folder=None, payload=None):
    cmd = ['node', str(ROOT / 'scripts/suno_bridge.mjs'), command, config['client_module']]
    if payload is not None:
        target = folder / ('suno-' + command + '.json')
        atomic_json(target, payload)
        cmd.append(str(target))
    result = subprocess.run(cmd, capture_output=True, timeout=90)
    try:
        return json.loads(result.stdout.decode('utf-8').strip())
    except (ValueError, UnicodeError):
        raise ValueError('Suno client returned no structured result; inspect login without resubmitting') from None


def ssh(config, command, data=None, timeout=45):
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                             config['ssh_host'], shlex.join(command)], input=data, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError(f'Grok gateway transport failed ({result.returncode}); response withheld')
    return result.stdout


def grok_metadata(config):
    code = """import fs from 'node:fs';
const c=JSON.parse(fs.readFileSync('/home/node/.openclaw/openclaw.json','utf8'));
const p=JSON.parse(fs.readFileSync('/home/node/.openclaw/auth-profiles.json','utf8'));
const files=fs.readdirSync('/app/dist').filter(x=>/^agent-scope-config-.*\\.js$/.test(x));
if(files.length!==1)throw new Error('Agent scope module must be reverified after runtime upgrade');
const scope=await import('/app/dist/'+files[0]);
const named=name=>Object.values(scope).find(x=>typeof x==='function'&&x.name===name);
const resolveAgentDir=named('resolveAgentDir'), resolveDefaultAgentDir=named('resolveDefaultAgentDir');
if(!resolveAgentDir||!resolveDefaultAgentDir)throw new Error('Native agent scope exports changed');
const agentDir=resolveAgentDir(c,process.argv[1]);
const defaultAgentDir=resolveDefaultAgentDir(c);
const profiles=p.profiles||{};
const profileId=p.lastGood?.xai || (profiles['xai:default']?'xai:default':Object.keys(profiles).find(id=>profiles[id]?.provider==='xai'&&profiles[id]?.type==='oauth'));
const active=profiles[profileId];
const oauth=active?.provider==='xai'&&active?.type==='oauth';
const hasAccess=typeof active?.access==='string'&&active.access.trim().length>0;
const hasRefresh=typeof active?.refresh==='string'&&active.refresh.trim().length>0;
const refreshNeeded=!hasAccess||!Number.isFinite(active?.expires)||active.expires<=Date.now()+300000;
const providerSource=fs.readFileSync('/app/dist/video-generation-provider-PMWf4yep.js','utf8');
const campaignContract=providerSource.match(/const CAMPAIGN_XAI_CONTRACT = "([^"]+)"/)?.[1];
console.log(JSON.stringify({model:c.agents?.defaults?.videoGenerationModel,
campaign_contract:campaignContract||null,
oauth,oauth_usable_or_refreshable:Boolean(oauth&&(!refreshNeeded||hasRefresh)),
selected_by_last_good:Boolean(p.lastGood?.xai&&active),refresh_available:hasRefresh,
refresh_needed:refreshNeeded,refresh_handling:'openclaw_native_resolver',
agent_dir:agentDir,agent_context_matches:agentDir===defaultAgentDir,
apiCredential:Object.values(profiles).some(x=>x.provider==='xai'&&x.type!=='oauth')||Boolean(process.env.XAI_API_KEY||c.models?.providers?.xai?.apiKey||c.env?.XAI_API_KEY||c.env?.vars?.XAI_API_KEY)}));"""
    return json.loads(ssh(config, ['docker', 'exec', '-u', 'node', config['container'], 'node', '--input-type=module', '-e', code, config['agent']]))


def require_grok_subscription_context(meta, config):
    model = meta.get('model') or {}
    if not meta.get('oauth') or not meta.get('oauth_usable_or_refreshable') or meta.get('apiCredential') or model.get('primary') != config['model'] or model.get('fallbacks'):
        raise ValueError('Subscription-only route is not verified: inspect selected OAuth profile/model/fallback configuration')
    # The installed gateway's provider resolver supplies its default agentDir. Never let
    # a campaign silently resolve credentials in a different agent context.
    if not meta.get('agent_dir') or not meta.get('agent_context_matches'):
        raise ValueError('Grok agentDir differs from the native provider resolver context; no generation submitted')


def gateway(config, job_id, args):
    params = {'name': 'video_generate', 'agentId': config['agent'],
              'sessionKey': f'agent:{config["agent"]}:campaign-{job_id}', 'args': args}
    if args['action'] == 'generate':
        params['idempotencyKey'] = 'campaign-' + job_id
    result = ssh(config, ['docker', 'exec', '-u', 'node', config['container'], 'openclaw',
              'gateway', 'call', 'tools.invoke', '--json', '--params', json.dumps(params), '--timeout', '20000'], timeout=35)
    return json.loads(result)


def words_from_alignment(alignment):
    chars = alignment.get('characters', [])
    starts = alignment.get('character_start_times_seconds', [])
    ends = alignment.get('character_end_times_seconds', [])
    if not chars or not len(chars) == len(starts) == len(ends):
        raise ValueError('Missing or inconsistent narration alignment')
    words, current = [], None
    previous = 0
    for char, start, end in zip(chars, starts, ends):
        number(start, 'word start', 0, 36000)
        number(end, 'word end', start, 36000)
        if start < previous - .05:
            raise ValueError('Narration alignment is not ordered')
        previous = start
        if char.isspace():
            if current:
                words.append(current)
                current = None
        elif current:
            current['word'] += char
            current['end'] = end
        else:
            current = {'word': char, 'start': start, 'end': end}
    if current:
        words.append(current)
    return words


def probe(provider, config):
    c = config[provider]
    if provider == 'images':
        return {'route': 'codex_builtin', 'agent_must_verify_tool_available': True, 'generation_tested': False}
    if provider == 'genspark':
        env = {**os.environ, 'GSK_NO_AUTO_UPDATE': '1'}
        result = subprocess.run(['node', c['cli_entry'], '--no-input', 'login-info'],
                                capture_output=True, timeout=45, env=env)
        try:
            response = json.loads(result.stdout.decode('utf-8'))
            data = response.get('data') or {}
        except (ValueError, UnicodeError):
            return {'route': c['route'], 'cli_authenticated': False, 'browser_verification_required': True,
                    'generation_tested': False}
        return {'route': c['route'], 'cli_authenticated': response.get('status') == 'ok',
                'cli_plan': data.get('plan'), 'cli_credit_balance': data.get('credit_balance'),
                'browser_verification_required': c['route'] == 'browser_existing_account' or not data.get('credit_balance'), 'generation_tested': False,
                'note': 'CLI credit balance does not establish website credit availability; verify the signed-in website.'}
    if provider == 'suno':
        return suno('probe', c)
    if provider == 'elevenlabs':
        voice = eleven_http(c, 'voices/' + c['voice_id'])
        return {'voice_accessible': voice.get('voice_id') == c['voice_id'], 'generation_tested': False}
    if provider == 'heygen':
        return {'route': c['route'], 'subscription': heygen_bridge.cli(c, ['status']),
                'generation_limits': heygen_bridge.cli(c, ['generation-limits']), 'generation_tested': False}
    meta = grok_metadata(c)
    result = gateway(c, 'probe', {'action': 'list'})
    providers = result.get('output', {}).get('details', {}).get('providers', [])
    xai = next((p for p in providers if p.get('id') == 'xai'), {})
    meta['tool_available'] = bool(result.get('ok'))
    meta['capability_configured'] = xai.get('configured')
    meta['api_key_discovery_is_not_oauth_health'] = True
    try:
        require_grok_subscription_context(meta, c)
        meta['connection_verified'] = bool(result.get('ok') and xai)
    except ValueError:
        meta['connection_verified'] = False
    meta['capabilities'] = xai.get('capabilities', {})
    meta['native_expansion_active'] = meta.get('campaign_contract') == grok_contract.CONTRACT and \
        '1080P' in meta['capabilities'].get('generate', {}).get('resolutions', [])
    meta['ready_to_submit'] = meta['connection_verified'] and (not c.get('native_contract') or meta['native_expansion_active'])
    meta['generation_tested'] = False
    return meta


def execute(folder, config, estimated_usage):
    folder = Path(folder).resolve()
    with lock(folder / '.lock'):
        job = load_json(folder / 'job.json')
        r, c = job['request'], job['connection']
        provider = r['provider']
        safe_preflight_retry = job['state'] == 'blocked' and job.get('provider_result', {}).get('submitted') is False
        if job['state'] != 'prepared' and not safe_preflight_retry:
            raise ValueError('Job already attempted. Use status/collect; never resubmit an unknown job')
        if c != config[provider]:
            raise ValueError('Connection changed; prepare and review a new request')
        approval = job.get('approval', {})
        if approval.get('request_id') != job['id']:
            raise ValueError('Exact request has no current-task approval')
        number(estimated_usage, 'estimated_usage', 0, approval['limit'])
        for ref in r.get('references', []):
            if sha256_file(ref['path']) != ref['sha256']:
                raise ValueError('Reference changed after approval')
        if provider == 'heygen':
            heygen_bridge.preflight(r, c)
        if provider == 'genspark':
            if r.get('fallback_for'):
                validate_fallback(r)
            if c['route'] == 'existing_cli':
                check = probe('genspark', config)
                if not check.get('cli_authenticated') or not isinstance(check.get('cli_credit_balance'), (int, float)) or check['cli_credit_balance'] <= 0:
                    raise ValueError('Genspark CLI has no verified usable credits; no generation submitted')
                job['cli_preflight'] = {**check, 'at': now()}
            elif c['route'] == 'browser_existing_account':
                check = job.get('browser_preflight', {})
                from datetime import datetime, timezone
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(check['at'])).total_seconds() if check.get('at') else float('inf')
                if not 0 <= age <= 900 or check.get('credit_balance', 0) <= 0 or not check.get('evidence'):
                    raise ValueError('Verify current Genspark website account/balance with browser-check before execution')
            else:
                raise ValueError('Unsupported Genspark transport')
        if provider == 'grok':
            meta = grok_metadata(c)
            require_grok_subscription_context(meta, c)
            capability = gateway(c, 'probe', {'action': 'list'})
            providers = capability.get('output', {}).get('details', {}).get('providers', [])
            xai = next((p for p in providers if p.get('id') == 'xai'), {})
            if not capability.get('ok') or not xai:
                raise ValueError('Grok video tool/provider is unavailable; no generation submitted')
            grok_contract.ensure_capability(r, xai, meta)
            input_check = grok_contract.inspect_video_input(r)
            if input_check:
                job['input_video_check'] = input_check
        with batch_guard(folder, approval, estimated_usage):
            job.update(state='submitting', attempted_at=now(), estimated_usage=estimated_usage)
            atomic_json(folder / 'job.json', job)  # Persist before transport; a crash cannot cause a repeat.
        try:
            if provider == 'images':
                args = {'prompt': r['prompt']}
                if r['references']:
                    args['referenced_image_paths'] = [x['path'] for x in r['references']]
                job['tool_request'] = {'tool': 'image_gen.imagegen', 'args': args}
                job['state'] = 'awaiting_agent_tool'
            elif provider == 'genspark':
                if c['route'] == 'existing_cli':
                    payload = {'query': r['prompt'], 'model': c['model'],
                               'image_urls': [ref['path'] for ref in r['references']],
                               'duration': r['duration_seconds'], 'aspect_ratio': r['aspect_ratio'],
                               'video_size': r['resolution'].lower(), 'audio_enable': r['audio'],
                               'reference_mode': False, 'file_name': 'campaign-' + job['id'] + '.mp4'}
                    args_file = folder / 'genspark-submit.json'
                    atomic_json(args_file, payload)
                    env = {**os.environ, 'GSK_NO_AUTO_UPDATE': '1'}
                    # Preserve complete receipts before attempting downloads. A timeout stays unknown.
                    result = subprocess.run(['node', c['cli_entry'], '--no-input', 'video', '--args-file', str(args_file)],
                                            capture_output=True, timeout=1800, env=env)
                    (folder / 'genspark-response.json').write_bytes(result.stdout)
                    response = json.loads(result.stdout.decode('utf-8'))
                    job['provider_result'] = response
                    job['state'] = 'failed' if response.get('status') == 'error' else 'submitted'
                else:
                    job['tool_request'] = {'tool': 'cua_repl', 'workflow': 'genspark-existing-account-video',
                    'url': c['browser_url'], 'model': c['model'], 'prompt': r['prompt'],
                    'first_frame_path': r['references'][0]['path'] if r['references'] else None, 'duration_seconds': r['duration_seconds'],
                    'aspect_ratio': r['aspect_ratio'], 'resolution': r['resolution'], 'audio': r['audio'],
                    'count': 1, 'auto_prompt': False,
                    'receipt_command': 'record-browser', 'collection_command': 'register'}
                    job['state'] = 'awaiting_agent_tool'
            elif provider == 'suno':
                result = suno('submit', c, folder, {**r, 'model': c['model']})
                job['provider_result'] = result
                job['state'] = 'submitted' if result.get('ids') else 'blocked' if result.get('submitted') is False else 'unknown'
            elif provider == 'heygen':
                job['provider_result'] = heygen_bridge.submit(r, c)
                job['state'] = 'submitted'
            elif provider == 'grok':
                def upload_reference(ref):
                    remote = grok_contract.remote_reference_path(ref)
                    # Exact controlled destination; no prompt or user path enters a shell program.
                    ssh(c, ['docker', 'exec', '-i', '-u', 'node', c['container'], 'node', '-e',
                        "require('fs').writeFileSync(process.argv[1],require('fs').readFileSync(0))", remote],
                        Path(ref['path']).read_bytes())
                    return remote
                args = grok_contract.arguments(r, c, job['id'], upload_reference)
                job['provider_result'] = gateway(c, job['id'], args)
                job['state'] = 'submitted' if job['provider_result'].get('ok') else 'unknown'
            else:
                result = eleven_http(c, 'text-to-speech/' + c['voice_id'] + '/with-timestamps?output_format=mp3_44100_128',
                     {'text': r['text'], 'model_id': c['model'],
                      'voice_settings': {k: r[k] for k in ('stability', 'similarity_boost', 'style', 'speed')}})
                # Preserve successful audio before alignment QA: repair timing without paying for speech again.
                audio = base64.b64decode(result.pop('audio_base64'), validate=True)
                if not audio:
                    raise ValueError('Provider returned empty narration')
                (folder / 'narration.mp3').write_bytes(audio)
                atomic_json(folder / 'alignment.json', result)
                job['audio_received'] = True
                words = words_from_alignment(result.get('normalized_alignment') or result.get('alignment') or {})
                atomic_json(folder / 'words.json', {'words': words, 'source': 'elevenlabs_alignment'})
                job['assets'] = [{'path': str(folder / 'narration.mp3'), 'sha256': sha256_file(folder / 'narration.mp3')}]
                job['state'] = 'complete'
        except Exception as error:
            job['state'] = 'received_needs_alignment' if job.get('audio_received') else 'unknown'
            job['error_type'] = type(error).__name__
            atomic_json(folder / 'job.json', job)
            raise ValueError('Attempt did not complete cleanly; state persisted. Reconcile before any new generation') from None
        atomic_json(folder / 'job.json', job)
        return job


def status(folder):
    folder = Path(folder).resolve()
    with lock(folder / '.lock'):
        job = load_json(folder / 'job.json')
        if job['state'] in ('prepared', 'complete', 'blocked', 'awaiting_agent_tool', 'received_needs_alignment'):
            return job
        provider, c = job['request']['provider'], job['connection']
        if provider == 'suno' and job.get('provider_result', {}).get('ids'):
            result = suno('status', c, folder, {'ids': job['provider_result']['ids']})
        elif provider == 'grok':
            result = gateway(c, job['id'], {'action': 'status'})
        elif provider == 'heygen':
            result = heygen_bridge.status(job['request'], c)
        else:
            return job
        job['last_status'] = result
        job['checked_at'] = now()
        atomic_json(folder / 'job.json', job)
        return job


def remote_paths(value):
    found = set()
    if isinstance(value, dict):
        for v in value.values():
            found.update(remote_paths(v))
    elif isinstance(value, list):
        for v in value:
            found.update(remote_paths(v))
    elif isinstance(value, str):
        found.update(re.findall(r'/home/node/\.openclaw/media/[A-Za-z0-9_./-]+\.mp4', value))
    return found


def collect_grok(folder):
    folder = Path(folder).resolve()
    with lock(folder / '.lock'):
        job = load_json(folder / 'job.json')
        if job['request']['provider'] != 'grok' or job['state'] == 'complete':
            raise ValueError('Requires an uncollected Grok job')
        paths = remote_paths([job.get('provider_result'), job.get('last_status')])
        if not paths:
            raise ValueError('No output path in provider receipt/status; reconcile the exact session, do not regenerate')
        assets = []
        for index, path in enumerate(sorted(paths)):
            p = PurePosixPath(path)
            if '..' in p.parts or not str(p).startswith('/home/node/.openclaw/media/'):
                raise ValueError('Unexpected remote output path')
            local = folder / f'grok-{index + 1}.mp4'
            if not local.exists():
                content = ssh(job['connection'], ['docker', 'exec', job['connection']['container'], 'cat', str(p)], timeout=120)
                with local.open('xb') as stream:
                    stream.write(content)
            from studio import ffprobe
            media = ffprobe(local)
            asset = {'path': str(local), 'sha256': sha256_file(local), 'media': media}
            assets.append(asset)
            try:
                asset['qa'] = grok_contract.media_qa(media, job['request'])
            except ValueError as error:
                job.update(state='received_needs_review', assets=assets, technical_issue=str(error))
                atomic_json(folder / 'job.json', job)
                raise
        job.update(state='complete', assets=assets)
        atomic_json(folder / 'job.json', job)
        return job


def collect_heygen(folder):
    folder = Path(folder).resolve()
    with lock(folder / '.lock'):
        job = load_json(folder / 'job.json')
        if job['request']['provider'] != 'heygen' or job['state'] in ('prepared', 'complete'):
            raise ValueError('Requires a submitted HeyGen video job')
        result = heygen_bridge.status(job['request'], job['connection'])
        video_id = result.get('cli_receipt', {}).get('result', {}).get('video_id')
        if not video_id:
            raise ValueError('This HeyGen operation has no rendered video ID; use status and its avatar/audio/workflow receipt')
        local = folder / 'heygen.mp4'
        if not local.exists():
            heygen_bridge.cli(job['connection'], ['download', '--id', video_id, '--out', str(local)], timeout=660)
        from studio import ffprobe
        media = ffprobe(local)
        asset = {'path': str(local), 'sha256': sha256_file(local), 'media': media}
        try:
            expected = job['request']['options'].get('resolution', '720p' if job['request']['operation'] == 'create' else None)
            asset['qa'] = grok_contract.media_qa(media, {'resolution': expected})
        except ValueError as error:
            job.update(state='received_needs_review', assets=[asset], technical_issue=str(error))
            atomic_json(folder / 'job.json', job)
            raise
        job.update(state='complete', assets=[asset], last_status=result)
        atomic_json(folder / 'job.json', job)
        return job


def register(folder, asset, receipt):
    folder = Path(folder).resolve()
    with lock(folder / '.lock'):
        job = load_json(folder / 'job.json')
        provider = job['request']['provider']
        if provider not in ('images', 'suno', 'genspark') or job['state'] not in ('awaiting_agent_tool', 'submitted', 'unknown'):
            raise ValueError('Registration is for awaited Codex output or Suno downloads')
        source = Path(asset).resolve()
        if not source.is_file() or not receipt.strip():
            raise ValueError('Existing asset and provider receipt are required')
        allowed = ('.png', '.jpg', '.jpeg', '.webp') if provider == 'images' else ('.mp4', '.mov', '.webm') if provider == 'genspark' else ('.mp3', '.wav', '.flac', '.m4a', '.ogg')
        if source.suffix.lower() not in allowed:
            raise ValueError('Registered output extension does not match provider')
        from studio import ffprobe
        media = ffprobe(source)
        kind = 'video' if provider in ('images', 'genspark') else 'audio'
        if not any(s['codec_type'] == kind for s in media['streams']):
            raise ValueError('Asset type does not match provider')
        target = folder / ('asset-' + sha256_file(source)[:16] + source.suffix.lower())
        if not target.exists():
            with source.open('rb') as inp, target.open('xb') as out:
                shutil.copyfileobj(inp, out)
        job.setdefault('assets', []).append({'path': str(target), 'sha256': sha256_file(target), 'receipt': receipt})
        job['state'] = 'complete'
        atomic_json(folder / 'job.json', job)
        return job


def validate_fallback(request):
    binding = request['fallback_for']
    parent = load_json(binding['path'])
    if parent.get('id') != binding['id'] or parent.get('request', {}).get('provider') != 'grok':
        raise ValueError('Fallback parent identity/provider changed')
    safely_blocked = parent.get('state') == 'blocked' and parent.get('provider_result', {}).get('submitted') is False
    if parent.get('state') != 'failed' and not safely_blocked:
        raise ValueError('Reconcile the original Grok job before fallback; only confirmed failure or unsubmitted block is eligible')
    if parent.get('assets'):
        raise ValueError('Reuse successful original assets instead of creating a fallback')
    original = parent['request']
    for field in ('prompt', 'duration_seconds', 'aspect_ratio', 'resolution', 'audio'):
        if request[field] != original[field]:
            raise ValueError('Fallback must preserve the approved shot contract: ' + field)
    if [r['sha256'] for r in request['references']] != [r['sha256'] for r in original.get('references', [])]:
        raise ValueError('Fallback must reuse the original first-frame image bytes')


def collect_genspark(folder):
    folder = Path(folder).resolve()
    with lock(folder / '.lock'):
        job = load_json(folder / 'job.json')
        if job['request']['provider'] != 'genspark' or job['state'] not in ('submitted', 'unknown'):
            raise ValueError('Requires an existing uncollected Genspark request')
        response = job.get('provider_result') or load_json(folder / 'genspark-response.json')
        videos = (response.get('data') or {}).get('generated_videos') or []
        urls = [url for item in videos for url in item.get('video_urls', [])]
        if len(urls) != 1:
            raise ValueError('Expected one completed output URL in the saved receipt; reconcile without regenerating')
        url = urls[0]
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise ValueError('Unexpected output URL scheme')
        target = folder / 'genspark.mp4'
        if target.exists():
            raise ValueError('Collection file already exists; inspect the previous download and register it')
        env = {**os.environ, 'GSK_NO_AUTO_UPDATE': '1'}
        result = subprocess.run(['node', job['connection']['cli_entry'], '--no-input', 'download', url, '--save', str(target)],
                                capture_output=True, timeout=180, env=env)
        (folder / 'genspark-download-receipt.json').write_bytes(result.stdout)
        if result.returncode or not target.is_file():
            raise ValueError('Download did not complete; keep the generation receipt and reconcile the same URL')
    return register(folder, target, 'Genspark CLI completed output; task receipt genspark-response.json and account download receipt preserved')


def browser_check(folder, credit_balance, evidence):
    number(credit_balance, 'credit_balance', 0, 100000000)
    if not evidence.strip():
        raise ValueError('Record the observed signed-in website account and balance evidence')
    folder = Path(folder)
    with lock(folder / '.lock'):
        job = load_json(folder / 'job.json')
        if job['request']['provider'] != 'genspark' or job['state'] != 'prepared':
            raise ValueError('Browser preflight is only for an unsubmitted Genspark fallback')
        job['browser_preflight'] = {'at': now(), 'credit_balance': credit_balance, 'evidence': evidence}
        atomic_json(folder / 'job.json', job)
        return {'browser_preflight_saved': True}


def record_browser(folder, task_url, outcome, receipt):
    from urllib.parse import urlparse
    url = urlparse(task_url)
    if url.scheme != 'https' or url.hostname not in ('www.genspark.ai', 'genspark.ai') or url.username or url.password:
        raise ValueError('Use the exact observed Genspark task URL')
    if outcome not in ('submitted', 'failed', 'unknown') or not receipt.strip():
        raise ValueError('Record an observed browser outcome and receipt')
    folder = Path(folder)
    with lock(folder / '.lock'):
        job = load_json(folder / 'job.json')
        if job['request']['provider'] != 'genspark' or job['state'] not in ('awaiting_agent_tool', 'submitted', 'unknown'):
            raise ValueError('Requires the existing attempted Genspark job')
        job.setdefault('browser_receipts', []).append({'at': now(), 'task_url': task_url, 'outcome': outcome, 'receipt': receipt})
        job['state'] = outcome
        atomic_json(folder / 'job.json', job)
        return {'id': job['id'], 'state': job['state']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--connections', default=str(ROOT / 'connections.json'))
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('probe'); q.add_argument('provider', choices=['images', 'suno', 'grok', 'genspark', 'elevenlabs', 'heygen'])
    q = sub.add_parser('prepare'); q.add_argument('--request', required=True); q.add_argument('--jobs', required=True)
    q = sub.add_parser('approve'); q.add_argument('--job', required=True); q.add_argument('--evidence', required=True)
    q.add_argument('--limit', type=float, required=True); q.add_argument('--unit', required=True)
    q = sub.add_parser('approve-batch'); q.add_argument('--jobs', required=True)
    q.add_argument('--job', action='append', required=True, help='job id under --jobs; repeat per job')
    q.add_argument('--evidence', required=True); q.add_argument('--limit', type=float, required=True, help='total cap for the whole batch')
    q.add_argument('--unit', required=True); q.add_argument('--per-job', type=float, help='optional cap per single job (default: the batch limit)')
    q.add_argument('--pilot', type=int, help='only the first N listed jobs may execute until batch-release')
    q = sub.add_parser('batch-status'); q.add_argument('--jobs', required=True); q.add_argument('--batch', required=True)
    q = sub.add_parser('batch-release'); q.add_argument('--jobs', required=True); q.add_argument('--batch', required=True)
    q.add_argument('--evidence', required=True, help='what the pilot review found')
    q = sub.add_parser('execute'); q.add_argument('--job', required=True); q.add_argument('--estimated-usage', type=float, required=True)
    for name in ('status', 'collect-grok', 'collect-genspark', 'collect-heygen'):
        q = sub.add_parser(name); q.add_argument('--job', required=True)
    q = sub.add_parser('register'); q.add_argument('--job', required=True); q.add_argument('--asset', required=True); q.add_argument('--receipt', required=True)
    q = sub.add_parser('browser-check'); q.add_argument('--job', required=True); q.add_argument('--credits', type=float, required=True); q.add_argument('--evidence', required=True)
    q = sub.add_parser('record-browser'); q.add_argument('--job', required=True); q.add_argument('--task-url', required=True); q.add_argument('--outcome', choices=['submitted','failed','unknown'], required=True); q.add_argument('--receipt', required=True)
    a = p.parse_args(); config = load_json(a.connections)
    if a.command == 'probe': result = probe(a.provider, config)
    elif a.command == 'prepare': result = {'job': str(prepare(a.request, a.jobs, config))}
    elif a.command == 'approve': result = authorize(a.job, a.evidence, a.limit, a.unit) or {'approved_record_saved': True}
    elif a.command == 'approve-batch': result = authorize_batch(a.jobs, a.job, a.evidence, a.limit, a.unit, a.per_job, a.pilot)
    elif a.command == 'batch-status': result = batch_status(a.jobs, a.batch)
    elif a.command == 'batch-release': result = batch_release(a.jobs, a.batch, a.evidence)
    elif a.command == 'execute': result = execute(a.job, config, a.estimated_usage)
    elif a.command == 'status': result = status(a.job)
    elif a.command == 'collect-grok': result = collect_grok(a.job)
    elif a.command == 'collect-genspark': result = collect_genspark(a.job)
    elif a.command == 'collect-heygen': result = collect_heygen(a.job)
    elif a.command == 'browser-check': result = browser_check(a.job, a.credits, a.evidence)
    elif a.command == 'record-browser': result = record_browser(a.job, a.task_url, a.outcome, a.receipt)
    else: result = register(a.job, a.asset, a.receipt)
    # Raw receipts and user copy stay in the project; stdout reveals only operational fields.
    if isinstance(result, dict) and 'request' in result:
        result = {k: result[k] for k in ('id', 'state', 'tool_request', 'assets') if k in result}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try: main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr); sys.exit(1)
