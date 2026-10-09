from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from openpyxl import Workbook

from dashboard_product.management.personnel_contribution import (
    DEFAULT_ORDER_STATUS_MODE,
    ORDER_STATUS_MODES,
)
from dashboard_product.management.personnel_history import apply_history, load_history


MONTHS = (
    ('2026-06', 11, '6月'),
    ('2026-07', 19, '7月'),
    ('2026-08', 27, '8月'),
    ('2026-09', 35, '9月'),
)


def make_history(path, *, header_override=None, bad_amount=False,
                 missing_formula_cache=False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'FY27市场人员产能'
    sheet['A1'] = '组别'
    sheet['B1'] = '人员'
    sheet['C1'] = 'FY27'
    for month, start, month_label in MONTHS:
        sheet.cell(1, start, month_label)
        labels = (
            '英美澳加留学资源', '欧亚留学资源',
            '总留学资源' if month == '2026-09' else '总留学工单',
            '总语培资源' if month == '2026-09' else '总语培工单',
            '总资源量' if month == '2026-09' else '总工单量',
            '留学签约（万元）', '语培签约（万元）', '总签约金额（万元）',
        )
        for offset, label in enumerate(labels):
            sheet.cell(2, start + offset, label)

    sheet['A13'] = '线下-高校组'
    sheet['B13'] = '孙伟'
    sheet['B14'] = '吴子玄'
    sheet['B21'] = '其他'
    sheet['A22'] = '线下组合计（不含退回）'

    values = {
        '2026-06': (0, 2, 2, 0, 1.25, 1.25),
        '2026-07': (3, 2, 5, 1.5, 0, 1.5),
        '2026-08': (4, 1, 5, None, 0.25, None),
        '2026-09': (7, 0, 7, 0.2, 0, 0.2),
    }
    for month, start, _ in MONTHS:
        for offset, value in enumerate(values[month], start=2):
            sheet.cell(13, start + offset, value)
        # This second actual person keeps genuine zeroes and blank cells distinct.
        for offset, value in enumerate((None, 0, None, 0, None, 0), start=2):
            sheet.cell(14, start + offset, value)
    if bad_amount:
        sheet['Q13'] = '不是金额'
    if header_override:
        cell, value = header_override
        sheet[cell] = value
    workbook.save(path)
    workbook.close()

    # Make one formula-backed zero with a valid cached value, and emulate the
    # source file's stale 1x1 worksheet dimension without needing Excel.
    with zipfile.ZipFile(path) as source:
        entries = [(item, source.read(item.filename)) for item in source.infolist()]
    patched = []
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    for item, content in entries:
        if item.filename != 'xl/worksheets/sheet1.xml':
            patched.append((item, content))
            continue
        root = ET.fromstring(content)
        dimension = root.find(f'{ns}dimension')
        if dimension is not None:
            dimension.set('ref', 'A1:A1')
        formula_cell = root.find(f'.//{ns}c[@r="M13"]')
        formula_cell.attrib.pop('t', None)
        for child in list(formula_cell):
            if child.tag in (ns + 'f', ns + 'v'):
                formula_cell.remove(child)
        formula = ET.Element(ns + 'f')
        formula.text = '1-1'
        formula_cell.insert(0, formula)
        if not missing_formula_cache:
            cached = ET.Element(ns + 'v')
            cached.text = '0'
            formula_cell.insert(1, cached)
        patched.append((item, ET.tostring(root, encoding='utf-8', xml_declaration=True)))
    rewritten = path.with_suffix('.rewritten.xlsx')
    with zipfile.ZipFile(rewritten, 'w', zipfile.ZIP_DEFLATED) as target:
        for item, content in patched:
            target.writestr(item, content)
    rewritten.replace(path)


def person(name, business_line='abroad', targets=None):
    row = {
        'name': name,
        'business_line': business_line,
        'self': {'orders': 8, 'cash': 80},
        'received': {'orders': 2, 'cash': 20},
        'own_total': {'orders': 10, 'cash': 100},
        'targets': deepcopy(targets if targets is not None else {'orders': 10, 'cash': 10000}),
        'completion': {'orders': 1, 'cash': 0.01},
        'self_rate': {'orders': 0.8, 'cash': 0.8},
        'output': {'orders': 3, 'cash': 40},
        'created_total': {'orders': 12, 'cash': 120},
        'pending_count': 2,
        'source_kind': 'current',
    }
    row['order_status_views'] = {}
    outputs = {'00': {'orders': 2, 'cash': 40},
               '01': {'orders': 3, 'cash': 40},
               '10': {'orders': 5, 'cash': 40},
               '11': {'orders': 7, 'cash': 40}}
    for mode in ORDER_STATUS_MODES:
        view = {key: deepcopy(row[key]) for key in (
            'self', 'received', 'own_total', 'targets', 'completion', 'self_rate',
            'output', 'created_total',
        )}
        view['output'] = outputs[mode]
        view['breakdowns'] = {}
        row['order_status_views'][mode] = view
    row['output'] = deepcopy(row['order_status_views'][DEFAULT_ORDER_STATUS_MODE]['output'])
    return row


def capacity_period(month, people):
    return {
        'id': month,
        'coverage': {'abroad': {'connected': False, 'orders_through': '2026-06-10',
                                'cash_through': '2026-06-10'}},
        'people': people,
        'pending_count': 2,
        'pending': [{'name': '孙伟', 'source': '留学资源', 'reason': '待核', 'count': 1},
                    {'name': '语培甲', 'source': '语培工单', 'reason': '待核', 'count': 1}],
    }


class PersonnelHistoryTests(unittest.TestCase):
    def test_loads_fixed_rows_preserves_zero_and_missing_values_and_cash_units(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.xlsx'
            make_history(path)
            before = path.read_bytes()
            history = load_history(path)

        self.assertEqual(history['source_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(history['sheet'], 'FY27市场人员产能')
        self.assertNotIn('其他', [row['name'] for row in history['rows']])
        june = next(row for row in history['rows']
                    if row['month'] == '2026-06' and row['name'] == '孙伟')
        self.assertEqual(june['components'], {
            'study_abroad': {'orders': 0, 'cash': 0},
            'small_language': {'orders': 2, 'cash': 12500},
        })
        self.assertEqual(june['source_total'], {'orders': 2, 'cash': 12500})
        self.assertEqual(june['source_cells']['components.study_abroad.orders'], 'M13')
        self.assertEqual(june['source_labels']['components.small_language.cash'], '语培签约（万元）')
        august = next(row for row in history['rows']
                      if row['month'] == '2026-08' and row['name'] == '孙伟')
        self.assertIsNone(august['components']['study_abroad']['cash'])
        self.assertEqual(august['components']['small_language']['cash'], 2500)
        september = next(row for row in history['rows']
                         if row['month'] == '2026-09' and row['name'] == '孙伟')
        self.assertEqual(september['source_cells']['components.study_abroad.orders'], 'AK13')
        self.assertEqual(september['source_labels']['components.study_abroad.orders'], '总留学资源')

    def test_missing_file_is_optional_and_has_no_apply_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            history = load_history(Path(directory) / 'missing.xlsx')
        capacity = {'periods': [capacity_period('2026-06', [person('孙伟')])]}
        before = deepcopy(capacity)
        self.assertIsNone(history)
        self.assertIsNone(apply_history(capacity, history))
        self.assertEqual(capacity, before)

    def test_applies_history_only_to_existing_abroad_people_in_june_through_august(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.xlsx'
            make_history(path)
            history = load_history(path)
        periods = []
        for month in ('2026-06', '2026-07', '2026-08'):
            target = {'orders': 0, 'cash': 0} if month == '2026-07' else {
                'orders': 10, 'cash': 10000,
            }
            periods.append(capacity_period(month, [
                person('孙伟', targets=target),
                person('吴子玄', 'training'),
                person('未知人员'),
            ]))
        september = capacity_period('2026-09', [person('孙伟')])
        periods.append(september)
        september_before = deepcopy(september)
        untouched_people = [deepcopy(period['people'][index])
                            for period in periods[:3] for index in (1, 2)]
        targets_before = [deepcopy(period['people'][0]['targets']) for period in periods[:3]]
        status_targets_before = [deepcopy(period['people'][0]['order_status_views'])
                                 for period in periods[:3]]
        capacity = {'periods': periods}

        result = apply_history(capacity, history)

        self.assertEqual(result, {'adopted_rows': 3})
        for index, period in enumerate(periods[:3]):
            abroad = period['people'][0]
            self.assertEqual(abroad['source_kind'], 'confirmed_history')
            self.assertEqual(abroad['pending_count'], 0)
            self.assertEqual(abroad['targets'], targets_before[index])
            self.assertEqual(abroad['output'], {'orders': 3, 'cash': 40})
            self.assertEqual(abroad['output'],
                             abroad['order_status_views'][DEFAULT_ORDER_STATUS_MODE]['output'])
            for bucket in ('self', 'received', 'self_rate', 'created_total'):
                self.assertEqual(abroad[bucket], {'orders': None, 'cash': None})
            self.assertEqual(abroad['breakdowns']['study_abroad']['own_total']['orders'],
                             [0, 3, 4][index])
            self.assertEqual(abroad['breakdowns']['small_language']['own_total']['orders'],
                             [2, 2, 1][index])
            for breakdown in abroad['breakdowns'].values():
                self.assertEqual(breakdown['output'], {'orders': 3, 'cash': 40})
            for breakdown in abroad['breakdowns'].values():
                for bucket in ('self', 'received', 'self_rate', 'created_total'):
                    self.assertEqual(breakdown[bucket], {'orders': None, 'cash': None})
            self.assertEqual(period['coverage']['history'], {
                'label': '留学及小语种历史结果',
                'adopted_people': ['孙伟'], 'split_available': False,
                'order_status_detail_available': False,
            })
            for mode in ORDER_STATUS_MODES:
                status_view = abroad['order_status_views'][mode]
                prior_view = status_targets_before[index][mode]
                self.assertEqual(status_view['own_total'], abroad['own_total'])
                self.assertEqual(status_view['completion'], abroad['completion'])
                self.assertEqual(status_view['targets'], prior_view['targets'])
                self.assertEqual(status_view['output'], prior_view['output'])
                self.assertEqual(status_view['own_total'], abroad['own_total'])
                for bucket in ('self', 'received', 'self_rate', 'created_total'):
                    self.assertEqual(status_view[bucket], {'orders': None, 'cash': None})
                for scope, breakdown in status_view['breakdowns'].items():
                    self.assertEqual(breakdown['own_total'], abroad['breakdowns'][scope]['own_total'])
                    self.assertEqual(breakdown['targets'], targets_before[index])
                    self.assertEqual(breakdown['completion'], abroad['breakdowns'][scope]['completion'])
                    self.assertEqual(breakdown['output'], status_view['output'])
                    for bucket in ('self', 'received', 'self_rate', 'created_total'):
                        self.assertEqual(breakdown[bucket], {'orders': None, 'cash': None})
            self.assertTrue(period['coverage']['abroad']['connected'])
            self.assertEqual([entry['name'] for entry in period['pending']], ['语培甲'])
            self.assertEqual(period['pending_count'], 2)
        self.assertEqual(periods[0]['people'][0]['own_total'], {'orders': 2, 'cash': 12500})
        self.assertEqual(periods[0]['people'][0]['completion'], {'orders': 0.2, 'cash': 1.25})
        self.assertEqual(periods[1]['people'][0]['own_total'], {'orders': 5, 'cash': 15000})
        self.assertEqual(periods[1]['people'][0]['completion'], {'orders': None, 'cash': None})
        self.assertEqual(periods[2]['people'][0]['own_total'], {'orders': 5, 'cash': None})
        self.assertEqual(periods[2]['people'][0]['completion'], {'orders': 0.5, 'cash': None})
        self.assertEqual(periods[0]['people'][0]['breakdowns']['study_abroad']['completion'],
                         {'orders': 0, 'cash': 0})
        self.assertEqual(periods[0]['people'][0]['breakdowns']['small_language']['completion'],
                         {'orders': 0.2, 'cash': 1.25})
        self.assertEqual(periods[2]['people'][0]['breakdowns']['study_abroad']['completion'],
                         {'orders': 0.4, 'cash': None})
        self.assertEqual(periods[2]['people'][0]['breakdowns']['small_language']['completion'],
                         {'orders': 0.1, 'cash': 0.25})
        self.assertEqual([period['people'][i] for period in periods[:3] for i in (1, 2)],
                         untouched_people)
        self.assertEqual(september, september_before)

    def test_rejects_bad_headers_amounts_and_formula_without_cached_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_header = root / 'bad-header.xlsx'
            make_history(bad_header, header_override=('B1', '姓名'))
            bad_unit = root / 'bad-unit.xlsx'
            make_history(bad_unit, header_override=('P2', '留学签约'))
            bad_amount = root / 'bad-amount.xlsx'
            make_history(bad_amount, bad_amount=True)
            missing_cache = root / 'missing-cache.xlsx'
            make_history(missing_cache, missing_formula_cache=True)

            with self.assertRaisesRegex(ValueError, '表头无效'):
                load_history(bad_header)
            with self.assertRaisesRegex(ValueError, '单位须为万元'):
                load_history(bad_unit)
            with self.assertRaisesRegex(ValueError, '数值无效'):
                load_history(bad_amount)
            with self.assertRaisesRegex(ValueError, '公式缺少缓存值'):
                load_history(missing_cache)


if __name__ == '__main__':
    unittest.main()
