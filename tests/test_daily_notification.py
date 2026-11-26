import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from data_acquisition.jobs.daily_notification import notify_published


DAY = '2026-10-30'
RELEASE = 'daily-20261030_093500'
TZ = ZoneInfo('Asia/Shanghai')


def sent():
    return {'status': 'sent', 'release_id': RELEASE, 'as_of_date': DAY,
            'message_count': 8, 'message_status_counts': {'sent': 8}}


def execute_ok(workspace, day, release, log):
    log.write_text(json.dumps(sent()) + '\n')
    return 0


@pytest.mark.parametrize('hour, minute', [(9, 35), (11, 0)])
def test_sends_immediately_at_any_hour_on_the_release_day(tmp_path, hour, minute):
    now = datetime(2026, 10, 30, hour, minute, tzinfo=TZ)
    execute = Mock(side_effect=execute_ok)
    result = notify_published(tmp_path, DAY, RELEASE, tmp_path/'batch',
                              clock=lambda: now, execute=execute)
    assert result == sent()
    assert notify_published(tmp_path, DAY, RELEASE, tmp_path/'batch',
                            clock=lambda: now, execute=execute) == sent()
    execute.assert_called_once()


def test_unconfirmed_transport_is_never_replayed(tmp_path):
    execute = Mock(side_effect=OSError('private transport detail'))
    batch = tmp_path/'batch'
    kwargs = dict(clock=lambda: datetime(2026, 10, 30, 10, 1, tzinfo=TZ), execute=execute)
    result = notify_published(tmp_path, DAY, RELEASE, batch, **kwargs)
    assert result['status'] == 'unknown'
    assert 'private transport detail' not in (batch/'notification-result.json').read_text()
    assert notify_published(tmp_path, DAY, RELEASE, batch, **kwargs) == result
    execute.assert_called_once()


def test_interrupted_attempt_without_result_blocks_replay(tmp_path):
    batch = tmp_path/'batch'; batch.mkdir()
    (batch/'notification-attempt.json').write_text('{}')
    execute = Mock()
    result = notify_published(tmp_path, DAY, RELEASE, batch, execute=execute)
    assert result['status'] == 'unknown'
    execute.assert_not_called()


@pytest.mark.parametrize('now, day', [
    (datetime(2026, 10, 30, 11, 0, tzinfo=TZ), '2026-10-29'),
    (datetime(2026, 10, 31, 9, 35, tzinfo=TZ), DAY),
])
def test_cross_day_does_not_send(tmp_path, now, day):
    execute = Mock()
    with pytest.raises(ValueError):
        notify_published(tmp_path, day, RELEASE, tmp_path/'batch',
                          clock=lambda: now, execute=execute)
    execute.assert_not_called()


def test_partial_messages_do_not_look_successful(tmp_path):
    def partial(workspace, day, release, log):
        log.write_text(json.dumps({**sent(), 'status': 'partial',
                                  'message_status_counts': {'sent': 7, 'unknown': 1}}))
        return 2
    result = notify_published(tmp_path, DAY, RELEASE, tmp_path/'batch',
                              clock=lambda: datetime(2026, 10, 30, 10, 1, tzinfo=TZ), execute=partial)
    assert result['status'] == 'unknown'


def test_different_release_cannot_reuse_a_sent_receipt(tmp_path):
    batch = tmp_path/'batch'; batch.mkdir()
    (batch/'notification-result.json').write_text(json.dumps(sent()))
    with pytest.raises(ValueError, match='identity'):
        notify_published(tmp_path, DAY, 'daily-other', batch)


def test_execute_uses_published_send_mode(tmp_path, monkeypatch):
    from data_acquisition.jobs import daily_notification

    calls = []
    monkeypatch.setattr(daily_notification, 'ssh_config', lambda private: (['ssh', 'host'], {'X': '1'}))
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(daily_notification.subprocess, 'run', run)

    assert daily_notification._execute(tmp_path, DAY, RELEASE, tmp_path/'notification.log') == 0
    assert calls[0][0] == ['ssh', 'host', f'/usr/local/sbin/shadow-bi-notify send-published {RELEASE} {DAY}']


def _server_report(**changes):
    return {**sent(), 'deduplicated': 8, 'network_send_attempted': False, **changes}


def test_resume_reconciles_crashed_local_attempt_with_server_dedup(tmp_path):
    from data_acquisition.jobs.daily_notification import notify_published_resumable
    batch = tmp_path / 'batch'
    old = batch / 'notification-attempts' / 'crashed'
    old.mkdir(parents=True)
    (old / 'attempt.json').write_text('{}')
    calls = []

    def execute(workspace, day, release, log):
        calls.append(log)
        log.write_text(json.dumps(_server_report()))
        return 0

    result = notify_published_resumable(tmp_path, DAY, RELEASE, batch,
        clock=lambda: datetime(2026, 10, 30, 10, 1, tzinfo=TZ), execute=execute)
    assert result['status'] == 'sent' and result['reason'] == 'already_sent_today'
    assert result['network_send_attempted'] is False
    assert len(calls) == 1 and calls[0].parent != old
    assert (old / 'attempt.json').read_text() == '{}'


def test_resume_reports_partial_and_uses_new_attempt_for_next_server_decision(tmp_path):
    from data_acquisition.jobs.daily_notification import notify_published_resumable
    reports = iter([
        (_server_report(status='partial', message_status_counts={'sent': 7, 'pending': 1},
                        deduplicated=7, network_send_attempted=False), 2),
        (_server_report(deduplicated=7, network_send_attempted=True), 0),
    ])
    logs = []

    def execute(workspace, day, release, log):
        logs.append(log)
        report, code = next(reports)
        log.write_text(json.dumps(report))
        return code

    kwargs = dict(clock=lambda: datetime(2026, 10, 30, 10, 1, tzinfo=TZ), execute=execute)
    first = notify_published_resumable(tmp_path, DAY, RELEASE, tmp_path/'batch', **kwargs)
    second = notify_published_resumable(tmp_path, DAY, RELEASE, tmp_path/'batch', **kwargs)
    assert first['status'] == 'partial'
    assert second['status'] == 'sent' and second.get('reason') != 'already_sent_today'
    assert len(set(logs)) == 2
    assert all((log.parent / 'result.json').is_file() for log in logs)


def test_resume_does_not_accept_unconfirmed_or_inconsistent_receipt(tmp_path):
    from data_acquisition.jobs.daily_notification import notify_published_resumable
    def execute(workspace, day, release, log):
        log.write_text(json.dumps(_server_report(message_status_counts={'sent': 7, 'unknown': 1})))
        return 0
    result = notify_published_resumable(tmp_path, DAY, RELEASE, tmp_path/'batch',
        clock=lambda: datetime(2026, 10, 30, 10, 1, tzinfo=TZ), execute=execute)
    assert result['status'] == 'unknown'
