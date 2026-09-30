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
                           '市场人员：师顺盈', '大学', '', '', '大学顾问', '被动', '', identifier]
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
            person = next(p for p in evidence['digests'][0]['people'] if p['display_name'] == '师顺盈')
            self.assertEqual(person['orders_actual'], 1)
            self.assertEqual(person['cash_actual'], 200)
            self.assertEqual(person['heads_actual'], 1)
            self.assertTrue((output / '_query' / 'run_monitor_fixture_offline_university_orders_by_id').is_dir())
            self.assertGreater((output / 'offline_university' / 'people.png').stat().st_size, 0)
            self.assertGreater((output / 'offline_university' / 'details.xlsx').stat().st_size, 0)

    def test_school_agent_note_boundary_routes_orders_and_cash_consistently(self):
        root = Path(__file__).resolve().parents[2]
        sql_dir = root / 'monitoring_product' / 'sql'
        order_columns = [
            'ID', '分配时间', '线上线下', '二级渠道', '一级渠道', '活动名称',
            '资源描述', '团队', '跟进顾问', '年级校正', '顾问归属', '主被动',
            '资源录入人', 'source_row_number',
        ]
        cash_columns = [
            '工单ID', '业务日期', '市场活动名称', '渠道', '团队', '渠道属性',
            '新老生类型', '报入现金收入', '学员编号', 'source_row_number',
        ]
        serial = lambda day: str((date.fromisoformat(day) - date(1899, 12, 30)).days)
        people = [
            ('liu', '刘彬', '高中', '高中顾问', '高中', '备注：校代备注提到石仁达'),
            ('ma', '马澳', '青少', '青少顾问', '青少', '备注:备注里提到刘彬'),
            ('shi', '石仁达', '大学', '大学顾问', '大学', '备注：备注里提到刘彬'),
        ]
        order_rows = []
        cash_rows = []
        for identifier, person_name, source_team, adviser, cash_team, suffix in people:
            order_rows.append([
                identifier, serial('2026-09-01'), '线上', '校代', 'TMK激活-平台',
                '2027财年第4财月91校代系统资源活动',
                f'市场人员：{person_name}{suffix}', source_team, '', '', adviser,
                '被动', '', identifier,
            ])
            cash_rows.append([
                identifier, serial('2026-09-01'), '校代系统资源活动', 'TMK', cash_team,
                '被动', '新生', '100', f'student_{identifier}', identifier,
            ])

        negatives = [
            ('note_other', '未知人员备注：石仁达', 'TMK激活-平台', '校代系统资源活动', '大学', '大学顾问', '大学'),
            ('no_tmk', '市场人员：刘彬备注：保留线上', '平台', '校代系统资源活动', '高中', '高中顾问', '高中'),
            ('no_school_agent', '市场人员：马澳备注：保留线上', 'TMK激活-平台', '普通活动', '青少', '青少顾问', '青少'),
        ]
        for identifier, description, first_channel, campaign, source_team, adviser, cash_team in negatives:
            order_rows.append([
                identifier, serial('2026-09-01'), '线上', '校代', first_channel, campaign,
                description, source_team, '', '', adviser, '被动', '', identifier,
            ])
            cash_rows.append([
                identifier, serial('2026-09-01'), campaign, 'TMK', cash_team,
                '被动', '新生', '100', f'student_{identifier}', identifier,
            ])

        with duckdb.connect() as db:
            db.execute('CREATE SCHEMA landing')
            for table, columns, rows in (
                ('br_work_orders__sheet_1f0596db9f25', order_columns, order_rows),
                ('br_cash__sheet_39b8dee2e4b3', cash_columns, cash_rows),
            ):
                db.execute(
                    'CREATE TABLE landing.' + table + '(' +
                    ','.join('"' + column + '" VARCHAR' for column in columns) + ')'
                )
                db.executemany(
                    'INSERT INTO landing.' + table + ' VALUES (' +
                    ','.join('?' for _ in columns) + ')', rows,
                )

            def selected_ids(filename, team_id, business_group):
                params = ['2026-09-01', '2026-09-02', team_id, business_group]
                cursor = db.execute((sql_dir / filename).read_text(encoding='utf-8'), params)
                names = [column[0] for column in cursor.description]
                id_column = 'ID' if filename == 'notify_work_orders.sql' else '工单ID'
                return {row[names.index(id_column)] for row in cursor.fetchall()}

            for name, group in (('liu', '高中'), ('ma', '留学预备'), ('shi', '大学')):
                expected = {name}
                self.assertEqual(selected_ids('notify_work_orders.sql', 'offline_market', group), expected)
                self.assertEqual(selected_ids('notify_cash.sql', 'offline_market', group), expected)

            expected_online = {'note_other', 'no_tmk', 'no_school_agent'}
            self.assertEqual(selected_ids('notify_work_orders.sql', 'online_platform', None), expected_online)
            self.assertEqual(selected_ids('notify_cash.sql', 'online_platform', None), expected_online)
