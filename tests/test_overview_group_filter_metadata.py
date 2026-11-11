"""总览业务组原生筛选只联动语培，保留独立控件及持久身份。"""
from copy import deepcopy

import pytest

from dashboard_product.shadow_bi.p4.sql_release import configure_overview_group_filter


def metadata():
    return {'native_filter_configuration': [
        {'id': 'overview-unit', 'name': '管理单元',
         'targets': [{'datasetId': 17, 'column': {'name': '管理单元'}}],
         'chartsInScope': [10, 11, 12, 13],
         'scope': {'rootPath': ['ROOT_ID'], 'excluded': [99]},
         'tabsInScope': ['overview'],
         'defaultDataMask': {'filterState': {'value': ['市场总计']}},
         'controlValues': {'multiSelect': False}},
        {'id': 'period', 'name': '期间', 'chartsInScope': [10, 11, 12, 13],
         'targets': [{'datasetId': 18, 'column': {'name': '期间'}}]},
    ]}


def test_overview_group_keeps_filter_identity_and_defaults_but_excludes_abroad():
    value = metadata()
    original = deepcopy(value)
    configure_overview_group_filter(value, 17, [11, 13])
    group = value['native_filter_configuration'][0]
    assert group['name'] == '业务组'
    assert group['chartsInScope'] == [10, 12]
    assert group['scope'] == {'rootPath': ['ROOT_ID'], 'excluded': [11, 13, 99]}
    for key in ['id', 'targets', 'defaultDataMask', 'controlValues', 'tabsInScope']:
        assert group[key] == original['native_filter_configuration'][0][key]
    assert value['native_filter_configuration'][1] == original['native_filter_configuration'][1]
    once = deepcopy(value)
    configure_overview_group_filter(value, 17, [11, 13])
    assert value == once


def test_overview_group_rejects_missing_or_ambiguous_source():
    value = metadata()
    with pytest.raises(ValueError, match='身份不唯一'):
        configure_overview_group_filter(value, 999, [11])
    value['native_filter_configuration'].append(deepcopy(value['native_filter_configuration'][0]))
    with pytest.raises(ValueError, match='身份不唯一'):
        configure_overview_group_filter(value, 17, [11])


def test_overview_group_rejects_erasing_all_chart_scope():
    with pytest.raises(ValueError, match='范围无效'):
        configure_overview_group_filter(metadata(), 17, [10, 11, 12, 13])


def test_overview_group_adds_training_school_tab_and_excludes_abroad_tabs():
    value = metadata()
    value['native_filter_configuration'][0]['scope']['excluded'] = [14, 99]
    positions = {
        'DASHBOARD_VERSION_KEY': 'v2',
        'overview': {'type': 'TAB'}, 'school': {'type': 'TAB'}, 'country': {'type': 'TAB'},
        'first': {'type': 'CHART', 'meta': {'chartId': 10}, 'parents': ['overview']},
        'abroad': {'type': 'CHART', 'meta': {'chartId': 11}, 'parents': ['country']},
        'school-chart': {'type': 'CHART', 'meta': {'chartId': 14}, 'parents': ['school']},
    }
    configure_overview_group_filter(value, 17, [11], [14], positions)
    control = value['native_filter_configuration'][0]
    assert control['chartsInScope'] == [10, 14]
    assert control['scope']['excluded'] == [11]
    assert control['tabsInScope'] == ['overview', 'school']
    assert value['native_filter_configuration'][1] == metadata()['native_filter_configuration'][1]
