"""Run fixed SQL against the cloud warehouse's verified landing tables."""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile

from . import sql_daily

_CLOUD_ROOT = Path('/var/lib/shadow-bi')
_CODE = '/srv/shadow-bi/code'
_PYTHON = '/srv/shadow-bi/venv/bin/python'


def _request_path(name):
    if not re.fullmatch(r'daily-[A-Za-z0-9_-]{1,90}', name):
        raise ValueError('invalid foundation build release')
    return _CLOUD_ROOT/'sql-incoming'/(name+'-sql-build')


def _file_hash(path):
    return sql_daily.sha256_file(path)


def _release_coverage(pointer, source, candidate):
    coverage = deepcopy(pointer)
    business = source['coverage']
    current_start = min(business['orders_start'],business['cash_start'])
    coverage.update(coverage_start=current_start,orders_coverage_start=business['orders_start'],
                    cash_coverage_start=business['cash_start'],capacity_start=max('2026-06-01',current_start))
    through = candidate['through_date']
    activity = (f"活动按当前Snapshot可用历史累计；工单覆盖{business['orders_start']}至"
                f"{min(business['orders_end'],through)}，现金覆盖{business['cash_start']}至"
                f"{min(business['cash_end'],through)}，不保证覆盖活动完整生命周期。")
    scope = '工单、现金和去重人头汇总中，线上留学包含虚拟人，待确认归属只计留学总盘；'
    notices = ('SSC及待确认归属只计留学总盘，不计线上/线下留学团队；',
               '线上留学现金汇总包含线上虚拟人；留学及小语种现金总计剔除SSC；待确认归属只计留学总盘；',
               '工单、现金和去重人头汇总中，线上留学包含虚拟人，留学及小语种总计剔除SSC；待确认归属只计留学总盘；')
    notes = []
    for note in coverage['notes']:
        if not note.startswith('活动按当前Snapshot可用历史累计；'):
            for notice in notices:
                note = note.replace(notice,scope)
            notes.append(note)
    coverage['notes'] = [*notes,activity]
    return coverage


def prepare_remote_business(*, workspace, day, pair, run_id, release_id, attempt,
                            candidate_dir, ssh, ssh_env, command, command_result,
                            current_state, advertising_manifest, code_dir=_CODE,
                            migration_override=None, comparison_contract=None):
    """Send SQL build rules and changes to landing, never a database or Snapshot."""
    from business_data_mcp.build_context import build_bundle
    from dashboard_product.shadow_bi.sql_warehouse.build import prepare_sealed_build_inputs

    if advertising_manifest is not None and json.loads(Path(advertising_manifest).read_text()) != {'sources':[]}:
        raise ValueError('business publication requires fees to be ingested separately')
    if code_dir != _CODE and code_dir != f'/srv/shadow-bi/.cutover-{release_id}/code':
        raise ValueError('invalid fixed cloud SQL source directory')
    pointer, _, baseline, sealed, migration, contract_sha = current_state
    if migration_override is not None:
        migration,contract_sha = migration_override
    snapshots = {'training':pair['sources']['bi']['snapshot_id'],'abroad':pair['sources']['study_abroad']['snapshot_id']}
    job = _request_path(release_id)
    attempt = Path(attempt)
    inputs = attempt/'build-inputs'
    prepare_sealed_build_inputs(workspace=workspace,sealed_candidate=sealed/'candidate.json',
                                output_dir=inputs,comparison_contract=comparison_contract)
    rules = {name:base64.b64encode((inputs/name).read_bytes()).decode('ascii')
             for name in ('build-inputs.json','scorecard.json','empty-fees.json')}
    request = {'release':release_id,'batch':run_id,'as_of':day,'old':pointer['release'],
               'snapshots':snapshots,'build_inputs':rules,'business_context':build_bundle(workspace=Path(workspace)),
               'coverage':pointer['coverage'],'previous_warehouse_sha256':pointer['warehouse_sha256'],
               'catalogue_sha256':migration['catalogue_sha256'],'contract_sha256':contract_sha}
    if snapshots != baseline['snapshots']:
        from .landing_sync import local_changes

        index = command_result(ssh+[_cloud_command(code_dir,'--index',pointer['release'],pointer['warehouse_sha256'])],
                               attempt/'cloud-landing-index.log',text=True,env=ssh_env)
        patch,metadata,landing,coverage = local_changes(workspace=Path(workspace),snapshots=snapshots,day=day,
            batch_id=run_id,output=attempt,index=index,old_release=pointer['release'],old_sha=pointer['warehouse_sha256'])
        request.update(delta=patch,landing_metadata=metadata,landing_contract=landing,source_coverage=coverage)
        sql_daily._atomic_json(attempt/'delta-summary.json',{
            name:{'changed_values':len(table['values']),'removed_rows':sum(table['removed'].values()),'rows':len(table['order'])}
            for name,table in patch['tables'].items()})
    _upload_request(job,request,attempt,ssh,ssh_env,command)
    return _run_and_fetch(job,request,attempt,candidate_dir,ssh,ssh_env,command_result,code_dir)


def prepare_remote_costs(*, workspace, day, pair, run_id, release_id, attempt,
                         candidate_dir, ssh, ssh_env, command, command_result,
                         current_state, costs):
    """Send only approved expense rows for the currently sealed business inputs."""
    pointer, _, _, _, migration, contract_sha = current_state
    request = {'release':release_id,'batch':run_id,'as_of':day,'old':pointer['release'],
               'snapshots':{'training':pair['sources']['bi']['snapshot_id'],
                            'abroad':pair['sources']['study_abroad']['snapshot_id']},
               'coverage':pointer['coverage'],'previous_warehouse_sha256':pointer['warehouse_sha256'],
               'catalogue_sha256':migration['catalogue_sha256'],'contract_sha256':contract_sha,'costs':costs}
    job = _request_path(release_id)
    attempt = Path(attempt)
    _upload_request(job,request,attempt,ssh,ssh_env,command)
    return _run_and_fetch(job,request,attempt,candidate_dir,ssh,ssh_env,command_result,_CODE)


def _upload_request(job,request,attempt,ssh,ssh_env,command):
    setup = f'umask 077; mkdir -p {shlex.quote(str(job.parent))}; mkdir {shlex.quote(str(job))}; cat > {shlex.quote(str(job/"request.json"))}'
    command(ssh[:1]+['-C']+ssh[1:]+[setup],attempt/'cloud-request.log',input=json.dumps(request,default=str),text=True,env=ssh_env)


def _cloud_command(code_dir,*args):
    return (f'set -eu; set -a; . /etc/shadow-bi.env; set +a; cd {shlex.quote(code_dir)}; '
            f'{_PYTHON} -m dashboard_product.shadow_bi.p5.cloud_foundation {shlex.join(args)}')


def _run_and_fetch(job,request,attempt,candidate_dir,ssh,ssh_env,command_result,code_dir):
    release_id,run_id = request['release'],request['batch']
    call = _cloud_command(code_dir,release_id)
    staged = command_result(ssh+[call],attempt/'cloud-sql-build.log',text=True,env=ssh_env)
    if staged.get('status')!='prepared' or staged.get('release')!=release_id or staged.get('batch_id')!=run_id:
        raise ValueError('invalid cloud foundation build receipt')
    sql_daily._atomic_json(attempt/'cloud-sql-build.json',staged)
    result_archive = attempt/'cloud-result.tar'
    with result_archive.open('wb') as result, (attempt/'cloud-result-transfer.log').open('w') as errors:
        subprocess.run(ssh[:1]+['-C']+ssh[1:]+[f'cat {shlex.quote(str(job/"result/sql-release.tar"))}'],
                       stdout=result,stderr=errors,check=True,env=ssh_env)
    if _file_hash(result_archive)!=staged['archive_sha256']:
        raise ValueError('cloud SQL result archive hash mismatch')
    sql_daily._validate_archive(result_archive,release_id)
    destination = attempt/'releases'
    destination.mkdir()
    with tarfile.open(result_archive) as packaged:
        packaged.extractall(destination,filter='data')
    release_root = destination/release_id
    from dashboard_product.shadow_bi.p4.sql_release import load_release
    release_manifest,candidate,database = load_release(release_root/'library')
    if (candidate['batch_id']!=run_id or _file_hash(database)!=staged['warehouse_sha256']
            or release_manifest['superset_catalogue']['sha256']!=request['catalogue_sha256']):
        raise ValueError('retrieved cloud SQL candidate did not match server receipt')
    candidate_dir = Path(candidate_dir)
    candidate_dir.mkdir(parents=True)
    for item in ('candidate.json','warehouse.duckdb','notification-preview.json'):
        shutil.copyfile(release_root/'library'/item,candidate_dir/item)
    return {'prepared':staged,'local_release_root':release_root,'candidate':candidate,
            'release_manifest':release_manifest,'source':staged['source']}


def build_on_server(release_id):
    from dashboard_product.shadow_bi.p5.sql_bundle import prepare_release
    from dashboard_product.shadow_bi.sql_warehouse.build import build_from_sealed
    from data_platform.sql_release_query import resolve_sql_release

    os.umask(0o077)
    job = _request_path(release_id)
    request = json.loads((job/'request.json').read_text())
    if request['release']!=release_id or not re.fullmatch(r'run_[A-Za-z0-9_-]{3,72}',request['batch']):
        raise ValueError('invalid cloud SQL build identity')
    old = (_CLOUD_ROOT/'current').resolve(strict=True)
    if old.parent!=_CLOUD_ROOT/'releases' or old.name!=request['old']:
        raise ValueError('current cloud release changed before SQL build')
    old_library = old/'library'
    if _file_hash(old_library/'warehouse.duckdb')!=request['previous_warehouse_sha256']:
        raise ValueError('cloud expense baseline does not match the current release')
    batch,day = request['batch'],request['as_of']
    candidate_dir = job/'candidate'
    sealed = resolve_sql_release(old)
    if not sealed or ('delta' not in request and sealed.candidate['snapshots']!=request['snapshots']):
        raise ValueError('云端当前基础表身份不匹配')
    old_manifest = json.loads((old_library/'release.json').read_text())
    landing = {'descriptions':sealed.landing_description,'provenance':sealed.landing_provenance,
               'semantics':old_manifest['semantics'],'business_context':old_manifest['business_context']}
    if 'costs' in request:
        from decimal import Decimal
        from ops.costs import build_cost_candidate

        if sealed.candidate['as_of_date']!=day:
            raise ValueError('fee update does not match the current business Snapshot')
        costs = request['costs']
        for row in costs['rows']:
            if row['amount'] is not None:
                row['amount'] = Decimal(row['amount'])
        candidate = build_cost_candidate(baseline_dir=old_library,output_dir=candidate_dir,costs=costs,batch_id=batch)
    else:
        landing['business_context'] = request['business_context']
        if 'delta' not in request and landing['business_context']['manifest']['source_sha256']['bridge']!=landing['semantics']['Work/Bridge/reference.json']:
            raise ValueError('直接重算的已批准 Bridge 与云端封存版本不符')
        inputs = job/'build-inputs'
        inputs.mkdir()
        rules = request['build_inputs']
        if set(rules)!= {'build-inputs.json','scorecard.json','empty-fees.json'}:
            raise ValueError('invalid fixed SQL build inputs')
        for name,value in rules.items():
            (inputs/name).write_bytes(base64.b64decode(value,validate=True))
        updates = metadata = None
        if 'delta' in request:
            from data_acquisition.transfer.sql_landing_delta import apply_delta
            from .landing_sync import read_cloud_rows

            with tempfile.TemporaryDirectory(prefix='landing-read-',dir=job) as temporary:
                old_rows=read_cloud_rows(old,old.name,sealed.batch_id,Path(temporary))
                updates=apply_delta(old_rows,request['delta'],expected_release=old.name,
                                    expected_warehouse_sha256=request['previous_warehouse_sha256'])
            metadata=request['landing_metadata']
            if metadata['snapshots']!=request['snapshots']:
                raise ValueError('基础表增量后的批次身份不符')
            landing=request['landing_contract']
        candidate = build_from_sealed(sealed_library=old_library,output_dir=candidate_dir,batch_id=batch,
                                     as_of_date=day,config_root=Path.cwd(),build_inputs=inputs,
                                     **({'landing_updates':updates,'landing_metadata':metadata} if updates is not None else {}))
    source = {'source_order_receipts':candidate['source_order_receipts']}
    coverage = (_release_coverage(request['coverage'],{'coverage':request['source_coverage']},candidate)
                if 'source_coverage' in request else request['coverage'])
    coverage['notes'] = [note.replace('，留学及小语种总计剔除SSC','') for note in coverage['notes']]
    acceptance = {'mode':'runtime_contract','migration_acceptance':{'sha256':request['contract_sha256']},
                  'runtime_contract':{'status':'passed','catalogue_sha256':request['catalogue_sha256'],
                                      'candidate_identity_passed':True,'source_gates_passed':True}}
    result = prepare_release(candidate=candidate_dir,workspace=job,release_id=release_id,output_dir=job/'result',
        coverage_template=coverage,acceptance=acceptance,landing_contract=landing)
    library = Path(result['library'])
    if _file_hash(library/'superset-catalogue.json')!=request['catalogue_sha256']:
        raise ValueError('server-generated SQL catalogue differs from the approved contract')
    if resolve_sql_release(library.parent) is None:
        raise ValueError('server-generated SQL release is unavailable to the controlled query service')
    if (_CLOUD_ROOT/'current').resolve(strict=True)!=old:
        raise ValueError('current cloud release changed during SQL build')
    target = _CLOUD_ROOT/'releases'/release_id
    # Repository code builds in a private directory; only the derived runtime library is installed.
    if target.exists():
        raise ValueError('cloud SQL target release already exists')
    library.parent.rename(target)
    target.chmod(0o755)
    (target/'library').chmod(0o755)
    for path in (target/'library').iterdir():
        path.chmod(0o644)
    (candidate_dir/'warehouse.duckdb').unlink()
    (candidate_dir/'notification-preview.json').unlink()
    return {'status':'prepared','release':release_id,'batch_id':batch,'warehouse_sha256':candidate['database']['sha256'],
            'archive_sha256':result['archive_sha256'],'source':source,'foundation_snapshots':request['snapshots'],
            'uploaded_database_files':0,
            'computed_on':'cloud_fixed_sql','mode':'costs' if 'costs' in request else 'business'}


def cloud_landing_index(release_id,warehouse_sha):
    from data_acquisition.transfer.sql_landing_delta import make_index
    from data_platform.sql_release_query import resolve_sql_release
    from .landing_sync import read_cloud_rows

    release = (_CLOUD_ROOT/'current').resolve(strict=True)
    if release.parent!=_CLOUD_ROOT/'releases' or release.name!=release_id:
        raise ValueError('current changed before landing index')
    sealed=resolve_sql_release(release)
    if not sealed or _file_hash(sealed.warehouse)!=warehouse_sha:
        raise ValueError('current warehouse differs from landing index request')
    with tempfile.TemporaryDirectory(prefix='landing-index-',dir=_CLOUD_ROOT/'sql-incoming') as temporary:
        return make_index(read_cloud_rows(release,release_id,sealed.batch_id,Path(temporary)),
                          release=release_id,warehouse_sha256=warehouse_sha)


if __name__=='__main__':
    result=cloud_landing_index(*sys.argv[2:]) if sys.argv[1]=='--index' else build_on_server(sys.argv[1])
    print(json.dumps(result,ensure_ascii=False))
