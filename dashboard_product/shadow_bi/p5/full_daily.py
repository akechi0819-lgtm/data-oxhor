"""Guard a full-daily publication from an explicit current-day capture bundle.

The host supplies verified native exports; no automated advertising downloader is
included. Missing capture is blocked. No messages are sent or schedules enabled.
Expected source scope is configured independently of capture receipts.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import fcntl
import hashlib
import json
import os
import shutil
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo('Asia/Shanghai')
ROOT = Path(__file__).resolve().parents[3]
KNOWN_GAP = 'tencent_ads_training'


class DailyBlocked(ValueError):
    """Safe, fixed diagnostic codes only; dependency exceptions may contain secrets."""


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


@contextmanager
def production_lock(workspace):
    """Same lock inode as legacy daily, taken before collecting any source."""
    path = Path(workspace) / 'Output/ShadowDaily/.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as held:
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DailyBlocked('production_busy') from None
        yield held


def evidence_file(spec, capture_dir):
    """Only this attempt's captured evidence can prove a successful new capture."""
    if not isinstance(spec, dict) or set(spec) != {'path', 'sha256'}:
        raise DailyBlocked('evidence_missing')
    path = Path(spec['path']).resolve(strict=True)
    if not path.is_relative_to(Path(capture_dir).resolve()) or not path.is_file():
        raise DailyBlocked('evidence_outside_attempt')
    if digest(path) != spec['sha256']:
        raise DailyBlocked('evidence_digest_mismatch')
    return path


def validate_capture(captured, expected, day, capture_dir, loader=None):
    """Validate actual parsed data as well as independently configured scope.

    Each expected source declares accounts and manifest_source_ids. The latter
    are parser source IDs (prefixes also match xhs/SEM derived account leaves).
    A zero-account receipt remains evidence, never a fabricated data row.
    SEM requires an actual source completion statement beyond prefilled cells.
    """
    if loader is None:
        from dashboard_product.management.advertising_sources import load_sources
        loader = load_sources
    through = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    sources = captured.get('sources')
    if not isinstance(sources, list):
        raise DailyBlocked('source_receipts_missing')
    by_id = {s.get('source_id'): s for s in sources if isinstance(s, dict)}
    if len(by_id) != len(sources) or set(by_id) != set(expected):
        raise DailyBlocked('source_scope_mismatch')
    candidate = Path(captured.get('manifest_path', '')).resolve(strict=True)
    if not candidate.is_relative_to(Path(capture_dir).resolve()):
        raise DailyBlocked('manifest_outside_attempt')
    manifest = json.loads(candidate.read_text())
    parsed = loader(candidate)
    files = {str(candidate): digest(candidate)}
    manifest_files = {}
    for entry in manifest['sources']:
        path = Path(entry['path'])
        path = (path if path.is_absolute() else candidate.parent / path).resolve(strict=True)
        actual = digest(path)
        if entry.get('sha256') != actual:
            raise DailyBlocked('manifest_digest_missing_or_wrong')
        files[str(path)] = actual
        manifest_files[entry['source_id']] = str(path)
    for source_id, config in expected.items():
        item = by_id[source_id]
        try:
            captured_time = datetime.fromisoformat(item['captured_at'])
            if captured_time.tzinfo is None:
                raise ValueError('timezone required')
            captured_day = captured_time.astimezone(SHANGHAI).date().isoformat()
        except (KeyError, TypeError, ValueError):
            raise DailyBlocked('capture_time_missing:' + source_id) from None
        if captured_day != day:
            raise DailyBlocked('capture_not_today:' + source_id)
        if item.get('status') != 'success' or item.get('through_date') != through:
            raise DailyBlocked('source_not_complete:' + source_id)
        accounts = item.get('account_ids', [])
        if len(accounts) != len(set(accounts)) or set(accounts) != set(config['accounts']):
            raise DailyBlocked('account_scope_mismatch:' + source_id)
        if item.get('start_date') != config['start_date']:
            raise DailyBlocked('source_window_mismatch:' + source_id)
        proof = evidence_file(item.get('evidence'), capture_dir)
        files[str(proof)] = digest(proof)
        # This is a verified native source statement captured by the collector,
        # not inferred from download time, nonzero cells or the user's usual hour.
        completion = item.get('completion', {})
        if completion.get('complete') is not True or completion.get('through_date') != through:
            raise DailyBlocked('native_completion_missing:' + source_id)
        if source_id == 'sem' and completion.get('basis') not in {'source_updated_through', 'native_completed_date'}:
            raise DailyBlocked('sem_native_completion_missing')
        source_files = set()
        if not item.get('files'):
            raise DailyBlocked('captured_file_missing:' + source_id)
        for spec in item['files']:
            path = evidence_file(spec, capture_dir)
            files[str(path)] = digest(path)
            source_files.add(str(path))
        expected_ids = config['manifest_source_ids']
        if not expected_ids or any(key not in manifest_files for key in expected_ids):
            raise DailyBlocked('parsed_source_missing:' + source_id)
        if not {manifest_files[key] for key in expected_ids}.issubset(source_files):
            raise DailyBlocked('manifest_not_from_capture:' + source_id)
        rows = [row for row in parsed['rows'] if any(
            row['source_id'] == key or row['source_id'].startswith(key + ':') for key in expected_ids)]
        if not rows:
            raise DailyBlocked('parsed_rows_missing:' + source_id)
        if any(row['start_date'] < config['start_date'] or row['end_date'] > through
               or row.get('amount') is None for row in rows):
            raise DailyBlocked('parsed_window_or_amount_invalid:' + source_id)
        # Dense native account / SEM reports must contain each expected day.
        # Sparse project rows rely on the verified native export-window evidence.
        if config.get('dense_daily'):
            keys = config.get('parsed_source_ids')
            if not keys or len(keys) != len(set(keys)):
                raise DailyBlocked('expected_parsed_scope_missing:' + source_id)
            if set(keys) != {row['source_id'] for row in rows}:
                raise DailyBlocked('parsed_scope_mismatch:' + source_id)
            for key in keys:
                days = {r['start_date'] for r in rows if r['source_id'] == key and r['start_date'] == r['end_date']}
                count = (date.fromisoformat(through) - date.fromisoformat(config['start_date'])).days + 1
                if len(days) != count:
                    raise DailyBlocked('parsed_day_gap:' + source_id)
        parsed_accounts = {str(row['account_id']) for row in rows if row.get('account_id') is not None}
        if parsed_accounts and parsed_accounts != set(config['accounts']):
            raise DailyBlocked('parsed_account_scope_mismatch:' + source_id)
    # Resolve all paths before atomically installing the candidate in its normal
    # location. Historical sources may live outside this capture directory.
    for entry in manifest['sources']:
        entry['path'] = manifest_files[entry['source_id']]
    return manifest, files, parsed


def code_files(root):
    # Explicit changed execution path. Existing business-library binding separately
    # validates its complete rules/input closure; do not crawl other products.
    names = [
        'shadow_bi/p5/full_daily.py', 'shadow_bi/p5/daily.py',
        'shadow_bi/library.py', 'shadow_bi/acquisition.py',
        'shadow_bi/p3/build_projection.py', 'shadow_bi/p3/catalog.py',
        'management/calculation.py', 'management/advertising_costs.py',
        'management/advertising_sources.py', 'management/sem_sources.py',
        'management/xhs_sources.py', 'management/platforms.py',
        'management/sql/advertising_rollup.sql',
    ]
    files = [Path(root) / 'dashboard_product' / name for name in names]
    files += [Path(root) / 'data_acquisition/jobs/daily_warehouses.py',
              Path(root) / 'data_acquisition/jobs/rebuild_bi_warehouse.py',
              Path(root) / 'data_acquisition/jobs/update_tencent_study_abroad.py']
    return [path for path in files if path.is_file()]


def freeze_inputs(workspace, manifest, capture_files, pair, root):
    files = dict(capture_files)
    for path in code_files(root):
        files[str(path.resolve())] = digest(path)
    normal = Path(workspace) / 'Input/AdvertisingCosts/sources.json'
    files[str(normal.resolve())] = digest(normal)
    config = Path(workspace) / '.private/full-daily-sources.json'
    files[str(config.resolve())] = digest(config)
    # The joint receipt validates explicit Snapshot identity and source hashes;
    # no customer database connection or unrestricted query is introduced here.
    business = {key: value.get('value_sha256') for key, value in pair['sources'].items()}
    if not business or any(not value for value in business.values()):
        raise DailyBlocked('business_source_digest_missing')
    semantic_manifest = json.loads(json.dumps(manifest))
    for item in semantic_manifest['sources']:
        item.pop('path', None)
    # Evidence paths/capture timestamps can change without changing data. Include
    # input bytes, mappings, rule bytes and actual business export hashes instead.
    fingerprints = {str(p.relative_to(root)): files[str(p.resolve())] for p in code_files(root)}
    fingerprint = canonical({'manifest': semantic_manifest, 'business': business,
                             'rules': fingerprints, 'expected_sources': digest(config)})
    return {'files': files, 'pair': pair, 'fingerprint': fingerprint}


def verify_frozen(frozen, workspace, day, assert_ready):
    if any(not Path(path).is_file() or digest(path) != value for path, value in frozen['files'].items()):
        raise DailyBlocked('frozen_inputs_changed')
    if assert_ready(Path(workspace), day) != frozen['pair']:
        raise DailyBlocked('business_pair_changed')


def capture_business(workspace, day, run_id):
    import certifi
    from data_acquisition.jobs.daily_warehouses import refresh_daily, assert_daily_ready
    config = json.loads((workspace / '.private/tencent-source.json').read_text())
    suffix = run_id.removeprefix('run_shadow_daily_')
    result = refresh_daily(workspace=workspace, as_of_date=day, run_id=run_id,
        bi_snapshot_id='snapshot_bi_operations_' + suffix,
        study_snapshot_id='snapshot_study_abroad_' + suffix,
        doc_id=config['doc_id'], page_url=config['page_url'],
        cookie_file=workspace / '.private/tencent-cookies.json', ca_file=Path(certifi.where()))
    if result['status'] != 'passed':
        raise DailyBlocked('business_capture_failed')
    return assert_daily_ready(workspace, day)


def restore_manifest(path, original, installed_hash):
    # Never overwrite another task's or a human's intervening change.
    if not path.exists() or digest(path) != installed_hash:
        return False
    if original is None:
        path.unlink()
    else:
        temporary = path.with_name(path.name + '.restore')
        temporary.write_bytes(original)
        temporary.replace(path)
    return True


def prepare_candidate(workspace, day, run_id, pair, folder, guard):
    """Build and seal locally through the publication boundary; no SSH is used."""
    from .daily import command, package_tables
    from data_platform.business_library import load_library
    guard()
    base_batch = run_id + '_business'
    source = workspace / 'Output/ShadowBI' / base_batch / 'library'
    command([sys.executable, '-m', 'dashboard_product.shadow_bi.library', 'build',
             '--workspace', str(workspace), '--snapshot-id', pair['sources']['bi']['snapshot_id'],
             '--study-abroad-snapshot-id', pair['sources']['study_abroad']['snapshot_id'],
             '--run-id', base_batch, '--as-of-date', day], folder / 'build.log')
    presentation = folder / 'presentation'
    env = dict(os.environ, SHADOW_BI_SOURCE_LIBRARY=str(source),
               SHADOW_BI_SOURCE_BATCH=base_batch, SHADOW_BI_LIBRARY=str(presentation),
               SHADOW_BI_BATCH=run_id, SHADOW_BI_AUDIT=str(folder))
    command([sys.executable, '-m', 'dashboard_product.shadow_bi.p3.build_projection'],
            folder / 'projection.log', env=env)
    load_library(source, base_batch)
    manifest, _, _ = load_library(presentation, run_id)
    transfer = folder / 'transfer'
    package_tables(source, presentation, transfer)
    guard()
    result = {'status': 'prepared', 'candidate': str(presentation),
              'batch_id': manifest['batch_id'], 'coverage': manifest['coverage'],
              'table_count': len(manifest['tables']),
              'sealed_manifest_sha256': digest(transfer / 'library_manifest.json'),
              'published': False, 'publish_outcome': 'not_attempted'}
    atomic_json(folder / 'prepared-candidate.json', result)
    return result


def run(workspace, day=None, *, collect=None, business_capture=None, publish=None,
        assert_ready=None, loader=None, root=ROOT, now=None, prepare=False):
    workspace = Path(workspace).resolve()
    now = now or datetime.now(SHANGHAI)
    day = day or now.astimezone(SHANGHAI).date().isoformat()
    if date.fromisoformat(day) != now.astimezone(SHANGHAI).date():
        raise DailyBlocked('not_shanghai_today')
    if business_capture is None:
        business_capture = capture_business
    if publish is None and not prepare:
        from .daily import run as publish
    if assert_ready is None:
        from data_acquisition.jobs.daily_warehouses import assert_daily_ready as assert_ready
    with production_lock(workspace) as held:
        state = workspace / 'Output/ShadowDaily'
        run_id = 'run_shadow_daily_' + day.replace('-', '') + '_' + now.astimezone(SHANGHAI).strftime('%H%M%S%f')
        folder = state / 'Full' / run_id
        folder.mkdir(parents=True, exist_ok=False)
        report = {'schema_version': 'shadow_full_daily.v1', 'day': day, 'run_id': run_id,
                  'status': 'running', 'mode': 'prepare' if prepare else 'publish',
                  'known_gaps': [KNOWN_GAP]}
        atomic_json(folder / 'result.json', report)
        installed, old, installed_hash = False, None, None
        publish_attempted = False
        normal = workspace / 'Input/AdvertisingCosts/sources.json'
        try:
            if collect is None:
                raise DailyBlocked('advertising_capture_receipt_required')
            config_path = workspace / '.private/full-daily-sources.json'
            config = json.loads(config_path.read_text())
            expected = config.get('expected_sources')
            if not isinstance(expected, dict) or not expected or KNOWN_GAP in expected:
                raise DailyBlocked('expected_sources_invalid')
            capture_dir = folder / 'capture'
            capture_dir.mkdir()
            captured = collect(workspace, day, run_id, capture_dir)
            manifest, files, parsed = validate_capture(captured, expected, day, capture_dir, loader)
            pair = business_capture(workspace, day, run_id)
            if pair != assert_ready(workspace, day):
                raise DailyBlocked('business_pair_changed')
            old = normal.read_bytes() if normal.exists() else None
            atomic_json(normal, manifest)
            installed = True
            installed_hash = digest(normal)
            frozen = freeze_inputs(workspace, manifest, files, pair, Path(root))
            atomic_json(folder / 'frozen-inputs.json', frozen)
            last_path = state / 'Full' / (day + '.json')
            previous = json.loads(last_path.read_text()) if last_path.exists() else None
            guard = lambda: verify_frozen(frozen, workspace, day, assert_ready)
            guard()
            if prepare:
                result = prepare_candidate(workspace, day, run_id, pair, folder, guard)
                if result.get('status') != 'prepared' or result.get('published') is not False:
                    raise DailyBlocked('candidate_not_confirmed')
                report.update(result, fingerprint=frozen['fingerprint'])
            elif previous and previous.get('status') == 'published' and previous.get('fingerprint') == frozen['fingerprint']:
                # Legacy recheck verifies actual server current against its day
                # receipt. It must exist, otherwise do not let a recheck collect.
                legacy_day = state / (day + '.json')
                if not legacy_day.exists() or json.loads(legacy_day.read_text()).get('status') != 'published':
                    raise DailyBlocked('published_receipt_missing')
                result = publish(workspace, day, held_lock=held)
                if result.get('release') != previous.get('release'):
                    raise DailyBlocked('published_release_changed')
                report.update(status='published', release=result['release'], reused=True,
                              fingerprint=frozen['fingerprint'])
            else:
                publish_attempted = True
                result = publish(workspace, day, held_lock=held, prepared_sources=pair,
                                 run_id_override=run_id, before_publish=guard)
                if result.get('status') != 'published':
                    raise DailyBlocked('publish_not_confirmed')
                report.update(status='published', release=result['release'], reused=False,
                              fingerprint=frozen['fingerprint'])
            report['through_date'] = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
            report['source_ids'] = sorted(expected)
            report['expense_rows'] = len(parsed['rows'])
            if not prepare:
                atomic_json(last_path, report)
            return report
        except Exception as error:
            report.update(status='blocked' if isinstance(error, DailyBlocked) else 'failed',
                          reason=str(error) if isinstance(error, DailyBlocked) else type(error).__name__,
                          publish_outcome='uncertain' if publish_attempted else 'not_attempted')
            raise
        finally:
            if installed and (prepare or report['status'] in {'failed', 'blocked'}):
                report['input_manifest_restored'] = restore_manifest(normal, old, installed_hash)
            atomic_json(folder / 'result.json', report)
            atomic_json(state / 'Full/current.json', report)


def receipt_collector(receipt_path):
    """Stage an explicit host-captured bundle; does not download any platform."""
    receipt_path = Path(receipt_path).resolve(strict=True)

    def collect(workspace, day, run_id, capture_dir):
        captured = json.loads(receipt_path.read_text())
        candidate = Path(captured['manifest_path'])
        candidate = (candidate if candidate.is_absolute() else receipt_path.parent / candidate).resolve(strict=True)
        manifest = json.loads(candidate.read_text())
        replacements = {}
        for source in captured['sources']:
            for spec in [*source['files'], source['evidence']]:
                original = Path(spec['path'])
                original = (original if original.is_absolute() else receipt_path.parent / original).resolve(strict=True)
                if digest(original) != spec['sha256']:
                    raise DailyBlocked('bundle_digest_mismatch')
                destination = capture_dir / (spec['sha256'] + original.suffix)
                if not destination.exists():
                    shutil.copyfile(original, destination)
                replacements[str(original)] = str(destination)
                spec['path'] = str(destination)
        for entry in manifest['sources']:
            original = Path(entry['path'])
            original = (original if original.is_absolute() else candidate.parent / original).resolve(strict=True)
            entry['path'] = replacements.get(str(original), str(original))
        target = capture_dir / 'sources.json'
        atomic_json(target, manifest)
        captured['manifest_path'] = str(target)
        return captured

    return collect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--date', default=None)
    parser.add_argument('--prepare', action='store_true', help='Build and verify a local candidate only; never SSH or activate server current')
    parser.add_argument('--capture-receipt', type=Path, help='Explicit current-day host-captured advertising bundle; no browser downloader is implied')
    args = parser.parse_args()
    try:
        collector = receipt_collector(args.capture_receipt) if args.capture_receipt else None
        result = run(args.workspace, args.date, collect=collector, prepare=args.prepare)
        print(json.dumps({k: result[k] for k in ('status', 'day', 'release', 'candidate', 'known_gaps') if k in result}, ensure_ascii=False))
    except DailyBlocked as error:
        print(json.dumps({'status': 'blocked', 'reason': str(error)}, ensure_ascii=False))
        return 2
    except Exception as error:
        print(json.dumps({'status': 'failed', 'reason': type(error).__name__}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
