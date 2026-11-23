from pathlib import Path

import duckdb


def test_personal_student_selection_keeps_orders_and_unlabelled_only_in_all():
    con = duckdb.connect(':memory:')
    con.execute('CREATE SCHEMA business')
    con.execute("""CREATE TABLE business.personal_windows AS SELECT
        '2026-11' AS period_id, 'calendar' AS month_mode,
        DATE '2026-11-01' AS start_date, DATE '2026-11-11' AS through_date""")
    con.execute("""CREATE TABLE business.personal_allocations (
        business_line VARCHAR, metric VARCHAR, student_type VARCHAR,
        event_date DATE, order_status VARCHAR, counts_toward_completion BOOLEAN,
        value DOUBLE)""")
    con.executemany('INSERT INTO business.personal_allocations VALUES (?,?,?,?,?,?,?)', [
        ('training', 'cash', '新生', '2026-11-11', None, True, 2000),
        ('training', 'cash', '老生', '2026-11-11', None, True, 3000),
        ('training', 'cash', None, '2026-11-11', None, True, 100),
        ('training', 'orders', None, '2026-11-11', '正常', True, 1),
        ('abroad', 'cash', None, '2026-11-11', None, True, 500),
    ])
    sql = Path('dashboard_product/shadow_bi/sql_warehouse/sql/personal.sql').read_text()
    con.execute(sql[sql.index('CREATE OR REPLACE VIEW business.personal_states'):sql.index('CREATE OR REPLACE VIEW business.personal_values')])
    rows = con.execute("""SELECT state,business_line,metric,SUM(value)
        FROM business.personal_events WHERE comparison='actual'
        AND state IN ('01','01|新生','01|老生') GROUP BY ALL""").fetchall()
    values = {(state, line, metric): amount for state, line, metric, amount in rows}
    assert values['01', 'training', 'cash'] == 5100
    assert values['01|新生', 'training', 'cash'] == 2000
    assert values['01|老生', 'training', 'cash'] == 3000
    for state in ('01', '01|新生', '01|老生'):
        assert values[state, 'training', 'orders'] == 1
        assert values[state, 'abroad', 'cash'] == 500
    con.close()
