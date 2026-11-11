import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

import pytest

from dashboard_product.shadow_bi.p5 import foundation_candidate as candidate


DAY = '2026-11-04'
BATCH = 'run_shadow_daily_20261104_online3'
RELEASE = 'daily-20261104-online-routing'
COMPANY = 'workspace_bi_operations'


def file_spec(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}


def bundle_manifest(payload, **extra):
    return {
        'schema_version': candidate.SCHEMA,
        'batch_id': BATCH,
        'release_id': RELEASE,
        'company_id': COMPANY,
        'as_of_date': DAY,
        'snapshots': {'bi': 'snapshot_bi_operations_20261104_103334',
                      'study_abroad': 'snapshot_study_abroad_20261104_103334'},
        'files': {name: file_spec(data) for name, data in payload.items()},
        **extra,
    }


def make_bundle(path, payload, manifest=None):
    manifest = manifest or bundle_manifest(payload)
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
    with tarfile.open(path, 'w:') as tar:
        item = tarfile.TarInfo('manifest.json')
        item.size = len(raw)
        item.mode = 0o440
        import io
        tar.addfile(item, io.BytesIO(raw))
        for name, data in payload.items():
            item = tarfile.TarInfo(name)
            item.size = len(data)
            item.mode = 0o440
            import io
            tar.addfile(item, io.BytesIO(data))
    path.chmod(0o600)
    return manifest


def test_validate_manifest_binds_the_same_day_pair_and_optional_candidate_fee_manifest():
    payload = {'workspace/Input/AdvertisingCosts/candidate-sources.json': b'{"sources":[]}'}
    manifest = bundle_manifest(payload, advertising_manifest='Input/AdvertisingCosts/candidate-sources.json')
    assert candidate.validate_manifest(manifest, batch_id=BATCH, release_id=RELEASE,
                                      as_of_date=DAY, company_id=COMPANY) == manifest

    invalid = {**manifest, 'snapshots': {'bi': 'one'}}
    with pytest.raises(ValueError, match='Snapshot pair'):
        candidate.validate_manifest(invalid, batch_id=BATCH, release_id=RELEASE,
                                    as_of_date=DAY, company_id=COMPANY)


@pytest.mark.parametrize('value', ['../escape', 'workspace/../escape', '/absolute', 'workspace\\escape'])
def test_safe_relative_rejects_escape_paths(value):
    with pytest.raises(ValueError):
        candidate._safe_relative(value)


def test_extract_bundle_hashes_and_extracts_only_declared_workspace_files(tmp_path, monkeypatch):
    payload = {'workspace/Work/workspace.json': b'{"company_id":"workspace_bi_operations"}'}
    archive = tmp_path / 'payload.tar'
    make_bundle(archive, payload)
    foundation = tmp_path / 'foundation'
    foundation.mkdir()
    manifest, archive_sha, manifest_sha = candidate.extract_bundle(
        archive, foundation, batch_id=BATCH, release_id=RELEASE, as_of_date=DAY,
        company_id=COMPANY, disk_root=tmp_path, max_free=0, owner_uid=os.geteuid())

    assert manifest['batch_id'] == BATCH
    assert archive_sha == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert manifest_sha == hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert (foundation / 'Work/workspace.json').read_bytes() == payload['workspace/Work/workspace.json']
    assert (foundation / 'Work/workspace.json').stat().st_mode & 0o777 == 0o600


def test_extract_bundle_rejects_changed_member(tmp_path):
    payload = {'workspace/Input/value.json': b'original'}
    manifest = bundle_manifest(payload)
    payload['workspace/Input/value.json'] = b'modified'
    archive = tmp_path / 'payload.tar'
    make_bundle(archive, payload, manifest)
    foundation = tmp_path / 'foundation'
    foundation.mkdir()

    with pytest.raises(ValueError, match='digest differs'):
        candidate.extract_bundle(archive, foundation, batch_id=BATCH, release_id=RELEASE,
                                 as_of_date=DAY, company_id=COMPANY,
                                 disk_root=tmp_path, max_free=0, owner_uid=os.geteuid())


def _write_queryable_library(foundation):
    import duckdb
    from data_platform.query.evidence import file_ref

    library = foundation / 'Output/ShadowBI' / BATCH / 'library'
    (library / 'tables').mkdir(parents=True)
    table_data = b'{"value":1}\n'
    table_path = library / 'tables/sample.jsonl'
    table_path.write_bytes(table_data)
    database = library / 'business.duckdb'
    with duckdb.connect(str(database)) as connection:
        connection.execute('CREATE SCHEMA queries')
        connection.execute('CREATE TABLE queries.batch(batch_id VARCHAR)')
        connection.execute('INSERT INTO queries.batch VALUES (?)', [BATCH])
        connection.execute('CREATE TABLE queries.sample(value BIGINT)')
        connection.execute('INSERT INTO queries.sample VALUES (1)')
    (library / 'library_manifest.json').write_text(json.dumps({
        'schema_version': 'business_query_library.v1', 'batch_id': BATCH,
        'as_of_date': DAY,
        'snapshots': {'training': 'snapshot_bi_operations_20261104_103334',
                      'abroad': 'snapshot_study_abroad_20261104_103334'},
        'coverage': {'data_through': '2026-11-03',
                     'study_abroad_source': {'through_date': '2026-11-03'}},
        'binding': {'inputs': {'workspace': 'a' * 64}, 'rules': {'rules.py': 'b' * 64}},
        'source_queries': [{'path': 'Output/source-query/receipt.json', 'sha256': 'c' * 64}],
        'tables': {'sample': {'rows': 1, 'logical_sha256': 'd' * 64,
                              'columns': {'value': 'BIGINT'},
                              'data': {'path': 'tables/sample.jsonl',
                                       'sha256': hashlib.sha256(table_data).hexdigest(),
                                       'size_bytes': len(table_data)}}},
        'database': file_ref(database, library, 'application/vnd.duckdb'),
    }))
    return library


def _prepare_fixture(tmp_path, builder, monkeypatch):
    owner_uid = os.geteuid()
    monkeypatch.setattr(candidate.os, 'geteuid', lambda: 0)
    base = tmp_path / 'shadow-bi'
    releases = base / 'releases'
    old = releases / 'daily-20261103-old'
    old.mkdir(parents=True)
    (base / 'current').symlink_to(old)
    input_root = base / 'foundation-inputs'
    source_folder = input_root / BATCH
    source_folder.mkdir(parents=True)
    payload = {'workspace/Work/workspace.json': json.dumps({'company_id': COMPANY}).encode()}
    make_bundle(source_folder / 'payload.tar', payload)
    monkeypatch.setattr(candidate, 'validate_workspace', lambda *args, **kwargs: {})
    return candidate.prepare(
        batch_id=BATCH, release_id=RELEASE, as_of_date=DAY, base=base,
        minimum_free_bytes=0, policy_context=lambda: (COMPANY, '2026-10-30'),
        builder=builder, mode_setter=lambda target: None, owner_uid=owner_uid)


def test_prepare_builds_final_candidate_without_switching_current(tmp_path, monkeypatch):
    def builder(foundation, manifest):
        _write_queryable_library(foundation)
        return {'gates': {'physical_counts_verified': True}}

    result = _prepare_fixture(tmp_path, builder, monkeypatch)
    base = tmp_path / 'shadow-bi'

    assert result['status'] == 'prepared'
    assert result['coverage']['data_through'] == '2026-11-03'
    assert result['library'] == str(base / 'releases' / RELEASE / 'library')
    assert (Path(result['library']) / 'business.duckdb').is_file()
    assert not (Path(result['library']) / 'tables').exists()
    assert (base / 'current').resolve().name == 'daily-20261103-old'
    assert not (base / 'foundation-inputs' / BATCH).exists()


def test_prepare_failure_removes_only_its_target_and_input_bundle(tmp_path, monkeypatch):
    def fail(foundation, manifest):
        raise ValueError('simulated candidate failure')

    with pytest.raises(ValueError, match='simulated candidate failure'):
        _prepare_fixture(tmp_path, fail, monkeypatch)
    base = tmp_path / 'shadow-bi'

    assert (base / 'current').resolve().name == 'daily-20261103-old'
    assert (base / 'releases' / 'daily-20261103-old').is_dir()
    assert not (base / 'releases' / RELEASE).exists()
    assert not (base / 'foundation-inputs' / BATCH).exists()


def test_compact_library_removes_verified_jsonl_but_keeps_queryable_database_metadata(tmp_path):
    import duckdb
    from data_platform.query.evidence import file_ref
    from data_platform.business_library import execute_library_query, load_library, read_library_result

    library = tmp_path / 'library'
    (library / 'tables').mkdir(parents=True)
    table_bytes = b'{"value":1}\n'
    table = library / 'tables/value.jsonl'
    table.write_bytes(table_bytes)
    database = library / 'business.duckdb'
    with duckdb.connect(str(database)) as connection:
        connection.execute('CREATE SCHEMA queries')
        connection.execute('CREATE TABLE queries.batch(batch_id VARCHAR)')
        connection.execute('INSERT INTO queries.batch VALUES (?)', [BATCH])
        connection.execute('CREATE TABLE queries.data_values(value BIGINT)')
        connection.execute('INSERT INTO queries.data_values VALUES (1)')
    manifest = {
        'schema_version': 'business_query_library.v1', 'batch_id': BATCH,
        'as_of_date': DAY, 'snapshots': {'training': 'bi', 'abroad': 'abroad'},
        'coverage': {'data_through': '2026-11-03'},
        'binding': {'inputs': {'a': 'a' * 64}, 'rules': {'b': 'b' * 64}},
        'source_queries': [{'path': 'Output/source-receipt.json', 'sha256': 'c' * 64}],
        'tables': {'data_values': {'rows': 1, 'logical_sha256': 'd' * 64,
                              'columns': {'value': 'BIGINT'},
                              'data': {'path': 'tables/value.jsonl', 'sha256': hashlib.sha256(table_bytes).hexdigest(),
                                       'size_bytes': len(table_bytes)}}},
        'database': file_ref(database, library, 'application/vnd.duckdb'),
    }
    (library / 'library_manifest.json').write_text(json.dumps(manifest))

    digest = candidate._compact_library(library)
    assert digest == hashlib.sha256((library / 'library_manifest.json').read_bytes()).hexdigest()
    assert not table.exists()
    compacted = json.loads((library / 'library_manifest.json').read_bytes())
    assert compacted['tables']['data_values']['storage'] == {'schema': 'queries', 'table': 'data_values'}
    assert 'data' not in compacted['tables']['data_values']

    loaded, _, _ = load_library(library, BATCH)
    result = execute_library_query(library=library, batch_id=BATCH,
                                   sql='SELECT value FROM queries.data_values',
                                   run_id='run_foundation_compact_test', output_root=tmp_path / 'queries')
    assert read_library_result(result, output_root=tmp_path / 'queries')['rows'] == [[1]]


def test_cleanup_prunes_only_explicit_old_release_after_current_check(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate.os, 'geteuid', lambda: 0)
    import dashboard_product.shadow_bi.p5.raw_publish as raw_publish
    monkeypatch.setattr(raw_publish, 'live_reference', lambda path: False)
    base = tmp_path / 'shadow-bi'
    releases = base / 'releases'
    old = releases / 'daily-20261103-old'
    current_release = releases / RELEASE
    old.mkdir(parents=True)
    current_release.mkdir()
    (old / 'marker').write_text('old')
    (current_release / 'marker').write_text('new')
    (base / 'current').symlink_to(current_release)
    (base / 'previous').symlink_to(old)
    (base / '.foundation-candidate.lock').touch()

    result = candidate.cleanup(expected_current=RELEASE, remove_release='daily-20261103-old',
                               expected_previous='daily-20261103-old', drop_previous=True, base=base)

    assert result == {'status': 'pruned', 'current': RELEASE,
                      'removed_release': 'daily-20261103-old', 'previous_removed': True}
    assert current_release.is_dir()
    assert not old.exists()
    assert not (base / 'previous').is_symlink()


def test_cleanup_preflight_rejection_leaves_old_release_intact(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate.os, 'geteuid', lambda: 0)
    base = tmp_path / 'shadow-bi'
    releases = base / 'releases'
    old = releases / 'daily-20261103-old'
    new = releases / RELEASE
    old.mkdir(parents=True)
    new.mkdir()
    (base / 'current').symlink_to(old)
    (base / 'previous').symlink_to(new)
    (base / '.foundation-candidate.lock').touch()

    with pytest.raises(ValueError, match='current release changed'):
        candidate.cleanup(expected_current=RELEASE, remove_release='daily-20261103-old',
                          expected_previous='daily-20261103-old', drop_previous=True, base=base)

    assert old.is_dir()
    assert (base / 'previous').is_symlink()


def test_cleanup_reports_nonfatal_error_after_release_retirement(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate.os, 'geteuid', lambda: 0)
    import dashboard_product.shadow_bi.p5.raw_publish as raw_publish
    monkeypatch.setattr(raw_publish, 'live_reference', lambda path: False)
    base = tmp_path / 'shadow-bi'
    releases = base / 'releases'
    old = releases / 'daily-20261103-old'
    current_release = releases / RELEASE
    old.mkdir(parents=True)
    current_release.mkdir()
    (base / 'current').symlink_to(current_release)
    (base / 'previous').symlink_to(old)
    (base / '.foundation-candidate.lock').touch()
    real_rmtree = shutil.rmtree

    def fail_retired(path, *args, **kwargs):
        if Path(path).name == '.retired-daily-20261103-old':
            raise OSError('simulated unlink failure')
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(candidate.shutil, 'rmtree', fail_retired)
    result = candidate.cleanup(expected_current=RELEASE, remove_release='daily-20261103-old',
                               expected_previous='daily-20261103-old', drop_previous=True, base=base)

    assert result['status'] == 'retired_cleanup_incomplete'
    assert result['retired_release'] == 'daily-20261103-old'
    assert current_release.is_dir()
    assert not old.exists()
    assert (releases / '.retired-daily-20261103-old').is_dir()


@pytest.mark.parametrize('previous_state', ['absent', 'dangling'])
def test_cleanup_accepts_missing_or_dangling_previous(tmp_path, monkeypatch, previous_state):
    monkeypatch.setattr(candidate.os, 'geteuid', lambda: 0)
    import dashboard_product.shadow_bi.p5.raw_publish as raw_publish
    monkeypatch.setattr(raw_publish, 'live_reference', lambda path: False)
    base = tmp_path / 'shadow-bi'
    releases = base / 'releases'
    old = releases / 'daily-20261103-old'
    current_release = releases / RELEASE
    old.mkdir(parents=True)
    current_release.mkdir()
    (base / 'current').symlink_to(current_release)
    (base / '.foundation-candidate.lock').touch()
    previous = base / 'previous'
    if previous_state == 'dangling':
        previous.symlink_to(old)
        shutil.rmtree(old)

    result = candidate.cleanup(expected_current=RELEASE, remove_release='daily-20261103-old',
                               expected_previous='daily-20261103-old', drop_previous=True, base=base)

    assert result['status'] == 'pruned'
    assert current_release.is_dir()
    assert not previous.is_symlink()


def test_cleanup_after_rollback_removes_only_the_failed_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate.os, 'geteuid', lambda: 0)
    import dashboard_product.shadow_bi.p5.raw_publish as raw_publish
    monkeypatch.setattr(raw_publish, 'live_reference', lambda path: False)
    base = tmp_path / 'shadow-bi'
    releases = base / 'releases'
    old = releases / 'daily-20261103-old'
    failed = releases / RELEASE
    old.mkdir(parents=True)
    failed.mkdir()
    (old / 'marker').write_text('old')
    (failed / 'marker').write_text('failed')
    (base / 'current').symlink_to(old)
    (base / 'previous').symlink_to(failed)
    (base / '.foundation-candidate.lock').touch()

    result = candidate.cleanup(expected_current='daily-20261103-old', remove_release=RELEASE,
                               expected_previous=RELEASE, drop_previous=True, base=base)

    assert result['status'] == 'pruned'
    assert old.is_dir()
    assert not failed.exists()
    assert not (base / 'previous').is_symlink()
