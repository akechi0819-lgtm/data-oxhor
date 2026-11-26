"""Compute and verify deltas of controlled landing-query results.

Inputs are ordered JSON query results, never database connections or Snapshot
files. A row's business values determine reuse. Positional and source lineage
values travel separately so a refreshed source hash does not resend the table.
"""
from collections import Counter
import hashlib
import json
import re

from dashboard_product.shadow_bi.sql_warehouse.foundation import TABLES
from data_platform.snapshots.ingest import PROVENANCE


SCHEMA = 'sql_landing_delta.v1'
LANDING_TABLES = frozenset(TABLES['training'] + TABLES['abroad'])
LINEAGE_COLUMNS = frozenset(PROVENANCE + [
    'origin_sha256', 'origin_filename', 'origin_sheet', 'origin_row_number', 'record_key',
])


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _table(table):
    if not isinstance(table, dict) or set(table) != {'columns', 'rows'}:
        raise ValueError('landing query result must contain columns and rows')
    columns, rows = table['columns'], table['rows']
    if (not isinstance(columns, list) or not columns or not all(isinstance(c, str) for c in columns)
            or len(set(columns)) != len(columns) or 'source_row_number' not in columns
            or not isinstance(rows, list)
            or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
        raise ValueError('landing query result has invalid columns or rows')
    _bytes(table)
    return columns, rows


def _parts(columns, row):
    business = [value for name, value in zip(columns, row) if name not in LINEAGE_COLUMNS]
    lineage = [value for name, value in zip(columns, row) if name in LINEAGE_COLUMNS]
    return business, lineage


def make_index(old_tables, *, release, warehouse_sha256):
    """Create an identity-bound index without exposing old business values."""
    if set(old_tables) != LANDING_TABLES or not isinstance(release, str) or not release:
        raise ValueError('explicit five-table landing input and release are required')
    if not isinstance(warehouse_sha256, str) or not re.fullmatch('[0-9a-f]{64}', warehouse_sha256):
        raise ValueError('warehouse SHA-256 is required')
    tables = {}
    for name in sorted(LANDING_TABLES):
        columns, rows = _table(old_tables[name])
        counts = Counter(_digest(_parts(columns, row)[0]) for row in rows)
        tables[name] = {'columns': columns, 'old_sha256': _digest(old_tables[name]),
                        'counts': dict(counts), 'row_count': len(rows)}
    return {'schema_version': SCHEMA, 'release': release, 'warehouse_sha256': warehouse_sha256,
            'tables': tables}


def make_delta_from_index(index, new_tables, *, expected_release, expected_warehouse_sha256):
    """Compare a verified cloud index with controlled local query results."""
    if (not isinstance(index, dict) or index.get('schema_version') != SCHEMA
            or index.get('release') != expected_release
            or index.get('warehouse_sha256') != expected_warehouse_sha256
            or set(index.get('tables', {})) != LANDING_TABLES
            or set(new_tables) != LANDING_TABLES):
        raise ValueError('explicit five-table landing input is required')
    deltas = {}
    for name in sorted(LANDING_TABLES):
        prior = index['tables'][name]
        new_columns, new_rows = _table(new_tables[name])
        columns = prior['columns']
        old_counts = Counter(prior['counts'])
        if (sum(old_counts.values()) != prior['row_count']
                or not re.fullmatch('[0-9a-f]{64}', prior['old_sha256'])
                or any(not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key)
                       or type(count) is not int or count <= 0 for key, count in old_counts.items())):
            raise ValueError(f'invalid landing index: {name}')
        if columns != new_columns:
            raise ValueError(f'landing schema changed: {name}')
        new_values, lineage_values = {}, {}
        new_counts = Counter()
        order = []
        for row in new_rows:
            values, lineage = _parts(columns, row)
            key, lineage_key = _digest(values), _digest(lineage)
            if key in new_values and new_values[key] != values:
                raise ValueError('business row digest collision')
            if lineage_key in lineage_values and lineage_values[lineage_key] != lineage:
                raise ValueError('lineage digest collision')
            if key not in old_counts:
                new_values[key] = values
            lineage_values[lineage_key] = lineage
            new_counts[key] += 1
            order.append([key, lineage_key])
        removed = {key: count - new_counts[key] for key, count in old_counts.items()
                   if count > new_counts[key]}
        deltas[name] = {'columns': columns, 'old_sha256': prior['old_sha256'],
                        'new_sha256': _digest(new_tables[name]), 'values': new_values,
                        'lineage': lineage_values, 'order': order, 'removed': removed}
    return {'schema_version': SCHEMA, 'release': index['release'],
            'warehouse_sha256': index['warehouse_sha256'], 'tables': deltas}


def make_delta(old_tables, new_tables):
    """Compare controlled results locally when both copies are already available."""
    index = make_index(old_tables, release='local', warehouse_sha256='0' * 64)
    return make_delta_from_index(index, new_tables, expected_release='local',
                                 expected_warehouse_sha256='0' * 64)


def apply_delta(old_tables, delta, *, expected_release, expected_warehouse_sha256):
    """Reconstruct exact ordered results after checking both content identities."""
    if (set(old_tables) != LANDING_TABLES or not isinstance(delta, dict)
            or delta.get('schema_version') != SCHEMA or set(delta.get('tables', {})) != LANDING_TABLES
            or delta.get('release') != expected_release
            or delta.get('warehouse_sha256') != expected_warehouse_sha256):
        raise ValueError('invalid landing delta identity')
    result = {}
    for name in sorted(LANDING_TABLES):
        columns, old_rows = _table(old_tables[name])
        patch = delta['tables'][name]
        if patch['columns'] != columns or patch['old_sha256'] != _digest(old_tables[name]):
            raise ValueError(f'landing delta baseline mismatch: {name}')
        values = {}
        for row in old_rows:
            business, _ = _parts(columns, row)
            values[_digest(business)] = business
        for key, business in patch['values'].items():
            if _digest(business) != key:
                raise ValueError('landing delta business digest mismatch')
            values[key] = business
        rows = []
        for key, lineage_key in patch['order']:
            business_data = values[key]
            lineage_data = patch['lineage'][lineage_key]
            if _digest(lineage_data) != lineage_key:
                raise ValueError('landing delta lineage digest mismatch')
            if (len(lineage_data) != sum(name in LINEAGE_COLUMNS for name in columns)
                    or len(business_data) + len(lineage_data) != len(columns)):
                raise ValueError('landing delta row width mismatch')
            business = iter(business_data)
            lineage = iter(lineage_data)
            row = [next(lineage) if name in LINEAGE_COLUMNS else next(business) for name in columns]
            rows.append(row)
        table = {'columns': columns, 'rows': rows}
        _table(table)
        if _digest(table) != patch['new_sha256']:
            raise ValueError(f'landing delta result mismatch: {name}')
        result[name] = table
    return result
