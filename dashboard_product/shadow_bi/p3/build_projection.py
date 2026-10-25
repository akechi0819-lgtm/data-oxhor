"""P3 presentation copy: preserve all P2 relations, project omitted annual-card scalars.

Existing build_radar is reused unchanged on controlled P2 facts. No new business rule.
"""
import json,shutil,hashlib
from datetime import datetime,UTC
import duckdb
from data_platform.business_library import execute_library_query,read_library_result,load_library
from dashboard_product.management.capacity_radar import build_radar
from dashboard_product.shadow_bi.library import write_table
from dashboard_product.shadow_bi.p3.catalog import ROOT,AUDIT,SOURCE_LIBRARY as LIBRARY,SOURCE_BATCH as BATCH,LIBRARY as OUTPUT_LIBRARY,BATCH as OUTPUT_BATCH
from data_platform.query.evidence import file_ref

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 source,source_db,source_ref=load_library(LIBRARY,BATCH)
 out=OUTPUT_LIBRARY
 if out.exists():raise ValueError('拒绝覆盖P3投影库')
 receipts=[];facts=[]
 for offset in range(0,source['tables']['personnel_facts']['rows'],5000):
  r=execute_library_query(library=LIBRARY,batch_id=BATCH,sql=f'SELECT row_json FROM queries.personnel_facts ORDER BY fact_id LIMIT 5000 OFFSET {offset}',run_id=f'run_p3_annual_facts_{offset:05}',output_root=AUDIT/'evidence',max_rows=5000,max_result_bytes=20000000)
  data=read_library_result(r,output_root=AUDIT/'evidence');facts.extend(json.loads(row[0]) for row in data['rows']);receipts.append(r)
 paths=['workspace_modeling/operations/people.json','dashboard_product/config/offline_market_people.json','dashboard_product/config/capacity_targets.json']
 def bound(p):
  if sha(ROOT/p)!=source['binding']['rules'][p]:raise ValueError('P2已绑定规则变化：'+p)
  return json.loads((ROOT/p).read_text())
 through=source['coverage']['data_through']
 people=build_radar(facts,bound(paths[0]),bound(paths[1]),through,bound(paths[2]))
 out.mkdir();shutil.copyfile(source_db,out/'business.duckdb')
 with duckdb.connect(str(out/'business.duckdb')) as con:
  table=write_table(con,out,'radar_people',people)
  con.execute("UPDATE queries.batch SET batch_id=?",[OUTPUT_BATCH])
 manifest={**source,'batch_id':OUTPUT_BATCH,'created_at':datetime.now(UTC).isoformat(),'tables':{**source['tables'],'radar_people':table},'database':file_ref(out/'business.duckdb',out,'application/vnd.duckdb'),'presentation_source':{'batch_id':BATCH,'library_manifest':source_ref,'database':source['database'],'unchanged_base_relations':list(source['tables']),'controlled_reads':receipts,'function':'dashboard_product.management.capacity_radar.build_radar','projection_code':file_ref(__import__('pathlib').Path(__file__),ROOT,'text/x-python')}}
 (out/'library_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 print(json.dumps({'base_relations':len(source['tables']),'radar_people':len(people),'controlled_reads':len(receipts),'batch_id':manifest['batch_id']},ensure_ascii=False))
if __name__=='__main__':main()
