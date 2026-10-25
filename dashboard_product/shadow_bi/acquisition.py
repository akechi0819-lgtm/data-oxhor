"""语培主被动独立视图：复用既有归属、期间及人头去重，不覆盖被动基线。"""
from copy import deepcopy
import json
from dashboard_product.management.aggregate import aggregate
from dashboard_product.management.breakdowns import enrich_periods
from dashboard_product.management.enhancements import selection_views
from dashboard_product.management.market_totals import attach_market_orders
from dashboard_product.management.study_abroad_progress import attach_progress
from dashboard_product.management.team_scopes import attach_team_scope_views
from dashboard_product.management.online_view import online_view
from dashboard_product.online_team.build import ROOT

SCOPES = ('被动', '主动', '全部')

def clear_training_targets(value):
    """未下达主动/全部目标；留学目标及人员产能不参与此切换。"""
    if isinstance(value, list):
        for row in value: clear_training_targets(row)
    elif isinstance(value, dict):
        if value.get('business_line') == 'abroad': return
        if 'actual' in value:
            for key in ('target', 'completion', 'gap', 'time_gap'): value[key] = None
        value.pop('passive_cash_share', None)
        for key, child in value.items():
            if key not in ('abroad', 'abroad_progress', 'study_abroad_progress', 'people', 'person_calendar'):
                clear_training_targets(child)

def scoped_tables(model):
    from dashboard_product.shadow_bi.library import tables
    def read(path): return json.loads((ROOT/path).read_text())
    training_targets=read('dashboard_product/config/project_targets.json')
    abroad_targets=read('dashboard_product/config/offline_market_targets.json')
    online_targets=read('dashboard_product/online_team/config/study_abroad_targets.json')
    expanded=model['scope_training_facts']
    abroad=[f for f in model['facts'] if f['business_line']=='abroad']
    names=('team_periods','selection_team_periods','online_lines','online_groups','online_platforms','online_daily')
    result={'scoped_'+name:[] for name in names}
    result['acquisition_facts']=expanded+abroad
    for scope in SCOPES:
        if scope=='被动': current=model
        else:
            facts=[f for f in expanded if scope=='全部' or f['acquisition_mode']==scope]+abroad
            body=aggregate(facts,model['people'],model['abroad_people'],training_targets,abroad_targets,online_targets,
                model['through'],abroad_source=model['public']['metadata']['study_abroad_source'])
            enrich_periods(body['periods'],facts,training_targets,abroad_targets,online_targets)
            attach_progress(body['periods'])
            market=[dict(f,business_group=f.get('comparison_group')) for f in facts if f['business_line']=='training' and f['metric']=='orders']
            attach_market_orders(body['periods'],market)
            attach_team_scope_views(body['periods'],facts,market,training_targets,model['new_student_cash_rows'])
            segments=selection_views(body['periods'],facts,model['people'],training_targets)
            clear_training_targets(body['periods']);clear_training_targets(segments)
            for period in body['periods']:
                for team in period['teams']:
                    if 'combined_orders' in team:
                        team['combined_orders']={'actual':None,'prior':None,'yoy':None,'status':'not_configured','note':'跨业务线合计不支持语培主被动切换。'}
                    if 'market_orders' in team: team['market_orders']['note']=f'语培{scope}工单按观远原始团队白名单及主被动字段统计；包含删除/回收。'
            public={**model['public'], 'periods':body['periods']}
            online=online_view(public,facts,online_targets,order_facts=expanded)
            # 费用不跟随主被动变化；主动范围不借用被动ROI。保留留学完整投影。
            for p,original in zip(online['periods'],model['online_data']['periods']):
                p['lines']['abroad']=deepcopy(original['lines']['abroad'])
                for row,old in zip(p['daily'],original['daily']):
                    row.update({k:v for k,v in old.items() if k.startswith('abroad_') or k in ('training_spend','training_spend_status')})
                    row['training_cash']=sum(f['value'] for f in facts if f['business_line']=='training' and f['metric']=='cash' and f['team_id']=='online_platform' and f['event_date']==row['date'])
                    row['training_roi']=None
            current={**model,'public':public,'segments':segments,'online_data':online}
        projected=tables(current)
        for name in names:
            result['scoped_'+name].extend(dict(row,acquisition_scope=scope) for row in projected[name])
    return result
