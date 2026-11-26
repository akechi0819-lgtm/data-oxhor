from __future__ import annotations

from decimal import Decimal

import duckdb

from dashboard_product.shadow_bi.sql_warehouse.platforms import install_platforms


def _fact(fact_id, business_line, metric, value, day, *, group=None, mode=None,
          team_id=None, segment_id=None):
    return (
        fact_id, business_line, metric, '{}', None, None, None, None, None,
        fact_id, day, Decimal(value), group, mode, team_id, segment_id,
    )


def _relation_schema(con, relation):
    return [(row[0], row[1]) for row in con.execute(f'DESCRIBE SELECT * FROM {relation}').fetchall()]


def _rows(con, relation):
    return con.execute(
        f'SELECT * FROM {relation} ORDER BY acquisition_scope,event_date,business_line,expense_group,platform'
    ).fetchall()


def test_online_daily_cache_preserves_scopes_schema_and_refreshes_on_reinstall():
    con = duckdb.connect(':memory:')
    try:
        con.execute('CREATE SCHEMA business')
        con.execute('''CREATE TABLE business.facts(
            fact_id VARCHAR,business_line VARCHAR,metric VARCHAR,source_record JSON,
            second_channel VARCHAR,first_channel VARCHAR,raw_second_channel VARCHAR,
            third_channel VARCHAR,raw_first_channel VARCHAR,work_order_id VARCHAR,
            event_date DATE,value DECIMAL(24,2),business_group VARCHAR,
            acquisition_mode VARCHAR,team_id VARCHAR,segment_id VARCHAR)''')
        rows = [
            _fact('training-passive-orders', 'training', 'orders', '2.00', '2026-11-05',
                  group='大学', mode='被动', team_id='online_platform'),
            _fact('training-passive-cash', 'training', 'cash', '30.00', '2026-11-05',
                  group='大学', mode='被动', team_id='online_platform'),
            _fact('training-active-orders', 'training', 'orders', '3.00', '2026-11-05',
                  group='大学', mode='主动', team_id='online_platform'),
            _fact('training-active-cash', 'training', 'cash', '7.00', '2026-11-05',
                  group='大学', mode='主动', team_id='online_platform'),
            _fact('training-offline', 'training', 'orders', '100.00', '2026-11-05',
                  group='大学', mode='被动', team_id='offline_market'),
            _fact('abroad-online-orders', 'abroad', 'orders', '1.00', '2026-11-05',
                  segment_id='study_abroad_online'),
            _fact('abroad-online-cash', 'abroad', 'cash', '50.00', '2026-11-05',
                  segment_id='study_abroad_online'),
            _fact('abroad-offline', 'abroad', 'orders', '100.00', '2026-11-05',
                  segment_id='study_abroad_offline'),
        ]
        con.executemany('INSERT INTO business.facts VALUES (' + ','.join('?' for _ in rows[0]) + ')', rows)

        install_platforms(con)

        cache_schema = _relation_schema(con, 'business.online_daily_cache')
        assert _relation_schema(con, 'business.online_scoped_daily') == cache_schema
        assert cache_schema == [
            ('acquisition_scope', 'VARCHAR'),
            ('event_date', 'DATE'),
            ('business_line', 'VARCHAR'),
            ('expense_group', 'VARCHAR'),
            ('platform', 'VARCHAR'),
            ('orders', 'DECIMAL(38,2)'),
            ('cash', 'DECIMAL(38,2)'),
        ]
        assert con.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema='business' AND table_name='online_scoped_daily'"
        ).fetchone()[0] == 'VIEW'
        assert con.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema='business' AND table_name='online_daily'"
        ).fetchone()[0] == 'VIEW'

        scoped = _rows(con, 'business.online_scoped_daily')
        assert len(scoped) == 6
        by_scope_line = {
            (row[0], row[2]): (row[5], row[6])
            for row in scoped
        }
        assert by_scope_line == {
            ('被动', 'training'): (Decimal('2.00'), Decimal('30.00')),
            ('主动', 'training'): (Decimal('3.00'), Decimal('7.00')),
            ('全部', 'training'): (Decimal('5.00'), Decimal('37.00')),
            ('被动', 'abroad'): (Decimal('1.00'), Decimal('50.00')),
            ('主动', 'abroad'): (Decimal('1.00'), Decimal('50.00')),
            ('全部', 'abroad'): (Decimal('1.00'), Decimal('50.00')),
        }
        passive_schema = _relation_schema(con, 'business.online_daily')
        assert passive_schema == cache_schema[1:]
        passive_rows = con.execute(
            'SELECT * FROM business.online_daily ORDER BY event_date,business_line,expense_group,platform'
        ).fetchall()
        expected_passive = con.execute(
            "SELECT * EXCLUDE(acquisition_scope) FROM business.online_scoped_daily "
            "WHERE acquisition_scope='被动' ORDER BY event_date,business_line,expense_group,platform"
        ).fetchall()
        assert passive_rows == expected_passive
        assert len(passive_rows) == 2

        con.execute(
            "INSERT INTO business.facts VALUES "
            "('training-refresh-cash','training','cash','{}',NULL,NULL,NULL,NULL,NULL,"
            "'training-refresh-cash','2026-11-05',5.00,'大学','被动','online_platform',NULL)"
        )
        before_reinstall = con.execute(
            "SELECT cash FROM business.online_scoped_daily "
            "WHERE acquisition_scope='被动' AND business_line='training'"
        ).fetchone()[0]
        assert before_reinstall == Decimal('30.00')

        install_platforms(con)

        refreshed = {
            (row[0], row[2]): (row[5], row[6])
            for row in _rows(con, 'business.online_scoped_daily')
        }
        assert refreshed[('被动', 'training')] == (Decimal('2.00'), Decimal('35.00'))
        assert refreshed[('主动', 'training')] == (Decimal('3.00'), Decimal('7.00'))
        assert refreshed[('全部', 'training')] == (Decimal('5.00'), Decimal('42.00'))
        assert _relation_schema(con, 'business.online_scoped_daily') == cache_schema
    finally:
        con.close()


def test_abroad_exact_paid_channel_contract_in_sql_cache():
    con = duckdb.connect(':memory:')
    try:
        con.execute('CREATE SCHEMA business')
        con.execute('''CREATE TABLE business.facts(
            fact_id VARCHAR,business_line VARCHAR,metric VARCHAR,source_record JSON,
            second_channel VARCHAR,first_channel VARCHAR,raw_second_channel VARCHAR,
            third_channel VARCHAR,raw_first_channel VARCHAR,work_order_id VARCHAR,
            event_date DATE,value DECIMAL(24,2),business_group VARCHAR,
            acquisition_mode VARCHAR,team_id VARCHAR,segment_id VARCHAR)''')
        examples = ([(label, '腾讯广告') for label in ('微信朋友圈', '微信搜索', '微信搜索乐语', '微信小程序', '微信小程序乐语')] +
                    [(label, '抖音') for label in ('抖音', '抖音本地推', '抖音来客', '抖音来客私信')] +
                    [(label, '小红书') for label in ('小红书', '分公司小红书', '小红书付费', '小红书免费', '小红书私信')] +
                    [('小红书-付费', '小红书'), ('小红书－免费', '小红书'),
                    ('今日头条', '其他线上来源'), ('抖音品专', '其他线上来源'),
                    ('小红书品专', '其他线上来源'), ('腾讯广告', '其他线上来源'),
                    ('微信官微', '微信')])
        rows = []
        for index, (third, expected) in enumerate(examples):
            for metric in ('orders', 'cash'):
                row = list(_fact(f'{index}-{metric}', 'abroad', metric, '1.00', '2026-11-05',
                                 segment_id='study_abroad_online'))
                row[7] = third
                if expected in ('腾讯广告', '抖音', '小红书'):
                    row[6] = '百度'
                rows.append(row)
        con.executemany('INSERT INTO business.facts VALUES (' + ','.join('?' for _ in rows[0]) + ')', rows)
        install_platforms(con)
        actual = dict(con.execute('SELECT fact_id,platform FROM business.platform_audit').fetchall())
        for index, (_, expected) in enumerate(examples):
            for metric in ('orders', 'cash'):
                assert actual[f'{index}-{metric}'] == expected
    finally:
        con.close()
