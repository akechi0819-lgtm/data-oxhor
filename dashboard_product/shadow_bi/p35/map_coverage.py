"""把181项功能与22项作用域映射到Superset原生工作台。"""
import csv,json
from dashboard_product.shadow_bi.p3.catalog import ROOT,VIEWS
from dashboard_product.shadow_bi.p35.native_catalog import native_views

def main():
    proof=json.loads((ROOT/'.local/audits/shadow-bi-p35-20261023/native-bootstrap.json').read_text())
    by={v.key:v for v in list(VIEWS)+native_views()};valid=set(proof['visible_chart_keys'])
    path=ROOT/'docs/shadow-bi-p3-feature-mapping-20261022.csv';rows=list(csv.DictReader(path.open(encoding='utf-8-sig')))
    for row in rows:
        original=row['p3_dataset_keys'].split(';');keys=[]
        for key in original:
            v=by[key];native='native_'+key
            if key in ['online_platforms','online_platform_groups']:
                keys.extend(['native_online_platform_training','native_online_platform_abroad'])
            elif key=='online_daily':keys.extend(['native_online_daily_training','native_online_daily_abroad'])
            elif key.endswith(('_countries','_countries_child')):keys.append('native_'+v.page+'_country_tree')
            elif key.endswith(('_channels','_channels_child')):
                keys.extend(k for k in ['native_'+v.page+'_channel_tree_training','native_'+v.page+'_channel_tree_abroad'] if k in valid)
            elif key=='overview_personal_channels':keys.append('prep_personal_channels')
            elif key.endswith(('_schools','_schools_child','_grades')):
                stem='native_'+v.page+('_grades' if key.endswith('_grades') else '_schools')
                keys.extend(k for k in [stem,stem+'_training',stem+'_abroad'] if k in valid)
            elif key.endswith('_lines') or key=='online_summary':
                keys.extend(k for k in ['native_'+v.page+'_training','native_'+v.page+'_abroad','native_'+v.page+'_cash_lines'] if k in valid)
                if v.page=='online':keys.extend(['native_online_roi_tree','native_online_costs'])
            elif key.endswith('_groups'):
                keys.extend(k for k in [native,'native_'+v.page+'_cash_groups'] if k in valid)
            elif native in valid:keys.append(native)
            elif key in valid:keys.append(key)
            elif v.section in ['经营总览','目标进度']:
                keys.extend(k for k in ['native_'+v.page+'_training','native_'+v.page+'_abroad','native_'+v.page+'_cash_lines','native_'+v.page+'_groups'] if k in valid)
            elif v.section=='明细核对':pass
            else:raise AssertionError(('missing-visible-mapping',key))
        keys=list(dict.fromkeys(keys));assert all(k in valid for k in keys)
        row['new_location']='；'.join(proof['url']+' → '+('市场活动' if by[k].page=='activities' else by[k].page)+' → '+(by[k].section if k.startswith('native_') else '原生对应分析/明细页') for k in keys)
        row['native_chart_keys']=';'.join(keys);row['native_chart_ids']=';'.join(str(proof['charts'][k]) for k in keys)
        row['p35_status']='依用户要求从经营看板移除，仅后台核查' if not keys else 'Superset原生Tabs/Table/图表；待独立验收；HTML替代界面已撤销'
    assert len(rows)==181
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    path=ROOT/'docs/shadow-bi-p3-filter-scopes-20261022.json';scopes=json.loads(path.read_text())
    for scope in scopes:
        scope.pop('p35_location',None);scope.pop('p35_scope_contract',None)
        scope['p35_native_location']=proof['url']+' → 原生筛选栏/对应图表控件'
        scope['p35_scope_contract']='原始图表限定集合保留；新增原生投影继承其源视图的筛选合同。原生分页随筛选复测，不使用自定义offset。'
    assert len(scopes)==22;path.write_text(json.dumps(scopes,ensure_ascii=False,indent=2));print('181 features / 22 scopes mapped to native dashboard')
if __name__=='__main__':main()
