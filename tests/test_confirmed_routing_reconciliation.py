"""Confirmed source routing must explain both work-order and cash deltas."""
from unittest.mock import patch

from dashboard_product.management.calculation import reconciliation


def test_confirmed_routing_explains_order_and_cash_without_hiding_other_deltas():
    baseline = {'teams': [
        {'team_id': 'offline_market', 'groups': [{'display_name': '大学', 'monthly_actuals': {
            'orders': [1] + [0] * 11, 'cash': [100] + [0] * 11}}]},
        {'team_id': 'online_platform', 'groups': [{'display_name': '大学', 'monthly_actuals': {
            'orders': [0] * 12, 'cash': [0] * 12}}]},
    ]}
    period = {'label': '全年', 'status': 'available', 'start_date': '2026-06-01',
              'through_date': '2026-11-03', 'teams': [
        {'id': 'university', 'name': '大学', 'lines': {'training': {
            'orders': {'actual': 0}, 'cash': {'actual': 0}}}},
        {'id': 'online', 'name': '线上', 'lines': {'training': {
            'orders': {'actual': 1}, 'cash': {'actual': 100}}}},
    ]}
    result = {'metadata': {'data_through': '2026-11-03'}, 'periods': [period]}
    facts = [{'metric': metric, 'value': value, 'event_date': '2026-06-03',
              'business_group': '大学', 'team_id': 'online_platform',
              'team_before_override': 'offline_market',
              'team_override_reason': '用户确认直接线上投放归属'}
             for metric, value in [('orders', 1), ('cash', 100)]]
    with patch('dashboard_product.refresh.project', return_value=baseline):
        rows = reconciliation(result, [], {}, {}, facts)['rows']
        assert len(rows) == 4
        assert all(row['status'] == 'confirmed_change' for row in rows)
        period['teams'][1]['lines']['training']['orders']['actual'] = 2
        rows = reconciliation(result, [], {}, {}, facts)['rows']
        assert rows[2]['status'] == 'difference'
