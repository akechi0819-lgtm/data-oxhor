"""沿真实保存图表配置验证学校排序、分页总数和主被动，不用测试自定顺序覆盖接线。"""
import json
from concurrent.futures import ThreadPoolExecutor
from dashboard_product.shadow_bi.p3 import verify_api
from dashboard_product.shadow_bi.p3.catalog import VIEWS,ROOT
from dashboard_product.shadow_bi.p35.native_catalog import native_views

def main():
    extra=native_views();verify_api.VIEWS=list(VIEWS)+extra;c=verify_api.Client();checks=[]
    meta=json.loads((ROOT/'.local/audits/shadow-bi-p35-20261023/native-bootstrap.json').read_text())
    for page in ['overview','virtual','prep']:
        key='native_'+page+'_schools';spec=next(v for v in extra if v.key==key)
        chart=c.s.get(c.base+'/api/v1/chart/'+str(meta['charts'][key])).json()['result'];params=json.loads(chart['params'])
        assert chart['viz_type']=='table' and params['server_pagination'] and params['server_page_length']==50
        order=[json.loads(x) for x in params['order_by_cols']]
        assert order==[['排列顺序',True]],(key,order)
        for metric,direction in [('工单','升序'),('现金','降序')]:
            filters=[verify_api.f(k,v) for k,v in spec.filters.items() if k not in ['排序依据','排序方向']]+[verify_api.f('排序依据',metric),verify_api.f('排序方向',direction)]
            # 排序与展示列均取已保存配置；增加数值列仅供独立单调断言。
            result=c.query(key,columns=params['all_columns']+['学校','父'+metric,'排列顺序'],filters=filters,order=order,limit=params['server_page_length'],name=page+'-saved-'+metric+'-'+direction)
            rows=result['data'];values=[r['父'+metric] for r in rows if r['父'+metric] is not None]
            assert values==sorted(values,reverse=direction=='降序'),(key,metric,values)
            assert all('<details>' in r['学校表现'] and '<summary>' in r['学校表现'] for r in rows)
            count=c.query(key,columns=params['all_columns'],filters=filters,order=order,limit=params['row_limit'],is_rowcount=True,name=page+'-native-total')['data'][0]['rowcount']
            second=c.query(key,columns=['学校','业务线','排列顺序'],filters=filters,order=order,limit=50,offset=50,name=page+'-native-second-page')['data']
            assert count>50 and second and len(rows)==50
            assert max(r['排列顺序'] for r in rows)<min(r['排列顺序'] for r in second)
            checks.append({'key':page+'-'+metric+'-'+direction,'status':'passed','saved_order':order,'first_values':values[:8],'page_size':len(rows),'full_count':count})
    spec=next(v for v in extra if v.key=='native_overview_schools')
    for scope in ['全部','主动','被动']:
        filters=[verify_api.f(k,scope if k=='学校主被动' else v) for k,v in spec.filters.items()]+[verify_api.f('学校','南开大学')]
        data=c.query(spec.key,columns=['学校树'],filters=filters,limit=10,name='school-mode-'+scope)['data']
        tree=next(json.loads(r['学校树']) for r in data if json.loads(r['学校树'])['line']=='语培')
        expected={'全部':'521,911.30','主动':'172,491.30','被动':'349,420.00'}[scope]
        assert tree['cash']==expected,(scope,tree)
        assert {s['name'] for s in tree['scopes']}==({'主动','被动'} if scope=='全部' else {scope})
        checks.append({'key':'school-mode-'+scope,'status':'passed','cash':tree['cash']})
    # 两次正常分页同时请求，覆盖学校页曾在其他查询并行时OOM的现场风险。
    saved=json.loads(c.s.get(c.base+'/api/v1/chart/'+str(meta['charts'][spec.key])).json()['result']['params'])
    def page_request(offset):
        client=verify_api.Client()
        rows=client.query(spec.key,columns=saved['all_columns']+['排列顺序'],limit=50,offset=offset,order=[json.loads(x) for x in saved['order_by_cols']],name='parallel-school-page-'+str(offset))['data']
        assert len(rows)==50
        client.save([{'key':'parallel-school-page-'+str(offset),'status':'passed','rows':len(rows)}])
        return {'offset':offset,'first_rank':rows[0]['排列顺序'],'last_rank':rows[-1]['排列顺序'],'seconds':client.results[0]['seconds'],'evidence':str(client.evidence)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        pages=list(pool.map(page_request,[0,50]))
    assert pages[0]['last_rank']<pages[1]['first_rank']
    checks.append({'key':'parallel-native-school-pages','status':'passed','pages':pages})
    for item in meta['filters']:
        assert not any(t.startswith('TAB-TEAM-') for t in item['tabsInScope'])
    c.save(checks)

if __name__=='__main__':main()
