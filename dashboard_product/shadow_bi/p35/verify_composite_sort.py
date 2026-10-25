"""抓住复合展示列字典序回归及F013隐藏回归；经真实Superset API验证。"""
import json,math
from dashboard_product.shadow_bi.p3 import verify_api
from dashboard_product.shadow_bi.p3.catalog import VIEWS,ROOT
from dashboard_product.shadow_bi.p35.native_catalog import native_views


def main():
    extra=native_views();verify_api.VIEWS=list(VIEWS)+extra;c=verify_api.Client();checks=[]
    expected={'工单表现':'工单完成','现金表现':'现金完成（元）','人头表现':'人头数值','本期完成':'当期','上年同期':'同期','同比变化':'同比','目标与完成率':'目标'}
    for v in extra:
        mappings={label:column for label,column in expected.items() if label in v.columns}
        if not mappings:continue
        chart=c.s.get(c.base+'/api/v1/chart/'+str(c.b['charts'][v.key]['id'])).json()['result']
        params=json.loads(chart['params']);assert params['server_pagination'] is True,(v.key,'client would sort strings')
        for label,column in mappings.items():
            for asc in [True,False]:
                rows=c.query(v.key,columns=list(dict.fromkeys(v.columns+[column])),order=[[label,asc]],limit=1000,name=v.key+'-'+label+'-'+('asc' if asc else 'desc'))['data']
                values=[r[column] for r in rows if r[column] is not None]
                assert values==sorted(values,reverse=not asc),(v.key,label,asc,values)
        checks.append({'key':v.key+'-composite-header-numeric-sort','status':'passed','columns':list(mappings)})
    spec=next(v for v in extra if v.key=='native_overview_targets')
    assert '被动现金占新生收入' in spec.columns
    chart=c.s.get(c.base+'/api/v1/chart/'+str(c.b['charts'][spec.key]['id'])).json()['result'];params=json.loads(chart['params'])
    assert '被动现金占新生收入' in params['all_columns']
    assert params['column_config']['被动现金占新生收入']['d3NumberFormat']=='.1%'
    for team in ['全部','线上','线下']:
        filters=[verify_api.f('期间','FY27'),verify_api.f('管理单元','市场总计'),verify_api.f('目标团队',team)]
        rows=c.query(spec.key,filters=filters,columns=spec.columns+['被动现金分子','新生现金固定分母'],order=[['业务组名称',True]],limit=1000,name='F013-'+team)['data']
        refs=c.query('overview_targets',filters=filters,columns=['业务组名称','指标','被动现金分子','新生现金固定分母','被动现金占比'],limit=1000,name='F013-original-'+team)['data']
        lookup={r['业务组名称']:r for r in refs if r['指标']=='现金（元）'}
        assert rows and any(r['被动现金占新生收入'] is not None for r in rows)
        for row in rows:
            ref=lookup[row['业务组名称']]
            assert row['被动现金占新生收入']==ref['被动现金占比']
            assert row['被动现金分子']==ref['被动现金分子'] and row['新生现金固定分母']==ref['新生现金固定分母']
            if row['新生现金固定分母']:
                assert math.isclose(row['被动现金占新生收入'],row['被动现金分子']/row['新生现金固定分母'],abs_tol=1e-10)
        active=c.query(spec.key,filters=filters+[verify_api.f('语培统计范围','主动')],columns=spec.columns+['被动现金分子','新生现金固定分母'],order=[['业务组名称',True]],limit=1000,name='F013-active-does-not-change-'+team)['data']
        assert rows==active
        checks.append({'key':'F013-visible-original-caliber-'+team,'status':'passed','shares':{r['业务组名称']:r['被动现金占新生收入'] for r in rows}})
    c.save(checks)

if __name__=='__main__':main()
