"""显式批次业务查询库的describe/query受控入口。"""
import argparse
import json
from pathlib import Path
from data_platform.business_library import describe_library,execute_library_query

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['describe','query'])
    p.add_argument('--library',type=Path,required=True);p.add_argument('--batch-id',required=True)
    p.add_argument('--sql-file',type=Path);p.add_argument('--params-json',default='null');p.add_argument('--run-id');p.add_argument('--output-root',type=Path)
    p.add_argument('--max-rows',type=int,default=1000);p.add_argument('--max-result-bytes',type=int,default=1_000_000)
    a=p.parse_args()
    try:
        if a.command=='describe':result=describe_library(library=a.library,batch_id=a.batch_id)
        else:
            if not (a.sql_file and a.run_id and a.output_root):p.error('query必须提供sql-file/run-id/output-root')
            result=execute_library_query(library=a.library,batch_id=a.batch_id,sql=a.sql_file.read_text(),parameters=json.loads(a.params_json),run_id=a.run_id,output_root=a.output_root,max_rows=a.max_rows,max_result_bytes=a.max_result_bytes)
        print(json.dumps(result,ensure_ascii=False,default=str));return 0
    except (ValueError,OSError,KeyError) as e:
        print(json.dumps({'status':'failed','error':str(e)},ensure_ascii=False));return 1
if __name__=='__main__':raise SystemExit(main())
