"""P2：同批源输入重算业务库；只连接新建派生库，不直接连接客户Snapshot。"""
from __future__ import annotations
import argparse
from datetime import date, timedelta, datetime, UTC
from pathlib import Path
import hashlib
import json
import re
import shutil
import sys

import duckdb
from data_platform.query.evidence import encode, file_ref
from dashboard_product.management.calculation import calculate
from dashboard_product.online_team.build import ROOT, read, sha, write
from dashboard_product.management.aggregate import _roster


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def table_digest(rows):
    # SQL relations are unordered; preserve multiplicity, ignore physical row order.
    h=hashlib.sha256()
    for row in sorted(encode(r) for r in rows): h.update(row+b'\n')
    return h.hexdigest()


def source_files(workspace):
    # Bind only immutable input closure, not new query evidence produced by rebuild.
    files=[p for folder in ('Work','Input') for p in (workspace/folder).rglob('*') if p.is_file()]
    pointer=read(workspace/'Work/StudyAbroad/current.json')
    lineage=read(workspace/pointer['source_lineage'])
    history=lineage.get('normalized_history',{})
    for run_id in history.get('query_run_ids',{}).values():
        files.extend(p for p in (workspace/'Output/StudyAbroad/历史查询回执'/run_id).rglob('*') if p.is_file())
    return sorted(set(files))


def code_files():
    roots = ['dashboard_product/management', 'dashboard_product/online_team',
             'dashboard_product/config', 'workspace_modeling/operations',
             'data_acquisition/jobs', 'data_platform/query', 'data_platform/business_library.py',
             'dashboard_product/shadow_bi/library.py', 'dashboard_product/shadow_bi/acquisition.py', 'interfaces/business_library.py',
             'dashboard_product/shadow_bi/p5/raw_inputs.py', 'dashboard_product/shadow_bi/p5/raw_compute.py',
             'dashboard_product/shadow_bi/p5/raw_receiver.py']
    paths = []
    for root in roots:
        p = ROOT/root
        paths.extend([p] if p.is_file() else p.rglob('*'))
    paths += [ROOT/'dashboard_product/refresh.py', ROOT/'dashboard_product/fallback_mapping.py', ROOT/'pyproject.toml']
    return sorted(set(p for p in paths if p.is_file() and p.suffix in {'.py','.sql','.json','.toml'}))


def binding(workspace):
    return {'inputs': {p.relative_to(workspace).as_posix():sha(p) for p in source_files(workspace)},
            'rules': {p.relative_to(ROOT).as_posix():sha(p) for p in code_files()}}


def initialize(frozen_workspace, target):
    """Explicit new copy without old Output, preventing cached old result consumption."""
    if target.exists():
        raise ValueError('输入副本已存在；请选择新的workspace目录')
    target.mkdir(parents=True)
    for name in ('Work','Input'):
        shutil.copytree(frozen_workspace/name, target/name)
    history = Path('Output/StudyAbroad/历史查询回执')
    if (frozen_workspace/history).is_dir():
        shutil.copytree(frozen_workspace/history,target/history)
    expected = {p.relative_to(frozen_workspace).as_posix():sha(p) for p in source_files(frozen_workspace)}
    actual = {p.relative_to(target).as_posix():sha(p) for p in source_files(target)}
    if expected != actual:
        raise ValueError('同批源输入副本摘要不一致')
    write(target.parent/'input-copy.json', {'source':str(frozen_workspace),'workspace':str(target),
                                           'files':actual, 'copied_legacy_dashboard_output':False,'historical_query_evidence':True})


def relative_paths(value,workspace):
    if isinstance(value,dict): return {k:relative_paths(v,workspace) for k,v in value.items()}
    if isinstance(value,list): return [relative_paths(v,workspace) for v in value]
    if isinstance(value,str) and value.startswith(str(workspace)+'/'): return value[len(str(workspace))+1:]
    return value


def tables(model):
    public, online = model['public'], model['online_data']
    result = {'facts':model['facts'], 'personnel_facts':model['person_facts'], 'contributions':model['personnel_details']['records'],
              'pending_contributions':model['personnel_details']['pending'],
              'marker_diagnostics':model['personnel_details']['marker_diagnostics'],
              'training_source_rows':model['training_rows'], 'order_source_rows':model['order_rows'],
              'market_orders':model['market_order_rows'], 'new_student_cash':model['new_student_cash_rows'],
              'activities':public['activities'], 'people':_roster(model['people'],model['abroad_people']),
              'periods':[], 'team_periods':[], 'person_periods':[], 'selection_team_periods':[],
              'capacity_people':[], 'radar_axes':[], 'online_lines':[], 'online_daily':[],
              'online_platforms':[], 'online_groups':[]}
    for p in public['periods']:
        result['periods'].append({k:v for k,v in p.items() if k!='teams'})
        for t in p['teams']:
            result['team_periods'].append({'period_id':p['id'],'team_id':t['id'], 'view':t})
            for mode, container in [('performance',t),('calendar',t.get('person_calendar',{}))]:
                for person in container.get('people',[]):
                    for state, view in person.get('order_status_views',{}).items():
                        result['person_periods'].append({'period_id':p['id'],'team_id':t['id'],
                            'month_mode':mode,'state':state,'person_name':person['name'],
                            'window_start':container.get('person_start'),'window_end':container.get('person_through'),
                            'view':view,'person':{k:v for k,v in person.items() if k!='order_status_views'}})
    for selection, periods in model['segments'].items():
        for p in periods:
            result['selection_team_periods'].append({'selection':selection,'period_id':p['id'],'view':p})
    for p in public['capacity']['periods']:
        for person in p['people']:
            for state, view in person['order_status_views'].items():
                result['capacity_people'].append({'period_id':p['id'],'person_name':person['name'],
                    'state':state,'view':view,'person':{k:v for k,v in person.items() if k!='order_status_views'},
                    'coverage':p['coverage']})
    for person in public['capacity']['radar']['people']:
        for axis in person['radar']['axes']:
            result['radar_axes'].append({'person_name':person['name'],'through_date':public['capacity']['radar']['through_date'],**axis})
    for p in online['periods']:
        for line_id, line in p['lines'].items():
            result['online_lines'].append({'period_id':p['id'],'business_line':line_id,'view':line})
            for channel in line.get('channels',[]):
                result['online_platforms'].append({'period_id':p['id'],'business_line':line_id,**channel})
            for group in line.get('groups',[]):
                result['online_groups'].append({'period_id':p['id'],'business_line':line_id,**group})
        result['online_daily'].extend({'period_id':p['id'],**r} for r in p['daily'])
    for field, name in [('school_name','schools'),('first_channel','channels')]:
        values = {(f['business_line'], f.get(field)) for f in model['facts']}
        result[name] = [{'dimension_id':digest([line,value]),'business_line':line,'name':value}
                        for line,value in sorted(values,key=str)]
    days=[]
    start=date.fromisoformat(model['public']['metadata']['coverage_start'])
    end=model['through']
    from workspace_modeling.operations.personnel import date_to_perf_month
    while start<=end:
        days.append({'event_date':start.isoformat(),'calendar_month':start.isoformat()[:7],
                     'performance_month':date_to_perf_month(start.isoformat())})
        start+=timedelta(days=1)
    result['calendar']=days
    out=model['out']
    costs=read(out/'advertising_sources.json')
    result['expense_rows']=costs['rows']; result['expense_sources']=relative_paths(costs['sources'],model['workspace'])
    result['advertising_rollup']=read(out/'advertising_result.json')
    result['platform_audit']=read(out/'platform_classification_audit.json')
    # Official scorecard remains an external reference; never import its rows.
    refs=[]
    for path in model['sources']:
        path=Path(path)
        if path.suffix=='.json' and ('targets' in path.name or path.name=='people.json' or path.name=='offline_market_people.json'):
            refs.append({'name':path.name,'sha256':sha(path),'document':read(path)})
    result['target_roster_references']=refs
    history=model['personnel_details'].get('history')
    result['personnel_history']=[{'document':{**history,'source_path':str(Path(history['source_path']).relative_to(model['workspace']))}}] if history is not None else []
    result['coverage']=[{'business_line':'training',**model['coverage']},
                        {'business_line':'abroad',**public['metadata']['study_abroad_source']}]
    return result


def write_table(connection, root, name, rows):
    """Lossless row_json plus scalar columns for actual filters, grouping and drilldown."""
    columns=sorted({key for row in rows for key in row})
    types={}
    for key in columns:
        values=[r[key] for r in rows if r.get(key) is not None]
        if values and all(isinstance(v,bool) for v in values): typ='BOOLEAN'
        elif values and all(type(v) is int for v in values): typ='BIGINT'
        elif key in {'value','amount','cash','spend','roi_cash','roi_spend'} and values and all(isinstance(v,(int,float)) or re.fullmatch(r'-?\d+(\.\d+)?',str(v)) for v in values): typ='DECIMAL(24,2)'
        elif values and all(isinstance(v,(int,float)) for v in values): typ='DOUBLE'
        elif key in {'event_date','start_date','end_date','through_date','window_start','window_end'} and values and all(re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(v)) for v in values): typ='DATE'
        else: typ='VARCHAR'
        types[key]=typ
    types['row_json']='JSON'
    def scalar(v):
        return encode(v).decode() if isinstance(v,(dict,list)) else v
    data=root/'tables'/f'{name}.jsonl'; data.parent.mkdir(exist_ok=True)
    with data.open('wb') as f:
        for row in rows:
            f.write(encode({**{k:scalar(row.get(k)) for k in columns},'row_json':row})+b'\n')
    def quote(text): return "'"+text.replace("'","''")+"'"
    schema='{'+','.join(quote(k)+':'+quote(t) for k,t in types.items())+'}'
    if rows:
        connection.execute(f'CREATE TABLE queries."{name}" AS SELECT * FROM read_json(?, columns={schema}, format=\'newline_delimited\')',[str(data)])
    else:
        connection.execute(f'CREATE TABLE queries."{name}" (row_json JSON)')
    return {'rows':len(rows),'logical_sha256':table_digest(rows),'columns':types,
            'data':file_ref(data,root,'application/x-ndjson')}


def build(args):
    ws=args.workspace.resolve(); out=ws/'Output/ShadowBI'/args.run_id
    if out.exists(): raise ValueError('拒绝覆盖既有业务库批次；使用新的run-id')
    before=binding(ws)
    model=calculate(args,output_area='ShadowBI')
    from dashboard_product.shadow_bi.acquisition import scoped_tables
    scope_values=scoped_tables(model)
    after=binding(ws)
    if before!=after: raise ValueError('计算期间输入或规则发生变化')
    library=out/'library'; library.mkdir()
    db=library/'business.duckdb'
    # Roster team_ids is a frozenset in the existing rule function.
    values={**tables(model), **scope_values}
    if getattr(args, 'server_complete', False):
        from dashboard_product.management.capacity_radar import build_radar
        values['radar_people']=build_radar(model['person_facts'], model['people'], model['abroad_people'], model['through'], read(ROOT/'dashboard_product/config/capacity_targets.json'))
    with duckdb.connect(str(db)) as connection:
        connection.execute('CREATE SCHEMA queries')
        receipts={}
        # Normalize one relation at a time instead of duplicating the entire model in JSON.
        for name, rows in values.items():
            normalized=json.loads(json.dumps(rows,ensure_ascii=False,default=lambda v:sorted(v) if isinstance(v,(set,frozenset)) else str(v)))
            receipts[name]=write_table(connection,library,name,normalized)
            del normalized
        connection.execute('CREATE TABLE queries.batch (batch_id VARCHAR)')
        connection.execute('INSERT INTO queries.batch VALUES (?)',[args.run_id])
    # Record actual source queries, not a synthetic successful query receipt.
    from data_platform.query.evidence import verify_receipt
    source_queries=[]
    pointer=read(ws/'Work/StudyAbroad/current.json')
    lineage=read(ws/pointer['source_lineage'])
    historical_runs=set(lineage.get('normalized_history',{}).get('query_run_ids',{}).values())
    for p in sorted(ws.joinpath('Output').rglob('receipt.json')):
        if library in p.parents: continue
        # Output也含呈现层的business_query回执；只校验本批及显式历史来源。
        candidate=read(p)
        candidate_run=candidate.get('run_id','')
        if not (candidate_run.startswith(args.run_id+'_') or candidate_run in historical_runs): continue
        doc,_=verify_receipt(p)
        source_queries.append({'path':p.relative_to(ws).as_posix(),'sha256':sha(p),
                               'snapshot_ref':doc['snapshot_ref'],'relations':doc['referenced_relations'],
                               'source_ids':doc['referenced_source_ids']})
    if binding(ws)!=before: raise ValueError('业务库封口前输入或规则发生变化')
    manifest={'schema_version':'business_query_library.v1','batch_id':args.run_id,
        'created_at':datetime.now(UTC).isoformat(),'as_of_date':args.as_of_date,
        'snapshots':{'training':args.snapshot_id,'abroad':args.study_abroad_snapshot_id},
        'coverage':model['public']['metadata'], 'binding':before,'source_queries':source_queries,
        'tables':receipts,'database':file_ref(db,library,'application/vnd.duckdb'),
        'official_reference_policy':'官方记分卡仅绑定外部文件摘要，覆盖内优先；不导入库、不补齐、不回写目标。'}
    write(library/'library_manifest.json',manifest)
    # Save calculated business sections for full finite-combination reconciliation.
    # This is generated from model, never read by the business build.
    validation=out/'calculated';validation.mkdir()
    for name,value in [('public',model['public']),('selections',model['segments']),
                       ('online',model['online_data']),('personnel',model['personnel_details']),
                       ('diagnostics',model['diagnostics'])]: write(validation/f'{name}.json',value)
    print(json.dumps({'status':'built','batch_id':args.run_id,'library':str(library),
                      'tables':{k:v['rows'] for k,v in receipts.items()},'source_queries':len(source_queries)},ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('copy-inputs'); init.add_argument('--frozen-workspace',type=Path,required=True);init.add_argument('--workspace',type=Path,required=True)
    b=sub.add_parser('build');b.add_argument('--workspace',type=Path,required=True);b.add_argument('--snapshot-id',required=True)
    b.add_argument('--study-abroad-snapshot-id',required=True);b.add_argument('--run-id',required=True);b.add_argument('--as-of-date',required=True)
    a=p.parse_args()
    if a.command=='copy-inputs':initialize(a.frozen_workspace.resolve(),a.workspace.resolve())
    else:build(a)

if __name__=='__main__': main()
