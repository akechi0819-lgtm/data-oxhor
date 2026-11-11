import unittest

import duckdb

from dashboard_product.shadow_bi.sql_warehouse.native_school import native_school_sql


class NativeSchoolSqlTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(':memory:')
        self.con.execute('CREATE SCHEMA business')
        self.con.execute('''
            CREATE TABLE business.periods (
                period_id VARCHAR, start_date DATE, through_date DATE
            )
        ''')
        self.con.execute('''
            CREATE TABLE business.facts (
                business_line VARCHAR, acquisition_mode VARCHAR, metric VARCHAR,
                team_id VARCHAR, school_name VARCHAR, grade_name VARCHAR,
                event_date VARCHAR, value DECIMAL(24,2)
            )
        ''')
        self.con.execute("""
            INSERT INTO business.periods VALUES
                ('2026-06', DATE '2026-06-01', DATE '2026-06-30')
        """)
        self.con.executemany(
            'INSERT INTO business.facts VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            [
                ('training', '主动', 'cash', None, '学校A', '初一', '2026-06-10', 1500),
                ('training', '主动', 'cash', None, '学校A', '初一', '2025-06-10', 1000),
                ('training', '被动', 'cash', None, '学校A', '初一', '2026-06-10', 9000),
                ('abroad', '主动', 'cash', None, '学校A', '初一', '2026-06-10', 8000),
            ],
        )

    def tearDown(self):
        self.con.close()

    @staticmethod
    def _legacy_sql(*, missing=True):
        missing_ctes = """
            , missing_grades AS (
                SELECT f.school_name, f.grade_name, SUM(f.value) AS cash
                FROM queries.acquisition_facts f
                JOIN queries.periods p ON p.id='{{ chosen_period }}'
                GROUP BY f.school_name, f.grade_name
            ), missing AS (
                SELECT school_name, SUM(cash) AS cash FROM missing_grades GROUP BY school_name
            )
        """ if missing else ''
        missing_select = 'SELECT school_name, cash FROM missing' if missing else 'SELECT * FROM nodes'
        return """
            {% set chosen_period = '2026-06' %}
            WITH raw AS (
                SELECT period_id, school_name, grade_name
                FROM queries.scoped_team_periods
                WHERE display_note='a parenthesis ) inside a string ('
            ), nodes AS (
                SELECT * FROM raw
            )
        """ + missing_ctes + ' ' + missing_select

    @staticmethod
    def _factory(page):
        return "SELECT '2026-06' AS period_id, 'flat' AS source_name /* page=" + page + " */"

    def test_replaces_raw_source_and_keeps_legacy_tree_ctes(self):
        sql = native_school_sql('overview', self._legacy_sql(missing=False), self._factory)
        self.assertIn("WITH raw AS (SELECT '2026-06' AS period_id, 'flat' AS source_name", sql)
        self.assertIn('SELECT * FROM raw', sql)
        self.assertIn("{% set chosen_period = '2026-06' %}", sql)
        self.assertNotIn('queries.', sql)

    def test_replaces_missing_source_with_business_facts_and_compat_periods(self):
        sql = native_school_sql('virtual', self._legacy_sql(), self._factory)
        self.assertNotIn('queries.', sql)
        self.assertIn('FROM business.facts f', sql)
        self.assertIn('FROM business.periods', sql)
        self.assertIn("f.acquisition_mode='主动'", sql)
        self.assertIn('f.team_id IS NULL', sql)
        executable = sql.replace("{% set chosen_period = '2026-06' %}", '')
        executable = executable.replace("'{{ chosen_period }}'", "'2026-06'")
        self.assertEqual(self.con.execute(executable).fetchone(), ('学校A', 1500.0))

    def test_prep_page_uses_same_source_adapter(self):
        called = []

        def factory(page):
            called.append(page)
            return self._factory(page)

        sql = native_school_sql('prep', self._legacy_sql(), factory)
        self.assertEqual(called, ['prep'])
        self.assertNotIn('queries.', sql)
        self.assertIn('missing_grades AS', sql)

    def test_adapter_keeps_rank_only_tree_sql_and_ordered_raw_source(self):
        legacy = """
            WITH raw AS (SELECT * FROM queries.source_rows),
            nodes AS (
                SELECT 学校, SUM(工单) AS 工单,
                    to_json(list(json_object('name', 年级)
                        ORDER BY CASE 年级 WHEN '在职' THEN 1 WHEN '大学已毕业' THEN 1 ELSE 9 END ASC)) AS grades
                FROM raw GROUP BY 学校
            )
            SELECT ordered.*, ROW_NUMBER() OVER (ORDER BY 工单 DESC NULLS LAST) AS 排列顺序
            FROM (SELECT * FROM nodes) ordered
        """

        def ordered_factory(_page):
            return """
                SELECT * FROM (VALUES
                    ('学校甲', '在职', 3),
                    ('学校甲', '大学已毕业', 2),
                    ('学校乙', '初一', 5)
                ) AS r(学校, 年级, 工单)
                ORDER BY 学校 ASC, 年级 ASC
            """

        sql = native_school_sql('overview', legacy, ordered_factory)
        rows = self.con.execute(sql).fetchall()

        grades_by_school = {row[0]: row[2] for row in rows}
        self.assertEqual(grades_by_school['学校甲'], '[{"name":"在职"},{"name":"大学已毕业"}]')
        self.assertIn('ORDER BY 学校 ASC, 年级 ASC', sql)
        self.assertIn("ORDER BY CASE 年级 WHEN '在职' THEN 1 WHEN '大学已毕业' THEN 1 ELSE 9 END ASC", sql)
        self.assertNotIn('_tree_input_order', sql)
        self.assertNotIn('ordered._tree_input_order', sql)
        self.assertNotIn('END ASC, 年级 ASC', sql)

    def test_rejects_unsupported_pages_and_missing_raw_contract(self):
        with self.assertRaises(ValueError):
            native_school_sql('university', self._legacy_sql(), self._factory)
        with self.assertRaisesRegex(ValueError, 'raw CTE'):
            native_school_sql('overview', 'SELECT 1', self._factory)


if __name__ == '__main__':
    unittest.main()
