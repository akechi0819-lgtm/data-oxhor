import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from dashboard_product.shadow_bi.sql_warehouse.scorecard import install_scorecard


class ScorecardSQLTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'scorecard.json'
        self.document = {
            'schema_version': 'fixture.v1', 'scorecard_id': 'fixture', 'captured_at': '2026-09-01',
            'units': {'resource_count': '人', 'signed_count': '人', 'sign_rate': '比例', 'gross_signed_amount': '万元'},
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

    def install(self, start='2026-08-01', end='2026-08-31'):
        return install_scorecard(self.con, self.path, warehouse_coverage_start=start, warehouse_coverage_end=end)

    def test_freezes_identity_and_keeps_incomparable_values_separate(self):
        result = self.install()
        self.assertEqual(result['source_sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())
        official = self.con.execute("SELECT period_start,period_end,official_value,unit FROM ref.official_scorecard WHERE scope='online' AND metric='资源数'").fetchone()
        self.assertEqual(tuple(map(str, official[:2])), ('2026-06-01', '2026-08-31'))
        self.assertEqual(official[2:], (30.0, '人'))
        row = self.con.execute("SELECT official_value,warehouse_value,delta,authority_source FROM mart.study_abroad_summary WHERE metric='资源数' AND scope='online'").fetchone()
        self.assertEqual(row, (30.0, None, None, 'official_scorecard'))
        row = self.con.execute("SELECT period_start,period_end,warehouse_value,authority_source FROM mart.study_abroad_summary WHERE metric='orders'").fetchone()
        self.assertEqual((str(row[0]), str(row[1]), row[2], row[3]), ('2026-08-01', '2026-08-31', 7.0, 'warehouse'))

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
