"""Focused compatibility checks for the current Tencent workbook export."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET

import openpyxl

from workspace_modeling.operations.study_abroad_source import read_sources


RESOURCE_SHEET = '资源登记表（前途）'
CONTRACT_SHEET = '留学签约看板（市场）'
LANGUAGE_SHEET = '小语种签约看板（市场）'
MAPPING_SHEET = '筛选项（前途）'
MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

RESOURCE_HEADERS = [
    '财年', '分单月份', '分单日期\n（跟系统一致）', '资源ID\n（跟系统一致）',
    '市场资源归属人\n需要市场老师判定', '市场资源归属组\n（公式勿动）',
    '咨询类型\n(下拉选项)', '91资源描述',
]
CONTRACT_HEADERS = [
    '记录id', '合同编号', '客户ID', '归档月份', '归档日期',
    '市场资源归属人\n需要市场老师判定', '签约金额',
]
LANGUAGE_HEADERS = [
    '客服操作人', '工单ID', '业务日期', '市场资源归属人\n需要市场老师判定',
    '市场资源归属组\n（公式勿动）', '实缴金额', '学员编号', '语种',
]


def _append_record(sheet, headers: list[str], record: dict[str, object]) -> None:
    sheet.append([record.get(header) for header in headers])


def _write_tencent_workbook(path: Path, *, include_legacy_resource=False,
                            language_rows=None) -> None:
    book = openpyxl.Workbook()
    resources = book.active
    resources.title = RESOURCE_SHEET
    resources.append(['FY27 前途市场资源登记'])
    resources.append(['模板说明：第三行开始填写'])
    resources.append(RESOURCE_HEADERS)
    _append_record(resources, RESOURCE_HEADERS, {
        '分单日期\n（跟系统一致）': date(2026, 10, 9),
        '资源ID\n（跟系统一致）': 'R-001',
        '市场资源归属人\n需要市场老师判定': '合成负责人',
        '市场资源归属组\n（公式勿动）': '线上组',
        '咨询类型\n(下拉选项)': '留学',
        '91资源描述': '合成描述',
    })

    contracts = book.create_sheet(CONTRACT_SHEET)
    contracts.append(CONTRACT_HEADERS)
    _append_record(contracts, CONTRACT_HEADERS, {
        '记录id': 'R-001', '合同编号': 'C-001', '客户ID': 'U-001',
        '归档月份': '2026-10', '归档日期': date(2026, 10, 7),
        '市场资源归属人\n需要市场老师判定': '合成负责人', '签约金额': 1000,
    })

    languages = book.create_sheet(LANGUAGE_SHEET)
    languages.append(LANGUAGE_HEADERS)
    language_rows = language_rows or [
        # Formula-prefilled template row: visible owner text alone is not a business record.
        {'客服操作人': '模板操作人', '市场资源归属人\n需要市场老师判定': '模板归属人'},
        # A real but incomplete row remains visible for downstream validation.
        {'工单ID': 'W-INCOMPLETE', '市场资源归属人\n需要市场老师判定': '合成负责人'},
        {'工单ID': 'W-001', '业务日期': date(2026, 10, 9),
         '市场资源归属人\n需要市场老师判定': '合成负责人', '实缴金额': 500,
         '学员编号': 'S-001', '语种': '日语'},
    ]
    for record in language_rows:
        _append_record(languages, LANGUAGE_HEADERS, record)

    mapping = book.create_sheet(MAPPING_SHEET)
    mapping.sheet_state = 'hidden'
    for row_number in range(1, 50):
        channel_option = f'下拉渠道{row_number}' if row_number <= 28 else None
        country_option = f'下拉国家{row_number}' if row_number <= 28 else None
        owner = f'合成负责人{row_number}'
        source_group = 'SSC' if row_number == 1 else '线上组' if row_number == 4 else '线下组'
        mapping.append([channel_option, country_option, owner, source_group])

    if include_legacy_resource:
        legacy = book.create_sheet('资源')
        legacy.append(RESOURCE_HEADERS)
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    book.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _add_empty_fills(path: Path, count: int = 3) -> None:
    with ZipFile(path, 'r') as source:
        entries = [(item, source.read(item.filename)) for item in source.infolist()]
    rewritten = []
    for item, content in entries:
        if item.filename == 'xl/styles.xml':
            root = ET.fromstring(content)
            fills = root.find(f'{{{MAIN_NS}}}fills')
            for _ in range(count):
                ET.SubElement(fills, f'{{{MAIN_NS}}}fill')
            fills.set('count', str(len(fills)))
            content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        rewritten.append((item, content))
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as target:
        for item, content in rewritten:
            target.writestr(item, content)


class TencentStudyAbroadSourceTests(unittest.TestCase):
    def test_tencent_names_header_offset_optional_fields_and_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tencent.xlsx'
            _write_tencent_workbook(path)
            digest = _sha256(path)

            result = read_sources(path)

            self.assertEqual({
                'resources': RESOURCE_SHEET,
                'contracts': CONTRACT_SHEET,
                'languages': LANGUAGE_SHEET,
                'group_mapping': MAPPING_SHEET,
            }, result['source_sheets'])
            self.assertEqual(4, result['resources'][0]['source_row_number'])
            self.assertEqual('R-001', result['resources'][0]['resource_id'])
            self.assertEqual('合成描述', result['resources'][0]['description'])
            self.assertIsNone(result['resources'][0]['status'])
            self.assertIsNone(result['resources'][0]['campaign'])
            self.assertIsNone(result['contracts'][0]['campaign'])
            self.assertIsNone(result['languages'][0]['resource_id'])
            self.assertEqual(49, len(result['group_mapping']))
            self.assertEqual('合成负责人1', result['group_mapping'][0]['owner'])
            self.assertEqual('SSC', result['group_mapping'][0]['source_group'])
            self.assertEqual('线上组', result['group_mapping'][3]['source_group'])
            self.assertNotIn('下拉渠道1', [row['owner'] for row in result['group_mapping']])
            self.assertEqual(digest, result['source_sha256'])
            self.assertEqual(digest, _sha256(path))

    def test_duplicate_legal_sheet_names_fail_as_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ambiguous.xlsx'
            _write_tencent_workbook(path, include_legacy_resource=True)

            with self.assertRaisesRegex(ValueError, '多个合法候选'):
                read_sources(path)

    def test_empty_fill_repair_preserves_dates_and_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty-fills.xlsx'
            _write_tencent_workbook(path)
            _add_empty_fills(path)
            digest = _sha256(path)

            rows = read_sources(path)

            self.assertEqual(date(2026, 10, 9), rows['resources'][0]['date'].date())
            self.assertEqual(date(2026, 10, 7), rows['contracts'][0]['archive_date'].date())
            self.assertEqual(digest, rows['source_sha256'])
            self.assertEqual(digest, _sha256(path))

    def test_blank_template_rows_drop_but_incomplete_business_rows_remain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'language-rows.xlsx'
            _write_tencent_workbook(path)

            rows = read_sources(path)['languages']

            self.assertEqual([3, 4], [row['source_row_number'] for row in rows])
            self.assertEqual('W-INCOMPLETE', rows[0]['work_order_id'])
            self.assertIsNone(rows[0]['date'])
            self.assertIsNone(rows[0]['amount'])
            self.assertEqual('W-001', rows[1]['work_order_id'])

    def test_read_keeps_raw_source_hash_and_actual_sheet_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.xlsx'
            _write_tencent_workbook(path)
            before = _sha256(path)

            result = read_sources(path)

            self.assertEqual(before, result['source_sha256'])
            self.assertEqual(str(path), result['source_path'])
            self.assertEqual(before, _sha256(path))
            self.assertEqual(RESOURCE_SHEET, result['source_sheets']['resources'])


if __name__ == '__main__':
    unittest.main()
