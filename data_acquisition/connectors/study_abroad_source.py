"""Shared read-only reader for the study-abroad reference workbook."""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET


_SHEET_NAMES = {
    'resources': ('资源', '资源登记表（前途）'),
    'contracts': ('留学签约', '留学签约看板（市场）'),
    'languages': ('小语种签约', '小语种签约看板（市场）'),
    'group_mapping': ('筛选项', '筛选项（前途）'),
}
_RESOURCE_HEADER_FIELDS = {
    'resource_id': '资源ID', 'date': '分单日期', 'owner': '市场资源归属人',
}
_XLSX_MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_XLSX_NS = {'main': _XLSX_MAIN_NS}


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


def _resolve_sheet_name(book, key, *, required=True):
    """Resolve only the explicit legacy/Tencent sheet names; reject collisions."""
    candidates = [name for name in _SHEET_NAMES[key] if name in book.sheetnames]
    if len(candidates) > 1:
        raise ValueError(f'留学工作簿的{key}工作表存在多个合法候选：{"、".join(candidates)}')
    if not candidates:
        if required:
            raise ValueError(f'留学工作簿缺少{key}工作表（允许名称：{"、".join(_SHEET_NAMES[key])}）')
        return None
    return candidates[0]


def _field_matches(header, label):
    labels = label if isinstance(label, (tuple, list)) else (label,)
    normalized = _normalized_header(header)
    return any(normalized == _normalized_header(item)
               or normalized.startswith(_normalized_header(item)) for item in labels)


def _find_header_row(sheet, fields, required, *, max_rows):
    """Find exactly one header row whose required fields all appear."""
    sheet.reset_dimensions()
    candidates = []
    for row_number, row in enumerate(
            sheet.iter_rows(min_row=1, max_row=max_rows, values_only=True), 1):
        labels = [_normalized_header(value) for value in row]
        if all(any(_field_matches(header, fields[key]) for header in labels)
               for key in required):
            candidates.append(row_number)
    if len(candidates) > 1:
        raise ValueError(f'{sheet.title}前{max_rows}行存在多个关键字段表头：{candidates}')
    if not candidates:
        required_labels = '、'.join(fields[key] for key in sorted(required))
        raise ValueError(f'{sheet.title}前{max_rows}行未找到关键字段表头：{required_labels}')
    return candidates[0]


def _load_workbook_read_only(path):
    """Load an XLSX, repairing only empty fill nodes in an in-memory copy."""
    import openpyxl

    styles_path = 'xl/styles.xml'
    with ZipFile(path, 'r') as source:
        if styles_path not in source.namelist():
            return openpyxl.load_workbook(path, read_only=True, data_only=True)
        styles = ET.fromstring(source.read(styles_path))
        fills = styles.find('main:fills', _XLSX_NS)
        empty_fills = [] if fills is None else [fill for fill in fills.findall('main:fill', _XLSX_NS)
                                                if not list(fill)]
        if not empty_fills:
            return openpyxl.load_workbook(path, read_only=True, data_only=True)

        # Preserve fill indices because cellXfs reference them by position.
        for fill in empty_fills:
            ET.SubElement(fill, f'{{{_XLSX_MAIN_NS}}}patternFill', {'patternType': 'none'})
        repaired_styles = ET.tostring(styles, encoding='utf-8', xml_declaration=True)
        buffer = BytesIO()
        with ZipFile(buffer, 'w', compression=ZIP_DEFLATED) as repaired:
            for item in source.infolist():
                content = repaired_styles if item.filename == styles_path else source.read(item.filename)
                repaired.writestr(item, content)

    buffer.seek(0)
    return openpyxl.load_workbook(buffer, read_only=True, data_only=True)


def read_sheet_rows(book, name, fields, *, required=None, header_row=1):
    """Read non-empty rows by normalized headers, selecting the leftmost match.

    ``fields`` maps output names to the actual source header label.
    Fields are required unless an explicit subset is supplied. Descriptive
    optional fields return None. Row numbers retain physical Excel positions.
    """
    sheet = _sheet(book, name)
    rows = sheet.iter_rows(values_only=True)
    headers = ()
    for physical_row, row in enumerate(rows, 1):
        if physical_row == header_row:
            headers = row
            break
    labels = [_normalized_header(value) for value in headers]
    required = set(fields) if required is None else set(required)
    columns = {}
    for key, label in fields.items():
        matches = [index for index, header in enumerate(labels)
                   if _field_matches(header, label)]
        if not matches:
            if key in required:
                raise ValueError(f'{name} 缺少关键字段：{label}')
            columns[key] = None
            continue
        # Leftmost matching header is intentional for duplicate resource IDs.
        columns[key] = matches[0]

    result = []
    for row_number, row in enumerate(rows, header_row + 1):
        if not any(_text(value) for value in row):
            continue
        result.append({
            'source_row_number': row_number,
            **{key: row[index] if index is not None and index < len(row) else None
               for key, index in columns.items()},
        })
    return result


def _group_mapping_rows(book, name):
    if not name:
        return []
    columns_by_sheet = {'筛选项': (1, 2), '筛选项（前途）': (3, 4)}
    if name not in columns_by_sheet:
        raise ValueError(f'留学工作簿的归属映射工作表名称不受支持：{name}')
    sheet = _sheet(book, name)
    min_column, max_column = columns_by_sheet[name]
    result = []
    for row_number, row in enumerate(
            sheet.iter_rows(min_col=min_column, max_col=max_column, values_only=True), 1):
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
    path = Path(resource_path)
    before_hash = _sha256(path)
    book = _load_workbook_read_only(path)
    try:
        source_sheets = {
            key: _resolve_sheet_name(book, key, required=(key != 'group_mapping'))
            for key in _SHEET_NAMES
        }
        resource_fields = {
            **_RESOURCE_HEADER_FIELDS,
            'source_group': '市场资源归属组', 'status': '线下组资源',
            'campaign': '市场活动', 'first_channel': '一级渠道',
            'second_channel': '二级渠道', 'third_channel': '三级渠道',
            'channel_source': '渠道来源', 'consultation_type': '咨询类型',
            'country': '意向国家', 'stage': '意向阶段',
            'business_line': '归属条线', 'dashboard_category': '看板归类',
            'description': ('资源描述', '91资源描述'),
        }
        resource_header_row = _find_header_row(
            _sheet(book, source_sheets['resources']), resource_fields,
            {'resource_id', 'date', 'owner'}, max_rows=10)
        resources = read_sheet_rows(book, source_sheets['resources'], resource_fields,
                                    required={'resource_id', 'date', 'owner'},
                                    header_row=resource_header_row)
        contracts = read_sheet_rows(book, source_sheets['contracts'], {
            'resource_id': '记录id', 'contract_id': '合同编号', 'customer_id': '客户ID',
            'customer_name': '签约客户姓名',
            'month': '归档月份', 'archive_date': '归档日期', 'owner': '市场资源归属人',
            'source_group': '市场资源归属组', 'amount': '签约金额',
            'campaign': '91资源市场活动', 'country': '留学国家',
            'stage': '申请学位', 'first_channel': '来访类型',
            'second_channel': '来源渠道', 'third_channel': '渠道明细',
            'contract_status': '合同状态',
        }, required={'resource_id', 'contract_id', 'month', 'archive_date',
                     'owner', 'amount'})
        contracts = [row for row in contracts if _text(row.get('contract_id'))]
        languages = read_sheet_rows(book, source_sheets['languages'], {
            'resource_id': '资源ID', 'work_order_id': '工单ID', 'date': '业务日期',
            'owner': '市场资源归属人', 'source_group': '市场资源归属组',
            'amount': '实缴金额', 'student_id': '学员编号', 'language': '语种',
            'customer_name': '姓名',
            'course_code': '班级编码', 'business_type': '业务类型',
            'signup_type': '新签/续签',
            'first_channel': '来访类型',
            'second_channel': '渠道来源',
            'third_channel': '渠道明细',
        }, required={'work_order_id', 'date', 'owner', 'amount'})
        languages = [row for row in languages if any(_text(row.get(key)) for key in
                     ('date', 'amount', 'student_id', 'work_order_id'))]
        group_mapping = _group_mapping_rows(book, source_sheets['group_mapping'])
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
        'source_sheets': source_sheets,
        'source_sha256': before_hash,
        'source_path': str(path),
    }
