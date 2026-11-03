from unittest.mock import MagicMock,patch
import pytest
from data_acquisition.connectors.advertising.xhs_requests import save_login,ExportBlocked,ORIGIN
from data_acquisition.auth.auth_sessions import AuthSessionPaths

def objects():
    factory=MagicMock();pw=factory.return_value.__enter__.return_value
    browser=pw.chromium.launch.return_value
    context=browser.new_context.return_value;page=context.new_page.return_value
    page.url=ORIGIN+'/home'
    page.evaluate.side_effect=[{'http':200,'code':0,'success':True},{'dummy':'fixture-only'}]
    context.cookies.return_value=[{'name':'dummy','value':'fixture-only','domain':'mcc.xiaohongshu.com'}]
    return factory,pw,browser,context,page

def test_explicit_login_saves_only_xhs_using_existing_writer(tmp_path):
    factory,pw,browser,context,page=objects();confirmed=[]
    with patch('playwright.sync_api.sync_playwright',factory):
        result=save_login(tmp_path,confirm=lambda prompt:confirmed.append(prompt))
    assert result['login_task_query_verified'] and len(confirmed)==1
    pw.chromium.launch.assert_called_once_with(channel='chrome',headless=False)
    context.cookies.assert_called_once_with([ORIGIN]);browser.close.assert_called_once()
    assert AuthSessionPaths(tmp_path,'xhs').cookies.stat().st_mode&0o777==0o600
    assert not AuthSessionPaths(tmp_path,'bi').root.exists()
    assert 'fixture-only' not in str(result)

def test_failed_login_query_never_saves(tmp_path):
    factory,pw,browser,context,page=objects();page.evaluate.side_effect=[{'http':200,'code':-1,'success':False}]
    with patch('playwright.sync_api.sync_playwright',factory),pytest.raises(ExportBlocked,match='not_verified'):
        save_login(tmp_path,confirm=lambda prompt:None)
    context.cookies.assert_not_called();browser.close.assert_called_once()
    assert not AuthSessionPaths(tmp_path,'xhs').root.exists()
