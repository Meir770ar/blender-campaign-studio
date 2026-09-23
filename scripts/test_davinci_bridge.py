"""Offline contract tests for the DaVinci Resolve hand-off; no Resolve, ffprobe or network."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

import davinci_bridge as bridge
from studio import validate_plan


def fake_probe(path):
    name = Path(path).name
    if name.endswith('.png'):
        return {'width': 640, 'height': 360, 'duration_seconds': None, 'audio_channels': 0}
    if name.endswith('.wav'):
        return {'width': None, 'height': None, 'duration_seconds': '4.0', 'audio_channels': 2}
    return {'width': 640, 'height': 360, 'duration_seconds': '5.0', 'audio_channels': 1}


class FakeItem:
    def __init__(self, start, duration, left=0, online=True):
        self._start, self._duration, self._left, self._online = start, duration, left, online

    def GetStart(self):
        return self._start

    def GetDuration(self):
        return self._duration

    def GetLeftOffset(self):
        return self._left

    def GetMediaPoolItem(self):
        return object() if self._online else None


class FakeTimeline:
    def __init__(self, name, start, frames, tracks, uid='tl-1'):
        self.name, self.start, self.frames, self.tracks, self.uid = name, start, frames, tracks, uid

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.uid

    def GetStartFrame(self):
        return self.start

    def GetEndFrame(self):
        return self.start + self.frames

    def GetTrackCount(self, kind):
        return len(self.tracks.get(kind, []))

    def GetItemListInTrack(self, kind, index):
        return self.tracks[kind][index - 1]


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ('clip.mp4', 'כותרת ראשית.png', 'music.wav'):
            (self.root / name).write_bytes(b'fixture bytes, not decoded')
        self.plan = {'version': 1, 'width': 640, 'height': 360, 'fps': 24, 'frames': 96, 'clips': [
            {'id': 'A', 'kind': 'movie', 'path': 'clip.mp4', 'start': 1, 'duration': 48, 'channel': 1, 'source_start': 12},
            {'id': 'B', 'kind': 'movie', 'path': 'clip.mp4', 'start': 49, 'duration': 48, 'channel': 1, 'fade_in': 6},
            {'id': 'title', 'kind': 'image', 'path': 'כותרת ראשית.png', 'start': 25, 'duration': 40, 'channel': 3,
             'opacity': 0.8, 'motion': 'fade-rise'},
            {'id': 'music', 'kind': 'sound', 'path': 'music.wav', 'start': 1, 'duration': 96, 'channel': 5,
             'volume': 0.5, 'volume_keys': [[0, 0.5], [80, 0.1]]}]}
        self.plan_path = self.root / 'plan.json'
        self.plan_path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def build(self, name='CUT_v001'):
        plan, _ = validate_plan(self.plan_path, probe=False)
        return bridge.build_sequence(plan, name, probe=fake_probe)

    def test_tracks_follow_channels_and_frames_are_zero_based(self):
        xml, manifest = self.build()
        root = ElementTree.fromstring(xml.split('\n', 2)[2])  # skip declaration + doctype
        video_tracks = root.findall('./sequence/media/video/track')
        audio_tracks = root.findall('./sequence/media/audio/track')
        self.assertEqual((len(video_tracks), len(audio_tracks)), (2, 1))
        first = video_tracks[0].findall('clipitem')
        self.assertEqual([c.find('name').text for c in first], ['A', 'B'])
        self.assertEqual((first[0].find('start').text, first[0].find('end').text), ('0', '48'))
        self.assertEqual((first[0].find('in').text, first[0].find('out').text), ('12', '60'))
        self.assertEqual(root.find('./sequence/duration').text, '96')
        self.assertEqual(root.find('./sequence/timecode/frame').text, str(3600 * 24))
        self.assertEqual(manifest['expected_items'][0]['timeline_start'], 3600 * 24)
        self.assertEqual(manifest['expected_items'][2]['track_index'], 2)

    def test_file_defined_once_then_referenced(self):
        xml, manifest = self.build()
        self.assertEqual(xml.count('<file id="file-1">'), 1)
        self.assertEqual(xml.count('<file id="file-1"/>'), 1)
        self.assertEqual(manifest['media'][str(self.root / 'clip.mp4')]['frames'], 120)
        self.assertEqual(manifest['media'][str(self.root / 'כותרת ראשית.png')]['frames'], 40)

    def test_hebrew_and_space_paths_are_percent_encoded_urls(self):
        xml, _ = self.build()
        self.assertIn('%D7%9B%D7%95%D7%AA%D7%A8%D7%AA%20%D7%A8%D7%90%D7%A9%D7%99%D7%AA.png', xml)
        self.assertIn('<pathurl>file:///', xml)
        self.assertNotIn('\\', xml.split('<pathurl>')[1].split('</pathurl>')[0])

    def test_static_levels_mapped_and_dynamic_features_reported(self):
        xml, manifest = self.build()
        self.assertIn('<value>80</value>', xml)
        self.assertIn('<value>0.5</value>', xml)
        reported = {(u['clip'], u['field']) for u in manifest['unmapped']}
        self.assertEqual(reported, {('B', 'fade_in'), ('title', 'motion'), ('music', 'volume_keys')})
        for entry in manifest['unmapped']:
            self.assertTrue(entry['apply_in_resolve'])

    def test_timeline_name_rules(self):
        for bad in ('', ' CUT', 'a/b', 'x<y', 'q"r', None):
            with self.assertRaises(ValueError):
                bridge.validate_timeline_name(bad)
        self.assertEqual(bridge.validate_timeline_name('CUT_v001 (מחוברים)'), 'CUT_v001 (מחוברים)')

    def test_unknown_movie_duration_is_refused(self):
        def no_duration(path):
            info = fake_probe(path)
            info['duration_seconds'] = None
            return info
        plan, _ = validate_plan(self.plan_path, probe=False)
        with self.assertRaisesRegex(ValueError, 'duration unknown'):
            bridge.build_sequence(plan, 'CUT_v001', probe=no_duration)

    def test_export_writes_manifest_and_refuses_existing_directory(self):
        out = self.root / 'handoff-v001'
        manifest = bridge.export_xml(self.plan_path, out, 'CUT_v001', probe=fake_probe)
        self.assertTrue((out / 'sequence.xml').is_file())
        written = json.loads((out / 'handoff-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(written['sequence_sha256'], manifest['sequence_sha256'])
        self.assertEqual(written['plan_sha256'], manifest['plan_sha256'])
        with self.assertRaises(FileExistsError):
            bridge.export_xml(self.plan_path, out, 'CUT_v002', probe=fake_probe)

    def test_verify_passes_matching_timeline_and_flags_drift(self):
        _, manifest = self.build()
        base = 3600 * 24
        good = FakeTimeline('CUT_v001', base, 96, {
            'video': [[FakeItem(base, 48, 12), FakeItem(base + 48, 48)], [FakeItem(base + 24, 40)]],
            'audio': [[FakeItem(base, 96)]]})
        report = bridge.verify_timeline(good, manifest)
        self.assertEqual(report['errors'], [])
        self.assertTrue(report['technical_pass'])
        self.assertTrue(report['creative_review_required'])
        shifted = FakeTimeline('CUT_v001', 0, 96, {
            'video': [[FakeItem(0, 48, 12), FakeItem(48, 48)], [FakeItem(24, 40)]], 'audio': [[FakeItem(0, 96)]]})
        self.assertEqual(bridge.verify_timeline(shifted, manifest)['errors'], [], 'a different timeline start offset is not drift')
        drift = FakeTimeline('CUT_v001', base, 90, {
            'video': [[FakeItem(base, 48, 0), FakeItem(base + 48, 40)], [FakeItem(base + 24, 40, online=False)]],
            'audio': []})
        errors = bridge.verify_timeline(drift, manifest)['errors']
        self.assertTrue(any('spans 90' in e for e in errors))
        self.assertTrue(any('A: source in 0' in e for e in errors))
        self.assertTrue(any('B: duration 40' in e for e in errors))
        self.assertTrue(any('title: media offline' in e for e in errors))
        self.assertTrue(any('audio tracks' in e for e in errors))
        self.assertTrue(any("music: no item" in e for e in errors))

    def test_import_refuses_unsaved_project_and_repeated_name(self):
        out = self.root / 'handoff'
        bridge.export_xml(self.plan_path, out, 'CUT_v001', probe=fake_probe)
        manifest = out / 'handoff-manifest.json'

        class FakeProject:
            def __init__(self, name, timelines):
                self.name, self.timelines = name, timelines

            def GetName(self):
                return self.name

            def GetTimelineCount(self):
                return len(self.timelines)

            def GetTimelineByIndex(self, index):
                return self.timelines[index - 1]

        class FakeResolve:
            def __init__(self, project):
                self.project = project

            def GetProjectManager(self):
                resolve = self
                return type('PM', (), {'GetCurrentProject': lambda s: resolve.project})()

        with self.assertRaisesRegex(ValueError, 'named, saved project'):
            bridge.import_sequence(manifest, self.root / 'r1.json', resolve=FakeResolve(FakeProject('Untitled Project', [])))
        existing = FakeTimeline('CUT_v001', 0, 96, {'video': [], 'audio': []})
        with self.assertRaisesRegex(ValueError, 'already exists'):
            bridge.import_sequence(manifest, self.root / 'r2.json', resolve=FakeResolve(FakeProject('Campaign', [existing])))
        (out / 'sequence.xml').write_text('<changed/>', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed after export'):
            bridge.import_sequence(manifest, self.root / 'r3.json', resolve=FakeResolve(FakeProject('Campaign', [])))

    def test_doctor_reports_missing_registrations_without_live_call(self):
        report = bridge.doctor(home=self.root, live=False)
        self.assertFalse(report['claude_code']['configured'])
        self.assertFalse(report['codex']['configured'])
        self.assertFalse(report['ready'])
        server = bridge.connection_config()['mcp_server']
        (self.root / '.claude.json').write_text(json.dumps({'mcpServers': {server: {'command': str(self.root / 'clip.mp4'), 'args': []}}}), encoding='utf-8')
        (self.root / '.codex').mkdir()
        toml = "[mcp_servers.%s]\ncommand = '%s'\n" % (server, self.root / 'clip.mp4')  # TOML literal string, as Codex writes it
        (self.root / '.codex' / 'config.toml').write_text(toml, encoding='utf-8')
        report = bridge.doctor(home=self.root, live=False)
        self.assertTrue(report['claude_code']['configured'] and report['claude_code']['command_exists'])
        self.assertTrue(report['codex']['configured'] and report['codex']['command_exists'])


class FakeProc:
    def __init__(self, stdout=b'', stderr=b'', returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class FakeSSH:
    """Records every ssh/scp call and answers the station-helper commands the way the station would."""

    def __init__(self, import_report=None, error=None):
        self.calls, self.import_payload = [], None
        self.import_report, self.error = import_report, error

    def __call__(self, argv, input=None, capture_output=False, timeout=None, stdin=None, stdout=None, stderr=None):
        argv = [str(a) for a in argv]
        self.calls.append(argv)

        def emit(obj, returncode=0):
            data = json.dumps(obj).encode('utf-8')
            if stdout is not None and hasattr(stdout, 'write'):
                stdout.write(data)  # the bridge redirects ssh stdout to a file, then reads it back
            return FakeProc(stdout=data, returncode=returncode)

        if argv[0] == 'scp':
            return FakeProc()
        if argv[0] == 'ssh' and argv[-1].startswith('if not exist'):
            return FakeProc()
        if argv[0] == 'ssh' and '--payload-b64' in argv:
            command = argv[argv.index('--payload-b64') - 1]
            payload = json.loads(base64.b64decode(argv[argv.index('--payload-b64') + 1]).decode('utf-8'))
            if self.error and command in ('doctor', 'project', 'import'):
                return emit({'error': self.error}, returncode=1)
            if command == 'import':
                self.import_payload = payload
                return emit(self.import_report)
            if command == 'doctor':
                return emit({'ready': True, 'errors': [], 'resolve': {'product': 'DaVinci Resolve Studio'}})
            if command == 'project':
                return emit({**payload, 'action': 'created'})
        return FakeProc()


class StationRouteTests(unittest.TestCase):
    """Route the finishing to the VIDEO STATION: media-path remap and the SSH orchestration, no network."""

    CONFIG = {'ssh_alias': 'ai-station', 'root': 'D:/video-productions-archive', 'python': 'python',
              'scripting': dict(bridge.DEFAULT_SCRIPTING), 'mcp_server': 'davinci-resolve-station',
              'edition_required': 'DaVinci Resolve Studio'}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / 'campaign-2026'
        (self.project / 'media').mkdir(parents=True)
        for name in ('clip.mp4', 'title.png', 'music.wav'):
            (self.project / 'media' / name).write_bytes(b'fixture bytes, not decoded')
        self.plan = {'version': 1, 'width': 640, 'height': 360, 'fps': 24, 'frames': 96, 'clips': [
            {'id': 'A', 'kind': 'movie', 'path': 'media/clip.mp4', 'start': 1, 'duration': 96, 'channel': 1, 'source_start': 12},
            {'id': 'title', 'kind': 'image', 'path': 'media/title.png', 'start': 25, 'duration': 40, 'channel': 3, 'opacity': 0.8},
            {'id': 'music', 'kind': 'sound', 'path': 'media/music.wav', 'start': 1, 'duration': 96, 'channel': 5, 'volume': 0.5}]}
        self.plan_path = self.project / 'plan.json'
        self.plan_path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding='utf-8')
        self.station_root = 'D:/video-productions-archive/campaign-2026'

    def tearDown(self):
        self.temp.cleanup()

    def export_station(self, name='CUT_v001'):
        return bridge.export_xml(self.plan_path, self.project / 'handoff', name, probe=fake_probe,
                                 path_map=(self.project.resolve().as_posix(), self.station_root))

    def test_remap_rewrites_only_paths_under_the_production_root(self):
        m = ('<productions>/proj', 'D:/video-productions-archive/proj')
        self.assertEqual(bridge.remap_path('<productions>/proj/a/b.mp4', m), 'D:/video-productions-archive/proj/a/b.mp4')
        self.assertEqual(bridge.remap_path('<productions>/proj', m), 'D:/video-productions-archive/proj')
        self.assertEqual(bridge.remap_path('C:/elsewhere/x.mp4', m), 'C:/elsewhere/x.mp4', 'media outside the production root is left for the offline check to catch')
        self.assertEqual(bridge.remap_path('C:/p/x.mp4', None), 'C:/p/x.mp4')

    def test_export_station_writes_station_pathurls_and_keeps_local_hashes(self):
        manifest = self.export_station()
        self.assertEqual(manifest['finishing_host'], 'station')
        self.assertEqual(manifest['target_media_root'], self.station_root)
        xml = (self.project / 'handoff' / 'sequence.xml').read_text(encoding='utf-8')
        self.assertIn('<pathurl>file:///D:/video-productions-archive/campaign-2026/media/clip.mp4</pathurl>', xml)
        self.assertNotIn(self.temp.name.replace('\\', '/'), xml, 'no laptop path may leak into a station hand-off')
        self.assertTrue(all(Path(p).is_file() for p in manifest['media']), 'media is keyed by the real local path so the same bytes verify on the station')
        self.assertTrue(all('sha256' in meta for meta in manifest['media'].values()))

    def test_laptop_export_is_unchanged_by_the_new_parameter(self):
        manifest = bridge.export_xml(self.plan_path, self.project / 'handoff-laptop', 'CUT_v001', probe=fake_probe)
        self.assertEqual(manifest['finishing_host'], 'laptop')
        self.assertIsNone(manifest['target_media_root'])
        xml = (self.project / 'handoff-laptop' / 'sequence.xml').read_text(encoding='utf-8')
        self.assertIn(self.project.resolve().as_posix() + '/media/clip.mp4', xml)

    def test_production_path_map_requires_ascii_slug(self):
        hebrew = Path(self.temp.name) / 'קמפיין'
        hebrew.mkdir()
        with self.assertRaisesRegex(ValueError, 'ASCII slug'):
            bridge.production_path_map(self.CONFIG, hebrew)
        local_root, target, slug = bridge.production_path_map(self.CONFIG, self.project)
        self.assertEqual((slug, target), ('campaign-2026', self.station_root))

    def test_station_import_pushes_handoff_and_imports_on_the_station(self):
        self.export_station()
        manifest_path = self.project / 'handoff' / 'handoff-manifest.json'
        out_path = self.project / 'handoff' / 'import-report.json'
        fake = FakeSSH({'technical_pass': True, 'timeline_name': 'CUT_v001', 'errors': [], 'host': 'station'})
        with patch.object(bridge, 'station_config', return_value=self.CONFIG), \
             patch.object(bridge.subprocess, 'run', fake):
            report = bridge.station_import(self.project, manifest_path, out_path)
        self.assertTrue(report['technical_pass'])
        self.assertTrue(out_path.is_file(), 'a local copy of the verification is written next to the hand-off')
        scp_dests = [c[-1] for c in fake.calls if c and c[0] == 'scp']
        self.assertTrue(any(d.endswith('D:/video-productions-archive/campaign-2026/handoff/sequence.xml') for d in scp_dests))
        self.assertTrue(any(d.endswith('D:/video-productions-archive/campaign-2026/handoff/handoff-manifest.json') for d in scp_dests))
        self.assertEqual(fake.import_payload['xml'], 'D:/video-productions-archive/campaign-2026/handoff/sequence.xml')
        self.assertEqual(fake.import_payload['manifest'], 'D:/video-productions-archive/campaign-2026/handoff/handoff-manifest.json')
        self.assertEqual(fake.import_payload['out'], 'D:/video-productions-archive/campaign-2026/handoff/import-report.json')

    def test_station_import_refuses_a_laptop_manifest(self):
        bridge.export_xml(self.plan_path, self.project / 'handoff-laptop', 'CUT_v001', probe=fake_probe)
        manifest_path = self.project / 'handoff-laptop' / 'handoff-manifest.json'
        with patch.object(bridge, 'station_config', return_value=self.CONFIG):
            with self.assertRaisesRegex(ValueError, 'exported for the laptop'):
                bridge.station_import(self.project, manifest_path, self.project / 'r.json')

    def test_remote_call_surfaces_a_station_error(self):
        fake = FakeSSH(error='Resolve on the station refused the connection')
        with patch.object(bridge.subprocess, 'run', fake):
            with self.assertRaisesRegex(ValueError, 'refused the connection'):
                bridge.remote_call(self.CONFIG, 'doctor', {'scripting': self.CONFIG['scripting']})


if __name__ == '__main__':
    unittest.main()
