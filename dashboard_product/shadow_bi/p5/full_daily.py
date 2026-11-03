"""Guard a full-daily publication from an explicit current-day capture bundle.

The host supplies verified native exports; no automated advertising downloader is
included. Missing capture is blocked. No messages are sent or schedules enabled.
Expected source scope is configured independently of capture receipts.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
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


def business_batch_id(run_id):
    prefix = 'run_shadow_daily_'
    return ('run_sd_' + run_id[len(prefix):] + '_business'
            if run_id.startswith(prefix) else run_id + '_business')


def verified_empty_ocean_accounts(item, expected_accounts, day, through, proof, source_file_hashes):
    """Accept absent parsed rows only for accounts sealed as native-empty."""
    if item.get('source_id') != 'ocean':
        if 'native_empty_accounts' in item:
            raise DailyBlocked('native_empty_account_source_invalid')
        return set()
    declared = item.get('native_empty_accounts', [])
    if (not isinstance(declared, list)
            or any(not isinstance(account, str) for account in declared)
            or len(declared) != len(set(declared))):
        raise DailyBlocked('native_empty_account_declaration_invalid')
    try:
        evidence = json.loads(proof.read_text())
        results = evidence['accounts']
        if not isinstance(results, list):
            raise TypeError
        ids = [str(result['account_id']) for result in results]
    except Exception:
        raise DailyBlocked('native_empty_account_evidence_invalid') from None
    if (not isinstance(results, list) or len(ids) != len(set(ids))
            or set(ids) != set(item.get('account_ids', []))
            or not set(declared).issubset(set(expected_accounts))):
        raise DailyBlocked('native_empty_account_evidence_scope_mismatch')
    empty = set()
    for result in results:
        account = str(result['account_id'])
        try:
            captured_at = datetime.fromisoformat(result['captured_at'])
            selected_window = result['selected_window']
            native = result['native_validation']
            total = Decimal(str(result['total']))
            query_pages = result['query_pages']
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise DailyBlocked('native_empty_account_evidence_invalid') from None
        if (captured_at.tzinfo is None
                or captured_at.astimezone(SHANGHAI).date().isoformat() != day
                or selected_window != [item.get('start_date'), through]):
            raise DailyBlocked('native_empty_account_evidence_window_mismatch')
        if not isinstance(query_pages, list) or not query_pages:
            raise DailyBlocked('native_empty_account_evidence_file_missing')
        for spec in [result.get('file', {}), *query_pages]:
            if not isinstance(spec, dict) or spec.get('sha256') not in source_file_hashes:
                raise DailyBlocked('native_empty_account_evidence_file_missing')
        if result.get('rows') == 0:
            try:
                native_total = Decimal(str(native['total']))
            except (KeyError, TypeError, ValueError, InvalidOperation):
                raise DailyBlocked('native_empty_account_evidence_invalid') from None
            if (native.get('native_empty') is not True or native.get('rows') != 0
                    or total != 0 or native_total != 0 or not result.get('query_pages')):
                raise DailyBlocked('native_empty_account_not_proven')
            empty.add(account)
    if empty != set(declared):
        raise DailyBlocked('native_empty_account_declaration_mismatch')
    return empty


def validate_capture(captured, expected, day, capture_dir, loader=None):
    """Validate actual parsed data as well as independently configured scope.

    Each expected source declares accounts and manifest_source_ids. The latter
    are parser source IDs (prefixes also match xhs/SEM derived account leaves).
    A zero-account receipt remains evidence, never a fabricated data row.
    SEM keeps the native report's actual rows and missing values; it does not
    require a separate page-level completion marker.
    """
    if loader is None:
        from dashboard_product.management.candidate_sources import load_candidate_sources
        loader = load_candidate_sources
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
    from dashboard_product.management.candidate_sources import validate_candidate_authorities
    try:
        validate_candidate_authorities(manifest)
        parsed = loader(candidate)
    except ValueError as error:
        from dashboard_product.management.candidate_sources import CandidateSourceError
        if isinstance(error, CandidateSourceError):
            raise DailyBlocked(str(error)) from None
        raise
    files = {str(candidate): digest(candidate)}
    confirmation = manifest.get('business_scope_confirmation')
    if confirmation is not None:
        confirmation_specs = [confirmation.get('evidence')]
        sparse = confirmation.get('display_sparse_scope')
        if isinstance(sparse, dict):
            confirmation_specs.append(sparse.get('evidence'))
        for spec in confirmation_specs:
            if spec is None:
                continue
            proof = evidence_file(spec, capture_dir)
            files[str(proof)] = digest(proof)
    manifest_files = {}
    for entry in manifest['sources']:
        path = Path(entry['path'])
        path = (path if path.is_absolute() else candidate.parent / path).resolve(strict=True)
        actual = digest(path)
        if entry.get('sha256') != actual:
            raise DailyBlocked('manifest_digest_missing_or_wrong')
        files[str(path)] = actual
        manifest_files[entry['source_id']] = str(path)
        if entry.get('kind') == 'tencent_native_csv':
            bound = evidence_file(entry.get('capture_evidence'), capture_dir)
            files[str(bound)] = digest(bound)
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
        # Other sources require an observed native completion statement. SEM is
        # accepted as the latest whole workbook and exposes its row/amount gaps
        # through parsed source metadata and SQL coverage instead.
        completion = item.get('completion', {})
        if source_id != 'sem' and (completion.get('complete') is not True or completion.get('through_date') != through):
            raise DailyBlocked('native_completion_missing:' + source_id)
        source_files = set()
        source_file_hashes = set()
        if not item.get('files'):
            raise DailyBlocked('captured_file_missing:' + source_id)
        for spec in item['files']:
            path = evidence_file(spec, capture_dir)
            files[str(path)] = digest(path)
            source_files.add(str(path))
            source_file_hashes.add(spec['sha256'])
        empty_accounts = verified_empty_ocean_accounts(
            item, config['accounts'], day, through, proof, source_file_hashes)
        expected_ids = config['manifest_source_ids']
        if not expected_ids or any(key not in manifest_files for key in expected_ids):
            raise DailyBlocked('parsed_source_missing:' + source_id)
        if not {manifest_files[key] for key in expected_ids}.issubset(source_files):
            raise DailyBlocked('manifest_not_from_capture:' + source_id)
        rows = [row for row in parsed['rows'] if any(
            row['source_id'] == key or row['source_id'].startswith(key + ':') for key in expected_ids)]
        sem_sources = [source for source in parsed.get('sources', []) if any(
            source.get('source_id') == key or source.get('source_id', '').startswith(key + ':')
            for key in expected_ids)] if source_id == 'sem' else []
        if not rows and (source_id != 'sem' or not sem_sources):
            raise DailyBlocked('parsed_rows_missing:' + source_id)
        if any(row['start_date'] < config['start_date'] or row['end_date'] > through
               or (row.get('amount') is None and source_id != 'sem') for row in rows):
            raise DailyBlocked('parsed_window_or_amount_invalid:' + source_id)
        # Dense native account / SEM reports must contain each expected day.
        # Sparse project rows rely on the verified native export-window evidence.
        if config.get('dense_daily'):
            keys = config.get('parsed_source_ids')
            if not keys or len(keys) != len(set(keys)):
                raise DailyBlocked('expected_parsed_scope_missing:' + source_id)
            if source_id == 'sem':
                if set(keys) != {source.get('source_id') for source in sem_sources}:
                    raise DailyBlocked('parsed_scope_mismatch:' + source_id)
            else:
                if set(keys) != {row['source_id'] for row in rows}:
                    raise DailyBlocked('parsed_scope_mismatch:' + source_id)
                for key in keys:
                    days = {r['start_date'] for r in rows if r['source_id'] == key and r['start_date'] == r['end_date']}
                    count = (date.fromisoformat(through) - date.fromisoformat(config['start_date'])).days + 1
                    if len(days) != count:
                        raise DailyBlocked('parsed_day_gap:' + source_id)
        if source_id == 'ocean':
            # The native Ocean projection does not repeat account_id on every
            # row. Its seven-account capture proof validates the account set,
            # while these source IDs validate all nonempty mapped projections.
            if {row['source_id'] for row in rows} != set(expected_ids):
                raise DailyBlocked('parsed_scope_mismatch:' + source_id)
        else:
            parsed_accounts = ({source.get('source_sheet') for source in sem_sources}
                               if source_id == 'sem' else
                               {str(row['account_id']) for row in rows if row.get('account_id') is not None})
            if (parsed_accounts & empty_accounts
                    or parsed_accounts | empty_accounts != set(config['accounts'])):
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
        'management/candidate_sources.py', 'management/tencent_sources.py',
        'management/advertising_sources.py', 'management/sem_sources.py',
        'management/xhs_sources.py', 'management/platforms.py',
        'management/sql/advertising_rollup.sql',
    ]
    files = [Path(root) / 'dashboard_product' / name for name in names]
    files += [Path(root) / 'data_acquisition/jobs/daily_warehouses.py',
              Path(root) / 'data_acquisition/jobs/prepare_full_daily.py',
              Path(root) / 'data_acquisition/jobs/rebuild_bi_warehouse.py',
              Path(root) / 'data_acquisition/jobs/update_tencent_study_abroad.py']
    files += list((Path(root)/'data_acquisition/connectors/advertising').glob('*.py'))
    files += list((Path(root)/'data_acquisition/connectors/tencent_docs').glob('*.py'))
    files += [Path(root) / 'data_acquisition/jobs/sync_content_work_orders.py']
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
    from data_acquisition.jobs.daily_warehouses import refresh_daily, assert_daily_ready
    suffix = run_id.removeprefix('run_shadow_daily_')
    result = refresh_daily(workspace=workspace, as_of_date=day, run_id=run_id,
        bi_snapshot_id='snapshot_bi_operations_' + suffix,
        study_snapshot_id='snapshot_study_abroad_' + suffix)
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


def prepare_candidate(workspace, day, run_id, pair, folder, guard, *, advertising_manifest=None):
    """Build and seal locally through the publication boundary; no SSH is used."""
    from .daily import command, package_tables
    from data_platform.business_library import load_library
    guard()
    base_batch = business_batch_id(run_id)
    source = workspace / 'Output/ShadowBI' / base_batch / 'library'
    build_args = [sys.executable, '-m', 'dashboard_product.shadow_bi.library', 'build',
                  '--workspace', str(workspace), '--snapshot-id', pair['sources']['bi']['snapshot_id'],
                  '--study-abroad-snapshot-id', pair['sources']['study_abroad']['snapshot_id'],
                  '--run-id', base_batch, '--as-of-date', day]
    if advertising_manifest is not None:
        build_args += ['--advertising-manifest', str(advertising_manifest)]
    command(build_args, folder / 'build.log')
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
    if publish is None and not prepare:
        from .daily import run as publish
    if assert_ready is None:
        from data_acquisition.jobs.daily_warehouses import assert_daily_ready as assert_ready
    if business_capture is None:
        # Preview must not advance either warehouse's current pointer. Reuse
        # only the same-day joint source receipt, under the same freshness gate.
        business_capture = (lambda ws, selected_day, _run_id: assert_ready(ws, selected_day)) if prepare else capture_business
    with production_lock(workspace) as held:
        state = workspace / 'Output/ShadowDaily'
        run_id = 'run_shadow_daily_' + day.replace('-', '') + '_' + now.astimezone(SHANGHAI).strftime('%H%M%S')
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
            candidate_manifest = None
            if prepare:
                candidate_manifest = folder / 'candidate-sources.json'
                atomic_json(candidate_manifest, manifest)
                files[str(candidate_manifest.resolve())] = digest(candidate_manifest)
            else:
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
                result = prepare_candidate(workspace, day, run_id, pair, folder, guard,
                                           advertising_manifest=candidate_manifest)
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
            if installed and report['status'] in {'failed', 'blocked'}:
                report['input_manifest_restored'] = restore_manifest(normal, old, installed_hash)
            atomic_json(folder / 'result.json', report)
            if not prepare:
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
        confirmation = manifest.get('business_scope_confirmation')
        if confirmation is not None:
            specs = [confirmation.get('evidence')]
            sparse = confirmation.get('display_sparse_scope')
            if isinstance(sparse, dict):
                specs.append(sparse.get('evidence'))
            for spec in specs:
                if spec is None:
                    continue
                original = Path(spec['path'])
                original = (original if original.is_absolute() else candidate.parent / original).resolve(strict=True)
                if digest(original) != spec['sha256']:
                    raise DailyBlocked('business_scope_confirmation_digest_mismatch')
                destination = capture_dir / (spec['sha256'] + original.suffix)
                if not destination.exists():
                    shutil.copyfile(original, destination)
                if digest(destination) != spec['sha256']:
                    raise DailyBlocked('business_scope_confirmation_copy_mismatch')
                replacements[str(original)] = str(destination)
                spec['path'] = str(destination)
        for entry in manifest['sources']:
            original = Path(entry['path'])
            original = (original if original.is_absolute() else candidate.parent / original).resolve(strict=True)
            entry['path'] = replacements.get(str(original), str(original))
            if entry.get('kind') == 'tencent_native_csv':
                proof = Path(entry['capture_evidence']['path']).resolve(strict=True)
                if str(proof) not in replacements:
                    raise DailyBlocked('tencent_capture_evidence_not_in_bundle')
                entry['capture_evidence']['path'] = replacements[str(proof)]
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
