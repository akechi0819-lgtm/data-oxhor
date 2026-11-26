import json
from pathlib import Path

import duckdb

from data_acquisition.jobs.sync_dianping import HEADERS, sync
from ops.cli import _selected_status
from ops.sheets import run_sheets
from ops.state import OpsState


class Sheet:
    def __init__(self):
        headers = list(HEADERS)
        headers.insert(5, '人工备注')
        self.cols = {header: index for index, header in enumerate(headers)}
        self.grid = {(1, col): name for col, name in enumerate(headers)}
        self.grid[(2, self.cols['工单ID'])] = 'A'
        self.grid[(2, self.cols['工单情况'])] = '人工'
        self.grid[(2, self.cols['人工备注'])] = '保留'
        self.grid[(2, self.cols['签约课程'])] = '原课程'
        self.rows = 3
        self.writes = []
        self.styles = []

    def call_tool(self, name, params):
        if name == 'sheet.get_sheet_info':
            return {'sheets': [{'sheet_id': 'sheet', 'row_count': self.rows, 'col_count': len(self.cols)}]}
        if name == 'sheet.get_cell_data':
            return {'cells': [{'row': r, 'col': c, 'value_type': 'NUMBER', 'number_value': v}
                              if isinstance(v, (int, float))
                              else {'row': r, 'col': c, 'value_type': 'STRING', 'string_value': v}
                              for (r, c), v in self.grid.items() if params['start_row'] <= r <= params['end_row']]}
        if name == 'sheet.insert_dimension':
            self.rows += params['count']
        if name == 'sheet.set_range_value':
            self.writes.append(params['values'])
            for cell in params['values']:
                self.grid[cell['row'], cell['col']] = cell.get('number_value', cell.get('string_value'))
        if name == 'sheet.set_cell_style':
            self.styles.append(params)
        return {}


def test_dianping_aggregates_cash_and_uses_native_dates_and_registry(tmp_path):
    sheet = Sheet()
    path = tmp_path / 'registry.json'
    path.write_text(json.dumps({'protected_cells': [{'work_order_id': 'A', 'col': HEADERS.index('签约课程')}],
                                'entries': []}))
    con = duckdb.connect()
    con.execute('CREATE SCHEMA landing')
    con.execute("""CREATE TABLE landing.br_work_orders__sheet_1f0596db9f25 AS
                   SELECT * FROM (VALUES ('A','u1'),('B','u2')) orders("ID","学员号")
                   CROSS JOIN (SELECT '大众点评' AS "二级渠道", '46350' AS "分配时间", 'r' AS "资源id",
                      '示例' AS "姓名", '' AS "资源描述", '初三' AS "年级名称", '校区' AS "团队",
                      '学校' AS "学生学校名称", '课程' AS "咨询课程名称", '顾问' AS "跟进顾问",
                      '签约' AS "工单状态", 'B' AS "工单等级", 'FY27 Q2' AS "财季") attrs""")
    con.execute("""CREATE TABLE landing.br_cash__sheet_39b8dee2e4b3 AS
                   SELECT * FROM (VALUES (1,'A','','u1','46352','120','课A'),
                                         (2,'','','u1','46353','80','课B'),
                                         (3,'B','','u2','46353','20','课A'))
                   c(source_row_number,"工单ID","工单ID__2","学员编号","业务日期","现金收入","课程产品名称")""")

    def query(sql, params):
        result = con.execute(sql, params)
        rows = [dict(zip([spec[0] for spec in result.description], row)) for row in result.fetchall()]
        if 'max_business_date' in sql:
            for row in rows:
                row['max_business_date'] = '2026-11-30'
        return rows

    config = {'registry_path': str(path), 'file_id': 'file', 'sheet_id': 'sheet', 'start_date': '2026-11-01'}
    result = sync(client=sheet, config=config, query=query, snapshot_id='snapshot', as_of='2026-12-01')
    assert result['added'] == 1 and result['readback_verified']
    assert sheet.grid[2, sheet.cols['签约金额']] == 200
    assert sheet.grid[2, sheet.cols['签约时间']] == 46352
    assert sheet.styles[0]['number_format_pattern'] == 'yyyy-mm-dd'
    assert sheet.grid[2, sheet.cols['签约课程']] == '原课程'
    assert sheet.grid[2, sheet.cols['人工备注']] == '保留'
    assert sheet.grid[2, sheet.cols['工单情况']] == '人工'
    assert not any(c['col'] == sheet.cols['工单ID'] for c in sheet.writes[0])
    assert sheet.writes[-1] == [{'row': 3, 'col': sheet.cols['工单ID'], 'value_type': 'STRING', 'string_value': 'B'}]
    sheet.writes.clear()
    assert sync(client=sheet, config=config, query=query, snapshot_id='snapshot', as_of='2026-12-01')['written_cells'] == 0
    assert not sheet.writes


def test_paused_job_does_not_block_other_jobs_and_status_shows_reason(tmp_path, capsys):
    passed = lambda: {'status': 'passed', 'added': 1}
    results = run_sheets(tmp_path, tmp_path / 'runtime', day='2026-11-26', adapters={
        'content': passed, 'dianping': passed,
        'grade9': lambda: {'status': 'paused', 'reason': 'target_headers_missing', 'missing_headers': ['更新时间']},
    })
    assert results['status'] == 'partial'
    assert results['sheets']['dianping']['status'] == 'passed'
    _selected_status(tmp_path / 'runtime', '2026-11-26')
    assert '初三 paused target_headers_missing 更新时间' in capsys.readouterr().out


def test_active_sheet_does_not_block_other_jobs(tmp_path):
    runtime = tmp_path / 'runtime'
    state = OpsState(runtime)
    state.acquire('active', 'sync_content', '2026-11-26')
    passed = lambda: {'status': 'passed'}
    result = run_sheets(tmp_path, runtime, day='2026-11-26', adapters={
        'dianping': passed, 'grade9': passed,
    })
    assert result['sheets'] == {
        'content': {'status': 'paused', 'reason': 'sheet_run_already_active'},
        'dianping': {'status': 'passed'},
        'grade9': {'status': 'passed'},
    }
