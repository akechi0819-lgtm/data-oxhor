"""Exercise running Superset API; compare to sealed JSON, not canned receipts."""
from pathlib import Path
import json,requests,time
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];A=ROOT/'.local/audits/shadow-bi-p1-20261022';E=A/'evidence'
B=json.loads((E/'bootstrap.json').read_text());E=E/'api-runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');E.mkdir(parents=True,exist_ok=False);D=B['datasets'];S=requests.Session();base='http://127.0.0.1:18088'
c=json.loads((A/'runtime/credentials.json').read_text());res=S.post(base+'/api/v1/security/login',json={**{k:c[k] for k in ['username','password']},'provider':'db','refresh':True});res.raise_for_status();S.headers['Authorization']='Bearer '+res.json()['access_token'];S.headers['X-CSRFToken']=S.get(base+'/api/v1/security/csrf_token/').json()['result']
results=[]
def query(name,table,columns,filters=(),metrics=None,order=None,limit=10,offset=0,**extra):
 q={'columns':columns,'metrics':metrics or [],'filters':list(filters),'orderby':order or [],'row_limit':limit,'row_offset':offset,'time_range':'No filter',**extra};payload={'datasource':{'id':D[table],'type':'table'},'queries':[q],'force':True,'result_format':'json','result_type':'full'}
 t=time.monotonic();r=S.post(base+'/api/v1/chart/data',json=payload);j=r.json();(E/(name+'.json')).write_text(json.dumps({'status':r.status_code,'request':payload,'response':j},ensure_ascii=False,indent=2));r.raise_for_status();v=j['result'][0];assert not v.get('error'),v;results.append({'name':name,'status':r.status_code,'rows':v['rowcount'],'seconds':round(time.monotonic()-t,3)});return v

def f(col,val,op='=='):return {'col':col,'op':op,'val':val}
# Minimal native data and typed amount/date.
v=query('api-01-top','top',['期间','日期','语培工单','语培现金'],[f('期间','FY27')]);assert v['data'][0]['语培工单']==8639;assert v['data'][0]['语培现金']==17858997.4
p1=query('api-02-page1','activities',['活动','现金'],order=[['活动',True]])
p2=query('api-03-page2','activities',['活动','现金'],order=[['活动',True]],offset=10)
assert len(p1['data'])==len(p2['data'])==10
assert not ({x['活动'] for x in p1['data']}&{x['活动'] for x in p2['data']});assert 'LIMIT 10' in p1['query'].upper() and 'OFFSET 10' in p2['query'].upper()
v=query('api-04-substring-search','activities',['活动','现金'],[f('活动','%10月份低龄%','ILIKE')]);assert v['data'][0]['现金']==11883.3
count=query('api-05-count','activities',['活动','现金'],is_rowcount=True,limit=10000);assert count['data'][0]['rowcount']==5049
cols=['业务组','工单','分子','固定分母','占比']
a=query('api-06-team-all','targets',cols,[f('期间','FY27'),f('团队','all')]);b=query('api-07-team-online','targets',cols,[f('期间','FY27'),f('团队','online')]);a={x['业务组']:x for x in a['data']};b={x['业务组']:x for x in b['data']}
assert a['大学']['固定分母']==b['大学']['固定分母'] and a['大学']['分子']!=b['大学']['分子']
variants=[]
for month,mode,status in [('2026-10','performance','01'),('2026-10','calendar','01'),('2026-10','performance','00'),('2026-09','performance','01')]:
 v=query('api-08-personal-'+month+'-'+mode+'-'+status,'personal',['个人月份','月模式','状态组合','人员','工单','现金','人数','目标','窗口开始','窗口结束'],[f('人员','刘彬'),f('个人月份',month),f('月模式',mode),f('状态组合',status)]);variants.append(v['data'][0])
assert variants[0]['窗口开始']!=variants[1]['窗口开始'];assert variants[0]['工单']!=variants[2]['工单'];assert all(variants[0][k]==variants[2][k] for k in ['现金','人数','目标'])
metric={'expressionType':'SQL','sqlExpression':'COUNT(DISTINCT "学员ID")','label':'独立人数','hasCustomLabel':True,'optionName':'heads'}
filters=[f('业务线','training'),f('指标','cash')]
by_school=query('api-09-school','facts',['学校'],filters,[metric],order=[['学校',True]],limit=10000)
by_grade=query('api-10-school-grade','facts',['学校','年级'],filters,[metric],order=[['学校',True],['年级',True]],limit=10000)
all_heads=query('api-11-distinct-total','facts',[],filters,[metric])
raw=json.loads((A/'p1_facts.json').read_text());expected=len({x['学员ID'] for x in raw if x['业务线']=='training' and x['指标']=='cash' and x['学员ID'] is not None});assert all_heads['data'][0]['独立人数']==expected
assert sum(x['独立人数'] for x in by_grade['data'])>expected
for asc in [True,False]:
 v=query('api-12-null-sort-'+str(asc),'facts',['学校'],filters,[metric],order=[['学校',asc]],limit=10000);assert v['data'][-1]['学校'] is None
school=next(x['学校'] for x in by_school['data'] if x['学校'])
v=query('api-13-drill-school','facts',['事实ID','日期','金额或数量','学校','年级'],[*filters,f('学校',school)],order=[['事实ID',True]]);assert all(x['学校']==school for x in v['data']);assert len(v['data'])<=10
metrics=[]
for label in ['工单数','签约量','转化率','渠道／校代现金','TMK现金','活动现金']:metrics.append({'expressionType':'SQL','sqlExpression':f'MAX(CASE WHEN "维度" = \'{label}\' THEN "比例" END)','label':label,'hasCustomLabel':True,'optionName':label})
v=query('api-14-radar','radar',['系列'],metrics=metrics);assert len(v['data'])==2 and len(v['data'][0])==7
# Date predicates are executed in DuckDB by Superset.
v=query('api-15-date-amount','facts',['日期'],[f('业务线','training'),f('指标','cash'),f('日期','2026-10-01','>=')],[{'expressionType':'SQL','sqlExpression':'SUM("金额或数量")','label':'金额','hasCustomLabel':True,'optionName':'cash'}],order=[['日期',True]],limit=30)
assert v['rowcount']>0
# Two independent native-control predicates on a virtual dataset, all four combinations.
state_rows=[]
for deleted,dead in [('0','0'),('0','1'),('1','0'),('1','1')]:
 v=query('api-16-two-controls-'+deleted+dead,'personal',['状态组合','工单','现金','人数','目标'],[f('人员','刘彬'),f('个人月份','2026-07'),f('月模式','performance'),f('含删除回收',deleted),f('含死单',dead)])
 row=v['data'][0];assert row['状态组合']==deleted+dead;state_rows.append(row)
frozen=json.loads((ROOT/'.local/audits/shadow-bi-p0-20261022/workspace/Output/DashboardManagement/run_shadow_p0_20261022/shared_result.json').read_text())
frozen_person=next(x for p in frozen['periods'] if p['id']=='2026-07' for t in p['teams'] if t['id']=='total' for x in t['people'] if x['name']=='刘彬')
assert all(x['工单']==frozen_person['order_status_views'][x['状态组合']]['training_actual'] for x in state_rows)
assert state_rows[0]['工单']!=state_rows[1]['工单'] and state_rows[0]['工单']!=state_rows[2]['工单']
assert all(all(x[k]==state_rows[0][k] for k in ['现金','人数','目标']) for x in state_rows)
(E/'api-summary.json').write_text(json.dumps({'checks':results,'assertions':'passed','distinct_heads':expected,'sum_school_grade_heads':sum(x['独立人数'] for x in by_grade['data']),'personal_variants':variants,'two_control_variants':state_rows},ensure_ascii=False,indent=2));print('PASS',len(results),'real API requests; distinct',expected)
