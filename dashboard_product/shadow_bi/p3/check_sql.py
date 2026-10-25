"""受控查询核对所有 P3 投影；保留实际 SQL、结果与来源回执。"""
import json
import re
from datetime import datetime,UTC
from data_platform.business_library import execute_library_query,read_library_result
from dashboard_product.shadow_bi.p3.catalog import VIEWS,AUDIT,LIBRARY,BATCH

def render(sql,mask=7):
 sql=re.sub(r'{%.*?%}','',sql,flags=re.S)
 return sql.replace('{{ acquisition_scope }}','被动').replace('{{ mask }}',str(mask)).strip()
def main():
 out=AUDIT/'evidence'/('sql-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%S'))
 checks=[]
 for i,v in enumerate(VIEWS):
  try:
   pred=[]
   for k,val in v.filters.items():
    if k=='业务组':continue
    values=val if isinstance(val,list) else [val];pred.append('\"'+k+'\" IN ('+','.join("'"+str(x).replace("'","''")+"'" for x in values)+')')
   source='SELECT * FROM ('+render(v.sql)+') filtered'+(' WHERE '+' AND '.join(pred) if pred else '')
   sql='SELECT * FROM ('+source+') p3 LIMIT 2'
   if v.more and v.more.get('query_mode')=='aggregate':
    cols=v.more['groupby'];metrics=v.more['metrics'];sql='SELECT '+', '.join(['\"'+x+'\"' for x in cols]+[m['sqlExpression']+' AS \"'+m['label']+'\"' for m in metrics])+' FROM ('+source+') p3 GROUP BY '+', '.join('\"'+x+'\"' for x in cols)+' LIMIT 2'
   r=execute_library_query(library=LIBRARY,batch_id=BATCH,sql=sql,run_id=f'run_p3_sql_{i:03}',output_root=out,max_rows=2,max_result_bytes=100000)
   d=read_library_result(r,output_root=out)
   missing=(set(v.columns)-set(d['columns'])) if v.viz=='table' else set()
   if missing:raise ValueError('缺列 '+str(missing))
   checks.append({'key':v.key,'status':'passed','columns':d['columns'],'rows':d['rows'],'receipt':r['receipt']})
   print(v.key,'passed')
  except Exception as e:
   checks.append({'key':v.key,'status':'failed','error':str(e)});print(v.key,str(e))
 out.mkdir(exist_ok=True,parents=True);(out/'summary.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
 print('OUTPUT',out)
 if any(c['status']=='failed' for c in checks):raise SystemExit(1)
if __name__=='__main__':main()
