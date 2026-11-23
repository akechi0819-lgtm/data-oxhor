from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest

import duckdb

from dashboard_product.management.cash_share import attach_passive_cash_share
from dashboard_product.online_team.build import periods as dashboard_periods


ROOT = Path(__file__).resolve().parents[3]
SQL = ROOT / 'dashboard_product/management/sql/new_student_cash.sql'
CASH_TABLE = 'br_cash__sheet_39b8dee2e4b3'
CASH_COLUMNS = [
    ('source_row_number', 'BIGINT'), ('业务日期', 'DOUBLE'), ('团队', 'VARCHAR'),
    ('报入现金收入', 'VARCHAR'), ('渠道属性', 'VARCHAR'), ('新老生类型', 'VARCHAR'),
]


def _serial(day):
    return (day - date(1899, 12, 30)).days


class NewStudentCashQueryTests(unittest.TestCase):
    def test_query_keeps_positive_cash_by_student_type_across_channels_and_maps_groups(self):
        rows = [
            (1, _serial(date(2026, 6, 1)), '高中', '1.00', '被动', '新生'),
            (2, _serial(date(2026, 6, 10)), '青少', '10.10', '被动', '新生'),
            (3, _serial(date(2026, 6, 10)), '初中国际学科', '20.20', '主动', '新生'),
            (4, _serial(date(2026, 6, 15)), 'ICC', '5.50', '其他属性', '新生'),
            (5, _serial(date(2026, 6, 30)), '大学', '2.00', '新东方学校推荐', '新生'),
            (6, _serial(date(2026, 7, 1)), '留学', '3.00', '主动', '新生'),
            (7, _serial(date(2026, 6, 20)), '高中', '100.00', '被动', '老生'),
            (8, _serial(date(2026, 6, 20)), '高中', '-4.00', '被动', '新生'),
            (9, _serial(date(2026, 6, 20)), '高中', '0.00', '被动', '新生'),
            (10, _serial(date(2026, 6, 21)), '高中', '7.25', '主动', '   '),
        ]
        connection = duckdb.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute('CREATE SCHEMA landing')
        declaration = ', '.join(f'"{name}" {kind}' for name, kind in CASH_COLUMNS)
        connection.execute(f'CREATE TABLE landing."{CASH_TABLE}" ({declaration})')
        placeholders = ', '.join('?' for _ in CASH_COLUMNS)
        connection.executemany(
            f'INSERT INTO landing."{CASH_TABLE}" VALUES ({placeholders})', rows,
        )

        result = connection.execute(
            SQL.read_text(encoding='utf-8'), ['2026-06-01', '2026-07-02'],
        ).fetchall()
        values = {(student_type, cash_date.isoformat(), group): amount
                  for cash_date, student_type, group, amount in result}
        self.assertEqual(values, {
            ('新生', '2026-06-01', '高中'): Decimal('1.00'),
            ('新生', '2026-06-10', '留学预备'): Decimal('30.30'),
            ('新生', '2026-06-15', '高中'): Decimal('5.50'),
            ('新生', '2026-06-30', '大学'): Decimal('2.00'),
            ('新生', '2026-07-01', '业务组暂无法拆分'): Decimal('3.00'),
            ('老生', '2026-06-20', '高中'): Decimal('100.00'),
            (None, '2026-06-21', '高中'): Decimal('7.25'),
        })


class PassiveCashShareTests(unittest.TestCase):
    @staticmethod
    def _group(name, numerator):
        return {'name': name, 'cash': {'actual': numerator}}

    def test_period_windows_attach_only_to_total_and_preserve_original_cash(self):
        periods = dashboard_periods(date(2026, 7, 15))
        prep_numerators = {'FY27': 15.15, 'Q1': 15.15,
                           '2026-06': 5.05, '2026-07': 10.10}
        for period in periods:
            period['teams'] = [
                {'id': 'total', 'business_groups': [
                    self._group('留学预备', prep_numerators.get(period['id'], 5.05)),
                    self._group('高中', 10.01),
                    self._group('大学', 0),
                    self._group('业务组暂无法拆分', 10),
                ]},
                {'id': 'prep', 'business_groups': [self._group('留学预备', 5)]},
            ]
        original = {period['id']: deepcopy(period) for period in periods}
        daily_rows = [
            {'cash_date': '2026-06-15', 'business_group': '留学预备', 'cash_amount': 10.10},
            {'cash_date': '2026-07-14', 'business_group': '留学预备', 'cash_amount': 20.20},
            {'cash_date': '2026-07-16', 'business_group': '留学预备', 'cash_amount': 40.40},
            {'cash_date': '2026-06-20', 'business_group': '高中', 'cash_amount': 5.50},
            {'cash_date': '2026-06-20', 'business_group': '业务组暂无法拆分', 'cash_amount': 3.00},
        ]

        attach_passive_cash_share(periods, daily_rows)

        by_id = {period['id']: period for period in periods}
        for period_id in ('FY27', 'Q1'):
            prep = by_id[period_id]['teams'][0]['business_groups'][0]
            self.assertEqual(prep['passive_cash_share']['denominator'], 30.3)
            self.assertEqual(prep['passive_cash_share']['ratio'], 0.5)
        june = by_id['2026-06']['teams'][0]['business_groups'][0]['passive_cash_share']
        july = by_id['2026-07']['teams'][0]['business_groups'][0]['passive_cash_share']
        self.assertEqual(june['denominator'], 10.1)
        self.assertEqual(june['ratio'], 0.5)
        self.assertEqual(july['denominator'], 20.2)
        self.assertEqual(july['ratio'], 0.5)
        future = by_id['2026-08']['teams'][0]['business_groups'][0]['passive_cash_share']
        self.assertEqual((future['numerator'], future['denominator'], future['ratio'], future['status']),
                         (None, None, None, 'future'))
        high = by_id['2026-06']['teams'][0]['business_groups'][1]['passive_cash_share']
        self.assertEqual(high['status'], 'over_100_percent')
        self.assertGreater(high['ratio'], 1)
        self.assertIn('超过100%', high['note'])
        zero = by_id['2026-06']['teams'][0]['business_groups'][2]['passive_cash_share']
        self.assertEqual((zero['denominator'], zero['ratio'], zero['status']),
                         (0, None, 'zero_denominator'))
        unassigned = by_id['2026-06']['teams'][0]['business_groups'][3]['passive_cash_share']
        self.assertEqual(unassigned['denominator'], 3)
        self.assertEqual(unassigned['status'], 'over_100_percent')
        self.assertEqual(by_id['2026-06']['teams'][1], original['2026-06']['teams'][1])
        self.assertEqual(by_id['2026-06']['teams'][0]['business_groups'][0]['cash'],
                         original['2026-06']['teams'][0]['business_groups'][0]['cash'])

    def test_missing_query_or_unconnected_numerator_is_unavailable(self):
        period = {
            'id': '2026-06', 'kind': 'month', 'start_date': '2026-06-01',
            'through_date': '2026-06-15', 'status': 'available',
            'teams': [{'id': 'total', 'business_groups': [self._group('留学预备', 10)]}],
        }
        missing_query = deepcopy([period])
        attach_passive_cash_share(missing_query, None)
        result = missing_query[0]['teams'][0]['business_groups'][0]['passive_cash_share']
        self.assertEqual((result['denominator'], result['ratio'], result['status']),
                         (None, None, 'unavailable'))

        unconnected = deepcopy([period])
        unconnected[0]['teams'][0]['business_groups'][0]['cash']['actual'] = None
        attach_passive_cash_share(unconnected, [
            {'cash_date': '2026-06-10', 'business_group': '留学预备', 'cash_amount': 10},
        ])
        result = unconnected[0]['teams'][0]['business_groups'][0]['passive_cash_share']
        self.assertEqual((result['numerator'], result['denominator'], result['ratio'], result['status']),
                         (None, 10, None, 'unavailable'))


if __name__ == '__main__':
    unittest.main()
