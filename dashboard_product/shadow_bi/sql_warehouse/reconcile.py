"""Reconcile a sealed local candidate against an explicit frozen legacy run."""
import argparse
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time

import duckdb

from data_platform.query.evidence import resolve_file, file_ref
from . import compare
from .relations import records


def _rows(con, expected, sql, keys, fields=None):
    def normal(v):
        return v.isoformat() if isinstance(v, (date, datetime)) else v
    def key(r): return tuple(normal(r[k]) for k in keys)
    actual=records(con,sql)
    before={key(r):r for r in expected};after={key(r):r for r in actual}
    missing=sorted(set(before)-set(after),key=str);extra=sorted(set(after)-set(before),key=str)
    differences=[];checks=0
    for k in set(before)&set(after):
        for f in (fields or before[k].keys()):
            checks+=1
            a,b=normal(before[k].get(f)),normal(after[k].get(f))
            if not compare.equal(a,b):differences.append({'key':k,'field':f,'legacy':a,'sql':b})
    duplicates={'legacy':len(expected)-len(before),'sql':len(actual)-len(after)}
    return {'checks':checks,'legacy_rows':len(expected),'sql_rows':len(actual),
        'missing':missing,'extra':extra,'duplicates':duplicates,'differences':differences,
        'passed':not missing and not extra and not differences and not any(duplicates.values())}


def reconcile(*,candidate,reference,output):
    candidate,reference,output=map(lambda p:Path(p).resolve(),(candidate,reference,output))
    manifest=json.loads((candidate/'candidate.json').read_text())
    database=resolve_file(candidate,manifest['database'])
    used={}
    def load(name):
        p=reference/(name+'.json');used[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        return json.loads(p.read_text())
    public=load('public');facts=load('facts');all_training=load('scope_training_facts')
    metadata=public['metadata']
    if (metadata['snapshot_id']!=manifest['snapshots']['training'] or
        metadata['study_abroad_source']['snapshot_id']!=manifest['snapshots']['abroad'] or
        metadata['data_through']!=manifest['through_date']):
        raise ValueError('新旧对账必须绑定同一显式Snapshot对及截止日')
    results={};start=time.perf_counter()
    with duckdb.connect(str(database),read_only=True) as con:
        con.execute("SET threads=2; SET memory_limit='512MB'")
        results['facts']=compare.fact_comparison(con,facts)
        results['all_training']=compare.fact_comparison(con,all_training+[r for r in facts if r['business_line']=='abroad'],all_acquisitions=True)
        results['personnel_facts']=compare.fact_comparison(con,load('personnel_facts'),personal=True)
        results['teams']=compare.team_comparison(con,public)
        results['personal']=compare.personal_comparison(con,public)
        results['radar']=compare.radar_comparison(con,public)
        results['advertising']=compare.advertising_comparison(con,load('advertising_rollup'))
        results['activities']=compare.activity_comparison(con,load('activities'))
        results['contributions']=compare.contribution_comparison(con,public,load('personnel_details'))
        expense_rows=load('expense_rows')
        from .expenses import _ocean_account
        source_accounts={s['source_id']:_ocean_account(s) for s in load('expense_sources')
            if s['platform']=='抖音' and s['grain']=='daily' and not s.get('account_id')}
        enrichments={}
        for row in expense_rows:
            if row.get('account_id') is None and row['source_id'] in source_accounts:
                row['account_id']=source_accounts[row['source_id']]
                enrichments[row['source_id']]=enrichments.get(row['source_id'],0)+1
        results['expense_account_enrichment']={'passed':True,'source':'confirmed ocean_download.ACCOUNTS',
            'sources':[{'source_id':s,'account_id':source_accounts[s],'rows':n} for s,n in sorted(enrichments.items())]}
        results['expense_rows']=_rows(con,expense_rows,'SELECT * FROM expenses.expense_rows',
            ('source_id','source_row'),('source_id','source_row','account_id','business_line','business_group','platform','start_date','end_date','amount'))
        scoped=load('scoped_tables')
        team_rows=records(con,'SELECT * FROM business.team_metrics')
        team_index={(r['period_id'],r['unit_id'],r['acquisition_scope'],r['business_line'],r['metric']):r for r in team_rows}
        differences=[];checks=0
        selections=[(r['period_id'],r['team_id'],r['acquisition_scope'],r['view']) for r in scoped['scoped_team_periods']]
        selections += [(r['period_id'],'selection_'+r['selection'],r['acquisition_scope'],r['view']['teams'][0]) for r in scoped['scoped_selection_team_periods']]
        for period,unit,acquisition,team in selections:
            for line,metrics in team['lines'].items():
                for metric,expected in metrics.items():
                    if metric not in ('orders','cash','heads'):continue
                    got=team_index[(period,unit,acquisition,line,metric)]
                    for field in ('actual','prior','target','status','note'):
                        checks+=1
                        if not compare.equal(expected.get(field),got.get(field)):
                            differences.append({'key':(period,unit,acquisition,line,metric),'field':field,'legacy':expected.get(field),'sql':got.get(field)})
        results['all_scope_teams']={'checks':checks,'differences':differences,'passed':not differences}
        online_fields=['period_id','event_date AS date','acquisition_scope']
        for line in ('training','abroad'):
            for field in ('orders','cash','spend','spend_status','roi'):
                online_fields.append(f"max({field}) FILTER(WHERE business_line='{line}') AS {line}_{field}")
        results['scoped_online_daily']=_rows(con,scoped['scoped_online_daily'],
            'SELECT '+','.join(online_fields)+' FROM business.scoped_online_daily GROUP BY ALL',
            ('acquisition_scope','period_id','date'))
    preview=json.loads((candidate/'notification-preview.json').read_text())
    baseline=load('notification-preview')
    results['notification_preview']={'messages':len(preview.get('messages',[])),
        'passed':preview==baseline,'differences':[] if preview==baseline else ['完整通知JSON不同']}
    result={'schema_version':'sql_local_reconciliation.v1','batch_id':manifest['batch_id'],
        'candidate_ref':file_ref(candidate/'candidate.json',candidate,'application/json'),
        'database_ref':manifest['database'],'reference_binding':used,
        'passed':all(r['passed'] for r in results.values()),'results':results,
        'seconds':time.perf_counter()-start,'published':False}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',required=True);p.add_argument('--reference',required=True);p.add_argument('--output',required=True)
    result=reconcile(**vars(p.parse_args()))
    print(json.dumps({'passed':result['passed'],'results':{k:{f:v for f,v in r.items() if f in ('passed','checks','legacy_rows','sql_rows','messages')} for k,r in result['results'].items()}},ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
