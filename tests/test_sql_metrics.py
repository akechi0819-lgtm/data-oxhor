from pathlib import Path
import unittest

import duckdb

from dashboard_product.shadow_bi.sql_warehouse.metrics import install_metrics
from dashboard_product.shadow_bi.sql_warehouse.personal import install_personal
from dashboard_product.shadow_bi.sql_warehouse.relations import load_rows


ROOT=Path(__file__).resolve().parents[1]
TYPES={'fact_id':'VARCHAR','metric':'VARCHAR','business_line':'VARCHAR','event_date':'DATE','value':'DECIMAL(24,2)',
 'team_id':'VARCHAR','business_group':'VARCHAR','comparison_group':'VARCHAR','acquisition_mode':'VARCHAR',
 'student_id':'VARCHAR','class_code':'VARCHAR','registration_count':'DOUBLE','segment_id':'VARCHAR',
 'customer_domain':'VARCHAR','first_channel':'VARCHAR','school_attribute':'VARCHAR','school_name':'VARCHAR',
 'channel_school_name':'VARCHAR','owners':'VARCHAR[]','virtual_owners':'VARCHAR[]','campaign_name':'VARCHAR',
 'order_status':'VARCHAR','counts_toward_completion':'BOOLEAN','team_inferred':'BOOLEAN'}


def fact(key,value,**kw):
    return {'fact_id':key,'metric':'cash','business_line':'training','event_date':'2026-06-10',
     'value':value,'team_id':'online_platform','business_group':'大学','comparison_group':'大学',
     'acquisition_mode':'被动','student_id':'S1','class_code':'C1','registration_count':1,
     'owners':[],'virtual_owners':[],'counts_toward_completion':True,'team_inferred':False,**kw}


class SqlMetricTests(unittest.TestCase):
    def connect(self,training,abroad=()):
        c=duckdb.connect();self.addCleanup(c.close)
        load_rows(c,'business','training_facts',training,columns=TYPES)
        load_rows(c,'business','training_personnel_facts',training,columns=TYPES)
        load_rows(c,'business','abroad_facts',list(abroad),columns=TYPES)
        install_metrics(c,through='2026-11-05',abroad_start='2026-06-01',abroad_through='2026-11-05',config_root=ROOT)
        return c

    def test_online_abroad_cash_targets_keep_annual_and_quarter_values(self):
        c = self.connect([])
        rows = c.execute("SELECT period_id, target FROM business.team_metrics WHERE unit_id='online' AND business_line='abroad' AND metric='cash' AND acquisition_scope='被动' AND period_id IN ('FY27','Q1','Q2','Q3','Q4')").fetchall()
        self.assertEqual(dict(rows), {'FY27': 29930000, 'Q1': 7481400, 'Q2': 7481400, 'Q3': 7481400, 'Q4': 7481400})

    def test_heads_qualify_after_scope_filter_and_preserve_negative_cash(self):
        c=self.connect([fact('a',1400),fact('b',200,team_id='offline_market'),
                        fact('c',-1600,student_id='S2')])
        def heads(unit):
            return c.execute("SELECT actual FROM business.team_metrics WHERE period_id='2026-06' AND unit_id=? AND acquisition_scope='被动' AND business_line='training' AND metric='heads'",[unit]).fetchone()[0]
        self.assertEqual(heads('total'),2)
        self.assertEqual(heads('online'),1)
        self.assertEqual(heads('university'),0)

    def test_active_scope_is_independent_and_has_no_passive_target(self):
        c=self.connect([fact('a',1,metric='orders',acquisition_mode='主动')])
        rows=c.execute("SELECT acquisition_scope,actual,target FROM business.team_metrics WHERE period_id='2026-06' AND unit_id='online' AND business_line='training' AND metric='orders'").fetchall()
        values={r[0]:r[1:] for r in rows}
        self.assertEqual(values['主动'],(1,None));self.assertEqual(values['全部'],(1,None))
        self.assertEqual(values['被动'][0],0)

    def test_abroad_domains_stay_separate_and_future_is_not_zero(self):
        c=self.connect([], [fact('a',100,business_line='abroad',segment_id='study_abroad_online',customer_domain='study_abroad'),
                            fact('b',100,business_line='abroad',segment_id='study_abroad_online',customer_domain='small_language')])
        self.assertEqual(c.execute("SELECT actual,status FROM business.team_metrics WHERE period_id='2026-06' AND unit_id='online' AND acquisition_scope='被动' AND business_line='abroad' AND metric='heads'").fetchone(),(None,'separate_counts'))
        self.assertEqual(c.execute("SELECT actual,status FROM business.team_metrics WHERE period_id='2026-12' AND unit_id='online' AND acquisition_scope='被动' AND business_line='training' AND metric='cash'").fetchone(),(None,'future'))

    def test_personal_performance_month_and_calendar_month_are_different(self):
        c=self.connect([fact('a',1,metric='orders',event_date='2026-05-26',team_id='offline_market',business_group='高中',owners=['刘彬'])])
        install_personal(c,config_root=ROOT)
        values=dict(c.execute("SELECT month_mode,actual FROM business.personal_metrics WHERE period_id='2026-06' AND name='刘彬' AND state='01' AND business_line='training' AND metric='orders'").fetchall())
        self.assertEqual(values,{'calendar':0,'performance':1})

    def test_next_performance_month_opens_on_the_26th(self):
        c=self.connect([])
        install_personal(c,config_root=ROOT)
        c.execute("UPDATE config.clock SET through_date=DATE '2026-11-26'")
        values=dict(c.execute("SELECT month_mode,status FROM business.personal_windows WHERE period_id='2026-12'").fetchall())
        self.assertEqual(values,{'calendar':'future','performance':'available'})


if __name__=='__main__':unittest.main()
