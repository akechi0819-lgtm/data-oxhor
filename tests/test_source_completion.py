"""Synthetic completion evidence only; no real source completeness is asserted."""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from openpyxl import Workbook
from dashboard_product.shadow_bi.p5 import source_completion as sc, raw_inputs as ri, raw_compute as rc
from dashboard_product.management.cutoff import VerifiedCompletion, calculation_cutoff, observed_dates, personnel_coverage

DAY='2026-10-26'
COMPANY='workspace_bi_operations'

@pytest.fixture
def captured(tmp_path, monkeypatch):
    inputs={}
    for key in ri.FILES:
        path=tmp_path/(key+'.xlsx');book=Workbook();book.active.append(['test']);book.save(path);book.close();inputs[key]=path
    archive=tmp_path/'payload.tar';ri.pack(inputs,archive,batch='raw-evidence',company=COMPANY,day=DAY)
    ri.stage(archive,tmp_path/'received',company=COMPANY,day=DAY,minimum_cutoff='2026-10-24')
    received=tmp_path/'received/raw-evidence'
    control=tmp_path/'control';control.mkdir(mode=0o700);root=control/'source-completion';root.mkdir(mode=0o700)
    folder=root/received.name;folder.mkdir(mode=0o700)
    expected=sc.binding(received)
    approval={'schema_version':sc.SCHEMA,'binding':expected,'reviewed_at':'2026-10-26T09:40:00+08:00','sources':{}}
    for key in ('orders','cash'):
        body=('SYNTHETIC TEST ONLY completion watermark '+key).encode()
        (folder/(key+'.evidence')).write_bytes(body)
        approval['sources'][key]={'kind':'upstream_completion_watermark','source_id':{'orders':'br_work_orders','cash':'br_cash'}[key],
                                 'complete_through':'2026-10-25','evidence_sha256':hashlib.sha256(body).hexdigest()}
    def store(value=approval):ri.write(folder/'approval.json',value)
    store();monkeypatch.setattr(sc,'ROOT',root)
    original=sc._load
    # Test filesystem uses current UID; production resolve always requires UID 0.
    monkeypatch.setattr(sc,'_load',lambda root,expected:original(root,expected,owner_uid=os.geteuid(),now=datetime.fromisoformat('2026-10-26T10:00:00+08:00')))
    return received,root,folder,approval,store,original


def test_reviewed_evidence_binds_all_input_hashes_window_and_archive(captured):
    received,_,_,approval,_,_=captured
    decision,proof=sc.resolve(received)
    assert decision['status']=='verified' and isinstance(proof,VerifiedCompletion)
    assert proof.archive_sha256==ri.sha(received/'payload.tar')
    assert set(approval['binding']['files'])=={'orders','cash','tencent'}
    assert approval['binding']['bi_window']=={'start':'2026-04-26','end':DAY}
    assert calculation_cutoff({'orders_end':'2026-10-24','cash_end':'2026-10-24'},DAY,proof)==date(2026,10,25)


@pytest.mark.parametrize('change',[
    lambda a:a['binding'].update(archive_sha256='0'*64),
    lambda a:a['binding']['files'].update(orders='0'*64),
    lambda a:a['binding']['files'].update(tencent='0'*64),
    lambda a:a['binding']['bi_window'].update(end='2026-10-25'),
    lambda a:a['binding'].update(refresh_months=['2026-09']),
    lambda a:a['binding'].update(company_id='other_company'),
    lambda a:a['binding'].update(batch_id='raw-other'),
    lambda a:a['binding'].update(as_of_date='2026-10-25'),
    lambda a:a['binding'].update(data_through='2026-10-24'),
    lambda a:a['sources'].pop('cash'),
    lambda a:a['sources']['orders'].update(kind='etl_refresh_timestamp'),
    lambda a:a['sources']['cash'].update(kind='export_completed'),
    lambda a:a['sources']['cash'].update(kind='observed_max_date'),
    lambda a:a['sources']['orders'].update(complete_through='2026-10-24'),
    lambda a:a['sources']['cash'].update(complete_through='2026-10-26'),
    lambda a:a['sources']['orders'].update(source_id='br_cash'),
    lambda a:a['sources']['cash'].update(evidence_sha256='0'*64),
    lambda a:a.update(reviewed_at='2026-10-25T09:40:00+08:00'),
    lambda a:a.update(reviewed_at='2026-10-26T09:40:00'),
    lambda a:a.update(reviewed_at='2026-10-26T11:00:00+08:00'),
    lambda a:a.update(publish=True),
])
def test_wrong_or_insufficient_evidence_never_becomes_verified(captured,change):
    received,_,_,approval,store,_=captured
    value=deepcopy(approval);change(value);store(value)
    decision,proof=sc.resolve(received)
    assert decision=={'status':'unverified','reason':'evidence_invalid'} and proof is None


def test_absent_watermark_is_unverified_not_missing_business_data(captured):
    received,_,folder,_,_,_=captured;(folder/'approval.json').unlink()
    assert sc.resolve(received)==({'status':'unverified','reason':'evidence_missing'},None)


@pytest.mark.parametrize('kind',['approval_symlink','evidence_symlink','folder_symlink','fifo','writable_file','writable_directory','too_large'])
def test_proof_file_path_permissions_and_size_boundaries(captured,kind,tmp_path):
    received,root,folder,_,_,_=captured
    if kind=='approval_symlink':
        p=folder/'approval.json';copy=tmp_path/'outside.json';copy.write_bytes(p.read_bytes());p.unlink();p.symlink_to(copy)
    elif kind=='evidence_symlink':
        p=folder/'cash.evidence';copy=tmp_path/'outside.capture';copy.write_bytes(p.read_bytes());p.unlink();p.symlink_to(copy)
    elif kind=='folder_symlink':
        target=root/'.outside';folder.rename(target);folder.symlink_to(target,target_is_directory=True)
    elif kind=='fifo':
        p=folder/'cash.evidence';p.unlink();os.mkfifo(p)
    elif kind=='writable_file':(folder/'approval.json').chmod(0o666)
    elif kind=='writable_directory':root.chmod(0o777)
    else:(folder/'cash.evidence').write_bytes(b'x'*(2*1024**2+1))
    decision,proof=sc.resolve(received)
    assert decision['status']=='unverified' and proof is None


def test_wrong_owner_and_untrusted_uploaded_declarations_are_not_approvals(captured):
    received,root,_,approval,_,original=captured
    with pytest.raises(ValueError,match='protected'):original(root,approval['binding'],owner_uid=os.geteuid()+1)
    manifest=json.loads((received/'manifest.json').read_bytes());manifest['source_completion']=approval
    with pytest.raises(ValueError,match='unexpected manifest fields'):
        ri.validate_manifest(manifest,company=COMPANY,day=DAY,minimum_cutoff='2026-10-24')


def test_changing_received_bytes_invalidates_the_completion_binding(captured):
    received,*_=captured;p=received/'inputs/cash.xlsx';p.chmod(0o640);p.write_bytes(b'changed')
    with pytest.raises(ValueError,match='completion input changed'):sc.resolve(received)


def test_unverified_preflight_is_durable_and_never_starts_a_build(captured,tmp_path):
    received,_,folder,_,_,_=captured;(folder/'approval.json').unlink()
    args=dict(received=received,baseline=tmp_path/'baseline',root=tmp_path/'compute',day=DAY,company=COMPANY,minimum_cutoff='2026-10-24')
    with patch.object(rc.subprocess,'Popen',side_effect=AssertionError('no build')):
        result=rc.run(**args)
        assert result['status']=='coverage_unverified' and result['published'] is False
        assert result['reason']=='evidence_missing'
        assert rc.run(**args)==result
    assert not (tmp_path/'compute/raw-evidence/workspace').exists()
    assert not (tmp_path/'compute/raw-evidence/prepared.json').exists()


def test_existing_failed_receipt_stays_failed_even_when_evidence_arrives(captured,tmp_path):
    received,*_=captured;root=tmp_path/'compute';out=root/received.name;out.mkdir(parents=True)
    identity={'archive_sha256':ri.sha(received/'payload.tar'),'baseline':str((tmp_path/'baseline').resolve()),'expected':None}
    previous={'status':'failed','published':False,'identity':identity,'returncode':1};ri.write(out/'state.json',previous)
    with patch.object(rc.subprocess,'Popen',side_effect=AssertionError('no rebuild')):
        assert rc.run(received=received,baseline=tmp_path/'baseline',root=root,day=DAY,company=COMPANY,minimum_cutoff='2026-10-24')==previous


def test_declared_dict_cannot_select_a_calculation_cutoff():
    with pytest.raises(ValueError,match='verified source completion'):
        calculation_cutoff({'orders_end':'2026-10-24','cash_end':'2026-10-24'},DAY,{'complete_through':'2026-10-25'})


@pytest.mark.parametrize('asof,observed,expected,month,start,end',[
    ('2026-10-26','2026-10-24','2026-10-25','2026-10','2026-09-26','2026-10-25'),
    ('2026-10-27','2026-10-24','2026-10-26','2026-11','2026-10-26','2026-11-25'),
    ('2027-01-01','2026-12-30','2026-12-31','2027-01','2026-12-26','2027-01-25'),
])
def test_verified_zero_day_preserves_real_personal_26_to_25_rules(asof,observed,expected,month,start,end):
    from workspace_modeling.operations.personnel import date_to_perf_month
    from dashboard_product.management.aggregate import _calendar_month_window
    from dashboard_product.management.notifications import _personal_period
    coverage={'orders_start':'2025-03-01','cash_start':'2024-06-01','orders_end':observed,'cash_end':observed}
    proof=VerifiedCompletion(asof,expected,'raw-calendar','a'*64,'b'*64)
    through=calculation_cutoff(coverage,asof,proof)
    assert date_to_perf_month(through.isoformat())==month
    period={'kind':'month','id':month};assert _personal_period(through,{month:period},None)==(period,month)
    actual_start,actual_end=_calendar_month_window(period)
    assert (actual_start.isoformat(),actual_end.isoformat())==(start,end)
    assert observed_dates(coverage)=={'orders_max_date':observed,'cash_max_date':observed}
    assert personnel_coverage(coverage,through,proof)['orders_end']==expected
    assert coverage['orders_end']==observed  # no mutation or fabricated transactions
    assert calculation_cutoff(coverage,asof).isoformat()==observed  # legacy unchanged
    assert personnel_coverage(coverage,through)['cash_end']==observed


def test_verified_proof_cannot_be_reused_for_another_asof_day():
    proof=VerifiedCompletion(DAY,'2026-10-25','raw-calendar','a'*64,'b'*64)
    with pytest.raises(ValueError):calculation_cutoff({'orders_end':'2026-10-24','cash_end':'2026-10-24'},'2026-10-27',proof)


def test_verified_zero_day_passes_real_synthetic_39_table_physical_gates(captured,tmp_path):
    import duckdb
    from dashboard_product.shadow_bi.library import write_table
    from data_platform.query.evidence import file_ref
    received,*_=captured;_,proof=sc.resolve(received)
    library=tmp_path/'candidate/library';library.mkdir(parents=True);db=library/'business.duckdb'
    batch='run_completion_fixture'
    with duckdb.connect(str(db)) as connection:
        connection.execute('CREATE SCHEMA queries')
        connection.execute('CREATE TABLE queries.batch (batch_id VARCHAR)')
        connection.execute('INSERT INTO queries.batch VALUES (?)',[batch])
        tables={f'fixture_{i}':write_table(connection,library,f'fixture_{i}',[{'event_date':'2026-10-24','value':i}]) for i in range(39)}
    manifest={'schema_version':'business_query_library.v1','batch_id':batch,'as_of_date':DAY,
              'snapshots':{'training':'snapshot_synthetic'},'binding':{'inputs':{'fixture':'a'*64},'rules':{'fixture':'b'*64}},
              'source_queries':[{'snapshot_ref':{'snapshot_id':'snapshot_synthetic'}}],
              'coverage':{'data_through':'2026-10-25','observed_dates':{'orders_max_date':'2026-10-24','cash_max_date':'2026-10-24'},'source_completion':proof.metadata()},
              'tables':tables,'database':file_ref(db,library,'application/vnd.duckdb')}
    ri.write(library/'library_manifest.json',manifest)
    result=rc.gates(library,batch,DAY,completion=proof)
    assert result['tables']==39 and result['physical_counts_verified'] is True
    with pytest.raises(ValueError,match='verified completion required'):rc.gates(library,batch,DAY)
    manifest['coverage']['source_completion']['approval_sha256']='0'*64;ri.write(library/'library_manifest.json',manifest)
    with pytest.raises(ValueError,match='completion proof differs'):rc.gates(library,batch,DAY,completion=proof)


@pytest.mark.parametrize('asof,target,person_month,person_start',[
    ('2026-10-26','2026-10-25','2026-10','2026-09-26'),
    ('2026-10-27','2026-10-26','2026-11','2026-10-26'),
])
def test_actual_notification_builder_keeps_zero_day_and_personal_boundary(asof,target,person_month,person_start):
    from dashboard_product.management.aggregate import aggregate
    from dashboard_product.management.notifications import build_notifications
    proof=VerifiedCompletion(asof,target,'raw-notification-fixture','a'*64,'b'*64)
    through=calculation_cutoff({'orders_end':'2026-10-24','cash_end':'2026-10-24'},asof,proof)
    source={'snapshot_id':'snapshot_fixture','source_sha256':'c'*64,'start_date':'2026-06-01',
            'through_date':target,'no_yoy':True,'cross_system_customers':'not_aligned'}
    public=aggregate([],{'teams':[]},{},{},{},{},through,abroad_source=source)
    public['metadata']={'data_through':through.isoformat(),'study_abroad_source':source,'source_completion':proof.metadata()}
    result=build_notifications(public,[],{'teams':[]},{})
    assert result['data_through']==target and len(result['messages'])==8
    for message in result['messages']:
        assert message['window']['data_through']==target
        if not message['id'].startswith('online.'):
            assert message['window']['person_month']==person_month
            assert message['window']['person_start']==person_start
            assert message['window']['person_through']==target
        else:
            assert message['window']['person_month']==target[:7]
            assert message['window']['person_start'] is None
        if message['business_line']=='training':assert message['team_metrics']['orders']['daily_actual']==0
        assert message['ledgers']['team_orders']==[] and message['ledgers']['personal_orders']==[]


def test_http_unverified_status_exposes_no_private_completion_evidence(tmp_path):
    from flask import Flask
    from dashboard_product.shadow_bi.p5.raw_receiver import register
    from dashboard_product.shadow_bi.p5.raw_status import publish
    root=tmp_path/'public';root.mkdir(mode=0o700)
    publish(root,'raw-held','coverage_unverified')
    app=Flask(__name__)
    register(app,authorized=lambda:True,context=lambda:(COMPANY,'2026-10-24'),received_root=tmp_path/'received',queue_root=tmp_path/'queue',status_root=root)
    result=app.test_client().get('/v1/raw-batches/raw-held')
    assert result.status_code==200 and result.json=={'schema_version':'shadow_raw_status.v1','batch_id':'raw-held','status':'coverage_unverified','published':False}


@pytest.mark.parametrize('change', ['missing_decision', 'changed_decision', 'decision_symlink', 'missing_approval', 'changed_approval'])
def test_sealed_decision_requires_current_identical_approval(captured, tmp_path, change):
    received, _, folder, approval, store, _ = captured
    decision, proof = sc.resolve(received)
    sealed = tmp_path/'coverage-decision.json'
    ri.write(sealed, decision)
    assert sc.require_unchanged(received, sealed) == proof
    if change == 'missing_decision':
        sealed.unlink()
    elif change == 'changed_decision':
        ri.write(sealed, {**decision, 'approval_sha256': '0'*64})
    elif change == 'decision_symlink':
        target = tmp_path/'other.json'; sealed.rename(target); sealed.symlink_to(target)
    elif change == 'missing_approval':
        (folder/'approval.json').unlink()
    else:
        value = deepcopy(approval); value['reviewed_at'] = '2026-10-26T09:41:00+08:00'; store(value)
    with pytest.raises(ValueError, match='source completion'):
        sc.require_unchanged(received, sealed)


@pytest.mark.parametrize('missing', ['decision', 'approval'])
def test_prepared_replay_cannot_use_an_old_unverified_candidate(captured, tmp_path, monkeypatch, missing):
    received, _, folder, _, _, _ = captured
    root = tmp_path/'compute'; out = root/received.name; out.mkdir(parents=True)
    library = out/'workspace/Output/ShadowBI/run_fixture/library'; library.mkdir(parents=True)
    decision, _ = sc.resolve(received)
    ri.write(out/'coverage-decision.json', decision)
    ri.write(out/'baseline-binding.json', {'inputs': {}})
    ri.write(out/'prepared.json', {'library': str(library), 'batch_id': 'run_fixture'})
    identity = {'archive_sha256': ri.sha(received/'payload.tar'), 'baseline': str((tmp_path/'baseline').resolve()), 'expected': None}
    state = {'status': 'prepared', 'published': False, 'identity': identity, 'prepared_sha256': ri.sha(out/'prepared.json')}
    ri.write(out/'state.json', state)
    from dashboard_product.shadow_bi import library as lib
    monkeypatch.setattr(lib, 'binding', lambda path: {'inputs': {}})
    if missing == 'decision':
        (out/'coverage-decision.json').unlink()
    else:
        (folder/'approval.json').unlink()
    with patch.object(rc, 'gates', side_effect=AssertionError('no unverified gate')), patch.object(rc.subprocess, 'Popen', side_effect=AssertionError('no rebuild')):
        with pytest.raises(ValueError, match='source completion'):
            rc.run(received=received, baseline=tmp_path/'baseline', root=root, day=DAY, company=COMPANY, minimum_cutoff='2026-10-24')
    assert json.loads((out/'state.json').read_bytes()) == state


@pytest.mark.parametrize('missing', ['decision', 'approval'])
def test_sealed_failed_recheck_requires_proof_before_queries(captured, tmp_path, missing):
    received, _, folder, _, _, _ = captured
    output = tmp_path/'computed'/received.name; output.mkdir(parents=True)
    state = {'status': 'failed', 'published': False, 'identity': {'archive_sha256': ri.sha(received/'payload.tar')}}
    ri.write(output/'state.json', state)
    decision, _ = sc.resolve(received)
    ri.write(output/'coverage-decision.json', decision)
    if missing == 'decision':
        (output/'coverage-decision.json').unlink()
    else:
        (folder/'approval.json').unlink()
    from data_acquisition.jobs import daily_warehouses as daily
    with patch.object(daily, 'assert_daily_ready', side_effect=AssertionError('no unverified queries')):
        with pytest.raises(ValueError, match='source completion'):
            rc.recheck(output=output, received=received, baseline=tmp_path/'baseline', expected=tmp_path/'expected.json')
    assert json.loads((output/'state.json').read_bytes()) == state
