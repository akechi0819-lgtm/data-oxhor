import json
from datetime import datetime
from pathlib import Path
import pytest
from data_acquisition.connectors.advertising import tencent_requests as t

@pytest.fixture
def setup(tmp_path):
    stamp=datetime(2026,10,28,22,40,tzinfo=t.TZ)
    body={'task_name':'【新版】报表-账户-2026-09-01至2026-10-25','task_type':'TASK_TYPE_INTEGRATED_DATA_V3','account_id':74749810,'task_spec':{'account_id_list':[74749810],'is_total':False,'time_line':'REQUEST_TIME','date_range':{'start_date':'2026-09-01','end_date':'2026-10-25'},'fields':['report.date','report.cost'],'level':'ADVERTISER','group_by':['date'],'metrics_tbl':'UserRpt','is_sync':False}}
    contract={'origin':t.ORIGIN,'account_id':'74749810','product_scope':'display_plus','query':{'path':t.QUERY,'body':{'account_id_list':[74749810],'page':1,'page_size':20,'date_range':{}}},'create':{'path':t.CREATE,'body':body},'poll':{'path':t.POLL},'download':{'path':t.DOWNLOAD},'tasks':{'path':t.TASKS,'task_type_numeric':20003020}}
    raw=('\ufeff日期,曝光次数,点击次数,点击率,点击均价,花费\r\n2026-10-26,10,1,10%,1.00,1.00\r\n2026-10-27,20,1,5%,2.00,2.00\r\n').encode()
    calls=[]
    def post(kind,body):
        calls.append((kind,body))
        if kind=='query':return {'code':0,'data':{'list':[{'report':{'account_id':74749810,'date':'2026-10-26','cost':'1.00'}},{'report':{'account_id':74749810,'date':'2026-10-27','cost':'2.00'}}],'page_info':{'page':1,'page_size':20,'total_number':2,'total_page':1}}}
        if kind=='list':return {'code':0,'ret':0,'data':{'list':[],'conf':{'total_page':1}}}
        if kind=='create':return {'code':0,'ret':0,'data':{'task_id':12345}}
        return {'code':0,'data':{'task_id':12345,'task_type':body_type,'status':'TASK_STATUS_COMPLETED','result_status':'TASK_RESULT_STATUS_SUCCESS','file_id':'fixture'}}
    body_type=body['task_type']
    def transfer(url,path):path.write_bytes(raw)
    def run(post_fn=post,transfer_fn=transfer,**kwargs):return t.TencentExport(tmp_path,post=post_fn,transfer=transfer_fn,clock=lambda:stamp,**kwargs).run(folder=tmp_path/'job',contract=contract,start='2026-10-26',through='2026-10-27')
    return tmp_path,contract,post,transfer,run,calls,raw

def test_success_scope_and_idempotency(setup):
    root,contract,post,transfer,run,calls,raw=setup
    result=run();assert result['phase']=='verified' and result['native']['total']=='3.00'
    assert result['whole_account_complete'] is False
    body=next(body for kind,body in calls if kind=='create')
    assert json.loads(body['task_spec'])['date_range']=={'start_date':'2026-10-26','end_date':'2026-10-27'}
    assert '2026-10-26至2026-10-27' in body['task_name']
    assert 'file_url' not in (root/'job/state.json').read_text()
    assert run(lambda *a:pytest.fail('no duplicate request'))['task_id']==12345
    assert sum(kind=='create' for kind,body in calls)==1

def test_unknown_create_never_resubmitted(setup):
    root,contract,post,transfer,run,calls,raw=setup
    def uncertain(kind,body):
        if kind=='create':calls.append((kind,body));raise t.ExportPending('unknown')
        return post(kind,body)
    with pytest.raises(t.ExportPending):run(uncertain)
    with pytest.raises(t.ExportPending,match='no_resubmit'):run(post)
    assert sum(kind=='create' for kind,body in calls)==1

def test_unknown_pending_status_keeps_task_and_resume(setup):
    root,contract,post,transfer,run,calls,raw=setup
    def pending(kind,body):
        result=post(kind,body)
        if kind=='poll':result['data']['status']='UNOBSERVED_PENDING'
        return result
    with pytest.raises(t.ExportPending,match='pending_no_resubmit'):run(pending,generation_timeout=0)
    assert run()['task_id']==12345
    assert sum(kind=='create' for kind,body in calls)==1

def test_landed_partial_reused_without_retransfer(setup):
    root,contract,post,transfer,run,calls,raw=setup
    def interrupted(url,path):path.write_bytes(raw);raise t.ExportPending('unknown transfer')
    with pytest.raises(t.ExportPending):run(transfer_fn=interrupted)
    assert run(transfer_fn=lambda *a:pytest.fail('file already landed'))['phase']=='verified'
    assert sum(kind=='create' for kind,body in calls)==1

def test_wrong_query_account_prevents_creation(setup):
    root,contract,post,transfer,run,calls,raw=setup
    def wrong(kind,body):
        result=post(kind,body)
        if kind=='query':result['data']['list'][0]['report']['account_id']=999
        return result
    with pytest.raises(t.ExportBlocked,match='account_date'):run(wrong)
    assert not any(kind=='create' for kind,body in calls)

def test_same_job_changed_window_rejected(setup):
    root,contract,post,transfer,run,calls,raw=setup;run()
    client=t.TencentExport(root,post=lambda *a:pytest.fail('no new request'),clock=lambda:datetime(2026,10,29,tzinfo=t.TZ))
    with pytest.raises(t.ExportBlocked,match='input_changed'):client.run(folder=root/'job',contract=contract,start='2026-10-26',through='2026-10-28')

def test_unknown_creation_resolved_from_actual_task_list_without_recreate(setup):
    root,contract,post,transfer,run,calls,raw=setup;created=[False]
    def observed(kind,body):
        if kind=='create':created[0]=True;calls.append((kind,body));raise t.ExportPending('ack missing')
        if kind=='list' and created[0]:return {'code':0,'data':{'list':[{'uid':74749810,'task_id':12345,'task_name':'【新版】报表-账户-2026-10-26至2026-10-27(2026-10-28 22:40:00)','task_type':20003020,'created_time':1793198400}],'conf':{'total_page':1}}}
        return post(kind,body)
    with pytest.raises(t.ExportPending):run(observed)
    assert run(observed)['task_id']==12345
    assert sum(kind=='create' for kind,body in calls)==1

def test_valid_csv_prefix_is_not_accepted_as_complete_partial(setup):
    root,contract,post,transfer,run,calls,raw=setup
    def interrupted(task,path):path.write_bytes(raw[:raw.rfind(b'2026-10-27')]);raise t.ExportPending('partial')
    with pytest.raises(t.ExportPending):run(transfer_fn=interrupted)
    retransfers=[]
    def complete(task,path):retransfers.append(task['task_id']);transfer(task,path)
    assert run(transfer_fn=complete)['phase']=='verified' and retransfers==[12345]
    assert list((root/'job').glob('incomplete-*.part'))
    assert sum(kind=='create' for kind,body in calls)==1

def test_cookie_first_recovery_only_for_auth_errors(tmp_path):
    from unittest.mock import Mock
    from data_acquisition.auth.auth_sessions import AuthSessionPaths,AuthSessionExpiredError
    client=Mock();client.paths=AuthSessionPaths(tmp_path,'tencent_ads');login=Mock()
    client.run.return_value={'phase':'verified'}
    assert t.run_authenticated(client,login=login)['phase']=='verified';login.assert_not_called()
    client.run.side_effect=[AuthSessionExpiredError('expired'),{'phase':'verified'}]
    assert t.run_authenticated(client,login=login)['phase']=='verified';login.assert_called_once_with(tmp_path)
    login.reset_mock();client.run.side_effect=t.ExportBlocked('tencent_http_403')
    with pytest.raises(t.ExportBlocked):t.run_authenticated(client,login=login)
    login.assert_not_called()
    client.run.side_effect=AuthSessionExpiredError('still expired')
    with pytest.raises(AuthSessionExpiredError):t.run_authenticated(client,login=login)
    login.assert_called_once()

def test_observed_legacy_endpoint_and_task_schema_are_separate_scope(setup):
    root,contract,post,transfer,run,calls,raw=setup
    contract['product_scope']='legacy_search';contract['query']['path']=t.LEGACY_QUERY
    body=contract['create']['body'];body['task_type']='TASK_TYPE_INTEGRATED_DATA'
    spec=body['task_spec'];spec.pop('level');spec.pop('group_by');spec['breakdown']=['ACCOUNT_REPORT_BY_DATE']
    def legacy(kind,body):
        result=post(kind,body)
        if kind=='poll':result['data']['task_type']='TASK_TYPE_INTEGRATED_DATA'
        return result
    result=run(legacy)
    assert result['product_scope']=='legacy_search' and result['native']['scope_dates_complete'] is True
    assert result['whole_account_complete'] is False
    receipt=json.loads(Path(result['intake_receipt']).read_text())
    assert receipt['captures'][0]['product_scope']=='legacy_search'

def test_closed_next_day_window_is_sent_and_sparse_day_not_fabricated(setup):
    root,contract,post,transfer,run,calls,raw=setup
    client=t.TencentExport(root,post=post,transfer=transfer,clock=lambda:datetime(2026,10,29,9,30,tzinfo=t.TZ))
    result=client.run(folder=root/'next-day',contract=contract,start='2026-10-26',through='2026-10-28')
    request=next(body for kind,body in calls if kind=='create')
    assert json.loads(request['task_spec'])['date_range']['end_date']=='2026-10-28'
    assert result['native']['missing_selected_dates']==['2026-10-28']
    assert result['whole_account_complete'] is False

def test_native_download_uses_observed_authorized_form_and_never_cdn(tmp_path):
    from io import BytesIO
    from unittest.mock import Mock,patch
    from urllib.parse import urlsplit,parse_qs
    from data_acquisition.auth.auth_sessions import AuthSessionPaths,write_auth_session
    paths=AuthSessionPaths(tmp_path,'tencent_ads')
    write_auth_session('tencent_ads',cookies=[{'name':'dummy','value':'fixture-only','domain':'.qq.com'}],local_storage={},paths=paths)
    auth={'download':{'method':'POST','path':t.DOWNLOAD,'query':{},'headers':{'Content-Type':'application/x-www-form-urlencoded'},'body':{'qzreferrer':'https://ad.qq.com/atlas/74749810/download','task_id':'old','file_id':'old','format':'xls'}}}
    private=paths.root/'export-auth.json';private.write_text(json.dumps(auth));private.chmod(0o600)
    opener=Mock();opener.open.return_value=BytesIO(b'fixture-native')
    with patch.object(t,'build_opener',return_value=opener):
        t.TencentExport(tmp_path)._transfer({'task_id':12345,'file_id':'new-file','file_url':'http://internal-cdn.invalid/never-request'},tmp_path/'download.part')
    request=opener.open.call_args.args[0]
    assert request.get_method()=='POST' and urlsplit(request.full_url).netloc=='ad.qq.com' and urlsplit(request.full_url).path==t.DOWNLOAD
    body=parse_qs(request.data.decode());assert body['task_id']==['12345'] and body['file_id']==['new-file'] and body['format']==['xls']
