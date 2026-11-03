"""Regression coverage for the user-confirmed November university abroad targets."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from dashboard_product.management.aggregate import (
    _person_month_target,
    _personal_target,
    _roster,
)


ROOT = Path(__file__).resolve().parents[1]
PEOPLE_PATH = ROOT / 'workspace_modeling/operations/people.json'
NOVEMBER_ABROAD_TARGETS = {
    '师顺盈': 30,
    '石仁达': 32,
    '翟昕羽': 28,
    '曹恒玮': 20,
}
OCTOBER_ABROAD_TARGETS = {
    '师顺盈': 8,
    '石仁达': 9,
    '翟昕羽': 7,
    '曹恒玮': 5,
}


class NovemberAbroadTargetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        people_config = json.loads(PEOPLE_PATH.read_text(encoding='utf-8'))
        cls.people = {
            person['name']: person
            for person in _roster(people_config, {'people': []})
        }

    def test_november_uses_explicit_abroad_targets_for_four_university_people(self):
        targets = {
            name: _person_month_target(self.people[name], '2026-11', 'abroad')
            for name in NOVEMBER_ABROAD_TARGETS
        }

        self.assertEqual(targets, NOVEMBER_ABROAD_TARGETS)
        self.assertEqual(sum(targets.values()), 110)

    def test_october_keeps_the_existing_rounded_ten_percent_rule(self):
        targets = {
            name: _person_month_target(self.people[name], '2026-10', 'abroad')
            for name in OCTOBER_ABROAD_TARGETS
        }

        self.assertEqual(targets, OCTOBER_ABROAD_TARGETS)

    def test_unconfigured_november_abroad_value_falls_back_to_ten_percent(self):
        people_config = {
            'teams': [{
                'team_id': 'offline_market',
                'groups': [{
                    'display_name': '大学组',
                    'members': [{
                        'display_name': '大学回退人员',
                        'status': 'active',
                        'business_group': '大学',
                        'monthly_targets': {'2026-11': {'orders': 85}},
                    }],
                }],
            }],
        }
        person = _roster(people_config, {'people': []})[0]

        self.assertEqual(_person_month_target(person, '2026-11', 'abroad'), 9)

    def test_q2_abroad_target_sums_explicit_november_and_unchanged_month_rules(self):
        quarter = {'kind': 'quarter', 'id': 'Q2'}
        targets = {
            name: _personal_target(self.people[name], quarter, 'abroad')
            for name in NOVEMBER_ABROAD_TARGETS
        }

        self.assertEqual(targets, {
            '师顺盈': 51,
            '石仁达': 49,
            '翟昕羽': 45,
            '曹恒玮': 31,
        })
        self.assertEqual(sum(targets.values()), 176)


if __name__ == '__main__':
    unittest.main()
