"""受控读取本地 SQL 迁移候选；不切换正式 Snapshot 或发布指针。"""
from pathlib import Path
import json

from data_platform.query.evidence import encode,file_ref,resolve_file
from data_platform.query.service import (_connect,validate_query,_validate_business_query_ast,
                                         _json_value,QueryError,RUN_ID)


def query_candidate(*, candidate, batch_id, sql, run_id, output_root, parameters=None,
                    max_rows=10000,max_result_bytes=20_000_000,semantic=False):
    candidate,output_root=Path(candidate).resolve(),Path(output_root).resolve()
    manifest_path=candidate/'candidate.json'
    manifest=json.loads(manifest_path.read_bytes())
    if manifest.get('schema_version')!='sql_warehouse_candidate.v1' or manifest.get('batch_id')!=batch_id:
        raise QueryError('CANDIDATE_IDENTITY_INVALID','候选身份与显式批次不匹配')
    if not RUN_ID.fullmatch(run_id) or min(max_rows,max_result_bytes)<1:
        raise QueryError('QUERY_LIMIT_INVALID','run_id或查询限制无效')
    database=resolve_file(candidate,manifest['database'])
    if database.name!='warehouse.duckdb':raise QueryError('CANDIDATE_IDENTITY_INVALID','候选库文件名无效')
    with _connect(database) as con:
        if con.execute('SELECT batch_id FROM meta.identity').fetchall()!=[(batch_id,)]:
            raise QueryError('CANDIDATE_IDENTITY_INVALID','库内批次不匹配')
        semantic_allowed=None
        if semantic:
            from data_platform.sql_release_query import SEMANTIC_RELATIONS
            semantic_allowed=frozenset(manifest.get('semantic_relations', []))
            if not semantic_allowed or not semantic_allowed <= SEMANTIC_RELATIONS:
                raise QueryError('QUERY_REJECTED','候选语义关系不在只读范围')
        _validate_business_query_ast(con,sql,allowed_relations=set(manifest['query_relations']),
            allowed_schema='business',allowed_table_macros=() if semantic else set(manifest.get('query_macros', [])),
            allowed_qualified=semantic_allowed)
        validate_query(con,sql,parameters,allowed_schemas=set(manifest['schemas']))
        cur=con.execute(sql,parameters)
        columns=[c[0] for c in cur.description];rows=cur.fetchmany(max_rows+1)
    data={'columns':columns,'rows':[[_json_value(v) for v in row] for row in rows]}
    if len(rows)>max_rows or len(encode(data))>max_result_bytes:
        raise QueryError('QUERY_LIMIT_EXCEEDED','候选查询超出显式限制')
    out=output_root/run_id
    out.mkdir(parents=True,exist_ok=False)
    (out/'result.json').write_bytes(encode(data));(out/'query.sql').write_text(sql)
    (out/'parameters.json').write_bytes(encode(parameters))
    receipt={'schema_version':'sql_candidate_query.v1','batch_id':batch_id,'run_id':run_id,
        'candidate_ref':file_ref(manifest_path,candidate,'application/json'),
        'database_ref':manifest['database'],'snapshots':manifest['snapshots'],
        'columns':columns,'row_count':len(rows),
        **{k:file_ref(out/f,out,m) for k,f,m in [('result','result.json','application/json'),
          ('sql','query.sql','text/plain'),('parameters','parameters.json','application/json')]}}
    (out/'receipt.json').write_bytes(encode(receipt))
    return {'status':'passed','batch_id':batch_id,'run_id':run_id,'result':data,
            'receipt':file_ref(out/'receipt.json',output_root,'application/json')}
