from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from dashboard_product.management.aggregate import aggregate
from dashboard_product.management.tests.reference_notifications import build_notifications


def study_coverage(start_date='2026-09-01', through_date='2026-09-30'):
    return {'snapshot_id': 'snapshot_study_fixture', 'source_sha256': 'a' * 64,
            'start_date': start_date, 'through_date': through_date, 'no_yoy': True,
            'cross_system_customers': 'not_aligned'}


def metric(actual=None, target=None):
    return {
        'actual': actual,
        'target': target,
        'completion': actual / target if actual is not None and target else None,
        'status': 'available',
    }


def team(team_id, people=None):
    result = {
        'id': team_id,
        'people': people or [],
        'person_start': '2026-09-26',
        'person_through': '2026-09-28',
        'person_progress': 0.1,
        'lines': {
            'training': {
                'orders': metric(4, 10),
                'cash': metric(1000, 2000),
                'heads': metric(1, None),
            },
            'abroad': {
                'orders': {**metric(2, 5), 'source_coverage': study_coverage()},
                'cash': {**metric(None, None), 'source_coverage': study_coverage()},
                'heads': {**metric(None, None), 'source_coverage': study_coverage()},
                'source_coverage': study_coverage(),
            },
        },
    }
    if team_id == 'virtual':
        result['combined_orders'] = metric(2, 10)
    return result


def order(fid, line, team_id, *, group=None, owners=(), value=1, count=True,
          mode=None, eligible=False, first='市场活动', second='讲座', virtual_owners=()):
    row = {
        'fact_id': fid,
        'metric': 'orders',
        'business_line': line,
        'event_date': '2026-09-28',
        'value': value,
        'work_order_id': fid,
        'team_id': team_id,
        'business_group': group,
        'owners': list(owners),
        'virtual_owners': list(virtual_owners),
        'first_channel': first,
        'second_channel': second,
        'acquisition_mode': mode,
        'offline_channel_eligible': eligible,
        'counts_toward_completion': count,
        'exclusion_reason': None if count else '工单已回收',
        'order_status': '正常' if count else '已回收',
        'source_record': {'ID': fid, '团队': team_id},
    }
    if line == 'abroad':
        row.update({
            'segment_id': ('study_abroad_online' if team_id == 'online_platform' else
                           'study_abroad_offline' if team_id == 'offline_market' and eligible else
                           'unassigned'),
            'source_product': 'study_abroad',
            'customer_domain': 'study_abroad',
            'source_kind': 'study_abroad_warehouse',
        })
    return row


def cash(fid, line, team_id, value, *, owners=(), student='S-1', segment_id=None,
         customer_domain='study_abroad', source_product=None):
    row = {
        'fact_id': fid,
        'metric': 'cash',
        'business_line': line,
        'event_date': '2026-09-28',
        'value': value,
        'work_order_id': fid,
        'team_id': team_id,
        'business_group': None,
        'owners': list(owners),
        'student_id': student,
        'order_status': '删除',
        'counts_toward_completion': False,
    }
    if line == 'abroad':
        row.update({
            'segment_id': segment_id or (
                'study_abroad_online' if team_id == 'online_platform' else
                'study_abroad_offline' if team_id == 'offline_market' else 'unassigned'
            ),
            'source_product': source_product or customer_domain,
            'customer_domain': customer_domain,
            'source_kind': 'study_abroad_warehouse',
        })
    return row


def public_aggregate(facts, people, abroad_people, through):
    source = study_coverage()
    result = aggregate(facts, people, abroad_people, {}, {}, {}, through,
                       abroad_source=source)
    result['metadata'] = {
        'data_through': through.isoformat() if isinstance(through, date) else str(through),
        'study_abroad_source': source,
    }
    return result


class ManagementNotificationsTest(unittest.TestCase):
    def setUp(self):
        uni_person = {
            'name': '大学同事',
            'home_group': '大学',
            'business_line': 'training+abroad',
            'training_target': 10,
            'training_actual': 4,
            'training_completion': 0.4,
            'abroad_target': 1,
            'abroad_actual': 0,
            'abroad_completion': 0,
            'cash_actual': metric(1000, 2000),
            'heads_actual': metric(1, None),
        }
        abroad_person = {
            'name': '留学同事',
            'home_group': '大学',
            'business_line': 'abroad',
            'training_target': 2,
            'training_actual': 0,
            'training_completion': 0,
            'abroad_target': 20,
            'abroad_actual': 1,
            'abroad_completion': 0.05,
            'cash_actual': metric(None, None),
            'heads_actual': metric(None, None),
        }
        high_abroad_person = {
            'name': '马玥',
            'home_group': '高中',
            'business_line': 'abroad',
            'training_target': None,
            'training_actual': 0,
            'training_completion': None,
            'abroad_target': None,
            'abroad_actual': 1.5,
            'abroad_completion': None,
            'cash_actual': metric(None, None),
            'heads_actual': metric(None, None),
        }
        virtual_people = [
            {
                'name': '虚拟甲', 'home_group': '大学', 'business_line': 'training',
                'training_target': 10, 'training_actual': 1, 'training_completion': 0.1,
                'abroad_target': 1, 'abroad_actual': 1, 'abroad_completion': 1,
                'combined_target': 10, 'combined_actual': 2, 'combined_prior': 0,
                'combined_completion': 0.2,
                'cash_actual': metric(700, 1000), 'heads_actual': metric(1, None),
            },
            {
                'name': '虚拟乙', 'home_group': '大学', 'business_line': 'training',
                'training_target': 5, 'training_actual': 0, 'training_completion': 0,
                'abroad_target': 1, 'abroad_actual': 1, 'abroad_completion': 1,
                'combined_target': 5, 'combined_actual': 1, 'combined_prior': 0,
                'combined_completion': 0.2,
                'cash_actual': metric(0, 0), 'heads_actual': metric(0, None),
            },
        ]
        uni_people = [uni_person, abroad_person]
        teams_sep = [team(team_id, uni_people if team_id == 'university' else
                          (virtual_people if team_id == 'virtual' else
                           ([high_abroad_person] if team_id == 'high' else [])))
                     for team_id in ('prep', 'high', 'university', 'virtual', 'online')]
        teams_oct = [team(team_id, uni_people if team_id == 'university' else
                          (virtual_people if team_id == 'virtual' else
                           ([high_abroad_person] if team_id == 'high' else [])))
                     for team_id in ('prep', 'high', 'university', 'virtual', 'online')]
        self.public = {
            'metadata': {
                'data_through': '2026-09-28',
                'study_abroad_source': study_coverage(),
            },
            'periods': [
                {'id': '2026-09', 'start_date': '2026-09-01', 'through_date': '2026-09-28',
                 'time_progress': 28 / 30, 'teams': teams_sep},
                {'id': '2026-10', 'start_date': '2026-10-01', 'through_date': None,
                 'time_progress': 0, 'teams': teams_oct},
            ],
        }
        self.people = {
            'teams': [
                {
                    'team_id': 'offline_market',
                    'groups': [{
                        'display_name': '大学组',
                        'members': [{
                            'display_name': '大学同事',
                            'status': 'active',
                            'business_group': '大学',
                            'monthly_targets': {'2026-10': {'orders': 10, 'heads': 4}},
                        }],
                    }],
                },
                {
                    'team_id': 'online_private',
                    'groups': [{
                        'display_name': '大学组',
                        'members': [
                            {'display_name': '虚拟甲', 'status': 'active', 'business_group': '大学',
                             'monthly_targets': {'2026-10': {'orders': 10, 'heads': 2}}},
                            {'display_name': '虚拟乙', 'status': 'active', 'business_group': '大学',
                             'monthly_targets': {'2026-10': {'orders': 5, 'heads': 1}}},
                        ],
                    }],
                },
            ],
        }
        self.abroad_people = {'people': [
            {
                'display_name': '留学同事',
                'business_group': '大学',
                'monthly_targets': {'2026-10': {'orders': 20}},
            },
            {'display_name': '马玥', 'business_group': '高中'},
        ]}
        self.facts = [
            order('train-included', 'training', 'offline_market', group='大学',
                  owners=['大学同事'], second='线上讲座'),
            order('train-recycled', 'training', 'offline_market', group='大学',
                  owners=['大学同事'], count=False, second='回收渠道'),
            order('abroad-included', 'abroad', 'offline_market', owners=['大学同事'],
                  mode='offline', eligible=True, second='官方合作高校'),
            order('abroad-personal-only', 'abroad', 'online_platform', owners=['留学同事'],
                  mode='online', second='网络资源'),
            order('high-abroad-cocreate', 'abroad', 'offline_market', owners=['马玥', '留学同事'],
                  mode='offline', eligible=True, second='合作院校'),
            order('high-abroad-own', 'abroad', 'offline_market', owners=['马玥'],
                  mode='offline', eligible=True, second='转介绍'),
            order('online-included', 'abroad', 'online_platform', mode='online',
                  second='网络资源'),
            order('virtual-training', 'training', 'online_private', group='大学',
                  owners=['虚拟甲'], virtual_owners=['虚拟甲'], second='虚拟人'),
            order('virtual-extra', 'training', 'online_private', group='大学',
                  owners=['虚拟乙'], second='共同讲座', virtual_owners=['虚拟乙']),
        ]
        deleted = order('virtual-deleted', 'training', 'online_private', group='大学',
                        owners=['虚拟甲'], value=5, count=False, second='删除工单',
                        virtual_owners=['虚拟甲'])
        deleted['order_status'] = '删除'
        deleted['exclusion_reason'] = '工单已删除'
        self.facts.append(deleted)

    def test_eight_channels_include_high_school_abroad_personal_digest(self):
        result = build_notifications(self.public, self.facts, self.people, self.abroad_people)

        self.assertEqual(result['schema_version'], 'management_notifications.v1')
        self.assertEqual(result['data_through'], '2026-09-28')
        self.assertEqual(len(result['messages']), 8)
        university_training = next(row for row in result['messages']
                                   if row['id'] == 'university.training')
        university_abroad = next(row for row in result['messages']
                                 if row['id'] == 'university.abroad')
        self.assertEqual(university_training['channel_id'], 'offline_university')
        self.assertEqual(university_abroad['channel_id'], 'offline_university')
        high_training = next(row for row in result['messages'] if row['id'] == 'high.training')
        high_abroad = next(row for row in result['messages'] if row['id'] == 'high.abroad')
        self.assertEqual(high_training['channel_id'], 'offline_high_school')
        self.assertEqual(high_abroad['channel_id'], 'offline_high_school')
        self.assertEqual(high_abroad['title'], '高中留学')
        self.assertTrue(high_abroad['personal_only'])
        self.assertEqual(high_abroad['team_metrics'], {})
        self.assertEqual(high_abroad['ledgers']['team_orders'], [])
        self.assertEqual(high_abroad['ledgers']['team_cash'], [])
        self.assertEqual(university_training['month'], '2026-09')
        self.assertEqual(university_training['window']['person_month'], '2026-10')
        self.assertEqual([person['name'] for person in university_training['people']], ['大学同事'])
        self.assertEqual([person['name'] for person in university_abroad['people']], ['留学同事'])
        self.assertEqual([person['name'] for person in high_abroad['people']], ['马玥'])
        self.assertNotIn('马玥', [person['name'] for person in high_training['people']])
        self.assertEqual(high_abroad['people'][0]['orders_target'], None)
        self.assertEqual(high_abroad['people'][0]['orders_actual'], 1.5)
        self.assertEqual(high_abroad['window']['person_month'], '2026-10')

        channels = {row['name']: row for row in high_abroad['channels']}
        self.assertEqual(channels['合作院校']['month'], 0.5)
        self.assertEqual(channels['合作院校']['today'], 0.5)
        self.assertAlmostEqual(channels['合作院校']['share'], 1 / 3)
        self.assertEqual(channels['转介绍']['month'], 1)
        self.assertAlmostEqual(channels['转介绍']['share'], 2 / 3)
        personal_ledger = {row['fact_id']: row for row in high_abroad['ledgers']['personal_orders']}
        self.assertEqual(personal_ledger['high-abroad-cocreate']['value'], 1)
        self.assertEqual(personal_ledger['high-abroad-cocreate']['person_credits']['马玥'],
                         {'weight': 0.5, 'value': 0.5})
        self.assertEqual(set(personal_ledger), {'high-abroad-cocreate', 'high-abroad-own'})

    def test_person_targets_daily_counts_and_excluded_order_evidence(self):
        result = build_notifications(self.public, self.facts, self.people, self.abroad_people)
        training = next(row for row in result['messages'] if row['id'] == 'university.training')
        abroad = next(row for row in result['messages'] if row['id'] == 'university.abroad')
        person = training['people'][0]
        abroad_person = abroad['people'][0]

        self.assertEqual(person['orders_target'], 10)
        self.assertEqual(person['heads_target'], 4)
        self.assertEqual(person['heads_completion'], 0.25)
        self.assertEqual(person['secondary_business_line'], 'abroad')
        self.assertEqual(person['secondary_orders_target'], 1)
        self.assertFalse(person['behind'])
        # The reciprocal 10% line stays visible but does not drive lag status.
        self.assertTrue(abroad_person['behind'])
        self.assertEqual(person['today_orders'], 1)
        self.assertEqual(person['expected_orders'], 1)
        self.assertEqual(person['orders_gap'], 3)
        self.assertEqual(person['remaining_workdays'], 19)
        self.assertEqual(person['daily_orders'], 6 / 19)
        self.assertEqual(training['team_metrics']['orders']['daily_actual'], 2)
        self.assertEqual(training['team_metrics']['orders']['daily_average'], 4 / 28)
        self.assertTrue(training['team_metrics']['orders']['behind'])
        self.assertEqual(person['orders_actual'], 4)
        self.assertEqual(training['team_metrics']['orders']['actual'], 4)

        all_orders = training['ledgers']['team_orders']
        recycled = next(row for row in all_orders if row['fact_id'] == 'train-recycled')
        self.assertEqual(recycled['counts_toward_completion'], False)
        self.assertEqual(recycled['exclusion_reason'], '工单已回收')
        self.assertEqual(recycled['source_record'], {'ID': 'train-recycled', '团队': 'offline_market'})
        self.assertEqual(sum(row['month'] for row in training['channels']), 2)
        self.assertEqual(sum(row['today'] for row in training['channels']), 2)
        abroad_personal_ids = [row['fact_id'] for row in abroad['ledgers']['personal_orders']]
        abroad_team_ids = [row['fact_id'] for row in abroad['ledgers']['team_orders']]
        self.assertIn('abroad-personal-only', abroad_personal_ids)
        self.assertNotIn('abroad-personal-only', abroad_team_ids)

    def test_online_has_no_individual_roster(self):
        result = build_notifications(self.public, self.facts, self.people, self.abroad_people)
        online_training = next(row for row in result['messages'] if row['id'] == 'online.training')
        online_abroad = next(row for row in result['messages'] if row['id'] == 'online.abroad')

        self.assertEqual(online_training['channel_id'], 'online_platform')
        self.assertEqual(online_abroad['channel_id'], 'online_platform')
        self.assertEqual(online_training['people'], [])
        self.assertEqual(online_abroad['people'], [])
        self.assertEqual(
            {row['fact_id'] for row in online_abroad['ledgers']['team_orders']},
            {'abroad-personal-only', 'online-included'},
        )

    def test_abroad_notification_cash_uses_the_isolated_source_and_ledgers(self):
        facts = [
            order('study-order', 'abroad', 'offline_market', owners=['留学同事'],
                  eligible=True, second='合作院校'),
            cash('study-cash', 'abroad', 'offline_market', 320,
                 owners=['留学同事'], student='study-customer'),
        ]
        public = public_aggregate(facts, self.people, self.abroad_people, date(2026, 9, 28))
        result = build_notifications(public, facts, self.people, self.abroad_people)
        abroad = next(row for row in result['messages'] if row['id'] == 'university.abroad')
        person = next(row for row in abroad['people'] if row['name'] == '留学同事')

        self.assertEqual(abroad['source_coverage'], study_coverage())
        self.assertEqual(abroad['team_metrics']['cash']['actual'], 320)
        self.assertEqual(abroad['team_metrics']['heads']['actual'], 1)
        self.assertEqual([row['fact_id'] for row in abroad['ledgers']['team_cash']], ['study-cash'])
        self.assertEqual([row['fact_id'] for row in abroad['ledgers']['personal_cash']], ['study-cash'])
        self.assertEqual(person['cash_actual']['actual'], 320)
        self.assertEqual(person['cash_actual']['status'], 'available')

    def test_unassigned_cash_uses_personal_window_without_changing_cash_totals(self):
        personal = cash('cash-personal', 'training', 'offline_market', 100,
                        owners=['大学同事'])
        unmatched = cash('cash-unmatched', 'training', 'offline_market', 40, owners=[])
        other_person = cash('cash-other-person', 'training', 'offline_market', 60,
                            owners=['留学同事'])
        inferred = cash('cash-inferred', 'training', 'offline_market', 80,
                        owners=['大学同事'])
        outside_performance_window = cash(
            'cash-natural-only', 'training', 'offline_market', 30, owners=[],
        )
        for fact in (personal, unmatched, other_person, inferred, outside_performance_window):
            fact['business_group'] = '大学'
            fact['event_date'] = '2026-09-27'
        inferred['team_inferred'] = True
        outside_performance_window['event_date'] = '2026-09-25'
        facts = [personal, unmatched, other_person, inferred, outside_performance_window]
        public = public_aggregate(facts, self.people, self.abroad_people, date(2026, 9, 28))

        result = build_notifications(public, facts, self.people, self.abroad_people)
        message = next(row for row in result['messages'] if row['id'] == 'university.training')
        person = next(row for row in message['people'] if row['name'] == '大学同事')
        unassigned = {row['fact_id']: row for row in message['ledgers']['unassigned_cash']}

        self.assertEqual(set(unassigned), {
            'cash-unmatched', 'cash-other-person', 'cash-inferred',
        })
        self.assertEqual(unassigned['cash-unmatched']['attribution_reason'], '未匹配当前人员')
        self.assertEqual(unassigned['cash-other-person']['attribution_reason'],
                         '归属人员不在本消息考核名单')
        self.assertEqual(unassigned['cash-inferred']['attribution_reason'], '团队归属由渠道推断')
        self.assertEqual([row['fact_id'] for row in message['ledgers']['personal_cash']],
                         ['cash-personal'])
        self.assertEqual(person['cash_actual']['actual'], 100)
        self.assertEqual(message['team_metrics']['cash']['actual'], 310)

    def test_zero_weight_cash_is_not_returned_as_personal(self):
        fact = cash('cash-zero-weight', 'training', 'offline_market', 100,
                    owners=['大学同事'])
        fact['business_group'] = '大学'
        public = public_aggregate([fact], self.people, self.abroad_people, date(2026, 9, 28))

        with patch('dashboard_product.management.tests.reference_notifications._aggregate._personal_weights',
                   return_value={'大学同事': Decimal('0')}):
            result = build_notifications(public, [fact], self.people, self.abroad_people)
        message = next(row for row in result['messages'] if row['id'] == 'university.training')

        self.assertEqual(message['ledgers']['personal_cash'], [])
        self.assertEqual([row['fact_id'] for row in message['ledgers']['unassigned_cash']],
                         ['cash-zero-weight'])

    def test_abroad_notification_daily_values_are_unknown_outside_source_coverage(self):
        facts = [order('september-order', 'abroad', 'online_platform',
                       owners=['留学同事'], second='网络资源')]
        public = public_aggregate(facts, self.people, self.abroad_people, date(2026, 10, 10))
        result = build_notifications(public, facts, self.people, self.abroad_people)
        online = next(row for row in result['messages'] if row['id'] == 'online.abroad')
        university = next(row for row in result['messages'] if row['id'] == 'university.abroad')
        person = next(row for row in university['people'] if row['name'] == '留学同事')

        self.assertEqual(online['source_coverage'], study_coverage())
        self.assertIsNone(online['team_metrics']['orders']['daily_actual'])
        self.assertIsNone(person['today_orders'])

    def test_partial_abroad_personal_window_does_not_infer_performance_gap(self):
        abroad_people = {'people': [{
            'display_name': '留学同事', 'business_group': '大学', 'status': 'active',
            'monthly_targets': {'2026-10': {'orders': 10, 'cash': 1000}},
        }]}
        facts = [order('known-september-order', 'abroad', 'offline_market',
                       owners=['留学同事'], eligible=True),
                 cash('known-september-cash', 'abroad', 'offline_market', 320,
                      owners=['留学同事'])]
        public = public_aggregate(facts, self.people, abroad_people, date(2026, 10, 2))
        result = build_notifications(public, facts, self.people, abroad_people)
        message = next(row for row in result['messages'] if row['id'] == 'university.abroad')
        person = next(row for row in message['people'] if row['name'] == '留学同事')
        self.assertEqual(person['orders_actual'], 1)
        self.assertEqual(person['cash_actual']['actual'], 320)
        self.assertEqual(person['cash_actual']['status'], 'partial')
        for field in ('orders_completion', 'expected_orders', 'orders_gap',
                      'remaining_orders', 'daily_orders', 'behind', 'today_orders'):
            self.assertIsNone(person[field], field)

    def test_virtual_notification_keeps_training_ledger_and_deleted_order_evidence(self):
        result = build_notifications(self.public, self.facts, self.people, self.abroad_people)
        virtual = next(row for row in result['messages'] if row['id'] == 'virtual.mixed')
        by_name = {row['name']: row for row in virtual['people']}

        self.assertEqual(virtual['channel_id'], 'online_private')
        self.assertEqual(virtual['title'], '线上虚拟人')
        self.assertEqual(virtual['business_line'], 'mixed')
        self.assertEqual(virtual['team_metrics']['orders']['actual'], 2)
        self.assertEqual(virtual['team_metrics']['orders']['daily_actual'], 7)
        self.assertEqual(sum(row['month'] for row in virtual['channels']), 7)
        self.assertEqual(sum(row['today'] for row in virtual['channels']), 7)
        self.assertEqual(by_name['虚拟甲']['orders_actual'], 2)
        self.assertEqual(by_name['虚拟甲']['orders_target'], 10)
        self.assertEqual(by_name['虚拟甲']['today_orders'], 1)
        self.assertEqual(by_name['虚拟甲']['expected_orders'], 1)
        self.assertEqual(by_name['虚拟甲']['daily_orders'], 8 / 19)
        self.assertNotIn('secondary_business_line', by_name['虚拟甲'])
        self.assertEqual(by_name['虚拟甲']['heads_target'], 2)
        self.assertEqual(by_name['虚拟甲']['heads_actual']['actual'], 1)
        self.assertEqual(by_name['虚拟乙']['orders_actual'], 1)
        self.assertEqual(by_name['虚拟乙']['today_orders'], 1)

        team_ids = [row['fact_id'] for row in virtual['ledgers']['team_orders']]
        self.assertCountEqual(team_ids, ['virtual-training', 'virtual-extra', 'virtual-deleted'])
        included_ids = {row['fact_id'] for row in virtual['ledgers']['team_orders']
                        if row['counts_toward_completion']}
        self.assertEqual(included_ids, {'virtual-training', 'virtual-extra'})
        deleted_row = next(row for row in virtual['ledgers']['team_orders']
                           if row['fact_id'] == 'virtual-deleted')
        self.assertEqual(deleted_row['order_status'], '删除')
        self.assertEqual(deleted_row['exclusion_reason'], '工单已删除')
        self.assertCountEqual(
            [row['fact_id'] for row in virtual['ledgers']['personal_orders']],
            ['virtual-training', 'virtual-extra', 'virtual-deleted'],
        )
        personal_by_id = {row['fact_id']: row for row in virtual['ledgers']['personal_orders']}
        self.assertEqual(personal_by_id['virtual-extra']['owners'], ['虚拟乙'])
        self.assertEqual(personal_by_id['virtual-deleted']['owners'], ['虚拟甲'])
        team_by_id = {row['fact_id']: row for row in virtual['ledgers']['team_orders']}
        self.assertEqual(team_by_id['virtual-extra']['owners'], ['虚拟乙'])
        self.assertTrue(all('virtual_owners' not in fact for ledger in virtual['ledgers'].values()
                            for fact in ledger))
        self.assertEqual(virtual['ledgers']['personal_secondary_orders'], [])

    def test_virtual_notification_personal_ledger_matches_cross_scope_completion(self):
        people = {**self.people, 'teams': [*self.people['teams'], {
            'team_id': 'offline_market',
            'groups': [{'display_name': '高中组', 'members': [{
                'display_name': '高中同事', 'status': 'active', 'business_group': '高中',
                'monthly_targets': {'2026-09': {'orders': 10, 'cash': 1000}},
            }]}],
        }]}
        facts = [
            order('cross-training', 'training', 'offline_market', group='高中',
                  owners=['高中同事'], virtual_owners=['虚拟甲']),
            order('invalid-training', 'training', 'offline_market', group='高中',
                  owners=['高中同事'], virtual_owners=['虚拟甲']),
            order('cross-abroad', 'abroad', 'online_platform', owners=['留学同事'],
                  mode='online', first='网络资源', second='搜索'),
            {
                'fact_id': 'cross-cash', 'metric': 'cash', 'business_line': 'training',
                'event_date': '2026-09-28', 'value': 600, 'work_order_id': 'cash-order',
                'team_id': 'offline_market', 'business_group': '高中',
                'owners': ['高中同事'], 'virtual_owners': ['虚拟甲'],
                'team_inferred': True, 'order_status': '删除',
                'counts_toward_completion': True, 'first_channel': '市场活动',
                'second_channel': '校区活动', 'source_record': {'ID': 'cash-order'},
            },
        ]
        facts[1]['order_status'] = '无效'
        public = public_aggregate(facts, people, self.abroad_people, date(2026, 9, 28))

        result = build_notifications(public, facts, people, self.abroad_people)
        virtual = next(row for row in result['messages'] if row['id'] == 'virtual.mixed')
        high = next(row for row in result['messages'] if row['id'] == 'high.training')
        online_abroad = next(row for row in result['messages'] if row['id'] == 'online.abroad')
        by_name = {row['name']: row for row in virtual['people']}
        personal_order_ids = [row['fact_id'] for row in virtual['ledgers']['personal_orders']]
        team_order_ids = [row['fact_id'] for row in virtual['ledgers']['team_orders']]
        personal_cash_ids = [row['fact_id'] for row in virtual['ledgers']['personal_cash']]
        virtual_personal_by_id = {
            row['fact_id']: row for row in virtual['ledgers']['personal_orders']
        }

        self.assertEqual(by_name['虚拟甲']['orders_actual'], 1)
        self.assertEqual(by_name['虚拟甲']['today_orders'], 1)
        self.assertCountEqual(personal_order_ids, ['cross-training'])
        self.assertEqual(team_order_ids, [])
        self.assertEqual(virtual_personal_by_id['cross-training']['owners'], ['虚拟甲'])
        self.assertNotIn('cross-abroad', virtual_personal_by_id)
        self.assertEqual(personal_cash_ids, ['cross-cash'])
        self.assertEqual(virtual['ledgers']['personal_cash'][0]['owners'], ['虚拟甲'])

        high_personal = {row['fact_id']: row for row in high['ledgers']['personal_orders']}
        high_team = {row['fact_id']: row for row in high['ledgers']['team_orders']}
        self.assertEqual(high_personal['cross-training']['owners'], ['高中同事'])
        self.assertEqual(high_team['cross-training']['owners'], ['高中同事'])
        self.assertEqual(high['ledgers']['team_cash'][0]['owners'], ['高中同事'])
        self.assertEqual(online_abroad['ledgers']['team_orders'][0]['owners'], ['留学同事'])
        self.assertEqual(facts[0]['owners'], ['高中同事'])
        self.assertEqual(facts[0]['virtual_owners'], ['虚拟甲'])
        self.assertEqual(facts[3]['owners'], ['高中同事'])
        self.assertEqual(facts[3]['virtual_owners'], ['虚拟甲'])
        self.assertTrue(all('virtual_owners' not in fact
                            for message in result['messages']
                            for ledger in message['ledgers'].values()
                            for fact in ledger))

    def test_personal_notifications_show_weighted_shared_credits_and_raw_values(self):
        people = {
            'teams': [
                {'team_id': 'offline_market', 'groups': [{
                    'display_name': '大学组',
                    'members': [
                        {'display_name': '共创甲', 'status': 'active', 'business_group': '大学'},
                        {'display_name': '共创乙', 'status': 'active', 'business_group': '大学'},
                    ],
                }]},
                {'team_id': 'online_private', 'groups': [{
                    'display_name': '大学组',
                    'members': [
                        {'display_name': '虚拟甲', 'status': 'active', 'business_group': '大学'},
                    ],
                }]},
            ],
        }
        facts = [
            order('shared-order', 'training', 'offline_market', group='大学',
                  owners=['共创甲', '共创乙'], virtual_owners=['虚拟甲'],
                  value=1, second='共同讲座'),
            {
                'fact_id': 'shared-cash', 'metric': 'cash', 'business_line': 'training',
                'event_date': '2026-09-28', 'value': 100, 'work_order_id': 'shared-order',
                'team_id': 'offline_market', 'business_group': '大学',
                'owners': ['共创甲', '共创乙'], 'virtual_owners': ['虚拟甲'],
                'student_id': 'S-1', 'first_channel': '市场活动', 'second_channel': '共同讲座',
                'team_inferred': False, 'counts_toward_completion': True,
            },
        ]
        public = public_aggregate(facts, people, {'people': []}, date(2026, 9, 28))

        result = build_notifications(public, facts, people, {'people': []})
        university = next(row for row in result['messages'] if row['id'] == 'university.training')
        virtual = next(row for row in result['messages'] if row['id'] == 'virtual.mixed')
        university_people = {row['name']: row for row in university['people']}
        virtual_people = {row['name']: row for row in virtual['people']}

        self.assertEqual(university_people['共创甲']['orders_actual'], 0.5)
        self.assertEqual(university_people['共创乙']['orders_actual'], 0.5)
        self.assertEqual(university_people['共创甲']['today_orders'], 0.5)
        self.assertEqual(university_people['共创乙']['today_orders'], 0.5)
        self.assertEqual(virtual_people['虚拟甲']['orders_actual'], 1)
        self.assertEqual(virtual_people['虚拟甲']['today_orders'], 1)

        offline_order = university['ledgers']['personal_orders'][0]
        self.assertEqual(offline_order['value'], 1)
        self.assertEqual(offline_order['person_credits'], {
            '共创甲': {'weight': 0.5, 'value': 0.5},
            '共创乙': {'weight': 0.5, 'value': 0.5},
        })
        self.assertNotIn('person_credits', university['ledgers']['team_orders'][0])

        offline_cash = university['ledgers']['personal_cash'][0]
        self.assertEqual(offline_cash['value'], 100)
        self.assertEqual(offline_cash['person_credits'], {
            '共创甲': {'weight': 0.5, 'value': 50},
            '共创乙': {'weight': 0.5, 'value': 50},
        })
        self.assertEqual(virtual['ledgers']['personal_orders'][0]['person_credits'], {
            '虚拟甲': {'weight': 1, 'value': 1},
        })
        self.assertEqual(virtual['ledgers']['personal_cash'][0]['person_credits'], {
            '虚拟甲': {'weight': 1, 'value': 100},
        })
        self.assertEqual(facts[0]['value'], 1)
        self.assertEqual(facts[1]['value'], 100)
        self.assertNotIn('person_credits', facts[0])
        self.assertNotIn('person_credits', facts[1])

    def test_person_credits_omit_other_home_group_but_keep_it_in_weight_denominator(self):
        people = {'teams': [{
            'team_id': 'offline_market',
            'groups': [
                {'display_name': '大学组', 'members': [
                    {'display_name': '大学甲', 'status': 'active', 'business_group': '大学'},
                ]},
                {'display_name': '高中组', 'members': [
                    {'display_name': '高中乙', 'status': 'active', 'business_group': '高中'},
                ]},
            ],
        }]}
        facts = [order(
            'cross-group-order', 'training', 'offline_market', group='大学',
            owners=['大学甲', '高中乙'], value=1,
        )]
        public = public_aggregate(facts, people, {'people': []}, date(2026, 9, 28))

        result = build_notifications(public, facts, people, {'people': []})
        university = next(row for row in result['messages'] if row['id'] == 'university.training')
        person = next(row for row in university['people'] if row['name'] == '大学甲')
        ledger = university['ledgers']['personal_orders'][0]

        self.assertEqual(person['orders_actual'], 0.5)
        self.assertEqual(person['today_orders'], 0.5)
        self.assertEqual(ledger['value'], 1)
        self.assertEqual(ledger['person_credits'], {
            '大学甲': {'weight': 0.5, 'value': 0.5},
        })

    def test_three_person_cash_credits_round_after_the_rows_are_summed(self):
        people = {'teams': [{
            'team_id': 'offline_market',
            'groups': [{'display_name': '大学组', 'members': [
                {'display_name': name, 'status': 'active', 'business_group': '大学'}
                for name in ('现金甲', '现金乙', '现金丙')
            ]}],
        }]}
        owners = ['现金甲', '现金乙', '现金丙']
        facts = [
            {
                'fact_id': f'cash-{i}', 'metric': 'cash', 'business_line': 'training',
                'event_date': '2026-09-28', 'value': 1, 'work_order_id': f'order-{i}',
                'team_id': 'offline_market', 'business_group': '大学',
                'owners': owners, 'virtual_owners': [], 'student_id': f'S-{i}',
                'first_channel': '市场活动', 'second_channel': '共同讲座',
                'team_inferred': False, 'counts_toward_completion': True,
            }
            for i in range(1, 4)
        ]
        public = public_aggregate(facts, people, {'people': []}, date(2026, 9, 28))

        result = build_notifications(public, facts, people, {'people': []})
        university = next(row for row in result['messages'] if row['id'] == 'university.training')
        people_rows = {row['name']: row for row in university['people']}
        ledger = university['ledgers']['personal_cash']

        self.assertEqual(len(ledger), 3)
        self.assertEqual([row['value'] for row in ledger], [1, 1, 1])
        for name in owners:
            self.assertEqual(people_rows[name]['cash_actual']['actual'], 1)
            raw_credits = [row['person_credits'][name]['value'] for row in ledger]
            self.assertTrue(all(value != 0.33 for value in raw_credits))
            total = Decimal(str(sum(raw_credits))).quantize(Decimal('0.01'))
            self.assertEqual(total, Decimal('1.00'))


    def test_platforms_merge_same_secondary_channel_and_include_deleted_for_team(self):
        from datetime import date
        from dashboard_product.management.tests.reference_notifications import _channels
        rows = [
            {'first_channel': '平台', 'second_channel': '小红书', 'event_date': '2026-09-27', 'value': 2},
            {'first_channel': 'TMK激活-平台', 'second_channel': '小红书', 'event_date': '2026-09-28', 'value': 1},
            {'first_channel': '平台', 'second_channel': '大众点评', 'event_date': '2026-09-28', 'value': 1},
            {'first_channel': '平台', 'second_channel': '小红书', 'event_date': '2026-09-28', 'value': 10,
             'counts_toward_completion': False},
        ]
        channels = _channels(rows, date(2026, 9, 28))
        self.assertEqual(channels, [
            {'name': '小红书', 'month': 13, 'today': 11, 'share': 13 / 14},
            {'name': '大众点评', 'month': 1, 'today': 1, 'share': 1 / 14},
        ])


if __name__ == '__main__':
    unittest.main()
