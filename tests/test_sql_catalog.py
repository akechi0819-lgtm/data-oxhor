from __future__ import annotations

import re
import os
import math
from decimal import Decimal
from datetime import date
from pathlib import Path

import pytest

from dashboard_product.shadow_bi.sql_warehouse.catalog import (
    _direct_sql,
    _online_sql,
    build_catalogue,
    catalogue_status,
    render_dataset_sql,
    supported_views,
)


@pytest.fixture
def catalog_integration_paths():
    candidate_env = os.environ.get('SHADOW_BI_CATALOG_WAREHOUSE')
    legacy_env = os.environ.get('SHADOW_BI_CATALOG_LEGACY_WAREHOUSE')
    if not candidate_env and not legacy_env:
        pytest.skip(
            '本地catalog集成对账需同时设置SHADOW_BI_CATALOG_WAREHOUSE和'
            'SHADOW_BI_CATALOG_LEGACY_WAREHOUSE'
        )
    if not candidate_env or not legacy_env:
        pytest.fail(
            'catalog集成对账必须同时设置SHADOW_BI_CATALOG_WAREHOUSE和'
            'SHADOW_BI_CATALOG_LEGACY_WAREHOUSE'
        )

    candidate = Path(candidate_env).expanduser()
    legacy = Path(legacy_env).expanduser()
    if not candidate.is_file():
        pytest.fail(f'显式指定的本地候选库不存在：{candidate}')
    if not legacy.is_file():
        pytest.fail(f'显式指定的本地旧版对照库不存在：{legacy}')
    return candidate, legacy


@pytest.fixture
def minimal_team_target_warehouse():
    duckdb = pytest.importorskip('duckdb')
    con = duckdb.connect(':memory:')
    con.execute('CREATE SCHEMA business')
    con.execute(
        'CREATE TABLE business.team_metrics('
        'period_id VARCHAR,unit_id VARCHAR,business_line VARCHAR,metric VARCHAR,'
        'acquisition_scope VARCHAR,actual DOUBLE,prior DOUBLE,status VARCHAR,'
        'time_progress DOUBLE,target DOUBLE,note VARCHAR)'
    )
    con.execute(
        'CREATE TABLE business.team_values('
        'period_id VARCHAR,unit_id VARCHAR,business_line VARCHAR,'
        'acquisition_scope VARCHAR,comparison VARCHAR,study_heads BIGINT,language_heads BIGINT)'
    )
    con.execute(
        'CREATE TABLE business.team_targets('
        'period_id VARCHAR,unit_id VARCHAR,business_line VARCHAR,metric VARCHAR,target DOUBLE)'
    )

    scopes = ['被动', '主动', '全部']
    units = ['total', 'virtual', 'online', 'overview_high', 'overview_university', 'overview_prep']
    metrics = [('orders', 9284.0), ('cash', 12500.0), ('heads', 8.0)]
    rows = []
    values = []
    for scope in scopes:
        for unit in units:
            values.append(('FY27', unit, 'training', scope, 'actual', 0, 0))
            for metric, total_actual in metrics:
                actual = total_actual if unit == 'total' else total_actual / 10
                rows.append((
                    'FY27', unit, 'training', metric, scope, actual, actual / 2,
                    'available', 0.5, None, ''
                ))
    con.executemany('INSERT INTO business.team_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?)', rows)
    con.executemany('INSERT INTO business.team_values VALUES (?,?,?,?,?,?,?)', values)
    con.execute(
        "INSERT INTO business.team_targets VALUES ('FY27','total','training','orders',20456)"
    )
    con.executemany(
        "INSERT INTO business.team_targets VALUES ('FY27',?,'training','orders',?)",
        [('overview_high', 2000), ('overview_university', 3000), ('overview_prep', 4000)],
    )
    try:
        yield con
    finally:
        con.close()


def _render_sql(sql, filters):
    from jinja2 import Environment

    def filter_values(column, remove_filter=False):
        value=filters.get(column,[])
        return value if isinstance(value,list) else [value]

    def where_in(values):
        return '(' + ', '.join("'"+str(value).replace("'","''")+"'" for value in values) + ')'

    env=Environment(autoescape=False)
    env.globals.update(filter_values=filter_values,columns=[],groupby=[])
    env.filters['where_in']=where_in
    return env.from_string(sql).render()


def _render_acquisition_scope_sql(key, scope, catalogue, unit='市场总计'):
    return _render_sql(catalogue[key].sql,
                       {'语培统计范围': [scope], '管理单元': [unit]})


def test_flat_catalogue_preserves_every_legacy_dataset_contract():
    from dashboard_product.shadow_bi.sql_warehouse.catalog import _metadata

    legacy = _metadata()
    catalogue = build_catalogue()
    assert set(catalogue) == {view.key for view in legacy}
    for view in legacy:
        entry = catalogue[view.key]
        assert entry.columns == tuple(view.columns), view.key
        assert entry.filters == view.filters, view.key
        assert entry.title == view.title, view.key
        assert entry.page == view.page, view.key
        assert entry.section == view.section, view.key
    assert len(catalogue) == 159
    assert catalogue_status(catalogue)['status'] == 'pass'
    assert catalogue_status(catalogue)['unsupported'] == []
    assert len(supported_views(catalogue)) == len(catalogue)


def test_supported_sql_has_no_legacy_storage_or_unrendered_template():
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    catalogue = build_catalogue()
    for key, entry in catalogue.items():
        sql = render_dataset_sql(key, catalogue=catalogue)
        assert 'queries.' not in sql.lower(), key
        assert '{{' not in sql and '{%' not in sql, key
        assert re.search(r'\b(?:FROM|JOIN)\s+(?:business|source|config|expenses)\.',sql,re.I) or 'FROM (' in sql, key


def test_selection_and_acquisition_jinja_render_to_finite_sql():
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    catalogue = build_catalogue()
    prep = render_dataset_sql(
        'prep_lines', {'业务组': ['青少', '高中'], '语培统计范围': ['主动']}, catalogue)
    assert "selection_'||CAST(5 AS VARCHAR)" in prep
    assert "acquisition_scope='主动'" in prep
    online = render_dataset_sql(
        'online_platforms', {'语培统计范围': ['全部']}, catalogue)
    assert "acquisition_scope='全部'" in online
    assert 'business.scoped_advertising_rollup' in online


def test_online_latest_keeps_training_first_when_work_orders_tie():
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    duckdb = pytest.importorskip('duckdb')
    con = duckdb.connect(':memory:')
    con.execute('CREATE SCHEMA business')
    con.execute(
        'CREATE TABLE business.scoped_online_daily('
        'acquisition_scope VARCHAR,period_id VARCHAR,event_date DATE,business_line VARCHAR,'
        'orders BIGINT,cash DECIMAL(24,2),spend DECIMAL(24,2),spend_status VARCHAR,roi DOUBLE)'
    )
    # Reverse insertion order to prove the dataset SQL defines the legacy tie order.
    con.execute(
        "INSERT INTO business.scoped_online_daily VALUES "
        "('被动','2026-10','2026-10-31','abroad',19,80000,4810.25,'available',NULL),"
        "('被动','2026-10','2026-10-31','training',19,113674.20,6960.37,'available',NULL)"
    )
    sql = _render_sql(_online_sql('online_latest'), {'语培统计范围': '被动'})
    rows = con.execute(
        'SELECT "业务线","工单" FROM ('+sql+') AS virtual_table ORDER BY "工单" DESC'
    ).fetchall()
    assert rows == [('语培', 19.0), ('留学及小语种', 19.0)]
    con.close()


def test_activities_are_sorted_by_name_across_paginated_requests():
    duckdb = pytest.importorskip('duckdb')
    con = duckdb.connect(':memory:')
    con.execute('CREATE SCHEMA business')
    con.execute(
        'CREATE TABLE business.activities('
        'activity VARCHAR,training_orders DECIMAL(38,2),abroad_orders DECIMAL(38,2),'
        'orders DECIMAL(38,2),cash DECIMAL(38,2),heads HUGEINT,heads_display VARCHAR,'
        'heads_parts JSON,cash_status VARCHAR)'
    )
    con.execute(
        "INSERT INTO business.activities VALUES "
        "('活动乙',1,0,1,0,0,NULL,'[]','available'),"
        "('#N/A',0,2,2,0,0,NULL,'[]','available'),"
        "('活动甲',1,0,1,0,0,NULL,'[]','available')"
    )
    sql = _direct_sql('activities', 'overview')
    page_one = con.execute(
        'SELECT "活动" FROM ('+sql+') AS virtual_table LIMIT 2'
    ).fetchall()
    page_two = con.execute(
        'SELECT "活动" FROM ('+sql+') AS virtual_table LIMIT 2 OFFSET 2'
    ).fetchall()
    names = [row[0] for row in page_one + page_two]
    assert names == sorted(['活动乙', '#N/A', '活动甲'])
    assert names[0] == '#N/A'
    assert len(names) == len(set(names))
    con.close()


def test_school_parent_grade_sql_keeps_hidden_measures_and_selected_scope():
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    catalogue = build_catalogue()
    filters = {'期间':['FY27'],'管理单元':['市场总计'],'语培统计范围':['被动']}
    base = render_dataset_sql('overview_schools',filters,catalogue)
    for name in ['父工单','子工单','父现金','子现金','父人头','子人头']:
        assert f'AS "{name}"' in base
    assert 'c.grade AS 年级' in base
    assert "['被动']::VARCHAR[]" in base
    assert 'AS 主被动' not in base


def test_native_university_school_sort_keeps_basis_and_direction():
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    catalogue = build_catalogue()
    sql = render_dataset_sql(
        'native_university_schools',
        {'排序依据':['现金占比'],'排序方向':['升序']},
        catalogue,
    )
    assert re.search(r'ORDER BY\s+"现金占比"\s+ASC\s+NULLS LAST',sql)
    assert 'GROUP BY 期间,业务线,学校' in sql


def test_native_school_tree_keeps_rank_only_templates_and_orders_raw_source():
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    catalogue = build_catalogue()
    sql = render_dataset_sql(
        'native_overview_schools',
        {'期间':['2026-11'],'学校主被动':['全部'],'排序依据':['工单'],'排序方向':['降序']},
        catalogue,
    )
    assert "WHEN '被动' THEN 1 WHEN '主动' THEN 2 WHEN '全部' THEN 3" in sql
    assert "WHEN 'abroad' THEN 1 WHEN 'training' THEN 2" in sql
    assert 'p."父工单" DESC NULLS LAST, p.school ASC, c.grade ASC' in sql
    assert '_tree_input_order' not in sql
    assert re.search(r'ORDER BY CASE 年级 .*? END ASC',sql,re.S)
    assert not re.search(r'ORDER BY CASE 年级 .*? END ASC,\s*年级 ASC',sql,re.S)
    assert 'ordered._tree_input_order' not in sql


def test_native_university_channel_tree_uses_typed_children_but_keeps_parent_json():
    catalogue = build_catalogue()
    sql = render_dataset_sql(
        'native_university_channel_tree_training',
        {'期间':['FY27'],'语培统计范围':['被动'],'排序依据':['工单'],'排序方向':['降序']},
        catalogue,
    )
    assert 'business.university_channel_nodes_cache' in sql
    assert sql.count('business.university_channel_nodes_cache') == 2
    assert 'business.scoped_team_periods_channel_cache' in sql
    assert "json_each(b.v, '$.channels')" in sql
    assert "json_each(e.value, '$.groups')" not in sql
    assert "json_each(g.value, '$.schools')" not in sql
    assert "node_kind='group'" in sql
    assert "node_kind='school'" in sql
    assert "acquisition_scope='被动'" in sql
    assert 'period_id IN (\'FY27\')' in sql


def _warehouse_relations(con):
    relations = {
        (schema, name)
        for schema, name in con.execute(
            "SELECT table_schema,table_name FROM information_schema.tables "
            "WHERE table_schema IN ('business','source','config','expenses')"
        ).fetchall()
    }
    relations.update((schema,name) for schema,name in con.execute(
        "SELECT schema_name,function_name FROM duckdb_functions() "
        "WHERE function_type='table_macro' AND schema_name IN ('business','source','config','expenses')"
    ).fetchall())
    return relations


def _missing_relations(sql, available):
    references = set()
    for match in re.finditer(r'\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)', sql, re.I):
        schema, name = match.group(1).split('.', 1)
        if (schema.lower(), name.lower()) not in available:
            references.add(match.group(1))
    return references


def _rows_by_key(con, sql, key_columns):
    cursor = con.execute('SELECT * FROM (' + sql + ') AS catalogue_result')
    columns = [row[0] for row in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    keyed = {tuple(row[column] for column in key_columns): row for row in rows}
    assert len(keyed) == len(rows), 'Comparison keys must uniquely identify every result row'
    return columns, keyed


def _assert_result_rows_equal(legacy_con, candidate_con, legacy_sql, candidate_sql, key_columns):
    old_columns, old_rows = _rows_by_key(legacy_con, legacy_sql, key_columns)
    new_columns, new_rows = _rows_by_key(candidate_con, candidate_sql, key_columns)
    assert new_columns == old_columns
    assert new_rows.keys() == old_rows.keys()
    for key, old_row in old_rows.items():
        new_row = new_rows[key]
        for column in old_columns:
            old_value = old_row[column]
            new_value = new_row[column]
            if old_value is None or new_value is None:
                assert old_value is new_value, (key, column, old_value, new_value)
            elif isinstance(old_value, (int, float, Decimal)) and isinstance(new_value, (int, float, Decimal)):
                assert math.isclose(float(old_value), float(new_value), rel_tol=1e-12, abs_tol=1e-8), (
                    key, column, old_value, new_value)
            else:
                assert old_value == new_value, (key, column, old_value, new_value)
    return old_rows, new_rows


def test_rendered_catalogue_sql_binds_against_readonly_candidate(catalog_integration_paths):
    duckdb = pytest.importorskip('duckdb')
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    warehouse, legacy_warehouse = catalog_integration_paths

    con = duckdb.connect(str(warehouse), read_only=True)
    legacy_con = duckdb.connect(str(legacy_warehouse),read_only=True)
    catalogue = build_catalogue()
    available = _warehouse_relations(con)
    bound = []
    pending = {}
    try:
        for key, entry in catalogue.items():
            contexts=[entry.filters]
            if '语培统计范围' in entry.filters:
                contexts += [{**entry.filters,'语培统计范围':scope} for scope in ['主动','全部']]
            if '产品范围' in entry.filters:
                contexts += [{**entry.filters,'产品范围':product} for product in ['留学','小语种']]
            if '业务组' in entry.filters:
                contexts += [{**entry.filters,'业务组':['高中']}]
            if key=='native_university_schools':
                contexts.append({**entry.filters,'排序依据':['现金占比'],'排序方向':['升序']})
            for context_index,filters in enumerate(contexts):
                sql = render_dataset_sql(key, filters, catalogue)
                missing = _missing_relations(sql, available)
                if missing:
                    pending.setdefault(key,set()).update(missing)
                    continue
                try:
                    con.execute('EXPLAIN SELECT * FROM ('+sql+') AS candidate_catalogue_query').fetchall()
                    if context_index==0:
                        old_sql=_render_sql(entry.contract.sql,entry.filters)
                        old_columns=[row[0] for row in legacy_con.execute(
                            'DESCRIBE SELECT * FROM ('+old_sql+') AS legacy_catalogue_query').fetchall()]
                        new_columns=[row[0] for row in con.execute(
                            'DESCRIBE SELECT * FROM ('+sql+') AS candidate_catalogue_query').fetchall()]
                        assert new_columns==old_columns, f'{key}: expected columns/order {old_columns}, got {new_columns}'
                except Exception as exc:
                    raise AssertionError(f'{key} context {context_index} failed to bind against the read-only candidate: {exc}') from exc
                bound.append((key,context_index))
    finally:
        con.close()
        legacy_con.close()

    assert not pending, f'Catalogue references missing candidate relations/macros: {pending}'
    assert len(bound) >= 159, f'Only {len(bound)} rendered datasets bound'


def test_overview_market_preserves_legacy_total_and_training_order_target(catalog_integration_paths):
    duckdb = pytest.importorskip('duckdb')
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    warehouse, legacy_warehouse = catalog_integration_paths

    candidate_con = duckdb.connect(str(warehouse), read_only=True)
    legacy_con = duckdb.connect(str(legacy_warehouse),read_only=True)
    catalogue = build_catalogue()
    # _metadata supplies the original SQL contract while the candidate catalogue
    # supplies the flat SQL implementation.
    from dashboard_product.shadow_bi.sql_warehouse.catalog import _metadata
    legacy_contracts = {view.key: view for view in _metadata()}
    expected_units = {'市场总计'}
    try:
        market_rows = {}
        for scope in ['被动', '主动', '全部']:
            filters = {**legacy_contracts['overview_market'].filters, '语培统计范围': scope}
            old_sql = _render_sql(legacy_contracts['overview_market'].sql, filters)
            old_sql = "SELECT * FROM (" + old_sql + ") old_total WHERE 管理单元='市场总计'"
            new_sql = render_dataset_sql('overview_market', filters, catalogue)
            _, old_rows = _assert_result_rows_equal(
                legacy_con, candidate_con, old_sql, new_sql,
                ['期间', '管理单元', '语培统计范围'])
            assert len(old_rows) == 17
            assert {key[1] for key in old_rows} == expected_units
            assert len({key[0] for key in old_rows}) == 17
            market_rows[scope] = old_rows

        passive_fy27 = market_rows['被动'][('FY27', '市场总计', '被动')]
        assert passive_fy27['目标'] == 20456
        assert passive_fy27['完成率'] == pytest.approx(0.45380328509972623)
        assert passive_fy27['目标配置'] == '已配置'
        assert passive_fy27['口径'] == (
            '语培被动工单按观远8类原始团队白名单统计，排除空团队；包含删除/回收，'
            '按工单ID去重。个人业绩剔除删除/回收。')
        assert market_rows['主动'][('FY27', '市场总计', '主动')]['目标'] is None
        assert market_rows['全部'][('FY27', '市场总计', '全部')]['目标'] is None

        for scope in ['被动', '主动', '全部']:
            filters = {**legacy_contracts['native_overview_training'].filters, '语培统计范围': scope}
            old_sql = _render_sql(legacy_contracts['native_overview_training'].sql, filters)
            old_sql = "SELECT * FROM (" + old_sql + ") old_total WHERE 管理单元='市场总计'"
            new_sql = render_dataset_sql('native_overview_training', filters, catalogue)
            _, old_rows = _assert_result_rows_equal(
                legacy_con, candidate_con, old_sql, new_sql,
                ['期间', '管理单元', '语培统计范围', '指标'])
            assert len(old_rows) == 51
            assert len({key[0] for key in old_rows}) == 17
            assert {key[1] for key in old_rows} == expected_units

        native_passive_fy27 = _rows_by_key(
            candidate_con,
            render_dataset_sql('native_overview_training',
                               {**legacy_contracts['native_overview_training'].filters,
                                '语培统计范围': '被动'}, catalogue),
            ['期间', '管理单元', '语培统计范围', '指标'])[1]
        assert native_passive_fy27[('FY27', '市场总计', '被动', '工单')]['目标与完成率'] == '20,456 · 45.4%'
    finally:
        candidate_con.close()
        legacy_con.close()


def test_overview_market_uses_selected_group_targets_and_preserves_acquisition_scopes(
        minimal_team_target_warehouse):
    con = minimal_team_target_warehouse
    catalogue = build_catalogue()

    for scope, unit in [(scope, unit) for scope in ['被动', '主动', '全部']
                        for unit in ['市场总计', '高中', '大学', '留学预备']]:
        market_sql = _render_acquisition_scope_sql('overview_market', scope, catalogue, unit)
        _, market_rows = _rows_by_key(
            con, market_sql, ['期间', '管理单元', '语培统计范围']
        )
        assert len(market_rows) == 1
        total = market_rows[('FY27', unit, scope)]
        actual = 9284 if unit == '市场总计' else 928.4
        target = {'市场总计': 20456, '高中': 2000, '大学': 3000, '留学预备': 4000}[unit]
        assert total['当期'] == pytest.approx(actual)
        if scope == '被动':
            assert total['目标'] == target
            assert total['完成率'] == pytest.approx(actual / target)
            assert total['目标配置'] == '已配置'
        else:
            assert total['目标'] is None
            assert total['完成率'] is None
            assert total['目标配置'] == '未配置'

        native_sql = _render_acquisition_scope_sql(
            'native_overview_training', scope, catalogue, unit
        )
        _, native_rows = _rows_by_key(
            con, native_sql, ['期间', '管理单元', '语培统计范围', '指标']
        )
        assert {row[1] for row in native_rows} == {unit}
        total_orders = native_rows[('FY27', unit, scope, '工单')]
        if scope == '被动':
            assert total_orders['目标与完成率'] == f'{target:,.0f} · {actual / target:.1%}'
        else:
            assert total_orders['目标与完成率'] == '—'


def test_people_targets_keep_legacy_double_types_from_decimal_storage():
    duckdb = pytest.importorskip('duckdb')
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    from dashboard_product.shadow_bi.sql_warehouse.catalog import _people_sql

    with duckdb.connect(':memory:') as con:
        con.execute('CREATE SCHEMA config')
        con.execute('CREATE SCHEMA business')
        con.execute(
            'CREATE TABLE config.people('
            'name VARCHAR,home_group VARCHAR,business_line VARCHAR,selection_group VARCHAR,'
            'team_ids VARCHAR[],training_roster BOOLEAN)'
        )
        con.execute(
            "INSERT INTO config.people VALUES ('甲','青少','training','青少',[],TRUE)"
        )
        con.execute(
            'CREATE TABLE business.personal_metrics('
            'period_id VARCHAR,month_mode VARCHAR,state VARCHAR,name VARCHAR,business_line VARCHAR,metric VARCHAR,'
            'actual DECIMAL(24,2),target DECIMAL(24,2),status VARCHAR,start_date DATE,through_date DATE,'
            'end_date DATE,time_progress DOUBLE,coverage_status VARCHAR,heads_display VARCHAR)'
        )
        con.executemany(
            'INSERT INTO business.personal_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            [
                ('2026-11','performance','00','甲','training','orders',12,50,'available',
                 date(2026,11,1),date(2026,11,30),date(2026,11,30),1.0,'available',None),
                ('2026-11','performance','00','甲','training','cash',64000,80000,'available',
                 date(2026,11,1),date(2026,11,30),date(2026,11,30),1.0,'available',None),
                ('2026-11','performance','00','甲','training','heads',4,None,'available',
                 date(2026,11,1),date(2026,11,30),date(2026,11,30),1.0,'available',None),
            ],
        )
        sql = _render_sql(
            _people_sql('overview'),
            {'月模式':['绩效月'],'个人月份':['2026-11'],'含删除回收':['不含'],'含死单':['不含']},
        )
        cursor = con.execute(sql)
        columns = [item[0] for item in cursor.description]
        row = dict(zip(columns, cursor.fetchone()))
        types = {item[0]: item[1] for item in con.execute('DESCRIBE SELECT * FROM ('+sql+') person_view').fetchall()}

    assert types['语培目标'] == 'DOUBLE'
    assert types['现金目标'] == 'DOUBLE'
    assert type(row['语培目标']) is float and row['语培目标'] == 50.0
    assert type(row['现金目标']) is float and row['现金目标'] == 80000.0


def test_online_platform_and_activity_outputs_keep_legacy_integer_and_cash_types():
    duckdb = pytest.importorskip('duckdb')
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    with duckdb.connect(':memory:') as con:
        con.execute('CREATE SCHEMA business')
        con.execute('CREATE SCHEMA config')
        con.execute('CREATE SCHEMA expenses')
        con.execute(
            'CREATE TABLE business.scoped_advertising_rollup('
            'period_id VARCHAR,acquisition_scope VARCHAR,record_type VARCHAR,business_line VARCHAR,'
            'platform VARCHAR,business_group VARCHAR,orders DECIMAL(38,2),prior_orders DECIMAL(38,2),'
            'today_orders DECIMAL(38,2),cash DECIMAL(38,2),prior_cash DECIMAL(38,2),spend DECIMAL(38,2),'
            'spend_status VARCHAR,roi DOUBLE,cost_per_order DOUBLE,roi_cash DECIMAL(38,2),'
            'roi_spend DECIMAL(38,2),roi_orders DECIMAL(38,2),roi_start_date DATE,roi_through_date DATE)'
        )
        con.execute(
            "INSERT INTO business.scoped_advertising_rollup VALUES "
            "('2026-11','被动','platform','training','平台甲',NULL,1,2,1,1234.56,500,100,'complete',12.3,100,1000,100,1,'2026-11-01','2026-11-06')"
        )
        con.execute(
            'CREATE TABLE business.periods(period_id VARCHAR,kind VARCHAR,through_date DATE)'
        )
        con.execute("INSERT INTO business.periods VALUES ('2026-11','month','2026-11-06')")
        con.execute('CREATE TABLE config.clock(through_date DATE)')
        con.execute("INSERT INTO config.clock VALUES ('2026-11-06')")
        con.execute(
            'CREATE TABLE expenses.expense_sources('
            'business_line VARCHAR,platform VARCHAR,business_group VARCHAR,start_date DATE,end_date DATE,'
            'missing_amount_count BIGINT,summary_json VARCHAR,grain VARCHAR)'
        )

        online_sql = _render_sql(_online_sql('online_platforms'), {'语培统计范围':['被动']})
        online_cursor = con.execute(online_sql)
        online_columns = [item[0] for item in online_cursor.description]
        online_row = dict(zip(online_columns, online_cursor.fetchone()))
        online_types = {item[0]:item[1] for item in con.execute(
            'DESCRIBE SELECT * FROM ('+online_sql+') online_result').fetchall()}
        assert online_types['工单'] == 'BIGINT'
        assert online_types['截止日新增'] == 'BIGINT'
        assert online_types['现金'] == 'DECIMAL(24,2)'
        assert type(online_row['工单']) is int and online_row['工单'] == 1
        assert type(online_row['截止日新增']) is int and online_row['截止日新增'] == 1
        assert online_row['现金'] == Decimal('1234.56')

        con.execute(
            'CREATE TABLE business.activities('
            'activity VARCHAR,training_orders DECIMAL(38,2),abroad_orders DECIMAL(38,2),'
            'orders DECIMAL(38,2),cash DECIMAL(38,2),heads HUGEINT,heads_display VARCHAR,'
            'heads_parts JSON,cash_status VARCHAR)'
        )
        con.execute(
            "INSERT INTO business.activities VALUES ('活动甲',1,2,3,1234.56,4,'4人','{}','available')"
        )
        activities_sql = _direct_sql('activities','overview')
        activities_cursor = con.execute(activities_sql)
        activities_columns = [item[0] for item in activities_cursor.description]
        activities_row = dict(zip(activities_columns, activities_cursor.fetchone()))
        activities_types = {item[0]:item[1] for item in con.execute(
            'DESCRIBE SELECT * FROM ('+activities_sql+') activities_result').fetchall()}
        for column in ['语培工单','留学工单','合计工单','人头']:
            assert activities_types[column] == 'BIGINT'
            assert type(activities_row[column]) is int
        assert activities_types['现金'] == 'DECIMAL(24,2)'
        assert activities_row['现金'] == Decimal('1234.56')


def test_daily_aggregate_exports_keep_legacy_order_for_equal_values():
    duckdb = pytest.importorskip('duckdb')
    pytest.importorskip('jinja2')
    from dashboard_product.shadow_bi.sql_warehouse.catalog import _metadata
    legacy = next(v.sql for v in _metadata() if v.key == 'online_daily')
    with duckdb.connect(':memory:') as con:
        con.execute('SET threads=1')
        con.execute('CREATE SCHEMA queries')
        con.execute('CREATE SCHEMA business')
        metrics = ['orders', 'cash', 'spend', 'roi']
        fields = [f'{line}_{metric} DOUBLE' for line in ['training', 'abroad'] for metric in metrics]
        fields += [f'{line}_spend_status VARCHAR' for line in ['training', 'abroad']]
        con.execute('CREATE TABLE queries.online_daily(period_id VARCHAR,date DATE,'+','.join(fields)+')')
        con.executemany('INSERT INTO queries.online_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', [
            ['2026-10', f'2026-10-0{i}', 3, 20, None, None, 3, 20, None, None, 'missing', 'missing']
            for i in range(1, 5)])
        old_sql = _render_sql(legacy, {})
        con.execute("CREATE TABLE business.scoped_online_daily AS SELECT 线上期间 AS period_id,日期 AS event_date,"
                    "CASE 业务线 WHEN '语培' THEN 'training' ELSE 'abroad' END AS business_line,"
                    "工单 AS orders,现金 AS cash,花费 AS spend,回收倍数 AS roi,'missing' AS spend_status,'被动' AS acquisition_scope "
                    "FROM ("+old_sql+") ORDER BY 日期 DESC,业务线")
        new_sql = _render_sql(_online_sql('online_daily'), {'语培统计范围':['被动']})
        for metric in ['工单', '现金']:
            export = lambda sql: ('SELECT 日期,业务线,SUM("'+metric+'") AS total FROM ('+sql+
                                  ') daily GROUP BY 日期,业务线 ORDER BY total DESC LIMIT 1000000')
            assert con.execute(export(new_sql)).fetchall() == con.execute(export(old_sql)).fetchall()
