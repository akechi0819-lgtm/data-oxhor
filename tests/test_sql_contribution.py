"""贡献规则端到端执行 SQL，不调用旧 Python 归属核算。"""
import unittest
import duckdb
from dashboard_product.shadow_bi.sql_warehouse.contribution import install_contribution
from dashboard_product.shadow_bi.sql_warehouse.relations import load_rows

FACT_COLUMNS = {'fact_id':'VARCHAR','business_line':'VARCHAR','metric':'VARCHAR','event_date':'VARCHAR',
'value':'DOUBLE','source_row_number':'BIGINT','work_order_id':'VARCHAR','order_status':'VARCHAR','campaign_name':'VARCHAR'}
ORDER_COLUMNS = {'work_order_id':'VARCHAR','resource_id':'VARCHAR','order_status':'VARCHAR','campaign_name':'VARCHAR',
'first_channel':'VARCHAR','resource_entry_person':'VARCHAR','resource_description':'VARCHAR','source_row_number':'BIGINT'}


def connection(facts=(), orders=(), resources=(), contracts=(), languages=()):
    c=duckdb.connect(':memory:')
    c.execute("SET threads=2; SET memory_limit='512MB'; CREATE SCHEMA business")
    people=[dict(name=name,business_line=line,home_group='大学',team_ids=teams,
                 training_roster=line=='training',abroad_roster=line=='abroad')
            for name,line,teams in [('甲','training',['offline_market']),('乙','training',['offline_market']),
                                   ('丙','abroad',['offline_market']),('丁','abroad',['offline_market']),
                                   ('虚拟','training',['online_private'])]]
    load_rows(c,'config','people',people)
    load_rows(c,'config','personal_targets',[dict(name='丙',business_line='abroad',month='2026-06',metric='orders',target=10)])
    c.execute("CREATE TABLE config.clock AS SELECT DATE '2026-06-30' through_date")
    c.execute("CREATE TABLE business.periods AS SELECT '2026-06' period_id,'month' kind")
    load_rows(c,'business','training_personnel_facts',list(facts),columns=FACT_COLUMNS)
    load_rows(c,'source','order_events',list(orders),columns=ORDER_COLUMNS)
    for kind,rows in [('resources',resources),('contracts',contracts),('languages',languages)]:
        load_rows(c,'landing','study_abroad_market__'+kind,list(rows),columns=None if rows else {'origin_row_number':'VARCHAR'})
    return c


def fact(key='o1', campaign='甲乙虚拟', status='有效'):
    return dict(fact_id=key,business_line='training',metric='orders',event_date='2026-06-01',value=1,
                source_row_number=1,work_order_id=key,order_status=status,campaign_name=campaign)


def resource(**changes):
    r=dict(resource_id='123',record_key='r1',origin_row_number='7',owner='丙',source_owner='甲',
           event_date='2026-06-01',consultation_type='留学',market_group='国际市场',segment_id='international_market',
           campaign='甲（丙）',status='有效',market_eligible='true',personal_eligible='true')
    r.update(changes)
    return r


class ContributionSqlTests(unittest.TestCase):
    def test_offline_equal_share_virtual_does_not_dilute_and_status(self):
        c=connection(facts=[fact(status='死单')]);install_contribution(c)
        self.assertEqual(c.execute('SELECT person,weight FROM business.contributions ORDER BY person').fetchall(),[('乙',.5),('甲',.5)])
        self.assertEqual(c.execute("SELECT state,value FROM business.contribution_totals WHERE person='甲' AND product_scope='all' ORDER BY state").fetchall(),[('01',.5),('11',.5)])
        self.assertEqual(c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='business' AND table_type='BASE TABLE'").fetchone()[0],4) # inputs, periods, two caches
        c.close()

    def test_thirds_preserve_decimal_ledger_and_completion_float(self):
        from decimal import Decimal
        c=connection(facts=[fact(campaign='甲乙戊')])
        c.execute("INSERT INTO config.people SELECT * REPLACE ('戊' AS name) FROM config.people WHERE name='甲'")
        c.execute("INSERT INTO config.personal_targets VALUES ('甲','training','2026-06','orders',105)")
        install_contribution(c)
        expected=Decimal(1)/Decimal(3)
        weight, amount=c.execute("SELECT weight,credited_value FROM business.contributions WHERE person='甲'").fetchone()
        self.assertEqual(weight,expected)
        self.assertEqual(amount,expected)
        completion=c.execute("SELECT completion FROM business.contribution_capacity WHERE person='甲' AND metric='orders' AND state='01' AND product_scope='all'").fetchone()[0]
        self.assertEqual(completion,float(expected/Decimal(105)))
        c.execute('ALTER TABLE config.personal_targets ALTER target TYPE DECIMAL(24,2)')
        c.execute("UPDATE config.personal_targets SET target=0.5 WHERE name='甲'")
        install_contribution(c)
        completion=c.execute("SELECT completion FROM business.contribution_capacity WHERE person='甲' AND metric='orders' AND state='01' AND product_scope='all'").fetchone()[0]
        self.assertEqual(completion,float(expected/Decimal('0.5')))
        c.close()

    def test_marker_authority_and_half_handoff(self):
        c=connection(resources=[resource(),resource(resource_id='124',record_key='r2',campaign='乙（丙）')])
        install_contribution(c)
        self.assertEqual(c.execute("SELECT json_extract_string(cross_business_marker,'$.source_row_number') FROM business.contributions WHERE key='resources:123' LIMIT 1").fetchone()[0],'7')
        self.assertEqual(c.execute("SELECT json_type(cross_business_marker,'$.source_row_number') FROM business.contributions WHERE key='resources:123' LIMIT 1").fetchone()[0],'VARCHAR')
        self.assertEqual(c.execute('SELECT key,person,bucket,weight,rule FROM business.contributions ORDER BY key,person').fetchall(),[
            ('resources:123','丙','received',.5,'source_marker_handoff'),
            ('resources:123','甲','output',.5,'source_marker_handoff'),
            ('resources:124','甲','output',1.,'source_marker_owner_authoritative')])
        c.close()

    def test_cash_keeps_actual_owner_and_history_unknown_splits(self):
        c=connection(resources=[resource()],contracts=[dict(resource_id='123',contract_id='c1',record_key='c1',
          origin_row_number='8',owner='丙',event_date='2026-06-02',month='2026-06',amount='4000',amount_status='present')])
        history={'rows':[dict(month='2026-06',name='丙',components={'study_abroad':{'orders':8,'cash':9000},'small_language':{'orders':2,'cash':None}})]}
        install_contribution(c,history)
        self.assertEqual(c.execute("SELECT person,bucket,weight,rule FROM business.contributions WHERE source='contracts'").fetchall(),[('丙','self',1.,'ordinary_co_creation')])
        self.assertEqual(c.execute("SELECT self,received,own_total,completion FROM business.contribution_capacity WHERE person='丙' AND metric='orders' AND product_scope='all' AND state='01'").fetchone(),(None,None,10.,1.))
        self.assertIsNone(c.execute("SELECT own_total FROM business.contribution_capacity WHERE person='丙' AND metric='cash' AND product_scope='all' AND state='01'").fetchone()[0])
        # An explicit rerun refreshes the same cache from changed source input.
        c.execute("UPDATE landing.study_abroad_market__contracts SET amount='8000'")
        install_contribution(c,history)
        self.assertEqual(c.execute("SELECT credited_value FROM business.contributions WHERE source='contracts'").fetchone()[0],8000)
        c.close()

    def test_latest_resource_marker_conflict_fails(self):
        c=connection(resources=[resource(),resource(source_owner='乙',record_key='r2')])
        with self.assertRaisesRegex(ValueError,'标记冲突'):install_contribution(c)
        c.close()

    def test_same_resource_identity_conflict_fails(self):
        c=connection(resources=[resource(market_group='线下组',segment_id='study_abroad_offline'),
                                resource(market_group='线下组',segment_id='study_abroad_offline',owner='丁')])
        with self.assertRaisesRegex(ValueError,'记录存在冲突'):install_contribution(c)
        c.close()
