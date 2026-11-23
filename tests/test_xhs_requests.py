import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from openpyxl import Workbook
from data_acquisition.connectors.advertising import xhs_requests as x
from data_acquisition.auth.auth_sessions import AuthSessionPaths, write_auth_session

@pytest.fixture
def setup(tmp_path):
    stamp = datetime(2026, 10, 28, 17, 5, 33, tzinfo=x.TZ)
    contract = {'origin':x.ORIGIN,'export':{'path':x.CREATE,'body':{'period':'day','accountOrgCode':'confirmed'}},'tasks':{'path':x.TASKS,'body':{}}}
    proof = {'account_ids':['123'],'account_org_code':'confirmed','organization_identity':{'accountOrgName':'org','taskTypeName':'推广数据导出','platformName':'聚光'}}
    old = {'code':'old','accountOrgName':'org','taskTypeName':'推广数据导出','platformName':'聚光'}
    new = {**old,'code':'new','createTime':'2026-10-28 17:05:33','endTime':'2026-10-28 17:05:36','taskResult':1,'taskProgress':'下载完成','taskProgressValue':2,'downloadFile':'https://example.test/private-signed-url'}
    book = Workbook(); book.active.append(['周期','投放ID','账户类型','广告主账户ID','总消耗'])
    for day in ['20261026','20261027']:book.active.append([day,'123','代理商子账户','brand',2])
    fixture=tmp_path/'fixture.xlsx';book.save(fixture)
    return tmp_path,stamp,contract,proof,old,new,fixture.read_bytes()

def run(setup, post, transfer=None, **kwargs):
    root,stamp,contract,proof,old,new,raw=setup
    def deliver(url,path):path.write_bytes(raw)
    client=x.XHSExport(post=post,transfer=transfer or deliver,clock=lambda:stamp,**kwargs)
    return client.run(folder=root/'job',contract=contract,verification=proof,start='2026-10-26',through='2026-10-27')

def api(rows):return {'code':0,'success':True,'data':{'dataList':rows}}

def test_success_real_xlsx_intake_and_idempotency(setup):
    root,stamp,contract,proof,old,new,raw=setup; calls=[]
    def post(path,body):
        calls.append(path)
        return {'success':True} if path==x.CREATE else api([old] if len(calls)==1 else [old,new])
    result=run(setup,post)
    assert result['phase']=='verified' and result['native']['amount']=='4'
    assert result['timings']['server_generation_seconds']==3
    receipt=json.loads(Path(result['intake_receipt']).read_text())
    assert receipt['captures'][0]['status']=='received' and not receipt['production_ready']
    assert 'private-signed-url' not in ''.join(p.read_text() for p in (root/'job').glob('*.json'))
    run(setup,lambda *a:pytest.fail('verified must not request again'))
    assert calls.count(x.CREATE)==1

def test_unknown_creation_result_reconciles_without_resubmit(setup):
    root,stamp,contract,proof,old,new,raw=setup; calls=[]
    def post(path,body):
        calls.append(path)
        if path==x.CREATE:raise x.ExportPending('unconfirmed')
        return api([old] if len(calls)==1 else [old,new])
    assert run(setup,post)['create_acknowledged'] is False
    assert calls.count(x.CREATE)==1

def test_pending_then_resume_does_not_create(setup):
    root,stamp,contract,proof,old,new,raw=setup; calls=[]
    def post(path,body):calls.append(path);return {} if path==x.CREATE else api([old])
    with pytest.raises(x.ExportPending,match='no_resubmit'):run(setup,post,generation_timeout=0)
    assert json.loads((root/'job/state.json').read_text())['phase']=='pending_generation'
    def resume(path,body):assert path==x.TASKS;return api([old,new])
    assert run(setup,resume)['phase']=='verified'
    assert calls.count(x.CREATE)==1

def test_ambiguous_new_tasks_block(setup):
    old,new=setup[4:6];n=[0]
    def post(path,body):
        n[0]+=1
        return {} if path==x.CREATE else api([old] if n[0]==1 else [old,new,{**new,'code':'other'}])
    with pytest.raises(x.ExportBlocked,match='ambiguous'):run(setup,post)

def test_baseline_failure_can_retry_without_submission(setup):
    with pytest.raises(x.ExportPending):run(setup,lambda *a:(_ for _ in ()).throw(x.ExportPending('before create')))
    old,new=setup[4:6];calls=[]
    def post(path,body):calls.append(path);return {} if path==x.CREATE else api([old] if len(calls)==1 else [old,new])
    assert run(setup,post)['phase']=='verified'
    assert calls.count(x.CREATE)==1

def test_completed_partial_is_adopted_without_redownload(setup):
    root,stamp,contract,proof,old,new,raw=setup;n=[0]
    def post(path,body):n[0]+=1;return {} if path==x.CREATE else api([old] if n[0]==1 else [old,new])
    def interrupted(url,path):path.write_bytes(raw);raise x.ExportPending('uncertain transport')
    with pytest.raises(x.ExportPending):run(setup,post,interrupted)
    assert run(setup,lambda *a:api([old,new]),lambda *a:pytest.fail('already landed'))['phase']=='verified'

@pytest.mark.parametrize('service',['bi','xhs','ocean','tencent_ads'])
def test_auth_formats_and_permissions(tmp_path,service):
    paths=AuthSessionPaths(tmp_path,service)
    write_auth_session(service,cookies=[{'name':'dummy','value':'fixture'}],local_storage={'dummy':'fixture'},paths=paths)
    assert paths.root.stat().st_mode&0o777==0o700
    for path in (paths.cookies,paths.local_storage):assert path.stat().st_mode&0o777==0o600
    assert isinstance(json.loads(paths.cookies.read_text()),list)
    assert isinstance(json.loads(paths.local_storage.read_text()),dict)

def test_auth_wrong_platform_path_rejected(tmp_path):
    with pytest.raises(ValueError,match='mismatch'):write_auth_session('xhs',cookies=[],local_storage={},paths=AuthSessionPaths(tmp_path,'bi'))
    assert not (tmp_path/'data_acquisition').exists()

def test_cookie_file_must_be_private_and_scoped(tmp_path):
    paths=AuthSessionPaths(tmp_path,'xhs');write_auth_session('xhs',cookies=[{'name':'dummy','value':'fixture','domain':'.example.test'}],local_storage={},paths=paths)
    client=x.XHSExport(cookie_file=paths.cookies)
    with pytest.raises(x.ExportBlocked,match='wrong_domain'):client._cookie(x.TASKS)
    paths.cookies.chmod(0o644)
    with pytest.raises(x.ExportBlocked,match='not_private'):client._cookie(x.TASKS)

def test_candidate_uses_confirmed_mapping_and_preserves_formal_manifest(setup):
    root,stamp,contract,proof,old,new,raw=setup
    formal=root/'formal.json'
    formal.write_text(json.dumps({'sources':[{'source_id':'confirmed','kind':'xhs_mcc_daily','path':'old.xlsx','start_date':'2026-10-01','end_date':'2026-10-25','brand_accounts':{'brand':{'business_line':'training','business_group':'大学'}}}]}))
    before=formal.read_bytes();job=root/'candidate';job.mkdir()
    native=job/'native.xlsx';native.write_bytes(raw)
    evidence=job/'evidence.json';evidence.write_text('{"task_id":"real-caller-proof"}')
    candidate=x.build_candidate(job,formal,native_file=native,evidence_file=evidence,captured_at=stamp.isoformat(),start='2026-10-26',through='2026-10-27',expected_accounts=['123'])
    assert formal.read_bytes()==before
    manifest=json.loads(Path(candidate['manifest']).read_text())
    assert len(manifest['sources'])==1 and manifest['sources'][0]['source_id']=='confirmed'
    assert manifest['sources'][0]['path']==str(native)
    capture=json.loads(Path(candidate['capture']).read_text())
    assert capture['sources'][0]['completion']['complete'] is True
    assert json.loads((job/'candidate-validation.json').read_text())['full_source_scope_complete'] is False
    formal.write_text(json.dumps({'sources':[]}));before=formal.read_bytes()
    with pytest.raises(x.ExportBlocked,match='mapping_missing'):x.build_candidate(job,formal,native_file=native,evidence_file=evidence,captured_at=stamp.isoformat(),start='2026-10-26',through='2026-10-27',expected_accounts=['123'])
    assert formal.read_bytes()==before

def test_candidate_excludes_verified_extra_zero_account_from_rows(setup):
    root,stamp,contract,proof,old,new,raw=setup
    formal=root/'formal.json'
    formal.write_text(json.dumps({'sources':[{'source_id':'confirmed','kind':'xhs_mcc_daily','path':'old.xlsx',
        'start_date':'2026-10-01','end_date':'2026-10-25',
        'brand_accounts':{'brand':{'business_line':'training','business_group':'大学'}}}]}))
    job=root/'candidate';job.mkdir()
    book=Workbook();book.active.append(['周期','投放ID','账户类型','广告主账户ID','总消耗'])
    for day in ('20261026','20261027'):
        book.active.append([day,'123','代理商子账户','brand',2])
        book.active.append([day,'456','代理商子账户','brand',0])
    native=job/'native.xlsx';book.save(native)
    evidence=job/'evidence.json';evidence.write_text('{}')
    candidate=x.build_candidate(job,formal,native_file=native,evidence_file=evidence,
        captured_at=stamp.isoformat(),start='2026-10-26',through='2026-10-27',expected_accounts=['123'])
    manifest=json.loads(Path(candidate['manifest']).read_text())
    assert manifest['sources'][0]['excluded_zero_account_ids']==['456']
    validation=json.loads((job/'candidate-validation.json').read_text())
    assert validation['native']['account_ids']==['123']
    assert validation['native']['extra_zero_account_ids']==['456']
    assert validation['rows']==2

def test_auth_interrupt_after_create_preserves_unknown_task_without_recreate(setup):
    root,stamp,contract,proof,old,new,raw=setup;calls=[];login=[]
    def post(path,body):
        calls.append(path)
        if path==x.CREATE:raise x.AuthSessionExpiredError('401 or auth interruption')
        return api([old] if len(calls)==1 else [old,new])
    def transfer(url,path):path.write_bytes(raw)
    client=x.XHSExport(post=post,transfer=transfer,clock=lambda:stamp)
    result=x.run_authenticated(client,'workspace',login=lambda workspace:login.append(workspace),folder=root/'job',contract=contract,verification=proof,start='2026-10-26',through='2026-10-27')
    assert result['phase']=='verified' and calls.count(x.CREATE)==1 and login==['workspace']

def test_confirmed_scope_does_not_require_old_task_to_remain_in_recent_list(setup):
    old,new=setup[4:6];calls=[]
    def post(path,body):
        calls.append(path)
        return {} if path==x.CREATE else api([{**old,'code':'another-recent-task'}] if len(calls)==1 else [new])
    assert run(setup,post)['phase']=='verified'

def test_closed_window_advances_without_hardcoded_capture_date(setup):
    root,stamp,contract,proof,old,new,raw=setup;stamp+=timedelta(days=1);requests=[]
    new={**new,'createTime':stamp.strftime('%Y-%m-%d %H:%M:%S'),'endTime':(stamp+timedelta(seconds=2)).strftime('%Y-%m-%d %H:%M:%S')}
    book=Workbook();book.active.append(['周期','投放ID','账户类型','广告主账户ID','总消耗'])
    for day in ['20261026','20261027','20261028']:book.active.append([day,'123','代理商子账户','brand',2])
    fixture=root/'next-day-fixture.xlsx';book.save(fixture)
    def post(path,body):
        requests.append((path,body))
        return {} if path==x.CREATE else api([old] if len(requests)==1 else [old,new])
    def transfer(url,path):path.write_bytes(fixture.read_bytes())
    result=x.XHSExport(post=post,transfer=transfer,clock=lambda:stamp).run(folder=root/'day29',contract=contract,verification=proof,start='2026-10-26',through='2026-10-28')
    assert result['native']['days']==3 and result['native']['amount']=='6'
    body=next(body for path,body in requests if path==x.CREATE)
    assert body['timeEnd']=='2026-10-28' and body['timeStart']=='2026-10-26'


def test_confirmed_nonzero_exclusion_resumes_partial_and_builds_candidate(setup):
    root, stamp, contract, proof, old, new, raw = setup
    proof['excluded_account_ids'] = ['456']
    book = Workbook(); book.active.append(['周期', '投放ID', '账户类型', '广告主账户ID', '总消耗'])
    for day in ('20261026', '20261027'):
        book.active.append([day, '123', '代理商子账户', 'brand', 2])
        book.active.append([day, '456', '代理商子账户', 'unmapped', 109.17])
    fixture = root/'excluded.xlsx'; book.save(fixture)
    calls = []
    def post(path, body):
        calls.append(path)
        return {} if path == x.CREATE else api([old] if len(calls) == 1 else [old, new])
    def interrupted(url, path):
        path.write_bytes(fixture.read_bytes())
        raise x.ExportPending('transfer interrupted')
    with pytest.raises(x.ExportPending):
        run(setup, post, interrupted)
    result = run(setup, lambda path, body: api([old, new]), lambda *a: pytest.fail('must reuse partial'))
    assert calls.count(x.CREATE) == 1
    assert result['native']['excluded_account_ids'] == ['456']
    assert result['native']['extra_zero_account_ids'] == []
    formal = root/'formal.json'
    formal.write_text(json.dumps({'sources':[{'source_id':'confirmed','kind':'xhs_mcc_daily','path':'old.xlsx',
        'start_date':'2026-10-01','end_date':'2026-10-25',
        'brand_accounts':{'brand':{'business_line':'training','business_group':'大学'}}}]}))
    job = root/'job'
    candidate = x.build_candidate(job, formal, native_file=job/'native.xlsx', evidence_file=job/'evidence.json',
        captured_at=stamp.isoformat(), start='2026-10-26', through='2026-10-27',
        expected_accounts=result['expected_accounts'], excluded_account_ids=result['native']['excluded_account_ids'])
    entry = json.loads(Path(candidate['manifest']).read_text())['sources'][0]
    assert entry['excluded_account_ids'] == ['456']
    assert 'excluded_zero_account_ids' not in entry
    assert json.loads((job/'candidate-validation.json').read_text())['rows'] == 2
    with pytest.raises(Exception, match='scope_mismatch'):
        x.XHSExport()._inspect(job/'native.xlsx', '2026-10-26', '2026-10-27', ['123'])
    with pytest.raises(Exception, match='scope_mismatch'):
        x.XHSExport()._inspect(job/'native.xlsx', '2026-10-26', '2026-10-27', ['123', '789'], ['456'])
