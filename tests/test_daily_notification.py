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
