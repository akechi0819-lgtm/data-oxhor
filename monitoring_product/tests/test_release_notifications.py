"""Isolated server release/notification contract; all HTTP is prohibited."""
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from dashboard_product.management.tests import test_notifications as fixture_notifications
from dashboard_product.management.tests.test_notifications import order
from dashboard_product.management.notifications import build_notifications
from dashboard_product.shadow_bi.library import write_table
from data_platform.query.evidence import file_ref
from monitoring_product import release_notifications as n, shared_delivery as d, delivery_transport as transport
from monitoring_product.tests.test_shared_delivery import _fake_render_notifications


class ReleaseNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.network = patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden'))
        self.network.start(); self.addCleanup(self.network.stop)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start(); self.addCleanup(self.environment.stop)
        f = fixture_notifications.ManagementNotificationsTest(); f.setUp()
        self.fixture = f
        self.release = self.root/'daily-fixture'; self.release.mkdir()
        self.library = self.release/'library'; self.library.mkdir()
        self.current = self.root/'current'; self.current.symlink_to(self.release)
        metadata = {'run_id':'run_fixture_20260929','snapshot_id':'snapshot_fixture_20260929',
                    'data_through':'2026-09-28', 'study_abroad_source':{
                        **f.public['metadata']['study_abroad_source'],
                        'snapshot_id':'snapshot_study_20260929','through_date':'2026-09-28'}}
        self.public = deepcopy(f.public); self.public['metadata'] = metadata
        rows = {'periods':[{k:v for k,v in p.items() if k!='teams'} for p in self.public['periods']],
                'team_periods':[{'period_id':p['id'],'team_id':t['id'],'view':t} for p in self.public['periods'] for t in p['teams']],
                'facts':f.facts, 'personnel_facts':f.facts,
                'target_roster_references':[{'name':name,'document':value,'sha256':'a'*64} for name,value in
                    [('people.json',f.people),('offline_market_people.json',f.abroad_people)]]}
        database = self.library/'business.duckdb'
        with duckdb.connect(str(database)) as con:
            con.execute('CREATE SCHEMA queries')
            tables = {name:write_table(con,self.library,name,values) for name,values in rows.items()}
            con.execute("CREATE TABLE queries.batch AS SELECT 'run_fixture_20260929' AS batch_id")
        self.manifest = {'schema_version':'business_query_library.v1','batch_id':metadata['run_id'],
            'as_of_date':'2026-09-29','coverage':metadata,
            'snapshots':{'training':metadata['snapshot_id'],'abroad':metadata['study_abroad_source']['snapshot_id']},
            'binding':{'inputs':{'Work/Pack/pack.json':'a'*64,'Work/Bridge/reference.json':'b'*64},'rules':{'fixture':'c'*64}},
            'source_queries':[{'source':'synthetic-only'}], 'tables':tables,
            'database':file_ref(database,self.library,'application/vnd.duckdb')}
        self.write_manifest()
        self.bundle = self.root/'bundle'
        n.build_bundle(library=self.library,batch_id=metadata['run_id'],release_id=self.release.name,output_dir=self.bundle)
        self.state = self.root/'state'
        self.env = self.root/'credentials.env'
        self.env.write_text('\n'.join(f'{transport.webhook_env_name(channel)}=https://example.invalid/fixture' for channel in sorted(transport.ALLOWED_CHANNELS)))
        self.assets = self.root/'assets'; self.assets.mkdir()

    def write_manifest(self):
        (self.library/'library_manifest.json').write_bytes(n.canonical(self.manifest))

    def seed_state(self, rows=None):
        self.state.mkdir(exist_ok=True)
        self.proof=self.state.parent/'state-origin';self.proof.mkdir(exist_ok=True)
        state={'schema_version':d.STATE_SCHEMA,'deliveries':rows or {}}
        encoded=n.canonical(state)
        (self.proof/'imported_state.json').write_bytes(encoded)
        (self.state/d.STATE_FILENAME).write_bytes(encoded)
        (self.proof/'delivery_origin.json').write_bytes(n.canonical({
            'schema_version':'delivery_state_import.v1','source':'grok',
            'sha256':hashlib.sha256(encoded).hexdigest(),'channels':sorted(transport.ALLOWED_CHANNELS),
            'cutover_policy':{'no_backfill':True,'history_complete':False,'send_start_date':'2026-09-29'}}))

    def invoke(self, *, dry_run=False):
        with patch.object(d,'_today_shanghai',return_value=date(2026,9,29)), \
             patch('monitoring_product.shared_preview.render_notifications',side_effect=_fake_render_notifications):
            return n.deliver_bundle(bundle_path=self.bundle/'bundle.json',current_release=self.current,
                output_dir=self.root/'rendered',state_dir=self.state,env_file=self.env,
                asset_root=self.assets,dry_run=dry_run)

    def test_controlled_release_reconstruction_and_native_link(self):
        bundle,_=n.verify_bundle(self.bundle/'bundle.json',self.current)
        payload=json.loads((self.bundle/'notifications.json').read_bytes())
        self.assertEqual(len(payload['messages']),8)
        self.assertEqual(bundle['source']['semantics'],self.manifest['binding']['inputs'])
        result=self.invoke(dry_run=True)
        self.assertEqual(len(result['messages']),8)
        self.assertFalse(self.state.exists())
        from monitoring_product.shared_preview import _dashboard_url
        for message in payload['messages']:
            self.assertEqual(_dashboard_url(message,n.NATIVE_URL),n.NATIVE_URL)

    def test_personal_source_controls_daily_and_ledger_without_expanding_team(self):
        f=self.fixture
        extra=order('personal-only','training','offline_market',group='大学',owners=('大学同事',))
        old=build_notifications(deepcopy(f.public),f.facts,f.people,f.abroad_people)
        new=build_notifications(deepcopy(f.public),f.facts,f.people,f.abroad_people,person_facts=[*f.facts,extra])
        before=next(x for x in old['messages'] if x['id']=='university.training')
        after=next(x for x in new['messages'] if x['id']=='university.training')
        self.assertEqual(before['team_metrics'],after['team_metrics'])
        self.assertEqual(before['ledgers']['team_orders'],after['ledgers']['team_orders'])
        self.assertEqual(after['people'][0]['today_orders'],before['people'][0]['today_orders']+1)
        self.assertIn('personal-only',[x['work_order_id'] for x in after['ledgers']['personal_orders']])
        self.assertEqual([x['channel_id'] for x in old['messages']],[x['channel_id'] for x in new['messages']])

    def test_local_project_import_origin_is_accepted_without_grok_access(self):
        self.seed_state()
        path=self.proof/'delivery_origin.json';origin=json.loads(path.read_bytes())
        origin['source']='local-project';path.write_bytes(n.canonical(origin))
        self.assertEqual(n.require_imported_state(self.state)['schema_version'],d.STATE_SCHEMA)

    def test_missing_state_blocks_before_credentials_and_network(self):
        with patch.object(d,'_preflight_credentials',side_effect=AssertionError('credentials must not be read')):
            with self.assertRaisesRegex(ValueError,'DeliveryState'):
                self.invoke()
        self.assertFalse(self.state.exists())

    def test_import_evidence_and_saved_unknown_cannot_be_cleared(self):
        key='2026-09-29|offline_youth|prep.training'
        self.seed_state({key:{'status':'unknown'}})
        (self.state/d.STATE_FILENAME).write_bytes(n.canonical({'schema_version':d.STATE_SCHEMA,'deliveries':{}}))
        with self.assertRaisesRegex(ValueError,'must not be cleared'):
            self.invoke()
        (self.proof/'imported_state.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'migration evidence'):
            self.invoke()

    def test_current_release_and_snapshot_or_rule_changes_block(self):
        self.manifest['snapshots']['training']='snapshot_other_20260929';self.write_manifest()
        with self.assertRaises(ValueError):n.verify_bundle(self.bundle/'bundle.json',self.current)
        self.manifest['snapshots']['training']=self.manifest['coverage']['snapshot_id'];self.write_manifest()
        with patch.object(n,'rule_binding',return_value={}):
            with self.assertRaisesRegex(ValueError,'implementation digest'):
                n.verify_bundle(self.bundle/'bundle.json',self.current)
        other=self.root/'daily-other';other.mkdir();(other/'library').symlink_to(self.library)
        self.current.unlink();self.current.symlink_to(other)
        with self.assertRaisesRegex(ValueError,'current formal release'):
            n.verify_bundle(self.bundle/'bundle.json',self.current)

    def test_payload_and_query_result_tampering_block(self):
        notification=self.bundle/'notifications.json';original=notification.read_bytes();notification.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError,'digest'):
            n.verify_bundle(self.bundle/'bundle.json',self.current)
        notification.write_bytes(original)
        b=json.loads((self.bundle/'bundle.json').read_bytes());receipt=self.bundle/b['query_receipts'][0]['path']
        doc=json.loads(receipt.read_bytes());(receipt.parent/doc['result']['path']).write_text('{}')
        with self.assertRaises(ValueError):n.verify_bundle(self.bundle/'bundle.json',self.current)

    def test_stale_delivery_blocks_but_historical_preview_is_allowed(self):
        self.seed_state()
        with patch.object(d,'_today_shanghai',return_value=date(2026,9,30)):
            with self.assertRaisesRegex(ValueError,'today'):
                n.deliver_bundle(bundle_path=self.bundle/'bundle.json',current_release=self.current,
                    output_dir=self.root/'out',state_dir=self.state,env_file=self.env,asset_root=self.assets,dry_run=False)
        self.assertEqual(self.invoke(dry_run=True)['status'],'dry_run')

    def test_same_day_repeat_is_deduplicated_without_ssh_credentials(self):
        self.seed_state()
        with patch.object(transport,'post_dingtalk',return_value={'status':'sent'}) as posted:
            first=self.invoke();second=self.invoke()
        self.assertEqual(first['status'],'sent');self.assertEqual(second['status'],'sent')
        self.assertEqual(posted.call_count,8)
        self.assertTrue(all(x['deduplicated'] for x in second['messages']))
        self.assertEqual(len([p for p in self.assets.iterdir() if not p.name.startswith('.')]),8)

    def test_asset_failure_is_pending_and_only_that_message_retries(self):
        self.seed_state();original=n.publish_local_assets;count=0
        def upload(*args,**kwargs):
            nonlocal count
            count+=1
            if count==1:raise OSError('synthetic asset failure')
            return original(*args,**kwargs)
        with patch.object(n,'publish_local_assets',side_effect=upload),patch.object(transport,'post_dingtalk',return_value={'status':'sent'}) as posted:
            first=self.invoke();second=self.invoke()
        self.assertEqual(first['status'],'partial');self.assertEqual(first['messages'][0]['status'],'pending')
        self.assertEqual(second['status'],'sent');self.assertEqual(posted.call_count,8)

    def test_uncertain_http_is_never_retried_and_remaining_messages_continue(self):
        self.seed_state();count=0
        def send(*args):
            nonlocal count
            count+=1
            if count==1:raise TimeoutError('synthetic outcome unknown')
            return {'status':'sent'}
        with patch.object(transport,'post_dingtalk',side_effect=send) as posted:
            first=self.invoke();second=self.invoke()
        self.assertEqual(first['status'],'partial');self.assertEqual(second['status'],'partial')
        self.assertEqual(second['messages'][0]['status'],'unknown');self.assertEqual(posted.call_count,8)

    def test_current_switch_during_batch_leaves_remaining_pending(self):
        self.seed_state();other=self.root/'daily-other';other.mkdir();(other/'library').symlink_to(self.library)
        def send(*args):
            self.current.unlink();self.current.symlink_to(other)
            return {'status':'sent'}
        with patch.object(transport,'post_dingtalk',side_effect=send) as posted:
            result=self.invoke()
        self.assertEqual(posted.call_count,1)
        self.assertEqual([x['status'] for x in result['messages']],['sent']+['pending']*7)

    def test_server_status_reports_missing_history_without_loading_credentials(self):
        from monitoring_product.server_notify import run
        report=run('status',warehouse=self.root,home=self.root,env_file=self.env,asset_root=self.assets)
        self.assertFalse(report['imported_state_ready'])
        self.assertEqual(report['status'],'blocked')

    def test_server_scheduled_entry_rejects_outside_ten_before_build_or_credentials(self):
        from monitoring_product.server_notify import run
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with patch.object(n,'build_bundle',side_effect=AssertionError('must not build')):
            with self.assertRaisesRegex(ValueError,'10:00'):
                run('send-scheduled',warehouse=self.root,home=self.root,env_file=self.env,
                    asset_root=self.assets,now=datetime(2026,9,29,11,tzinfo=ZoneInfo('Asia/Shanghai')))
        with self.assertRaisesRegex(ValueError,'DeliveryState'):
            run('send-scheduled',warehouse=self.root,home=self.root,env_file=self.env,
                asset_root=self.assets,now=datetime(2026,9,29,10,tzinfo=ZoneInfo('Asia/Shanghai')))

    def test_fixed_server_preview_does_not_send_or_initialize_history(self):
        from monitoring_product.server_notify import run
        with patch('monitoring_product.shared_preview.render_notifications',side_effect=_fake_render_notifications):
            report=run('preview',warehouse=self.root,home=self.root,env_file=self.env,asset_root=self.assets)
        self.assertEqual(report['status'],'dry_run')
        self.assertEqual(report['message_count'],8)
        self.assertFalse(report['network_send_attempted'])
        self.assertFalse(self.state.exists())

    def test_cutover_preserves_history_and_refuses_older_date(self):
        self.seed_state()
        path=self.proof/'delivery_origin.json';origin=json.loads(path.read_bytes())
        origin['cutover_policy']['send_start_date']='2026-09-30'
        path.write_bytes(n.canonical(origin))
        with self.assertRaisesRegex(ValueError,'cutover'):
            self.invoke()

    def test_clock_window_is_checked_again_before_each_message(self):
        from monitoring_product import server_notify as server
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.seed_state()
        moment=datetime(2026,9,29,10,tzinfo=ZoneInfo('Asia/Shanghai'))
        def fake_delivery(**kwargs):
            kwargs['before_send']()
            raise AssertionError('expired window must reject before sending')
        with patch.object(server,'datetime') as clock, patch.object(n,'deliver_bundle',side_effect=fake_delivery):
            clock.now.side_effect=[moment,moment.replace(hour=11)]
            with self.assertRaisesRegex(ValueError,'window elapsed'):
                server.run('send-scheduled',warehouse=self.root,home=self.root,env_file=self.env,asset_root=self.assets)

    def test_expected_release_mismatch_blocks_before_build(self):
        from monitoring_product.server_notify import run
        with patch.object(n,'build_bundle',side_effect=AssertionError('must not build')):
            with self.assertRaisesRegex(ValueError,'expected current'):
                run('preview',warehouse=self.root,home=self.root,expected_release='daily-wrong')

    def test_missing_source_closure_is_not_filled_with_defaults(self):
        del self.manifest['tables']['personnel_facts'];self.write_manifest()
        with self.assertRaisesRegex(ValueError,'closure'):
            n.build_bundle(library=self.library,batch_id=self.manifest['batch_id'],release_id=self.release.name,output_dir=self.root/'missing')


if __name__=='__main__':unittest.main()
