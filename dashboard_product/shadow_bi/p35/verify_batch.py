"""受控查询逐表比较当前源批次与展示批次，保留排序行内容摘要。"""
import json
from datetime import datetime,UTC
from data_platform.business_library import execute_library_query,read_library_result
from dashboard_product.shadow_bi.p3.catalog import ROOT,SOURCE_LIBRARY,SOURCE_BATCH,LIBRARY,BATCH

def main():
    out=ROOT/'.local/audits/shadow-bi-p35-20261023'/('batch-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%S'))
    source=json.loads((SOURCE_LIBRARY/'library_manifest.json').read_text())
    display=json.loads((LIBRARY/'library_manifest.json').read_text())
    checks=[]
    for i,(table,spec) in enumerate(source['tables'].items()):
        expr='CAST(row_json AS VARCHAR)' if 'row_json' in spec['columns'] else 'CAST(to_json(t) AS VARCHAR)'
        sql=f'SELECT COUNT(*) AS rows, sha256(string_agg({expr}, chr(10) ORDER BY {expr})) AS content_sha256 FROM queries.{table}'
        results=[]
        for label,library,batch in [('source',SOURCE_LIBRARY,SOURCE_BATCH),('display',LIBRARY,BATCH)]:
            r=execute_library_query(library=library,batch_id=batch,sql=sql,run_id=f'run_p35_same_batch_{i:02}_{label}',output_root=out,max_rows=1,max_result_bytes=10000)
            results.append(read_library_result(r,output_root=out)['rows'][0])
        assert results[0]==results[1],(table,results)
        assert spec['logical_sha256']==display['tables'][table]['logical_sha256']
        checks.append({'table':table,'status':'passed','rows':results[0][0],'content_sha256':results[0][1]})
        print(table,'passed',flush=True)
    (out/'summary.json').write_text(json.dumps({'source_batch':SOURCE_BATCH,'display_batch':BATCH,'checks':checks},ensure_ascii=False,indent=2))
    print(out)
if __name__=='__main__':main()
