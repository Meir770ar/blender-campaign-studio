"""Boundary tests for local production contracts; no paid services or media renders."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from studio import main, validate_plan, write_new


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / 'image.png').write_bytes(b'contract fixture, not decoded')
        self.plan = {'version': 1, 'width': 640, 'height': 360, 'fps': 24, 'frames': 72,
                     'clips': [{'id': 'base', 'kind': 'image', 'path': 'image.png',
                                'start': 1, 'duration': 72, 'channel': 1}]}

    def tearDown(self):
        self.temp.cleanup()

    def validate(self):
        path = self.root / 'plan.json'
        path.write_text(json.dumps(self.plan), encoding='utf-8')
        return validate_plan(path, probe=False)

    def test_normal_plan_resolves_relative_path(self):
        plan, warnings = self.validate()
        self.assertEqual(plan['clips'][0]['path'], str(self.root / 'image.png'))
        self.assertEqual(warnings, [])

    def test_overlapping_channels_rejected(self):
        other = copy.deepcopy(self.plan['clips'][0])
        other['id'] = 'overlap'
        self.plan['clips'].append(other)
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.validate()

    def test_layered_visuals_allowed(self):
        other = copy.deepcopy(self.plan['clips'][0])
        other.update(id='overlay', channel=2, start=10, duration=30)
        self.plan['clips'].append(other)
        self.assertEqual(len(self.validate()[0]['clips']), 2)

    def test_gap_rejected(self):
        self.plan['clips'][0].update(start=2, duration=71)
        with self.assertRaisesRegex(ValueError, 'No visual'):
            self.validate()

    def test_overrun_rejected(self):
        self.plan['clips'][0]['duration'] = 73
        with self.assertRaises(ValueError):
            self.validate()

    def test_missing_source_rejected(self):
        self.plan['clips'][0]['path'] = 'missing.png'
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.validate()

    def test_remote_source_rejected(self):
        self.plan['clips'][0]['path'] = 'https://example.com/media.png'
        with self.assertRaisesRegex(ValueError, 'local file'):
            self.validate()

    def test_nan_opacity_rejected(self):
        self.plan['clips'][0]['opacity'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'finite'):
            self.validate()

    def test_fades_cannot_consume_entire_clip(self):
        self.plan['clips'][0].update(fade_in=36, fade_out=36)
        with self.assertRaisesRegex(ValueError, 'fades'):
            self.validate()

    def test_odd_delivery_dimensions_rejected(self):
        self.plan['width'] = 641
        with self.assertRaisesRegex(ValueError, 'even'):
            self.validate()

    def test_boolean_frame_rejected(self):
        self.plan['clips'][0]['start'] = True
        with self.assertRaisesRegex(ValueError, 'integer'):
            self.validate()

    def test_output_collision_preserves_original(self):
        path = self.root / 'result.txt'
        write_new(path, 'original')
        with self.assertRaises(FileExistsError):
            write_new(path, 'replacement')
        self.assertEqual(path.read_text(), 'original')

    def test_init_preserves_hebrew_and_refuses_reinitialization(self):
        project = self.root / 'production'
        idea = 'סרטון בעברית עם Blender — רעיון חופשי'
        main(['init', '--project', str(project), '--idea', idea])
        self.assertEqual((project / 'idea.txt').read_text(encoding='utf-8'), idea)
        self.assertTrue((project / 'planning/direction-v1.template.json').is_file())
        self.assertTrue((project / 'planning/shots-v1.template.json').is_file())
        self.assertTrue((project / 'reviews').is_dir())
        self.assertTrue((project / 'jobs').is_dir())
        state = json.loads((project / 'production.json').read_text(encoding='utf-8'))
        self.assertEqual(state['status'], 'intake')
        self.assertEqual(state['external_actions_authorized_by_initialization'], [])
        with self.assertRaises(FileExistsError):
            main(['init', '--project', str(project), '--idea', 'replacement'])
        self.assertEqual((project / 'idea.txt').read_text(encoding='utf-8'), idea)


if __name__ == '__main__':
    unittest.main(verbosity=2)
