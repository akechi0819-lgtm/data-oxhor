"""跨业务活动的本业务、跨业务成果不能统一平分。"""
from decimal import Decimal
import unittest

from dashboard_product.management.aggregate import _personal_actual, _personal_weights
from workspace_modeling.operations.personnel import activity_co_creation_weights


class ActivityAttributionTests(unittest.TestCase):
    def setUp(self):
        self.roster = {
            name: {'name': name, 'business_line': line, 'team_ids': {'offline_market'},
                   'training_roster': line == 'training', 'abroad_roster': line == 'abroad',
                   'home_group': '大学'}
            for name, line in [('语培主办', 'training'), ('语培共创', 'training'),
                               ('留学接收', 'abroad'), ('留学接收乙', 'abroad')]
        }

    def test_training_creator_keeps_full_orders_cash_and_unique_heads(self):
        from datetime import date
        base = {'owners': ['语培主办', '留学接收'], 'campaign_name': '活动-语培主办（留学接收）',
                'business_line': 'training', 'business_group': '大学',
                'team_id': 'offline_market', 'event_date': date(2026, 9, 30),
                'counts_toward_completion': True, 'student_id': 'S1'}
        facts = [{**base, 'metric': 'orders', 'value': Decimal(1)},
                 {**base, 'metric': 'cash', 'value': Decimal(10800)},
                 {**base, 'metric': 'cash', 'value': Decimal(8400)}]
        for kind, expected in [('orders', 1), ('cash', 19200), ('heads', 1)]:
            value = _personal_actual(facts, self.roster['语培主办'], 'training', kind,
                                     date(2026, 9, 26), date(2026, 10, 8), self.roster)
            self.assertEqual(value, expected)
        self.assertEqual(_personal_weights(facts[1], 'cash', self.roster), {'语培主办': Decimal(1)})
        self.assertEqual(_personal_actual(facts, self.roster['留学接收'], 'training', 'cash',
                                         date(2026, 9, 26), date(2026, 10, 8), self.roster), 0)

    def test_actual_opposite_business_splits_half_per_side(self):
        names = ['语培主办', '语培共创', '留学接收', '留学接收乙']
        campaign = '语培主办/语培共创（留学接收/留学接收乙）'
        self.assertEqual(activity_co_creation_weights(names, self.roster, 'abroad', campaign),
                         {name: Decimal('0.25') for name in names})
        self.assertEqual(activity_co_creation_weights(names, self.roster, 'training', campaign),
                         {'语培主办': Decimal('0.5'), '语培共创': Decimal('0.5')})

    def test_same_business_brackets_and_virtual_independent_credit(self):
        self.roster['虚拟人'] = {'business_line': 'training', 'team_ids': {'online_private'}}
        self.assertEqual(activity_co_creation_weights(
            ['语培主办', '语培共创', '虚拟人'], self.roster, 'training', '语培主办（语培共创）/虚拟人'),
            {'语培主办': Decimal('0.5'), '语培共创': Decimal('0.5'), '虚拟人': Decimal(1)})

    def test_manual_owner_is_not_expanded_from_activity_names(self):
        self.assertEqual(activity_co_creation_weights(
            ['留学接收'], self.roster, 'abroad', '语培主办（留学接收）'),
            {'留学接收': Decimal(1)})


if __name__ == '__main__':
    unittest.main()
