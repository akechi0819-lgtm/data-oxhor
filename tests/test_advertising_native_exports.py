from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from openpyxl import Workbook
from zoneinfo import ZoneInfo

from data_acquisition.connectors.advertising import native_exports as e


class Download:
    def __init__(self, data): self.data = data
    def save_as(self, path): Path(path).write_bytes(self.data)
    def failure(self): return None


class Pending:
    def __init__(self, page): self.page, self.value = page, Download(page.raw)
    def __enter__(self): self.page.events.append('expect_download'); return self
    def __exit__(self, *args): pass


class Locator:
    def __init__(self, page, key, index=None): self.page, self.key, self.index = page, key, index
    def nth(self, index): return Locator(self.page, self.key, index)
    @property
    def first(self): return self
    def fill(self, text): self.page.events.append('fill:' + text); self.page.inputs[self.index] = text
    def input_value(self): return self.page.inputs[self.index]
    def press(self, key): self.page.events.append('press:' + key)
    def click(self, **kwargs): self.page.events.append('click:' + self.key)
    def count(self): return 8 if self.key == 'role:textbox' else 1
    def is_visible(self): return True
    def is_enabled(self): return True
    def wait_for(self, **kwargs): self.page.events.append('visible:' + self.key)
    def filter(self, **kwargs):
        key = str(kwargs.get('has_text', self.key))
        self.page.events.append('filter:' + key)
        return Locator(self.page, 'filtered:' + key)
    def get_by_text(self, text, **kwargs): return Locator(self.page, str(text))
    def all_text_contents(self): return self.page.row_sets[self.page.reloads]
    def inner_text(self, **kwargs): return self.page.body


class Page:
    def __init__(self, raw, context, rows=None, title='汇报202610SEM', body=''):
        self.raw, self.context = raw, context
        self.events, self.inputs = [], {}
        self.row_sets = rows or [[]]
        self.reloads = 0
        self._title, self.body = title, body
    def get_by_role(self, role, name=None, **kwargs): return Locator(self, 'role:' + role if name is None else name)
    def get_by_text(self, text, **kwargs): return Locator(self, text)
    def locator(self, selector): return Locator(self, selector)
    def frame_locator(self, selector): self.events.append('frame:' + selector); return self
    def title(self): return self._title
    def reload(self, **kwargs): self.reloads = min(self.reloads + 1, len(self.row_sets) - 1)
    def wait_for_timeout(self, ms): self.events.append('poll')
    def expect_download(self, **kwargs): return Pending(self)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = object()
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        self.start, self.end = today - timedelta(days=2), today - timedelta(days=1)
        book = Workbook()
        book.active.append(['周期', '投放ID', '账户类型', '广告主账户ID', '总消耗'])
        for day in (self.start, self.end):
            book.active.append([day.strftime('%Y%m%d'), '123', '代理商子账户', 'brand', 2])
            book.active.append([day.strftime('%Y%m%d'), '999', '品牌主账户', 'brand', 0])
        path = self.root / 'fixture.xlsx'
        book.save(path)
        self.raw = path.read_bytes()
        stamp = datetime.now(e.SHANGHAI).strftime('%Y-%m-%d %H:%M:%S')
        self.old = f'T20261027001115 组织 推广数据导出 聚光 成功 2026-10-27 12:19:36 结果导出'
        self.waiting = f'T20261028000001 组织 推广数据导出 聚光 生成中 {stamp}'
        self.done = f'T20261028000001 组织 推广数据导出 聚光 成功 {stamp} 结果导出'
    def run_xhs(self, rows=None, accounts=('123',), **kwargs):
        self.report = Page(self.raw, self.context)
        self.tasks = Page(self.raw, self.context, rows or [[self.old], [self.old, self.waiting], [self.old, self.done]])
        return e.download_xhs(self.report, self.tasks, start_date=self.start.isoformat(), through_date=self.end.isoformat(),
            expected_accounts=accounts, organization='组织', destination=self.root/'download.xlsx', **kwargs)
    def test_xhs_new_task_bound_not_old_success(self):
        result = self.run_xhs()
        self.assertEqual(result['task_id'], 'T20261028000001')
        self.assertTrue(result['completion']['complete'])
        self.assertIn('filter:T20261028000001', self.tasks.events)
        self.assertLess(self.tasks.events.index('expect_download'), self.tasks.events.index('click:结果导出'))
        self.assertEqual(result['account_ids'], ['123'])
        self.assertTrue(Path(result['files'][0]['path']).exists())
    def test_xhs_missing_native_account_rejected(self):
        with self.assertRaisesRegex(e.ExportError, 'account_scope_mismatch'): self.run_xhs(accounts=('123', '456'))
    def test_xhs_two_new_tasks_rejected(self):
        other = self.done.replace('T20261028000001', 'T20261028000002')
        with self.assertRaisesRegex(e.ExportError, 'new_task_ambiguous'): self.run_xhs([[self.old], [self.old,self.done,other]])
        self.assertNotIn('expect_download', self.tasks.events)
    def test_xhs_old_task_never_downloaded_on_timeout(self):
        with mock.patch.object(e.time, 'monotonic', side_effect=[0, 0, 2]):
            with self.assertRaisesRegex(e.ExportError, 'task_timeout'): self.run_xhs([[self.old],[self.old]], timeout_sec=1)
        self.assertNotIn('expect_download', self.tasks.events)
    def test_xhs_bound_failure_rejected(self):
        with self.assertRaisesRegex(e.ExportError, 'task_failed'): self.run_xhs([[self.old], [self.old,self.waiting.replace('生成中','失败')]])
    def test_xhs_wrong_context_rejected_before_click(self):
        report, tasks = Page(self.raw, object()), Page(self.raw, object())
        with self.assertRaisesRegex(e.ExportError, 'same_context'):
            e.download_xhs(report,tasks,start_date=self.start.isoformat(),through_date=self.end.isoformat(),expected_accounts=['123'],organization='组织',destination=self.root/'x.xlsx')
        self.assertFalse(report.events)
    def test_xhs_native_missing_day_rejected(self):
        b=Workbook(); b.active.append(['周期','投放ID','账户类型','广告主账户ID','总消耗'])
        b.active.append([self.start.strftime('%Y%m%d'),'123','代理商子账户','brand',1]); p=self.root/'gap.xlsx';b.save(p)
        with self.assertRaisesRegex(e.ExportError,'day_missing'):e.inspect_xhs(p,self.start,self.end,['123'])
    def test_xhs_window_readback_mismatch_rejected(self):
        class Wrong(Locator):
            def input_value(self): return '1900-01-01'
            def nth(self,i): return Wrong(self.page,self.key,i)
        page=Page(self.raw,self.context)
        page.get_by_role=lambda role,**kwargs: Wrong(page,'role:'+role)
        with self.assertRaisesRegex(e.ExportError,'window_not_applied'):e._select_xhs_window(page,self.start,self.end)
    def sem(self, complete=False):
        b=Workbook();b.active.title='SEM总计';b.create_sheet('2665');b.create_sheet('bing');p=self.root/'sem-source.xlsx';b.save(p)
        page=Page(p.read_bytes(),self.context,body='已更新至'+self.end.isoformat() if complete else '最后编辑时间 18:00')
        result=e.download_sem(page,destination=self.root/'sem.xlsx',workbook_title='汇报202610SEM',expected_sheets=['SEM总计','2665','bing'],start_date=self.start.isoformat(),through_date=self.end.isoformat())
        return result,page
    def test_sem_whole_workbook_and_download_event_registered_first(self):
        result,page=self.sem()
        self.assertIn('click::text-is("菜单"):visible', page.events)
        self.assertLess(page.events.index('expect_download'),page.events.index('click:Excel (.xlsx，表格整体)'))
        self.assertFalse(result['completion']['complete'])
        self.assertEqual(result['completion']['basis'],'download_only')
        self.assertIn('frame:#wiki-new-sheet-iframe',page.events)

    def test_sem_menu_uses_one_visible_exact_frame_scoped_target(self):
        result, page = self.sem()
        self.assertEqual(result['status'], 'success')
        self.assertIn('click::text-is("菜单"):visible', page.events)
        self.assertFalse(any('.first' in event or '.nth(' in event for event in page.events))

    def test_sem_waits_for_delayed_menu_layers_before_counting(self):
        book = Workbook()
        book.active.title = 'SEM总计'
        book.create_sheet('2665')
        book.create_sheet('bing')
        source = self.root / 'delayed-menu-fixture.xlsx'
        book.save(source)
        page = Page(source.read_bytes(), self.context)
        ready = {'菜单': True}
        previous = {'clicked': None}
        expected_previous = {
            '表格': '菜单',
            '下载为': '表格',
            'Excel (.xlsx，表格整体)': '下载为',
        }

        class DelayedLocator:
            def __init__(self, label): self.label = label
            def wait_for(self, **_kwargs):
                expected = expected_previous.get(self.label)
                if expected is not None:
                    if previous['clicked'] != expected:
                        raise RuntimeError('menu was not opened')
                    ready[self.label] = True
                page.events.append('wait:' + self.label)
            def count(self): return int(ready.get(self.label, False))
            def click(self, **_kwargs):
                if not ready.get(self.label, False):
                    raise RuntimeError('menu item was not visible')
                page.events.append('click:' + self.label)
                previous['clicked'] = self.label

        original_get_by_text = page.get_by_text
        def get_by_text(label, **kwargs):
            if label == 'Excel (.xlsx，表格整体)':
                return DelayedLocator(label)
            return original_get_by_text(label, **kwargs)
        page.get_by_text = get_by_text

        with mock.patch.object(
            e, 'visible_exact_text_locator', side_effect=lambda _frame, label: DelayedLocator(label)
        ):
            result = e.download_sem(
                page, destination=self.root/'delayed-sem.xlsx', workbook_title='汇报202610SEM',
                expected_sheets=['SEM总计', '2665', 'bing'],
                start_date=self.start.isoformat(), through_date=self.end.isoformat())

        self.assertEqual(result['status'], 'success')
        self.assertEqual([event for event in page.events if event.startswith('wait:')], [
            'wait:菜单', 'wait:表格', 'wait:下载为', 'wait:Excel (.xlsx，表格整体)',
        ])
        self.assertEqual([event for event in page.events if event.startswith('click:')], [
            'click:菜单', 'click:表格', 'click:下载为', 'click:Excel (.xlsx，表格整体)',
        ])

    def test_sem_unknown_click_result_is_pending_and_records_last_safe_phase(self):
        page = Page(self.raw, self.context)
        phases = []

        class ClickMayHaveSubmitted(Locator):
            def click(self, **kwargs):
                self.page.events.append('click:' + self.key)
                raise RuntimeError('opaque browser detail')

        original_get_by_text = page.get_by_text
        def get_by_text(text, **kwargs):
            if text == 'Excel (.xlsx，表格整体)':
                return ClickMayHaveSubmitted(page, text)
            return original_get_by_text(text, **kwargs)
        page.get_by_text = get_by_text
        with self.assertRaisesRegex(e.ExportPending, 'sem_export_submission_or_download_unknown'):
            e.download_sem(
                page, destination=self.root/'unknown.xlsx', workbook_title='汇报202610SEM',
                expected_sheets=['2665'], start_date=self.start.isoformat(),
                through_date=self.end.isoformat(), phase_callback=phases.append)
        self.assertEqual(phases, ['export_click_pending'])
        self.assertFalse((self.root/'unknown.xlsx').exists())

    def test_sem_menu_failure_is_diagnosed_before_export_submission(self):
        page = Page(self.raw, self.context)

        class MenuFailure(Locator):
            def click(self, **kwargs):
                raise RuntimeError('opaque browser detail')

        page.frame_locator = lambda _selector: type('Frame', (), {
            'locator': lambda _self, selector: MenuFailure(page, selector),
        })()
        with self.assertRaisesRegex(e.ExportError, 'sem_menu_open_failed'):
            e.download_sem(
                page, destination=self.root/'menu-failed.xlsx', workbook_title='汇报202610SEM',
                expected_sheets=['2665'], start_date=self.start.isoformat(),
                through_date=self.end.isoformat())
        self.assertFalse((self.root/'menu-failed.xlsx').exists())
    def test_sem_actual_explicit_completion_label_used(self):
        result,_=self.sem(complete=True)
        self.assertTrue(result['completion']['complete'])
        self.assertEqual(result['completion']['through_date'],self.end.isoformat())

    def test_sem_observes_only_task_id_from_captured_submit_response(self):
        self.assertEqual(
            e._extract_sem_job_id({'data': {'jobId': '32377865293', 'token': 'do-not-store'}}),
            '32377865293')
        self.assertIsNone(e._extract_sem_job_id({'items': [
            {'jobId': '32377865293'}, {'jobId': '32377865294'}]}))

        book = Workbook()
        book.active.title = 'SEM总计'
        book.create_sheet('2665')
        book.create_sheet('bing')
        source = self.root / 'observer-fixture.xlsx'
        book.save(source)
        page = Page(source.read_bytes(), self.context)
        listeners = {}
        page.on = lambda event, callback: listeners.setdefault(event, []).append(callback)
        page.remove_listener = lambda event, callback: listeners[event].remove(callback)
        response = type('Response', (), {
            'url': 'https://alidocs.dingtalk.com/core/api/document/submitExportJob?secret=fixture',
            'status': 200,
            'request': type('Request', (), {'method': 'POST'})(),
            'json': lambda _self: {'data': {'jobId': '32377865293', 'token': 'do-not-store'}},
        })()

        original_get_by_text = page.get_by_text
        def get_by_text(text, **kwargs):
            if text == 'Excel (.xlsx，表格整体)':
                class SubmittingLocator(Locator):
                    def click(self, **_kwargs):
                        self.page.events.append('click:' + self.key)
                        for callback in list(listeners.get('response', [])):
                            callback(response)
                return SubmittingLocator(page, text)
            return original_get_by_text(text, **kwargs)
        page.get_by_text = get_by_text

        seen = []
        result = e.download_sem(
            page, destination=self.root/'observed-sem.xlsx', workbook_title='汇报202610SEM',
            expected_sheets=['SEM总计', '2665', 'bing'],
            start_date=self.start.isoformat(), through_date=self.end.isoformat(),
            submission_callback=seen.append)
        self.assertEqual(result['task_id'], '32377865293')
        self.assertEqual(seen, [{
            'kind': 'submit', 'http_status': 200,
            'task_id': '32377865293', 'response_body_status': 'parsed',
        }])
        self.assertNotIn('do-not-store', json.dumps(seen))
        self.assertNotIn('fixture', json.dumps(seen))
    def test_sem_wrong_workbook_stops_before_export(self):
        page=Page(self.raw,self.context,title='另一本表')
        with self.assertRaisesRegex(e.ExportError,'title_mismatch'):
            e.download_sem(page,destination=self.root/'sem.xlsx',workbook_title='汇报202610SEM',expected_sheets=['2665'],start_date=self.start.isoformat(),through_date=self.end.isoformat())
        self.assertFalse(page.events)
    def test_invalid_xlsx_download_is_not_accepted(self):
        with self.assertRaisesRegex(e.ExportError,'invalid_xlsx'):
            e._save_download(Download(b'<html>login required</html>'),self.root/'login.xlsx')
    def test_sem_single_sheet_export_is_not_accepted_as_whole(self):
        page=Page(self.raw,self.context)
        with self.assertRaisesRegex(e.ExportError,'whole_workbook_missing_sheets'):
            e.download_sem(page,destination=self.root/'partial.xlsx',workbook_title='汇报202610SEM',expected_sheets=['2665','bing'],start_date=self.start.isoformat(),through_date=self.end.isoformat())
    def test_existing_download_is_never_overwritten(self):
        p=self.root/'existing.xlsx';p.write_bytes(b'original')
        with self.assertRaisesRegex(e.ExportError,'destination_already_exists'):e._save_download(Download(self.raw),p)
        self.assertEqual(p.read_bytes(),b'original')


class NativePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = self.root / 'native.xlsx'
        book = Workbook()
        book.active.append(['native row'])
        book.save(self.native)
        self.original = self.native.read_bytes()
        self.target = self.root / 'capture' / 'copied.xlsx'

    def test_cua_path_only_object_is_adopted_without_save_as(self):
        class PathOnlyDownload:
            def __init__(self, path): self.value = path
            def path(self): return str(self.value)
        downloaded = PathOnlyDownload(self.native)
        self.assertFalse(hasattr(downloaded, 'save_as'))
        receipt = e.adopt_download_path(downloaded.path(), self.target)
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(receipt['sha256'], e.hashlib.sha256(self.original).hexdigest())
        self.assertEqual(receipt['path'], str(self.target.resolve()))

    def test_html_or_empty_native_path_does_not_create_target(self):
        for raw in (b'<html>login required</html>', b''):
            self.native.write_bytes(raw)
            with self.assertRaisesRegex(e.ExportError, 'invalid_xlsx'):
                e.adopt_download_path(str(self.native), self.target)
            self.assertFalse(self.target.exists())
            self.assertEqual(self.native.read_bytes(), raw)

    def test_repeated_destination_refuses_second_registration(self):
        first = e.adopt_download_path(str(self.native), self.target)
        with self.assertRaisesRegex(e.ExportError, 'destination_already_exists'):
            e.adopt_download_path(str(self.native), self.target)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(first['sha256'], e.hashlib.sha256(self.original).hexdigest())

    def test_browser_private_path_rejected_before_read(self):
        private = self.root / 'Library' / 'Application Support' / 'Google' / 'Chrome' / 'private.xlsx'
        with mock.patch.object(e, '_validate_xlsx', side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(e.ExportError, 'native_download_path_invalid'):
                e.adopt_download_path(str(private), self.target)
        self.assertFalse(self.target.exists())

    def test_save_as_and_native_path_use_identical_validation(self):
        with mock.patch.object(e, '_validate_xlsx', wraps=e._validate_xlsx) as validate:
            first = e._save_download(Download(self.original), self.target)
            self.assertEqual(validate.call_count, 1)
            other = self.root / 'second.xlsx'
            second = e.adopt_download_path(str(self.native), other)
            self.assertEqual(validate.call_count, 3)
        self.assertEqual(first['sha256'], second['sha256'])

if __name__=='__main__':unittest.main()
