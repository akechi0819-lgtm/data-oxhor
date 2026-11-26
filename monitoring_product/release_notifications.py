"""Server-side notification bundles from a pinned, controlled BI release.

Build/preview are offline. Formal delivery additionally requires an operator
imported delivery baseline; this module never initializes or imports one.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from monitoring_product import shared_delivery as delivery, delivery_transport as transport

SCHEMA = 'release_notifications.v1'
NATIVE_URL = 'https://dashboard.apinova.cn/superset/dashboard/shadow-bi-native/?standalone=1'
TABLES = ('periods', 'team_periods', 'facts', 'personnel_facts', 'target_roster_references')
ROOT = Path(__file__).resolve().parents[1]
RULE_FILES = ('monitoring_product/release_notifications.py', 'monitoring_product/server_notify.py',
              'monitoring_product/shared_delivery.py', 'monitoring_product/shared_preview.py',
              'monitoring_product/delivery_transport.py', 'monitoring_product/sql_release_notifications.py',
              'dashboard_product/shadow_bi/p4/sql_release.py')



def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def rule_binding():
    return {name: sha(ROOT / name) for name in RULE_FILES}


def build_bundle(*, library, batch_id, release_id, output_dir):
    from monitoring_product.sql_release_notifications import build_bundle as build_sql_bundle
    return build_sql_bundle(library=library, batch_id=batch_id, release_id=release_id, output_dir=output_dir)


def _bound_file(root, reference):
    relative = Path(reference['path'])
    raw = root/relative
    p = raw.resolve()
    if relative.is_absolute() or '..' in relative.parts or raw.is_symlink() or not p.is_relative_to(root) or not p.is_file() or sha(p) != reference['sha256']:
        raise ValueError('notification artifact digest/path mismatch')
    return p


def verify_bundle(bundle_path, current_release, *, fresh=False):
    from monitoring_product.sql_release_notifications import verify_bundle as verify_sql_bundle
    return verify_sql_bundle(bundle_path, current_release, fresh=fresh)


def require_imported_state(state_dir, state=None):
    """Only an explicit, immutable operator-import record permits server sending."""
    root = Path(state_dir).resolve()
    proof = root.parent/'state-origin'
    for path in (proof/'delivery_origin.json', proof/'imported_state.json', root/delivery.STATE_FILENAME):
        if not path.is_file() or path.is_symlink():
            raise ValueError('original DeliveryState and migration evidence required before sending')
    origin = json.loads((proof/'delivery_origin.json').read_bytes())
    if (origin.get('schema_version') != 'delivery_state_import.v1' or origin.get('source') not in {'local-project', 'grok'}
        or origin.get('channels') != sorted(transport.ALLOWED_CHANNELS)
        or origin.get('sha256') != sha(proof/'imported_state.json')):
        raise ValueError('invalid delivery state migration evidence')
    original = delivery._load_state(proof/'imported_state.json')
    current = delivery._load_state(root/delivery.STATE_FILENAME) if state is None else state
    for key, row in original['deliveries'].items():
        saved = current['deliveries'].get(key)
        if saved is None or (row.get('status') in {'sent', 'sending', 'unknown'} and saved.get('status') != row['status']):
            raise ValueError('imported sent/uncertain delivery state must not be cleared')
    policy = origin.get('cutover_policy') or {}
    if (policy.get('no_backfill') is not True or policy.get('history_complete') is not False
            or not isinstance(policy.get('send_start_date'), str)):
        raise ValueError('explicit no-backfill cutover policy required')
    from datetime import date
    if date.fromisoformat(policy['send_start_date']).isoformat() != policy['send_start_date']:
        raise ValueError('canonical cutover date required')
    return current


def require_send_date(state_dir, as_of_date):
    require_imported_state(state_dir)
    policy = json.loads((Path(state_dir).resolve().parent/'state-origin/delivery_origin.json').read_bytes())['cutover_policy']
    if as_of_date < policy['send_start_date']:
        raise ValueError('date precedes authorized no-backfill cutover')


def publish_local_assets(stage_dir, token, *, asset_root, env_file=None):
    stage = transport._validate_stage(stage_dir, token)
    root = Path(asset_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('explicit existing local notification asset directory required')
    target = root/token
    if target.exists():
        raise ValueError('refuse to overwrite notification asset token')
    temp = Path(tempfile.mkdtemp(prefix='.notify-', dir=root))
    try:
        for channel in stage.iterdir():
            folder = temp/channel.name
            folder.mkdir(mode=0o755)
            for name in ('people.png', 'details.xlsx'):
                shutil.copyfile(channel/name, folder/name)
                (folder/name).chmod(0o644)
        temp.chmod(0o755)
        temp.rename(target)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return 'local notification assets published'


def deliver_bundle(*, bundle_path, current_release, output_dir, state_dir, env_file=None,
                   asset_root=None, dry_run=True, before_send=None):
    bundle, shared = verify_bundle(bundle_path, current_release, fresh=not dry_run)
    if not dry_run:
        require_send_date(state_dir, bundle['source']['as_of_date'])
        if asset_root is None:
            raise ValueError('server-local asset directory required')
    # Pin immutable manifest + current link before every HTTP attempt, without
    # rehashing the entire database eight times or creating a second calculation.
    def current_guard():
        if before_send is not None:
            before_send()
        current = Path(current_release).resolve(strict=True)
        manifest_name='release.json' if bundle.get('source_mode')=='sql_warehouse' else 'library_manifest.json'
        if current.name != bundle['source']['release_id'] or sha(current/'library'/manifest_name) != bundle['source_manifest_sha256']:
            raise ValueError('current release changed before notification send')
    def publisher(stage, token, env_file=None):
        current_guard()
        return publish_local_assets(stage, token, asset_root=asset_root)
    result = delivery.deliver(shared, Path(output_dir), bundle['source']['as_of_date'], Path(state_dir),
        env_file=env_file, dashboard_base_url=bundle['dashboard_url'], dry_run=dry_run,
        asset_publisher=publisher, before_send=current_guard, state_validator=require_imported_state)
    return {**result, 'release_id': bundle['source']['release_id'],
            'source_binding_sha256': bundle['source']['source_binding_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build')
    for name in ('library', 'batch-id', 'release-id', 'output-dir'):
        build.add_argument('--'+name, required=True)
    send = sub.add_parser('deliver')
    for name in ('bundle', 'current-release', 'output-dir', 'state-dir'):
        send.add_argument('--'+name, required=True)
    send.add_argument('--env-file'); send.add_argument('--asset-root')
    send.add_argument('--send', action='store_true', help='real send; default is offline preview')
    args = parser.parse_args()
    if args.command == 'build':
        result = build_bundle(library=args.library, batch_id=args.batch_id, release_id=args.release_id, output_dir=args.output_dir)
        result = {'status': 'built', 'source': result['source']}
    else:
        result = deliver_bundle(bundle_path=args.bundle, current_release=args.current_release,
            output_dir=args.output_dir, state_dir=args.state_dir,
            env_file=Path(args.env_file) if args.env_file else None,
            asset_root=args.asset_root, dry_run=not args.send)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
