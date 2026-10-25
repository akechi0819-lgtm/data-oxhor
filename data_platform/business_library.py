"""受控查询已封口的业务派生库；来源绑定与原始Snapshot查询合同分开。"""
from __future__ import annotations
from datetime import UTC, datetime
from pathlib import Path
import json
import re
import uuid
from data_platform.query.evidence import (encode, file_ref, resolve_file, producer, metadata, EvidenceError)
from data_platform.query.service import _connect, validate_query, _json_value, _provenance_sql, QueryError, RUN_ID


def load_library(library: Path, batch_id: str):
    library=library.resolve()
    path=library/'library_manifest.json'
    manifest=json.loads(path.read_bytes())
    if manifest.get('schema_version')!='business_query_library.v1' or manifest.get('batch_id')!=batch_id:
        raise QueryError('LIBRARY_IDENTITY_INVALID','显式批次与业务库不匹配')
    if not manifest.get('snapshots') or not manifest.get('binding',{}).get('inputs') or not manifest.get('binding',{}).get('rules') or not manifest.get('source_queries'):
        raise QueryError('LIBRARY_PROVENANCE_INVALID','业务库缺少Snapshot/规则/输入/查询来源绑定')
    db=resolve_file(library,manifest['database'])
    if db.name!='business.duckdb': raise QueryError('LIBRARY_IDENTITY_INVALID','业务库文件名无效')
    return manifest,db,file_ref(path,library,'application/json')


def describe_library(*, library: Path, batch_id: str):
    manifest,db,ref=load_library(library,batch_id)
    with _connect(db) as con:
        if con.execute('SELECT batch_id FROM queries.batch').fetchall()!=[(batch_id,)]:
            raise QueryError('LIBRARY_IDENTITY_INVALID','业务库内部批次不匹配')
        columns=con.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='queries' ORDER BY table_name,ordinal_position").fetchall()
    return {'schema_version':'business_library_description.v1','status':'passed','batch_id':batch_id,
            'library_ref':ref,'snapshots':manifest['snapshots'],'tables':manifest['tables'], 'columns':columns}


def execute_library_query(*, library: Path, batch_id: str, sql: str, run_id: str,
                          output_root: Path, parameters=None, max_rows=1000, max_result_bytes=1_000_000):
    if not RUN_ID.fullmatch(run_id): raise QueryError('RUN_ID_INVALID','无效run_id')
    if min(max_rows,max_result_bytes)<1: raise QueryError('QUERY_LIMIT_INVALID','查询限制必须为正数')
    manifest,db,ref=load_library(library,batch_id)
    with _connect(db) as con:
        if con.execute('SELECT batch_id FROM queries.batch').fetchall()!=[(batch_id,)]:
            raise QueryError('LIBRARY_IDENTITY_INVALID','业务库内部批次不匹配')
        validate_query(con,sql,parameters)
        names=sorted(con.get_table_names(_provenance_sql(con,sql),qualified=True))
        # All business data resides in the existing allowed queries schema.
        relations=set(manifest['tables'])|{'batch'}
        allowed={f'queries.{name}' for name in relations}|{f'{db.stem}.queries.{name}' for name in relations}
        if any(name.replace('"','') not in allowed for name in names):
            raise QueryError('QUERY_PROVENANCE_INVALID','查询引用未登记的业务关系')
        cur=con.execute(sql,parameters)
        columns=[x[0] for x in cur.description];rows=cur.fetchmany(max_rows+1)
    if len(rows)>max_rows: raise QueryError('QUERY_LIMIT_EXCEEDED','超过行数限制，必须明确分页')
    data={'columns':columns,'rows':[[_json_value(x) for x in row] for row in rows]}
    raw=encode(data)
    if len(raw)>max_result_bytes: raise QueryError('QUERY_LIMIT_EXCEEDED','超过字节限制，必须明确分页')
    eid='evidence_'+uuid.uuid4().hex
    root=output_root/run_id/'data/business_query_results'/eid
    if not root.resolve().is_relative_to(output_root.resolve()): raise ValueError('输出路径越界')
    root.mkdir(parents=True,exist_ok=False)
    for name,value in [('query.sql',sql.encode()),('parameters.json',encode(parameters)),('result.json',raw)]:
        (root/name).write_bytes(value)
    receipt={'schema_version':'business_query_receipt.v1','kind':'business_query','batch_id':batch_id,
        'run_id':run_id,'created_at':datetime.now(UTC).isoformat(),'producer':producer('data_platform.business_library'),
        'library_ref':ref,'database_ref':manifest['database'],'snapshots':manifest['snapshots'],
        'source_queries':manifest['source_queries'],'binding_sha256':__import__('hashlib').sha256(encode(manifest['binding'])).hexdigest(),
        'referenced_relations':names,'columns':columns,'row_count':len(rows),
        'limits':{'max_rows':max_rows,'max_result_bytes':max_result_bytes},
        **{key:file_ref(root/name,root,mime) for key,name,mime in [('sql','query.sql','text/plain'),('parameters','parameters.json','application/json'),('result','result.json','application/json')]}}
    (root/'receipt.json').write_bytes(encode(receipt))
    verify_library_receipt(root/'receipt.json')
    return {'schema_version':'business_query_result.v1','status':'passed','batch_id':batch_id,'run_id':run_id,
            'receipt':file_ref(root/'receipt.json',output_root/run_id,'application/json'),
            'result':data if len(raw)<=64_000 else None}


def verify_library_receipt(path):
    doc=json.loads(path.read_bytes())
    if doc.get('schema_version')!='business_query_receipt.v1' or doc.get('kind')!='business_query': raise EvidenceError('业务查询回执版本无效')
    metadata({**doc,'snapshot_id':doc['batch_id']})
    for field in ('library_ref','database_ref'):
        ref=doc[field]
        if not re.fullmatch('[0-9a-f]{64}',ref['sha256']) or ref['size_bytes']<1: raise EvidenceError('业务库摘要无效')
    data=json.loads(resolve_file(path.parent,doc['result']).read_bytes())
    resolve_file(path.parent,doc['sql']);json.loads(resolve_file(path.parent,doc['parameters']).read_bytes())
    if data['columns']!=doc['columns'] or len(data['rows'])!=doc['row_count'] or any(len(r)!=len(data['columns']) for r in data['rows']): raise EvidenceError('结果与回执不一致')
    if len(data['rows'])>doc['limits']['max_rows'] or len(encode(data))>doc['limits']['max_result_bytes']: raise EvidenceError('结果超过声明限制')
    if not doc['snapshots'] or not doc['source_queries'] or not re.fullmatch('[0-9a-f]{64}',doc['binding_sha256']): raise EvidenceError('来源回执不完整')
    return doc,data


def read_library_result(response, *, output_root):
    if response.get('schema_version')!='business_query_result.v1' or response.get('status')!='passed' or not RUN_ID.fullmatch(response.get('run_id','')): raise EvidenceError('业务查询响应无效')
    receipt=resolve_file(output_root/response['run_id'],response['receipt'])
    doc,data=verify_library_receipt(receipt)
    if any(response[k]!=doc[k] for k in ('batch_id','run_id')):raise EvidenceError('响应身份不匹配')
    if response.get('result') is not None and response['result']!=data:raise EvidenceError('内联结果不匹配')
    return data
