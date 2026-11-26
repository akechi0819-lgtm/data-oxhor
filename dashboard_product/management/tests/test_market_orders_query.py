from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from data_platform.query.evidence import read_query_result, verify_receipt
from data_platform.query.service import execute_query
MAPPING = Path(__file__).resolve().parents[2] / 'online_team/config/confirmed_team_mapping.json'
from tests.evidence_helpers import manifest


ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = 'snapshot_market_orders_query_test'
WORK_ORDERS = 'br_work_orders__sheet_1f0596db9f25'
EPOCH = date(1899, 12, 30)
WORK_ORDER_COLUMNS = [
    ('source_row_number', 'BIGINT'), ('ID', 'VARCHAR'), ('分配时间', 'DOUBLE'),
    ('团队', 'VARCHAR'), ('顾问归属', 'VARCHAR'), ('跟进顾问', 'VARCHAR'),
    ('主被动', 'VARCHAR'), ('工单状态', 'VARCHAR'), ('年级校正', 'VARCHAR'),
    ('线上线下', 'VARCHAR'), ('二级渠道', 'VARCHAR'), ('一级渠道', 'VARCHAR'),
    ('活动名称', 'VARCHAR'), ('学生学校名称', 'VARCHAR'), ('年级名称', 'VARCHAR'),
    ('资源描述', 'VARCHAR'), ('资源录入人', 'VARCHAR'),
]


def work_order(row_number, work_order_id, day, adviser, team=None, status='有效'):
    return {
        'source_row_number': row_number,
        'ID': work_order_id,
        '分配时间': (date.fromisoformat(day) - EPOCH).days,
        '团队': team,
        '顾问归属': '',
        '跟进顾问': adviser,
        '主被动': '被动',
        '工单状态': status,
        '年级校正': '',
        '线上线下': '线上',
        '二级渠道': '合成渠道',
        '一级渠道': '市场活动',
        '活动名称': '',
        '学生学校名称': '',
        '年级名称': '',
        '资源描述': '',
        '资源录入人': '',
    }


class MarketOrdersQueryTests(unittest.TestCase):
    def test_confirmed_study_orders_are_removed_after_authoritative_id_dedup(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        warehouse = root / 'warehouse.duckdb'
        output = root / 'controlled-query-evidence'

        mapping = json.loads(MAPPING.read_text(encoding='utf-8'))['mappings']
        study_advisers = [row['source_adviser'] for row in mapping
                          if row['labeled_team'] == '留学']
        prep_adviser = next(row['source_adviser'] for row in mapping
                            if row['labeled_team'] == '留学预备')
        study_adviser = study_advisers[0]
        unknown_adviser = '合成未知顾问'

        rows = [
            work_order(1, 'excluded-team-current', '2026-10-02', unknown_adviser, '留学'),
            work_order(2, 'excluded-adviser-current-empty', '2026-10-03', study_adviser, ''),
            work_order(3, 'excluded-adviser-current-null', '2026-10-04', study_adviser, None),
            work_order(4, 'prep-current', '2026-10-05', prep_adviser, '留学预备'),
            work_order(5, 'training-team-kept', '2026-10-06', study_adviser, '高中'),
            work_order(6, 'unknown-adviser-kept', '2026-10-07', unknown_adviser, ''),
            work_order(7, 'undetermined-team-kept', '2026-10-08', unknown_adviser, '无法判断'),
            work_order(8, 'campus-unowned-kept', '2026-10-09', unknown_adviser, '校区资源无法归属'),
            work_order(9, 'deleted-kept', '2026-10-10', unknown_adviser, '', '删除'),
            work_order(10, 'recovered-kept', '2026-10-11', unknown_adviser, '大学', '回收'),
            # The first source row is authoritative. A later training row must not
            # restore this ID after its confirmed-study first row is excluded.
            work_order(11, 'duplicate-study-first', '2026-10-06', study_adviser, ''),
            work_order(12, 'duplicate-study-first', '2026-10-06', unknown_adviser, '高中'),
            # Conversely, a later study row cannot displace a kept first row.
            work_order(13, 'duplicate-training-first', '2026-10-06', unknown_adviser, '高中'),
            work_order(14, 'duplicate-training-first', '2026-10-06', unknown_adviser, '留学'),
            work_order(15, 'excluded-team-prior', '2025-10-02', unknown_adviser, '留学'),
            work_order(16, 'excluded-adviser-prior', '2025-10-03', study_adviser, ''),
            work_order(17, 'prep-prior', '2025-10-04', prep_adviser, '留学预备'),
            work_order(18, 'unknown-prior', '2025-10-05', unknown_adviser, None),
            work_order(19, 'deleted-prior', '2025-10-06', unknown_adviser, '', '删除'),
            work_order(20, 'recovered-prior', '2025-10-07', unknown_adviser, '大学', '回收'),
        ]

        with duckdb.connect(str(warehouse)) as connection:
            connection.execute('CREATE SCHEMA ingest')
            connection.execute('CREATE SCHEMA landing')
            connection.execute('CREATE SCHEMA quality')
            connection.execute('CREATE SCHEMA queries')
            connection.execute(
                'CREATE TABLE ingest.sources(source_id VARCHAR, snapshot_id VARCHAR)'
            )
            connection.execute(
                'CREATE TABLE ingest.sheets(source_id VARCHAR, target_table VARCHAR, header_columns JSON)'
            )
            connection.execute('INSERT INTO ingest.sources VALUES (?, ?)',
                               ['synthetic_work_orders', SNAPSHOT])
            connection.execute('INSERT INTO ingest.sheets VALUES (?, ?, ?)',
                               ['synthetic_work_orders', WORK_ORDERS, '[]'])
            declaration = ', '.join(f'"{name}" {kind}'
                                    for name, kind in WORK_ORDER_COLUMNS)
            connection.execute(f'CREATE TABLE landing."{WORK_ORDERS}" ({declaration})')
            names = ', '.join(f'"{name}"' for name, _ in WORK_ORDER_COLUMNS)
            values = ', '.join('?' for _ in WORK_ORDER_COLUMNS)
            connection.executemany(
                f'INSERT INTO landing."{WORK_ORDERS}" ({names}) VALUES ({values})',
                [[row[name] for name, _ in WORK_ORDER_COLUMNS] for row in rows],
            )
        manifest(warehouse, SNAPSHOT)

        sql_path = ROOT / 'dashboard_product/management/sql/market_orders.sql'
        result = execute_query(
            warehouse=warehouse,
            snapshot_id=SNAPSHOT,
            sql=sql_path.read_text(encoding='utf-8'),
            parameters=['2025-10-01', '2026-10-12'],
            run_id='run_market_orders_test',
            output_root=output,
            max_rows=1000,
            max_result_bytes=2_000_000,
        )
        receipt_path = output / result['run_id'] / result['receipt']['path']
        receipt, _ = verify_receipt(receipt_path)
        self.assertEqual(receipt['referenced_relations'], [f'landing.{WORK_ORDERS}'])
        data = read_query_result(result, output_root=output)
        queried = [dict(zip(data['columns'], row)) for row in data['rows']]

        ids = [row['work_order_id'] for row in queried]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {
            'prep-current', 'training-team-kept',
            'undetermined-team-kept', 'campus-unowned-kept',
            'recovered-kept', 'duplicate-training-first', 'prep-prior',
            'recovered-prior',
        })
        by_id = {row['work_order_id']: row for row in queried}
        self.assertEqual(by_id['prep-current']['business_group'], '初中')
        self.assertEqual(by_id['prep-prior']['business_group'], '初中')
        self.assertEqual(by_id['training-team-kept']['business_group'], '高中')
        self.assertEqual(by_id['duplicate-training-first']['business_group'], '高中')
        self.assertEqual(by_id['undetermined-team-kept']['business_group'], '业务组暂无法拆分')
        self.assertEqual(by_id['campus-unowned-kept']['business_group'], '业务组暂无法拆分')
        self.assertEqual(by_id['recovered-kept']['business_group'], '大学')
        self.assertEqual(by_id['recovered-prior']['business_group'], '大学')


if __name__ == '__main__':
    unittest.main()
