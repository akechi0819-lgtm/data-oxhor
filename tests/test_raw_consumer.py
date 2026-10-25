from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
import json
import os
from pathlib import Path
import stat
import threading
from unittest.mock import patch
import pytest
from openpyxl import Workbook
from dashboard_product.shadow_bi.p5 import raw_consumer as c,raw_inputs as ri,raw_status as rs

DAY='2026-10-25'
COMPANY='workspace_bi_operations'

@pytest.fixture
def setup(tmp_path):
    roots={key:tmp_path/key for key in ('received_root','queue_root','work_root','status_root','baseline')}
    for root in roots.values():root.mkdir(mode=0o700)
    (roots['baseline']/'Work/StudyAbroad').mkdir(parents=True);ri.write(roots['baseline']/'Work/StudyAbroad/current.json',{'snapshot_id':'snapshot_fixture'});ri.write(roots['baseline']/'Work/workspace.json',{'company_id':COMPANY})
    manifest=tmp_path/'formal.json';ri.write(manifest,{'coverage':{'data_through':'2026-10-24'}})
    policy=c.Policy.from_mapping({'schema_version':c.SCHEMA,'company_id':COMPANY,**{k:str(v) for k,v in roots.items()},'current_manifest':str(manifest)})
    files={}
    for key in ri.FILES:
        p=tmp_path/(key+'.xlsx');w=Workbook();w.active.append(['id']);w.active.append([1]);w.save(p);w.close();files[key]=p
    def submit(batch='raw-consumer',day=DAY):
        archive=tmp_path/(batch+day+'.tar');ri.pack(files,archive,batch=batch,company=COMPANY,day=day)
        # Producer input state itself is not trusted by the consumer, only archive bytes.
        folder=roots['received_root']/batch;folder.mkdir(exist_ok=True);(folder/'payload.tar').write_bytes(archive.read_bytes())
        c.enqueue(roots['queue_root'],batch,ri.sha(archive))
        return batch
    return policy,files,submit


def prepared(policy,received,day):
    return {'status':'prepared','published':False,'library':'/private/library.duckdb','baseline':'secret-path','credential':'never-visible'}


def test_fixed_consumer_projects_only_status(setup):
    p,files,submit=setup;batch=submit()
    result=c.run_once(p,processor=prepared,day=DAY)
    assert result['batches']=={batch:'prepared'} and result['published'] is False
    public=rs.read(p.status_root,batch)
    assert set(public)=={'schema_version','batch_id','status','published'}
    assert 'secret' not in (p.status_root/(batch+'.json')).read_text()
    assert (p.status_root/(batch+'.json')).stat().st_mode & 0o777==0o640
    assert (p.queue_root/'.queue.lock').stat().st_mode & 0o777==0o660
    assert not (p.queue_root/batch).exists()
    assert (p.work_root/'inputs'/batch/'payload.tar').stat().st_mode & 0o222==0


def test_duplicate_terminal_never_calls_compute_again(setup):
    p,files,submit=setup;batch=submit();calls=[]
    def compute(*args):calls.append(1);return prepared(*args)
    c.run_once(p,processor=compute,day=DAY)
    digest=json.loads((p.work_root/'jobs'/(batch+'.json')).read_bytes())['archive_sha256']
    c.enqueue(p.queue_root,batch,digest)
    c.run_once(p,processor=compute,day=DAY)
    assert len(calls)==1 and rs.read(p.status_root,batch)['status']=='prepared'


def test_same_batch_changed_hash_does_not_replace_success(setup):
    p,files,submit=setup;batch=submit();c.run_once(p,processor=prepared,day=DAY)
    c.enqueue(p.queue_root,batch,'0'*64)
    with patch.object(c,'compute',side_effect=AssertionError('not called')):
        assert c.run_once(p,processor=lambda *a:pytest.fail('recompute'),day=DAY)['batches'][batch]=='rejected'
    assert rs.read(p.status_root,batch)['status']=='prepared'


def test_crash_after_compute_recovers_without_second_execution(setup):
    p,files,submit=setup;batch=submit();executions=[]
    class Crash(BaseException):pass
    def idempotent(policy,received,day):
        state=policy.work_root/'synthetic-compute.json'
        if not state.exists():executions.append(1);ri.write(state,{'status':'prepared','published':False})
        return json.loads(state.read_bytes())
    with pytest.raises(Crash):
        c.run_once(p,processor=idempotent,day=DAY,after_compute=lambda:(_ for _ in ()).throw(Crash()))
    assert rs.read(p.status_root,batch)['status']=='running'
    (p.queue_root/batch).unlink()  # Worker-owned journal recovers a disappeared queue marker.
    assert c.run_once(p,processor=idempotent,day=DAY)['batches'][batch]=='prepared'
    assert len(executions)==1


def test_crash_after_terminal_commit_repairs_public_projection(setup):
    p,files,submit=setup;batch=submit();c.run_once(p,processor=prepared,day=DAY)
    (p.status_root/(batch+'.json')).unlink()
    assert c.run_once(p,processor=lambda *a:pytest.fail('must not compute'),day=DAY)['status']=='drained'
    assert rs.read(p.status_root,batch)['status']=='prepared'


def test_concurrent_consumers_only_one_enters_processor(setup):
    p,files,submit=setup;submit();entered=threading.Event();release=threading.Event();calls=[]
    def slow(*args):calls.append(1);entered.set();assert release.wait(3);return prepared(*args)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(c.run_once,p,processor=slow,day=DAY)
        assert entered.wait(3)
        second=pool.submit(c.run_once,p,processor=slow,day=DAY)
        assert second.result(timeout=3)['status']=='busy'
        release.set();assert first.result(timeout=3)['status']=='drained'
    assert len(calls)==1


def test_busy_producer_retains_queue_for_bounded_restart(setup):
    p,files,submit=setup;batch=submit()
    def busy(*args):raise BlockingIOError()
    assert c.run_once(p,processor=busy,day=DAY)['status']=='busy'
    assert (p.queue_root/batch).exists() and rs.read(p.status_root,batch)['status']=='running'
    assert c.run_once(p,processor=prepared,day=DAY)['batches'][batch]=='prepared'


@pytest.mark.parametrize('outcome',['failed','timed_out','interrupted'])
def test_terminal_failures_never_requeue_or_publish(setup,outcome):
    p,files,submit=setup;batch=submit()
    assert c.run_once(p,processor=lambda *a:{'status':outcome,'published':False},day=DAY)['batches'][batch]==outcome
    assert rs.read(p.status_root,batch)['published'] is False
    assert not (p.queue_root/batch).exists()


@pytest.mark.parametrize('value',[
    {'status':'published','published':True},
    {'status':'prepared','published':True},
    {'status':'running','published':False},
    {'status':'/etc/passwd','published':False},
])
def test_invalid_compute_outcomes_fail_closed(setup,value):
    p,files,submit=setup;batch=submit()
    assert c.run_once(p,processor=lambda *a:value,day=DAY)['batches'][batch]=='failed'
    assert rs.read(p.status_root,batch)['error_code']=='compute_failed'


@pytest.mark.parametrize('attack',['traversal','mismatch','extra_command','symlink','fifo'])
def test_malicious_queue_never_executes_or_follows(setup,tmp_path,attack):
    p,files,submit=setup;outside=tmp_path/'outside.json';outside.write_text('must survive')
    target=p.queue_root/'raw-malicious'
    if attack=='symlink':target.symlink_to(outside)
    elif attack=='fifo':os.mkfifo(target)
    else:
        item={'batch_id':'raw-malicious','archive_sha256':'0'*64}
        if attack=='traversal':item['batch_id']='../../outside'
        elif attack=='mismatch':item['batch_id']='raw-other'
        else:item['command']='touch /arbitrary'
        ri.write(target,item)
    c.run_once(p,processor=lambda *a:pytest.fail('must not execute'),day=DAY)
    assert outside.read_text()=='must survive' and not target.exists()


@pytest.mark.parametrize('attack',['directory_link','archive_link','archive_fifo','hash_change','wrong_day'])
def test_untrusted_input_paths_are_frozen_or_rejected(setup,tmp_path,attack):
    p,files,submit=setup;batch=submit();folder=p.received_root/batch;payload=folder/'payload.tar'
    if attack=='directory_link':
        folder.rename(tmp_path/'redirect');folder.symlink_to(tmp_path/'redirect',target_is_directory=True)
    elif attack=='archive_link':
        payload.rename(tmp_path/'archive');payload.symlink_to(tmp_path/'archive')
    elif attack=='archive_fifo':payload.unlink();os.mkfifo(payload)
    elif attack=='hash_change':payload.write_bytes(b'changed')
    day='2026-10-26' if attack=='wrong_day' else DAY
    result=c.run_once(p,processor=lambda *a:pytest.fail('must not compute'),day=day)
    assert result['batches'][batch]=='rejected'
    assert rs.read(p.status_root,batch)['published'] is False


def test_policy_rejects_commands_and_overlapping_private_status_roots(setup):
    p,files,submit=setup
    mapping={'schema_version':c.SCHEMA,'company_id':COMPANY,**{name:str(getattr(p,name)) for name in c.POLICY_FIELDS-{'schema_version','company_id'}}}
    with pytest.raises(ValueError):c.Policy.from_mapping({**mapping,'command':'bash'})
    with pytest.raises(ValueError):c.Policy.from_mapping({**mapping,'status_root':str(p.work_root/'public')})


def test_status_rejects_private_fields_symlinks_and_fake_published(setup,tmp_path):
    p,files,submit=setup;batch='raw-visible'
    for extra in [{'library':'/private'}, {'published':True}, {'status':['bad']}]:
        value={'schema_version':rs.SCHEMA,'batch_id':batch,'status':'prepared','published':False,**extra}
        (p.status_root/(batch+'.json')).write_text(json.dumps(value))
        with pytest.raises(ValueError):rs.read(p.status_root,batch)
    outside=tmp_path/'secret';outside.write_text('secret')
    target=p.status_root/(batch+'.json');target.unlink();target.symlink_to(outside)
    with pytest.raises(OSError):rs.read(p.status_root,batch)


def test_receiver_reads_only_status_projection(setup):
    from flask import Flask
    from dashboard_product.shadow_bi.p5.raw_receiver import register
    p,files,submit=setup;batch=submit();c.run_once(p,processor=prepared,day=DAY)
    private=p.work_root/'runs'/batch;private.mkdir(parents=True);(private/'state.json').write_text('{"status":"prepared","credential":"private"}')
    app=Flask(__name__);register(app,authorized=lambda:True,context=lambda:(COMPANY,'2026-10-24'),received_root=p.received_root,queue_root=p.queue_root,status_root=p.status_root)
    response=app.test_client().get('/v1/raw-batches/'+batch)
    assert response.status_code==200 and 'private' not in response.get_data(as_text=True)
    assert response.json==rs.read(p.status_root,batch)


def test_changed_baseline_during_recovery_fails_closed(setup):
    p,files,submit=setup;batch=submit()
    def busy(*args):raise BlockingIOError()
    c.run_once(p,processor=busy,day=DAY)
    ri.write(p.baseline/'Work/StudyAbroad/current.json',{'snapshot_id':'snapshot_changed'})
    assert c.run_once(p,processor=lambda *a:pytest.fail('no mixed baseline'),day=DAY)['batches'][batch]=='rejected'


def test_invalid_business_workbook_rejected_before_history_copy(setup):
    p,files,submit=setup;batch=submit()
    result=c.run_once(p,day=DAY)
    assert result['batches'][batch]=='failed'
    assert not (p.work_root/'runs').exists()


def test_fixed_context_projects_only_cutoff_without_secret(tmp_path):
    from dashboard_product.shadow_bi.p5 import raw_context
    release=tmp_path/'releases/accepted';(release/'library').mkdir(parents=True)
    (tmp_path/'raw-control').mkdir();(tmp_path/'current').symlink_to(release)
    ri.write(release/'library/library_manifest.json',{'coverage':{'data_through':'2026-10-24'},'private':'not projected'})
    original_fstat=os.fstat
    def root_directory(fd):
        info=original_fstat(fd)
        if stat.S_ISDIR(info.st_mode):
            from types import SimpleNamespace
            return SimpleNamespace(st_uid=0,st_mode=info.st_mode)
        return info
    with patch.object(raw_context.os,'fchown') as chown,patch.object(raw_context.os,'fstat',side_effect=root_directory):
        value=raw_context.refresh(tmp_path,123)
    assert set(value)=={'schema_version','coverage','formal_manifest_sha256'} and 'private' not in json.dumps(value)
    chown.assert_called_once()
    assert (tmp_path/'raw-control/formal-context.json').stat().st_mode & 0o777==0o640


def test_fixed_context_rejects_nonrelease_pointer(tmp_path):
    from dashboard_product.shadow_bi.p5 import raw_context
    (tmp_path/'releases').mkdir();(tmp_path/'outside').mkdir();(tmp_path/'current').symlink_to(tmp_path/'outside')
    with pytest.raises(ValueError):raw_context.refresh(tmp_path,123)


def test_status_root_owner_mismatch_fails_closed(setup):
    p,files,submit=setup;batch=submit();c.run_once(p,processor=prepared,day=DAY)
    with pytest.raises(ValueError):rs.read(p.status_root,batch,owner_uid=os.getuid()+1000)


def test_worker_rejects_broad_private_directory(setup):
    p,files,submit=setup;p.work_root.chmod(0o755)
    with pytest.raises(ValueError,match='private work root'):c.run_once(p,processor=prepared,day=DAY)


def test_raw_enablement_reuses_existing_auth_before_disk(tmp_path,monkeypatch):
    import importlib.util
    monkeypatch.setenv('SHADOW_RECEIVER_RAW_ENABLED','1')
    monkeypatch.setenv('SHADOW_RECEIVER_TOKEN_SHA256',__import__('hashlib').sha256(b'fixture-only').hexdigest())
    from dashboard_product.shadow_bi.p5 import raw_receiver
    with patch.object(raw_receiver.pwd,'getpwnam',return_value=type('U',(),{'pw_uid':os.getuid()})()):
        path=Path(__file__).parents[1]/'dashboard_product/shadow_bi/p5/receiver.py'
        spec=importlib.util.spec_from_file_location('enabled_raw_fixture',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    client=module.app.test_client()
    for route in ['/v1/raw-batches','/v1/batches','/v1/notifications/jobs']:
        assert client.post(route,data=b'bad').status_code==401
    assert client.get('/v1/raw-batches/raw-unknown').status_code==401
    assert client.get('/health').status_code==200


def test_malicious_queue_directory_quarantined_without_following(setup,tmp_path):
    p,files,submit=setup;directory=p.queue_root/'raw-invalid-directory';directory.mkdir();(directory/'link').symlink_to(tmp_path/'outside')
    c.run_once(p,processor=lambda *a:pytest.fail('not a request'),day=DAY)
    assert not directory.exists()
    assert len(list(p.queue_root.glob('.rejected-directory-*')))==1


def test_deployment_keeps_complete_external_prefix():
    root=Path(__file__).parents[1]/'dashboard_product/shadow_bi/p5/deploy'
    text=(root/'raw-location.conf').read_text()
    assert 'location = /shadow-bi/v1/raw-batches {' in text
    assert 'location ^~ /shadow-bi/v1/raw-batches/ {' in text
    assert 'rewrite ^/shadow-bi/v1/raw-batches$ /v1/raw-batches break;' in text
    assert '127.0.0.1:18091' in text
    service=(root/'shadow-bi-raw-compute.service').read_text()
    assert 'User=shadowraw' in service and 'RestrictAddressFamilies=AF_UNIX' in service
    assert 'EnvironmentFile=' not in service and 'activate' not in service


def test_one_calculation_batch_per_service_lifetime(setup):
    p,files,submit=setup;submit('raw-first');submit('raw-second');calls=[]
    def actor(*args):calls.append(1);return prepared(*args)
    first=c.run_once(p,processor=actor,day=DAY)
    assert len(first['batches'])==1 and len(calls)==1
    assert len([v for v in p.queue_root.iterdir() if v.name.startswith('raw-')])==1
    second=c.run_once(p,processor=actor,day=DAY)
    assert len(second['batches'])==1 and len(calls)==2
