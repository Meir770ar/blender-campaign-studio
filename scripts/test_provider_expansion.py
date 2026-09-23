import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import grok_contract as grok
import heygen_bridge as heygen
import provider_jobs as jobs
from activate_grok_patch import package


class ProviderExpansion(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.image = self.root / 'frame.png'
        self.image.write_bytes(b'reference fixture')
        self.config = {'grok': {'model': 'xai/grok-imagine-video', 'preferred_model': 'xai/grok-imagine-video-1.5'},
                       'heygen': {'cli_entry': 'fixture.mjs'}}

    def request(self, **values):
        return {'provider': 'grok', 'prompt': 'A restrained camera push toward the subject.', **values}

    def validate(self, value):
        return jobs.validate_request(value, self.root, self.config)['request']

    def prepare(self, request):
        path = self.root / 'request.json'
        jobs.atomic_json(path, request)
        return jobs.prepare(path, self.root / 'jobs', self.config)

    def test_1080_and_native_audio_contract(self):
        r = self.validate(self.request(resolution='1080P', references=[str(self.image)], audio=True))
        self.assertEqual(r['model'], 'xai/grok-imagine-video-1.5')
        self.assertEqual(r['references'][0]['role'], 'first_frame')
        args = grok.arguments(r, self.config['grok'], 'id', lambda ref: '/media/ref.png')
        self.assertEqual(args['resolution'], '1080P')
        self.assertEqual(args['imageRoles'], ['first_frame'])
        self.assertTrue(args['audio'])

    def test_frame_combinations_and_unsupported_1080_fail_early(self):
        refs = [{'path': str(self.image), 'role': role} for role in ('first_frame', 'last_frame', 'reference_image')]
        r = self.validate(self.request(references=refs, duration_seconds=15))
        self.assertEqual(r['mode'], 'reference-to-video')
        for invalid in [self.request(references=refs, resolution='1080P'),
                        self.request(model='xai/grok-imagine-video', references=refs),
                        self.request(references=refs + [refs[0]]), self.request(duration_seconds=True)]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.validate(invalid)

    def test_moved_image_keeps_fingerprint_but_role_and_bytes_change_it(self):
        first = self.prepare(self.request(references=[str(self.image)]))
        other = self.root / 'moved.png'; other.write_bytes(self.image.read_bytes())
        self.assertEqual(first, self.prepare(self.request(references=[str(other)])))
        self.assertNotEqual(first, self.prepare(self.request(references=[{'path': str(other), 'role': 'reference_image'}])))
        other.write_bytes(b'changed')
        self.assertNotEqual(first, self.prepare(self.request(references=[str(other)])))

    def test_identical_first_last_frames_keep_distinct_native_paths(self):
        r = self.validate(self.request(references=[{'path': str(self.image), 'role': 'first_frame'}, {'path': str(self.image), 'role': 'last_frame'}]))
        self.assertNotEqual(*[grok.remote_reference_path(ref) for ref in r['references']])
        with self.assertRaisesRegex(ValueError, 'Duplicate image bytes'):
            self.validate(self.request(references=[str(self.image), str(self.image)]))

    def test_video_edit_extend_validate_source_and_omit_inherited_controls(self):
        r = self.validate(self.request(mode='edit', video_url='https://vidgen.x.ai/source.mp4', source_duration_seconds=6))
        self.assertNotIn('duration_seconds', r)
        self.assertNotIn('audio', r)
        self.assertEqual(r['model'], 'xai/grok-imagine-video')
        args = grok.arguments(r, self.config['grok'], 'id', lambda _: None)
        self.assertEqual(args['videoRoles'], ['reference_video'])
        self.assertNotIn('resolution', args)
        for invalid in [dict(r, resolution='1080P'), dict(r, source_duration_seconds=9),
                        dict(r, video_url='https://127.0.0.1/input.mp4'), dict(r, video_url='http://host/input.mp4')]:
            # Normalized refs must be converted back to user input for this boundary check.
            with self.assertRaises(ValueError):
                grok.validate(invalid, self.root, self.config['grok'])

    def test_capability_probe_is_not_generation_evidence(self):
        r = self.validate(self.request(resolution='1080P'))
        cap = {'capabilities': {'generate': {'resolutions': ['1080P'], 'supportsAudio': True}}}
        with self.assertRaisesRegex(ValueError, 'not active'):
            grok.ensure_capability(r, cap, {})
        grok.ensure_capability(r, cap, {'campaign_contract': grok.CONTRACT})
        with self.assertRaisesRegex(ValueError, 'resolution'):
            grok.ensure_capability(r, {'capabilities': {'generate': {'resolutions': ['720P']}}}, {'campaign_contract': grok.CONTRACT})

    def test_low_resolution_output_is_preserved_for_review_and_cannot_resubmit(self):
        folder = self.prepare(self.request(resolution='1080P'))
        job = jobs.load_json(folder / 'job.json')
        job.update(state='submitted', provider_result={'path': '/home/node/.openclaw/media/result.mp4'})
        job['connection']['container'] = 'fixture'
        jobs.atomic_json(folder / 'job.json', job)
        with patch.object(jobs, 'ssh', return_value=b'received video'), patch('studio.ffprobe', return_value={'streams': [{'codec_type': 'video', 'width': 1280, 'height': 720}]}):
            with self.assertRaisesRegex(ValueError, 'below requested'):
                jobs.collect_grok(folder)
        saved = jobs.load_json(folder / 'job.json')
        self.assertEqual(saved['state'], 'received_needs_review')
        self.assertTrue((folder / 'grok-1.mp4').exists())
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            jobs.execute(folder, self.config, 1)

    def test_media_qa_checks_audio_shape_and_duration(self):
        r = self.validate(self.request(resolution='1080P', audio=True))
        media = {'duration_seconds': '6.0', 'streams': [{'codec_type': 'video', 'width': 1920, 'height': 1080}, {'codec_type': 'audio'}]}
        self.assertEqual(grok.media_qa(media, r)['creative_review'], 'pending')
        with self.assertRaisesRegex(ValueError, 'audio'):
            grok.media_qa({**media, 'streams': media['streams'][:1]}, r)
        with self.assertRaisesRegex(ValueError, 'duration'):
            grok.media_qa({**media, 'duration_seconds': '2'}, r)

    def test_heygen_preparation_forbids_execute_and_hashes_file_inputs(self):
        request = {'provider': 'heygen', 'operation': 'avatar-photo-upload', 'options': {'file': str(self.image)}}
        with patch.object(heygen, 'cli', return_value={'preview': True, 'fingerprint': 'f' * 64}):
            first = self.prepare(request)
            moved = self.root / 'moved.png'; moved.write_bytes(self.image.read_bytes())
            self.assertEqual(first, self.prepare({**request, 'options': {'file': str(moved)}}))
        for key in ['execute', 'allow-credits', 'out']:
            with self.assertRaisesRegex(ValueError, 'controller'):
                heygen.validate({**request, 'options': {key: True}}, self.root, self.config['heygen'])

    def test_heygen_modified_inputs_block_before_submit(self):
        r = {'provider': 'heygen', 'operation': 'avatar-photo-upload', 'options': {'file': str(self.image)}}
        with patch.object(heygen, 'cli', return_value={'preview': True, 'fingerprint': 'f' * 64}):
            normalized = heygen.validate(r, self.root, self.config['heygen'])
        self.image.write_bytes(b'changed after approval')
        with patch.object(heygen, 'cli') as call, self.assertRaisesRegex(ValueError, 'changed after approval'):
            heygen.preflight(normalized, self.config['heygen'])
        call.assert_not_called()

    def test_heygen_execute_reuses_cli_receipt_and_never_repeats(self):
        r = {'provider': 'heygen', 'operation': 'avatar-photo-upload', 'options': {'file': str(self.image)}}
        with patch.object(heygen, 'cli', return_value={'preview': True, 'fingerprint': 'f' * 64}):
            folder = self.prepare(r)
        jobs.authorize(folder, 'Approved exact fixture upload', 1, 'upload')
        with patch.object(heygen, 'preflight'), patch.object(heygen, 'submit', return_value={'cli_receipt': {'state': 'accepted', 'ids': {'group_id': 'group'}}}) as submit:
            self.assertEqual(jobs.execute(folder, self.config, 1)['state'], 'submitted')
            with self.assertRaisesRegex(ValueError, 'already attempted'):
                jobs.execute(folder, self.config, 1)
        self.assertEqual(submit.call_count, 1)

    def test_heygen_ambiguous_failure_persists_unknown(self):
        r = {'provider': 'heygen', 'operation': 'avatar-photo-upload', 'options': {'file': str(self.image)}}
        with patch.object(heygen, 'cli', return_value={'preview': True, 'fingerprint': 'f' * 64}):
            folder = self.prepare(r)
        jobs.authorize(folder, 'Approved exact fixture upload', 1, 'upload')
        with patch.object(heygen, 'preflight'), patch.object(heygen, 'submit', side_effect=ValueError('timeout')):
            with self.assertRaisesRegex(ValueError, 'Reconcile'):
                jobs.execute(folder, self.config, 1)
        self.assertEqual(jobs.load_json(folder / 'job.json')['state'], 'unknown')

    def test_source_duration_checked_before_edit_submission(self):
        r = self.validate(self.request(mode='edit', video_url='https://vidgen.x.ai/source.mp4', source_duration_seconds=6))
        data = {'format': {'duration': '9.0'}, 'streams': [{'codec_type': 'video'}]}
        with patch.object(grok.shutil, 'which', return_value='ffprobe'), patch.object(grok.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(data).encode(), b'')):
            with self.assertRaisesRegex(ValueError, 'duration'):
                grok.inspect_video_input(r)

    def test_patch_and_rollback_manifests_are_exact_opposites(self):
        forward, reverse = package(), package(True)
        self.assertEqual(len(forward['files']), 2)
        for before, after in zip(forward['files'], reverse['files']):
            self.assertEqual(before['remote'], after['remote'])
            self.assertEqual(before['target_sha256'], after['expected_sha256'])
            self.assertEqual(before['expected_sha256'], after['target_sha256'])


if __name__ == '__main__':
    unittest.main()
