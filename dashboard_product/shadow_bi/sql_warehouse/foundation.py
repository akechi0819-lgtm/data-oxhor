"""Import explicit Snapshots through the existing read-only Data Platform API."""
from __future__ import annotations

import json
import time
from pathlib import Path

from data_platform.query.service import describe_warehouse, execute_query
from data_platform.query.evidence import read_query_result
from .relations import load_rows, quote


TABLES = {
    'training': ('br_work_orders__sheet_1f0596db9f25', 'br_cash__sheet_39b8dee2e4b3'),
    'abroad': ('study_abroad_market__resources', 'study_abroad_market__contracts', 'study_abroad_market__languages'),
}


def import_foundation(con, *, workspace, training_snapshot, abroad_snapshot, run_id, output_root):
    """The caller's connection is a new candidate, never the customer database."""
    workspace, output_root = Path(workspace).resolve(), Path(output_root).resolve()
    training = json.loads((workspace/'Work/workspace.json').read_text())
    abroad = json.loads((workspace/'Work/StudyAbroad/current.json').read_text())
    if training['current_snapshot_id']!=training_snapshot or abroad['snapshot_id']!=abroad_snapshot:
        raise ValueError('explicit Snapshot pair does not match frozen input')
    con.execute('CREATE SCHEMA IF NOT EXISTS landing')
    con.execute('CREATE SCHEMA IF NOT EXISTS meta')
    con.execute('CREATE TABLE meta.imports (source VARCHAR, snapshot_id VARCHAR, relation VARCHAR, row_count BIGINT, seconds DOUBLE)')
    receipts=[]
    for source, pointer, snapshot, path_key in (
        ('training', training, training_snapshot, 'current_warehouse_path'),
        ('abroad', abroad, abroad_snapshot, 'warehouse'),
    ):
        warehouse = workspace/pointer[path_key]
        description=describe_warehouse(warehouse=warehouse,snapshot_id=snapshot)
        for number, name in enumerate(TABLES[source]):
            spec=next(r for r in description['relations'] if r['schema']=='landing' and r['name']==name)
            columns={c['name']:c['type'] for c in spec['columns']}
            relation='landing.'+quote(name)
            con.execute(f'CREATE TABLE {relation} ('+','.join(quote(k)+' '+v for k,v in columns.items())+')')
            offset,count=0,0
            started=time.perf_counter()
            while True:
                response=execute_query(warehouse=warehouse,snapshot_id=snapshot,
                    run_id=f'{run_id}_{source}_{number}_{offset}',output_root=output_root,
                    sql=f'SELECT * FROM {relation} ORDER BY source_row_number LIMIT 5000 OFFSET {offset}',
                    max_rows=5000,max_result_bytes=50_000_000)
                if response.get('status')!='passed':
                    raise ValueError(response.get('errors'))
                data=read_query_result(response,output_root=output_root)
                rows=[dict(zip(data['columns'],r)) for r in data['rows']]
                receipts.append(response)
                if rows:
                    load_rows(con,'staging','page',rows,columns=columns)
                    con.execute(f'INSERT INTO {relation} SELECT * FROM staging.page')
                    con.execute('DROP TABLE staging.page')
                count+=len(rows)
                if len(rows)<5000:break
                offset+=5000
            con.execute('INSERT INTO meta.imports VALUES (?,?,?,?,?)',[source,snapshot,name,count,time.perf_counter()-started])
    return receipts


def sql_literal(value):
    if value is None:return 'NULL'
    if isinstance(value,list):return '['+','.join(sql_literal(v) for v in value)+']'
    if isinstance(value,(int,float)):return str(value)
    return "'"+str(value).replace("'","''")+"'"


def bind_sql(path, parameters):
    """Bind only product-owned SQL templates; no user-provided SQL interpolation."""
    return bind_text(Path(path).read_text(),parameters)


def bind_text(text,parameters):
    chunks=text.strip().rstrip(';').split('?')
    if len(chunks)!=len(parameters)+1:raise ValueError('SQL parameter count differs')
    return ''.join(part+sql_literal(value) for part,value in zip(chunks,parameters))+chunks[-1]
