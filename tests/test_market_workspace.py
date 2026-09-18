import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'market_workspace/tools/data.py'
spec = importlib.util.spec_from_file_location('market_data', SCRIPT)
market_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market_data)


class MarketWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.market = self.root / 'market_workspace'
        self.market.mkdir()
        self.source = self.root / 'customers/bi_operations'
        (self.source / 'Work').mkdir(parents=True)
        (self.source / 'Work/db').write_text('synthetic identity fixture; never opened as a database')
        self.config = {'current_snapshot_id': 'snapshot_test', 'current_warehouse_path': 'Work/db',
                       'company_id': 'workspace_test'}
        self.route = {'next_step': 'analyze', 'snapshot_id': 'snapshot_test'}
        for name, value in [('MARKET', self.market), ('REPO', self.root), ('SOURCE', self.source)]:
            patch = mock.patch.object(market_data, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(market_data, 'context', return_value=(0, self.route, self.config))
        patch.start()
        self.addCleanup(patch.stop)

    def args(self, *extra):
        return market_data.parser().parse_args([
            'query', '--snapshot-id', 'snapshot_test', '--run-id', 'run_test_one', *extra])

    def test_controlled_query_freezes_sql_and_keeps_evidence_local(self):
        sql = self.market / 'draft.sql'
        sql.write_text('SELECT 1 AS smoke')
        from tests.platform.test_query_service import warehouse
        from data_platform.query.service import execute_query
        db=self.source/'Work/warehouse.duckdb'; warehouse(db,'snapshot_test')
        def controlled_call(module, argv):
            return 0, execute_query(warehouse=db,snapshot_id='snapshot_test',sql='SELECT 1 AS smoke',run_id='run_test_one',output_root=self.market/'Evidence')
        with mock.patch.object(market_data, 'call', side_effect=controlled_call) as call:
            code, result = market_data.execute(self.args('--sql-file', str(sql)))
        self.assertEqual(code, 0)
        module, argv = call.call_args.args
        self.assertEqual(module, 'interfaces.data_platform')
        self.assertEqual(argv[0], 'query')
        self.assertEqual(argv[argv.index('--output-root') + 1], self.market / 'Evidence')
        sql.unlink()
        self.assertEqual((self.market / 'Evidence/run_test_one/query.sql').read_text(), 'SELECT 1 AS smoke')
        self.assertEqual(json.loads((self.market / 'Evidence/run_test_one/receipt.json').read_text()), result)
        self.assertEqual(list(self.source.rglob('receipt.json')), [])

    def test_changed_snapshot_and_unaligned_bridge_block_before_query(self):
        sql = self.market / 'draft.sql'
        sql.write_text('SELECT 1')
        with mock.patch.object(market_data, 'call') as call:
            self.config['current_snapshot_id'] = 'snapshot_changed'
            with self.assertRaisesRegex(ValueError, 'Snapshot changed'):
                market_data.execute(self.args('--sql-file', str(sql)))
            self.config['current_snapshot_id'] = 'snapshot_test'
            self.route['next_step'] = 'align_bridge'
            with self.assertRaisesRegex(ValueError, 'analysis blocked'):
                market_data.execute(self.args('--sql-file', str(sql)))
            call.assert_not_called()

    def test_escaping_sql_and_evidence_symlinks_are_rejected(self):
        outside = self.root / 'outside.sql'
        outside.write_text('SELECT 1')
        sql = self.market / 'linked.sql'
        sql.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'SQL must'):
            market_data.execute(self.args('--sql-file', str(sql)))
        sql.unlink()
        sql.write_text('SELECT 1')
        (self.market / 'Evidence').symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Evidence must'):
            market_data.execute(self.args('--sql-file', str(sql)))

    def test_existing_run_cannot_be_overwritten(self):
        sql = self.market / 'draft.sql'
        sql.write_text('SELECT 1')
        run = self.market / 'Evidence/run_test_one'
        run.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            market_data.execute(self.args('--sql-file', str(sql)))

    def test_failed_query_receipt_is_retained(self):
        sql = self.market / 'draft.sql'
        sql.write_text('DELETE FROM landing.anything')
        with mock.patch.object(market_data, 'call', return_value=(1, {'status': 'failed'})):
            code, result = market_data.execute(self.args('--sql-file', str(sql)))
        self.assertEqual(code, 1)
        self.assertEqual(result['result']['status'], 'failed')
        self.assertTrue((self.market / 'Evidence/run_test_one/receipt.json').is_file())
