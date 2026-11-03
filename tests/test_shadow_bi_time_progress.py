import json
import math
from types import SimpleNamespace

import duckdb
from dashboard_product.shadow_bi.p3.catalog import VIEWS, personal_time_progress
from dashboard_product.shadow_bi.p35.bootstrap_native import configure_window_table, percentage_bar_css
from dashboard_product.shadow_bi.p35.native_catalog import native_views


def test_personal_window_projects_mode_specific_sealed_progress():
    views = {view.key: view for view in VIEWS}
    native = {view.key: view for view in native_views()}
    for page in ['overview', 'virtual', 'prep', 'university']:
        source = views[f'{page}_people']
        window = native[f'native_{page}_people_window']

        assert 'window_progress' in source.sql
        assert "last_day(TRY_CAST(" in source.sql
        assert 'window_end IS NULL THEN 0.0' in source.sql
        assert 'window_progress AS "时间进度"' in source.sql
        assert '时间进度' in window.columns

    formula = personal_time_progress('period_id', 'month_mode', 'window_start', 'window_end')
    assert "month_mode='calendar'" in formula
    assert "period_id||'-25'" in formula
    assert 'date_diff(\'day\'' in formula


def test_personal_window_aggregates_progress_as_numeric_metric():
    native = {view.key: view for view in native_views()}
    expected_metric = {
        'expressionType': 'SQL',
        'sqlExpression': 'MAX("时间进度")',
        'label': '时间进度',
        'hasCustomLabel': True,
        'optionName': 'time_progress',
    }
    for page in ['overview', 'virtual', 'prep', 'university']:
        window = native[f'native_{page}_people_window']
        assert window.more['groupby'] == [column for column in window.columns if column != '时间进度']
        assert window.more['metrics'] == [expected_metric]

    for key in ['native_capacity_month_window', 'native_capacity_annual_window']:
        window = native[key]
        assert window.more['groupby'] == window.columns
        assert window.more['metrics'] == []


def test_operating_windows_expose_existing_period_progress_for_all_five_pages():
    views = {view.key: view for view in VIEWS}
    for page in ['overview', 'virtual', 'prep', 'university', 'online']:
        window = views[f'{page}_window']
        assert {'开始日期', '截止日期', '时间进度'} <= set(window.columns)
        assert 'queries.periods' in window.sql
        period_filter = '线上期间' if page == 'online' else '期间'
        assert period_filter in window.filters


def test_personal_time_progress_sql_counts_inclusive_days_and_month_lengths():
    formula = personal_time_progress('period_id', 'month_mode', 'window_start', 'window_end')
    rows = duckdb.connect(':memory:').execute(f"""
        SELECT case_id, {formula} AS progress
        FROM (VALUES
            ('november-performance', '2026-11', 'performance', '2026-10-26', '2026-10-28'),
            ('october-calendar', '2026-10', 'calendar', '2026-10-01', '2026-10-28'),
            ('october-complete', '2026-10', 'calendar', '2026-10-01', '2026-10-31'),
            ('future', '2026-11', 'calendar', '2026-11-01', NULL),
            ('february-non-leap', '2027-02', 'calendar', '2027-02-01', '2027-02-14'),
            ('february-leap-complete', '2028-02', 'calendar', '2028-02-01', '2028-02-29')
        ) windows(case_id, period_id, month_mode, window_start, window_end)
        ORDER BY case_id
    """).fetchall()
    expected = {
        'november-performance': 3 / 31,
        'october-calendar': 28 / 31,
        'october-complete': 1.0,
        'future': 0.0,
        'february-non-leap': 14 / 28,
        'february-leap-complete': 1.0,
    }

    assert {case_id for case_id, _ in rows} == set(expected)
    for case_id, value in rows:
        assert math.isclose(value, expected[case_id], rel_tol=0, abs_tol=1e-12)


def test_time_progress_column_uses_percent_bars_with_fixed_full_scale():
    params = {}
    configure_window_table(params, ['统计期间', '开始日期', '截止日期', '时间进度', '状态'])

    assert params['column_config']['时间进度'] == {
        'd3NumberFormat': '.1%',
        'showCellBars': True,
    }
    chart = SimpleNamespace(id=42, params=json.dumps(params))
    css = percentage_bar_css({'period-window': chart})
    assert '.dashboard-chart-id-42 tbody td:nth-child(4)' in css
    assert 'clamp(0%, calc(var(--percentage-value) * 100%), 100%)' in css


def test_window_tables_are_compact_and_do_not_paginate():
    # The layout uses a single window row, so paging/search controls are noise.
    params = {}
    configure_window_table(params, ['个人月份', '月模式', '窗口开始', '窗口结束', '时间进度'])

    assert params['server_pagination'] is False
    assert params['include_search'] is False
    assert params['page_length'] == 0
    assert params['column_config']['时间进度']['showCellBars'] is True
