"""Preserve the Dianping registry's ownership and use controlled Snapshot queries."""
from datetime import date, timedelta
import json
from pathlib import Path

from .sheet_sync_common import commit_with_readback, map_columns, readback_matches
from .sync_content_work_orders import _call_tool, _encode_cell, _identifier, _sync_lock, _write_json

SQL_ROOT = Path(__file__).with_name('dianping_sql')
HEADERS = ('序号', '季度', '月', '日', '工单ID', '资源ID', '工单姓名', '客资校区', '工单年级',
           '项目归属', '学校', '咨询内容', '在跟顾问', '91状态', '工单等级', '工单情况',
           '签约时间', '签约周期', '签约课程', '签约金额')
MANUAL = '工单情况'
KEY = '工单ID'
SIGNED = '签约时间'


def load_orders(query, start, through):
    coverage = query((SQL_ROOT / 'coverage.sql').read_text(), [])
    if {r['source'] for r in coverage} != {'work_orders', 'cash'} or any(
            not r['max_business_date'] or r['max_business_date'] < through.isoformat() for r in coverage):
        raise ValueError('dianping_snapshot_coverage_short')
    detail = query((SQL_ROOT / 'detail.sql').read_text(), [start.isoformat(), through.isoformat()])
    cash = query((SQL_ROOT / 'cash.sql').read_text(), [start.isoformat(), through.isoformat()])
    for values in (detail, cash):
        identities = [_identifier(row['ID']) for row in values]
        if None in identities or len(set(identities)) != len(identities):
            raise ValueError('dianping_source_id_missing_or_duplicate')
    return detail, {_identifier(row['ID']): row for row in cash}


def values_for_order(order, matching, config, sequence):
    assigned = date.fromisoformat(str(order['assigned_date']))
    positive = matching.get('first_positive_date')
    signed = date.fromisoformat(str(positive)) if positive else None
    cash = matching.get('total_cash')
    return dict(zip(HEADERS, (
        sequence, order['财季'], assigned.month, assigned.day, _identifier(order['ID']),
        _identifier(order['资源id']), order['姓名'], config.get('campus_by_team', {}).get(order['团队']),
        order['年级名称'], config.get('group_by_grade', {}).get(order['年级名称']), order['学生学校名称'],
        order['咨询课程名称'], order['跟进顾问'], order['工单状态'], order['工单等级'], None,
        (signed - date(1899, 12, 30)).days if signed else None,
        (signed - assigned).days if signed and signed >= assigned else None,
        matching.get('courses'), float(cash) if cash is not None else None,
    ), strict=True))


def sync(*, client, config, query, snapshot_id, as_of, receipt_path=None):
    registry_path = Path(config['registry_path'])
    with _sync_lock(registry_path.parent):
        registry = json.loads(registry_path.read_text())
        return _sync(client, config, query, snapshot_id, as_of, registry_path, registry, receipt_path)


def _sync(client, config, query, snapshot_id, as_of, registry_path, registry, receipt_path):
    target = {key: config[key] for key in ('file_id', 'sheet_id')}
    as_of = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    through = as_of - timedelta(days=1)
    detail, cash = load_orders(query, date.fromisoformat(config['start_date']), through)
    sheets = _call_tool(client, 'sheet.get_sheet_info', {'file_id': target['file_id']})['sheets']
    matches = [s for s in sheets if str(s['sheet_id']) == target['sheet_id']]
    if len(matches) != 1:
        raise ValueError('dianping_sheet_not_unique')
    height, width = (int(matches[0][key]) for key in ('row_count', 'col_count'))
    header_row = config.get('header_row', 1)
    if type(header_row) is not int or not 0 <= header_row < height:
        raise ValueError('dianping_header_row_invalid')

    def read(first, last):
        cells, formulas = {}, set()
        page_rows = max(1, 1000 // width)
        for start in range(first, last + 1, page_rows):
            answer = _call_tool(client, 'sheet.get_cell_data', {
                **target, 'start_row': start, 'end_row': min(start + page_rows - 1, last),
                'start_col': 0, 'end_col': width - 1, 'return_csv': False, 'include_formula': True,
            })
            for cell in answer['cells']:
                coordinate = (int(cell['row']), int(cell['col']))
                if coordinate in cells:
                    raise ValueError('dianping_duplicate_remote_coordinate')
                key = {'STRING': 'string_value', 'NUMBER': 'number_value', 'BOOL': 'bool_value'}.get(cell.get('value_type'))
                cells[coordinate] = cell.get(key) if key else None
                if cell.get('formula') or cell.get('formula_value') or cell.get('value_type') == 'FORMULA':
                    formulas.add(coordinate)
        return cells, formulas

    header, _ = read(header_row, header_row)
    remote_headers = [header.get((header_row, col)) for col in range(width)]
    missing = [name for name in HEADERS if name not in remote_headers]
    if missing:
        return {'status': 'paused', 'reason': 'target_headers_missing', 'missing_headers': missing}
    try:
        columns = map_columns(HEADERS, remote_headers)
    except ValueError:
        return {'status': 'paused', 'reason': 'target_headers_ambiguous'}
    existing, formula_cells = read(header_row + 1, height - 1)
    key_col = columns[KEY]
    order_rows = {}
    for (row, column), value in existing.items():
        if column == key_col and (identity := _identifier(value)):
            if identity in order_rows:
                raise ValueError('dianping_duplicate_remote_id')
            order_rows[identity] = row
    compatible_cols = {columns[h] for h in HEADERS if h not in (MANUAL, KEY)}
    occupied = set(order_rows.values())
    if any(row not in occupied and col in compatible_cols and value not in (None, '')
           for (row, col), value in existing.items()):
        raise ValueError('dianping_uncommitted_data_rows_require_review')

    protected = {(str(row['work_order_id']), row['col']) for row in registry['protected_cells']}
    owned = {(str(row['work_order_id']), row['col']): row for row in registry['entries']
             if row.get('readback_verified') is True}
    logical = {header: col for col, header in enumerate(HEADERS)}
    source, keys, ownership = {}, {}, {}
    changed_rows = set()
    next_row = max([header_row, *(row for (row, _), value in existing.items() if value not in (None, '')),
                    *(row for row, _ in formula_cells)]) + 1
    sequence = max([0, *(v for (_, c), v in existing.items()
                       if c == columns['序号'] and isinstance(v, (int, float)) and not isinstance(v, bool))])
    for order in detail:
        identity = _identifier(order['ID'])
        row = order_rows.get(identity)
        if row is None:
            row = next_row
            next_row += 1
            sequence = int(sequence) + 1
            keys[row, key_col] = identity
        existing_sequence = existing.get((row, columns['序号']))
        values = values_for_order(order, cash.get(identity, {}), config, existing_sequence if identity in order_rows else sequence)
        for field, value in values.items():
            if field in (MANUAL, KEY) or value in (None, ''):
                continue
            cell = (row, columns[field])
            previous = existing.get(cell)
            registry_key = (identity, logical[field])
            last = owned.get(registry_key)
            if cell in formula_cells or registry_key in protected or previous == value:
                continue
            if previous not in (None, '') and (last is None or previous != last['last_written_value']):
                continue
            source[cell] = value
            ownership[cell] = (registry_key, previous)
            changed_rows.add(row)

    if next_row > height:
        _call_tool(client, 'sheet.insert_dimension', {
            **target, 'dimension_type': 'row', 'index': height - 1, 'count': next_row - height,
            'direction': 'after',
        })
    # Verify the original sheet values immediately before writing. Registry promotion follows both reads.
    if source or keys:
        rows = sorted(changed_rows | {row for row, _ in keys})
        first, last = rows[0], rows[-1]
        before = {(r, c): existing.get((r, c)) for r in rows for c in range(width)}
        observed, observed_formulas = read(first, last)
        if not readback_matches(observed, before) or any(cell in observed_formulas for cell in (*source, *keys)):
            raise ValueError('dianping_destination_changed')
        untouched = {cell: value for cell, value in before.items() if cell not in source}

        def write(cells):
            values = [_encode_cell(row, col, value) for (row, col), value in cells.items()]
            for offset in range(0, len(values), 200):
                _call_tool(client, 'sheet.set_range_value', {**target, 'values': values[offset:offset + 200]})
            for (row, col) in cells:
                if col == columns[SIGNED]:
                    _call_tool(client, 'sheet.set_cell_style', {
                        **target, 'start_row': row, 'end_row': row, 'start_col': col,
                        'end_col': col, 'number_format_pattern': 'yyyy-mm-dd',
                    })

        commit_with_readback(write, lambda: read(first, last)[0], source, keys, untouched)
        by_key = {(str(row['work_order_id']), row['col']): row for row in registry['entries']}
        for cell, value in source.items():
            (identity, col), previous = ownership[cell]
            by_key[identity, col] = {'work_order_id': identity, 'col': col,
                                     'value_type': _encode_cell(*cell, value)['value_type'],
                                     'last_written_value': value, 'before': previous,
                                     'readback_verified': True}
        registry['entries'] = list(by_key.values())
    registry['snapshot_id'] = snapshot_id
    result = {'status': 'passed', 'data_through': through.isoformat(), 'added': len(keys),
              'written_cells': len(source) + len(keys), 'readback_verified': True}
    if receipt_path is not None:
        _write_json(receipt_path, result)
        registry['last_success_receipt'] = str(receipt_path)
    _write_json(registry_path, registry)
    return result
