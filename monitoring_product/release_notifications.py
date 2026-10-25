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

from data_platform.business_library import load_library, execute_library_query, read_library_result, verify_library_receipt
from dashboard_product.management.notifications import build_notifications, _performance_month
from monitoring_product import shared_delivery as delivery, delivery_transport as transport

SCHEMA = 'release_notifications.v1'
NATIVE_URL = 'https://dashboard.apinova.cn/superset/dashboard/shadow-bi-native/?standalone=1'
TABLES = ('periods', 'team_periods', 'facts', 'personnel_facts', 'target_roster_references')
ROOT = Path(__file__).resolve().parents[1]
RULE_FILES = ('dashboard_product/management/notifications.py', 'dashboard_product/management/aggregate.py',
              'dashboard_product/online_team/build.py', 'workspace_modeling/operations/personnel.py',
              'data_platform/business_library.py', 'data_platform/query/service.py', 'data_platform/query/evidence.py',
              'monitoring_product/release_notifications.py', 'monitoring_product/server_notify.py', 'monitoring_product/shared_delivery.py',
              'monitoring_product/shared_preview.py', 'monitoring_product/delivery_transport.py')


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


def identity(manifest, release_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', release_id):
        raise ValueError('invalid release identity')
    snapshots = manifest['snapshots']
    if set(snapshots) != {'training', 'abroad'} or not all(snapshots.values()):
        raise ValueError('notification release requires both Snapshots')
    binding = manifest['binding']
    semantics = {name: binding['inputs'][name] for name in ('Work/Pack/pack.json', 'Work/Bridge/reference.json')}
    if any(not re.fullmatch('[0-9a-f]{64}', value) for value in semantics.values()):
        raise ValueError('invalid Pack/Bridge binding')
    coverage = manifest['coverage']
    as_of = date.fromisoformat(manifest['as_of_date'])
    if coverage['data_through'] != (as_of - timedelta(days=1)).isoformat():
        raise ValueError('release cutoff must be as_of minus one day')
    if coverage['snapshot_id'] != snapshots['training'] or coverage['study_abroad_source']['snapshot_id'] != snapshots['abroad']:
        raise ValueError('release coverage Snapshot mismatch')
    if coverage['study_abroad_source']['through_date'] != coverage['data_through']:
        raise ValueError('joint source cutoff mismatch')
    return {'release_id': release_id, 'batch_id': manifest['batch_id'], 'snapshots': snapshots,
            'as_of_date': manifest['as_of_date'], 'data_through': coverage['data_through'],
            'database_sha256': manifest['database']['sha256'],
            'source_binding_sha256': hashlib.sha256(canonical(binding)).hexdigest(),
            'semantics': semantics}


def reconstruct(manifest, read_rows):
    """Reassemble lossless stored inputs; never recalculate business aggregates."""
    through = date.fromisoformat(manifest['coverage']['data_through'])
    months = sorted({through.strftime('%Y-%m'), _performance_month(through)})
    periods = read_rows('periods', 'WHERE id IN (?, ?)', [months[0], months[-1]])
    by_id = {p['id']: {**p, 'teams': []} for p in periods}
    if set(by_id) != set(months) or len(periods) != len(months):
        raise ValueError('release lacks required notification periods')
    seen = set()
    for row in read_rows('team_periods', 'WHERE period_id IN (?, ?)', [months[0], months[-1]]):
        key = (row['period_id'], row['team_id'])
        if key in seen or row['view']['id'] != row['team_id']:
            raise ValueError('duplicate or inconsistent stored team view')
        seen.add(key)
        by_id[row['period_id']]['teams'].append(row['view'])
    starts = [through.replace(day=1).isoformat()]
    for p in by_id.values():
        for team in p['teams']:
            if team.get('person_start'):
                starts.append(team['person_start'])
    start = min(starts)
    facts = read_rows('facts', 'WHERE event_date BETWEEN ? AND ?', [start, through.isoformat()])
    personal = read_rows('personnel_facts', 'WHERE event_date BETWEEN ? AND ?', [start, through.isoformat()])
    references = {}
    for row in read_rows('target_roster_references', '', []):
        if row['name'] in references and references[row['name']] != row['document']:
            raise ValueError('ambiguous bound reference')
        references[row['name']] = row['document']
    for required in ('people.json', 'offline_market_people.json'):
        if required not in references or not isinstance(references[required], dict):
            raise ValueError('release lacks bound roster input: ' + required)
    public = {'metadata': deepcopy(manifest['coverage']), 'periods': list(by_id.values())}
    return public, facts, personal, references['people.json'], references['offline_market_people.json']


def build_bundle(*, library, batch_id, release_id, output_dir):
    library, output_dir = Path(library).resolve(), Path(output_dir).resolve()
    if output_dir.exists():
        raise ValueError('refuse to overwrite notification bundle')
    manifest, _, manifest_ref = load_library(library, batch_id)
    source = identity(manifest, release_id)
    if not set(TABLES).issubset(manifest['tables']):
        raise ValueError('release notification input closure incomplete')
    rules = rule_binding()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.notification-build-', dir=output_dir.parent))
    receipts = []
    try:
        def rows(table, where, params):
            result = []
            for offset in range(0, manifest['tables'][table]['rows'], 200):
                response = execute_library_query(library=library, batch_id=batch_id,
                    sql=f'SELECT row_json FROM queries."{table}" {where} ORDER BY rowid LIMIT 200 OFFSET {offset}',
                    parameters=params, run_id=f'run_notify_{table}_{offset:06}', output_root=stage/'queries',
                    max_rows=200, max_result_bytes=32_000_000)
                data = read_library_result(response, output_root=stage/'queries')
                receipts.append({'path': str((Path('queries')/response['run_id']/response['receipt']['path'])),
                                 'sha256': response['receipt']['sha256']})
                result.extend(json.loads(row[0]) for row in data['rows'])
                if len(data['rows']) < 200:
                    break
            return result
        public, facts, personal, people, abroad = reconstruct(manifest, rows)
        payload = build_notifications(public, facts, people, abroad, person_facts=personal)
        metadata = {**public['metadata'], 'run_id': batch_id, 'as_of_date': source['as_of_date'],
                    'release_id': release_id, 'preview_only': True}
        payload['metadata'] = metadata
        shared = {'metadata': metadata, 'notifications_ref': {'path': 'notifications.json',
                  'sha256': hashlib.sha256(canonical(payload)).hexdigest()}}
        delivery._validate_contract(shared, payload, source['as_of_date'], sending=False)
        if rule_binding() != rules or sha(library/'library_manifest.json') != manifest_ref['sha256']:
            raise ValueError('release or notification rules changed during build')
        bundle = {'schema_version': SCHEMA, 'source': source, 'source_manifest_sha256': manifest_ref['sha256'],
                  'notification_rules': rules, 'notification_source_policy': 'team=facts;personal=personnel_facts',
                  'shared_result': {'path': 'shared_result.json', 'sha256': hashlib.sha256(canonical(shared)).hexdigest()},
                  'notifications': shared['notifications_ref'], 'query_receipts': receipts,
                  'dashboard_url': NATIVE_URL, 'team_deep_links': 'not configured; unified native dashboard'}
        for name, value in [('notifications.json', payload), ('shared_result.json', shared), ('bundle.json', bundle)]:
            (stage/name).write_bytes(canonical(value))
        stage.rename(output_dir)
        return bundle
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _bound_file(root, reference):
    relative = Path(reference['path'])
    raw = root/relative
    p = raw.resolve()
    if relative.is_absolute() or '..' in relative.parts or raw.is_symlink() or not p.is_relative_to(root) or not p.is_file() or sha(p) != reference['sha256']:
        raise ValueError('notification artifact digest/path mismatch')
    return p


def verify_bundle(bundle_path, current_release, *, fresh=False):
    bundle_path = Path(bundle_path).resolve()
    root = bundle_path.parent
    bundle = json.loads(bundle_path.read_bytes())
    if bundle.get('schema_version') != SCHEMA:
        raise ValueError('unsupported notification bundle')
    current = Path(current_release).resolve(strict=True)
    manifest, _, ref = load_library(current/'library', bundle['source']['batch_id'])
    if identity(manifest, current.name) != bundle['source'] or ref['sha256'] != bundle['source_manifest_sha256']:
        raise ValueError('notification bundle is not the current formal release')
    if rule_binding() != bundle['notification_rules']:
        raise ValueError('notification implementation digest mismatch')
    shared_path = _bound_file(root, bundle['shared_result'])
    _bound_file(root, bundle['notifications'])
    shared, payload = delivery.shared_preview._read_shared_notifications(shared_path)
    expected_metadata = {**manifest['coverage'], 'run_id': manifest['batch_id'],
                         'as_of_date': manifest['as_of_date'], 'release_id': current.name, 'preview_only': True}
    if shared['metadata'] != expected_metadata:
        raise ValueError('notification release/source metadata mismatch')
    delivery._validate_contract(shared, payload, manifest['as_of_date'], sending=fresh)
    for reference in bundle['query_receipts']:
        receipt = _bound_file(root, reference)
        doc, _ = verify_library_receipt(receipt)
        if doc['batch_id'] != bundle['source']['batch_id'] or doc['snapshots'] != bundle['source']['snapshots'] or doc['binding_sha256'] != bundle['source']['source_binding_sha256']:
            raise ValueError('notification query provenance mismatch')
    return bundle, shared_path


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
        if current.name != bundle['source']['release_id'] or sha(current/'library/library_manifest.json') != bundle['source_manifest_sha256']:
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
