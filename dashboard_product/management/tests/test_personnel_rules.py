"""Shared personnel attribution rules."""
from decimal import Decimal
import unittest

from workspace_modeling.operations.personnel import co_creation_weights


def roster_row(*team_ids, status=None):
    row = {'team_ids': set(team_ids)}
    if status is not None:
        row['status'] = status
    return row


class CoCreationWeightsTests(unittest.TestCase):
    def test_two_offline_members_split_while_virtual_member_is_full_weight(self):
        roster = {
            '线下甲': roster_row('offline_market'),
            '线下乙': roster_row('offline_market'),
            '虚拟甲': roster_row('online_private'),
        }

        self.assertEqual(
            co_creation_weights(['线下甲', '虚拟甲', '线下乙', '线下甲'], roster),
            {'线下甲': Decimal('0.5'), '线下乙': Decimal('0.5'), '虚拟甲': Decimal(1)},
        )

    def test_single_offline_and_virtual_or_virtual_pair_each_get_full_weight(self):
        roster = {
            '线下甲': roster_row('offline_market'),
            '虚拟甲': roster_row('online_private'),
            '虚拟乙': roster_row('online_private'),
        }

        self.assertEqual(
            co_creation_weights(['线下甲', '虚拟甲'], roster),
            {'线下甲': Decimal(1), '虚拟甲': Decimal(1)},
        )
        self.assertEqual(
            co_creation_weights(['虚拟甲', '虚拟乙'], roster),
            {'虚拟甲': Decimal(1), '虚拟乙': Decimal(1)},
        )

    def test_hidden_and_unknown_names_do_not_dilute_pending_roster_members(self):
        roster = {
            '在职甲': roster_row('offline_market'),
            '在职乙': roster_row('offline_market'),
            '待确认': roster_row('offline_market', status='pending'),
            '待替补': roster_row('offline_market', status='pending_replacement'),
            '未填写状态': roster_row('offline_market'),
            '离职': roster_row('offline_market', status='departed'),
            '转岗': roster_row('offline_market', status='transferred'),
            '空缺': roster_row('offline_market', status='vacant'),
        }

        weights = co_creation_weights(
            ['在职甲', '在职乙', '待确认', '待替补', '未填写状态',
             '离职', '转岗', '空缺', '未知人员'],
            roster,
        )
        expected = Decimal(1) / Decimal(5)
        self.assertEqual(weights, {
            '在职甲': expected,
            '在职乙': expected,
            '待确认': expected,
            '待替补': expected,
            '未填写状态': expected,
        })
        self.assertEqual(
            co_creation_weights(['在职甲', '在职乙', '离职'], roster),
            {'在职甲': Decimal('0.5'), '在职乙': Decimal('0.5')},
        )

    def test_virtual_members_are_not_counted_in_offline_denominator(self):
        roster = {
            '线下甲': roster_row('offline_market'),
            '线上兼任': roster_row('offline_market', 'online_private'),
        }

        self.assertEqual(
            co_creation_weights(['线下甲', '线上兼任'], roster),
            {'线下甲': Decimal(1), '线上兼任': Decimal(1)},
        )


if __name__ == '__main__':
    unittest.main()
