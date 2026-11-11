from pathlib import Path
import json
import unittest

import duckdb

from dashboard_product.shadow_bi.sql_warehouse.metrics import install_metrics
from dashboard_product.shadow_bi.sql_warehouse.notifications import compile_notifications
from dashboard_product.shadow_bi.sql_warehouse.personal import install_personal
from dashboard_product.shadow_bi.sql_warehouse.relations import load_rows


ROOT = Path(__file__).resolve().parents[1]
FACT_COLUMNS = {
    'fact_id': 'VARCHAR', 'metric': 'VARCHAR', 'business_line': 'VARCHAR',
    'event_date': 'DATE', 'value': 'DECIMAL(24,2)', 'work_order_id': 'VARCHAR',
    'order_status': 'VARCHAR', 'counts_toward_completion': 'BOOLEAN',
    'exclusion_reason': 'VARCHAR', 'source_record': 'JSON', 'student_id': 'VARCHAR',
    'team_id': 'VARCHAR', 'business_group': 'VARCHAR', 'comparison_group': 'VARCHAR',
    'school_name': 'VARCHAR', 'school_attribute': 'VARCHAR', 'school_attribute_status': 'VARCHAR',
    'channel_school_name': 'VARCHAR', 'grade_name': 'VARCHAR', 'campaign_name': 'VARCHAR',
    'first_channel': 'VARCHAR', 'second_channel': 'VARCHAR', 'country': 'VARCHAR', 'line': 'VARCHAR',
    'owners': 'VARCHAR[]', 'virtual_owners': 'VARCHAR[]', 'source_row_number': 'BIGINT',
    'acquisition_mode': 'VARCHAR', 'class_code': 'VARCHAR', 'registration_count': 'DOUBLE',
    'team_inferred': 'BOOLEAN', 'team_before_override': 'VARCHAR', 'team_override_reason': 'VARCHAR',
    'third_channel': 'VARCHAR', 'raw_first_channel': 'VARCHAR', 'raw_second_channel': 'VARCHAR',
    'channel_source': 'VARCHAR', 'channel_mapping_status': 'VARCHAR', 'channel_mapping_rule': 'VARCHAR',
    'source_sha256': 'VARCHAR', 'source_sheet': 'VARCHAR', 'source_filename': 'VARCHAR',
    'source_owner': 'VARCHAR', 'owner': 'VARCHAR', 'source_product': 'VARCHAR',
    'customer_domain': 'VARCHAR', 'resource_id': 'VARCHAR', 'contract_id': 'VARCHAR',
    'customer_key': 'VARCHAR', 'resource_status': 'VARCHAR', 'contract_status': 'VARCHAR',
    'segment_id': 'VARCHAR', 'team_eligible': 'BOOLEAN', 'market_eligible': 'BOOLEAN',
    'personal_eligible': 'BOOLEAN', 'offline_channel_eligible': 'BOOLEAN',
    'intended_stage': 'VARCHAR', 'source_kind': 'VARCHAR',
}


def training_order(fact_id, event_date, owner, group):
    row = {key: None for key in FACT_COLUMNS}
    row.update({
        'fact_id': fact_id, 'metric': 'orders', 'business_line': 'training',
        'event_date': event_date, 'value': 1, 'work_order_id': fact_id,
        'counts_toward_completion': True, 'team_id': 'offline_market',
        'business_group': group, 'comparison_group': group, 'owners': [owner],
        'virtual_owners': [], 'acquisition_mode': '被动', 'team_inferred': False,
        'first_channel': '市场活动', 'second_channel': '线下转介绍',
    })
    return row


class SqlNotificationTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.addCleanup(self.con.close)
        # A fixed configured roster entry keeps the fixture tied to the same SQL ownership path.
        roster = json.loads((ROOT / 'workspace_modeling/operations/people.json').read_text())
        member = next(person for team in roster['teams'] for group in team['groups']
                      for person in group.get('members', [])
                      if person.get('display_name') == '刘彬')
        self.owner = member['display_name']
        self.group = member['business_group']

        rows = [training_order('order-1', '2026-11-02', self.owner, self.group)]
        load_rows(self.con, 'business', 'training_facts', rows, columns=FACT_COLUMNS)
        load_rows(self.con, 'business', 'training_personnel_facts', rows, columns=FACT_COLUMNS)
        load_rows(self.con, 'business', 'abroad_facts', [], columns=FACT_COLUMNS)
        install_metrics(self.con, through='2026-11-05', abroad_start='2026-06-01',
                        abroad_through='2026-11-05', config_root=ROOT)
        install_personal(self.con, config_root=ROOT)

    def test_compiles_eight_channel_payload_from_sql_views(self):
        payload = compile_notifications(
            self.con,
            through='2026-11-05',
            study_abroad_source={
                'start_date': '2026-06-01', 'through_date': '2026-11-05',
                'snapshot_id': 'fixture',
            },
        )

        self.assertEqual(payload['schema_version'], 'management_notifications.v1')
        self.assertEqual(payload['data_through'], '2026-11-05')
        messages = payload['messages']
        self.assertEqual([m['id'] for m in messages], [
            'prep.training', 'high.training', 'high.abroad', 'university.training',
            'university.abroad', 'virtual.mixed', 'online.training', 'online.abroad',
        ])
        self.assertEqual(len(messages), 8)
        high = messages[1]
        self.assertEqual(high['window']['person_start'], '2026-10-26')
        self.assertEqual(high['ledgers']['team_orders'][0]['fact_id'], 'order-1')
        self.assertEqual(high['ledgers']['personal_orders'][0]['person_credits'][self.owner]['value'], 1)
        self.assertEqual(messages[2]['ledgers']['team_orders'], [])
        self.assertEqual(messages[2]['channels'], [])
        self.assertEqual(messages[6]['team_metrics']['orders']['actual'], 0)
        self.assertEqual(messages[6]['team_metrics']['orders']['target'], 439)

        persistent = self.con.execute("""
            SELECT count(*) FROM information_schema.tables
            WHERE table_name LIKE 'notification_%' AND table_catalog <> 'temp'
        """).fetchone()[0]
        self.assertEqual(persistent, 0)

    def test_requires_explicit_abroad_coverage(self):
        with self.assertRaisesRegex(ValueError, 'study_abroad_source coverage is required'):
            compile_notifications(self.con, through='2026-11-05')
        with self.assertRaisesRegex(ValueError, 'must include start_date and through_date'):
            compile_notifications(self.con, through='2026-11-05', study_abroad_source={})


if __name__ == '__main__':
    unittest.main()
