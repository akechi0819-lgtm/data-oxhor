from __future__ import annotations

import hashlib
from datetime import date, datetime
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import load_workbook
from PIL import Image

from monitoring_product.shared_preview import (
    _read_shared_notifications,
    _validate_payload,
    main,
    render_notifications,
)


def metric(actual, target=100, status='available'):
    return {
        'actual': actual,
        'target': target,
        'completion': actual / target if actual is not None and target else None,
        'status': status,
    }


def fact(order_id, *, line='training', kind='orders', value=1, included=True,
         status=None, reason=None, owners=None):
    return {
        'fact_id': f'fact-{order_id}',
        'business_line': line,
        'metric': kind,
        'event_date': '2026-09-28',
        'work_order_id': order_id,
        'value': value,
        'owners': owners or ['大学同事'],
        'order_status': status,
        'counts_toward_completion': included,
        'exclusion_reason': reason,
        'source_row_number': 318,
        'query_run_id': 'must-not-export-query-id',
        'ingest_batch': 'must-not-export-ingest-batch',
        'source_record': {
            'ID': order_id,
            '分配时间': 46293,
            '学员姓名': f'RAW_STUDENT_SECRET_{order_id}',
            'snapshot_id': 'must-not-export-snapshot-field',
            'source_id': 'must-not-export-source-id',
            'source_sha256': 'must-not-export-source-hash',
        },
    }


def notifications_payload():
    message_defs = [
        ('prep.training', 'offline_youth', '线下青少语培', 'training'),
        ('high.training', 'offline_high_school', '线下高中语培', 'training'),
        ('university.training', 'offline_university', '线下大学语培', 'training'),
        ('university.abroad', 'offline_university', '线下大学留学', 'abroad'),
        ('virtual.training', 'online_private', '线上虚拟人语培', 'training'),
        ('online.training', 'online_platform', '线上平台语培', 'training'),
        ('online.abroad', 'online_platform', '线上平台留学', 'abroad'),
    ]
    messages = []
    for message_id, channel_id, title, line in message_defs:
        people = []
        if message_id == 'university.training':
            people = [{
                'name': '大学同事', 'home_group': '大学',
                'orders_target': 10, 'orders_actual': 3, 'orders_completion': 0.3,
                'secondary_business_line': 'abroad', 'secondary_orders_target': 1,
                'secondary_orders_actual': 1, 'secondary_orders_completion': 1,
                'cash_actual': {'actual': 123456.9, 'target': None, 'completion': None, 'status': 'available'},
                'heads_actual': {'actual': 2, 'target': 4, 'completion': 0.5, 'status': 'available'},
                'heads_target': 4, 'heads_completion': 0.5,
                'today_orders': 2, 'expected_orders': 3.1, 'daily_orders': 1.25,
                'remaining_workdays': 19, 'behind': None,
            }]
        elif message_id == 'university.abroad':
            people = [{
                'name': '留学同事', 'home_group': '大学',
                'orders_target': 20, 'orders_actual': 5, 'orders_completion': 0.25,
                'secondary_business_line': 'training', 'secondary_orders_target': 2,
                'secondary_orders_actual': 2, 'secondary_orders_completion': 1,
                'cash_actual': {'actual': None, 'target': None, 'completion': None, 'status': 'not_connected'},
                'heads_actual': {'actual': None, 'target': None, 'completion': None, 'status': 'not_connected'},
                'behind': False, 'today_orders': 1, 'daily_orders': 2.5,
            }]
        orders = [
            fact('included-order', line=line),
            fact('recalled-order', line=line, included=False,
                 status='order_status_recalled', reason='order_status_recalled'),
        ]
        cash = [fact('cash-row', line=line, kind='cash', value=123456.9)] if line == 'training' else []
        person_secondary = [fact('secondary-abroad-order', line='abroad', owners=['大学同事'])]
        messages.append({
            'id': message_id,
            'channel_id': channel_id,
            'business_line': line,
            'title': title,
            'month': '2026-09',
            'window': {
                'team_start': '2026-09-01', 'team_end': '2026-09-30',
                'team_through': '2026-09-28', 'team_progress': 0.93,
                'person_month': '2026-10', 'person_start': '2026-09-26',
                'person_end': '2026-10-25', 'person_through': '2026-09-28',
                'person_progress': 0.1,
            },
            'team_metrics': {
                'orders': {**metric(3, 10), 'daily_actual': 2, 'daily_average': 0.107, 'daily_required': 1.25},
                'cash': metric(123456.9, None, 'available') if line == 'training' else metric(None, None, 'not_connected'),
                'heads': metric(2, None, 'available') if line == 'training' else metric(None, None, 'not_connected'),
            },
            'people': people,
            'channels': [{'first_channel': '市场活动', 'name': '长渠道名称不得进入人员通知',
                          'month': 3, 'today': 2, 'share': 1.0}],
            'ledgers': {
                'personal_orders': orders if people else [],
                'personal_secondary_orders': person_secondary if message_id == 'university.training' else [],
                'team_orders': orders,
                'personal_cash': cash if people else [],
                'team_cash': cash,
            },
        })
    return {
        'schema_version': 'management_notifications.v1',
        'data_through': '2026-09-28',
        'metadata': {
            'run_id': 'run_synthetic_preview',
            'snapshot_id': 'snapshot_synthetic_20260929',
            'data_through': '2026-09-28',
            'as_of_date': '2026-10-01',
            'preview_only': True,
        },
        'messages': messages,
    }


class SharedPreviewTests(unittest.TestCase):
    def test_compact_render_and_relevant_workbooks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = render_notifications(notifications_payload(), root / 'preview',
                                          'http://127.0.0.1:8778')
            self.assertEqual(result['status'], 'preview_ready')
            self.assertEqual(len(result['messages']), 7)
            university = [item for item in result['messages'] if item['id'].startswith('university.')]
            self.assertEqual([item['channel_id'] for item in university],
                             ['offline_university', 'offline_university'])
            self.assertTrue(Path(result['index_html']).is_file())

            online = next(item for item in result['messages'] if item['id'] == 'online.training')
            with Image.open(online['png']) as image:
                self.assertEqual(image.width, 1200)
                self.assertLess(image.height, 800)
            online_html = Path(online['html']).read_text(encoding='utf-8')
            self.assertIn('历史数据预览，未发送', online_html)
            self.assertIn('自然月时间进度', online_html)
            self.assertIn('二级渠道', online_html)
            self.assertNotIn('一级渠道', online_html)
            self.assertNotIn('市场活动', online_html)
            self.assertNotIn('channel_id', online_html)
            self.assertNotIn('RAW_STUDENT_SECRET', online_html)
            self.assertIn('online.html', online['dashboard_url'])

            online_book = load_workbook(online['xlsx'], data_only=True)
            self.assertEqual(online_book.sheetnames, ['进度汇总', '工单明细', '现金明细'])
            self.assertNotIn('团队自然月明细', online_book.sheetnames)
            self.assertNotIn('当月全量原始工单', online_book.sheetnames)
            self.assertNotIn('渠道汇总', online_book.sheetnames)
            online_orders = online_book['工单明细']
            headers = {cell.value: cell.column for cell in online_orders[4]}
            recalled = next(row for row in range(5, online_orders.max_row + 1)
                            if online_orders.cell(row, headers['工单ID']).value == 'recalled-order')
            self.assertEqual(online_orders.cell(recalled, headers['是否计入工单完成']).value, '否')
            self.assertEqual(online_orders.cell(recalled, headers['工单状态']).value, '回收')
            self.assertEqual(online_orders.cell(recalled, headers['不计入原因']).value,
                             '工单状态为回收，不计入工单完成')
            source_date = online_orders.cell(recalled, headers['分配时间']).value
            self.assertIsInstance(source_date, (date, datetime))
            for technical in ('fact_id', 'source_id', 'source_sha256', 'source_row_number', 'query_run_id', 'snapshot_id'):
                self.assertNotIn(technical, headers)
            self.assertEqual(online['dashboard_url'], 'http://127.0.0.1:8778/online.html')

            training = next(item for item in result['messages'] if item['id'] == 'university.training')
            training_book = load_workbook(training['xlsx'], data_only=True)
            self.assertEqual(training_book.sheetnames, ['个人进度', '工单明细', '现金明细'])
            personal = training_book['个人进度']
            personal_headers = {personal.cell(4, col).value: col for col in range(1, personal.max_column + 1)}
            self.assertEqual(personal.cell(5, personal_headers['现金目标(元)']).value, '未配置')
            self.assertAlmostEqual(personal.cell(5, personal_headers['现金完成(元)']).value, 123456.9)
            self.assertEqual(personal.cell(5, personal_headers['另一业务线']).value, '留学')
            self.assertEqual(personal.cell(5, personal_headers['另一业务线工单目标']).value, 1)

            orders = training_book['工单明细']
            order_headers = {cell.value: cell.column for cell in orders[4]}
            secondary = next(row for row in range(5, orders.max_row + 1)
                             if orders.cell(row, order_headers['工单ID']).value == 'secondary-abroad-order')
            self.assertEqual(orders.cell(secondary, order_headers['业务线']).value, '留学')
            self.assertEqual(orders.cell(secondary, order_headers['是否计入工单完成']).value, '是')
            markdown = Path(training['markdown']).read_text(encoding='utf-8')
            self.assertIn('(message.png)', markdown)
            self.assertIn('(details.xlsx)', markdown)
            self.assertIn('http://127.0.0.1:8778/university.html', markdown)
            online_markdown = Path(online['markdown']).read_text(encoding='utf-8')
            self.assertIn('| 二级渠道 | 月累计 | 当日新增 | 占比 |', online_markdown)
            self.assertNotIn('市场活动', online_markdown)

            abroad = next(item for item in result['messages'] if item['id'] == 'university.abroad')
            abroad_html = Path(abroad['html']).read_text(encoding='utf-8')
            self.assertIn('大学留学现金及人头未接入', abroad_html)
            self.assertNotIn('现金完成率', abroad_html)

    def test_channel_mapping_is_validated(self):
        payload = notifications_payload()
        payload['messages'][2]['channel_id'] = 'wrong_channel'
        with self.assertRaisesRegex(ValueError, 'offline_university'):
            _validate_payload(payload)

    def test_shared_result_reference_checks_hash_and_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = notifications_payload()
            payload['metadata'].update({'run_id': 'run_shared', 'snapshot_id': 'snapshot_shared'})
            notifications = root / 'notifications.json'
            notifications.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            shared = {
                'metadata': {'run_id': 'run_shared', 'snapshot_id': 'snapshot_shared', 'data_through': '2026-09-28'},
                'notifications_ref': {'path': 'notifications.json',
                                      'sha256': hashlib.sha256(notifications.read_bytes()).hexdigest()},
            }
            shared_path = root / 'shared_result.json'
            shared_path.write_text(json.dumps(shared), encoding='utf-8')
            _, found = _read_shared_notifications(shared_path)
            self.assertEqual(found['metadata']['run_id'], 'run_shared')
            shared['notifications_ref']['sha256'] = '0' * 64
            shared_path.write_text(json.dumps(shared), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'sha256'):
                _read_shared_notifications(shared_path)

    def test_cli_emits_json_manifest_and_rejects_reference_escape(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = notifications_payload()
            notifications = root / 'notifications.json'
            notifications.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            shared = {
                'metadata': {
                    'run_id': 'run_synthetic_preview', 'snapshot_id': 'snapshot_synthetic_20260929',
                    'data_through': '2026-09-28',
                },
                'notifications_ref': {'path': 'notifications.json',
                                      'sha256': hashlib.sha256(notifications.read_bytes()).hexdigest()},
            }
            shared_path = root / 'shared_result.json'
            shared_path.write_text(json.dumps(shared), encoding='utf-8')
            captured = StringIO()
            with patch('sys.stdout', captured):
                code = main(['--shared-result', str(shared_path), '--output-dir', str(root / 'preview'),
                             '--dashboard-base-url', 'http://127.0.0.1:8778'])
            self.assertEqual(code, 0)
            manifest = json.loads(captured.getvalue())
            self.assertEqual(manifest['status'], 'preview_ready')
            self.assertEqual(len(manifest['messages']), 7)
            self.assertEqual(next(row for row in manifest['messages'] if row['id'] == 'university.training')['channel_id'],
                             'offline_university')

            outside = root.parent / 'notifications.json'
            outside.write_text(notifications.read_text(encoding='utf-8'), encoding='utf-8')
            shared['notifications_ref'] = {
                'path': '../notifications.json', 'sha256': hashlib.sha256(outside.read_bytes()).hexdigest(),
            }
            shared_path.write_text(json.dumps(shared), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'inside'):
                _read_shared_notifications(shared_path)
            outside.unlink(missing_ok=True)


    def test_virtual_mixed_preview_has_no_extra_business_line_columns(self):
        payload = notifications_payload()
        message = next(m for m in payload['messages'] if m['id'].startswith('virtual.'))
        message.update(id='virtual.mixed', business_line='mixed', title='线上虚拟人')
        payload['messages'] = [message]
        with TemporaryDirectory() as directory:
            result = render_notifications(payload, Path(directory))
            item = result['messages'][0]
            self.assertEqual(item['channel_id'], 'online_private')
            book = load_workbook(item['xlsx'], read_only=True, data_only=True)
            try:
                progress_headers = list(book['个人进度'].values)[3]
                self.assertIn('工单目标', progress_headers)
                self.assertNotIn('另一业务线', progress_headers)
                self.assertNotIn('业务线', list(book['工单明细'].values)[3])
            finally:
                book.close()


    def test_expected_progress_preserves_fractional_orders(self):
        payload = notifications_payload()
        message = next(m for m in payload['messages'] if m['id'] == 'university.training')
        message['people'][0]['expected_orders'] = 8.5
        message['people'][0]['behind'] = True
        payload['messages'] = [message]
        with TemporaryDirectory() as directory:
            item = render_notifications(payload, Path(directory))['messages'][0]
            self.assertIn('8.5', Path(item['html']).read_text())
            self.assertIn('应完成 8.5', Path(item['markdown']).read_text())


if __name__ == '__main__':
    unittest.main()
