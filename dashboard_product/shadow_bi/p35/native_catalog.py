"""原生图表展示投影：仅重排现有指标，业务规则仍归P3查询。"""
from dashboard_product.shadow_bi.p3.catalog import VIEWS,View,q
BASE={v.key:v for v in VIEWS}

def view(key,source,title,sql,columns):
    v=BASE[source]
    return View(key,title,sql,columns,v.page,'经营与目标',dict(v.filters))

def summaries(page):
    source=page+'_lines' if page!='online' else 'online_summary'
    v=BASE[source]
    sql_source=v.sql
    if page=='overview':
        market=BASE['overview_market'].sql
        sql_source="SELECT s.* REPLACE (CASE WHEN s.指标='工单' AND s.业务线='语培' THEN m.目标 ELSE s.目标 END AS 目标, CASE WHEN s.指标='工单' AND s.业务线='语培' THEN m.完成率 ELSE s.完成率 END AS 完成率) FROM ("+v.sql+') s LEFT JOIN ('+market+') m ON s.期间=m.期间 AND s.管理单元=m.管理单元'
    for line,label in [('语培','语培经营'),('留学及小语种','留学及小语种')]:
        if page=='prep' and line!='语培':continue
        # 仅格式化已有值；字符串列用于原生表格同时显示分域人数与缺失说明。
        sql="""SELECT *, CASE 指标 WHEN '工单' THEN 1 WHEN '现金（元）' THEN 2 ELSE 3 END AS 指标顺序,
        COALESCE(呈现,CASE WHEN 指标='现金（元）' THEN format('{:,.2f}',当期) ELSE regexp_replace(format('{:,.2f}',当期),'[.]00$','') END,'—') AS 本期完成,
        CASE WHEN 目标 IS NULL THEN '—' ELSE CASE WHEN 指标='现金（元）' THEN format('{:,.2f}',目标) ELSE format('{:,.0f}',目标) END||' · '||format('{:.1f}%',完成率*100) END AS 目标与完成率,
        COALESCE(CASE WHEN 指标='现金（元）' THEN format('{:,.2f}',同期) ELSE regexp_replace(format('{:,.2f}',同期),'[.]00$','') END,'—') AS 上年同期,
        COALESCE(format('{:+.1f}%',同比*100),'—') AS 同比变化
        FROM ("""+sql_source+") src WHERE 业务线='"+line+"'"
        result=view('native_'+page+'_'+('training' if line=='语培' else 'abroad'),source,label,sql,['指标','本期完成','目标与完成率','上年同期','同比变化'])
        result.more={'order_by_cols':['["指标顺序", true]'],'server_pagination':False,'page_length':0}
        yield result

def compact(source):
    v=BASE[source]
    dims=list(dict.fromkeys([*v.filters,'业务组名称']))
    metrics=[];columns=(['业务线'] if '业务线' in v.filters else [])+['业务组名称']
    for name,metric,field in [('工单完成','工单','当期'),('工单目标','工单','目标'),('工单进度','工单','完成率'),('现金完成（元）','现金（元）','当期'),('现金目标（元）','现金（元）','目标'),('现金进度','现金（元）','完成率'),('人头','人头','当期'),('人头同比','人头','同比')]:
        if name=='人头':
            metrics.append("MAX(CASE WHEN 指标='人头' THEN COALESCE(呈现,format('{:,.0f}',当期),'—') END) AS 人头")
        else:
            metrics.append(f'MAX(CASE WHEN 指标=\'{metric}\' THEN {q(field)} END) AS {q(name)}')
        columns.append(name)
    metrics.append("MAX(CASE WHEN 指标='人头' THEN 当期 END) AS 人头数值")
    if '被动现金占比' in v.columns:
        metrics.extend(['MAX(被动现金占比) AS 被动现金占比','MAX(被动现金分子) AS 被动现金分子','MAX(新生现金固定分母) AS 新生现金固定分母'])
    sql='SELECT '+', '.join([q(d) for d in dims]+metrics)+' FROM ('+v.sql+') src GROUP BY '+', '.join(q(d) for d in dims)
    result=view('native_'+source,source,('固定被动目标 · ' if source=='overview_targets' else '')+v.title+' · 紧凑比较',sql,columns)
    result.sql="SELECT *, CASE 业务组名称 WHEN '留学预备' THEN 1 WHEN '高中' THEN 2 WHEN '大学' THEN 3 ELSE 4 END AS 业务组顺序 FROM ("+result.sql+') ordered'
    # 展示列按业务组聚合；底层数值列仍保留用于查询与核对。
    blocks=[]
    for label,metric in [('工单表现','工单'),('现金表现','现金（元）'),('人头表现','人头')]:
        fmt='{:,.2f}' if metric=='现金（元）' else '{:,.0f}'
        value=lambda field: f"COALESCE(format('{fmt}',MAX(CASE WHEN 指标='{metric}' THEN {q(field)} END)),'—')"
        actual=("COALESCE(MAX(CASE WHEN 指标='人头' THEN 呈现 END),"+value('当期')+")") if metric=='人头' else value('当期')
        yoy=f"COALESCE(format('{{:+.1f}}%',MAX(CASE WHEN 指标='{metric}' THEN 同比 END)*100),'—')"
        text=actual+"||chr(10)||'同期 '"+'||'+value('同期')+"||'  ('||"+yoy+"||')'"
        if metric!='人头':
            progress=f"COALESCE(format('{{:.1f}}%',MAX(CASE WHEN 指标='{metric}' THEN 完成率 END)*100),'—')"
            text+="||chr(10)||'目标 '"+'||'+value('目标')+"||' · '||"+progress+"||chr(10)||'目标差额 '"+'||'+value('目标差额')+"||' · 时间进度差额 '"+'||'+value('时间进度差额')
        blocks.append(text+' AS '+q(label))
    display='SELECT '+', '.join([q(d) for d in dims]+blocks)+' FROM ('+v.sql+') src GROUP BY '+', '.join(q(d) for d in dims)
    result.sql='SELECT n.*, d.工单表现, d.现金表现, d.人头表现 FROM ('+result.sql+') n JOIN ('+display+') d ON '+ ' AND '.join('n.'+q(d)+' IS NOT DISTINCT FROM d.'+q(d) for d in dims)
    result.columns=(['业务线'] if '业务线' in v.filters else [])+['业务组名称','现金表现','工单表现','人头表现']
    if '被动现金占比' in v.columns:
        result.sql='SELECT *,被动现金占比 AS 被动现金占新生收入 FROM ('+result.sql+') share_visible'
        result.columns.append('被动现金占新生收入')
    result.more={'server_pagination':False,'page_length':0,'order_by_cols':['["业务组顺序", true]']}
    return result

def ssc(page):
    if page!='overview':return None
    source=page+'_supplemental'
    if source not in BASE:return None
    v=BASE[source];dims=list(v.filters)
    sql='SELECT '+', '.join([q(k) for k in dims])+", MAX(CASE WHEN 指标='工单' THEN 当期 END) AS 工单, MAX(CASE WHEN 指标='现金（元）' THEN 当期 END) AS \"现金（元）\", MAX(CASE WHEN 指标='人头' THEN COALESCE(呈现,CAST(当期 AS VARCHAR),'—') END) AS 人头 FROM ("+v.sql+") src WHERE 补充范围='SSC' GROUP BY "+', '.join(q(k) for k in dims)
    result=view('native_'+page+'_ssc',source,'SSC · 留学就地摘要',sql,['工单','现金（元）','人头']);result.more={'server_pagination':False,'page_length':0};return result

def native_views():
    result=[]
    for page in ['overview','virtual','prep','university','online']:
        result.extend(summaries(page))
        result.append(compact(page+'_groups'))
        if row:=ssc(page):result.append(row)
    result.append(online_costs())
    result.append(online_annual_goals())
    result.extend(compact(key) for key in ['overview_targets','overview_abroad_targets'])
    result.extend(cash_comparison(page, kind) for page in ['overview','virtual','online','prep','university'] for kind in ['lines','groups'])
    result.extend(grade_view(page) for page in ['overview','virtual','prep','university'])
    result.extend(school_tree(page) for page in ['overview','virtual','prep','university'])
    from dashboard_product.shadow_bi.p35.personnel_views import build
    result.extend(build(BASE))
    from dashboard_product.shadow_bi.p35.breakdown_views import build as build_breakdowns
    result.extend(build_breakdowns(BASE,result))
    from dashboard_product.shadow_bi.p35.platform_views import build as build_platforms
    result.extend(build_platforms(BASE))
    from dashboard_product.shadow_bi.p35.dimension_views import build as build_dimensions
    result.extend(build_dimensions(BASE))
    return result


def school_detail_source(page):
    """沿用已有学校父/年级子值；原生Drill by请求主被动时才展开两个既有范围。"""
    from dashboard_product.shadow_bi.p3.catalog import WIDE_NUM
    selection="""{% set selected = filter_values('语培统计范围', remove_filter=True) %}
{% set acquisition_scope = selected[0] if selected|length == 1 and selected[0] in ['被动','主动','全部'] else '被动' %}
{% set breakdown = '主被动' in (columns|default([], true)) or '主被动' in (groupby|default([], true)) or filter_values('主被动')|length > 0 %}
"""
    if page=='prep':
        selection+="""{% set groups = filter_values('业务组', remove_filter=True) %}
{% set mask = (1 if '青少' in groups else 0) + (2 if '初中' in groups else 0) + (4 if '高中' in groups else 0) %}
"""
        source="SELECT period_id AS 期间, 'prep_high' AS 管理单元, acquisition_scope, unnest(json_extract(row_json,'$.view.teams[*]')) AS v FROM queries.scoped_selection_team_periods WHERE CAST(selection AS INTEGER)={{ mask }}"
    else:
        unit={'overview':"team_id IN ('total','virtual','online')",'virtual':"team_id='virtual'",'university':"team_id='university'"}[page]
        unit_label="CASE team_id WHEN 'total' THEN '市场总计' WHEN 'virtual' THEN '线上虚拟人' WHEN 'online' THEN '线上团队' ELSE team_id END" if page=='overview' else 'team_id'
        source="SELECT period_id AS 期间, "+unit_label+" AS 管理单元, acquisition_scope, view AS v FROM queries.scoped_team_periods WHERE "+unit
    # 先裁剪父JSON，再展开学校；只需schools_by_line，其他团队大字段不进入中间表。
    source=source.replace('view AS v',"json_object('schools_by_line',json_extract(view,'$.schools_by_line')) AS v")
    source+=" AND {% if breakdown %} acquisition_scope IN ('被动','主动') {% else %} acquisition_scope='{{ acquisition_scope }}' {% endif %}"
    # 明确类型一次解码父学校和年级；保留TRY_CAST原有的无效数值转NULL语义。
    import json
    measures={name:{'actual':'DOUBLE','prior':'DOUBLE','yoy':'DOUBLE'} for name in ['orders','cash','heads']}
    measures['heads']['display']='VARCHAR'
    node={'name':'VARCHAR',**measures,'share':'DOUBLE','cash_share':'DOUBLE'}
    structure=json.dumps([{**node,'grades':[node]}],separators=(',',':'))
    fields=['期间','管理单元',"CASE line_key WHEN 'training' THEN '语培' ELSE '留学及小语种' END AS 业务线", "CASE line_key WHEN 'training' THEN acquisition_scope ELSE '不区分' END AS 主被动", "school_node.name AS 学校", "grade_node.name AS 年级", "'{{ acquisition_scope }}' AS 语培统计范围"]
    for name,path in WIDE_NUM.items():
        for prefix,ref in [('父','school_node'),('子','grade_node')]:fields.append('TRY_CAST('+ref+'.'+path+' AS DOUBLE) AS '+q(prefix+name))
    for prefix,ref in [('父','school_node'),('子','grade_node')]:fields.append(ref+'.heads.display AS '+q(prefix+'分域人数'))
    if page=='prep':fields.append('NULL::VARCHAR AS 业务组')
    sql=selection+'WITH b AS ('+source+"), line_keys AS MATERIALIZED (SELECT 期间,管理单元,acquisition_scope,v,unnest(json_keys(json_extract(v,'$.schools_by_line'))) AS line_key FROM b), lines AS MATERIALIZED (SELECT 期间,管理单元,acquisition_scope,line_key,json_transform(json_extract(v,'$.schools_by_line.'||line_key),'"+structure+"') AS school_array FROM line_keys), schools AS MATERIALIZED (SELECT 期间,管理单元,acquisition_scope,line_key,unnest(school_array) AS school_node FROM lines), grades AS (SELECT 期间,管理单元,acquisition_scope,line_key,school_node,unnest(school_node.grades) AS grade_node FROM schools) SELECT "+', '.join(fields)+" FROM grades WHERE (line_key='training' OR NOT {{ breakdown }} OR acquisition_scope='被动')"+(" AND line_key='training'" if page=='prep' else '')
    columns=['业务线','学校']+list(WIDE_NUM)
    metrics=[]
    for name in list(WIDE_NUM)+['分域人数']:
        metrics.append({'expressionType':'SQL','sqlExpression':f'CASE WHEN COUNT(DISTINCT 年级)>1 THEN MAX({q("父"+name)}) ELSE MAX({q("子"+name)}) END','label':name,'hasCustomLabel':True,'optionName':'schooltree_'+name})
    numeric_metrics=metrics
    value=lambda name: next(m['sqlExpression'] for m in numeric_metrics if m['label']==name)
    metrics=[]
    for label,current,prior,yoy in [('现金表现','现金','现金同期','现金同比'),('工单表现','工单','工单同期','工单同比'),('人头表现','人头','人头同期','人头同比')]:
        fmt='{:,.2f}' if current=='现金' else '{:,.0f}'
        actual="COALESCE(format('"+fmt+"',"+value(current)+"),'—')"
        if current=='人头':actual='COALESCE('+value('分域人数')+','+actual+')'
        expr=actual+"||chr(10)||'同期 '||COALESCE(format('"+fmt+"',"+value(prior)+"),'—')||' ('||COALESCE(format('{:+.1f}%',("+value(yoy)+")*100),'—')||')'"
        metrics.append({'expressionType':'SQL','sqlExpression':expr,'label':label,'hasCustomLabel':True,'optionName':'schooltree_'+label})
    result=view('native_'+page+'_schools',page+'_schools','学校表现',sql,columns)
    result.section='学校';result.more={'query_mode':'aggregate','groupby':['业务线','学校'],'all_columns':[],'metrics':metrics,'server_pagination':True,'server_page_length':50,'page_length':50,'include_search':True,'order_by_cols':[],'order_desc':True,'timeseries_limit_metric':numeric_metrics[0]}
    return result


def cash_comparison(page,kind):
    """现金比较使用原生横向分组柱图，同期/目标缺失保持空值。"""
    source=page+'_'+kind if not (page=='online' and kind=='lines') else 'online_summary'
    v=BASE[source]
    label="业务线" if kind=='lines' else "业务组名称"
    sql='SELECT * FROM ('+v.sql+") cash WHERE 指标='现金（元）'"
    if page=='online' and kind=='groups':
        sql="SELECT * REPLACE (业务线||' · '||业务组名称 AS 业务组名称) FROM ("+sql+") separated"
    result=view('native_'+page+'_cash_'+kind,source,'现金 · '+('条线' if kind=='lines' else '业务组')+'本期 / 同期 / 目标',sql,v.columns)
    metrics=[{'expressionType':'SQL','sqlExpression':'MAX('+q(field)+')','label':name,'hasCustomLabel':True,'optionName':'cash_'+field} for name,field in [('本期现金','当期'),('同期现金','同期'),('目标现金','目标')]]
    result.viz='echarts_timeseries_bar'
    result.section='现金与进度'
    result.more={'query_mode':'aggregate','x_axis':label,'groupby':[], 'metrics':metrics,'orientation':'horizontal','stack':None,'show_value':True,'rich_tooltip':True,'tooltipTimeFormat':'smart_date','x_axis_time_format':'smart_date','time_grain_sqla':None,'y_axis_format':',.0f','truncate_metric':False,'legendOrientation':'top','legendType':'plain','color_scheme':'supersetColors','x_axis_title':'','y_axis_title':'元','row_limit':1000,'show_legend':True}
    return result


def online_costs():
    source=BASE['online_summary']
    selection="{% set selected_lines = filter_values('业务线', remove_filter=True) %}"
    sql=selection+"WITH costs AS (SELECT 线上期间, 语培统计范围, 业务线, 花费, 回收倍数, 单条工单成本, 费用窗口开始||' — '||费用窗口结束 AS 费用覆盖 FROM ("+source.sql+") costs WHERE 指标='现金（元）' {% if selected_lines %} AND 业务线 IN {{ selected_lines|where_in }} {% endif %}) SELECT * FROM costs UNION ALL SELECT 线上期间, 语培统计范围, '合计' AS 业务线, SUM(花费), NULL::DOUBLE, NULL::DOUBLE, '各业务线已提供费用' FROM costs GROUP BY 线上期间, 语培统计范围"
    result=view('native_online_costs','online_summary','总花费',"SELECT * FROM ("+sql+") total WHERE 业务线='合计'",['花费'])
    result.more={'server_pagination':False,'page_length':0}
    return result


def online_annual_goals():
    # 独立年度目标条，绝不拿全年分母计算月度完成率。
    source=BASE['overview_abroad_targets']
    sql="SELECT 业务组名称, MAX(CASE WHEN 指标='工单' THEN 目标 END) AS 全年工单目标, MAX(CASE WHEN 指标='现金（元）' THEN 目标 END) AS 全年现金目标 FROM ("+source.sql+") goals WHERE 期间='FY27' AND 管理单元='市场总计' AND 目标团队='全部' AND 业务组名称='线上留学' GROUP BY 业务组名称"
    result=view('native_online_abroad_annual_goals','online_summary','留学及小语种 · FY27 全年目标',sql,['业务组名称','全年工单目标','全年现金目标'])
    result.filters={};result.more={'server_pagination':False,'page_length':0}
    return result


def school_html_sql(sql):
    """在原生Table中分页呈现完整学校树，避免一次挂载全部折叠节点。"""
    def text(node,key):
        value=f"COALESCE(json_extract_string({node},'$.{key}'),'—')"
        for a,b in [('&','&amp;'),('<','&lt;'),('>','&gt;'),('"','&quot;')]:
            value=f"replace({value},'{a}','{b}')"
        return value
    def literal(value):return "'"+value.replace("'","''")+"'"
    def row(node,title,subtitle=None,labels=False):
        parts=[literal('<span>'),text(node,title)]
        if subtitle:parts += [literal('<span>'),text(node,subtitle),literal('</span>')]
        parts += [literal('</span>')]
        for field,label in [('cash','现金（元）'),('orders','工单'),('heads','人头')]:
            parts += [literal('<span>')]
            if labels:parts += [literal('<span>'+label+'</span>')]
            parts += [literal('<strong>'),text(node,field),literal('</strong><span>同期 '),text(node,field+'_prior'),literal(' · '),text(node,field+'_yoy'),literal('</span>')]
            if field!='heads':parts += [literal('<span>占比 '),text(node,field+'_share'),literal('</span>')]
            parts += [literal('</span>')]
        return '||'.join(parts)
    def grades(node):
        # 数组本来已按年级/范围排序；list_transform保留顺序，避免相关json_each
        # 为每个学校重复构造携带整个父JSON的delim join。只改变HTML拼装方式。
        return "COALESCE(array_to_string(list_transform(CAST(json_extract("+node+",'$.grades') AS JSON[]), lambda g: '<div role=\"row\">'||"+row('g','name')+"||'</div>'),''),'')"
    scopes="COALESCE(array_to_string(list_transform(CAST(json_extract(t.学校树,'$.scopes') AS JSON[]), lambda s: '<details><summary>'||"+row('s','name','team_scope')+"||'</summary>'||"+grades('s')+"||'</details>'),''),'')"
    missing="CASE WHEN json_extract_string(t.学校树,'$.missing.name') IS NULL THEN '' ELSE '<details><summary>'||"+row("json_extract(t.学校树,'$.missing')",'name')+"||'</summary>'||"+grades("json_extract(t.学校树,'$.missing')")+"||'</details>' END"
    html="'<div><details><summary>'||"+row('t.学校树','name','line',True)+"||'</summary>'||"+scopes+'||'+missing+"||'</details></div>'"
    return 'SELECT t.*,'+html+' AS 学校表现 FROM ('+sql+') t'


def school_tree(page):
    """原生分页表格中的行内树；节点使用已有父/子值，不按子级加总人数。"""
    if page=='university':return passive_school_ranking()
    source=school_detail_source(page)
    raw=source.sql.replace("{% if breakdown %} acquisition_scope IN ('被动','主动') {% else %} acquisition_scope='{{ acquisition_scope }}' {% endif %}","acquisition_scope IN ('全部','主动','被动')")
    raw=raw.replace("'{{ acquisition_scope }}' AS 语培统计范围", "'{{ acquisition_scope }}' AS 语培统计范围, acquisition_scope AS 节点范围")
    # 在解开学校 JSON 前缩小期间/管理单元，避免把全部历史树都送入模板。
    prefix="{% set periods = filter_values('期间', remove_filter=True) %}{% set chosen_period = periods[0] if periods|length == 1 else 'FY27' %}"
    raw=raw.replace('FROM queries.scoped_team_periods WHERE ',"FROM queries.scoped_team_periods WHERE period_id='{{ chosen_period }}' AND ")
    raw=raw.replace('WHERE CAST(selection AS INTEGER)',"WHERE period_id='{{ chosen_period }}' AND CAST(selection AS INTEGER)")
    if page=='overview':
        prefix+="{% set units = filter_values('管理单元', remove_filter=True) %}{% set unit = units[0] if units|length == 1 else '市场总计' %}{% set unit_id = {'市场总计':'total','线上虚拟人':'virtual','线上团队':'online'}.get(unit,'total') %}"
        raw=raw.replace("team_id IN ('total','virtual','online')","team_id='{{ unit_id }}'")
    if page=='overview':
        raw=raw.replace("team_id='{{ unit_id }}'","team_id='total'")
        raw=raw.replace("filter_values('语培统计范围', remove_filter=True)","filter_values('学校主被动', remove_filter=True)").replace("else '被动' %}","else '全部' %}")
    raw=sort_prefix()+prefix+raw

    def metric(name,node='父'):
        return q(node+name)
    def disp(name,node='父'):
        fmt='{:,.2f}' if name.startswith('现金') and '同比' not in name else '{:,.0f}'
        value="COALESCE(format('"+fmt+"',"+metric(name,node)+"),'—')"
        if name=='人头':value='COALESCE('+metric('分域人数',node)+','+value+')'
        return value
    def cells(node='父'):
        fields=[]
        for label,name in [('cash','现金'),('orders','工单'),('heads','人头')]:
            fields.extend(["'"+label+"',"+disp(name,node),"'"+label+"_prior',"+disp(name+'同期',node),"'"+label+"_yoy',COALESCE(format('{:+.1f}%',"+metric(name+'同比',node)+"*100),'—')"])
        fields.extend(["'cash_share',COALESCE(format('{:.1f}%',"+metric('现金占比',node)+"*100),'—')","'orders_share',COALESCE(format('{:.1f}%',"+metric('工单占比',node)+"*100),'—')"])
        return ','.join(fields)
    # 每个学校/范围父值仅取一次，年级直接读取原子值。
    from dashboard_product.shadow_bi.p3.catalog import WIDE_NUM
    group=['期间','管理单元','业务线','学校','语培统计范围','节点范围']+(['业务组'] if page=='prep' else [])
    agg=[]
    for name in list(WIDE_NUM)+['分域人数']:
        agg.append('CASE WHEN COUNT(DISTINCT 年级)>1 THEN MAX('+q('父'+name)+') ELSE MAX('+q('子'+name)+') END AS '+q('父'+name))
    grade="json_object('name',年级,"+cells('子')+")"
    sql='WITH raw AS ('+raw+'), nodes AS (SELECT '+','.join(q(x) for x in group)+','+','.join(agg)+",to_json(list("+grade+" ORDER BY "+grade_order('年级')+' ASC'+")) AS grades FROM raw GROUP BY "+','.join(q(x) for x in group)+') '
    join=' AND '.join('p.'+q(x)+' IS NOT DISTINCT FROM c.'+q(x) for x in ['期间','管理单元','业务线','学校'])
    scope="json_object('name',CASE WHEN 业务线='语培' THEN 节点范围 ELSE '不区分' END,'team_scope','"+('全盘' if page=='overview' else '当前团队')+"',"+cells()+",'grades',json(grades))"
    sql+=', children AS (SELECT 期间,管理单元,业务线,学校,to_json(list('+scope+" ORDER BY 节点范围) FILTER(WHERE (业务线='语培' AND 节点范围 IN ('主动','被动') AND ('{{ acquisition_scope }}'='全部' OR 节点范围='{{ acquisition_scope }}')) OR (业务线!='语培' AND 节点范围='{{ acquisition_scope }}'))) AS scopes FROM nodes GROUP BY 期间,管理单元,业务线,学校) SELECT p.*,json_object('name',p.学校,'line',p.业务线,'scope',p.语培统计范围,"+cells()+",'scopes',json(c.scopes)) AS 学校树 FROM nodes p JOIN children c ON "+join+" WHERE p.节点范围='{{ acquisition_scope }}'"
    if page!='overview':
        sql=sql.replace(" AND ('{{ acquisition_scope }}'='全部' OR 节点范围='{{ acquisition_scope }}')",'')
        # 归属缺失只单列补证，绝不把学校归属猜成团队归属或并回团队父值。
        missing="""missing_grades AS (
          SELECT f.school_name,COALESCE(f.grade_name,'年级未归属') AS grade_name,
          SUM(CASE WHEN f.event_date BETWEEN p.start_date AND p.through_date THEN f.value ELSE 0 END) AS cash,
          SUM(CASE WHEN f.event_date BETWEEN CAST(p.prior_start_date AS DATE) AND CAST(p.prior_through_date AS DATE) THEN f.value ELSE 0 END) AS prior
          FROM queries.acquisition_facts f JOIN queries.periods p ON p.id='{{ chosen_period }}'
          WHERE f.business_line='training' AND f.acquisition_mode='主动' AND f.metric='cash' AND f.team_id IS NULL
          AND (f.event_date BETWEEN p.start_date AND p.through_date OR f.event_date BETWEEN CAST(p.prior_start_date AS DATE) AND CAST(p.prior_through_date AS DATE))
          GROUP BY f.school_name,f.grade_name), missing AS (
          SELECT school_name,json_object('name','主动 · 团队未归属','cash',format('{:,.2f}',SUM(cash)),'cash_prior',format('{:,.2f}',SUM(prior)),
          'cash_yoy',CASE WHEN SUM(prior)=0 THEN '—' ELSE format('{:+.1f}%',(SUM(cash)/SUM(prior)-1)*100) END,'orders','—','orders_prior','—','orders_yoy','—','heads','—','heads_prior','—','heads_yoy','—',
          'grades',to_json(list(json_object('name',grade_name,'cash',format('{:,.2f}',cash),'cash_prior',format('{:,.2f}',prior),'cash_yoy',CASE WHEN prior=0 THEN '—' ELSE format('{:+.1f}%',(cash/prior-1)*100) END,'orders','—','orders_prior','—','orders_yoy','—','heads','—','heads_prior','—','heads_yoy','—') ORDER BY grade_name))) AS missing_tree
          FROM missing_grades GROUP BY school_name)
        """
        # 同一个WITH串追加补证，再由模板读取额外节点。
        sql=sql.replace('SELECT p.*,json_object(',','+missing+' SELECT p.*,json_object(',1)
        sql=sql.replace("'scopes',json(c.scopes)) AS 学校树", "'scopes',json(c.scopes),'missing',json(m.missing_tree)) AS 学校树")
        sql=sql.replace(" WHERE p.节点范围=", " LEFT JOIN missing m ON p.业务线='语培' AND p.学校=m.school_name WHERE p.节点范围=")
    result=view('native_'+page+'_schools',page+'_schools','学校表现',sql,['业务线','学校','学校树'])
    if page=='overview':
        result.filters.pop('管理单元',None);result.filters.pop('语培统计范围',None)
        result.filters['学校主被动']='全部'
    result.sql=ordered_sql(result.sql,{'学校':'学校','业务线':'业务线',**{k:q('父'+k) for k in WIDE_NUM}},'父工单')
    result.filters.update({'排序依据':'工单','排序方向':'降序'})
    result.sql=school_html_sql(result.sql)
    result.columns=['学校表现']
    result.viz='table';result.section='学校'
    result.more={'query_mode':'raw','groupby':[],'metrics':[],'all_columns':result.columns,'row_limit':1000000,'server_pagination':True,'server_page_length':50,'page_length':50,'include_search':False,'allow_render_html':True,'order_by_cols':['["排列顺序", true]']}
    return result


def grade_order(column):
    groups=[['幼儿园','学龄前','幼儿','幼儿园托班','托班'],['幼儿园小班','小班'],['幼儿园中班','中班'],['幼儿园大班','大班']]
    groups += [[n+'年级',str(i+1)+'年级'] for i,n in enumerate(['一','二','三','四','五','六'])]
    groups += [[n,str(i+7)+'年级（'+n+'）',str(i+7)+'年级('+n+')',cn+'年级'] for i,(n,cn) in enumerate([('初一','七'),('初二','八'),('初三','九')])]
    groups += [[n,str(i+10)+'年级（'+n+'）',str(i+10)+'年级('+n+')',str(i+10)+'年级(国外高中)',str(i+10)+'年级（国外高中）'] for i,n in enumerate(['高一','高二','高三'])]
    groups += [['13年级(国外高中)'],['大一','大学一年级'],['大二','大学二年级'],['大三','大学三年级'],['大四','大学四年级'],['大五'],['研一'],['研二'],['研三'],['研究生以上'],['博一'],['博二'],['博士在读'],['博士毕业'],['大学已毕业','毕业/在职','已毕业在职','在职']]
    return 'CASE '+column+' '+''.join("WHEN '"+name+"' THEN "+str(i)+' ' for i,names in enumerate(groups) for name in names)+"ELSE 999 END"

def sort_prefix():
    return "{% set bases = filter_values('排序依据', remove_filter=True) %}{% set sort_basis = bases[0] if bases|length == 1 else '' %}{% set directions = filter_values('排序方向', remove_filter=True) %}{% set sort_direction = directions[0] if directions|length == 1 else '降序' %}"

def sort_expression(columns,default):
    return ''.join(("{% if" if i==0 else "{% elif")+" sort_basis == '"+name+"' %}"+expr for i,(name,expr) in enumerate(columns.items()))+"{% else %}"+default+"{% endif %} {% if sort_direction == '升序' %} ASC {% else %} DESC {% endif %} NULLS LAST"

def ordered_sql(sql,columns,default):
    return sort_prefix()+"SELECT ordered.*, ROW_NUMBER() OVER (ORDER BY "+sort_expression(columns,default)+") AS 排列顺序 FROM ("+sql+") ordered"

def passive_school_ranking():
    import re
    from dashboard_product.shadow_bi.p3.catalog import WIDE_NUM
    source=BASE['university_schools']
    raw=re.sub(r"{% set acquisition_scope = .*? %}","{% set acquisition_scope = '被动' %}",source.sql,count=1)
    metrics=[m for m in source.more['metrics'] if m['label'] in WIDE_NUM or m['label']=='分域人数']
    sql='SELECT 期间,业务线,学校,'+','.join(m['sqlExpression']+' AS '+q(m['label']) for m in metrics)+' FROM ('+raw+") s WHERE 业务线='语培' GROUP BY 期间,业务线,学校"
    columns=['学校','工单','工单占比','现金','现金占比','工单同期','工单同比','现金同期','现金同比','人头','人头同期','人头同比']
    result=view('native_university_schools','university_schools','学校被动占比排名',ordered_sql(sql,{c:q(c) for c in columns},'工单'),columns)
    result.filters={'期间':'FY27','排序依据':'工单','排序方向':'降序'};result.section='学校'
    result.more={'query_mode':'raw','server_pagination':True,'server_page_length':50,'page_length':50,'include_search':True,'order_by_cols':['["排列顺序", true]']}
    return result

def grade_view(page):
    source=BASE[page+'_grades'];columns=[c for c in source.columns if c not in ['年级顺序','分域人数','人头','人头同期','人头同比'] and not c.endswith('状态')]
    sql='SELECT * REPLACE ('+grade_order('年级')+' AS 年级顺序) FROM ('+source.sql+') g'
    result=view('native_'+page+'_grades',page+'_grades','年级表现',ordered_sql(sql,{c:('年级顺序' if c=='年级' else q(c)) for c in columns},'年级顺序'),columns)
    result.section='年级';result.filters.update({'排序依据':'年级','排序方向':'升序'})
    result.more={'query_mode':'raw','server_pagination':True,'server_page_length':50,'page_length':50,'include_search':True,'order_by_cols':['["排列顺序", true]']}
    return result


def numeric_sort_bindings(v):
    """原生表头展示复合文本，服务端排序读取其首项的原始数值。"""
    candidates={'现金表现':'现金完成（元）','工单表现':'工单完成','人头表现':'人头数值','本期完成':'当期','上年同期':'同期','同比变化':'同比','目标与完成率':'目标'}
    if v.key.endswith('_people'):
        candidates.update({'语培表现':'语培工单','留学表现':'留学工单','合计表现':'合计工单','现金表现':'现金','人头表现':'人头'})
    if v.key=='native_capacity_month':
        candidates.update({'自创表现':'自主创造工单','接收表现':'额外接收工单','本业务表现':'本业务合计工单','输出表现':'额外输出工单','自创合计表现':'自创合计工单'})
    return {label:column for label,column in candidates.items() if label in v.columns}
