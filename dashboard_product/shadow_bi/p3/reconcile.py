"""Compare all existing finite periods/month modes/statuses to frozen P0 values.

SQL is executed only through Data Platform. Expected values are read from P0,
never used by BI datasets. Numeric comparison tolerates binary float noise only.
"""
import json,math
from datetime import datetime,UTC
from data_platform.business_library import execute_library_query,read_library_result
from dashboard_product.shadow_bi.p3.catalog import ROOT,AUDIT,LIBRARY,BATCH,VIEWS,WIDE_NUM
from dashboard_product.shadow_bi.p3.check_sql import render
P0=ROOT/'.local/audits/shadow-bi-p0-20261022/workspace/Output/DashboardManagement/run_shadow_p0_20261022'
LINE={'training':'语培','abroad':'留学及小语种'};UNITS={'total':'市场总计','virtual':'线上虚拟人','online':'线上团队'};METRICS={'orders':'工单','cash':'现金（元）','heads':'人头'}

def get(obj,path):
 for k in path.split('.'):
  if not isinstance(obj,dict):return None
  obj=obj.get(k)
 return obj
class Check:
 def __init__(self):
  self.out=AUDIT/'evidence'/('reconcile-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%S'));self.out.mkdir();self.results=[];self.seq=0
 def query(self,key,cols,where='',mask=7,aggregate=False):
  v=next(v for v in VIEWS if v.key==key);self.seq+=1
  source='SELECT * FROM ('+render(v.sql,mask)+') v'+(' WHERE '+where if where else '')
  if aggregate:
   dims=[x for x in cols if x in v.more['groupby']]
   sql='SELECT '+', '.join('"'+x+'"' for x in dims)+', '+', '.join(m['sqlExpression']+' AS "'+m['label']+'"' for m in v.more['metrics'])+' FROM ('+source+') src GROUP BY '+', '.join('"'+x+'"' for x in dims)
   sql='SELECT '+', '.join('"'+x+'"' for x in cols)+' FROM ('+sql+') grouped'
  else:sql='SELECT '+', '.join('"'+x+'"' for x in cols)+' FROM ('+source+') projected'
  r=execute_library_query(library=LIBRARY,batch_id=BATCH,sql=sql,run_id=f'run_p3_finite_{self.seq:03}',output_root=self.out,max_rows=100000,max_result_bytes=30000000)
  d=read_library_result(r,output_root=self.out);return [dict(zip(d['columns'],row)) for row in d['rows']]
 def compare(self,name,actual,expected,keys):
  def sortkey(row):return tuple(str(row.get(k)) for k in keys)
  a=sorted(actual,key=sortkey);b=sorted(expected,key=sortkey);errors=[]
  if len(a)!=len(b):errors.append({'actual_rows':len(a),'expected_rows':len(b)})
  if len(a)==len(b):
   for x,y in zip(a,b):
    for k,value in y.items():
     other=x.get(k)
     if isinstance(value,(int,float)) and not isinstance(value,bool) and other is not None:
      ok=math.isclose(float(value),float(other),rel_tol=1e-12,abs_tol=1e-8)
     else:ok=value==other
     if not ok:
      errors.append({'key':sortkey(y),'column':k,'actual':other,'expected':value})
      if len(errors)>=8:break
    if len(errors)>=8:break
  self.results.append({'name':name,'status':'failed' if errors else 'passed','rows':len(a),'errors':errors});print(name,self.results[-1]['status'],len(a),flush=True)
 def save(self):
  (self.out/'summary.json').write_text(json.dumps({'checks':self.results,'controlled_queries':self.seq},ensure_ascii=False,indent=2));print(self.out,flush=True)

def main():
 c=Check();public=json.loads((P0/'shared_result.json').read_text());online=json.loads((P0/'online_shared_result.json').read_text())
 cols=['期间','管理单元','业务线','指标','当期','同期','同比','目标','完成率','目标差额','时间进度差额']
 fields={'当期':'actual','同期':'prior','同比':'yoy','目标':'target','完成率':'completion','目标差额':'gap','时间进度差额':'time_gap'}
 def lines_expected(periods,units,prep=False):
  out=[]
  for p in periods:
   for t in p['teams']:
    if t['id'] not in units:continue
    for l,obj in t['lines'].items():
     if prep and l!='training':continue
     for key,label in METRICS.items():out.append({'期间':p['id'],'管理单元':UNITS.get(t['id'],t['id']),'业务线':LINE[l],'指标':label,**{n:obj[key].get(k) for n,k in fields.items()}})
  return out
 c.compare('市场三管理单元×17期间全部指标',c.query('overview_lines',cols),lines_expected(public['periods'],UNITS),cols[:4])
 # All existing top-order identities, including the separate virtual total.
 mc=['期间','管理单元','指标']+list(fields);expected=[]
 for p in public['periods']:
  for t in p['teams']:
   if t['id'] not in UNITS:continue
   metric=t.get('market_orders') or t.get('combined_orders') or {}
   expected.append({'期间':p['id'],'管理单元':UNITS[t['id']],'指标':'团队合并工单' if t['id']=='virtual' else '语培总盘逐ID工单',**{n:metric.get(k) for n,k in fields.items()}})
 c.compare('全部期间市场逐ID及虚拟合并工单',c.query('overview_market',mc),expected,mc[:3])
 vc=['期间','指标']+list(fields);expected=[]
 for p in public['periods']:
  t=next(t for t in p['teams'] if t['id']=='virtual');expected.append({'期间':p['id'],'指标':'团队合并工单',**{n:t['combined_orders'].get(k) for n,k in fields.items()}})
 c.compare('虚拟人独立页全部期间合并工单',c.query('virtual_market',vc),expected,vc[:2])
 c.compare('大学独立页全部期间经营指标',c.query('university_lines',cols),lines_expected(public['periods'],{'university'}),cols[:4])
 # Complete personal grid, using fixed base cash/heads/targets and state-specific orders.
 pc=['个人月份','管理单元','月模式','含删除回收','含死单','人员','语培工单','留学工单','合计工单','现金','人头','语培目标','留学目标','现金目标','窗口开始','窗口结束']
 def personal_expected(periods,units,withunit=True):
  out=[]
  for p in periods:
   for t in p['teams']:
    if t['id'] not in units:continue
    for mode,container in [('绩效月',t),('自然月',t.get('person_calendar',{}))]:
     for person in container.get('people',[]):
      for state,v in person.get('order_status_views',{}).items():
       row={'个人月份':p['id'],'月模式':mode,'含删除回收':'包含' if state[0]=='1' else '不含','含死单':'包含' if state[1]=='1' else '不含','人员':person['name'],'语培工单':v.get('training_actual'),'留学工单':v.get('abroad_actual'),'合计工单':v.get('combined_actual'),'现金':get(person,'cash_actual.actual'),'人头':get(person,'heads_actual.actual'),'语培目标':person.get('training_target'),'留学目标':person.get('abroad_target'),'现金目标':get(person,'cash_actual.target'),'窗口开始':container.get('person_start'),'窗口结束':container.get('person_through')}
       if withunit:row['管理单元']=UNITS[t['id']]
       out.append(row)
  return out
 c.compare('三管理单元×全部个人月份×双月模式×四状态',c.query('overview_people',pc),personal_expected(public['periods'],UNITS),pc[:6])
 uc=[x for x in pc if x!='管理单元']
 c.compare('大学全部个人月份×双月模式×四状态',c.query('university_people',uc),personal_expected(public['periods'],{'university'},False),uc[:5])
 for mask in range(1,8):
  p=json.loads((P0/f'site/prep_high.{mask}.data.json').read_text())
  expected=lines_expected(p['periods'],{'prep_high'},True)
  c.compare(f'青少初高中组合{mask}×全部期间',c.query('prep_lines',cols,mask=mask),expected,cols[:4])
  cp=[x for x in pc if x!='管理单元']
  c.compare(f'组合{mask}×全部个人月份×双月模式×四状态',c.query('prep_people',cp,mask=mask),personal_expected(p['periods'],{'prep_high'},False),cp[:5])
 c.compare('业务组空选不展示部门完成',c.query('prep_lines',cols,mask=0),[],cols[:4])
 # Target team scope preserves fixed cash denominator across all periods.
 tc=['期间','目标团队','业务组名称','指标','当期','同期','目标','完成率','被动现金分子','新生现金固定分母','被动现金占比'];expected=[]
 for p in public['periods']:
  t=next(t for t in p['teams'] if t['id']=='total')
  for scope,obj in t['team_scope_views'].items():
   for g in obj['business_groups']:
    for metric,label in METRICS.items():expected.append({'期间':p['id'],'目标团队':{'all':'全部','online':'线上','offline':'线下'}[scope],'业务组名称':g['name'],'指标':label,'当期':g[metric].get('actual'),'同期':g[metric].get('prior'),'目标':g[metric].get('target'),'完成率':g[metric].get('completion'),'被动现金分子':get(g,'passive_cash_share.numerator'),'新生现金固定分母':get(g,'passive_cash_share.denominator'),'被动现金占比':get(g,'passive_cash_share.ratio')})
 c.compare('全部期间×三目标团队及固定分母',c.query('overview_targets',tc,"管理单元='市场总计'"),expected,tc[:4])
 # Full monthly capacity statuses and product scopes.
 cc=['产能月份','人员','含删除回收','含死单','产品范围']+[l+u for l in ['自主创造','自创率','目标','本业务完成率','额外接收','本业务合计','额外输出','自创合计'] for u in ['工单','现金']];expected=[]
 for p in public['capacity']['periods']:
  for person in p['people']:
   for state,v in person['order_status_views'].items():
    for scope,key in [('合计',None),('留学','study_abroad'),('小语种','small_language')]:
     obj=v if key is None else v['breakdowns'][key]
     expected.append({'产能月份':p['id'],'人员':person['name'],'含删除回收':'包含' if state[0]=='1' else '不含','含死单':'包含' if state[1]=='1' else '不含','产品范围':scope,**{label+unit:get(obj,bucket+'.'+metric) for bucket,label in [('self','自主创造'),('self_rate','自创率'),('targets','目标'),('completion','本业务完成率'),('received','额外接收'),('own_total','本业务合计'),('output','额外输出'),('created_total','自创合计')] for metric,unit in [('orders','工单'),('cash','现金')]}})
 c.compare('产能全部月份×四状态×三产品范围',c.query('capacity_month',cc),expected,cc[:5])
 ac=['活动','语培工单','留学工单','合计工单','现金','人头','分域人数','现金状态']
 expected=[dict(zip(ac,[x.get(k) for k in ['name','training_orders','abroad_orders','orders','cash','heads','heads_display','cash_status']])) for x in public['activities']]
 c.compare('全部5049活动累计',c.query('activities',ac),expected,['活动'])
 # Every school parent is compared with independent P0 heads, including multi-grade schools.
 for page,unit in [('overview','total'),('virtual','virtual'),('university','university')]:
  sc=['业务线','学校']+list(WIDE_NUM);expected=[]
  t=next(t for p in public['periods'] if p['id']=='FY27' for t in p['teams'] if t['id']==unit)
  for l,schools in t['schools_by_line'].items():
   for s in schools:expected.append({'业务线':LINE[l],'学校':s['name'],**{n:get(s,k) for n,k in WIDE_NUM.items()}})
  where="期间='FY27'"+(" AND 管理单元='市场总计'" if page=='overview' else '')
  c.compare(page+'学校五指标与独立人头',c.query(page+'_schools',sc,where,aggregate=True),expected,['业务线','学校'])
 # Exact annual-card scalars and axes come from the reused rule, not rounded column projections.
 rc=['六维人员','年度工单','年度现金','年度人头','年度转化率','年度现金目标','现金时间进度完成率']
 expected=[dict(zip(rc,[p.get(k) for k in ['name','orders','cash','heads','conversion','cash_capacity','cash_progress_completion']])) for p in public['capacity']['radar']['people']]
 c.compare('年度六维完整人员标量',c.query('capacity_annual_targets',rc),expected,['六维人员'])
 oc=['线上期间','业务线','指标','当期','同期','同比','目标','完成率','目标差额','时间进度差额','花费','回收倍数','单条工单成本','同窗现金','同窗费用','同窗工单','费用窗口开始','费用窗口结束'];expected=[]
 for p in online['periods']:
  for l,v in p['lines'].items():
   for m,label in METRICS.items():expected.append({'线上期间':p['id'],'业务线':LINE[l],'指标':label,**{n:v[m].get(k) for n,k in fields.items()},**{n:get(v,'advertising.'+k) for n,k in [('花费','spend'),('回收倍数','roi'),('单条工单成本','cost_per_order'),('同窗现金','roi_cash'),('同窗费用','roi_spend'),('同窗工单','roi_orders'),('费用窗口开始','roi_start_date'),('费用窗口结束','roi_through_date')]}})
 c.compare('线上全部期间×业务线×费用同窗',c.query('online_summary',oc),expected,oc[:3])
 c.save()
 if any(x['status']=='failed' for x in c.results):raise SystemExit(1)
if __name__=='__main__':main()
