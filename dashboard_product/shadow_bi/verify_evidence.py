"""Verify saved P1 observations; never generate UI/command success claims."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parents[2];A=ROOT/'.local/audits/shadow-bi-p1-20261022';E=A/'evidence';checks={}
def check(name,condition):
 checks[name]=bool(condition)
 if not condition:raise AssertionError(name)
try:
 before=json.loads((E/'p0-before.json').read_text());p0=ROOT/'.local/audits/shadow-bi-p0-20261022'
 check('P0 sealed bytes unchanged',all((p0/n).is_file() and hashlib.sha256((p0/n).read_bytes()).hexdigest()==h for n,h in before.items()))
 requests=[json.loads(x) for x in (E/'chart-requests-captured.jsonl').read_text().splitlines()]
 chart=[x for x in requests if x['path']=='/api/v1/chart/data' and x.get('response') and x['status']==200]
 def native(x,cid):return x['request'].get('form_data',{}).get('slice_id')==cid
 check('native activity page 2 LIMIT10 OFFSET10 returns10',any(native(x,2) and x['request']['queries'][0].get('row_offset')==10 and x['request']['queries'][0].get('row_limit')==10 and x['response']['result'][0]['rowcount']==10 and 'OFFSET 10' in x['response']['result'][0]['query'] for x in chart))
 check('native school grade drill scoped to school',any(native(x,0) and x['request']['queries'][0]['columns']==['年级'] and any(f['col']=='学校' and f['val']=='天津大学' for f in x['request']['queries'][0]['filters']) for x in chart))
 samples=[x for x in requests if x['path']=='/datasource/samples']
 check('native detail server LIMIT50 OFFSET50',any(x['args'].get('page')=='2' and x['response']['result']['rowcount']==50 and 'LIMIT 50 OFFSET 50' in x['response']['result']['query'] for x in samples))
 for col,allowed in [('团队',{3}),('期间',{1,3}),('个人月份',{4}),('月模式',{4}),('含删除回收',{4}),('含死单',{4})]:
  relevant=[x for x in chart if x['request'].get('form_data',{}).get('slice_id') in range(1,9) and any(f.get('col')==col for q in x['request']['queries'] for f in q.get('filters',[]))]
  check('native scope '+col,bool(relevant) and all(x['request']['form_data']['slice_id'] in allowed for x in relevant))
 config=json.loads((E/'native-final-config.json').read_text());check('global cross filtering disabled',config['cross_filters_enabled'] is False)
 check('two distinct native status filters',{'NATIVE_FILTER-deleted','NATIVE_FILTER-dead'}.issubset({x['id'] for x in config['native_filter_configuration']}))
 for name in ['p1-activity-input.txt','p1-activity-search.txt']:
  text=(E/name).read_text();check(name+' actual input and ratio','1000' in text and '11.88×' in text)
 check('school NULL appears on final page','N/A' in (E/'p1-school-null-last.txt').read_text())
 summary=json.loads((E/'api-final/api-summary.json').read_text());check('23 API requests passed',summary['assertions']=='passed' and len(summary['checks'])==23)
 check('distinct total not sum of children',summary['distinct_heads']==6445 and summary['sum_school_grade_heads']==6485)
 check('readonly boundary tested',json.loads((E/'connector-boundary.json').read_text())['nonbusiness_synthetic_file_read_possible'])
 result={'status':'passed','checks':checks,'request_records':len(requests),'sealed_P0_files':len(before)}
except Exception as e:
 result={'status':'failed','checks':checks,'error':str(e)}
 (E/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));raise
(E/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
