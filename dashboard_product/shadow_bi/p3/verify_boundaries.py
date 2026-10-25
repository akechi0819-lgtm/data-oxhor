"""Native API boundary cases and explicit saved filter scopes."""
import json
from dashboard_product.shadow_bi.p3.verify_api import Client,f
from dashboard_product.shadow_bi.p3.catalog import ROOT,AUDIT,VIEWS,SOURCE_LIBRARY,SOURCE_BATCH

def main():
 c=Client();checks=[]
 # 2026-10-22 已授权观远口径批次替代 P0 数值基准。独立查询当前源库，
 # 不从被测 API 返回值生成期望；保留源查询、批次、manifest 与结果回执。
 from data_platform.business_library import execute_library_query,read_library_result
 def source_count(table,where=''):
  receipt=execute_library_query(library=SOURCE_LIBRARY,batch_id=SOURCE_BATCH,
   sql='SELECT COUNT(*) AS n FROM queries.'+table+(' WHERE '+where if where else ''),
   run_id='run_p35_boundary_'+table,output_root=c.evidence,max_rows=1,max_result_bytes=10000)
  return read_library_result(receipt,output_root=c.evidence)['rows'][0][0]
 activity_count=source_count('activities')
 fact_count=source_count('acquisition_facts',"business_line<>'training' OR acquisition_mode='被动'")
 checks.append({'name':'当前基准来源','batch':SOURCE_BATCH,'activities':activity_count,'passive_facts':fact_count,'reason':'docs/guanyuan-acquisition-scope-20261022.md；非P0旧口径；以独立受控源查询为期望'})
 def passed(name):checks.append({'name':name,'status':'passed'});print(name,'passed',flush=True)
 a=c.query('activities',limit=50,order=[['活动',True]],name='activity-first50');b=c.query('activities',limit=50,offset=50,order=[['活动',True]],name='activity-second50')
 assert len(a['data'])==len(b['data'])==50 and not {x['活动'] for x in a['data']} & {x['活动'] for x in b['data']};assert 'LIMIT 50' in b['query'].upper() and 'OFFSET 50' in b['query'].upper()
 count=c.query('activities',columns=[],metrics=[{'expressionType':'SQL','sqlExpression':'COUNT(*)','label':'项数','optionName':'count','hasCustomLabel':True}],limit=1,name='activity-count');assert count['data'][0]['项数']==activity_count
 search=c.query('activities',filters=[f('活动','%10月份低龄%','ILIKE')],name='activity-search');assert any(x['现金']==11883.3 for x in search['data']);passed('活动50行分页、包含搜索及当前批次源库全量计数')
 far=c.query('facts',limit=50,offset=10000,order=[['事实ID',True]],name='facts-beyond10000');assert len(far['data'])==50 and 'OFFSET 10000' in far['query'].upper()
 count=c.query('facts',columns=[],metrics=[{'expressionType':'SQL','sqlExpression':'COUNT(*)','label':'项数','optionName':'count','hasCustomLabel':True}],limit=1,name='facts-full-count');assert count['data'][0]['项数']==fact_count;passed('明细超10000仍可服务端分页，当前被动明细与源库全量计数一致')
 for groups in [['青少'],['初中','高中'],['高中'],[]]:
  d=c.query('prep_lines',filters=[f('期间','FY27')]+([f('业务组',groups)] if groups else []),name='selection-'+str(len(c.results)))
  assert len(d['data'])==(3 if groups else 0)
  assert '业务组 IN' not in d['query']
 passed('原生多选真实选择P2组合，空选为空')
 rows=[]
 for state in ['00','01','10','11']:
  d=c.query('overview_people',filters=[f('管理单元','市场总计'),f('个人月份','2026-07'),f('月模式','绩效月'),f('含删除回收','包含' if state[0]=='1' else '不含'),f('含死单','包含' if state[1]=='1' else '不含'),f('人员','刘彬')],name='person-state-'+state);rows.append(d['data'][0])
 assert [r['语培工单'] for r in rows]==[6,13,7,14]
 assert all(all(r[k]==rows[0][k] for k in ['现金','人头','语培目标','留学目标','现金目标','现金目标状态']) for r in rows);passed('两个独立状态开关仅改变既定工单，现金人头目标不变')
 windows=[]
 for mode in ['绩效月','自然月']:
  d=c.query('overview_people',filters=[f('管理单元','市场总计'),f('个人月份','2026-10'),f('月模式',mode),f('含删除回收','不含'),f('含死单','包含'),f('人员','刘彬')],name='person-mode-'+mode);windows.append(d['data'][0])
 assert windows[0]['窗口开始']!=windows[1]['窗口开始'];passed('个人绩效/自然月分别使用真实窗口')
 targets=[]
 for scope in ['全部','线上']:
  d=c.query('overview_targets',filters=[f('期间','FY27'),f('管理单元','市场总计'),f('目标团队',scope),f('业务组名称','大学'),f('指标','工单')],name='fixed-denominator-'+scope);targets.append(d['data'][0])
 assert targets[0]['新生现金固定分母']==targets[1]['新生现金固定分母']==12777455.1 and targets[0]['被动现金分子']!=targets[1]['被动现金分子'];passed('市场团队分子变化，特殊现金分母固定')
 for unit in ['线上虚拟人','线上团队']:
  d=c.query('overview_targets',columns=['目标团队'],filters=[f('期间','FY27'),f('管理单元',unit)],name='unit-only-all-'+unit);assert d['data']==[{'目标团队':'全部'}]
 passed('非市场总计管理单元只提供全部目标团队，不提供无效的线上/线下选择')
 # Actual native Drill by adds grade while retaining selected school.
 school='天津大学'
 cols=['业务线','学校','年级'];filters=[f('期间','FY27'),f('管理单元','市场总计'),f('学校',school),f('业务线','语培')]
 drill=c.query('overview_schools',columns=cols,filters=filters,limit=1000,name='native-school-grade-drill');child=c.query('overview_schools_child',filters=filters,limit=1000,name='school-grade-reference')
 a={r['年级']:r for r in drill['data']};b={r['年级']:r for r in child['data']};assert a.keys()==b.keys()
 for g in a:
  for k in ['工单','现金','人头','工单同比','工单占比','现金占比']:assert a[g][k]==b[g][k]
 passed('原生学校→年级下钻与P2独立子级数据一致')
 for asc in [True,False]:
  d=c.query('overview_schools',filters=[f('期间','FY27'),f('管理单元','市场总计')],limit=5000,order=[['工单同比',asc]],name='null-last-'+str(asc));values=[x['工单同比'] for x in d['data']];null=False
  for v in values:
   if v is None:null=True
   else:assert not null
 passed('学校同比升降序均缺失后置')
 # Scope metadata is checked against real chart IDs used by the running service.
 b=c.b
 # 原生新增展示投影由verify_native单独验证；本段继续检查原始图表集合的既有作用域。
 base_chart_ids={b['charts'][v.key]['id'] for v in VIEWS if v.key in b['charts']}
 def scope(page,name):return [cid for cid in next(f['chartsInScope'] for f in b['pages'][page]['filters'] if f['name']==name) if cid in base_chart_ids]
 charts=b['charts'];ids=lambda keys:{charts[k]['id'] for k in keys}
 assert set(scope('overview','目标团队'))==ids(['overview_targets','overview_abroad_targets'])
 assert not (set(scope('overview','期间')) & ids(['overview_people']))
 assert not (set(scope('capacity','产能月份')) & ids(['capacity_radar','capacity_radar_values','capacity_annual_targets','capacity_annual_products']))
 assert set(scope('online','平台业务线'))==ids(['online_platforms'])
 assert set(scope('online','平台'))==ids(['online_platforms','online_platform_groups'])
 for page,p in b['pages'].items():
  response=c.s.get(c.base+'/api/v1/dashboard/'+str(p['id']));response.raise_for_status();meta=response.json()['result']['json_metadata'];meta=json.loads(meta) if isinstance(meta,str) else meta
  assert meta['cross_filters_enabled'] is False
  assert meta['native_filter_configuration']==p['filters']
  (c.evidence/('metadata-'+page+'.json')).write_text(json.dumps({'dashboard_id':p['id'],'cross_filters_enabled':meta['cross_filters_enabled'],'native_filter_configuration':meta['native_filter_configuration']},ensure_ascii=False,indent=2))
 month_filter=next(item for item in b['pages']['overview']['filters'] if item['name']=='个人月份')
 payload={'datasource':{'id':month_filter['targets'][0]['datasetId'],'type':'table'},'queries':[{'columns':['个人月份'],'metrics':[],'filters':[],'row_limit':100,'time_range':'No filter'}],'force':True,'result_format':'json','result_type':'full'}
 response=c.s.post(c.base+'/api/v1/chart/data',json=payload);response.raise_for_status();month_result=response.json();assert not month_result['result'][0].get('error')
 values={row['个人月份'] for row in month_result['result'][0]['data']};assert len(values)==12 and all(__import__('re').fullmatch(r'\d{4}-\d{2}',value) for value in values)
 (c.evidence/'month-options.json').write_text(json.dumps({'request':payload,'response':month_result},ensure_ascii=False,indent=2))
 passed('个人月份选项仅包含旧版12个月，不混入财年和季度')
 passed('限定团队、独立个人/产能月、年度窗及平台局部筛选作用域')
 no_high=c.query('prep_personal_channels',filters=[f('期间','FY27'),f('业务组',['青少']),f('含删除回收','不含'),f('含死单','包含')],name='hide-highschool-personal');assert not no_high['data'];passed('未选高中时不显示高中留学个人渠道')
 d=c.query('capacity_pending',filters=[f('产能月份','2026-10'),f('线下团队','语培 · 高中')],name='pending-team-empty');assert not d['data'] and 'affected_people' in d['query']
 total=c.query('capacity_pending_count',name='pending-whole-month');assert total['data'][0]['全月待核数']==0
 passed('待核人员明细按团队过滤，全月事件数独立且真实为0')
 c.save(checks)
if __name__=='__main__':main()
