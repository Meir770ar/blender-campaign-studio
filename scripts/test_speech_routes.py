import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import narration_plan
import provider_jobs as jobs

AUDIO_MEDIA = {'duration_seconds': '2.0', 'streams': [{'codec_type': 'audio', 'codec_name': 'pcm_s16le'}]}


class SpeechRoutes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = {'gemini_tts': {'env_file': 'fixture.env', 'model': 'gemini-3.8-flash-tts', 'voice': 'Charon',
                                      'style': '', 'alignment': 'elevenlabs_forced_alignment'},
                       'elevenlabs': {'env_file': 'fixture.env', 'voice_id': 'v', 'model': 'eleven_v3'},
                       'elevenlabs_sfx': {'env_file': 'fixture.env', 'model': 'eleven_text_to_sound_v2',
                                          'output_format': 'mp3_44100_128'}}

    def validate(self, value):
        return jobs.validate_request(value, self.root, self.config)['request']

    def prepare(self, request):
        path = self.root / 'request.json'
        jobs.atomic_json(path, request)
        return jobs.prepare(path, self.root / 'jobs', self.config)

    def test_gemini_request_takes_text_style_and_voice_only(self):
        r = self.validate({'provider': 'gemini_tts', 'text': 'שלום לכולם.', 'style': ' calm, warm '})
        self.assertEqual((r['voice'], r['style']), ('Charon', 'calm, warm'))
        for invalid in [{'provider': 'gemini_tts', 'text': 'x', 'stability': .5},
                        {'provider': 'gemini_tts', 'text': 'x', 'voice': 'not a voice!'},
                        {'provider': 'gemini_tts', 'text': 'x', 'style': 's' * 301},
                        {'provider': 'gemini_tts', 'text': 'a <break time="1s"/> b'},
                        {'provider': 'gemini_tts', 'text': ' '}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.validate(invalid)

    def test_sfx_request_ranges(self):
        r = self.validate({'provider': 'elevenlabs_sfx', 'text': 'soft whoosh', 'duration_seconds': 1.5})
        self.assertEqual((r['prompt_influence'], r['loop'], r['duration_seconds']), (.3, False, 1.5))
        for invalid in [{'provider': 'elevenlabs_sfx', 'text': 'x', 'duration_seconds': 31},
                        {'provider': 'elevenlabs_sfx', 'text': 'x', 'prompt_influence': 2},
                        {'provider': 'elevenlabs_sfx', 'text': 'x', 'loop': 'yes'},
                        {'provider': 'elevenlabs_sfx', 'text': 'x' * 451}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.validate(invalid)

    def test_forced_alignment_tokens_become_words(self):
        alignment = {'words': [{'text': 'שלום', 'start': 0.1, 'end': 0.4}, {'text': ' ', 'start': 0.4, 'end': 0.45},
                               {'text': 'לכולם', 'start': 0.45, 'end': 0.9}, {'text': '.', 'start': 0.9, 'end': 0.95},
                               {'text': ' ', 'start': 0.95, 'end': 1.0}, {'text': 'טוב', 'start': 1.0, 'end': 1.3}]}
        words = jobs.words_from_forced_alignment(alignment)
        self.assertEqual([w['word'] for w in words], ['שלום', 'לכולם.', 'טוב'])
        self.assertEqual((words[1]['start'], words[1]['end']), (0.45, 0.95))
        with self.assertRaises(ValueError):
            jobs.words_from_forced_alignment({'words': [{'text': 'b', 'start': 1, 'end': 2},
                                                        {'text': 'a', 'start': 0.5, 'end': 0.9}]})
        with self.assertRaises(ValueError):
            jobs.words_from_forced_alignment({'words': []})

    def test_gemini_execute_saves_audio_then_aligns_once(self):
        folder = self.prepare({'provider': 'gemini_tts', 'text': 'שלום לכולם. טוב', 'style': 'calm'})
        jobs.authorize(folder, 'Approved one Gemini audition', 20, 'characters')
        response = {'id': 'int-1', 'output_audio': {'data': base64.b64encode(b'RIFFfixture').decode(),
                                                    'mime_type': 'audio/wav'}}
        alignment = {'words': [{'text': 'שלום', 'start': 0.1, 'end': 0.4}, {'text': ' ', 'start': 0.4, 'end': 0.45},
                               {'text': 'לכולם.', 'start': 0.45, 'end': 0.9}, {'text': ' ', 'start': 0.9, 'end': 1.0},
                               {'text': 'טוב', 'start': 1.0, 'end': 1.3}], 'loss': 0.1}
        with patch.object(jobs, 'gemini_http', return_value=response) as gemini, \
                patch.object(jobs, 'eleven_multipart', return_value=alignment) as align, \
                patch.object(jobs, 'ffprobe', return_value=AUDIO_MEDIA):
            job = jobs.execute(folder, self.config, 15)
        self.assertEqual(job['state'], 'complete')
        body = gemini.call_args[0][2]
        self.assertEqual(body['model'], 'gemini-3.8-flash-tts')
        self.assertEqual(body['generation_config'], {'speech_config': [{'voice': 'Charon'}]})
        self.assertEqual(body['input'][0]['content'][0]['annotations'], [{'type': 'speech_metadata', 'style': 'calm'}])
        self.assertEqual(body['response_format'], {'type': 'audio', 'mime_type': 'audio/wav'})
        self.assertEqual((folder / 'narration.wav').read_bytes(), b'RIFFfixture')
        self.assertEqual(align.call_args[0][1:3], ('forced-alignment', {'text': 'שלום לכולם. טוב'}))
        words = json.loads((folder / 'words.json').read_text(encoding='utf-8'))
        self.assertEqual(words['source'], 'elevenlabs_forced_alignment')
        self.assertEqual([w['word'] for w in words['words']], ['שלום', 'לכולם.', 'טוב'])
        receipt = json.loads((folder / 'gemini-receipt.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['output_audio'], {'mime_type': 'audio/wav'})
        self.assertEqual(Path(job['assets'][0]['path']).name, 'narration.wav')
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            jobs.execute(folder, self.config, 15)

    def test_gemini_alignment_failure_keeps_audio_for_repair(self):
        folder = self.prepare({'provider': 'gemini_tts', 'text': 'שלום'})
        jobs.authorize(folder, 'Approved', 20, 'characters')
        response = {'output_audio': {'data': base64.b64encode(b'RIFFfixture').decode()}}
        with patch.object(jobs, 'gemini_http', return_value=response), \
                patch.object(jobs, 'eleven_multipart', side_effect=ValueError('ElevenLabs HTTP 401')), \
                patch.object(jobs, 'ffprobe', return_value=AUDIO_MEDIA):
            with self.assertRaisesRegex(ValueError, 'Reconcile'):
                jobs.execute(folder, self.config, 5)
        job = jobs.load_json(folder / 'job.json')
        self.assertEqual(job['state'], 'received_needs_alignment')
        self.assertTrue((folder / 'narration.wav').is_file())
        self.assertFalse((folder / 'words.json').exists())

    def test_gemini_without_audio_is_unknown_and_never_repeats(self):
        folder = self.prepare({'provider': 'gemini_tts', 'text': 'שלום'})
        jobs.authorize(folder, 'Approved', 20, 'characters')
        with patch.object(jobs, 'gemini_http', return_value={'id': 'x', 'status': 'failed'}):
            with self.assertRaisesRegex(ValueError, 'Reconcile'):
                jobs.execute(folder, self.config, 5)
        self.assertEqual(jobs.load_json(folder / 'job.json')['state'], 'unknown')

    def test_gemini_rest_steps_shape_is_saved_and_receipt_drops_audio(self):
        # On the wire the Interactions API returns audio inside steps[].content[], not output_audio (SDK property).
        self.config['gemini_tts']['alignment'] = 'local_faster_whisper'
        config = self.config
        folder = self.prepare({'provider': 'gemini_tts', 'text': 'Hello there.'})
        jobs.authorize(folder, 'Approved', 1, 'requests')
        response = {'id': 'int-rest', 'status': 'completed', 'input': [{'type': 'user_input'}],
                    'steps': [{'type': 'model_output', 'content': [
                        {'type': 'audio', 'data': base64.b64encode(b'RIFFrest').decode(), 'mime_type': 'audio/wav'}]}],
                    'usage': {'total_tokens': 42}}
        with patch.object(jobs, 'gemini_http', return_value=response),                 patch.object(jobs, 'eleven_multipart') as align, patch.object(jobs, 'ffprobe', return_value=AUDIO_MEDIA):
            job = jobs.execute(folder, config, 1)
        self.assertEqual(job['state'], 'complete')
        align.assert_not_called()
        self.assertEqual((folder / 'narration.wav').read_bytes(), b'RIFFrest')
        receipt = (folder / 'gemini-receipt.json').read_text(encoding='utf-8')
        self.assertNotIn(base64.b64encode(b'RIFFrest').decode(), receipt)
        self.assertEqual(json.loads(receipt)['steps'][0]['content'][0], {'type': 'audio', 'mime_type': 'audio/wav'})
        self.assertFalse((folder / 'gemini-response.pending.json').exists())
        self.assertNotIn('provider_response_saved', job)

    def test_gemini_headerless_pcm_is_wrapped_in_wav(self):
        import io
        import wave
        self.config['gemini_tts']['alignment'] = 'none'
        config = self.config
        folder = self.prepare({'provider': 'gemini_tts', 'text': 'Hello.'})
        jobs.authorize(folder, 'Approved', 1, 'requests')
        pcm = b'\x01\x00' * 480
        response = {'steps': [{'type': 'model_output', 'content': [
            {'type': 'audio', 'data': base64.b64encode(pcm).decode(), 'mime_type': 'audio/l16;rate=24000'}]}]}
        with patch.object(jobs, 'gemini_http', return_value=response), patch.object(jobs, 'ffprobe', return_value=AUDIO_MEDIA):
            jobs.execute(folder, config, 1)
        with wave.open(io.BytesIO((folder / 'narration.wav').read_bytes())) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()), (1, 2, 24000, 480))

    def test_gemini_response_without_audio_is_preserved_with_reason(self):
        folder = self.prepare({'provider': 'gemini_tts', 'text': 'Hello.'})
        jobs.authorize(folder, 'Approved', 1, 'requests')
        response = {'id': 'int-text', 'status': 'completed',
                    'steps': [{'type': 'model_output', 'content': [{'type': 'text', 'text': 'no audio'}]}]}
        with patch.object(jobs, 'gemini_http', return_value=response):
            with self.assertRaisesRegex(ValueError, 'Reconcile'):
                jobs.execute(folder, self.config, 1)
        job = jobs.load_json(folder / 'job.json')
        self.assertEqual(job['state'], 'unknown')
        self.assertIn('no audio part', job['error'])
        self.assertEqual(jobs.load_json(folder / 'gemini-response.pending.json')['id'], 'int-text')

    def test_narration_retake_names_the_earlier_attempt_and_gets_a_new_identity(self):
        request = {'provider': 'gemini_tts', 'text': 'Hello.'}
        first = self.prepare(request)
        with self.assertRaisesRegex(ValueError, 'never attempted'):
            self.prepare({**request, 'retake_of': first.name})
        jobs.authorize(first, 'Approved', 1, 'requests')
        with patch.object(jobs, 'gemini_http', return_value={'id': 'x', 'status': 'completed', 'steps': []}):
            with self.assertRaisesRegex(ValueError, 'Reconcile'):
                jobs.execute(first, self.config, 1)
        self.assertEqual(self.prepare(request), first)
        with self.assertRaisesRegex(ValueError, 'Only an unsubmitted'):
            jobs.authorize(first, 'Approved again', 1, 'requests')
        retake = self.prepare({**request, 'retake_of': first.name})
        self.assertNotEqual(retake, first)
        self.assertEqual(jobs.load_json(retake / 'job.json')['request']['retake_of'], first.name)
        for bad in ('0' * 64, 'not-an-id'):
            with self.assertRaises(ValueError):
                self.prepare({**request, 'retake_of': bad})

    def test_sfx_execute_saves_mp3_once(self):
        folder = self.prepare({'provider': 'elevenlabs_sfx', 'text': 'soft whoosh', 'duration_seconds': 1.5, 'loop': False})
        jobs.authorize(folder, 'Approved one effect', 1, 'generation')
        media = {'duration_seconds': '1.5', 'streams': [{'codec_type': 'audio', 'codec_name': 'mp3'}]}
        with patch.object(jobs, 'eleven_http', return_value=b'ID3fixture') as http, \
                patch.object(jobs, 'ffprobe', return_value=media):
            job = jobs.execute(folder, self.config, 1)
        self.assertEqual(job['state'], 'complete')
        endpoint, body = http.call_args[0][1], http.call_args[0][2]
        self.assertEqual(endpoint, 'sound-generation?output_format=mp3_44100_128')
        self.assertEqual(body, {'text': 'soft whoosh', 'model_id': 'eleven_text_to_sound_v2', 'prompt_influence': .3,
                                'loop': False, 'duration_seconds': 1.5})
        self.assertTrue(http.call_args[1]['raw'])
        self.assertEqual(Path(job['assets'][0]['path']).name, 'sfx.mp3')
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            jobs.execute(folder, self.config, 1)

    def test_sfx_undecodable_output_is_kept_for_review(self):
        folder = self.prepare({'provider': 'elevenlabs_sfx', 'text': 'click'})
        jobs.authorize(folder, 'Approved', 1, 'generation')
        with patch.object(jobs, 'eleven_http', return_value=b'not audio'), \
                patch.object(jobs, 'ffprobe', return_value={'duration_seconds': '0', 'streams': []}):
            with self.assertRaisesRegex(ValueError, 'Reconcile'):
                jobs.execute(folder, self.config, 1)
        self.assertEqual(jobs.load_json(folder / 'job.json')['state'], 'received_needs_review')

    def test_secret_reads_named_variable_from_env_file(self):
        env = self.root / 'speech.env'
        env.write_text('ELEVENLABS_API_KEY="e-key"\nexport GEMINI_API_KEY=g-key\n', encoding='utf-8')
        self.assertEqual(jobs.secret({'env_file': str(env)}), 'e-key')
        self.assertEqual(jobs.secret({'env_file': str(env)}, 'GEMINI_API_KEY'), 'g-key')
        self.assertEqual(jobs.secret({'env_file': str(env), 'key_variable': 'GEMINI_API_KEY'}), 'g-key')
        with self.assertRaisesRegex(ValueError, 'OTHER_KEY missing'):
            jobs.secret({'env_file': str(env)}, 'OTHER_KEY')

    def test_probes_are_read_only(self):
        with patch.object(jobs, 'gemini_http', return_value={'name': 'models/gemini-3.8-flash-tts',
                                                             'inputTokenLimit': 8192}) as g:
            probe = jobs.probe('gemini_tts', self.config)
        self.assertTrue(probe['model_accessible'] and not probe['generation_tested'])
        self.assertEqual(g.call_args[0][1], 'models/gemini-3.8-flash-tts')
        with patch.object(jobs, 'eleven_http', return_value=[{'model_id': 'eleven_v3'}]):
            probe = jobs.probe('elevenlabs_sfx', self.config)
        self.assertTrue(probe['api_reachable'] and not probe['sound_model_listed'] and not probe['generation_tested'])

    def test_narration_script_chooses_gemini_and_layout_finds_the_recorded_asset(self):
        script = {'version': 1, 'provider': 'gemini_tts', 'voice': {'voice': 'Charon', 'style': 'calm'}, 'start_at': 0.5,
                  'segments': [{'id': 'hook', 'text': 'שלום לכולם.', 'pause_after': 1},
                               {'id': 'cta', 'text': 'טוב', 'pause_after': 0}]}
        path = self.root / 'narration.json'
        path.write_text(json.dumps(script, ensure_ascii=False), encoding='utf-8')
        report = narration_plan.split(path, self.root / 'requests')
        single = json.loads(Path(report['single_request']).read_text(encoding='utf-8'))
        self.assertEqual(single, {'provider': 'gemini_tts', 'text': 'שלום לכולם.\n\nטוב', 'voice': 'Charon', 'style': 'calm'})
        self.assertEqual(report['provider'], 'gemini_tts')
        with self.assertRaisesRegex(ValueError, 'gemini_tts voice accepts'):
            narration_plan.validate_script({**script, 'voice': {'stability': .5}})
        with self.assertRaisesRegex(ValueError, 'provider must be'):
            narration_plan.validate_script({**script, 'provider': 'kokoro'})
        elevenlabs = narration_plan.validate_script({**script, 'provider': 'elevenlabs', 'voice': {'speed': 1.1}})
        self.assertEqual(elevenlabs['voice']['speed'], 1.1)
        jobs_root = self.root / 'jobs'
        folder = jobs_root / 'abc'
        folder.mkdir(parents=True)
        audio = folder / 'narration.wav'
        audio.write_bytes(b'RIFF')
        jobs.atomic_json(folder / 'job.json', {'request': {'provider': 'gemini_tts', 'text': 'שלום לכולם.\n\nטוב'},
                                               'state': 'complete', 'assets': [{'path': str(audio)}]})
        self.assertEqual(narration_plan.find_rendered(jobs_root, 'שלום לכולם.\n\nטוב'), audio)
        with self.assertRaisesRegex(ValueError, 'found 0'):
            narration_plan.find_rendered(jobs_root, 'other text')


if __name__ == '__main__':
    unittest.main()
