import json,hashlib,tempfile,unittest
from pathlib import Path
from dashboard_product.management.candidate_sources import load_candidate_sources,validate_candidate_authorities,CandidateSourceError

class TencentCandidateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.raw=self.root/'native.csv';self.raw.write_text('日期,曝光次数,点击次数,点击率,点击均价,花费\n2026-10-28,100,1,1%,2.50,2.50\n',encoding='utf-8-sig');self.state=self.root/'state.json';self.state.write_text(json.dumps({'phase':'verified','account_id':'74749810','product_scope':'legacy_search','window':['2026-10-01','2026-10-28'],'file_sha256':self.sha(self.raw),'native':{'rows':1,'total':'2.50'}}))
  self.entry={'source_id':'tencent_search','kind':'tencent_native_csv','path':str(self.raw),'sha256':self.sha(self.raw),'business_line':'abroad','business_group':'留学整体','platform':'腾讯广告','account_id':'74749810','product_scope':'legacy_search','time_basis':'播放口径','start_date':'2026-10-01','end_date':'2026-10-28','capture_evidence':{'path':str(self.state),'sha256':self.sha(self.state)}}
 def sha(self,p):return hashlib.sha256(p.read_bytes()).hexdigest()
 def parse(self):
  p=self.root/'sources.json';p.write_text(json.dumps({'sources':[self.entry]}));return load_candidate_sources(p)
 def scope_confirmation(self):
  path=self.root/'tencent-scope-business-confirmation.json';record={'evidence_type':'user_confirmed_business_scope','account_id':'74749810','confirmed_entrances':['竞价－搜索投放','竞价－展示投放'],'combine_rule':'sum','exclude_costs_by_product':False,'technical_disjointness_proven':False};path.write_text(json.dumps(record,ensure_ascii=False))
  return {'account_id':'74749810','product_scopes':['display_plus','legacy_search'],'combine_rule':'sum','evidence':{'path':str(path),'sha256':self.sha(path)}}
 def test_native_spend_keeps_tencent_bucket_and_product_scope(self):
  r=self.parse();self.assertEqual(r['rows'][0]['amount'],2.5);self.assertEqual(r['rows'][0]['platform'],'腾讯广告');self.assertEqual(r['rows'][0]['product_scope'],'legacy_search');self.assertFalse(r['sources'][0]['whole_account_complete']);self.assertIn('2026-10-27',r['sources'][0]['missing_selected_dates'])
 def test_csv_cannot_claim_other_account_or_training_group(self):
  for field,value in [('account_id','other'),('business_line','training'),('platform','微信')]:
   original=self.entry[field];self.entry[field]=value
   with self.assertRaisesRegex(ValueError,'business_scope_unverified'):self.parse()
   self.entry[field]=original
 def test_capture_provenance_hash_is_bound(self):
  self.state.write_text('{}')
  with self.assertRaisesRegex(ValueError,'capture_digest_mismatch'):self.parse()
 def test_native_bytes_must_match_verified_capture(self):
  self.raw.write_text(self.raw.read_text().replace('2.50,2.50','2.50,3.00'));self.entry['sha256']=self.sha(self.raw)
  with self.assertRaisesRegex(ValueError,'capture_identity_mismatch'):self.parse()
 def test_two_tencent_scopes_require_and_accept_user_confirmation(self):
  other={**self.entry,'source_id':'display','product_scope':'display_plus'}
  with self.assertRaisesRegex(CandidateSourceError,'product_overlap_unverified'):
   validate_candidate_authorities({'sources':[self.entry,other]})
  confirmation=self.scope_confirmation()
  self.assertIn('腾讯',validate_candidate_authorities({'sources':[self.entry,other]},business_scope_confirmation=confirmation))
 def test_confirmed_tencent_scopes_can_sum_same_account_day_without_hiding_same_scope_duplicates(self):
  other={**self.entry,'source_id':'display','product_scope':'display_plus'}
  manifest={'sources':[self.entry,other]};confirmation=self.scope_confirmation()
  rows={'rows':[{'platform':'腾讯广告','account_id':'74749810','product_scope':'legacy_search','start_date':'2026-10-28','end_date':'2026-10-28'},{'platform':'腾讯广告','account_id':'74749810','product_scope':'display_plus','start_date':'2026-10-28','end_date':'2026-10-28'}]}
  from dashboard_product.management.candidate_sources import validate_candidate_account_days
  validate_candidate_account_days(rows,manifest,business_scope_confirmation=confirmation)
  with self.assertRaisesRegex(CandidateSourceError,'account_date_overlap'):
   validate_candidate_account_days({'rows':[rows['rows'][0],rows['rows'][0]]},manifest,business_scope_confirmation=confirmation)
 def test_confirmed_tencent_pair_manifest_flows_through_normal_candidate_loader(self):
  display_raw=self.root/'display.csv';display_raw.write_text('日期,曝光次数,点击次数,点击率,点击均价,花费\n2026-10-28,80,1,1%,1.25,1.25\n',encoding='utf-8-sig')
  display_state=self.root/'display-state.json';display_state.write_text(json.dumps({'phase':'verified','account_id':'74749810','product_scope':'display_plus','window':['2026-10-01','2026-10-28'],'file_sha256':self.sha(display_raw),'native':{'rows':1,'total':'1.25'}}))
  display={**self.entry,'source_id':'tencent_display','path':str(display_raw),'sha256':self.sha(display_raw),'product_scope':'display_plus','capture_evidence':{'path':str(display_state),'sha256':self.sha(display_state)}}
  manifest={'sources':[self.entry,display],'business_scope_confirmation':self.scope_confirmation()}
  path=self.root/'combined-sources.json';path.write_text(json.dumps(manifest,ensure_ascii=False))
  from dashboard_product.management.candidate_sources import load_candidate_sources
  parsed=load_candidate_sources(path)
  self.assertEqual(len(parsed['rows']),2);self.assertEqual(sum(r['amount'] for r in parsed['rows']),3.75)
 def test_full_daily_stages_capture_identity_and_stops_reading_original(self):
  from dashboard_product.shadow_bi.p5.full_daily import receipt_collector
  manifest=self.root/'manifest.json';manifest.write_text(json.dumps({'sources':[self.entry]}))
  receipt=self.root/'capture.json';receipt.write_text(json.dumps({'manifest_path':str(manifest),'sources':[{'files':[{'path':str(self.raw),'sha256':self.sha(self.raw)},{'path':str(self.state),'sha256':self.sha(self.state)}],'evidence':{'path':str(self.state),'sha256':self.sha(self.state)}}]}))
  stage=self.root/'stage';stage.mkdir();captured=receipt_collector(receipt)(self.root,'2026-10-29','run_test',stage)
  entry=json.loads(Path(captured['manifest_path']).read_text())['sources'][0]
  self.assertTrue(Path(entry['capture_evidence']['path']).is_relative_to(stage))
  self.state.write_text('{}')
  self.assertEqual(len(load_candidate_sources(Path(captured['manifest_path']))['rows']),1)
 def test_capture_identity_outside_bundle_is_not_silently_referenced(self):
  from dashboard_product.shadow_bi.p5.full_daily import receipt_collector,DailyBlocked
  manifest=self.root/'manifest.json';manifest.write_text(json.dumps({'sources':[self.entry]}))
  proof=self.root/'other-proof.json';proof.write_text('{}')
  receipt=self.root/'capture.json';receipt.write_text(json.dumps({'manifest_path':str(manifest),'sources':[{'files':[{'path':str(self.raw),'sha256':self.sha(self.raw)}],'evidence':{'path':str(proof),'sha256':self.sha(proof)}}]}))
  stage=self.root/'stage';stage.mkdir()
  with self.assertRaisesRegex(DailyBlocked,'capture_evidence_not_in_bundle'):receipt_collector(receipt)(self.root,'2026-10-29','run_test',stage)
 def test_group_aggregate_and_designated_sem_cannot_supplement_native_tencent(self):
  for other,reason in [({'kind':'network_weekly'},'group_aggregate_forbidden'),({'kind':'sem_daily','source_id':'sem','sheets':{'x':{'platform':'微信'}}},'authority_conflict')]:
   with self.assertRaisesRegex(CandidateSourceError,reason):validate_candidate_authorities({'sources':[self.entry,other]})
if __name__=='__main__':unittest.main()
