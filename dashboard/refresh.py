#!/usr/bin/env python3
import argparse,datetime as dt,json,subprocess,uuid,csv
from pathlib import Path
ROOT=Path(__file__).resolve().parent; DEFAULT_WAREHOUSE=ROOT.parent/'customers/bi_operations/Work/Runs/run_bi_full_20260902_r2/data/snapshots/snapshot_bi_full_20260902_r2/warehouse.duckdb'; SNAPSHOT='snapshot_bi_full_20260902_r2'; STARTS={'Q1':dt.date(2026,6,1),'Q2':dt.date(2026,9,1),'Q3':dt.date(2026,12,1),'Q4':dt.date(2027,3,1)}
def window(q): return (STARTS['Q1'],dt.date(2027,6,1)) if q=='全年' else (STARTS[q],{'Q1':STARTS['Q2'],'Q2':STARTS['Q3'],'Q3':STARTS['Q4'],'Q4':dt.date(2027,6,1)}[q])
def query(warehouse,run,out,sql,params):
 c=['python3','-m','interfaces.data_foundation','query','--warehouse',str(warehouse),'--snapshot-id',SNAPSHOT,'--run-id',run,'--output-root',str(out),'--sql-file',str(sql),'--params-json',json.dumps(params),'--max-rows','100']; p=subprocess.run(c,cwd=ROOT.parent,text=True,capture_output=True); (out/'stdout.txt').write_text(p.stdout); (out/'stderr.txt').write_text(p.stderr)
 if p.returncode: raise SystemExit(p.stderr or p.stdout)
 return json.loads(p.stdout)
def main():
 a=argparse.ArgumentParser(); a.add_argument('--quarter',choices=['Q1','Q2','Q3','Q4','全年'],default='全年'); a.add_argument('--warehouse',default=str(DEFAULT_WAREHOUSE)); x=a.parse_args(); start,end=window(x.quarter); rules=list(csv.DictReader((ROOT/'config/team_mapping.csv').open())); rule=next((r for r in rules if r['source_team']=='无法判断'),None)
 if not rule or rule['target_team']!='前途出国' or rule['include_language_dashboard'].lower()!='false':
  raise SystemExit('缺少“无法判断→前途出国（隔离）”映射')
 run=f'run_dashboard_{dt.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}'
 out=ROOT/'runtime'/run
 out.mkdir(parents=True)
 h=out/'headers.sql'; h.write_text('SELECT * FROM landing.br_cash__sheet_39b8dee2e4b3 WHERE source_row_number=1 LIMIT 1;'); hp=query(x.warehouse,run+'_cash_headers',out,h,[]); mapping={str(v).strip():c for c,v in zip(hp['columns'],hp['result']['rows'][0]) if v not in (None,'')}
 oh=out/'order_headers.sql'; oh.write_text('SELECT * FROM landing.br_work_orders__sheet_1f0596db9f25 WHERE source_row_number=1 LIMIT 1;'); op=query(x.warehouse,run+'_order_headers',out,oh,[]); order_mapping={str(v).strip():c for c,v in zip(op['columns'],op['result']['rows'][0]) if v not in (None,'')}
 missing=[n for n in ['业务日期','财年','渠道属性','报入现金收入'] if n not in mapping]+[n for n in ['ID','分配时间','团队','年级属性'] if n not in order_mapping]
 if missing: raise SystemExit('缺少必要表头: '+', '.join(missing))
 compiled=(ROOT/'sql/actuals_by_quarter.sql').read_text();
 for n,p in mapping.items(): compiled=compiled.replace('{{'+n+'}}',p)
 for n,p in order_mapping.items(): compiled=compiled.replace('{{工单表_'+n+'}}',p)
 cs=out/'compiled.sql'; cs.write_text(compiled); payload=query(x.warehouse,run,out,cs,[start.isoformat(),end.isoformat()]); result={'run_id':run,'quarter':x.quarter,'start':str(start),'end':str(end),'query':payload}; (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)); (ROOT/'runtime/latest.json').write_text(json.dumps({'run_id':run,'quarter':x.quarter,'result':payload.get('result',{})},ensure_ascii=False,indent=2)); print(json.dumps({'run_id':run,'output':str(out)},ensure_ascii=False))
if __name__=='__main__': main()
