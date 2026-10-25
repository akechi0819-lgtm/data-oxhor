import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo
from dashboard_product.shadow_bi.p5 import notification_contract as c
from monitoring_product import receiver_notify_worker as w

class NotificationContractTests(unittest.TestCase):
    def setUp(self):
        self.payload={'operation':'preview','expected_release':'daily-fixture','as_of_date':'2026-10-26'}
        self.manifest={'as_of_date':'2026-10-26','coverage':{'data_through':'2026-10-25'}}
        self.policy={'send_start_date':'2026-10-26','no_backfill':True,'history_complete':False,'imported_state_ready':True}
        self.now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Shanghai'))
    def test_identity_is_idempotent_and_retry_does_not_change_it(self):
        self.assertEqual(c.job_id(self.payload),c.job_id({**self.payload,'retry':True}))
    def test_no_arbitrary_operation_path_recipient_or_date(self):
        for value in ({**self.payload,'command':'whoami'}, {**self.payload,'recipient':'other'},
                      {**self.payload,'operation':'status'}, {**self.payload,'expected_release':'../../etc'},
                      {**self.payload,'as_of_date':'20261026'}, {**self.payload,'retry':1}):
            with self.subTest(value=value), self.assertRaises(c.Rejected):c.normalize(value)
    def test_stale_current_and_incomplete_cutoff_fail(self):
        for release,manifest in [('daily-other',self.manifest),('daily-fixture',{**self.manifest,'coverage':{'data_through':'2026-10-24'}})]:
            with self.assertRaises(c.Rejected):c.validate(self.payload,release,manifest,self.policy,self.now)
    def test_sending_requires_start_time_and_import_proof(self):
        item={**self.payload,'operation':'send-scheduled'}
        c.validate(item,'daily-fixture',self.manifest,self.policy,self.now)
        for policy,now in [({**self.policy,'send_start_date':'2026-10-27'},self.now),
                            (self.policy,self.now.replace(hour=11)),
                            ({**self.policy,'imported_state_ready':False},self.now)]:
            with self.assertRaises(c.Rejected):c.validate(item,'daily-fixture',self.manifest,policy,now)
    def test_preview_ignores_sending_window_without_granting_send(self):
        c.validate(self.payload,'daily-fixture',self.manifest,{},self.now.replace(hour=18))

class WorkerTests(NotificationContractTests):
    def setUp(self):
        super().setUp()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'receiver';self.control=self.base/'control'
        for p in (self.root/'notify-requests',self.root/'notify-pending',self.control/'results',self.base/'releases/daily-fixture/library'):p.mkdir(parents=True,exist_ok=True)
        (self.base/'current').symlink_to(self.base/'releases/daily-fixture')
        (self.base/'current/library/library_manifest.json').write_text(json.dumps(self.manifest))
        (self.control/'policy.json').write_text(json.dumps(self.policy))
    def save(self,control,identifier,result):
        (control/'results'/(identifier+'.json')).write_text(json.dumps(result))
    def invoke(self,payload=None,execute=None):
        payload=payload or self.payload;identifier=c.job_id(payload)
        (self.root/'notify-requests'/(identifier+'.json')).write_text(json.dumps(payload))
        (self.root/'notify-pending'/identifier).touch()
        w.process(identifier,root=self.root,control=self.control,now=self.now,execute=execute,save=self.save)
        return json.loads((self.control/'results'/(identifier+'.json')).read_bytes())
    def report(self,operation='preview',status='dry_run',counts=None):
        return SimpleNamespace(returncode=0,stdout=json.dumps({'status':status,'release_id':'daily-fixture','as_of_date':'2026-10-26','message_count':8,'message_status_counts':counts or {'preview':8},'network_send_attempted':operation=='send-scheduled'}))
    def test_fixed_argv_and_duplicate_never_executes_twice(self):
        execute=Mock(return_value=self.report())
        self.assertEqual(self.invoke(execute=execute)['status'],'dry_run')
        self.invoke(execute=execute)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[0],[w.ENTRY,'preview','daily-fixture','2026-10-26'])
    def test_stale_request_and_symlink_do_not_execute(self):
        execute=Mock()
        self.manifest['as_of_date']='2026-10-25';(self.base/'current/library/library_manifest.json').write_text(json.dumps(self.manifest))
        self.assertEqual(self.invoke(execute=execute)['status'],'blocked');execute.assert_not_called()
        p=self.root/'notify-requests'/'bad.json';p.symlink_to(self.control/'policy.json')
        with self.assertRaises(OSError):w.read_request(p.parent,p.name)
    def test_unknown_outcome_cannot_be_replayed(self):
        payload={**self.payload,'operation':'send-scheduled'}
        execute=Mock(side_effect=TimeoutError())
        first=self.invoke(payload,execute)
        self.assertEqual(first['status'],'unknown');self.assertFalse(first['retryable'])
        self.invoke({**payload,'retry':True},execute);execute.assert_called_once()
    def test_partial_pending_has_bounded_explicit_retry(self):
        payload={**self.payload,'operation':'send-scheduled'}
        execute=Mock(return_value=self.report('send-scheduled','partial',{'sent':1,'pending':7}))
        first=self.invoke(payload,execute);self.assertTrue(first['retryable'])
        second=self.invoke(payload,execute);self.assertEqual(execute.call_count,1)
        self.assertEqual(second['status'],'partial')
        self.invoke({**payload,'retry':True},execute)
        self.assertEqual(execute.call_count,2)
        self.invoke({**payload,'retry':True},execute)
        self.invoke({**payload,'retry':True},execute)
        self.assertEqual(execute.call_count,3)
    def test_running_after_crash_blocks_without_replay(self):
        identifier=c.job_id(self.payload)
        self.save(self.control,identifier,{'status':'running','attempt':1})
        execute=Mock();self.assertEqual(self.invoke(execute=execute)['status'],'unknown');execute.assert_not_called()

    def test_partial_unknown_result_does_not_allow_retries(self):
        payload={**self.payload,'operation':'send-scheduled'}
        execute=Mock(return_value=self.report('send-scheduled','partial',{'unknown':1,'pending':7}))
        self.assertFalse(self.invoke(payload,execute)['retryable'])
        self.invoke({**payload,'retry':True},execute);execute.assert_called_once()
