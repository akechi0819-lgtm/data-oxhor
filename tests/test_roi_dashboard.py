import unittest
from datetime import date
from decimal import Decimal

import duckdb
from jinja2 import Environment

from dashboard_product.shadow_bi.sql_warehouse.roi_dashboard import roi_dashboard_sql
from dashboard_product.shadow_bi.p4.roi_dashboard import CHARTS, layout


class RoiDashboardTests(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE SCHEMA business')
        self.db.execute('''CREATE TABLE business.periods(period_id VARCHAR,kind VARCHAR,status VARCHAR,
                        start_date DATE,through_date DATE)''')
        self.db.execute("""INSERT INTO business.periods VALUES
            ('FY27','year','available','2026-06-01','2026-11-24'),
            ('2026-11','month','available','2026-11-01','2026-11-24'),
            ('2026-12','month','future','2026-12-01',NULL)""")
        self.db.execute('''CREATE TABLE business.online_daily(event_date DATE,business_line VARCHAR,
            expense_group VARCHAR,platform VARCHAR,orders DECIMAL(18,2),cash DECIMAL(18,2))''')
        self.db.execute("""INSERT INTO business.online_daily VALUES
            ('2026-11-01','training','大学','抖音',10,100),
            ('2026-11-02','training','高中','小红书',5,70),
            ('2026-11-03','training','大学','腾讯广告',2,30),
            ('2025-11-01','training','大学','抖音',4,40),
            ('2026-11-01','abroad','留学整体','抖音',3,60)""")
        self.db.execute('''CREATE TABLE business.expense_rows(business_line VARCHAR,business_group VARCHAR,
            platform VARCHAR,start_date DATE,end_date DATE,amount DECIMAL(18,2))''')
        self.db.execute("""INSERT INTO business.expense_rows VALUES
            ('training','大学','抖音','2026-11-01','2026-11-01',40),
            ('training','高中','小红书','2026-11-02','2026-11-02',20),
            ('training','大学','腾讯广告','2026-11-03','2026-11-03',10),
            ('training','大学','抖音','2026-10-01','2026-10-31',100),
            ('abroad','留学整体','抖音','2026-11-01','2026-11-01',30)""")

    def query(self, kind, filters=None):
        env = Environment()
        env.globals['filter_values'] = lambda name, remove_filter=False: (filters or {}).get(name, [])
        env.filters['where_in'] = lambda values: '(' + ','.join("'" + v.replace("'", "''") + "'" for v in values) + ')'
        sql = env.from_string(roi_dashboard_sql(kind)).render()
        cursor = self.db.execute(sql)
        return [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]

    def test_tables_total_selected_platforms_and_group_and_compare_prior(self):
        rows = self.query('training')
        november = [r for r in rows if r['线上期间'] == '2026-11']
        self.assertEqual(len(november), 4)
        total = next(r for r in november if r['平台'] == '合计')
        self.assertEqual((total['本期花费'], total['本期工单'], total['本期产出']),
                         (Decimal('70'), Decimal('17'), Decimal('200')))
        self.assertEqual((total['上年同期工单'], total['上年同期产出']), (Decimal('4'), Decimal('40')))
        self.assertEqual(total['月份'], date(2026, 11, 1))
        selected = self.query('training', {'平台业务组': ['大学'], '平台': ['抖音', '腾讯广告']})
        month = [r for r in selected if r['线上期间'] == '2026-11']
        self.assertEqual({r['平台'] for r in month}, {'抖音', '腾讯广告', '合计'})
        total = next(r for r in month if r['平台'] == '合计')
        self.assertEqual((total['本期花费'], total['本期工单'], total['本期产出']),
                         (Decimal('50'), Decimal('12'), Decimal('130')))
        year = next(r for r in selected if r['线上期间'] == 'FY27' and r['平台'] == '合计')
        self.assertEqual(year['本期花费'], Decimal('150'))

    def test_trends_month_only_total_and_null_denominators(self):
        for kind in ('roi', 'cpl', 'spend'):
            rows = self.query(kind, {'平台': ['小红书'], '平台业务组': ['大学']})
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row['线上期间'] == '2026-11' and row['平台'] == '合计' for row in rows))
            training = next(row for row in rows if row['业务线'] == '语培')
            self.assertIsNone(training['本期花费'])
            self.assertIsNone(training['ROI'])
            self.assertIsNone(training['单条成本'])
        summary = self.query('summary')
        self.assertEqual({row['线上期间'] for row in summary}, {'FY27', '2026-11'})
        self.assertTrue(all(row['平台'] == '合计' for row in summary))
        self.assertTrue(all(row['业务线'] == '留学及小语种' for row in self.query('abroad')))
        self.assertEqual(self.query('summary', {'平台': ['未知平台']}), [])

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            roi_dashboard_sql('unknown')

    def test_missing_tencent_days_are_zero_for_invested_groups(self):
        self.db.execute("""INSERT INTO business.online_daily VALUES
            ('2026-11-02','training','高中','腾讯广告',2,30),
            ('2026-11-02','abroad','留学整体','腾讯广告',5,50)""")
        for kind, group in [('training', '高中'), ('abroad', '留学整体')]:
            rows = self.query(kind, {'平台业务组': [group], '平台': ['腾讯广告']})
            row = next(r for r in rows if r['线上期间'] == '2026-11' and r['平台'] == '腾讯广告')
            self.assertEqual(row['本期花费'], Decimal('0'))
            self.assertIsNone(row['ROI'])
            self.assertEqual(row['单条成本'], 0)
        rows = self.query('training', {'平台业务组': ['留学预备'], '平台': ['腾讯广告']})
        row = next(r for r in rows if r['线上期间'] == '2026-11' and r['平台'] == '腾讯广告')
        self.assertIsNone(row['本期花费'])

    def test_period_expense_is_not_allocated_into_partial_windows(self):
        self.db.execute("""INSERT INTO business.expense_rows VALUES
            ('training','大学','腾讯广告','2026-10-01','2026-10-31',73.22)""")
        rows = self.query('training', {'平台业务组': ['大学'], '平台': ['腾讯广告']})
        month = next(r for r in rows if r['线上期间'] == '2026-11' and r['平台'] == '腾讯广告')
        year = next(r for r in rows if r['线上期间'] == 'FY27' and r['平台'] == '腾讯广告')
        self.assertEqual(month['本期花费'], Decimal('10'))
        self.assertEqual(year['本期花费'], Decimal('83.22'))

    def test_quarters_in_tables_and_summary_but_not_monthly_trends(self):
        self.db.execute("""INSERT INTO business.periods VALUES
            ('Q1','quarter','available','2026-06-01','2026-08-31'),
            ('Q2','quarter','available','2026-09-01','2026-11-24'),
            ('Q3','quarter','future','2026-12-01',NULL)""")
        self.db.execute("""INSERT INTO business.online_daily VALUES
            ('2026-08-31','training','大学','抖音',7,77),
            ('2026-09-01','training','大学','抖音',8,88),
            ('2026-11-25','training','大学','抖音',9,99)""")
        self.db.execute("""INSERT INTO business.expense_rows VALUES
            ('training','大学','抖音','2026-08-31','2026-08-31',11),
            ('training','大学','抖音','2026-09-01','2026-09-01',12),
            ('training','大学','抖音','2026-11-25','2026-11-25',13)""")
        for kind in ('training', 'summary'):
            rows = [row for row in self.query(kind) if row['业务线'] == '语培' and row['平台'] == '合计']
            quarters = {row['线上期间']: row for row in rows if row['线上期间'].startswith('Q')}
            self.assertEqual(set(quarters), {'Q1', 'Q2'})
            self.assertEqual((quarters['Q1']['月份'], quarters['Q1']['本期工单'], quarters['Q1']['本期花费']),
                             (date(2026, 6, 1), Decimal('7'), Decimal('11')))
            self.assertEqual((quarters['Q2']['月份'], quarters['Q2']['本期工单'], quarters['Q2']['本期花费']),
                             (date(2026, 9, 1), Decimal('25'), Decimal('182')))
        self.assertEqual({row['线上期间'] for row in self.query('abroad')}, {'FY27', 'Q1', 'Q2', '2026-11'})
        for kind in ('roi', 'cpl', 'spend'):
            self.assertEqual({row['线上期间'] for row in self.query(kind)}, {'2026-11'})

    def test_layout_reorders_only_roi_tab_and_preserves_other_filter_scope(self):
        roles = [role for role, _, _ in CHARTS.values()]
        by_role = {role: index + 1 for index, role in enumerate(roles)}
        positions = {
            'TABS-online': {'children': ['TAB-roi', 'TAB-other']},
            'TAB-roi': {'type': 'TAB', 'meta': {'text': '日趋势与明细'},
                        'children': [f'ROW-{role}' for role in reversed(roles)]},
            'TAB-other': {'type': 'TAB', 'meta': {'text': '其他'}, 'children': ['ROW-other']},
            'CHART-other': {'type': 'CHART', 'meta': {'chartId': 99},
                            'parents': ['ROOT_ID', 'TAB-other', 'ROW-other']},
        }
        for role, chart_id in by_role.items():
            positions[f'CHART-{role}'] = {'type': 'CHART', 'meta': {'chartId': chart_id},
                                          'parents': ['ROOT_ID', 'TAB-roi', f'ROW-{role}']}
        filter_ids = ['NATIVE_FILTER-p3-online-0', 'NATIVE_FILTER-p3-online-1',
                      'NATIVE_FILTER-p35-platform-group', 'NATIVE_FILTER-p3-online-4']
        metadata = {'native_filter_configuration': [
            {'id': filter_id, 'chartsInScope': [99, *by_role.values()],
             'scope': {'rootPath': ['ROOT_ID'], 'excluded': []}, 'tabsInScope': []}
            for filter_id in filter_ids]}
        original_charts = {node['meta']['chartId'] for node in positions.values()
                           if node.get('type') == 'CHART'}

        layout(metadata, positions, by_role)

        self.assertEqual(positions['TAB-roi']['meta']['text'], 'ROI 看板')
        self.assertEqual(positions['TAB-other']['meta']['text'], '其他')
        self.assertEqual(positions['TAB-other']['children'], ['ROW-other'])
        self.assertEqual(positions['TAB-roi']['children'],
                         [f'ROW-{role}' for role in ('summary', 'training', 'abroad', 'roi', 'spend', 'cpl')])
        self.assertEqual({node['meta']['chartId'] for node in positions.values()
                          if node.get('type') == 'CHART'}, original_charts)
        expected = [ {'summary', 'training', 'abroad'}, set(roles), set(roles)-{'abroad'}, set(roles)]
        for filter_, scoped_roles in zip(metadata['native_filter_configuration'], expected):
            self.assertEqual(set(filter_['chartsInScope']), {99} | {by_role[role] for role in scoped_roles})
            self.assertEqual(set(filter_['scope']['excluded']),
                             {by_role[role] for role in set(roles)-scoped_roles})
            self.assertEqual(set(filter_['tabsInScope']), {'TAB-roi', 'TAB-other'})


if __name__ == '__main__':
    unittest.main()
