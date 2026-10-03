"""Market total order restoration from the controlled per-order source."""
from __future__ import annotations

from copy import deepcopy
import unittest

from dashboard_product.management.market_totals import (
    UNKNOWN_GROUP,
    attach_market_orders,
)
from dashboard_product.online_team.build import metric


def order(order_id, day, group, channel='市场活动'):
    return {
        'work_order_id': order_id,
        'event_date': day,
        'business_group': group,
        'second_channel': channel,
    }


def orders(group, count, day, prefix, channel='市场活动'):
    return [order(f'{prefix}-{index}', day, group, channel) for index in range(count)]


def group_row(name, target, cash_actual, heads_actual):
    return {
        'name': name,
        'orders': metric(900, 800, target, 0.5, '单'),
        'cash': metric(cash_actual, cash_actual - 10, None, 0.5, '元'),
        'heads': metric(heads_actual, heads_actual - 1, None, 0.5, '人'),
    }


def make_total(*, training_target=75, status='available', include_unknown=False):
    training_orders = metric(
        40 if status == 'available' else None,
        30 if status == 'available' else None,
        training_target, 0.5, '单', status=status,
    )
    business_groups = [
        group_row('留学预备', 10, 1000, 10),
        group_row('高中', 20, 2000, 20),
        group_row('大学', 30, 3000, 30),
    ]
    yoy_groups = [
        group_row(name, None, index * 100, index)
        for index, name in enumerate(('青少', '初中', '高中', '大学'), 1)
    ]
    if include_unknown:
        business_groups.append(group_row(UNKNOWN_GROUP, 4, 444, 44))
        yoy_groups.append(group_row(UNKNOWN_GROUP, 5, 555, 55))
    return {
        'id': 'total',
        'name': '市场总计',
        'lines': {
            'training': {
                'orders': training_orders,
                'cash': metric(1234, 1000, 5000, 0.5, '元'),
                'heads': metric(12, 10, None, 0.5, '人'),
            },
            'abroad': {
                'orders': metric(3, 2, None, 0.5, '单'),
                'cash': metric(None, None, None, 0.5, '元', status='not_connected'),
                'heads': metric(None, None, None, 0.5, '人', status='not_connected'),
            },
        },
        'business_groups': business_groups,
        'yoy_groups': yoy_groups,
    }


def baseline_rows():
    rows = []
    rows += orders('青少', 1, '2026-09-01', 'current-youth')
    rows.append(order('current-youth-small-language', '2026-09-01', '青少', '小语种'))
    # Overlapping source exports keep one order ID only.
    rows.append(order('current-youth-0', '2026-09-01', '青少'))
    rows += orders('初中', 3, '2026-09-15', 'current-middle')
    rows += orders('高中', 7, '2026-09-15', 'current-high')
    rows += orders('大学', 11, '2026-09-01', 'current-university')
    rows += orders('历史未映射团队', 12, '2026-09-10', 'current-unknown')
    rows += orders('青少', 1, '2026-09-16', 'after-current-window')
    rows += orders('高中', 1, '2026-08-31', 'before-current-window')

    rows += orders('青少', 1, '2025-09-01', 'prior-youth')
    rows += orders('初中', 2, '2025-09-15', 'prior-middle')
    rows += orders('高中', 4, '2025-09-15', 'prior-high')
    rows += orders('大学', 5, '2025-09-01', 'prior-university')
    rows += orders('历史未映射团队', 6, '2025-09-10', 'prior-unknown')
    rows += orders('青少', 1, '2025-09-16', 'after-prior-window')
    rows += orders('高中', 1, '2025-08-31', 'before-prior-window')

    # The old training market total includes both raw and cleaned SSC orders.
    rows.append(order('raw-ssc', '2026-09-10', '大学', '  SsC  '))
    rows.append(order('raw-ssc', '2026-09-10', '大学', '普通渠道'))
    rows.append(order('cleaned-ssc', '2026-09-10', '大学', '普通渠道'))
    rows.append(order('cleaned-ssc', '2026-09-10', '大学', '其他渠道'))
    return rows


def period(team, *, status='available', start='2026-09-01', through='2026-09-15'):
    return {
        'id': '2026-09' if status == 'available' else '2026-10',
        'status': status,
        'start_date': start,
        'through_date': through,
        'time_progress': 0.5,
        'teams': [team],
    }


def by_name(rows, name):
    return next(row for row in rows if row['name'] == name)


class MarketTotalsTest(unittest.TestCase):
    def test_unattributed_passive_tmk_orders_stay_in_market_unknown_group(self):
        total = make_total()
        source = period(total)
        rows = []
        for order_id, status in (
            ('unattributed-tmk-valid', '有效'),
            ('unattributed-tmk-deleted', '删除'),
            ('unattributed-tmk-recovered', '回收'),
        ):
            row = order(order_id, '2026-09-10', None, 'TMK激活')
            row.update({
                'source_team': '',
                'work_order_active_type': '被动',
                'order_status': status,
                # The abroad-only cleaning label must not narrow this source.
                'derived_study_abroad_ssc_exclusion': True,
            })
            rows.append(row)

        attach_market_orders([source], rows)

        self.assertEqual((total['market_orders']['actual'],
                          total['market_orders']['prior']), (3, 0))
        unknown = by_name(total['business_groups'], UNKNOWN_GROUP)
        self.assertEqual((unknown['orders']['actual'],
                          unknown['orders']['prior']), (3, 0))
        self.assertEqual(total['lines']['training']['orders']['actual'], 40)
        self.assertEqual(total['lines']['training']['cash']['actual'], 1234)

    def test_market_and_group_orders_use_deduped_windowed_source(self):
        total = make_total()
        other_team = {
            'id': 'prep',
            'lines': {'training': {'orders': metric(5, 3, 10, 0.5, '单')}},
            'business_groups': [group_row('留学预备', 10, 10, 1)],
            'yoy_groups': [],
        }
        other_before = deepcopy(other_team)
        total_cash_before = deepcopy(total['lines']['training']['cash'])
        total_heads_before = deepcopy(total['lines']['training']['heads'])
        abroad_before = deepcopy(total['lines']['abroad'])
        group_cash_before = {
            row['name']: deepcopy(row['cash']) for row in total['business_groups']
        }
        group_heads_before = {
            row['name']: deepcopy(row['heads']) for row in total['business_groups']
        }
        yoy_non_order_before = {
            row['name']: (deepcopy(row['cash']), deepcopy(row['heads']))
            for row in total['yoy_groups']
        }
        source = period(total)
        source['teams'].append(other_team)
        before_training_orders = deepcopy(total['lines']['training']['orders'])

        result = attach_market_orders([source], baseline_rows())

        self.assertIs(result[0], source)
        self.assertEqual(other_team, other_before)
        self.assertEqual(total['lines']['training']['cash'], total_cash_before)
        self.assertEqual(total['lines']['training']['heads'], total_heads_before)
        self.assertEqual(total['lines']['abroad'], abroad_before)
        self.assertEqual(
            total['lines']['training']['orders']['actual'],
            before_training_orders['actual'],
        )
        self.assertEqual(
            total['lines']['training']['orders']['prior'],
            before_training_orders['prior'],
        )
        for key in ('target', 'completion', 'gap', 'time_gap'):
            self.assertNotIn(key, total['lines']['training']['orders'])

        market = total['market_orders']
        self.assertEqual((market['actual'], market['prior']), (37, 18))
        self.assertEqual(market['target'], 75)
        self.assertEqual(market['completion'], 37 / 75)
        self.assertEqual(market['unit'], '单')
        for phrase in (
            '未归因团队', '删除/回收', '按工单ID去重', '留学专项清洗不改变总盘纳入范围',
            '个人业绩剔除删除/回收',
        ):
            self.assertIn(phrase, market['note'])

        business = {row['name']: row for row in total['business_groups']}
        self.assertEqual(
            {name: (row['orders']['actual'], row['orders']['prior'])
             for name, row in business.items()},
            {
                '留学预备': (5, 3),
                '高中': (7, 4),
                '大学': (13, 5),
                UNKNOWN_GROUP: (12, 6),
            },
        )
        self.assertEqual(business['留学预备']['orders']['target'], 10)
        self.assertEqual(business['高中']['orders']['target'], 20)
        self.assertEqual(business['大学']['orders']['target'], 30)
        self.assertIsNone(business[UNKNOWN_GROUP]['orders']['target'])
        self.assertEqual((business[UNKNOWN_GROUP]['cash']['actual'],
                          business[UNKNOWN_GROUP]['cash']['prior'],
                          business[UNKNOWN_GROUP]['cash']['target']), (0, 0, None))
        self.assertEqual((business[UNKNOWN_GROUP]['heads']['actual'],
                          business[UNKNOWN_GROUP]['heads']['prior'],
                          business[UNKNOWN_GROUP]['heads']['target']), (0, 0, None))
        for name, row in business.items():
            if name in group_cash_before:
                self.assertEqual(row['cash'], group_cash_before[name])
                self.assertEqual(row['heads'], group_heads_before[name])

        yoy = {row['name']: row for row in total['yoy_groups']}
        self.assertEqual(
            {name: (yoy[name]['orders']['actual'], yoy[name]['orders']['prior'])
             for name in ('青少', '初中', '高中', '大学', UNKNOWN_GROUP)},
            {'青少': (2, 1), '初中': (3, 2), '高中': (7, 4),
             '大学': (13, 5), UNKNOWN_GROUP: (12, 6)},
        )
        for name, (cash, heads) in yoy_non_order_before.items():
            self.assertEqual(yoy[name]['cash'], cash)
            self.assertEqual(yoy[name]['heads'], heads)
        # The newly restored unknown comparison row is order-only because its
        # source query does not provide cash/head comparisons.
        self.assertNotIn('cash', yoy[UNKNOWN_GROUP])
        self.assertNotIn('heads', yoy[UNKNOWN_GROUP])

    def test_existing_unknown_rows_keep_cash_heads_and_order_targets(self):
        total = make_total(include_unknown=True)
        business_unknown = by_name(total['business_groups'], UNKNOWN_GROUP)
        yoy_unknown = by_name(total['yoy_groups'], UNKNOWN_GROUP)
        business_cash = deepcopy(business_unknown['cash'])
        business_heads = deepcopy(business_unknown['heads'])
        yoy_cash = deepcopy(yoy_unknown['cash'])
        yoy_heads = deepcopy(yoy_unknown['heads'])
        source = period(total)

        attach_market_orders([source], baseline_rows())

        business_unknown = by_name(total['business_groups'], UNKNOWN_GROUP)
        yoy_unknown = by_name(total['yoy_groups'], UNKNOWN_GROUP)
        self.assertEqual(business_unknown['orders']['target'], 4)
        self.assertEqual((business_unknown['orders']['actual'],
                          business_unknown['orders']['prior']), (12, 6))
        self.assertEqual(business_unknown['cash'], business_cash)
        self.assertEqual(business_unknown['heads'], business_heads)
        self.assertEqual(yoy_unknown['orders']['target'], 5)
        self.assertEqual((yoy_unknown['orders']['actual'],
                          yoy_unknown['orders']['prior']), (12, 6))
        self.assertEqual(yoy_unknown['cash'], yoy_cash)
        self.assertEqual(yoy_unknown['heads'], yoy_heads)

    def test_future_unknown_rows_and_market_metric_have_no_actual_or_prior(self):
        total = make_total(status='future', training_target=50)
        source = period(
            total, status='future', start='2026-10-01', through=None,
        )

        attach_market_orders([source], baseline_rows())

        market = total['market_orders']
        self.assertIsNone(market['actual'])
        self.assertIsNone(market['prior'])
        self.assertEqual(market['target'], 50)
        self.assertEqual(market['status'], 'future')
        self.assertNotIn('target', total['lines']['training']['orders'])
        self.assertIsNone(total['lines']['training']['orders']['actual'])
        self.assertIsNone(total['lines']['training']['orders']['prior'])

        business_unknown = by_name(total['business_groups'], UNKNOWN_GROUP)
        self.assertEqual(business_unknown['orders']['status'], 'future')
        self.assertIsNone(business_unknown['orders']['actual'])
        self.assertIsNone(business_unknown['orders']['prior'])
        for key in ('cash', 'heads'):
            self.assertEqual(business_unknown[key]['status'], 'future')
            self.assertIsNone(business_unknown[key]['actual'])
            self.assertIsNone(business_unknown[key]['prior'])

        yoy_unknown = by_name(total['yoy_groups'], UNKNOWN_GROUP)
        self.assertEqual(yoy_unknown['orders']['status'], 'future')
        self.assertIsNone(yoy_unknown['orders']['actual'])
        self.assertIsNone(yoy_unknown['orders']['prior'])


if __name__ == '__main__':
    unittest.main()
