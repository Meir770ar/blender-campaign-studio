"""Long-form (150 s) commercial upgrades: gain automation, brand captions, batch approvals, camera
moves, image sequences, narration segmentation and freeze/alpha helpers. Local only; no providers."""
from array import array
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import antigravity
import audio_finish
import captions
import creative_gates
import davinci_bridge as bridge
import narration_plan
import provider_jobs as jobs
import sequence_tools
from studio import validate_plan
from test_davinci_bridge import fake_probe

SKILL_ROOT = Path(__file__).resolve().parent.parent


def tone(path, seconds, frequency=440):
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    f'sine=frequency={frequency}:sample_rate=48000:duration={seconds}', str(path)], check=True)


def samples(path):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1', '-ar', '48000', '-f', 'f32le', '-'])
    data = array('f')
    data.frombytes(raw)
    return data


def rms(data, start, end):
    chunk = data[start:end]
    return (sum(v * v for v in chunk) / len(chunk)) ** .5


class GainAutomationTests(unittest.TestCase):
    def test_envelope_expression_and_validation(self):
        expr = audio_finish.gain_envelope([[0, -20], [2, -20], [3, 0]])
        self.assertTrue(expr.startswith("volume='pow(10,(") and expr.endswith("/20)':eval=frame"), expr)
        self.assertIn('lt(t,(2))', expr)
        for bad in ([[1, 0]], [[0, 0], [0, -6]], [[0, 0], [5, 0]], [[0, 13], [1, 0]], 'x', [[0, 0], 3]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                audio_finish.checked_gain_keys(bad, 4)
        self.assertEqual(audio_finish.checked_gain_keys([], 4), [])

    def test_music_lift_measured_on_the_stem(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'tone.wav'
            tone(source, 6)
            spec = root / 'mix.json'
            spec.write_text(json.dumps({'duration': 6, 'target_lufs': -16, 'true_peak_dbtp': -4, 'tracks': [
                {'path': str(source), 'role': 'music', 'at': 0, 'in': 0, 'duration': 6, 'gain_db': 0,
                 'gain_keys': [[0, -20], [2, -20], [3, 0], [6, 0]]}]}), encoding='utf-8')
            audio_finish.finish(spec, root / 'out')
            music = samples(root / 'out' / 'music.wav')
            quiet = rms(music, 4800, 48000 * 2 - 4800)          # 0.1-1.9 s at -20 dB
            loud = rms(music, 48000 * 4, 48000 * 6 - 4800)       # 4.0-5.9 s at 0 dB
            self.assertAlmostEqual(loud / quiet, 10, delta=1.0)
            mid = rms(music, int(48000 * 2.45), int(48000 * 2.55))  # halfway up the ramp: about -10 dB
            self.assertGreater(mid / quiet, 2)
            self.assertLess(mid / quiet, 5)
            saved = json.loads((root / 'out' / 'source-mix.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['tracks'][0]['gain_keys'][2], [3, 0])


class BrandCaptionTests(unittest.TestCase):
    def test_brand_words_keep_their_color_while_emphasis_moves(self):
        group = [{'word': 'ברוכים', 'start': 0, 'end': .4}, {'word': '"מחוברים",', 'start': .4, 'end': .9},
                 {'word': 'היום.', 'start': .9, 'end': 1.3}]
        brand = captions.brand_colors({'מחוברים': '#1E88E5'})
        colors = lambda active, emphasis: [r['color'] for r in captions.phrase_runs(group, active, '#ffffff', emphasis, brand)]
        self.assertEqual(colors(1, '#ffd36a'), ['#ffffff', '#1E88E5', '#ffffff'])
        self.assertEqual(colors(2, '#ffd36a'), ['#ffffff', '#1E88E5', '#ffd36a'])
        self.assertEqual(colors(0, None), ['#ffffff', '#1E88E5', '#ffffff'])
        runs = captions.phrase_runs(group, 0, '#ffffff', None, brand)
        self.assertEqual(''.join(r['text'] for r in runs), 'ברוכים "מחוברים", היום.')
        for bad in ({'': '#123456'}, {'מילה': 'blue'}, {'מילה': '#12345'}, [], {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                captions.brand_colors(bad)

    def test_no_spoken_emphasis_yields_one_state_per_phrase(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            words = root / 'words.json'
            words.write_text(json.dumps({'words': [{'word': 'שלום', 'start': 0, 'end': .5},
                                                   {'word': 'מחוברים', 'start': .5, 'end': 1.0}]}), encoding='utf-8')
            (root / 'font.otf').write_bytes(b'fixture')
            style = root / 'style.json'
            style.write_text(json.dumps({'width': 640, 'height': 360, 'font_file': 'font.otf', 'font_size': 40,
                                         'highlight_color': None, 'brand_words': {'מחוברים': '#1E88E5'}}), encoding='utf-8')
            rendered = []

            def fake_render(spec_path, png):
                rendered.append(json.loads(Path(spec_path).read_text(encoding='utf-8')))
                Path(png).write_bytes(b'png')

            with patch.object(captions, 'render', fake_render):
                report = captions.build(words, style, root / 'out', 24, 10)
            self.assertEqual(report['states'], 1)
            self.assertFalse(report['spoken_word_emphasis'])
            self.assertEqual(report['brand_words_applied'], 1)
            self.assertEqual([r['color'] for r in rendered[0]['runs']], ['#ffffff', '#1E88E5'])
            bad_style = root / 'bad.json'
            bad_style.write_text(json.dumps({'width': 640, 'height': 360, 'font_file': 'font.otf', 'font_size': 40,
                                             'highlight_color': 'gold'}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'highlight_color'):
                captions.build(words, bad_style, root / 'out2', 24, 10)


class PlanMotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'image.png').write_bytes(b'fixture')
        (self.root / 'seq').mkdir()
        for index in range(1, 5):
            (self.root / 'seq' / f'frame_{index:05d}.png').write_bytes(b'fixture')
        (self.root / 'seq.mov').write_bytes(b'fixture')
        self.plan = {'version': 1, 'width': 640, 'height': 360, 'fps': 24, 'frames': 72,
                     'clips': [{'id': 'base', 'kind': 'image', 'path': 'image.png', 'start': 1, 'duration': 72, 'channel': 1}]}

    def validate(self, plan=None):
        path = self.root / 'plan.json'
        path.write_text(json.dumps(plan or self.plan), encoding='utf-8')
        return validate_plan(path, probe=False)[0]

    def with_clip(self, **fields):
        plan = copy.deepcopy(self.plan)
        plan['clips'].append({'id': 'over', 'kind': 'image', 'path': 'image.png', 'start': 1, 'duration': 48, 'channel': 2, **fields})
        return plan

    def test_motion_presets_amount_and_transform_keys(self):
        for motion in ('zoom-in', 'zoom-out', 'pan-left', 'pan-right', 'slide-left', 'slide-right', 'slide-down', 'push-in', 'fade-rise'):
            with self.subTest(motion=motion):
                self.validate(self.with_clip(motion=motion, motion_amount=.08))
        keys = [{'frame': 0, 'scale': 1}, {'frame': 47, 'scale': 1.12, 'offset_x': -40, 'rotation': 2}]
        plan = self.validate(self.with_clip(transform_keys=keys))
        self.assertEqual(plan['clips'][1]['transform_keys'], keys)
        for bad in (dict(motion='orbit'), dict(motion_amount=.05), dict(motion='zoom-in', motion_amount=.6),
                    dict(motion='zoom-in', transform_keys=keys), dict(transform_keys=keys[:1]),
                    dict(transform_keys=[{'frame': 5, 'scale': 1}, {'frame': 5, 'scale': 2}]),
                    dict(transform_keys=[{'frame': 0, 'scale': 1}, {'frame': 48, 'scale': 2}]),
                    dict(transform_keys=[{'frame': 0}, {'frame': 1, 'scale': 1}]),
                    dict(transform_keys=[{'frame': 0, 'zoom': 1}, {'frame': 1, 'scale': 1}]),
                    dict(transform_keys=[{'frame': 0, 'scale': 0}, {'frame': 1, 'scale': 1}])):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.validate(self.with_clip(**bad))
        sound = copy.deepcopy(self.plan)
        (self.root / 'a.wav').write_bytes(b'fixture')
        sound['clips'].append({'id': 's', 'kind': 'sound', 'path': 'a.wav', 'start': 1, 'duration': 10, 'channel': 3, 'transform_keys': keys})
        with self.assertRaisesRegex(ValueError, 'visual motion'):
            self.validate(sound)

    def test_image_sequence_frames_hold_and_companion(self):
        plan = self.validate(self.with_clip(kind='image-sequence', path='seq/frame_00001.png', duration=4))
        files = plan['clips'][1]['sequence_files']
        self.assertEqual([Path(f).name for f in files], [f'frame_{i:05d}.png' for i in range(1, 5)])
        with self.assertRaisesRegex(ValueError, 'hold_last'):
            self.validate(self.with_clip(kind='image-sequence', path='seq/frame_00001.png', duration=6))
        plan = self.validate(self.with_clip(kind='image-sequence', path='seq/frame_00002.png', duration=6, hold_last=True,
                                            resolve_movie='seq.mov'))
        files = plan['clips'][1]['sequence_files']
        self.assertEqual([Path(f).name for f in files], ['frame_00002.png', 'frame_00003.png', 'frame_00004.png'] + ['frame_00004.png'] * 3)
        self.assertEqual(plan['clips'][1]['resolve_movie'], str(self.root / 'seq.mov'))
        for bad in (dict(kind='image-sequence', path='seq/frame_00001.png', duration=4, source_start=1),
                    dict(kind='image-sequence', path='seq/frame_00001.png', duration=4, resolve_movie='missing.mov'),
                    dict(kind='image-sequence', path='seq/frame_00001.png', duration=4, hold_last='yes'),
                    dict(hold_last=True), dict(resolve_movie='seq.mov')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.validate(self.with_clip(**bad))


class BridgeSequenceTests(unittest.TestCase):
    def test_image_sequence_reaches_resolve_through_its_companion_movie(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'base.png').write_bytes(b'fixture')
            (root / 'fx').mkdir()
            for index in range(1, 4):
                (root / 'fx' / f'frame_{index:05d}.png').write_bytes(b'fixture')
            (root / 'butterfly.mov').write_bytes(b'fixture')
            plan_path = root / 'plan.json'
            plan_path.write_text(json.dumps({'version': 1, 'width': 640, 'height': 360, 'fps': 24, 'frames': 24, 'clips': [
                {'id': 'base', 'kind': 'image', 'path': 'base.png', 'start': 1, 'duration': 24, 'channel': 1},
                {'id': 'fx', 'kind': 'image-sequence', 'path': 'fx/frame_00001.png', 'start': 5, 'duration': 3, 'channel': 2,
                 'resolve_movie': 'butterfly.mov'}]}), encoding='utf-8')
            plan, _ = validate_plan(plan_path, probe=False)
            xml, manifest = bridge.build_sequence(plan, 'CUT_v001', probe=fake_probe)
            self.assertIn('butterfly.mov', xml)
            self.assertNotIn('frame_00001.png', xml)
            item = next(i for i in manifest['expected_items'] if i['id'] == 'fx')
            self.assertEqual(item['kind'], 'movie')
            self.assertTrue(item['path'].endswith('butterfly.mov'))
            del plan['clips'][1]['resolve_movie']
            with self.assertRaisesRegex(ValueError, 'resolve_movie'):
                bridge.build_sequence(plan, 'CUT_v002', probe=fake_probe)
            plan['clips'][0]['transform_keys'] = [{'frame': 0, 'scale': 1}, {'frame': 23, 'scale': 1.1}]
            plan['clips'][1]['resolve_movie'] = str(root / 'butterfly.mov')
            _, manifest = bridge.build_sequence(plan, 'CUT_v003', probe=fake_probe)
            self.assertIn('transform_keys', [u['field'] for u in manifest['unmapped']])


class BatchApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'images': {'route': 'codex_builtin'}, 'suno': {'client_module': 'x', 'model': 'm'}}

    def prepare(self, prompt, provider='images'):
        path = self.root / f'{abs(hash(prompt))}.json'
        request = {'provider': provider, 'prompt': prompt} if provider == 'images' else {'provider': provider, 'style': prompt}
        jobs.atomic_json(path, request)
        return jobs.prepare(path, self.root / 'jobs', self.config)

    def test_style_constraints_and_avoid_fold_into_the_prompt_once(self):
        r = jobs.validate_request({'provider': 'images', 'prompt': 'Woman at a bright desk ',
                                   'style_constraints': ['soft even daylight', ' clean muted palette '],
                                   'avoid': ['heavy shadows', ' saturated neon colors ']}, self.root, self.config)['request']
        self.assertEqual(r['prompt'], 'Woman at a bright desk\n\nStyle constraints: soft even daylight; clean muted palette.'
                                      '\n\nAvoid: heavy shadows; saturated neon colors.')
        self.assertEqual(r['avoid'], ['heavy shadows', 'saturated neon colors'])
        only = jobs.validate_request({'provider': 'images', 'prompt': 'p', 'avoid': ['glasses']}, self.root, self.config)['request']
        self.assertEqual(only['prompt'], 'p\n\nAvoid: glasses.')
        for bad in ({'provider': 'images', 'prompt': r['prompt'], 'avoid': ['x']},
                    {'provider': 'images', 'prompt': 'p', 'avoid': []},
                    {'provider': 'images', 'prompt': 'p', 'avoid': [' ']},
                    {'provider': 'images', 'prompt': 'p', 'avoid': ['a', 'b', 'c', 'd']},
                    {'provider': 'images', 'prompt': 'p', 'style_constraints': ['x'] * 13},
                    {'provider': 'suno', 'style': 's', 'avoid': ['x']}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                jobs.validate_request(bad, self.root, self.config)

    def test_batch_cap_is_enforced_across_the_jobs(self):
        a, b, c = [self.prepare(f'Shot {i}: the presenter walks to the window') for i in range(3)]
        ids = [p.name for p in (a, b, c)]
        result = jobs.authorize_batch(self.root / 'jobs', ids, 'user approved three stills at most two now', 2, 'images')
        self.assertEqual(result['jobs'], 3)
        for folder in (a, b, c):
            approval = json.loads((folder / 'job.json').read_text(encoding='utf-8'))['approval']
            self.assertEqual((approval['batch'], approval['batch_limit'], approval['limit']), (result['batch'], 2, 2))
        self.assertEqual(jobs.execute(a, self.config, 1)['state'], 'awaiting_agent_tool')
        self.assertEqual(jobs.execute(b, self.config, 1)['state'], 'awaiting_agent_tool')
        with self.assertRaisesRegex(ValueError, 'exceed'):
            jobs.execute(c, self.config, 1)
        self.assertEqual(json.loads((c / 'job.json').read_text(encoding='utf-8'))['state'], 'prepared')
        status = jobs.batch_status(self.root / 'jobs', result['batch'])
        self.assertEqual((status['spent_estimated'], status['remaining_estimated']), (2, 0))
        self.assertEqual([row['attempted'] for row in status['jobs']], [True, True, False])
        with self.assertRaisesRegex(ValueError, 'unapproved'):
            jobs.authorize_batch(self.root / 'jobs', ids, 'again', 5, 'images')

    def test_batch_rules(self):
        a, b = self.prepare('Shot A opens on the office'), self.prepare('Shot B the meeting room')
        with self.assertRaisesRegex(ValueError, 'at least two'):
            jobs.authorize_batch(self.root / 'jobs', [a.name], 'e', 1, 'images')
        with self.assertRaises(ValueError):
            jobs.authorize_batch(self.root / 'jobs', [a.name, b.name], 'e', 2, 'images', per_job=3)
        with self.assertRaisesRegex(ValueError, 'no prepared job'):
            jobs.authorize_batch(self.root / 'jobs', [a.name, 'missing'], 'e', 2, 'images')
        s = self.prepare('Warm strings, restrained', provider='suno')
        with self.assertRaisesRegex(ValueError, 'one provider'):
            jobs.authorize_batch(self.root / 'jobs', [a.name, s.name], 'e', 2, 'images')
        result = jobs.authorize_batch(self.root / 'jobs', [a.name, b.name], 'two stills approved', 4, 'images', per_job=1)
        self.assertEqual(result['per_job_limit'], 1)
        with self.assertRaises(ValueError):
            jobs.execute(a, self.config, 2)


class NarrationPlanTests(unittest.TestCase):
    def script(self, root, **overrides):
        script = {'version': 1, 'voice': {'stability': .5}, 'start_at': .5, 'segments': [
            {'id': 's01', 'text': 'בוקר טוב, ברוכים הבאים.', 'pause_after': .8},
            {'id': 's02', 'text': 'היום נראה איך זה עובד.', 'pause_after': 1.0}], **overrides}
        path = root / 'narration.json'
        path.write_text(json.dumps(script, ensure_ascii=False), encoding='utf-8')
        return path

    def test_split_validates_and_writes_one_request_per_segment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = narration_plan.split(self.script(root), root / 'split')
            self.assertEqual(len(report['segments']), 2)
            request = json.loads(Path(report['segments'][0]['request']).read_text(encoding='utf-8'))
            self.assertEqual(request['provider'], 'elevenlabs')
            self.assertEqual((request['stability'], request['speed']), (.5, 1))
            self.assertEqual(request['text'], 'בוקר טוב, ברוכים הבאים.')
            self.assertGreater(report['estimated_seconds'], 2)
            for bad in (dict(segments=[{'id': 's01', 'text': 'a'}, {'id': 's01', 'text': 'b'}]),
                        dict(segments=[{'id': 'S 1', 'text': 'a'}]),
                        dict(segments=[{'id': 's01', 'text': 'a <break time="1s"/> b'}]),
                        dict(segments=[{'id': 's01', 'text': 'a', 'pause_after': 11}]),
                        dict(segments=[{'id': 's01', 'text': 'a', 'pause': 1}]),
                        dict(voice={'stability': .5, 'speed': 2}), dict(segments=[])):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    narration_plan.validate_script({'version': 1, 'segments': [{'id': 's01', 'text': 'a'}], **bad})

    def test_layout_places_segments_with_pauses_and_merges_words(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'a').mkdir(); (root / 'b').mkdir()
            tone(root / 'a' / 'narration.wav', 1.0)
            tone(root / 'b' / 'narration.wav', 0.5)
            (root / 'a' / 'words.json').write_text(json.dumps({'words': [{'word': 'בוקר', 'start': 0, 'end': .4},
                                                                          {'word': 'טוב', 'start': .5, 'end': .9}]}), encoding='utf-8')
            report = narration_plan.layout(self.script(root), root / 'layout',
                                           audio_overrides={'s01': root / 'a' / 'narration.wav', 's02': root / 'b' / 'narration.wav'})
            self.assertEqual([t['at'] for t in report['tracks']], [.5, 2.3])
            self.assertEqual(report['end_of_speech_seconds'], 2.8)
            self.assertEqual(report['suggested_mix_duration'], 5)
            self.assertEqual(report['segments_without_words'], ['s02'])
            words = json.loads((root / 'layout' / 'words.json').read_text(encoding='utf-8'))['words']
            self.assertEqual([w['start'] for w in words], [.5, 1.0])
            tracks = json.loads((root / 'layout' / 'mix-tracks.json').read_text(encoding='utf-8'))
            self.assertEqual(tracks[1]['duration'], .5)
            with self.assertRaisesRegex(ValueError, '--jobs or --audio'):
                narration_plan.layout(self.script(root), root / 'layout2')

    def test_layout_finds_the_completed_job_by_exact_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            jobs_root = root / 'jobs'
            for name, text, state in (('j1', 'בוקר טוב, ברוכים הבאים.', 'complete'), ('j2', 'היום נראה איך זה עובד.', 'complete'),
                                      ('j3', 'היום נראה איך זה עובד.', 'prepared')):
                (jobs_root / name).mkdir(parents=True)
                (jobs_root / name / 'job.json').write_text(json.dumps({'state': state, 'request': {'provider': 'elevenlabs', 'text': text}}), encoding='utf-8')
                tone(jobs_root / name / 'narration.mp3', .5)
            report = narration_plan.layout(self.script(root), root / 'layout', jobs_root=jobs_root)
            self.assertEqual([t['segment'] for t in report['tracks']], ['s01', 's02'])
            (jobs_root / 'j3' / 'job.json').write_text(json.dumps({'state': 'complete', 'request': {'provider': 'elevenlabs', 'text': 'היום נראה איך זה עובד.'}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'found 2'):
                narration_plan.layout(self.script(root), root / 'layout2', jobs_root=jobs_root)


class SequenceToolTests(unittest.TestCase):
    def test_still_alpha_sequence_and_movie_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=24:duration=1',
                            '-pix_fmt', 'yuv420p', str(root / 'clip.mp4')], check=True)
            report = sequence_tools.still(root / 'clip.mp4', .5, root / 'freeze.png')
            self.assertTrue(Path(report['still']).is_file())
            self.assertEqual((report['width'], report['height']), (64, 64))
            with self.assertRaisesRegex(ValueError, 'no alpha'):
                sequence_tools.alpha_sequence(root / 'clip.mp4', root / 'seq-opaque')
            with self.assertRaises(ValueError):
                sequence_tools.still(root / 'clip.mp4', 5, root / 'late.png')
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red@0.5:size=64x64:rate=24:duration=0.5,format=rgba',
                            '-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', str(root / 'alpha.mov')], check=True)
            sequence = sequence_tools.alpha_sequence(root / 'alpha.mov', root / 'seq')
            self.assertEqual((sequence['count'], sequence['fps'], sequence['alpha']), (12, 24, True))
            self.assertEqual(sequence['plan_clip']['duration'], 12)
            first = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', sequence['first']]))
            self.assertEqual(first['streams'][0]['pix_fmt'], 'rgba')
            movie = sequence_tools.alpha_movie(sequence['first'], 24, root / 'roundtrip.mov')
            self.assertEqual(movie['frames'], 12)
            self.assertTrue(movie['pix_fmt'].startswith('yuva'))
            with self.assertRaises(ValueError):
                sequence_tools.alpha_movie(sequence['first'], 24, root / 'roundtrip.mov')


class ExclusionGateTests(unittest.TestCase):
    def direction(self):
        def fill(value):
            if isinstance(value, dict):
                return {k: fill(v) for k, v in value.items()}
            if isinstance(value, list):
                return [fill(v) for v in value]
            if isinstance(value, str) and value.startswith('REPLACE:'):
                return 'A concrete, observable production decision written for this test.'
            return value
        return fill(json.loads((SKILL_ROOT / 'templates' / 'direction-v1.json').read_text(encoding='utf-8-sig')))

    def test_exclusions_must_be_concrete(self):
        direction = self.direction()
        errors, _ = creative_gates.validate_direction(direction)
        self.assertEqual(errors, [])
        direction['visual_system']['exclusions'] = ['heavy shadows', 'saturated neon colors', 'text baked into the image']
        direction['visual_system']['style_constraints'] = ['soft even daylight', 'clean muted palette']
        self.assertEqual(creative_gates.validate_direction(direction)[0], [])
        for bad in ('heavy shadows', ['REPLACE: what to avoid'], ['ab'], ['tbd'], ['a', 'b', 'c', 'd']):
            with self.subTest(bad=bad):
                direction['visual_system']['exclusions'] = bad
                self.assertTrue(creative_gates.validate_direction(direction)[0])
        direction['visual_system']['exclusions'] = []
        for bad in ('soft', ['REPLACE: rule'], ['x'] * 13):
            with self.subTest(bad=bad):
                direction['visual_system']['style_constraints'] = bad
                self.assertTrue(creative_gates.validate_direction(direction)[0])


class MotionWarningTests(PlanMotionTests):
    def test_motion_density_and_repeated_presets_warn(self):
        plan = copy.deepcopy(self.plan)
        for index in range(5):
            plan['clips'].append({'id': f'o{index}', 'kind': 'image', 'path': 'image.png', 'start': 1 + index * 10,
                                  'duration': 8, 'channel': 2 + index, 'motion': 'zoom-in'})
        path = self.root / 'plan.json'
        path.write_text(json.dumps(plan), encoding='utf-8')
        _, warnings = validate_plan(path, probe=False)
        self.assertTrue(any('visual strips move' in w for w in warnings), warnings)
        self.assertTrue(any('back to back' in w for w in warnings), warnings)
        plan['clips'][1]['motion'] = 'pan-left'
        plan['clips'] = plan['clips'][:3]
        path.write_text(json.dumps(plan), encoding='utf-8')
        _, warnings = validate_plan(path, probe=False)
        self.assertEqual(warnings, [])

    def test_small_source_under_motion_warns_with_probe(self):
        (self.root / 'clip.mp4').write_bytes(b'fixture')
        plan = {'version': 1, 'width': 1920, 'height': 1080, 'fps': 24, 'frames': 48, 'clips': [
            {'id': 'bg', 'kind': 'movie', 'path': 'clip.mp4', 'start': 1, 'duration': 48, 'channel': 1, 'motion': 'zoom-in'}]}
        path = self.root / 'plan.json'
        path.write_text(json.dumps(plan), encoding='utf-8')
        fake = {'duration_seconds': '5', 'streams': [{'codec_type': 'video', 'width': 1280, 'height': 720,
                                                       'avg_frame_rate': '24/1', 'r_frame_rate': '24/1', 'duration': '5'}]}
        import studio
        with patch.object(studio, 'ffprobe', return_value=fake):
            _, warnings = validate_plan(path, probe=True)
        self.assertTrue(any('smaller than the 1920x1080' in w for w in warnings), warnings)
        plan['clips'][0].pop('motion')
        path.write_text(json.dumps(plan), encoding='utf-8')
        with patch.object(studio, 'ffprobe', return_value=fake):
            _, warnings = validate_plan(path, probe=True)
        self.assertEqual(warnings, [])


class PilotBatchTests(BatchApprovalTests):
    def test_pilot_holds_the_rest_until_release(self):
        a, b, c = [self.prepare(f'Pilot shot {i}: she enters the office') for i in range(3)]
        ids = [p.name for p in (a, b, c)]
        with self.assertRaises(ValueError):
            jobs.authorize_batch(self.root / 'jobs', ids, 'e', 3, 'images', pilot=3)
        result = jobs.authorize_batch(self.root / 'jobs', ids, 'three stills, pilot two', 3, 'images', pilot=2)
        self.assertEqual(result['pilot'], 2)
        with self.assertRaisesRegex(ValueError, 'pilot'):
            jobs.execute(c, self.config, 1)
        with self.assertRaisesRegex(ValueError, 'not yet attempted'):
            jobs.batch_release(self.root / 'jobs', result['batch'], 'reviewed')
        jobs.execute(a, self.config, 1)
        jobs.execute(b, self.config, 1)
        status = jobs.batch_status(self.root / 'jobs', result['batch'])
        self.assertEqual((status['pilot'], status['released']), (2, False))
        with self.assertRaises(ValueError):
            jobs.batch_release(self.root / 'jobs', result['batch'], '   ')
        released = jobs.batch_release(self.root / 'jobs', result['batch'], 'pilot stills match the character sheet')
        self.assertEqual(released['remaining_jobs'], [c.name])
        self.assertEqual(jobs.execute(c, self.config, 1)['state'], 'awaiting_agent_tool')
        with self.assertRaisesRegex(ValueError, 'already released'):
            jobs.batch_release(self.root / 'jobs', result['batch'], 'again')


class SunoExtendTests(unittest.TestCase):
    config = {'suno': {'client_module': 'x', 'model': 'chirp-fenix'}}

    def test_extension_fields_validate_together(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            r = jobs.validate_request({'provider': 'suno', 'style': 'builds into uplifting strings', 'instrumental': True,
                                       'extend_clip_id': 'abcd1234-ef56', 'extend_at_seconds': 45}, root, self.config)['request']
            self.assertEqual((r['extend_clip_id'], r['extend_at_seconds']), ('abcd1234-ef56', 45))
            for bad in ({'provider': 'suno', 'style': 's', 'extend_clip_id': 'abcd1234-ef56'},
                        {'provider': 'suno', 'style': 's', 'extend_at_seconds': 45},
                        {'provider': 'suno', 'style': 's', 'extend_clip_id': 'bad id!', 'extend_at_seconds': 45},
                        {'provider': 'suno', 'style': 's', 'extend_clip_id': 'abcd1234-ef56', 'extend_at_seconds': 0}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    jobs.validate_request(bad, root, self.config)

    def test_bridge_sends_the_extension_to_the_existing_client(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            captured = root / 'body.json'
            module = root / 'fake-client.mjs'
            module.write_text('import fs from "node:fs";\nexport class SunoClient { constructor(){this.cookie="mock";} async api(path, opts){'
                              'if(path==="/api/c/check") return {status:200, body:{required:false}};'
                              'fs.writeFileSync(' + json.dumps(str(captured)) + ', JSON.stringify(opts.body));'
                              'return {status:200, body:{clips:[{id:"clip-1"}]}}; }}', encoding='utf-8')
            request = root / 'request.json'
            request.write_text(json.dumps({'style': 'uplifting', 'instrumental': True, 'model': 'chirp-fenix',
                                           'extend_clip_id': 'abcd1234-ef56', 'extend_at_seconds': 45}), encoding='utf-8')
            result = subprocess.run(['node', str(jobs.ROOT / 'scripts/suno_bridge.mjs'), 'submit', str(module), str(request)],
                                    capture_output=True, text=True)
            self.assertEqual(json.loads(result.stdout)['ids'], ['clip-1'], result.stderr)
            body = json.loads(captured.read_text(encoding='utf-8'))
            self.assertEqual((body['continue_clip_id'], body['continue_at'], body['task']), ('abcd1234-ef56', 45, 'extend'))
            request.write_text(json.dumps({'style': 'tense', 'instrumental': True, 'model': 'chirp-fenix'}), encoding='utf-8')
            subprocess.run(['node', str(jobs.ROOT / 'scripts/suno_bridge.mjs'), 'submit', str(module), str(request)], capture_output=True)
            body = json.loads(captured.read_text(encoding='utf-8'))
            self.assertEqual((body['continue_clip_id'], body['continue_at'], body['task']), (None, None, None))


class SingleNarrationTests(unittest.TestCase):
    def script(self, root):
        script = {'version': 1, 'start_at': .5, 'segments': [
            {'id': 's01', 'text': 'בוקר טוב לכולם', 'pause_after': .5},
            {'id': 's02', 'text': 'היום נתחיל מיד.', 'pause_after': 0}]}
        path = root / 'narration.json'
        path.write_text(json.dumps(script, ensure_ascii=False), encoding='utf-8')
        return path

    def test_split_writes_the_single_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = narration_plan.split(self.script(root), root / 'split')
            self.assertEqual(report['recommended_mode'], 'single')
            single = json.loads(Path(report['single_request']).read_text(encoding='utf-8'))
            self.assertEqual(single['text'], 'בוקר טוב לכולם\n\nהיום נתחיל מיד.')
            self.assertEqual(single['provider'], 'elevenlabs')

    def test_single_render_is_cut_at_segment_boundaries_with_pauses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'take').mkdir()
            tone(root / 'take' / 'narration.wav', 3.0)
            words = [('בוקר', .1, .4), ('טוב', .5, .8), ('לכולם', .9, 1.2), ('היום', 1.6, 1.9), ('נתחיל', 2.0, 2.3), ('מיד.', 2.4, 2.7)]
            (root / 'take' / 'words.json').write_text(json.dumps({'words': [{'word': w, 'start': a, 'end': b} for w, a, b in words]},
                                                                  ensure_ascii=False), encoding='utf-8')
            report = narration_plan.layout(self.script(root), root / 'layout', audio_overrides={'single': root / 'take' / 'narration.wav'}, mode='single')
            self.assertEqual(report['mode'], 'single')
            self.assertEqual([t['at'] for t in report['tracks']], [.5, 2.24])
            self.assertEqual([round(t['duration'], 2) for t in report['tracks']], [1.24, 1.24])
            self.assertEqual([s['source_in'] for s in report['segments']], [.06, 1.56])
            self.assertEqual([s['source_out'] for s in report['segments']], [1.3, 2.8])
            self.assertEqual(report['segments'][1]['natural_gap_before'], .4)
            self.assertEqual(report['end_of_speech_seconds'], 3.48)
            merged = json.loads((root / 'layout' / 'words.json').read_text(encoding='utf-8'))['words']
            self.assertEqual([w['start'] for w in merged][:4], [.54, .94, 1.34, 2.28])
            self.assertTrue(all(Path(t['path']).is_file() for t in report['tracks']))
            (root / 'take' / 'words.json').write_text(json.dumps({'words': [{'word': w, 'start': a, 'end': b} for w, a, b in words[:5]]},
                                                                  ensure_ascii=False), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'aligned words'):
                narration_plan.layout(self.script(root), root / 'layout2', audio_overrides={'single': root / 'take' / 'narration.wav'}, mode='single')
            with self.assertRaisesRegex(ValueError, 'single mode'):
                narration_plan.layout(self.script(root), root / 'layout3', mode='single')


class VisionCheckTests(unittest.TestCase):
    def test_check_flags_present_items_and_reads_the_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            media = root / 'shot.mp4'
            media.write_bytes(b'fixture')
            request = root / 'request.json'
            request.write_text(json.dumps({'provider': 'grok', 'prompt': 'p', 'avoid': ['heavy shadows', 'text in image']}), encoding='utf-8')
            reply = json.dumps({'items': [{'item': 'heavy shadows', 'present': True, 'confidence': .8, 'evidence': 'hard shadow on the wall at 0:02'},
                                          {'item': 'text in image', 'present': False, 'confidence': .9, 'evidence': 'none'}], 'notes': ''})
            with patch.object(antigravity, 'call_agy', return_value=reply) as call:
                result = antigravity.check_shot(media, antigravity.items_from_request(request), root / 'check.json', context='office entrance')
            self.assertEqual(result['verdict'], 'flagged')
            self.assertEqual([x['item'] for x in result['flagged']], ['heavy shadows'])
            self.assertIn('- heavy shadows', call.call_args.args[1])
            self.assertIn('office entrance', call.call_args.args[1])
            with patch.object(antigravity, 'call_agy', return_value=json.dumps({'items': [{'item': 'x', 'present': False}]})):
                clear = antigravity.check_shot(media, ['x'], root / 'clear.json')
            self.assertEqual(clear['verdict'], 'clear')
            with patch.object(antigravity, 'call_agy', return_value='no json here'):
                unparsed = antigravity.check_shot(media, ['x'], root / 'unparsed.json')
            self.assertEqual(unparsed['verdict'], 'unparsed')
            with self.assertRaises(ValueError):
                antigravity.check_shot(media, [], root / 'none.json')
            request.write_text(json.dumps({'provider': 'grok', 'prompt': 'p'}), encoding='utf-8')
            with self.assertRaises(ValueError):
                antigravity.items_from_request(request)


if __name__ == '__main__':
    unittest.main()
