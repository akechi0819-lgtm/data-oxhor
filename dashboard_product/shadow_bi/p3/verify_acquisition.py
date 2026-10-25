"""实际API验证主被动六指标、默认基线、留学不变及目标隔离。"""
from dashboard_product.shadow_bi.p3.verify_api import Client,f
from dashboard_product.shadow_bi.p3.catalog import VIEWS

def main():
 c=Client();checks=[]
 try:
  values={}
  for scope in ('被动','主动','全部'):
   data=c.query('overview_lines',filters=[f('期间','FY27'),f('管理单元','市场总计'),f('语培统计范围',scope)],name='scope_'+scope)['data']
   values[scope]={(r['业务线'],r['指标']):r for r in data}
  for scope,heads,prior in [('被动',1236,1483),('主动',1117,1364),('全部',2351,2846)]:
   row=values[scope][('语培','人头')]
   assert (row['当期'],row['同期'])==(heads,prior),(scope,row)
   assert abs(row['同比']-(heads/prior-1))<1e-10
  for kind in ('工单','现金（元）'):
   a,p,total=[values[s][('语培',kind)] for s in ('主动','被动','全部')]
   for field in ('当期','同期'):
    assert abs(a[field]+p[field]-total[field])<0.001,(kind,field,a,p,total)
   assert abs(total['同比']-(total['当期']/total['同期']-1))<1e-10
  assert values['被动'][('语培','工单')]['当期']==8639
  assert values['被动'][('语培','工单')]['同期']==9465
  assert abs(values['被动'][('语培','现金（元）')]['当期']-17858997.4)<.001
  for key,row in values['被动'].items():
   if key[0]=='留学及小语种':
    for scope in ('主动','全部'):
     assert {k:v for k,v in row.items() if k!='语培统计范围'}=={k:v for k,v in values[scope][key].items() if k!='语培统计范围'}
  checks.append({'key':'core_values_heads_union_abroad_unchanged','status':'passed','values':values_to_json(values)})
  for v in VIEWS:
   if '语培统计范围' not in v.filters:continue
   for scope in ('主动','全部'):
    filters=[f(k,scope if k=='语培统计范围' else val) for k,val in v.filters.items()]
    data=c.query(v.key,filters=filters,name=v.key+'_'+scope)['data']
    for row in data:
     if row.get('业务线')!='留学及小语种':
      for field in ('目标','完成率','目标差额','时间进度差额'):
       if field in row:assert row[field] is None,(v.key,scope,field,row)
    checks.append({'key':v.key+'_'+scope,'status':'passed','rows':len(data)})
 finally:c.save(checks)
 print('PASS',len(checks),flush=True)

def values_to_json(values):
 return {s:[{'业务线':k[0],'指标':k[1],**r} for k,r in rows.items()] for s,rows in values.items()}
if __name__=='__main__':main()
