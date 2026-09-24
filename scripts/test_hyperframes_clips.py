import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hyperframes_clips as hf

VERSION = '0.8.67\n'
DOCTOR = '✓ Version 0.8.67\n✓ Node.js v24\n✓ FFmpeg ffmpeg 8\n✓ Chrome ready\n'
VIDEO = {'duration_seconds': '3.0', 'streams': [{'codec_type': 'video', 'r_frame_rate': '24/1', 'width': 1920, 'height': 1080}]}


class HyperframesClips(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'motion-project'
        self.project.mkdir()
        (self.project / 'index.html').write_text('<div data-composition-id="main"></div>', encoding='utf-8')
        (self.root / 'plan.json').write_text(json.dumps({'fps': 24}), encoding='utf-8')
        self.cfg = {'cli': 'hyperframes', 'min_version': '0.8.67'}
        self.calls = []

    def fake_cli(self, check_code=0, render_code=0, produce=True):
        def run(cfg, args, timeout, cwd=None):
            self.calls.append(args)
            if args == ['--version']:
                return 0, VERSION
            if args == ['doctor']:
                return 0, DOCTOR
            if args[0] == 'check':
                return check_code, 'Layout\n  1 error(s)\nCheck failed' if check_code else 'ok'
            if args[0] == 'render':
                out = Path(args[args.index('--output') + 1])
                if produce:
                    out.write_bytes(b'mp4 fixture')
                return render_code, 'rendered'
            raise AssertionError(args)
        return run

    def test_doctor_reads_version_and_readiness(self):
        with patch.object(hf, 'run_cli', self.fake_cli()):
            health = hf.doctor(self.cfg)
        self.assertEqual((health['version'], health['render_ready'], health['chrome_ready']), ('0.8.67', True, True))
        missing = '✗ Chrome missing\n✓ FFmpeg\n✓ Node.js\n'
        with patch.object(hf, 'run_cli', lambda cfg, args, timeout, cwd=None: (0, VERSION if args == ['--version'] else missing)):
            health = hf.doctor(self.cfg)
        self.assertFalse(health['render_ready'])
        self.assertEqual(health['fix'], 'hyperframes browser ensure')
        with patch.object(hf, 'run_cli', self.fake_cli()):
            self.assertFalse(hf.doctor({**self.cfg, 'min_version': '0.9.0'})['version_ok'])

    def test_render_gates_on_check_then_renders_once_with_receipt(self):
        out = self.root / 'motion' / 'title.mp4'
        with patch.object(hf, 'run_cli', self.fake_cli()), patch.object(hf, 'ffprobe', return_value=VIDEO):
            receipt = hf.render(self.cfg, self.project, out, 24, quality='high', plan=self.root / 'plan.json',
                                variables='{"title": "שלום"}')
        render_calls = [c for c in self.calls if c[0] == 'render']
        self.assertEqual(len(render_calls), 1)
        self.assertIn('--strict', render_calls[0])
        self.assertEqual(render_calls[0][render_calls[0].index('--fps') + 1], '24')
        self.assertEqual(receipt['check']['exit_code'], 0)
        self.assertEqual(receipt['hyperframes'], '0.8.67')
        saved = json.loads((self.root / 'motion' / 'title.mp4.receipt.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['sha256'], receipt['sha256'])
        with patch.object(hf, 'run_cli', self.fake_cli()), patch.object(hf, 'ffprobe', return_value=VIDEO):
            with self.assertRaisesRegex(ValueError, 'Output exists'):
                hf.render(self.cfg, self.project, out, 24)

    def test_failed_check_blocks_render_unless_reason_recorded(self):
        out = self.root / 'a.mp4'
        with patch.object(hf, 'run_cli', self.fake_cli(check_code=1)), patch.object(hf, 'ffprobe', return_value=VIDEO):
            with self.assertRaisesRegex(ValueError, 'check failed'):
                hf.render(self.cfg, self.project, out, 24)
            self.assertFalse(any(c[0] == 'render' for c in self.calls))
            receipt = hf.render(self.cfg, self.project, out, 24,
                                skip_check_reason='static card: timeline does not advance by design')
        self.assertEqual(receipt['check'], {'skipped_reason': 'static card: timeline does not advance by design'})

    def test_input_contracts(self):
        with patch.object(hf, 'run_cli', self.fake_cli()), patch.object(hf, 'ffprobe', return_value=VIDEO):
            for kwargs, message in [({'fps': 30, 'plan': self.root / 'plan.json'}, 'differs from the plan fps'),
                                    ({'fps': 24, 'fmt': 'webm'}, 'must end with .webm'),
                                    ({'fps': 24, 'quality': 'best'}, 'quality must be'),
                                    ({'fps': 24, 'composition': '../outside.html'}, 'inside the project'),
                                    ({'fps': 24, 'variables': '[1]'}, 'JSON object'),
                                    ({'fps': 24, 'skip_check_reason': '  '}, 'needs the accepted finding')]:
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, message):
                    hf.render(self.cfg, self.project, self.root / 'x.mp4', **kwargs)
            with self.assertRaisesRegex(ValueError, 'differs from 24'):
                with patch.object(hf, 'ffprobe', return_value={'streams': [{'codec_type': 'video', 'r_frame_rate': '30/1'}]}):
                    hf.render(self.cfg, self.project, self.root / 'y.mp4', 24)
        with patch.object(hf, 'run_cli', self.fake_cli(produce=False)):
            with self.assertRaisesRegex(ValueError, 'did not produce'):
                hf.render(self.cfg, self.project, self.root / 'z.mp4', 24)


if __name__ == '__main__':
    unittest.main()
