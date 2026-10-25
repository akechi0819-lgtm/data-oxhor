import unittest
from datetime import date
from dashboard_product.management.aggregate import aggregate
from dashboard_product.management.breakdowns import enrich_periods


def study_coverage(start_date='2026-09-01', through_date='2026-09-30'):
    return {'snapshot_id': 'snapshot_study_fixture', 'source_sha256': 'a' * 64,
            'start_date': start_date, 'through_date': through_date, 'no_yoy': True,
            'cross_system_customers': 'not_aligned'}


class BreakdownTests(unittest.TestCase):
    def test_channel_groups_and_school_grades_expose_headcount_semantics(self):
        facts = []
        for year, label in ((2025, 'prior'), (2026, 'current')):
            for day, student, grade, suffix in (
                    (1, 'S1', '七年级', 'first'),
                    (2, 'S1', '七年级', 'repeat'),
                    (3, 'S1', '八年级', 'other_grade'),
                    (4, 'S2', '七年级', 'second_student')):
                if year == 2025 and student == 'S2':
                    continue
                facts.append({
                    'fact_id': f'{label}-{suffix}',
                    'event_date': f'{year}-09-{day:02d}',
                    'business_line': 'training',
                    'business_group': '留学预备',
                    'comparison_group': '青少',
                    'team_id': 'offline_market',
                    'work_order_id': f'{label}-{suffix}',
                    'owners': [],
                    'metric': 'cash',
                    'value': 1500, 'class_code':'fixture-class','registration_count':1,
                    'first_channel': '市场活动',
                    'second_channel': '校代',
                    'school_name': '主学校',
                    'grade_name': grade,
                    'student_id': student,
                })

        for product, student in (('study_abroad', 'A1'), ('small_language', 'A2')):
            facts.append({
                'fact_id': f'abroad-{product}',
                'event_date': '2026-09-10',
                'business_line': 'abroad',
                'business_group': '大学',
                'team_id': 'offline_market',
                'work_order_id': f'abroad-{product}',
                'owners': [],
                'metric': 'cash',
                'value': 100,
                'first_channel': '市场活动',
                'second_channel': '校代',
                'school_name': '留学学校',
                'grade_name': '大二',
                'student_id': student,
                'segment_id': 'study_abroad_offline',
                'source_product': product,
                'customer_domain': product,
                'source_kind': 'study_abroad_warehouse',
                'offline_channel_eligible': True,
            })

        targets = {}
        data = aggregate(
            facts, {'teams': []}, {'people': []}, targets, {}, {},
            date(2026, 9, 28), abroad_source=study_coverage(),
        )
        enrich_periods(data['periods'], facts, targets, {}, {})
        period = next(row for row in data['periods'] if row['id'] == '2026-09')

        prep = next(team for team in period['teams'] if team['id'] == 'prep')
        channel = next(row for row in prep['channels']
                       if row['business_line'] == 'training' and row['name'] == '校代')
        group = next(row for row in channel['groups'] if row['name'] == '青少')
        self.assertEqual((group['heads']['actual'], group['heads']['prior'],
                          group['heads']['yoy']), (2, 1, 1))

        school = prep['schools_by_line']['training'][0]
        self.assertEqual((school['heads']['actual'], school['heads']['prior'],
                          school['heads']['yoy']), (2, 1, 1))
        self.assertEqual(sum(grade['heads']['actual'] for grade in school['grades']), 3)
        self.assertEqual(sum(grade['heads']['prior'] for grade in school['grades']), 2)

        university = next(team for team in period['teams'] if team['id'] == 'university')
        abroad_channel = next(row for row in university['channels']
                              if row['business_line'] == 'abroad')
        abroad_group = abroad_channel['groups'][0]
        abroad_school = university['schools_by_line']['abroad'][0]
        abroad_grade = abroad_school['grades'][0]
        for metric in (abroad_group['heads'], abroad_school['heads'], abroad_grade['heads']):
            self.assertIsNone(metric['actual'])
            self.assertIsNone(metric['prior'])
            self.assertIsNone(metric['yoy'])
            self.assertEqual(metric['status'], 'separate_counts')
            self.assertTrue(metric['source_coverage']['no_yoy'])

    def test_subgroups_channels_and_country_folds_preserve_scope(self):
        facts=[]
        for ident, group, student in [('a','青少','s1'),('b','初中','s1')]:
            base=dict(fact_id=ident,event_date='2026-09-01',business_line='training',business_group='留学预备',comparison_group=group,team_id='offline_market',work_order_id=ident,owners=[],first_channel='市场活动',second_channel='校代',school_name='学校A',grade_name=group,student_id=student,class_code='fixture-class',registration_count=1)
            facts += [dict(base,metric='orders',value=1),dict(base,fact_id=ident+'cash',metric='cash',value=100)]
        facts.append(dict(fact_id='foreign',event_date='2026-09-01',business_line='abroad',business_group='大学',team_id='offline_market',work_order_id='c',owners=['孙伟'],metric='orders',value=1,first_channel='市场活动',second_channel='讲座',country='英国',line='英澳条线',acquisition_mode='online',offline_channel_eligible=True,segment_id='study_abroad_offline',source_product='study_abroad',customer_domain='study_abroad',source_kind='study_abroad_warehouse'))
        people={'teams':[]};abroad={'people':[{'display_name':'孙伟','business_group':'大学'}]};targets={'business_groups':{'prep':{'display_name':'留学预备','months':{'2026-09':{'offline_market':{'work_order_target':20,'passive_cash_target':1000}}}}}}
        data=aggregate(facts,people,abroad,targets,{}, {},date(2026,9,28),abroad_source=study_coverage())
        enrich_periods(data['periods'],facts,targets,{}, {})
        p=next(p for p in data['periods'] if p['id']=='2026-09')
        t=next(t for t in p['teams'] if t['id']=='prep')
        self.assertEqual([r['orders']['actual'] for r in t['yoy_groups']],[1,1])
        self.assertEqual(t['business_groups'][0]['heads']['actual'],0)
        self.assertEqual(t['business_groups'][0]['orders']['target'],20)
        self.assertEqual(sum(r['orders']['actual'] for r in t['channels']),2)
        self.assertEqual(t['channels'][0]['cash']['actual'],200)
        self.assertEqual(sum(r['orders']['actual'] for r in t['schools_by_line']['training'][0]['grades']),2)
        u=next(t for t in p['teams'] if t['id']=='university')
        self.assertEqual(u['country_groups'][0]['line'],'英澳条线')
        self.assertEqual(u['country_groups'][0]['online'],0)
        self.assertEqual(u['country_groups'][0]['offline'],1)
        self.assertEqual(u['country_groups'][0]['countries'][0]['country'],'英国')
        future=next(p for p in data['periods'] if p['id']=='2026-10')
        self.assertEqual(next(t for t in future['teams'] if t['id']=='prep')['channels'],[])

    def test_market_target_keeps_original_configured_team_sum(self):
        targets={'business_groups':{name:{'display_name':name,'quarters':{'Q1':{team:{'work_order_target':100,'passive_cash_target':1000} for team in ('offline_market','online_private','online_platform')}}} for name in ('留学预备','高中','大学')}}
        facts=[dict(fact_id='unknown',event_date='2026-07-01',business_line='training',business_group='大学',team_id=None,metric='orders',value=1,owners=[],work_order_id='unknown')]
        result=aggregate(facts,{'teams':[]},{'people':[]},targets,{}, {},date(2026,9,28),abroad_source=study_coverage())
        q=next(p for p in result['periods'] if p['id']=='Q1')
        total=next(t for t in q['teams'] if t['id']=='total')
        self.assertEqual(total['lines']['training']['orders']['target'],900)
        self.assertEqual(total['lines']['training']['cash']['target'],9000)
