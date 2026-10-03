from __future__ import annotations

import unittest

from dashboard_product.management.notifications import build_notifications


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
                'orders': metric(2, 5),
                'cash': metric(None, None),
                'heads': metric(None, None),
            },
        },
    }
    if team_id == 'virtual':
        result['combined_orders'] = metric(2, 10)
    return result


def order(fid, line, team_id, *, group=None, owners=(), value=1, count=True,
          mode=None, eligible=False, first='市场活动', second='讲座'):
    return {
        'fact_id': fid,
        'metric': 'orders',
        'business_line': line,
        'event_date': '2026-09-28',
        'value': value,
        'work_order_id': fid,
        'team_id': team_id,
        'business_group': group,
        'owners': list(owners),
        'first_channel': first,
        'second_channel': second,
        'acquisition_mode': mode,
        'offline_channel_eligible': eligible,
        'counts_toward_completion': count,
        'exclusion_reason': None if count else '工单已回收',
        'order_status': '正常' if count else '已回收',
        'source_record': {'ID': fid, '团队': team_id},
    }


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
                          (virtual_people if team_id == 'virtual' else []))
                     for team_id in ('prep', 'high', 'university', 'virtual', 'online')]
        teams_oct = [team(team_id, uni_people if team_id == 'university' else
                          (virtual_people if team_id == 'virtual' else []))
                     for team_id in ('prep', 'high', 'university', 'virtual', 'online')]
        self.public = {
            'metadata': {'data_through': '2026-09-28'},
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
        self.abroad_people = {'people': [{
            'display_name': '留学同事',
            'monthly_targets': {'2026-10': {'orders': 20}},
        }]}
        self.facts = [
            order('train-included', 'training', 'offline_market', group='大学',
                  owners=['大学同事'], second='线上讲座'),
            order('train-recycled', 'training', 'offline_market', group='大学',
                  owners=['大学同事'], count=False, second='回收渠道'),
            order('abroad-included', 'abroad', 'offline_market', owners=['大学同事'],
                  mode='offline', eligible=True, second='官方合作高校'),
            order('abroad-personal-only', 'abroad', 'online_platform', owners=['留学同事'],
                  mode='online', second='网络资源'),
            order('online-included', 'abroad', 'online_platform', mode='online',
                  second='网络资源'),
            order('virtual-training', 'training', 'online_private', group='大学',
                  owners=['虚拟甲'], second='虚拟人'),
            order('virtual-abroad', 'abroad', 'offline_market', owners=['虚拟甲', '虚拟乙'],
                  mode='online', second='留学工单'),
        ]
        deleted = order('virtual-deleted', 'abroad', 'offline_market', owners=['虚拟甲'],
                        value=5, count=False, mode='online', second='删除工单')
        deleted['order_status'] = '删除'
        deleted['exclusion_reason'] = '工单已删除'
        self.facts.append(deleted)

    def test_seven_channels_share_university_channel_and_preserve_line_detail(self):
        result = build_notifications(self.public, self.facts, self.people, self.abroad_people)

        self.assertEqual(result['schema_version'], 'management_notifications.v1')
        self.assertEqual(result['data_through'], '2026-09-28')
        self.assertEqual(len(result['messages']), 7)
        university_training = next(row for row in result['messages']
                                   if row['id'] == 'university.training')
        university_abroad = next(row for row in result['messages']
                                 if row['id'] == 'university.abroad')
        self.assertEqual(university_training['channel_id'], 'offline_university')
        self.assertEqual(university_abroad['channel_id'], 'offline_university')
        self.assertEqual(university_training['month'], '2026-09')
        self.assertEqual(university_training['window']['person_month'], '2026-10')
        self.assertEqual([person['name'] for person in university_training['people']], ['大学同事'])
        self.assertEqual([person['name'] for person in university_abroad['people']], ['留学同事'])

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

    def test_virtual_notification_merges_two_order_lines_and_deduplicates_team_ledger(self):
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
        self.assertEqual(by_name['虚拟甲']['today_orders'], 2)
        self.assertEqual(by_name['虚拟甲']['expected_orders'], 1)
        self.assertEqual(by_name['虚拟甲']['daily_orders'], 8 / 19)
        self.assertNotIn('secondary_business_line', by_name['虚拟甲'])
        self.assertEqual(by_name['虚拟甲']['heads_target'], 2)
        self.assertEqual(by_name['虚拟甲']['heads_actual']['actual'], 1)
        self.assertEqual(by_name['虚拟乙']['orders_actual'], 1)
        self.assertEqual(by_name['虚拟乙']['today_orders'], 1)

        team_ids = [row['fact_id'] for row in virtual['ledgers']['team_orders']]
        self.assertCountEqual(team_ids, ['virtual-training', 'virtual-abroad', 'virtual-deleted'])
        included_ids = {row['fact_id'] for row in virtual['ledgers']['team_orders']
                        if row['counts_toward_completion']}
        self.assertEqual(included_ids, {'virtual-training', 'virtual-abroad'})
        deleted_row = next(row for row in virtual['ledgers']['team_orders']
                           if row['fact_id'] == 'virtual-deleted')
        self.assertEqual(deleted_row['order_status'], '删除')
        self.assertEqual(deleted_row['exclusion_reason'], '工单已删除')
        self.assertCountEqual(
            [row['fact_id'] for row in virtual['ledgers']['personal_orders']],
            ['virtual-training', 'virtual-abroad', 'virtual-deleted'],
        )
        self.assertEqual(virtual['ledgers']['personal_secondary_orders'], [])


    def test_platforms_merge_same_secondary_channel_and_include_deleted_for_team(self):
        from datetime import date
        from dashboard_product.management.notifications import _channels
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


class OnlineProjectionScopeTest(unittest.TestCase):
    def test_projection_uses_team_attribution_scope_and_counts_deleted_orders(self):
        from dashboard_product.management.online_view import online_view
        from dashboard_product.online_team.build import metric
        from datetime import date
        p={'id':'FY27','label':'2027财年全年','kind':'year','status':'available',
           'start_date':'2026-06-01','through_date':'2026-10-02',
           'prior_start_date':'2025-06-01','prior_through_date':'2025-10-02',
           'teams':[{'id':'online','business_groups':[], 'lines':{
               line:{'orders':metric(1 if line=='abroad' else 0,0,None,0,'单'),
                     'cash':metric(None,None,None,0,'元',status='not_connected'),
                     'heads':metric(None,None,None,0,'人',status='not_connected')}
               for line in ('training','abroad')}}]}
        facts=[{'fact_id':'deleted-online','work_order_id':'a','team_id':'online_platform',
                'business_line':'abroad','acquisition_mode':'online','metric':'orders',
                'event_date':'2026-10-02','value':1,'order_status':'删除','counts_toward_completion':False},
               {'fact_id':'offline-attribution','work_order_id':'b','team_id':'online_platform',
                'business_line':'abroad','acquisition_mode':'offline','metric':'orders',
                'event_date':'2026-10-02','value':1,'order_status':'回收','counts_toward_completion':False}]
        result=online_view({'metadata':{'data_through':'2026-10-02'},'schema_version':'dashboard_rebuild.v1','periods':[p]},facts,{'cash':{'total':{'annual':None}}})
        period=result['periods'][0]
        self.assertEqual(period['lines']['abroad']['orders']['actual'],1)
        self.assertEqual(sum(r['orders'] for r in period['lines']['abroad']['channels']),1)
        self.assertEqual(sum(r['abroad_orders'] for r in period['daily']),1)
