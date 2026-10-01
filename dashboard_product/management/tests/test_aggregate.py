"""Regression tests for P2 management rollups and source boundaries."""
from __future__ import annotations

import unittest

from dashboard_product.management.aggregate import aggregate


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
         acquisition_mode=None, offline_channel_eligible=False):
    return {
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
        'acquisition_mode': acquisition_mode,
        'offline_channel_eligible': offline_channel_eligible,
    }


def abroad_people():
    return {'people': [{'display_name': '孙伟', 'monthly_targets': {}}]}


def project_targets():
    return {'business_groups': {}}


def offline_targets():
    return {'total': {'work_order_target': 2620, 'months': {'2026-10': 360}}}


def online_targets():
    return {'study_abroad': {'resource_target': {
        'annual': 6715,
        'quarters': {'Q2': 1800},
        'months': {'2026-10': 484},
    }}}


def build(rows, people, *, through='2026-09-28', abroad=None):
    return aggregate(
        rows,
        people,
        abroad or abroad_people(),
        project_targets(),
        offline_targets(),
        online_targets(),
        through,
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
        self.assertEqual(calendar['person_start'], '2026-10-01')
        self.assertIsNone(calendar['person_through'])
        self.assertEqual(calendar['person_progress'], 0)
        self.assertIsNone(calendar_person['training_actual'])
        self.assertEqual(calendar_person['training_target'], 20)

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

    def test_cross_group_order_is_capacity_only_and_heads_use_qualified_owners(self):
        people = inputs(
            [training_person('大学同事', '大学'), training_person('大学同事乙', '大学')],
            [training_person('高中同事', '高中')],
        )
        rows = [
            fact('uni-order', 'orders', 'training', '2026-09-10', 1,
                 group='大学', owners=['大学同事', '高中同事'], campaign='共同活动'),
            fact('cash-one', 'cash', 'training', '2026-09-10', 1000,
                 group='大学', owners=['大学同事', '高中同事'], student='S-1', campaign='共同活动'),
            # Same student, same eligible department; personal and team headcount must dedupe.
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
        self.assertEqual(actual(uni_person['heads_actual']), 1)
        self.assertEqual(actual(high_person['heads_actual']), 0)
        self.assertEqual(actual(high_person['training_actual']), 0)
        self.assertEqual(actual(uni_person['training_actual']), 1)

        capacity = {person['name']: person for person in result['capacity']}
        self.assertEqual(capacity['高中同事']['cross_training_orders'], 1)
        self.assertEqual(capacity['高中同事']['training_destinations'], [{'name': '大学', 'orders': 1}])
        # Shared cash remains the original amount for each owner; only heads split.
        self.assertEqual(capacity['大学同事']['cash'], 2200)
        self.assertEqual(capacity['高中同事']['cash'], 2200)
        self.assertEqual(capacity['大学同事']['heads'], 0.5)
        self.assertEqual(capacity['高中同事']['heads'], 0.5)

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

    def test_activities_use_all_history_and_mark_unconnected_abroad_cash(self):
        people = inputs([], [])
        result = build([
            fact('old-training-order', 'orders', 'training', '2025-04-03', 3,
                 group='大学', campaign='联合活动'),
            fact('old-training-cash', 'cash', 'training', '2025-04-03', 500,
                 group='大学', student='S-2', campaign='联合活动'),
            fact('old-abroad-order', 'orders', 'abroad', '2025-04-04', 1,
                 team='offline_market', owners=['孙伟'], student='S-3', country='英国',
                 business_line_name='英澳条线', campaign='联合活动'),
            fact('old-abroad-only-order', 'orders', 'abroad', '2025-04-05', 2,
                 team=None, owners=[], country='日本', business_line_name='欧亚条线',
                 campaign='留学单线活动'),
        ], people, through='2026-09-28')
        activities = {activity['name']: activity for activity in result['activities']}
        combined = activities['联合活动']
        self.assertEqual(combined['training_orders'], 3)
        self.assertEqual(combined['abroad_orders'], 1)
        self.assertEqual(combined['orders'], 4)
        self.assertEqual(combined['cash'], 500)
        self.assertEqual(combined['heads'], 1)
        self.assertEqual(combined['cash_status'], 'partial')

        abroad_only = activities['留学单线活动']
        self.assertIsNone(abroad_only['cash'])
        self.assertIsNone(abroad_only['heads'])
        self.assertEqual(abroad_only['cash_status'], 'not_connected')


    def test_unknown_group_is_retained_in_total_but_not_platform_kpi(self):
        rows = [fact('unknown', 'orders', 'training', '2026-09-01', 1, team='online_platform')]
        result = build(rows, inputs([], []))
        month = next(p for p in result['periods'] if p['id'] == '2026-09')
        self.assertEqual(by_team(month, 'total')['lines']['training']['orders']['actual'], 1)
        self.assertEqual(by_team(month, 'online')['lines']['training']['orders']['actual'], 0)

    def test_university_ownership_does_not_change_online_acquisition(self):
        rows = [fact('owned-online', 'orders', 'abroad', '2026-09-01', 1,
                     group='大学', owners=['孙伟'], acquisition_mode='online', country='日本',
                     offline_channel_eligible=True)]
        result = build(rows, inputs([], []))
        month = next(p for p in result['periods'] if p['id'] == '2026-09')
        university = by_team(month, 'university')
        self.assertEqual(university['lines']['abroad']['orders']['actual'], 1)
        self.assertEqual(university['countries'][0]['online'], 1)
        self.assertEqual(university['countries'][0]['offline'], 0)
        self.assertEqual(by_team(month, 'online')['lines']['abroad']['orders']['actual'], 0)

    def test_university_rollup_uses_channel_flag_without_roster_or_owner_claim(self):
        rows = [
            fact('unclaimed-offline', 'orders', 'abroad', '2026-09-01', 1,
                 team=None, owners=[], country='英国', acquisition_mode='offline',
                 offline_channel_eligible=True),
            fact('owner-only', 'orders', 'abroad', '2026-09-02', 1,
                 group='大学', owners=['孙伟'], country='日本', acquisition_mode='offline'),
        ]
        result = build(rows, inputs([], []), abroad={'people': []})
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        university = by_team(september, 'university')
        self.assertEqual(university['lines']['abroad']['orders']['actual'], 1)
        self.assertEqual([row['country'] for row in university['countries']], ['英国'])
        self.assertEqual(by_team(september, 'total')['lines']['abroad']['orders']['actual'], 2)

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

    def test_virtual_combined_orders_count_roster_owned_abroad_once_without_new_target(self):
        people = inputs(
            [training_person('大学同事', '大学')], [],
            virtual=[training_person('虚拟甲', '大学'), training_person('虚拟乙', '大学')],
        )
        rows = [
            fact('virtual-training', 'orders', 'training', '2026-09-20', 1,
                 team='online_private', group='大学', owners=['虚拟甲']),
            fact('shared-abroad', 'orders', 'abroad', '2026-09-20', 1,
                 owners=['虚拟甲', '虚拟乙']),
            fact('other-training', 'orders', 'training', '2026-09-20', 1,
                 group='大学', owners=['大学同事']),
            fact('unowned-abroad', 'orders', 'abroad', '2026-09-20', 1,
                 owners=[], offline_channel_eligible=True),
        ]
        result = build(rows, people, abroad={'people': []})
        september = next(period for period in result['periods'] if period['id'] == '2026-09')
        virtual = by_team(september, 'virtual')
        virtual_people = {person['name']: person for person in virtual['people']}
        virtual_calendar = {person['name']: person for person in virtual['person_calendar']['people']}

        self.assertEqual(virtual['lines']['training']['orders']['actual'], 1)
        self.assertEqual(virtual['combined_orders']['actual'], 2)
        self.assertIsNone(virtual['combined_orders']['target'])
        self.assertIn('多人共同工单', virtual['combined_orders']['note'])
        self.assertEqual(virtual_people['虚拟甲']['combined_actual'], 2)
        self.assertIsNone(virtual_people['虚拟甲']['combined_target'])
        self.assertEqual(virtual_people['虚拟乙']['combined_actual'], 1)
        self.assertEqual(virtual_calendar['虚拟甲']['combined_actual'], 2)
        self.assertIsNone(virtual_calendar['虚拟甲']['combined_target'])
        october = next(period for period in result['periods'] if period['id'] == '2026-10')
        self.assertIsNone(by_team(october, 'virtual')['combined_orders']['actual'])
        future_calendar = by_team(october, 'virtual')['person_calendar']
        self.assertIsNone(by_person(future_calendar, '虚拟甲')['combined_actual'])

        # Existing source ownership and totals stay as they were before the virtual rollup.
        self.assertEqual(by_team(september, 'total')['lines']['training']['orders']['actual'], 2)
        self.assertEqual(by_team(september, 'total')['lines']['abroad']['orders']['actual'], 2)
        self.assertEqual(by_team(september, 'university')['lines']['training']['orders']['actual'], 1)
        self.assertEqual(by_team(september, 'university')['lines']['abroad']['orders']['actual'], 1)


if __name__ == '__main__':
    unittest.main()
