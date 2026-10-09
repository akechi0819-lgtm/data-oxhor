from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from data_platform.query.evidence import read_query_result, verify_receipt
from data_platform.query.service import execute_query
from dashboard_product.management.build import _confirmed_adviser_lists
from dashboard_product.online_team.build import MAPPING
from tests.evidence_helpers import manifest


ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = 'snapshot_adviser_mapping_test'
WORK_ORDERS = 'br_work_orders__sheet_1f0596db9f25'
CASH = 'br_cash__sheet_39b8dee2e4b3'
EVENT_SERIAL = (date(2026, 6, 5) - date(1899, 12, 30)).days

WORK_ORDER_COLUMNS = [
    ('source_row_number', 'BIGINT'), ('ID', 'VARCHAR'), ('团队', 'VARCHAR'),
    ('跟进顾问', 'VARCHAR'), ('工单状态', 'VARCHAR'), ('分配时间', 'DOUBLE'),
    ('顾问归属', 'VARCHAR'), ('主被动', 'VARCHAR'), ('年级校正', 'VARCHAR'),
    ('线上线下', 'VARCHAR'), ('二级渠道', 'VARCHAR'), ('一级渠道', 'VARCHAR'),
    ('活动名称', 'VARCHAR'), ('学生学校名称', 'VARCHAR'), ('年级名称', 'VARCHAR'),
    ('资源描述', 'VARCHAR'), ('资源录入人', 'VARCHAR'), ('资源主被动', 'VARCHAR'),
    ('咨询方式一级渠道', 'VARCHAR'), ('渠道', 'VARCHAR'), ('其他转介绍人', 'VARCHAR'),
    ('所在学校', 'VARCHAR'), ('年级属性', 'VARCHAR'), ('目前年级', 'VARCHAR'),
]
CASH_COLUMNS = [
    ('source_row_number', 'BIGINT'), ('工单ID', 'VARCHAR'), ('业务日期', 'DOUBLE'),
    ('团队', 'VARCHAR'), ('渠道', 'VARCHAR'), ('市场活动名称', 'VARCHAR'),
    ('生源校', 'VARCHAR'), ('学员年级', 'VARCHAR'), ('学员编号', 'VARCHAR'),
    ('报入现金收入', 'VARCHAR'), ('渠道属性', 'VARCHAR'), ('新老生类型', 'VARCHAR'),
]


def work_order(row_number, work_order_id, adviser, team='', event_serial=EVENT_SERIAL):
    return {
        'source_row_number': row_number, 'ID': work_order_id, '团队': team,
        '跟进顾问': adviser, '工单状态': '', '分配时间': event_serial,
        '顾问归属': '', '主被动': '被动', '年级校正': '', '线上线下': '线上',
        '二级渠道': '合成渠道', '一级渠道': '市场活动', '活动名称': '',
        '学生学校名称': '', '年级名称': '', '资源描述': '', '资源录入人': '',
        '资源主被动': '被动', '咨询方式一级渠道': '市场活动-高校',
        '渠道': '高校活动', '其他转介绍人': '', '所在学校': '', '年级属性': '',
        '目前年级': '',
    }


class AdviserMappingQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'warehouse.duckdb'
        self.output = self.root / 'controlled-query-evidence'
        self.mapping_config = json.loads(MAPPING.read_text(encoding='utf-8'))
        self.mappings = self.mapping_config['mappings']
        study_advisers = [row for row in self.mappings if row['labeled_team'] == '留学']
        prep_advisers = [row for row in self.mappings if row['labeled_team'] == '留学预备']

        work_rows = [
            work_order(i + 1, f'T-mapped-{i:02}', row['source_adviser'])
            for i, row in enumerate(self.mappings)
        ]
        prep_adviser = prep_advisers[0]['source_adviser']
        study_adviser = study_advisers[0]['source_adviser']
        work_rows.extend([
            work_order(60, 'T-existing-team', prep_adviser, '大学'),
            work_order(61, 'T-unknown', '合成未知顾问'),
            work_order(62, 'T-added-prep', '合成新增预备顾问'),
            work_order(63, 'T-added-study', '合成新增留学顾问'),
            work_order(64, 'T-nonempty-high', study_adviser, '高中'),
        ])
        with duckdb.connect(str(self.db)) as connection:
            connection.execute('CREATE SCHEMA ingest')
            connection.execute('CREATE SCHEMA landing')
            connection.execute('CREATE SCHEMA quality')
            connection.execute('CREATE SCHEMA queries')
            connection.execute('CREATE TABLE ingest.sources(source_id VARCHAR, snapshot_id VARCHAR)')
            connection.execute('CREATE TABLE ingest.sheets(source_id VARCHAR, target_table VARCHAR, header_columns JSON)')
            connection.execute('INSERT INTO ingest.sources VALUES (?, ?), (?, ?)',
                               ['synthetic_work_orders', SNAPSHOT, 'synthetic_cash', SNAPSHOT])
            connection.execute('INSERT INTO ingest.sheets VALUES (?, ?, ?), (?, ?, ?)', [
                'synthetic_work_orders', WORK_ORDERS, '[]', 'synthetic_cash', CASH, '[]',
            ])
            connection.execute(self._create_table(WORK_ORDERS, WORK_ORDER_COLUMNS))
            connection.execute(self._create_table(CASH, CASH_COLUMNS))
            self._insert_rows(connection, WORK_ORDERS, WORK_ORDER_COLUMNS, work_rows)
            connection.execute(f'INSERT INTO landing."{CASH}" VALUES ({", ".join("?" for _ in CASH_COLUMNS)})',
                               [None] * len(CASH_COLUMNS))
        manifest(self.db, SNAPSHOT)

    @staticmethod
    def _create_table(table, columns):
        declaration = ', '.join(f'"{name}" {kind}' for name, kind in columns)
        return f'CREATE TABLE landing."{table}" ({declaration})'

    @staticmethod
    def _insert_rows(connection, table, columns, rows):
        names = ', '.join(f'"{name}"' for name, _ in columns)
        values = ', '.join('?' for _ in columns)
        sql = f'INSERT INTO landing."{table}" ({names}) VALUES ({values})'
        connection.executemany(sql, [[row[name] for name, _ in columns] for row in rows])

    def run_training_query(self, mapping_config):
        study_advisers, prep_advisers = _confirmed_adviser_lists(mapping_config)
        sql_path = ROOT / 'dashboard_product/management/sql/training_details.sql'
        parameters = ['2026-06-01', '2026-06-10', '2026-06-01', study_advisers, prep_advisers]
        result = execute_query(
            warehouse=self.db, snapshot_id=SNAPSHOT, sql=sql_path.read_text(encoding='utf-8'),
            parameters=parameters, run_id='run_adviser_mapping_test', output_root=self.output,
            max_rows=1000, max_result_bytes=2_000_000,
        )
        receipt_path = self.output / result['run_id'] / result['receipt']['path']
        receipt, _ = verify_receipt(receipt_path)
        expected_relations = [f'landing.{CASH}', f'landing.{WORK_ORDERS}']
        self.assertEqual(receipt['referenced_relations'], expected_relations)
        data = read_query_result(result, output_root=self.output)
        return [dict(zip(data['columns'], row)) for row in data['rows']], receipt

    @staticmethod
    def rows_by_id(rows):
        return {row['work_order_id']: row for row in rows}

    def test_existing_confirmed_mapping_matches_prior_rule(self):
        training, training_receipt = self.run_training_query(self.mapping_config)
        training_by_id = self.rows_by_id(training)
        expected_training = {
            f'T-mapped-{i:02}': ('初中' if row['labeled_team'] == '留学预备' else '业务组暂无法拆分')
            for i, row in enumerate(self.mappings)
        }
        expected_training.update({
            'T-existing-team': '大学', 'T-unknown': '业务组暂无法拆分',
            'T-added-prep': '业务组暂无法拆分', 'T-added-study': '业务组暂无法拆分',
            'T-nonempty-high': '高中',
        })
        self.assertEqual({key: value['business_group'] for key, value in training_by_id.items()}, expected_training)
        self.assertEqual(len(training_receipt['referenced_relations']), 2)

    def test_mapping_additions_and_removals_change_bi_training_sql_result(self):
        expanded = json.loads(json.dumps(self.mapping_config, ensure_ascii=False))
        expanded['mappings'].extend([
            {'source_adviser': '合成新增预备顾问', 'labeled_team': '留学预备'},
            {'source_adviser': '合成新增留学顾问', 'labeled_team': '留学'},
        ])
        expanded_training, _ = self.run_training_query(expanded)
        base_training, _ = self.run_training_query(self.mapping_config)
        self.assertEqual(self.rows_by_id(expanded_training)['T-added-prep']['business_group'], '初中')
        self.assertEqual(self.rows_by_id(base_training)['T-added-prep']['business_group'], '业务组暂无法拆分')

        removed = json.loads(json.dumps(self.mapping_config, ensure_ascii=False))
        removed['mappings'] = [
            row for row in removed['mappings']
            if row['source_adviser'] not in {
                next(row['source_adviser'] for row in self.mappings if row['labeled_team'] == '留学'),
                next(row['source_adviser'] for row in self.mappings if row['labeled_team'] == '留学预备'),
            }
        ]
        removed_training, _ = self.run_training_query(removed)
        self.assertEqual(self.rows_by_id(removed_training)['T-mapped-00']['business_group'], '业务组暂无法拆分')

    def test_nonempty_teams_are_preserved_and_unknown_advisers_remain_unmapped(self):
        training, _ = self.run_training_query(self.mapping_config)
        training_by_id = self.rows_by_id(training)
        self.assertEqual(training_by_id['T-existing-team']['business_group'], '大学')
        self.assertEqual(training_by_id['T-nonempty-high']['business_group'], '高中')
        self.assertEqual(training_by_id['T-unknown']['business_group'], '业务组暂无法拆分')



if __name__ == '__main__':
    unittest.main()
