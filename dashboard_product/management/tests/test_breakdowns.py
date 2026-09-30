import unittest
from datetime import date
from dashboard_product.management.aggregate import aggregate
from dashboard_product.management.breakdowns import enrich_periods

class BreakdownTests(unittest.TestCase):
    def test_subgroups_channels_and_country_folds_preserve_scope(self):
        facts=[]
        for ident, group, student in [('a','青少','s1'),('b','初中','s1')]:
            base=dict(fact_id=ident,event_date='2026-09-01',business_line='training',business_group='留学预备',comparison_group=group,team_id='offline_market',work_order_id=ident,owners=[],first_channel='市场活动',second_channel='校代',school_name='学校A',grade_name=group,student_id=student)
            facts += [dict(base,metric='orders',value=1),dict(base,fact_id=ident+'cash',metric='cash',value=100)]
        facts.append(dict(fact_id='foreign',event_date='2026-09-01',business_line='abroad',business_group='大学',team_id='offline_market',work_order_id='c',owners=['孙伟'],metric='orders',value=1,first_channel='市场活动',second_channel='讲座',country='英国',line='英澳条线',acquisition_mode='online'))
        people={'teams':[]};abroad={'people':[{'display_name':'孙伟'}]};targets={'business_groups':{'prep':{'display_name':'留学预备','months':{'2026-09':{'offline_market':{'work_order_target':20,'passive_cash_target':1000}}}}}}
        data=aggregate(facts,people,abroad,targets,{}, {},date(2026,9,28))
        enrich_periods(data['periods'],facts,targets,{}, {})
        p=next(p for p in data['periods'] if p['id']=='2026-09')
        t=next(t for t in p['teams'] if t['id']=='prep')
        self.assertEqual([r['orders']['actual'] for r in t['yoy_groups']],[1,1])
        self.assertEqual(t['business_groups'][0]['heads']['actual'],1)
        self.assertEqual(t['business_groups'][0]['orders']['target'],20)
        self.assertEqual(sum(r['orders']['actual'] for r in t['channels']),2)
        self.assertEqual(t['channels'][0]['cash']['actual'],200)
        self.assertEqual(sum(r['orders']['actual'] for r in t['schools_by_line']['training'][0]['grades']),2)
        u=next(t for t in p['teams'] if t['id']=='university')
        self.assertEqual(u['country_groups'][0]['line'],'英澳条线')
        self.assertEqual(u['country_groups'][0]['online'],1)
        self.assertEqual(u['country_groups'][0]['countries'][0]['country'],'英国')
        future=next(p for p in data['periods'] if p['id']=='2026-10')
        self.assertEqual(next(t for t in future['teams'] if t['id']=='prep')['channels'],[])

    def test_market_target_keeps_original_configured_team_sum(self):
        targets={'business_groups':{name:{'display_name':name,'quarters':{'Q1':{team:{'work_order_target':100,'passive_cash_target':1000} for team in ('offline_market','online_private','online_platform')}}} for name in ('留学预备','高中','大学')}}
        facts=[dict(fact_id='unknown',event_date='2026-07-01',business_line='training',business_group='大学',team_id=None,metric='orders',value=1,owners=[],work_order_id='unknown')]
        result=aggregate(facts,{'teams':[]},{'people':[]},targets,{}, {},date(2026,9,28))
        q=next(p for p in result['periods'] if p['id']=='Q1')
        total=next(t for t in q['teams'] if t['id']=='total')
        self.assertEqual(total['lines']['training']['orders']['target'],900)
        self.assertEqual(total['lines']['training']['cash']['target'],9000)
