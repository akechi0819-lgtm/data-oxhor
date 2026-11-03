"""Download native Ocean Local Ads project/day exports through an authenticated synchronous Playwright page.

No browser launch, profile, cookie access, API reverse engineering or production
registration. Selectors derive from the 2026-10-27 recorded native export route.
"""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo

STANDARD_URL = 'https://localads.chengzijianzhan.cn/lamp/pc/data2/standard?from=%2Flamp%2Fpc%2Fdata2%2FdataCenter&advid='
ACCOUNTS = (
    ('1862323317815369', 'training', '大学'),
    ('1862687614826500', 'training', '高中'),
    ('1872833578712263', 'training', '留学预备'),
    ('1862048006734852', 'abroad', '留学整体'),
    ('1830170629798923', 'abroad', '留学整体'),
    ('1810699393202185', 'abroad', '留学整体'),
    ('1813785787039897', 'training', None),
)


class OceanCaptureError(RuntimeError):
    """Fixed reason codes only; no dependency URL/session text escapes."""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def amount(text):
    return Decimal(str(text).replace(',', '').strip())


def _select_day(page, day):
    """Use the verified month dropdown and native date-cell title.

    Month labels vary with the current page. A year outside the displayed picker
    is deliberately rejected: no unverified year-switch control is guessed.
    """
    selector = f'td[title="{day}"]:visible'
    cell = page.locator(selector)
    if not cell.count():
        labels = page.get_by_text(re.compile(r'^\d{1,2}月$'), exact=True)
        visible = [node for node in labels.all() if node.is_visible()]
        if not visible:
            raise OceanCaptureError('calendar_month_control_unavailable')
        visible[0].click()
        target = page.get_by_text(f'{date.fromisoformat(day).month}月', exact=True)
        target.wait_for(state='visible', timeout=5000)
        target.click()
        if not cell.count():
            raise OceanCaptureError('calendar_year_or_day_unavailable')
    cell.first.click()


def _summary(page):
    if page.get_by_text('暂无数据', exact=True).is_visible():
        return {'count': 0, 'total': '0.00', 'empty': True}
    cells = page.get_by_role('row').nth(1).get_by_role('columnheader').all_text_contents()
    if len(cells) < 2 or not re.search(r'共\s*\d+\s*条数据', cells[0]):
        raise OceanCaptureError('summary_not_ready')
    count = int(re.search(r'共\s*(\d+)\s*条数据', cells[0])[1])
    # Native project summary includes five blank dimension cells before cost.
    total = next((value for value in cells[1:] if value.strip()), '')
    try:
        cost = amount(total)
    except Exception:
        raise OceanCaptureError('summary_cost_not_ready') from None
    return {'count': count, 'total': str(cost), 'empty': False}


def _settled_summary(page, previous, window_changed, timeout, poll):
    deadline, last, stable = time.monotonic() + timeout, None, 0
    while time.monotonic() < deadline:
        try:
            current = _summary(page)
        except OceanCaptureError:
            stable = 0
            time.sleep(poll)
            continue
        # The real high-school export once had new detail rows and an old total.
        # Require the prior nonempty summary to disappear before trusting a new
        # date window. Equal totals may fail closed, never silently publish stale.
        if window_changed and previous and not previous['empty'] and current == previous:
            stable = 0
        elif current == last:
            stable += 1
        else:
            stable = 1
        last = current
        if stable >= 3:
            return current
        time.sleep(poll)
    raise OceanCaptureError('summary_did_not_settle')


def validate_native(path, account, start, end, summary):
    from dashboard_product.management.advertising_sources import _read_rows, _parse_daily
    raw = Path(path).read_bytes()
    table, _ = _read_rows(raw, Path(path))
    expected = ('消耗(元)', '展示次数', '点击次数', '点击率', '平均千次展示费用(元)',
                '线索留资数(计费时间)', '线索留资成本(计费时间)', '确认意向数(计费时间)',
                '确认意向成本(计费时间)', '预付定金数(计费时间)', '预付定金成本(计费时间)',
                '私信意向数(计费时间)', '私信意向成本(计费时间)')
    if summary['empty']:
        if not table or tuple(table[0]) != expected or any(v not in (None, '-') for row in table[1:] for v in row):
            raise OceanCaptureError('empty_native_report_invalid')
        return {'rows': 0, 'total': '0.00', 'native_empty': True}
    if not table or tuple(table[0]) != ('项目ID', '项目名称', '日期', '营销场景', '投放类型') + expected:
        raise OceanCaptureError('native_project_header_changed')
    aid, line, group = account
    if group is None:
        raise OceanCaptureError('previously_empty_account_now_needs_business_mapping')
    item = {'source_id': 'ocean_' + aid, 'resolved_path': Path(path), 'raw': raw,
            'actual_sha256': hashlib.sha256(raw).hexdigest(), 'business_line': line,
            'business_group': group, 'platform': '抖音', 'kind': 'ocean_daily'}
    rows, _ = _parse_daily(item, date_header='日期', amount_header='消耗(元)', ocean=True)
    if any(r['start_date'] < start or r['end_date'] > end or r['amount'] is None for r in rows):
        raise OceanCaptureError('native_window_or_amount_invalid')
    total = sum((Decimal(str(r['amount'])) for r in rows), Decimal(0))
    if len(rows) != summary['count'] or abs(total - amount(summary['total'])) > Decimal('0.011'):
        raise OceanCaptureError('native_summary_mismatch')
    return {'rows': len(rows), 'total': str(total), 'native_empty': False}


def export_account(page, *, account, start_date, through_date, output_dir,
                         settle_timeout=90, poll=0.5):
    """Download one configured account; caller provides an already signed-in page."""
    start, end = (date.fromisoformat(value).isoformat() for value in (start_date, through_date))
    if start > end or account not in ACCOUNTS:
        raise OceanCaptureError('unconfirmed_account_or_window')
    folder = Path(output_dir) / account[0]
    folder.mkdir(parents=True, exist_ok=False)
    try:
        page.goto(STANDARD_URL + account[0], wait_until='domcontentloaded')
        identity = page.get_by_role('button', name=re.compile('ID：' + account[0]))
        identity.wait_for(state='visible', timeout=20000)
        header = identity.inner_text()
        if account[0] not in header:
            raise OceanCaptureError('account_identity_mismatch')
        page.get_by_text('项目', exact=True).click()
        # Empty native reports have no project-column header; the daily control
        # is present in both populated and empty project reports.
        page.get_by_role('textbox', name='请选择', exact=True).first.wait_for(state='visible', timeout=15000)
        granularity = page.get_by_role('textbox', name='请选择', exact=True).first
        if granularity.input_value() != '分日':
            granularity.click()
            page.get_by_text('分日', exact=True).click()
        if granularity.input_value() != '分日':
            raise OceanCaptureError('daily_grain_not_selected')
        first, last = (page.get_by_placeholder(n, exact=True) for n in ('开始时间', '结束时间'))
        old_window = (first.input_value(), last.input_value())
        try:
            old_summary = _summary(page)
        except OceanCaptureError:
            old_summary = None
        if old_window != (start, end):
            first.click()
            _select_day(page, start)
            last.click()
            _select_day(page, end)
        if (first.input_value(), last.input_value()) != (start, end):
            raise OceanCaptureError('selected_window_not_applied')
        summary = _settled_summary(page, old_summary, old_window != (start, end), settle_timeout, poll)
        # Register before clicking and finish the native download before account switch.
        with page.expect_download(timeout=120000) as pending:
            page.locator('[name="StandardDownloadBtn"]').click()
        download = pending.value
        target = folder / 'native.xlsx'
        download.save_as(str(target))
        verified = validate_native(target, account, start, end, summary)
        if not identity.is_visible() or account[0] not in identity.inner_text():
            raise OceanCaptureError('account_changed_during_download')
        after = _summary(page)
        if after != summary or (first.input_value(), last.input_value()) != (start, end):
            raise OceanCaptureError('report_changed_during_download')
        evidence = {'account_id': account[0], 'account_header': header, 'start_date': start,
                    'through_date': end, 'grain': '分日', 'dimension': '项目', 'summary': summary,
                    'captured_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    'file': {'path': str(target), 'sha256': sha(target)}, **verified}
        proof = folder / 'capture.json'
        proof.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
        return {**evidence, 'evidence': {'path': str(proof), 'sha256': sha(proof)}}
    except OceanCaptureError:
        raise
    except Exception as error:
        raise OceanCaptureError('native_download_failed:' + type(error).__name__) from None


def export_all(page, *, start_date, through_date, output_dir):
    """All seven known accounts, serially; any failure keeps this batch incomplete."""
    results = []
    for account in ACCOUNTS:
        results.append(export_account(page, account=account, start_date=start_date,
            through_date=through_date, output_dir=output_dir))
    return {'source_id': 'ocean', 'status': 'success', 'account_ids': [a[0] for a in ACCOUNTS],
            'start_date': start_date, 'through_date': through_date, 'accounts': results}
