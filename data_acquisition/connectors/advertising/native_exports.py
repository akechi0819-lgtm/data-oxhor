"""Native webpage exports using caller-owned, normally authenticated Playwright pages.

No browser launch, cookie access, login persistence, warehouse writes or publishing.
Selectors are from the project's 2026-10-26/27 successful browser transcripts;
these implementations still require live validation in the current login session.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
from io import BytesIO
import shutil
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from zipfile import ZipFile, BadZipFile

SHANGHAI = ZoneInfo('Asia/Shanghai')
TASK_ID = re.compile(r'\bT\d{12,}\b')
STAMP = re.compile(r'\b(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\b')


class ExportError(RuntimeError):
    """Fixed diagnostics; never include URLs, authentication state or page HTML."""

    def __init__(self, message, *, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics


class ExportPending(ExportError):
    """An export may have been submitted; inspect its state before any retry."""


def _window(start, through):
    start, through = date.fromisoformat(start), date.fromisoformat(through)
    if through < start:
        raise ExportError('window_reversed')
    if through >= datetime.now(SHANGHAI).date():
        raise ExportError('window_not_closed')
    return start, through


def _text(page):
    return page.locator('body').inner_text(timeout=10000)


def _validate_xlsx(path):
    try:
        raw = Path(path).read_bytes()
        if not raw:
            raise ExportError('invalid_xlsx')
        with ZipFile(BytesIO(raw)) as book:
            if book.testzip() is not None or 'xl/workbook.xml' not in book.namelist():
                raise ExportError('invalid_xlsx')
    except (OSError, ValueError, BadZipFile):
        raise ExportError('invalid_xlsx') from None
    return hashlib.sha256(raw).hexdigest()


def _save_download(download, destination):
    destination = Path(destination)
    if destination.exists():
        raise ExportError('destination_already_exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(destination))
    if download.failure():
        raise ExportError('download_failed')
    return {'path': str(destination.resolve()), 'sha256': _validate_xlsx(destination)}


def adopt_download_path(native_path, destination, *, file_format="xlsx"):
    """Adopt the explicit path returned by CUA download.path(); no UI or cookie I/O."""
    source, target = Path(native_path), Path(destination)
    parts = {part.casefold() for part in source.resolve().parts}
    if (not source.is_absolute() or source.is_symlink()
            or {'.private', 'cookies', 'local state', 'authsessions', 'auth_sessions', 'browser_profiles', 'login data'}.intersection(parts)
            or {'application support', 'chrome'}.issubset(parts)):
        raise ExportError('native_download_path_invalid')
    if target.exists():
        raise ExportError('destination_already_exists')
    def validate(path):
        if file_format == 'xlsx':
            return _validate_xlsx(path)
        if file_format != 'tencent_account_csv':
            raise ExportError('native_format_invalid')
        from .tencent_native import read_native_rows
        try:
            raw = Path(path).read_bytes()
            read_native_rows(raw)
        except (OSError, ValueError):
            raise ExportError('tencent_csv_invalid') from None
        return hashlib.sha256(raw).hexdigest()
    expected = validate(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open('rb') as original, target.open('xb') as copied:
            shutil.copyfileobj(original, copied)
    except FileExistsError:
        raise ExportError('destination_already_exists') from None
    if validate(target) != expected:
        raise ExportError('native_download_changed')
    return {'path': str(target.resolve()), 'sha256': expected}


def open_xhs_tasks(page):
    """Caller supplies a SECOND page already on the normal star-fire home.

    The first toolbar button opened the task centre in the verified transcript.
    Reject an unexpected target immediately instead of clicking further controls.
    """
    page.get_by_role('button').nth(0).click(timeout=10000)
    page.get_by_text('任务编号', exact=True).wait_for(state='visible', timeout=10000)


def _task_rows(page):
    rows = {}
    for text in page.get_by_role('row').all_text_contents():
        found = TASK_ID.search(text)
        if found:
            if found.group() in rows:
                raise ExportError('duplicate_task_id')
            rows[found.group()] = text
    return rows


def _select_xhs_window(page, start, through):
    # Filling alone did not submit the filter in the successful 27 October run.
    boxes = page.get_by_role('textbox')
    if boxes.count() < 8:
        raise ExportError('xhs_date_layout_changed')
    boxes.nth(6).fill(start.isoformat())
    boxes.nth(7).fill(through.isoformat())
    boxes.nth(7).press('Enter')
    boxes.nth(6).click()
    for chosen in (start, through):
        calendar = page.locator('.d-datepicker-calendar').filter(
            has=page.get_by_role('heading', name=f'{chosen.month}月', exact=True))
        if calendar.count() != 1:
            raise ExportError('xhs_calendar_month_ambiguous')
        calendar.get_by_text(str(chosen.day), exact=True).first.click()
    if (boxes.nth(6).input_value(), boxes.nth(7).input_value()) != (start.isoformat(), through.isoformat()):
        raise ExportError('xhs_window_not_applied')
    page.get_by_role('heading', name='推广数据', exact=True).wait_for(state='visible')


def inspect_xhs(path, start, through, expected_accounts):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book.active
        sheet.reset_dimensions()
        values = iter(sheet.values)
        headers = {str(v).strip(): i for i, v in enumerate(next(values, ()))}
        if not {'周期', '投放ID', '账户类型', '广告主账户ID', '总消耗'} <= headers.keys():
            raise ExportError('xhs_native_columns_missing')
        accounts, seen, total = set(), set(), Decimal(0)
        days = {(start + timedelta(days=i)).strftime('%Y%m%d') for i in range((through-start).days+1)}
        for row in values:
            if not any(v is not None for v in row):
                continue
            get = lambda key: row[headers[key]]
            day = str(get('周期')).strip()
            if day not in days:
                raise ExportError('xhs_native_window_mismatch')
            aid = str(get('投放ID')).strip()
            if aid.endswith('.0'):
                aid = aid[:-2]
            if (aid, day) in seen:
                raise ExportError('xhs_native_duplicate_account_day')
            seen.add((aid, day))
            amount = Decimal(str(get('总消耗')).replace(',', ''))
            if get('账户类型') == '品牌主账户':
                if amount:
                    raise ExportError('xhs_master_account_nonzero')
                continue
            if get('账户类型') != '代理商子账户':
                raise ExportError('xhs_account_type_unknown')
            accounts.add(aid)
            total += amount
        if accounts != set(map(str, expected_accounts)):
            raise ExportError('xhs_account_scope_mismatch')
        if any((aid, day) not in seen for aid in accounts for day in days):
            raise ExportError('xhs_native_day_missing')
        return {'account_ids': sorted(accounts), 'amount': str(total), 'days': len(days)}
    finally:
        book.close()


def download_xhs(report_page, task_page, *, start_date, through_date, expected_accounts,
                 organization, destination, timeout_sec=300, poll_sec=2):
    """Submit account/day export and download only the exact newly created task.

    report_page is on '聚光营销分析'; task_page is a separate existing task-centre
    page in the SAME caller-owned context. No current task or old export is reused.
    """
    start, through = _window(start_date, through_date)
    if report_page.context is not task_page.context:
        raise ExportError('xhs_pages_not_same_context')
    if not expected_accounts or not organization:
        raise ExportError('xhs_scope_missing')
    task_page.get_by_text('任务编号', exact=True).wait_for(state='visible', timeout=10000)
    before = set(_task_rows(task_page))
    _select_xhs_window(report_page, start, through)
    started = datetime.now(SHANGHAI)
    report_page.get_by_role('button', name='下载表格', exact=True).click()
    report_page.get_by_text('合计', exact=True).click()
    report_page.get_by_text('天', exact=True).click()
    report_page.get_by_role('button', name='确定', exact=True).click()
    deadline, bound, final_row = time.monotonic() + timeout_sec, None, None
    while time.monotonic() < deadline:
        task_page.reload(wait_until='domcontentloaded')
        task_page.get_by_text('任务编号', exact=True).wait_for(state='visible', timeout=10000)
        rows = _task_rows(task_page)
        if bound is None:
            candidates = []
            for task_id in rows.keys() - before:
                row = rows[task_id]
                stamps = STAMP.findall(row)
                if organization in row and '推广数据导出' in row and '聚光' in row and stamps:
                    created = datetime.strptime(stamps[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=SHANGHAI)
                    if created >= started - timedelta(seconds=5):
                        candidates.append(task_id)
            if len(candidates) > 1:
                raise ExportError('xhs_new_task_ambiguous')
            if candidates:
                bound = candidates[0]
        if bound and bound in rows:
            final_row = rows[bound]
            if '失败' in final_row or '取消' in final_row:
                raise ExportError('xhs_export_task_failed')
            if '成功' in final_row and '结果导出' in final_row:
                break
        task_page.wait_for_timeout(poll_sec * 1000)
    else:
        raise ExportError('xhs_export_task_timeout')
    row = task_page.get_by_role('row').filter(has_text=bound)
    if row.count() != 1:
        raise ExportError('xhs_bound_task_missing')
    with task_page.expect_download(timeout=timeout_sec * 1000) as pending:
        row.get_by_text('结果导出', exact=True).click()
    saved = _save_download(pending.value, destination)
    native = inspect_xhs(saved['path'], start, through, expected_accounts)
    evidence = Path(destination).with_suffix('.evidence.json')
    evidence.write_text(json.dumps({'task_id': bound, 'task_row': final_row,
        'window': [start_date, through_date], 'granularity': '天', 'native': native}, ensure_ascii=False, indent=2))
    return {'source_id': 'xhs', 'status': 'success', 'captured_at': datetime.now(SHANGHAI).isoformat(),
        'start_date': start_date, 'through_date': through_date, 'account_ids': native['account_ids'],
        'files': [saved], 'evidence': {'path': str(evidence.resolve()), 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()},
        'completion': {'complete': True, 'through_date': through_date, 'basis': 'native_export_window'}, 'task_id': bound}


def download_sem(page, *, destination, workbook_title, expected_sheets, start_date, through_date,
                 timeout_sec=180, phase_callback=None, submission_callback=None):
    """Export the current whole SEM workbook through authenticated requests."""
    from .sem_requests import download_sem_requests
    return download_sem_requests(
        page, destination=destination, workbook_title=workbook_title,
        expected_sheets=expected_sheets, start_date=start_date, through_date=through_date,
        timeout_sec=timeout_sec, phase_callback=phase_callback,
        submission_callback=submission_callback,
    )
