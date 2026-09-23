"""Offline tests for the Antigravity bridge; no node, no network, no subscription calls."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import antigravity as ag


class ExtractJsonTests(unittest.TestCase):
    def test_fenced_block(self):
        self.assertEqual(ag.extract_json('x ```json\n{"a": 1, "b": [2, 3]}\n``` y'), {'a': 1, 'b': [2, 3]})

    def test_bare_braces_nested(self):
        self.assertEqual(ag.extract_json('pre {"x": {"y": 1}} post'), {'x': {'y': 1}})

    def test_none_when_absent(self):
        self.assertIsNone(ag.extract_json('no json at all'))

    def test_none_on_malformed(self):
        self.assertIsNone(ag.extract_json('{"a": 1,,,}'))


class CallAgyArgvTests(unittest.TestCase):
    def _fake_run(self, stdout=b'{"ok": true}', returncode=0):
        calls = {}

        def run(argv, input=None, capture_output=False, timeout=None, env=None):
            calls['argv'] = [str(a) for a in argv]
            calls['input'] = input
            calls['env'] = env
            return types.SimpleNamespace(stdout=stdout, stderr=b'', returncode=returncode)
        return run, calls

    def test_text_argv_and_stdin(self):
        run, calls = self._fake_run(stdout='שלום'.encode('utf-8'))
        with patch.object(ag.subprocess, 'run', run):
            out = ag.call_agy('text', 'כתוב תסריט')
        self.assertEqual(out, 'שלום')
        self.assertEqual(calls['argv'][:3], ['node', str(ag.AGY_CALL), 'text'])
        self.assertNotIn('video', calls['argv'])
        self.assertEqual(calls['input'], 'כתוב תסריט'.encode('utf-8'))
        self.assertIn('AGY_CLOUDCODE', calls['env'])

    def test_video_argv_includes_media(self):
        with tempfile.TemporaryDirectory() as td:
            media = Path(td) / 'clip.mp4'
            media.write_bytes(b'not a real video')
            run, calls = self._fake_run()
            with patch.object(ag.subprocess, 'run', run):
                ag.call_agy('video', 'נתח', media=str(media))
            self.assertEqual(calls['argv'][2], 'video')
            self.assertEqual(Path(calls['argv'][3]), media.resolve())

    def test_failure_raises(self):
        run, _ = self._fake_run(stdout=b'', returncode=1)
        with patch.object(ag.subprocess, 'run', run):
            with self.assertRaisesRegex(ValueError, 'Antigravity call failed'):
                ag.call_agy('text', 'x')


class ScriptAndAnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def test_write_script_parses_and_records_provenance(self):
        brief = self.root / 'brief.md'
        brief.write_text('פרסומת קצרה למחוברים', encoding='utf-8')
        out = self.root / 'script.json'
        model_reply = '```json\n' + json.dumps({
            'logline': 'ל', 'duration_target_sec': 15, 'beats': ['a'],
            'scenes': [{'id': 'S1', 'purpose': 'p', 'visual': 'v', 'action': 'a',
                        'narration': 'n', 'on_screen_text': 't', 'sound': 's'}]}, ensure_ascii=False) + '\n```'
        with patch.object(ag, 'call_agy', return_value=model_reply):
            r = ag.write_script(brief, out, duration=15)
        self.assertTrue(out.is_file())
        self.assertEqual(len(r['script']['scenes']), 1)
        self.assertIsNone(r['raw'])
        self.assertEqual(r['provenance']['model'], ag.MODEL)
        self.assertFalse(r['provenance']['ai_advisory'])
        self.assertTrue(r['provenance']['parsed'])

    def test_script_keeps_raw_when_not_json(self):
        brief = self.root / 'brief.md'
        brief.write_text('x', encoding='utf-8')
        out = self.root / 'script.json'
        with patch.object(ag, 'call_agy', return_value='just prose, no json'):
            r = ag.write_script(brief, out)
        self.assertIsNone(r['script'])
        self.assertEqual(r['raw'], 'just prose, no json')
        self.assertFalse(r['provenance']['parsed'])

    def test_analyze_shot_has_fixes_and_per_tool_guidance(self):
        media = self.root / 'S1.mp4'
        media.write_bytes(b'bytes')
        out = self.root / 'review.json'
        reply = json.dumps({
            'summary': 's', 'matches_brief': True, 'continuity': 'c', 'emotional_read': 'e',
            'text_readability': 'r', 'audio_intelligible': True, 'defects': ['d'],
            'fixes': [{'issue': 'i', 'why': 'w', 'priority': 'high'}],
            'edit_blender': ['b1', 'b2'], 'edit_davinci': ['d1'], 'recommendation': 'revise', 'notes': 'n'},
            ensure_ascii=False)
        with patch.object(ag, 'call_agy', return_value=reply):
            r = ag.analyze_video(media, 'shot', out)
        self.assertTrue(out.is_file())
        self.assertEqual(len(r['analysis']['fixes']), 1)
        self.assertEqual(r['analysis']['edit_blender'], ['b1', 'b2'])
        self.assertEqual(r['analysis']['edit_davinci'], ['d1'])
        self.assertTrue(r['provenance']['ai_advisory'])
        self.assertEqual(r['provenance']['kind'], 'analyze-shot')

    def test_analyze_rejects_bad_kind(self):
        media = self.root / 'x.mp4'
        media.write_bytes(b'b')
        with self.assertRaisesRegex(ValueError, "kind must be"):
            ag.analyze_video(media, 'nope', self.root / 'o.json')

    def test_doctrines_route_to_both_tools(self):
        for doctrine in (ag.ANALYZE_SHOT_DOCTRINE, ag.ANALYZE_MASTER_DOCTRINE):
            self.assertIn('edit_blender', doctrine)
            self.assertIn('edit_davinci', doctrine)
            self.assertIn('fixes', doctrine)
        # script doctrine must not invent brand facts and must ask for structured scenes
        self.assertIn('scenes', ag.SCRIPT_DOCTRINE)
        self.assertIn('אל תמציא', ag.SCRIPT_DOCTRINE)


if __name__ == '__main__':
    unittest.main()
