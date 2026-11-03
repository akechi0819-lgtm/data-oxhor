import json,time
from unittest.mock import Mock,patch
from urllib.error import HTTPError
import pytest
from data_acquisition.connectors.advertising import xhs_requests as x
from data_acquisition.auth.auth_sessions import AuthSessionPaths,write_auth_session,AuthSessionMissingError,AuthSessionExpiredError

def test_valid_cookie_route_never_opens_login():
    client=Mock();client.run.return_value={'phase':'verified'};login=Mock()
    assert x.run_authenticated(client,'workspace',login=login,folder='same-job')['phase']=='verified'
    login.assert_not_called()

@pytest.mark.parametrize('error',[AuthSessionMissingError('missing'),AuthSessionExpiredError('expired')])
def test_auth_recovery_once_same_job(error):
    client=Mock();client.run.side_effect=[error,{'phase':'verified'}];login=Mock()
    x.run_authenticated(client,'workspace',login=login,folder='same-job')
    login.assert_called_once_with('workspace')
    assert client.run.call_args_list[0]==client.run.call_args_list[1]

def test_second_auth_failure_does_not_open_second_login():
    client=Mock();client.run.side_effect=AuthSessionExpiredError('expired');login=Mock()
    with pytest.raises(AuthSessionExpiredError):x.run_authenticated(client,'workspace',login=login)
    login.assert_called_once()

@pytest.mark.parametrize('error',[x.ExportPending('timeout'),x.ExportBlocked('xhs_http_403'),x.ExportBlocked('xhs_api_rejected')])
def test_non_auth_failure_does_not_login(error):
    client=Mock();client.run.side_effect=error;login=Mock()
    with pytest.raises(type(error)):x.run_authenticated(client,'workspace',login=login)
    login.assert_not_called()

@pytest.mark.parametrize('status,kind',[(401,AuthSessionExpiredError),(403,x.ExportBlocked),(500,x.ExportBlocked)])
def test_http_auth_classification(tmp_path,status,kind):
    paths=AuthSessionPaths(tmp_path,'xhs');write_auth_session('xhs',cookies=[{'name':'dummy','value':'fixture','domain':'.xiaohongshu.com'}],local_storage={},paths=paths)
    opener=Mock();opener.open.side_effect=HTTPError(x.ORIGIN,status,'fixture',None,None)
    with patch.object(x,'build_opener',return_value=opener),pytest.raises(kind):x.XHSExport(cookie_file=paths.cookies)._post(x.TASKS,{})

def test_only_known_expired_scoped_cookies_require_login(tmp_path):
    paths=AuthSessionPaths(tmp_path,'xhs');write_auth_session('xhs',cookies=[{'name':'dummy','value':'fixture','domain':'.xiaohongshu.com','expires':time.time()-60}],local_storage={},paths=paths)
    with pytest.raises(AuthSessionExpiredError):x.XHSExport(cookie_file=paths.cookies)._cookie(x.TASKS)
    with pytest.raises(AuthSessionMissingError):x.XHSExport(cookie_file=tmp_path/'absent')._cookie(x.TASKS)


def test_recovery_injects_saved_dedicated_state_before_navigation(tmp_path):
    from contextlib import nullcontext
    paths=AuthSessionPaths(tmp_path,'xhs')
    cookies=[{'name':'dummy','value':'fixture','domain':'.xiaohongshu.com'}]
    write_auth_session('xhs',cookies=cookies,local_storage={'saved':'fixture'},paths=paths)
    events=[]
    page=Mock();page.url=x.ORIGIN
    page.goto.side_effect=lambda *a,**k:events.append('navigate')
    page.evaluate.side_effect=[{'http':200,'code':0,'success':True},{'saved':'refreshed'}]
    context=Mock();context.new_page.return_value=page;context.cookies.return_value=cookies
    context.add_cookies.side_effect=lambda value:events.append(('cookies',value))
    context.add_init_script.side_effect=lambda script:events.append(('storage',script))
    browser=Mock();browser.new_context.return_value=context
    playwright=Mock();playwright.chromium.launch.return_value=browser
    with patch('playwright.sync_api.sync_playwright',return_value=nullcontext(playwright)):
        result=x.save_login(tmp_path,confirm=lambda prompt:None)
    assert result['login_task_query_verified'] is True
    assert events[0]==('cookies',cookies)
    assert events[1][0]=='storage' and 'mcc.xiaohongshu.com' in events[1][1]
    assert events[2]=='navigate'
    assert json.loads(paths.local_storage.read_text())=={'saved':'refreshed'}
    browser.close.assert_called_once()
