"""人员原生展示投影：主表聚合同格，完整字段仍由原表明细承载。"""
from dashboard_product.shadow_bi.p3.catalog import View,q


def number(column,percent=False):
    return "COALESCE(format('"+('{:.1f}%' if percent else '{:,.2~f}')+"',"+q(column)+('*100' if percent else '')+"),'—')" if percent else "COALESCE(regexp_replace(format('{:,.2f}',"+q(column)+"),'[.]00$',''),'—')"


def goal(actual,target,completion):
    return number(actual)+"||chr(10)||'目标 '||CASE WHEN "+q(target)+" IS NULL THEN '未配置' ELSE "+number(target)+" END||' · '||"+number(completion,True)


def build(base):
    result=[]
    def add(key,source,title,sql,columns,more=None):
        original=base[source]
        v=View(key,title,sql,columns,original.page,original.section,dict(original.filters))
        v.more={'query_mode':'raw','server_pagination':True,'server_page_length':50,'page_length':50,'include_search':True,'row_limit':1000000,**(more or {})}
        result.append(v);return v
    def window(source,key,title,columns):
        # 聚合在Superset执行：同一窗口只显示一次，人员等筛选仍先作用于原始行。
        groupby=[column for column in columns if column!='时间进度'] if '时间进度' in columns else columns
        metrics=([{'expressionType':'SQL','sqlExpression':'MAX("时间进度")','label':'时间进度','hasCustomLabel':True,'optionName':'time_progress'}] if '时间进度' in columns else [])
        return add(key,source,title,base[source].sql,columns,{'query_mode':'aggregate','groupby':groupby,'metrics':metrics,'all_columns':[],'server_pagination':False,'page_length':0,'include_search':False})
    for page in ['overview','virtual','prep','university']:
        source=page+'_people';sql=base[source].sql
        cells=[q('所属业务组')+"||' · '||"+q('主业务')+' AS 人员归属']
        for name,prefix in [('语培表现','语培'),('留学表现','留学'),('合计表现','合计')]:
            cells.append(goal(prefix+'工单',prefix+'目标',prefix+'完成率')+' AS '+q(name))
        cells.append(goal('现金','现金目标','现金完成率')+' AS 现金表现')
        cells.append('COALESCE(分域人数,'+number('人头')+') AS 人头表现')
        add('native_'+source,source,'个人完成 · 工单与现金','SELECT src.*,'+','.join(cells)+' FROM ('+sql+') src',['人员','人员归属','语培表现','留学表现','合计表现','现金表现','人头表现'])
        window(source,'native_'+page+'_people_window','个人统计区间',['个人月份','月模式','窗口开始','窗口结束','时间进度'])
    source='capacity_month';sql=base[source].sql
    cells=["COALESCE(所属业务组,'—')||' · '||COALESCE(主业务,'—') AS 人员归属"]
    for label,prefix,rate in [('自创表现','自主创造','自创率'),('接收表现','额外接收',None),('输出表现','额外输出',None),('自创合计表现','自创合计',None)]:
        parts=[]
        for unit in ['工单','现金']:
            parts += [("'"+unit+" '||"+number(prefix+unit)+( "||' · 自创率 '||"+number(rate+unit,True) if rate else ''))]
        cells.append("||chr(10)||".join(parts)+' AS '+q(label))
    cells.append("'工单 '||"+goal('本业务合计工单','目标工单','本业务完成率工单')+"||chr(10)||'现金 '||"+goal('本业务合计现金','目标现金','本业务完成率现金')+' AS 本业务表现')
    add('native_capacity_month',source,'月度贡献 · 自创、接收与输出','SELECT src.*,'+','.join(cells)+' FROM ('+sql+') src',['人员','人员归属','自创表现','接收表现','本业务表现','输出表现','自创合计表现','个人待核数'])
    window(source,'native_capacity_month_window','产能统计范围',['产能月份','产品范围'])
    source='capacity_annual_targets';sql=base[source].sql
    rows=[]
    for i,(label,actual,target,completion) in enumerate([('工单','年度工单',None,None),('现金','年度现金','年度现金目标','现金时间进度完成率'),('人头','年度人头',None,None),('转化率','年度转化率',None,None)]):
        display=number(actual,label=='转化率')
        target_text=("'目标 '||"+number(target)+"||' · 时间进度达成 '||"+number(completion,True)) if target else "'—'"
        rows.append('SELECT src.*,\''+label+'\' AS 指标,'+str(i)+' AS 指标顺序,'+display+' AS 本期表现,'+target_text+' AS 目标与进度 FROM ('+sql+') src')
    add('native_capacity_annual_summary',source,'年度业务摘要',' UNION ALL '.join(rows),['指标','本期表现','目标与进度'],{'server_pagination':False,'page_length':0,'include_search':False,'order_by_cols':['["指标顺序", true]']})
    window(source,'native_capacity_annual_window','年度统计范围',['六维人员','所属业务组','主业务','年度开始','年度截止','同组人数'])
    return result
