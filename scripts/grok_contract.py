"""Exact video request contract for the native subscription provider."""
from pathlib import Path
from urllib.parse import urlsplit
import ipaddress
import json
import shutil
import subprocess
from campaign_common import sha256_file
from studio import source_path, number

MODELS = ('xai/grok-imagine-video', 'xai/grok-imagine-video-1.5')
RATIOS = ('16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3')
CONTRACT = '20260909-v1.5-1080p'


def validate(r, base, connection):
    r = dict(r)
    r.setdefault('model', connection['model'] if r.get('mode') in ('edit', 'extend') else connection.get('preferred_model', connection['model']))
    if r['model'] not in MODELS:
        raise ValueError('Unsupported Grok model; no model fallback is permitted')
    modern = r['model'].endswith('-1.5')
    refs = r.get('references', [])
    if not isinstance(refs, list) or len(refs) > 9:
        raise ValueError('Grok supports at most nine image inputs: first, last, seven references')
    normalized = []
    for ref in refs:
        value = {'path': ref, 'role': 'first_frame' if len(refs) == 1 else 'reference_image'} if isinstance(ref, str) else ref
        if not isinstance(value, dict) or set(value) != {'path', 'role'} or value['role'] not in ('first_frame', 'last_frame', 'reference_image'):
            raise ValueError('Each Grok reference requires path and a supported role')
        path = source_path(value['path'], base)
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            raise ValueError('Unsupported Grok reference image format')
        normalized.append({'path': str(path), 'sha256': sha256_file(path), 'role': value['role']})
    r['references'] = normalized
    if len({(x['sha256'], x['role']) for x in normalized}) != len(normalized):
        raise ValueError('Duplicate image bytes with the same role would be deduplicated by the native tool')
    roles = [x['role'] for x in normalized]
    if roles.count('first_frame') > 1 or roles.count('last_frame') > 1 or roles.count('reference_image') > 7:
        raise ValueError('At most one first frame, one last frame and seven references are supported')
    is_reference = 'last_frame' in roles or 'reference_image' in roles
    if not modern and ('last_frame' in roles or ('first_frame' in roles and 'reference_image' in roles)):
        raise ValueError('Last frames and combined frame/reference inputs require Grok 1.5')
    mode = r.get('mode') or ('reference-to-video' if is_reference else 'image-to-video' if roles else 'text-to-video')
    r['mode'] = mode
    if mode in ('edit', 'extend'):
        if roles or any(key in r for key in ('resolution', 'aspect_ratio', 'audio')):
            raise ValueError('Edit/extend takes a video URL and inherits its format/audio; omit image references and format controls')
        if not isinstance(r.get('video_url'), str):
            raise ValueError('video_url must be a public HTTPS video URL')
        url = urlsplit(r['video_url'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.port not in (None, 443):
            raise ValueError('video_url must be a public HTTPS video URL without embedded credentials')
        if url.hostname in ('localhost',) or url.hostname.endswith(('.local', '.internal')):
            raise ValueError('Private video URLs are not supported')
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError('Private video URLs are not supported')
        source_duration = r.get('source_duration_seconds')
        number(source_duration, 'source_duration_seconds', .1 if mode == 'edit' else 2, 8.7 if mode == 'edit' else 15)
        if not url.path.lower().endswith('.mp4'):
            raise ValueError('The native video edit/extend route requires an MP4 source URL')
        if mode == 'edit' and 'duration_seconds' in r:
            raise ValueError('Edit preserves source duration; omit duration_seconds')
        if mode == 'extend':
            d = r.get('duration_seconds', 5)
            if type(d) is not int or not 2 <= d <= 10:
                raise ValueError('Extension duration_seconds must be an integer from 2 to 10')
            r['duration_seconds'] = d
        return r
    expected = 'reference-to-video' if is_reference else 'image-to-video' if roles else 'text-to-video'
    if mode != expected or any(key in r for key in ('video_url', 'source_duration_seconds')):
        raise ValueError('Grok mode does not match its image/video inputs')
    r.setdefault('duration_seconds', 6)
    r.setdefault('aspect_ratio', '16:9')
    # Existing 720p requests stay valid; production agents choose 1080p explicitly.
    r.setdefault('resolution', '720P')
    r.setdefault('audio', False)
    duration = r['duration_seconds']
    if type(duration) is not int or not 1 <= duration <= (10 if is_reference and not modern else 15):
        raise ValueError('Duration exceeds the selected Grok mode limit')
    if r['aspect_ratio'] not in RATIOS or r['resolution'] not in ('480P', '720P', '1080P') or type(r['audio']) is not bool:
        raise ValueError('Unsupported Grok format or audio setting')
    if r['resolution'] == '1080P' and (not modern or is_reference):
        raise ValueError('1080P requires Grok 1.5 text-to-video or one first frame; references/last frame are capped at 720P')
    return r


def ensure_capability(request, provider, metadata):
    if metadata.get('campaign_contract') != CONTRACT:
        raise ValueError('Native Grok provider expansion is not active; apply the reviewed SDK patch before generation')
    mode = 'videoToVideo' if request['mode'] in ('edit', 'extend') else 'imageToVideo' if request['references'] else 'generate'
    cap = provider.get('capabilities', {}).get(mode, {})
    if not cap or cap.get('enabled') is False:
        raise ValueError('The native provider does not advertise the requested video mode')
    if request.get('resolution') and request['resolution'] not in cap.get('resolutions', []):
        raise ValueError('Requested resolution is unavailable in the active native provider')
    if request['references'] and len(request['references']) > cap.get('maxInputImages', 0):
        raise ValueError('Native provider reference limit is below this request')
    if request.get('audio') is not None and not cap.get('supportsAudio'):
        raise ValueError('Native provider does not advertise explicit audio control')


def arguments(request, connection, job_id, upload):
    args = {'action': 'generate', 'prompt': request['prompt'], 'model': request.get('model', connection['model']),
            'filename': f'campaign-{job_id}.mp4', 'timeoutMs': 600000}
    for source, target in [('duration_seconds', 'durationSeconds'), ('aspect_ratio', 'aspectRatio'), ('resolution', 'resolution'), ('audio', 'audio')]:
        if source in request:
            args[target] = request[source]
    if request.get('video_url'):
        args['video'] = request['video_url']
        args['videoRoles'] = ['reference_video']
    if request['references']:
        args['images'] = [upload(ref) for ref in request['references']]
        args['imageRoles'] = [ref.get('role', 'first_frame') for ref in request['references']]
    return args


def remote_reference_path(ref):
    # The SDK deduplicates input paths before assigning roles. Separate first/last
    # filenames preserve both roles even when a loop uses the same frame twice.
    return '/home/node/.openclaw/media/campaign-ref-' + ref['sha256'] + '-' + ref.get('role', 'first_frame') + Path(ref['path']).suffix.lower()


def inspect_video_input(request):
    if request.get('mode') not in ('edit', 'extend'):
        return None
    tool = shutil.which('ffprobe')
    if not tool:
        raise ValueError('ffprobe is required to verify source video before an edit/extension')
    result = subprocess.run([tool, '-v', 'error', '-rw_timeout', '20000000', '-show_streams', '-show_format',
                             '-of', 'json', request['video_url']], capture_output=True, timeout=45)
    if result.returncode:
        raise ValueError('Source video cannot be read; refresh its URL before submitting generation')
    media = json.loads(result.stdout)
    duration = float(media.get('format', {}).get('duration', 0))
    if not any(s.get('codec_type') == 'video' for s in media.get('streams', [])) or duration <= 0:
        raise ValueError('Source URL has no valid video stream and duration')
    if abs(duration - request['source_duration_seconds']) > .25 or (request['mode'] == 'edit' and duration > 8.7):
        raise ValueError('Source video duration differs from the reviewed request or exceeds the edit limit')
    return {'duration_seconds': duration, 'verified_before_submit': True}


def media_qa(media, request):
    video = next((s for s in media.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError('Output has no decodable video stream')
    expected = request.get('resolution')
    if expected and min(video.get('width', 0), video.get('height', 0)) < int(expected.rstrip('Pp')):
        raise ValueError(f'Output is below requested {expected}; keep received media and review without regenerating')
    audio = any(s.get('codec_type') == 'audio' for s in media.get('streams', []))
    if request.get('audio') is True and not audio:
        raise ValueError('Requested native audio is missing; preserve the received clip for review')
    if request.get('aspect_ratio') and video.get('width') and video.get('height'):
        width, height = map(int, request['aspect_ratio'].split(':'))
        if abs(video['width'] / video['height'] - width / height) > .025:
            raise ValueError('Output aspect ratio differs from the reviewed request')
    duration = float(media.get('duration_seconds') or video.get('duration') or 0)
    expected_duration = request.get('duration_seconds')
    if request.get('mode') == 'edit':
        expected_duration = request['source_duration_seconds']
    elif request.get('mode') == 'extend':
        expected_duration = request['source_duration_seconds'] + request['duration_seconds']
    if duration and expected_duration and abs(duration - expected_duration) > .6:
        raise ValueError('Output duration differs from the reviewed request')
    return {'width': video.get('width'), 'height': video.get('height'), 'audio_track': audio,
            'duration_seconds': duration, 'requested_resolution': expected, 'technical_check': 'passed', 'creative_review': 'pending'}
