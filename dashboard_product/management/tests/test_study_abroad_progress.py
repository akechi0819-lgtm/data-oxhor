import unittest

from dashboard_product.management.aggregate import aggregate
from dashboard_product.management.study_abroad_progress import attach_progress


class StudyAbroadProgressTests(unittest.TestCase):
    def test_only_confirmed_team_targets_are_projected(self):
        source = {'start_date': '2026-09-01', 'through_date': '2026-09-30'}
        facts = [dict(fact_id='resource', metric='orders', value=1,
                      business_line='abroad', event_date='2026-09-10', owners=[],
                      segment_id='study_abroad_offline', first_channel='市场活动'),
                 dict(fact_id='cash', metric='cash', value=10000,
                      business_line='abroad', event_date='2026-09-10', owners=[],
                      segment_id='study_abroad_offline', first_channel='市场活动',
                      student_id='contracts:1', customer_domain='study_abroad')]
        offline = {'total': {'work_order_target': 2620},
                   'groups': {'市场活动': {'work_order_target': 1800}},
                   'cash': {'total': {'annual': 660},
                            'groups': {'市场活动': {'annual': 277.2}}}}
        online = {'study_abroad': {'resource_target': {'annual': 6715}},
                  'cash': {'total': {'annual': 2992.56},
                           'groups': {'网络资源': {'annual': 2753.56}}}}
        data = aggregate(facts, {'teams': []}, {'people': []}, {}, offline, online,
                         '2026-10-02', abroad_source=source)
        attach_progress(data['periods'])
        year = next(p for p in data['periods'] if p['id'] == 'FY27')
        total = next(t for t in year['teams'] if t['id'] == 'total')
        line = next(r for r in total['abroad_progress'] if r['id'] == 'university')
        self.assertEqual([row['name'] for row in total['abroad_progress']], ['线上留学', '线下留学'])
        self.assertNotIn('channels', line)
        self.assertEqual(line['cash']['target'], 6600000)
        self.assertAlmostEqual(line['cash']['completion'], 10000 / 6600000)
        self.assertEqual(line['orders']['target'], 2620)
        september = next(p for p in data['periods'] if p['id'] == '2026-09')
        month_line = next(t for t in september['teams'] if t['id'] == 'university')['abroad_progress'][0]
        self.assertIsNone(month_line['cash']['target'])
        self.assertEqual(month_line['cash']['actual'], 10000)
