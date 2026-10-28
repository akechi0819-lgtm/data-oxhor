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

    def test_sem_prefilled_zero_needs_native_completion(self):
        folder = self.root / 'capture'
        folder.mkdir()
        value = self.collect(None, None, None, folder)
        value['sources'][0]['source_id'] = 'sem'
        expected = {'sem': self.expected['xhs']}
        with self.assertRaisesRegex(daily.DailyBlocked, 'sem_native_completion_missing'):
            daily.validate_capture(value, expected, '2026-10-28', folder)

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

    def prepared(self, workspace, day, run_id, pair, folder, guard):
        guard()
        return {'status': 'prepared', 'published': False,
                'candidate': str(folder / 'presentation'), 'publish_outcome': 'not_attempted'}

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
        self.assertTrue(result['input_manifest_restored'])
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
        def changed(workspace, day, run_id, pair, folder, guard):
            self.rule.write_text('# changed during candidate build\n')
            guard()
        publisher = mock.Mock()
        with mock.patch.object(daily, 'prepare_candidate', side_effect=changed):
            with self.assertRaisesRegex(daily.DailyBlocked, 'frozen_inputs_changed'):
                self.run_daily(prepare=True, publish=publisher)
        publisher.assert_not_called()
        self.assertEqual(self.normal.read_bytes(), self.original)
        report = json.loads((self.workspace / 'Output/ShadowDaily/Full/current.json').read_text())
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['publish_outcome'], 'not_attempted')
        self.assertTrue(report['input_manifest_restored'])

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
        source = self.workspace / 'Output/ShadowBI' / (run_id + '_business') / 'library'
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
            result = daily.prepare_candidate(self.workspace, '2026-10-28', run_id, pair, folder, guard)
        self.assertEqual(result['status'], 'prepared')
        self.assertFalse(result['published'])
        self.assertEqual(result['table_count'], 1)
        self.assertEqual((folder / 'transfer/tables/example.jsonl').read_bytes(), table_bytes)
        self.assertTrue((folder / 'prepared-candidate.json').exists())
        self.assertEqual(guard.call_count, 2)
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(args[:2] == [daily.sys.executable, '-m'] for args in commands))
        self.assertFalse((self.workspace / 'Output/ShadowDaily/2026-10-28.json').exists())

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
