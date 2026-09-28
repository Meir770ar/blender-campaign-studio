"""Small fal/Kie queue adapters. One POST per approved job; no hidden retries."""
from __future__ import annotations
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

STAGES = ('image', 'video', 'voice', 'music')
MODELS = {
    'fal': {
        'image': 'fal-ai/flux/schnell',
        'video': 'fal-ai/wan/v2.2-a14b/text-to-video',
        'voice': 'fal-ai/minimax/speech-02-hd',
        'music': 'fal-ai/ace-step/prompt-to-audio',
    },
    'kie': {
        'image': 'bytedance/seedream-v4-text-to-image',
        'video': 'kling-2.6/text-to-video',
        'voice': 'elevenlabs/text-to-speech-multilingual-v2',
        'music': 'V5',  # Kie Suno API, separate from Market createTask
    },
}


def validate(request, connection):
    r = dict(request)
    provider, stage = r.get('provider'), r.get('stage')
    if provider not in MODELS or stage not in STAGES:
        raise ValueError('Select fal/kie and image/video/voice/music')
    allowed = {'provider', 'stage', 'prompt', 'text', 'duration_seconds', 'aspect_ratio', 'instrumental', 'voice_id', 'title'}
    if set(r) - allowed:
        raise ValueError('Unknown aggregator fields: ' + ', '.join(sorted(set(r) - allowed)))
    required = 'text' if stage == 'voice' else 'prompt'
    if not isinstance(r.get(required), str) or not r[required].strip():
        raise ValueError(required + ' is required')
    if stage == 'voice' and len(r['text']) > 4500:
        raise ValueError('Split narration below 4500 characters')
    if stage == 'video':
        duration = r.get('duration_seconds', 5)
        if type(duration) is not int or duration not in ((5, 10) if provider == 'kie' else range(1, 11)):
            raise ValueError('Unsupported duration for the selected video route')
        r['duration_seconds'] = duration
        r.setdefault('aspect_ratio', '16:9')
        if r['aspect_ratio'] not in ('16:9', '9:16', '1:1'):
            raise ValueError('Unsupported aspect ratio')
    if stage == 'music':
        r.setdefault('instrumental', True)
        if type(r['instrumental']) is not bool:
            raise ValueError('instrumental must be boolean')
        if provider == 'kie':
            if not r['instrumental']:
                raise ValueError('Kie music route currently supports instrumentals only')
            if not isinstance(r.get('title'), str) or not 1 <= len(r['title'].strip()) <= 80:
                raise ValueError('Kie instrumental music requires a title (1-80 characters)')
            if len(r['prompt']) > 1000:
                raise ValueError('Kie V5 custom-mode style must be at most 1000 characters')
    if stage == 'voice':
        if not isinstance(r.get('voice_id', connection.get('voice_id')), str) or not (r.get('voice_id') or connection.get('voice_id')):
            raise ValueError('Configure voice_id for this route')
        r['voice_id'] = r.get('voice_id') or connection['voice_id']
    stage_fields = {'image': {'prompt'}, 'video': {'prompt', 'duration_seconds', 'aspect_ratio'},
                    'voice': {'text', 'voice_id'}, 'music': {'prompt', 'instrumental', 'title'}}
    if set(r) - stage_fields[stage] - {'provider', 'stage'}:
        raise ValueError('Unsupported fields for this stage')
    routes = connection.get('models', {})
    if routes.get(stage) != MODELS[provider][stage]:
        raise ValueError('Only the documented model for this stage is supported; changing models needs an adapter update')
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*', connection.get('api_key_env', '')):
        raise ValueError('Configure an API key environment variable name')
    return r


def payload(r, c):
    provider, stage = r['provider'], r['stage']
    model = c['models'][stage]
    if provider == 'fal':
        if stage == 'image': data = {'prompt': r['prompt'], 'num_images': 1}
        elif stage == 'video': data = {'prompt': r['prompt'], 'num_frames': r['duration_seconds'] * 16 + 1,
                                       'frames_per_second': 16, 'aspect_ratio': r['aspect_ratio']}
        elif stage == 'voice': data = {'text': r['text'], 'voice_setting': {'voice_id': r['voice_id']}}
        else: data = {'prompt': r['prompt'], 'instrumental': r['instrumental']}
        return 'https://queue.fal.run/' + model, data
    if stage == 'music':
        # Kie Suno requires a callback URL even when the task is polled later.
        callback = c.get('music_callback_url')
        parsed = urllib.parse.urlparse(callback or '')
        if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('Kie music requires a configured HTTPS callback URL')
        return 'https://api.kie.ai/api/v1/generate', {'style': r['prompt'],
                                                       'title': r['title'], 'customMode': True,
                                                       'instrumental': True, 'model': model, 'callBackUrl': callback}
    if stage == 'image': data = {'prompt': r['prompt'], 'max_images': 1}
    elif stage == 'video': data = {'prompt': r['prompt'], 'sound': False, 'aspect_ratio': r['aspect_ratio'],
                                    'duration': str(r['duration_seconds'])}
    else: data = {'text': r['text'], 'voice': r['voice_id']}
    return 'https://api.kie.ai/api/v1/jobs/createTask', {'model': model, 'input': data}


def http(method, url, key, body=None):
    host = urllib.parse.urlparse(url).hostname
    if host not in ('queue.fal.run', 'api.kie.ai') or not url.startswith('https://'):
        raise ValueError('Unexpected aggregator endpoint')
    headers = {'Authorization': ('Key ' if host == 'queue.fal.run' else 'Bearer ') + key}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ValueError(f'Aggregator HTTP {error.code}; response withheld') from None


def key(c):
    value = os.environ.get(c['api_key_env'])
    if not value:
        raise ValueError('Aggregator API key missing in configured environment')
    return value


def submit(r, c):
    url, data = payload(r, c)
    result = http('POST', url, key(c), data)
    if r['provider'] == 'kie':
        kie_ok(result)
    elif not isinstance(result, dict):
        raise ValueError('fal returned no task object; reconcile account before another attempt')
    task_id = result.get('request_id') if r['provider'] == 'fal' else result['data'].get('taskId')
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{5,128}', task_id):
        raise ValueError('Submission response has no recognizable task ID; reconcile account before another attempt')
    return {'task_id': task_id, 'stage': r['stage'], 'model': c['models'][r['stage']]}


def kie_ok(response, task_id=None):
    if not isinstance(response, dict) or type(response.get('code')) is not int or response['code'] != 200:
        raise ValueError('Kie returned a non-success application code; response withheld')
    data = response.get('data')
    if not isinstance(data, dict) or (task_id is not None and data.get('taskId') != task_id):
        raise ValueError('Kie returned missing or mismatched task data; reconcile existing task')
    return data


def media_url(value):
    if not isinstance(value, str):
        return False
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password


def checked_result(r, result):
    """Minimal documented output shape; URL presence is not downloaded-media QA."""
    if not isinstance(result, dict):
        raise ValueError('Aggregator result is not an object; reconcile existing task')
    if r['provider'] == 'fal':
        if r['stage'] == 'image':
            files = result.get('images')
            valid = isinstance(files, list) and bool(files) and all(
                isinstance(item, dict) and media_url(item.get('url')) for item in files)
        else:
            item = result.get('video' if r['stage'] == 'video' else 'audio')
            valid = isinstance(item, dict) and media_url(item.get('url'))
    elif r['stage'] == 'music':
        files = result.get('sunoData')
        valid = isinstance(files, list) and bool(files) and all(
            isinstance(item, dict) and media_url(item.get('audioUrl')) for item in files)
    else:
        files = result.get('resultUrls')
        valid = isinstance(files, list) and bool(files) and all(media_url(url) for url in files)
    if not valid:
        raise ValueError('Aggregator result lacks valid media URLs; reconcile existing task')
    return result


def status(r, c, receipt):
    task_id = receipt['task_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]{5,128}', task_id):
        raise ValueError('Invalid task ID')
    if r['provider'] == 'fal':
        if receipt['model'] != c['models'][r['stage']]:
            raise ValueError('Receipt model differs from approved job')
        url = f'https://queue.fal.run/{receipt["model"]}/requests/{task_id}/status'
    elif r['stage'] == 'music':
        url = 'https://api.kie.ai/api/v1/generate/record-info?taskId=' + task_id
    else:
        url = 'https://api.kie.ai/api/v1/jobs/recordInfo?taskId=' + task_id
    response = http('GET', url, key(c))
    if r['provider'] == 'fal':
        if not isinstance(response, dict) or response.get('status') not in ('IN_QUEUE', 'IN_PROGRESS', 'COMPLETED'):
            raise ValueError('fal returned an unknown queue state; reconcile existing task')
        if response.get('request_id') != task_id:
            raise ValueError('fal returned a missing or different task ID; reconcile existing task')
    if r['provider'] == 'kie':
        data = kie_ok(response, task_id)
        state = data.get('status' if r['stage'] == 'music' else 'state')
        allowed = ('PENDING', 'TEXT_SUCCESS', 'FIRST_SUCCESS', 'SUCCESS', 'CREATE_TASK_FAILED',
                   'GENERATE_AUDIO_FAILED', 'CALLBACK_EXCEPTION', 'SENSITIVE_WORD_ERROR') if r['stage'] == 'music' else (
                       'waiting', 'queuing', 'generating', 'success', 'fail')
        if state not in allowed:
            raise ValueError('Kie returned an unknown task state; reconcile existing task')
    return response


def result(r, c, receipt):
    """Read the existing task result. Never resubmit when collection fails."""
    state = status(r, c, receipt)
    if r['provider'] == 'fal':
        if state.get('status') != 'COMPLETED':
            raise ValueError('fal task is not complete; keep its existing task ID')
        url = f'https://queue.fal.run/{receipt["model"]}/requests/{receipt["task_id"]}/response'
        return checked_result(r, http('GET', url, key(c)))
    data = state.get('data') or {}
    completed = 'SUCCESS' if r['stage'] == 'music' else 'success'
    if data.get('status' if r['stage'] == 'music' else 'state') != completed:
        raise ValueError('Kie task is not complete; keep its existing task ID')
    if r['stage'] == 'music':
        response = data.get('response')
        return checked_result(r, response)
    raw = data.get('resultJson')
    if not isinstance(raw, str):
        raise ValueError('Kie result is missing; reconcile the existing task')
    parsed = json.loads(raw)
    return checked_result(r, parsed)
