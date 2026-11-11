"""Native school JSON keeps the original hierarchy and source traversal."""
import json
import unittest

import duckdb

from dashboard_product.shadow_bi.sql_warehouse.native_school_json import (
    native_school_json_sql,
    school_json_source,
)


class NativeSchoolJsonTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(':memory:')
        self.con.execute('CREATE SCHEMA business')
        self.con.execute('''CREATE TABLE business.periods (
            period_id VARCHAR, kind VARCHAR, start_date DATE)''')
        self.con.executemany('INSERT INTO business.periods VALUES (?,?,?)', [
            ('FY27', 'year', '2026-06-01'),
            ('Q1', 'quarter', '2026-06-01'),
            ('2026-07', 'month', '2026-07-01'),
        ])
        self.con.execute('''CREATE TABLE business.fixture (
            period_id VARCHAR, unit_id VARCHAR, acquisition_scope VARCHAR,
            business_line VARCHAR, dimension_type VARCHAR, dim1 VARCHAR, dim2 VARCHAR,
            metric VARCHAR, actual DOUBLE, prior DOUBLE, yoy DOUBLE, status VARCHAR,
            display VARCHAR, share DOUBLE, cash_share DOUBLE)''')
        self.con.execute('''CREATE MACRO business.dimension_query(p,u,a,d) AS TABLE
            SELECT * FROM business.fixture WHERE list_contains(u,unit_id)
                AND list_contains(a,acquisition_scope)
                AND list_contains(d,dimension_type)''')

        # Insertion order intentionally differs from the legacy school and grade
        # ordering. Populate the three acquisition scopes and both lines.
        for scope, multiplier in [('被动', 1.0), ('主动', 2.0), ('全部', 3.0)]:
            for unit in ('total', 'selection_3'):
                for line in ('abroad', 'training'):
                    schools = [('Z学校', 7.0), ('A学校', 5.0)]
                    for school, amount in schools:
                        self._add_node(scope, unit, line, 'school', school, '∅', amount * multiplier)
                        for grade, grade_amount in [('2年级', 2.0), ('10年级', 3.0)]:
                            self._add_node(scope, unit, line, 'school_grade', school, grade,
                                           grade_amount * multiplier)

    def tearDown(self):
        self.con.close()

    def _add_node(self, scope, unit, line, dimension, school, grade, amount):
        for metric, value in [('orders', amount), ('cash', amount * 10), ('heads', amount / 2)]:
            self.con.execute('''INSERT INTO business.fixture VALUES
                ('FY27',?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', [
                    unit, scope, line, dimension, school, grade, metric, value,
                    value / 2, value / 2 - 1, 'available', '2人' if metric == 'heads' else None,
                    0.25 if metric == 'orders' else None,
                    0.5 if metric == 'cash' else None,
                ])

    def test_school_json_preserves_scope_line_school_grade_and_period_order(self):
        sql = school_json_source("['total']", "['全部','主动','被动']")
        rows = self.con.execute(sql).fetchall()
        self.assertEqual([(row[0], row[1], row[2]) for row in rows], [
            (period, 'total', scope)
            for scope in ('被动', '主动', '全部')
            for period in ('FY27', 'Q1', '2026-07')
        ])
        raw = next(row[3] for row in rows if row[0] == 'FY27' and row[2] == '被动')
        view = json.loads(raw)
        self.assertEqual(list(view['schools_by_line']), ['abroad', 'training'])
        for schools in view['schools_by_line'].values():
            self.assertEqual([school['name'] for school in schools], ['Z学校', 'A学校'])
            self.assertEqual([grade['name'] for grade in schools[0]['grades']],
                             ['10年级', '2年级'])
            self.assertEqual(schools[0]['grades'][0]['heads']['display'], '2人')
            self.assertEqual(schools[0]['grades'][0]['orders']['actual'], 3.0)


    def test_adapter_reuses_302_legacy_school_tree(self):
        legacy = 'SELECT view FROM queries.scoped_team_periods WHERE team_id=\'university\''
        adapted = native_school_json_sql('university', legacy)
        self.assertNotIn('queries.scoped_team_periods', adapted)
        self.assertIn("['{{ acquisition_scope }}']", adapted)
        self.assertIn("(['university'])::VARCHAR[]", adapted)
        self.assertNotIn("['total','prep','high','university','virtual','online']", adapted)
        self.assertIn("json_object('schools_by_line'", adapted)

    def test_adapter_rejects_unknown_page_or_nonunique_source(self):
        with self.assertRaises(ValueError):
            native_school_json_sql('prep', 'SELECT 1')
        with self.assertRaises(ValueError):
            native_school_json_sql('university', 'SELECT * FROM queries.scoped_team_periods, '
                                   'queries.scoped_team_periods')


if __name__ == '__main__':
    unittest.main()
