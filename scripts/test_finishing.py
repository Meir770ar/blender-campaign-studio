"""Behavioral tests: mocked provider transport and real local media integration when explicitly run."""
import base64
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
import provider_jobs as jobs
from campaign_common import lock
from editorial import map_words, checked_words
from captions import phrases, srt_time


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.config = {'images': {'route':'codex_builtin'}, 'suno': {'model':'test','client_module':'unused'},
                       'grok': {'model':'xai/grok-imagine-video'}, 'elevenlabs': {'model':'eleven_v3','voice_id':'test'}}

    def tearDown(self): self.temp.cleanup()

    def job(self, request):
        path = self.root/'request.json'; path.write_text(json.dumps(request),encoding='utf-8')
        return jobs.prepare(path,self.root/'jobs',self.config)

    def approve(self, folder): jobs.authorize(folder,'Test-only approval of mocked transport',1,'mock calls')

    def test_duplicate_semantic_input_same_job(self):
        one = self.job({'provider':'suno','style':'quiet piano'})
        two = self.job({'style':'quiet piano','provider':'suno','title':'','lyrics':'','instrumental':True})
        self.assertEqual(one,two)

    def test_reference_bytes_not_filename_define_identity(self):
        a=self.root/'a.png'; b=self.root/'b.png'; a.write_bytes(b'fixture'); b.write_bytes(b'fixture')
        one=self.job({'provider':'images','prompt':'test','references':[str(a)]})
        two=self.job({'provider':'images','prompt':'test','references':[str(b)]})
        self.assertEqual(one,two)

    def test_missing_approval_never_calls_transport(self):
        folder=self.job({'provider':'suno','style':'piano'})
        with patch.object(jobs,'suno') as submit:
            with self.assertRaisesRegex(ValueError,'approval'): jobs.execute(folder,self.config,1)
            submit.assert_not_called()

    def test_unknown_is_persisted_and_never_retried(self):
        folder=self.job({'provider':'suno','style':'piano'}); self.approve(folder)
        with patch.object(jobs,'suno',side_effect=TimeoutError) as submit:
            with self.assertRaises(ValueError): jobs.execute(folder,self.config,1)
            with self.assertRaisesRegex(ValueError,'already attempted'): jobs.execute(folder,self.config,1)
            self.assertEqual(submit.call_count,1)
        self.assertEqual(jobs.load_json(folder/'job.json')['state'],'unknown')

    def test_preflight_block_can_resume_without_duplicate_generation(self):
        folder=self.job({'provider':'suno','style':'piano'}); self.approve(folder)
        with patch.object(jobs,'suno',return_value={'submitted':False,'status':'blocked'}):
            self.assertEqual(jobs.execute(folder,self.config,1)['state'],'blocked')
        with patch.object(jobs,'suno',return_value={'submitted':True,'ids':['clip-1']}):
            self.assertEqual(jobs.execute(folder,self.config,1)['state'],'submitted')
        with self.assertRaises(ValueError): jobs.execute(folder,self.config,1)

    def test_budget_and_reference_changes_block(self):
        ref=self.root/'a.png'; ref.write_bytes(b'first')
        folder=self.job({'provider':'images','prompt':'test','references':[str(ref)]}); self.approve(folder)
        with self.assertRaises(ValueError): jobs.execute(folder,self.config,2)
        ref.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Reference changed'): jobs.execute(folder,self.config,1)

    def test_images_emit_native_tool_only(self):
        folder=self.job({'provider':'images','prompt':'test'}); self.approve(folder)
        job=jobs.execute(folder,self.config,1)
        self.assertEqual(job['tool_request'],{'tool':'image_gen.imagegen','args':{'prompt':'test'}})
        self.assertEqual(job['state'],'awaiting_agent_tool')

    def test_grok_paid_fallback_rejected_before_attempt(self):
        folder=self.job({'provider':'grok','prompt':'test'}); self.approve(folder)
        with patch.object(jobs,'grok_metadata',return_value={'oauth':True,'model':{'primary':'xai/grok-imagine-video','fallbacks':['fal/test']}}):
            with self.assertRaisesRegex(ValueError,'Subscription-only'): jobs.execute(folder,self.config,1)
        self.assertEqual(jobs.load_json(folder/'job.json')['state'],'prepared')

    def test_eleven_audio_survives_alignment_failure(self):
        folder=self.job({'provider':'elevenlabs','text':'שלום'}); self.approve(folder)
        with patch.object(jobs,'eleven_http',return_value={'audio_base64':base64.b64encode(b'mock audio').decode(),'alignment':{}}):
            with self.assertRaises(ValueError): jobs.execute(folder,self.config,1)
        self.assertEqual((folder/'narration.mp3').read_bytes(),b'mock audio')
        self.assertEqual(jobs.load_json(folder/'job.json')['state'],'received_needs_alignment')

    def grok_oauth_meta(self):
        return {'oauth':True,'oauth_usable_or_refreshable':True,'refresh_needed':True,'refresh_available':True,
                'apiCredential':False,'model':{'primary':'xai/grok-imagine-video'},
                'agent_dir':'/runtime/agents/meir/agent','agent_context_matches':True,
                'campaign_contract':jobs.grok_contract.CONTRACT}

    def test_grok_expired_oauth_ignores_api_key_discovery_false_negative(self):
        folder=self.job({'provider':'grok','prompt':'test'}); self.approve(folder)
        capability={'ok':True,'output':{'details':{'providers':[{'id':'xai','configured':False,
            'capabilities':{'generate':{'resolutions':['480P','720P','1080P'],'supportsAudio':True}}}]}}}
        with patch.object(jobs,'grok_metadata',return_value=self.grok_oauth_meta()), \
             patch.object(jobs,'gateway',side_effect=[capability,{'ok':True}]) as gateway:
            self.assertEqual(jobs.execute(folder,self.config,1)['state'],'submitted')
            self.assertEqual(gateway.call_count,2)
            self.assertEqual(gateway.call_args.args[2]['action'],'generate')
            self.assertEqual(gateway.call_args.args[2]['model'],'xai/grok-imagine-video')
        with self.assertRaisesRegex(ValueError,'already attempted'): jobs.execute(folder,self.config,1)

    def test_grok_wrong_agent_context_blocks_before_transport(self):
        folder=self.job({'provider':'grok','prompt':'test'}); self.approve(folder)
        meta={**self.grok_oauth_meta(),'agent_context_matches':False}
        with patch.object(jobs,'grok_metadata',return_value=meta),patch.object(jobs,'gateway') as gateway:
            with self.assertRaisesRegex(ValueError,'agentDir'): jobs.execute(folder,self.config,1)
            gateway.assert_not_called()
        self.assertEqual(jobs.load_json(folder/'job.json')['state'],'prepared')

    def test_grok_expired_without_refresh_or_missing_oauth_is_rejected(self):
        for change in [{'oauth_usable_or_refreshable':False},{'oauth':False},{'apiCredential':True}]:
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'Subscription-only'):
                jobs.require_grok_subscription_context({**self.grok_oauth_meta(),**change},self.config['grok'])

    def test_grok_missing_provider_still_blocks(self):
        folder=self.job({'provider':'grok','prompt':'test'}); self.approve(folder)
        with patch.object(jobs,'grok_metadata',return_value=self.grok_oauth_meta()), \
             patch.object(jobs,'gateway',return_value={'ok':True,'output':{'details':{'providers':[]}}}) as gateway:
            with self.assertRaisesRegex(ValueError,'unavailable'): jobs.execute(folder,self.config,1)
            self.assertEqual(gateway.call_count,1)

    def test_gateway_binds_requested_agent_and_isolated_session(self):
        config={'agent':'meir','container':'test-container'}
        with patch.object(jobs,'ssh',return_value=b'{"ok":true}') as transport:
            jobs.gateway(config,'fixture-job',{'action':'generate','model':'xai/grok-imagine-video'})
        command=transport.call_args.args[1]
        params=json.loads(command[command.index('--params')+1])
        self.assertEqual(params['agentId'],'meir')
        self.assertEqual(params['sessionKey'],'agent:meir:campaign-fixture-job')
        self.assertEqual(params['idempotencyKey'],'campaign-fixture-job')

    def test_lock_prevents_simultaneous_mutation(self):
        with lock(self.root/'.lock'):
            with self.assertRaises(ValueError):
                with lock(self.root/'.lock'): pass


class TimingTests(unittest.TestCase):
    def test_word_mapping_preserves_gap(self):
        words=[{'word':'שלום','start':2,'end':2.4},{'word':'עולם','start':3,'end':3.5}]
        self.assertEqual(map_words(words,1.9,3.6,5)[1]['start'],6.1)

    def test_cut_word_rejected(self):
        with self.assertRaisesRegex(ValueError,'cuts through word'):
            map_words([{'word':'שלום','start':1,'end':2}],1.5,3,0)

    def test_ordered_alignment(self):
        result=jobs.words_from_alignment({'characters':list('שלום 12'),'character_start_times_seconds':[i*.1 for i in range(7)],
                                         'character_end_times_seconds':[(i+1)*.1 for i in range(7)]})
        self.assertEqual([w['word'] for w in result],['שלום','12'])

    def test_phrase_break_and_srt_rounding(self):
        words=[{'word':'שלום.','start':0,'end':1},{'word':'עולם','start':1.2,'end':2}]
        self.assertEqual(len(phrases(words)),2)
        self.assertEqual(srt_time(59.9996),'00:01:00,000')

    def test_bad_timestamps_rejected(self):
        with self.assertRaises(ValueError): checked_words({'words':[{'word':'x','start':1,'end':0}]})


class SunoBridgeTests(unittest.TestCase):
    def check(self, response, should_submit):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); module=root/'fake-client.mjs'; request=root/'request.json'
            module.write_text('export class SunoClient { constructor(){this.cookie="mock";} async api(path){'
                +'if(path==="/api/c/check") return '+json.dumps(response)+';'
                +'throw new Error("UNEXPECTED_GENERATION"); }}',encoding='utf-8')
            request.write_text(json.dumps({'style':'test','instrumental':True,'model':'mock'}),encoding='utf-8')
            result=subprocess.run(['node',str(jobs.ROOT/'scripts/suno_bridge.mjs'),'submit',str(module),str(request)],capture_output=True,text=True)
            value=json.loads(result.stdout)
            if should_submit:
                self.assertEqual(value['status'],'unknown'); self.assertEqual(result.returncode,1)
            else:
                self.assertFalse(value['submitted']); self.assertEqual(value['status'],'blocked'); self.assertEqual(result.returncode,0)

    def test_unknown_captcha_does_not_submit(self): self.check({'status':200,'body':{}},False)
    def test_captcha_http_failure_does_not_submit(self): self.check({'status':503,'body':{'required':False}},False)
    def test_explicit_clear_captcha_reaches_submit(self): self.check({'status':200,'body':{'required':False}},True)


if __name__=='__main__': unittest.main()
