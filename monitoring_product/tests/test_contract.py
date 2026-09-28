import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from monitoring_product.notify import find_warehouse, send
from monitoring_product.digest import build_digest, ensure_roster, apply_warehouse_actuals


class MonitoringContractTest(unittest.TestCase):
    def test_online_channels_use_natural_month(self):
        context = {'as_of_date': '2026-09-26', 'data_through_date': '2026-09-25'}
        for channel_id in ('online_private', 'online_platform'):
            digest = build_digest(context, channel_id)
            self.assertEqual(digest['perf_month'], '2026-09')
            self.assertEqual(digest['month_label'], '自然月')
            self.assertEqual((digest['window_start'], digest['window_end']), ('2026-09-01', '2026-09-30'))

    def test_workspace_identity_and_path_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Work').mkdir()
            db = root / 'Work' / 'warehouse.duckdb'
            db.touch()
            config = root / 'Work' / 'workspace.json'
            config.write_text(json.dumps({'current_snapshot_id': 'snapshot_test',
                                          'current_warehouse_path': 'Work/warehouse.duckdb'}))
            self.assertEqual(find_warehouse(root, 'snapshot_test'), db.resolve())
            with self.assertRaisesRegex(ValueError, 'current snapshot'):
                find_warehouse(root, 'snapshot_other')
            config.write_text(json.dumps({'current_snapshot_id': 'snapshot_test',
                                          'current_warehouse_path': '../outside.duckdb'}))
            with self.assertRaisesRegex(ValueError, 'within workspace'):
                find_warehouse(root, 'snapshot_test')

    def test_monitoring_runs_without_dashboard_and_records_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Work').mkdir()
            (root / 'Work' / 'warehouse.duckdb').touch()
            (root / 'Work' / 'workspace.json').write_text(json.dumps({
                'current_snapshot_id': 'snapshot_test',
                'current_warehouse_path': 'Work/warehouse.duckdb',
            }))
            ledger = {
                'orders': {'columns': ['归属人', 'ID'], 'rows': [['潘体学', '1']]},
                'cash': {'columns': ['归属人', '报入现金收入', '学员编号'], 'rows': []},
            }
            with mock.patch('monitoring_product.notify.fetch_channel_ledger', return_value=ledger) as queried, \
                 mock.patch('monitoring_product.notify.upload_notify_assets') as uploaded, \
                 mock.patch('monitoring_product.notify.post_dingtalk') as posted, \
                 mock.patch.dict('os.environ', {'NOTIFY_FORCE_PIL': '1'}):
                result = send(root, snapshot_id='snapshot_test', run_id='run_test',
                              as_of_date='2026-09-07', data_through_date='2026-09-06',
                              team_ids=['online_private'], dry_run=True)
            self.assertEqual(queried.call_args.kwargs['workspace'], root.resolve())
            uploaded.assert_not_called()
            posted.assert_not_called()
            evidence = json.loads((Path(result['output_dir']) / 'evidence.json').read_text())
            self.assertEqual(evidence['snapshot_id'], 'snapshot_test')
            self.assertEqual(evidence['digests'][0]['orders']['total'], 1)
            self.assertFalse((root / 'Output' / 'Dashboard').exists())

    def test_zero_rows_are_valid_and_shared_cash_not_double_counted_in_totals(self):
        digest = build_digest({'as_of_date': '2026-09-26', 'data_through_date': '2026-09-25'}, 'offline_university')
        self.assertEqual(digest['perf_month'], '2026-10')
        self.assertEqual(digest['window_start'], '2026-09-26')
        digest['warehouse'] = {
            'orders': {'columns': ['归属人', 'ID'], 'rows': []},
            'cash': {'columns': ['归属人', '报入现金收入', '学员编号'],
                     'rows': [['甲、乙', 100, 'student1'], ['未归属', 50, 'student2']]},
        }
        actual = apply_warehouse_actuals(digest)
        self.assertEqual(actual['orders']['total'], 0)
        self.assertEqual(actual['cash']['total'], 150)
        self.assertEqual(actual['cash']['attributed'], 100)
        self.assertEqual(actual['cash']['unattributed'], 50)
