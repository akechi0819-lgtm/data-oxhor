"""Precomputed selectors; no client-side business aggregation."""
from . import aggregate as a
from . import breakdowns as b
from dashboard_product.management.windowing import metric

GROUPS = ('青少', '初中', '高中')
ROSTER_GROUPS = {'youth':'青少', 'middle_school':'初中', 'high_school':'高中'}
def _group_members(people_config):
    result={}
    for team in people_config.get('teams',[]):
        if team['team_id']!='offline_market':continue
        for group in team.get('groups',[]):
            scope=ROSTER_GROUPS.get(group.get('group_id'))
            if scope:
                for person in group['members']:result[person['display_name']]=scope
    return result


def _selected_person(person, selected, membership):
    group = membership.get(person['name'])
    if group is None and person.get('business_line') == 'abroad':
        group = person.get('home_group')
    return group in selected


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
                    status='not_configured', note='不纳部门留学考核；个人贡献单独展示。')
            lines['abroad']['source_coverage'] = dict(p['abroad_source'])
            originals=[t for t in p['teams'] if t['id'] in ('prep','high')]
            persons=[r for t in originals for r in t['people']
                     if _selected_person(r, selected, membership)]
            calendar_originals=[t['person_calendar'] for t in originals]
            calendar_persons=[r for t in calendar_originals for r in t['people']
                              if _selected_person(r, selected, membership)]
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
