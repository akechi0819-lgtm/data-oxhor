from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo
from openpyxl import Workbook
from data_acquisition.jobs import intake_advertising as mod

NOW=datetime(2026,10,28,13,0,tzinfo=ZoneInfo('Asia/Shanghai'))

class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.original=self.root/'native.xlsx'
        b=Workbook();b.active.append(['native']);b.save(self.original)
        self.item={'source':'xhs','status':'downloaded','captured_at':NOW.isoformat(),
            'account_ids':['123'],'selected_window':['2026-09-01','2026-10-27'],
            'native_file':str(self.original),'completion':{'verified':False,'through_date':None,'basis':None},'evidence_files':[]}
    def run_intake(self,items=None,day='2026-10-28',out='received'):
        inv=self.root/'raw_inventory.json';inv.write_text(json.dumps({'as_of_date':day,'captures':items or [self.item]}))
        return mod.intake(inv,self.root/out,now=NOW)
    def test_real_path_is_staged_without_playwright_object_or_original_change(self):
        before=self.original.read_bytes();r=self.run_intake();new=Path(r['captures'][0]['file']['path'])
        self.assertEqual(new.read_bytes(),before);self.assertEqual(self.original.read_bytes(),before)
        self.assertEqual(r['captures'][0]['file']['sha256'],hashlib.sha256(before).hexdigest())
        self.assertFalse(r['registration_performed']);self.assertFalse(r['candidate_built']);self.assertFalse(r['production_ready'])
    def test_incomplete_source_stays_incomplete_not_zero(self):
        r=self.run_intake();self.assertFalse(r['captures'][0]['completion']['verified'])
        self.assertEqual(r['status'],'received_with_gaps');self.assertIn('tencent_ads_abroad',r['missing_required_sources'])
    def test_script_and_ui_duplicate_capture_is_rejected_before_copy(self):
        with self.assertRaisesRegex(ValueError,'duplicate_logical_capture'):self.run_intake([self.item,{**self.item,'route':'cua'}])
        self.assertFalse((self.root/'received').exists())
    def test_existing_output_is_not_overwritten(self):
        self.run_intake()
        with self.assertRaises(FileExistsError):self.run_intake()
    def test_html_or_partial_download_cannot_be_received(self):
        self.original.write_text('<html>login</html>');r=self.run_intake()
        self.assertEqual(r['captures'][0]['status'],'rejected');self.assertFalse(r['published'])
    def test_wrong_declared_digest_is_not_accepted(self):
        self.item['sha256']='0'*64;r=self.run_intake();self.assertEqual(r['captures'][0]['status'],'rejected')
    def test_timezone_and_today_identity_are_required(self):
        self.item['captured_at']='2026-10-28T13:00:00'
        with self.assertRaises(ValueError):self.run_intake()
        with self.assertRaises(ValueError):self.run_intake(day='2026-10-27')
    def test_pending_login_has_no_file_and_is_not_promoted(self):
        self.item.update(source='tencent_ads_abroad',status='login_required',native_file=None)
        r=self.run_intake();self.assertEqual(r['captures'][0]['status'],'login_required')
        self.assertIn('tencent_ads_abroad',r['missing_required_sources'])

if __name__=='__main__':unittest.main()
