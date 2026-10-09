"""Regression tests for P2 management rollups and source boundaries."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from dashboard_product.management.aggregate import aggregate
from workspace_modeling.operations.personnel import (
    DEFAULT_ORDER_STATUS_MODE,
    ORDER_STATUS_MODES,
    order_status_allowed,
)


def training_person(name, group, targets=None):
    return {
        'display_name': name,
        'status': 'active',
        'business_group': group,
        'monthly_targets': targets or {},
    }


def inputs(*groups, virtual=()):
    teams = [{
            'team_id': 'offline_market',
            'groups': [
                {'display_name': '大学组', 'members': list(groups[0])},
                {'display_name': '高中组', 'members': list(groups[1])},
            ],
        }]
    if virtual:
        teams.append({
            'team_id': 'online_private',
            'groups': [{'display_name': '大学组', 'members': list(virtual)}],
        })
    return {'teams': teams}


def fact(fid, metric, line, day, value, *, group=None, team='offline_market',
         owners=(), student=None, campaign=None, country=None, business_line_name=None,
         acquisition_mode=None, offline_channel_eligible=False, virtual_owners=(),
         team_inferred=False, order_status=None, counts_toward_completion=True,
         segment_id=None, source_product=None, customer_domain=None, source_kind=None):
    row = {
        'fact_id': fid,
        'metric': metric,
        'business_line': line,
        'event_date': day,
        'value': value,
        'work_order_id': fid,
        'student_id': student,
        'team_id': team,
        'business_group': group,
        'campaign_name': campaign,
        'first_channel': None,
        'second_channel': None,
        'country': country,
        'line': business_line_name,
        'owners': list(owners),
        'virtual_owners': list(virtual_owners),
        'acquisition_mode': acquisition_mode,
        'offline_channel_eligible': offline_channel_eligible,
        'team_inferred': team_inferred,
        'order_status': order_status,
        'counts_toward_completion': counts_toward_completion,
    }
    if line == 'abroad':
        row.update({
            'segment_id': segment_id or (
                'study_abroad_online' if team == 'online_platform' else
                'study_abroad_offline' if team == 'offline_market' and offline_channel_eligible else
                'unassigned'
            ),
            'source_product': source_product or 'study_abroad',
            'customer_domain': customer_domain or 'study_abroad',
            'source_kind': source_kind or 'study_abroad_warehouse',
        })
    return row


def abroad_people():
    return {'people': [{'display_name': '孙伟', 'business_group': '大学',
                        'monthly_targets': {}}]}


def project_targets():
    return {'business_groups': {}}


def study_coverage(start_date='2026-09-01', through_date='2026-09-30'):
    return {
        'snapshot_id': 'snapshot_study_fixture',
        'source_sha256': 'a' * 64,
        'start_date': start_date,
        'through_date': through_date,
        'no_yoy': True,
        'cross_system_customers': 'not_aligned',
    }


def offline_targets():
    return {
        'total': {'work_order_target': 2620, 'months': {'2026-10': 360}},
        'cash': {'total': {'annual': 660, 'months': {'2026-10': 45}}},
    }


def online_targets():
    return {
        'study_abroad': {'resource_target': {
            'annual': 6715,
            'quarters': {'Q2': 1800},
            'months': {'2026-10': 484},
        }},
        'cash': {'total': {'annual': 2992.56, 'quarters': {'Q2': 748.14}}},
    }


def build(rows, people, *, through='2026-09-28', abroad=None, coverage=None):
    return aggregate(
        rows,
        people,
        abroad or abroad_people(),
        project_targets(),
        offline_targets(),
        online_targets(),
        through,
        abroad_source=coverage or study_coverage(),
    )


def by_team(period, team_id):
    return next(team for team in period['teams'] if team['id'] == team_id)


def by_person(team, name):
    return next(person for person in team['people'] if person['name'] == name)


def actual(metric):
    return metric.get('actual') if isinstance(metric, dict) else metric


class ManagementAggregateTest(unittest.TestCase):
    def test_team_and_person_windows_are_independent_at_month_boundary(self):
        people = inputs(
            [training_person('大学同事', '大学', {
                '2026-09': {'orders': 10}, '2026-10': {'orders': 20},
            })],
            [],
        )
        result = build([
            fact('before-cutoff', 'orders', 'training', '2026-09-25', 5,
                 group='大学', owners=['大学同事']),
            fact('in-performance-window', 'orders', 'training', '2026-09-26', 1,
                 group='大学', owners=['大学同事']),
            fact('after-data-through', 'orders', 'training', '2026-09-29', 7,
                 group='大学', owners=['大学同事']),
        ], people)
        october = next(period for period in result['periods'] if period['id'] == '2026-10')
        university = by_team(october, 'university')
        person = by_person(university, '大学同事')
        calendar = university['person_calendar']
        calendar_person = by_person(calendar, '大学同事')

        self.assertEqual(october['status'], 'future')
        self.assertEqual(university['lines']['training']['orders']['actual'], None)
        self.assertEqual(university['person_start'], '2026-09-26')
        self.assertEqual(university['person_through'], '2026-09-28')
        self.assertEqual(actual(person['training_actual']), 1)
        self.assertEqual(set(person['order_status_views']), set(ORDER_STATUS_MODES))
        for mode in ORDER_STATUS_MODES:
            self.assertEqual(person['order_status_views'][mode]['training_actual'], 1)
        self.assertEqual(calendar['person_start'], '2026-10-01')
        self.assertIsNone(calendar['person_through'])
        self.assertEqual(calendar['person_progress'], 0)
        self.assertIsNone(calendar_person['training_actual'])
        self.assertEqual(calendar_person['training_target'], 20)
        for view in calendar_person['order_status_views'].values():
            self.assertIsNone(view['training_actual'])
            self.assertIsNone(view['training_prior'])
            self.assertEqual(view['training_target'], 20)

    def test_calendar_people_use_natural_bounds_and_keep_month_targets(self):
        people = inputs(
            [training_person('大学同事', '大学', {
                '2026-09': {'orders': 10, 'cash': 1000},
            })],
            [],
        )
        rows = [
            fact('before-performance', 'orders', 'training', '2026-08-25', 11,
                 group='大学', owners=['大学同事']),
            fact('performance-start', 'orders', 'training', '2026-08-26', 2,
                 group='大学', owners=['大学同事']),
            fact('calendar-start', 'orders', 'training', '2026-09-01', 3,
                 group='大学', owners=['大学同事']),
            fact('shared-student-one', 'orders', 'training', '2026-09-25', 5,
                 group='大学', owners=['大学同事']),
            fact('calendar-only', 'orders', 'training', '2026-09-26', 7,
                 group='大学', owners=['大学同事']),
            fact('before-performance-cash', 'cash', 'training', '2026-08-25', 110,
                 group='大学', owners=['大学同事'], student='outside'),
            fact('performance-cash', 'cash', 'training', '2026-08-26', 100,
                 group='大学', owners=['大学同事'], student='performance'),
            fact('calendar-cash-one', 'cash', 'training', '2026-09-01', 200,
                 group='大学', owners=['大学同事'], student='shared'),
            fact('calendar-cash-two', 'cash', 'training', '2026-09-25', 300,
                 group='大学', owners=['大学同事'], student='shared'),
            fact('calendar-cash-late', 'cash', 'training', '2026-09-26', 400,
                 group='大学', owners=['大学同事'], student='calendar-only'),
            fact('performance-prior-one', 'cash', 'training', '2025-08-26', 25,
                 group='大学', owners=['大学同事'], student='prior-performance'),
            fact('performance-prior-two', 'cash', 'training', '2025-09-25', 75,
                 group='大学', owners=['大学同事'], student='prior-performance'),
            fact('calendar-prior-one', 'cash', 'training', '2025-09-01', 40,
                 group='大学', owners=['大学同事'], student='prior-calendar'),
            fact('calendar-prior-two', 'cash', 'training', '2025-09-26', 60,
                 group='大学', owners=['大学同事'], student='prior-calendar'),
        ]
        result = build(rows, people, through='2026-09-28')
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        university = by_team(september, 'university')
        performance_person = by_person(university, '大学同事')
        calendar = university['person_calendar']
        calendar_person = by_person(calendar, '大学同事')

        self.assertEqual(university['person_start'], '2026-08-26')
        self.assertEqual(university['person_through'], '2026-09-25')
        self.assertEqual(performance_person['training_actual'], 10)
        self.assertEqual(performance_person['training_prior'], 0)
        self.assertEqual(performance_person['cash_actual']['actual'], 600)
        self.assertEqual(performance_person['cash_actual']['target'], 1000)
        self.assertAlmostEqual(performance_person['cash_actual']['yoy'], 600 / 140 - 1)
        self.assertEqual(performance_person['heads_actual']['actual'], 2)
        self.assertEqual(performance_person['heads_actual']['prior'], 2)

        self.assertEqual(calendar['person_start'], '2026-09-01')
        self.assertEqual(calendar['person_through'], '2026-09-28')
        self.assertAlmostEqual(calendar['person_progress'], 28 / 30)
        self.assertEqual(calendar_person['training_actual'], 15)
        self.assertEqual(calendar_person['training_prior'], 0)
        self.assertEqual(calendar_person['training_target'], performance_person['training_target'])
        self.assertEqual(calendar_person['cash_actual']['actual'], 900)
        self.assertEqual(calendar_person['cash_actual']['prior'], 175)
        self.assertEqual(calendar_person['cash_actual']['target'], 1000)
        self.assertAlmostEqual(calendar_person['cash_actual']['yoy'], 900 / 175 - 1)
        self.assertEqual(calendar_person['cash_actual']['time_gap'], -33.33)
        self.assertEqual(calendar_person['heads_actual']['actual'], 2)
        self.assertEqual(calendar_person['heads_actual']['prior'], 2)
        # Team rollups retain their existing natural-calendar actuals.
        self.assertEqual(university['lines']['training']['orders']['actual'], 15)

    def test_shared_owner_cash_deduplicates_qualified_heads(self):
        people = inputs(
            [training_person('大学同事', '大学'), training_person('大学同事乙', '大学')],
            [training_person('高中同事', '高中')],
        )
        rows = [
            fact('uni-order', 'orders', 'training', '2026-09-10', 1,
                 group='大学', owners=['大学同事', '高中同事'], campaign='共同活动'),
            fact('cash-one', 'cash', 'training', '2026-09-10', 1000,
                 group='大学', owners=['大学同事', '高中同事'], student='S-1', campaign='共同活动'),
            # Same student across cash rows; team headcount still deduplicates.
            fact('cash-repeat', 'cash', 'training', '2026-09-11', 1200,
                 group='大学', owners=['大学同事', '高中同事'], student='S-1', campaign='共同活动'),
        ]
        result = build(rows, people, through='2026-09-28')
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        university = by_team(september, 'university')
        high = by_team(september, 'high')
        uni_person = by_person(university, '大学同事')
        high_person = by_person(high, '高中同事')

        self.assertEqual(university['lines']['training']['heads']['actual'], 1)
        self.assertEqual(actual(uni_person['heads_actual']), 0.5)
        self.assertEqual(actual(high_person['heads_actual']), 0)
        self.assertEqual(actual(high_person['training_actual']), 0)
        self.assertEqual(actual(uni_person['training_actual']), 0.5)

    def test_abroad_roster_uses_the_same_hidden_status_filter_as_training(self):
        people = inputs([], [])
        abroad = {'people': [
            {'display_name': '留学在职', 'business_group': '大学'},
            {'display_name': '留学离职', 'business_group': '大学', 'status': 'departed'},
            {'display_name': '留学转岗', 'business_group': '大学', 'status': 'transferred'},
            {'display_name': '留学空缺', 'business_group': '大学', 'status': 'vacant'},
        ]}
        result = build([
            fact('active-abroad', 'orders', 'abroad', '2026-09-10', 1,
                 team='online_platform', owners=['留学在职']),
            fact('departed-abroad', 'orders', 'abroad', '2026-09-10', 1,
                 team='online_platform', owners=['留学离职']),
        ], people, abroad=abroad)

        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        total = by_team(september, 'total')
        self.assertEqual([person['name'] for person in total['people']], ['留学在职'])

    def test_configured_abroad_roster_moves_ma_yue_to_high_without_changing_personal_credit(self):
        root = Path(__file__).resolve().parents[2]
        abroad_config = json.loads((root / 'config/offline_market_people.json').read_text(encoding='utf-8'))
        training_config = json.loads(
            (root.parent / 'workspace_modeling/operations/people.json').read_text(encoding='utf-8')
        )
        ma_yue_entries = [row for row in abroad_config['people']
                          if row['display_name'] == '马玥']
        training_names = {
            person['display_name']
            for team in training_config['teams']
            if team['team_id'] in ('offline_market', 'online_private')
            for group in team.get('groups', [])
            for person in group.get('members', [])
        }
        abroad_names = [row['display_name'] for row in abroad_config['people']]
        self.assertEqual(len(ma_yue_entries), 1)
        self.assertEqual(ma_yue_entries[0]['business_group'], '高中')
        self.assertEqual(len(abroad_names), len(set(abroad_names)))
        self.assertNotIn('马玥', training_names)
        self.assertTrue(all(row.get('business_group') in ('大学', '高中')
                            for row in abroad_config['people']))

        people = inputs([], [])
        abroad = {'people': [
            {'display_name': '马玥', 'business_group': '高中'},
            {'display_name': '邓睿', 'business_group': '大学'},
        ]}
        rows = [
            fact('current-search', 'orders', 'abroad', '2026-09-10', 1,
                 team='offline_market', owners=['马玥', '邓睿'],
                 acquisition_mode='offline', offline_channel_eligible=True,
                 campaign='市场活动', business_line_name='英澳条线'),
            fact('current-unknown', 'orders', 'abroad', '2026-09-11', 1,
                 team='offline_market', owners=['马玥', '邓睿'],
                 acquisition_mode='offline', offline_channel_eligible=True),
        ]
        rows[0]['first_channel'] = '市场活动'
        rows[0]['second_channel'] = '讲座'
        rows[1]['first_channel'] = None
        rows[1]['second_channel'] = ''

        result = build(rows, people, through='2026-09-28', abroad=abroad)
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        high = by_team(september, 'high')
        university = by_team(september, 'university')
        ma_yue = by_person(high, '马玥')
        deng_rui = by_person(university, '邓睿')

        self.assertNotIn('马玥', {person['name'] for person in university['people']})
        self.assertIn('马玥', {person['name'] for person in high['people']})
        self.assertNotIn('abroad_channels', deng_rui)
        self.assertEqual(ma_yue['abroad_actual'], 1)
        self.assertIsNone(ma_yue['abroad_prior'])
        channels = ma_yue['abroad_channels']
        self.assertEqual(
            {(row['first_channel'], row['name']) for row in channels},
            {('市场活动', '讲座'), ('一级渠道待确认', '二级渠道待确认')},
        )
        self.assertEqual(sum(row['orders']['actual'] for row in channels), ma_yue['abroad_actual'])
        self.assertAlmostEqual(sum(row['share'] for row in channels), 1)
        search = next(row for row in channels if row['name'] == '讲座')
        self.assertEqual(search['orders']['actual'], 0.5)
        self.assertIsNone(search['orders']['prior'])
        self.assertEqual(search['orders']['unit'], '单')
        self.assertEqual(search['orders']['status'], 'available')
        self.assertIsNone(search['orders']['yoy'])
        self.assertEqual(university['lines']['abroad']['orders']['actual'], 2)
        self.assertEqual(high['lines']['abroad']['orders']['status'], 'not_configured')

        performance_names = {person['name'] for person in high['people']}
        calendar_people = {person['name']: person
                           for person in high['person_calendar']['people']}
        self.assertIn('马玥', performance_names)
        self.assertIn('马玥', calendar_people)
        self.assertEqual(calendar_people['马玥']['abroad_actual'], 1)
        self.assertEqual(sum(row['orders']['actual']
                             for row in calendar_people['马玥']['abroad_channels']), 1)
        future = next(period for period in result['periods'] if period['id'] == '2026-11')
        future_high = by_team(future, 'high')
        self.assertEqual(by_person(future_high, '马玥')['abroad_channels'], [])
        self.assertEqual(
            by_person(future_high['person_calendar'], '马玥')['abroad_channels'], [],
        )

    def test_dual_training_and_abroad_member_keeps_training_home_group(self):
        people = inputs([training_person('双名单同事', '大学')], [])
        abroad = {'people': [{'display_name': '双名单同事', 'business_group': '高中'}]}

        result = build([], people, abroad=abroad)
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        total_person = by_person(by_team(september, 'total'), '双名单同事')

        self.assertEqual(total_person['home_group'], '大学')
        self.assertEqual(total_person['business_line'], 'training+abroad')
        self.assertIn('双名单同事', {row['name'] for row in by_team(september, 'university')['people']})
        self.assertNotIn('双名单同事', {row['name'] for row in by_team(september, 'high')['people']})

    def test_abroad_channel_fractional_rows_keep_each_fact_weight(self):
        people = inputs([], [])
        abroad = {'people': [
            {'display_name': '马玥', 'business_group': '高中'},
            {'display_name': '大学甲', 'business_group': '大学'},
            {'display_name': '大学乙', 'business_group': '大学'},
        ]}
        owners = ['马玥', '大学甲', '大学乙']
        rows = [
            fact(f'fraction-{index}', 'orders', 'abroad', '2026-09-10', 1,
                 team='offline_market', owners=owners,
                 acquisition_mode='offline', offline_channel_eligible=True,
                 business_line_name='亚洲条线')
            for index in range(3)
        ]
        for index, row in enumerate(rows):
            row['first_channel'] = f'一级{index}'
            row['second_channel'] = f'二级{index}'

        result = build(rows, people, through='2026-09-28', abroad=abroad)
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        ma_yue = by_person(by_team(september, 'high'), '马玥')
        channels = ma_yue['abroad_channels']

        self.assertEqual(ma_yue['abroad_actual'], 1)
        self.assertEqual([row['orders']['actual'] for row in channels], [1 / 3] * 3)
        self.assertAlmostEqual(sum(row['orders']['actual'] for row in channels),
                               ma_yue['abroad_actual'])

    def test_university_reciprocal_target_rounds_each_month_half_up_then_sums(self):
        targets = {
            '2026-09': {'orders': 0},
            '2026-10': {'orders': 15},  # 1.5 rounds up to 2.
            '2026-11': {'orders': 25},  # 2.5 rounds up to 3.
        }
        people = inputs([training_person('大学同事', '大学', targets)], [])
        result = build([], people, through='2026-11-30')
        q2 = next(period for period in result['periods'] if period['id'] == 'Q2')
        person = by_person(by_team(q2, 'university'), '大学同事')
        self.assertEqual(person['training_target'], 40)
        self.assertEqual(person['abroad_target'], 5)

    def test_preparation_and_high_school_abroad_are_unconfigured(self):
        people = inputs(
            [training_person('预备同事', '留学预备')],
            [training_person('高中同事', '高中')],
        )
        result = build([
            fact('abroad-one', 'orders', 'abroad', '2026-09-10', 1,
                 team=None, owners=['预备同事'], campaign='留学活动'),
        ], people)
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        for team_id in ('prep', 'high'):
            value = by_team(september, team_id)['lines']['abroad']['orders']
            self.assertEqual(value['status'], 'not_configured')
            self.assertIsNone(value['actual'])
            self.assertIn('暂不', value['note'])
            self.assertIn('贡献见人员产能', value['note'])
        self.assertEqual(actual(by_person(by_team(september, 'prep'), '预备同事')['abroad_actual']), 1)
        self.assertEqual(actual(by_person(by_team(september, 'high'), '高中同事')['abroad_actual']), 0)
        self.assertIsNone(by_person(by_team(september, 'prep'), '预备同事')['abroad_target'])

    def test_activities_include_connected_abroad_cash_and_keep_customer_domains_separate(self):
        people = inputs([], [])
        result = build([
            fact('old-training-order', 'orders', 'training', '2025-04-03', 3,
                 group='大学', campaign='联合活动'),
            fact('old-training-cash', 'cash', 'training', '2025-04-03', 500,
                 group='大学', student='S-2', campaign='联合活动'),
            fact('abroad-order', 'orders', 'abroad', '2026-09-04', 1,
                 team='offline_market', owners=['孙伟'], student='S-3', country='英国',
                 business_line_name='英澳条线', campaign='联合活动'),
            fact('abroad-cash', 'cash', 'abroad', '2026-09-04', 250,
                 team='offline_market', owners=['孙伟'], student='S-4',
                 campaign='联合活动'),
            fact('abroad-only-order', 'orders', 'abroad', '2026-09-05', 2,
                 team=None, owners=[], country='日本', business_line_name='欧亚条线',
                 campaign='留学单线活动'),
            fact('abroad-only-cash', 'cash', 'abroad', '2026-09-05', 350,
                 team=None, owners=[], student='study-only', campaign='留学单线活动'),
        ], people, through='2026-09-28')
        activities = {activity['name']: activity for activity in result['activities']}
        combined = activities['联合活动']
        self.assertEqual(combined['training_orders'], 3)
        self.assertEqual(combined['abroad_orders'], 1)
        self.assertEqual(combined['orders'], 4)
        self.assertEqual(combined['cash'], 750)
        self.assertIsNone(combined['heads'])
        self.assertEqual(combined['heads_parts'], [
            {'label': '语培', 'actual': 1}, {'label': '留学', 'actual': 1},
        ])
        self.assertEqual(combined['cash_status'], 'partial')

        abroad_only = activities['留学单线活动']
        self.assertEqual(abroad_only['cash'], 350)
        self.assertEqual(abroad_only['heads'], 1)
        self.assertEqual(abroad_only['cash_status'], 'available')


    def test_unknown_group_is_retained_in_total_but_not_platform_kpi(self):
        rows = [fact('unknown', 'orders', 'training', '2026-09-01', 1, team='online_platform')]
        result = build(rows, inputs([], []))
        month = next(p for p in result['periods'] if p['id'] == '2026-09')
        self.assertEqual(by_team(month, 'total')['lines']['training']['orders']['actual'], 1)
        self.assertEqual(by_team(month, 'online')['lines']['training']['orders']['actual'], 0)

    def test_abroad_segment_routes_are_authoritative_over_channel_labels(self):
        rows = [
            fact('offline-segment', 'orders', 'abroad', '2026-09-01', 1,
                 team='offline_market', owners=['孙伟'], acquisition_mode='online',
                 country='英国', offline_channel_eligible=True),
            fact('online-segment', 'orders', 'abroad', '2026-09-02', 2,
                 team='online_platform', owners=['孙伟'], acquisition_mode='offline',
                 country='日本', offline_channel_eligible=True),
        ]
        result = build(rows, inputs([], []))
        month = next(p for p in result['periods'] if p['id'] == '2026-09')
        university = by_team(month, 'university')
        self.assertEqual(university['lines']['abroad']['orders']['actual'], 1)
        self.assertEqual(university['countries'][0]['online'], 0)
        self.assertEqual(university['countries'][0]['offline'], 1)
        online = by_team(month, 'online')
        self.assertEqual(online['lines']['abroad']['orders']['actual'], 2)
        self.assertEqual(online['countries'][0]['online'], 2)
        self.assertEqual(online['countries'][0]['offline'], 0)

    def test_abroad_segments_keep_supplemental_products_out_of_departments(self):
        rows = [
            fact('international', 'orders', 'abroad', '2026-09-01', 1,
                 team='offline_market', owners=['孙伟'], country='英国',
                 segment_id='international_market'),
            fact('ssc', 'orders', 'abroad', '2026-09-02', 2,
                 team='online_platform', owners=['孙伟'], country='日本',
                 segment_id='ssc'),
            fact('unassigned', 'orders', 'abroad', '2026-09-03', 3,
                 team=None, owners=[], country='法国', segment_id='unassigned'),
            fact('offline', 'orders', 'abroad', '2026-09-04', 4,
                 team='offline_market', owners=[], country='意大利',
                 offline_channel_eligible=True),
            fact('online', 'orders', 'abroad', '2026-09-05', 5,
                 team='online_platform', owners=[], country='西班牙'),
        ]
        result = build(rows, inputs([], []), abroad={'people': []})
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        university = by_team(september, 'university')
        online_team = by_team(september, 'online')
        total = by_team(september, 'total')
        self.assertEqual(university['lines']['abroad']['orders']['actual'], 4)
        self.assertEqual(online_team['lines']['abroad']['orders']['actual'], 5)
        self.assertEqual([row['country'] for row in university['countries']], ['意大利'])
        self.assertEqual([row['country'] for row in online_team['countries']], ['西班牙'])
        self.assertEqual(total['lines']['abroad']['orders']['actual'], 15)
        self.assertEqual(
            {row['id']: row['orders']['actual'] for row in total['lines']['abroad']['supplemental']},
            {'international_market': 1, 'ssc': 2, 'unassigned': 3},
        )

    def test_abroad_metrics_use_coverage_without_yoy_or_fabricated_zeroes(self):
        rows = [
            fact('sept-order', 'orders', 'abroad', '2026-09-10', 2,
                 team='offline_market', offline_channel_eligible=True),
            fact('sept-cash-study-1', 'cash', 'abroad', '2026-09-10', 200,
                 team='offline_market', offline_channel_eligible=True, student='S-1'),
            fact('sept-cash-study-1-repeat', 'cash', 'abroad', '2026-09-11', 300,
                 team='offline_market', offline_channel_eligible=True, student='S-1',
                 order_status='删除', counts_toward_completion=False),
            fact('sept-cash-study-2', 'cash', 'abroad', '2026-09-12', 100,
                 team='offline_market', offline_channel_eligible=True, student='S-2'),
            fact('sept-cash-small-1', 'cash', 'abroad', '2026-09-13', 80,
                 team='offline_market', offline_channel_eligible=True, student='S-1',
                 source_product='small_language', customer_domain='small_language'),
            fact('sept-cash-small-1-repeat', 'cash', 'abroad', '2026-09-14', 20,
                 team='offline_market', offline_channel_eligible=True, student='S-1',
                 source_product='small_language', customer_domain='small_language',
                 order_status='删除', counts_toward_completion=False),
        ]
        result = build(rows, inputs([], []), through='2026-10-15')
        periods = {period['id']: period for period in result['periods']}
        for period_id in ('2026-06', '2026-07', '2026-08', '2026-10'):
            metric_row = by_team(periods[period_id], 'total')['lines']['abroad']['orders']
            self.assertIsNone(metric_row['actual'])
            self.assertEqual(metric_row['status'], 'not_covered')

        september = by_team(periods['2026-09'], 'total')['lines']['abroad']
        self.assertEqual(september['orders']['actual'], 2)
        self.assertIsNone(september['orders']['prior'])
        self.assertIsNone(september['orders']['yoy'])
        self.assertEqual(september['cash']['actual'], 700)
        self.assertIsNone(september['heads']['actual'])
        self.assertEqual(september['heads']['status'], 'separate_counts')
        self.assertEqual(september['heads']['parts'], [
            {'label': '留学', 'actual': 2}, {'label': '小语种', 'actual': 1},
        ])
        university = by_team(periods['2026-09'], 'university')['lines']['abroad']
        self.assertEqual(university['cash']['actual'], 700)
        self.assertIsNone(university['cash']['prior'])
        self.assertIsNone(university['cash']['yoy'])
        self.assertIsNone(university['heads']['actual'])
        self.assertEqual(university['heads']['status'], 'separate_counts')
        self.assertEqual(university['heads']['parts'], september['heads']['parts'])
        for period_id in ('Q2', 'FY27'):
            metric_row = by_team(periods[period_id], 'total')['lines']['abroad']['orders']
            self.assertEqual(metric_row['status'], 'partial')
            self.assertEqual(metric_row['actual'], 2)
            self.assertEqual(metric_row['source_coverage']['start_date'], '2026-09-01')
            self.assertEqual(metric_row['source_coverage']['through_date'], '2026-09-30')
            online = by_team(periods[period_id], 'online')['lines']['abroad']['orders']
            self.assertIsNotNone(online['target'])
            self.assertEqual(online['actual'], 0)
            self.assertEqual(online['completion'], online['actual'] / online['target'])
            self.assertIsNone(online['gap'])
            self.assertIsNone(online['time_gap'])
            online_cash = by_team(periods[period_id], 'online')['lines']['abroad']['cash']
            self.assertEqual(online_cash['actual'], 0)
            expected_cash_target = 7481400 if period_id == 'Q2' else 29925600
            self.assertEqual(online_cash['target'], expected_cash_target)
            self.assertEqual(online_cash['completion'], 0)
            self.assertIsNone(online_cash['gap'])
            self.assertIsNone(online_cash['time_gap'])

    def test_partial_annual_abroad_progress_uses_line_targets_and_october_keeps_uncovered_targets(self):
        rows = [
            fact('annual-offline-orders', 'orders', 'abroad', '2026-09-30', 131,
                 team='offline_market', offline_channel_eligible=True),
            fact('annual-offline-cash', 'cash', 'abroad', '2026-09-30', 381500,
                 team='offline_market', offline_channel_eligible=True, student='offline-1'),
            fact('annual-online-cash', 'cash', 'abroad', '2026-09-30', 1753064.4,
                 team='online_platform', student='online-1'),
        ]
        result = build(
            rows, inputs([], []), through='2026-10-15',
            coverage=study_coverage('2026-06-01', '2026-09-30'),
        )
        periods = {period['id']: period for period in result['periods']}
        offline = by_team(periods['FY27'], 'university')['lines']['abroad']
        online = by_team(periods['FY27'], 'online')['lines']['abroad']

        self.assertEqual(offline['orders']['actual'], 131)
        self.assertEqual(offline['orders']['target'], 2620)
        self.assertAlmostEqual(offline['orders']['completion'], 131 / 2620)
        self.assertEqual(offline['orders']['status'], 'partial')
        self.assertIsNone(offline['orders']['prior'])
        self.assertIsNone(offline['orders']['yoy'])
        self.assertIsNone(offline['orders']['gap'])
        self.assertIsNone(offline['orders']['time_gap'])
        self.assertEqual(offline['cash']['actual'], 381500)
        self.assertEqual(offline['cash']['target'], 6600000)
        self.assertAlmostEqual(offline['cash']['completion'], 381500 / 6600000)
        self.assertEqual(offline['cash']['status'], 'partial')
        self.assertIsNone(offline['cash']['prior'])
        self.assertIsNone(offline['cash']['yoy'])
        self.assertIsNone(offline['cash']['gap'])
        self.assertIsNone(offline['cash']['time_gap'])
        self.assertEqual(online['cash']['actual'], 1753064.4)
        self.assertEqual(online['cash']['target'], 29925600)
        self.assertAlmostEqual(online['cash']['completion'], 1753064.4 / 29925600)
        self.assertEqual(online['cash']['status'], 'partial')
        self.assertIsNone(online['cash']['prior'])
        self.assertIsNone(online['cash']['yoy'])
        self.assertIsNone(online['cash']['gap'])
        self.assertIsNone(online['cash']['time_gap'])
        self.assertEqual(online['cash']['source_coverage']['start_date'], '2026-06-01')
        self.assertEqual(online['orders']['target'], 6715)
        self.assertEqual(online['orders']['status'], 'partial')

        october = by_team(periods['2026-10'], 'university')['lines']['abroad']
        self.assertIsNone(october['orders']['actual'])
        self.assertEqual(october['orders']['status'], 'not_covered')
        self.assertEqual(october['orders']['target'], 360)
        self.assertIsNone(october['cash']['actual'])
        self.assertEqual(october['cash']['status'], 'not_covered')
        self.assertEqual(october['cash']['target'], 450000)

    def test_abroad_primary_person_uses_covered_cash_from_its_own_sheet(self):
        abroad = {'people': [{'display_name': '留学专员', 'business_group': '大学'}]}
        rows = [
            fact('study-cash', 'cash', 'abroad', '2026-09-10', 420,
                 team='offline_market', owners=['留学专员'], student='study-1',
                 offline_channel_eligible=True, order_status='删除',
                 counts_toward_completion=False),
            fact('training-cash', 'cash', 'training', '2026-09-11', 900,
                 group='大学', owners=['留学专员'], student='training-1'),
            fact('international-cash', 'cash', 'abroad', '2026-09-12', 600,
                 team='online_platform', owners=['留学专员'], student='intl-1',
                 segment_id='international_market'),
        ]
        result = build(rows, inputs([], []), abroad=abroad)
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        person = by_person(by_team(september, 'university'), '留学专员')
        total_person = by_person(by_team(september, 'total'), '留学专员')
        calendar_person = by_person(
            by_team(september, 'university')['person_calendar'], '留学专员',
        )

        self.assertEqual(person['cash_actual']['actual'], 420)
        self.assertEqual(person['cash_actual']['status'], 'partial')
        self.assertEqual(person['heads_actual']['actual'], 1)
        self.assertIsNone(person['cash_actual']['prior'])
        self.assertIsNone(person['cash_actual']['yoy'])
        self.assertEqual(total_person['cash_actual']['actual'], 420)
        self.assertEqual(calendar_person['cash_actual']['actual'], 420)
        self.assertEqual(calendar_person['cash_actual']['status'], 'available')

    def test_incomplete_quarter_personal_target_is_not_partial_sum(self):
        people = inputs([training_person('石仁达', '大学', {'2026-10': {'orders': 85}})], [])
        result = build([], people)
        quarter = next(p for p in result['periods'] if p['id'] == 'Q2')
        person = by_person(by_team(quarter, 'university'), '石仁达')
        self.assertIsNone(person['training_target'])
        self.assertIsNone(person['abroad_target'])


    def test_personal_time_gap_uses_performance_month_progress(self):
        people=inputs([training_person('石仁达','大学',{'2026-10':{'orders':85,'cash':10000}})],[])
        result=build([fact('cash','cash','training','2026-09-27',2000,group='大学',owners=['石仁达'],student='s')],people)
        october=next(p for p in result['periods'] if p['id']=='2026-10')
        team=by_team(october,'university'); person=by_person(team,'石仁达')
        self.assertAlmostEqual(team['person_progress'],.1)
        self.assertEqual(person['cash_actual']['time_gap'],1000)

    def test_virtual_combined_orders_do_not_claim_abroad_by_matching_name(self):
        people = inputs(
            [training_person('大学同事', '大学')], [],
            virtual=[training_person('虚拟甲', '大学'), training_person('虚拟乙', '大学')],
        )
        rows = [
            fact('virtual-training', 'orders', 'training', '2026-09-20', 1,
                 team='online_private', group='大学', owners=['虚拟甲'],
                 virtual_owners=['虚拟甲']),
            fact('shared-abroad', 'orders', 'abroad', '2026-09-20', 1,
                 owners=['虚拟甲', '虚拟乙'], virtual_owners=['虚拟甲', '虚拟乙'],
                 segment_id='international_market'),
            fact('other-training', 'orders', 'training', '2026-09-20', 1,
                 group='大学', owners=['大学同事']),
            fact('unowned-abroad', 'orders', 'abroad', '2026-09-20', 1,
                 owners=[], offline_channel_eligible=True, segment_id='unassigned'),
        ]
        result = build(rows, people, abroad={'people': []})
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        virtual = by_team(september, 'virtual')
        virtual_people = {person['name']: person for person in virtual['people']}
        virtual_calendar = {person['name']: person for person in virtual['person_calendar']['people']}

        self.assertEqual(virtual['lines']['training']['orders']['actual'], 1)
        self.assertEqual(virtual['combined_orders']['actual'], 1)
        self.assertIsNone(virtual['combined_orders']['target'])
        self.assertEqual(virtual_people['虚拟甲']['combined_actual'], 1)
        self.assertIsNone(virtual_people['虚拟甲']['combined_target'])
        self.assertEqual(virtual_people['虚拟乙']['combined_actual'], 0)
        self.assertEqual(virtual_people['虚拟甲']['abroad_actual'], 0)
        self.assertEqual(virtual_people['虚拟乙']['abroad_actual'], 0)
        self.assertEqual(virtual_calendar['虚拟甲']['combined_actual'], 1)
        self.assertIsNone(virtual_calendar['虚拟甲']['combined_target'])
        october = next(period for period in result['periods'] if period['id'] == '2026-10')
        self.assertIsNone(by_team(october, 'virtual')['combined_orders']['actual'])
        future_calendar = by_team(october, 'virtual')['person_calendar']
        self.assertIsNone(by_person(future_calendar, '虚拟甲')['combined_actual'])

        # Supplemental international rows remain in total but never enter a department or person.
        self.assertEqual(by_team(september, 'total')['lines']['training']['orders']['actual'], 2)
        self.assertEqual(by_team(september, 'total')['lines']['abroad']['orders']['actual'], 2)
        self.assertEqual(by_team(september, 'university')['lines']['training']['orders']['actual'], 1)
        self.assertEqual(by_team(september, 'university')['lines']['abroad']['orders']['actual'], 0)

    def test_virtual_personal_orders_and_cash_use_virtual_owners_across_team_and_group(self):
        people = inputs(
            [training_person('大学同事', '大学')],
            [training_person('高中同事', '高中')],
            virtual=[training_person('虚拟甲', '大学'), training_person('虚拟乙', '留学预备')],
        )
        rows = [
            fact('cross-training', 'orders', 'training', '2026-09-10', 1,
                 team='offline_market', group='高中', owners=['高中同事'],
                 virtual_owners=['虚拟甲', '虚拟乙']),
            fact('invalid-training', 'orders', 'training', '2026-09-11', 1,
                 team='offline_market', group='高中', owners=['高中同事'],
                 virtual_owners=['虚拟甲'], order_status='无效'),
            fact('inferred-cash', 'cash', 'training', '2026-09-12', 1200,
                 team='offline_market', group='高中', owners=['高中同事'],
                 virtual_owners=['虚拟甲'], team_inferred=True, order_status='删除',
                 student='cash-inferred'),
            fact('shared-cash', 'cash', 'training', '2026-09-13', 300,
                 team='offline_market', group='大学', owners=['大学同事'],
                 virtual_owners=['虚拟乙'], student='cash-shared'),
            fact('cross-abroad', 'orders', 'abroad', '2026-09-14', 1,
                 team='online_platform', group='高中', owners=['孙伟'],
                 acquisition_mode='online',
                 country='日本', business_line_name='亚洲条线'),
        ]

        result = build(rows, people, through='2026-09-28')
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        high = by_team(september, 'high')
        university = by_team(september, 'university')
        online = by_team(september, 'online')
        virtual = by_team(september, 'virtual')
        virtual_people = {row['name']: row for row in virtual['people']}

        self.assertEqual(high['lines']['training']['orders']['actual'], 2)
        self.assertEqual(high['lines']['training']['cash']['actual'], 1200)
        self.assertEqual(university['lines']['training']['cash']['actual'], 300)
        self.assertEqual(online['lines']['abroad']['orders']['actual'], 1)
        self.assertEqual(virtual['lines']['training']['orders']['actual'], 0)
        self.assertEqual(virtual['combined_orders']['actual'], 0)

        self.assertEqual(virtual_people['虚拟甲']['training_actual'], 1)
        self.assertEqual(virtual_people['虚拟甲']['abroad_actual'], 0)
        self.assertEqual(virtual_people['虚拟甲']['combined_actual'], 1)
        self.assertEqual(virtual_people['虚拟甲']['cash_actual']['actual'], 1200)
        self.assertEqual(virtual_people['虚拟甲']['heads_actual']['actual'], 0)
        self.assertEqual(virtual_people['虚拟乙']['training_actual'], 1)
        self.assertEqual(virtual_people['虚拟乙']['abroad_actual'], 0)
        self.assertEqual(virtual_people['虚拟乙']['cash_actual']['actual'], 300)
        self.assertEqual(virtual_people['虚拟乙']['heads_actual']['actual'], 0)

        high_person = by_person(high, '高中同事')
        self.assertEqual(high_person['training_actual'], 2)
        self.assertEqual(high_person['cash_actual']['actual'], 0)
        self.assertEqual(university['lines']['training']['heads']['actual'], 1)

    def test_offline_cocreators_share_across_home_groups_without_reallocation(self):
        people = inputs(
            [training_person('大学同事', '大学')],
            [training_person('高中同事', '高中')],
            virtual=[training_person('虚拟甲', '大学')],
        )
        owners = ['大学同事', '高中同事']
        virtual_owners = ['虚拟甲']
        rows = [
            fact('university-order', 'orders', 'training', '2026-09-10', 1,
                 group='大学', owners=owners, virtual_owners=virtual_owners),
            fact('high-order', 'orders', 'training', '2026-09-10', 1,
                 group='高中', owners=owners, virtual_owners=virtual_owners),
            fact('university-cash', 'cash', 'training', '2026-09-10', 100,
                 group='大学', owners=owners, virtual_owners=virtual_owners, student='S-1'),
            fact('high-cash', 'cash', 'training', '2026-09-10', 100,
                 group='高中', owners=owners, virtual_owners=virtual_owners, student='S-1'),
        ]

        result = build(rows, people, through='2026-09-28', abroad={'people': []})
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        total = by_team(september, 'total')
        total_people = {person['name']: person for person in total['people']}
        calendar_people = {person['name']: person for person in total['person_calendar']['people']}

        self.assertEqual(total['lines']['training']['orders']['actual'], 2)
        self.assertEqual(total['lines']['training']['cash']['actual'], 200)
        self.assertEqual(total['lines']['training']['heads']['actual'], 1)
        self.assertEqual(total_people['大学同事']['training_actual'], 0.5)
        self.assertEqual(total_people['高中同事']['training_actual'], 0.5)
        self.assertEqual(total_people['虚拟甲']['training_actual'], 2)
        self.assertEqual(total_people['大学同事']['cash_actual']['actual'], 50)
        self.assertEqual(total_people['高中同事']['cash_actual']['actual'], 50)
        self.assertEqual(total_people['虚拟甲']['cash_actual']['actual'], 200)
        self.assertEqual(actual(total_people['大学同事']['heads_actual']), 0.5)
        self.assertEqual(actual(total_people['高中同事']['heads_actual']), 0.5)
        self.assertEqual(actual(total_people['虚拟甲']['heads_actual']), 0)

        # The same shared credits appear in the 26th-to-25th personal window
        # and in the independent natural-calendar view.
        for name in ('大学同事', '高中同事', '虚拟甲'):
            self.assertEqual(calendar_people[name]['training_actual'], total_people[name]['training_actual'])
            self.assertEqual(calendar_people[name]['cash_actual']['actual'], total_people[name]['cash_actual']['actual'])
        self.assertEqual(by_team(september, 'university')['lines']['training']['orders']['actual'], 1)
        self.assertEqual(by_team(september, 'high')['lines']['training']['orders']['actual'], 1)

    def test_person_order_status_views_preserve_legacy_cash_heads_targets_and_windows(self):
        person = training_person('高中同事', '高中', {
            '2026-09': {'orders': 10, 'cash': 1000},
        })
        people = inputs([], [person])
        abroad = {'people': [{
            'display_name': '高中同事',
            'business_group': '高中',
            'monthly_targets': {'2026-09': {'orders': 4}},
        }]}
        rows = []
        current_statuses = [
            ('正常', 1, True, '市场活动', '讲座'),
            ('死单', 2, True, '渠道合作', '校代'),
            ('删除', 3, False, '网络资源', '搜索'),
            ('回收', 4, False, '官方合作高校', '高校活动'),
            ('无效', 5, True, '学校推荐', '校代'),
        ]
        for line in ('training', 'abroad'):
            for index, (order_status, amount, counts, first, second) in enumerate(current_statuses):
                current = fact(
                    f'{line}-current-{index}', 'orders', line,
                    f'2026-09-{10 + index:02d}', amount,
                    group='高中', owners=['高中同事'], order_status=order_status,
                    counts_toward_completion=counts,
                )
                current.update({'first_channel': first, 'second_channel': second})
                rows.append(current)
                prior = fact(
                    f'{line}-prior-{index}', 'orders', line,
                    f'2025-09-{10 + index:02d}', amount,
                    group='高中', owners=['高中同事'], order_status=order_status,
                    counts_toward_completion=counts,
                )
                prior.update({'first_channel': first, 'second_channel': second})
                rows.append(prior)

            # These rows are inside the natural-calendar window but beyond the
            # 26th-to-25th personal performance window.
            current_late = fact(
                f'{line}-late-current', 'orders', line, '2026-09-27', 9,
                group='高中', owners=['高中同事'], order_status='正常',
            )
            current_late.update({'first_channel': '活动后段', 'second_channel': '校代后段'})
            rows.append(current_late)
            prior_late = fact(
                f'{line}-late-prior', 'orders', line, '2025-09-27', 9,
                group='高中', owners=['高中同事'], order_status='正常',
            )
            prior_late.update({'first_channel': '活动后段', 'second_channel': '校代后段'})
            rows.append(prior_late)

        # Cash remains qualified independently of the linked work-order status.
        rows.extend([
            fact('cash-current-deleted-link', 'cash', 'training', '2026-09-10', 100,
                 group='高中', owners=['高中同事'], student='S-1',
                 order_status='删除', counts_toward_completion=False),
            fact('cash-current-recalled-link', 'cash', 'training', '2026-09-11', 200,
                 group='高中', owners=['高中同事'], student='S-2',
                 order_status='回收', counts_toward_completion=False),
            fact('cash-prior-link', 'cash', 'training', '2025-09-10', 50,
                 group='高中', owners=['高中同事'], student='S-3',
                 order_status='删除', counts_toward_completion=False),
        ])

        result = build(rows, people, through='2026-09-28', abroad=abroad)
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        high = by_team(september, 'high')
        person_row = by_person(high, '高中同事')
        calendar_row = by_person(high['person_calendar'], '高中同事')
        order_fields = {
            'training_target', 'training_actual', 'training_prior', 'training_completion',
            'combined_target', 'combined_actual', 'combined_prior', 'combined_completion',
            'abroad_target', 'abroad_actual', 'abroad_prior', 'abroad_completion',
            'abroad_channels',
        }

        # The existing person fields remain the original notification/base view:
        # delete/recovery are excluded, while the currently counted dead orders remain.
        self.assertEqual(person_row['training_actual'], 8)
        self.assertEqual(person_row['training_prior'], 8)
        self.assertEqual(person_row['training_completion'], 0.8)
        self.assertEqual(person_row['abroad_actual'], 8)
        self.assertIsNone(person_row['abroad_prior'])
        self.assertEqual(person_row['combined_actual'], 16)
        self.assertIsNone(person_row['combined_prior'])
        self.assertIsNone(person_row['combined_completion'])
        self.assertEqual(person_row['cash_actual']['actual'], 300)
        self.assertEqual(person_row['cash_actual']['prior'], 50)
        self.assertEqual(person_row['heads_actual']['actual'], 2)
        self.assertEqual(person_row['heads_actual']['prior'], 1)
        self.assertEqual(person_row['training_target'], 10)
        self.assertEqual(person_row['combined_target'], 10)
        self.assertEqual(set(person_row['order_status_views']), set(ORDER_STATUS_MODES))
        self.assertEqual(DEFAULT_ORDER_STATUS_MODE, '01')
        with self.assertRaisesRegex(ValueError, 'unsupported order status mode'):
            order_status_allowed('死单', '2')

        # The legacy notification/base row still excludes non-completion and
        # delete/recovery orders while retaining currently counted dead orders.
        views = person_row['order_status_views']
        self.assertEqual(views['01']['training_actual'], person_row['training_actual'])
        self.assertEqual(views['01']['training_prior'], person_row['training_prior'])
        self.assertIsNone(views['01']['abroad_prior'])
        for mode in ORDER_STATUS_MODES:
            view = views[mode]
            self.assertEqual(set(view), order_fields)
            self.assertNotIn('cash_actual', view)
            self.assertNotIn('heads_actual', view)
            self.assertEqual(view['training_target'], person_row['training_target'])
            self.assertEqual(view['abroad_target'], person_row['abroad_target'])

        expected_views = {
            '00': (6, {'市场活动': 1, '学校推荐': 5}),
            '01': (8, {'市场活动': 1, '学校推荐': 5, '渠道合作': 2}),
            '10': (13, {'市场活动': 1, '学校推荐': 5, '网络资源': 3, '官方合作高校': 4}),
            '11': (15, {'市场活动': 1, '学校推荐': 5, '渠道合作': 2,
                        '网络资源': 3, '官方合作高校': 4}),
        }
        expected_channel_names = {
            '市场活动': '讲座', '学校推荐': '校代', '渠道合作': '校代',
            '网络资源': '搜索', '官方合作高校': '高校活动',
        }
        for mode in ORDER_STATUS_MODES:
            view = views[mode]
            expected_actual, expected_channels = expected_views[mode]
            self.assertEqual(view['training_actual'], expected_actual)
            self.assertEqual(view['training_prior'], expected_actual)
            self.assertEqual(view['training_completion'], expected_actual / 10)
            self.assertEqual(view['abroad_actual'], expected_actual)
            self.assertIsNone(view['abroad_prior'])
            self.assertIsNone(view['abroad_completion'])
            self.assertEqual(view['combined_actual'], expected_actual * 2)
            self.assertIsNone(view['combined_prior'])
            self.assertIsNone(view['combined_completion'])

            channel_rows = {
                row['first_channel']: row for row in view['abroad_channels']
            }
            self.assertEqual(set(channel_rows), set(expected_channels))
            for first_channel, channel_actual in expected_channels.items():
                channel = channel_rows[first_channel]
                self.assertEqual(channel['name'], expected_channel_names[first_channel])
                self.assertEqual(channel['orders']['actual'], channel_actual)
                self.assertIsNone(channel['orders']['prior'])
                self.assertIsNone(channel['orders']['yoy'])
                self.assertAlmostEqual(channel['share'], channel_actual / expected_actual)
            self.assertAlmostEqual(sum(row['share'] for row in view['abroad_channels']), 1)
            self.assertEqual(sum(row['orders']['actual'] for row in view['abroad_channels']),
                             view['abroad_actual'])
            self.assertIsNone(view['abroad_prior'])

        # Both display windows carry their own order-status projection and the
        # same original window metadata; status choice does not move boundaries.
        self.assertEqual(person_row['order_status_views']['00']['training_actual'], 6)
        self.assertEqual(calendar_row['training_actual'], 17)
        self.assertEqual(high['person_calendar']['person_start'], '2026-09-01')
        self.assertEqual(high['person_calendar']['person_through'], '2026-09-28')
        self.assertEqual(high['person_calendar']['person_progress'], 28 / 30)
        expected_calendar_actuals = {'00': 15, '01': 17, '10': 22, '11': 24}
        for mode, expected_actual in expected_calendar_actuals.items():
            view = calendar_row['order_status_views'][mode]
            self.assertEqual(view['training_actual'], expected_actual)
            self.assertEqual(view['training_prior'], expected_actual)
            self.assertEqual(view['abroad_actual'], expected_actual)

        # Department totals keep all source orders, regardless of the personal selector.
        total = by_team(september, 'total')
        self.assertEqual(total['lines']['training']['orders']['actual'], 24)
        self.assertEqual(high['lines']['training']['orders']['actual'], 24)

    def test_virtual_invalid_order_stays_excluded_across_four_status_views(self):
        people = inputs([], [], virtual=[training_person('虚拟甲', '大学')])
        rows = [
            fact('virtual-invalid', 'orders', 'training', '2026-09-10', 11,
                 group='高中', owners=['高中同事'], virtual_owners=['虚拟甲'],
                 order_status='无效'),
            fact('virtual-deleted', 'orders', 'training', '2026-09-11', 2,
                 group='高中', owners=['高中同事'], virtual_owners=['虚拟甲'],
                 order_status='删除', counts_toward_completion=False),
            fact('virtual-dead', 'orders', 'training', '2026-09-12', 3,
                 group='高中', owners=['高中同事'], virtual_owners=['虚拟甲'],
                 order_status='死单'),
            fact('virtual-recalled', 'orders', 'training', '2026-09-13', 4,
                 group='高中', owners=['高中同事'], virtual_owners=['虚拟甲'],
                 order_status='回收', counts_toward_completion=False),
        ]

        result = build(rows, people, through='2026-09-28', abroad={'people': []})
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        virtual_row = by_person(by_team(september, 'virtual'), '虚拟甲')
        self.assertEqual(virtual_row['training_actual'], 3)
        expected_actuals = {'00': 0, '01': 3, '10': 6, '11': 9}
        for mode, expected_actual in expected_actuals.items():
            self.assertEqual(virtual_row['order_status_views'][mode]['training_actual'],
                             expected_actual)


if __name__ == '__main__':
    unittest.main()
