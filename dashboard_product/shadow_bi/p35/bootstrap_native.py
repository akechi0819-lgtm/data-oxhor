"""建立Superset原生团队工作台；不提供替代HTML/前端取数循环。"""
import json
from dashboard_product.shadow_bi.p3.catalog import PAGES,VIEWS
from dashboard_product.shadow_bi.p35.native_catalog import native_views


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
