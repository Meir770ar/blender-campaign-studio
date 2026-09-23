"""Genspark as a primary route: text-to-video or one first frame, no Grok parent required."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import provider_jobs as jobs


class GensparkPrimaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = {'genspark': {'route': 'existing_cli', 'cli_entry': 'fixture.js', 'model': 'xai/grok-imagine-video',
                                    'browser_url': 'https://www.genspark.ai/agents?type=video_generation_agent'}}
        self.ref = self.root / 'first.png'
        self.ref.write_bytes(b'fixture image')

    def validate(self, **fields):
        return jobs.validate_request({'provider': 'genspark', 'prompt': 'A quiet editing room at night, slow push-in.', **fields},
                                     self.root, self.config)['request']

    def test_text_to_video_and_first_frame_modes(self):
        r = self.validate(duration_seconds=5, resolution='1080P')
        self.assertEqual((r['mode'], r['references'], r['resolution']), ('text-to-video', [], '1080P'))
        r = self.validate(references=[str(self.ref)])
        self.assertEqual((r['mode'], r['resolution']), ('image-to-video', '720P'))
        for bad in (dict(references=[str(self.ref), str(self.ref)]), dict(references=[str(self.ref)], resolution='1080P'),
                    dict(resolution='4K'), dict(duration_seconds=16)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.validate(**bad)

    def test_primary_execute_sends_an_empty_image_list_and_records_once(self):
        path = self.root / 'request.json'
        path.write_text(json.dumps({'provider': 'genspark', 'prompt': 'A studio where lights switch on.', 'duration_seconds': 5,
                                    'aspect_ratio': '16:9', 'resolution': '720P', 'audio': False,
                                    'style_constraints': ['soft even daylight'], 'avoid': ['readable text']}), encoding='utf-8')
        folder = jobs.prepare(path, self.root / 'jobs', self.config)
        jobs.authorize(folder, 'user approved the demo pilot', 600, 'genspark credits')
        response = {'status': 'ok', 'data': {'generated_videos': [{'task_id': 't1', 'video_urls': ['https://www.genspark.ai/api/files/s/t1']}]}}
        with patch.object(jobs, 'probe', return_value={'cli_authenticated': True, 'cli_credit_balance': 5000}), \
             patch.object(jobs.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(response).encode(), b'')) as submit:
            result = jobs.execute(folder, self.config, 460)
        self.assertEqual(result['state'], 'submitted')
        payload = jobs.load_json(folder / 'genspark-submit.json')
        self.assertEqual((payload['image_urls'], payload['reference_mode'], payload['video_size']), ([], False, '720p'))
        self.assertIn('Style constraints: soft even daylight.', payload['query'])
        self.assertIn('Avoid: readable text.', payload['query'])
        self.assertEqual(submit.call_count, 1)
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            jobs.execute(folder, self.config, 460)


if __name__ == '__main__':
    unittest.main()
