"""Send the fixed daily notification after business publication, before fees."""
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

from dashboard_product.shadow_bi.p5.daily import ssh_config
from dashboard_product.shadow_bi.p5.full_daily import atomic_json

SHANGHAI = ZoneInfo('Asia/Shanghai')


def _sent(value, day, release):
    return (isinstance(value, dict) and value.get('status') == 'sent'
            and value.get('release_id') == release and value.get('as_of_date') == day
            and value.get('message_count') == 8
            and value.get('message_status_counts') == {'sent': 8})


def _execute(workspace, day, release, log):
    ssh, env = ssh_config(workspace / '.private')
    with log.open('x') as output:
        return subprocess.run(
            ssh + [f'/usr/local/sbin/shadow-bi-notify send-published {release} {day}'],
            env=env, stdout=output, stderr=subprocess.STDOUT,
        ).returncode


def notify_published(workspace, day, release, batch_dir, *, clock=None, execute=None):
    """Immediately send the published business release; never replay an unknown send."""
    workspace, batch = Path(workspace).resolve(), Path(batch_dir).resolve()
    if not re.fullmatch(r'daily-[A-Za-z0-9_-]{1,96}', release):
        raise ValueError('invalid expected notification release')
    clock = clock or (lambda: datetime.now(SHANGHAI))
    execute = execute or _execute
    batch.mkdir(parents=True, exist_ok=True)
    attempt = batch / 'notification-attempt.json'
    outcome = batch / 'notification-result.json'
    log = batch / 'notification.log'
    if outcome.exists():
        value = json.loads(outcome.read_text())
        if value.get('release_id') != release or value.get('as_of_date') != day:
            raise ValueError('notification batch identity changed')
        return value
    if attempt.exists() or log.exists():
        value = {'status': 'unknown', 'release_id': release, 'as_of_date': day,
                 'reason': 'existing_send_attempt_requires_server_state_review_no_resubmit'}
        atomic_json(outcome, value)
        return value
    now = clock().astimezone(SHANGHAI)
    if now.date().isoformat() != day:
        raise ValueError('notification requires Shanghai today')
    atomic_json(attempt, {'status': 'running', 'release_id': release, 'as_of_date': day,
                          'started_at': now.isoformat()})
    try:
        code = execute(workspace, day, release, log)
    except Exception as error:
        value = {'status': 'unknown', 'release_id': release, 'as_of_date': day,
                 'reason': 'notification_execution_unconfirmed_no_resubmit',
                 'error_type': type(error).__name__}
        atomic_json(outcome, value)
        return value
    messages = []
    for line in log.read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get('release_id') == release:
            messages.append(value)
    if code == 0 and len(messages) == 1 and _sent(messages[0], day, release):
        value = messages[0]
    else:
        value = {'status': 'unknown', 'release_id': release, 'as_of_date': day,
                 'reason': 'notification_not_fully_confirmed_review_log_and_state_no_resubmit',
                 'exit_code': code}
    atomic_json(outcome, value)
    return value


def notify_published_resumable(workspace, day, release, batch_dir, *, clock=None, execute=None):
    """Reconcile through the existing server lock; never infer delivery from local files.

    Each invocation has its own evidence directory. The fixed server entry decides
    under its delivery lock which messages are already sent or safe to send.
    """
    import uuid

    workspace, batch = Path(workspace).resolve(), Path(batch_dir).resolve()
    if not re.fullmatch(r'daily-[A-Za-z0-9_-]{1,96}', release):
        raise ValueError('invalid expected notification release')
    now = (clock or (lambda: datetime.now(SHANGHAI)))().astimezone(SHANGHAI)
    if now.date().isoformat() != day:
        raise ValueError('notification requires Shanghai today')
    attempts = batch / 'notification-attempts'
    attempts.mkdir(parents=True, exist_ok=True)
    attempt = attempts / uuid.uuid4().hex
    attempt.mkdir()
    atomic_json(attempt / 'attempt.json', {'status': 'running', 'release_id': release,
                                           'as_of_date': day, 'started_at': now.isoformat()})
    log = attempt / 'notification.log'
    try:
        code = (execute or _execute)(workspace, day, release, log)
    except Exception as error:
        value = {'status': 'unknown', 'release_id': release, 'as_of_date': day,
                 'reason': 'notification_execution_unconfirmed', 'error_type': type(error).__name__}
    else:
        messages = []
        for line in log.read_text().splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get('release_id') == release:
                messages.append(item)
        value = {'status': 'unknown', 'release_id': release, 'as_of_date': day,
                 'reason': 'notification_not_fully_confirmed', 'exit_code': code}
        if len(messages) == 1:
            report = messages[0]
            counts = report.get('message_status_counts')
            deduplicated = report.get('deduplicated')
            network = report.get('network_send_attempted')
            valid_counts = (isinstance(counts, dict) and set(counts) <= {'sent', 'pending', 'sending', 'unknown'}
                            and all(type(v) is int and v >= 0 for v in counts.values())
                            and sum(counts.values()) == 8)
            if (report.get('as_of_date') == day and report.get('message_count') == 8
                    and valid_counts and type(deduplicated) is int and 0 <= deduplicated <= counts.get('sent', 0)
                    and type(network) is bool):
                if code == 0 and report.get('status') == 'sent' and counts == {'sent': 8}:
                    value = dict(report)
                    if deduplicated == 8 and network is False:
                        value['reason'] = 'already_sent_today'
                elif code == 2 and report.get('status') == 'partial':
                    value = dict(report)
    atomic_json(attempt / 'result.json', value)
    return value
