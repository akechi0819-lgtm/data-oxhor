from datetime import date

import duckdb
import pytest

from dashboard_product.shadow_bi.p5.release_guard import compare_releases
from dashboard_product.shadow_bi.sql_warehouse.foundation import TABLES


def _warehouse(path, *, orders=200, negative=0, row_count=4):
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA business; CREATE SCHEMA config; CREATE SCHEMA landing")
        con.execute("CREATE TABLE config.clock AS SELECT DATE '2026-06-01' AS abroad_start, "
                    "DATE '2026-11-27' AS abroad_through")
        con.execute("CREATE TABLE business.periods AS SELECT 'FY27' AS period_id, "
                    "DATE '2026-06-01' AS start_date")
        con.execute("""
            CREATE TABLE business.scoped_facts (
                unit_id VARCHAR, acquisition_scope VARCHAR, business_line VARCHAR,
                event_date DATE, metric VARCHAR, value DECIMAL(18,2), student_id VARCHAR,
                class_code VARCHAR, registration_count INTEGER, customer_domain VARCHAR
            )
        """)
        con.execute("""
            INSERT INTO business.scoped_facts VALUES
                ('total','全部','training','2026-11-23','orders',?,NULL,NULL,0,NULL),
                ('total','全部','training','2026-11-23','cash',2000,'1','a',1,NULL),
                ('total','全部','training','2026-11-23','cash',?,'2','b',0,NULL),
                ('total','全部','training','2026-11-27','orders',999,NULL,NULL,0,NULL),
                ('total','全部','abroad','2026-11-23','cash',1200,'1',NULL,0,'study_abroad'),
                ('total','全部','abroad','2026-11-23','cash',1800,'1',NULL,0,'small_language')
        """, [orders, negative])
        for table, name in zip(TABLES['training'], ('分配时间', '业务日期'), strict=True):
            con.execute(f'CREATE TABLE landing.{table} AS SELECT '
                        f"date_diff('day', DATE '1899-12-30', DATE '2026-11-23') AS \"{name}\" "
                        'FROM range(?)', [row_count])
        for table in TABLES['abroad']:
            con.execute(f"CREATE TABLE landing.{table} AS SELECT DATE '2026-11-23' AS event_date")


@pytest.mark.parametrize('changes,through,block,warning', [
    ({'orders': 215}, '2026-11-25', None, None),
    ({'orders': 189}, '2026-11-26', 'training.orders:retraction', None),
    ({'row_count': 2}, '2026-11-26', f"{TABLES['training'][0]}:row_loss", None),
    ({'row_count': 0}, '2026-11-26', f"{TABLES['training'][0]}:empty", None),
    ({'negative': -350}, '2026-11-26', 'training.cash:retraction', None),
    ({'negative': -100}, '2026-11-26', None, 'training.cash:negative_cash_retraction'),
    ({}, '2026-11-24', 'coverage_regressed', None),
])
def test_release_compares_the_same_history_and_reports_blocks(tmp_path, changes, through, block, warning):
    baseline, candidate = tmp_path / 'old.duckdb', tmp_path / 'new.duckdb'
    _warehouse(baseline)
    _warehouse(candidate, **changes)
    report = compare_releases(baseline=baseline, candidate=candidate,
                              baseline_through='2026-11-25', candidate_through=through)
    assert report['common_through'] == min(through, '2026-11-25')
    assert report['metrics']['training.orders']['before'] == '200.00'
    assert report['metrics']['training.heads']['after'] == '1'
    assert report['metrics']['study_abroad.heads']['after'] == '1'
    assert report['metrics']['small_language.heads']['after'] == '1'
    if block:
        assert block in report['blocks'] and report['status'] == 'blocked'
    else:
        assert report['blocks'] == []
    if warning:
        assert warning in report['warnings']
        assert report['metrics']['training.cash']['negative_cash_rows'] == 1


def test_zero_comparison_baseline_has_no_ratio(tmp_path):
    baseline, candidate = tmp_path / 'old.duckdb', tmp_path / 'new.duckdb'
    _warehouse(baseline, orders=0)
    _warehouse(candidate, orders=5)
    report = compare_releases(baseline=baseline, candidate=candidate,
                              baseline_through='2026-11-25', candidate_through='2026-11-25')
    assert report['blocks'] == []
    assert 'training.orders:zero_comparison_baseline' in report['warnings']
    assert report['metrics']['training.orders']['ratio'] is None
