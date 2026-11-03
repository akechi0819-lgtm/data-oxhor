import json,tempfile,unittest,hashlib
from pathlib import Path
from openpyxl import Workbook
from data_acquisition.connectors.advertising.sem_candidate import stage_sem,load_sem_bundle
from dashboard_product.shadow_bi.p5.full_daily import validate_capture,DailyBlocked
class SemBridgeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name);self.native=self.r/'original.xlsx';b=Workbook();s=b.active;s.title='mapped';s.append(['时间','消费','现金消费']);s.append(['2026-10-28',10,8]);b.save(self.native);self.manifest=self.r/'mapping.json';self.entry={'source_id':'sem_existing','kind':'sem_daily','path':'old.xlsx','start_date':'2026-10-01','end_date':'2026-10-27','sheets':{'mapped':{'business_line':'abroad','business_group':'留学整体','platform':'百度'}}};self.manifest.write_text(json.dumps({'sources':[self.entry]}));self.output=self.r/'sample'
 def stage(self,**kw):return stage_sem(self.native,self.manifest,self.output,start='2026-10-28',through='2026-10-28',**kw)
 def test_actual_bytes_and_mapping_preserved_without_fake_capture(self):
  before=self.native.read_bytes();v=self.stage();self.assertTrue(v['sample_only']);self.assertEqual(v['rows'],1);self.assertEqual(self.native.read_bytes(),before);source=json.loads(Path(v['capture']).read_text())['sources'][0];self.assertIsNone(source['captured_at']);self.assertFalse(source['completion']['complete']);self.assertEqual(source['status'],'sample_only')
 def test_sample_never_passes_production_capture_gate(self):
  v=self.stage();capture=json.loads(Path(v['capture']).read_text())
  with self.assertRaisesRegex(DailyBlocked,'capture_time_missing:sem'):validate_capture(capture,{'sem':{}},'2026-10-29',self.output)
 def test_relative_manifest_and_native_paths_resolve_from_receipt(self):
  self.stage();p=self.output/'capture.json';v=json.loads(p.read_text());v['manifest_path']='candidate-sources.json';p.write_text(json.dumps(v));q=self.output/'candidate-sources.json';v=json.loads(q.read_text());v['sources'][0]['path']='native.xlsx';q.write_text(json.dumps(v));entries,_=load_sem_bundle(p);self.assertEqual(entries[0]['path'],str((self.output/'native.xlsx').resolve()))
 def test_wrong_source_cannot_hide_under_sem_receipt(self):
  self.stage();q=self.output/'candidate-sources.json';v=json.loads(q.read_text());v['sources'][0]['kind']='ocean_daily';q.write_text(json.dumps(v))
  with self.assertRaisesRegex(ValueError,'manifest_scope_invalid'):load_sem_bundle(self.output/'capture.json')
 def test_collector_mismatched_file_is_rejected_before_staging(self):
  p=self.r/'capture.json';p.write_text(json.dumps({'source_id':'sem','status':'success','start_date':'2026-10-28','through_date':'2026-10-28','account_ids':['mapped'],'files':[]}))
  with self.assertRaisesRegex(ValueError,'collector_file_mismatch'):self.stage(capture=p)
  self.assertFalse(self.output.exists())
