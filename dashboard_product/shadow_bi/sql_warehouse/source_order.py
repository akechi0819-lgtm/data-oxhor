"""Import sealed source-query traversal, never legacy business calculations."""
from datetime import date
import json
from pathlib import Path

from data_platform.query.evidence import file_ref, resolve_file, snapshot_ref, verify_receipt


_TRAINING_SQL = Path(__file__).resolve().parents[2] / 'management/sql/training_details.sql'


def install_training_source_order(con, *, receipts, snapshot_id, warehouse):
    """Load explicit chronological training query receipts as identity lineage."""
    if not receipts:
        raise ValueError('marker audit requires explicit training source-order receipts')
    expected_snapshot = snapshot_ref(Path(warehouse), snapshot_id)
    approved_sql = _TRAINING_SQL.read_text().strip().rstrip(';')
    identities, seals, receipt_paths, input_paths, evidence = [], [], [], [], []
    previous_end = None
    for supplied in receipts:
        path = Path(supplied).resolve()
        receipt, data = verify_receipt(path)
        if receipt['snapshot_ref'] != expected_snapshot:
            raise ValueError('source-order receipt does not match the explicit training Snapshot')
        sql = resolve_file(path.parent, receipt['sql']).read_text().strip().rstrip(';')
        parameters = json.loads(resolve_file(path.parent, receipt['parameters']).read_text())
        if sql != approved_sql or not isinstance(parameters, list) or len(parameters) != 6:
            raise ValueError('source-order receipt must use the existing training_details query')
        if parameters[5] != ['主动', '被动']:
            raise ValueError('source-order receipt must include both acquisition modes')
        start, end = date.fromisoformat(parameters[0]), date.fromisoformat(parameters[1])
        if start >= end or (previous_end is not None and start < previous_end):
            raise ValueError('source-order receipts must be chronological and non-overlapping')
        previous_end = end
        seal = file_ref(path, path.parent, 'application/json')['sha256']
        receipt_paths.append(str(path))
        input_paths.extend([str(path), *(str(resolve_file(path.parent, receipt[field]))
                                       for field in ('sql', 'parameters', 'result'))])
        evidence.append({'receipt_sha256': seal, 'snapshot_ref': receipt['snapshot_ref'],
                         'run_id': receipt['run_id'], 'evidence_id': receipt['evidence_id'],
                         **{field + '_sha256': receipt[field]['sha256']
                            for field in ('sql', 'parameters', 'result')},
                         'start_date': start.isoformat(), 'end_date': end.isoformat(),
                         'row_count': len(data['rows'])})
        fields = data['columns']
        indices = [fields.index(name) for name in ('metric', 'work_order_id', 'source_row_number')]
        for row in data['rows']:
            metric, work_order, source_row = (row[index] for index in indices)
            if metric not in ('work_orders', 'passive_reported_cash'):
                raise ValueError('unexpected metric in training source-order receipt')
            identity = work_order if metric == 'work_orders' else source_row
            if identity is None or not str(identity).strip():
                raise ValueError('missing identity in training source-order receipt')
            identities.append({'metric': metric, 'identity': str(identity).strip(),
                               'source_order': len(identities) + 1, 'receipt_sha256': seal})
        seals.append((seal, receipt['run_id'], receipt['evidence_id'], snapshot_id,
                      receipt['snapshot_ref']['manifest_sha256'], receipt['snapshot_ref']['warehouse_sha256'],
                      receipt['sql']['sha256'], receipt['parameters']['sha256'], receipt['result']['sha256'],
                      start, end, len(data['rows'])))
    con.execute('CREATE SCHEMA IF NOT EXISTS source; CREATE SCHEMA IF NOT EXISTS meta')
    con.execute("""CREATE OR REPLACE TABLE source.training_source_order AS
        SELECT CASE WHEN r.metric='work_orders' THEN 'training:order:' ELSE 'training:cash:' END || r.identity AS fact_id,
            MIN(r.source_order)::BIGINT AS source_order,
            arg_min(r.receipt_sha256,r.source_order) AS receipt_sha256
        FROM unnest(?::STRUCT(metric VARCHAR,identity VARCHAR,source_order BIGINT,receipt_sha256 VARCHAR)[]) t(r)
        GROUP BY 1""", [identities])
    con.execute("""CREATE OR REPLACE TABLE meta.training_source_order_evidence (
        receipt_sha256 VARCHAR,run_id VARCHAR,evidence_id VARCHAR,snapshot_id VARCHAR,
        manifest_sha256 VARCHAR,warehouse_sha256 VARCHAR,sql_sha256 VARCHAR,
        parameters_sha256 VARCHAR,result_sha256 VARCHAR,start_date DATE,end_date DATE,row_count BIGINT)""")
    con.executemany('INSERT INTO meta.training_source_order_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', seals)
    return {'receipts': len(seals),
            'identities': con.execute('SELECT COUNT(*) FROM source.training_source_order').fetchone()[0],
            'source_order_receipts': receipt_paths, 'input_paths': input_paths, 'evidence': evidence}
