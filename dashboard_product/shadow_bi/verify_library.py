"""P2独立核验：Agent通过受控入口读库；P0旧输出只在此对账，构建不读取。"""
from __future__ import annotations
import argparse
from collections import Counter
from decimal import Decimal
from pathlib import Path
import hashlib
import json
from data_platform.business_library import execute_library_query,read_library_result,describe_library
from data_platform.query.evidence import encode
from dashboard_product.online_team.build import read,write,sha


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True,allow_nan=False,default=str).encode()).hexdigest()


def table_digest(rows):
    h=hashlib.sha256()
    for row in sorted(encode(r) for r in rows): h.update(row+b'\n')
    return h.hexdigest()


def sorted_rows(rows):return sorted(rows,key=lambda r:encode(r))


def compare(label,left,right,checks):
    if left!=right:
        # Store a bounded concrete mismatch; never rewrite baseline to make it pass.
        raise AssertionError(f'{label} 不同: expected_sha={digest(left)}, actual_sha={digest(right)}')
    checks.append({'label':label,'status':'matched','sha256':digest(left)})


def canonical(value):
    if isinstance(value,dict):return {k:canonical(v) for k,v in value.items() if k not in {'source_path'}}
    if isinstance(value,list):return [canonical(v) for v in value]
    return value


def verify(a):
    evidence=a.evidence.resolve()
    if evidence.exists():raise ValueError('拒绝覆盖既有验收记录')
    evidence.mkdir(parents=True)
    checks=[];responses=[]
    description=describe_library(library=a.library,batch_id=a.batch_id)
    write(evidence/'description.json',description)
    manifest=read(a.library/'library_manifest.json')
    n=0
    def query(sql,params=None,max_rows=2000):
        nonlocal n;n+=1
        r=execute_library_query(library=a.library,batch_id=a.batch_id,sql=sql,parameters=params,
            run_id=f'run_p2_verify_{n:04}',output_root=evidence/'queries',max_rows=max_rows,max_result_bytes=200_000_000)
        responses.append(r);return read_library_result(r,output_root=evidence/'queries')
    def table(name):
        count=query(f'SELECT COUNT(*) FROM queries."{name}"')['rows'][0][0]
        size=3 if name=='selection_team_periods' else 10 if name in {'team_periods','periods'} else 2000
        rows=[]
        for offset in range(0,count,size):
            data=query(f'SELECT row_json FROM queries."{name}" ORDER BY rowid LIMIT ? OFFSET ?',[size,offset],max_rows=size)
            rows.extend(json.loads(r[0]) for r in data['rows'])
        compare(name+'库中逐行摘要',manifest['tables'][name]['logical_sha256'],table_digest(rows),checks)
        compare(name+'行数',manifest['tables'][name]['rows'],count,checks)
        return rows
    try:
        baseline=a.p0/'workspace/Output/DashboardManagement/run_shadow_p0_20261022'
        old=read(baseline/'shared_result.json');details=read(baseline/'details.json')
        facts=table('facts')
        compare('逐事实身份及全部字段',sorted_rows(details['records']),sorted_rows(facts),checks)
        ids=[r['fact_id'] for r in facts];compare('事实身份唯一',len(ids),len(set(ids)),checks)
        work_ids=[r['work_order_id'] for r in facts if r['metric']=='orders' and r.get('work_order_id')]
        compare('逐工单跨线无重复',len(work_ids),len(set(work_ids)),checks)
        # Compare money and distinct identities by line, metric, team, business group, day.
        def totals(rows):
            g={}
            for r in rows:
                k=tuple(r.get(f) for f in ['business_line','metric','team_id','business_group','event_date'])
                if k not in g:g[k]=[Decimal(0),set(),[]]
                g[k][0]+=Decimal(str(r['value']))
                if r.get('student_id'):g[k][1].add(r['student_id'])
                g[k][2].append(r['fact_id'])
            return {str(k):[str(v[0]),sorted(v[1]),sorted(v[2])] for k,v in g.items()}
        compare('逐日团队业务组金额与身份域',totals(details['records']),totals(facts),checks)
        compare('原精度逐笔人员贡献',sorted_rows(details['personnel_contribution']['records']),sorted_rows(table('contributions')),checks)
        compare('待核贡献',details['personnel_contribution']['pending'],table('pending_contributions'),checks)
        compare('跨线标记未归属例外',sorted_rows(details['personnel_contribution']['marker_diagnostics']),sorted_rows(table('marker_diagnostics')),checks)
        compare('活动全累计',old['activities'],table('activities'),checks)
        expected=[{'period_id':p['id'],'team_id':t['id'],'view':t} for p in old['periods'] for t in p['teams']]
        compare('全部17期间×6管理单元（含人员、双月模式、四状态及固定分母）',expected,table('team_periods'),checks)
        expected=[{'selection':mask,'period_id':p['id'],'view':p} for mask,periods in old['prep_high_selections'].items() for p in periods]
        compare('全部7业务组选择×17期间',expected,table('selection_team_periods'),checks)
        out=a.library.parent
        calculated=read(out/'calculated/public.json')
        for key in ('periods','activities','capacity','reconciliation'):
            compare('新计算/P0 '+key,old[key],calculated[key],checks)
        compare('线上（全部期间/平台/费用/共同窗口）',read(baseline/'online_shared_result.json')['periods'],read(out/'calculated/online.json')['periods'],checks)
        for key in ('records','pending','marker_diagnostics','diagnostics'):
            left=details['personnel_contribution'][key];right=read(out/'calculated/personnel.json')[key]
            compare('贡献诊断 '+key,sorted_rows(left) if isinstance(left,list) else left,sorted_rows(right) if isinstance(right,list) else right,checks)
        compare('历史汇总（来源路径另绑定）',canonical(details['personnel_contribution']['history']),canonical(table('personnel_history')[0]['document']),checks)
        # Every remaining table is actually queried and checked against its build digest.
        read_names={r['label'].removesuffix('库中逐行摘要') for r in checks if r['label'].endswith('库中逐行摘要')}
        for name in manifest['tables']:
            if name not in read_names:table(name)
        # Native SQL numeric and identity checks, independent of JSON payload roundtrip.
        sql_totals=query("SELECT business_line,metric,CAST(SUM(value) AS VARCHAR),COUNT(*),COUNT(DISTINCT student_id) FROM queries.facts GROUP BY business_line,metric ORDER BY 1,2")
        grouped={}
        for f in facts:
            k=(f['business_line'],f['metric']);v=grouped.setdefault(k,[Decimal(0),0,set()]);v[0]+=Decimal(str(f['value']));v[1]+=1
            if f.get('student_id') is not None:v[2].add(f['student_id'])
        for line,metric,amount,count,heads in sql_totals['rows']:
            v=grouped[(line,metric)]
            compare(f'SQL金额/人头 {line}/{metric}',[v[0],v[1],len(v[2])],[Decimal(amount),count,heads],checks)
        write(evidence/'sql-totals.json',sql_totals)
        # Verify immutable P0 artifacts against their original manifests; don't run its verifier.
        freeze=read(a.p0/'freeze.json');bad=[]
        for entry in freeze['files']:
            p=a.p0/entry['copy']
            if not p.is_file() or sha(p)!=entry['sha256']:bad.append(str(p))
        for entry in read(a.p0/'output-manifest.json')['files']:
            p=a.p0/entry['path']
            if not p.is_file() or sha(p)!=entry['sha256']:bad.append(str(p))
        compare('P0冻结输入源码及输出摘要',[],bad,checks)
        result={'status':'passed','batch_id':a.batch_id,'checks':checks,'controlled_queries':n,
                'facts':len(facts),'contributions':len(details['personnel_contribution']['records']),
                'external_differences':{'status':'open','guanyuan':[160,23,20]},'study_abroad_through':'2026-10-13'}
        write(evidence/'verification.json',result);print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False))
    except Exception as exc:
        write(evidence/'verification.json',{'status':'failed','checks':checks,'error':str(exc),'controlled_queries':n})
        raise
    finally:write(evidence/'query-responses.json',responses)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--library',type=Path,required=True);p.add_argument('--batch-id',required=True);p.add_argument('--p0',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True)
    verify(p.parse_args())
if __name__=='__main__':main()
