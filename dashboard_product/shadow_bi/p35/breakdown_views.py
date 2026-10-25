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
        if metric=='现金' and alias=='c':
            share+="||'<span>占本渠道现金 '||"+fmt(alias+'.渠道内现金占比',True)+"||'</span>'"
        parts.append("'<span><span>"+metric+"</span><strong>'||"+value+"||'</strong><span>同期 '||"+fmt(alias+'.'+q(metric+'同期'))+"||' · '||"+fmt(alias+'.'+q(metric+'同比'),True)+"||'</span>'"+share+"||'</span>'")
    return '||'.join(parts)


def channels(page,base):
    source=base[page+'_channels'];child=base[page+'_channels_child']
    join=' AND '.join('p.'+q(k)+' IS NOT DISTINCT FROM c.'+q(k) for k in ['期间','管理单元','业务线','渠道','一级渠道'])
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
