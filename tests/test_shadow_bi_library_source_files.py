import json
import shutil

import pytest

from dashboard_product.shadow_bi import library


def make_workspace(root):
    current = root / 'Work/Runs/run_current/data/snapshots/snapshot_current'
    old = root / 'Work/Runs/run_old/data/snapshots/snapshot_old'
    current.mkdir(parents=True)
    old.mkdir(parents=True)
    (current / 'warehouse.duckdb').write_bytes(b'current BI snapshot')
    (old / 'warehouse.duckdb').write_bytes(b'retired BI snapshot')
    (root / 'Work/Runs/_bi_export_keep').mkdir(parents=True)
    (root / 'Work/Runs/_bi_export_keep/orders.xlsx').write_bytes(b'original export')
    (root / 'Work/workspace.json').write_text(json.dumps({
        'schema_version': 'bridge_alignment_workspace.v1',
        'current_snapshot_id': 'snapshot_current',
        'current_warehouse_path': (
            'Work/Runs/run_current/data/snapshots/snapshot_current/warehouse.duckdb'
        ),
    }))
    study_current = root / 'Work/StudyAbroad/Runs/run_study_current'
    study_old = root / 'Work/StudyAbroad/Runs/run_study_old'
    study_current.mkdir(parents=True)
    study_old.mkdir(parents=True)
    (study_current / 'lineage.json').write_text(json.dumps({
        'normalized_history': {'query_run_ids': {'resources': 'run_history'}},
    }))
    (study_old / 'retained-history.json').write_text('study history')
    (root / 'Work/StudyAbroad/current.json').write_text(json.dumps({
        'source_lineage': 'Work/StudyAbroad/Runs/run_study_current/lineage.json',
    }))
    history = root / 'Output/StudyAbroad/历史查询回执/run_history'
    history.mkdir(parents=True)
    (history / 'receipt.json').write_text('{}')
    input_file = root / 'Input/Data/orders/orders.xlsx'
    input_file.parent.mkdir(parents=True)
    input_file.write_bytes(b'current input')
    return old


def test_source_files_binds_only_current_bi_run_and_survives_old_run_removal(
        tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    old_run = make_workspace(workspace)
    monkeypatch.setattr(library, 'code_files', lambda: [])

    before_paths = {path.relative_to(workspace).as_posix()
                    for path in library.source_files(workspace)}
    before_binding = library.binding(workspace)['inputs']

    current_path = 'Work/Runs/run_current/data/snapshots/snapshot_current/warehouse.duckdb'
    old_path = 'Work/Runs/run_old/data/snapshots/snapshot_old/warehouse.duckdb'
    assert current_path in before_paths
    assert old_path not in before_paths
    assert 'Work/Runs/_bi_export_keep/orders.xlsx' in before_paths
    assert 'Work/StudyAbroad/Runs/run_study_old/retained-history.json' in before_paths
    assert 'Output/StudyAbroad/历史查询回执/run_history/receipt.json' in before_paths

    target = tmp_path / 'copy' / 'workspace'
    library.initialize(workspace, target)
    copied_inputs = json.loads((tmp_path / 'copy/input-copy.json').read_text())['files']
    assert (target / old_path).is_file()
    assert current_path in copied_inputs
    assert old_path not in copied_inputs
    assert library.source_files(target)

    shutil.rmtree(old_run)
    after_paths = {path.relative_to(workspace).as_posix()
                   for path in library.source_files(workspace)}
    after_binding = library.binding(workspace)['inputs']
    assert after_paths == before_paths
    assert after_binding == before_binding


def test_source_files_requires_a_current_bi_snapshot(tmp_path):
    workspace = tmp_path / 'workspace'
    (workspace / 'Work').mkdir(parents=True)
    (workspace / 'Work/workspace.json').write_text(json.dumps({
        'schema_version': 'bridge_alignment_workspace.v1',
        'current_snapshot_id': None,
        'current_warehouse_path': None,
    }))

    with pytest.raises(ValueError, match='no current Snapshot'):
        library.source_files(workspace)
