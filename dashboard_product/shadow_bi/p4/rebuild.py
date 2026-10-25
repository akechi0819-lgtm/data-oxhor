"""从封存表文件确定性重建派生仓；原始客户Snapshot不在此入口打开。"""
import argparse, hashlib, json, os
from pathlib import Path
from datetime import datetime, UTC
import duckdb


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def rebuild(incoming, target):
    manifest=json.loads((incoming/'library_manifest.json').read_text())
    if target.exists():raise ValueError('拒绝覆盖批次')
    for name,spec in manifest['tables'].items():
        rel=Path(spec['data']['path'])
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('表路径越界')
        file=incoming/rel
        if sha(file)!=spec['data']['sha256'] or file.stat().st_size!=spec['data']['size_bytes']:raise ValueError('表摘要不符:'+name)
    target.mkdir(parents=True)
    database=target/'business.duckdb'
    with duckdb.connect(str(database),config={'memory_limit':'256MB','threads':1}) as con:
        con.execute('CREATE SCHEMA queries')
        for name,spec in manifest['tables'].items():
            q='"'+name.replace('"','""')+'"'
            types=spec['columns']
            if spec['rows']:
                con.execute(f'CREATE TABLE queries.{q} AS SELECT * FROM read_json(?, columns=?, format=\'newline_delimited\')',[str(incoming/spec['data']['path']),types])
            else:con.execute(f'CREATE TABLE queries.{q} (row_json JSON)')
            count=con.execute(f'SELECT count(*) FROM queries.{q}').fetchone()[0]
            if count!=spec['rows']:raise ValueError('表行数不符:'+name)
        con.execute('CREATE TABLE queries.batch(batch_id VARCHAR)')
        con.execute('INSERT INTO queries.batch VALUES (?)',[manifest['batch_id']])
    source_db=manifest['database']
    manifest['database']={**source_db,'path':'business.duckdb','size_bytes':database.stat().st_size,'sha256':sha(database)}
    manifest['server_rebuild']={'created_at':datetime.now(UTC).isoformat(),'upstream_database':source_db,'verified_tables':len(manifest['tables']),'method':'typed sealed JSONL rebuild; no business recalculation'}
    (target/'library_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    # 来源表保留于incoming；应用仅只读业务库，不持有来源文件权限。
    print(json.dumps({'batch':manifest['batch_id'],'tables':len(manifest['tables']),'database_sha256':manifest['database']['sha256']}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--incoming',type=Path,required=True);p.add_argument('--target',type=Path,required=True);a=p.parse_args();rebuild(a.incoming,a.target)
