"""Loudness gate binding for delivery QA; ffmpeg/ffprobe are mocked, no media is decoded."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import delivery_qa as dq

INFO = {'format': {'duration': '3.0'}, 'streams': [
    {'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p', 'width': 640, 'height': 360, 'avg_frame_rate': '24/1'},
    {'codec_type': 'audio', 'codec_name': 'aac'}]}
MEASURED = {'input_i': '-16.4', 'input_tp': '-1.7', 'input_lra': '6', 'input_thresh': '-27', 'target_offset': '0'}


class DeliveryQaTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video = self.root / 'final.mp4'
        self.video.write_bytes(b'encoded fixture')
        self.plan = {'version': 1, 'width': 640, 'height': 360, 'fps': 24, 'frames': 72,
                     'clips': [{'id': 'v', 'kind': 'image', 'path': 'x.png', 'start': 1, 'duration': 72, 'channel': 1},
                               {'id': 'a', 'kind': 'sound', 'path': 'x.wav', 'start': 1, 'duration': 72, 'channel': 2}]}
        self.patches = [patch.object(dq, 'inspect', return_value=INFO), patch.object(dq, 'run', return_value=('', '')),
                        patch.object(dq, 'loudness', return_value=dict(MEASURED))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def test_measured_but_ungated_is_flagged(self):
        report = dq.check(self.video, self.write('plan.json', self.plan))
        self.assertTrue(report['technical_pass'])
        self.assertEqual(report['audio_targets_source'], 'none')
        self.assertTrue(any('not gated' in w for w in report['warnings']))

    def test_audio_qa_targets_bind_to_delivery(self):
        qa = self.write('qa.json', {'target_lufs': -16, 'peak_limit': -1.5, 'pass': True})
        report = dq.check(self.video, self.write('plan.json', self.plan), audio_qa_path=qa)
        self.assertTrue(report['technical_pass'])
        self.assertEqual(report['audio_targets_source'], 'audio_qa')
        self.assertEqual(report['audio_qa']['sha256'], dq.sha256_file(qa))
        self.assertNotIn('warnings', report)

    def test_audio_qa_targets_fail_wrong_loudness(self):
        qa = self.write('qa.json', {'target_lufs': -14, 'peak_limit': -1.5, 'pass': True})
        report = dq.check(self.video, self.write('plan.json', self.plan), audio_qa_path=qa)
        self.assertFalse(report['technical_pass'])
        self.assertTrue(any(e.startswith('audio_target_lufs failed') for e in report['errors']))

    def test_plan_targets_take_precedence(self):
        plan = dict(self.plan, audio_target_lufs=-16, audio_true_peak_max=-1)
        qa = self.write('qa.json', {'target_lufs': -10, 'peak_limit': -3, 'pass': True})
        report = dq.check(self.video, self.write('plan.json', plan), audio_qa_path=qa)
        self.assertEqual(report['audio_targets_source'], 'plan+audio_qa')
        self.assertTrue(report['technical_pass'])

    def test_malformed_audio_qa_rejected(self):
        with self.assertRaisesRegex(ValueError, 'target_lufs'):
            dq.check(self.video, self.write('plan.json', self.plan), audio_qa_path=self.write('qa.json', {'pass': True}))


if __name__ == '__main__':
    unittest.main()
