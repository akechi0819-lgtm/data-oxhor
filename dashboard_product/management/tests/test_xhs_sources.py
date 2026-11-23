import csv
import json
import tempfile
import unittest
from pathlib import Path
from dashboard_product.management.advertising_sources import load_sources


class XhsMccSourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.entry = {'source_id': 'xhs', 'path': 'native.csv', 'kind': 'xhs_mcc_daily',
                      'start_date': '2026-10-25', 'end_date': '2026-10-26',
                      'brand_accounts': {'prep': {'business_line': 'training', 'business_group': '留学预备'},
                                         'study': {'business_line': 'abroad', 'business_group': '留学整体'}}}
        self.rows = [('20261025', 10, '品牌主账户', 'prep', 0),
                     ('20261025', 11, '代理商子账户', 'prep', '12.34'),
                     ('20261026', 11, '代理商子账户', 'prep', '0'),
                     ('20261026', 21, '代理商子账户', 'study', '43.21')]

    def load(self):
        with (self.root/'native.csv').open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['周期', '投放ID', '账户类型', '广告主账户ID', '总消耗'])
            writer.writerows(self.rows)
        path = self.root/'sources.json'
        path.write_text(json.dumps({'sources': [self.entry]}))
        return load_sources(path)

    def test_leaf_accounts_keep_line_zero_day_and_source_row(self):
        costs = self.load()
        self.assertEqual([r['amount'] for r in costs['rows']], [12.34, 0, 43.21])
        self.assertEqual([r['business_line'] for r in costs['rows']], ['training', 'training', 'abroad'])
        self.assertEqual([r['source_row'] for r in costs['rows']], [3, 4, 5])
        self.assertEqual(len(costs['sources']), 2)
        self.assertTrue(all(s['end_date'] == '2026-10-26' for s in costs['sources']))

    def test_duplicate_account_day_cannot_be_charged_twice(self):
        self.rows.append(self.rows[1])
        with self.assertRaisesRegex(ValueError, '账户日期重复'):
            self.load()

    def test_excluded_zero_account_does_not_create_cost_rows(self):
        self.entry['excluded_zero_account_ids'] = ['99']
        self.rows.extend([('20261025', 99, '代理商子账户', 'unmapped', 0),
                          ('20261026', 99, '代理商子账户', 'unmapped', 0)])
        costs = self.load()
        self.assertEqual({row['account_id'] for row in costs['rows']}, {'11', '21'})
        self.assertEqual(len(costs['rows']), 3)
        self.assertNotIn('xhs:99', {source['source_id'] for source in costs['sources']})

    def test_excluded_zero_account_rejects_any_nonzero_daily_amount(self):
        self.entry['excluded_zero_account_ids'] = ['99']
        self.rows.append(('20261025', 99, '代理商子账户', 'unmapped', '1'))
        with self.assertRaisesRegex(ValueError, '排除账户出现非零消费'):
            self.load()

    def test_explicit_exclusion_accepts_nonzero_without_brand_and_checks_amount(self):
        self.entry['excluded_account_ids'] = ['99']
        self.rows.append(('20261025', 99, '代理商子账户', 'unmapped', '109.17'))
        self.assertEqual(len(self.load()['rows']), 3)
        self.rows[-1] = ('20261025', 99, '代理商子账户', 'unmapped', 'invalid')
        with self.assertRaises(ValueError):
            self.load()

    def test_nonzero_principal_requires_scope_reconciliation(self):
        self.rows[0] = ('20261025', 10, '品牌主账户', 'prep', 12.34)
        with self.assertRaisesRegex(ValueError, '主账户有消费'):
            self.load()

    def test_unknown_brand_is_not_assigned_from_a_name(self):
        self.rows.append(('20261026', 99, '代理商子账户', 'unknown', 1))
        with self.assertRaisesRegex(ValueError, '归属未对齐'):
            self.load()
