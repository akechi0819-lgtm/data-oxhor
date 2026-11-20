"""原生展示投影、原始数据及限定筛选的真实API回归。"""
import json,math
from dashboard_product.shadow_bi.p3 import verify_api
from dashboard_product.shadow_bi.p3.catalog import VIEWS,AUDIT,ROOT
from dashboard_product.shadow_bi.p35.native_catalog import native_views,BASE

def main():
    extra=native_views();verify_api.VIEWS=list(VIEWS)+extra;c=verify_api.Client();checks=[]
    for v in extra:
        columns=None if v.more and v.more.get('query_mode')=='aggregate' else ['业务线','学校','学校树'] if '学校表现' in v.columns else v.columns
        if '_cash_' not in v.key and v.key.endswith(('_groups','_targets')):columns=list(dict.fromkeys(v.columns+['工单完成','工单目标','工单进度','现金完成（元）','现金目标（元）','现金进度','人头','人头同比']))
        result=c.query(v.key,columns=columns,limit=1000,name=v.key)['data']
        assert result or v.key not in ['native_overview_training','native_overview_targets','native_overview_ssc']
        if '_cash_' not in v.key and v.key.endswith(('_groups','_targets')):
            source_key=v.key.removeprefix('native_');source=BASE[source_key]
            columns=source.columns+(['业务线'] if '业务线' in source.filters and '业务线' not in source.columns else [])
            original=c.query(source_key,columns=columns,limit=1000,name=v.key+'-original')['data']
            for row in result:
                group=[r for r in original if r['业务组名称']==row['业务组名称'] and ('业务线' not in row or r['业务线']==row['业务线'])]
                assert len({r['指标'] for r in group})==len(group),(v.key,row)
                for name,metric,field in [('工单完成','工单','当期'),('工单目标','工单','目标'),('工单进度','工单','完成率'),('现金完成（元）','现金（元）','当期'),('现金目标（元）','现金（元）','目标'),('现金进度','现金（元）','完成率'),('人头同比','人头','同比')]:
                    expected=next(r for r in group if r['指标']==metric)[field]
                    assert row[name]==expected or (row[name] is not None and expected is not None and math.isclose(row[name],expected,abs_tol=1e-8)),(v.key,name,row[name],expected)
                heads=next(r for r in group if r['指标']=='人头');expected=heads['呈现'] or (f"{heads['当期']:,.0f}" if heads['当期'] is not None else '—');assert row['人头']==expected
        checks.append({'key':v.key,'status':'passed','rows':len(result)})
    passive=c.query('native_overview_training',columns=next(v.columns for v in extra if v.key=='native_overview_training'),limit=10)['data']
    assert next(r for r in passive if r['指标']=='工单')['目标与完成率'].startswith('20,456')
    for scope in ['主动','全部']:
        d=c.query('native_overview_training',columns=next(v.columns for v in extra if v.key=='native_overview_training'),filters=[verify_api.f('期间','FY27'),verify_api.f('管理单元','市场总计'),verify_api.f('语培统计范围',scope)],limit=10,name='native-summary-'+scope)['data']
        assert all(r['目标与完成率']=='—' for r in d)
    meta=json.loads((AUDIT.parent/'shadow-bi-p35-20261023/native-bootstrap.json').read_text());ids=set(meta['charts'].values());positions=meta['position'];filters=meta['filters']
    assert len(positions['TABS-TEAMS']['children'])==7
    for page,p in c.b['pages'].items():
        for f in p['filters']:
            visible=set(meta['visible_chart_keys'])
            baseids={meta['charts'][v.key] for v in VIEWS if v.key in visible}
            base_scope=set(f['chartsInScope'])&baseids
            actual=next((x for x in filters if x['id']==f['id']),None)
            if actual is None:
                assert not base_scope and not any(v.page==page and f['name'] in v.filters for v in extra),(page,f['name'])
                continue
            assert set(actual['chartsInScope'])&baseids==base_scope
            assert not set(actual['chartsInScope'])&set(actual['scope']['excluded'])
    from dashboard_product.shadow_bi.p3.catalog import WIDE_NUM
    for page in ['overview','virtual','prep']:
        original=BASE[page+'_schools'];metrics=[m for m in original.more['metrics'] if m['label'] in WIDE_NUM]
        trees=c.query('native_'+page+'_schools',columns=['学校树'],limit=20000,name=page+'-inline-tree')['data']
        trees=[json.loads(row['学校树']) for row in trees]
        assert trees and all(t['scopes'] for t in trees)
        for scope in ['被动','主动']:
            filters=[verify_api.f(k,scope if k=='语培统计范围' else val) for k,val in original.filters.items()]
            expected=c.query(original.key,filters=filters,metrics=metrics,limit=20000,name=page+'-original-'+scope)['data']
            lookup={(r['业务线'],r['学校']):r for r in expected}
            for tree in trees:
                if tree['line']!='语培':continue
                assert {row['name'] for row in tree['scopes']} <= {'主动','被动'}
                row=next((row for row in tree['scopes'] if row['name']==scope),None)
                ref=lookup.get((tree['line'],tree['name']))
                if row is None:
                    assert ref is None or ref['现金']==0 and ref['工单']==0
                    continue
                # 无该分支的旧学校记录保留空分支，不虚构数字。
                if ref is None:continue
                assert row['cash']==('—' if ref['现金'] is None else f"{ref['现金']:,.2f}"),(page,scope,tree['name'],row,ref)
                assert row['orders']==('—' if ref['工单'] is None else f"{ref['工单']:,.0f}")
                assert isinstance(row['grades'],list)
        checks.append({'key':page+'-inline-school-source-equality','status':'passed','schools':len(trees)})
    uni=next(v for v in extra if v.key=='native_university_schools')
    defaults=[verify_api.f(k,v) for k,v in uni.filters.items()]
    baseline=c.query(uni.key,limit=20000)['data']
    active=c.query(uni.key,filters=defaults+[verify_api.f('语培统计范围','主动')],limit=20000,name='university-still-passive')['data']
    assert {r['学校']:r for r in baseline}=={r['学校']:r for r in active}
    assert next(r for r in baseline if r['学校']=='南开大学')['现金']==266520
    overview=[json.loads(r['学校树']) for r in c.query('native_overview_schools',columns=['学校树'],limit=20000)['data']]
    nankai=next(t for t in overview if t['name']=='南开大学' and t['line']=='语培')
    assert nankai['cash']=='521,911.30'
    assert {r['name']:r['cash'] for r in nankai['scopes']}=={'主动':'172,491.30','被动':'349,420.00'}
    assert all('明细核对'!=p.get('meta',{}).get('text') for p in positions.values() if isinstance(p,dict))
    checks.append({'key':'school_placement_passive_team_and_global_tree','status':'passed'})
    for key in ['native_university_schools','native_overview_grades','native_overview_schools']:
        spec=next(v for v in extra if v.key==key)
        names=(['学校','业务线','现金','现金同期','现金同比','现金占比','工单','工单同期','工单同比','工单占比','人头','人头同期','人头同比'] if '学校表现' in spec.columns else spec.columns)
        for name in names:
            column='父'+name if '学校表现' in spec.columns and name not in ['学校','业务线'] else '年级顺序' if name=='年级' else name
            for direction in ['升序','降序']:
                filters=[verify_api.f(k,v) for k,v in spec.filters.items() if k not in ['排序依据','排序方向']]+[verify_api.f('排序依据',name),verify_api.f('排序方向',direction)]
                saved=json.loads(c.s.get(c.base+'/api/v1/chart/'+str(c.b['charts'][key]['id'])).json()['result']['params'])
                data=c.query(key,columns=list(dict.fromkeys([column,'排列顺序'])),filters=filters,order=[json.loads(x) for x in saved.get('order_by_cols',[])],limit=20000,name=key+'-'+name+'-'+direction)['data']
                values=[r[column] for r in data if r[column] is not None]
                # 中文文本由 DuckDB 排序；这里只对数值与自然年级序断言单调。
                if values:
                    assert values==sorted(values,reverse=direction=='降序'),(key,name,direction,values[:10])
        checks.append({'key':key+'-all-visible-columns-sort-both-directions','status':'passed','columns':len(names)})
    costs=c.query('native_online_costs',columns=['业务线','花费','回收倍数','单条工单成本'])['data'];parts=c.query('native_online_roi_tree',columns=['业务线','花费'])['data'];total=next(r for r in costs if r['业务线']=='合计')
    assert math.isclose(total['花费'],sum(r['花费'] for r in parts),abs_tol=1e-8)
    assert total['回收倍数'] is None and total['单条工单成本'] is None
    goals=c.query('native_online_abroad_annual_goals')['data'];assert goals[0]['全年现金目标']==29930000 and goals[0]['全年工单目标']==6715
    checks.append({'key':'cost_total_and_existing_annual_goals','status':'passed','total_cost':total['花费']})
    checks.append({'key':'native_layout_and_scopes','status':'passed','teams':7,'charts':len(ids)})
    c.save(checks)
if __name__=='__main__':main()
