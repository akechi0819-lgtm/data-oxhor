from datetime import datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import duckdb
import pytest
from openpyxl import Workbook
from flask import Flask
from dashboard_product.shadow_bi.p5 import raw_publish as rp,raw_inputs as ri,raw_status as rs,publish_status as ps,source_completion as sc
from dashboard_product.shadow_bi.p5.raw_receiver import register
from dashboard_product.shadow_bi.p5.raw_compute import run_names
from dashboard_product.shadow_bi.library import write_table
from data_platform.query.evidence import file_ref
from data_acquisition.jobs.daily_warehouses import _canonical_sha256

@pytest.fixture
def case(tmp_path,monkeypatch):
    day=datetime.now(ZoneInfo('Asia/Shanghai')).date();cutoff=(day-timedelta(days=1)).isoformat();day=day.isoformat();batch='raw-publish-fixture'
    for name in ['raw-inputs','raw-status','raw-publish-pending','raw-publish-status','raw-publish','raw-control','incoming','releases','raw-compute/runs']:
        (tmp_path/name).mkdir(parents=True,mode=0o700)
    (tmp_path/'raw-compute/runs/.producer.lock').touch()
    old=tmp_path/'releases/daily-old';(old/'library').mkdir(parents=True)
    ri.write(old/'library/library_manifest.json',{'coverage':{'data_through':cutoff}})
    (tmp_path/'current').symlink_to(old)
    ri.write(tmp_path/'raw-control/receiver-policy.json',{'company_id':'workspace_bi_operations'})
    ri.write(tmp_path/'raw-control/policy.json',{'baseline':'synthetic-old-baseline'})
    paths={}
    for key in ri.FILES:
        p=tmp_path/(key+'.xlsx');w=Workbook();w.active.append(['synthetic']);w.save(p);w.close();paths[key]=p
    archive=tmp_path/'inputs.tar';ri.pack(paths,archive,batch=batch,company='workspace_bi_operations',day=day)
    ri.stage(archive,tmp_path/'raw-inputs',company='workspace_bi_operations',day=day,minimum_cutoff=cutoff)
    received=tmp_path/'raw-inputs'/batch
    completion_root=tmp_path/'raw-control/source-completion';completion_root.mkdir(mode=0o700)
    completion_folder=completion_root/batch;completion_folder.mkdir(mode=0o700)
    expected=sc.binding(received)
    reviewed_at=datetime.now(ZoneInfo('Asia/Shanghai'))
    approval={'schema_version':sc.SCHEMA,'binding':expected,'reviewed_at':reviewed_at.isoformat(),'sources':{}}
    for key in ('orders','cash'):
        body=('SYNTHETIC TEST ONLY completion watermark '+key).encode()
        (completion_folder/(key+'.evidence')).write_bytes(body)
        approval['sources'][key]={'kind':'upstream_completion_watermark','source_id':{'orders':'br_work_orders','cash':'br_cash'}[key],
                                  'complete_through':cutoff,'evidence_sha256':hashlib.sha256(body).hexdigest()}
    ri.write(completion_folder/'approval.json',approval)
    monkeypatch.setattr(sc,'ROOT',completion_root)
    original_load=sc._load
    # Keep the real protected-file/parser checks while adapting the fixture owner to this test process.
    monkeypatch.setattr(sc,'_load',lambda root,binding:original_load(root,binding,owner_uid=os.geteuid(),now=reviewed_at))
    decision,completion=sc.resolve(received)
    assert completion is not None
    archive_sha=ri.sha(archive);suffix,_,business=run_names(day,archive_sha)
    work=tmp_path/'raw-compute/runs'/batch;library=work/'workspace/Output/ShadowBI'/business/'library';library.mkdir(parents=True)
    db=library/'business.duckdb'
    with duckdb.connect(str(db)) as con:
        con.execute('CREATE SCHEMA queries');con.execute('CREATE TABLE queries.batch(batch_id VARCHAR)');con.execute('INSERT INTO queries.batch VALUES (?)',[business])
        tables={f'fixture_{i}':write_table(con,library,f'fixture_{i}',[{'value':i}]) for i in range(39)}
    snapshots={'training':'snapshot_bi_operations_'+suffix,'abroad':'snapshot_study_abroad_'+suffix}
    manifest={'schema_version':'business_query_library.v1','as_of_date':day,'batch_id':business,'coverage':{'data_through':cutoff,'source_completion':completion.metadata()},'snapshots':snapshots,
              'tables':tables,'database':file_ref(db,library,'application/vnd.duckdb'),'binding':{'inputs':{'fixture':'a'*64},'rules':{'fixture':'b'*64}},'source_queries':[{'snapshot_ref':{'snapshot_id':snapshots['training']}}]}
    ri.write(library/'library_manifest.json',manifest)
    ri.write(work/'prepared.json',{'library':str(library),'batch_id':business,'gates':{'tables':39,'physical_counts_verified':True,'manifest_sha256':ri.sha(library/'library_manifest.json')}})
    ri.write(work/'coverage-decision.json',decision)
    ri.write(work/'state.json',{'status':'prepared','published':False,'identity':{'archive_sha256':archive_sha},'prepared_sha256':ri.sha(work/'prepared.json')})
    ri.write(work/'pair.json',{'status':'passed','as_of_date':day,'sources':{'bi':{'value_sha256':_canonical_sha256({k:ri.sha(paths[k]) for k in ['orders','cash']})},'study_abroad':{'value_sha256':ri.sha(paths['tencent'])}}})
    for key,snapshot in [('bi',snapshots['training']),('study',snapshots['abroad'])]:ri.write(work/('quality-'+key+'.json'),{'status':'passed','snapshot_id':snapshot,'errors':[],'result':{'rows':[]}})
    rs.publish(tmp_path/'raw-status',batch,'prepared')
    marker={'batch_id':batch,'as_of_date':day,'expected_current_sha256':ri.sha(old/'library/library_manifest.json')}
    def enqueue():ri.write(tmp_path/'raw-publish-pending'/batch,marker)
    calls=[]
    def activate(target):
        actual=(tmp_path/'current').resolve()
        calls.append(target.name);p=tmp_path/'next';p.symlink_to(target);p.replace(tmp_path/'current')
        if target!=actual:
            prev=tmp_path/'previous';prev.unlink(missing_ok=True);prev.symlink_to(actual)
    monkeypatch.setattr(rp,'prepare_baseline',lambda *args:tmp_path/'synthetic-new-baseline')
    monkeypatch.setattr(rp,'set_baseline',lambda *args:None)
    monkeypatch.setattr(rp,'activate',activate);monkeypatch.setattr(rp,'seal_release',lambda p:None)
    monkeypatch.setattr(rp,'verify_daily',lambda p:ri.write(p,{'status':'passed','metrics_compared':18}))
    monkeypatch.setattr(rp,'PUBLISH_LOCK',tmp_path/'publisher.lock')
    return tmp_path,batch,work,library,old,marker,enqueue,calls,manifest


def test_fixed_publish_rebuilds_39_and_deletes_old_only_after_verification(case):
    base,batch,work,library,old,marker,enqueue,calls,manifest=case;enqueue()
    with rp.publication_locks(base):result=rp.publish_one(base,batch)
    assert result['status']=='published' and result['published'] is True
    target=(base/'current').resolve();assert target.name==result['release']
    assert not old.exists() and not (base/'previous').exists()
    rebuilt=json.loads((target/'library/library_manifest.json').read_bytes())
    assert rebuilt['server_rebuild']['verified_tables']==39
    assert ps.read(base/'raw-publish-status',batch,os.geteuid())['published'] is True
    assert calls==[target.name]
    enqueue();rp.publish_one(base,batch);assert calls==[target.name]
    assert not (base/'raw-publish-pending'/batch).exists()


def test_failed_native_verification_restores_then_preserves_old(case,monkeypatch):
    base,batch,work,library,old,_,enqueue,calls,_=case;enqueue()
    monkeypatch.setattr(rp,'verify_daily',lambda p:(_ for _ in ()).throw(RuntimeError('synthetic HTTP failure')))
    result=rp.publish_one(base,batch)
    assert result['status']=='publish_failed' and result['published'] is False
    assert (base/'current').resolve()==old and old.is_dir()
    assert calls[-1]==old.name and len(calls)==2
    assert not (base/'previous').is_symlink()
    enqueue();rp.publish_one(base,batch);assert len(calls)==2


@pytest.mark.parametrize('bad',['not_prepared','source_changed','quality','pair','cutoff','table','table_link','current_changed'])
def test_preflight_failure_never_activates(case,bad):
    base,batch,work,library,old,marker,enqueue,calls,manifest=case
    if bad=='not_prepared':ri.write(work/'state.json',{'status':'failed'})
    elif bad=='source_changed':
        p=base/'raw-inputs'/batch/'inputs/cash.xlsx';p.chmod(0o600);p.write_bytes(b'changed')
    elif bad=='quality':ri.write(work/'quality-bi.json',{'status':'failed'})
    elif bad=='pair':ri.write(work/'pair.json',{'status':'failed'})
    elif bad=='cutoff':
        manifest['coverage']['data_through']='2026-01-01';ri.write(library/'library_manifest.json',manifest)
    elif bad in ['table','table_link']:
        p=library/'tables/fixture_0.jsonl'
        if bad=='table':p.write_bytes(b'changed')
        else:p.unlink();p.symlink_to(base/'raw-control/receiver-policy.json')
    else:marker['expected_current_sha256']='0'*64
    enqueue();result=rp.publish_one(base,batch)
    assert result['status']=='publish_failed' and (base/'current').resolve()==old and old.exists() and calls==[]


@pytest.mark.parametrize('bad',[
    'approval_missing','approval_changed','approval_hash','decision_missing','decision_changed',
    'manifest_missing','manifest_changed','uploaded_forgery',
])
def test_source_completion_integrity_failure_never_activates(case,bad):
    base,batch,work,library,old,marker,enqueue,calls,manifest=case
    approval_path=base/'raw-control/source-completion'/batch/'approval.json'
    decision_path=work/'coverage-decision.json'
    if bad=='approval_missing':
        approval_path.unlink()
    elif bad=='approval_changed':
        approval=json.loads(approval_path.read_bytes())
        approval['reviewed_at']=(datetime.fromisoformat(approval['reviewed_at'])-timedelta(microseconds=1)).isoformat()
        ri.write(approval_path,approval)
    elif bad=='approval_hash':
        approval=json.loads(approval_path.read_bytes())
        approval['sources']['orders']['evidence_sha256']='0'*64
        ri.write(approval_path,approval)
    elif bad=='decision_missing':
        decision_path.unlink()
    elif bad=='decision_changed':
        decision=json.loads(decision_path.read_bytes());decision['approval_sha256']='0'*64
        ri.write(decision_path,decision)
    elif bad=='manifest_missing':
        manifest['coverage'].pop('source_completion');ri.write(library/'library_manifest.json',manifest)
        prepared=json.loads((work/'prepared.json').read_bytes())
        prepared['gates']['manifest_sha256']=ri.sha(library/'library_manifest.json')
        ri.write(work/'prepared.json',prepared)
        state=json.loads((work/'state.json').read_bytes());state['prepared_sha256']=ri.sha(work/'prepared.json')
        ri.write(work/'state.json',state)
    elif bad=='manifest_changed':
        manifest['coverage']['source_completion']['approval_sha256']='0'*64
        ri.write(library/'library_manifest.json',manifest)
        prepared=json.loads((work/'prepared.json').read_bytes())
        prepared['gates']['manifest_sha256']=ri.sha(library/'library_manifest.json')
        ri.write(work/'prepared.json',prepared)
        state=json.loads((work/'state.json').read_bytes());state['prepared_sha256']=ri.sha(work/'prepared.json')
        ri.write(work/'state.json',state)
    else:
        received_manifest=base/'raw-inputs'/batch/'manifest.json'
        raw=json.loads(received_manifest.read_bytes());raw['source_completion']=manifest['coverage']['source_completion']
        received_dir=received_manifest.parent;mode=received_dir.stat().st_mode&0o777
        received_dir.chmod(0o700);ri.write(received_manifest,raw);received_dir.chmod(mode)
    enqueue();result=rp.publish_one(base,batch)
    assert result['status']=='publish_failed' and (base/'current').resolve()==old and old.exists() and calls==[]


@pytest.mark.parametrize('change',['revoke','replace'])
def test_completion_revoked_or_replaced_during_build_never_activates(case,monkeypatch,change):
    base,batch,work,library,old,marker,enqueue,calls,manifest=case
    approval_path=base/'raw-control/source-completion'/batch/'approval.json'
    def revoke_during_build(*args):
        if change=='revoke':
            approval_path.unlink()
        else:
            approval=json.loads(approval_path.read_bytes())
            approval['reviewed_at']=(datetime.fromisoformat(approval['reviewed_at'])-timedelta(microseconds=1)).isoformat()
            ri.write(approval_path,approval)
        return base/'synthetic-new-baseline'
    monkeypatch.setattr(rp,'prepare_baseline',revoke_during_build)
    enqueue();result=rp.publish_one(base,batch)
    assert result['status']=='publish_failed' and (base/'current').resolve()==old and old.exists() and calls==[]


@pytest.mark.parametrize('kind',['unknown_field','symlink','fifo','directory','old_day'])
def test_bad_request_is_terminal_not_an_execution_request(case,kind):
    base,batch,work,library,old,marker,enqueue,calls,_=case;enqueue();p=base/'raw-publish-pending'/batch
    if kind=='unknown_field':marker['command']='touch unsafe';enqueue()
    elif kind=='symlink':p.unlink();p.symlink_to(base/'raw-control/receiver-policy.json')
    elif kind=='fifo':p.unlink();os.mkfifo(p)
    elif kind=='directory':p.unlink();p.mkdir()
    else:marker['as_of_date']='2001-01-01';enqueue()
    result=rp.publish_one(base,batch)
    assert result['status']=='publish_failed' and result['error_code']=='input_rejected'
    assert calls==[] and old.exists() and not p.exists()


def test_shared_publisher_and_producer_locks_are_nonblocking(case):
    base,*_=case
    with rp.publication_locks(base):
        with pytest.raises(BlockingIOError):
            with rp.publication_locks(base):pass


def test_interrupted_switch_restores_saved_current_without_rebuild(case):
    base,batch,work,library,old,marker,enqueue,calls,_=case;enqueue()
    target=base/'releases/daily-interrupted';(target/'library').mkdir(parents=True)
    ri.write(target/'library/library_manifest.json',{'coverage':{}})
    (base/'current').unlink();(base/'current').symlink_to(target)
    ri.write(base/'raw-publish'/(batch+'.json'),{'status':'publishing','old_release':old.name,'release':target.name,'request_sha256':ri.sha(base/'raw-publish-pending'/batch)})
    result=rp.publish_one(base,batch)
    assert result['status']=='publish_failed' and (base/'current').resolve()==old and calls==[old.name]


def test_http_requires_auth_empty_object_and_prepared_status(case):
    base,batch,work,library,old,marker,enqueue,calls,manifest=case
    authorized=[False];app=Flask(__name__)
    register(app,authorized=lambda:authorized[0],context=lambda:('workspace_bi_operations',manifest['coverage']['data_through']),
             received_root=base/'raw-inputs',queue_root=base/'raw-pending',status_root=base/'raw-status',
             publish_pending_root=base/'raw-publish-pending',publish_status_root=base/'raw-publish-status',
             publication_context=lambda:marker['expected_current_sha256'],publish_owner_uid=os.geteuid())
    client=app.test_client();url='/v1/raw-batches/'+batch+'/publish-prepared'
    assert client.post(url,json={}).status_code==401
    authorized[0]=True
    assert client.post(url,json={'command':'anything'}).status_code==400
    assert client.post(url,json={}).status_code==202
    assert client.post(url,json={}).status_code==202
    assert len(list((base/'raw-publish-pending').glob('raw-*')))==1
    rp.publish_one(base,batch)
    assert client.get('/v1/raw-batches/'+batch).json['status']=='published'
    assert client.post(url,json={}).json['published'] is True
    duplicate=client.post('/v1/raw-batches',data=(base/'inputs.tar').read_bytes())
    assert duplicate.status_code==200 and duplicate.json['status']=='published' and duplicate.json['published'] is True
    rs.publish(base/'raw-status','raw-other','failed')
    assert client.post('/v1/raw-batches/raw-other/publish-prepared',json={}).status_code==409


def test_low_space_stops_before_release_activation(case,monkeypatch):
    from types import SimpleNamespace
    base,batch,work,library,old,marker,enqueue,calls,_=case;enqueue()
    monkeypatch.setattr(rp.shutil,'disk_usage',lambda p:SimpleNamespace(free=0))
    result=rp.publish_one(base,batch)
    assert result['status']=='publish_failed' and calls==[] and (base/'current').resolve()==old


def test_input_archive_symlink_is_rejected_without_following_it(case):
    base,batch,work,library,old,marker,enqueue,calls,_=case;enqueue()
    p=base/'raw-inputs'/batch/'payload.tar';p.parent.chmod(0o750);p.chmod(0o600);p.unlink();p.symlink_to(base/'raw-control/receiver-policy.json')
    result=rp.publish_one(base,batch)
    assert result['status']=='publish_failed' and calls==[] and old.exists()


def test_baseline_is_promoted_only_after_native_success(case,monkeypatch):
    base,batch,work,library,old,marker,enqueue,calls,_=case;enqueue();events=[]
    monkeypatch.setattr(rp,'verify_daily',lambda p:events.append('verified'))
    monkeypatch.setattr(rp,'set_baseline',lambda b,p:events.append('baseline:'+Path(p).name))
    rp.publish_one(base,batch)
    assert events==['verified','baseline:synthetic-new-baseline']


def test_baseline_failure_happens_before_current_switch(case,monkeypatch):
    base,batch,work,library,old,marker,enqueue,calls,_=case;enqueue()
    monkeypatch.setattr(rp,'prepare_baseline',lambda *a:(_ for _ in ()).throw(ValueError('synthetic missing snapshot')))
    result=rp.publish_one(base,batch)
    assert result['status']=='publish_failed' and calls==[] and (base/'current').resolve()==old


def test_compact_next_baseline_keeps_only_current_snapshot_and_history(tmp_path):
    import shutil
    from dashboard_product.shadow_bi.p5.published_baseline import compact
    source=tmp_path/'source';target=tmp_path/'copy'
    for name in ['Work/Runs/run_old','Work/Runs/run_current','Work/Runs/_bi_export_keep','Work/StudyAbroad/Runs/run_old','Work/StudyAbroad/Runs/run_current','Work/StudyAbroad/Downloads','Output/StudyAbroad/历史查询回执/run_old','Output/StudyAbroad/历史查询回执/run_history']:
        p=source/name;p.mkdir(parents=True);(p/'fixture.txt').write_text(name)
    ri.write(source/'Work/workspace.json',{'current_warehouse_path':'Work/Runs/run_current/data/snapshot/warehouse.duckdb'})
    ri.write(source/'Work/StudyAbroad/current.json',{'warehouse':'Work/StudyAbroad/Runs/run_current/data/snapshot/warehouse.duckdb','source_lineage':'Work/StudyAbroad/Runs/run_current/lineage.json'})
    ri.write(source/'Work/StudyAbroad/Runs/run_current/lineage.json',{'normalized_history':{'query_run_ids':{'resources':'run_history'}}})
    shutil.copytree(source,target);compact(target)
    assert (target/'Work/Runs/run_current').is_dir() and not (target/'Work/Runs/run_old').exists()
    assert (target/'Work/StudyAbroad/Runs/run_current').is_dir() and not (target/'Work/StudyAbroad/Runs/run_old').exists()
    assert (target/'Output/StudyAbroad/历史查询回执/run_history').is_dir() and not (target/'Output/StudyAbroad/历史查询回执/run_old').exists()
    assert (source/'Work/Runs/run_old/fixture.txt').is_file()  # never prune the original source


def test_latest_only_does_not_delete_an_actively_referenced_old_product(case,monkeypatch):
    base,batch,work,library,old,marker,enqueue,calls,_=case;enqueue()
    monkeypatch.setattr(rp,'live_reference',lambda p:True)
    result=rp.publish_one(base,batch)
    assert result['status']=='published' and result['cleanup_pending'] is True
    assert old.is_dir() and (base/'current').resolve()!=old
