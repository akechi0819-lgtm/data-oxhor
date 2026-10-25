"""Create representative native Superset datasets/charts/dashboard in P1 metadata."""
import json
from pathlib import Path
from superset.app import create_app
ROOT=Path(__file__).resolve().parents[2]; A=ROOT/'.local/audits/shadow-bi-p1-20261022'

def main():
 app=create_app()
 with app.app_context():
  from superset import db,security_manager
  from superset.models.core import Database
  from superset.connectors.sqla.models import SqlaTable,SqlMetric
  from superset.models.slice import Slice
  from superset.models.dashboard import Dashboard
  if db.session.query(Dashboard).filter_by(slug='shadow-bi-p1').first():raise RuntimeError('P1 metadata already exists; do not overwrite evidence')
  c=json.loads((A/'runtime/credentials.json').read_text())
  user=security_manager.find_user(username=c['username'])
  if not user:user=security_manager.add_user(c['username'],'P1','Local','p1@localhost.invalid',security_manager.find_role('Admin'),password=c['password'])
  database=Database(database_name='P1 sealed JSON projection',sqlalchemy_uri='duckdb:///'+str(A/'runtime/projection.duckdb'),extra=json.dumps({'engine_params':{'connect_args':{'read_only':True}}}),allow_dml=False,expose_in_sqllab=False)
  db.session.add(database);db.session.flush()
  datasets={}
  for name in ['facts','activities','top','targets','personal','radar']:
   ds=SqlaTable(table_name='p1_'+name,database=database,schema='main',owners=[user]);db.session.add(ds);db.session.flush();
   if name=='personal':ds.sql='SELECT *, left("状态组合",1) AS "含删除回收", right("状态组合",1) AS "含死单" FROM main.p1_personal'
   ds.fetch_metadata();datasets[name]=ds
  db.session.commit()
  charts=[]
  def chart(title,name,columns,filters=(),metrics=None,groupby=None,viz='table',server=True,more=None):
   ds=datasets[name]; cid=len(charts)+1
   f={'datasource':f'{ds.id}__table','viz_type':viz,'query_mode':'aggregate' if metrics else 'raw','all_columns':columns,'groupby':groupby or [],'metrics':metrics or [],'adhoc_filters':list(filters),'row_limit':10000,'server_pagination':server,'server_page_length':10,'page_length':10,'include_search':True,'order_by_cols':[json.dumps([columns[0],True])] if columns else [],'time_range':'No filter','table_timestamp_format':'%Y-%m-%d','color_scheme':'supersetColors','show_legend':True,'legendType':'plain','legendOrientation':'bottom','column_config':{}}
   if more:f.update(more)
   sl=Slice(slice_name=title,datasource_id=ds.id,datasource_type='table',viz_type=viz,params=json.dumps(f,ensure_ascii=False),owners=[user])
   db.session.add(sl);db.session.flush();f['slice_id']=sl.id;sl.params=json.dumps(f,ensure_ascii=False);charts.append(sl);return sl
  def filt(col,val):return {'expressionType':'SIMPLE','subject':col,'operator':'IN','comparator':[val],'clause':'WHERE','sqlExpression':None,'filterOptionName':col+str(val)}
  chart('01 最小语培工单现金','top',['期间','日期','语培工单','语培现金'],[filt('期间','FY27')])
  chart('02 活动原生服务端分页（输入见附加组件）','activities',['活动','工单','现金','人数','状态'])
  target=chart('03 团队目标与固定分母','targets',['期间','团队','业务组','工单','现金','目标','分子','固定分母','占比'],[filt('期间','FY27')])
  personal=chart('04 独立个人月份绩效月状态','personal',['个人月份','月模式','状态组合','人员','工单','现金','人数','目标','窗口开始','窗口结束'],[filt('人员','刘彬')])
  # SQL aggregation on facts: distinct people, never summing grouped counts.
  school=chart('05 学校层级与独立人数','facts',[],[filt('业务线','training'),filt('指标','cash')],metrics=[{'expressionType':'SQL','sqlExpression':'COUNT(DISTINCT "学员ID")','label':'独立人数','hasCustomLabel':True,'optionName':'distinct_heads'}],groupby=['学校'],more={'order_by_cols':[]})
  # Native radar axes are metrics; use six conditional metrics, normalized per sealed P0 scale.
  radar_metrics=[]
  for label in ['工单数','签约量','转化率','渠道／校代现金','TMK现金','活动现金']:
   radar_metrics.append({'expressionType':'SQL','sqlExpression':f'MAX(CASE WHEN "维度" = \'{label}\' THEN "比例" END)','label':label,'hasCustomLabel':True,'optionName':label})
  chart('06 年度六维（同P0各轴比例）','radar',[],metrics=radar_metrics,groupby=['系列'],viz='radar',server=False,more={'radarMetricMaxValue':1,'radarMetricMinValue':0,'show_labels':True,'number_format':'.2f'})
  chart('07 六维原值与同组均值','radar',['维度','系列','原值','比例','上限','年度','截止日期'])
  chart('08 必需字段明细','facts',['事实ID','指标','日期','金额或数量','学校','年级'],[filt('业务线','training')])
  dashboard=Dashboard(dashboard_title='P1 影子BI技术验证 · 冻结批次',slug='shadow-bi-p1',published=True,owners=[user]);dashboard.slices=charts;db.session.add(dashboard);db.session.flush()
  pos={'DASHBOARD_VERSION_KEY':'v2','ROOT_ID':{'id':'ROOT_ID','type':'ROOT','children':['GRID_ID']},'GRID_ID':{'id':'GRID_ID','type':'GRID','children':[],'parents':['ROOT_ID']},'HEADER_ID':{'id':'HEADER_ID','type':'HEADER','meta':{'text':dashboard.dashboard_title}}}
  for i,sl in enumerate(charts):
   row=f'ROW-{i}';key=f'CHART-{sl.id}';pos['GRID_ID']['children'].append(row);pos[row]={'id':row,'type':'ROW','children':[key],'parents':['ROOT_ID','GRID_ID'],'meta':{'background':'BACKGROUND_TRANSPARENT'}};pos[key]={'id':key,'type':'CHART','children':[],'parents':['ROOT_ID','GRID_ID',row],'meta':{'chartId':sl.id,'width':12,'height':70 if sl.viz_type=='radar' else 50,'sliceName':sl.slice_name}}
  dashboard.position_json=json.dumps(pos)
  configs=[]
  for fid,name,col,ds,scope,default in [('team','目标团队','团队','targets',[target.id],'all'),('month','个人月份','个人月份','personal',[personal.id],'2026-10'),('mode','月模式','月模式','personal',[personal.id],'performance'),('deleted','含删除回收','含删除回收','personal',[personal.id],'0'),('dead','含死单','含死单','personal',[personal.id],'1')]:
   fid='NATIVE_FILTER-'+fid
   configs.append({'id':fid,'name':name,'filterType':'filter_select','targets':[{'datasetId':datasets[ds].id,'column':{'name':col}}],'defaultDataMask':{'extraFormData':{'filters':[{'col':col,'op':'IN','val':[default]}]},'filterState':{'value':[default]}},'cascadeParentIds':[],'scope':{'rootPath':['ROOT_ID'],'excluded':[sl.id for sl in charts if sl.id not in scope]},'controlValues':{'enableEmptyFilter':False,'multiSelect':False,'searchAllOptions':False,'inverseSelection':False},'type':'NATIVE_FILTER','description':'P1范围限定代表样例','chartsInScope':scope,'tabsInScope':[]})
  for sl in [charts[0],charts[2]]:
   f=json.loads(sl.params);f['adhoc_filters']=[];sl.params=json.dumps(f,ensure_ascii=False)
  configs.insert(0,{'id':'NATIVE_FILTER-period','name':'部门期间','filterType':'filter_select','targets':[{'datasetId':datasets['top'].id,'column':{'name':'期间'}}],'defaultDataMask':{'extraFormData':{'filters':[{'col':'期间','op':'IN','val':['FY27']}]},'filterState':{'value':['FY27']}},'cascadeParentIds':[],'scope':{'rootPath':['ROOT_ID'],'excluded':[sl.id for sl in charts if sl.id not in [charts[0].id,charts[2].id]]},'controlValues':{'enableEmptyFilter':False,'multiSelect':False},'type':'NATIVE_FILTER','chartsInScope':[charts[0].id,charts[2].id],'tabsInScope':[]})
  dashboard.json_metadata=json.dumps({'native_filter_configuration':configs,'color_scheme':'supersetColors','cross_filters_enabled':False})
  db.session.commit()
  receipt={'database':database.id,'datasets':{k:v.id for k,v in datasets.items()},'charts':{sl.slice_name:sl.id for sl in charts},'dashboard':dashboard.id,'url':'http://127.0.0.1:18088/superset/dashboard/shadow-bi-p1/'}
  (A/'evidence/bootstrap.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':main()
