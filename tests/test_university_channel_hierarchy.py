from datetime import date
import re

from dashboard_product.management.breakdowns import _channels
from dashboard_product.shadow_bi.p3 import catalog
from dashboard_product.shadow_bi.p35.breakdown_views import build


def _period():
    return {
        'status': 'available',
        'start_date': '2026-09-01',
        'through_date': '2026-09-30',
        'time_progress': 1.0,
        'abroad_source': {
            'start_date': '2026-09-01',
            'through_date': '2026-09-30',
            'no_yoy': True,
        },
    }


def _training_fact(name, attribute, student, metric, value, *, raw_name=None, group='大学'):
    return {
        'fact_id': f'{name}-{metric}',
        'event_date': date(2026, 9, 10),
        'business_line': 'training',
        'business_group': group,
        'comparison_group': '青少' if group == '留学预备' else group,
        'team_id': 'offline_market',
        'metric': metric,
        'value': value,
        'first_channel': '线下',
        'second_channel': '校代',
        'school_name': raw_name or name,
        'channel_school_name': name,
        'school_attribute': attribute,
        'student_id': student,
        'class_code': 'fixture-class',
        'registration_count': 1,
    }


def test_university_channels_group_by_normalized_school_and_keep_parent_heads_deduped():
    facts = []
    # The same student appears at two universities. School leaf headcounts must
    # each be measured independently; their sum must not replace parent dedupe.
    for school, raw, orders, cash in [
        ('天津师范大学', '天津师范大学-八里台校区', 1, 1500),
        ('其他学校', '其他学校', 2, 3000),
    ]:
        facts.append(_training_fact(school, '大学*', 'same-student', 'orders', orders, raw_name=raw))
        facts.append(_training_fact(school, '大学*', 'same-student', 'cash', cash, raw_name=raw))
    for school, attribute, student in [
        ('本地学校', '本地大学', 'local-student'),
        ('归巢学校', '归巢大学', 'return-student'),
        ('国外学校', '国外大学', 'foreign-student'),
        ('缺少映射', '其他值', 'unmatched-student'),
    ]:
        facts.append(_training_fact(school, attribute, student, 'orders', 1))
        facts.append(_training_fact(school, attribute, student, 'cash', 1500))
    facts.append(_training_fact('其他渠道学校', '大学*', 'other-channel-student', 'orders', 3))
    facts[-1].update(first_channel='线上', second_channel='活动')
    facts.append(_training_fact('其他渠道学校', '大学*', 'other-channel-student', 'cash', 3000))
    facts[-1].update(first_channel='线上', second_channel='活动')
    facts.append({
        'fact_id': 'abroad-order',
        'event_date': date(2026, 9, 10),
        'business_line': 'abroad',
        'business_group': '大学',
        'team_id': 'offline_market',
        'segment_id': 'study_abroad_offline',
        'source_product': 'study_abroad',
        'customer_domain': 'study_abroad',
        'metric': 'orders',
        'value': 1,
        'first_channel': '线下',
        'second_channel': '讲座',
    })

    channels = _channels(facts, {'id': 'university'}, _period())
    training = next(row for row in channels if row['business_line'] == 'training')
    group = next(row for row in training['groups'] if row['name'] == '大学*')

    assert [row['name'] for row in training['groups']] == [
        '大学*', '本地大学', '归巢大学', '国外大学', '毕业及其他',
    ]
    assert training['orders']['actual'] == 7
    assert training['cash']['actual'] == 10500
    assert sum(row['orders']['actual'] for row in training['groups']) == training['orders']['actual']
    assert sum(row['cash']['actual'] for row in training['groups']) == training['cash']['actual']
    assert training['heads']['actual'] == 5
    assert (group['orders']['actual'], group['cash']['actual'], group['heads']['actual']) == (3, 4500, 1)
    assert sum(row['heads']['actual'] for row in group['schools']) == 2
    schools = {row['name']: row for row in group['schools']}
    assert schools['天津师范大学']['orders']['actual'] == 1
    assert schools['天津师范大学']['share'] == 1 / 10
    assert schools['天津师范大学']['cash_share'] == 1500 / 13500
    assert schools['天津师范大学']['channel_cash_share'] == 1500 / 10500
    assert schools['其他学校']['orders']['actual'] == 2
    assert schools['其他学校']['share'] == 2 / 10
    assert schools['其他学校']['cash_share'] == 3000 / 13500
    assert schools['其他学校']['channel_cash_share'] == 3000 / 10500
    assert schools['天津师范大学']['share'] != schools['其他学校']['share']
    assert schools['天津师范大学']['cash_share'] != schools['其他学校']['cash_share']
    assert schools['天津师范大学']['channel_cash_share'] != schools['其他学校']['channel_cash_share']

    abroad = next(row for row in channels if row['business_line'] == 'abroad')
    assert [(row['name'], [school['name'] for school in row['schools']])
            for row in abroad['groups']] == [('毕业及其他', ['暂无归属'])]


def test_non_university_channel_group_structure_is_unchanged():
    facts = [
        _training_fact('留学预备学校', '大学*', 's1', 'orders', 1, group='留学预备'),
        _training_fact('留学预备学校', '大学*', 's1', 'cash', 1500, group='留学预备'),
    ]
    row = next(item for item in _channels(facts, {'id': 'prep'}, _period())
               if item['business_line'] == 'training')

    assert len(row['groups']) == 1
    assert set(row['groups'][0]) == {
        'name', 'orders', 'cash', 'heads', 'share', 'cash_share', 'channel_cash_share',
    }
    assert row['groups'][0]['name'] == '青少'


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
