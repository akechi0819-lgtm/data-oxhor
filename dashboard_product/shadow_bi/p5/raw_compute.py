"""Private offline producer. Receives no commands/paths from an HTTP payload; never activates BI."""
from __future__ import annotations
import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from dashboard_product.shadow_bi.p5.raw_inputs import BATCH, FILES, sha, write, validate_manifest

ROOT = Path(__file__).resolve().parents[3]


def limits():
    """Private worker runtime; applied before imports and inherited by query subprocesses."""
    import duckdb
    original=duckdb.connect
    def connect(*args, **kwargs):
        config=dict(kwargs.get('config') or {}); locked=config.pop('lock_configuration',None)
        config.update(memory_limit='256MB',threads='2',temp_directory=os.environ['OXHOR_RAW_TMP'],max_temp_directory_size='512MB')
        kwargs['config']=config
        con=original(*args,**kwargs);con.execute('SET enable_progress_bar = false')
        if locked in (True,'true','True'):con.execute('SET lock_configuration = true')
        return con
    duckdb.connect=connect


def gates(library, batch, day, expected=None):
    from data_platform.business_library import load_library, execute_library_query, read_library_result
    m,_,_=load_library(library,batch)
    if len(m['tables'])!=39 or m['as_of_date']!=day:raise ValueError('incomplete business library')
    from datetime import date,timedelta
    if m['coverage']['data_through']!=(date.fromisoformat(day)-timedelta(days=1)).isoformat():raise ValueError('business cutoff mismatch')
    for key,spec in m['tables'].items():
        rel=Path(spec['data']['path'])
        if rel.is_absolute() or '..' in rel.parts or sha(library/rel)!=spec['data']['sha256']:raise ValueError('sealed table changed')
    # Controlled business queries verify physical counts and batch; no raw DuckDB connection.
    sql=' UNION ALL '.join('SELECT '+str(i)+' AS n, COUNT(*) AS rows FROM queries."'+name+'"' for i,name in enumerate(m['tables']))
    result=execute_library_query(library=library,batch_id=batch,sql=sql,run_id=batch.replace('raw-','run_raw_')+'_gate',output_root=library.parent/'gates',max_rows=40)
    actual=read_library_result(result,output_root=library.parent/'gates')['rows']
    counts={int(n):int(rows) for n,rows in actual}
    if any(counts[i]!=spec['rows'] for i,spec in enumerate(m['tables'].values())):raise ValueError('physical counts mismatch')
    comparison=None
    if expected:
        ref=json.loads(expected.read_bytes())
        if set(ref['tables'])!=set(m['tables']):raise ValueError('reference table set differs')
        comparison={name:all(m['tables'][name][k]==ref['tables'][name][k] for k in ('rows','logical_sha256')) for name in m['tables']}
        if not all(comparison.values()):
            write(library.parent/'comparison.json',comparison)
            raise ValueError('same-source reconciliation failed')
    return {'tables':39,'physical_counts_verified':True,'same_source_comparison':comparison,'manifest_sha256':sha(library/'library_manifest.json')}



def run_names(day, archive_sha256):
    # Leave room for existing _personnel_history_resources and other query suffixes.
    suffix=day.replace('-','')+'_'+archive_sha256[:12]
    return suffix, 'run_shadow_daily_'+suffix, 'run_business_'+suffix

def child(received, baseline, output, expected, resume_sources=False):
    from dashboard_product.shadow_bi.library import initialize, binding, build
    from data_acquisition.jobs.daily_warehouses import refresh_daily,assert_daily_ready
    m=json.loads((received/'manifest.json').read_bytes())
    ws=output/'workspace'
    before=binding(baseline)
    suffix,run,business_run=run_names(m['as_of_date'],sha(received/'payload.tar'))
    if resume_sources:
        previous=json.loads((output/'baseline-binding.json').read_bytes())
        if before['inputs']!=previous['inputs']:raise ValueError('baseline inputs changed since failed attempt')
        pair=assert_daily_ready(ws,m['as_of_date'])
        from data_acquisition.jobs.daily_warehouses import _canonical_sha256
        expected_bi=_canonical_sha256({key:m['files'][key]['sha256'] for key in ('orders','cash')})
        if pair['sources']['bi']['value_sha256']!=expected_bi or pair['sources']['study_abroad']['value_sha256']!=m['files']['tencent']['sha256']:
            raise ValueError('prepared sources differ from immutable input batch')
        write(output/'resumed-source-pair.json',pair)
    else:
        write(output/'baseline-binding.json',before)
        initialize(baseline,ws)
        config=json.loads((ws/'Work/workspace.json').read_bytes())
        if config['company_id']!=m['company_id']:raise ValueError('baseline company mismatch')
        paths={}
        for key,rel in FILES.items():
            target=output/'capture'/key/m['files'][key]['filename'];target.parent.mkdir(parents=True)
            shutil.copyfile(received/rel,target)
            if sha(target)!=m['files'][key]['sha256']:raise ValueError('received source changed')
            paths[key]=target
        pair=refresh_daily(workspace=ws,as_of_date=m['as_of_date'],run_id=run,
            bi_snapshot_id='snapshot_bi_operations_'+suffix,study_snapshot_id='snapshot_study_abroad_'+suffix,
            doc_id='',page_url='',cookie_file=Path('/dev/null'),input_paths=paths)
        write(output/'pair.json',pair)
        if pair['status']!='passed':raise ValueError('dual Snapshot quality/identity gate failed')
        pair=assert_daily_ready(ws,m['as_of_date'])
    # Explicit quality result through the controlled platform, after both ingests.
    from data_platform.query.service import quality_issues
    for key,warehouse,snapshot in [
        ('bi',ws/json.loads((ws/'Work/workspace.json').read_bytes())['current_warehouse_path'],pair['sources']['bi']['snapshot_id']),
        ('study',ws/json.loads((ws/'Work/StudyAbroad/current.json').read_bytes())['warehouse'],pair['sources']['study_abroad']['snapshot_id'])]:
        result=quality_issues(warehouse=warehouse,snapshot_id=snapshot,run_id='run_quality_'+key+'_'+suffix,output_root=output/'quality',max_rows=10000)
        write(output/('quality-'+key+'.json'),result)
        # quality_issues returns the controlled query evidence; inspect the returned result.
        from data_platform.query.evidence import read_query_result
        data=read_query_result(result,output_root=output/'quality')
        if data['rows']:raise ValueError('Snapshot quality issues require review')
    args=SimpleNamespace(workspace=ws,snapshot_id=pair['sources']['bi']['snapshot_id'],study_abroad_snapshot_id=pair['sources']['study_abroad']['snapshot_id'],run_id=business_run,as_of_date=m['as_of_date'],server_complete=True)
    build(args)
    library=ws/'Output/ShadowBI'/args.run_id/'library'
    public=json.loads((library.parent/'calculated/public.json').read_bytes())
    metrics=[]
    for period in public['periods']:
        for team in period['teams']:
            for line, values in team.get('lines',{}).items():
                for metric,value in values.items():
                    if isinstance(value,dict) and 'actual' in value:metrics.append([period['id'],team['id'],line,metric,value['actual']])
    metric_check={'metrics':len(metrics),'actual':metrics}
    if expected and (expected.parent/'expected-key-metrics.json').is_file():
        metric_check['match']=metrics==json.loads((expected.parent/'expected-key-metrics.json').read_bytes())
        if not metric_check['match']:raise ValueError('same-source business metrics differ')
    write(output/'key-metrics.json',metric_check)
    checked=gates(library,args.run_id,m['as_of_date'],expected)
    if binding(baseline)!=before:raise ValueError('baseline changed during isolated update')
    for key,rel in FILES.items():
        if sha(received/rel)!=m['files'][key]['sha256']:raise ValueError('immutable source changed')
    write(output/'prepared.json',{'status':'prepared','published':False,'library':str(library),'batch_id':args.run_id,'baseline_unchanged':True,'gates':checked})


def run(*, received, baseline, root, day, company, minimum_cutoff, expected=None, timeout=1500, resume_sources=False):
    """One global producer lock. Retry uses a fresh batch; stale running is interrupted, not success."""
    if not BATCH.fullmatch(received.name):raise ValueError('invalid received batch')
    m=validate_manifest(json.loads((received/'manifest.json').read_bytes()),company=company,day=day,minimum_cutoff=minimum_cutoff)
    if m['batch_id']!=received.name:raise ValueError('received identity mismatch')
    receipt=json.loads((received/'received.json').read_bytes())
    if receipt['archive_sha256']!=sha(received/'payload.tar'):raise ValueError('received archive changed')
    for key,rel in FILES.items():
        if sha(received/rel)!=m['files'][key]['sha256']:raise ValueError('received input changed')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (root/'.producer.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Inherit the lock through the child, so a killed supervisor cannot permit a second producer.
        os.set_inheritable(lock.fileno(),True)
        out=root/m['batch_id'];state=out/'state.json'
        identity={'archive_sha256':receipt['archive_sha256'],'baseline':str(baseline.resolve()),'expected':sha(expected) if expected else None}
        if resume_sources and not state.is_file():raise ValueError('source resume requires a recorded failed attempt')
        if out.exists():
            result=json.loads(state.read_bytes())
            if result['identity']!=identity:raise ValueError('compute identity changed')
            if result['status']=='running':
                result.update(status='interrupted',published=False);write(state,result)
            if result['status']=='prepared':
                from dashboard_product.shadow_bi.library import binding
                if binding(baseline)['inputs']!=json.loads((out/'baseline-binding.json').read_bytes())['inputs']:raise ValueError('baseline identity changed')
                if sha(out/'prepared.json')!=result['prepared_sha256']:raise ValueError('prepared receipt changed')
                prepared=json.loads((out/'prepared.json').read_bytes())
                if not Path(prepared['library']).resolve().is_relative_to((out/'workspace/Output/ShadowBI').resolve()):raise ValueError('prepared library escaped output')
                gates(Path(prepared['library']),prepared['batch_id'],day,expected)
            if not resume_sources or result['status']!='failed':return result
            write(out/('failed-attempt-'+str(time.time_ns())+'.json'),result)
        if shutil.disk_usage(root).free < 5*1024**3:raise ValueError('need 4GiB working budget plus 1GiB reserve')
        out.mkdir(exist_ok=resume_sources);(out/'tmp').mkdir(exist_ok=resume_sources);(out/'runtime').mkdir(exist_ok=resume_sources)
        result={'status':'running','published':False,'batch_id':m['batch_id'],'identity':identity,'started_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
        write(state,result);started=time.monotonic()
        try:
            from dashboard_product.shadow_bi.p5.raw_inputs import stage
            verified=stage(received/'payload.tar',out/'verified',company=company,day=day,minimum_cutoff=minimum_cutoff)
            if verified['archive_sha256']!=receipt['archive_sha256']:raise ValueError('input changed while freezing')
            received=out/'verified'/m['batch_id']
            (out/'runtime/sitecustomize.py').write_text('from dashboard_product.shadow_bi.p5.raw_compute import limits\nlimits()\n')
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(out/'runtime')+os.pathsep+str(ROOT),OXHOR_RAW_TMP=str(out/'tmp'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
            cmd=[sys.executable,'-m',__name__ if __name__!='__main__' else 'dashboard_product.shadow_bi.p5.raw_compute','_child','--received',str(received),'--baseline',str(baseline),'--output',str(out)]
            if expected:cmd+=['--expected',str(expected)]
            if resume_sources:cmd+=['--resume-sources']
            with (out/'compute.log').open('w') as log:
                proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,pass_fds=(lock.fileno(),))
                try:rc=proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                    result['status']='timed_out';rc=None
                if rc==0 and (out/'prepared.json').is_file():result.update(status='prepared',prepared_sha256=sha(out/'prepared.json'))
                elif rc is not None:result.update(status='failed',returncode=rc)
        except BaseException as error:
            if 'proc' in locals() and proc.poll() is None:
                os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            result.update(status='interrupted' if isinstance(error,(KeyboardInterrupt,SystemExit)) else 'failed',error_type=type(error).__name__)
            raise
        finally:
            result['elapsed_seconds']=round(time.monotonic()-started,3);write(state,result)
        return result


def recheck(*, output, received, baseline, expected):
    """Maintenance-only recovery of an already sealed failed candidate; never recalculate."""
    from dashboard_product.shadow_bi.library import binding
    from data_acquisition.jobs.daily_warehouses import assert_daily_ready, _canonical_sha256
    from data_platform.business_library import load_library
    with (output.parent/'.producer.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=json.loads((output/'state.json').read_bytes())
        if state['status']!='failed':raise ValueError('recheck requires a failed sealed candidate')
        m=json.loads((received/'manifest.json').read_bytes())
        if sha(received/'payload.tar')!=state['identity']['archive_sha256']:raise ValueError('source archive changed')
        for key,rel in FILES.items():
            if sha(received/rel)!=m['files'][key]['sha256']:raise ValueError('source input changed')
        if binding(baseline)['inputs']!=json.loads((output/'baseline-binding.json').read_bytes())['inputs']:raise ValueError('baseline inputs changed')
        pair=assert_daily_ready(output/'workspace',m['as_of_date'])
        if (pair['sources']['bi']['value_sha256']!=_canonical_sha256({key:m['files'][key]['sha256'] for key in ('orders','cash')})
                or pair['sources']['study_abroad']['value_sha256']!=m['files']['tencent']['sha256']):raise ValueError('source pair changed')
        _,_,batch=run_names(m['as_of_date'],state['identity']['archive_sha256'])
        library=output/'workspace/Output/ShadowBI'/batch/'library'
        manifest,_,_=load_library(library,batch)
        if manifest['snapshots']!={'training':pair['sources']['bi']['snapshot_id'],'abroad':pair['sources']['study_abroad']['snapshot_id']}:raise ValueError('sealed Snapshot pair changed')
        metric=json.loads((output/'key-metrics.json').read_bytes())
        wanted=json.loads((expected.parent/'expected-key-metrics.json').read_bytes())
        if metric['actual']!=wanted:raise ValueError('key metrics mismatch')
        checked=gates(library,batch,m['as_of_date'],expected)
        prepared={'status':'prepared','published':False,'library':str(library),'batch_id':batch,'baseline_unchanged':True,'gates':checked,
                  'recovery':'sealed candidate rechecked against explicit replay reference; no ingest or business recompute',
                  'original_failure_state_sha256':sha(output/'state.json')}
        write(output/('failed-before-recheck-'+str(time.time_ns())+'.json'),state)
        write(output/'prepared.json',prepared)
        state.update(status='prepared',prepared_sha256=sha(output/'prepared.json'),rechecked=True)
        state['identity']['expected']=sha(expected)
        write(output/'state.json',state)
        return prepared


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');b=sub.add_parser('_child')
    for parser in (a,b):
        parser.add_argument('--received',required=True,type=Path);parser.add_argument('--baseline',required=True,type=Path);parser.add_argument('--expected',type=Path);parser.add_argument('--resume-sources',action='store_true')
    a.add_argument('--root',required=True,type=Path);a.add_argument('--company',required=True);a.add_argument('--day',default=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat());a.add_argument('--minimum-cutoff',required=True);a.add_argument('--timeout',type=int,default=1500)
    b.add_argument('--output',required=True,type=Path)
    c=sub.add_parser('recheck')
    for name in ('output','received','baseline','expected'):c.add_argument('--'+name,required=True,type=Path)
    args=vars(p.parse_args());mode=args.pop('command')
    if mode=='recheck':print(json.dumps(recheck(**args),ensure_ascii=False));return
    if mode=='_child':child(**args);return
    result=run(**args);print(json.dumps(result,ensure_ascii=False));sys.exit(0 if result['status']=='prepared' else 1)

if __name__=='__main__':main()
