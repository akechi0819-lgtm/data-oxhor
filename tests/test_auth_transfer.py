import hashlib,json
from pathlib import Path
import pytest
from data_acquisition.auth.auth_sessions import AuthSessionPaths,AuthSessionError,import_auth_session_file

def test_sample_transfer_validation_then_existing_writer(tmp_path):
    source=tmp_path/'explicit-sample.json';source.write_text(json.dumps({'cookies':[{'name':'dummy','value':'fixture-only'}],'localStorage':{'dummy':'fixture-only'}}))
    digest=hashlib.sha256(source.read_bytes()).hexdigest();paths=AuthSessionPaths(tmp_path/'test-workspace','xhs')
    result=import_auth_session_file('xhs',source=source,expected_sha256=digest,paths=paths)
    assert result['format_valid'] and not result['credentials_written']
    assert 'fixture-only' not in str(result) and not paths.root.exists()
    result=import_auth_session_file('xhs',source=source,expected_sha256=digest,paths=paths,save=True)
    assert result['credentials_written'] and paths.root.stat().st_mode&0o777==0o700
    assert paths.cookies.stat().st_mode&0o777==0o600
    assert paths.local_storage.stat().st_mode&0o777==0o600
    assert not AuthSessionPaths(tmp_path/'test-workspace','bi').root.exists()

@pytest.mark.parametrize('failure',['hash','format','symlink','platform'])
def test_transfer_rejects_before_creating_auth_state(tmp_path,failure):
    source=tmp_path/'explicit.json';source.write_text('{}' if failure=='format' else '{"cookies":[],"localStorage":{}}')
    digest=hashlib.sha256(source.read_bytes()).hexdigest();paths=AuthSessionPaths(tmp_path/'workspace','xhs')
    if failure=='hash':digest='0'*64
    if failure=='symlink':link=tmp_path/'link.json';link.symlink_to(source);source=link
    if failure=='platform':paths=AuthSessionPaths(tmp_path/'workspace','bi')
    with pytest.raises(AuthSessionError):import_auth_session_file('xhs',source=source,expected_sha256=digest,paths=paths,save=True)
    assert not paths.root.exists()
