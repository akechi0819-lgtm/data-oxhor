import unittest
from datetime import date
from dashboard_product.management.aggregate import aggregate
from dashboard_product.management.breakdowns import enrich_periods
from dashboard_product.management.enhancements import selection_views, enhance_capacity

class EnhancementTests(unittest.TestCase):
    def base(self):
        people={'teams':[{'team_id':'offline_market','groups':[{'group_id':'youth','display_name':'青少组','members':[{'display_name':'马澳','business_group':'留学预备','status':'active','monthly_targets':{'2026-09':{'orders':100}}}]},{'group_id':'middle_school','display_name':'初中组','members':[]},{'group_id':'high_school','display_name':'高中组','members':[]}]}]}
        targets={'business_groups':{'prep':{'display_name':'留学预备','months':{'2026-09':{'offline_market':{'work_order_target':100,'passive_cash_target':1000}}}},'high':{'display_name':'高中','months':{'2026-09':{'offline_market':{'work_order_target':50,'passive_cash_target':500}}}}}}
        facts=[]
        for i,g in enumerate(('青少','初中','高中')):
            for metric in ('orders','cash'):
                facts.append(dict(fact_id=f'{g}-{metric}',event_date='2026-09-10',business_line='training',business_group='高中' if g=='高中' else '留学预备',comparison_group=g,team_id='offline_market',work_order_id=str(i),owners=['马澳'],student_id='same-student',metric=metric,value=1 if metric=='orders' else 100,first_channel='市场活动',second_channel='线下校代',school_name='学校A',grade_name=g))
        facts.append(dict(fact_id='study',event_date='2026-09-10',business_line='abroad',business_group=None,team_id=None,owners=['马澳'],metric='orders',value=3,work_order_id='study',country='英国',line='英澳',first_channel='市场活动',second_channel='讲座',grade_name='高三'))
        body=aggregate(facts,people,{'people':[]},targets,{}, {},date(2026,9,28))
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
        body=aggregate(facts,people,{'people':[]},targets,{}, {},date(2026,9,28))
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

    def test_grade_totals_include_all_schools_and_abroad_cash_is_missing(self):
        facts,people,targets,body=self.base()
        total=next(p for p in body['periods'] if p['id']=='2026-09')['teams'][0]
        self.assertEqual(sum(r['cash']['actual'] for r in total['grades_by_line']['training']),300)
        self.assertEqual(sum(r['orders']['actual'] for r in total['grades_by_line']['abroad']),3)
        self.assertIsNone(total['grades_by_line']['abroad'][0]['cash']['actual'])

    def test_capacity_same_window_and_original_six_axes(self):
        facts,people,targets,body=self.base()
        facts.append(dict(facts[0],fact_id='old',event_date='2025-09-10',value=2))
        enhance_capacity(body,facts,people,{'people':[]},date(2026,9,28),{'annual_cash_by_person':800000})
        p=body['capacity'][0]
        self.assertEqual(p['orders_metric']['actual'],6)
        self.assertEqual(p['orders_metric']['prior'],2)
        self.assertEqual(p['orders_metric']['yoy'],2)
        self.assertEqual(len(p['radar']['axes']),6)
        self.assertEqual(p['radar']['axes'][0]['value'],3)
        self.assertEqual(p['radar']['axes'][3]['value'],300)

    def test_radar_peer_statistics_include_every_member(self):
        facts,people,targets,_=self.base()
        people['teams'][0]['groups'][0]['members'].append({'display_name':'同组同事','business_group':'留学预备','status':'active'})
        body=aggregate(facts,people,{'people':[]},targets,{}, {},date(2026,9,28))
        enhance_capacity(body,facts,people,{'people':[]},date(2026,9,28),{'annual_cash_by_person':800000})
        selected=next(p for p in body['capacity'] if p['name']=='马澳')
        self.assertEqual(selected['radar']['peer_count'],2)
        self.assertEqual(selected['radar']['axes'][0]['mean'],1.5)
        self.assertEqual(selected['radar']['axes'][0]['relative'],1)

    def test_grade_aliases_merge_without_changing_totals(self):
        facts,people,targets,body=self.base()
        facts[0]['grade_name']='七年级'
        facts[1]['grade_name']='初一'
        facts[2]['grade_name']='10年级(国外高中)'
        result=aggregate(facts,people,{'people':[]},targets,{}, {},date(2026,9,28))
        enrich_periods(result['periods'],facts,targets,{}, {})
        t=next(p for p in result['periods'] if p['id']=='2026-09')['teams'][0]
        rows={r['name']:r for r in t['grades_by_line']['training']}
        self.assertNotIn('七年级',rows)
        self.assertEqual(rows['初一']['orders']['actual'],1)
        self.assertEqual(rows['初一']['cash']['actual'],100)
        self.assertIn('10年级(国外高中)',rows)
        self.assertEqual(sum(r['cash']['actual'] for r in rows.values()),300)
