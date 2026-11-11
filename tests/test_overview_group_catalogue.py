from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dashboard_product.shadow_bi.p5.sql_bundle import OPTION_SQL
from dashboard_product.shadow_bi.sql_warehouse.catalog import build_catalogue, render_dataset_sql
from dashboard_product.shadow_bi.sql_warehouse.native_channel_cache import ORDINARY_UNITS, UNITS


GROUPS = {
    '市场总计': 'total',
    '高中': 'overview_high',
    '大学': 'overview_university',
    '留学预备': 'overview_prep',
}
ACQUISITION_SCOPES = ('被动', '主动', '全部')


@pytest.fixture(scope='module')
def catalogue():
    pytest.importorskip('jinja2', reason='Jinja2随Superset运行时提供')
    return build_catalogue()


def test_overview_group_sql_renders_each_selection_and_acquisition_scope(catalogue):
    keys = (
        'overview_market', 'overview_lines', 'overview_groups', 'overview_channels',
        'overview_schools', 'overview_grades', 'overview_targets', 'overview_people',
        'native_overview_grades', 'native_overview_channel_tree', 'native_overview_schools',
    )
    for label, unit_id in GROUPS.items():
        for acquisition in ACQUISITION_SCOPES:
            rendered = {
                key: render_dataset_sql(
                    key,
                    {**catalogue[key].filters, '管理单元': label, '语培统计范围': acquisition},
                    catalogue,
                )
                for key in keys
            }
            for key, sql in rendered.items():
                assert '{{' not in sql and '{%' not in sql, (key, label, acquisition)
                if key not in ('overview_people', 'overview_targets'):
                    assert "'" + acquisition + "'" in sql, (key, label, acquisition)

            assert f"tm.unit_id='{unit_id}'" in rendered['overview_market']
            assert f"t.unit_id='{unit_id}'" in rendered['overview_lines']
            assert "t.business_line='abroad' AND t.unit_id='total'" in rendered['overview_lines']
            assert f"d.unit_id='{unit_id}'" in rendered['overview_groups']
            assert f"d.unit_id='{unit_id}'" in rendered['overview_targets']
            assert "d.business_line='abroad' AND d.unit_id='total'" in rendered['overview_channels']
            assert "d.business_line='abroad' AND d.unit_id='total'" in rendered['overview_grades']
            assert "d.business_line='abroad' AND d.unit_id='total'" in rendered['overview_schools']
            if label == '市场总计':
                assert "SELECT p.*,'total' AS selected_unit FROM config.people p" in rendered['overview_people']
                assert "list_contains(p.team_ids,'online_private')" not in rendered['overview_people']
            else:
                assert f"p.home_group='{label}'" in rendered['overview_people']
                assert "p.business_line='abroad'" in rendered['overview_people']
            assert f"team_id IN ('{unit_id}','total')" in rendered['native_overview_grades']
            assert f"team_id IN ('{unit_id}','total')" in rendered['native_overview_channel_tree']


def test_pure_abroad_overview_sql_keeps_total_scope(catalogue):
    for label in GROUPS:
        for key in (
            'overview_abroad_targets', 'overview_supplemental',
            'overview_countries', 'overview_countries_child',
        ):
            sql = render_dataset_sql(
                key,
                {**catalogue[key].filters, '管理单元': label, '语培统计范围': '全部'},
                catalogue,
            )
            assert "'市场总计' AS 管理单元" in sql, (key, label)
        abroad_targets = render_dataset_sql(
            'overview_abroad_targets',
            {**catalogue['overview_abroad_targets'].filters, '管理单元': label},
            catalogue,
        )
        assert "tm.unit_id IN ('online','university')" in abroad_targets
        countries = render_dataset_sql(
            'overview_countries',
            {**catalogue['overview_countries'].filters, '管理单元': label},
            catalogue,
        )
        assert "d.unit_id='total'" in countries


def test_native_abroad_grade_and_channel_sql_ignore_all_four_overview_groups(catalogue):
    keys = ('native_overview_grades_abroad', 'native_overview_channel_tree_abroad')
    for key in keys:
        rendered_by_group = {}
        for label in GROUPS:
            rendered = render_dataset_sql(
                key,
                {**catalogue[key].filters, '管理单元': label, '语培统计范围': '主动'},
                catalogue,
            )
            assert '{{' not in rendered and '{%' not in rendered, (key, label)
            assert "'市场总计' AS 管理单元" in rendered, (key, label)
            assert "team_id IN ('total','total')" in rendered, (key, label)
            assert "'overview_high'" not in rendered, (key, label)
            assert "'overview_university'" not in rendered, (key, label)
            assert "'overview_prep'" not in rendered, (key, label)
            rendered_by_group[label] = rendered
        assert len(set(rendered_by_group.values())) == 1, (key, rendered_by_group.keys())


def test_overview_options_are_exactly_four_groups_and_channel_cache_keeps_old_units():
    duckdb = pytest.importorskip('duckdb')
    con = duckdb.connect(':memory:')
    try:
        values = {row[0] for row in con.execute(OPTION_SQL['p35_overview_options_1']).fetchall()}
    finally:
        con.close()
    assert values == set(GROUPS)
    assert len(values) == 4
    assert {'total', 'prep', 'high', 'university', 'virtual', 'online'} <= set(UNITS)
    assert all(unit in ORDINARY_UNITS for unit in ('overview_prep', 'overview_high', 'overview_university'))


def test_dimension_query_returns_each_new_overview_group():
    pytest.importorskip('duckdb')
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from test_sql_dimensions import DimensionSqlTests
    finally:
        sys.path.pop(0)

    case = DimensionSqlTests()
    case.setUp()
    try:
        groups = (
            ('overview_prep', '留学预备', '青少'),
            ('overview_high', '高中', '高中'),
            ('overview_university', '大学', '大学'),
        )
        for unit_id, group, comparison_group in groups:
            case.con.execute(
                'INSERT INTO business.scopes VALUES (?, NULL, ?, NULL, NULL)',
                [unit_id, group],
            )
            case._event(
                unit=unit_id, business_group=group, comparison_group=comparison_group,
                metric='cash', value=1500, student=unit_id, course='C1', registration=1,
                school='学校'+group, grade='五年级',
            )
            case._event(
                unit=unit_id, business_group=group, comparison_group=comparison_group,
                metric='orders', value=1, student=unit_id, school='学校'+group,
                grade='五年级',
            )
            missing_target_teams = {
                '留学预备': (),
                '高中': ('offline_market', 'online_private', 'online_platform'),
                '大学': ('online_private', 'online_platform'),
            }[group]
            if missing_target_teams:
                case.con.executemany(
                    'INSERT INTO config.targets VALUES (?, ?, ?, ?, ?, ?)',
                    [('training', group, team, '2026-06', 'orders', 20)
                     for team in missing_target_teams],
                )

        for unit_id, group, _ in groups:
            rows = case.con.execute(
                "SELECT dimension_type,dim1,metric,actual,target FROM business.dimension_query("
                "['2026-06']::VARCHAR[],[?]::VARCHAR[],['被动']::VARCHAR[],"
                "['business_group','school','school_grade','grade']::VARCHAR[]) "
                "WHERE unit_id=? AND business_line='training'",
                [unit_id, unit_id],
            ).fetchall()
            group_orders = [row for row in rows if row[0] == 'business_group' and row[1] == group and row[2] == 'orders']
            assert group_orders and group_orders[0][3] == 1, (unit_id, rows)
            expected_target = {'overview_prep': 60, 'overview_high': 60, 'overview_university': 80}[unit_id]
            assert group_orders[0][4] == expected_target, (unit_id, rows)
            assert any(row[0] == 'school' and row[1] == '学校'+group for row in rows)
    finally:
        case.tearDown()
