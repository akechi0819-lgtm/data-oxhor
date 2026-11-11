"""同一输入对账：数值、状态分开比较，不把未覆盖项目视为通过。"""
from decimal import Decimal
import re
import json

from .relations import records


def equal(a,b,*,tolerance='0.000000001'):
    if a is None or b is None:return a is None and b is None
    if isinstance(a,bool) or isinstance(b,bool):return a is b
    numeric=lambda v:isinstance(v,(int,float,Decimal)) or isinstance(v,str) and re.fullmatch(r'-?\d+(?:\.\d+)?',v)
    if numeric(a) and numeric(b) and (not isinstance(a,str) or not isinstance(b,str)):
        return abs(Decimal(str(a))-Decimal(str(b)))<=Decimal(tolerance)
    return a==b


def team_comparison(con, public):
    actual={(r['period_id'],r['unit_id'],r['business_line'],r['metric']):r
        for r in records(con,"SELECT * FROM business.team_metrics WHERE acquisition_scope='被动'")}
    differences=[];checked=0
    for p in public['periods']:
        for team in p['teams']:
            for line in ('training','abroad'):
                for metric in ('orders','cash','heads'):
                    expected=team['lines'][line][metric]
                    key=(p['id'],team['id'],line,metric)
                    got=actual[key]
                    for field in ('actual','prior','target','status'):
                        checked+=1
                        if not equal(expected.get(field),got.get(field)):
                            differences.append(dict(key=key,field=field,legacy=expected.get(field),sql=got.get(field)))
    return {'checks':checked,'differences':differences,'passed':not differences}


def personal_comparison(con, public):
    actual={(r['period_id'],r['month_mode'],r['name'],r['business_line'],r['state'],r['metric']):r
        for r in records(con,'SELECT * FROM business.personal_metrics')}
    differences=[];checked=0
    for p in public['periods']:
        total=next(t for t in p['teams'] if t['id']=='total')
        for mode,container in [('performance',total),('calendar',total['person_calendar'])]:
            for person in container['people']:
                for state,view in person['order_status_views'].items():
                    for line in ('training','abroad'):
                        key=(p['id'],mode,person['name'],line,state,'orders')
                        got=actual[key]
                        for field in ('actual','prior','target'):
                            expected=view.get(f'{line}_{field}')
                            # Abroad has no year-on-year comparison in the contract.
                            value=None if line=='abroad' and field=='prior' else got[field]
                            checked+=1
                            if not equal(expected,value):differences.append(dict(key=key,field=field,legacy=expected,sql=value))
                primary='training' if person['business_line'] in ('training','training+abroad') else 'abroad'
                # Cash and customer heads are primary-business metrics and independent of order status.
                for metric,field in [('cash','cash_actual'),('heads','heads_actual')]:
                    key=(p['id'],mode,person['name'],primary,'01',metric)
                    got=actual[key]
                    for value_field in ('actual','prior','target'):
                        expected=person[field].get(value_field)
                        value=got[value_field]
                        if primary=='abroad' and value_field=='prior':value=None
                        checked+=1
                        if not equal(expected,value):differences.append(dict(key=key,field=value_field,legacy=expected,sql=value))
    return {'checks':checked,'differences':differences,'passed':not differences}


def fact_comparison(con,expected,*,personal=False,all_acquisitions=False):
    relation='business.personnel_facts' if personal else 'business.facts'
    condition='' if personal or all_acquisitions else " WHERE business_line<>'training' OR acquisition_mode='被动'"
    actual={r['fact_id']:r for r in records(con,'SELECT * FROM '+relation+condition)}
    baseline={r['fact_id']:r for r in expected}
    missing=sorted(set(baseline)-set(actual));extra=sorted(set(actual)-set(baseline));differences=[];checks=0
    for key in sorted(set(baseline)&set(actual)):
        for field,value in baseline[key].items():
            got=actual[key].get(field)
            if field=='source_record' and isinstance(got,str):
                try:got=json.loads(got)
                except json.JSONDecodeError:pass
            checks+=1
            if not equal(value,got):differences.append({'key':key,'field':field,'legacy':value,'sql':got})
    return {'legacy_rows':len(baseline),'sql_rows':len(actual),'checks':checks,
            'missing':missing,'extra':extra,'differences':differences,
            'passed':not missing and not extra and not differences}


def radar_comparison(con,public):
    actual={r['name']:r for r in records(con,'SELECT * FROM business.radar_people')}
    axes={(r['name'],r['axis']):r for r in records(con,'SELECT * FROM business.radar_axes')}
    differences=[];checked=0
    for p in public['capacity']['radar']['people']:
        for field in ('business_line','home_team','home_group','peer_group','start_date','through_date','orders','cash','heads',
                      'conversion','partner','tmk','campaign','cash_capacity','cash_progress_completion'):
            expected=p[field];got=actual[p['name']][field]
            if field in ('start_date','through_date'):got=str(got)
            checked+=1
            if not equal(expected,got):differences.append({'key':p['name'],'field':field,'legacy':expected,'sql':got})
        for a in p['radar']['axes']:
            got=axes[(p['name'],a['key'])]
            for field in ('value','mean','relative','scale'):
                checked+=1
                if not equal(a[field],got[field]):differences.append({'key':[p['name'],a['key']],'field':field,'legacy':a[field],'sql':got[field]})
    return {'checks':checked,'differences':differences,'passed':not differences}


def advertising_comparison(con,expected):
    fields=('period_id','business_line','record_type','business_group','platform','event_date')
    key=lambda r:tuple(str(r.get(f)) if r.get(f) is not None else None for f in fields)
    actual={key(r):r for r in records(con,'SELECT * FROM business.advertising_rollup')}
    baseline={key(r):r for r in expected};differences=[];checked=0
    missing=sorted(set(baseline)-set(actual),key=str);extra=sorted(set(actual)-set(baseline),key=str)
    for k in set(actual)&set(baseline):
        for field,value in baseline[k].items():
            got=actual[k].get(field)
            if field.endswith('_date') and got is not None:got=str(got)
            checked+=1
            if not equal(value,got):differences.append({'key':k,'field':field,'legacy':value,'sql':got})
    return {'legacy_rows':len(baseline),'sql_rows':len(actual),'checks':checked,'missing':missing,'extra':extra,
            'differences':differences,'passed':not missing and not extra and not differences}


def activity_comparison(con,expected):
    actual={r['activity']:r for r in records(con,'SELECT * FROM business.activities')}
    differences=[];checked=0
    for row in expected:
        for field,value in row.items():
            if field=='name':continue
            got=actual.get(row['name'],{}).get(field)
            if field=='heads_parts' and isinstance(got,str):got=json.loads(got)
            checked+=1
            if not equal(value,got):differences.append({'key':row['name'],'field':field,'legacy':value,'sql':got})
    extra=sorted(set(actual)-{r['name'] for r in expected})
    return {'checks':checked,'differences':differences,'extra':extra,'passed':not differences and not extra}


def contribution_comparison(con,public,details):
    key=lambda r:(r['key'],r['person'],r['bucket'])
    actual={key(r):r for r in records(con,'SELECT * FROM business.contributions')}
    expected={key(r):r for r in details['records']}
    missing=sorted(set(expected)-set(actual));extra=sorted(set(actual)-set(expected));diffs=[];checks=0
    for k in set(expected)&set(actual):
        for field,value in expected[k].items():
            got=actual[k].get(field)
            if field=='cross_business_marker' and isinstance(got,str):got=json.loads(got)
            checks+=1
            if not equal(value,got):diffs.append({'key':k,'field':field,'legacy':value,'sql':got})
    capacity={(r['month'],r['person'],r['state'],r['product_scope'],r['metric']):r
        for r in records(con,'SELECT * FROM business.contribution_capacity')}
    capacity_diffs=[];capacity_checks=0
    for p in public['capacity']['periods']:
        for person in p['people']:
            for state,view in person['order_status_views'].items():
                for scope,values in [('all',view),*view['breakdowns'].items()]:
                    for metric in ('orders','cash'):
                        k=(p['id'],person['name'],state,scope,metric);got=capacity[k]
                        for field in ('self','received','own_total','output','created_total','self_rate','completion','targets'):
                            value=values[field][metric];sql=got['target' if field=='targets' else field]
                            capacity_checks+=1
                            if not equal(value,sql):capacity_diffs.append({'key':k,'field':field,'legacy':value,'sql':sql})
    diagnostics={r['diagnostic']:r['value'] for r in records(con,'SELECT * FROM business.contribution_diagnostics')}
    diag_diffs=[{'key':k,'legacy':v,'sql':diagnostics.get(k)} for k,v in details['diagnostics'].items()
        if k not in diagnostics or not equal(v,diagnostics[k])]
    return {'checks':checks+capacity_checks,'ledger_rows':len(actual),'capacity_rows':len(capacity),
        'missing':missing,'extra':extra,'differences':diffs+capacity_diffs+diag_diffs,
        'passed':not missing and not extra and not diffs and not capacity_diffs and not diag_diffs}
