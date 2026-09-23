"""Offline tests for the Tesseract overlay bridge; no station, no network, no renderer."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tesseract_overlay as tess


class CleanFamilyTests(unittest.TestCase):
    def test_strips_periods_spaces_and_nonascii(self):
        self.assertEqual(tess.clean_family('Almoni Tzar DL 4.0 AAA'), 'AlmoniTzarDL40AAA')
        self.assertEqual(tess.clean_family('Kedem-Sans_Black'), 'KedemSansBlack')
        self.assertEqual(tess.clean_family('פונט עברי'), 'BrandFont')  # non-ASCII -> safe default
        self.assertEqual(tess.clean_family('Inter'), 'Inter')


class TextActionTests(unittest.TestCase):
    def test_action_shape_and_centering(self):
        actions = tess._text_action('שלום', 'BrandX', 'Regular', 120, (1080, 1920), (1, 1, 1, 1))
        self.assertEqual(len(actions), 1)
        a = actions[0]
        self.assertEqual((a['type'], a['compositionId'], a['layerId']), ('createFxTextLayer', 'main', 1))
        st = a['sourceText']
        self.assertEqual((st['fontFamily'], st['fontStyle'], st['fontSize']), ('BrandX', 'Regular', 120))
        self.assertEqual(st['text'], 'שלום')
        self.assertTrue(st['boxText'])
        self.assertEqual(st['justification'], 'center')
        # box fits inside the canvas with a margin
        self.assertLess(st['boxSize'][0], 1080)
        self.assertEqual(st['fillColor'], [1, 1, 1, 1])


class MakeTitleOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.out = Path(self.temp.name).resolve() / 'overlays'
        self.config = {'ssh_alias': 'ai-station', 'tsrct': 'X:/tsrct.cmd', 'work_root': 'C:/w'}

    def tearDown(self):
        self.temp.cleanup()

    def test_overlay_builds_actions_and_prores_export(self):
        captured = {}

        def fake_prepare(font_path, out_dir):
            return {'family': 'BrandX', 'style': 'Regular', 'ttf': str(Path(out_dir) / 'BrandX.ttf'),
                    'source': str(font_path), 'source_family': 'Brand X', 'source_style': 'Bold'}

        def fake_ssh_ps(config, ps, timeout=300):
            captured['ps'] = ps
            return 'PREVIEW 100\nEXPORT 200'

        def fake_from(config, remote, local, timeout=600):
            Path(local).write_bytes(b'rendered bytes')  # so sha256_file finds a file

        with patch.object(tess, 'prepare_font', fake_prepare), \
             patch.object(tess, 'scp_to_station', lambda *a, **k: None), \
             patch.object(tess, 'ssh_ps', fake_ssh_ps), \
             patch.object(tess, 'scp_from_station', fake_from):
            report = tess.make_title('שַׁבָּת שָׁלוֹם', 'brand.otf', 'shabbat', self.out,
                                     overlay=True, config=self.config)

        # the overlay export must be a transparent ProRes solo of the title layer
        self.assertIn('--format prores --fx-solo main:1', captured['ps'])
        self.assertIn('import-font', captured['ps'])
        # actions file written with the normalized family and the Hebrew text
        actions = json.loads((self.out / 'shabbat-actions.json').read_text(encoding='utf-8'))
        self.assertEqual(actions[0]['sourceText']['fontFamily'], 'BrandX')
        self.assertEqual(actions[0]['sourceText']['text'], 'שַׁבָּת שָׁלוֹם')
        # report records a MOV export with a hash and is not treated as acceptance
        self.assertTrue(report['export'].endswith('.mov'))
        self.assertEqual(report['export_kind'], 'ProRes 4444 MOV (alpha)')
        self.assertTrue(report['export_sha256'])
        self.assertFalse(report['ai_advisory'])

    def test_default_mp4_skips_resize_roundtrip(self):
        with patch.object(tess, 'prepare_font', lambda f, d: {'family': 'BrandX', 'style': 'Regular',
                                                              'ttf': str(Path(d) / 'BrandX.ttf'), 'source': f,
                                                              'source_family': 'B', 'source_style': 'R'}), \
             patch.object(tess, 'scp_to_station', lambda *a, **k: None), \
             patch.object(tess, 'scp_from_station', lambda c, r, l, timeout=600: Path(l).write_bytes(b'x')):
            seen = {}
            with patch.object(tess, 'ssh_ps', lambda c, ps, timeout=300: seen.update(ps=ps) or 'PREVIEW 1\nEXPORT 2'):
                r = tess.make_title('שלום', 'brand.otf', 'plain', self.out, config=self.config)
        # default 1080x1920 / 3s: no checkout/commit round-trip, and an MP4 export
        self.assertNotIn('project checkout', seen['ps'])
        self.assertNotIn('--fx-solo', seen['ps'])
        self.assertTrue(r['export'].endswith('.mp4'))

    def test_name_must_be_ascii_slug(self):
        with self.assertRaisesRegex(ValueError, 'ASCII slug'):
            tess.make_title('שלום', 'brand.otf', 'לא-חוקי', self.out, config=self.config)


if __name__ == '__main__':
    unittest.main()
