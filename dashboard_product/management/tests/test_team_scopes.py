"""团队筛选合并事实去重，保留总盤和目标的既有边界。"""
from copy import deepcopy
from datetime import date
import unittest

from dashboard_product.management.aggregate import aggregate
from dashboard_product.management.breakdowns import enrich_periods
from dashboard_product.management.cash_share import attach_passive_cash_share
from dashboard_product.management.market_totals import attach_market_orders
from dashboard_product.management.study_abroad_progress import attach_progress
from dashboard_product.management.team_scopes import attach_team_scope_views


class TeamScopeTests(unittest.TestCase):
    def test_scopes_recompute_people_and_targets_without_changing_total(self):
        source = {'start_date': '2026-06-01', 'through_date': '2026-10-08', 'no_yoy': True}
        facts = []
        market = []
        for i, team in enumerate(('online_private', 'online_platform', 'offline_market', None)):
            row = {'fact_id': str(i), 'work_order_id': str(i), 'event_date': '2026-09-30',
                   'business_line': 'training', 'business_group': '大学', 'comparison_group': '大学',
                   'team_id': team, 'owners': [], 'value': 1, 'metric': 'orders'}
            facts.append(row)
            market.append(row)
            facts.append({**row, 'fact_id': 'cash' + str(i), 'metric': 'cash',
                          'value': 100, 'class_code':'fixture-class','registration_count':1, 'student_id': 'shared-online' if i < 2 else str(i)})
        # Repeated raw order ID and an order absent from training still follow market baseline.
        market += [market[0], {**market[2], 'work_order_id': 'raw-only'}]
        targets = {'business_groups': {'college': {'display_name': '大学', 'months': {
            '2026-09': {team: {'work_order_target': goal, 'passive_cash_target': goal * 100}
                        for team, goal in [('online_private', 10), ('online_platform', 20),
                                           ('offline_market', 30)]}}}}}
        periods = aggregate(facts, {'teams': []}, {'people': []}, targets, {}, {},
                            date(2026, 10, 8), abroad_source=source)['periods']
        enrich_periods(periods, facts, targets, {}, {})
        attach_progress(periods)
        attach_market_orders(periods, market)
        denominators = [{'cash_date': '2026-09-30', 'business_group': '大学', 'cash_amount': 1000}]
        attach_passive_cash_share(periods, denominators)
        before = deepcopy(periods)
        attach_team_scope_views(periods, facts, market, targets, denominators)
        september = next(period for period in periods if period['id'] == '2026-09')
        total = next(team for team in september['teams'] if team['id'] == 'total')
        views = total.pop('team_scope_views')
        original = next(p for p in before if p['id'] == '2026-09')
        self.assertEqual(total, next(t for t in original['teams'] if t['id'] == 'total'))
        groups = {scope: next(row for row in view['business_groups'] if row['name'] == '大学')
                  for scope, view in views.items()}
        self.assertEqual(groups['all']['orders']['actual'], 5)
        self.assertEqual(groups['online']['orders']['actual'], 2)
        self.assertEqual(groups['offline']['orders']['actual'], 2)
        self.assertEqual(groups['online']['orders']['target'], 30)
        self.assertEqual(groups['offline']['orders']['target'], 30)
        self.assertEqual(groups['online']['heads']['actual'], 0)
        self.assertEqual(groups['online']['cash']['actual'], 200)
        self.assertEqual(groups['online']['passive_cash_share']['ratio'], 0.2)
        self.assertEqual([r['id'] for r in views['online']['study_abroad_progress']], ['online'])
        self.assertEqual([r['id'] for r in views['offline']['study_abroad_progress']], ['university'])
        future = next(p for p in periods if p['id'] == '2026-11')
        future_total = next(t for t in future['teams'] if t['id'] == 'total')
        self.assertIsNone(future_total['team_scope_views']['online']['business_groups'][0]['heads']['actual'])


if __name__ == '__main__':
    unittest.main()
