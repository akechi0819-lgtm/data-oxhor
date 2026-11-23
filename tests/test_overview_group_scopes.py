from pathlib import Path
import unittest

import duckdb

from dashboard_product.shadow_bi.sql_warehouse.metrics import install_metrics
from dashboard_product.shadow_bi.sql_warehouse.relations import load_rows


ROOT = Path(__file__).resolve().parents[1]
COLUMNS = {
    'fact_id': 'VARCHAR', 'metric': 'VARCHAR', 'business_line': 'VARCHAR',
    'event_date': 'DATE', 'value': 'DECIMAL(24,2)', 'team_id': 'VARCHAR',
    'business_group': 'VARCHAR', 'comparison_group': 'VARCHAR',
    'acquisition_mode': 'VARCHAR', 'student_id': 'VARCHAR', 'student_type': 'VARCHAR',
    'class_code': 'VARCHAR',
    'registration_count': 'DOUBLE', 'segment_id': 'VARCHAR',
    'customer_domain': 'VARCHAR', 'first_channel': 'VARCHAR',
    'school_attribute': 'VARCHAR', 'school_name': 'VARCHAR',
    'channel_school_name': 'VARCHAR', 'owners': 'VARCHAR[]', 'virtual_owners': 'VARCHAR[]',
    'campaign_name': 'VARCHAR', 'order_status': 'VARCHAR',
    'counts_toward_completion': 'BOOLEAN', 'team_inferred': 'BOOLEAN',
}
GROUPS = {
    '留学预备': ('overview_prep', 'prep', 10),
    '高中': ('overview_high', 'high', 100),
    '大学': ('overview_university', 'university', 1000),
}
TARGET_TEAMS = ('offline_market', 'online_private', 'online_platform')


def fact(fact_id, value, *, metric='orders', business_group=None, team_id=None,
         student_id=None, class_code=None, business_line='training',
         segment_id=None, customer_domain=None):
    return {
        'fact_id': fact_id,
        'metric': metric,
        'business_line': business_line,
        'event_date': '2026-06-10',
        'value': value,
        'team_id': team_id,
        'business_group': business_group,
        'comparison_group': business_group,
        'acquisition_mode': '被动',
        'student_id': student_id,
        'student_type': '新生' if metric == 'cash' else None,
        'class_code': class_code,
        'registration_count': 1,
        'segment_id': segment_id,
        'customer_domain': customer_domain,
        'first_channel': None,
        'school_attribute': None,
        'school_name': None,
        'channel_school_name': None,
        'owners': [],
        'virtual_owners': [],
        'campaign_name': None,
        'order_status': None,
        'counts_toward_completion': True,
        'team_inferred': False,
    }


class OverviewGroupScopeTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(':memory:')
        self.addCleanup(self.con.close)
        self.training = []
        channel_values = {
            'offline_market': 1,
            'online_private': 2,
            'online_platform': 3,
            None: 4,
        }
        for group, (_, _, total) in GROUPS.items():
            unit = total // 10
            for team_id, value in channel_values.items():
                self.training.append(fact(
                    f'order:{group}:{team_id or "unassigned"}', value * unit,
                    business_group=group, team_id=team_id,
                ))
        self.training.append(fact('order:unknown-group', 10000,
                                  business_group='其他', team_id='offline_market'))

        # Two classes for one student each reach 1,500 only after channel rows
        # are combined. The selected group must count one distinct student.
        for class_code in ('C1', 'C2'):
            for team_id, value in zip(TARGET_TEAMS, (700, 400, 400)):
                self.training.append(fact(
                    f'cash:shared:{class_code}:{team_id}', value, metric='cash',
                    business_group='高中', team_id=team_id, student_id='shared',
                    class_code=class_code,
                ))

        abroad = [fact('abroad:offline', 1, business_line='abroad',
                       segment_id='study_abroad_offline', customer_domain='study_abroad',
                       team_id='university')]
        load_rows(self.con, 'business', 'training_facts', self.training, columns=COLUMNS)
        load_rows(self.con, 'business', 'training_personnel_facts', self.training, columns=COLUMNS)
        load_rows(self.con, 'business', 'abroad_facts', abroad, columns=COLUMNS)
        install_metrics(
            self.con, through='2026-06-30', abroad_start='2026-06-01',
            abroad_through='2026-06-30', config_root=ROOT,
        )

    def metric(self, unit, line, name, period='FY27', acquisition='被动'):
        return self.con.execute(
            'SELECT actual, target, status FROM business.team_metrics '
            'WHERE period_id=? AND unit_id=? AND acquisition_scope=? '
            'AND business_line=? AND metric=?',
            [period, unit, acquisition, line, name],
        ).fetchone()

    def test_overview_group_facts_are_cross_channel_subsets_and_old_units_stay_offline(self):
        total_ids = {
            row[0] for row in self.con.execute(
                "SELECT fact_id FROM business.scoped_facts "
                "WHERE unit_id='total' AND acquisition_scope='被动'"
            ).fetchall()
        }
        for group, (overview_unit, old_unit, expected_orders) in GROUPS.items():
            selected_ids = {
                row[0] for row in self.con.execute(
                    'SELECT fact_id FROM business.scoped_facts '
                    'WHERE unit_id=? AND acquisition_scope=\'被动\'',
                    [overview_unit],
                ).fetchall()
            }
            expected_ids = {
                row['fact_id'] for row in self.training
                if row['business_group'] == group
            }
            self.assertEqual(selected_ids, expected_ids)
            self.assertTrue(selected_ids <= total_ids)
            self.assertEqual(self.metric(overview_unit, 'training', 'orders')[0], expected_orders)

            # Existing prep/high/university units retain their offline-only scope.
            old_expected = sum(
                row['value'] for row in self.training
                if row['business_group'] == group and row['team_id'] == 'offline_market'
                and row['metric'] == 'orders'
            )
            self.assertEqual(self.metric(old_unit, 'training', 'orders')[0], old_expected)

        self.assertEqual(self.metric('total', 'training', 'orders')[0], 11110)
        self.assertNotIn('order:unknown-group', {
            row[0] for row in self.con.execute(
                "SELECT fact_id FROM business.scoped_facts "
                "WHERE unit_id='overview_prep' AND acquisition_scope='被动'"
            ).fetchall()
        })
        self.assertEqual(self.metric('university', 'abroad', 'orders')[0], 1)

    def test_group_heads_qualify_after_cross_channel_scope_and_deduplicate_students(self):
        self.assertEqual(self.metric('high', 'training', 'heads')[0], 0)
        self.assertEqual(self.metric('overview_high', 'training', 'heads')[0], 1)

    def test_group_targets_sum_three_team_targets_and_require_all_three(self):
        for group, (overview_unit, _, _) in GROUPS.items():
            for metric in ('orders', 'cash'):
                expected = self.con.execute(
                    'SELECT sum(target) FROM config.targets '
                    "WHERE business_line='training' AND business_group=? AND metric=? "
                    "AND team_id IN ('offline_market','online_private','online_platform') "
                    "AND period_id IN ('Q1','Q2','Q3','Q4')",
                    [group, metric],
                ).fetchone()[0]
                actual = self.con.execute(
                    'SELECT target FROM business.team_targets '
                    "WHERE period_id='FY27' AND unit_id=? AND business_line='training' AND metric=?",
                    [overview_unit, metric],
                ).fetchone()[0]
                self.assertEqual(actual, expected)

        self.con.execute(
            "DELETE FROM config.targets WHERE business_line='training' "
            "AND business_group='高中' AND team_id='online_private' "
            "AND period_id='Q1' AND metric='orders'"
        )
        missing_team_target = self.con.execute(
            "SELECT target FROM business.team_targets WHERE period_id='FY27' "
            "AND unit_id='overview_high' AND business_line='training' AND metric='orders'"
        ).fetchone()[0]
        self.assertIsNone(missing_team_target)

        for acquisition in ('主动', '全部'):
            self.assertIsNone(self.metric('overview_prep', 'training', 'orders', acquisition=acquisition)[1])

    def test_abroad_is_unconfigured_for_group_scopes_instead_of_zero(self):
        for unit in ('overview_prep', 'overview_high', 'overview_university'):
            actual, target, status = self.metric(unit, 'abroad', 'orders')
            self.assertIsNone(actual)
            self.assertIsNone(target)
            self.assertEqual(status, 'not_configured')


if __name__ == '__main__':
    unittest.main()
