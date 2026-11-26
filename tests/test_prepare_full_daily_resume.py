import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from data_acquisition.jobs.fee_sources import resume_ocean_account
from data_acquisition.ops_io import DailyBlocked,digest
class ResumeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name);self.file=self.p/'projection.xlsx';self.file.write_bytes(b'confirmed projection');self.raw=self.p/'page.json';self.raw.write_text('{}');self.value={'account_id':'known','selected_window':['2026-09-01','2026-10-28'],'captured_at':'2026-10-29T00:34:00+08:00','file':{'path':str(self.file),'sha256':digest(self.file)},'query_pages':[{'path':str(self.raw),'sha256':digest(self.raw)}]};self.proof=self.p/'verification.json';self.proof.write_text(json.dumps(self.value));self.client=Mock();self.args=dict(account=('known','abroad','留学整体'),start='2026-09-01',through='2026-10-28',output=self.p,day='2026-10-29')
 def test_verified_account_not_requested_again_after_later_account_failure(self):
  self.assertEqual(resume_ocean_account(self.client,**self.args),self.value);self.client.run.assert_not_called()
 def test_raw_tamper_stops_resume_without_reexport(self):
  self.raw.write_text('{"changed":true}')
  with self.assertRaisesRegex(DailyBlocked,'partial_input_changed'):resume_ocean_account(self.client,**self.args)
  self.client.run.assert_not_called()
 def test_old_date_cannot_be_relabelled_today(self):
  self.args['day']='2026-10-30'
  with self.assertRaisesRegex(DailyBlocked,'partial_not_today'):resume_ocean_account(self.client,**self.args)
  self.client.run.assert_not_called()
 def test_missing_proof_uses_existing_real_adapter_once(self):
  self.proof.unlink();self.client.run.return_value={'fresh':True};self.assertEqual(resume_ocean_account(self.client,**self.args),{'fresh':True});self.client.run.assert_called_once()
