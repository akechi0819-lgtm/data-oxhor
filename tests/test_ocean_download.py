from datetime import date
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from openpyxl import Workbook

from data_acquisition.connectors.advertising import ocean_download as ocean
HEAD = ('项目ID','项目名称','日期','营销场景','投放类型','消耗(元)','展示次数','点击次数','点击率','平均千次展示费用(元)','线索留资数(计费时间)','线索留资成本(计费时间)','确认意向数(计费时间)','确认意向成本(计费时间)','预付定金数(计费时间)','预付定金成本(计费时间)','私信意向数(计费时间)','私信意向成本(计费时间)')


def native(path, start, *, empty=False, duplicate=False, amount='12.00'):
    book = Workbook(); sheet = book.active
    if empty:
        sheet.append(HEAD[5:]); sheet.append(['-']*13)
    else:
        sheet.append(HEAD); sheet.append([None]*5+[amount]+[None]*12)
        row = ['123','项目',start,'短视频','通投',amount]+[0]*12
        sheet.append(row)
        if duplicate:sheet.append(row)
    book.save(path)


class Node:
    def __init__(self, page, kind, value=None):self.p,self.kind,self.value=page,kind,value
    @property
    def first(self):return self
    def nth(self,n):return Node(self.p,self.kind,n)
    def get_by_role(self,role,**kwargs):return Node(self.p,'summary_cells')
    def wait_for(self,**kwargs):
        if self.kind=='identity' and self.p.wrong_identity:raise TimeoutError('auth material must not leak')
    def input_value(self):
        return {'start':self.p.window[0],'end':self.p.window[1],'grain':self.p.grain}[self.kind]
    def inner_text(self):return '门店账户 ID：'+self.p.account
    def is_visible(self):return self.kind in ('month','identity') or self.kind=='empty' and self.p.empty
    def count(self):
        if self.kind!='day':return 1
        d=date.fromisoformat(self.value)
        return int(d.year==2026 and d.month in (self.p.month,self.p.month+1))
    def all(self):return [Node(self.p,'month',str(self.p.month)+'月')]
    def all_text_contents(self):
        total='1.00' if self.p.window!=self.p.target else self.p.ui_total
        return ['共1条数据',total]
    def click(self):
        self.p.events.append(('click',self.kind,self.value))
        if self.kind=='day':
            self.p.window[self.p.date_index]=self.value
            self.p.date_index+=1
        elif self.kind=='start':self.p.date_index=0
        elif self.kind=='end':self.p.date_index=1
        elif self.kind=='choose_day_grain':self.p.grain='分日'
        elif self.kind=='month':self.p.month=int(self.value[:-1])
        elif self.kind=='download':
            if not self.p.armed:raise AssertionError('expect_download must be registered first')
            self.p.download_clicked=True


class Download:
    def __init__(self,page):self.p=page
    def save_as(self,path):
        if not self.p.download_clicked:raise AssertionError('download not clicked')
        native(path,self.p.window[0],empty=self.p.empty,duplicate=self.p.duplicate,amount=self.p.file_total)
        self.p.events.append(('saved',str(path)))
        if self.p.switch_during_download:self.p.account='999'


class Expect:
    def __init__(self,p):self.p=p
    def __enter__(self):self.p.events.append(('expect_download',));self.p.armed=True;return self
    def __exit__(self,*args):self.p.armed=False
    @property
    def value(self):return Download(self.p)


class Page:
    def __init__(self, *, target=('2026-09-01','2026-10-27'), empty=False):
        self.target=list(target);self.window=['2026-10-20','2026-10-27'];self.month=10;self.grain='合计'
        self.account='';self.empty=empty;self.events=[];self.armed=False;self.download_clicked=False
        self.ui_total=self.file_total='12.00';self.duplicate=False;self.wrong_identity=False;self.switch_during_download=False
    def goto(self,url,**kwargs):self.account=url.split('advid=')[1];self.events.append(('goto',url))
    def get_by_role(self,role,**kwargs):
        name=kwargs.get('name')
        if role=='button':return Node(self,'identity')
        if role=='row':return Node(self,'row')
        if role=='columnheader':return Node(self,'columnheader')
        return Node(self,{'开始时间':'start','结束时间':'end','请选择':'grain'}[name])
    def get_by_placeholder(self,name,**kwargs):
        return Node(self,{'开始时间':'start','结束时间':'end'}[name])
    def get_by_text(self,text,**kwargs):
        if isinstance(text,re.Pattern):return Node(self,'month',str(self.month)+'月')
        return Node(self,{'项目':'project','暂无数据':'empty','分日':'choose_day_grain'}.get(text,'month'),text)
    def locator(self,selector):
        if selector=='[name="StandardDownloadBtn"]':return Node(self,'download')
        return Node(self,'day',re.search(r'title="([0-9-]+)"',selector)[1])
    def expect_download(self,**kwargs):return Expect(self)


def no_sleep(_):pass


class OceanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.sleep_patch=mock.patch.object(ocean.time,'sleep',no_sleep);self.sleep_patch.start();self.addCleanup(self.sleep_patch.stop)
    def capture(self,page,**kwargs):
        return ocean.export_account(page,account=kwargs.pop('account',ocean.ACCOUNTS[0]),
            start_date=page.target[0],through_date=page.target[1],output_dir=self.tmp.name,poll=0,settle_timeout=.01,**kwargs)
    def test_download_is_armed_first_and_native_total_verified(self):
        p=Page();r=self.capture(p)
        self.assertEqual(r['rows'],1);self.assertEqual(r['total'],'12.0')
        self.assertLess(p.events.index(('expect_download',)),next(i for i,e in enumerate(p.events) if e[:2]==('click','download')))
        self.assertEqual(r['start_date'],'2026-09-01');self.assertEqual(p.grain,'分日')
        self.assertLess(p.events.index(('click','end',None)),p.events.index(('click','day','2026-10-27')))
        self.assertTrue(Path(r['evidence']['path']).exists())
    def test_next_day_is_not_hardcoded_26(self):
        p=Page(target=('2026-10-01','2026-10-28'));r=self.capture(p)
        self.assertEqual(r['through_date'],'2026-10-28');self.assertEqual(p.window[1],'2026-10-28')
    def test_native_and_ui_total_mismatch_blocks_capture(self):
        p=Page();p.file_total='11.00'
        with self.assertRaisesRegex(ocean.OceanCaptureError,'native_summary_mismatch'):self.capture(p)
        self.assertFalse((Path(self.tmp.name)/ocean.ACCOUNTS[0][0]/'capture.json').exists())
    def test_project_duplicate_key_rejected(self):
        p=Page();p.duplicate=True
        with self.assertRaisesRegex(ocean.OceanCaptureError,'native_download_failed:ValueError'):self.capture(p)
    def test_wrong_account_or_login_never_clicks_download(self):
        p=Page();p.wrong_identity=True
        with self.assertRaisesRegex(ocean.OceanCaptureError,'native_download_failed:TimeoutError'):self.capture(p)
        self.assertFalse(p.download_clicked)
    def test_account_change_during_download_blocks_capture(self):
        p=Page();p.switch_during_download=True
        with self.assertRaisesRegex(ocean.OceanCaptureError,'account_changed_during_download'):self.capture(p)

    def test_empty_native_preserved_without_project_rows(self):
        p=Page(empty=True);r=self.capture(p,account=ocean.ACCOUNTS[-1])
        self.assertEqual(r['rows'],0);self.assertTrue(r['native_empty']);self.assertEqual(r['total'],'0.00')
    def test_previous_empty_account_cannot_silently_gain_group(self):
        with self.assertRaisesRegex(ocean.OceanCaptureError,'previously_empty_account_now_needs_business_mapping'):
            self.capture(Page(),account=ocean.ACCOUNTS[-1])
    def test_unverified_year_control_fails_closed(self):
        p=Page(target=('2025-12-01','2026-10-27'))
        with self.assertRaisesRegex(ocean.OceanCaptureError,'calendar_year_or_day_unavailable'):self.capture(p)
        self.assertFalse(p.download_clicked)
    def test_export_all_covers_exact_seven_accounts_serially(self):
        events=[]
        def exported(page,**kwargs):
            aid=kwargs['account'][0];events.append(('start',aid));events.append(('done',aid))
            return {'account_id':aid}
        with mock.patch.object(ocean,'export_account',exported):
            result=ocean.export_all(Page(),start_date='2026-09-01',through_date='2026-10-27',output_dir=self.tmp.name)
        ids=[a[0] for a in ocean.ACCOUNTS]
        self.assertEqual(result['account_ids'],ids)
        self.assertEqual(len(result['accounts']),7)
        self.assertEqual(events,[(label,aid) for aid in ids for label in ('start','done')])

    def test_stale_summary_cannot_be_called_settled(self):
        p=Page();p.ui_total='1.00'
        with self.assertRaisesRegex(ocean.OceanCaptureError,'summary_did_not_settle'):self.capture(p)
        self.assertFalse(p.download_clicked)


if __name__=='__main__':unittest.main()
