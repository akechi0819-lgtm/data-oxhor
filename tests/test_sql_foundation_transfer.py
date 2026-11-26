import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from data_acquisition.transfer.sql_foundation import (
    extract_sql_foundation,
    prepare_sql_foundation,
)


TRAINING = 'snapshot_training_20261126'
ABROAD = 'snapshot_abroad_20261126'


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def workspace(root):
    for run, snapshot in (('training', TRAINING), ('abroad', ABROAD)):
        relative = Path('Work/Runs') / run / snapshot
        database = (run + ' data').encode()
        write(root / relative / 'warehouse.duckdb', database)
        manifest = {'schema_version': 'warehouse_snapshot.v2', 'snapshot_id': snapshot,
                    'artifacts': [{'path': 'warehouse.duckdb',
                                   'size_bytes': len(database),
                                   'sha256': hashlib.sha256(database).hexdigest()}]}
        write(root / relative / 'snapshot_manifest.json', json.dumps(manifest).encode())
    pointer = {'company_id': 'test', 'current_snapshot_id': TRAINING,
               'current_warehouse_path': f'Work/Runs/training/{TRAINING}/warehouse.duckdb'}
    abroad = {'company_id': 'test', 'snapshot_id': ABROAD,
              'warehouse': f'Work/Runs/abroad/{ABROAD}/warehouse.duckdb'}
    write(root / 'Work/workspace.json', json.dumps(pointer).encode())
    write(root / 'Work/StudyAbroad/current.json', json.dumps(abroad).encode())
    write(root / 'Work/Bridge/reference.json', b'{}')
    write(root / 'Input/Reference/留学板块-官方记分卡.json', b'{}')
    write(root / 'Input/Reference/留学-FY26-资源表.xlsx', b'reference')
    write(root / '.private/server-password', b'never include')
    write(root / 'Work/Runs/training/extra.csv', b'never include')


def test_round_trip_selects_only_explicit_build_inputs(tmp_path):
    source = tmp_path / 'source'
    workspace(source)
    contract = tmp_path / 'approved.json'
    contract.write_text('{}')
    archive = tmp_path / 'payload.tar'
    result = prepare_sql_foundation(source, training_snapshot=TRAINING, abroad_snapshot=ABROAD,
                                    output_path=archive, comparison_contract=contract)
    assert len(result['files']) == 10
    assert '.private/server-password' not in result['files']
    extracted = extract_sql_foundation(archive, expected_sha256=result['sha256'],
                                       output_dir=tmp_path / 'remote')
    assert extracted['snapshots'] == {'training': TRAINING, 'abroad': ABROAD}
    assert (Path(extracted['workspace']) / 'Input/Reference/留学板块-官方记分卡-对账口径.json').is_file()


def test_rejects_wrong_pair_and_modified_snapshot(tmp_path):
    source = tmp_path / 'source'
    workspace(source)
    archive = tmp_path / 'payload.tar'
    with pytest.raises(ValueError, match='does not match workspace pointers'):
        prepare_sql_foundation(source, training_snapshot=ABROAD, abroad_snapshot=TRAINING, output_path=archive)
    (source / f'Work/Runs/training/{TRAINING}/warehouse.duckdb').write_bytes(b'altered')
    with pytest.raises(ValueError, match='warehouse hash|manifest identity'):
        prepare_sql_foundation(source, training_snapshot=TRAINING, abroad_snapshot=ABROAD, output_path=archive)


def test_rejects_tampered_and_path_escape_archive(tmp_path):
    source = tmp_path / 'source'
    workspace(source)
    archive = tmp_path / 'payload.tar'
    result = prepare_sql_foundation(source, training_snapshot=TRAINING, abroad_snapshot=ABROAD, output_path=archive)
    with pytest.raises(ValueError, match='archive hash mismatch'):
        extract_sql_foundation(archive, expected_sha256='0'*64, output_dir=tmp_path / 'bad_hash')
    bad = tmp_path / 'escape.tar'
    with tarfile.open(bad, 'w') as tar:
        payload = json.dumps({'schema_version': 'sql_foundation_transfer.v1',
                              'snapshots': {'training': TRAINING, 'abroad': ABROAD},
                              'files': {'../escape': {'sha256': hashlib.sha256(b'x').hexdigest(),
                                                      'size_bytes': 1}}}).encode()
        manifest = tarfile.TarInfo('manifest.json')
        manifest.size = len(payload)
        tar.addfile(manifest, io.BytesIO(payload))
        item = tarfile.TarInfo('workspace/../escape')
        item.size = 1
        tar.addfile(item, io.BytesIO(b'x'))
    with pytest.raises(ValueError, match='unsafe'):
        extract_sql_foundation(bad, expected_sha256=hashlib.sha256(bad.read_bytes()).hexdigest(),
                               output_dir=tmp_path / 'bad_path')
    assert not (tmp_path / 'escape').exists()
    assert not (tmp_path / 'bad_path').exists()
