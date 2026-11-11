"""Sealed source lineage and SQL audit-cache contracts."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from data_platform.query.evidence import encode, file_ref, snapshot_ref
from dashboard_product.shadow_bi.sql_warehouse.source_order import install_training_source_order, _TRAINING_SQL
from dashboard_product.shadow_bi.sql_warehouse.contribution import install_marker_audit


class MarkerSourceOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.warehouse = self.root / 'warehouse.duckdb'
        self.warehouse.write_bytes(b'test snapshot identity')
        manifest = {'schema_version': 'warehouse_snapshot.v2', 'snapshot_id': 'snapshot_test',
                    'artifacts': [{'path': 'warehouse.duckdb', 'size_bytes': self.warehouse.stat().st_size,
                                   'sha256': hashlib.sha256(self.warehouse.read_bytes()).hexdigest()}]}
        (self.root / 'snapshot_manifest.json').write_bytes(encode(manifest))
        self.con = duckdb.connect(':memory:')

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def receipt(self, name='one', start='2026-01-01', end='2026-11-06', rows=None):
        directory = self.root / name
        directory.mkdir()
        (directory / 'query.sql').write_text(_TRAINING_SQL.read_text())
        (directory / 'parameters.json').write_bytes(encode([start, end, '2026-10-26', [], [], ['主动', '被动']]))
        data = {'columns': ['metric', 'work_order_id', 'source_row_number', 'actual_value'],
                'rows': rows if rows is not None else [['work_orders', 'O1', 10, 1], ['passive_reported_cash', 'O2', 20, 39800.0]]}
        (directory / 'result.json').write_bytes(encode(data))
        receipt = {'schema_version': 'query_receipt.v1', 'kind': 'query', 'run_id': 'run_' + name,
                   'snapshot_id': 'snapshot_test', 'snapshot_ref': snapshot_ref(self.warehouse, 'snapshot_test'),
                   'evidence_id': 'evidence_' + name, 'created_at': '2026-11-06T00:00:00+00:00',
                   'producer': {'name': 'data_platform.query', 'version': 'test'},
                   'columns': data['columns'], 'row_count': len(data['rows']),
                   'limits': {'max_rows': 1000, 'max_result_bytes': 1000000},
                   'referenced_relations': ['landing.br_work_orders__sheet_1f0596db9f25', 'landing.br_cash__sheet_39b8dee2e4b3'],
                   'referenced_source_ids': ['br_work_orders', 'br_cash']}
        for field, file, media in [('sql', 'query.sql', 'text/plain'), ('parameters', 'parameters.json', 'application/json'), ('result', 'result.json', 'application/json')]:
            receipt[field] = file_ref(directory / file, directory, media)
        path = directory / 'receipt.json'
        path.write_bytes(encode(receipt))
        return path

    def install(self, receipts):
        return install_training_source_order(self.con, receipts=receipts,
                                             snapshot_id='snapshot_test', warehouse=self.warehouse)

    def test_source_identity_only_and_all_evidence_inputs_are_bound(self):
        first = self.receipt(end='2026-07-01')
        second = self.receipt('two', start='2026-07-01', rows=[['work_orders', 'O3', 30, 123]])
        result = self.install([first, second])
        self.assertEqual(self.con.execute('SELECT fact_id,source_order FROM source.training_source_order ORDER BY source_order').fetchall(),
                         [('training:order:O1', 1), ('training:cash:20', 2), ('training:order:O3', 3)])
        self.assertEqual([row[0] for row in self.con.execute('DESCRIBE source.training_source_order').fetchall()],
                         ['fact_id', 'source_order', 'receipt_sha256'])
        self.assertEqual(len(result['input_paths']), 8)
        self.assertEqual(result['source_order_receipts'], [str(first.resolve()), str(second.resolve())])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM meta.training_source_order_evidence').fetchone()[0], 2)

    def test_missing_or_overlapping_receipts_fail(self):
        with self.assertRaisesRegex(ValueError, 'explicit'):
            self.install([])
        first, second = self.receipt(), self.receipt('two')
        with self.assertRaisesRegex(ValueError, 'non-overlapping'):
            self.install([first, second])

    def test_tampered_bytes_and_wrong_snapshot_are_rejected(self):
        receipt = self.receipt()
        (receipt.parent / 'result.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'byte identity'):
            self.install([receipt])
        receipt = self.receipt('other')
        doc = json.loads(receipt.read_text())
        doc['snapshot_ref']['warehouse_sha256'] = '0' * 64
        receipt.write_bytes(encode(doc))
        with self.assertRaisesRegex(ValueError, 'explicit training Snapshot'):
            self.install([receipt])

    def audit_fixture(self):
        self.con.execute('CREATE SCHEMA business')
        self.con.execute("""CREATE TABLE business.marker_input AS SELECT * FROM (VALUES
            ('training:cash:20','bi','20','cash',39800::DECIMAL(38,6),[]::VARCHAR[]),
            ('training:order:O1','bi','10','orders',1::DECIMAL(38,6),[]::VARCHAR[])
        ) r(key,source,source_row_number,metric,value,affected_people)""")
        self.con.execute('CREATE VIEW business.contribution_marker_diagnostics AS SELECT * FROM business.marker_input')
        self.con.execute("CREATE TABLE business.contribution_result_cache AS SELECT * FROM (VALUES ('contribution_marker_diagnostics'),('contribution_pending')) r(result_kind)")

    def test_audit_keeps_array_contract_source_order_and_text_types(self):
        self.audit_fixture()
        result = install_marker_audit(self.con, lineage=self.install([self.receipt()]))
        self.assertEqual(result['rows'], 2)
        self.assertEqual(self.con.execute('SELECT key,affected_people,affected_people_text,source_value FROM business.contribution_marker_diagnostics').fetchall(),
                         [('training:order:O1', [], '[]', '1'), ('training:cash:20', [], '[]', '39800.0')])
        self.assertEqual(self.con.execute('SELECT * FROM business.contribution_result_cache').fetchall(), [('contribution_pending',)])

    def test_missing_marker_source_identity_is_not_silently_dropped(self):
        self.audit_fixture()
        receipt = self.receipt(rows=[['work_orders', 'O1', 10, 1]])
        with self.assertRaisesRegex(ValueError, 'does not cover marker identity'):
            install_marker_audit(self.con, lineage=self.install([receipt]))
