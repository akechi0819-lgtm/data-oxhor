"""P3 的真实 BI 消费 SQL；只投影已验收 P2 语义，不重算业务规则。"""
from dataclasses import dataclass
from pathlib import Path
import json
import os

ROOT=Path(__file__).resolve().parents[3]
_PATH_ENV={
 'AUDIT':'SHADOW_BI_AUDIT', 'SOURCE_LIBRARY':'SHADOW_BI_SOURCE_LIBRARY',
 'SOURCE_BATCH':'SHADOW_BI_SOURCE_BATCH', 'LIBRARY':'SHADOW_BI_LIBRARY',
 'BATCH':'SHADOW_BI_BATCH',
}
_RUNTIME_PATHS=('AUDIT','LIBRARY','BATCH')
_SOURCE_PATHS=('SOURCE_LIBRARY','SOURCE_BATCH')

def _current_paths(root):
 workspace=Path(root)/'customers/shadow_bi_daily'
 pointer=workspace/'Output/ShadowDaily/current.json'
 try:
  current=json.loads(pointer.read_text(encoding='utf-8'))
 except FileNotFoundError as exc:
  raise FileNotFoundError(f'新版数仓current发布指针缺失：{pointer}') from exc
 except json.JSONDecodeError as exc:
  raise ValueError(f'新版数仓current发布指针不是有效JSON：{pointer}') from exc
 if not isinstance(current,dict):
  raise ValueError(f'新版数仓current发布指针不是JSON对象：{pointer}')
 run_id=current.get('run_id')
 if (current.get('status')!='published' or not isinstance(run_id,str)
     or not run_id.startswith('run_shadow_daily_') or Path(run_id).name!=run_id):
  raise ValueError(f'新版数仓current发布指针未指向已发布日更批次：{pointer}')
 batch=run_id+'_business'
 run_root=workspace/'Output/ShadowDaily'/run_id
 paths={
  'AUDIT':Path(root)/'.local/audits'/f'shadow-bi-p3-{run_id}',
  'SOURCE_LIBRARY':workspace/'Output/ShadowBI'/batch/'library',
  'SOURCE_BATCH':batch,
  'LIBRARY':run_root/'presentation',
  'BATCH':run_id,
 }
 for name in ('SOURCE_LIBRARY','LIBRARY'):
  if not paths[name].is_dir():
   raise FileNotFoundError(f'新版数仓current批次缺少P3 {name}：{paths[name]}')
 return paths

def _paths_for_environment(root,environ):
 explicit={name:environ.get(env_name) for name,env_name in _PATH_ENV.items()}
 if any(value=='' for value in explicit.values()):
  raise ValueError('SHADOW_BI_* path and batch environment values must not be empty')
 runtime_configured=all(explicit[name] is not None for name in _RUNTIME_PATHS)
 source_configured=all(explicit[name] is not None for name in _SOURCE_PATHS)
 source_unused=all(explicit[name] is None for name in _SOURCE_PATHS)
 if runtime_configured and (source_configured or source_unused):
  current={}
 else:
  current=_current_paths(root)
 result={}
 for name,value in explicit.items():
  selected=value if value is not None else current.get(name)
  result[name]=Path(selected) if name in {'AUDIT','SOURCE_LIBRARY','LIBRARY'} and selected is not None else selected
 return result

_PATHS=_paths_for_environment(ROOT,os.environ)
AUDIT=_PATHS['AUDIT']
SOURCE_LIBRARY=_PATHS['SOURCE_LIBRARY']
SOURCE_BATCH=_PATHS['SOURCE_BATCH']
LIBRARY=_PATHS['LIBRARY']
BATCH=_PATHS['BATCH']
PAGES={'overview':'市场总览','virtual':'线上虚拟人','prep':'留学预备与高中','university':'大学','online':'线上平台','capacity':'人员产能'}

def q(s):return '"'+s.replace('"','""')+'"'
def txt(obj,path):return f"json_extract_string({obj}, '$.{path}')"
def num(obj,path):return f"TRY_CAST({txt(obj,path)} AS DOUBLE)"
def col(expr,name):return f'{expr} AS {q(name)}'
def line(expr):return f"CASE {expr} WHEN 'training' THEN '语培' WHEN 'abroad' THEN '留学及小语种' ELSE {expr} END"
def status(expr):
 return f"CASE {expr} WHEN 'available' THEN '已提供' WHEN 'partial' THEN '部分覆盖' WHEN 'missing' THEN '未提供' WHEN 'not_covered' THEN '该期间未覆盖' WHEN 'not_connected' THEN '未接入' WHEN 'not_configured' THEN '未配置' WHEN 'future' THEN '尚未开始' WHEN 'separate_counts' THEN '分域人数' WHEN 'zero_denominator' THEN '分母为零' ELSE {expr} END"

def personal_time_progress(period,mode,start,end):
 target_end=f"CASE WHEN {mode}='calendar' THEN last_day(TRY_CAST({period}||'-01' AS DATE)) ELSE TRY_CAST({period}||'-25' AS DATE) END"
 elapsed=f"date_diff('day', TRY_CAST({start} AS DATE), TRY_CAST({end} AS DATE))+1"
 total=f"date_diff('day', TRY_CAST({start} AS DATE), {target_end})+1"
 return f"CASE WHEN {end} IS NULL THEN 0.0 WHEN NOT regexp_matches({period}, '^[0-9]{{4}}-[0-9]{{2}}$') THEN NULL ELSE CAST({elapsed} AS DOUBLE)/NULLIF({total},0) END"

@dataclass
class View:
 key:str
 title:str
 sql:str
 columns:list
 page:str
 section:str
 filters:dict
 viz:str='table'
 more:dict|None=None

VIEWS=[]
def add(key,title,sql,columns,page,section,filters=None,viz='table',more=None):
 VIEWS.append(View(key,title,sql,columns,page,section,filters or {},viz,more))

# Every filter uses a visible Chinese column; Jinja only selects an existing finite mask.
SELECTION="""{% set groups = filter_values('业务组', remove_filter=True) %}
{% set mask = (1 if '青少' in groups else 0) + (2 if '初中' in groups else 0) + (4 if '高中' in groups else 0) %}
"""

def base(page):
 if page=='prep':
  return SELECTION+"SELECT period_id AS 期间, 'prep_high' AS 管理单元, t.value AS v FROM queries.selection_team_periods, json_each(json_extract(selection_team_periods.row_json, '$.view'), '$.teams') t WHERE CAST(selection AS INTEGER) = {{ mask }}"
 unit={'virtual':'virtual','university':'university'}.get(page)
 return 'SELECT period_id AS 期间, team_id AS 管理单元, view AS v FROM queries.team_periods'+(f" WHERE team_id='{unit}'" if unit else " WHERE team_id IN ('total','virtual','online')")

def cte(page):
 b=base(page)
 if b.startswith('{%'):
  return SELECTION+'WITH b AS ('+b[len(SELECTION):]+') '
 return 'WITH b AS ('+b+') '

METRIC_COLUMNS=['指标','当期','呈现','同期','同比','同期状态','目标','目标配置','完成率','目标差额','时间进度差额','状态','口径']
def metric_cols(obj):
 return [col(num(obj,'actual'),'当期'),col(txt(obj,'display'),'呈现'),col(num(obj,'prior'),'同期'),col(num(obj,'yoy'),'同比'),col(f"CASE WHEN {txt(obj,'status')} IN ('partial','not_covered','separate_counts') THEN '不可同比' WHEN {txt(obj,'prior')} IS NULL OR {txt(obj,'yoy')} IS NULL THEN '无同期同比' ELSE '可比' END",'同期状态'),col(num(obj,'target'),'目标'),col(f"CASE WHEN {txt(obj,'target')} IS NULL THEN '未配置' ELSE '已配置' END",'目标配置'),col(num(obj,'completion'),'完成率'),col(num(obj,'gap'),'目标差额'),col(num(obj,'time_gap'),'时间进度差额'),col(status(txt(obj,'status')),'状态'),col(txt(obj,'note'),'口径')]

def metric_rows(prefix,obj,source,metric_names=('orders','cash','heads')):
 # Values stay numeric; presentation and missing status are separate columns.
 return 'SELECT '+', '.join(prefix+[col("CASE m.key WHEN 'orders' THEN '工单' WHEN 'cash' THEN '现金（元）' WHEN 'heads' THEN '人头' ELSE m.key END",'指标')]+metric_cols('m.value'))+f" FROM {source}, json_each({obj}) m WHERE m.key IN ("+','.join("'"+x+"'" for x in metric_names)+')'

for page in ['overview','virtual','prep','university']:
 common={'期间':'FY27'}
 if page in ['overview','virtual']:common['管理单元']='total' if page=='overview' else 'virtual'
 if page=='prep':common['业务组']=['青少','初中','高中']
 pre=[q('期间'),q('管理单元'),col(line('l.key'),'业务线')]
 sql=cte(page)+metric_rows(pre,'l.value',"b, json_each(b.v, '$.lines') l")
 add(page+'_lines','当期经营 · 工单 / 现金 / 独立人头',sql,['业务线']+METRIC_COLUMNS,page,'经营总览',common)
 if page in ['overview','virtual']:
  special='combined_orders' if page=='virtual' else 'market_orders'
  sql=cte(page)+"SELECT 期间, 管理单元, '"+('团队合并工单' if page=='virtual' else '语培总盘逐ID工单')+"' AS 指标, "+', '.join(metric_cols("json_extract(v, '$.combined_orders')" if page=='virtual' else "COALESCE(json_extract(v, '$.market_orders'),json_extract(v, '$.combined_orders'))"))+" FROM b"
  add(page+'_market','团队合并工单' if page=='virtual' else '语培市场总盘 · 逐工单去重',sql,METRIC_COLUMNS,page,'经营总览',common)
 # Ordinary group comparison and SSC remain independent from target-team scope.
 for path,title,key in [('business_groups','业务组目标与完成','groups'),('yoy_groups','业务组同期对比 · 含 SSC','yoy')]:
  sql=cte(page)+metric_rows([q('期间'),q('管理单元'),col(txt('g.value','name'),'业务组名称')],'g.value',f"b, json_each(b.v, '$.{path}') g")
  add(page+'_'+key,title,sql,['业务组名称']+METRIC_COLUMNS,page,'经营总览',common)
 if page=='overview':
  sql=cte(page)+metric_rows([q('期间'),q('管理单元'),col("CASE s.key WHEN 'all' THEN '全部' WHEN 'online' THEN '线上' ELSE '线下' END",'目标团队'),col(txt('g.value','name'),'业务组名称'),col(num('g.value','passive_cash_share.numerator'),'被动现金分子'),col(num('g.value','passive_cash_share.denominator'),'现金固定分母'),col(num('g.value','passive_cash_share.ratio'),'被动现金占比'),col(status(txt('g.value','passive_cash_share.status')),'占比状态')],'g.value',"b, json_each(COALESCE(json_extract(b.v, '$.team_scope_views'), json_object('all', json_object('business_groups', json_extract(b.v, '$.business_groups'), 'study_abroad_progress',json_extract(b.v,'$.abroad_progress'))))) s, json_each(s.value, '$.business_groups') g")
  add('overview_targets','团队目标与被动现金占比',sql,['目标团队','业务组名称']+METRIC_COLUMNS+['被动现金分子','现金固定分母','被动现金占比','占比状态'],page,'目标进度',{**common,'目标团队':'全部'})
  sql=cte(page)+metric_rows([q('期间'),q('管理单元'),col("CASE s.key WHEN 'all' THEN '全部' WHEN 'online' THEN '线上' ELSE '线下' END",'目标团队'),col(txt('g.value','name'),'业务组名称')],'g.value',"b, json_each(COALESCE(json_extract(b.v, '$.team_scope_views'), json_object('all', json_object('business_groups', json_extract(b.v, '$.business_groups'), 'study_abroad_progress',json_extract(b.v,'$.abroad_progress'))))) s, json_each(s.value, '$.study_abroad_progress') g")
  add('overview_abroad_targets','留学线上 / 线下目标进度',sql,['目标团队','业务组名称']+METRIC_COLUMNS,page,'目标进度',{**common,'目标团队':'全部'})
 if page!='prep':
  sql=cte(page)+"SELECT 期间, 管理单元, "+', '.join([col(txt('g.value','line'),'条线')]+[col(num('g.value',k),n) for k,n in [('online','线上'),('offline','线下'),('unassigned','待确认'),('total','合计')]])+" FROM b, json_each(b.v, '$.country_groups') g"
  add(page+'_countries','国家条线汇总',sql,['条线','线上','线下','待确认','合计'],page,'国家条线',common)
  sql=cte(page)+"SELECT 期间, 管理单元, "+', '.join([col(txt('g.value','line'),'条线'),col(txt('c.value','country'),'国家')]+[col(num('c.value',k),n) for k,n in [('online','线上'),('offline','线下'),('unassigned','待确认'),('total','合计')]])+" FROM b, json_each(b.v, '$.country_groups') g, json_each(g.value, '$.countries') c"
  add(page+'_countries_child','条线 × 国家',sql,['条线','国家','线上','线下','待确认','合计'],page,'国家条线',common)
 # Personal source is deliberately independent of operating period and team target.
 if page=='prep':
  personal=SELECTION+"WITH b AS (SELECT period_id, t.value v FROM queries.selection_team_periods, json_each(json_extract(selection_team_periods.row_json, '$.view'), '$.teams') t WHERE CAST(selection AS INTEGER)={{ mask }}), p0 AS (SELECT period_id, mode, e.value person, json_extract_string(v, CASE WHEN mode='calendar' THEN '$.person_calendar.person_start' ELSE '$.person_start' END) window_start, json_extract_string(v, CASE WHEN mode='calendar' THEN '$.person_calendar.person_through' ELSE '$.person_through' END) window_end FROM b, (VALUES ('performance'),('calendar')) modes(mode), json_each(v, CASE WHEN mode='calendar' THEN '$.person_calendar.people' ELSE '$.people' END) e), p AS (SELECT *, "+personal_time_progress('period_id','mode','window_start','window_end')+" AS window_progress FROM p0) SELECT period_id, mode AS month_mode, person, s.value AS \"view\", s.key AS state, window_start, window_end, window_progress FROM p, json_each(person, '$.order_status_views') s"
 else:
  unit={'overview':'total','virtual':'virtual','university':'university'}[page]
  personal="SELECT period_id, team_id, month_mode, person, view, state, window_start, window_end, "+personal_time_progress('period_id','month_mode','window_start','window_end')+" AS window_progress FROM queries.person_periods WHERE "+("team_id IN ('total','virtual','online')" if page=='overview' else f"team_id='{unit}'")
 pfx=SELECTION if page=='prep' else ''
 inner=personal[len(SELECTION):] if page=='prep' else personal
 personal_sql=pfx+'WITH p AS ('+inner+') SELECT '+', '.join([col('period_id','个人月份'),*([col('team_id','管理单元')] if page=='overview' else []),col("CASE month_mode WHEN 'performance' THEN '绩效月' ELSE '自然月' END",'月模式'),col("CASE left(state,1) WHEN '1' THEN '包含' ELSE '不含' END",'含删除回收'),col("CASE right(state,1) WHEN '1' THEN '包含' ELSE '不含' END",'含死单'),col(txt('person','name'),'人员'),col(txt('person','home_group'),'所属业务组'),col(line(txt('person','business_line')),'主业务'),col('window_start','窗口开始'),col('window_end','窗口结束'),col('window_progress','时间进度')]+[col(num('view',k),n) for k,n in [('training_actual','语培工单'),('abroad_actual','留学工单'),('combined_actual','合计工单'),('training_completion','语培完成率'),('abroad_completion','留学完成率'),('combined_completion','合计完成率')]]+[col(num('person',k),n) for k,n in [('training_target','语培目标'),('abroad_target','留学目标'),('combined_target','合计目标'),('cash_actual.actual','现金'),('cash_actual.target','现金目标'),('cash_actual.completion','现金完成率'),('heads_actual.actual','人头')]]+[col(txt('person','heads_actual.display'),'分域人数'),col(status(txt('person','cash_actual.status')),'现金状态'),col(status(txt('person','heads_actual.status')),'人数状态')])+' FROM p'
 pf={'个人月份':'2026-10','月模式':'绩效月','含删除回收':'不含','含死单':'包含'}
 if page=='prep':pf['业务组']=['青少','初中','高中']
 if page=='overview':pf['管理单元']='total'
 add(page+'_people','个人完成 · 独立月份',personal_sql,['人员','所属业务组','主业务','语培工单','语培目标','语培完成率','留学工单','留学目标','留学完成率','合计工单','合计目标','合计完成率','现金','现金目标','现金完成率','人头','分域人数','现金状态','人数状态','窗口开始','窗口结束'],page,'个人表现',pf)
 # High-school personal channels use operating natural window, not personal-month filter.
 if page in ['prep','overview']:
  sql="WITH p AS (SELECT * FROM queries.person_periods WHERE team_id='total' AND month_mode='calendar' AND json_extract_string(person,'$.home_group')='高中' AND json_extract_string(person,'$.business_line')='abroad') SELECT "+', '.join([col('period_id','期间'),col('person_name','人员'),col("CASE left(state,1) WHEN '1' THEN '包含' ELSE '不含' END",'含删除回收'),col("CASE right(state,1) WHEN '1' THEN '包含' ELSE '不含' END",'含死单'),col('window_start','窗口开始'),col('window_end','窗口结束'),col(txt('c.value','name'),'二级渠道'),col(txt('c.value','first_channel'),'一级渠道'),col(num('view','abroad_actual'),'本人工单分母'),col(num('person','cash_actual.actual'),'本人现金'),col(num('c.value','orders.actual'),'工单'),col(num('c.value','orders.prior'),'同期'),col(num('c.value','orders.yoy'),'同比'),col(num('c.value','share'),'本人占比')])+" FROM p, json_each(p.view, '$.abroad_channels') c"
  add(page+'_personal_channels','高中留学 · 本人渠道构成',sql,['人员','二级渠道','一级渠道','工单','同期','同比','本人工单分母','本人占比','本人现金','窗口开始','窗口结束'],page,'高中留学渠道',{'期间':'FY27','含删除回收':'不含','含死单':'包含'})

# Online line and platform-local filters remain distinct.
adcols=[col(num('a','spend'),'花费'),col(status(txt('a','spend_status')),'费用状态'),col(num('a','roi'),'回收倍数'),col(num('a','cost_per_order'),'单条工单成本'),col(num('a','roi_cash'),'同窗现金'),col(num('a','roi_spend'),'同窗费用'),col(num('a','roi_orders'),'同窗工单'),col(txt('a','roi_start_date'),'费用窗口开始'),col(txt('a','roi_through_date'),'费用窗口结束'),col(txt('a','note'),'费用说明')]
ADC=['花费','费用状态','回收倍数','单条工单成本','同窗现金','同窗费用','同窗工单','费用窗口开始','费用窗口结束','费用说明']
of={'线上期间':'2026-10','业务线':['语培','留学及小语种']}
for key,table,title,obj in [('summary','online_lines','线上经营 · 目标与时间进度差额','view'),('groups','online_groups','业务组目标与进度','row_json')]:
 prefix=[col('period_id','线上期间'),col(line('business_line'),'业务线')]
 if key=='groups':prefix.append(col('name','业务组名称'))
 sql='WITH x AS (SELECT *, json_extract('+obj+", '$.advertising') a FROM queries."+table+') '+metric_rows(prefix+adcols,obj,'x')
 add('online_'+key,title,sql,(['业务组名称'] if key=='groups' else ['业务线'])+METRIC_COLUMNS+ADC,'online','经营总览',of)
sql="WITH x AS (SELECT *, advertising::JSON a FROM queries.online_platforms) SELECT "+', '.join([col('period_id','线上期间'),col(line('business_line'),'业务线'),col(line('business_line'),'平台业务线'),col('name','平台'),col('orders','工单'),col('prior_orders','工单同期'),col('orders_yoy','工单同比'),col('share','工单占比'),col('today_orders','截止日新增'),col('cash','现金'),col('prior_cash','现金同期'),col('cash_yoy','现金同比')]+adcols)+' FROM x'
add('online_platforms','平台表现',sql,['平台','平台业务线','工单','工单同期','工单同比','工单占比','截止日新增','现金','现金同期','现金同比']+ADC,'online','平台',{**of,'平台业务线':['语培','留学及小语种']})
sql="WITH x AS (SELECT *, g.value g, json_extract(g.value,'$.advertising') a FROM queries.online_platforms, json_each(online_platforms.row_json, '$.groups') g) SELECT "+', '.join([col('period_id','线上期间'),col(line('business_line'),'业务线'),col('name','平台'),col(txt('g','name'),'业务组名称'),col(num('g','orders'),'工单'),col(num('g','prior_orders'),'工单同期'),col(num('g','today_orders'),'截止日新增'),col(num('g','cash'),'现金'),col(num('g','prior_cash'),'现金同期')]+adcols)+' FROM x'
add('online_platform_groups','平台 × 业务组',sql,['平台','业务组名称','工单','工单同期','截止日新增','现金','现金同期']+ADC,'online','平台',of)
sql="SELECT period_id AS 线上期间, CAST(date AS DATE) AS 日期, CASE l WHEN 'training' THEN '语培' ELSE '留学及小语种' END AS 业务线, "+', '.join([col(f"CASE l WHEN 'training' THEN TRY_CAST(training_{k} AS DOUBLE) ELSE TRY_CAST(abroad_{k} AS DOUBLE) END",n) for k,n in [('orders','工单'),('cash','现金'),('spend','花费'),('roi','回收倍数')]])+", CASE l WHEN 'training' THEN training_spend_status ELSE abroad_spend_status END AS 费用状态 FROM queries.online_daily, (VALUES ('training'),('abroad')) lines(l)"
add('online_daily','每日明细',sql,['日期','业务线','工单','现金','花费','回收倍数','费用状态'],'online','日趋势与明细',of)
add('online_trend','日趋势 · 工单',sql,['日期','业务线','工单'],'online','日趋势与明细',of,'echarts_timeseries_line',{'x_axis':'日期','time_grain_sqla':'P1D','groupby':['业务线'],'metrics':[{'expressionType':'SQL','sqlExpression':'SUM("工单")','label':'工单','hasCustomLabel':True,'optionName':'orders'}],'query_mode':'aggregate','row_limit':1000000,'rich_tooltip':True})
sql="SELECT period_id AS 线上期间, "+line('business_line')+" AS 业务线, "+', '.join([col(txt('d.value','name'),'条线'),col(num('d.value','orders'),'工单'),col(num('d.value','prior_orders'),'同期'),col(num('d.value','yoy'),'同比')])+" FROM queries.online_lines, json_each(online_lines.row_json, '$.view.dimensions') d"
add('online_countries','留学条线汇总',sql,['条线','工单','同期','同比'],'online','国家条线',of)
sql="SELECT period_id AS 线上期间, "+line('business_line')+" AS 业务线, "+', '.join([col(txt('d.value','name'),'条线'),col(txt('c.value','name'),'国家'),col(num('c.value','orders'),'工单'),col(num('c.value','prior_orders'),'同期'),col(num('c.value','yoy'),'同比')])+" FROM queries.online_lines, json_each(online_lines.row_json, '$.view.dimensions') d, json_each(d.value, '$.children') c"
add('online_countries_child','条线 × 国家',sql,['条线','国家','工单','同期','同比'],'online','国家条线',of)

# Capacity: monthly independent controls and the exact existing product breakdown.
sql="SELECT period_id AS 产能月份, person_name AS 人员, CASE left(state,1) WHEN '1' THEN '包含' ELSE '不含' END AS 含删除回收, CASE right(state,1) WHEN '1' THEN '包含' ELSE '不含' END AS 含死单, "+', '.join([col("concat("+line(txt('person','business_line'))+", ' · ', "+txt('person','home_group')+")",'线下团队'),col(txt('person','home_group'),'所属业务组'),col(line(txt('person','business_line')),'主业务'),col("scope",'产品范围')]+[col(num("CASE WHEN scope='合计' THEN view ELSE json_extract(view, CASE scope WHEN '留学' THEN '$.breakdowns.study_abroad' ELSE '$.breakdowns.small_language' END) END",f'{bucket}.{metric}'),label+unit) for bucket,label in [('self','自主创造'),('self_rate','自创率'),('targets','目标'),('completion','本业务完成率'),('received','额外接收'),('own_total','本业务合计'),('output','额外输出'),('created_total','自创合计')] for metric,unit in [('orders','工单'),('cash','现金')]]+[col(num('person','pending_count'),'个人待核数'),col("CASE WHEN json_extract_string(person,'$.source_kind')='confirmed_history' THEN '历史确认汇总；未提供状态及自创明细' ELSE '按已提供来源' END",'历史细分覆盖')])+" FROM queries.capacity_people, (VALUES ('合计'),('留学'),('小语种')) scopes(scope)"
capcols=['人员','所属业务组','主业务','产品范围']+[l+u for l in ['自主创造','自创率','目标','本业务完成率','额外接收','本业务合计','额外输出','自创合计'] for u in ['工单','现金']]+['个人待核数','历史细分覆盖']
add('capacity_month','月度产能 · 自创 / 接收 / 输出',sql,capcols,'capacity','月度贡献',{'产能月份':'2026-10','产品范围':'合计','含删除回收':'不含','含死单':'包含'})
sql="SELECT person_name AS 六维人员, label AS 维度, TRY_CAST(json_extract_string(row_json,'$.value') AS DOUBLE) AS 本人, mean AS 同组均值, scale AS 轴上限, relative AS 相对同组, through_date AS 年度截止, '2026-06-01' AS 年度开始 FROM queries.radar_axes"
add('capacity_radar_values','年度六维 · 原值与同组均值',sql,['六维人员','维度','本人','同组均值','轴上限','相对同组','年度开始','年度截止'],'capacity','年度六维',{'六维人员':'刘彬'})
radsql="SELECT person_name AS 六维人员, label AS 维度, series AS 系列, CASE series WHEN '本人' THEN TRY_CAST(json_extract_string(row_json,'$.value') AS DOUBLE)/NULLIF(scale,0) ELSE mean/NULLIF(scale,0) END AS 比例 FROM queries.radar_axes, (VALUES ('本人'),('同组均值')) s(series)"
metrics=[{'expressionType':'SQL','sqlExpression':f'MAX(CASE WHEN "维度"=\'{label}\' THEN "比例" END)','label':label,'hasCustomLabel':True,'optionName':str(i)} for i,label in enumerate(['工单数','签约量','转化率','渠道／校代现金','TMK现金','活动现金'])]
add('capacity_radar','年度六维 · 本人和同组均值',radsql,['系列','维度','比例'],'capacity','年度六维',{'六维人员':'刘彬'},'radar',{'metrics':metrics,'groupby':['系列'],'query_mode':'aggregate','radarMetricMaxValue':1,'radarMetricMinValue':0,'show_labels':True})
# Full fact drill dataset has no 10,000-record cap; actual UI requests use LIMIT/OFFSET.
FACT_COLUMNS={'fact_id':'事实ID','business_line':'业务线','metric':'指标','event_date':'日期','value':'数值','school_name':'学校','grade':'年级','first_channel':'一级渠道','person_name':'人员'}
# The precise available fact fields are set by bootstrap from the sealed manifest.
sql="SELECT name AS 活动, training_orders AS 语培工单, abroad_orders AS 留学工单, orders AS 合计工单, cash AS 现金, heads AS 人头, heads_display AS 分域人数, heads_parts AS 分域明细, cash_status AS 现金状态 FROM queries.activities"
add('activities','市场活动 · 历史累计',sql,['活动','语培工单','留学工单','合计工单','现金','人头','分域人数','现金状态'],'activities','累计')
# Minimal, existing audit fields only; no full raw-row JSON in the browser.
add('facts','业务明细',"SELECT fact_id AS 事实ID, "+line('business_line')+" AS 业务线, metric AS 指标, event_date AS 日期, value AS 数值, school_name AS 学校, grade_name AS 年级, first_channel AS 一级渠道, second_channel AS 二级渠道, owner AS 人员, order_status AS 工单状态, source_kind AS 来源, source_record AS 来源记录 FROM queries.facts",['事实ID','业务线','指标','日期','数值','学校','年级','一级渠道','二级渠道','人员','工单状态','来源','来源记录'],'overview','明细核对')
PENDING_SQL="""WITH expanded AS (
 SELECT json_extract_string(row_json,'$.month') AS 产能月份,
 json_extract_string(a.value,'$') AS 人员,
 json_extract_string(row_json,'$.source_label') AS 来源,
 json_extract_string(row_json,'$.reason') AS 原因
 FROM queries.pending_contributions, json_each(pending_contributions.row_json,'$.affected_people') a
), roster AS (
 SELECT period_id, person_name,
 concat(CASE json_extract_string(person,'$.business_line') WHEN 'training' THEN '语培' ELSE '留学及小语种' END,' · ',json_extract_string(person,'$.home_group')) AS 线下团队
 FROM queries.capacity_people WHERE state='01'
)
SELECT e.产能月份,e.人员,r.线下团队,e.来源,e.原因,COUNT(*) AS 待核记录数
FROM expanded e LEFT JOIN roster r ON r.period_id=e.产能月份 AND r.person_name=e.人员
GROUP BY e.产能月份,e.人员,r.线下团队,e.来源,e.原因"""
add('capacity_pending','待核贡献明细',PENDING_SQL,['人员','来源','原因','待核记录数'],'capacity','待核明细',{'产能月份':'2026-10'})
add('capacity_pending_count','全月去重待核数',"SELECT period_id AS 产能月份, count(pending_contributions.row_json) AS 全月待核数 FROM (SELECT DISTINCT period_id FROM queries.capacity_people) months LEFT JOIN queries.pending_contributions ON json_extract_string(pending_contributions.row_json,'$.month')=months.period_id GROUP BY period_id",['全月待核数'],'capacity','待核明细',{'产能月份':'2026-10'})
add('capacity_markers','跨线标记 · 保留待核原因',"SELECT month AS 产能月份, affected_people AS 涉及人员, source_label AS 来源, reason AS 原因, source_value AS 原值, work_order_id AS 工单ID, resource_id AS 资源ID FROM queries.marker_diagnostics",['涉及人员','来源','原因','原值','工单ID','资源ID'],'capacity','待核明细',{'产能月份':'2026-10'})
add('capacity_annual_targets','年度产能与目标',"SELECT name AS 六维人员, home_group AS 所属业务组, "+line('business_line')+" AS 主业务, TRY_CAST(json_extract_string(row_json,'$.orders') AS DOUBLE) AS 年度工单, TRY_CAST(json_extract_string(row_json,'$.cash') AS DOUBLE) AS 年度现金, TRY_CAST(json_extract_string(row_json,'$.heads') AS DOUBLE) AS 年度人头, TRY_CAST(json_extract_string(row_json,'$.conversion') AS DOUBLE) AS 年度转化率, TRY_CAST(json_extract_string(row_json,'$.cash_capacity') AS DOUBLE) AS 年度现金目标, TRY_CAST(json_extract_string(row_json,'$.cash_progress_completion') AS DOUBLE) AS 现金时间进度完成率, start_date AS 年度开始, through_date AS 年度截止, json_extract_string(row_json,'$.radar.peer_count') AS 同组人数, product_parts AS 产品分域 FROM queries.radar_people",['六维人员','所属业务组','主业务','年度工单','年度现金','年度人头','年度转化率','年度现金目标','现金时间进度完成率','同组人数','年度开始','年度截止'],'capacity','年度六维',{'六维人员':'刘彬'})
add('capacity_annual_products','年度人头与转化率 · 产品身份域',"SELECT name AS 六维人员, CASE e.key WHEN 'training' THEN '语培' WHEN 'study_abroad' THEN '留学' WHEN 'small_language' THEN '小语种' ELSE '未归属产品' END AS 产品, "+', '.join([col(num('e.value',k),n) for k,n in [('orders','工单'),('cash','现金'),('heads','独立人头'),('conversion','转化率')]])+" FROM queries.radar_people, json_each(radar_people.row_json,'$.product_parts') e",['六维人员','产品','工单','现金','独立人头','转化率'],'capacity','年度六维',{'六维人员':'刘彬'})

# Chinese management choices are finite and scoped; stable internal IDs remain in
# the sealed source relations. Empty business-group selection yields no P2 mask.
for v in VIEWS:
 if v.page=='overview' and '管理单元' in v.filters:
  v.sql='SELECT * REPLACE (CASE 管理单元 WHEN \'total\' THEN \'市场总计\' WHEN \'virtual\' THEN \'线上虚拟人\' WHEN \'online\' THEN \'线上团队\' ELSE 管理单元 END AS 管理单元) FROM ('+v.sql+') managed'
  v.filters['管理单元']='市场总计'

# Wide business tables make every legacy sort metric a real sortable column.
WIDE_NUM={'工单':'orders.actual','工单同期':'orders.prior','工单同比':'orders.yoy','现金':'cash.actual','现金同期':'cash.prior','现金同比':'cash.yoy','人头':'heads.actual','人头同期':'heads.prior','人头同比':'heads.yoy','工单占比':'share','现金占比':'cash_share'}
WIDE_TEXT={'分域人数':'heads.display','工单状态':'orders.status','现金状态':'cash.status','人数状态':'heads.status'}
GRADE_ORDER=['学龄前','幼儿','幼儿园小班','幼儿园中班','幼儿园大班','一年级','二年级','三年级','四年级','五年级','六年级','初一','初二','初三','高一','高二','高三','10年级(国外高中)','11年级(国外高中)','12年级(国外高中)','13年级(国外高中)','大一','大二','大三','大四','大五','研一','研二','研三','研究生以上','博一','博二','博士在读','博士毕业','大学已毕业','在职','年级待确认']
for page in ['overview','virtual','prep','university']:
 for kind,path,parent,child in [('channels','channels','渠道','业务组名称'),('schools','schools_by_line','学校','年级'),('grades','grades_by_line','年级',None)]:
  for detail in [False,True] if child else [False]:
   key=page+'_'+kind+('_child' if detail else '')
   filters={'期间':'FY27'}
   if page=='overview':filters['管理单元']='市场总计'
   if page=='virtual':filters['管理单元']='virtual'
   if page=='prep':filters['业务组']=['青少','初中','高中']
   title=parent+' × '+child if detail else {'channels':'渠道表现','schools':'学校排名','grades':'整体年级表现'}[kind]
   v=View(key,title,'',[],page,{'channels':'渠道','schools':'学校','grades':'年级'}[kind],filters);VIEWS.append(v)
   src="b, json_each(b.v, '$.channels') e" if kind=='channels' else f"b, json_each(b.v, '$.{path}') ln, json_each(ln.value) e"
   business=txt('e.value','business_line') if kind=='channels' else 'ln.key'
   dims=[q('期间'),q('管理单元'),col(line(business),'业务线'),col(txt('e.value','name'),parent)]
   names=['业务线',parent]
   if kind=='channels':dims.append(col(txt('e.value','first_channel'),'一级渠道'));names.append('一级渠道')
   node='e.value'
   if detail:
    src+=", json_each(e.value, '$."+('groups' if kind=='channels' else 'grades')+"') c";dims.append(col(txt('c.value','name'),child));names.append(child);node='c.value'
   vals=[col(num(node,k),n) for n,k in WIDE_NUM.items()]+[col(status(txt(node,k)) if n.endswith('状态') else txt(node,k),n) for n,k in WIDE_TEXT.items()]
   vals.append(col(f"CASE WHEN {txt(node,'orders.yoy')} IS NULL THEN '无同期同比' ELSE '可比' END",'同期状态'))
   if kind=='channels' and detail:vals.append(col(num(node,'channel_cash_share'),'渠道内现金占比'))
   if kind=='grades':
    vals.append(col("CASE "+txt(node,'name')+' '+''.join("WHEN '"+g+"' THEN "+str(i)+' ' for i,g in enumerate(GRADE_ORDER))+"ELSE 999 END",'年级顺序'));names.append('年级顺序')
   sql=cte(page)+'SELECT '+', '.join(dims+vals)+' FROM '+src+ (" WHERE "+business+"='training'" if page=='prep' else '')
   v.sql=sql;v.columns=names+list(WIDE_NUM)+list(WIDE_TEXT)+['同期状态']+(['渠道内现金占比'] if kind=='channels' and detail else []);v.more={'order_by_cols':['["年级顺序", true]']} if kind=='grades' else None
   if kind=='schools' and not detail:
    # Aggregation chooses exact P2 parent or exact child, without summing heads.
    fields=[q('期间'),q('管理单元'),col(line('ln.key'),'业务线'),col(txt('e.value','name'),'学校'),col(txt('c.value','name'),'年级')]
    for name,path2 in WIDE_NUM.items():fields.extend([col(num('e.value',path2),'父'+name),col(num('c.value',path2),'子'+name)])
    for name,path2 in WIDE_TEXT.items():fields.extend([col(txt('e.value',path2),'父'+name),col(txt('c.value',path2),'子'+name)])
    fields=[f.replace('ln.key','line_key').replace('e.value','school_json').replace('c.value','grade_json') for f in fields]
    school_cte=cte(page).rstrip()+", line_keys AS MATERIALIZED (SELECT 期间,管理单元,v,unnest(json_keys(json_extract(v,'$.schools_by_line'))) AS line_key FROM b), lines AS MATERIALIZED (SELECT 期间,管理单元,line_key,CAST(json_extract(v,'$.schools_by_line.'||line_key) AS JSON[]) AS school_array FROM line_keys), schools AS MATERIALIZED (SELECT 期间,管理单元,line_key,unnest(school_array) AS school_json FROM lines), grades AS (SELECT 期间,管理单元,line_key,school_json,unnest(CAST(json_extract(school_json,'$.grades') AS JSON[])) AS grade_json FROM schools) "
    v.sql=school_cte+'SELECT '+', '.join(fields)+" FROM grades"+(" WHERE line_key='training'" if page=='prep' else '')
    metrics=[]
    for name in list(WIDE_NUM)+list(WIDE_TEXT):
     expr=f'CASE WHEN COUNT(DISTINCT "年级") > 1 THEN MAX("父{name}") ELSE MAX("子{name}") END'
     if name.endswith('状态'):expr=status('('+expr+')')
     metrics.append({'expressionType':'SQL','sqlExpression':expr,'label':name,'hasCustomLabel':True,'optionName':'school_'+name})
    metrics.append({'expressionType':'SQL','sqlExpression':"CASE WHEN MAX(\"父工单同比\") IS NULL THEN '无同期同比' ELSE '可比' END",'label':'同期状态','hasCustomLabel':True,'optionName':'priorstatus'})
    v.more={'query_mode':'aggregate','groupby':['业务线','学校'],'metrics':metrics,'all_columns':[],'order_by_cols':[],'order_desc':True,'timeseries_limit_metric':metrics[0]}
  # Existing Chinese management source filter.
 for v in [v for v in VIEWS if v.page==page and v.key.startswith(page+'_') and any(v.key==page+'_'+x for x in ['channels','channels_child','schools','schools_child','grades'])]:
  if page=='overview':v.sql="SELECT * REPLACE (CASE 管理单元 WHEN 'total' THEN '市场总计' WHEN 'virtual' THEN '线上虚拟人' WHEN 'online' THEN '线上团队' ELSE 管理单元 END AS 管理单元) FROM ("+v.sql+") managed"

for page in ['overview','virtual','prep','university','online']:
 name='线上期间' if page=='online' else '期间'
 sql='SELECT id AS '+q(name)+", json_extract_string(row_json,'$.label') AS 统计期间, json_extract_string(row_json,'$.start_date') AS 开始日期, json_extract_string(row_json,'$.through_date') AS 截止日期, TRY_CAST(json_extract_string(row_json,'$.time_progress') AS DOUBLE) AS 时间进度, "+status("json_extract_string(row_json,'$.status')")+" AS 状态 FROM queries.periods"
 add(page+'_window','统计窗口',sql,['统计期间','开始日期','截止日期','时间进度','状态'],page,'经营总览',{name:'2026-10' if page=='online' else 'FY27'})
 if page!='prep':
  sql=cte(page)+metric_rows([q('期间'),q('管理单元'),col(txt('e.value','name'),'补充范围')],'e.value',"b, json_each(b.v, '$.lines.abroad.supplemental') e")
  filters={'期间':'FY27'}
  if page=='overview':filters['管理单元']='市场总计';sql="SELECT * REPLACE (CASE 管理单元 WHEN 'total' THEN '市场总计' WHEN 'virtual' THEN '线上虚拟人' WHEN 'online' THEN '线上团队' ELSE 管理单元 END AS 管理单元) FROM ("+sql+") managed"
  add(page+'_supplemental','留学专项 · 国际市场 / SSC / 待确认',sql,['补充范围']+METRIC_COLUMNS,page,'经营总览',filters)
# All three legacy daily series, with each unit retained on its own axis.
daily=next(v.sql for v in VIEWS if v.key=='online_daily')
for key,label,viz in [('花费','每日花费','echarts_timeseries_bar'),('现金','每日毛签金额','echarts_timeseries_line')]:
 metric={'expressionType':'SQL','sqlExpression':'SUM('+q(key)+')','label':key,'hasCustomLabel':True,'optionName':'daily_'+key}
 add('online_trend_'+('spend' if key=='花费' else 'cash'),label,daily,['日期','业务线',key],'online','日趋势与明细',of,viz,{'x_axis':'日期','groupby':['业务线'],'metrics':[metric],'query_mode':'aggregate','row_limit':1000000,'rich_tooltip':True})
last='SELECT * FROM ('+daily+') d QUALIFY 日期 = MAX(日期) OVER (PARTITION BY 线上期间)'
add('online_latest','截止日 · 工单 / 毛签 / 花费 / ROI',last,['日期','业务线','工单','现金','花费','回收倍数','费用状态'],'online','日趋势与明细',of)

for v in VIEWS:
 if v.page=='prep' and '业务组' in v.filters:
  # Native compatibility checks require a scalar target column. The filter is
  # consumed by filter_values(remove_filter=True), so this NULL is never filtered.
  v.sql='SELECT *, NULL::VARCHAR AS 业务组 FROM ('+v.sql+') finite_selection'
 if v.key=='prep_personal_channels':
  v.sql=SELECTION+'SELECT *, NULL::VARCHAR AS 业务组 FROM ('+v.sql+') personal_channels WHERE ({{ mask }} & 4) <> 0'
  v.filters['业务组']=['青少','初中','高中']
 if v.key.endswith('_people') and v.page in ['overview','virtual','prep','university']:
  v.sql='SELECT *, '+', '.join('CASE WHEN '+q(n)+" IS NULL THEN '未配置' ELSE '已配置' END AS "+q(n+'状态') for n in ['语培目标','留学目标','现金目标'])+' FROM ('+v.sql+') person_status'
  v.columns+=['语培目标状态','留学目标状态','现金目标状态']
# Online has its own business-line source; market supplemental rows belong only
# to the market/university pages.
VIEWS[:]=[v for v in VIEWS if v.key!='online_supplemental']
for v in VIEWS:
 if v.key=='prep_lines':v.sql=v.sql.replace("WHERE m.key IN ('orders','cash','heads')","WHERE m.key IN ('orders','cash','heads') AND l.key='training'")
 if v.key=='overview_market':
  v.sql=v.sql.replace("'语培总盘逐ID工单' AS 指标", "CASE WHEN json_extract_string(v,'$.id')='virtual' THEN '团队合并工单' ELSE '语培总盘逐ID工单' END AS 指标")
for v in VIEWS:
 old="CASE l WHEN 'training' THEN training_spend_status ELSE abroad_spend_status END AS 费用状态"
 if old in v.sql:v.sql=v.sql.replace(old,status("CASE l WHEN 'training' THEN training_spend_status ELSE abroad_spend_status END")+' AS 费用状态')

# 只切换语培经营与拆分；个人产能、留学专项、费用趋势不纳入范围。
_SCOPE_TABLES=('selection_team_periods','team_periods','online_platforms','online_groups','online_lines')
_SCOPE_KEYS={page+'_'+suffix for page in ('overview','virtual','prep','university')
             for suffix in ('lines','groups','yoy','channels','channels_child','schools','schools_child','grades')}
_SCOPE_KEYS.add('overview_market')
_SCOPE_KEYS.update(('online_summary','online_groups','online_platforms','online_platform_groups'))
ACQUISITION_SELECTION="""{% set acquisition = filter_values('语培统计范围', remove_filter=True) %}
{% set acquisition_scope = acquisition[0] if acquisition|length == 1 and acquisition[0] in ['被动','主动','全部'] else '被动' %}
"""
for v in VIEWS:
 if v.key not in _SCOPE_KEYS: continue
 sql=v.sql
 for table in _SCOPE_TABLES:
  sql=sql.replace('queries.'+table, "(SELECT * FROM queries.scoped_"+table+" WHERE acquisition_scope='{{ acquisition_scope }}') "+table)
 v.sql=ACQUISITION_SELECTION+"SELECT *, '{{ acquisition_scope }}' AS 语培统计范围 FROM ("+sql+") scope_view"
 v.filters={**v.filters,'语培统计范围':'被动'}

# 此核查固定为全盘，不能假装随管理单元筛选变化；随统计期间联动。
add('overview_classification','语培全盘 · 主被动未分类核查',"""
WITH p AS (SELECT * FROM queries.periods), o AS (SELECT * FROM queries.order_source_rows)
SELECT p.id AS 期间, '全盘（不随管理单元筛选）' AS 核查范围,
CASE WHEN p.through_date IS NULL THEN NULL ELSE COUNT(o.work_order_id) FILTER (
 WHERE o.event_date BETWEEN CAST(p.start_date AS DATE) AND CAST(p.through_date AS DATE)) END AS 当期未分类工单,
CASE WHEN p.through_date IS NULL THEN NULL ELSE COUNT(o.work_order_id) FILTER (
 WHERE o.event_date BETWEEN CAST(p.prior_start_date AS DATE) AND CAST(p.prior_through_date AS DATE)) END AS 同期未分类工单,
'全部仅指主动＋被动；这里的未分类记录不计入两类合计。' AS 说明
FROM p LEFT JOIN o
ON o.source_team IN ('塘沽','大学','无法判断','校区资源无法归属','武清','留学预备','需要判定','高中')
AND COALESCE(o.main_active_type,'') NOT IN ('主动','被动')
GROUP BY p.id,p.start_date,p.through_date,p.prior_start_date,p.prior_through_date
""",['核查范围','当期未分类工单','同期未分类工单','说明'],'overview','经营总览',{'期间':'FY27'})

# 明细同样支持语培主被动，留学明细保持原数据。
for v in VIEWS:
 if v.key=='facts':
  source="(SELECT * FROM queries.acquisition_facts WHERE business_line<>'training' OR acquisition_mode='{{ acquisition_scope }}' OR '{{ acquisition_scope }}'='全部') facts"
  v.sql=ACQUISITION_SELECTION+"SELECT *, '{{ acquisition_scope }}' AS 语培统计范围 FROM ("+v.sql.replace('queries.facts',source)+") details_scope"
  v.filters={**v.filters,'语培统计范围':'被动'}

# 服务器实测：原生复合表重复展开整份团队JSON会携带学校/人员大数组，
# 即使只查三项经营指标也超过1GB。先投影本查询实际引用的顶层键，
# 再执行原SQL；不改变任何值、筛选或业务聚合。
import re as _re
for _view in VIEWS:
 _keys=sorted(set(_re.findall(r"json_(?:extract_string|extract|each)\((?:b\.)?v,\s*'\$\.([A-Za-z0-9_]+)",_view.sql)))
 if _keys:
  for _source in ('view','t.value'):
   _needle=_source+' AS v'
   if _needle in _view.sql:
    _projection='json_object('+','.join("'"+k+"',json_extract("+_source+",'$."+k+"')" for k in _keys)+') AS v'
    _view.sql=_view.sql.replace(_needle,_projection)
