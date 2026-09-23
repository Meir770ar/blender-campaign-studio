"""Self-delivery behavior with mocked WAHA; never contacts WhatsApp."""
import base64
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import whatsapp_delivery as wa


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name).resolve()
        self.copy=self.root/'final.mp4'; self.copy.write_bytes(b'mock encoded copy')
        self.inspect=patch.object(wa,'inspect',return_value={'streams':[{'codec_type':'video','codec_name':'h264','pix_fmt':'yuv420p'}]})
        self.inspect.start()
        # Delivery identity comes from connections.json at import; tests pin their own so they run on any machine.
        self.identity=patch.multiple(wa,HOST='root@test-host',SELF_CHAT='000000000000@c.us',SESSION='default')
        self.identity.start()

    def tearDown(self): self.identity.stop(); self.inspect.stop(); self.temp.cleanup()

    def prepare(self,caption='Final viewing copy'):
        return wa.prepare(self.copy,self.root/'deliveries',caption,'Explicit test-only instruction with mocked transport')

    def test_caption_change_does_not_duplicate_same_video(self):
        self.assertEqual(self.prepare(),self.prepare('A different caption'))

    def test_wrong_connected_identity_cannot_send(self):
        folder=self.prepare()
        with patch.object(wa,'session_status',return_value={'working':True,'self_matches':False}),patch.object(wa,'api') as api:
            with self.assertRaises(ValueError): wa.send(folder)
            api.assert_not_called()

    def test_changed_file_cannot_send(self):
        folder=self.prepare(); self.copy.write_bytes(b'changed')
        with patch.object(wa,'api') as api:
            with self.assertRaisesRegex(ValueError,'changed'): wa.send(folder)
            api.assert_not_called()

    def test_send_receipt_and_no_duplicate(self):
        folder=self.prepare()
        with patch.object(wa,'session_status',return_value={'working':True,'self_matches':True}),patch.object(wa,'api',return_value={'id':'message-1','ack':1}) as api:
            self.assertEqual(wa.send(folder)['state'],'accepted')
            endpoint,body=api.call_args.args
            self.assertEqual(endpoint,'/api/sendVideo'); self.assertEqual(body['chatId'],wa.SELF_CHAT)
            self.assertFalse(body['convert']); self.assertIn('data',body['file'])
            with self.assertRaises(ValueError): wa.send(folder)
            self.assertEqual(api.call_count,1)

    def test_timeout_is_unknown_and_not_retried(self):
        folder=self.prepare()
        with patch.object(wa,'session_status',return_value={'working':True,'self_matches':True}),patch.object(wa,'api',side_effect=TimeoutError) as api:
            with self.assertRaises(ValueError): wa.send(folder)
            with self.assertRaises(ValueError): wa.send(folder)
            self.assertEqual(api.call_count,1)
        self.assertEqual(wa.load_json(folder/'delivery.json')['state'],'unknown')

    def test_device_receipt_required_for_delivered(self):
        folder=self.prepare()
        with patch.object(wa,'session_status',return_value={'working':True,'self_matches':True}),patch.object(wa,'api',return_value={'id':'message-1','ack':1}): wa.send(folder)
        with patch.object(wa,'api',return_value={'ack':1}): self.assertEqual(wa.status(folder)['state'],'accepted')
        with patch.object(wa,'api',return_value={'ack':2}): self.assertEqual(wa.status(folder)['state'],'delivered')

    def uncertain(self):
        folder=self.prepare(); job=wa.load_json(folder/'delivery.json')
        job.update(state='unknown',attempted_at=wa.now()); wa.atomic_json(folder/'delivery.json',job)
        return folder,job

    def receipt(self,job,**changes):
        sha=base64.b64encode(bytes.fromhex(job['sha256'])).decode()
        return dict(dict(id='matched-message',fromMe=True,ack=1,timestamp=datetime.fromisoformat(job['attempted_at']).timestamp(),
             _data={'message':{'videoMessage':{'fileSha256':{'data':sha}}}}),**changes)

    def test_unknown_reconciles_by_hash_time_and_outgoing_without_send(self):
        folder,job=self.uncertain()
        with patch.object(wa,'session_status',return_value={'working':True,'self_matches':True}), \
             patch.object(wa,'api',return_value=[self.receipt(job)]) as api:
            result=wa.reconcile(folder)
            self.assertEqual(result['state'],'accepted'); self.assertTrue(result['reconciled'])
            self.assertEqual(len(api.call_args.args),1); self.assertIn('downloadMedia=false',api.call_args.args[0])
            with self.assertRaisesRegex(ValueError,'already attempted'): wa.send(folder)
            self.assertEqual(api.call_count,1)

    def test_ack_2_proves_delivery_after_reconciliation(self):
        folder,job=self.uncertain()
        with patch.object(wa,'session_status',return_value={'working':True,'self_matches':True}), \
             patch.object(wa,'api',return_value=[self.receipt(job,ack=2)]):
            self.assertEqual(wa.reconcile(folder)['state'],'delivered')

    def test_old_incoming_missing_time_and_wrong_hash_cannot_match(self):
        folder,job=self.uncertain(); past=datetime.fromisoformat(job['attempted_at']).timestamp()-60
        messages=[self.receipt(job,timestamp=past),self.receipt(job,fromMe=False),self.receipt(job,timestamp=None),
                  self.receipt(job,_data={'message':{'videoMessage':{'fileSha256':'invalid'}}}),self.receipt(job,_data=None)]
        with patch.object(wa,'session_status',return_value={'working':True,'self_matches':True}), \
             patch.object(wa,'api',return_value=messages):
            result=wa.reconcile(folder)
        self.assertEqual(result['matching_messages'],0); self.assertTrue(result['reconcile_required'])
        self.assertEqual(wa.load_json(folder/'delivery.json'),job)

    def test_ambiguous_receipts_do_not_resolve_or_resend(self):
        folder,job=self.uncertain()
        with patch.object(wa,'session_status',return_value={'working':True,'self_matches':True}), \
             patch.object(wa,'api',return_value=[self.receipt(job),self.receipt(job,id='second')]):
            result=wa.reconcile(folder)
        self.assertEqual(result['matching_messages'],2); self.assertEqual(result['state'],'unknown')
        self.assertEqual(wa.load_json(folder/'delivery.json'),job)

    def test_wrong_identity_or_unattempted_job_cannot_reconcile(self):
        prepared=self.prepare()
        with patch.object(wa,'api') as api:
            with self.assertRaisesRegex(ValueError,'recorded uncertain'): wa.reconcile(prepared)
            api.assert_not_called()
        folder,_=self.uncertain()
        with patch.object(wa,'session_status',return_value={'working':True,'self_matches':False}), patch.object(wa,'api') as api:
            with self.assertRaisesRegex(ValueError,'identity differs'): wa.reconcile(folder)
            api.assert_not_called()

    def test_changed_copy_and_transport_failure_preserve_unknown(self):
        folder,job=self.uncertain()
        with patch.object(wa,'session_status',return_value={'working':True,'self_matches':True}), \
             patch.object(wa,'api',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError): wa.reconcile(folder)
        self.assertEqual(wa.load_json(folder/'delivery.json'),job)
        self.copy.write_bytes(b'changed')
        with patch.object(wa,'api') as api:
            with self.assertRaisesRegex(ValueError,'changed'): wa.reconcile(folder)
            api.assert_not_called()


if __name__=='__main__': unittest.main()
