"""线上平台 ROI 页签的原生图表及筛选接线。"""
from decimal import Decimal
import json


CHARTS = {
    'online_latest': ('summary', '截止日 · 工单 / 毛签 / 花费 / ROI', '本期投流总览'),
    'native_online_daily_training': ('training', '语培 · 每日明细', '语培 · 平台 ROI 明细'),
    'native_online_daily_abroad': ('abroad', '留学及小语种 · 每日明细', '留学及小语种 · 平台 ROI 明细'),
    'online_trend': ('roi', '日趋势 · 工单', '月度 ROI'),
    'online_trend_spend': ('spend', '每日花费', '月度花费'),
    'online_trend_cash': ('cpl', '每日毛签金额', '月度单条成本'),
}
COLUMNS = {
    '线上期间': 'VARCHAR', '月份': 'DATE', '业务线': 'VARCHAR', '平台': 'VARCHAR',
    '平台业务组': 'VARCHAR', '本期花费': 'DECIMAL', '本期工单': 'BIGINT',
    '本期产出': 'DECIMAL', 'ROI': 'DOUBLE', '单条成本': 'DOUBLE',
    '上年同期工单': 'BIGINT', '上年同期产出': 'DECIMAL',
}
TREND = {'roi': ('ROI', 'echarts_timeseries_line'),
         'spend': ('本期花费', 'echarts_timeseries_bar'),
         'cpl': ('单条成本', 'echarts_timeseries_line')}


def table_name(kind):
    return '线上平台 · ' + next(name for value, name, _ in CHARTS.values() if value == kind)


def chart_params(previous, role):
    if role in TREND:
        column, viz = TREND[role]
        metric = {'expressionType': 'SQL', 'sqlExpression': f'MAX("{column}")',
                  'label': column, 'hasCustomLabel': True, 'optionName': 'roi_dashboard_'+role}
        return {**previous, 'viz_type': viz, 'x_axis': '月份', 'granularity_sqla': '月份',
                'time_grain_sqla': 'P1M', 'time_range': 'No filter', 'adhoc_filters': [],
                'groupby': ['业务线'], 'metrics': [metric], 'query_mode': 'aggregate',
                'rich_tooltip': True, 'stack': False, 'y_axis_format': ',.2~f'}, viz
    label = {'training': ['平台业务组', '平台'], 'abroad': ['平台'], 'summary': ['业务线', '平台业务组']}[role]
    columns = label + ['本期花费', '本期工单', '本期产出', 'ROI', '单条成本']
    if role == 'training':
        columns += ['上年同期工单', '上年同期产出']
    labels = {'本期工单': '本期资源', '本期产出': '本期签约及小语种实缴'} if role == 'abroad' else {}
    if role == 'training':
        labels = {'本期产出': '本期报名现金', '上年同期产出': '上年同期报名现金'}
    return {**previous, 'viz_type': 'table', 'query_mode': 'raw', 'all_columns': columns,
            'column_config': {c: {'d3NumberFormat': ',.2f', **({'columnLabel': labels[c]} if c in labels else {})}
                              for c in columns if COLUMNS[c] != 'VARCHAR'},
            'metrics': [], 'groupby': [], 'adhoc_filters': [], 'order_by_cols': [],
            'time_range': 'No filter', 'include_search': False}, 'table'


def layout(metadata, positions, by_role):
    """复用原页签、图表及筛选，月度趋势保留连续的历史横轴。"""
    tabs = positions['TABS-online']['children']
    tab, = (positions[key] for key in tabs if positions[key]['meta']['text'] in ('日趋势与明细', 'ROI 看板'))
    nodes = {node['meta']['chartId']: node for node in positions.values()
             if isinstance(node, dict) and node.get('type') == 'CHART'}
    ids = set(by_role.values())
    rows = {node['meta']['chartId']: node['parents'][-1] for node in nodes.values() if node['meta']['chartId'] in ids}
    assert set(rows.values()) == set(tab['children']), 'ROI 页签图表身份有变化'
    order = ['summary', 'training', 'abroad', 'roi', 'spend', 'cpl']
    tab['children'] = [rows[by_role[role]] for role in order]
    tab['meta']['text'] = 'ROI 看板'
    for role, _, title in CHARTS.values():
        chart = nodes[by_role[role]]
        chart['meta'].update(sliceName=title, height=44 if role in TREND else 28)
    filter_scopes = {
        'NATIVE_FILTER-p3-online-0': {'training', 'abroad', 'summary'},
        'NATIVE_FILTER-p3-online-1': set(order),
        'NATIVE_FILTER-p35-platform-group': set(order)-{'abroad'},
        'NATIVE_FILTER-p3-online-4': set(order),
    }
    for filter_id, roles in filter_scopes.items():
        filter_, = (item for item in metadata['native_filter_configuration'] if item['id'] == filter_id)
        active = (set(filter_['chartsInScope'])-ids)|{by_role[role] for role in roles}
        filter_['chartsInScope'] = sorted(active)
        filter_['scope']['excluded'] = sorted(set(nodes)-active)
        filter_['tabsInScope'] = sorted({parent for cid in active & nodes.keys() for parent in nodes[cid]['parents']
                                        if positions.get(parent, {}).get('type') == 'TAB'})


def install_roi_dashboard(dashboard, by_name, positions, metadata):
    from superset import db
    from superset.connectors.sqla.models import TableColumn

    by_role = {}
    for role, _, title in CHARTS.values():
        dataset = by_name[table_name(role)]
        chart, = (c for c in dashboard.slices if c.datasource_type == 'table' and c.datasource_id == dataset.id)
        by_role[role] = chart.id
        known = {column.column_name for column in dataset.columns}
        for column, kind in COLUMNS.items():
            if column not in known:
                db.session.add(TableColumn(table=dataset, column_name=column, type=kind, is_dttm=kind == 'DATE'))
        params, chart.viz_type = chart_params(json.loads(chart.params), role)
        chart.params = json.dumps(params, ensure_ascii=False)
        chart.slice_name = title
    layout(metadata, positions, by_role)


def verify_roi_dashboard(client, base, positions, datasets, current_month):
    from dashboard_product.shadow_bi.p4.verify_server import payload

    tab, = (positions[key] for key in positions['TABS-online']['children']
            if positions[key]['meta']['text'] == 'ROI 看板')
    titles = {positions[c]['meta']['sliceName'] for row in tab['children']
              for c in positions[row]['children']}
    if titles != {title for _, _, title in CHARTS.values()}:
        raise ValueError('ROI 看板图表范围不符')
    checks = []
    data_fields = ['线上期间', '平台', '本期花费', '本期产出', '本期工单', 'ROI', '单条成本']
    for key, (role, _, _) in CHARTS.items():
        filters = [] if role in TREND else [{'col': '线上期间', 'op': 'IN', 'val': [current_month]}]
        response = client.post(base+'/api/v1/chart/data', json=payload(datasets[key], data_fields, filters), timeout=120)
        response.raise_for_status()
        result, = response.json()['result']
        if result.get('error') or not result.get('data'):
            raise ValueError(f'ROI 正式图表无数据: {key}')
        for row in result['data']:
            if role in TREND and (row['线上期间'].startswith('FY') or row['平台'] != '合计'):
                raise ValueError('ROI 月度图表数据范围不符')
            spend = Decimal(str(row['本期花费'])) if row['本期花费'] is not None else None
            for name, numerator, denominator in (
                ('ROI', Decimal(str(row['本期产出'])), spend),
                ('单条成本', spend, Decimal(str(row['本期工单']))),
            ):
                actual = row[name]
                if numerator is None or not denominator:
                    valid = actual is None
                else:
                    valid = actual is not None and abs(Decimal(str(actual)) - numerator/denominator) < Decimal('0.000001')
                if not valid:
                    raise ValueError(f'ROI 正式图表计算不符: {key}/{name}')
        checks.append({'key': key, 'rows': len(result['data'])})
    return {'status': 'passed', 'checks': checks}
