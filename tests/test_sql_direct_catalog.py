import unittest
from datetime import date
import duckdb
from jinja2 import Template
from dashboard_product.shadow_bi.sql_warehouse.direct_catalog import direct_sql
from dashboard_product.shadow_bi.sql_warehouse.catalog import _direct_sql


class DirectCatalogTests(unittest.TestCase):
    def test_pending_count_preserves_zero_months(self):
        with duckdb.connect() as c:
            c.execute('CREATE SCHEMA business')
            c.execute("CREATE TABLE business.contribution_capacity AS SELECT * FROM (VALUES ('2026-10'),('2026-11')) t(month)")
            c.execute("CREATE TABLE business.contribution_pending AS SELECT '2026-10' AS month,'record-1' AS key")
            rows=c.execute(direct_sql('capacity_pending_count')+' ORDER BY 产能月份').fetchall()
            self.assertEqual(rows,[('2026-10',1),('2026-11',0)])

    def test_unmapped_product_has_no_conversion(self):
        with duckdb.connect() as c:
            c.execute('CREATE SCHEMA business')
            c.execute('''CREATE TABLE business.radar_products(
              name VARCHAR,domain VARCHAR,orders DECIMAL(38,30),cash DECIMAL(38,30),heads DECIMAL(38,28))''')
            c.execute("INSERT INTO business.radar_products VALUES "
                      "('甲','unmapped',2,100,1),('甲','study_abroad',4,100,2)")
            rows=c.execute(direct_sql('capacity_annual_products')+' ORDER BY 产品').fetchall()
            self.assertEqual(rows,[('甲','未归属产品',2.0,100.0,1.0,None),('甲','留学',4.0,100.0,2.0,0.5)])
            types={row[0]:row[1] for row in c.execute(
                'DESCRIBE SELECT * FROM ('+direct_sql('capacity_annual_products')+') products').fetchall()}
            for column in ['工单','现金','独立人头']:
                self.assertEqual(types[column],'DOUBLE')
            self.assertIs(type(rows[0][2]),float)

    def test_annual_target_projection_restores_legacy_double_types(self):
        with duckdb.connect() as c:
            c.execute('CREATE SCHEMA business')
            c.execute('''CREATE TABLE business.radar_people(
              name VARCHAR,home_group VARCHAR,business_line VARCHAR,orders DECIMAL(38,30),
              cash DECIMAL(38,30),heads DECIMAL(38,28),conversion DOUBLE,cash_capacity DECIMAL(38,2),
              cash_progress_completion DOUBLE,start_date DATE,through_date DATE,peer_count BIGINT)''')
            c.execute("INSERT INTO business.radar_people VALUES "
                      "('甲','青少','training',50,80000,4,0.08,100000,0.8,'2026-06-01','2027-05-31',3)")
            c.execute('''CREATE TABLE business.radar_products(
              name VARCHAR,domain VARCHAR,orders DECIMAL(38,30),cash DECIMAL(38,30),heads DECIMAL(38,28))''')
            c.execute("INSERT INTO business.radar_products VALUES ('甲','training',50,80000,4)")
            sql=direct_sql('capacity_annual_targets')
            cursor=c.execute(sql)
            row=cursor.fetchone()
            types={item[0]:item[1] for item in c.execute(
                'DESCRIBE SELECT * FROM ('+sql+') targets').fetchall()}
            for column in ['年度工单','年度现金','年度人头']:
                self.assertEqual(types[column],'DOUBLE')
            self.assertEqual(row[3:6],(50.0,80000.0,4.0))
            self.assertTrue(all(type(value) is float for value in row[3:6]))

    def test_capacity_radar_values_keep_the_legacy_axis_order_after_person_sort(self):
        axes=[
            ('orders','工单数'),('heads','签约量'),('conversion','转化率'),
            ('partner','渠道／校代现金'),('tmk','TMK现金'),('campaign','活动现金'),
        ]
        names=['A','B']
        with duckdb.connect() as c:
            c.execute('CREATE SCHEMA business')
            c.execute('''CREATE TABLE business.radar_axes(
                name VARCHAR,axis VARCHAR,label VARCHAR,value DOUBLE,mean DOUBLE,
                scale DOUBLE,relative DOUBLE,through_date DATE)''')
            rows=[]
            for person_index,name in reversed(list(enumerate(names))):
                for axis_index,(axis,label) in reversed(list(enumerate(axes))):
                    value=float((person_index+1)*10+axis_index)
                    rows.append((name,axis,label,value,value+0.5,100.0,value/100.0,date(2027,5,31)))
            c.executemany('INSERT INTO business.radar_axes VALUES (?,?,?,?,?,?,?,?)',rows)

            sql=_direct_sql('capacity_radar_values','capacity')
            cursor=c.execute('SELECT * FROM ('+sql+') AS dataset ORDER BY 六维人员')
            result=cursor.fetchall()
            self.assertEqual([column[0] for column in cursor.description],[
                '六维人员','维度','本人','同组均值','轴上限','相对同组','年度截止','年度开始'])
            self.assertEqual([row[0] for row in result],['A']*6+['B']*6)
            for person_index,name in enumerate(names):
                person_rows=[row for row in result if row[0]==name]
                self.assertEqual([row[1] for row in person_rows],[label for _,label in axes])
                for axis_index,row in enumerate(person_rows):
                    value=float((person_index+1)*10+axis_index)
                    self.assertEqual(row[2:],(
                        value,value+0.5,100.0,value/100.0,date(2027,5,31),'2026-06-01'))

    def test_personal_channel_metric_ties_keep_reverse_legacy_json_order(self):
        with duckdb.connect() as c:
            c.execute('CREATE SCHEMA business')
            c.execute('CREATE SCHEMA config')
            c.execute('''CREATE TABLE business.personal_events(
                period_id VARCHAR,name VARCHAR,state VARCHAR,first_channel VARCHAR,
                second_channel VARCHAR,value DOUBLE,weight DOUBLE,comparison VARCHAR,
                month_mode VARCHAR,business_line VARCHAR,metric VARCHAR)''')
            c.execute("""INSERT INTO business.personal_events VALUES
                ('FY27','甲','01','M','Beta',5,1,'actual','calendar','abroad','orders'),
                ('FY27','甲','01','Z','Alpha',3,1,'actual','calendar','abroad','orders'),
                ('FY27','甲','01','A','Zeta',3,1,'actual','calendar','abroad','orders'),
                ('FY27','甲','01','A','Alpha',3,1,'actual','calendar','abroad','orders'),
                ('FY27','甲','01','M','Gamma',1,1,'actual','calendar','abroad','orders')""")
            c.execute('CREATE TABLE config.people(name VARCHAR,business_line VARCHAR,home_group VARCHAR)')
            c.execute("INSERT INTO config.people VALUES ('甲','abroad','高中')")
            c.execute('''CREATE TABLE business.personal_metrics(
                period_id VARCHAR,name VARCHAR,state VARCHAR,month_mode VARCHAR,
                business_line VARCHAR,metric VARCHAR,start_date DATE,through_date DATE,actual DOUBLE)''')
            c.execute("""INSERT INTO business.personal_metrics VALUES
                ('FY27','甲','01','calendar','abroad','orders','2026-06-01','2027-05-31',15),
                ('FY27','甲','01','calendar','abroad','cash','2026-06-01','2027-05-31',100)""")

            prep_sql = Template(direct_sql('prep_personal_channels')).render(
                filter_values=lambda name, remove_filter=False: ['高中'] if name == '业务组' else [])
            for sql in (direct_sql('overview_personal_channels'), prep_sql):
                # The chart's actual request sorts by orders descending. Since
                # the legacy JSON array was traversed in reverse of its
                # first_channel/second_channel construction order, equal-order
                # rows must retain these source identities descending.
                rows = c.execute(
                    f'SELECT * FROM ({sql}) AS dataset ORDER BY "工单" DESC').fetchall()
                self.assertEqual([(row[7], row[6], row[10]) for row in rows], [
                    ('M', 'Beta', 5),
                    ('Z', 'Alpha', 3),
                    ('A', 'Zeta', 3),
                    ('A', 'Alpha', 3),
                    ('M', 'Gamma', 1),
                ])


if __name__=='__main__':unittest.main()
