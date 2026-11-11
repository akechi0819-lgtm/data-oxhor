"""读取同批 SQL 通知封口结果，沿用原投递器与去重状态。"""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from dashboard_product.shadow_bi.p4.sql_release import load_release
from data_platform.query.evidence import resolve_file


def source(library):
    release, candidate, _ = load_release(library)
    return release, candidate


def identity(release, release_id):
    from monitoring_product import release_notifications as n
    coverage, snapshots = release['coverage'], release['snapshots']
    if (coverage['snapshot_id'] != snapshots['training']
            or coverage['study_abroad_source']['snapshot_id'] != snapshots['abroad']
            or coverage['study_abroad_source']['through_date'] != coverage['data_through']
            or coverage['data_through'] != (date.fromisoformat(release['as_of_date'])-timedelta(days=1)).isoformat()):
        raise ValueError('SQL通知双来源或截止日期不一致')
    # 同一语义和双 Snapshot 继续进入原通知去重／来源合同。
    return {'release_id': release_id, 'batch_id': release['batch_id'],
            'snapshots': release['snapshots'], 'as_of_date': release['as_of_date'],
            'data_through': release['coverage']['data_through'],
            'database_sha256': release['database_sha256'],
            'source_binding_sha256': hashlib.sha256(n.canonical(release['binding'])).hexdigest(),
            'semantics': release['semantics']}


def build_bundle(*, library, batch_id, release_id, output_dir):
    from monitoring_product import release_notifications as n
    library, output_dir = Path(library).resolve(), Path(output_dir).resolve()
    release, candidate = source(library)
    if batch_id != candidate['batch_id'] or output_dir.exists():
        raise ValueError('通知批次不匹配或输出已存在')
    preview = resolve_file(library, candidate['notification_preview'])
    payload = json.loads(preview.read_bytes())
    if payload['data_through'] != candidate['through_date'] or len(payload['messages']) != 8:
        raise ValueError('同批SQL通知结果不完整')
    metadata = {**release['coverage'], 'run_id': batch_id, 'as_of_date': release['as_of_date'],
                'release_id': release_id, 'preview_only': True}
    payload['metadata'] = metadata
    shared = {'metadata': metadata, 'notifications_ref': {'path': 'notifications.json',
              'sha256': hashlib.sha256(n.canonical(payload)).hexdigest()}}
    n.delivery._validate_contract(shared, payload, release['as_of_date'], sending=False)
    bundle = {'schema_version': n.SCHEMA, 'source_mode': 'sql_warehouse',
              'source': identity(release, release_id),
              'source_manifest_sha256': n.sha(library/'release.json'),
              'notification_rules': n.rule_binding(),
              'notification_source_policy': 'team=facts;personal=personnel_facts',
              'shared_result': {'path': 'shared_result.json', 'sha256': hashlib.sha256(n.canonical(shared)).hexdigest()},
              'notifications': shared['notifications_ref'], 'query_receipts': [],
              'candidate_preview': candidate['notification_preview'],
              'dashboard_url': n.NATIVE_URL,
              'team_deep_links': 'not configured; unified native dashboard'}
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.sql-notification-', dir=output_dir.parent))
    try:
        for name, value in [('notifications.json', payload), ('shared_result.json', shared), ('bundle.json', bundle)]:
            (stage/name).write_bytes(n.canonical(value))
        stage.rename(output_dir)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return bundle


def verify_bundle(bundle_path, current_release, *, fresh=False):
    from monitoring_product import release_notifications as n
    path = Path(bundle_path).resolve()
    bundle = json.loads(path.read_bytes())
    current = Path(current_release).resolve(strict=True)
    release, candidate = source(current/'library')
    if (identity(release, current.name) != bundle['source']
            or n.sha(current/'library/release.json') != bundle['source_manifest_sha256']
            or n.rule_binding() != bundle['notification_rules']
            or candidate['notification_preview'] != bundle['candidate_preview']):
        raise ValueError('SQL通知来源或规则已变化')
    preview = json.loads(resolve_file(current/'library', candidate['notification_preview']).read_bytes())
    shared_path = n._bound_file(path.parent, bundle['shared_result'])
    n._bound_file(path.parent, bundle['notifications'])
    shared, payload = n.delivery.shared_preview._read_shared_notifications(shared_path)
    expected_metadata = {**release['coverage'], 'run_id': release['batch_id'],
                         'as_of_date': release['as_of_date'], 'release_id': current.name, 'preview_only': True}
    if shared['metadata'] != expected_metadata or payload['metadata'] != expected_metadata:
        raise ValueError('SQL通知日期或批次不匹配')
    actual = deepcopy(payload)
    actual.pop('metadata')
    if actual != preview:
        raise ValueError('通知内容与SQL封口结果不同')
    n.delivery._validate_contract(shared, payload, release['as_of_date'], sending=fresh)
    return bundle, shared_path
