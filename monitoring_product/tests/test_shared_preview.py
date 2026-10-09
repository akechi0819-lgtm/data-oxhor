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
    _count,
    _employee_columns,
    _employee_values,
    _hours,
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
         status=None, reason=None, owners=None, person_credits=None):
    record = {
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
    if person_credits is not None:
        record['person_credits'] = person_credits
    return record


def notifications_payload():
    message_defs = [
        ('prep.training', 'offline_youth', '线下青少语培', 'training'),
        ('high.training', 'offline_high_school', '线下高中语培', 'training'),
        ('high.abroad', 'offline_high_school', '高中留学', 'abroad'),
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
        elif message_id == 'high.abroad':
            people = [{
                'name': '马玥', 'home_group': '高中',
                'orders_target': None, 'orders_actual': 1.5, 'orders_completion': None,
                'cash_actual': {'actual': None, 'target': None, 'completion': None, 'status': 'not_connected'},
                'heads_actual': {'actual': None, 'target': None, 'completion': None, 'status': 'not_connected'},
                'behind': False, 'today_orders': 0.5, 'expected_orders': None,
                'daily_orders': None,
            }]
        orders = [
            fact('included-order', line=line),
            fact('recalled-order', line=line, included=False,
                 status='order_status_recalled', reason='order_status_recalled'),
            fact('weighted-order', line=line, value=100, person_credits={
                '大学同事': {'weight': 0.5, 'value': 50},
                '另一位同事': {'weight': 0.5, 'value': 50},
            }),
        ]
        cash = [fact('cash-row', line=line, kind='cash', value=123456.9, person_credits={
            '大学同事': {'weight': 0.5, 'value': 61728.45},
            '另一位同事': {'weight': 0.5, 'value': 61728.45},
        })] if line == 'training' else []
        person_secondary = [fact('secondary-abroad-order', line='abroad', owners=['大学同事'])]
        channels = [{'first_channel': '市场活动', 'name': '长渠道名称不得进入人员通知',
                     'month': 3, 'today': 2, 'share': 1.0}]
        if message_id == 'high.abroad':
            own_order = fact('ma-own', line='abroad', value=1, owners=['马玥'],
                             person_credits={'马玥': {'weight': 1, 'value': 1}})
            own_order['event_date'] = '2026-09-27'
            orders = [
                fact('ma-cocreate', line='abroad', value=1, owners=['马玥', '共创同事'],
                     person_credits={'马玥': {'weight': 0.5, 'value': 0.5}}),
                own_order,
            ]
            channels = [
                {'name': '合作院校', 'month': 0.5, 'today': 0.5, 'share': 1 / 3},
                {'name': '转介绍', 'month': 1, 'today': 0, 'share': 2 / 3},
            ]
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
            'team_metrics': {} if message_id == 'high.abroad' else {
                'orders': {**metric(3, 10), 'daily_actual': 2, 'daily_average': 0.107, 'daily_required': 1.25},
                'cash': metric(123456.9, None, 'available') if line == 'training' else metric(None, None, 'not_connected'),
                'heads': metric(2, None, 'available') if line == 'training' else metric(None, None, 'not_connected'),
            },
            'people': people,
            'channels': channels,
            'ledgers': {
                'personal_orders': orders if people else [],
                'personal_secondary_orders': person_secondary if message_id == 'university.training' else [],
                'team_orders': [] if message_id == 'high.abroad' else orders,
                'personal_cash': cash if people else [],
                'team_cash': [] if message_id == 'high.abroad' else cash,
            },
            **({'personal_only': True} if message_id == 'high.abroad' else {}),
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
    def test_fractional_counts_keep_up_to_two_decimal_places(self):
        self.assertEqual(_count(1), '1')
        self.assertEqual(_count(0.5), '0.5')
        self.assertEqual(_count(1 / 3), '0.33')
        self.assertEqual(_hours(1), '1')
        self.assertEqual(_hours(0.5), '0.5')
        self.assertEqual(_hours(1 / 3), '0.33')

    def test_compact_render_and_relevant_workbooks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = notifications_payload()
            abroad_message = next(message for message in payload['messages']
                                  if message['id'] == 'university.abroad')
            abroad_message['source_coverage'] = {
                'start_date': '2026-09-01', 'through_date': '2026-09-30',
                'snapshot_id': 'snapshot_abroad_display_fixture',
            }
            abroad_message['team_metrics']['cash'] = {
                'actual': 23456.78, 'target': 50000, 'completion': None, 'status': 'partial',
            }
            abroad_message['team_metrics']['heads'] = {
                'actual': None, 'target': None, 'completion': None,
                'status': 'separate_counts', 'display': '留学36人／小语种71人',
                'parts': [{'label': '留学', 'actual': 36}, {'label': '小语种', 'actual': 71}],
            }
            abroad_person = abroad_message['people'][0]
            abroad_person['abroad_source_coverage'] = dict(abroad_message['source_coverage'])
            abroad_person['cash_actual'] = dict(abroad_message['team_metrics']['cash'])
            abroad_person['heads_actual'] = dict(abroad_message['team_metrics']['heads'])
            abroad_message['ledgers']['personal_cash'] = [{
                'fact_id': 'abroad-cash-resource-fact', 'business_line': 'abroad',
                'metric': 'cash', 'event_date': '2026-09-15', 'work_order_id': None,
                'resource_id': 'RES-ABROAD-2026-001', 'value': 23456.78,
                'owners': ['留学同事'], 'counts_toward_completion': True,
                'source_record': {'资源ID': 'RES-ABROAD-2026-001', '合同编号': 'CONTRACT-001'},
            }]
            result = render_notifications(payload, root / 'preview',
                                          'http://127.0.0.1:8778')
            self.assertEqual(result['status'], 'preview_ready')
            self.assertEqual(len(result['messages']), 8)
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
            self.assertEqual(online_orders.cell(recalled, headers['是否计入工单完成']).value, '是')
            self.assertEqual(online_orders.cell(recalled, headers['工单状态']).value, '回收')
            self.assertIsNone(online_orders.cell(recalled, headers['不计入原因']).value)
            self.assertNotIn('个人分配权重', headers)
            self.assertNotIn('个人贡献数量/金额', headers)
            weighted_team_order = next(row for row in range(5, online_orders.max_row + 1)
                                        if online_orders.cell(row, headers['工单ID']).value == 'weighted-order')
            self.assertEqual(online_orders.cell(weighted_team_order, headers['数量/金额']).value, 100)
            source_date = online_orders.cell(recalled, headers['分配时间']).value
            self.assertIsInstance(source_date, (date, datetime))
            for technical in ('fact_id', 'source_id', 'source_sha256', 'source_row_number', 'query_run_id', 'snapshot_id'):
                self.assertNotIn(technical, headers)
            online_cash_headers = {cell.value for cell in online_book['现金明细'][4]}
            self.assertNotIn('个人分配权重', online_cash_headers)
            self.assertNotIn('个人贡献数量/金额', online_cash_headers)
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
            self.assertLess(order_headers['个人分配权重'], order_headers['数量/金额'])
            self.assertLess(order_headers['个人贡献数量/金额'], order_headers['数量/金额'])
            secondary = next(row for row in range(5, orders.max_row + 1)
                             if orders.cell(row, order_headers['工单ID']).value == 'secondary-abroad-order')
            self.assertEqual(orders.cell(secondary, order_headers['业务线']).value, '留学')
            self.assertEqual(orders.cell(secondary, order_headers['是否计入工单完成']).value, '是')
            weighted_order = next(row for row in range(5, orders.max_row + 1)
                                  if orders.cell(row, order_headers['工单ID']).value == 'weighted-order')
            self.assertEqual(orders.cell(weighted_order, order_headers['数量/金额']).value, 100)
            self.assertEqual(orders.cell(weighted_order, order_headers['个人分配权重']).value,
                             '大学同事：0.5；另一位同事：0.5')
            self.assertEqual(orders.cell(weighted_order, order_headers['个人贡献数量/金额']).value,
                             '大学同事：50；另一位同事：50')

            cash_sheet = training_book['现金明细']
            cash_headers = {cell.value: cell.column for cell in cash_sheet[4]}
            weighted_cash = next(row for row in range(5, cash_sheet.max_row + 1)
                                 if cash_sheet.cell(row, cash_headers['工单ID']).value == 'cash-row')
            self.assertAlmostEqual(cash_sheet.cell(weighted_cash, cash_headers['数量/金额']).value, 123456.9)
            self.assertEqual(cash_sheet.cell(weighted_cash, cash_headers['个人分配权重']).value,
                             '大学同事：0.5；另一位同事：0.5')
            self.assertEqual(cash_sheet.cell(weighted_cash, cash_headers['个人贡献数量/金额']).value,
                             '大学同事：61,728.45 元；另一位同事：61,728.45 元')
            markdown = Path(training['markdown']).read_text(encoding='utf-8')
            self.assertIn('(message.png)', markdown)
            self.assertIn('(details.xlsx)', markdown)
            self.assertIn('http://127.0.0.1:8778/university.html', markdown)
            online_markdown = Path(online['markdown']).read_text(encoding='utf-8')
            self.assertIn('| 二级渠道 | 月累计 | 当日新增 | 占比 |', online_markdown)
            self.assertNotIn('市场活动', online_markdown)

            abroad = next(item for item in result['messages'] if item['id'] == 'university.abroad')
            source_message = next(item for item in payload['messages'] if item['id'] == 'university.abroad')
            with Image.open(abroad['png']) as picture:
                self.assertGreaterEqual(picture.width, sum(width for _, width in _employee_columns(source_message)) + 64)
            abroad_html = Path(abroad['html']).read_text(encoding='utf-8')
            self.assertNotIn('大学留学现金及人头未接入', abroad_html)
            self.assertIn('现金', abroad_html)
            self.assertIn('23,456.78 元', abroad_html)
            self.assertIn('部分覆盖', abroad_html)
            self.assertIn('留学36人／小语种71人', abroad_html)
            self.assertIn('留学数据覆盖 2026-09-01—2026-09-30', abroad_html)
            abroad_markdown = Path(abroad['markdown']).read_text(encoding='utf-8')
            self.assertIn('留学数据覆盖 2026-09-01—2026-09-30', abroad_markdown)
            abroad_book = load_workbook(abroad['xlsx'], data_only=True)
            self.assertIn('现金明细', abroad_book.sheetnames)
            abroad_cash = abroad_book['现金明细']
            abroad_cash_headers = {cell.value: cell.column for cell in abroad_cash[4]}
            self.assertIsNone(abroad_cash.cell(5, abroad_cash_headers['工单ID']).value)
            self.assertEqual('RES-ABROAD-2026-001',
                             abroad_cash.cell(5, abroad_cash_headers['资源ID']).value)
            detail_amount = abroad_cash.cell(5, abroad_cash_headers['数量/金额'])
            self.assertEqual(23456.78, detail_amount.value)
            self.assertEqual('#,##0.00', detail_amount.number_format)
            abroad_progress = abroad_book['个人进度']
            abroad_progress_headers = {cell.value: cell.column for cell in abroad_progress[4]}
            self.assertIn('现金完成(元)', abroad_progress_headers)
            abroad_cash_cell = abroad_progress.cell(5, abroad_progress_headers['现金完成(元)'])
            self.assertEqual(23456.78, abroad_cash_cell.value)
            self.assertEqual('#,##0.00', abroad_cash_cell.number_format)
            self.assertEqual('留学36人／小语种71人', abroad_progress.cell(
                5, abroad_progress_headers['人头完成'],
            ).value)

            high_abroad = next(item for item in result['messages'] if item['id'] == 'high.abroad')
            self.assertEqual(high_abroad['channel_id'], 'offline_high_school')
            self.assertEqual(high_abroad['dashboard_url'], 'http://127.0.0.1:8778/prep_high.html')
            high_html = Path(high_abroad['html']).read_text(encoding='utf-8')
            self.assertIn('马玥', high_html)
            self.assertIn('<th>工单完成</th>', high_html)
            self.assertIn('<th>当日新增</th>', high_html)
            for omitted in ('工单目标', '工单完成率', '应完成', '日均需完成'):
                self.assertNotIn(omitted, high_html)
            self.assertIn('<td class="numeric">0.5</td>', high_html)
            self.assertIn('个人渠道分布', high_html)
            self.assertIn('合作院校', high_html)
            self.assertIn('http://127.0.0.1:8778/prep_high.html', high_html)
            self.assertNotIn('落后时间进度', high_html)
            self.assertNotIn('现金目标', high_html)
            self.assertIn('现金', high_html)
            high_book = load_workbook(high_abroad['xlsx'], data_only=True)
            self.assertEqual(high_book.sheetnames, ['个人进度', '渠道分布', '工单明细'])
            progress_sheet = high_book['个人进度']
            progress_headers = {cell.value for cell in progress_sheet[4]}
            self.assertEqual(progress_headers, {'人员', '业务团队', '工单完成', '当日新增', '现金'})
            self.assertEqual(progress_sheet.cell(5, 1).value, '马玥')
            self.assertEqual(progress_sheet.cell(5, 3).value, 1.5)
            self.assertEqual(progress_sheet.cell(5, 4).value, 0.5)
            self.assertEqual(progress_sheet.cell(5, 5).value, '未接入')
            payload_message = next(row for row in notifications_payload()['messages']
                                   if row['id'] == 'high.abroad')
            ma_person = payload_message['people'][0]
            self.assertEqual([label for label, _ in _employee_columns(payload_message)],
                             ['人员', '业务团队', '工单完成', '当日新增', '现金'])
            self.assertEqual(_employee_values(ma_person, payload_message),
                             ['马玥', '高中', '1.5', '0.5', '未接入'])
            with Image.open(high_abroad['png']) as high_image:
                self.assertEqual(high_image.width, 1200)
            channel_sheet = high_book['渠道分布']
            channel_headers = {cell.value: cell.column for cell in channel_sheet[4]}
            co_row = next(row for row in range(5, channel_sheet.max_row + 1)
                          if channel_sheet.cell(row, channel_headers['二级渠道']).value == '合作院校')
            self.assertEqual(channel_sheet.cell(co_row, channel_headers['月累计']).value, 0.5)
            self.assertEqual(channel_sheet.cell(co_row, channel_headers['当日新增']).value, 0.5)
            self.assertAlmostEqual(channel_sheet.cell(co_row, channel_headers['占比%']).value, 33.3)
            order_sheet = high_book['工单明细']
            order_headers = {cell.value: cell.column for cell in order_sheet[4]}
            self.assertEqual(order_sheet.max_row, 6)
            self.assertEqual(order_sheet.cell(5, order_headers['工单ID']).value, 'ma-cocreate')
            self.assertEqual(order_sheet.cell(5, order_headers['个人分配权重']).value, '马玥：0.5')
            self.assertEqual(order_sheet.cell(5, order_headers['个人贡献数量/金额']).value, '马玥：0.5')
            self.assertNotIn('团队自然月明细', high_book.sheetnames)
            high_book.close()
            high_markdown = Path(high_abroad['markdown']).read_text(encoding='utf-8')
            self.assertIn('马玥', high_markdown)
            self.assertIn('个人渠道分布', high_markdown)
            self.assertIn('合作院校', high_markdown)
            self.assertIn('| 人员 | 业务团队 | 工单完成 | 当日新增 |', high_markdown)
            self.assertIn('| 马玥 | 高中 | 1.5 | 0.5 |', high_markdown)
            for omitted in ('工单目标', '工单完成率', '应完成工单', '日均需完成'):
                self.assertNotIn(omitted, high_markdown)
            self.assertIn('[查看看板](http://127.0.0.1:8778/prep_high.html)', high_markdown)
            self.assertNotIn('团队自然月', high_markdown)

    def test_channel_mapping_is_validated(self):
        payload = notifications_payload()
        next(message for message in payload['messages']
             if message['id'] == 'university.training')['channel_id'] = 'wrong_channel'
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
            self.assertEqual(len(manifest['messages']), 8)
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

    def test_abroad_not_covered_cash_is_distinct_from_zero_or_unconnected(self):
        payload = notifications_payload()
        message = next(row for row in payload['messages'] if row['id'] == 'university.abroad')
        message['source_coverage'] = {
            'start_date': '2026-09-01', 'through_date': '2026-09-30',
            'snapshot_id': 'snapshot_abroad_not_covered_fixture',
        }
        message['team_metrics']['cash'] = {
            'actual': None, 'target': None, 'completion': None, 'status': 'not_covered',
        }
        message['people'][0]['cash_actual'] = dict(message['team_metrics']['cash'])
        with TemporaryDirectory() as directory:
            item = next(row for row in render_notifications(payload, Path(directory))['messages']
                        if row['id'] == 'university.abroad')
            html = Path(item['html']).read_text(encoding='utf-8')
            markdown = Path(item['markdown']).read_text(encoding='utf-8')
            self.assertIn('现金', html)
            self.assertIn('该期间未覆盖', html)
            self.assertIn('留学数据覆盖 2026-09-01—2026-09-30', html)
            self.assertNotIn('大学留学现金及人头未接入', html)
            self.assertNotIn('0 元', html)
            self.assertIn('留学数据覆盖 2026-09-01—2026-09-30', markdown)

    def test_unknown_abroad_performance_is_not_reported_as_nobody_behind(self):
        payload = notifications_payload()
        message = next(row for row in payload['messages'] if row['id'] == 'university.abroad')
        message['source_coverage'] = {'start_date': '2026-09-01', 'through_date': '2026-09-30'}
        message['window'].update(person_start='2026-09-26', person_through='2026-10-02')
        for person in message['people']:
            person['behind'] = None
        payload['messages'] = [message]
        with TemporaryDirectory() as directory:
            item = render_notifications(payload, Path(directory))['messages'][0]
            for path in (item['html'], item['markdown']):
                text = Path(path).read_text(encoding='utf-8')
                self.assertIn('来源未覆盖完整绩效窗口，暂不判断落后', text)
                self.assertNotIn('无人落后时间进度', text)


if __name__ == '__main__':
    unittest.main()
