"""Local-only regression fixtures for delayed audio tails and encoded delivery gates."""
from array import array
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import audio_finish
import delivery_qa


class SampleTimingTests(unittest.TestCase):
    def test_trimmed_delayed_music_retains_tail_and_fractional_onset(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'tone.wav'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                            'sine=frequency=440:sample_rate=48000:duration=9',str(source)],check=True)
            at=4.250125; length=3
            tracks=[dict(path=str(source),role='music',**{'in':2.1},at=at,duration=length,
                         gain_db=0,fade_in=0,fade_out=0),
                    dict(path=str(source),role='sfx',**{'in':0},at=0,duration=1,
                         gain_db=-6,fade_in=0,fade_out=0)]
            spec=root/'mix.json'; spec.write_text(json.dumps(dict(duration=8,target_lufs=-16,
                true_peak_dbtp=-4,tracks=tracks)),encoding='utf-8')
            audio_finish.finish(spec,root/'out')
            def samples(name):
                raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(root/'out'/name),
                                             '-ac','1','-ar','48000','-f','f32le','-'])
                data=array('f');data.frombytes(raw);return data
            music=samples('music.wav'); start=round(at*48000); end=start+length*48000
            self.assertEqual(len(music),8*48000)
            self.assertLess(max(map(abs,music[:start])),1e-7)
            onset=next(i for i,v in enumerate(music) if abs(v)>1e-5)
            self.assertLessEqual(abs(onset-start),2)
            self.assertGreater(sum(v*v for v in music[end-4800:end])/4800,1e-4)
            self.assertLess(max(map(abs,music[end:])),1e-7)
            sfx=samples('sfx.wav')
            self.assertGreater(sum(v*v for v in sfx[:48000])/48000,1e-5)
            self.assertLess(max(map(abs,sfx[48000:])),1e-7)


class EncodedTargetTests(unittest.TestCase):
    def check_measurement(self,measurement,targets):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);video=root/'fixture.mp4';video.write_bytes(b'fixture')
            plan=root/'plan.json'; plan.write_text(json.dumps(dict(width=1920,height=1080,
                fps=24,frames=48,clips=[dict(kind='sound')],**targets)),encoding='utf-8')
            info=dict(format=dict(duration='2'),streams=[dict(codec_type='video',codec_name='h264',
                pix_fmt='yuv420p',width=1920,height=1080,avg_frame_rate='24/1'),dict(codec_type='audio')])
            with patch.object(delivery_qa,'inspect',return_value=info), \
                 patch.object(delivery_qa,'run',return_value=(b'','')), \
                 patch.object(delivery_qa,'loudness',return_value=measurement):
                return delivery_qa.check(video,plan)

    def test_peak_ceiling_and_loudness_boundaries(self):
        targets=dict(audio_target_lufs=-16,audio_true_peak_max=-1.5)
        for lufs,peak,expected in [(-16,-3.86,True),(-17,-1.5,True),
                                   (-16,-1.48,False),(-18,-3,False),
                                   (float('nan'),-3,False)]:
            with self.subTest(lufs=lufs,peak=peak):
                result=self.check_measurement(dict(input_i=str(lufs),input_tp=str(peak)),targets)
                self.assertEqual(result['technical_pass'],expected)

    def test_legacy_plan_without_targets_remains_measurement_only(self):
        result=self.check_measurement(dict(input_i='-18',input_tp='-1'),{})
        self.assertTrue(result['technical_pass'])
        self.assertTrue(result['creative_listening_and_visual_review_required'])


if __name__=='__main__':unittest.main()
