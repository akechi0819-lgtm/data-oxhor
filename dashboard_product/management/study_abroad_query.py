"""Run source queries against one explicit, isolated study-abroad Snapshot."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path

from data_platform.query.evidence import read_query_result
from data_platform.query.service import execute_query
from data_acquisition.jobs.build_study_abroad_warehouse import SCHEMA


SQL_ROOT = Path(__file__).with_name('sql') / 'study_abroad'
QUERY_NAMES = ('facts', 'monthly', 'people', 'checks')


def query_sql(query_name):
    if query_name not in QUERY_NAMES:
        raise ValueError('不支持的留学查询')
    body = (SQL_ROOT / f'{query_name}.sql').read_text(encoding='utf-8').strip().rstrip(';')
    if query_name in {'monthly', 'people'}:
        body = body.replace('__STUDY_ABROAD_FACTS__', query_sql('facts').strip().rstrip(';'))
    return body + ';\n'


def query_sample(*, workspace: Path, snapshot_id: str, run_id: str,
                 start_date: str, end_date: str, query_name: str = 'monthly') -> dict:
    return execute_sample_query(workspace=workspace, snapshot_id=snapshot_id, run_id=run_id,
                                start_date=start_date, end_date=end_date, sql=query_sql(query_name))


def execute_sample_query(*, workspace: Path, snapshot_id: str, run_id: str,
                         start_date: str, end_date: str, sql: str) -> dict:
    """Apply the same isolated-source identity checks to a product-owned SELECT."""
    workspace = Path(workspace).resolve()
    isolated = workspace / 'Work/StudyAbroad'
    pointer = json.loads((isolated / 'current.json').read_text(encoding='utf-8'))
    customer = json.loads((workspace / 'Work/workspace.json').read_text(encoding='utf-8'))
    if pointer.get('schema_version') != SCHEMA or pointer.get('company_id') != customer.get('company_id'):
        raise ValueError('留学仓客户身份不匹配')
    if pointer.get('snapshot_id') != snapshot_id:
        raise ValueError('显式Snapshot必须匹配留学仓当前指针')
    warehouse = (workspace / pointer['warehouse']).resolve()
    if not warehouse.is_relative_to((isolated / 'Runs').resolve()) or warehouse.name != 'warehouse.duckdb':
        raise ValueError('留学查询不能读取BI仓或工作区外部路径')
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if start >= end:
        raise ValueError('留学查询日期必须为左闭右开的有效区间')
    effective_end = min(end, date.fromisoformat(pointer['through_date']) + timedelta(days=1))
    if start >= effective_end:
        raise ValueError('查询区间晚于留学来源明确截止日')
    output = workspace / 'Output/StudyAbroad'
    result = execute_query(
        warehouse=warehouse, snapshot_id=snapshot_id, run_id=run_id,
        output_root=output, sql=sql,
        parameters=[start.isoformat(), effective_end.isoformat()],
        max_rows=10000, max_result_bytes=20_000_000,
    )
    if result['status'] != 'passed':
        raise ValueError('受控留学查询失败：' + json.dumps(result.get('errors', []), ensure_ascii=False))
    read_query_result(result, output_root=output)
    return result


def main():
    parser = argparse.ArgumentParser(description='查询隔离留学样本仓，输出同Snapshot查询回执')
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--snapshot-id', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--start-date', required=True)
    parser.add_argument('--end-date', required=True)
    parser.add_argument('--query-name', choices=QUERY_NAMES, default='monthly')
    args = parser.parse_args()
    try:
        print(json.dumps(query_sample(**vars(args)), ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
