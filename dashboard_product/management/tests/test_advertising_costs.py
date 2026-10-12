"""SQL仅在无客户数据的内存夹具执行；实际业务验证走受控CLI。"""
import unittest
from datetime import date, timedelta
import duckdb
from dashboard_product.management.advertising_costs import render_sql, apply_result


def costs(rows):
    sources = {}
    for row in rows:
        key = (row['source_id'],row['business_line'],row['business_group'],row['platform'])
        sources[key] = {k:row[k] for k in ('source_id','business_line','business_group','platform','start_date','end_date')}
        sources[key]['grain'] = 'daily' if row['start_date']==row['end_date'] else 'period'
    return {'configured':True,'rows':rows,'sources':list(sources.values())}


def expense(sid, group, amount, start='2026-10-03', end='2026-10-03', line='training', platform='小红书'):
    return dict(source_id=sid,business_line=line,business_group=group,platform=platform,start_date=start,end_date=end,amount=amount)


def business_days(start, end, line='training', group='大学', platform='小红书', orders=1, cash=10):
    current, last = date.fromisoformat(start), date.fromisoformat(end)
    rows = []
    while current <= last:
        rows.append((current.isoformat(),line,group,platform,orders,cash))
        current += timedelta(days=1)
    return rows


class AdvertisingSqlTests(unittest.TestCase):
    def execute(self,business,expenses,start='2026-10-03',end='2026-10-03'):
        periods=[dict(id='test',start_date=start,through_date=end,prior_start_date='2025-10-03',prior_through_date='2025-10-03',status='available')]
        sql=render_sql(periods,business,costs(expenses))
        with duckdb.connect(':memory:') as connection:
            result=connection.execute(sql)
            names=[c[0] for c in result.description]
            return [dict(zip(names,row)) for row in result.fetchall()]

    def test_group_fees_are_not_repeated_when_platform_rolls_up(self):
        business=[('2026-10-03','training','留学预备','小红书',2,500),('2026-10-03','training','高中','小红书',3,600)]
        result=self.execute(business,[expense('prep','留学预备',100),expense('high','高中',200)])
        platform=next(r for r in result if r['record_type']=='platform')
        self.assertEqual(platform['spend'],300)
        self.assertEqual(platform['orders'],5)
        self.assertAlmostEqual(platform['roi'],1100/300)
        leaf={r['business_group']:r for r in result if r['record_type']=='leaf'}
        self.assertEqual(leaf['留学预备']['spend'],100)
        self.assertEqual(leaf['高中']['spend'],200)

    def test_missing_group_fee_uses_provided_cost_basis(self):
        result=self.execute([('2026-10-03','training','大学','小红书',2,500),('2026-10-03','training','高中','小红书',1,100)],[expense('college','大学',100)])
        parent=next(r for r in result if r['record_type']=='platform')
        self.assertEqual(parent['spend'],100)
        self.assertEqual(parent['spend_status'],'partial')
        self.assertEqual(parent['roi'],6)
        self.assertAlmostEqual(parent['cost_per_order'],100/3)

    def test_zero_and_missing_expenses_are_distinct(self):
        result=self.execute([('2026-10-03','training','大学','小红书',1,10),('2026-10-03','training','高中','小红书',1,10)],[expense('college','大学',0)])
        leaf={r['business_group']:r for r in result if r['record_type']=='leaf'}
        self.assertEqual(leaf['大学']['spend'],0)
        self.assertEqual(leaf['大学']['cost_per_order'],0)
        self.assertIsNone(leaf['大学']['roi'])
        self.assertIsNone(leaf['高中']['spend'])

    def test_week_total_is_not_divided_into_daily_bars(self):
        result=self.execute([('2026-10-03','abroad','留学整体','抖音',2,500)],
                            [expense('week','留学整体',70,'2026-10-03','2026-10-09','abroad','抖音')],end='2026-10-09')
        summary=next(r for r in result if r['record_type']=='line')
        self.assertEqual(summary['spend'],70)
        self.assertEqual(summary['spend_status'],'complete')
        self.assertTrue(all(r['spend'] is None for r in result if r['record_type']=='daily' and r['business_line']=='abroad'))
        clipped=self.execute([('2026-10-03','abroad','留学整体','抖音',2,500)],
                            [expense('week','留学整体',70,'2026-10-03','2026-10-09','abroad','抖音')],end='2026-10-05')
        self.assertIsNone(next(r for r in clipped if r['record_type']=='line')['spend'])

    def test_two_projects_same_day_sum_before_coverage_check(self):
        result=self.execute([('2026-10-03','training','大学','小红书',1,20)],
                            [expense('college','大学',10),expense('college','大学',30)])
        self.assertEqual(next(r for r in result if r['record_type']=='platform')['spend'],40)
        self.assertEqual(next(r for r in result if r['record_type']=='platform')['spend_status'],'complete')

    def test_decimal_query_output_is_numeric_in_the_view(self):
        expenses=[expense('college','大学',100)]
        rows=self.execute([('2026-10-03','training','大学','小红书',2,500)],expenses)
        for row in rows:
            for field in ('cash','prior_cash','spend','roi_spend','roi_cash','roi_orders'):
                if row[field] is not None:
                    row[field]=str(row[field])
        view={'metadata':{'data_through':'2026-10-03'},'periods':[{
            'id':'test','through_date':'2026-10-03','daily':[],
            'lines':{'training':{'orders':{'actual':2},'cash':{'actual':500},
                'channels':[{'name':'小红书','first_channels':['平台']}],
                'groups':[{'name':'大学'}]}}}]}
        apply_result(view,rows,costs(expenses),[])
        channel=view['periods'][0]['lines']['training']['channels'][0]
        self.assertEqual(channel['cash'],500)
        self.assertEqual(channel['advertising']['spend'],100)
        self.assertEqual(channel['advertising']['roi'],5)
        self.assertEqual(channel['advertising']['roi_spend'],100)
        self.assertEqual(channel['advertising']['roi_cash'],500)
        self.assertEqual(channel['advertising']['roi_orders'],2)
        self.assertEqual(str(channel['advertising']['roi_start_date']),'2026-10-03')
        self.assertEqual(str(channel['advertising']['roi_through_date']),'2026-10-03')

    def test_daily_overall_roi_uses_daily_cash_and_all_platform_expenses(self):
        business=[('2026-10-03','training','大学','小红书',2,500),('2026-10-03','training','大学','抖音',3,600)]
        result=self.execute(business,[expense('xhs','大学',100),expense('dy','大学',200,platform='抖音')])
        daily=next(r for r in result if r['record_type']=='daily' and r['business_line']=='training')
        self.assertEqual(daily['cash'],1100)
        self.assertEqual(daily['spend'],300)
        self.assertAlmostEqual(daily['roi'],1100/300)
        incomplete=self.execute(business,[expense('xhs','大学',100)])
        self.assertEqual(next(r for r in incomplete if r['record_type']=='daily' and r['business_line']=='training')['roi'],11)

    def test_rollup_roi_uses_common_daily_window_and_keeps_full_period_totals(self):
        business=(business_days('2026-10-01','2026-10-11',platform='小红书',cash=10)
                  + business_days('2026-10-01','2026-10-11',platform='抖音',orders=2,cash=20))
        expenses=([expense('xhs','大学',100,f'2026-10-{day:02d}',f'2026-10-{day:02d}') for day in range(1,10)]
                  + [expense('dy','大学',20,f'2026-10-{day:02d}',f'2026-10-{day:02d}',platform='抖音') for day in range(1,11)])
        result=self.execute(business,expenses,start='2026-10-01',end='2026-10-11')
        line=next(r for r in result if r['record_type']=='line')
        self.assertEqual((line['spend'],line['cash'],line['orders']),(1100,330,33))
        self.assertEqual((str(line['roi_start_date']),str(line['roi_through_date'])),('2026-10-01','2026-10-09'))
        self.assertEqual((line['roi_spend'],line['roi_cash'],line['roi_orders']),(1080,270,27))
        self.assertAlmostEqual(line['roi'],0.25)
        platforms={r['platform']:r for r in result if r['record_type']=='platform'}
        self.assertEqual(str(platforms['小红书']['roi_through_date']),'2026-10-09')
        self.assertEqual(str(platforms['抖音']['roi_through_date']),'2026-10-10')
        self.assertEqual(platforms['抖音']['roi_spend'],200)
        daily={str(r['event_date']):r for r in result if r['record_type']=='daily' and r['business_line']=='training'}
        self.assertEqual(daily['2026-10-10']['spend'],20)
        self.assertIsNone(daily['2026-10-10']['roi'])
        self.assertEqual(daily['2026-10-09']['roi'],0.25)

    def test_consecutive_period_sources_form_one_continuous_fee_stream(self):
        business=business_days('2026-09-01','2026-10-11',line='abroad',group='留学整体',platform='抖音')
        expenses=[expense('sep','留学整体',300,'2026-09-01','2026-09-30','abroad','抖音'),
                  expense('oct','留学整体',110,'2026-10-01','2026-10-11','abroad','抖音')]
        result=self.execute(business,expenses,start='2026-09-01',end='2026-10-11')
        line=next(r for r in result if r['record_type']=='line')
        self.assertEqual(line['spend'],410)
        self.assertEqual((str(line['roi_start_date']),str(line['roi_through_date'])),('2026-09-01','2026-10-11'))
        self.assertEqual((line['roi_spend'],line['roi_cash'],line['roi_orders']),(410,410,41))
        self.assertEqual(line['roi'],1)

    def test_common_roi_window_stops_before_first_internal_missing_day(self):
        business=business_days('2026-10-01','2026-10-10')
        expenses=[expense('xhs','大学',10,f'2026-10-{day:02d}',f'2026-10-{day:02d}')
                  for day in range(1,11) if day!=5]
        result=self.execute(business,expenses,start='2026-10-01',end='2026-10-10')
        line=next(r for r in result if r['record_type']=='line')
        self.assertEqual(line['spend'],90)
        self.assertEqual((str(line['roi_start_date']),str(line['roi_through_date'])),('2026-10-01','2026-10-04'))
        self.assertEqual((line['roi_spend'],line['roi_cash'],line['roi_orders']),(40,40,4))

    def test_zero_fee_is_covered_but_missing_fee_has_no_roi_window(self):
        business=[('2026-10-03','training','大学','小红书',1,10),('2026-10-03','training','高中','小红书',1,10)]
        result=self.execute(business,[expense('college','大学',0),expense('high','高中',None)])
        leaves={r['business_group']:r for r in result if r['record_type']=='leaf'}
        self.assertEqual(leaves['大学']['roi_spend'],0)
        self.assertEqual(str(leaves['大学']['roi_start_date']),'2026-10-03')
        self.assertIsNone(leaves['大学']['roi'])
        self.assertIsNone(leaves['高中']['roi_start_date'])
        self.assertIsNone(leaves['高中']['roi_spend'])
        self.assertIsNone(leaves['高中']['roi'])


if __name__=='__main__':
    unittest.main()
