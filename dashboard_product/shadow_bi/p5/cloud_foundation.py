"""Build a staged dashboard release on the cloud host from explicit foundation inputs."""
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

from . import sql_daily

_CLOUD_ROOT = Path('/var/lib/shadow-bi')
_CODE = '/srv/shadow-bi/code'
_PYTHON = '/srv/shadow-bi/venv/bin/python'


def _request_path(name):
    if not re.fullmatch(r'daily-[A-Za-z0-9_-]{1,90}', name):
        raise ValueError('invalid foundation build release')
    return _CLOUD_ROOT/'sql-incoming'/(name+'-foundation')


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
    """Upload two foundations; retrieve only the result of the server-side SQL build."""
    from data_acquisition.transfer.sql_foundation import prepare_sql_foundation

    if advertising_manifest is not None and json.loads(Path(advertising_manifest).read_text()) != {'sources':[]}:
        raise ValueError('business publication requires fees to be ingested separately')
    if code_dir != _CODE and code_dir != f'/srv/shadow-bi/.cutover-{release_id}/code':
        raise ValueError('invalid fixed cloud SQL source directory')
    pointer, _, _, _, migration, contract_sha = current_state
    if migration_override is not None:
        migration,contract_sha = migration_override
    snapshots = {'training':pair['sources']['bi']['snapshot_id'],'abroad':pair['sources']['study_abroad']['snapshot_id']}
    job = _request_path(release_id)
    attempt = Path(attempt)
    bundle = attempt/'foundation.tar'
    description = prepare_sql_foundation(workspace,training_snapshot=snapshots['training'],
                                       abroad_snapshot=snapshots['abroad'],output_path=bundle,
                                       comparison_contract=comparison_contract)
    request = {'release':release_id,'batch':run_id,'as_of':day,'old':pointer['release'],
               'snapshots':snapshots,'foundation_sha256':description['sha256'],
               'coverage':pointer['coverage'],'previous_warehouse_sha256':pointer['warehouse_sha256'],
               'catalogue_sha256':migration['catalogue_sha256'],'contract_sha256':contract_sha}
    _upload_request(job,request,attempt,ssh,ssh_env,command)
    with bundle.open('rb') as stream:
        command(ssh[:1]+['-C']+ssh[1:]+[f'umask 077; cat > {shlex.quote(str(job/"foundation.tar"))}'],
                attempt/'foundation-transfer.log',stdin=stream,env=ssh_env)
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
    command(ssh+[setup],attempt/'cloud-request.log',input=json.dumps(request,default=str),text=True,env=ssh_env)


def _run_and_fetch(job,request,attempt,candidate_dir,ssh,ssh_env,command_result,code_dir):
    release_id,run_id = request['release'],request['batch']
    call = (f'set -eu; set -a; . /etc/shadow-bi.env; set +a; cd {shlex.quote(code_dir)}; '
            f'{_PYTHON} -m dashboard_product.shadow_bi.p5.cloud_foundation {shlex.quote(release_id)}')
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
    evidence_archive = attempt/'cloud-source-evidence.tar'
    with evidence_archive.open('wb') as evidence, (attempt/'cloud-evidence-transfer.log').open('w') as errors:
        subprocess.run(ssh[:1]+['-C']+ssh[1:]+[f'cat {shlex.quote(str(job/"source-evidence.tar"))}'],
                       stdout=evidence,stderr=errors,check=True,env=ssh_env)
    if _file_hash(evidence_archive)!=staged['evidence_sha256']:
        raise ValueError('cloud source evidence archive hash mismatch')
    with tarfile.open(evidence_archive) as packaged:
        if any(Path(item.name).parts[0] not in ('source-evidence','source-order')
               or not (item.isfile() or item.isdir()) for item in packaged.getmembers()):
            raise ValueError('unexpected cloud source evidence member')
        packaged.extractall(candidate_dir,filter='data')
    from data_platform.query.evidence import read_query_result
    for ref in candidate['source_queries']:
        read_query_result(ref,output_root=candidate_dir/'source-evidence')
    source = dict(staged['source'])
    source['source_order_receipts'] = [str(candidate_dir/Path(item).relative_to(job))
                                       for item in source['source_order_receipts']]
    if not all(Path(path).is_file() for path in source['source_order_receipts']):
        raise ValueError('cloud source traversal receipts are missing')
    return {'prepared':staged,'local_release_root':release_root,'candidate':candidate,
            'release_manifest':release_manifest,'source':source}


def build_on_server(release_id):
    from data_acquisition.transfer.sql_foundation import extract_sql_foundation
    from dashboard_product.shadow_bi.p5.sql_bundle import prepare_release
    from dashboard_product.shadow_bi.sql_warehouse.build import build_local

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
    if 'costs' in request:
        from decimal import Decimal
        from ops.costs import build_cost_candidate

        previous_job = _request_path(old.name)
        origin = json.loads((previous_job/'foundation-origin.json').read_text())
        origin_job = _request_path(origin['release'])
        workspace = origin_job/'foundation/workspace'
        old_manifest = json.loads((old_library/'candidate.json').read_text())
        if old_manifest['snapshots']!=request['snapshots'] or old_manifest['as_of_date']!=day:
            raise ValueError('fee update does not match the current business Snapshot')
        baseline = job/'baseline'
        baseline.mkdir()
        for name in ('candidate.json','warehouse.duckdb','notification-preview.json'):
            os.link(old_library/name,baseline/name)
        (baseline/'source-evidence').symlink_to(origin_job/'candidate/source-evidence',target_is_directory=True)
        costs = request['costs']
        for row in costs['rows']:
            if row['amount'] is not None:
                row['amount'] = Decimal(row['amount'])
        candidate = build_cost_candidate(baseline_dir=baseline,output_dir=candidate_dir,costs=costs,batch_id=batch)
        shutil.copytree(origin_job/'source-order',job/'source-order')
        source = {'source_order_receipts':[str(job/Path(item).relative_to(origin_job))
                                          for item in old_manifest['source_order_receipts']]}
        coverage = request['coverage']
    else:
        foundation = extract_sql_foundation(job/'foundation.tar',expected_sha256=request['foundation_sha256'],
                                           output_dir=job/'foundation')
        if foundation['snapshots']!=request['snapshots']:
            raise ValueError('cloud foundation Snapshot identities differ')
        workspace = Path(foundation['workspace'])
        origin = {'release':release_id,'sha256':request['foundation_sha256']}
        source = sql_daily.source_order_receipts(workspace=workspace,training_snapshot=request['snapshots']['training'],
                                               as_of_date=day,batch_id=batch,output_root=job/'source-order')
        blank = job/'no-new-expenses.json'
        sql_daily._atomic_json(blank,{'sources':[]})
        candidate = build_local(workspace=workspace,output_dir=candidate_dir,batch_id=batch,
            training_snapshot=request['snapshots']['training'],abroad_snapshot=request['snapshots']['abroad'],
            as_of_date=day,config_root=Path.cwd(),source_order_receipts=source['source_order_receipts'],
            expense_baseline=old_library,advertising_manifest=blank)
        coverage = _release_coverage(request['coverage'],source,candidate)
    sql_daily._atomic_json(job/'foundation-origin.json',origin)
    acceptance = {'mode':'runtime_contract','migration_acceptance':{'sha256':request['contract_sha256']},
                  'runtime_contract':{'status':'passed','catalogue_sha256':request['catalogue_sha256'],
                                      'candidate_identity_passed':True,'source_gates_passed':True}}
    result = prepare_release(candidate=candidate_dir,workspace=workspace,release_id=release_id,output_dir=job/'result',
        coverage_template=coverage,acceptance=acceptance)
    library = Path(result['library'])
    if _file_hash(library/'superset-catalogue.json')!=request['catalogue_sha256']:
        raise ValueError('server-generated SQL catalogue differs from the approved contract')
    if (_CLOUD_ROOT/'current').resolve(strict=True)!=old:
        raise ValueError('current cloud release changed during SQL build')
    target = _CLOUD_ROOT/'releases'/release_id
    evidence_archive = job/'source-evidence.tar'
    with tarfile.open(evidence_archive,'w') as evidence:
        evidence.add(candidate_dir/'source-evidence',arcname='source-evidence')
        evidence.add(job/'source-order',arcname='source-order')
    # Repository code builds in a private directory; only the derived runtime library is installed.
    if target.exists():
        raise ValueError('cloud SQL target release already exists')
    library.parent.rename(target)
    target.chmod(0o755)
    (target/'library').chmod(0o755)
    for path in (target/'library').iterdir():
        path.chmod(0o644)
    return {'status':'prepared','release':release_id,'batch_id':batch,'warehouse_sha256':candidate['database']['sha256'],
            'archive_sha256':result['archive_sha256'],'source':source,'foundation_sha256':origin['sha256'],
            'evidence_sha256':_file_hash(evidence_archive),'foundation_snapshots':request['snapshots'],
            'computed_on':'cloud_fixed_sql','mode':'costs' if 'costs' in request else 'business'}


if __name__=='__main__':
    print(json.dumps(build_on_server(sys.argv[1]),ensure_ascii=False))
