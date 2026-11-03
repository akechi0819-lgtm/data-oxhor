import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from data_acquisition.connectors.advertising import ocean_requests as ocean
from data_acquisition.auth.auth_sessions import AuthSessionPaths,write_auth_session,AuthSessionMissingError,AuthSessionExpiredError

class OceanRequestTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.paths=AuthSessionPaths(self.root,'ocean')
  write_auth_session('ocean',cookies=[{'domain':'localads.chengzijianzhan.cn','path':'/','name':'test','value':'private','expires':-1}],local_storage={},paths=self.paths)
  spec=self.paths.root/'query-auth.json';spec.write_text(json.dumps({'headers':{},'body':{'PageParams':{'Limit':'1000','Offset':'0'},'DataSetKey':'pc_data_adv2_detail_clue2','Filters':{'Conditions':[{'Field':'advertiser_id','Values':['prior-account']}]}}}));spec.chmod(0o600)
  self.job={'account':ocean.ACCOUNTS[0],'start':'2026-09-01','through':'2026-10-27','output':self.root/'capture'}
 def response(self,*,empty=False):
  dims={k:{'Value':'x','ValueStr':'x'} for k,_ in ocean.DIMENSIONS};dims.update(cdp_project_id={'Value':'123','ValueStr':'123'},stat_time_day={'Value':'millis','ValueStr':'2026-10-27'})
  metrics={k:{'Value':0,'ValueStr':'0'} for k,_ in ocean.METRICS};metrics['stat_cost']={'Value':2.5,'ValueStr':'2.50'}
  totals=copy.deepcopy(metrics)
  if empty:totals['stat_cost']={'Value':0,'ValueStr':'-'}
  return {'status_code':0,'data':{'StatsData':{'TotalCount':'0' if empty else '1','Totals':totals,'Rows':[] if empty else [{'Dimensions':dims,'Metrics':metrics}]}}}
 def run_value(self,value):
  post=Mock(return_value=value);client=ocean.OceanExport(self.root,post=post);return client.run(**self.job),post
 def test_native_summary_skips_observed_blank_dimension_cells(self):
  from unittest.mock import MagicMock
  from data_acquisition.connectors.advertising.ocean_download import _summary
  page=MagicMock();page.get_by_text.return_value.is_visible.return_value=False;page.get_by_role.return_value.nth.return_value.get_by_role.return_value.all_text_contents.return_value=['共7条数据','','','','','439.52','1,222']
  self.assertEqual(_summary(page),{'count':7,'total':'439.52','empty':False})
 def test_real_export_route_and_project_projection(self):
  self.assertEqual(ocean.QUERY,'/api/lamp/pc/v2/statistics/data/statQuery');r,post=self.run_value(self.response());self.assertEqual(r['rows'],1);self.assertEqual(r['total'],'2.5');self.assertFalse(r['browser_used']);self.assertTrue(Path(r['query_pages'][0]['path']).is_file());body=post.call_args.args[1];self.assertEqual(body['PageParams'],{'Limit':'1000','Offset':'0'});self.assertEqual(body['StartTime'],'2026-09-01 00:00:00');self.assertEqual(body['Filters']['Conditions'][0]['Values'],[self.job['account'][0]])
 def test_zero_requires_successful_raw_response_and_empty_projection(self):
  self.job['account']=ocean.ACCOUNTS[-1];r,_=self.run_value(self.response(empty=True));self.assertEqual(r['rows'],0);self.assertTrue(r['native_validation']['native_empty'])
 def test_native_empty_account_scope_is_explicit_and_requires_native_validation(self):
  results=[{'account_id':'1813785787039897','rows':0,'total':'0','native_validation':{'rows':0,'total':'0.00','native_empty':True},'file':{'sha256':'a'*64},'query_pages':[{'sha256':'b'*64}]}]
  self.assertEqual(ocean.verified_native_empty_accounts(results),['1813785787039897'])
  results[0]['native_validation']['native_empty']=False
  with self.assertRaisesRegex(ocean.OceanBlocked,'empty_native_not_verified'):
   ocean.verified_native_empty_accounts(results)
 def test_missing_page_not_accepted_as_complete(self):
  v=self.response();v['data']['StatsData']['TotalCount']='2'
  with self.assertRaisesRegex(ocean.OceanBlocked,'incomplete_no_guessed_pagination'):self.run_value(v)
  self.assertFalse((self.job['output']/'verification.json').exists())
 def test_duplicate_natural_key_blocked(self):
  v=self.response();s=v['data']['StatsData'];s['TotalCount']='2';s['Rows']*=2
  with self.assertRaisesRegex(ocean.OceanBlocked,'duplicate_or_outside_window'):self.run_value(v)
 def test_outside_selected_window_blocked(self):
  v=self.response();v['data']['StatsData']['Rows'][0]['Dimensions']['stat_time_day']['ValueStr']='2026-10-28'
  with self.assertRaisesRegex(ocean.OceanBlocked,'duplicate_or_outside_window'):self.run_value(v)
 def test_total_mismatch_cannot_make_projection(self):
  v=self.response();v['data']['StatsData']['Totals']['stat_cost']['Value']=10
  with self.assertRaisesRegex(ocean.OceanBlocked,'total_mismatch'):self.run_value(v)
  self.assertFalse((self.job['output']/'api-projection.xlsx').exists())
 def test_new_nonempty_unknown_group_needs_mapping(self):
  self.job['account']=ocean.ACCOUNTS[-1]
  with self.assertRaisesRegex(ocean.OceanBlocked,'needs_mapping'):self.run_value(self.response())
 def test_over_observed_native_limit_blocks_instead_of_guessing_pages(self):
  v=self.response();v['data']['StatsData']['TotalCount']='1001'
  with self.assertRaisesRegex(ocean.OceanBlocked,'bounds_invalid'):self.run_value(v)
 def test_existing_capture_never_overwritten(self):
  self.job['output'].mkdir();sentinel=self.job['output']/'keep';sentinel.write_text('keep')
  with self.assertRaisesRegex(ocean.OceanBlocked,'output_already_exists'):self.run_value(self.response())
  self.assertEqual(sentinel.read_text(),'keep')
 def test_missing_auth_does_not_create_attempt_directory(self):
  self.paths.cookies.unlink()
  with self.assertRaises(AuthSessionMissingError):self.run_value(self.response())
  self.assertFalse(self.job['output'].exists())
 def test_expired_or_missing_login_once_only_business_error_never_login(self):
  for error in [AuthSessionMissingError('missing'),AuthSessionExpiredError('expired')]:
   client=Mock();client.run.side_effect=[error,{'verified':True}];login=Mock();self.assertEqual(ocean.run_authenticated(client,self.root,login=login,**self.job),{'verified':True});login.assert_called_once_with(self.root,start=self.job['start'],through=self.job['through'])
  client=Mock();client.run.side_effect=ocean.OceanBlocked('ocean_http_403');login=Mock()
  with self.assertRaises(ocean.OceanBlocked):ocean.run_authenticated(client,self.root,login=login,**self.job)
  login.assert_not_called()
 def test_cookie_domain_path_expiry_and_injection(self):
  good={'domain':'.chengzijianzhan.cn','path':'/','name':'ok','value':'x','expires':-1}
  other={'domain':'other.example','path':'/','name':'wrong','value':'never','expires':-1}
  self.assertEqual(ocean.cookie_header([other,good]),'ok=x')
  with self.assertRaises(AuthSessionExpiredError):ocean.cookie_header([{**good,'expires':1}],timestamp=2)
  with self.assertRaises(ocean.OceanBlocked):ocean.cookie_header([{**good,'value':'x\r\nSecret: bad'}])
if __name__=='__main__':unittest.main()
