"""平台父子表的原生紧凑投影；分组选择直接读取相应叶子，不混用全盘费用。"""
from copy import deepcopy
from dashboard_product.shadow_bi.p3.catalog import q
from dashboard_product.shadow_bi.p35.breakdown_views import escaped,fmt

SORTS=['平台','花费','同窗费用','同窗收入','回收倍数','单条工单成本','工单','工单同期','工单同比','工单占比','截止日新增','现金','现金同期','现金同比']
GROUP_SELECTION="""{% set platform_groups = filter_values('平台业务组', remove_filter=True) %}
{% set chosen_group = platform_groups[0] if platform_groups|length == 1 else '' %}
"""


def display(alias,child=False):
    f=lambda name:alias+'.'+q(name)
    value=lambda name:fmt('TRY_CAST('+f(name)+' AS DOUBLE)')
    percent=lambda name:fmt('TRY_CAST('+f(name)+' AS DOUBLE)',True)
    label='业务组名称' if child else '平台'
    lead="'<span>'||"+escaped(f(label))+"||'<span>'||"+escaped(f('统计业务组'))+"||'</span><span>本期花费 '||"+value('花费')+"||'</span></span>'"
    investment="'<span><span>同窗投入 / 收入（元）</span><strong>'||"+value('同窗费用')+"||' / '||"+value('同窗收入')+"||'</strong><span>ROI '||"+value('回收倍数')+"||' · 单条成本 '||"+value('单条工单成本')+"||'</span>'||CASE WHEN "+f('花费')+" IS NULL THEN '<span>当前范围无费用口径</span>' ELSE '' END||'</span>'"
    operation="'<span><span>本期工单 / 现金（元）</span><strong>'||"+value('工单')+"||' / '||"+value('现金')+"||'</strong><span>工单同期 '||"+value('工单同期')+"||' · '||"+percent('工单同比')+"||'</span><span>现金同期 '||"+value('现金同期')+"||' · '||"+percent('现金同比')+"||'</span></span>'"
    share="'<span><span>'||"+escaped(f('占比分母'))+"||'</span><strong>'||"+percent('工单占比')+"||'</strong><span>截止日新增 '||"+value('截止日新增')+"||'</span><span>同窗工单 '||"+value('同窗工单')+"||'</span></span>'"
    return '||'.join([lead,investment,operation,share])


def build(base):
    from dashboard_product.shadow_bi.p35.native_catalog import ordered_sql
    result=[]
    for token,line in [('training','语培'),('abroad','留学及小语种')]:
        parent=base['online_platforms'];child=base['online_platform_groups']
        # 每个范围直接消费自身平台叶子；不再从被动费用表补主动/全部的同期。
        leaves="SELECT g.*,CASE WHEN 工单同期<>0 THEN 工单/工单同期-1 END AS 工单同比,CASE WHEN 现金同期<>0 THEN 现金/现金同期-1 END AS 现金同比,工单/NULLIF(SUM(工单) OVER(PARTITION BY 线上期间,业务线,业务组名称),0) AS 工单占比,业务组名称 AS 统计业务组,'占本业务组工单' AS 占比分母,CASE WHEN 费用窗口开始 IS NOT NULL AND 费用窗口结束 IS NOT NULL THEN 同窗现金 END AS 同窗收入 FROM groups_source g"
        fields=['线上期间','业务线','语培统计范围','平台','工单','工单同期','工单同比','工单占比','截止日新增','现金','现金同期','现金同比','花费','费用状态','回收倍数','单条工单成本','同窗现金','同窗费用','同窗工单','费用窗口开始','费用窗口结束','费用说明']
        text_fields={'线上期间','业务线','语培统计范围','平台','费用状态','费用窗口开始','费用窗口结束','费用说明'}
        projection=lambda alias:','.join(alias+'.'+q(k) if k in text_fields else 'TRY_CAST('+alias+'.'+q(k)+' AS DOUBLE) AS '+q(k) for k in fields)
        parent_rows="SELECT "+projection('p')+",NULL::VARCHAR AS 业务组名称,'全部业务组' AS 统计业务组,'占本业务线工单' AS 占比分母,CASE WHEN 费用窗口开始 IS NOT NULL AND 费用窗口结束 IS NOT NULL THEN 同窗现金 END AS 同窗收入 FROM parents p"
        selected="SELECT "+projection('g')+",业务组名称,统计业务组,占比分母,同窗收入 FROM leaves g WHERE 业务组名称='{{ chosen_group|replace(\"'\",\"''\") }}'"
        selection=("{% if chosen_group %}"+selected+"{% else %}"+parent_rows+"{% endif %}") if token=='training' else parent_rows
        cte=GROUP_SELECTION+"WITH parents AS ("+parent.sql+"), groups_source AS ("+child.sql+"), leaves AS ("+leaves+"), picked AS ("+selection+") "
        children="COALESCE((SELECT string_agg('<div>'||"+display('g',True)+"||'</div>','' ORDER BY g.业务组名称) FROM leaves g WHERE g.线上期间=p.线上期间 AND g.业务线=p.业务线 AND g.平台=p.平台),'')"
        root=display('p')
        if token=='training':html="CASE WHEN '{{ chosen_group|replace(\"'\",\"''\") }}'='' THEN '<div><details><summary>'||"+root+"||'</summary>'||"+children+"||'</details></div>' ELSE '<div><div>'||"+root+"||'</div></div>' END"
        else:html="'<div><div>'||"+root+"||'</div></div>'"
        sql=cte+'SELECT p.*,'+html+" AS 平台投入产出 FROM picked p WHERE 业务线='"+line+"'"
        v=deepcopy(parent);v.key='native_online_platform_'+token;v.title=line+' · 平台投入产出';v.sql=ordered_sql(sql,{k:q(k) for k in SORTS},'同窗费用');v.columns=['平台投入产出'];v.section='平台';v.filters={'线上期间':'2026-10','排序依据':'同窗费用','排序方向':'降序'}
        if token=='training':v.filters['语培统计范围']='被动'
        v.more={'query_mode':'raw','all_columns':v.columns,'metrics':[],'groupby':[],'allow_render_html':True,'server_pagination':True,'server_page_length':50,'page_length':50,'include_search':False,'order_by_cols':['["排列顺序", true]']}
        result.append(v)
    return result
