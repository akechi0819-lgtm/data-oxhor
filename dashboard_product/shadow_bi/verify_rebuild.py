"""Read both libraries through Data Platform and compare complete relation content."""
from pathlib import Path
import argparse
import json
from data_platform.business_library import execute_library_query,read_library_result
from dashboard_product.online_team.build import read,write


def main():
    p=argparse.ArgumentParser();p.add_argument('--first',type=Path,required=True);p.add_argument('--second',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);a=p.parse_args()
    if a.evidence.exists():raise ValueError('拒绝覆盖已有复建验证')
    a.evidence.mkdir(parents=True)
    manifests=[read(x/'library_manifest.json') for x in (a.first,a.second)]
    if manifests[0]['binding']!=manifests[1]['binding']:raise AssertionError('输入/规则版本不一致')
    checks=[];responses=[]
    try:
        for name in manifests[0]['tables']:
            results=[]
            for i,(library,m) in enumerate(zip((a.first,a.second),manifests)):
                rows=[]
                count=m['tables'][name]['rows']
                size=3 if name=='selection_team_periods' else 10 if name in {'team_periods','periods'} else 2000
                for offset in range(0,count,size):
                    r=execute_library_query(library=library,batch_id=m['batch_id'],sql=f'SELECT row_json FROM queries."{name}" ORDER BY rowid LIMIT ? OFFSET ?',parameters=[size,offset],run_id=f'run_rebuild_{name}_{i}_{offset}',output_root=a.evidence/'queries',max_rows=size,max_result_bytes=200_000_000)
                    responses.append(r)
                    rows.extend(json.loads(x[0]) for x in read_library_result(r,output_root=a.evidence/'queries')['rows'])
                from dashboard_product.shadow_bi.library import table_digest
                actual=[len(rows),table_digest(rows)]
                expected=[m['tables'][name]['rows'],m['tables'][name]['logical_sha256']]
                if actual!=expected:raise AssertionError(f'{name} 库{i} 内容摘要不匹配: {actual} != {expected}')
                results.append(actual)
            if results[0]!=results[1]:raise AssertionError(f'{name} 两次复建内容不一致')
            checks.append({'table':name,'rows':results[0][0],'logical_sha256':results[0][1]})
        write(a.evidence/'verification.json',{'status':'passed','batches':[m['batch_id'] for m in manifests],'tables':checks,'controlled_queries':len(responses),'input_rule_bindings_equal':True})
        print(json.dumps({'status':'passed','tables':len(checks),'controlled_queries':len(responses)}))
    except Exception as e:
        write(a.evidence/'verification.json',{'status':'failed','tables':checks,'error':str(e)});raise
    finally:write(a.evidence/'responses.json',responses)
if __name__=='__main__':main()
