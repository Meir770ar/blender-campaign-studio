"""Contract tests: all transport is mocked, never generates media."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import aggregator_routes as routes
import provider_jobs as jobs


class AggregatorRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = {p: {'api_key_env': p.upper() + '_KEY', 'models': dict(models),
                           'voice_id': 'Wise_Woman', 'music_callback_url': 'https://example.com/callback'}
                       for p, models in routes.MODELS.items()}

    def test_four_stages_each_provider(self):
        for provider in routes.MODELS:
            for stage in routes.STAGES:
                with self.subTest(provider=provider, stage=stage):
                    req = {'provider': provider, 'stage': stage,
                           'text' if stage == 'voice' else 'prompt': 'Hebrew campaign'}
                    if provider == 'kie' and stage == 'music':
                        req['title'] = 'Campaign music'
                    r = jobs.validate_request(req, self.root, self.config)['request']
                    url, payload = routes.payload(r, self.config[provider])
                    self.assertTrue(url.startswith('https://'))
                    self.assertIsInstance(payload, dict)
                    self.assertEqual(r['stage'], stage)

    def test_payloads_match_documented_model_contracts(self):
        fal = routes.validate({'provider': 'fal', 'stage': 'video', 'prompt': 'shot', 'duration_seconds': 5}, self.config['fal'])
        self.assertEqual(routes.payload(fal, self.config['fal'])[1],
                         {'prompt': 'shot', 'num_frames': 81, 'frames_per_second': 16, 'aspect_ratio': '16:9'})
        kie = routes.validate({'provider': 'kie', 'stage': 'music', 'prompt': 'Warm piano', 'title': 'Campaign'}, self.config['kie'])
        body = routes.payload(kie, self.config['kie'])[1]
        self.assertEqual((body['customMode'], body['instrumental'], body['style'], body['title']),
                         (True, True, 'Warm piano', 'Campaign'))
        with self.assertRaisesRegex(ValueError, 'title'):
            routes.validate({'provider': 'kie', 'stage': 'music', 'prompt': 'Warm piano'}, self.config['kie'])

    def test_unknown_fields_and_models_fail_closed(self):
        with self.assertRaises(ValueError):
            jobs.validate_request({'provider': 'fal', 'stage': 'image', 'prompt': 'x', 'text': 'wrong'}, self.root, self.config)
        self.config['fal']['models']['image'] = 'different-model'
        with self.assertRaises(ValueError):
            jobs.validate_request({'provider': 'fal', 'stage': 'image', 'prompt': 'x'}, self.root, self.config)

    def test_approval_cap_and_one_submit(self):
        request = self.root / 'request.json'
        request.write_text(json.dumps({'provider': 'fal', 'stage': 'image', 'prompt': 'A product on a table'}))
        folder = jobs.prepare(request, self.root / 'jobs', self.config)
        with self.assertRaisesRegex(ValueError, 'approval'):
            jobs.execute(folder, self.config, 1)
        jobs.authorize(folder, 'user approved one render', 2, 'USD estimate')
        with self.assertRaises(ValueError):
            jobs.execute(folder, self.config, 3)
        with patch.object(routes, 'key', return_value='fixture'), patch.object(routes, 'submit', return_value={'task_id': 'req-123456', 'model': routes.MODELS['fal']['image']} ) as submit:
            job = jobs.execute(folder, self.config, 1)
            self.assertEqual(job['state'], 'submitted')
            with self.assertRaisesRegex(ValueError, 'already attempted'):
                jobs.execute(folder, self.config, 1)
            submit.assert_called_once()

    def test_kie_application_response_contract(self):
        r = routes.validate({'provider': 'kie', 'stage': 'image', 'prompt': 'A desk'}, self.config['kie'])
        c = self.config['kie']
        receipt = {'task_id': 'task_123456', 'model': c['models']['image']}
        success = {'code': 200, 'msg': 'success', 'data': {'taskId': 'task_123456'}}
        with patch.object(routes, 'key', return_value='fixture'), patch.object(routes, 'http', return_value=success):
            self.assertEqual(routes.submit(r, c)['task_id'], 'task_123456')
        for bad in ({'code': 402, 'msg': 'Insufficient Credits', 'data': {'taskId': 'task_123456'}},
                    {'code': 200, 'msg': 'success', 'data': {}},
                    {'code': 200, 'msg': 'success', 'data': 'wrong'}):
            with self.subTest(bad=bad), patch.object(routes, 'key', return_value='fixture'), \
                 patch.object(routes, 'http', return_value=bad), self.assertRaises(ValueError):
                routes.submit(r, c)
        generating = {'code': 200, 'msg': 'success', 'data': {'taskId': 'task_123456', 'state': 'generating'}}
        with patch.object(routes, 'key', return_value='fixture'), patch.object(routes, 'http', return_value=generating):
            self.assertEqual(routes.status(r, c, receipt)['data']['state'], 'generating')
            with self.assertRaisesRegex(ValueError, 'not complete'):
                routes.result(r, c, receipt)
        complete = {'code': 200, 'msg': 'success', 'data': {'taskId': 'task_123456', 'state': 'success',
                                                           'resultJson': '{"resultUrls":["https://example.com/image.jpg"]}'}}
        with patch.object(routes, 'key', return_value='fixture'), patch.object(routes, 'http', return_value=complete):
            self.assertEqual(routes.result(r, c, receipt)['resultUrls'], ['https://example.com/image.jpg'])
        for bad in ({'code': 501, 'msg': 'failed', 'data': generating['data']},
                    {'code': 200, 'msg': 'success', 'data': {'taskId': 'wrong-id', 'state': 'success'}},
                    {'code': 200, 'msg': 'success', 'data': {'taskId': 'task_123456', 'state': 'unexpected'}}):
            with self.subTest(bad=bad), patch.object(routes, 'key', return_value='fixture'), \
                 patch.object(routes, 'http', return_value=bad), self.assertRaises(ValueError):
                routes.status(r, c, receipt)
        with patch.object(routes, 'key', return_value='fixture'), \
             patch.object(routes, 'http', return_value={'code': 200, 'msg': 'success', 'data': {
                 'taskId': 'task_123456', 'state': 'success', 'resultJson': '{}'}}), self.assertRaises(ValueError):
            routes.result(r, c, receipt)

    def test_kie_music_detail_contract(self):
        r = routes.validate({'provider': 'kie', 'stage': 'music', 'prompt': 'Warm piano', 'title': 'Campaign'}, self.config['kie'])
        c = self.config['kie']
        receipt = {'task_id': 'task_123456', 'model': 'V5'}
        body = routes.payload(r, c)[1]
        self.assertNotIn('prompt', body)  # Instrumental custom mode uses style, not lyrics.
        good = {'code': 200, 'msg': 'success', 'data': {'taskId': 'task_123456', 'status': 'SUCCESS',
                 'response': {'taskId': 'task_123456', 'sunoData': [{'id': 'track-1',
                  'audioUrl': 'https://example.com/music.mp3'}]}}}
        with patch.object(routes, 'key', return_value='fixture'), patch.object(routes, 'http', return_value=good):
            self.assertEqual(routes.result(r, c, receipt)['sunoData'][0]['id'], 'track-1')
        bad = {'code': 200, 'msg': 'success', 'data': {'taskId': 'task_123456', 'status': 'SUCCESS',
                'response': {'sunoData': []}}}
        with patch.object(routes, 'key', return_value='fixture'), patch.object(routes, 'http', return_value=bad), \
             self.assertRaisesRegex(ValueError, 'valid media URLs'):
            routes.result(r, c, receipt)

    def test_all_eight_result_shapes_and_errors(self):
        examples = {
            ('fal', 'image'): {'images': [{'url': 'https://example.com/image.jpg'}]},
            ('fal', 'video'): {'video': {'url': 'https://example.com/video.mp4'}},
            ('fal', 'voice'): {'audio': {'url': 'https://example.com/speech.mp3'}},
            ('fal', 'music'): {'audio': {'url': 'https://example.com/music.wav'}},
            ('kie', 'image'): {'resultUrls': ['https://example.com/image.jpg']},
            ('kie', 'video'): {'resultUrls': ['https://example.com/video.mp4']},
            ('kie', 'voice'): {'resultUrls': ['https://example.com/speech.mp3']},
            ('kie', 'music'): {'sunoData': [{'audioUrl': 'https://example.com/music.mp3'}]},
        }
        for (provider, stage), payload in examples.items():
            with self.subTest(provider=provider, stage=stage):
                r = {'provider': provider, 'stage': stage}
                self.assertEqual(routes.checked_result(r, payload), payload)
                for malformed in ({}, {'resultUrls': ['http://example.com/insecure.mp3']},
                                  {'audio': {'url': 'file:///tmp/missing.mp3'}},
                                  {'sunoData': [{'id': 'track-without-audio'}]}):
                    with self.assertRaisesRegex(ValueError, 'valid media URLs'):
                        routes.checked_result(r, malformed)
                receipt = {'task_id': 'task_123456', 'model': routes.MODELS[provider][stage]}
                c = self.config[provider]
                if provider == 'fal':
                    state = {'status': 'COMPLETED', 'request_id': 'task_123456'}
                    with patch.object(routes, 'key', return_value='fixture'), \
                         patch.object(routes, 'http', side_effect=[state, payload]):
                        self.assertEqual(routes.result(r, c, receipt), payload)
                    with patch.object(routes, 'key', return_value='fixture'), \
                         patch.object(routes, 'http', side_effect=[state, {}]), self.assertRaises(ValueError):
                        routes.result(r, c, receipt)
                    for invalid in ({'status': 'COMPLETED'},
                                    {'status': 'COMPLETED', 'request_id': 'wrong-id'},
                                    {'status': 'FAILED'}, {}, {'status': 'IN_PROGRESS'}):
                        with patch.object(routes, 'key', return_value='fixture'), \
                             patch.object(routes, 'http', return_value=invalid), self.assertRaises(ValueError):
                            routes.result(r, c, receipt)
                else:
                    data = {'taskId': 'task_123456', 'status' if stage == 'music' else 'state':
                            'SUCCESS' if stage == 'music' else 'success'}
                    if stage == 'music':
                        data['response'] = payload
                    else:
                        data['resultJson'] = json.dumps(payload)
                    good = {'code': 200, 'msg': 'success', 'data': data}
                    with patch.object(routes, 'key', return_value='fixture'), \
                         patch.object(routes, 'http', return_value=good):
                        self.assertEqual(routes.result(r, c, receipt), payload)
                    bad_data = dict(data, **({'response': {}} if stage == 'music' else {'resultJson': '{}'}))
                    with patch.object(routes, 'key', return_value='fixture'), \
                         patch.object(routes, 'http', return_value={'code': 200, 'msg': 'success', 'data': bad_data}), \
                         self.assertRaises(ValueError):
                        routes.result(r, c, receipt)

    def test_receipt_status_and_collection_do_not_post(self):
        request = self.root / 'request.json'
        request.write_text(json.dumps({'provider': 'kie', 'stage': 'video', 'prompt': 'A slow push in'}))
        folder = jobs.prepare(request, self.root / 'jobs', self.config)
        job = jobs.load_json(folder / 'job.json')
        job.update(state='submitted', provider_result={'task_id': 'task-123456', 'model': routes.MODELS['kie']['video']})
        jobs.atomic_json(folder / 'job.json', job)
        with patch.object(routes, 'status', return_value={'code': 200, 'msg': 'success', 'data': {'taskId': 'task-123456', 'state': 'generating'}}), \
             patch.object(routes, 'result', return_value={'resultUrls': ['https://example.com/one.mp4']}):
            self.assertEqual(jobs.status(folder)['last_status']['data']['state'], 'generating')
            self.assertEqual(jobs.collect_aggregator(folder)['state'], 'ready_to_download')
            self.assertTrue((folder / 'aggregator-result.json').exists())


if __name__ == '__main__':
    unittest.main()
