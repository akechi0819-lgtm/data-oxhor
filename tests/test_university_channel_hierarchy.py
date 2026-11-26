from datetime import date
import re

from dashboard_product.shadow_bi.p3 import catalog
from dashboard_product.shadow_bi.p35.breakdown_views import build


def test_university_channel_html_projects_school_leaves_from_existing_json():
    base = {view.key: view for view in catalog.VIEWS}
    view = next(item for item in build(base, [])
                if item.key == 'native_university_channel_tree')

    assert view.title == '渠道 · 展开学校属性与学校'
    assert "json_each(b.v, '$.channels') e" in view.sql
    assert "json_each(e.value, '$.groups') g" in view.sql
    assert "json_each(g.value, '$.schools') s" in view.sql
    assert 'AS "学校名称"' in view.sql
    assert 's."现金"' in view.sql
    assert 's.渠道内现金占比' in view.sql
    assert 'g.渠道内现金占比' in view.sql
    assert "ORDER BY CASE g.业务组名称 WHEN '大学*' THEN 1 WHEN '本地大学' THEN 2 WHEN '归巢大学' THEN 3 WHEN '国外大学' THEN 4 WHEN '毕业及其他' THEN 5 ELSE 6 END" in view.sql
    assert "'<details><summary>'" in view.sql
    assert 'FROM groups g WHERE' in view.sql
    assert 'FROM schools s WHERE' in view.sql


def test_university_period_selection_precedes_all_three_json_expansions():
    import pytest
    Environment = pytest.importorskip('jinja2', reason='模板渲染测试使用 Superset 运行时的 Jinja2').Environment

    base = {view.key: view for view in catalog.VIEWS}
    university = next(item for item in build(base, [])
                      if item.key == 'native_university_channel_tree')
    prep = next(item for item in build(base, [])
                if item.key == 'native_prep_channel_tree')

    def render(view, selected_periods):
        env = Environment()
        env.filters['where_in'] = lambda values: '(' + ', '.join(
            "'" + str(value).replace("'", "''") + "'" for value in values
        ) + ')'
        return env.from_string(view.sql).render(
            filter_values=lambda name, **_: selected_periods if name == '期间' else [],
        )

    rendered = render(university, ['2026-10'])
    period_filters = [m.start() for m in re.finditer(
        r"WHERE team_id='university'\s+AND period_id IN \('2026-10'\)", rendered,
    )]
    expansions = [m.start() for m in re.finditer(
        r"json_each\(b\.v, '\$\.channels'\) e", rendered,
    )]
    assert len(period_filters) == len(expansions) == 3
    assert all(period < expansion for period, expansion in zip(period_filters, expansions))

    empty_periods = render(university, [])
    assert "period_id IN" not in empty_periods
    assert empty_periods.count("WHERE team_id='university'") == 3

    rendered_prep = render(prep, ['2026-10'])
    assert prep.title == '渠道 · 展开业务组'
    assert 'period_id IN' not in rendered_prep
    assert "json_each(g.value, '$.schools') s" not in rendered_prep
