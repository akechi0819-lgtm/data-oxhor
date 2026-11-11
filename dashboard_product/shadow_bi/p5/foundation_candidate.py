"""Build an isolated Superset release from one sealed paired Snapshot bundle."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import fcntl
import grp
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile

from dashboard_product.shadow_bi.p5.publish_status import RELEASE

BASE = Path('/var/lib/shadow-bi')
INPUT_ROOT = BASE / 'foundation-inputs'
RELEASES = BASE / 'releases'
SCHEMA = 'shadow_foundation_bundle.v1'
BATCH = re.compile(r'run_shadow_daily_[a-z0-9_-]{1,28}')
SHA256 = re.compile(r'[0-9a-f]{64}')
RELEASE_DAY = re.compile(r'daily-(\d{8})[-_]')
MAX_ARCHIVE = 8 * 1024**3
MAX_EXPANDED = 16 * 1024**3
MAX_ENTRIES = 50_000
MIN_FREE = 5 * 1024**3


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _json(raw: bytes):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + str(os.getpid()) + '.tmp')
    with temporary.open('x', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _safe_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise ValueError('unsafe foundation path')
    path = PurePosixPath(value)
    if (not value or '\\' in value or '\x00' in value
            or path.is_absolute() or path.as_posix() != value
            or any(part in {'', '.', '..'} for part in path.parts)):
        raise ValueError('unsafe foundation path')
    return path


def _iso_day(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('invalid as_of_date')
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError('invalid as_of_date')
    return result


def validate_manifest(value: dict, *, batch_id: str, release_id: str, as_of_date: str,
                      company_id: str | None = None) -> dict:
    if not isinstance(value, dict):
        raise ValueError('invalid foundation bundle manifest')
    required = {'schema_version', 'batch_id', 'release_id', 'company_id',
                'as_of_date', 'snapshots', 'files'}
    if 'advertising_manifest' in value:
        required.add('advertising_manifest')
    if set(value) != required or value.get('schema_version') != SCHEMA:
        raise ValueError('invalid foundation bundle manifest')
    if (not BATCH.fullmatch(batch_id) or value['batch_id'] != batch_id
            or not RELEASE.fullmatch(release_id) or value['release_id'] != release_id
            or value['as_of_date'] != as_of_date
            or batch_id.split('_')[3] != as_of_date.replace('-', '')):
        raise ValueError('foundation bundle identity differs')
    release_day = RELEASE_DAY.match(release_id)
    if release_day is None or release_day.group(1) != as_of_date.replace('-', ''):
        raise ValueError('release date differs from as_of_date')
    day = _iso_day(as_of_date)
    if not isinstance(value['company_id'], str) or not re.fullmatch('[a-z][a-z0-9_-]{2,90}', value['company_id']):
        raise ValueError('invalid foundation company')
    if company_id is not None and value['company_id'] != company_id:
        raise ValueError('foundation company differs from server policy')
    snapshots = value['snapshots']
    if (not isinstance(snapshots, dict) or set(snapshots) != {'bi', 'study_abroad'}
            or any(not isinstance(item, str) or not item for item in snapshots.values())):
        raise ValueError('invalid foundation Snapshot pair')
    if not isinstance(value['files'], dict) or not value['files'] or len(value['files']) > MAX_ENTRIES - 1:
        raise ValueError('invalid foundation file inventory')
    declared = 0
    for relative, spec in value['files'].items():
        path = _safe_relative(relative)
        if not path.parts or path.parts[0] != 'workspace':
            raise ValueError('foundation files must be rooted at workspace/')
        if not isinstance(spec, dict) or set(spec) != {'sha256', 'size_bytes'}:
            raise ValueError('invalid foundation file entry')
        if (not isinstance(spec['sha256'], str) or not SHA256.fullmatch(spec['sha256'])
                or type(spec['size_bytes']) is not int or spec['size_bytes'] < 0):
            raise ValueError('invalid foundation file digest or size')
        declared += spec['size_bytes']
    if declared > MAX_EXPANDED:
        raise ValueError('foundation bundle expansion exceeds limit')
    ad_manifest = value.get('advertising_manifest')
    if ad_manifest is not None:
        if not isinstance(ad_manifest, str):
            raise ValueError('advertising manifest is not in the sealed workspace')
        ad_path = _safe_relative(ad_manifest)
        if (not ad_path.is_relative_to(PurePosixPath('Input/AdvertisingCosts'))
                or 'workspace/' + ad_manifest not in value['files']):
            raise ValueError('advertising manifest is not in the sealed workspace')
    return value


def _regular_file(path: Path, *, max_size: int | None = None) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('foundation input must be a regular file')
    if max_size is not None and (info.st_size <= 0 or info.st_size > max_size):
        raise ValueError('foundation input exceeds size limit')
    return info


def extract_bundle(archive: Path, foundation: Path, *, batch_id: str,
                   release_id: str, as_of_date: str, company_id: str,
                   max_free: int = MIN_FREE, disk_root: Path = BASE,
                   owner_uid: int = 0) -> tuple[dict, str, str]:
    """Copy and unpack one explicit bundle, verifying every member before use."""
    info = _regular_file(archive, max_size=MAX_ARCHIVE)
    if info.st_uid != owner_uid or info.st_mode & 0o022:
        raise ValueError('foundation archive must be root-owned and protected')
    archive_sha = sha(archive)
    with tarfile.open(archive, mode='r:') as bundle:
        members = bundle.getmembers()
        if not members or len(members) > MAX_ENTRIES or any(not m.isfile() for m in members):
            raise ValueError('foundation archive must contain regular files only')
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise ValueError('duplicate foundation archive entry')
        for member in members:
            _safe_relative(member.name)
            if member.size < 0 or member.size > MAX_EXPANDED:
                raise ValueError('foundation archive member size invalid')
        if names.count('manifest.json') != 1:
            raise ValueError('foundation bundle manifest missing')
        manifest_member = bundle.getmember('manifest.json')
        if manifest_member.size > 2 * 1024**2:
            raise ValueError('foundation manifest exceeds size limit')
        stream = bundle.extractfile(manifest_member)
        if stream is None:
            raise ValueError('foundation manifest is unreadable')
        raw_manifest = stream.read(2 * 1024**2 + 1)
        if len(raw_manifest) != manifest_member.size:
            raise ValueError('foundation manifest size changed')
        manifest = validate_manifest(_json(raw_manifest), batch_id=batch_id,
                                     release_id=release_id, as_of_date=as_of_date,
                                     company_id=company_id)
        expected = {'manifest.json', *manifest['files']}
        if set(names) != expected:
            raise ValueError('foundation archive inventory differs from manifest')
        declared_total = sum(spec['size_bytes'] for spec in manifest['files'].values())
        if declared_total > MAX_EXPANDED:
            raise ValueError('foundation expansion exceeds limit')
        if shutil.disk_usage(disk_root).free < max_free + declared_total:
            raise ValueError('insufficient disk reserve for candidate build')
        for archive_name, spec in manifest['files'].items():
            member = bundle.getmember(archive_name)
            if member.size != spec['size_bytes']:
                raise ValueError('foundation member size differs')
            relative = _safe_relative(archive_name).parts[1:]
            target = foundation.joinpath(*relative)
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise ValueError('foundation destination already exists')
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError('foundation member is unreadable')
            digest = hashlib.sha256()
            count = 0
            with source, target.open('xb') as output:
                while chunk := source.read(1024 * 1024):
                    count += len(chunk)
                    if count > spec['size_bytes']:
                        raise ValueError('foundation member grew during extraction')
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if count != spec['size_bytes'] or digest.hexdigest() != spec['sha256']:
                raise ValueError('foundation member digest differs')
            target.chmod(0o600)
    return manifest, archive_sha, hashlib.sha256(raw_manifest).hexdigest()


def _snapshot_manifest(foundation: Path, warehouse_path: str, snapshot_id: str) -> None:
    relative = _safe_relative(warehouse_path)
    if len(relative.parts) < 6 or relative.parts[0] != 'Work' or relative.parts[-1] != 'warehouse.duckdb':
        raise ValueError('invalid current warehouse path')
    warehouse = foundation.joinpath(*relative.parts)
    if warehouse.is_symlink() or not warehouse.is_file() or snapshot_id not in relative.parts:
        raise ValueError('current warehouse identity differs')
    root = warehouse.parent
    manifest = _json((root / 'snapshot_manifest.json').read_bytes())
    if manifest.get('schema_version') != 'warehouse_snapshot.v2' or manifest.get('snapshot_id') != snapshot_id:
        raise ValueError('Snapshot manifest identity differs')
    entries = manifest.get('artifacts')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Snapshot artifact manifest is empty')
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256', 'size_bytes'}:
            raise ValueError('invalid Snapshot artifact entry')
        artifact_rel = _safe_relative(entry['path'])
        artifact = root.joinpath(*artifact_rel.parts)
        if artifact.is_symlink() or not artifact.resolve().is_relative_to(root.resolve()) or not artifact.is_file():
            raise ValueError('Snapshot artifact escaped its root')
        if type(entry['size_bytes']) is not int or artifact.stat().st_size != entry['size_bytes'] or sha(artifact) != entry['sha256']:
            raise ValueError('Snapshot artifact digest differs')


def validate_workspace(foundation: Path, manifest: dict, as_of_date: str,
                       *, minimum_cutoff: str | None = None) -> dict:
    required = ('Work/workspace.json', 'Work/StudyAbroad/current.json',
                'Work/DailyWarehouseRefresh/current.json', 'Work/Bridge/reference.json',
                'Work/Pack/pack.json')
    if any(not (foundation / path).is_file() for path in required):
        raise ValueError('foundation workspace closure is incomplete')
    workspace = _json((foundation / 'Work/workspace.json').read_bytes())
    abroad = _json((foundation / 'Work/StudyAbroad/current.json').read_bytes())
    if workspace.get('company_id') != manifest['company_id'] or abroad.get('company_id') != manifest['company_id']:
        raise ValueError('foundation workspace company differs')
    snapshots = manifest['snapshots']
    if (workspace.get('current_snapshot_id') != snapshots['bi']
            or abroad.get('snapshot_id') != snapshots['study_abroad']):
        raise ValueError('foundation current Snapshot pair differs')
    _snapshot_manifest(foundation, workspace['current_warehouse_path'], snapshots['bi'])
    _snapshot_manifest(foundation, abroad['warehouse'], snapshots['study_abroad'])
    from data_acquisition.jobs.daily_warehouses import assert_daily_ready
    receipt = assert_daily_ready(foundation, as_of_date,
                                 bi_snapshot_id=snapshots['bi'],
                                 study_snapshot_id=snapshots['study_abroad'])
    if receipt.get('company_id') != manifest['company_id']:
        raise ValueError('daily Snapshot pair receipt company differs')
    return receipt


def _policy_context() -> tuple[str, str]:
    from dashboard_product.shadow_bi.p5.raw_receiver import deployment_context
    return deployment_context()


def _quality_gate(foundation: Path, manifest: dict, batch_id: str) -> dict:
    from data_platform.query.service import quality_issues
    from data_platform.query.evidence import read_query_result

    workspace = _json((foundation / 'Work/workspace.json').read_bytes())
    abroad = _json((foundation / 'Work/StudyAbroad/current.json').read_bytes())
    suffix = hashlib.sha256(batch_id.encode()).hexdigest()[:12]
    output = foundation / 'Output/FoundationQuality'
    results = {}
    for key, warehouse, snapshot in (
        ('bi', foundation / workspace['current_warehouse_path'], manifest['snapshots']['bi']),
        ('study_abroad', foundation / abroad['warehouse'], manifest['snapshots']['study_abroad']),
    ):
        run_id = 'run_quality_' + key + '_' + suffix
        result = quality_issues(warehouse=warehouse, snapshot_id=snapshot, run_id=run_id,
                                output_root=output, max_rows=10000)
        _write_json(output / (key + '.json'), result)
        data = read_query_result(result, output_root=output)
        if data['rows']:
            raise ValueError('Snapshot quality issues require review')
        results[key] = {'snapshot_id': snapshot, 'status': result['status'],
                        'receipt': result['receipt']}
    return results


def _build_library(foundation: Path, library_path: Path, *, manifest: dict,
                   batch_id: str, as_of_date: str, gate_minimum_cutoff: str) -> dict:
    # Keep DuckDB use bounded as in the existing isolated raw builder.
    temporary = foundation / '.duckdb-tmp'
    temporary.mkdir(mode=0o700)
    os.environ['OXHOR_RAW_TMP'] = str(temporary)
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['OMP_NUM_THREADS'] = '1'
    from dashboard_product.shadow_bi.p5.raw_compute import limits, library_gates
    limits()
    quality = _quality_gate(foundation, manifest, batch_id)
    from types import SimpleNamespace
    from dashboard_product.shadow_bi.library import build
    args = SimpleNamespace(
        workspace=foundation,
        snapshot_id=manifest['snapshots']['bi'],
        study_abroad_snapshot_id=manifest['snapshots']['study_abroad'],
        run_id=batch_id,
        as_of_date=as_of_date,
        server_complete=True,
    )
    advertising_manifest = manifest.get('advertising_manifest')
    if advertising_manifest is not None:
        args.advertising_manifest = foundation / _safe_relative(advertising_manifest)
    model = build(args)
    del model
    source_library = foundation / 'Output/ShadowBI' / batch_id / 'library'
    if not source_library.is_dir() or source_library.resolve() != library_path.resolve():
        raise ValueError('shared calculation wrote the library outside the candidate')
    metadata = json.loads((source_library / 'library_manifest.json').read_bytes())
    yesterday = (date.fromisoformat(as_of_date) - timedelta(days=1)).isoformat()
    if metadata['coverage']['data_through'] != yesterday:
        raise ValueError('business cutoff mismatch')
    if metadata['coverage']['study_abroad_source']['through_date'] != yesterday:
        raise ValueError('study-abroad cutoff mismatch')
    if metadata['coverage']['data_through'] < gate_minimum_cutoff:
        raise ValueError('computed cutoff is older than the formal release')
    if metadata['snapshots'] != {'training': manifest['snapshots']['bi'],
                                 'abroad': manifest['snapshots']['study_abroad']}:
        raise ValueError('business library Snapshot pair differs')
    if metadata['as_of_date'] != as_of_date or metadata['batch_id'] != batch_id:
        raise ValueError('business library batch identity differs')
    checked = library_gates(source_library, batch_id, as_of_date)
    metadata = json.loads((source_library / 'library_manifest.json').read_bytes())
    return {'library_manifest': metadata, 'gates': {**checked, 'quality': quality}}


def _compact_library(library: Path) -> str:
    manifest_path = library / 'library_manifest.json'
    manifest = _json(manifest_path.read_bytes())
    removed = 0
    for name, spec in manifest['tables'].items():
        data = spec.pop('data', None)
        if data is None:
            raise ValueError('business table data missing before compaction')
        relative = _safe_relative(data['path'])
        if len(relative.parts) != 2 or relative.parts[0] != 'tables' or not relative.name.endswith('.jsonl'):
            raise ValueError('invalid business table payload path')
        path = library.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file() or path.stat().st_size != data['size_bytes'] or sha(path) != data['sha256']:
            raise ValueError('business table payload changed after physical gate')
        path.unlink()
        spec['storage'] = {'schema': 'queries', 'table': name}
        removed += 1
    tables = library / 'tables'
    if tables.exists():
        tables.rmdir()
    manifest['server_materialization'] = {
        'kind': 'typed_duckdb',
        'table_payloads_removed_after_gates': removed,
        'queryable_database': 'business.duckdb',
    }
    _write_json(manifest_path, manifest)
    return sha(manifest_path)


def _set_release_modes(target: Path) -> None:
    group = grp.getgrnam('shadowbi').gr_gid
    os.chown(target, 0, group)
    target.chmod(0o750)
    foundation = target / 'foundation'
    for path in [foundation, *foundation.rglob('*')]:
        if path.is_symlink():
            raise ValueError('foundation symlink rejected')
        os.chown(path, 0, 0)
        path.chmod(0o700 if path.is_dir() else 0o600)
    library = target / 'library'
    for path in [library, *library.rglob('*')]:
        if path.is_symlink():
            raise ValueError('library symlink rejected')
        os.chown(path, 0, group)
        path.chmod(0o750 if path.is_dir() else 0o640)
    prepared = target / 'prepared.json'
    if prepared.exists():
        os.chown(prepared, 0, group)
        prepared.chmod(0o640)


def _validate_prepared_target(target: Path, release_id: str, releases: Path = RELEASES) -> None:
    resolved = target.resolve(strict=True)
    if resolved.parent != releases.resolve(strict=True) or resolved.name != release_id:
        raise ValueError('candidate escaped the fixed releases directory')


def prepare(*, batch_id: str, release_id: str, as_of_date: str,
            base: Path = BASE, minimum_free_bytes: int = MIN_FREE,
            policy_context=None, builder=None, mode_setter=None, owner_uid: int = 0) -> dict:
    """Prepare a final release tree without changing current/previous pointers."""
    if os.geteuid() != 0:
        raise PermissionError('foundation candidate preparation requires root')
    _iso_day(as_of_date)
    if not BATCH.fullmatch(batch_id) or not RELEASE.fullmatch(release_id):
        raise ValueError('invalid foundation candidate identity')
    if batch_id.split('_')[3] != as_of_date.replace('-', ''):
        raise ValueError('batch date differs from as_of_date')
    base = Path(base)
    releases = base / 'releases'
    input_root = base / 'foundation-inputs'
    source_folder = input_root / batch_id
    archive = source_folder / 'payload.tar'
    target = releases / release_id
    lock_path = base / '.foundation-candidate.lock'
    if base.is_symlink() or releases.is_symlink() or input_root.is_symlink() or source_folder.is_symlink():
        raise ValueError('foundation candidate roots must not be symlinks')
    with lock_path.open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not releases.is_dir() or not input_root.is_dir():
            raise ValueError('foundation candidate directories are not installed')
        for directory in (input_root, source_folder):
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid or info.st_mode & 0o022:
                raise ValueError('foundation upload directory must be root-owned and protected')
        if target.exists() or target.is_symlink():
            raise ValueError('release target already exists')
        current = base / 'current'
        if current.exists() and current.resolve(strict=True) == target:
            raise ValueError('release target is already current')
        if policy_context is None:
            company_id, minimum_cutoff = _policy_context()
        else:
            company_id, minimum_cutoff = policy_context()
        target.mkdir(mode=0o700)
        try:
            (target / 'foundation').mkdir(mode=0o700)
            manifest, archive_sha, bundle_manifest_sha = extract_bundle(
                archive, target / 'foundation', batch_id=batch_id,
                release_id=release_id, as_of_date=as_of_date,
                company_id=company_id, max_free=minimum_free_bytes, disk_root=base,
                owner_uid=owner_uid)
            validate_workspace(target / 'foundation', manifest, as_of_date,
                               minimum_cutoff=minimum_cutoff)
            if builder is None:
                built = _build_library(
                    target / 'foundation',
                    target / 'foundation/Output/ShadowBI' / batch_id / 'library',
                    manifest=manifest, batch_id=batch_id, as_of_date=as_of_date,
                    gate_minimum_cutoff=minimum_cutoff)
            else:
                built = builder(target / 'foundation', manifest)
            generated_library = target / 'foundation/Output/ShadowBI' / batch_id / 'library'
            library = target / 'library'
            if library.exists() or not generated_library.is_dir():
                raise ValueError('generated business library is missing')
            generated_library.rename(library)
            manifest_sha = _compact_library(library)
            from data_platform.business_library import load_library, execute_library_query, read_library_result
            library_manifest, _, _ = load_library(library, batch_id)
            gate_result = execute_library_query(
                library=library, batch_id=batch_id,
                sql='SELECT batch_id FROM queries.batch',
                run_id='run_release_' + hashlib.sha256(batch_id.encode()).hexdigest()[:20],
                output_root=target / 'foundation/Output/ShadowBI/release-checks')
            if read_library_result(gate_result, output_root=target / 'foundation/Output/ShadowBI/release-checks')['rows'] != [[batch_id]]:
                raise ValueError('released business library identity differs')
            coverage = library_manifest['coverage']
            result = {
                'status': 'prepared', 'published': False,
                'release': release_id, 'batch_id': batch_id,
                'as_of_date': as_of_date, 'coverage': coverage,
                'snapshots': library_manifest['snapshots'],
                'foundation': str(target / 'foundation'),
                'library': str(library),
                'bundle_sha256': archive_sha,
                'bundle_manifest_sha256': bundle_manifest_sha,
                'manifest_sha256': manifest_sha,
                'gates': built['gates'],
            }
            _write_json(target / 'prepared.json', result)
            temporary = target / 'foundation/.duckdb-tmp'
            if temporary.exists():
                shutil.rmtree(temporary)
            setter = mode_setter or _set_release_modes
            setter(target)
            _validate_prepared_target(target, release_id, releases)
            # The payload is now represented by the persisted foundation tree.
            if source_folder.exists() and not source_folder.is_symlink():
                shutil.rmtree(source_folder)
            return result
        except BaseException:
            if target.exists() and not target.is_symlink():
                shutil.rmtree(target)
            if source_folder.exists() and not source_folder.is_symlink():
                shutil.rmtree(source_folder)
            raise


def _previous_is(previous: Path, release_path: Path) -> bool:
    if not previous.is_symlink():
        return False
    link = Path(os.readlink(previous))
    linked = link if link.is_absolute() else previous.parent / link
    return Path(os.path.abspath(linked)) == Path(os.path.abspath(release_path))


def cleanup(*, expected_current: str, remove_release: str,
            expected_previous: str | None = None, drop_previous: bool = False,
            base: Path = BASE) -> dict:
    """Prune only an explicitly named release after current has been verified."""
    if os.geteuid() != 0:
        raise PermissionError('foundation release cleanup requires root')
    if not RELEASE.fullmatch(expected_current) or not RELEASE.fullmatch(remove_release):
        raise ValueError('invalid cleanup release identity')
    if expected_current == remove_release:
        raise ValueError('cleanup cannot remove current')
    if drop_previous and expected_previous is None:
        raise ValueError('dropping previous requires its explicit release identity')
    if expected_previous is not None and not RELEASE.fullmatch(expected_previous):
        raise ValueError('invalid previous release identity')
    base = Path(base)
    releases = base / 'releases'
    current = base / 'current'
    previous = base / 'previous'
    with (base / '.foundation-candidate.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if releases.is_symlink() or not current.is_symlink():
            raise ValueError('release pointers are not installed')
        target_path = releases / expected_current
        if current.resolve(strict=True) != target_path.resolve(strict=True):
            raise ValueError('current release changed before cleanup')
        previous_path = releases / expected_previous if expected_previous is not None else None
        if expected_previous is not None:
            if previous.exists() or previous.is_symlink():
                if not _previous_is(previous, previous_path):
                    raise ValueError('previous release changed before cleanup')
        if drop_previous and expected_previous is None:
            raise ValueError('previous release identity required')
        removal = releases / remove_release
        if removal.is_symlink():
            raise ValueError('refusing to remove a release symlink')
        retired = releases / ('.retired-' + remove_release)
        if retired.is_symlink():
            raise ValueError('retired release is a symlink')
        if removal.exists() and retired.exists():
            raise ValueError('both live and retired release paths exist')
        if removal.exists():
            resolved = removal.resolve(strict=True)
            if resolved.parent != releases.resolve(strict=True) or resolved == target_path.resolve(strict=True):
                raise ValueError('cleanup release escaped fixed releases directory')
            from dashboard_product.shadow_bi.p5.raw_publish import live_reference
            if live_reference(resolved):
                raise ValueError('release still has active file readers')
        elif retired.exists():
            resolved = retired.resolve(strict=True)
            if resolved.parent != releases.resolve(strict=True):
                raise ValueError('retired release escaped fixed releases directory')
        elif expected_previous is not None and previous.is_symlink() and not _previous_is(previous, previous_path):
            raise ValueError('previous release changed before cleanup')
        # All identities and active readers are checked before the first destructive step.
        moved = False
        retirement_started = not removal.exists() and not retired.exists()
        try:
            if removal.exists():
                os.replace(removal, retired)
                moved = True
                retirement_started = True
            if drop_previous and (previous.exists() or previous.is_symlink()):
                previous.unlink()
            if retired.exists():
                shutil.rmtree(retired)
            fd = os.open(releases, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as error:
            if retirement_started or retired.exists():
                return {'status': 'retired_cleanup_incomplete', 'current': expected_current,
                        'retired_release': remove_release, 'retired_path': str(retired),
                        'error_type': type(error).__name__}
            raise
        return {'status': 'pruned', 'current': expected_current,
                'removed_release': remove_release,
                'previous_removed': bool(drop_previous)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('prepare')
    command.add_argument('--batch-id', required=True)
    command.add_argument('--release-id', required=True)
    command.add_argument('--as-of-date', required=True)
    clean = sub.add_parser('cleanup')
    clean.add_argument('--expected-current', required=True)
    clean.add_argument('--remove-release', required=True)
    clean.add_argument('--expected-previous')
    clean.add_argument('--drop-previous', action='store_true')
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(batch_id=args.batch_id, release_id=args.release_id, as_of_date=args.as_of_date)
    else:
        result = cleanup(expected_current=args.expected_current, remove_release=args.remove_release,
                         expected_previous=args.expected_previous, drop_previous=args.drop_previous)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
