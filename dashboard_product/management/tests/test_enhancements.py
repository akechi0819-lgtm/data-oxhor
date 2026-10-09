import unittest
from datetime import date
from dashboard_product.management.aggregate import aggregate
from dashboard_product.management.breakdowns import enrich_periods
from dashboard_product.management.enhancements import selection_views
from workspace_modeling.operations.personnel import DEFAULT_ORDER_STATUS_MODE, ORDER_STATUS_MODES


def study_coverage(start_date='2026-09-01', through_date='2026-09-30'):
    return {'snapshot_id': 'snapshot_study_fixture', 'source_sha256': 'a' * 64,
            'start_date': start_date, 'through_date': through_date, 'no_yoy': True,
            'cross_system_customers': 'not_aligned'}


class EnhancementTests(unittest.TestCase):
    def base(self):
        people={'teams':[{'team_id':'offline_market','groups':[{'group_id':'youth','display_name':'青少组','members':[{'display_name':'马澳','business_group':'留学预备','status':'active','monthly_targets':{'2026-09':{'orders':100}}}]},{'group_id':'middle_school','display_name':'初中组','members':[]},{'group_id':'high_school','display_name':'高中组','members':[]}]}]}
        targets={'business_groups':{'prep':{'display_name':'留学预备','months':{'2026-09':{'offline_market':{'work_order_target':100,'passive_cash_target':1000}}}},'high':{'display_name':'高中','months':{'2026-09':{'offline_market':{'work_order_target':50,'passive_cash_target':500}}}}}}
        facts=[]
        for i,g in enumerate(('青少','初中','高中')):
            for metric in ('orders','cash'):
                facts.append(dict(fact_id=f'{g}-{metric}',event_date='2026-09-10',business_line='training',business_group='高中' if g=='高中' else '留学预备',comparison_group=g,team_id='offline_market',work_order_id=str(i),owners=['马澳'],student_id='same-student',metric=metric,value=1 if metric=='orders' else 100,first_channel='市场活动',second_channel='线下校代',school_name='学校A',grade_name=g))
        facts.append(dict(fact_id='study',event_date='2026-09-10',business_line='abroad',business_group=None,team_id=None,owners=['马澳'],metric='orders',value=3,work_order_id='study',country='英国',line='英澳',first_channel='市场活动',second_channel='讲座',grade_name='高三',segment_id='unassigned',source_product='study_abroad',customer_domain='study_abroad',source_kind='study_abroad_warehouse'))
        body=aggregate(facts,people,{'people':[]},targets,{}, {},date(2026,9,28),abroad_source=study_coverage())
        enrich_periods(body['periods'],facts,targets,{}, {})
        return facts,people,targets,body

    def test_multiselect_deduplicates_heads_and_does_not_split_targets(self):
        facts,people,targets,body=self.base()
        views=selection_views(body['periods'],facts,people,targets)
        self.assertEqual(set(views),set('1234567'))
        def selected(mask):return next(p for p in views[mask] if p['id']=='2026-09')['teams'][0]
        combined=selected('3');single=selected('1');all_groups=selected('7')
        self.assertEqual(combined['lines']['training']['orders']['actual'],2)
        self.assertEqual(combined['lines']['training']['heads']['actual'],1)
        self.assertEqual(combined['lines']['training']['orders']['target'],100)
        self.assertIsNone(single['lines']['training']['orders']['target'])
        self.assertEqual(all_groups['lines']['training']['orders']['target'],150)
        self.assertEqual(all_groups['people'][0]['abroad_actual'],3)
        self.assertIsNone(all_groups['people'][0]['abroad_target'])
        self.assertEqual(sum(r['cash']['actual'] for r in all_groups['channels']),300)
        self.assertEqual(sum(r['share'] for r in all_groups['channels']),1)

    def test_deleted_and_recycled_orders_count_for_teams_but_not_people(self):
        people={'teams':[{'team_id':'offline_market','groups':[
            {'group_id':'youth','display_name':'青少组','members':[
                {'display_name':'马澳','business_group':'留学预备','status':'active',
                 'monthly_targets':{'2026-09':{'orders':100}}},
            ]},
            {'group_id':'middle_school','display_name':'初中组','members':[]},
            {'group_id':'high_school','display_name':'高中组','members':[]},
        ]}]}
        targets={'business_groups':{'prep':{'display_name':'留学预备','months':{
            '2026-09':{'offline_market':{'work_order_target':100,'passive_cash_target':1000}},
        }}}}
        facts=[
            {'fact_id':'deleted','event_date':'2026-09-15','business_line':'training',
             'business_group':'留学预备','comparison_group':'青少','team_id':'offline_market',
             'work_order_id':'deleted','owners':['马澳'],'metric':'orders','value':1,
             'order_status':'删除','counts_toward_completion':False,
             'first_channel':'市场活动','second_channel':'线下校代',
             'school_name':'学校A','grade_name':'初二'},
            {'fact_id':'recycled','event_date':'2026-09-20','business_line':'training',
             'business_group':'留学预备','comparison_group':'初中','team_id':'offline_market',
             'work_order_id':'recycled','owners':['马澳'],'metric':'orders','value':1,
             'order_status':'回收','first_channel':'市场活动','second_channel':'线下校代',
             'school_name':'学校A','grade_name':'初二'},
        ]
        body=aggregate(facts,people,{'people':[]},targets,{}, {},date(2026,9,28),abroad_source=study_coverage())
        enrich_periods(body['periods'],facts,targets,{}, {})
        september=next(p for p in body['periods'] if p['id']=='2026-09')
        prep=next(t for t in september['teams'] if t['id']=='prep')

        self.assertEqual(prep['lines']['training']['orders']['actual'],2)
        self.assertEqual(sum(r['orders']['actual'] for r in prep['channels']),2)
        self.assertEqual(sum(r['orders']['actual'] for r in prep['yoy_groups']),2)
        self.assertEqual(prep['schools_by_line']['training'][0]['orders']['actual'],2)
        self.assertEqual(prep['grades_by_line']['training'][0]['orders']['actual'],2)
        person=prep['people'][0]
        calendar_person=prep['person_calendar']['people'][0]
        self.assertEqual(person['training_actual'],0)
        self.assertEqual(calendar_person['training_actual'],0)
        self.assertEqual(DEFAULT_ORDER_STATUS_MODE,'01')
        self.assertEqual(set(person['order_status_views']),set(ORDER_STATUS_MODES))
        self.assertEqual(set(calendar_person['order_status_views']),set(ORDER_STATUS_MODES))
        expected_status_actuals={'00':0,'01':0,'10':2,'11':2}
        for mode,expected_actual in expected_status_actuals.items():
            self.assertEqual(person['order_status_views'][mode]['training_actual'],expected_actual)
            self.assertEqual(calendar_person['order_status_views'][mode]['training_actual'],expected_actual)
        self.assertEqual({r['name']:r['orders'] for r in body['activities']}['未填写活动'],2)

        views=selection_views(body['periods'],facts,people,targets)
        selected=next(p for p in views['3'] if p['id']=='2026-09')['teams'][0]
        self.assertEqual(selected['lines']['training']['orders']['actual'],2)
        self.assertEqual(sum(r['orders']['actual'] for r in selected['channels']),2)
        self.assertEqual(selected['people'][0]['training_actual'],0)
        self.assertEqual(selected['person_calendar']['people'][0]['training_actual'],0)
        self.assertEqual(set(selected['people'][0]['order_status_views']),set(ORDER_STATUS_MODES))
        self.assertEqual(set(selected['person_calendar']['people'][0]['order_status_views']),set(ORDER_STATUS_MODES))
        for mode,expected_actual in expected_status_actuals.items():
            self.assertEqual(selected['people'][0]['order_status_views'][mode]['training_actual'],expected_actual)
            self.assertEqual(selected['person_calendar']['people'][0]['order_status_views'][mode]['training_actual'],expected_actual)

    def test_selection_views_filter_calendar_people_and_keep_calendar_window(self):
        facts,people,targets,_=self.base()
        people['teams'][0]['groups'][1]['members'].append({
            'display_name':'初中同事','business_group':'留学预备','status':'active',
            'monthly_targets':{'2026-09':{'orders':80}},
        })
        people['teams'][0]['groups'][2]['members'].append({
            'display_name':'高中同事','business_group':'高中','status':'active',
            'monthly_targets':{'2026-09':{'orders':90}},
        })
        body=aggregate(facts,people,{'people':[]},targets,{}, {},date(2026,9,28),abroad_source=study_coverage())
        enrich_periods(body['periods'],facts,targets,{}, {})
        views=selection_views(body['periods'],facts,people,targets)

        def calendar(mask):
            period=next(p for p in views[mask] if p['id']=='2026-09')
            return period['teams'][0]['person_calendar']

        expected={
            '1':['马澳'],
            '2':['初中同事'],
            '3':['马澳','初中同事'],
            '4':['高中同事'],
            '5':['马澳','高中同事'],
            '6':['初中同事','高中同事'],
            '7':['马澳','初中同事','高中同事'],
        }
        for mask,names in expected.items():
            selected=calendar(mask)
            self.assertEqual(selected['person_start'],'2026-09-01')
            self.assertEqual(selected['person_through'],'2026-09-28')
            self.assertAlmostEqual(selected['person_progress'],28/30)
            self.assertEqual(sorted(person['name'] for person in selected['people']),sorted(names))

    def test_migrated_abroad_person_and_channels_follow_high_multiselect_masks(self):
        facts,people,targets,_=self.base()
        facts.append(dict(
            fact_id='ma-yue-abroad',event_date='2026-09-10',business_line='abroad',
            business_group=None,team_id='online_platform',work_order_id='ma-yue-abroad',
            owners=['马玥'],virtual_owners=[],metric='orders',value=2,
            first_channel='网络资源',second_channel='搜索',acquisition_mode='online',
            offline_channel_eligible=False,segment_id='study_abroad_online',
            source_product='study_abroad',customer_domain='study_abroad',
            source_kind='study_abroad_warehouse',
        ))
        abroad={'people':[
            {'display_name':'马玥','business_group':'高中'},
            {'display_name':'邓睿','business_group':'大学'},
        ]}
        body=aggregate(facts,people,abroad,targets,{}, {},date(2026,9,28),abroad_source=study_coverage())
        enrich_periods(body['periods'],facts,targets,{}, {})
        views=selection_views(body['periods'],facts,people,targets)

        for mask in ('1','2','3'):
            period=next(p for p in views[mask] if p['id']=='2026-09')
            team=period['teams'][0]
            self.assertNotIn('马玥',{row['name'] for row in team['people']})
            self.assertNotIn('马玥',{row['name'] for row in team['person_calendar']['people']})

        for mask in ('4','5','6','7'):
            period=next(p for p in views[mask] if p['id']=='2026-09')
            team=period['teams'][0]
            person=next(row for row in team['people'] if row['name']=='马玥')
            calendar=next(row for row in team['person_calendar']['people']
                          if row['name']=='马玥')
            self.assertEqual(person['abroad_channels'][0]['name'],'搜索')
            self.assertEqual(person['abroad_channels'][0]['orders']['actual'],2)
            self.assertEqual(calendar['abroad_channels'][0]['orders']['actual'],2)
            self.assertEqual(team['lines']['abroad']['orders']['status'],'not_configured')

    def test_grade_totals_include_all_schools_and_covered_abroad_cash_is_zero(self):
        facts,people,targets,body=self.base()
        total=next(p for p in body['periods'] if p['id']=='2026-09')['teams'][0]
        self.assertEqual(sum(r['cash']['actual'] for r in total['grades_by_line']['training']),300)
        self.assertEqual(sum(r['orders']['actual'] for r in total['grades_by_line']['abroad']),3)
        self.assertEqual(total['grades_by_line']['abroad'][0]['cash']['actual'],0)
        self.assertEqual(total['grades_by_line']['abroad'][0]['cash']['status'],'available')

    def test_grade_aliases_merge_without_changing_totals(self):
        facts,people,targets,body=self.base()
        facts[0]['grade_name']='七年级'
        facts[1]['grade_name']='初一'
        facts[2]['grade_name']='10年级(国外高中)'
        result=aggregate(facts,people,{'people':[]},targets,{}, {},date(2026,9,28),abroad_source=study_coverage())
        enrich_periods(result['periods'],facts,targets,{}, {})
        t=next(p for p in result['periods'] if p['id']=='2026-09')['teams'][0]
        rows={r['name']:r for r in t['grades_by_line']['training']}
        self.assertNotIn('七年级',rows)
        self.assertEqual(rows['初一']['orders']['actual'],1)
        self.assertEqual(rows['初一']['cash']['actual'],100)
        self.assertIn('10年级(国外高中)',rows)
        self.assertEqual(sum(r['cash']['actual'] for r in rows.values()),300)
