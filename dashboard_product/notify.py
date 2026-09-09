#!/usr/bin/env python3
"""Build and send per-team DingTalk personnel progress messages."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import hashlib
import base64
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dashboard_product.digest import NOTIFY_CHANNEL_IDS, NOTIFY_CHANNELS, apply_warehouse_actuals, build_all_digests, ensure_roster, ledger_attributions, missing_cash_order_ids, resolve_channels
from dashboard_product.notify_render import (
    dingtalk_title,
    render_markdown,
    render_people_html,
    write_details_xlsx,
    write_people_image,
)

ROOT = Path(__file__).parent
DEFAULT_ORIGIN = 'http://dashboard.apinova.cn'


DROP_WAREHOUSE_COLUMNS = {'source_sha256', 'ingest_batch_id', 'source_id', 'snapshot_id'}
DATE_HINTS = ('时间', '日期')


def _excel_date(value):
    from datetime import date, timedelta
    if value in (None, ''):
        return value
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return value
    if 20000 <= number <= 80000:
        return (date(1899, 12, 30) + timedelta(days=int(number))).isoformat()
    return value


def _load_query_table(payload):
    if payload.get('result') and payload['result'].get('rows') is not None:
        return payload['result']['columns'], payload['result']['rows']
    artifact = payload.get('artifact') or {}
    path = artifact.get('path')
    if not path:
        return [], []
    return None, path


def _pack_warehouse_table(columns, rows, owners=None):
    keep = [column for column in columns if column not in DROP_WAREHOUSE_COLUMNS]
    indexes = [columns.index(column) for column in keep]
    date_cols = {index for index, column in enumerate(keep) if any(hint in column for hint in DATE_HINTS)}
    packed = []
    for row_index, row in enumerate(rows):
        packed_row = []
        if owners is not None:
            packed_row.append(owners[row_index] if row_index < len(owners) else '未归属')
        for position, source in enumerate(indexes):
            value = row[source] if source < len(row) else None
            if position in date_cols:
                value = _excel_date(value)
            packed_row.append(value)
        packed.append(packed_row)
    return {'columns': (['归属人'] + keep) if owners is not None else keep, 'rows': packed}


def find_warehouse(workspace, snapshot_id):
    matches = list((Path(workspace) / 'Work' / 'Runs').glob(f'**/snapshots/{snapshot_id}/warehouse.duckdb'))
    if not matches:
        raise FileNotFoundError(f'warehouse not found for {snapshot_id}')
    return matches[0]


def run_detail_query(workspace, snapshot_id, run_id, sql_file, params, output_root):
    import subprocess
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    command = [
        'python3', '-m', 'interfaces.data_platform', 'query',
        '--warehouse', str(find_warehouse(workspace, snapshot_id)),
        '--snapshot-id', snapshot_id,
        '--run-id', run_id,
        '--output-root', str(output_root),
        '--sql-file', str(sql_file),
        '--params-json', json.dumps(params),
        '--max-rows', '20000',
        '--max-result-bytes', '20000000',
    ]
    completed = subprocess.run(command, cwd=str(ROOT.parent), capture_output=True, text=True)
    payload = json.loads(completed.stdout or '{}')
    if payload.get('status') != 'passed':
        raise ValueError(f'detail query failed: {payload.get("errors") or completed.stderr}')
    if payload.get('result') and payload['result'].get('rows') is not None:
        return payload['result']['columns'], payload['result']['rows']
    artifact = payload.get('artifact') or {}
    relative = artifact.get('path')
    if not relative:
        return [], []
    data = read_json(output_root / run_id / relative)
    return data['columns'], data['rows']


def fetch_channel_ledger(artifact, digest, workspace=None, output_root=None):
    workspace = Path(workspace) if workspace else ROOT.parent / 'customers' / 'bi_operations'
    output_root = Path(output_root) if output_root else Path(digest.get('output_root') or '/tmp/dashboard-notify-query')
    channel = NOTIFY_CHANNELS[digest['team_id']]
    from datetime import date, timedelta
    start = date.fromisoformat(digest['window_start'])
    end = date.fromisoformat(digest['window_end']) + timedelta(days=1)
    params = [start.isoformat(), end.isoformat(), channel['team_id'], channel['business_group']]
    snapshot_id = artifact['snapshot_id']
    orders_columns, orders_rows = run_detail_query(
        workspace, snapshot_id, f"{artifact['run_id']}_{digest['team_id']}_orders",
        ROOT / 'sql' / 'notify_work_orders.sql', params, output_root,
    )
    cash_columns, cash_rows = run_detail_query(
        workspace, snapshot_id, f"{artifact['run_id']}_{digest['team_id']}_cash",
        ROOT / 'sql' / 'notify_cash.sql', params, output_root,
    )
    extra_columns, extra_rows = [], []
    missing_ids = missing_cash_order_ids(orders_columns, orders_rows, cash_columns, cash_rows)
    if missing_ids:
        extra_columns, extra_rows = run_detail_query(
            workspace, snapshot_id, f"{artifact['run_id']}_{digest['team_id']}_orders_by_id",
            ROOT / 'sql' / 'notify_work_orders_by_ids.sql', [missing_ids], output_root,
        )
    order_owners, cash_owners = ledger_attributions(
        orders_columns, orders_rows, cash_columns, cash_rows, digest.get('people') or [],
        extra_order_columns=extra_columns, extra_order_rows=extra_rows,
    )
    return {
        'orders': _pack_warehouse_table(orders_columns, orders_rows, owners=order_owners),
        'cash': _pack_warehouse_table(cash_columns, cash_rows, owners=cash_owners),
    }



def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_notify_config():
    path = ROOT / 'config' / 'dingtalk.json'
    if not path.exists():
        return {'schema_version': 'dashboard_dingtalk.v1', 'public_origin': DEFAULT_ORIGIN}
    data = read_json(path)
    data.setdefault('public_origin', DEFAULT_ORIGIN)
    return data


def public_origin(config):
    return os.environ.get('NOTIFY_PUBLIC_ORIGIN') or config.get('public_origin') or DEFAULT_ORIGIN


def webhook_env_name(team_id):
    return f'DINGTALK_WEBHOOK_{team_id.upper()}'


def secret_env_name(team_id):
    return f'DINGTALK_SECRET_{team_id.upper()}'


def signed_webhook(url, secret):
    if not secret:
        return url
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f'{timestamp}\n{secret}'.encode('utf-8')
    digest = hmac.new(secret.encode('utf-8'), string_to_sign, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    joiner = '&' if '?' in url else '?'
    return f'{url}{joiner}timestamp={timestamp}&sign={sign}'


def post_dingtalk(webhook, secret, title, text):
    url = signed_webhook(webhook, secret)
    payload = json.dumps({
        'msgtype': 'markdown',
        'markdown': {'title': title, 'text': text},
    }, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    import ssl
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=20, context=context) as response:
        body = json.loads(response.read().decode('utf-8'))
    if body.get('errcode') not in (0, None):
        raise ValueError(f'dingtalk rejected message: {body.get("errmsg") or body}')
    return {'status': 'sent'}


def write_team_artifacts(digest, output_dir, artifact=None, workspace=None):
    team_dir = Path(output_dir) / digest['team_id']
    team_dir.mkdir(parents=True, exist_ok=True)
    html_path = team_dir / 'people.html'
    png_path = team_dir / 'people.png'
    xlsx_path = team_dir / 'details.xlsx'
    md_path = team_dir / 'message.md'
    digest = dict(digest)
    people_config_path = ROOT / 'config' / 'people.json'
    if people_config_path.exists():
        months = ((artifact or {}).get('dashboard') or {}).get('months') or []
        digest = ensure_roster(digest, read_json(people_config_path), months=months)
    if artifact is not None:
        try:
            digest['warehouse'] = fetch_channel_ledger(artifact, digest, workspace=workspace, output_root=Path(output_dir) / '_query')
            digest = apply_warehouse_actuals(digest)
        except Exception as error:
            digest = dict(digest)
            digest['warehouse_error'] = str(error)
    html_path.write_text(render_people_html(digest), encoding='utf-8')
    write_people_image(digest, html_path, png_path)
    write_details_xlsx(digest, xlsx_path)
    preview = render_markdown(digest, str(png_path), str(xlsx_path))
    md_path.write_text(preview, encoding='utf-8')
    return {
        'team_id': digest['team_id'],
        'display_name': digest['display_name'],
        'html': str(html_path),
        'png': str(png_path),
        'xlsx': str(xlsx_path),
        'markdown': str(md_path),
        'digest': {
            'perf_month': digest['perf_month'],
            'people': len(digest['people']),
            'behind': [item['display_name'] for item in digest['behind']],
            'orders': digest['orders'],
            'cash': digest['cash'],
        },
    }


def stage_upload_tree(team_files, stage_dir):
    import shutil
    stage_dir = Path(stage_dir)
    for item in team_files:
        dest = stage_dir / item['team_id']
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item['png'], dest / 'people.png')
        shutil.copy2(item['xlsx'], dest / 'details.xlsx')
        if (dest / 'people.html').exists() or (dest / 'message.md').exists():
            raise ValueError('refusing to stage html or markdown')
    if any(path.suffix.lower() not in {'.png', '.xlsx'} for path in stage_dir.rglob('*') if path.is_file()):
        raise ValueError('notify stage may only contain png and xlsx')
    return stage_dir


def upload_notify_assets(stage_dir, token, env_file=None):
    script = ROOT / 'deploy' / 'publish_notify_assets.sh'
    env = os.environ.copy()
    if env_file:
        env['ENV_FILE'] = str(env_file)
    env['NOTIFY_TOKEN'] = token
    env['NOTIFY_STAGE'] = str(stage_dir)
    completed = __import__('subprocess').run(
        ['/bin/bash', str(script)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def public_urls(origin, token, team_id):
    base = f'{origin.rstrip("/")}/notify/{token}/{team_id}'
    return f'{base}/people.png', f'{base}/details.xlsx'


def send_team_message(digest, png_url, xlsx_url):
    webhook = os.environ.get(webhook_env_name(digest['team_id']))
    if not webhook:
        return {'status': 'skipped', 'reason': f'missing {webhook_env_name(digest["team_id"])}'}
    secret = os.environ.get(secret_env_name(digest['team_id'])) or ''
    text = render_markdown(digest, png_url, xlsx_url)
    post_dingtalk(webhook, secret, dingtalk_title(digest), text)
    return {'status': 'sent', 'png': png_url, 'xlsx': xlsx_url}


def default_output_dir(artifact_path):
    return Path(artifact_path).resolve().parent / 'notify'


def load_env_file(path):
    path = Path(path)
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())


def send(artifact, team_ids=None, dry_run=False, output_dir=None, env_file=None):
    artifact_path = Path(artifact)
    data = read_json(artifact_path)
    config = load_notify_config()
    if env_file:
        load_env_file(env_file)
    elif (ROOT / '.env.server').exists():
        load_env_file(ROOT / '.env.server')
    selected = resolve_channels(team_ids)
    digests = build_all_digests(data, selected)
    output_dir = Path(output_dir) if output_dir else default_output_dir(artifact_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = [write_team_artifacts(digest, output_dir, artifact=data) for digest in digests]
    result = {
        'status': 'dry_run' if dry_run else 'built',
        'artifact': str(artifact_path),
        'output_dir': str(output_dir),
        'teams': files,
    }
    if dry_run:
        return result
    token = secrets.token_hex(16)
    stage_dir = output_dir / f'.stage-{token}'
    try:
        stage_upload_tree(files, stage_dir)
        upload_notify_assets(stage_dir, token, env_file=env_file or ROOT / '.env.server')
        origin = public_origin(config)
        deliveries = []
        for digest in digests:
            png_url, xlsx_url = public_urls(origin, token, digest['team_id'])
            delivery = send_team_message(digest, png_url, xlsx_url)
            delivery['team_id'] = digest['team_id']
            deliveries.append(delivery)
        result['status'] = 'sent' if all(item['status'] == 'sent' for item in deliveries) else 'partial'
        result['token'] = token
        result['deliveries'] = deliveries
        if result['status'] != 'sent':
            missing = [item['team_id'] for item in deliveries if item['status'] != 'sent']
            result['errors'] = [f'not sent: {team_id}' for team_id in missing]
        return result
    finally:
        import shutil
        shutil.rmtree(stage_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    send_parser = sub.add_parser('send')
    send_parser.add_argument('--artifact', type=Path, required=True)
    send_parser.add_argument('--team', action='append', help='channel id, or offline_market for the three offline groups')
    send_parser.add_argument('--dry-run', action='store_true')
    send_parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.command == 'send':
        result = send(args.artifact, team_ids=args.team, dry_run=args.dry_run, output_dir=args.output_dir)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] in {'dry_run', 'sent'} else 1
    raise SystemExit('unknown command')


if __name__ == '__main__':
    raise SystemExit(main())
