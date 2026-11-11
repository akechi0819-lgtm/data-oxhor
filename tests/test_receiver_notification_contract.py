import json
from datetime import datetime
import hashlib
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo
from dashboard_product.shadow_bi.p5 import notification_contract as c
from monitoring_product import receiver_notify_worker as w


def write_sql_release(library, *, as_of_date='2026-10-26', through='2026-10-25', batch_id='run_fixture'):
    snapshots={'training':'snapshot_training','abroad':'snapshot_abroad'}
    coverage={'data_through':through,'snapshot_id':snapshots['training'],
              'study_abroad_source':{'snapshot_id':snapshots['abroad'],'through_date':through}}
    warehouse_bytes=b'synthetic warehouse bytes'
    (library/'warehouse.duckdb').write_bytes(warehouse_bytes)
    database={'path':'warehouse.duckdb','sha256':hashlib.sha256(warehouse_bytes).hexdigest(),
              'size_bytes':len(warehouse_bytes),'media_type':'application/vnd.duckdb'}
    candidate={'schema_version':'sql_warehouse_candidate.v1','batch_id':batch_id,
               'as_of_date':as_of_date,'through_date':through,'snapshots':snapshots,
               'database':database}
    candidate_bytes=json.dumps(candidate).encode()
    (library/'candidate.json').write_bytes(candidate_bytes)
    candidate_sha=hashlib.sha256(candidate_bytes).hexdigest()
    release={'schema_version':'sql_warehouse_release.v1','release_id':library.parent.name,
             'batch_id':batch_id,'as_of_date':as_of_date,'through_date':through,
             'snapshots':snapshots,'coverage':coverage,
             'candidate':{'path':'candidate.json','sha256':candidate_sha,
                          'size_bytes':len(candidate_bytes),'media_type':'application/json'},
             'candidate_sha256':candidate_sha,'database_sha256':database['sha256']}
    (library/'release.json').write_text(json.dumps(release))
    return release

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

    def test_current_manifest_validates_candidate_identity_and_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            library=Path(folder)/'releases/daily-fixture/library'
            library.mkdir(parents=True)
            release=write_sql_release(library)
            self.assertEqual(c.current_manifest(library),release)
            tampered=json.loads((library/'candidate.json').read_bytes())
            tampered['status']='tampered'
            (library/'candidate.json').write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError,'candidate digest'):
                c.current_manifest(library)

    def test_current_manifest_rejects_release_identity_drift(self):
        for field,value in [('batch_id','run_other'),('as_of_date','2026-10-27'),
                            ('snapshots',{'training':'snapshot_other','abroad':'snapshot_abroad'})]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                library=Path(folder)/'releases/daily-fixture/library'
                library.mkdir(parents=True)
                write_sql_release(library)
                release=json.loads((library/'release.json').read_bytes())
                release[field]=value
                (library/'release.json').write_text(json.dumps(release))
                with self.assertRaises(ValueError):c.current_manifest(library)

    def test_legacy_manifest_is_available_for_explicit_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            library=Path(folder)/'releases/daily-fixture/library'
            library.mkdir(parents=True)
            legacy={'schema_version':'business_query_library.v1','batch_id':'run_legacy',
                    'as_of_date':'2026-10-26','coverage':{'data_through':'2026-10-25'}}
            (library/'library_manifest.json').write_text(json.dumps(legacy))
            self.assertEqual(c.current_manifest(library),legacy)

class WorkerTests(NotificationContractTests):
    def setUp(self):
        super().setUp()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'receiver';self.control=self.base/'control'
        library=self.base/'releases/daily-fixture/library'
        for p in (self.root/'notify-requests',self.root/'notify-pending',self.control/'results',library):p.mkdir(parents=True,exist_ok=True)
        (self.base/'current').symlink_to(self.base/'releases/daily-fixture')
        self.manifest=write_sql_release(library)
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
        self.manifest=write_sql_release(self.base/'current/library',as_of_date='2026-10-25',through='2026-10-24')
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


    def test_busy_exit_is_persisted_without_claiming_network_send(self):
        payload={**self.payload,'operation':'send-scheduled'}
        output=SimpleNamespace(returncode=75,stdout='',stderr='')
        execute=Mock(return_value=output)
        result=self.invoke(payload,execute)
        self.assertEqual(result['status'],'blocked');self.assertTrue(result['retryable'])
        self.assertFalse(result['network_send_attempted']);self.assertEqual(result['executor_returncode'],75)
        identifier=c.job_id(payload)
        evidence=json.loads((self.control/'executor-evidence'/(identifier+'-1.json')).read_bytes())
        self.assertEqual(evidence['returncode'],75)
        self.invoke(payload,execute);execute.assert_called_once()

    def test_malformed_executor_keeps_audit_and_unknown_without_secrets(self):
        payload={**self.payload,'operation':'send-scheduled'}
        output=SimpleNamespace(returncode=2,stdout=json.dumps({'status':'blocked','error_type':'ValueError'}),stderr='synthetic private detail')
        result=self.invoke(payload,Mock(return_value=output))
        self.assertEqual(result['status'],'unknown');self.assertEqual(result['executor_returncode'],2)
        self.assertEqual(result['executor_error_type'],'ValueError');self.assertFalse(result['retryable'])
        evidence=(self.control/'executor-evidence'/(c.job_id(payload)+'-1.json')).read_text()
        self.assertNotIn('synthetic private detail',evidence)
