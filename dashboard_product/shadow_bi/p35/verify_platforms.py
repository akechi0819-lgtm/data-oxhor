"""平台同范围逐数值、实际HTML字段、分组边界、清除与相邻整改回归。"""
import json,math
from pathlib import Path
from xml.etree import ElementTree as ET
from dashboard_product.shadow_bi.p3 import verify_api as api
from dashboard_product.shadow_bi.p3.catalog import ROOT,AUDIT,SOURCE_LIBRARY,SOURCE_BATCH
from data_platform.business_library import execute_library_query,read_library_result
from dashboard_product.shadow_bi.p35.native_catalog import native_views

METRICS=['工单','工单同期','工单同比','工单占比','截止日新增','现金','现金同期','现金同比','花费','同窗费用','同窗收入','回收倍数','单条工单成本','同窗工单']
FEES=['花费','同窗费用','同窗现金','回收倍数','单条工单成本','同窗工单','费用窗口开始','费用窗口结束']


def close(x,y):
    if x is None or y is None:assert x is None and y is None,(x,y)
    else:assert math.isclose(float(x),float(y),rel_tol=1e-10,abs_tol=1e-8),(x,y)


def cell_check(node,row):
    cells=node.findall('span');assert len(cells)==4
    text=[''.join(cell.itertext()) for cell in cells]
    def value(key,pct=False):
        v=row[key]
        return '—' if v is None else format(float(v)*(100 if pct else 1),'.1f' if pct else ',.2f')+('%' if pct else '')
    assert row['平台'] in text[0] or row.get('业务组名称','not-a-child') in text[0]
    assert row['统计业务组'] in text[0] and '本期花费 '+value('花费') in text[0]
    assert cells[1].find('strong').text==value('同窗费用')+' / '+value('同窗收入')
    assert 'ROI '+value('回收倍数')+' · 单条成本 '+value('单条工单成本') in text[1]
    assert cells[2].find('strong').text==value('工单')+' / '+value('现金')
    assert '工单同期 '+value('工单同期')+' · '+value('工单同比',True) in text[2]
    assert '现金同期 '+value('现金同期')+' · '+value('现金同比',True) in text[2]
    assert row['占比分母'] in text[3] and cells[3].find('strong').text==value('工单占比',True)
    assert '截止日新增 '+value('截止日新增') in text[3] and '同窗工单 '+value('同窗工单') in text[3]
    if row['花费'] is None:assert '当前范围无费用口径' in text[1]


def main():
    api.VIEWS+=native_views();c=api.Client();checks=[]
    proof=json.loads((AUDIT.parent/'shadow-bi-p35-20261023/native-bootstrap.json').read_text())
    receipt=execute_library_query(library=SOURCE_LIBRARY,batch_id=SOURCE_BATCH,sql="SELECT row_json FROM queries.advertising_rollup WHERE record_type='leaf' AND business_line='training'",run_id='run_platform_leaf_reference_20261024',output_root=c.evidence/'source',max_rows=5000,max_result_bytes=10000000)
    source_rows=[json.loads(row[0]) for row in read_library_result(receipt,output_root=c.evidence/'source')['rows']]
    raw={(r['period_id'],r['business_group'],r['platform']):r for r in source_rows}
    fields=['平台','业务线','业务组名称','统计业务组','占比分母','平台投入产出']+METRICS+['同窗现金','费用窗口开始','费用窗口结束']
    for period in ['2026-09','2026-10']:
        for scope in ['被动','主动','全部']:
            filters=[api.f('线上期间',period),api.f('语培统计范围',scope)]
            old=c.query('online_platforms',columns=['平台','业务线']+[k for k in METRICS if k!='同窗收入']+['同窗现金','费用窗口开始','费用窗口结束'],filters=filters,limit=1000)['data']
            groups=c.query('online_platform_groups',columns=['平台','业务线','业务组名称','工单','工单同期','现金','现金同期','截止日新增']+FEES,filters=filters,limit=1000)['data']
            for token,line in [('training','语培'),('abroad','留学及小语种')]:
                actual=c.query('native_online_platform_'+token,columns=fields,filters=filters,limit=1000)['data']
                expected={r['平台']:r for r in old if r['业务线']==line};assert len(actual)==len(expected)
                for row in actual:
                    ref=expected[row['平台']]
                    for key in METRICS:
                        if key=='同窗收入':close(row[key],ref['同窗现金'] if ref['费用窗口开始'] and ref['费用窗口结束'] else None)
                        else:close(row[key],ref[key])
                    root=ET.fromstring(row['平台投入产出']);details=root.find('details');node=details.find('summary') if details is not None else root.find('div');cell_check(node,row)
                    if token=='training':
                        children={n.find('span').text:n for n in details.findall('div')}
                        expected_children=[g for g in groups if g['业务线']==line and g['平台']==row['平台']]
                        assert len(children)==len(expected_children)
                        assert set(children)=={r['业务组名称'] for r in expected_children}
                if token=='abroad':
                    leaked=c.query('native_online_platform_abroad',columns=fields,filters=filters+[api.f('平台业务组','留学预备')],limit=1000)['data']
                    key=lambda rows:sorted(json.dumps(r,sort_keys=True,ensure_ascii=False) for r in rows)
                    assert key(actual)==key(leaked)
            for group in ['高中','留学预备','大学']:
                selected=c.query('native_online_platform_training',columns=fields,filters=filters+[api.f('平台业务组',group)],limit=1000)['data']
                expected={g['平台']:g for g in groups if g['业务线']=='语培' and g['业务组名称']==group};assert len(selected)==len(expected)
                denominator=sum(float(g['工单'] or 0) for g in expected.values())
                parent_rows=c.query('native_online_platform_training',columns=fields,filters=filters,limit=1000)['data'];parent_lookup={r['平台']:r for r in parent_rows}
                for row in selected:
                    ref=expected[row['平台']];assert row['业务组名称']==group and row['统计业务组']==group
                    for key in ['工单','现金']+FEES:
                        if key in ['费用窗口开始','费用窗口结束']:assert row[key]==ref[key]
                        else:close(row[key],ref[key])
                    close(row['同窗收入'],ref['同窗现金'] if ref['费用窗口开始'] and ref['费用窗口结束'] else None)
                    leaf=raw.get((period,group,row['平台']))
                    for field,original in [('工单同期','prior_orders'),('现金同期','prior_cash')]:
                        close(row[field],ref[field])
                        if scope=='被动':close(row[field],leaf[original] if leaf else None)
                    close(row['截止日新增'],ref['截止日新增'])
                    if scope=='被动':close(row['截止日新增'],leaf['today_orders'] if leaf and parent_lookup[row['平台']]['截止日新增'] is not None else None)
                    for metric in ['工单','现金']:
                        prior=row[metric+'同期'];close(row[metric+'同比'],row[metric]/prior-1 if prior else None)
                    close(row['工单占比'],float(ref['工单'])/denominator if denominator else None)
                    root=ET.fromstring(row['平台投入产出']);assert root.find('details') is None;cell_check(root.find('div'),row)
                    node=ET.fromstring(parent_lookup[row['平台']]['平台投入产出']).find('details')
                    child=next(n for n in node.findall('div') if n.find('span').text==group);cell_check(child,row)
                checks.append({'period':period,'scope':scope,'group':group,'platforms':len(selected),'status':'passed'})
    # 确定性独立例子，精确锁定组归属与同窗ROI，不能混用全盘小红书费用。
    f=[api.f('线上期间','2026-10'),api.f('语培统计范围','被动'),api.f('平台业务组','留学预备')]
    rows=c.query('native_online_platform_training',columns=fields,filters=f,limit=1000)['data'];x=next(r for r in rows if r['平台']=='小红书');close(x['花费'],10851.64);close(x['同窗收入'],24336.4);close(x['回收倍数'],2.242647194341132)
    d=next(r for r in rows if r['平台']=='抖音');close(d['花费'],9504.65);close(d['回收倍数'],0)
    assert any(r['花费'] is None and r['单条工单成本'] is None for r in rows)
    # 清除组筛选恢复原全体；按每个实际列排序，空值留后。
    from dashboard_product.shadow_bi.p35.platform_views import SORTS
    for name in SORTS:
        for direction in ['升序','降序']:
            data=c.query('native_online_platform_training',columns=[name,'排列顺序'],filters=f+[api.f('排序依据',name),api.f('排序方向',direction)],order=[['排列顺序',True]],limit=1000)['data']
            values=[r[name] for r in data if r[name] is not None];assert values==sorted(values,reverse=direction=='降序'),(name,direction)
    # 保存配置：业务组仅绑定语培平台；期间/平台/排序绑定新板块，不影响其他组图表。
    control=next(x for x in proof['filters'] if x['id']=='NATIVE_FILTER-p35-platform-group')
    assert control['chartsInScope']==[proof['charts']['native_online_platform_training']]
    assert not control['controlValues']['multiSelect'] and not control['controlValues']['enableEmptyFilter'] and control['defaultDataMask']=={}
    visible=set(proof['visible_chart_keys']);assert not visible&{'online_platforms','online_platform_groups','online_daily'}
    for page in ['overview','virtual','university','online']:
        assert page+'_countries' not in visible and page+'_countries_child' not in visible
        names=['工单','同期','同比'] if page=='online' else ['合计','线上','线下','待确认']
        original=c.query(page+'_countries',columns=['条线']+names,limit=1000)['data']
        children=c.query(page+'_countries_child',columns=['条线','国家']+names,limit=1000)['data']
        merged=c.query('native_'+page+'_country_tree',columns=['条线','条线工单']+names,limit=1000)['data']
        assert len(merged)==len(original)
        for row in merged:
            ref=next(r for r in original if r['条线']==row['条线'])
            for name in names:close(row[name],ref[name])
            node=ET.fromstring(row['条线工单']).find('details')
            expected={r['国家']:r for r in children if r['条线']==row['条线']}
            assert len(node.findall('div'))==len(expected)
            def displayed(n,r):
                text=''.join(n.itertext())
                for name in names:
                    v=r[name];s='—' if v is None else format(float(v)*(100 if name=='同比' else 1),'.1f' if name=='同比' else ',.2f')+('%' if name=='同比' else '')
                    assert s in text,(page,name,s,text)
            displayed(node.find('summary'),ref)
            for child in node.findall('div'):displayed(child,expected[child.find('span').text])
        checks.append({'key':page+'-country-parent-child-display','status':'passed'})
    daily_fields=['日期','业务线','工单','现金','花费','回收倍数']
    for period in ['2026-09','2026-10']:
        filters=[api.f('线上期间',period)]
        original=c.query('online_daily',columns=daily_fields,filters=filters,limit=1000)['data']
        for token,line in [('training','语培'),('abroad','留学及小语种')]:
            actual=c.query('native_online_daily_'+token,columns=daily_fields,filters=filters,limit=1000)['data']
            key=lambda rows:sorted(json.dumps(r,sort_keys=True,ensure_ascii=False) for r in rows)
            assert key(actual)==key([r for r in original if r['业务线']==line])
        checks.append({'key':period+'-daily-line-split-source-equality','status':'passed'})
    c.save(checks)

if __name__=='__main__':main()
