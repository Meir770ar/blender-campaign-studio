"""Actual local PCM fixtures and clock contracts; no network or provider use."""
from array import array
import json
import math
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import patch

import audio_finish
import delivery_qa
import edit_audit as audit
from campaign_common import sha256_file


def wav(path, frames, values):
    pcm = array('h')
    for i in range(frames):
        value = values(i)
        pcm.extend(value if isinstance(value, tuple) else (value, value))
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(2); output.setsampwidth(2); output.setframerate(audit.RATE)
        output.writeframes(pcm.tobytes())


class ClockTests(unittest.TestCase):
    def segments(self, source_start=10):
        return [dict(source_id='photos', timeline_start_frame=0, timeline_end_frame=10, source_start_frame=0),
                dict(source_id='photos', timeline_start_frame=10, timeline_end_frame=20,
                     source_start_frame=source_start, continues_previous=True)]

    def test_continuous_clock_and_72_frame_regression(self):
        self.assertTrue(all(r['pass'] for r in audit.check_clocks(self.segments())))
        result = audit.check_clocks(self.segments(82))[-1]
        self.assertFalse(result['pass']); self.assertEqual(result['source_jump_frames'], 72)

    def test_retime_rate_and_explicit_cut(self):
        spec = self.segments(20); spec[0]['source_frames_per_frame'] = 2
        self.assertTrue(audit.check_clocks(spec)[-1]['pass'])
        spec[1].update(continues_previous=False, source_start_frame=72)
        self.assertTrue(audit.check_clocks(spec)[-1]['pass'])

    def test_invalid_overlap_and_nonfinite_rejected(self):
        for key, value in [('timeline_start_frame', 9), ('source_start_frame', float('nan'))]:
            with self.subTest(key=key):
                spec = self.segments(); spec[1][key] = value
                with self.assertRaises(ValueError): audit.check_clocks(spec)


class PCMTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source.wav'
        wav(self.source, 48000, lambda i: int(4000 * math.sin(2 * math.pi * 440 * i / 48000)))

    def tearDown(self): self.temp.cleanup()

    def test_silent_trim_and_antiphase_stereo(self):
        path = self.root / 'source-with-silence.wav'
        wav(path, 48000, lambda i: (2000, -2000) if i < 24000 else 0)
        self.assertGreater(audit.signal_stats(path, 0, .5)['peak'], 0)
        self.assertEqual(audit.signal_stats(path, .5, .5)['nonzero_samples'], 0)
        with self.assertRaisesRegex(ValueError, 'duration'): audit.signal_stats(path, .9, .2)

    def test_energy_jump_and_sample_step_are_separate(self):
        path = self.root / 'join.wav'
        # Strong RMS change with the first post-cut sample still at zero.
        wav(path, 48000, lambda i: int((100 if i < 24000 else 5000) * math.sin(2 * math.pi * 400 * i / 48000)))
        result = audit.join_stats(path, .5)
        self.assertGreater(result['rms_jump_db'], 30)
        self.assertLess(result['boundary_sample_step'], .001)
        self.assertIn('energy_transition_requires_listening', result['review_signals'])
        self.assertNotIn('sample_step_requires_listening', result['review_signals'])

    def test_join_outside_source_rejected(self):
        for at in (.001, 1):
            with self.assertRaises(ValueError): audit.join_stats(self.source, at)

    def test_local_repair_exact_outside_window_and_protected_word(self):
        revised = self.root / 'repaired.wav'
        wav(revised, 48000, lambda i: int(4000 * math.sin(2 * math.pi * 440 * i / 48000)) + (1 if 24000 <= i < 24480 else 0))
        good = audit.compare_pcm(self.source, revised, [[.5, .51]], [[.6, .9]])
        self.assertTrue(good['pass']); self.assertEqual(good['changed_frames'], 480)
        self.assertFalse(audit.compare_pcm(self.source, revised, [[.5, .505]])['pass'])
        protected = audit.compare_pcm(self.source, revised, [[.5, .51]], [[.505, .51]])
        self.assertEqual(protected['changed_in_protected'], 240); self.assertFalse(protected['pass'])

    def test_unchanged_and_length_change(self):
        self.assertTrue(audit.compare_pcm(self.source, self.source, [])['pass'])
        shorter = self.root / 'short.wav'; wav(shorter, 24000, lambda i: 0)
        self.assertFalse(audit.compare_pcm(self.source, shorter, [])['same_frame_count'])

    def test_silent_sfx_rejected_before_mix_and_missing_waiver_reason(self):
        silent = self.root / 'silent.wav'; wav(silent, 48000, lambda i: 0)
        track = dict(path=str(silent), role='sfx', duration=1)
        spec = self.root / 'mix.json'
        for change, message in [({}, 'silent'), ({'expect_signal':False}, 'silence_reason'),
                                ({'expect_signal':False, 'silence_reason':None}, 'silence_reason')]:
            spec.write_text(json.dumps(dict(duration=1, tracks=[dict(track, **change)])), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, message): audio_finish.finish(spec, self.root / 'out')
            self.assertFalse((self.root / 'out').exists())

    def test_explicit_intentional_silence_with_audible_music(self):
        silent = self.root / 'silent.wav'; wav(silent, 48000, lambda i: 0)
        spec = self.root / 'mix.json'
        spec.write_text(json.dumps(dict(duration=1, tracks=[dict(path=str(self.source),role='music',duration=1),
            dict(path=str(silent),role='sfx',duration=1,expect_signal=False,silence_reason='Intentional one-second timing placeholder')])) ,encoding='utf-8')
        result = audio_finish.finish(spec, self.root / 'out')
        self.assertTrue(result['qa']['pass'])

    def test_audit_reports_failed_signal_and_keeps_review_pending(self):
        silent = self.root / 'silent.wav'; wav(silent, 48000, lambda i: 0)
        spec = self.root / 'audit.json'
        spec.write_text(json.dumps(dict(schema_version=1, target=str(self.source),
            required_signals=[dict(path=str(silent))])), encoding='utf-8')
        result = audit.audit(spec)
        self.assertFalse(result['technical_pass']); self.assertTrue(result['listening_and_motion_review_required'])
        self.assertEqual(result['target_sha256'], sha256_file(self.source))


class DeliveryEvidenceTests(unittest.TestCase):
    def test_changing_clock_contract_invalidates_prior_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(); video=root/'copy.mp4'; video.write_bytes(b'encoded copy')
            spec=root/'spec.json'; report=root/'audit.json'
            value=dict(schema_version=1,target=str(video),clock_segments=[dict(source_id='photos',
                       timeline_start_frame=0,timeline_end_frame=10,source_start_frame=0)])
            spec.write_text(json.dumps(value),encoding='utf-8')
            report.write_text(json.dumps(audit.audit(spec)),encoding='utf-8')
            value['clock_segments'][0]['source_start_frame']=72
            spec.write_text(json.dumps(value),encoding='utf-8')
            info=dict(format=dict(duration='1'),streams=[dict(codec_type='video',codec_name='h264',pix_fmt='yuv420p')])
            with patch.object(delivery_qa,'inspect',return_value=info),patch.object(delivery_qa,'run',return_value=('', '')):
                result=delivery_qa.check(video,edit_audit_path=report)
            self.assertFalse(result['technical_pass'])
            self.assertTrue(any('spec.json' in message for message in result['errors']))

    def test_target_and_source_hashes_and_failed_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); video = root / 'copy.mp4'; video.write_bytes(b'actual encoded bytes')
            stem = root / 'stem.wav'; stem.write_bytes(b'stem')
            report = root / 'audit.json'
            info = dict(format=dict(duration='1'), streams=[dict(codec_type='video', codec_name='h264', pix_fmt='yuv420p')])
            base = dict(schema_version=1, target_sha256=sha256_file(video), technical_pass=True,
                        files={str(stem):sha256_file(stem)})
            for change, expected in [({}, True), ({'technical_pass':False},False), ({'target_sha256':'wrong'},False),
                                     ({'files':{str(stem):'stale'}},False)]:
                with self.subTest(change=change), patch.object(delivery_qa,'inspect',return_value=info), \
                     patch.object(delivery_qa,'run',return_value=('', '')):
                    report.write_text(json.dumps(dict(base, **change)),encoding='utf-8')
                    result=delivery_qa.check(video,edit_audit_path=report)
                    self.assertEqual(result['technical_pass'],expected)
                    self.assertTrue(result['creative_listening_and_visual_review_required'])


if __name__ == '__main__': unittest.main()
