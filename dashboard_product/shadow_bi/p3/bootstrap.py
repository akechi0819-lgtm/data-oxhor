"""Build all P3 native dashboards against sealed P2, in P3-only metadata."""
import json,os
from superset.app import create_app
from dashboard_product.shadow_bi.p3.catalog import VIEWS,AUDIT,LIBRARY,PAGES,WIDE_NUM,BATCH

def fetch_schema(ds):
 # DuckDB能从空结果给出完整SQL类型。Superset默认LIMIT1会先展开学校大数组；
 # 外层WHERE FALSE只用于字段探测，完成后始终恢复真正业务SQL。
 original_sql=ds.sql
 try:
  ds.sql='SELECT * FROM ('+original_sql+') schema_probe WHERE FALSE'
  ds.fetch_metadata()
 finally:ds.sql=original_sql

def main():
 app=create_app()
 with app.app_context():
  from superset import db,security_manager
  from superset.models.core import Database
  from superset.connectors.sqla.models import SqlaTable
  from superset.models.slice import Slice
  from superset.models.dashboard import Dashboard
  creds=json.loads((AUDIT/'runtime/credentials.json').read_text());user=security_manager.find_user(username=creds['username'])
  database=db.session.query(Database).filter_by(database_name='市场经营 · 2026-10-22独立批次').first() or Database(database_name='市场经营 · 2026-10-22独立批次',sqlalchemy_uri='duckdb:///'+str(LIBRARY/'business.duckdb'),extra=json.dumps({'engine_params':{'connect_args':{'read_only':True,'config':{'enable_external_access':False,'lock_configuration':True}}}}),allow_dml=False,expose_in_sqllab=False)
  database.sqlalchemy_uri='duckdb:///'+str(LIBRARY/'business.duckdb')
  if os.environ.get('SHADOW_BI_DUCKDB_MEMORY'):
   connection_config={'enable_external_access':False,'lock_configuration':True,'memory_limit':os.environ['SHADOW_BI_DUCKDB_MEMORY'],'threads':1}
   if os.environ.get('SHADOW_BI_DUCKDB_TEMP'):
    connection_config.update(temp_directory=os.environ['SHADOW_BI_DUCKDB_TEMP'],max_temp_directory_size='2GB')
   database.extra=json.dumps({'engine_params':{'connect_args':{'read_only':True,'config':connection_config}}})
  db.session.add(database);db.session.flush()
  datasets={};charts={};pages={};receipt={'datasets':{},'charts':{},'pages':{},'batch':BATCH}
  for v in VIEWS:
   ds=db.session.query(SqlaTable).filter_by(table_name=PAGES.get(v.page,'市场活动')+' · '+v.title,database_id=database.id).first() or SqlaTable(table_name=PAGES.get(v.page,'市场活动')+' · '+v.title,database=database,schema='queries',owners=[user]);metadata_changed=ds.sql!=v.sql or not ds.columns;ds.sql=v.sql;db.session.add(ds);db.session.flush();
   if metadata_changed:fetch_schema(ds)
   if v.key.endswith('_schools'):
    for column in ds.columns:
     if column.column_name.startswith(('父','子')):
      column.groupby=False;column.filterable=False;column.verbose_name=('学校' if column.column_name.startswith('父') else '年级')+column.column_name[1:]
   datasets[v.key]=ds;print('dataset',v.key,flush=True)
   receipt['datasets'][v.key]=ds.id
   if v.page=='activities':continue
   p={'datasource':f'{ds.id}__table','viz_type':v.viz,'query_mode':'raw','all_columns':v.columns,'groupby':[],'metrics':[],'adhoc_filters':[],'row_limit':1000000,'server_pagination':True,'server_page_length':50,'page_length':50,'include_search':False,'order_by_cols':[],'time_range':'No filter','table_timestamp_format':'%Y-%m-%d','color_scheme':'supersetColors','show_legend':True,'legendType':'plain','legendOrientation':'bottom','column_config':{c:{'d3NumberFormat':'.1%'} for c in v.columns if ('同比' in c or '率' in c or '占比' in c or c=='时间进度') or c in ['同比','完成率','工单占比','现金占比','本人占比','被动现金占比','渠道内现金占比','语培完成率','留学完成率','现金完成率','合计完成率']},'allow_rearrange_columns':False}
   # Sort numeric metric values with NULLS LAST in DuckDB (both directions).
   sort=next((c for c in ['当期','工单','日期','人员'] if c in v.columns),v.columns[0]);p['order_by_cols']=[json.dumps([sort,False if sort!='人员' else True])]
   if v.more:p.update(v.more)
   if v.viz=='table':
    numeric={column.column_name for column in ds.columns if any(token in str(column.type).upper() for token in ['INT','DOUBLE','FLOAT','REAL','NUMERIC','DECIMAL'])}|set(WIDE_NUM)|{'回收倍数','单条工单成本','花费','同窗现金','同窗费用','同窗工单','本人','同组均值','轴上限','相对同组'}
    formatting={name:{'d3NumberFormat':',.2~f'} for name in v.columns if name in numeric}
    formatting.update({name:{'d3NumberFormat':'.1%'} for name in v.columns if '同比' in name or '率' in name or '占比' in name or name=='时间进度'})
    p['column_config']=formatting;p['show_cell_bars']=False
   if v.viz!='table':p.update(server_pagination=False,all_columns=[],order_by_cols=[])
   if v.viz.startswith('echarts_timeseries'):p.update(x_axis_time_format='%m-%d',y_axis_format=',.0f',time_grain_sqla='P1D')
   sl=db.session.query(Slice).filter_by(datasource_id=ds.id,datasource_type='table').first() or Slice(slice_name=v.title,datasource_id=ds.id,datasource_type='table',viz_type=v.viz,params=json.dumps(p,ensure_ascii=False),owners=[user]);sl.slice_name=v.title;sl.params=json.dumps(p,ensure_ascii=False);db.session.add(sl);db.session.flush();p['slice_id']=sl.id;sl.params=json.dumps(p,ensure_ascii=False);charts[v.key]=sl
   receipt['charts'][v.key]={'id':sl.id,'dataset':ds.id,'page':v.page,'section':v.section,'columns':v.columns,'filters':v.filters}
  # A tiny options relation drives the finite existing selection, never a new rule engine.
  opts=db.session.query(SqlaTable).filter_by(table_name='p3_group_options',database_id=database.id).first() or SqlaTable(table_name='p3_group_options',database=database,schema='queries',sql="SELECT unnest(['青少','初中','高中']) AS 业务组",owners=[user]);db.session.add(opts);db.session.flush();opts.fetch_metadata()
  option_sets={}
  for key,column,sql in [('acquisition_options','语培统计范围',"SELECT unnest(['被动','主动','全部']) AS 语培统计范围"),('school_options','学校',"SELECT DISTINCT COALESCE(name,'暂无归属') AS 学校 FROM queries.schools"),('person_options','人员',"SELECT DISTINCT name AS 人员 FROM queries.people"),('person_month_options','个人月份',"SELECT id AS 个人月份 FROM queries.periods WHERE regexp_matches(id,'^[0-9]{4}-[0-9]{2}$')")]:
   option=db.session.query(SqlaTable).filter_by(table_name='p3_'+key,database_id=database.id).first() or SqlaTable(table_name='p3_'+key,database=database,schema='queries',sql=sql,owners=[user]);db.session.add(option);db.session.flush()
   if not option.columns:option.fetch_metadata()
   option_sets[column]=option
  db.session.commit()
  for page,title in PAGES.items():
   specs=[v for v in VIEWS if v.page==page];slices=[charts[v.key] for v in specs]
   dashboard=db.session.query(Dashboard).filter_by(slug='shadow-bi-p3-'+page).first() or Dashboard(dashboard_title=title,slug='shadow-bi-p3-'+page,published=True,owners=[user]);dashboard.slices=slices;db.session.add(dashboard);db.session.flush();pages[page]=dashboard
   pos={'DASHBOARD_VERSION_KEY':'v2','ROOT_ID':{'id':'ROOT_ID','type':'ROOT','children':['GRID_ID']},'GRID_ID':{'id':'GRID_ID','type':'GRID','children':[],'parents':['ROOT_ID']},'HEADER_ID':{'id':'HEADER_ID','type':'HEADER','meta':{'text':title}}}
   # Native tabs keep repeated analysis compact and preserve independent scopes.
   tabroot='TABS-'+page;pos['GRID_ID']['children']=[tabroot];pos[tabroot]={'id':tabroot,'type':'TABS','children':[],'parents':['ROOT_ID','GRID_ID'],'meta':{}}
   sections=list(dict.fromkeys(v.section for v in specs))
   for si,section in enumerate(sections):
    tab=f'TAB-{page}-{si}';pos[tabroot]['children'].append(tab);pos[tab]={'id':tab,'type':'TAB','children':[],'parents':['ROOT_ID','GRID_ID',tabroot],'meta':{'text':section}}
    noteid=f'MARKDOWN-{page}-{si}';rowid=f'ROW-NOTE-{page}-{si}';pos[tab]['children'].append(rowid);parents=['ROOT_ID','GRID_ID',tabroot,tab]
    pos[rowid]={'id':rowid,'type':'ROW','children':[noteid],'parents':parents,'meta':{'background':'BACKGROUND_TRANSPARENT'}}
    links=' · '.join(f'[{n}](/superset/dashboard/shadow-bi-p3-{k}/)' for k,n in PAGES.items() if k!=page)
    text='[工作台](/p3/) · [市场活动](/p3/activity/)\n\n语培截至 **2026-10-21** · 留学截至 **2026-10-13**。费用按已提供窗口计算；语培工单、新生报名现金及经营人头按观远同窗核对；人头按学员＋班级报入金额绝对值≥1500元且报名人次为正后去重。语培统计范围默认被动，可切换主动或全部；留学保持原口径，跨线合计及人员产能不参与切换。\n\n'+links
    pos[noteid]={'id':noteid,'type':'MARKDOWN','children':[],'parents':parents+[rowid],'meta':{'code':text,'width':12,'height':15}}
    for v in [v for v in specs if v.section==section]:
     sl=charts[v.key];row='ROW-'+str(sl.id);cid='CHART-'+str(sl.id);pos[tab]['children'].append(row);pos[row]={'id':row,'type':'ROW','children':[cid],'parents':parents,'meta':{'background':'BACKGROUND_TRANSPARENT'}};pos[cid]={'id':cid,'type':'CHART','children':[],'parents':parents+[row],'meta':{'chartId':sl.id,'width':12,'height':65 if v.viz!='table' else 60,'sliceName':v.title}}
   filters=[]
   defaults={}
   for v in specs:defaults.update(v.filters)
   # Optional native filters: selection only narrows its explicitly named region.
   if page=='online':defaults.update({'平台':None,'条线':None})
   if page=='capacity':defaults.update({'线下团队':None})
   if page in ['overview','virtual','prep','university']:defaults.update({'学校':None,'条线':None,'人员':None})
   for idx,(name,default) in enumerate(defaults.items()):
    scope=[charts[v.key].id for v in specs if name in v.filters or (default is None and name in datasets[v.key].column_names)]
    if name=='平台':scope=[charts[v.key].id for v in specs if v.key in ['online_platforms','online_platform_groups']]
    if name=='人员':scope=[charts[v.key].id for v in specs if v.section in ['个人表现','高中留学渠道']]
    if not scope:continue
    candidates=[v for v in specs if charts[v.key].id in scope and name in datasets[v.key].column_names]
    ds=opts if name=='业务组' else option_sets[name] if name in option_sets else datasets[candidates[0].key]
    values=default if isinstance(default,list) else [default]
    control={'enableEmptyFilter':name in {'期间','线上期间','个人月份','产能月份','语培统计范围','管理单元','目标团队','月模式','含删除回收','含死单','产品范围','六维人员','业务线','平台业务线'},'multiSelect':isinstance(default,list) or default is None,'searchAllOptions':True,'inverseSelection':False,'defaultToFirstItem':False}
    mask={} if default is None else {'extraFormData':{'filters':[{'col':name,'op':'IN','val':values}]},'filterState':{'value':values}}
    filters.append({'id':f'NATIVE_FILTER-p3-{page}-{idx}','name':name,'filterType':'filter_select','targets':[{'datasetId':ds.id,'column':{'name':name}}],'defaultDataMask':mask,'cascadeParentIds':[],'scope':{'rootPath':['ROOT_ID'],'excluded':[s.id for s in slices if s.id not in scope]},'controlValues':control,'type':'NATIVE_FILTER','chartsInScope':scope,'tabsInScope':[]})
   for item in filters:
    if item['name']=='语培统计范围':
     item['description']='仅影响语培工单、新生报入现金和人头及同比；全部为主动加被动，人头按学员编号去重。留学、跨线合计、人员产能和费用趋势不参与切换。'
   if page=='overview':
    parent=next(item['id'] for item in filters if item['name']=='管理单元')
    for item in filters:
     if item['name']=='目标团队':
      item['cascadeParentIds']=[parent];item['description']='市场总计可切换线上/线下目标；其他管理单元仅显示本单元全部。'
   dashboard.position_json=json.dumps(pos,ensure_ascii=False)
   dashboard.json_metadata=json.dumps({'native_filter_configuration':filters,'cross_filters_enabled':False,'color_scheme':'supersetColors','show_native_filters':True},ensure_ascii=False)
   dashboard.css='body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}.dashboard-header{border-bottom:3px solid #176779}.dashboard-content{background:#f4f7f8}.filter-bar{background:#fff}.dashboard-component-header{font-weight:600;color:#183f4c}th{white-space:nowrap}'
   receipt['pages'][page]={'id':dashboard.id,'url':os.environ.get('SHADOW_BI_PUBLIC_URL','http://127.0.0.1:18089')+f'/superset/dashboard/shadow-bi-p3-{page}/','filters':filters}
  db.session.commit()
  (AUDIT/'evidence/bootstrap.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
  print(json.dumps({'pages':len(pages),'datasets':len(datasets),'charts':len(charts)},ensure_ascii=False))
if __name__=='__main__':main()
