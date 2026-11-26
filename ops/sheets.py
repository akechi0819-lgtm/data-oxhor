"""Run the three sheet adapters and persist their independent outcomes."""
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .pipeline import _tracked_run
from .state import OpsState, RunActiveError

JOBS = ('content', 'dianping', 'grade9')
ORDERS = 'br_work_orders__sheet_1f0596db9f25'


def _config(workspace, job):
    base = workspace / '.private'
    path = base / f'{job}-sync.json'
    if not path.is_file():
        raise ValueError(f'{job}_sync_config_missing')
    result = json.loads(path.read_text())
    for key in ('token_file', 'registry_path'):
        if key in result:
            result[key] = str((base / result[key]).resolve())
    return result


def _source(workspace, *, expected_snapshot):
    pointer = json.loads((workspace / 'Work/workspace.json').read_text())
    snapshot = pointer['current_snapshot_id']
    database = (workspace / pointer['current_warehouse_path']).resolve(strict=True)
    if not database.is_relative_to(workspace) or (expected_snapshot and snapshot != expected_snapshot):
        raise ValueError('BI_snapshot_binding_changed')
    return snapshot, database


def _content(workspace, *, day, run_id, expected_snapshot):
    from data_acquisition.jobs.daily_warehouses import assert_daily_ready
    from data_acquisition.jobs.sync_content_work_orders import SyncError, sync

    receipt = assert_daily_ready(workspace, day, bi_snapshot_id=expected_snapshot)
    orders = receipt['sources']['bi']['orders_export']
    path = Path(orders['path']).resolve(strict=True)
    if not path.is_relative_to(workspace):
        raise ValueError('content_export_outside_workspace')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != orders['sha256']:
            raise ValueError('content_export_digest_mismatch')
    try:
        result = sync(workspace, path, day, run_id)
    except SyncError as error:
        reason = str(error)
        status = 'paused' if reason.startswith('remote_') else 'failed'
        return {'status': status, 'reason': reason}
    return {**result, 'data_through': min(day, receipt['sources']['bi']['coverage']['orders_max_date']),
            'readback_verified': result['readback_status'] == 'passed'}


def _snapshot_job(workspace, *, job, day, run_id, evidence, expected_snapshot):
    from data_acquisition.connectors.tencent_docs.mcp import TencentDocsMCPClient
    from data_platform.query.evidence import read_query_result
    from data_platform.query.service import describe_warehouse, execute_query

    config = _config(workspace, job)
    snapshot, database = _source(workspace, expected_snapshot=expected_snapshot)
    as_of = date.fromisoformat(day)
    if job == 'grade9':
        # Preserve the existing refresh proof gate. A complete table schema alone cannot
        # certify that the current day's input has arrived.
        from data_acquisition.jobs.daily_warehouses import assert_daily_ready
        receipt = assert_daily_ready(workspace, day, bi_snapshot_id=snapshot)
        if receipt['sources']['bi']['coverage']['orders_max_date'] < (as_of - timedelta(days=1)).isoformat():
            raise ValueError('grade9_snapshot_coverage_short')

    def records(sql, parameters=None):
        result = execute_query(warehouse=database, snapshot_id=snapshot, sql=sql,
                               run_id=run_id, output_root=evidence, parameters=parameters,
                               max_rows=100_000, max_result_bytes=50_000_000)
        return read_query_result(result, output_root=evidence)

    client = TencentDocsMCPClient(Path(config['token_file']))
    if job == 'dianping':
        from data_acquisition.jobs.sync_dianping import sync

        def query(sql, parameters):
            payload = records(sql, parameters)
            return [dict(zip(payload['columns'], row)) for row in payload['rows']]
        return sync(client=client, config=config, query=query, snapshot_id=snapshot,
                    as_of=as_of, receipt_path=evidence / run_id / 'sync-receipt.json')

    from data_acquisition.jobs.sync_grade9_work_orders import sync

    relation = next(item for item in describe_warehouse(warehouse=database, snapshot_id=snapshot)['relations']
                    if item['schema'] == 'landing' and item['name'] == ORDERS)
    return sync(client, config['file_id'], config['sheet_id'], relation,
                lambda sql, _headers: records(sql), as_of, date.fromisoformat(config['start_date']))


def run_sheets(workspace, runtime, *, job='all', day, snapshot_id=None, adapters=None):
    state = OpsState(runtime)
    evidence = runtime / 'sheet-evidence'
    all_results = {}
    for name in JOBS if job == 'all' else (job,):
        run_id = f'run_sync_{name}_{uuid4().hex[:16]}'
        pipeline = 'sync_' + name
        try:
            with _tracked_run(state, run_id, pipeline, day):
                try:
                    if adapters is not None:
                        result = adapters[name]()
                    elif name == 'content':
                        result = _content(workspace, day=day, run_id=run_id, expected_snapshot=snapshot_id)
                    else:
                        result = _snapshot_job(workspace, job=name, day=day, run_id=run_id,
                                               evidence=evidence, expected_snapshot=snapshot_id)
                except (ValueError, OSError, KeyError, RuntimeError, StopIteration) as error:
                    code = str(error) if isinstance(error, ValueError) and str(error).replace('_', '').isalnum() else type(error).__name__
                    result = {'status': 'paused' if code.endswith(('_missing', '_short')) else 'failed', 'reason': code}
                status = result['status']
                summary = {key: result[key] for key in (
                    'status', 'reason', 'missing_headers', 'missing_columns', 'data_through', 'added',
                    'written_cells', 'readback_verified',
                ) if key in result}
                if 'error' in result:
                    summary['reason'] = result['error']
                state.record_stage(run_id, 'sync', status, detail=summary)
                if status == 'passed':
                    state.observe_pointer(pipeline, run_id, result.get('data_through', day), verified=True)
                state.end(run_id, 'complete' if status == 'passed' else status, summary=summary,
                          error_code=summary.get('reason'))
                all_results[name] = summary
        except RunActiveError:
            all_results[name] = {'status': 'paused', 'reason': 'sheet_run_already_active'}
    return {'status': 'complete' if all(x['status'] == 'passed' for x in all_results.values()) else 'partial',
            'sheets': all_results}
