"""仍分离的条线/国家父子表合并；日明细按业务线分区。"""
from copy import deepcopy
from dashboard_product.shadow_bi.p3.catalog import q
from dashboard_product.shadow_bi.p35.breakdown_views import escaped,fmt


def build(base):
    from dashboard_product.shadow_bi.p35.native_catalog import ordered_sql
    result=[]
    for page in ['overview','virtual','university','online']:
        parent=base[page+'_countries'];child=base[page+'_countries_child']
        names=['工单','同期','同比'] if page=='online' else ['合计','线上','线下','待确认']
        def row(alias,label):
            cells=["'<span>'||"+escaped(alias+'.'+q(label))+"||'</span>'"]
            if page=='online':
                for name in names:cells.append("'<span><span>"+('工单同比' if name=='同比' else '工单同期' if name=='同期' else name)+"</span><strong>'||"+fmt('TRY_CAST('+alias+'.'+q(name)+' AS DOUBLE)',name=='同比')+"||'</strong></span>'")
            else:
                for group in [['合计'],['线上','线下'],['待确认']]:
                    parts=[]
                    for name in group:parts.append("'<span>"+name+"工单</span><strong>'||"+fmt('TRY_CAST('+alias+'.'+q(name)+' AS DOUBLE)')+"||'</strong>'")
                    cells.append("'<span>'||"+'||'.join(parts)+"||'</span>'")
            return '||'.join(cells)
        keys=['期间','管理单元','条线'] if page!='online' else ['线上期间','业务线','条线']
        join=' AND '.join('p.'+q(k)+' IS NOT DISTINCT FROM c.'+q(k) for k in keys)
        children="COALESCE((SELECT string_agg('<div>'||"+row('c','国家')+"||'</div>','' ORDER BY c.国家) FROM children c WHERE "+join+"),'')"
        html="'<div><details><summary>'||"+row('p','条线')+"||'</summary>'||"+children+"||'</details></div>'"
        sql='WITH parents AS ('+parent.sql+'), children AS ('+child.sql+') SELECT p.*,'+html+' AS 条线工单 FROM parents p'
        v=deepcopy(parent);v.key='native_'+page+'_country_tree';v.title='留学条线 · 展开国家';v.columns=['条线工单'];v.sql=ordered_sql(sql,{k:q(k) for k in ['条线']+names},names[0]);v.filters.pop('业务线',None);v.filters.update({'排序依据':names[0],'排序方向':'降序'})
        v.more={'query_mode':'raw','all_columns':v.columns,'metrics':[],'groupby':[],'allow_render_html':True,'server_pagination':True,'server_page_length':50,'page_length':50,'include_search':False,'order_by_cols':['["排列顺序", true]']};result.append(v)
    for token,line in [('training','语培'),('abroad','留学及小语种')]:
        source=base['online_daily'];v=deepcopy(source);v.key='native_online_daily_'+token;v.title=line+' · 每日明细';v.sql="SELECT * FROM ("+source.sql+") daily WHERE 业务线='"+line+"'";v.columns=['日期','工单','现金','花费','回收倍数']
        v.more={'query_mode':'raw','all_columns':v.columns,'metrics':[],'groupby':[],'server_pagination':True,'server_page_length':50,'page_length':50,'include_search':False,'order_by_cols':['["日期", false]']};result.append(v)
    return result
