import copy
import pytest
from data_acquisition.connectors.advertising.dingtalk_contract import inspect_contract,UPLOAD,SUBMIT,QUERY

@pytest.fixture
def observed():
    return {'platform':'dingtalk_sem','source_title':'汇报202610SEM','response_body_status':'unavailable','observed_requests':[
        {'path':UPLOAD,'method':'POST','body':{'resourceName':'汇报202610SEM'},'status':200},
        {'path':SUBMIT,'method':'POST','body_schema':{'exportType':'dingTalksheetToxlsx'},'status':200},
        {'path':QUERY,'method':'GET','query':{'jobId':'32377865292'},'status':200}]}

def test_http200_does_not_prove_export_success(observed):
    result=inspect_contract(observed)
    assert result['job_id']=='32377865292'
    for key in ('api_success_proven','native_file_verified','replay_performed','safe_to_create_another_job','script_ready','intake_ready','published'):
        assert result[key] is False

@pytest.mark.parametrize('change', ['order','job','response','duplicate','title'])
def test_unobserved_contract_rejected(observed,change):
    if change=='order':observed['observed_requests'].reverse()
    if change=='job':observed['observed_requests'][-1]['query']['jobId']=''
    if change=='response':observed['response_body_status']='available'
    if change=='duplicate':observed['observed_requests'].append(copy.deepcopy(observed['observed_requests'][-1]))
    if change=='title':observed['observed_requests'][0]['body']['resourceName']='other'
    with pytest.raises(ValueError):inspect_contract(observed)

def test_landed_file_does_not_supply_lost_response_schema(observed):
    observed['response_body_status']='Original response buffers no longer available after recovery: No resource with given identifier found'
    observed['download_status']='landed; verified in dingtalk-download-verification.json'
    observed['network_listener_cleanup']='Network.disable succeeded after tool resumed naturally'
    result=inspect_contract(observed)
    assert result['listener_disable_confirmed'] is True
    assert result['response_schema_known'] is False
    assert result['script_ready'] is False
    assert result['native_file_verified'] is False  # this parser has not read that file
