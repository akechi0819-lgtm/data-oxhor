"""Transfer the explicit Snapshot pair required by a remote SQL build."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

from data_acquisition.transfer.foundation import _relative, _sha_size
from data_platform.query.evidence import snapshot_ref
from data_platform.snapshots.ingest import SNAPSHOT_ID


SCHEMA = 'sql_foundation_transfer.v1'
REFERENCES = (
    'Work/workspace.json',
    'Work/StudyAbroad/current.json',
    'Work/Bridge/reference.json',
    'Input/Reference/留学板块-官方记分卡.json',
    'Input/Reference/留学-FY26-资源表.xlsx',
)
OPTIONAL = (
    'Input/Reference/留学板块-官方记分卡-对账口径.json',
    'Input/Reference/人员产能/留学人员历史产能.xlsx',
)


def _selected(workspace, training_snapshot, abroad_snapshot):
    if not all(isinstance(value, str) and SNAPSHOT_ID.fullmatch(value)
               for value in (training_snapshot, abroad_snapshot)):
        raise ValueError('explicit Snapshot identities are invalid')
    if training_snapshot == abroad_snapshot:
        raise ValueError('Snapshot identities must be distinct')
    training = json.loads((workspace / REFERENCES[0]).read_bytes())
    abroad = json.loads((workspace / REFERENCES[1]).read_bytes())
    if training['current_snapshot_id'] != training_snapshot or abroad['snapshot_id'] != abroad_snapshot:
        raise ValueError('Snapshot pair does not match workspace pointers')
    if training['company_id'] != abroad['company_id']:
        raise ValueError('Snapshot pair does not match company')
    files = list(REFERENCES)
    for pointer, key, snapshot in (
        (training, 'current_warehouse_path', training_snapshot),
        (abroad, 'warehouse', abroad_snapshot),
    ):
        relative = _relative(pointer[key], 'warehouse path')
        if relative.name != 'warehouse.duckdb' or relative.parent.name != snapshot:
            raise ValueError('warehouse path does not identify the requested Snapshot')
        warehouse = workspace.joinpath(*relative.parts)
        if not warehouse.resolve(strict=True).is_relative_to(workspace):
            raise ValueError('warehouse path escapes workspace')
        ref = snapshot_ref(warehouse, snapshot)
        digest, _ = _sha_size(warehouse)
        if digest != ref['warehouse_sha256']:
            raise ValueError('warehouse hash differs from Snapshot manifest')
        files.extend((relative.as_posix(), (relative.parent / 'snapshot_manifest.json').as_posix()))
    files.extend(path for path in OPTIONAL if (workspace / path).is_file())
    return files


def prepare_sql_foundation(workspace, *, training_snapshot, abroad_snapshot, output_path,
                           comparison_contract=None):
    """Seal exactly two Snapshots and their build references into one TAR."""
    workspace = Path(workspace).resolve(strict=True)
    paths = _selected(workspace, training_snapshot, abroad_snapshot)
    source = {name: workspace / name for name in paths}
    if comparison_contract is not None:
        source[OPTIONAL[0]] = Path(comparison_contract).resolve(strict=True)
    entries = {}
    for name, path in source.items():
        if path.is_symlink() or not path.resolve(strict=True).is_file():
            raise ValueError('transfer input must be a regular file')
        digest, size = _sha_size(path)
        entries[name] = {'sha256': digest, 'size_bytes': size}
    manifest = {'schema_version': SCHEMA,
                'snapshots': {'training': training_snapshot, 'abroad': abroad_snapshot},
                'files': entries}
    output_path = Path(output_path).absolute()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() or output_path.is_symlink():
        raise ValueError('refuse to overwrite transfer archive')
    fd, tmp_name = tempfile.mkstemp(prefix='.sql-foundation-', dir=output_path.parent)
    os.close(fd)
    temporary = Path(tmp_name)
    try:
        with tarfile.open(temporary, 'w') as archive:
            payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
            info = tarfile.TarInfo('manifest.json')
            info.size, info.mode = len(payload), 0o600
            archive.addfile(info, io.BytesIO(payload))
            for name, path in sorted(source.items()):
                spec = entries[name]
                if _sha_size(path) != (spec['sha256'], spec['size_bytes']):
                    raise ValueError('transfer input changed before packing')
                info = tarfile.TarInfo('workspace/' + name)
                info.size, info.mode = spec['size_bytes'], 0o600
                with path.open('rb') as stream:
                    archive.addfile(info, stream)
                if _sha_size(path) != (spec['sha256'], spec['size_bytes']):
                    raise ValueError('transfer input changed during packing')
        digest, size = _sha_size(temporary)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {'sha256': digest, 'size_bytes': size, 'files': sorted(entries)}


def extract_sql_foundation(archive_path, *, expected_sha256, output_dir):
    """Validate and extract into a fresh isolated workspace."""
    archive_path = Path(archive_path).resolve(strict=True)
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256) or _sha_size(archive_path)[0] != expected_sha256:
        raise ValueError('transfer archive hash mismatch')
    output_dir = Path(output_dir).absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError('refuse to overwrite transfer output')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.sql-foundation-', dir=output_dir.parent))
    try:
        with tarfile.open(archive_path, 'r:') as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)) or 'manifest.json' not in names:
                raise ValueError('transfer archive has duplicate or missing entries')
            if any(not member.isfile() for member in members):
                raise ValueError('transfer archive must contain only regular files')
            manifest_member = archive.getmember('manifest.json')
            if manifest_member.size > 1024 * 1024:
                raise ValueError('transfer manifest is too large')
            manifest = json.load(archive.extractfile(manifest_member))
            if manifest.get('schema_version') != SCHEMA or not isinstance(manifest.get('files'), dict):
                raise ValueError('transfer manifest is invalid')
            files = manifest['files']
            expected = {'manifest.json'} | {'workspace/' + name for name in files}
            if set(names) != expected:
                raise ValueError('transfer members differ from manifest')
            for name, spec in files.items():
                relative = _relative(name, 'transfer path')
                member = archive.getmember('workspace/' + name)
                if (not isinstance(spec, dict) or set(spec) != {'sha256', 'size_bytes'}
                        or not re.fullmatch('[0-9a-f]{64}', str(spec['sha256']))
                        or type(spec['size_bytes']) is not int or member.size != spec['size_bytes']):
                    raise ValueError('transfer file identity is invalid')
                target = stage.joinpath('workspace', *relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('xb') as destination:
                    shutil.copyfileobj(source, destination)
                if _sha_size(target) != (spec['sha256'], spec['size_bytes']):
                    raise ValueError('transfer member hash mismatch')
        workspace = stage / 'workspace'
        snapshots = manifest['snapshots']
        selected = _selected(workspace, snapshots['training'], snapshots['abroad'])
        if set(selected) != set(files):
            raise ValueError('transfer contains files outside SQL build inputs')
        os.replace(stage, output_dir)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {'workspace': str(output_dir / 'workspace'), 'snapshots': snapshots}
