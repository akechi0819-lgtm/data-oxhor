import json,tempfile
from pathlib import Path
import unittest
from dashboard_product.management.candidate_sources import validate_candidate_authorities,validate_candidate_account_days,load_candidate_sources,CandidateSourceError
from dashboard_product.management.advertising_sources import load_sources

class CandidateAuthorityTests(unittest.TestCase):
    def test_group_aggregate_is_rejected_even_if_platforms_excluded(self):
        with self.assertRaisesRegex(CandidateSourceError,'group_aggregate_forbidden'):
            validate_candidate_authorities({'sources':[{'kind':'network_weekly','source_id':'old','exclude_platforms':['小红书','抖音']} ]})
    def test_group_period_difference_is_not_a_candidate_fallback(self):
        with self.assertRaisesRegex(CandidateSourceError,'group_aggregate_forbidden'):
            validate_candidate_authorities({'sources':[],'network_period_differences':[{}]})
    def test_multiple_native_accounts_share_one_authority(self):
        result=validate_candidate_authorities({'sources':[{'kind':'ocean_daily','source_id':'one'},{'kind':'ocean_daily','source_id':'two'}]})
        self.assertEqual(result,{'抖音':{'authority':'native:ocean','source_ids':['one','two']}})
    def test_sem_native_platform_conflict_is_reported_not_silently_dropped(self):
        manifest={'sources':[{'kind':'xhs_mcc_daily','source_id':'native'},{'kind':'sem_daily','source_id':'manual','sheets':{'account':{'platform':'小红书'}}}]}
        with self.assertRaisesRegex(CandidateSourceError,'authority_conflict:小红书'):validate_candidate_authorities(manifest)
        self.assertEqual(len(manifest['sources']),2)
    def test_existing_designated_sem_platforms_remain_valid(self):
        manifest={'sources':[{'kind':'xhs_mcc_daily','source_id':'xhs'},{'kind':'ocean_daily','source_id':'ocean'},{'kind':'sem_daily','source_id':'sem','sheets':{p:{'platform':p} for p in ['百度','必应','闲鱼']}}]}
        result=validate_candidate_authorities(manifest)
        self.assertTrue(all(result[p]['authority']=='designated:sem' for p in ['百度','必应','闲鱼']))
    def test_mcc_and_old_xhs_exports_cannot_double_cover_accounts(self):
        with self.assertRaisesRegex(CandidateSourceError,'xhs_report_overlap_unverified'):
            validate_candidate_authorities({'sources':[{'kind':'xhs_mcc_daily','source_id':'mcc'},{'kind':'xhs_daily','source_id':'old'}]})
    def test_account_day_overlap_is_rejected_while_distinct_accounts_are_allowed(self):
        a={'platform':'小红书','account_id':'1','start_date':'2026-10-27','end_date':'2026-10-27'}
        validate_candidate_account_days({'rows':[a,{**a,'account_id':'2'}]})
        with self.assertRaisesRegex(CandidateSourceError,'account_date_overlap'):validate_candidate_account_days({'rows':[a,a]})
    def test_repeated_sem_leaf_day_is_rejected(self):
        a={'platform':'百度','source_sheet':'2665','start_date':'2026-10-27','end_date':'2026-10-27'}
        with self.assertRaisesRegex(CandidateSourceError,'account_date_overlap'):validate_candidate_account_days({'rows':[a,a]})
    def test_two_revisions_of_same_ocean_project_day_cannot_sum(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);entries=[]
            for i in [1,2]:
                raw=root/f'{i}.csv';raw.write_text('项目ID,项目名称,日期,营销场景,投放类型,消耗(元)\n1,a,2026-10-27,短视频,通投,'+str(i)+'\n')
                entries.append({'source_id':f'ocean_{i}','path':str(raw),'kind':'ocean_daily','business_line':'training','business_group':'大学','platform':'抖音'})
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'sources':entries}))
            self.assertEqual(len(load_sources(manifest)['rows']),2)
            with self.assertRaisesRegex(CandidateSourceError,'ocean_project_date_overlap'):load_candidate_sources(manifest)
    def test_registered_parser_remains_available_for_historical_trace(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=root/'old.csv';raw.write_text('开始日期,结束日期\n2026-10-01,2026-10-11\n公司,渠道中类,总推广费用\n天津,微信搜索,3020\n')
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'sources':[{'source_id':'old','kind':'network_weekly','path':str(raw),'business_line':'abroad','business_group':'留学整体','company':'天津'}]}))
            self.assertEqual(load_sources(manifest)['rows'][0]['amount'],3020)
            with self.assertRaisesRegex(CandidateSourceError,'group_aggregate_forbidden'):load_candidate_sources(manifest)

if __name__=='__main__':unittest.main()
