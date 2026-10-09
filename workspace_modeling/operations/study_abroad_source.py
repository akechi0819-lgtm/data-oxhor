"""Shared read-only reader for the study-abroad reference workbook."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re


def _text(value):
    return '' if value is None else str(value).strip()


def _normalized_header(value):
    return re.sub(r'\s+', '', _text(value)).casefold()


def _sheet(book, name):
    if name not in book.sheetnames:
        raise ValueError(f'留学工作簿缺少工作表：{name}')
    sheet = book[name]
    # Some exports declare A1 dimensions while retaining rows in the XML.
    sheet.reset_dimensions()
    return sheet


def read_sheet_rows(book, name, fields, *, required=None):
    """Read non-empty rows by normalized headers, selecting the leftmost match.

    ``fields`` maps output names to the actual source header label.
    Fields are required unless an explicit subset is supplied. Descriptive
    optional fields return None. Row numbers retain physical Excel positions.
    """
    sheet = _sheet(book, name)
    rows = sheet.iter_rows(values_only=True)
    headers = next(rows, ())
    labels = [_normalized_header(value) for value in headers]
    required = set(fields) if required is None else set(required)
    columns = {}
    for key, label in fields.items():
        option = _normalized_header(label)
        matches = [index for index, header in enumerate(labels)
                   if header == option or header.startswith(option)]
        if not matches:
            if key in required:
                raise ValueError(f'{name} 缺少关键字段：{label}')
            columns[key] = None
            continue
        # Leftmost matching header is intentional for duplicate resource IDs.
        columns[key] = matches[0]

    result = []
    for row_number, row in enumerate(rows, 2):
        if not any(_text(value) for value in row):
            continue
        result.append({
            'source_row_number': row_number,
            **{key: row[index] if index is not None and index < len(row) else None
               for key, index in columns.items()},
        })
    return result


def _group_mapping_rows(book):
    if '筛选项' not in book.sheetnames:
        return []
    sheet = _sheet(book, '筛选项')
    result = []
    for row_number, row in enumerate(sheet.iter_rows(values_only=True), 1):
        first = row[0] if len(row) > 0 else None
        second = row[1] if len(row) > 1 else None
        if not _text(first) and not _text(second):
            continue
        result.append({
            'source_row_number': row_number,
            'owner': first,
            'source_group': second,
        })
    return result


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_sources(resource_path: Path) -> dict:
    """Read the three study-abroad source sheets and the hidden owner map.

    Dates, amounts, and source-group cells remain in their workbook values for
    downstream normalization. Empty descriptive columns are returned as None.
    Contract explanation rows and records without a contract number are omitted.
    """
    import openpyxl

    path = Path(resource_path)
    before_hash = _sha256(path)
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        resources = read_sheet_rows(book, '资源', {
            'resource_id': '资源ID', 'date': '分单日期', 'owner': '市场资源归属人',
            'source_group': '市场资源归属组', 'status': '线下组资源',
            'campaign': '市场活动', 'first_channel': '一级渠道',
            'second_channel': '二级渠道', 'third_channel': '三级渠道',
            'channel_source': '渠道来源', 'consultation_type': '咨询类型',
            'country': '意向国家', 'stage': '意向阶段',
            'business_line': '归属条线', 'dashboard_category': '看板归类',
            'description': '资源描述',
        }, required={'resource_id', 'date', 'owner', 'status', 'campaign'})
        contracts = read_sheet_rows(book, '留学签约', {
            'resource_id': '记录id', 'contract_id': '合同编号', 'customer_id': '客户ID',
            'month': '归档月份', 'archive_date': '归档日期', 'owner': '市场资源归属人',
            'source_group': '市场资源归属组', 'amount': '签约金额',
            'campaign': '91资源市场活动', 'country': '留学国家',
            'stage': '申请学位', 'first_channel': '来访类型',
            'second_channel': '来源渠道', 'third_channel': '渠道明细',
            'contract_status': '合同状态',
        }, required={'resource_id', 'contract_id', 'month', 'archive_date',
                     'owner', 'amount', 'campaign'})
        contracts = [row for row in contracts if _text(row.get('contract_id'))]
        languages = read_sheet_rows(book, '小语种签约', {
            'resource_id': '资源ID', 'work_order_id': '工单ID', 'date': '业务日期',
            'owner': '市场资源归属人', 'source_group': '市场资源归属组',
            'amount': '实缴金额', 'student_id': '学员编号', 'language': '语种',
            'course_code': '班级编码', 'business_type': '业务类型',
            'signup_type': '新签/续签',
            'first_channel': '来访类型',
            'second_channel': '渠道来源',
            'third_channel': '渠道明细',
        }, required={'resource_id', 'work_order_id', 'date', 'owner', 'amount'})
        group_mapping = _group_mapping_rows(book)
    finally:
        book.close()

    after_hash = _sha256(path)
    if after_hash != before_hash:
        raise ValueError('留学工作簿在读取过程中发生变化')
    return {
        'resources': resources,
        'contracts': contracts,
        'languages': languages,
        'group_mapping': group_mapping,
        'source_sha256': before_hash,
        'source_path': str(path),
    }
