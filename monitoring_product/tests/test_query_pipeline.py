"""Synthetic warehouse only: exercise the real controlled CLI and notification SQL."""
import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import duckdb

from monitoring_product.notify import send


class QueryPipelineTest(unittest.TestCase):
    def test_snapshot_to_files_with_cross_month_cash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Work').mkdir()
            warehouse = root / 'Work' / 'warehouse.duckdb'
            sid = 'snapshot_monitor_fixture'
            (root / 'Work' / 'workspace.json').write_text(json.dumps({
                'current_snapshot_id': sid, 'current_warehouse_path': 'Work/warehouse.duckdb',
            }))
            orders = ['ID', '分配时间', '线上线下', '二级渠道', '一级渠道', '活动名称',
                      '资源描述', '团队', '跟进顾问', '年级校正', '顾问归属', '主被动',
                      '资源录入人', 'source_row_number']
            cash = ['工单ID', '业务日期', '市场活动名称', '渠道', '团队', '渠道属性',
                    '新老生类型', '报入现金收入', '学员编号', 'source_row_number']
            serial = lambda day: str((date.fromisoformat(day) - date(1899, 12, 30)).days)
            with duckdb.connect(str(warehouse)) as db:
                db.execute('CREATE SCHEMA ingest')
                db.execute('CREATE SCHEMA landing')
                db.execute('CREATE TABLE ingest.sources(source_id VARCHAR, snapshot_id VARCHAR)')
                db.execute('CREATE TABLE ingest.sheets(source_id VARCHAR, target_table VARCHAR, header_columns JSON)')
                for source, table, columns in [
                    ('br_work_orders', 'br_work_orders__sheet_1f0596db9f25', orders),
                    ('br_cash', 'br_cash__sheet_39b8dee2e4b3', cash),
                ]:
                    db.execute('INSERT INTO ingest.sources VALUES (?, ?)', [source, sid])
                    headers = [{'technical_name': c, 'original_name': c} for c in columns]
                    db.execute('INSERT INTO ingest.sheets VALUES (?, ?, ?)', [source, table, json.dumps(headers)])
                    db.execute('CREATE TABLE landing.' + table + '(' + ','.join('"' + c + '" VARCHAR' for c in columns) + ')')
                for identifier, day in [('current', '2026-09-01'), ('historical', '2026-07-01')]:
                    row = [identifier, serial(day), '线上', '校代', 'TMK激活-平台', '校代系统资源',
                           '市场人员：李进', '大学', '', '', '大学顾问', '被动', '', identifier]
                    db.execute('INSERT INTO landing.br_work_orders__sheet_1f0596db9f25 VALUES (' + ','.join('?' for _ in row) + ')', row)
                db.execute('INSERT INTO landing.br_cash__sheet_39b8dee2e4b3 VALUES (?,?,?,?,?,?,?,?,?,?)',
                           ['historical', serial('2026-09-02'), '校代系统资源', 'TMK', '大学', '被动', '新生', '200', 'student1', '1'])
            from tests.evidence_helpers import manifest
            manifest(warehouse, sid)
            before = hashlib.sha256(warehouse.read_bytes()).hexdigest()
            with mock.patch.dict('os.environ', {'NOTIFY_FORCE_PIL': '1'}), \
                 mock.patch('monitoring_product.notify.post_dingtalk') as posted, \
                 mock.patch('monitoring_product.notify.upload_notify_assets') as uploaded:
                result = send(root, snapshot_id=sid, run_id='run_monitor_fixture',
                              as_of_date='2026-09-16', data_through_date='2026-09-15',
                              team_ids=['offline_university'], dry_run=True)
            posted.assert_not_called()
            uploaded.assert_not_called()
            self.assertEqual(before, hashlib.sha256(warehouse.read_bytes()).hexdigest())
            output = Path(result['output_dir'])
            evidence = json.loads((output / 'evidence.json').read_text())
            person = next(p for p in evidence['digests'][0]['people'] if p['display_name'] == '李进')
            self.assertEqual(person['orders_actual'], 1)
            self.assertEqual(person['cash_actual'], 200)
            self.assertEqual(person['heads_actual'], 1)
            self.assertTrue((output / '_query' / 'run_monitor_fixture_offline_university_orders_by_id').is_dir())
            self.assertGreater((output / 'offline_university' / 'people.png').stat().st_size, 0)
            self.assertGreater((output / 'offline_university' / 'details.xlsx').stat().st_size, 0)
