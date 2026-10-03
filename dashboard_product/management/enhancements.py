"""Precomputed selectors and personnel comparisons; no client-side business aggregation."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from . import aggregate as a
from . import breakdowns as b
from dashboard_product.capacity import cash_contribution_bucket
from dashboard_product.online_team.build import metric

GROUPS = ('青少', '初中', '高中')
ROSTER_GROUPS = {'youth':'青少', 'middle_school':'初中', 'high_school':'高中'}
RADAR_DIMS = (('orders','工单数'),('heads','签约量'),('conversion','转化率'),
              ('partner','渠道／校代现金'),('tmk','TMK现金'),('campaign','活动现金'))


def comparison(current, prior, unit='条', status='available'):
    return {'actual': current, 'prior': prior,
            'yoy': current / prior - 1 if current is not None and prior not in (None,0) else None,
            'status': status if current is not None else 'not_connected', 'unit': unit}


def enhance_capacity(body, facts, people_config, abroad_people_config, through, capacity_config):
    valid = a._valid_facts(facts, through)
    roster = a._roster(people_config, abroad_people_config)
    prior_end = a._shift_year(through)
    prior = {p['name']:p for p in a._capacity(valid, roster, prior_end,
                capacity_config.get('annual_cash_by_person',800000), start=date(2025,6,1))}
    cash_buckets = defaultdict(lambda: defaultdict(Decimal))
    training_orders = defaultdict(Decimal)
    for f in valid:
        if f['business_line'] != 'training' or not date(2026,6,1) <= f['event_date'] <= through:
            continue
        for owner in f['owners']:
            if f['metric']=='orders':
                training_orders[owner] += f['value']
            else:
                cash_buckets[owner][cash_contribution_bucket(f.get('first_channel'),f.get('second_channel'))] += f['value']
    for p in body['capacity']:
        old=prior[p['name']]
        p['orders_metric']=comparison(p['orders'],old['orders'])
        p['cash_metric']=comparison(p['cash'],old['cash'],'元',p['cash_status'])
        p['heads_metric']=comparison(p['heads'],old['heads'],'人',p['cash_status'])
        current_dest={r['name']:r['orders'] for r in p['training_destinations']}
        prior_dest={r['name']:r['orders'] for r in old['training_destinations']}
        p['destinations']={g:comparison(current_dest.get(g,0),prior_dest.get(g,0))
                           for g in sorted(set(current_dest)|set(prior_dest)|{'大学','高中','留学预备'})}
        p['abroad_metric']=comparison(p['abroad_orders'],old['abroad_orders'])
        p['other_orders']=sum(v for g,v in current_dest.items() if g not in ('大学','高中','留学预备'))
        p['peer_group']='|'.join((p['home_team'],p['home_group'] or '',p['business_line']))
        orders=float(training_orders[p['name']])
        has_training = orders > 0 or p['cash'] is not None
        values={'orders':orders, 'heads':p['heads'],
                'conversion':p['heads']/orders if p['heads'] is not None and orders else None,
                **{k:float(cash_buckets[p['name']][k]) if has_training else None for k in ('partner','tmk','campaign')}}
        p['radar_values']=values
    peers=defaultdict(list)
    for p in body['capacity']:peers[p['peer_group']].append(p)
    for p in body['capacity']:
        axes=[]
        for key,label in RADAR_DIMS:
            vals=[r['radar_values'][key] for r in peers[p['peer_group']] if r['radar_values'][key] is not None]
            value=p['radar_values'][key]
            mean=sum(vals)/len(vals) if vals else None
            axes.append({'key':key,'label':label,'value':value,
                         'mean':mean, 'relative':value/mean-1 if value is not None and mean else None,
                         'scale':max(vals) if vals and max(vals)>0 else 1})
        p['radar']={'scope':'沿用语培贡献口径；留学现金未接入', 'axes':axes,
                    'peer_count':len(peers[p['peer_group']])}
    for p in body['capacity']:
        del p['radar_values']


def _group_members(people_config):
    result={}
    for team in people_config.get('teams',[]):
        if team['team_id']!='offline_market':continue
        for group in team.get('groups',[]):
            scope=ROSTER_GROUPS.get(group.get('group_id'))
            if scope:
                for person in group['members']:result[person['display_name']]=scope
    return result


def _target(targets, period, selected, kind):
    if ('青少' in selected) != ('初中' in selected):return None
    groups=(['留学预备'] if '青少' in selected else [])+(['高中'] if '高中' in selected else [])
    fn=a._department_training_target if kind=='orders' else a._department_training_cash_target
    values=[fn(targets,period,'offline_market',g) for g in groups]
    return None if not values or any(v is None for v in values) else sum(values)


def selection_views(periods, facts, people_config, training_targets):
    through=max(a._date(p['through_date']) for p in periods if p.get('through_date'))
    valid=a._valid_facts(facts,through,include_non_completion=True)
    membership=_group_members(people_config)
    result={}
    for mask in range(1,8):
        selected=[g for i,g in enumerate(GROUPS) if mask & (1<<i)]
        scoped=[f for f in valid if f['business_line']=='training' and f['team_id']=='offline_market'
                and f.get('comparison_group') in selected]
        output=[]
        for p in periods:
            lines={'training':{},'abroad':{}}
            for kind in ('orders','cash','heads'):
                target=_target(training_targets,p,selected,kind) if kind!='heads' else None
                lines['training'][kind]=b._measure(scoped,'training',kind,lambda f:True,p,'total',target)
                if target is None and kind!='heads' and p['status']!='future':
                    lines['training'][kind]['note']='所选组合未单独下达目标，不按比例拆分留学预备整体目标。'
                lines['abroad'][kind]=metric(None,None,None,p['time_progress'],kind,
                    status='not_configured' if kind=='orders' else 'not_connected',
                    note='不纳部门留学考核；人员贡献见产能。' if kind=='orders' else '留学现金未接入')
            originals=[t for t in p['teams'] if t['id'] in ('prep','high')]
            persons=[r for t in originals for r in t['people'] if membership.get(r['name']) in selected]
            calendar_originals=[t['person_calendar'] for t in originals]
            calendar_persons=[r for t in calendar_originals for r in t['people']
                              if membership.get(r['name']) in selected]
            team={'id':'total','name':'＋'.join(selected),'lines':lines,'people':persons,
                  'person_start':originals[0]['person_start'],'person_through':originals[0]['person_through'],'person_progress':originals[0]['person_progress'],
                  'person_calendar':{
                      'person_start':calendar_originals[0]['person_start'],
                      'person_through':calendar_originals[0]['person_through'],
                      'person_progress':calendar_originals[0]['person_progress'],
                      'people':calendar_persons,
                  },
                  'countries':[], 'selected_groups':selected}
            output.append({**p,'teams':[team]})
        b.enrich_periods(output,scoped,{}, {}, {})
        for p in output:
            t=p['teams'][0];t['id']='prep_high'
            t['yoy_groups']=[r for r in t['yoy_groups'] if r['name'] in selected]
            t['business_groups']=[r for r in t['business_groups'] if (r['name']=='高中' and '高中' in selected) or (r['name']=='留学预备' and any(g in selected for g in ('青少','初中')))]
            for r in t['business_groups']:
                full = r['name']=='高中' or all(g in selected for g in ('青少','初中'))
                if r['name']=='留学预备' and not full:r['name']='＋'.join(g for g in selected if g!='高中')
                for kind in ('orders','cash'):
                    fn=a._department_training_target if kind=='orders' else a._department_training_cash_target
                    goal=fn(training_targets,p,'offline_market',r['name']) if full else None
                    old=r[kind];r[kind]=metric(old['actual'],old['prior'],goal,p['time_progress'],kind,status=old['status'])
        result[str(mask)]=output
    return result
