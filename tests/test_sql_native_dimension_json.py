"""Native grade JSON retains the old traversal and acquisition selection."""
import json
import unittest

import duckdb
from jinja2 import Template

from dashboard_product.shadow_bi.sql_warehouse.native_dimension_json import (
    grade_json_source, native_channel_json_sql, native_grade_json_sql,
    university_channel_json_source,
)
from dashboard_product.shadow_bi.sql_warehouse.common_rules import UNIVERSITY_SCHOOL_ATTRIBUTES


class NativeDimensionJsonTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(':memory:')
        self.con.execute('CREATE SCHEMA business')
        self.con.execute('''CREATE TABLE business.fixture (
            period_id VARCHAR, unit_id VARCHAR, acquisition_scope VARCHAR,
            business_line VARCHAR, dim1 VARCHAR, metric VARCHAR,
            actual DOUBLE, prior DOUBLE, yoy DOUBLE, status VARCHAR,
            display VARCHAR, share DOUBLE, cash_share DOUBLE)''')
        self.con.execute('''CREATE MACRO business.dimension_query(p,u,a,d) AS TABLE
            SELECT * FROM business.fixture WHERE list_contains(u,unit_id)
                AND list_contains(a,acquisition_scope)''')
        # Deliberately reverse source order; array order belongs to the legacy
        # grade-name sort, while line object keys follow training then abroad.
        for scope, amount in [('被动', 10), ('主动', 20), ('全部', 30)]:
            for period in ('2026-07', 'Q2', 'FY27', 'Q1'):
                for line in ('abroad', 'training'):
                    for name in ('B', 'A'):
                        for metric in ('orders', 'cash'):
                            self.con.execute('INSERT INTO business.fixture VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                [period, 'total', scope, line, name, metric,
                                 amount, 5, amount / 5 - 1, 'available', None, .5, .5])

    def tearDown(self):
        self.con.close()

    def test_all_scopes_keep_line_keys_grade_order_double_values_and_periods(self):
        for scope, amount in [('被动', 10), ('主动', 20), ('全部', 30)]:
            sql = Template(grade_json_source("['total']")).render(acquisition_scope=scope)
            rows = self.con.execute(sql).fetchall()
            self.assertEqual([row[0] for row in rows], ['FY27', 'Q1', 'Q2', '2026-07'])
            for _, unit, actual_scope, raw in rows:
                self.assertEqual((unit, actual_scope), ('total', scope))
                lines = json.loads(raw)['grades_by_line']
                self.assertEqual(list(lines), ['training', 'abroad'])
                for grades in lines.values():
                    self.assertEqual([grade['name'] for grade in grades], ['A', 'B'])
                    self.assertIs(type(grades[0]['cash']['actual']), float)
                    self.assertEqual(grades[0]['cash']['actual'], amount)
                    self.assertIsNone(grades[0]['heads']['actual'])

    def test_parent_team_order_matches_legacy_iteration(self):
        self.con.execute("INSERT INTO business.fixture SELECT * REPLACE ('online' AS unit_id) FROM business.fixture WHERE unit_id='total'")
        self.con.execute("INSERT INTO business.fixture SELECT * REPLACE ('virtual' AS unit_id) FROM business.fixture WHERE unit_id='total'")
        sql = Template(grade_json_source("['online','virtual','total']")).render(acquisition_scope='被动')
        rows = self.con.execute(sql).fetchall()
        self.assertEqual([(row[0], row[1]) for row in rows],
                         [(period, unit) for period in ['FY27', 'Q1', 'Q2', '2026-07']
                          for unit in ['total', 'virtual', 'online']])

    def test_adapter_preserves_original_native_wrapper(self):
        legacy = 'SELECT ROW_NUMBER() OVER (ORDER BY n) FROM queries.scoped_team_periods, json_each(view) e'
        adapted = native_grade_json_sql('overview', legacy)
        source = '(' + grade_json_source("['total','virtual','online']") + ')'
        self.assertEqual(adapted.replace(source, 'queries.scoped_team_periods'), legacy)
        self.assertNotIn('queries.', adapted)

    def test_channels_keep_parent_sort_and_nested_groups_in_each_scope(self):
        from dashboard_product.shadow_bi.sql_warehouse.native_dimension_json import channel_json_source
        self.con.execute("ALTER TABLE business.fixture ADD COLUMN dimension_type VARCHAR DEFAULT 'channel'")
        self.con.execute("ALTER TABLE business.fixture ADD COLUMN dim2 VARCHAR DEFAULT 'G'")
        self.con.execute("ALTER TABLE business.fixture ADD COLUMN first_channel VARCHAR DEFAULT '∅'")
        self.con.execute('ALTER TABLE business.fixture ADD COLUMN channel_cash_share DOUBLE DEFAULT 1')
        self.con.execute("INSERT INTO business.fixture SELECT * REPLACE ('channel_group' AS dimension_type) FROM business.fixture WHERE dimension_type='channel'")
        for scope in ['被动', '主动', '全部']:
            rows = self.con.execute(Template(channel_json_source("['total']")).render(acquisition_scope=scope)).fetchall()
            self.assertEqual([row[0] for row in rows], ['FY27', 'Q1', 'Q2', '2026-07'])
            for _, _, actual_scope, raw in rows:
                self.assertEqual(actual_scope, scope)
                nodes = json.loads(raw)['channels']
                self.assertEqual([(n['business_line'], n['name']) for n in nodes],
                                 [(line, name) for line in ['abroad', 'training'] for name in ['A', 'B']])
                for node in nodes:
                    self.assertIsNone(node['first_channel'])
                    self.assertEqual([g['name'] for g in node['groups']], ['G'])
                    self.assertEqual(node['cash']['actual'], node['groups'][0]['cash']['actual'])

    def test_prep_adapters_keep_selection_mask_in_original_wrapper(self):
        legacy = 'SELECT selection FROM queries.scoped_selection_team_periods, json_each(row_json) e'
        for adapter in [native_grade_json_sql, native_channel_json_sql]:
            adapted = Template(adapter('prep', legacy)).render(mask=5, acquisition_scope='主动')
            self.assertNotIn('queries.', adapted)
            self.assertIn('5 AS selection', adapted)
            self.assertIn("selection_'||CAST(5 AS VARCHAR)", adapted)
            self.assertIn("['主动']", adapted)

    def test_university_channel_tree_keeps_scope_attribute_and_school_order(self):
        self.con.execute('''ALTER TABLE business.fixture ADD COLUMN dimension_type VARCHAR''')
        self.con.execute('''ALTER TABLE business.fixture ADD COLUMN dim2 VARCHAR''')
        self.con.execute('''ALTER TABLE business.fixture ADD COLUMN dim3 VARCHAR''')
        self.con.execute('''ALTER TABLE business.fixture ADD COLUMN first_channel VARCHAR''')
        self.con.execute('''ALTER TABLE business.fixture ADD COLUMN channel_cash_share DOUBLE''')
        self.con.execute('''CREATE OR REPLACE MACRO business.dimension_query(p,u,a,d) AS TABLE
            SELECT * FROM business.fixture
            WHERE list_contains(u,unit_id) AND list_contains(a,acquisition_scope)
                AND list_contains(d,dimension_type)''')

        scopes = ('被动', '主动', '全部')
        periods = ('2026-07', 'Q1', 'FY27')
        metrics = ('orders', 'cash', 'heads')
        for scope_index, scope in enumerate(scopes):
            for period_index, period in enumerate(periods):
                for line in ('training', 'abroad'):
                    # Insert attributes and schools in reverse display order.
                    for attr_index, attribute in reversed(list(enumerate(UNIVERSITY_SCHOOL_ATTRIBUTES))):
                        school_names = (('天津乙', '天津甲') if attr_index == 0
                                        else (f'{attribute}校',))
                        for dimension_type, dim2, dim3, school_index in [
                            ('channel_group', attribute, None, 0),
                            *[('channel_school', attribute, school, i)
                              for i, school in enumerate(school_names)],
                        ]:
                            for metric_index, metric in enumerate(metrics):
                                value = 1000 * scope_index + 100 * period_index + 10 * attr_index + school_index + metric_index + 1
                                self.con.execute('''INSERT INTO business.fixture
                                    (period_id,unit_id,acquisition_scope,business_line,dim1,metric,actual,prior,yoy,status,
                                     display,share,cash_share,dimension_type,dim2,dim3,first_channel,channel_cash_share)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                    [period,'university',scope,line,'门店A',metric,value,value/2,1.0,'available',None,
                                     0.5,0.25,dimension_type,dim2,dim3,'∅',0.75])
                    for metric_index, metric in enumerate(metrics):
                        value = 2000 * scope_index + 100 * period_index + metric_index + 1
                        self.con.execute('''INSERT INTO business.fixture
                            (period_id,unit_id,acquisition_scope,business_line,dim1,metric,actual,prior,yoy,status,
                             display,share,cash_share,dimension_type,dim2,dim3,first_channel,channel_cash_share)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            [period,'university',scope,line,'门店A',metric,value,value/2,1.0,'available',None,
                             1.0,1.0,'channel',None,None,'∅',1.0])

        sql = university_channel_json_source()
        period_index = {'2026-07': 0, 'Q1': 1, 'FY27': 2}
        for scope_index, scope in enumerate(scopes):
            rendered = Template(sql).render(acquisition_scope=scope)
            rows = self.con.execute(rendered).fetchall()
            self.assertEqual([row[0] for row in rows], ['FY27', 'Q1', '2026-07'])
            for period, unit, actual_scope, raw in rows:
                self.assertEqual((unit, actual_scope), ('university', scope))
                channels = json.loads(raw)['channels']
                self.assertEqual([item['business_line'] for item in channels], ['abroad', 'training'])
                self.assertEqual(channels[0]['first_channel'], None)
                self.assertEqual(channels[0]['cash']['actual'], 2000 * scope_index +
                                 100 * period_index[period] + 2)
                groups = channels[0]['groups']
                self.assertEqual([item['name'] for item in groups], list(UNIVERSITY_SCHOOL_ATTRIBUTES))
                self.assertEqual([item['name'] for item in groups[0]['schools']], ['天津乙', '天津甲'])
                for group in groups[1:]:
                    self.assertEqual([school['name'] for school in group['schools']], [f"{group['name']}校"])

    def test_university_and_existing_channel_wrappers_remove_queries(self):
        university = native_channel_json_sql(
            'university', 'SELECT view FROM queries.scoped_team_periods')
        self.assertNotIn('queries.', university)
        self.assertEqual(university, 'SELECT view FROM business.scoped_team_periods_channel_cache')

        overview = native_channel_json_sql(
            'overview', 'SELECT view FROM queries.scoped_team_periods')
        virtual = native_channel_json_sql(
            'virtual', 'SELECT view FROM queries.scoped_team_periods')
        prep = native_channel_json_sql(
            'prep', 'SELECT row_json FROM queries.scoped_selection_team_periods')
        for adapted in (overview, virtual, prep):
            self.assertNotIn('queries.', adapted)

    def test_university_adapter_replaces_only_group_and_school_ctes_with_typed_source(self):
        legacy = """{% set periods = ['FY27'] %}
        WITH parents AS (
            SELECT * FROM queries.scoped_team_periods WHERE team_id='university'
        ), groups AS (
            SELECT * FROM queries.scoped_team_periods WHERE team_id='university'
        ), schools AS (
            SELECT * FROM queries.scoped_team_periods WHERE team_id='university'
        ) SELECT * FROM parents"""
        sources = {
            'groups': "SELECT group_name AS 业务组名称 FROM business.university_channel_nodes_cache "
                      "WHERE team_id='university' AND node_kind='group' "
                      "AND acquisition_scope='{{ acquisition_scope }}'",
            'schools': "SELECT school_name AS 学校名称 FROM business.university_channel_nodes_cache "
                       "WHERE team_id='university' AND node_kind='school' "
                       "AND acquisition_scope='{{ acquisition_scope }}'",
        }
        adapted = native_channel_json_sql(
            'university', legacy, university_channel_node_sources=sources)
        from jinja2 import Environment
        env = Environment()
        env.filters['where_in'] = lambda values: '(' + ', '.join("'" + value + "'" for value in values) + ')'
        rendered = env.from_string(adapted).render(acquisition_scope='被动')
        self.assertIn('FROM business.scoped_team_periods_channel_cache WHERE team_id=', rendered)
        self.assertEqual(rendered.count('FROM business.university_channel_nodes_cache'), 2)
        self.assertEqual(rendered.count("AND period_id IN ('FY27')"), 2)
        self.assertIn("node_kind='group'", rendered)
        self.assertIn("node_kind='school'", rendered)
        self.assertNotIn('queries.', rendered)
