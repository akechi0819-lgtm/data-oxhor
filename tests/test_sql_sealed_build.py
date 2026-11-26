import duckdb
import pytest

from dashboard_product.shadow_bi.sql_warehouse.build import _replace_sealed_rows


def test_delta_replaces_only_isolated_table_with_same_schema():
    con = duckdb.connect()
    con.execute('CREATE SCHEMA landing')
    con.execute('CREATE TABLE landing.source (source_row_number BIGINT, name VARCHAR, amount DECIMAL(10,2))')
    con.execute("INSERT INTO landing.source VALUES (1, 'old', 10)")
    _replace_sealed_rows(con, 'landing', 'source', {
        'columns': ['source_row_number', 'name', 'amount'],
        'rows': [[2, 'new', '12.34'], [3, None, '0.00']],
    })
    assert con.execute('SELECT source_row_number,name,amount::VARCHAR FROM landing.source ORDER BY 1').fetchall() == [
        (2, 'new', '12.34'), (3, None, '0.00'),
    ]


def test_delta_rejects_changed_schema_without_removing_source_rows():
    con = duckdb.connect()
    con.execute('CREATE SCHEMA landing')
    con.execute('CREATE TABLE landing.source (source_row_number BIGINT, name VARCHAR)')
    con.execute("INSERT INTO landing.source VALUES (1, 'old')")
    with pytest.raises(ValueError, match='表结构'):
        _replace_sealed_rows(con, 'landing', 'source', {
            'columns': ['name', 'source_row_number'], 'rows': [['new', 2]],
        })
    assert con.execute('SELECT * FROM landing.source').fetchall() == [(1, 'old')]
