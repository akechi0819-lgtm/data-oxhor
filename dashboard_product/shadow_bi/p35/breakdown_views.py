"""原生表内渠道与费用展开；只投影已提供的父子指标，不分摊未知费用。"""
from copy import deepcopy
from dashboard_product.shadow_bi.p3.catalog import q


def escaped(expr):
    value="COALESCE(CAST("+expr+" AS VARCHAR),'—')"
    for a,b in [('&','&amp;'),('<','&lt;'),('>','&gt;'),('"','&quot;')]:
        value=f"replace({value},'{a}','{b}')"
    return value


def fmt(expr,percent=False):
    return "COALESCE(format('"+('{:.1f}%' if percent else '{:,.2f}')+"',"+expr+('*100' if percent else '')+"),'—')"


def channel_row(alias,label):
    parts=["'<span>'||"+escaped(alias+'.'+q(label))+"||'</span>'"]
    if label=='渠道':parts[0]="'<span>'||"+escaped(alias+'.渠道')+"||'<span>'||"+escaped(alias+'.一级渠道')+"||'</span></span>'"
    for metric in ['现金','工单','人头']:
        value=fmt(alias+'.'+q(metric))
        if metric!='现金':value="regexp_replace("+value+",'[.]00$','')"
        if metric=='人头':value='COALESCE('+alias+'.分域人数,'+value+')'
        share=''
        if metric in ['现金','工单']:
            share="||'<span>占本业务线"+metric+" '||"+fmt(alias+'.'+q(metric+'占比'),True)+"||'</span>'"
        if metric=='现金' and alias in ('c','g','s'):
            share+="||'<span>占本渠道现金 '||"+fmt(alias+'.渠道内现金占比',True)+"||'</span>'"
        parts.append("'<span><span>"+metric+"</span><strong>'||"+value+"||'</strong><span>同期 '||"+fmt(alias+'.'+q(metric+'同期'))+"||' · '||"+fmt(alias+'.'+q(metric+'同比'),True)+"||'</span>'"+share+"||'</span>'")
    return '||'.join(parts)


def channels(page,base):
    source=base[page+'_channels'];child=base[page+'_channels_child']
    parent_keys=['期间','管理单元','业务线','渠道','一级渠道']
    if page=='university':
        from dashboard_product.shadow_bi.p3 import catalog as p3

        period_selection="{% set periods = filter_values('期间', remove_filter=True) %}"
        period_clause=" {% if periods %} AND period_id IN {{ periods|where_in }} {% endif %}"
        select_periods=lambda sql: sql.replace(
            "WHERE team_id='university'",
            "WHERE team_id='university'"+period_clause,
        )
        join=' AND '.join('p.'+q(k)+' IS NOT DISTINCT FROM g.'+q(k) for k in parent_keys)
        group_keys=' AND '.join('g.'+q(k)+' IS NOT DISTINCT FROM s.'+q(k) for k in parent_keys+['业务组名称'])
        school_rows="COALESCE((SELECT string_agg('<div role=\"row\">'||"+channel_row('s','学校名称')+"||'</div>','' ORDER BY s.工单 DESC NULLS LAST, s.现金 DESC NULLS LAST, s.学校名称) FROM schools s WHERE "+group_keys+"),'')"
        attribute_order="CASE g.业务组名称 WHEN '大学*' THEN 1 WHEN '本地大学' THEN 2 WHEN '归巢大学' THEN 3 WHEN '国外大学' THEN 4 WHEN '毕业及其他' THEN 5 ELSE 6 END"
        group_rows=("COALESCE((SELECT string_agg('<details><summary>'||"+channel_row('g','业务组名称')+
                     "||'</summary>'||"+school_rows+"||'</details>','' ORDER BY "+attribute_order+") "
                     "FROM groups g WHERE "+join+"),'')")
        html="'<div class=\"university-channel-tree\"><details><summary>'||"+channel_row('p','渠道')+"||'</summary>'||"+group_rows+"||'</details></div>'"
        acquisition_scope=("{% set acquisition = filter_values('语培统计范围', remove_filter=True) %}"
                           "{% set acquisition_scope = acquisition[0] if acquisition|length == 1 and acquisition[0] in ['被动','主动','全部'] else '被动' %}")
        scoped_cte=select_periods(p3.cte('university').replace(
            'queries.team_periods',
            "(SELECT * FROM queries.scoped_team_periods WHERE acquisition_scope='{{ acquisition_scope }}') team_periods",
        ))
        school_columns=[
            q('期间'),q('管理单元'),
            p3.col(p3.line(p3.txt('e.value','business_line')),'业务线'),
            p3.col(p3.txt('e.value','name'),'渠道'),
            p3.col(p3.txt('e.value','first_channel'),'一级渠道'),
            p3.col(p3.txt('g.value','name'),'业务组名称'),
            p3.col(p3.txt('s.value','name'),'学校名称'),
            p3.col("'{{ acquisition_scope }}'",'语培统计范围'),
        ]
        school_columns.extend(p3.col(p3.num('s.value',path),name) for name,path in p3.WIDE_NUM.items())
        school_columns.extend(
            p3.col(p3.status(p3.txt('s.value',path)) if name.endswith('状态') else p3.txt('s.value',path),name)
            for name,path in p3.WIDE_TEXT.items()
        )
        school_columns.append(p3.col(p3.num('s.value','channel_cash_share'),'渠道内现金占比'))
        schools_sql=(acquisition_scope+scoped_cte+"SELECT "+', '.join(school_columns)+
                     " FROM b, json_each(b.v, '$.channels') e, json_each(e.value, '$.groups') g, json_each(g.value, '$.schools') s")
        v=deepcopy(source);v.key='native_'+page+'_channel_tree';v.title='渠道 · 展开学校属性与学校';v.columns=['渠道表现']
        v.sql=(period_selection+'WITH parents AS ('+select_periods(source.sql)+'), groups AS ('+
               select_periods(child.sql)+'), schools AS ('+schools_sql+') SELECT p.*,'+html+
               ' AS 渠道表现 FROM parents p')
    else:
        join=' AND '.join('p.'+q(k)+' IS NOT DISTINCT FROM c.'+q(k) for k in parent_keys)
        child_html="COALESCE((SELECT string_agg('<div role=\"row\">'||"+channel_row('c','业务组名称')+"||'</div>','' ORDER BY c.工单 DESC NULLS LAST) FROM children c WHERE "+join+"),'')"
        html="'<div><details><summary>'||"+channel_row('p','渠道')+"||'</summary>'||"+child_html+"||'</details></div>'"
        v=deepcopy(source);v.key='native_'+page+'_channel_tree';v.title='渠道 · 展开业务组';v.columns=['渠道表现'];v.sql='WITH parents AS ('+source.sql+'), children AS ('+child.sql+') SELECT p.*,'+html+' AS 渠道表现 FROM parents p'
    from dashboard_product.shadow_bi.p35.native_catalog import ordered_sql
    v.sql=ordered_sql(v.sql,{k:q(k) for k in ['渠道','一级渠道','工单','工单同期','工单同比','现金','现金同期','现金同比','现金占比','工单占比','人头','人头同期','人头同比']},'工单')
    v.filters.update({'排序依据':'工单','排序方向':'降序'})
    v.more={'query_mode':'raw','all_columns':v.columns,'metrics':[],'groupby':[],'allow_render_html':True,'server_pagination':True,'server_page_length':50,'page_length':50,'include_search':False,'order_by_cols':['["排列顺序", true]']}
    return v


def roi(base):
    parent=base['online_summary'];child=base['online_groups']
    def row(a,label):
        return "'<span>'||"+escaped(a+'.'+q(label))+"||'</span><span><span>花费</span><strong>'||"+fmt(a+'.花费')+"||'</strong></span><span><span>回收倍数</span><strong>'||"+fmt(a+'.回收倍数')+"||'</strong></span><span><span>单条工单成本</span><strong>'||"+fmt(a+'.单条工单成本')+"||'</strong></span>'"
    children="COALESCE((SELECT string_agg('<div role=\"row\">'||"+row('c','业务组名称')+"||'</div>','' ORDER BY c.业务组名称) FROM children c WHERE c.线上期间=p.线上期间 AND c.业务线=p.业务线),'')"
    abroad_children="COALESCE((SELECT string_agg('<div role=\"row\"><span>'||"+escaped('a.条线')+"||'</span><span><span>本期工单</span><strong>'||"+fmt('a.工单')+"||'</strong></span><span>费用未按条线提供</span><span>ROI 未计算</span></div>','' ORDER BY a.条线) FROM countries a WHERE a.线上期间=p.线上期间 AND a.业务线='留学及小语种'),'')"
    html="'<div><details><summary>'||"+row('p','业务线')+"||'</summary>'||CASE WHEN p.业务线='语培' THEN "+children+" ELSE "+abroad_children+" END||'</details></div>'"
    v=deepcopy(parent);v.key='native_online_roi_tree';v.title='总花费与回收 · 展开业务组';v.columns=['费用与回收'];v.sql="WITH parents AS (SELECT * FROM ("+parent.sql+") s WHERE 指标='现金（元）'), children AS (SELECT * FROM ("+child.sql+") s WHERE 指标='现金（元）'), countries AS ("+base['online_countries'].sql+") SELECT p.*,"+html+' AS 费用与回收 FROM parents p'
    v.more={'query_mode':'raw','all_columns':v.columns,'metrics':[],'groupby':[],'allow_render_html':True,'server_pagination':False,'page_length':0,'include_search':False,'order_by_cols':['["业务线", false]']}
    return v


def build(base,views):
    result=[channels(p,base) for p in ['overview','virtual','prep','university']]+[roi(base)]
    for v in list(views)+list(result):
        if not (v.key.endswith(('_schools','_grades','_channel_tree'))):continue
        if v.key=='native_university_schools':continue
        for token,line in [('training','语培'),('abroad','留学及小语种')]:
            if v.page=='prep' and token=='abroad':continue
            clone=deepcopy(v);clone.key=v.key+'_'+token;clone.title=line+' · '+v.title
            inner=v.sql
            if v.key.endswith('_schools'):
                # 固定业务线在学校数组展开前生效；两个独立板子不重复展开另一条线。
                operator='=' if token=='training' else '<>'
                inner=inner.replace('FROM line_keys), schools AS',"FROM line_keys WHERE line_key"+operator+"'training'), schools AS")
            clone.sql='SELECT * FROM ('+inner+') partitioned WHERE 业务线=\''+line+"'";clone.filters.pop('业务线',None)
            result.append(clone)
    return result
