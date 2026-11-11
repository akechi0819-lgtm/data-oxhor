from pathlib import Path

import duckdb

from dashboard_product.management.tests.test_market_orders_query import (
    WORK_ORDER_COLUMNS, WORK_ORDERS, work_order,
)


def test_market_scope_routes_platform_tmk_before_original_team_and_keeps_source_whitelist():
    rows = []
    for number, name, first, second, source_team in [
        (1, 'platform-offline', 'TMK激活-平台', '小表单', '大学'),
        (2, 'platform-private', 'TMK激活-平台', '虚拟人', '大学'),
        (3, 'market-offline', 'TMK激活-市场活动', '校代', '大学'),
        (4, 'unconfirmed', 'TMK激活-平台', '小表单', ''),
    ]:
        row = work_order(number, name, '2026-10-05', '合成顾问', source_team)
        row.update({'一级渠道': first, '二级渠道': second, '线上线下': '线下'})
        rows.append(row)
    with duckdb.connect(':memory:') as connection:
        connection.execute('CREATE SCHEMA landing')
        declaration = ', '.join(f'"{name}" {kind}' for name, kind in WORK_ORDER_COLUMNS)
        connection.execute(f'CREATE TABLE landing.{WORK_ORDERS} ({declaration})')
        connection.executemany(
            f'INSERT INTO landing.{WORK_ORDERS} VALUES ({",".join("?" for _ in WORK_ORDER_COLUMNS)})',
            [[row.get(name) for name, _ in WORK_ORDER_COLUMNS] for row in rows],
        )
        sql = (Path(__file__).resolve().parents[1] / 'dashboard_product/management/sql/market_orders.sql').read_text()
        result = connection.execute(sql, ['2026-10-01', '2026-11-01'])
        columns = [column[0] for column in result.description]
        records = [dict(zip(columns, row)) for row in result.fetchall()]
    assert {row['work_order_id']: row['team_id'] for row in records} == {
        'platform-offline': 'online_platform',
        'platform-private': 'online_platform',
        'market-offline': 'offline_market',
    }
    assert all(row['actual_value'] == 1 for row in records)
