import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from dashboard_product.shadow_bi.sql_warehouse.scorecard import install_scorecard
from data_platform.query.service import QueryError, validate_query


class ScorecardSQLTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'scorecard.json'
        self.document = {
            'schema_version': 'fixture.v1', 'scorecard_id': 'fixture', 'captured_at': '2026-09-01',
            'units': {'resource_count': '资源/工单数', 'signed_count': '人', 'sign_rate': '比例', 'gross_signed_amount': '毛签万元'},
            'online': {'rows': [{'period': 'FY27-Q1', 'row_kind': 'actual', '累计': {'资源数': 30, '毛签万元': 4}, '线上资源占比': 0.4}]},
            'offline': {'rows': [{'period': 'FY27-Q1', 'row_kind': 'actual', '累计': {'资源数': 50}},
                                 {'period': 'FY27', 'row_kind': 'target', '累计': {'资源数': 100}}]},
        }
        self.path.write_text(json.dumps(self.document, ensure_ascii=False), encoding='utf-8')
        self.con = duckdb.connect(':memory:')
        self.addCleanup(self.con.close)
        self.con.execute('CREATE SCHEMA business')
        self.con.execute('''CREATE TABLE business.periods(period_id VARCHAR, start_date DATE, through_date DATE)''')
        self.con.execute("INSERT INTO business.periods VALUES ('Q1','2026-06-01','2026-08-31')")
        self.con.execute('''CREATE TABLE business.team_values(period_id VARCHAR, unit_id VARCHAR,
            acquisition_scope VARCHAR, business_line VARCHAR, comparison VARCHAR, orders DOUBLE, cash DOUBLE, heads DOUBLE)''')
        self.con.execute("INSERT INTO business.team_values VALUES ('Q1','online_scope','全部','abroad','actual',7,80,2)")
        self.con.execute('''CREATE TABLE business.abroad_facts(customer_domain VARCHAR, metric VARCHAR,
            event_date DATE, value DOUBLE, segment_id VARCHAR, first_channel VARCHAR, resource_id VARCHAR)''')
        self.con.execute("""INSERT INTO business.abroad_facts VALUES
            ('study_abroad','orders','2026-07-01',1,'study_abroad_online','网络资源','1'),
            ('study_abroad','orders','2026-07-02',1,'study_abroad_virtual','网络资源','2'),
            ('study_abroad','orders','2026-07-02',1,'study_abroad_online','网络资源','1'),
            ('study_abroad','orders','2026-07-02',1,'study_abroad_online','网络资源',NULL),
            ('small_language','orders','2026-07-02',1,'study_abroad_online','网络资源','3'),
            ('study_abroad','orders','2026-07-02',1,'study_abroad_online','其他','4'),
            ('study_abroad','cash','2026-07-02',50000,'study_abroad_online','网络资源',NULL),
            ('study_abroad','cash','2026-07-03',-10000,'study_abroad_online','网络资源',NULL),
            ('small_language','cash','2026-07-03',90000,'study_abroad_online','网络资源',NULL)""")

    def install(self, start='2026-08-01', end='2026-08-31', comparison_contract=None):
        return install_scorecard(self.con, self.path, warehouse_coverage_start=start,
                                 warehouse_coverage_end=end, comparison_contract=comparison_contract)

    def test_freezes_identity_and_keeps_incomparable_values_separate(self):
        result = self.install()
        self.assertEqual(result['source_sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())
        official = self.con.execute("SELECT period_start,period_end,official_value,unit FROM ref.official_scorecard WHERE scope='online' AND metric='资源数'").fetchone()
        self.assertEqual(official[:2], (None, None))
        self.assertEqual(official[2:], (30.0, '资源/工单数'))
        row = self.con.execute("SELECT official_value,warehouse_value,delta,authority_source FROM mart.study_abroad_summary WHERE metric='资源数' AND scope='online'").fetchone()
        self.assertEqual(row, (30.0, None, None, 'official_scorecard'))
        row = self.con.execute("SELECT period_start,period_end,warehouse_value,authority_source FROM mart.study_abroad_summary WHERE metric='orders'").fetchone()
        self.assertEqual((str(row[0]), str(row[1]), row[2], row[3]), ('2026-08-01', '2026-08-31', 7.0, 'warehouse'))

    def test_explicit_approved_period_and_scope_compare_pure_study_resources(self):
        contract = {
            'source_sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
            'approval_reference': 'fixture-authority',
            'resource_comparisons': [{
                'period': 'FY27-Q1', 'scope': 'online', 'dimension': '累计',
                'period_start': '2026-06-01', 'period_end': '2026-08-31',
                'segments': ['study_abroad_online', 'study_abroad_virtual'],
                'first_channels': ['网络资源'],
            }],
        }
        self.install(start='2026-06-01', comparison_contract=contract)
        row = self.con.execute("""SELECT official_value,warehouse_value,delta,comparability_reason
            FROM mart.study_abroad_summary WHERE metric='资源数' AND scope='online'""").fetchone()
        self.assertEqual(row, (30.0, 2.0, -28.0, None))
        self.assertEqual(self.con.execute("""SELECT comparison_approval FROM mart.study_abroad_summary
            WHERE metric='资源数' AND scope='online'""").fetchone()[0], 'fixture-authority')
        self.assertEqual(self.con.execute("""SELECT comparability_reason FROM mart.study_abroad_summary
            WHERE metric='毛签万元' AND scope='online'""").fetchone()[0], 'comparison_contract_missing')

    def test_approved_gross_signing_converts_positive_yuan_to_wan_yuan(self):
        contract = {
            'source_sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
            'approval_reference': 'fixture-authority',
            'gross_signing_comparisons': [{
                'period': 'FY27-Q1', 'scope': 'online', 'dimension': '累计',
                'period_start': '2026-06-01', 'period_end': '2026-08-31',
                'segments': ['study_abroad_online'],
                'first_channels': ['网络资源'], 'definition': 'positive_signature_yuan',
            }],
        }
        self.install(start='2026-06-01', comparison_contract=contract)
        row = self.con.execute("""SELECT official_value, warehouse_value, delta, comparability_reason
            FROM mart.study_abroad_summary WHERE metric='毛签万元' AND scope='online'""").fetchone()
        self.assertEqual(row, (4.0, 5.0, 1.0, None))

    def test_gross_signing_requires_an_approved_definition(self):
        contract = {
            'source_sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
            'approval_reference': 'fixture-authority',
            'gross_signing_comparisons': [{
                'period': 'FY27-Q1', 'scope': 'online', 'dimension': '累计',
                'period_start': '2026-06-01', 'period_end': '2026-08-31',
                'segments': ['study_abroad_online'], 'first_channels': ['网络资源'],
            }],
        }
        with self.assertRaisesRegex(ValueError, 'invalid scorecard comparison'):
            self.install(start='2026-06-01', comparison_contract=contract)

    def test_comparison_requires_complete_coverage_and_same_scorecard(self):
        contract = {
            'source_sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
            'approval_reference': 'fixture-authority',
            'resource_comparisons': [{
                'period': 'FY27-Q1', 'scope': 'online', 'dimension': '累计',
                'period_start': '2026-06-01', 'period_end': '2026-08-31',
                'segments': ['study_abroad_online'], 'first_channels': ['网络资源'],
            }],
        }
        self.install(comparison_contract=contract)
        row = self.con.execute("""SELECT warehouse_value,delta,comparability_reason
            FROM mart.study_abroad_summary WHERE metric='资源数' AND scope='online'""").fetchone()
        self.assertEqual(row, (None, None, 'warehouse_coverage_incomplete'))

    def test_rejects_comparison_contract_for_another_scorecard(self):
        with self.assertRaisesRegex(ValueError, 'source hash mismatch'):
            self.install(comparison_contract={
                'source_sha256': 'wrong', 'approval_reference': 'fixture-authority',
                'resource_comparisons': [],
            })

    def test_controlled_query_allows_quoted_ref_and_still_rejects_other_schemas(self):
        self.install()
        validate_query(self.con, 'SELECT * FROM mart.study_abroad_summary',
                       allowed_schemas={'mart', 'business', 'ref'})
        with self.assertRaises(QueryError):
            validate_query(self.con, 'SELECT * FROM mart.study_abroad_summary',
                           allowed_schemas={'mart', 'business'})

    def test_warehouse_period_outside_verified_end_is_not_mislabelled(self):
        self.install(end='2026-08-15')
        self.assertEqual(self.con.execute("SELECT count(*) FROM mart.study_abroad_summary WHERE authority_source='warehouse'").fetchone()[0], 0)

    def test_source_file_remains_untouched_and_invalid_measures_fail(self):
        self.document['online']['rows'][0]['累计']['资源数'] = 'bad'
        self.path.write_text(json.dumps(self.document), encoding='utf-8')
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
