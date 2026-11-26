from copy import deepcopy

import pytest

from data_acquisition.transfer.sql_landing_delta import (
    LANDING_TABLES, apply_delta, make_delta, make_delta_from_index, make_index,
)


def tables():
    columns = ['source_id', 'source_sha256', 'source_filename', 'sheet_name',
               'source_row_number', 'ingest_batch_id', 'snapshot_id', 'origin_sha256',
               'origin_row_number', 'record_key', 'ID', '金额']
    rows = [['source', 'old-hash', 'old.xlsx', 'sheet', 2, 'old', 'old', 'h1', 3, 'r1', 'a', '10.00'],
            ['source', 'old-hash', 'old.xlsx', 'sheet', 3, 'old', 'old', 'h1', 4, 'r2', 'b', '20.00'],
            ['source', 'old-hash', 'old.xlsx', 'sheet', 4, 'old', 'old', 'h1', 5, 'r3', 'b', '20.00']]
    return {name: {'columns': columns[:], 'rows': deepcopy(rows)} for name in LANDING_TABLES}


def test_incremental_reorder_duplicate_delete_and_lineage():
    old = tables()
    new = deepcopy(old)
    name = sorted(LANDING_TABLES)[0]
    rows = new[name]['rows']
    rows[0][10:] = ['c', '30.00']
    rows.pop(1)
    rows.reverse()
    for row in rows:
        row[1], row[5], row[6] = 'new-hash', 'new', 'new'
    delta = make_delta(old, new)
    patch = delta['tables'][name]
    assert len(patch['values']) == 1
    assert sum(patch['removed'].values()) == 2
    assert apply_delta(old, delta, expected_release='local', expected_warehouse_sha256='0' * 64) == new


def test_verified_index_avoids_uploading_unchanged_values():
    old = tables()
    index = make_index(old, release='daily-cloud', warehouse_sha256='a' * 64)
    delta = make_delta_from_index(index, old, expected_release='daily-cloud', expected_warehouse_sha256='a' * 64)
    assert all(not patch['values'] and not patch['removed'] for patch in delta['tables'].values())
    assert apply_delta(old, delta, expected_release='daily-cloud', expected_warehouse_sha256='a' * 64) == old
    with pytest.raises(ValueError, match='identity'):
        apply_delta(old, delta, expected_release='other-release', expected_warehouse_sha256='a' * 64)


def test_baseline_and_result_changes_are_rejected():
    old = tables()
    new = deepcopy(old)
    name = sorted(LANDING_TABLES)[0]
    new[name]['rows'][0][-1] = '100.00'
    delta = make_delta(old, new)
    bad = deepcopy(old)
    bad[name]['rows'][0][-1] = '12.00'
    with pytest.raises(ValueError, match='baseline mismatch'):
        apply_delta(bad, delta, expected_release='local', expected_warehouse_sha256='0' * 64)
    patch = delta['tables'][name]
    patch['order'].reverse()
    with pytest.raises(ValueError, match='result mismatch'):
        apply_delta(old, delta, expected_release='local', expected_warehouse_sha256='0' * 64)


def test_invalid_schema_and_index_rejected():
    old = tables()
    new = deepcopy(old)
    name = sorted(LANDING_TABLES)[0]
    new[name]['columns'].reverse()
    with pytest.raises(ValueError, match='schema changed'):
        make_delta(old, new)
    index = make_index(old, release='daily-cloud', warehouse_sha256='a' * 64)
    index['tables'][name]['row_count'] += 1
    with pytest.raises(ValueError, match='invalid landing index'):
        make_delta_from_index(index, old, expected_release='daily-cloud', expected_warehouse_sha256='a' * 64)
