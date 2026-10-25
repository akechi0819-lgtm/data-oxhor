"""Synthetic-only boundary for the real batch's empty pending relation."""
import json,unittest
import duckdb
from dashboard_product.shadow_bi.p3.catalog import PENDING_SQL,VIEWS

class PendingScope(unittest.TestCase):
 def test_shared_event_detail_must_not_replace_whole_month_count(self):
  # Two events; one affects two people. Detail counts sum to 3, monthly count 2.
  with duckdb.connect(':memory:') as con:
   con.execute('CREATE SCHEMA queries')
   con.execute('CREATE TABLE queries.pending_contributions(row_json JSON)')
   for people,source in [(['甲','乙'],'语培工单'),(['甲'],'留学资源')]:
    con.execute('INSERT INTO queries.pending_contributions VALUES (?)',[json.dumps({'month':'2026-10','affected_people':people,'source_label':source,'reason':'待确认'},ensure_ascii=False)])
   con.execute('CREATE TABLE queries.capacity_people(period_id VARCHAR,person_name VARCHAR,state VARCHAR,person JSON)')
   for name,group in [('甲','高中'),('乙','大学')]:
    for state in ['00','01','10','11']:con.execute('INSERT INTO queries.capacity_people VALUES (?,?,?,?)',['2026-10',name,state,json.dumps({'business_line':'training','home_group':group},ensure_ascii=False)])
   rows=con.execute(PENDING_SQL).fetchall()
   self.assertEqual(sum(row[-1] for row in rows),3)
   selected=con.execute("SELECT * FROM ("+PENDING_SQL+") detail WHERE 线下团队='语培 · 高中'").fetchall()
   self.assertEqual({row[1] for row in selected},{'甲'})
   self.assertEqual(sum(row[-1] for row in selected),2)
   total=next(v.sql for v in VIEWS if v.key=='capacity_pending_count')
   self.assertEqual(con.execute(total).fetchall(),[('2026-10',2)])
if __name__=='__main__':unittest.main()
