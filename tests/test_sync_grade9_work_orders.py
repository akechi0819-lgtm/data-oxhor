from datetime import date

from data_acquisition.jobs.sync_grade9_work_orders import sync


class Sheet:
    def __init__(self, headers, rows):
        self.data = {(r, c): value for r, values in enumerate([headers] + rows)
                     for c, value in enumerate(values) if value is not None}
        self.rows, self.cols = 5, len(headers)
        self.mutations = []

    def call_tool(self, name, params):
        if name == 'sheet.get_sheet_info':
            return {'sheets': [{'sheet_id': 'sheet', 'row_count': self.rows, 'col_count': self.cols}]}
        if name == 'sheet.get_cell_data':
            cells = []
            for (row, col), value in self.data.items():
                if params['start_row'] <= row <= params['end_row']:
                    cells.append({'row': row, 'col': col, 'value_type': 'STRING', 'string_value': value})
            return {'cells': cells}
        self.mutations.append(name)
        if name == 'sheet.set_range_value':
            for cell in params['values']:
                self.data[(cell['row'], cell['col'])] = cell.get('string_value', cell.get('number_value', cell.get('bool_value')))
        elif name == 'sheet.insert_dimension':
            self.rows += params['count']
        return {}


def relation(headers):
    return {'schema': 'landing', 'name': 'br_work_orders', 'columns':
            [{'name': 'c' + str(i), 'header_label': h} for i, h in enumerate(headers)] + [{'name': 'source_row_number'}]}


def run(sheet, source_headers, records):
    return sync(sheet, 'file', 'sheet', relation(source_headers),
                lambda sql, headers: {'columns': headers, 'rows': records}, date(2026, 11, 26), date(2026, 9, 1))


def test_missing_headers_pauses_before_query_and_writes():
    source_headers = ['ID', '工单状态', '学员状态值', '工单审批状态', '更新时间', '下次回访时间']
    sheet = Sheet(['ID', '工单状态'], [])
    result = sync(sheet, 'file', 'sheet', relation(source_headers),
                  lambda *_: (_ for _ in ()).throw(AssertionError('query called')),
                  date(2026, 11, 26), date(2026, 9, 1))
    assert result == {'status': 'paused', 'reason': 'target_headers_missing', 'missing_headers': source_headers[2:]}
    assert sheet.mutations == []


def test_updates_only_status_and_appends_and_is_idempotent():
    source_headers = ['ID', '工单状态', '年级校正', '主被动', '分配时间']
    sheet = Sheet(source_headers + ['人工备注'], [['1', '旧', '原年级', '原渠道', None, '保留']])
    records = [['1', '新', '9年级（初三）', '被动', None], ['2', '新单', '9年级（初三）', '被动', None]]
    assert run(sheet, source_headers, records)['status'] == 'passed'
    assert sheet.data[(1, 1)] == '新'
    assert sheet.data[(1, 2)] == '原年级'
    assert sheet.data[(1, 5)] == '保留'
    assert sheet.data[(2, 0)] == '2'
    sheet.mutations.clear()
    assert run(sheet, source_headers, records)['added'] == 0
    assert sheet.mutations == []


def test_partial_append_pauses_before_retrying():
    headers = ['ID', '工单状态', '年级校正', '主被动', '分配时间']
    sheet = Sheet(headers, [[None, None, '9年级（初三）', '被动', None]])
    assert run(sheet, headers, []) == {
        'status': 'paused', 'reason': 'grade9_uncommitted_data_rows_require_review',
    }
    assert sheet.mutations == []
