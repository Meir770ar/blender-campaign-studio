"""Contract tests for the station archive; SSH/scp/sftp are replaced by a recording fake."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import station_archive as sa

CONFIG = {'ssh_alias': 'ai-station', 'root': 'D:/video-productions-archive', 'python': 'python'}


class FakeStation:
    """Answers the helper commands the way the station would; records every transport call."""

    def __init__(self):
        self.commands, self.files, self.manifest = [], {}, None
        self.hash_answers = None

    def __call__(self, command, timeout=300, input_bytes=None):
        command = [str(c) for c in command]
        self.commands.append(command)
        if command[0] == 'sftp':
            batch = Path(command[command.index('-b') + 1]).read_text(encoding='utf-8')
            for line in batch.splitlines():
                local, remote = line.split('"')[1], line.split('"')[3]
                self.files[remote] = sa.sha256_file(local)
            return ''
        if command[0] == 'scp' or (command[0] == 'ssh' and '--root' not in command):
            return ''
        sub = command[command.index('--root') - 1]
        root = command[command.index('--root') + 1]
        payload = json.loads(input_bytes.decode('utf-8')) if input_bytes else None
        if sub == 'manifest':
            return json.dumps(self.manifest or {'exists': False, 'files': {}})
        if sub == 'ensure-dirs':
            return json.dumps({'root': root, 'created': len(payload)})
        if sub == 'hash':
            if self.hash_answers is not None:
                return json.dumps(self.hash_answers)
            return json.dumps({r: ({'sha256': self.files[sa.sftp_path(root + '/' + r)], 'size': 0}
                                   if sa.sftp_path(root + '/' + r) in self.files else None) for r in payload})
        if sub == 'write-manifest':
            self.manifest = {'exists': True, 'files': payload['files']}
            return json.dumps({'manifest': root + '/archive-manifest.json', 'files': len(payload['files'])})
        if sub == 'free':
            return json.dumps({'free_bytes': 10 ** 12, 'total_bytes': 2 * 10 ** 12})
        raise AssertionError(command)


class StationArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / 'campaign-2026'
        for relative, data in (('assets/קליפ גלם.mp4', b'raw'), ('renders/v001/final.mp4', b'render'),
                               ('plan-v001.json', b'{}'), ('renders/v001/frame.png.writing', b'tmp'),
                               ('scripts/__pycache__/x.pyc', b'pyc')):
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.station = FakeStation()
        self.patcher = patch.object(sa, 'run', self.station)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def test_scan_excludes_temp_and_cache_and_uses_hash_cache(self):
        calls = []

        def counting(path):
            calls.append(path)
            return sa.sha256_file(path)
        first = sa.scan_local(self.project, hasher=counting)
        self.assertEqual(sorted(first['files']), ['assets/קליפ גלם.mp4', 'plan-v001.json', 'renders/v001/final.mp4'])
        self.assertEqual(len(calls), 3)
        second = sa.scan_local(self.project, hasher=counting)
        self.assertEqual(len(calls), 3, 'unchanged files are not re-hashed')
        self.assertEqual(second['hashed_now'], 0)
        (self.project / 'plan-v001.json').write_bytes(b'{"changed":1}')
        third = sa.scan_local(self.project, hasher=counting)
        self.assertEqual(third['hashed_now'], 1)

    def test_only_filters_top_level_folders(self):
        scan = sa.scan_local(self.project, only=['renders'])
        self.assertEqual(list(scan['files']), ['renders/v001/final.mp4'])
        self.assertIn('plan-v001.json', scan['skipped_by_only'])

    def test_push_uploads_verifies_and_records_then_second_push_is_idle(self):
        report = sa.push(self.project, config=CONFIG)
        self.assertTrue(report['technical_pass'])
        self.assertEqual(report['to_upload'], 3)
        self.assertEqual(sorted(report['verified']), sorted(report['verified']) and ['assets/קליפ גלם.mp4', 'plan-v001.json', 'renders/v001/final.mp4'])
        self.assertEqual(self.station.manifest['files'].keys(), report and set(report['verified']))
        batch_puts = [c for c in self.station.commands if c[0] == 'sftp']
        self.assertEqual(len(batch_puts), 1)
        self.assertTrue(any('/D:/video-productions-archive/campaign-2026/' in remote for remote in self.station.files))
        again = sa.push(self.project, config=CONFIG)
        self.assertEqual((again['to_upload'], again['unchanged']), (0, 3))
        self.assertFalse(any(c[0] == 'sftp' for c in self.station.commands[len(self.station.commands) - 3:]))
        reports = list((self.project / 'archive').glob('push-*.json'))
        self.assertEqual(len(reports), 2)

    def test_mismatch_is_not_recorded_and_fails(self):
        self.station.hash_answers = {'assets/קליפ גלם.mp4': {'sha256': 'deadbeef', 'size': 3},
                                     'plan-v001.json': None, 'renders/v001/final.mp4': {'sha256': sa.sha256_file(self.project / 'renders/v001/final.mp4'), 'size': 6}}
        report = sa.push(self.project, config=CONFIG)
        self.assertFalse(report['technical_pass'])
        self.assertEqual([m['file'] for m in report['mismatched']], ['assets/קליפ גלם.mp4', 'plan-v001.json'])
        self.assertEqual(list(self.station.manifest['files']), ['renders/v001/final.mp4'])

    def test_never_issues_delete_commands_and_keeps_archived_only_files(self):
        self.station.manifest = {'exists': True, 'files': {'old/removed-locally.mov': {'sha256': 'x', 'size': 1}}}
        report = sa.push(self.project, config=CONFIG)
        self.assertEqual(report['archived_not_local'], ['old/removed-locally.mov'])
        self.assertIn('old/removed-locally.mov', self.station.manifest['files'])
        joined = ' '.join(' '.join(c) for c in self.station.commands).lower()
        for forbidden in (' rm ', ' del ', 'rmdir', 'remove-item', ' rm -'):
            self.assertNotIn(forbidden, joined)

    def test_dry_run_touches_nothing_remote(self):
        report = sa.push(self.project, dry_run=True, config=CONFIG)
        self.assertEqual(report['planned_upload'], ['assets/קליפ גלם.mp4', 'plan-v001.json', 'renders/v001/final.mp4'])
        self.assertEqual(self.station.commands, [])

    def test_slug_rules(self):
        hebrew = Path(self.temp.name) / 'קמפיין'
        hebrew.mkdir()
        with self.assertRaisesRegex(ValueError, 'ASCII slug'):
            sa.push(hebrew, config=CONFIG, dry_run=True)
        self.assertEqual(sa.push(hebrew, slug='kampain-2026', config=CONFIG, dry_run=True)['slug'], 'kampain-2026')

    def test_status_reports_gaps(self):
        sa.push(self.project, config=CONFIG)
        (self.project / 'renders/v002').mkdir()
        (self.project / 'renders/v002/final.mp4').write_bytes(b'new render')
        report = sa.status(self.project, config=CONFIG, verify=True)
        self.assertFalse(report['fully_archived'])
        self.assertEqual(report['not_archived_or_changed'], ['renders/v002/final.mp4'])
        self.assertEqual(report['remote_verify_failed'], [])

    def test_sftp_paths_use_drive_form(self):
        self.assertEqual(sa.sftp_path('D:/archive/x y/ק.mp4'), '/D:/archive/x y/ק.mp4')
        self.assertEqual(sa.sftp_path('D:\\archive\\a.mp4'), '/D:/archive/a.mp4')


if __name__ == '__main__':
    unittest.main()
