"""单仓发布身份及通知读取合同；不访问网络或客户文件。"""
from copy import deepcopy
import json

import pytest

from dashboard_product.management.tests import test_notifications as fixture_notifications
from dashboard_product.management.notifications import build_notifications
from dashboard_product.shadow_bi.p4.sql_release import load_release, verify_acceptance
from data_platform.query.evidence import file_ref
from monitoring_product import release_notifications as notifications


@pytest.fixture
def release(tmp_path):
    root = tmp_path/'daily-sql-fixture'
    library = root/'library'
    library.mkdir(parents=True)
    fixture = fixture_notifications.ManagementNotificationsTest()
    fixture.setUp()
    public = deepcopy(fixture.public)
    public['metadata']['snapshot_id'] = 'snapshot_training'
    public['metadata']['study_abroad_source'].update(snapshot_id='snapshot_abroad', through_date='2026-09-28')
    payload = build_notifications(public, fixture.facts,
                                  fixture.people, fixture.abroad_people)
    through = payload['data_through']
    coverage = {**public['metadata'], 'data_through': through}
    (library/'warehouse.duckdb').write_bytes(b'sealed database file; query adapter tested separately')
    (library/'notification-preview.json').write_text(json.dumps(payload, ensure_ascii=False))
    candidate = {'schema_version': 'sql_warehouse_candidate.v1', 'batch_id': 'run_sql_fixture',
                 'snapshots': {'training': 'snapshot_training', 'abroad': 'snapshot_abroad'},
                 'as_of_date': '2026-09-29', 'through_date': through,
                 'database': file_ref(library/'warehouse.duckdb', library, 'application/vnd.duckdb'),
                 'notification_preview': file_ref(library/'notification-preview.json', library, 'application/json')}
    (library/'candidate.json').write_text(json.dumps(candidate))
    semantics = {'Work/Pack/pack.json': 'a'*64, 'Work/Bridge/reference.json': 'b'*64}
    ref = file_ref(library/'candidate.json', library, 'application/json')
    manifest = {'schema_version': 'sql_warehouse_release.v1', 'release_id': root.name,
                'batch_id': candidate['batch_id'], 'snapshots': candidate['snapshots'],
                'as_of_date': candidate['as_of_date'], 'coverage': coverage,
                'candidate': ref, 'candidate_sha256': ref['sha256'],
                'database_sha256': candidate['database']['sha256'],
                'semantics': semantics, 'binding': {'inputs': semantics}}
    (library/'release.json').write_text(json.dumps(manifest))
    return root, library, manifest, payload


def test_single_warehouse_manifest_rejects_file_and_identity_drift(release):
    root, library, manifest, _ = release
    assert load_release(library)[2] == library/'warehouse.duckdb'
    manifest['snapshots']['training'] = 'snapshot_other'
    (library/'release.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_release(library)


def test_single_warehouse_database_tampering_is_rejected(release):
    _, library, _, _ = release
    with (library/'warehouse.duckdb').open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError):
        load_release(library)


def test_notification_adapter_preserves_all_compiled_payload_and_binds_current(release, tmp_path):
    root, library, _, expected = release
    bundle_dir = tmp_path/'bundle'
    bundle = notifications.build_bundle(library=library, batch_id='run_sql_fixture',
                                       release_id=root.name, output_dir=bundle_dir)
    assert bundle['source_mode'] == 'sql_warehouse'
    actual = json.loads((bundle_dir/'notifications.json').read_text())
    actual.pop('metadata')
    assert actual == expected
    notifications.verify_bundle(bundle_dir/'bundle.json', root)
    other = tmp_path/'daily-other'
    other.mkdir()
    (other/'library').symlink_to(library)
    with pytest.raises(ValueError):
        notifications.verify_bundle(bundle_dir/'bundle.json', other)


def test_notification_payload_cannot_be_replaced_after_sealing(release, tmp_path):
    root, library, _, _ = release
    bundle_dir = tmp_path/'bundle'
    notifications.build_bundle(library=library, batch_id='run_sql_fixture',
                               release_id=root.name, output_dir=bundle_dir)
    with (bundle_dir/'notifications.json').open('ab') as stream:
        stream.write(b' ')
    with pytest.raises(ValueError):
        notifications.verify_bundle(bundle_dir/'bundle.json', root)


def test_daily_release_requires_real_migration_certificate_and_current_source_checks(release, tmp_path):
    import hashlib
    _, library, manifest, _ = release
    contract = tmp_path/'migration.json'
    contract.write_text(json.dumps({'numbers_match': True, 'functions_match': True,
                                   'interface_match': True, 'catalogue_sha256': 'c'*64}))
    acceptance = {'mode': 'runtime_contract', 'candidate_sha256': manifest['candidate_sha256'],
                  'migration_acceptance': {'sha256': hashlib.sha256(contract.read_bytes()).hexdigest()},
                  'runtime_contract': {'status': 'passed', 'catalogue_sha256': 'c'*64,
                                       'candidate_identity_passed': True, 'source_gates_passed': True}}
    manifest['superset_catalogue'] = {'sha256': 'c'*64}
    def seal():
        (library/'acceptance.json').write_text(json.dumps(acceptance))
        manifest['acceptance'] = file_ref(library/'acceptance.json', library, 'application/json')
    seal()
    verify_acceptance(library, manifest, contract_file=contract)
    acceptance['runtime_contract']['source_gates_passed'] = False
    seal()
    with pytest.raises(ValueError):
        verify_acceptance(library, manifest, contract_file=contract)
    acceptance['runtime_contract']['source_gates_passed'] = True
    seal()
    contract.write_bytes(contract.read_bytes()+b' ')
    with pytest.raises(ValueError):
        verify_acceptance(library, manifest, contract_file=contract)


def test_first_switch_restores_original_sql_connection_and_current_on_smoke_failure(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from pathlib import Path
    import sys
    import types
    from dashboard_product.shadow_bi.p4 import sql_release as runtime
    base = tmp_path/'warehouse'
    old = base/'releases/daily-old'
    target = base/'releases/daily-sql-new'
    old.mkdir(parents=True)
    target.mkdir()
    (base/'current').symlink_to(old)
    maintenance = tmp_path/'maintenance'
    real_path = Path
    def local_path(value):
        return {'/var/lib/shadow-bi': base,
                '/run/shadow-bi-maintenance': maintenance}.get(str(value), real_path(value))
    monkeypatch.setattr(runtime, 'Path', local_path)
    monkeypatch.setattr(runtime, 'load_release', lambda _: ({'release_id': target.name}, {'batch_id': 'run_new'}, target/'library/warehouse.duckdb'))
    monkeypatch.setattr(runtime, 'verify_acceptance', lambda *_: {})
    original = {'sqlalchemy_uri': 'duckdb:///old/business.duckdb', 'dataset_sql': {'1': 'SELECT * FROM queries.original'}}
    restored, installed, commands = [], [], []
    def metadata(action, library=None, *, snapshot=None):
        if action == 'snapshot':
            return original
        if action == 'install':
            installed.append(library)
        if action == 'restore':
            restored.append(snapshot)
    monkeypatch.setattr(runtime, '_metadata_call', metadata)
    monkeypatch.setattr(runtime, '_wait_health', lambda: None)
    def failed_smoke(*_):
        raise ValueError('actual HTTP smoke failed')
    monkeypatch.setattr(runtime, 'verify_http', failed_smoke)
    monkeypatch.setattr(runtime.subprocess, 'run', lambda args, **kwargs: commands.append(args))
    app_module = types.ModuleType('superset.app')
    app_module.create_app = lambda: types.SimpleNamespace(app_context=nullcontext)
    monkeypatch.setitem(sys.modules, 'superset.app', app_module)
    with pytest.raises(ValueError, match='actual HTTP smoke failed'):
        runtime._activate(target, expected_current=old.name)
    assert (base/'current').resolve() == old
    assert restored == [original] and len(installed) == 1
    assert not maintenance.exists()
    assert commands[-1] == ['systemctl', 'start', 'shadow-bi']
    assert json.loads((base/'app/sql-cutover'/target.name/'metadata.json').read_text()) == original


def test_metadata_uses_original_peer_identity_and_stdin_for_restore(monkeypatch):
    import subprocess
    from dashboard_product.shadow_bi.p4 import sql_release as runtime
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout='initialization log\n{"status":"restored"}\n')
    monkeypatch.setattr(runtime.subprocess, 'run', run)
    original = {'sqlalchemy_uri': 'duckdb:///original', 'dataset_sql': {'1': 'SELECT 1'}}
    assert runtime._metadata_call('restore', snapshot=original) == {'status': 'restored'}
    command, kwargs = calls[0]
    assert command[:5] == ['runuser', '-u', 'shadowbi', '--preserve-environment', '--']
    assert command[-2:] == ['--metadata-action', 'restore']
    assert json.loads(kwargs['input']) == original
    assert kwargs['check'] and kwargs['capture_output']


@pytest.mark.parametrize('unexpected_file', [False, True])
def test_retire_only_verified_previous_sql_bundle(release, tmp_path, monkeypatch, unexpected_file):
    from pathlib import Path
    import shutil
    from dashboard_product.shadow_bi.p4 import sql_release as runtime
    root, _, _, _ = release
    base = tmp_path/'server'
    (base/'releases').mkdir(parents=True)
    old = base/'releases'/root.name
    shutil.move(root, old)
    for name in ('superset-catalogue.json', 'landing-description.json', 'acceptance.json'):
        (old/'library'/name).write_text('{}')
    current = base/'releases/daily-sql-next'
    shutil.copytree(old, current)
    manifest = json.loads((current/'library/release.json').read_text())
    manifest['release_id'] = current.name
    (current/'library/release.json').write_text(json.dumps(manifest))
    (base/'current').symlink_to(current)
    (base/'previous').symlink_to(old)
    receipt = base/'app/sql-cutover'/current.name/'verification.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({'status': 'passed', 'metrics_compared': 18}))
    if unexpected_file:
        (old/'library/unreviewed.txt').write_text('keep')
    real_path = Path
    monkeypatch.setattr(runtime, 'Path', lambda value: base if str(value) == '/var/lib/shadow-bi' else real_path(value))
    if unexpected_file:
        with pytest.raises(ValueError, match='未核销'):
            runtime.retire_previous(current, expected_previous=old.name)
        assert old.is_dir() and (base/'previous').is_symlink()
    else:
        result = runtime.retire_previous(current, expected_previous=old.name)
        assert result['status'] == 'retired' and result['warehouse_count_in_releases'] == 1
        assert not old.exists() and not (base/'previous').exists()
    assert (current/'library/warehouse.duckdb').is_file()
