import json
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch
import provider_jobs as jobs


class GensparkFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.config={'grok':{'model':'xai/grok-imagine-video'},'genspark':{'route':'browser_existing_account','model':'xai/grok-imagine-video','browser_url':'https://www.genspark.ai/agents?type=video_generation_agent'}}
        self.ref=self.root/'first.png';self.ref.write_bytes(b'fixture image')
        self.original={'provider':'grok','prompt':'A child deposits one coin.','references':[str(self.ref)],'duration_seconds':6,'aspect_ratio':'9:16','resolution':'720P','audio':False}
        p=self.root/'original.json';p.write_text(json.dumps(self.original))
        self.parent=jobs.prepare(p,self.root/'jobs',self.config)
        data=jobs.load_json(self.parent/'job.json');data['state']='failed';jobs.atomic_json(self.parent/'job.json',data)
        self.request={**self.original,'provider':'genspark','fallback_for':str(self.parent/'job.json')}

    def tearDown(self):self.temp.cleanup()
    def prepare(self,request=None):
        p=self.root/'fallback.json';p.write_text(json.dumps(request or self.request));return jobs.prepare(p,self.root/'jobs',self.config)
    def ready(self):
        folder=self.prepare();jobs.authorize(folder,'User authorized one existing-credit fallback',1,'initial generation request')
        jobs.browser_check(folder,10000,'Signed-in website menu observed with 10000 credits')
        return folder
    def test_emits_exact_browser_workflow_and_reserves_once(self):
        folder=self.ready();result=jobs.execute(folder,self.config,1)
        self.assertEqual(result['state'],'awaiting_agent_tool')
        self.assertEqual(result['tool_request']['first_frame_path'],str(self.ref))
        self.assertEqual(result['tool_request']['count'],1)
        self.assertFalse(result['tool_request']['auto_prompt'])
        with self.assertRaisesRegex(ValueError,'already attempted'):jobs.execute(folder,self.config,1)
    def test_unknown_or_successful_parent_cannot_be_fallback(self):
        for state in ('unknown','submitted','submitting','complete'):
            parent=jobs.load_json(self.parent/'job.json');parent['state']=state;jobs.atomic_json(self.parent/'job.json',parent)
            with self.subTest(state=state),self.assertRaisesRegex(ValueError,'Reconcile'):self.prepare()
    def test_changed_contract_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'shot contract'):self.prepare({**self.request,'prompt':'A different action'})
    def test_parent_success_after_preparation_blocks_execution(self):
        folder=self.ready();parent=jobs.load_json(self.parent/'job.json');parent['state']='complete';jobs.atomic_json(self.parent/'job.json',parent)
        with self.assertRaisesRegex(ValueError,'Reconcile'):jobs.execute(folder,self.config,1)
    def test_fresh_positive_browser_balance_required(self):
        folder=self.prepare();jobs.authorize(folder,'One attempt approved',1,'request')
        with self.assertRaisesRegex(ValueError,'browser-check'):jobs.execute(folder,self.config,1)
        jobs.browser_check(folder,0,'Website says zero')
        with self.assertRaisesRegex(ValueError,'browser-check'):jobs.execute(folder,self.config,1)
    def test_uncertain_browser_submission_cannot_be_repeated(self):
        folder=self.ready();jobs.execute(folder,self.config,1)
        jobs.record_browser(folder,'https://www.genspark.ai/agents?id=fixture','unknown','Connection lost after click')
        with self.assertRaisesRegex(ValueError,'already attempted'):jobs.execute(folder,self.config,1)
    def test_receipt_cannot_reference_unrelated_site(self):
        folder=self.ready();jobs.execute(folder,self.config,1)
        with self.assertRaisesRegex(ValueError,'Genspark task URL'):jobs.record_browser(folder,'https://example.com','submitted','receipt')
    def test_register_keeps_actual_video_hash_and_rejects_image(self):
        folder=self.ready();jobs.execute(folder,self.config,1)
        with self.assertRaisesRegex(ValueError,'extension'):jobs.register(folder,self.ref,'Not a video')
        video=self.root/'result.mp4';video.write_bytes(b'video fixture')
        with patch('studio.ffprobe',return_value={'streams':[{'codec_type':'video'}]}):
            result=jobs.register(folder,video,'Verified completed task fixture')
        self.assertEqual(result['state'],'complete');self.assertEqual(len(result['assets']),1)
    def test_cli_saves_result_before_collection_and_never_repeats(self):
        self.config['genspark'].update(route='existing_cli',cli_entry='fixture.js')
        folder=self.ready()
        response={'status':'ok','data':{'generated_videos':[{'task_id':'fixture','video_urls':['https://www.genspark.ai/api/files/s/fixture']} ]}}
        with patch.object(jobs,'probe',return_value={'cli_authenticated':True,'cli_credit_balance':10000}),patch.object(jobs.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(response).encode(),b'')) as submit:
            result=jobs.execute(folder,self.config,1)
            self.assertEqual(result['state'],'submitted');self.assertTrue((folder/'genspark-response.json').exists())
            payload=jobs.load_json(folder/'genspark-submit.json')
            self.assertEqual(payload['image_urls'],[str(self.ref)]);self.assertFalse(payload['reference_mode'])
            with self.assertRaisesRegex(ValueError,'already attempted'):jobs.execute(folder,self.config,1)
            self.assertEqual(submit.call_count,1)
    def test_cli_empty_balance_blocks_before_transport(self):
        self.config['genspark'].update(route='existing_cli',cli_entry='fixture.js');folder=self.ready()
        with patch.object(jobs,'probe',return_value={'cli_authenticated':True,'cli_credit_balance':0}),patch.object(jobs.subprocess,'run') as submit:
            with self.assertRaisesRegex(ValueError,'no verified usable credits'):jobs.execute(folder,self.config,1)
            submit.assert_not_called()
        self.assertEqual(jobs.load_json(folder/'job.json')['state'],'prepared')
    def test_cli_timeout_preserves_unknown_state(self):
        self.config['genspark'].update(route='existing_cli',cli_entry='fixture.js');folder=self.ready()
        with patch.object(jobs,'probe',return_value={'cli_authenticated':True,'cli_credit_balance':10000}),patch.object(jobs.subprocess,'run',side_effect=subprocess.TimeoutExpired('fixture',1)):
            with self.assertRaises(ValueError):jobs.execute(folder,self.config,1)
        self.assertEqual(jobs.load_json(folder/'job.json')['state'],'unknown')

if __name__=='__main__':unittest.main()
