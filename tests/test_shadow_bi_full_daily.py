import importlib.util
import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from dashboard_product.shadow_bi.p5 import full_daily as daily

NOW = datetime(2026, 10, 28, 9, 30, tzinfo=ZoneInfo('Asia/Shanghai'))
PAIR = {'sources': {'bi': {'value_sha256': 'a' * 64}, 'study_abroad': {'value_sha256': 'b' * 64}}}


class FullDailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.workspace = self.root / 'workspace'
        self.repo = self.root / 'repo'
        rule = self.repo / 'dashboard_product/management/calculation.py'
        rule.parent.mkdir(parents=True)
        rule.write_text('# known rule\n')
        self.rule = rule
        self.expected = {'xhs': {'accounts': ['123'], 'manifest_source_ids': ['xhs'],
                        'parsed_source_ids': ['xhs:123'], 'start_date': '2026-10-26', 'dense_daily': True}}
        config = self.workspace / '.private/full-daily-sources.json'
        daily.atomic_json(config, {'expected_sources': self.expected})
        self.normal = self.workspace / 'Input/AdvertisingCosts/sources.json'
        daily.atomic_json(self.normal, {'sources': []})
        self.original = self.normal.read_bytes()
        self.published = []

    def collect(self, workspace, day, run_id, folder):
        raw = folder / 'native.csv'
        raw.write_text('周期,投放ID,账户类型,广告主账户ID,总消耗\n20261026,123,代理商子账户,brand,1\n20261027,123,代理商子账户,brand,2\n')
        proof = folder / 'native-window.json'
        daily.atomic_json(proof, {'selected_start': '2026-10-26', 'selected_end': '2026-10-27'})
        manifest = folder / 'sources.json'
        daily.atomic_json(manifest, {'sources': [{'source_id': 'xhs', 'kind': 'xhs_mcc_daily',
            'path': str(raw), 'sha256': daily.digest(raw), 'start_date': '2026-10-26', 'end_date': '2026-10-27',
            'brand_accounts': {'brand': {'business_line': 'training', 'business_group': '大学'}}}]})
        return {'manifest_path': str(manifest), 'sources': [{'source_id': 'xhs', 'status': 'success',
            'captured_at': NOW.isoformat(), 'start_date': '2026-10-26', 'through_date': '2026-10-27',
            'account_ids': ['123'], 'evidence': {'path': str(proof), 'sha256': daily.digest(proof)},
            'completion': {'complete': True, 'through_date': '2026-10-27', 'basis': 'native_export_window'},
            'files': [{'path': str(raw), 'sha256': daily.digest(raw)}]}]}

    def publish(self, workspace, day, **kwargs):
        if kwargs.get('before_publish'):
            kwargs['before_publish']()
        self.published.append(kwargs)
        result = {'status': 'published', 'release': 'release-1'}
        daily.atomic_json(workspace / 'Output/ShadowDaily' / (day + '.json'), result)
        return result

    def run_daily(self, **kwargs):
        return daily.run(self.workspace, now=kwargs.pop('now', NOW), root=self.repo,
            collect=kwargs.pop('collect', self.collect), business_capture=lambda *a: PAIR,
            assert_ready=lambda *a: PAIR, publish=kwargs.pop('publish', self.publish), **kwargs)

    def test_actual_parser_to_single_publish_and_known_gap(self):
        result = self.run_daily()
        self.assertEqual(result['status'], 'published')
        self.assertEqual(result['known_gaps'], ['tencent_ads_training'])
        self.assertEqual(result['expense_rows'], 2)
        self.assertEqual(len(self.published), 1)
        self.assertEqual(self.published[0]['prepared_sources'], PAIR)
        self.assertTrue(self.normal.exists())

    def test_preview_business_batch_fits_historical_controlled_query_run_id_limit(self):
        from data_acquisition.jobs.study_abroad_snapshot_history import _query_run_id
        base = daily.business_batch_id('run_shadow_daily_20261029_175509113820')
        self.assertEqual(base, 'run_sd_20261029_175509113820_business')
        personnel_run = base + '_personnel'
        for kind in ('resources', 'contracts', 'languages'):
            self.assertTrue(_query_run_id(personnel_run, kind).startswith('run_sd_'))

    def test_candidate_cannot_reintroduce_group_aggregate_even_with_valid_capture(self):
        def grouped(*args):
            value = self.collect(*args)
            path = Path(value['manifest_path'])
            manifest = json.loads(path.read_text())
            manifest['sources'][0]['kind'] = 'network_weekly'
            daily.atomic_json(path, manifest)
            return value
        with self.assertRaisesRegex(daily.DailyBlocked, 'candidate_group_aggregate_forbidden'):
            self.run_daily(prepare=True, collect=grouped)
        self.assertEqual(self.normal.read_bytes(), self.original)
        self.assertFalse(self.published)

    def test_missing_required_source_never_publishes(self):
        def missing(*args):
            value = self.collect(*args)
            value['sources'] = []
            return value
        with self.assertRaisesRegex(daily.DailyBlocked, 'source_scope_mismatch'):
            self.run_daily(collect=missing)
        self.assertEqual(self.published, [])
        self.assertEqual(self.normal.read_bytes(), self.original)

    def test_expected_account_not_in_native_rows_is_blocked(self):
        self.expected['xhs']['accounts'].append('456')
        self.expected['xhs']['parsed_source_ids'].append('xhs:456')
        daily.atomic_json(self.workspace / '.private/full-daily-sources.json', {'expected_sources': self.expected})
        def missing_native(*args):
            value = self.collect(*args)
            value['sources'][0]['account_ids'].append('456')
            return value
        with self.assertRaisesRegex(daily.DailyBlocked, 'parsed_scope_mismatch'):
            self.run_daily(collect=missing_native)
        self.assertFalse(self.published)

    def test_verified_native_empty_ocean_account_counts_scope_without_a_synthetic_row(self):
        folder=self.root/'ocean-empty-attempt';folder.mkdir()
        expected={'ocean':{'accounts':['123','456'],'manifest_source_ids':['ocean_123'],
                           'start_date':'2026-10-26','dense_daily':False}}
        item_files=[];account_results=[]
        for account,rows,total,empty in [('123',1,'1.00',False),('456',0,'0.00',True)]:
            native=folder/f'{account}.xlsx';native.write_bytes(('native-'+account).encode())
            page=folder/f'{account}-page.json';page.write_text('{}')
            item_files.extend([{'path':str(native),'sha256':daily.digest(native)},
                               {'path':str(page),'sha256':daily.digest(page)}])
            account_results.append({
                'account_id':account,'rows':rows,'total':total,
                'captured_at':NOW.isoformat(),'selected_window':['2026-10-26','2026-10-27'],
                'native_validation':{'rows':rows,'total':total,'native_empty':empty},
                'file':{'path':str(native),'sha256':daily.digest(native)},
                'query_pages':[{'path':str(page),'sha256':daily.digest(page)}],
            })
        proof=folder/'verification.json'
        daily.atomic_json(proof,{'accounts':account_results})
        native=folder/'123.xlsx'
        manifest=folder/'sources.json'
        daily.atomic_json(manifest,{'sources':[{
            'source_id':'ocean_123','kind':'ocean_daily','path':str(native),
            'sha256':daily.digest(native),'business_line':'training',
            'business_group':'大学','platform':'抖音',
        }]})
        captured={'manifest_path':str(manifest),'sources':[{
            'source_id':'ocean','status':'success','captured_at':NOW.isoformat(),
            'start_date':'2026-10-26','through_date':'2026-10-27',
            'account_ids':['123','456'],'native_empty_accounts':['456'],
            'completion':{'complete':True,'through_date':'2026-10-27','basis':'native_export_api_window'},
            'files':item_files,'evidence':{'path':str(proof),'sha256':daily.digest(proof)},
        }]}
        parsed={'rows':[{'source_id':'ocean_123','platform':'抖音',
                         'start_date':'2026-10-27','end_date':'2026-10-27','amount':'1.00'}]}
        _manifest,_files,validated=daily.validate_capture(
            captured,expected,'2026-10-28',folder,loader=lambda _path:parsed)
        self.assertEqual(len(validated['rows']),1)
        self.assertEqual({row['source_id'] for row in validated['rows']},{'ocean_123'})

    def test_ocean_empty_scope_without_explicit_sealed_empty_metadata_stays_blocked(self):
        folder=self.root/'ocean-empty-unsealed-attempt';folder.mkdir()
        expected={'ocean':{'accounts':['123','456'],'manifest_source_ids':['ocean_123'],
                           'start_date':'2026-10-26','dense_daily':False}}
        native=folder/'123.xlsx';native.write_bytes(b'native')
        page=folder/'123-page.json';page.write_text('{}')
        empty_native=folder/'456.xlsx';empty_native.write_bytes(b'empty-native')
        empty_page=folder/'456-page.json';empty_page.write_text('{}')
        proof=folder/'verification.json'
        daily.atomic_json(proof,{'accounts':[
            {'account_id':'123','rows':1,'total':'1','captured_at':NOW.isoformat(),
             'selected_window':['2026-10-26','2026-10-27'],'native_validation':{'rows':1,'total':'1','native_empty':False},
             'file':{'sha256':daily.digest(native)},'query_pages':[{'sha256':daily.digest(page)}]},
            {'account_id':'456','rows':0,'total':'0','captured_at':NOW.isoformat(),
             'selected_window':['2026-10-26','2026-10-27'],'native_validation':{'rows':0,'total':'0','native_empty':True},
             'file':{'sha256':daily.digest(empty_native)},'query_pages':[{'sha256':daily.digest(empty_page)}]},
        ]})
        manifest=folder/'sources.json'
        daily.atomic_json(manifest,{'sources':[{'source_id':'ocean_123','kind':'ocean_daily',
            'path':str(native),'sha256':daily.digest(native),'business_line':'training',
            'business_group':'大学','platform':'抖音'}]})
        captured={'manifest_path':str(manifest),'sources':[{
            'source_id':'ocean','status':'success','captured_at':NOW.isoformat(),
            'start_date':'2026-10-26','through_date':'2026-10-27','account_ids':['123','456'],
            'completion':{'complete':True,'through_date':'2026-10-27','basis':'native_export_api_window'},
            'files':[{'path':str(path),'sha256':daily.digest(path)} for path in
                     (native,page,empty_native,empty_page)],
            'evidence':{'path':str(proof),'sha256':daily.digest(proof)},
        }]}
        parsed={'rows':[{'source_id':'ocean_123','account_id':'123','platform':'抖音',
                         'start_date':'2026-10-27','end_date':'2026-10-27','amount':'1.00'}]}
        with self.assertRaisesRegex(daily.DailyBlocked,'native_empty_account_declaration_mismatch'):
            daily.validate_capture(captured,expected,'2026-10-28',folder,loader=lambda _path:parsed)

    def test_yesterday_label_does_not_hide_missing_native_day(self):
        def gap(*args):
            value = self.collect(*args)
            raw = Path(value['sources'][0]['files'][0]['path'])
            raw.write_text(raw.read_text().replace('20261027,123,代理商子账户,brand,2\n', ''))
            value['sources'][0]['files'][0]['sha256'] = daily.digest(raw)
            manifest = Path(value['manifest_path'])
            data = json.loads(manifest.read_text())
            data['sources'][0]['sha256'] = daily.digest(raw)
            daily.atomic_json(manifest, data)
            return value
        with self.assertRaisesRegex(daily.DailyBlocked, 'parsed_day_gap'):
            self.run_daily(collect=gap)
        self.assertFalse(self.published)

    def test_naive_capture_time_rejected(self):
        def naive(*args):
            value = self.collect(*args)
            value['sources'][0]['captured_at'] = '2026-10-28T09:30:00'
            return value
        with self.assertRaisesRegex(daily.DailyBlocked, 'capture_time_missing'):
            self.run_daily(collect=naive)

    def test_sem_uses_latest_available_rows_without_completion_marker(self):
        folder = self.root / 'capture'
        folder.mkdir()
        value = self.collect(None, None, None, folder)
        captured = value['sources'][0]
        captured.update(source_id='sem', account_ids=['百度'],
                        completion={'complete': False, 'through_date': None, 'basis': 'download_only'})
        manifest_path = Path(value['manifest_path'])
        manifest = json.loads(manifest_path.read_text())
        manifest['sources'][0] = {
            'source_id': 'sem', 'kind': 'sem_daily',
            'path': manifest['sources'][0]['path'], 'sha256': manifest['sources'][0]['sha256'],
            'start_date': '2026-10-26', 'end_date': '2026-10-27',
            'sheets': {'百度': {'business_line': 'abroad', 'business_group': '留学整体', 'platform': '百度'}},
        }
        daily.atomic_json(manifest_path, manifest)
        expected = {'sem': {
            'accounts': ['百度'], 'manifest_source_ids': ['sem'],
            'parsed_source_ids': ['sem:百度'], 'start_date': '2026-10-26', 'dense_daily': True,
        }}
        parsed = {
            'rows': [{'source_id': 'sem:百度', 'source_sheet': '百度', 'start_date': '2026-10-27',
                      'end_date': '2026-10-27', 'amount': None}],
            'sources': [{'source_id': 'sem:百度', 'source_sheet': '百度', 'start_date': '2026-10-27',
                         'end_date': '2026-10-27', 'missing_date_rows': ['2026-10-26'],
                         'missing_amount_dates': ['2026-10-27']}],
        }
        _manifest, _files, validated = daily.validate_capture(
            value, expected, '2026-10-28', folder, loader=lambda _path: parsed)
        self.assertIsNone(validated['rows'][0]['amount'])
        self.assertEqual(validated['sources'][0]['missing_date_rows'], ['2026-10-26'])

    def test_non_sem_source_still_requires_native_completion(self):
        def incomplete(*args):
            value = self.collect(*args)
            value['sources'][0]['completion'] = {'complete': False, 'through_date': None}
            return value
        with self.assertRaisesRegex(daily.DailyBlocked, 'native_completion_missing:xhs'):
            self.run_daily(collect=incomplete)

    def test_rule_mutation_blocks_publish_and_restores_own_manifest(self):
        def mutate(workspace, day, **kwargs):
            self.rule.write_text('# changed during build\n')
            kwargs['before_publish']()
            self.fail('guard should fail')
        with self.assertRaisesRegex(daily.DailyBlocked, 'frozen_inputs_changed'):
            self.run_daily(publish=mutate)
        self.assertEqual(self.normal.read_bytes(), self.original)
        report = json.loads((self.workspace / 'Output/ShadowDaily/Full/current.json').read_text())
        self.assertEqual(report['publish_outcome'], 'uncertain')

    def test_lock_contention_prevents_even_capture(self):
        called = mock.Mock()
        with daily.production_lock(self.workspace):
            with self.assertRaisesRegex(daily.DailyBlocked, 'production_busy'):
                self.run_daily(collect=called)
        called.assert_not_called()

    def test_same_actual_bytes_rechecks_instead_of_republishing(self):
        first = self.run_daily()
        second = self.run_daily(now=NOW.replace(second=1))
        self.assertFalse(first['reused'])
        self.assertTrue(second['reused'])
        self.assertIn('before_publish', self.published[0])
        self.assertNotIn('before_publish', self.published[1])

    def test_missing_collector_writes_blocked_not_import_error(self):
        with self.assertRaisesRegex(daily.DailyBlocked, 'advertising_capture_receipt_required'):
            self.run_daily(collect=None)
        report = json.loads((self.workspace / 'Output/ShadowDaily/Full/current.json').read_text())
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['publish_outcome'], 'not_attempted')

    def test_dependency_error_text_is_not_written(self):
        def fail(*args):
            raise RuntimeError('secret-token-must-not-escape')
        with self.assertRaises(RuntimeError):
            self.run_daily(collect=fail)
        report = (self.workspace / 'Output/ShadowDaily/Full/current.json').read_text()
        self.assertNotIn('secret-token', report)
        self.assertIn('RuntimeError', report)

    def test_explicit_receipt_stages_real_files_and_preserves_capture_time(self):
        folder = self.root / 'external-capture'
        folder.mkdir()
        captured = self.collect(None, None, None, folder)
        receipt = folder / 'receipt.json'
        daily.atomic_json(receipt, captured)
        result = self.run_daily(collect=daily.receipt_collector(receipt))
        self.assertEqual(result['status'], 'published')


    def test_receipt_collector_stages_business_scope_confirmation_evidence(self):
        folder = self.root / 'external-capture-with-scope'
        folder.mkdir()
        captured = self.collect(None, None, None, folder)
        manifest_path = Path(captured['manifest_path'])
        manifest = json.loads(manifest_path.read_text())
        proof = folder / 'scope-confirmation.json'
        proof.write_text(json.dumps({'user_answer': 'approved'}))
        proof_sha = daily.digest(proof)
        sparse_proof = folder / 'display-pause-confirmation.json'
        sparse_proof.write_text(json.dumps({'user_statement': '展示投放有时会停'}))
        sparse_sha = daily.digest(sparse_proof)
        manifest['business_scope_confirmation'] = {
            'evidence': {'path': str(proof.resolve()), 'sha256': proof_sha},
            'display_sparse_scope': {
                'allowed': True,
                'evidence': {'path': str(sparse_proof.resolve()), 'sha256': sparse_sha},
            },
        }
        daily.atomic_json(manifest_path, manifest)
        receipt = folder / 'receipt.json'
        daily.atomic_json(receipt, captured)
        capture_dir = self.root / 'attempt' / 'capture'
        capture_dir.mkdir(parents=True)
        staged = daily.receipt_collector(receipt)(
            self.workspace, '2026-10-28', 'run-test', capture_dir)
        staged_manifest = Path(staged['manifest_path'])
        staged_value = json.loads(staged_manifest.read_text())
        staged_proof = Path(staged_value['business_scope_confirmation']['evidence']['path'])
        staged_sparse = Path(staged_value['business_scope_confirmation']['display_sparse_scope']['evidence']['path'])
        self.assertTrue(staged_proof.is_relative_to(capture_dir))
        self.assertTrue(staged_sparse.is_relative_to(capture_dir))
        self.assertEqual(daily.digest(staged_proof), proof_sha)
        self.assertEqual(daily.digest(staged_sparse), sparse_sha)
        _manifest, files, _parsed = daily.validate_capture(
            staged, self.expected, '2026-10-28', capture_dir)
        self.assertIn(str(staged_proof.resolve()), files)
        self.assertIn(str(staged_sparse.resolve()), files)


class LegacyLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dashboard_product.shadow_bi.p5 import daily as legacy
        cls.legacy = legacy

    def test_shared_descriptor_keeps_lock_held_after_inner_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with daily.production_lock(workspace) as held:
                with self.legacy.production_lock(workspace / 'Output/ShadowDaily', held):
                    pass
                with self.assertRaises(daily.DailyBlocked):
                    with daily.production_lock(workspace):
                        pass

    def test_wrong_descriptor_cannot_bypass_existing_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with daily.production_lock(root):
                with (root / 'other.lock').open('a') as other:
                    with self.assertRaisesRegex(ValueError, '身份不符'):
                        with self.legacy.production_lock(root / 'Output/ShadowDaily', other):
                            self.fail('wrong lock accepted')


class PrepareDailyTests(unittest.TestCase):
    setUp = FullDailyTests.setUp
    collect = FullDailyTests.collect
    publish = FullDailyTests.publish
    run_daily = FullDailyTests.run_daily

    def prepared(self, workspace, day, run_id, pair, folder, guard, *, advertising_manifest=None):
        guard()
        return {'status': 'prepared', 'published': False,
                'candidate': str(folder / 'presentation'), 'publish_outcome': 'not_attempted'}

    def test_generated_run_id_uses_seconds_precision_for_history_query_ids(self):
        now = NOW.replace(microsecond=987654)
        with mock.patch.object(daily, 'prepare_candidate', side_effect=self.prepared):
            result = self.run_daily(prepare=True, now=now)

        self.assertEqual(result['run_id'], 'run_shadow_daily_20261028_093000')
        for kind in ('resources', 'contracts', 'languages'):
            query_run_id = f"{result['run_id']}_business_personnel_history_{kind}"
            self.assertLessEqual(len(query_run_id), 72)
            self.assertRegex(query_run_id, r'^run_[a-z0-9][a-z0-9_-]{2,67}$')

    def test_prepare_never_calls_publisher_or_changes_success_receipts(self):
        self.run_daily()
        state = self.workspace / 'Output/ShadowDaily'
        legacy = state / '2026-10-28.json'
        full = state / 'Full/2026-10-28.json'
        old_legacy, old_full = legacy.read_bytes(), full.read_bytes()
        old_manifest = self.normal.read_bytes()
        publisher = mock.Mock(side_effect=AssertionError('prepare called publisher'))
        with mock.patch.object(daily, 'prepare_candidate', side_effect=self.prepared) as build:
            result = self.run_daily(prepare=True, publish=publisher, now=NOW.replace(second=1))
        publisher.assert_not_called()
        build.assert_called_once()
        self.assertEqual(result['status'], 'prepared')
        self.assertFalse(result['published'])
        self.assertEqual(result['publish_outcome'], 'not_attempted')
        self.assertNotIn('input_manifest_restored', result)
        self.assertEqual(legacy.read_bytes(), old_legacy)
        self.assertEqual(full.read_bytes(), old_full)
        self.assertEqual(self.normal.read_bytes(), old_manifest)

    def test_prepare_missing_source_uses_same_gate_and_does_not_build(self):
        def missing(*args):
            value = self.collect(*args)
            value['sources'] = []
            return value
        publisher = mock.Mock()
        with mock.patch.object(daily, 'prepare_candidate') as build:
            with self.assertRaisesRegex(daily.DailyBlocked, 'source_scope_mismatch'):
                self.run_daily(prepare=True, collect=missing, publish=publisher)
        publisher.assert_not_called()
        build.assert_not_called()
        self.assertEqual(self.normal.read_bytes(), self.original)

    def test_prepare_changed_input_is_blocked_and_manifest_restored(self):
        def changed(workspace, day, run_id, pair, folder, guard, *, advertising_manifest=None):
            self.rule.write_text('# changed during candidate build\n')
            guard()
        publisher = mock.Mock()
        with mock.patch.object(daily, 'prepare_candidate', side_effect=changed):
            with self.assertRaisesRegex(daily.DailyBlocked, 'frozen_inputs_changed'):
                self.run_daily(prepare=True, publish=publisher)
        publisher.assert_not_called()
        self.assertEqual(self.normal.read_bytes(), self.original)
        folder = self.workspace / 'Output/ShadowDaily/Full/run_shadow_daily_20261028_093000'
        report = json.loads((folder / 'result.json').read_text())
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['publish_outcome'], 'not_attempted')
        self.assertNotIn('input_manifest_restored', report)

    def test_prepare_rejects_published_builder_result(self):
        with mock.patch.object(daily, 'prepare_candidate', return_value={'status': 'published', 'published': True}):
            with self.assertRaisesRegex(daily.DailyBlocked, 'candidate_not_confirmed'):
                self.run_daily(prepare=True)
        self.assertFalse(self.published)

    def test_real_prepare_function_only_builds_projects_and_validates_sealed_tables(self):
        from dashboard_product.shadow_bi.p5 import daily as legacy
        pair = {'sources': {'bi': {'snapshot_id': 'snapshot_bi_test'},
                            'study_abroad': {'snapshot_id': 'snapshot_study_test'}}}
        folder = self.workspace / 'candidate'
        folder.mkdir()
        run_id = 'run_shadow_daily_20261028_candidate'
        source = self.workspace / 'Output/ShadowBI' / (daily.business_batch_id(run_id)) / 'library'
        table_bytes = b'{"cash":123}\n'
        table_hash = __import__('hashlib').sha256(table_bytes).hexdigest()
        manifest = {'batch_id': run_id, 'coverage': {'data_through': '2026-10-27'},
                    'tables': {'example': {'data': {'path': 'tables/example.jsonl', 'sha256': table_hash}}}}
        commands = []
        def command(args, log, **kwargs):
            commands.append(args)
            if args[2:4] == ['dashboard_product.shadow_bi.library', 'build']:
                (source / 'tables').mkdir(parents=True)
                (source / 'tables/example.jsonl').write_bytes(table_bytes)
                daily.atomic_json(source / 'library_manifest.json', manifest)
            elif args[2:] == ['dashboard_product.shadow_bi.p3.build_projection']:
                target = Path(kwargs['env']['SHADOW_BI_LIBRARY'])
                daily.atomic_json(target / 'library_manifest.json', manifest)
            else:
                self.fail('unexpected command: ' + repr(args))
        def load(path, batch):
            return json.loads((path / 'library_manifest.json').read_text()), None, None
        guard = mock.Mock()
        with mock.patch.object(legacy, 'command', side_effect=command), \
             mock.patch.object(legacy, 'ssh_config', side_effect=AssertionError('SSH forbidden')), \
             mock.patch('data_platform.business_library.load_library', side_effect=load):
            result = daily.prepare_candidate(self.workspace, '2026-10-28', run_id, pair, folder, guard,
                                             advertising_manifest=folder / 'candidate-sources.json')
        self.assertEqual(result['status'], 'prepared')
        self.assertFalse(result['published'])
        self.assertEqual(result['table_count'], 1)
        self.assertEqual((folder / 'transfer/tables/example.jsonl').read_bytes(), table_bytes)
        self.assertTrue((folder / 'prepared-candidate.json').exists())
        self.assertEqual(guard.call_count, 2)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][-2:], ['--advertising-manifest', str(folder / 'candidate-sources.json')])
        self.assertTrue(all(args[:2] == [daily.sys.executable, '-m'] for args in commands))
        self.assertFalse((self.workspace / 'Output/ShadowDaily/2026-10-28.json').exists())

    def test_prepare_success_failure_and_exception_never_write_registered_manifest_or_current(self):
        state = self.workspace / 'Output/ShadowDaily'
        protected = [self.normal, state / 'current.json', state / '2026-10-28.json',
                     state / 'Full/current.json', state / 'Full/2026-10-28.json']
        for path in protected[1:]:
            daily.atomic_json(path, {'sentinel': 'published-before-prepare'})
        before = {path: path.read_bytes() for path in protected}
        atomic = daily.atomic_json
        def forbid(path, value):
            self.assertNotIn(Path(path), protected, 'prepare attempted a registered input/current write')
            atomic(path, value)
        def builder(workspace, day, run_id, pair, folder, guard, *, advertising_manifest):
            self.assertEqual(advertising_manifest, folder / 'candidate-sources.json')
            self.assertNotEqual(advertising_manifest, self.normal)
            self.assertEqual(json.loads(advertising_manifest.read_text())['sources'][0]['source_id'], 'xhs')
            guard()
            if self.failure == 'exception':
                raise RuntimeError('failed local build')
            if self.failure == 'blocked':
                return {'status': 'failed', 'published': False}
            return self.prepared(workspace, day, run_id, pair, folder, guard,
                                 advertising_manifest=advertising_manifest)
        for second, outcome in enumerate(('success', 'blocked', 'exception'), 10):
            with self.subTest(outcome=outcome):
                self.failure = outcome
                with mock.patch.object(daily, 'atomic_json', side_effect=forbid), \
                     mock.patch.object(daily, 'restore_manifest', side_effect=AssertionError('prepare cannot restore registered fees')), \
                     mock.patch.object(daily, 'prepare_candidate', side_effect=builder):
                    if outcome == 'success':
                        result = self.run_daily(prepare=True, now=NOW.replace(second=second))
                        self.assertEqual(result['status'], 'prepared')
                    else:
                        with self.assertRaises(daily.DailyBlocked if outcome == 'blocked' else RuntimeError):
                            self.run_daily(prepare=True, now=NOW.replace(second=second))
                self.assertEqual({path: path.read_bytes() for path in protected}, before)
        self.assertFalse(self.published)

    def test_prepare_default_reuses_verified_today_without_refreshing_warehouse_current(self):
        with mock.patch.object(daily, 'capture_business', side_effect=AssertionError('prepare refreshed warehouse')), \
             mock.patch.object(daily, 'prepare_candidate', side_effect=self.prepared):
            result = daily.run(self.workspace, now=NOW, root=self.repo, collect=self.collect,
                               assert_ready=lambda workspace, day: PAIR, prepare=True)
        self.assertEqual(result['status'], 'prepared')
        self.assertEqual(self.normal.read_bytes(), self.original)
        self.assertFalse((self.workspace / 'Output/ShadowDaily/current.json').exists())

    def test_prepare_single_platform_cannot_pass_an_all_source_config(self):
        expected = {**self.expected, 'ocean': {}, 'sem': {}, 'tencent_ads_abroad': {}}
        daily.atomic_json(self.workspace / '.private/full-daily-sources.json', {'expected_sources': expected})
        with mock.patch.object(daily, 'prepare_candidate') as build:
            with self.assertRaisesRegex(daily.DailyBlocked, 'source_scope_mismatch'):
                self.run_daily(prepare=True)
        build.assert_not_called()
        self.assertEqual(self.normal.read_bytes(), self.original)
        self.assertFalse((self.workspace / 'Output/ShadowDaily/current.json').exists())
        self.assertFalse((self.workspace / 'Output/ShadowDaily/Full/current.json').exists())

    def test_prepare_cli_prints_candidate_without_requiring_release(self):
        import io
        result = {'status': 'prepared', 'day': '2026-10-28',
                  'candidate': '/local/candidate', 'known_gaps': ['tencent_ads_training']}
        stdout = io.StringIO()
        with mock.patch.object(daily, 'run', return_value=result) as run, \
             mock.patch.object(daily.sys, 'argv', ['full_daily', '--workspace', str(self.workspace), '--prepare']), \
             mock.patch('sys.stdout', stdout):
            self.assertEqual(daily.main(), 0)
        self.assertTrue(run.call_args.kwargs['prepare'])
        self.assertEqual(json.loads(stdout.getvalue())['status'], 'prepared')


if __name__ == '__main__':
    unittest.main()
