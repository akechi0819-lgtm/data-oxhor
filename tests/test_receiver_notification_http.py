import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
try:
    import flask
except ModuleNotFoundError:
    raise unittest.SkipTest('receiver HTTP tests require locked Flask runtime')
from dashboard_product.shadow_bi.p5 import notification_contract as c

class ReceiverNotificationHTTPTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        base=Path(tmp.name);root=base/'receiver';release=base/'releases/daily-fixture'
        (release/'library').mkdir(parents=True);(base/'current').symlink_to(release)
        (release/'library/library_manifest.json').write_text(json.dumps({'as_of_date':'2026-10-25','coverage':{'data_through':'2026-10-24'}}))
        self.control=base/'control';(self.control/'results').mkdir(parents=True)
        (self.control/'policy.json').write_text(json.dumps({'send_start_date':'2026-10-26','no_backfill':True,'history_complete':False,'imported_state_ready':True}))
        token='synthetic-only'
        with patch.dict(os.environ,SHADOW_RECEIVER_ROOT=str(root),SHADOW_RECEIVER_TOKEN_SHA256=hashlib.sha256(token.encode()).hexdigest(),SHADOW_RECEIVER_NOTIFY_ENABLED='1'):
            spec=importlib.util.spec_from_file_location('fixture_notify_receiver',Path(__file__).resolve().parents[1]/'dashboard_product/shadow_bi/p5/receiver.py')
            self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.module.NOTIFY_CONTROL=self.control;self.client=self.module.app.test_client()
        self.headers={'Authorization':'Bearer '+token};self.root=root
        self.payload={'operation':'preview','expected_release':'daily-fixture','as_of_date':'2026-10-25'}
        validate=c.validate
        clock=datetime(2026,10,25,10,tzinfo=ZoneInfo('Asia/Shanghai'))
        patcher=patch.object(c,'validate',side_effect=lambda *args:validate(*args,now=clock));patcher.start();self.addCleanup(patcher.stop)
    def test_auth_before_status_parse_and_queue(self):
        for method,path in [('get','/v1/notifications/status'),('post','/v1/notifications/jobs'),('get','/v1/notifications/jobs/'+'0'*64)]:
            self.assertEqual(getattr(self.client,method)(path).status_code,401)
        self.assertFalse(self.root.exists())
    def test_preview_queue_is_async_idempotent_and_returns_sanitized_receipt(self):
        first=self.client.post('/v1/notifications/jobs',headers=self.headers,json=self.payload)
        self.assertEqual(first.status_code,202);identifier=first.json['job_id']
        self.assertEqual(self.client.post('/v1/notifications/jobs',headers=self.headers,json=self.payload).status_code,200)
        self.assertEqual(len(list((self.root/'notify-pending').iterdir())),1)
        self.assertEqual(self.client.get('/v1/notifications/jobs/'+identifier,headers=self.headers).json['status'],'queued')
        self.assertEqual(self.client.get('/v1/notifications/status',headers=self.headers).status_code,200)
    def test_real_send_before_cutover_and_stale_extra_fields_are_rejected(self):
        for item,status in [({**self.payload,'operation':'send-scheduled'},403),({**self.payload,'expected_release':'daily-wrong'},409),({**self.payload,'command':'uname'},400)]:
            self.assertEqual(self.client.post('/v1/notifications/jobs',headers=self.headers,json=item).status_code,status)
        self.assertFalse((self.root/'notify-pending').exists())

    def test_reconciliation_is_an_additional_receipt_not_a_rewritten_job(self):
        identifier='0'*64;path=self.control/'results'/(identifier+'.json')
        original=json.dumps({'status':'unknown','retryable':False,'network_send_attempted':True}).encode();path.write_bytes(original)
        folder=self.control/'reconciliations';folder.mkdir();(folder/(identifier+'.json')).write_text('{}')
        receipt={'delivery_status':'sent','message_status_counts':{'sent':8},'no_send_performed':True}
        with patch('monitoring_product.notification_job_reconcile.read_receipt',return_value=receipt):
            value=self.client.get('/v1/notifications/jobs/'+identifier,headers=self.headers)
        self.assertEqual(value.status_code,200);self.assertEqual(value.json['status'],'unknown')
        self.assertFalse(value.json['retryable']);self.assertEqual(value.json['delivery_reconciliation'],receipt)
        self.assertEqual(path.read_bytes(),original)
