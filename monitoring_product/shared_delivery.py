"""Deliver accepted notification payloads from a management shared result.

This module is deliberately a thin delivery adapter: the shared result owns
the business calculations, ``shared_preview`` owns rendering, and ``notify``
provides the existing upload and DingTalk primitives.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
from zoneinfo import ZoneInfo

from monitoring_product import delivery_transport as notify, shared_preview


EXPECTED_MESSAGES = {
    'prep.training': 'offline_youth',
    'high.training': 'offline_high_school',
    'high.abroad': 'offline_high_school',
    'university.training': 'offline_university',
    'university.abroad': 'offline_university',
    'virtual.mixed': 'online_private',
    'online.training': 'online_platform',
    'online.abroad': 'online_platform',
}
STATE_FILENAME = 'shared_delivery_state.json'
LOCK_FILENAME = 'shared_delivery.lock'
STATE_SCHEMA = 'management_shared_delivery_state.v1'
SNAPSHOT_DATE_PATTERN = re.compile(r'_(\d{8})(?=_|$)')


def _today_shanghai() -> date:
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()


def _iso_date(value: str, field: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError(f'{field} must be an ISO date (YYYY-MM-DD)')
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f'{field} is not a valid date') from error


def _snapshot_cut_date(snapshot_id: str) -> date | None:
    match = SNAPSHOT_DATE_PATTERN.search(str(snapshot_id or ''))
    if not match:
        return None
    encoded = match.group(1)
    try:
        return _iso_date(f'{encoded[:4]}-{encoded[4:6]}-{encoded[6:]}', 'snapshot date')
    except ValueError:
        return None


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _message_key(as_of_date: str, channel_id: str, message_id: str) -> str:
    return f'{as_of_date}|{channel_id}|{message_id}'


def _validate_contract(shared: dict, payload: dict, as_of_date: str,
                       *, sending: bool) -> list[dict]:
    shared_metadata = shared.get('metadata') or {}
    notification_metadata = payload.get('metadata') or {}
    for field in ('run_id', 'snapshot_id', 'data_through'):
        if not shared_metadata.get(field):
            raise ValueError(f'shared result metadata is missing {field}')
        if notification_metadata.get(field) != shared_metadata[field]:
            raise ValueError(f'notification {field} does not match shared result metadata')
    if payload.get('data_through') != shared_metadata['data_through']:
        raise ValueError('notification data_through does not match shared result metadata')
    if notification_metadata.get('as_of_date') != as_of_date:
        raise ValueError('notification as_of_date does not match --as-of-date')
    study_source = shared_metadata.get('study_abroad_source')
    if study_source is not None and notification_metadata.get('study_abroad_source') != study_source:
        raise ValueError('notification study-abroad source does not match shared result metadata')

    through = _iso_date(shared_metadata['data_through'], 'data_through')
    as_of = _iso_date(as_of_date, 'as-of-date')
    if sending:
        today = _today_shanghai()
        if as_of != today:
            raise ValueError('sending requires --as-of-date to be today in Asia/Shanghai')
        snapshot_date = _snapshot_cut_date(shared_metadata['snapshot_id'])
        freshness_reasons = []
        if snapshot_date is None:
            freshness_reasons.append(
                f'cannot parse snapshot cut date from snapshot_id: {shared_metadata["snapshot_id"]}',
            )
        elif snapshot_date != as_of:
            freshness_reasons.append(
                f'snapshot {shared_metadata["snapshot_id"]} 不是当天新切 '
                f'(snapshot date {snapshot_date.isoformat()}, as-of {as_of.isoformat()})',
            )
        yesterday = as_of - timedelta(days=1)
        if through != yesterday:
            freshness_reasons.append(
                f'sending requires data_through to be exactly yesterday ({yesterday.isoformat()})',
            )
        if study_source is not None and _iso_date(study_source['through_date'], 'study-abroad through_date') != yesterday:
            freshness_reasons.append(f'留学来源须覆盖至昨日 ({yesterday.isoformat()})，当前为 {study_source["through_date"]}')
        if freshness_reasons:
            raise ValueError('freshness guard blocked delivery: ' + '; '.join(freshness_reasons))

    messages = shared_preview._validate_payload(payload)
    actual = Counter((str(message.get('id')), str(message.get('channel_id'))) for message in messages)
    expected = Counter(EXPECTED_MESSAGES.items())
    if actual != expected:
        raise ValueError('notification messages must match the fixed eight-message, five-channel contract')
    return messages


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {'schema_version': STATE_SCHEMA, 'deliveries': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('schema_version') != STATE_SCHEMA
            or not isinstance(data.get('deliveries'), dict)):
        raise ValueError('shared delivery state has an unsupported or invalid structure')
    return data


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.{secrets.token_hex(4)}.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as output:
            json.dump(state, output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _state_lock(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / LOCK_FILENAME
    with lock_path.open('a+b') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield state_dir / STATE_FILENAME
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _preflight_credentials(messages: list[dict], env_file: Path | None, *, require_upload_credentials=True) -> None:
    if env_file is None:
        raise ValueError('formal delivery requires --env-file')
    env_path = Path(env_file)
    try:
        mode = env_path.stat().st_mode
    except OSError as error:
        raise ValueError('--env-file must be an existing readable regular file') from error
    if not stat.S_ISREG(mode) or not os.access(env_path, os.R_OK):
        raise ValueError('--env-file must be an existing readable regular file')
    notify.load_env_file(env_file)
    missing = []
    for channel_id in sorted({message['channel_id'] for message in messages}):
        if not os.environ.get(notify.webhook_env_name(channel_id)):
            missing.append(notify.webhook_env_name(channel_id))
    for name in (('SERVER_HOST', 'SERVER_PORT', 'SERVER_USER', 'SERVER_PASSWORD')
                 if require_upload_credentials else ()):
        if not os.environ.get(name):
            missing.append(name)
    if missing:
        raise ValueError('missing delivery configuration: ' + ', '.join(missing))


def _rendered_by_id(rendered: dict) -> dict[str, dict]:
    entries = rendered.get('messages')
    if not isinstance(entries, list):
        raise ValueError('notification renderer returned no messages')
    indexed = {str(item.get('id')): item for item in entries if isinstance(item, dict)}
    if len(indexed) != len(entries) or set(indexed) != set(EXPECTED_MESSAGES):
        raise ValueError('notification renderer output does not match the eight-message contract')
    return indexed


def _prepare_markdown(message: dict, artifact: dict, png_url: str, xlsx_url: str) -> str:
    markdown_path = Path(artifact['markdown'])
    markdown = markdown_path.read_text(encoding='utf-8')
    markdown = markdown.replace('![本地消息图片](message.png)', f'![消息图片]({png_url})')
    markdown = markdown.replace('[查看HTML预览](message.html)', '')
    markdown = markdown.replace('[下载相关工单与现金流水](details.xlsx)',
                                f'[下载相关工单与现金流水]({xlsx_url})')
    if any(local_link in markdown for local_link in (
            '](message.png)', '](details.xlsx)', '](message.html)')):
        raise ValueError(f'{message["id"]} markdown still contains a local preview link')
    return markdown.strip()


def _stage_message(output_dir: Path, message: dict, artifact: dict,
                   token: str) -> Path:
    stage_dir = output_dir / f'.delivery-stage-{token}'
    team_dir = stage_dir / message['channel_id']
    team_dir.mkdir(parents=True)
    png = Path(artifact['png'])
    xlsx = Path(artifact['xlsx'])
    for source, name in ((png, 'people.png'), (xlsx, 'details.xlsx')):
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f'{message["id"]} renderer output is missing or empty: {source.name}')
        shutil.copy2(source, team_dir / name)
    return stage_dir


def deliver(shared_result: Path, output_dir: Path, as_of_date: str,
            state_dir: Path, env_file: Path | None = None,
            dashboard_base_url: str | None = None, dry_run: bool = False, *,
            asset_publisher=None, before_send=None, state_validator=None) -> dict:
    shared, payload = shared_preview._read_shared_notifications(shared_result)
    messages = _validate_contract(shared, payload, as_of_date, sending=not dry_run)
    metadata = shared['metadata']
    identity = {field: metadata[field] for field in ('run_id', 'snapshot_id', 'data_through')}

    if dry_run:
        rendered = shared_preview.render_notifications(payload, output_dir, dashboard_base_url)
        return {
            'status': 'dry_run', **identity, 'as_of_date': as_of_date,
            'output_dir': str(output_dir.resolve()),
            'index_html': rendered.get('index_html'),
            'messages': [
                {'id': item['id'], 'channel_id': item['channel_id'],
                 'message_sha256': _canonical_sha256(next(m for m in messages if m['id'] == item['id'])),
                 'png': item['png'], 'xlsx': item['xlsx'], 'markdown': item['markdown']}
                for item in rendered['messages']
            ],
        }

    _preflight_credentials(messages, env_file, require_upload_credentials=asset_publisher is None)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir = state_dir.resolve()
    state_path = state_dir / STATE_FILENAME
    receipts = []
    with _state_lock(state_dir) as locked_state_path:
        state = _load_state(locked_state_path)
        if state_validator is not None:
            state_validator(state_dir, state)
        delivery_rows = state['deliveries']
        pending = []
        for message in messages:
            message_id, channel_id = message['id'], message['channel_id']
            key = _message_key(as_of_date, channel_id, message_id)
            payload_hash = _canonical_sha256({**identity, 'as_of_date': as_of_date, 'message': message})
            prior = delivery_rows.get(key)
            if prior and prior.get('status') == 'sent':
                receipts.append({
                    'id': message_id, 'channel_id': channel_id, 'status': 'sent',
                    'deduplicated': True, 'message_sha256': prior.get('message_sha256'),
                    'run_id': prior.get('run_id'), 'snapshot_id': prior.get('snapshot_id'),
                    'data_through': prior.get('data_through'),
                })
                continue
            if prior and prior.get('status') in {'sending', 'unknown'}:
                receipts.append({
                    'id': message_id, 'channel_id': channel_id, 'status': prior['status'],
                    'blocked': True, 'message_sha256': prior.get('message_sha256'),
                    'run_id': prior.get('run_id'), 'snapshot_id': prior.get('snapshot_id'),
                    'data_through': prior.get('data_through'),
                })
                continue
            if prior and prior.get('status') not in {'pending', 'sent', 'sending', 'unknown'}:
                raise ValueError(f'unsupported saved delivery status for {message_id}')
            row = {
                'as_of_date': as_of_date, 'channel_id': channel_id, 'message_id': message_id,
                **identity, 'message_sha256': payload_hash, 'status': 'pending',
            }
            delivery_rows[key] = row
            pending.append((key, message, row))
        _save_state(state_path, state)

        if pending:
            rendered = shared_preview.render_notifications(payload, output_dir, dashboard_base_url)
            artifacts = _rendered_by_id(rendered)
            origin = (os.environ.get('NOTIFY_PUBLIC_ORIGIN') or notify.DEFAULT_ORIGIN).rstrip('/')
            for key, message, row in pending:
                message_id, channel_id = message['id'], message['channel_id']
                token = secrets.token_hex(16)
                stage_dir = None
                try:
                    artifact = artifacts[message_id]
                    stage_dir = _stage_message(output_dir, message, artifact, token)
                    (asset_publisher or notify.upload_notify_assets)(stage_dir, token, env_file=env_file)
                    png_url, xlsx_url = notify.public_urls(origin, token, channel_id)
                    markdown = _prepare_markdown(message, artifact, png_url, xlsx_url)
                    asset_hashes = {
                        'png': _file_sha256(Path(artifact['png'])),
                        'xlsx': _file_sha256(Path(artifact['xlsx'])),
                        'markdown': hashlib.sha256(markdown.encode('utf-8')).hexdigest(),
                    }
                    if before_send is not None:
                        before_send()
                    row.update({
                        'status': 'sending', 'token': token,
                        'png_url': png_url, 'xlsx_url': xlsx_url,
                        'asset_sha256': asset_hashes,
                        'updated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    })
                    _save_state(state_path, state)
                except Exception as error:
                    # Upload/render errors happen before the DingTalk request. Keep
                    # the record pending so a later invocation can safely retry.
                    row.update({
                        'status': 'pending', 'error': notify.redact_secrets(error, env_file),
                        'updated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    })
                    _save_state(state_path, state)
                    receipts.append({
                        'id': message_id, 'channel_id': channel_id, 'status': 'pending',
                        **identity,
                        'message_sha256': row['message_sha256'],
                        'error': notify.redact_secrets(error, env_file),
                    })
                    if stage_dir is not None:
                        shutil.rmtree(stage_dir, ignore_errors=True)
                    continue

                webhook = os.environ[notify.webhook_env_name(channel_id)]
                secret = os.environ.get(notify.secret_env_name(channel_id)) or ''
                try:
                    outcome = notify.post_dingtalk(
                        webhook, secret, message.get('title') or message_id, markdown,
                    )
                    if not isinstance(outcome, dict) or outcome.get('status') != 'sent':
                        raise RuntimeError('DingTalk delivery did not confirm sent status')
                except Exception as error:  # network outcomes cannot be safely retried
                    row.update({
                        'status': 'unknown',
                        'error': notify.redact_secrets(error, env_file),
                        'updated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    })
                    _save_state(state_path, state)
                    receipts.append({
                        'id': message_id, 'channel_id': channel_id, 'status': 'unknown',
                        **identity,
                        'message_sha256': row['message_sha256'], 'asset_sha256': asset_hashes,
                    })
                else:
                    row.update({
                        'status': 'sent',
                        'delivery': {'status': 'sent', 'message_sha256': row['message_sha256'],
                                      'asset_sha256': asset_hashes},
                        'updated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    })
                    _save_state(state_path, state)
                    receipts.append({
                        'id': message_id, 'channel_id': channel_id, 'status': 'sent',
                        **identity,
                        'deduplicated': False, 'message_sha256': row['message_sha256'],
                        'asset_sha256': asset_hashes, 'png_url': png_url, 'xlsx_url': xlsx_url,
                    })
                finally:
                    if stage_dir is not None:
                        shutil.rmtree(stage_dir, ignore_errors=True)

    statuses = [item['status'] for item in receipts]
    status = 'sent' if all(value == 'sent' for value in statuses) else 'partial'
    return {
        'status': status, **identity, 'as_of_date': as_of_date,
        'output_dir': str(output_dir.resolve()), 'state_file': str(state_path),
        'messages': receipts,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Deliver notifications from a management shared result.')
    parser.add_argument('--shared-result', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--as-of-date', required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--dashboard-base-url')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = deliver(
            args.shared_result, args.output_dir, args.as_of_date,
            args.state_dir, args.env_file, args.dashboard_base_url, args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result['status'] in {'sent', 'dry_run'} else 1
    except Exception as error:
        redacted = (notify.redact_secrets(error, args.env_file)
                    if not args.dry_run and args.env_file else str(error))
        print(json.dumps({'status': 'blocked', 'error': redacted}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
