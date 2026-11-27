import hashlib
import json
from pathlib import Path

import pytest

from dashboard_product.shadow_bi.p5 import notification_contract as contract
from monitoring_product import bundle_retention, release_notifications, shared_delivery


@pytest.fixture
def environment(tmp_path, monkeypatch):
    warehouse = tmp_path/'warehouse'
    home = tmp_path/'notify'
    releases = warehouse/'releases'
    current = releases/'daily-current'
    (current/'library').mkdir(parents=True)
    (current/'library/release.json').write_text(json.dumps({'as_of_date': '2026-11-28'}))
    (warehouse/'current').symlink_to(current)
    previous = releases/'daily-previous'
    previous.mkdir()
    (warehouse/'previous').symlink_to(previous)
    (home/'bundles').mkdir(parents=True)
    (home/'state').mkdir()
    (warehouse/'receiver/notify-pending').mkdir(parents=True)
    (warehouse/'receiver/notify-requests').mkdir()
    (warehouse/'notify-control/results').mkdir(parents=True)
    entry = tmp_path/'entry.lock'
    dispatch = tmp_path/'dispatch.lock'
    for path in (entry, dispatch, home/'.run.lock', warehouse/'receiver/.notify.lock',
                 home/'state'/shared_delivery.LOCK_FILENAME):
        path.touch()
    (home/'state'/shared_delivery.STATE_FILENAME).write_text('unchanged delivery state')
    assets = tmp_path/'public-attachments'
    assets.mkdir()
    (assets/'people.png').write_bytes(b'preserve public attachment')
    state = {'deliveries': {}}
    monkeypatch.setattr(release_notifications, 'require_imported_state', lambda _: state)
    return warehouse, home, entry, dispatch, state, assets


def bundle(home, release, day):
    folder = home/'bundles'/(release+'-'+'a'*16)
    folder.mkdir()
    shared = folder/'shared_result.json'
    notification = folder/'notifications.json'
    shared.write_text('derived shared result')
    notification.write_text('derived notification')
    (folder/'bundle.json').write_text(json.dumps({
        'schema_version': release_notifications.SCHEMA,
        'source_mode': 'sql_warehouse',
        'source': {'release_id': release, 'as_of_date': day},
        'shared_result': {'path': shared.name, 'sha256': hashlib.sha256(shared.read_bytes()).hexdigest()},
        'notifications': {'path': notification.name, 'sha256': hashlib.sha256(notification.read_bytes()).hexdigest()},
    }))
    return folder


def sent(state, day, *, status='sent'):
    for message, channel in shared_delivery.EXPECTED_MESSAGES.items():
        key = shared_delivery._message_key(day, channel, message)
        state['deliveries'][key] = {'status': status}


def run(env):
    warehouse, home, entry, dispatch, _, _ = env
    return bundle_retention.retire_obsolete_bundles(
        warehouse=warehouse, home=home, entry_lock=entry, dispatch_lock=dispatch)


def test_removes_only_obsolete_confirmed_and_old_preview_bundles(environment):
    warehouse, home, _, _, state, assets = environment
    sent(state, '2026-11-25')
    sent(state, '2026-11-26', status='pending')
    removed = bundle(home, 'daily-retired', '2026-11-25')
    preview = bundle(home, 'daily-preview', '2026-11-24')
    active = bundle(home, 'daily-current', '2026-11-25')
    previous = bundle(home, 'daily-previous', '2026-11-25')
    pending = bundle(home, 'daily-pending', '2026-11-26')
    incomplete = bundle(home, 'daily-today', '2026-11-28')
    ledger = home/'state'/shared_delivery.STATE_FILENAME
    before = hashlib.sha256(ledger.read_bytes()).hexdigest()

    result = run(environment)

    assert result['status'] == 'passed'
    assert set(result['removed']) == {removed.name, preview.name}
    assert all(path.is_dir() for path in (active, previous, pending, incomplete))
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == before
    assert (assets/'people.png').read_bytes() == b'preserve public attachment'


@pytest.mark.parametrize('state_name,retryable', [('unknown', False), ('running', False),
                                                  ('partial', False), ('blocked', True)])
def test_preserves_unresolved_and_retryable_jobs(environment, state_name, retryable):
    warehouse, home, _, _, state, _ = environment
    sent(state, '2026-11-25')
    folder = bundle(home, 'daily-unresolved', '2026-11-25')
    request = {'operation': 'send-scheduled', 'expected_release': 'daily-unresolved',
               'as_of_date': '2026-11-25'}
    identifier = contract.job_id(request)
    (warehouse/'notify-control/results'/(identifier+'.json')).write_text(json.dumps({
        **request, 'status': state_name, 'retryable': retryable,
    }))
    assert run(environment)['removed'] == []
    assert folder.is_dir()


def test_preserves_queued_request(environment):
    warehouse, home, _, _, state, _ = environment
    sent(state, '2026-11-25')
    folder = bundle(home, 'daily-queued', '2026-11-25')
    request = {'operation': 'preview', 'expected_release': 'daily-queued',
               'as_of_date': '2026-11-25'}
    identifier = contract.job_id(request)
    (warehouse/'receiver/notify-pending'/identifier).touch()
    (warehouse/'receiver/notify-requests'/(identifier+'.json')).write_text(json.dumps(request))
    assert run(environment)['removed'] == []
    assert folder.is_dir()


def test_busy_notification_lock_stops_cleaning(environment):
    import fcntl

    warehouse, home, entry, _, state, _ = environment
    sent(state, '2026-11-25')
    folder = bundle(home, 'daily-retired', '2026-11-25')
    with entry.open('r+b') as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run(environment) == {'status': 'skipped', 'reason': 'notification_busy', 'removed': []}
    assert folder.is_dir()


@pytest.mark.parametrize('change', ['extra', 'legacy', 'damaged', 'symlink'])
def test_preserves_unrecognized_bundle_footprint(environment, change):
    _, home, _, _, state, _ = environment
    sent(state, '2026-11-25')
    folder = bundle(home, 'daily-retired', '2026-11-25')
    manifest = folder/'bundle.json'
    if change == 'extra':
        (folder/'unrecognized.txt').write_text('preserve')
    elif change == 'legacy':
        data = json.loads(manifest.read_bytes())
        data['source_mode'] = 'legacy'
        manifest.write_text(json.dumps(data))
    elif change == 'damaged':
        (folder/'notifications.json').write_text('changed')
    else:
        (folder/'notifications.json').unlink()
        (folder/'notifications.json').symlink_to(manifest)
    assert run(environment)['removed'] == []
    assert folder.is_dir()


def test_empty_or_absent_bundle_directory_needs_no_notification_locks(environment):
    warehouse, home, entry, dispatch, _, _ = environment
    entry.unlink()
    dispatch.unlink()
    assert run(environment)['removed'] == []
    (home/'bundles').rmdir()
    assert run(environment)['removed'] == []
