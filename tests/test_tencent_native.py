from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import tempfile,json,hashlib
import unittest
from data_acquisition.connectors.advertising.tencent_native import read_native_rows,inspect_report,HEADERS
from data_acquisition.jobs.intake_advertising import intake
from data_acquisition.connectors.advertising.native_exports import adopt_download_path,ExportError

CSV=','.join(HEADERS)+'\n2026-09-01,1,1,100%,2.5,2.50\n'
NOW=datetime(2026,10,28,15,0,tzinfo=ZoneInfo('Asia/Shanghai'))

class TencentNativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.file=self.root/'native.csv';self.file.write_text(CSV,encoding='utf-8-sig')
    def inspect(self,**kw):
        args=dict(account_id='74749810',product_scope='legacy_search',time_basis='播放口径',start_date='2026-09-01',through_date='2026-10-27');args.update(kw);return inspect_report(self.file,**args)
    def item(self,scope='legacy_search'):
        return dict(source='tencent_ads_abroad',status='downloaded',captured_at=NOW.isoformat(),account_ids=['74749810'],selected_window=['2026-09-01','2026-10-27'],native_file=str(self.file),sha256=hashlib.sha256(self.file.read_bytes()).hexdigest(),native_format='tencent_account_csv',product_scope=scope,time_basis='播放口径',completion={'verified':False,'through_date':None,'basis':'product_scope_only'})
    def receive(self,items):
        inv=self.root/'inventory.json';inv.write_text(json.dumps({'as_of_date':'2026-10-28','captures':items}));return intake(inv,self.root/'out',now=NOW)
    def test_native_bom_and_decimal_are_preserved(self):
        result=self.inspect();self.assertEqual(result['total'],'2.50');self.assertFalse(result['whole_account_complete']);self.assertFalse(result['registration_performed'])
    def test_missing_days_are_not_materialized_as_zero(self):
        result=self.inspect(product_scope='display_plus');self.assertEqual(result['rows'],1);self.assertEqual(len(result['missing_selected_dates']),56);self.assertFalse(result['scope_dates_complete']);self.assertEqual(len(result['rows_data']),1)
    def test_full_date_scope_does_not_prove_whole_account(self):
        result=self.inspect(through_date='2026-09-01');self.assertTrue(result['scope_dates_complete']);self.assertFalse(result['whole_account_complete'])
    def test_account_product_and_time_basis_are_required(self):
        for kw in [{'account_id':'1'},{'product_scope':'all_products'},{'time_basis':'转化口径'}]:
            with self.subTest(kw=kw),self.assertRaisesRegex(ValueError,'scope_unverified'):self.inspect(**kw)
    def test_duplicate_account_day_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate_day'):read_native_rows((CSV+CSV.splitlines()[1]+'\n').encode())
    def test_bad_header_html_and_nonfinite_spend_are_rejected(self):
        for raw in [b'<html>login</html>',CSV.replace('花费','现金').encode(),CSV.replace('2.50','NaN').encode()]:
            with self.subTest(raw=raw[:10]),self.assertRaises(ValueError):read_native_rows(raw)
    def test_selected_window_cannot_silently_filter_native_rows(self):
        with self.assertRaisesRegex(ValueError,'outside_selected_window'):self.inspect(start_date='2026-09-02')
    def test_csv_path_adoption_is_explicit_and_does_not_modify_original(self):
        before=self.file.read_bytes();saved=adopt_download_path(self.file,self.root/'copy.csv',file_format='tencent_account_csv');self.assertEqual(Path(saved['path']).read_bytes(),before);self.assertEqual(self.file.read_bytes(),before)
        with self.assertRaises(ExportError):adopt_download_path(self.file,self.root/'wrong.xlsx')
    def test_intake_keeps_two_product_scopes_separate_without_sum_or_registration(self):
        result=self.receive([self.item(),self.item('display_plus')]);self.assertEqual(len(result['captures']),2);self.assertEqual({r['product_scope'] for r in result['captures']},{'legacy_search','display_plus'});self.assertTrue(all(r['file']['path'].endswith('.csv') for r in result['captures']));self.assertFalse(result['aggregation_performed']);self.assertFalse(result['production_ready']);self.assertFalse(result['registration_performed'])
    def test_same_scope_script_ui_duplicate_remains_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate_logical_capture'):self.receive([self.item(),self.item()])
    def test_missing_scope_cannot_receive_arbitrary_csv(self):
        item=self.item();item.pop('product_scope')
        with self.assertRaisesRegex(ValueError,'product_scope_missing'):self.receive([item])

if __name__=='__main__':unittest.main()
