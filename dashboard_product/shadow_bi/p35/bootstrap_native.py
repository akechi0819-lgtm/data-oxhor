"""建立Superset原生团队工作台；不提供替代HTML/前端取数循环。"""
import json,os
from pathlib import Path
from datetime import datetime,UTC
from dashboard_product.shadow_bi.p3.catalog import AUDIT,PAGES,VIEWS,LIBRARY
from dashboard_product.shadow_bi.p35.native_catalog import native_views,numeric_sort_bindings
from dashboard_product.shadow_bi.p35.coverage_note import coverage_note


def percentage_bar_css(charts):
    """原生 Table 默认按列最大值缩放；百分比必须以 1 为满刻度。

    td.title 是 Table 自带的原始数值。typed attr 在单元格上计算后继承给条形，
    保留原生数字、格式和排序。旧浏览器仅显示数字，避免展示错误比例条。
    """
    selectors=[]
    for chart in charts.values():
        params=json.loads(chart.params)
        for index,name in enumerate(params.get('all_columns',[]),1):
            config=params.get('column_config',{}).get(name,{})
            if config.get('showCellBars') and '%' in config.get('d3NumberFormat',''):
                selectors.append(f'.dashboard-chart-id-{chart.id} tbody td:nth-child({index})')
    if not selectors:return ''
    cells=':is('+','.join(selectors)+')'
    return f"""
{cells} > .cell-bar {{ display: none; }}
@supports (width: calc(attr(title type(<number>), 0) * 100%)) {{
  {cells} {{ --percentage-value: attr(title type(<number>), 0); }}
  {cells}[title] > .cell-bar {{
    display: block;
    width: clamp(0%, calc(var(--percentage-value) * 100%), 100%) !important;
    left: 0 !important;
  }}
}}
"""


def configure_window_table(params, columns):
    params['all_columns']=list(columns)
    params.update(server_pagination=False,include_search=False,page_length=0)
    if '时间进度' in columns:
        params.setdefault('column_config',{})['时间进度']={'d3NumberFormat':'.1%','showCellBars':True}


def overview_option_sql():
    # 候选值只读现有维度列；不为加载下拉框展开经营JSON及指标。
    return {
        '期间':"SELECT DISTINCT period_id AS 期间 FROM queries.scoped_team_periods WHERE team_id IN ('total','virtual','online') AND acquisition_scope='被动'",
        '管理单元':"SELECT DISTINCT CASE team_id WHEN 'total' THEN '市场总计' WHEN 'virtual' THEN '线上虚拟人' WHEN 'online' THEN '线上团队' END AS 管理单元 FROM queries.scoped_team_periods WHERE team_id IN ('total','virtual','online')",
        '目标团队':"SELECT unnest(['全部','线上','线下']) AS 目标团队",
    }


def attach_overview_options(filters,database_id,user):
    from superset import db
    from superset.connectors.sqla.models import SqlaTable
    for index,(name,sql) in enumerate(overview_option_sql().items()):
        table='p35_overview_options_'+str(index)
        dataset=db.session.query(SqlaTable).filter_by(table_name=table,database_id=database_id).first() or SqlaTable(table_name=table,database_id=database_id,schema='queries',owners=[user])
        dataset.sql=sql;db.session.add(dataset);db.session.flush()
        if not dataset.columns:dataset.fetch_metadata()
        for item in filters:
            if item['id'].startswith('NATIVE_FILTER-p3-overview-') and item['targets'][0]['column']['name']==name:
                item['targets'][0]['datasetId']=dataset.id


def configure_overview_student_filter(metadata,positions,dashboard,database):
    """Add the student-type selector to existing overview cash and personal charts."""
    from superset import db,security_manager
    from superset.connectors.sqla.models import SqlaTable

    table_name='p35_overview_student_options'
    sql="SELECT unnest(['全部','新生','老生']) AS 新老生"
    dataset=(db.session.query(SqlaTable).filter_by(
        table_name=table_name,database_id=database.id).first()
        or SqlaTable(table_name=table_name,database_id=database.id,schema='queries',
                     owners=list(dashboard.owners)))
    dataset.sql=sql;db.session.add(dataset);db.session.flush()
    if not dataset.columns:dataset.fetch_metadata()

    reader_role=security_manager.find_role('ShadowReaderData')
    if reader_role is None:raise ValueError('市场总览新老生筛选缺少 ShadowReaderData 角色')
    permission=(security_manager.find_permission_view_menu('datasource_access',dataset.perm)
                or security_manager.add_permission_view_menu('datasource_access',dataset.perm))
    security_manager.add_permission_role(reader_role,permission)

    chart_keys={
        'native_overview_training','native_overview_groups',
        'native_overview_cash_lines','native_overview_cash_groups','native_overview_targets',
        'native_overview_grades_training',
        'native_overview_channel_tree_training','overview_people','native_overview_people',
    }
    school_chart_keys=('native_overview_schools_training',)
    contracts={view.key:view for view in [*VIEWS,*native_views()]}
    missing=chart_keys-contracts.keys()
    if missing:raise ValueError('市场总览新老生筛选缺少数据集合同：'+','.join(sorted(missing)))
    names={PAGES.get(contracts[key].page,'市场活动')+' · '+contracts[key].title
           for key in chart_keys}
    school_names={PAGES.get(contracts[key].page,'市场活动')+' · '+contracts[key].title
                  for key in school_chart_keys if key in contracts}
    tables=db.session.query(SqlaTable).filter_by(database_id=database.id).all()
    by_name={table.table_name:table for table in tables}
    missing_names=names-by_name.keys()
    if missing_names:raise ValueError('市场总览新老生筛选缺少数据集：'+','.join(sorted(missing_names)))
    target_ids={by_name[name].id for name in names}
    school_ids={by_name[name].id for name in school_names if name in by_name}
    chart_nodes=[node for node in positions.values()
                 if isinstance(node,dict) and node.get('type')=='CHART']
    active={node['meta']['chartId'] for node in chart_nodes}
    scope={chart.id for chart in dashboard.slices
           if chart.datasource_type=='table' and chart.datasource_id in target_ids|school_ids}&active
    if not scope:raise ValueError('市场总览新老生筛选没有可见目标图表')
    if not any(chart.datasource_type=='table' and chart.datasource_id in school_ids
               and chart.id in active for chart in dashboard.slices):
        raise ValueError('市场总览新老生筛选缺少训练学校图表')
    existing=[item for item in metadata['native_filter_configuration']
              if item.get('id')=='NATIVE_FILTER-p35-overview-student-type']
    if len(existing)>1:raise ValueError('市场总览新老生筛选身份不唯一')
    item={
        'id':'NATIVE_FILTER-p35-overview-student-type','name':'新老生',
        'filterType':'filter_select','type':'NATIVE_FILTER',
        'targets':[{'datasetId':dataset.id,'column':{'name':'新老生'}}],
        'defaultDataMask':{'extraFormData':{'filters':[{'col':'新老生','op':'IN','val':['全部']}]},
                           'filterState':{'value':['全部']}},
        'cascadeParentIds':[],
        'controlValues':{'enableEmptyFilter':False,'multiSelect':False,
                         'searchAllOptions':True,'inverseSelection':False,'defaultToFirstItem':False},
        'chartsInScope':sorted(scope),
        'scope':{'rootPath':['ROOT_ID'],'excluded':sorted(active-scope)},
        'tabsInScope':sorted({tabs[-1] for node in chart_nodes
                              if node['meta']['chartId'] in scope
                              for tabs in [[parent for parent in node.get('parents',[])
                                            if positions.get(parent,{}).get('type')=='TAB']]
                              if tabs}),
        'description':'仅影响市场总览语培现金及个人表现；工单、留学和费用目标保持原口径。',
    }
    filters=metadata['native_filter_configuration']
    if existing:
        filters[filters.index(existing[0])]=item
    else:
        insertion=next((i+1 for i,value in enumerate(filters)
                        if value.get('name')=='语培统计范围'),len(filters))
        filters.insert(insertion,item)
    return dataset


def prep_period_option_sql():
    # 期间选项独立于业务组；下拉框请求不携带经营图表的业务组筛选。
    return "SELECT DISTINCT period_id AS 期间 FROM queries.scoped_selection_team_periods WHERE acquisition_scope='被动'"


def prep_filter_option_sql():
    return {
        '期间':prep_period_option_sql(),
        '月模式':"SELECT unnest(['绩效月','自然月']) AS 月模式",
        '含删除回收':"SELECT unnest(['不含','包含']) AS 含删除回收",
        '含死单':"SELECT unnest(['不含','包含']) AS 含死单",
    }


def attach_prep_filter_options(filters,database_id,user):
    from superset import db,security_manager
    from superset.connectors.sqla.models import SqlaTable
    reader_role=security_manager.find_role('ShadowReaderData')
    for index,(name,sql) in enumerate(prep_filter_option_sql().items()):
        table='p35_prep_period_options' if name=='期间' else 'p35_prep_control_options_'+str(index)
        dataset=db.session.query(SqlaTable).filter_by(table_name=table,database_id=database_id).first() or SqlaTable(table_name=table,database_id=database_id,schema='queries',owners=[user])
        dataset.sql=sql;db.session.add(dataset);db.session.flush()
        if not dataset.columns:dataset.fetch_metadata()
        # 原生筛选请求不带图表ID，沿用阅读角色的逐数据集授权。
        if reader_role:
            permission=security_manager.find_permission_view_menu('datasource_access',dataset.perm) or security_manager.add_permission_view_menu('datasource_access',dataset.perm)
            security_manager.add_permission_role(reader_role,permission)
        for item in filters:
            if item['id'].startswith('NATIVE_FILTER-p3-prep-') and item['targets'][0]['column']['name']==name:
                item['targets'][0]['datasetId']=dataset.id


def main():
    from dashboard_product.shadow_bi.p3 import bootstrap as original
    base=list(VIEWS);extra=native_views();original.VIEWS=base+extra
    sorting={v.key:{k:v.filters.pop(k) for k in ['排序依据','排序方向','学校主被动'] if k in v.filters} for v in extra}
    original.main()
    for v in extra:v.filters.update(sorting[v.key])
    app=original.create_app()
    with app.app_context():
        from superset import db,security_manager
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice
        from superset.connectors.sqla.models import SqlaTable
        receipt=json.loads((AUDIT/'evidence/bootstrap.json').read_text())
        creds=json.loads((AUDIT/'runtime/credentials.json').read_text())
        user=security_manager.find_user(username=creds['username'])
        charts={v.key:db.session.get(Slice,receipt['charts'][v.key]['id']) for v in base+extra if v.page!='activities'}
        # 活动主列表也是原生Table；P1临时投入工具只作为活动页的独立操作。
        dsid=receipt['datasets']['activities'];activity=next(v for v in base if v.key=='activities')
        sl=db.session.query(Slice).filter_by(slice_name='市场活动 · 累计列表').first() or Slice(slice_name='市场活动 · 累计列表',datasource_id=dsid,datasource_type='table',viz_type='table',owners=[user])
        sl.params=json.dumps({'datasource':f'{dsid}__table','viz_type':'table','query_mode':'raw','all_columns':activity.columns,'metrics':[],'groupby':[],'row_limit':1000000,'server_pagination':True,'server_page_length':50,'page_length':50,'include_search':True,'time_range':'No filter','column_config':{'现金':{'d3NumberFormat':',.2f'}},'adhoc_filters':[]});db.session.add(sl);db.session.flush();charts['activities']=sl;receipt['charts']['activities']={'id':sl.id,'dataset':dsid}
        for v in base+extra:
            if v.key not in charts:continue
            if v.key.startswith('native_') and v.key.endswith('_schools'):
                for column in db.session.get(SqlaTable,receipt['datasets'][v.key]).columns:
                    column.groupby=column.column_name in ['业务线','学校','主被动','年级']
            chart=charts[v.key];chart.viz_type=v.viz;params=json.loads(chart.params)
            if v.key=='native_overview_targets':chart.slice_name='业务组目标与完成 · 固定被动'
            if v.key=='native_overview_abroad_targets':chart.slice_name='留学目标与完成' 
            if v.viz=='table':
                if v.key.startswith('native_') and not v.key.endswith('_schools'):
                    params.update(server_pagination=False,include_search=False,page_length=0)
                    params['column_config']={c:{'d3NumberFormat':'+.1%' if '同比' in c else '.1%' if '进度' in c or '占比' in c else ',.2f' if '现金' in c else ',.2~f','showCellBars':'进度' in c,'colorPositiveNegative':'同比' in c} for c in v.columns if c not in ['业务组名称','指标','本期完成','目标与完成率','上年同期','同比变化','人头']}
                    if v.key.endswith('_ssc'):params['column_config']['工单']={'d3NumberFormat':',.0f'}
                    if '被动现金占收入' in v.columns:params['column_config']['被动现金占收入']={'d3NumberFormat':'.1%','showCellBars':True}
                    if numeric_sort_bindings(v):params.update(server_pagination=True,server_page_length=50,page_length=50)
                    if v.key.endswith('_people') or v.key=='native_capacity_month':params.update(v.more)
                else:
                    # 原始诊断列保留在数据集，仅用户可读字段进主表。
                    params['all_columns']=[c for c in v.columns if c not in ['呈现','目标配置','口径','费用说明','费用窗口开始','费用窗口结束','同窗现金','同窗费用','同窗工单','分域人数'] and (not c.endswith('状态') or (v.key=='facts' and c=='工单状态'))]
                    if params.get('query_mode')=='aggregate':
                        params['all_columns']=[]
                        params['metrics']=[m for m in params.get('metrics',[]) if not m.get('label','').endswith('状态') and m.get('label')!='分域人数']
                    params['include_search']=True
                    if '学校表现' in v.columns:params.update(v.more)
                    if v.key.endswith('_people') or v.key in ['capacity_month','capacity_radar_values','capacity_annual_targets']:
                        params.update(all_columns=v.columns,server_pagination=True,server_page_length=50,page_length=50)
            if v.viz=='table':
                params['all_columns']=[c for c in params.get('all_columns',[]) if c not in ['窗口开始','窗口结束','年度开始','年度截止','现金状态','人数状态','语培目标状态','留学目标状态','同期状态','本人工单分母','本人现金','分域人数'] and (not c.endswith('状态') or c=='工单状态')]
                for c in params['all_columns']:
                    if c not in ['学校表现','渠道表现','费用与回收'] and any(x in c for x in ['工单','现金','人头','花费','成本','倍数']) and not any(x in c for x in ['同比','占比','完成率','进度']) and '%' not in params.get('column_config',{}).get(c,{}).get('d3NumberFormat',''):
                        params.setdefault('column_config',{}).setdefault(c,{})['d3NumberFormat']=',.2~f'
                if v.key.endswith('_window'):
                    configure_window_table(params,v.columns)
                if v.more and v.more.get('allow_render_html'):params.update(v.more)
                if v.key.endswith('_personal_channels'):params.update(page_length=50,server_pagination=True,server_page_length=50)
            params['slice_id']=chart.id;chart.params=json.dumps(params,ensure_ascii=False)
        dashboard=db.session.query(Dashboard).filter_by(slug='shadow-bi-native').first() or Dashboard(dashboard_title='市场经营看板',slug='shadow-bi-native',published=True,owners=[user]);db.session.add(dashboard);db.session.flush()
        pos={'DASHBOARD_VERSION_KEY':'v2','ROOT_ID':{'id':'ROOT_ID','type':'ROOT','children':['GRID_ID']},'GRID_ID':{'id':'GRID_ID','type':'GRID','children':['TABS-TEAMS'],'parents':['ROOT_ID']},'HEADER_ID':{'id':'HEADER_ID','type':'HEADER','meta':{'text':'市场经营看板'}},'TABS-TEAMS':{'id':'TABS-TEAMS','type':'TABS','children':[],'parents':['ROOT_ID','GRID_ID'],'meta':{}}}
        used=[];chart_tabs={}
        def row(parent,keys,height=40,widths=None):
            keys=[k for k in keys if k in charts]
            if not keys:return
            rid='ROW-'+parent+'-'+str(len(pos));parents=pos[parent]['parents']+[parent]
            pos[parent]['children'].append(rid);pos[rid]={'id':rid,'type':'ROW','parents':parents,'children':[],'meta':{'background':'BACKGROUND_TRANSPARENT'}}
            for i,key in enumerate(keys):
                chart=charts[key];cid='CHART-'+str(chart.id);pos[rid]['children'].append(cid);pos[cid]={'id':cid,'type':'CHART','children':[],'parents':parents+[rid],'meta':{'chartId':chart.id,'width':widths[i] if widths else 12//len(keys),'height':height,'sliceName':chart.slice_name}}
                used.append(chart);chart_tabs[chart.id]=[x for x in parents if x.startswith('TAB-')]
        def note(parent,text,height=5):
            rid='ROW-NOTE-'+str(len(pos));mid='MARKDOWN-'+str(len(pos));parents=pos[parent]['parents']+[parent]
            pos[parent]['children'].append(rid);pos[rid]={'id':rid,'type':'ROW','parents':parents,'children':[mid],'meta':{'background':'BACKGROUND_TRANSPARENT'}};pos[mid]={'id':mid,'type':'MARKDOWN','parents':parents+[rid],'children':[],'meta':{'code':text,'width':12,'height':height}}
        source_coverage=json.loads((LIBRARY/'library_manifest.json').read_text())['coverage']
        note('GRID_ID',coverage_note(source_coverage),10)
        pos['GRID_ID']['children']=pos['GRID_ID']['children'][1:]+['TABS-TEAMS']
        pages={**PAGES,'activities':'市场活动'}
        # 顺序与旧版一致；团队是原生Tabs，不再跳到另一HTML。
        for page in ['overview','virtual','online','prep','university','capacity','activities']:
            tid='TAB-TEAM-'+page;pos['TABS-TEAMS']['children'].append(tid);parents=['ROOT_ID','GRID_ID','TABS-TEAMS'];pos[tid]={'id':tid,'type':'TAB','parents':parents,'children':[],'meta':{'text':pages[page]}}
            nested='TABS-'+page;pos[tid]['children'].append(nested);pos[nested]={'id':nested,'type':'TABS','parents':parents+[tid],'children':[],'meta':{}}
            specs=[v for v in base if v.page==page]
            if page=='activities':sections={'活动累计':['activities']}
            elif page=='capacity':
                sections={'月度贡献':['native_capacity_month_window','native_capacity_month'],'月度明细':['capacity_month'],'年度六维':['native_capacity_annual_window','capacity_radar','native_capacity_annual_summary','capacity_annual_products'],'年度明细':['capacity_radar_values','capacity_annual_targets'],'待核明细':['capacity_pending_count','capacity_pending','capacity_markers']}
            else:
                sections={}
                if page!='capacity':sections['经营与目标']=[]
                for v in specs:
                    if v.key.endswith('_people'):
                        sections.setdefault('个人表现',[]).extend(['native_'+page+'_people_window','native_'+v.key])
                        sections.setdefault('个人明细',[]).append(v.key);continue
                    if v.key==page+'_countries':
                        sections.setdefault('国家条线',[]).append('native_'+page+'_country_tree');continue
                    if v.key==page+'_countries_child':continue
                    if v.key=='online_daily':
                        sections.setdefault('日趋势与明细',[]).extend(['native_online_daily_training','native_online_daily_abroad']);continue
                    if page=='online' and v.key=='online_platforms':
                        sections.setdefault('平台',[]).extend(['native_online_platform_training','native_online_platform_abroad']);continue
                    if page=='online' and v.key=='online_platform_groups':continue
                    if v.section=='高中留学渠道' and page!='prep':continue
                    if v.key.endswith('_channels_child'):continue
                    if v.key==page+'_channels':
                        sections.setdefault('渠道',[]).extend(['native_'+page+'_channel_tree_training']+([] if page=='prep' else ['native_'+page+'_channel_tree_abroad']));continue
                    if v.key.endswith('_schools_child') or v.section=='明细核对':continue
                    if v.key.endswith('_grades'):
                        sections.setdefault('年级',[]).extend(['native_'+v.key+'_training']+([] if page=='prep' else ['native_'+v.key+'_abroad']));continue
                    if v.key.endswith('_schools'):
                        sections.setdefault('学校',[]).extend(['native_'+v.key] if page=='university' else ['native_'+v.key+'_training']+([] if page=='prep' else ['native_'+v.key+'_abroad']));continue
                    if v.section in ['经营总览','目标进度']:
                        sections.setdefault('现金与进度',[])
                        continue
                    else:name=v.section
                    sections.setdefault(name,[]).append(v.key)
            for idx,(section,keys) in enumerate(sections.items()):
                tab='TAB-'+page+'-'+str(idx);pos[nested]['children'].append(tab);pos[tab]={'id':tab,'type':'TAB','parents':parents+[tid,nested],'children':[],'meta':{'text':section}}
                if section=='经营与目标':
                    row(tab,[f'{page}_window'],20)
                    summaries=[f'native_{page}_{kind}' for kind in ['training','abroad'] if f'native_{page}_{kind}' in charts]
                    row(tab,summaries,26)
                    if page=='online':
                        row(tab,['native_online_roi_tree'],64)
                        row(tab,['native_online_costs'],18)
                        row(tab,['native_online_abroad_annual_goals'],18)
                    row(tab,[f'native_{page}_ssc'],18)
                    if page=='overview':
                        row(tab,['native_overview_abroad_targets'],34)
                        row(tab,['native_overview_targets'],56)
                    else:row(tab,['native_'+page+'_groups'],48)
                elif section=='年度六维':
                    row(tab,['native_capacity_annual_window'],18)
                    row(tab,['capacity_radar','native_capacity_annual_summary'],44,[7,5])
                    row(tab,['capacity_annual_products'],28)
                elif section=='现金与进度':
                    row(tab,[f'native_{page}_cash_lines',f'native_{page}_cash_groups'],40,[6,6])
                    row(tab,['native_'+page+'_groups'],56 if page=='overview' else 48)
                    
                else:
                    if page=='online' and section=='平台':
                        from dashboard_product.shadow_bi.p35.expense_coverage import expense_coverage_note
                        note(tab,expense_coverage_note(LIBRARY,json.loads((LIBRARY/'library_manifest.json').read_text())['batch_id'],AUDIT),12)
                    if page=='activities':note(tab,'活动为历史累计，不随经营期间变化。[填写本次临时投入并计算回收倍数](/p3/activity/)',7)
                    for key in keys:
                        spec=next(v for v in base+extra if v.key==key)
                        height=80 if key.endswith('_country_tree') else 96 if key.startswith('native_online_platform_') else 18 if key.endswith('_window') else 80 if '_channel_tree_' in key else 42 if key=='native_virtual_people' else 58 if key.endswith('_people') or key=='native_capacity_month' else 96 if key.endswith('_schools') else 72 if charts[key].viz_type=='table' and len(spec.columns)>8 else 48 if charts[key].viz_type=='table' else 50
                        row(tab,[key],height)
        allids={s.id for s in used};filters=[]
        for page,p in receipt['pages'].items():
            for item in p['filters']:
                item=json.loads(json.dumps(item));scope=set(item['chartsInScope'])&allids
                # 原生新增图表使用同一筛选合同，不扩大原作用域。
                scope|={charts[v.key].id for v in extra if v.page==page and item['name'] in v.filters}
                if item['defaultDataMask']=={}:
                    name=item['name'];scope|={charts[v.key].id for v in extra if v.page==page and (name in v.columns or (v.key.startswith('native_online_platform_') and name=='平台') or (v.key.endswith('_country_tree') and name=='条线') or (v.key.endswith('_people_window') and name=='人员'))}
                if not scope:continue
                item['chartsInScope']=sorted(scope);item['scope']={'rootPath':['ROOT_ID'],'excluded':sorted(allids-scope)};item['tabsInScope']=sorted({t for cid in scope for t in chart_tabs.get(cid,[])})
                item['description']=item.get('description','') or '仅影响本团队中与此筛选绑定的图表。'
                filters.append(item)
        # 排序选择为有限选项，只作用于当前学校/年级图表。
        for v in extra:
            if v.key=='native_online_platform_abroad':continue
            if not v.key.endswith(('_schools','_grades','_channel_tree','_country_tree')) and v.key!='native_online_platform_training':continue
            scoped_ids={charts[x.key].id for x in extra if (x.key==v.key or x.key in [v.key+'_training',v.key+'_abroad']) and charts[x.key].id in allids}
            if v.key=='native_online_platform_training':scoped_ids={charts['native_online_platform_training'].id,charts['native_online_platform_abroad'].id}
            if not scoped_ids:continue
            if v.key=='native_online_platform_training':
                from dashboard_product.shadow_bi.p35.platform_views import SORTS
                names=SORTS;default='同窗费用'
            elif v.key.endswith('_country_tree'):
                names=['条线','工单','同期','同比'] if v.page=='online' else ['条线','合计','线上','线下','待确认'];default='工单' if v.page=='online' else '合计'
            elif '渠道表现' in v.columns:
                names=['渠道','一级渠道','现金','现金同期','现金同比','现金占比','工单','工单同期','工单同比','工单占比','人头','人头同期','人头同比'];default='工单'
            elif '学校表现' in v.columns:
                names=['学校','业务线','现金','现金同期','现金同比','现金占比','工单','工单同期','工单同比','工单占比','人头','人头同期','人头同比'];default='工单'
            else:names=v.columns;default=v.filters.get('排序依据','工单')
            controls=[('排序依据',names,default),('排序方向',['升序','降序'],v.filters.get('排序方向','降序'))]
            if '学校主被动' in v.filters:controls.insert(0,('学校主被动',['全部','主动','被动'],'全部'))
            for name,values,chosen in controls:
                table_name='p35_sort_'+v.key+'_'+name
                ds=db.session.query(SqlaTable).filter_by(table_name=table_name,database_id=db.session.get(SqlaTable,receipt['datasets'][v.key]).database_id).first() or SqlaTable(table_name=table_name,database_id=db.session.get(SqlaTable,receipt['datasets'][v.key]).database_id,schema='queries',owners=[user])
                ds.sql='SELECT unnest(['+','.join("'"+value+"'" for value in values)+']) AS "'+name+'"';db.session.add(ds);db.session.flush()
                if not ds.columns:ds.fetch_metadata()
                cid=charts[v.key].id
                filters.append({'id':'NATIVE_FILTER-p35-'+v.key+'-'+name,'name':'主被动' if name=='学校主被动' else name,'filterType':'filter_select','type':'NATIVE_FILTER','targets':[{'datasetId':ds.id,'column':{'name':name}}],'defaultDataMask':{'extraFormData':{'filters':[{'col':name,'op':'IN','val':[chosen]}]},'filterState':{'value':[chosen]}},'cascadeParentIds':[],'controlValues':{'enableEmptyFilter':False,'multiSelect':False,'searchAllOptions':True,'inverseSelection':False,'defaultToFirstItem':False},'chartsInScope':sorted(scoped_ids),'scope':{'rootPath':['ROOT_ID'],'excluded':sorted(allids-scoped_ids)},'tabsInScope':chart_tabs[next(iter(scoped_ids))]})
        # 选项取三种范围真实平台和叶子的并集，不用被动广告叶子限制主动范围。
        platform_chart=charts['native_online_platform_training'];platform_ds=db.session.get(SqlaTable,receipt['datasets']['native_online_platform_training'])
        group_ds=db.session.query(SqlaTable).filter_by(table_name='p35_platform_group_options',database_id=platform_ds.database_id).first() or SqlaTable(table_name='p35_platform_group_options',database_id=platform_ds.database_id,schema='queries',owners=[user])
        group_ds.sql="SELECT DISTINCT json_extract_string(g.value,'$.name') AS 平台业务组 FROM queries.scoped_online_platforms p,json_each(p.row_json,'$.groups') g WHERE business_line='training' AND json_extract_string(g.value,'$.name') IS NOT NULL";db.session.add(group_ds);db.session.flush();group_ds.fetch_metadata()
        options_ds=db.session.query(SqlaTable).filter_by(table_name='p35_platform_options',database_id=platform_ds.database_id).first() or SqlaTable(table_name='p35_platform_options',database_id=platform_ds.database_id,schema='queries',owners=[user])
        options_ds.sql="SELECT DISTINCT name AS 平台 FROM queries.scoped_online_platforms";db.session.add(options_ds);db.session.flush();options_ds.fetch_metadata()
        for item in filters:
            if item['name']=='平台':item['targets']=[{'datasetId':options_ds.id,'column':{'name':'平台'}}]
        cid=platform_chart.id
        filters.append({'id':'NATIVE_FILTER-p35-platform-group','name':'平台业务组','filterType':'filter_select','type':'NATIVE_FILTER','targets':[{'datasetId':group_ds.id,'column':{'name':'平台业务组'}}],'defaultDataMask':{},'cascadeParentIds':[],'controlValues':{'enableEmptyFilter':False,'multiSelect':False,'searchAllOptions':True,'inverseSelection':False,'defaultToFirstItem':False},'chartsInScope':[cid],'scope':{'rootPath':['ROOT_ID'],'excluded':sorted(allids-{cid})},'tabsInScope':chart_tabs[cid],'description':'清除回到全部业务组；仅影响语培平台板块。'})
        attach_overview_options(filters,platform_ds.database_id,user)
        attach_prep_filter_options(filters,platform_ds.database_id,user)
        # 每个控件只声明实际子页，不借团队父Tab扩大可见范围。
        priority={name:i for i,name in enumerate(['期间','线上期间','产能月份','个人月份','学校主被动','语培统计范围','管理单元','业务组','业务线','目标团队','平台业务组','平台','学校','人员','六维人员','排序依据','排序方向','条线','平台业务线','产品范围','线下团队','月模式','含删除回收','含死单'])}
        for item in filters:
            item['tabsInScope']=sorted({chart_tabs[cid][-1] for cid in item['chartsInScope'] if chart_tabs.get(cid)})
        filters.sort(key=lambda item:priority.get(item['targets'][0]['column']['name'],99))
        dashboard.slices=list({s.id:s for s in used}.values())
        metadata={'native_filter_configuration':filters,'cross_filters_enabled':False,'filter_bar_orientation':'HORIZONTAL','show_native_filters':True,'refresh_frequency':900}
        configure_overview_student_filter(metadata,pos,dashboard,db.session.get(Database,platform_ds.database_id))
        dashboard.position_json=json.dumps(pos,ensure_ascii=False)
        dashboard.json_metadata=json.dumps(metadata,ensure_ascii=False)
        dashboard.css=percentage_bar_css(charts)+'\n'+Path(__file__).with_name('native_theme.css').read_text().replace('__COMPOSITE_CHART__',':is('+','.join('.dashboard-chart-id-'+str(charts[v.key].id) for v in extra if numeric_sort_bindings(v) and not (v.key.endswith('_people') or v.key=='native_capacity_month'))+')')+'\n'+Path(__file__).with_name('school_tree.css').read_text().replace('__SCHOOL_CHART__',':is('+','.join('.dashboard-chart-id-'+str(charts[v.key].id) for v in extra if '学校表现' in v.columns or '渠道表现' in v.columns or '费用与回收' in v.columns or '平台投入产出' in v.columns or '条线工单' in v.columns)+')')
        personnel_ids=[charts[v.key].id for v in extra if v.key.endswith('_people') or v.key=='native_capacity_month' or v.key.endswith('_window') or v.key in ['native_capacity_annual_summary','capacity_annual_products']]
        dashboard.css+='\n:is('+','.join('.dashboard-chart-id-'+str(i) for i in personnel_ids)+') .dt-select-page-size{display:none;}\n'
        dashboard.css+='\n.dashboard-chart-id-'+str(charts['capacity_annual_products'].id)+' .row:has(>.dt-select-page-size){display:none;}\n'
        db.session.commit()
        proof={'created_at':datetime.now(UTC).isoformat(),'dashboard_id':dashboard.id,'url':os.environ.get('SHADOW_BI_PUBLIC_URL','http://127.0.0.1:18089')+'/superset/dashboard/shadow-bi-native/?standalone=1','datasets':receipt['datasets'],'charts':{k:s.id for k,s in charts.items()},'filters':filters,'position':pos,'extra_views':[v.key for v in extra],'original_views':[v.key for v in base],'visible_chart_keys':[k for k,s in charts.items() if s.id in allids],'school_tree_datasets':[receipt['datasets'][v.key] for v in extra if '学校表现' in v.columns],'numeric_sort_bindings':{str(receipt['datasets'][v.key]):numeric_sort_bindings(v) for v in extra if numeric_sort_bindings(v)}}
        out=AUDIT.parent/'shadow-bi-p35-20261023';out.mkdir(exist_ok=True);(out/'native-bootstrap.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2));print(proof['url'])
if __name__=='__main__':main()
