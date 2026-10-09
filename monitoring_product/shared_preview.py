"""Render compact local previews from a management notifications payload.

This module only formats an already-built payload. It never queries, uploads,
or sends. The image and HTML show the same short notification that a recipient
would read; the workbook keeps only the relevant personal or team ledger rows.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
INK = '#182230'
MUTED = '#687587'
BLUE = '#2d6cdf'
RED = '#c34b3d'
LINE = '#dfe5ec'
CANVAS = '#f5f7fa'
TECHNICAL_FIELDS = {
    'fact_id', 'source_id', 'source_sha256', 'source_row_number', 'ingest_batch',
    'ingest_id', 'query_run_id', 'query_receipt', 'receipt_path', 'snapshot_id',
    'run_id', 'source_file', 'normalized_at', 'normalization_version',
}
STATUS_LABELS = {
    'available': '已接入',
    'partial': '部分覆盖',
    'not_configured': '未配置',
    'not_connected': '未接入',
    'not_covered': '该期间未覆盖',
    'separate_counts': '分业务统计',
    'future': '窗口未开始',
    'unavailable': '不可用',
}
TEAM_CHANNELS = {
    'prep': 'offline_youth',
    'high': 'offline_high_school',
    'university': 'offline_university',
    'virtual': 'online_private',
    'online': 'online_platform',
}
DASHBOARD_PAGES = {
    'online': 'online.html',
    'university': 'university.html',
    'prep': 'prep_high.html',
    'high': 'prep_high.html',
    'virtual': 'index.html?unit=virtual',
}

DASHBOARD_FONTS = (
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/System/Library/Fonts/STHeiti Light.ttc',
)


def _font(size: int, bold: bool = False):
    """Load a CJK-capable font for local previews."""
    preferred = []
    if bold:
        preferred.extend([
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
            '/System/Library/Fonts/STHeiti Medium.ttc',
            '/System/Library/Fonts/Hiragino Sans GB.ttc',
        ])
    preferred.extend(DASHBOARD_FONTS)
    seen = set()
    for path in preferred:
        if path in seen or not Path(path).exists():
            continue
        seen.add(path)
        for index in (0, 2, 1, 3, 4):
            try:
                return ImageFont.truetype(path, size, index=index)
            except OSError:
                continue
            except Exception:
                continue
    raise FileNotFoundError(
        'No CJK font found for shared preview. Install fonts-noto-cjk '
        'or configure monitoring_product.shared_preview.DASHBOARD_FONTS'
    )


def _escape(value) -> str:
    return html.escape('' if value is None else str(value), quote=True)


def _line_name(value) -> str:
    return {'training': '语培', 'abroad': '留学'}.get(value, str(value or ''))


def _status(value) -> str:
    return STATUS_LABELS.get(value, value or '')


def _missing(value, status=None) -> str:
    if value is not None:
        return ''
    if status in {'not_connected', 'not_configured', 'not_covered', 'future', 'unavailable', 'partial'}:
        return _status(status)
    if status == 'separate_counts':
        return '—'
    return '未配置'


def _number_text(value) -> str:
    number = float(value)
    whole, separator, fraction = f'{number:,.2f}'.partition('.')
    fraction = fraction.rstrip('0')
    text = whole + (f'.{fraction}' if separator and fraction else '')
    return '0' if text == '-0' else text


def _count(value) -> str:
    return '未配置' if value is None else _number_text(value)


def _money(value) -> str:
    if value is None:
        return '未配置'
    text = f'{float(value):,.2f}'.rstrip('0').rstrip('.')
    return f'{text} 元'


def _daily(value) -> str:
    return '—' if value is None else f'{float(value):,.1f}'


def _percent(value) -> str:
    return '未配置' if value is None else f'{float(value) * 100:.1f}%'


def _hours(value) -> str:
    if value is None:
        return '—'
    return _number_text(value)


def _metric_display(actual, status=None, display=None, parts=None, *, money=False) -> str:
    if status == 'not_covered':
        return _status(status)
    if status == 'separate_counts':
        if display:
            return str(display)
        if isinstance(parts, list):
            values = []
            for part in parts:
                if not isinstance(part, dict) or part.get('actual') is None:
                    continue
                label = str(part.get('label') or '').strip()
                value = _money(part['actual']) if money else _count(part['actual'])
                values.append(f'{label} {value}'.strip())
            return '／'.join(values) if values else '—'
        return '—'
    if status in {'available', 'partial'} and display:
        return str(display)
    if actual is None:
        return _missing(None, status)
    return _money(actual) if money else _count(actual)


def _metric_spreadsheet_value(actual, status=None, display=None, parts=None):
    if status == 'not_covered':
        return _status(status)
    if status == 'separate_counts':
        return display or _metric_display(actual, status, display, parts)
    if status in {'available', 'partial'} and display:
        return display
    return actual if actual is not None else _missing(None, status)


def _behind(person: dict) -> str:
    if person.get('behind') is True:
        return '落后'
    if person.get('behind') is False:
        return '正常'
    return '目标未配置'


def _slug(message: dict, index: int) -> str:
    value = str(message.get('id') or f'message-{index}')
    return re.sub(r'[^A-Za-z0-9_-]+', '-', value).strip('-_').lower() or f'message-{index}'


def _team_key(message: dict) -> str:
    return str(message.get('id') or '').split('.', 1)[0].lower()


def _expected_channel(message: dict) -> str | None:
    return TEAM_CHANNELS.get(_team_key(message))


def _validate_payload(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or payload.get('schema_version') != 'management_notifications.v1':
        raise ValueError('expected schema_version management_notifications.v1')
    messages = payload.get('messages')
    if not isinstance(messages, list) or not messages:
        raise ValueError('notifications payload must contain messages')
    slugs, university_channels = set(), []
    for index, message in enumerate(messages, start=1):
        if not isinstance(message, dict) or not message.get('id') or not message.get('channel_id'):
            raise ValueError(f'message {index} requires id and channel_id')
        slug = _slug(message, index)
        if slug in slugs:
            raise ValueError(f'duplicate message id: {message["id"]}')
        slugs.add(slug)
        expected = _expected_channel(message)
        if expected and message['channel_id'] != expected:
            raise ValueError(f'{message["id"]} must map to channel_id {expected}')
        if _team_key(message) == 'university':
            university_channels.append(message['channel_id'])
    if len(university_channels) > 1 and len(set(university_channels)) != 1:
        raise ValueError('university training and study-abroad messages must share offline_university')
    return messages


def _message_is_online(message: dict) -> bool:
    return _team_key(message) == 'online'


def _message_uses_heads(message: dict) -> bool:
    return _team_key(message) == 'university' and message.get('business_line') == 'training'


def _message_has_heads(message: dict) -> bool:
    metrics = message.get('team_metrics') or {}
    if isinstance(metrics, dict) and metrics.get('heads') is not None:
        return True
    return any(person.get('heads_actual') is not None for person in message.get('people') or [])


def _message_has_cash(message: dict) -> bool:
    metrics = message.get('team_metrics') or {}
    if isinstance(metrics, dict) and metrics.get('cash') is not None:
        return True
    if any(person.get('cash_actual') is not None for person in message.get('people') or []):
        return True
    ledgers = message.get('ledgers') or {}
    return bool(ledgers.get('team_cash') or ledgers.get('personal_cash'))


def _cash_metric_label(message: dict) -> str:
    return '现金'


def _detail_download_label(message: dict) -> str:
    return '相关工单与现金流水'


def _window(message: dict, data_through: str) -> dict:
    return message.get('window') or {}


def _source_coverage_text(message: dict) -> str:
    coverage = message.get('source_coverage')
    if not isinstance(coverage, dict) or not coverage.get('start_date') or not coverage.get('through_date'):
        candidates = [person.get('abroad_source_coverage') for person in message.get('people') or []
                      if isinstance(person, dict) and isinstance(person.get('abroad_source_coverage'), dict)]
        unique = {(item.get('start_date'), item.get('through_date')) for item in candidates}
        if len(unique) == 1:
            start_date, through_date = next(iter(unique))
            coverage = {'start_date': start_date, 'through_date': through_date}
    if not isinstance(coverage, dict):
        return ''
    start_date, through_date = coverage.get('start_date'), coverage.get('through_date')
    if not start_date or not through_date:
        return ''
    return f'留学数据覆盖 {start_date}—{through_date}'


def _personal_window_text(message: dict, data_through: str) -> tuple[str, float | None, int | None]:
    window = _window(message, data_through)
    month = window.get('person_month') or message.get('month') or data_through[:7]
    start = window.get('person_start') or '—'
    end = window.get('person_end') or window.get('person_through') or '—'
    through = window.get('person_through') or data_through
    progress = window.get('person_progress')
    people = message.get('people') or []
    remaining = next((person.get('remaining_workdays') for person in people
                      if person.get('remaining_workdays') is not None), None)
    label = f'绩效月 {month}（{start} 至 {end}）· 数据截止 {through}'
    coverage = _source_coverage_text(message)
    if coverage:
        label += f' · {coverage}'
    return label, progress, remaining


def _team_window_text(message: dict, data_through: str) -> tuple[str, float | None]:
    window = _window(message, data_through)
    month = message.get('month') or data_through[:7]
    start = window.get('team_start') or f'{month}-01'
    end = window.get('team_end') or window.get('team_through') or data_through
    through = window.get('team_through') or data_through
    label = f'自然月 {month}（{start} 至 {end}）· 数据截止 {through}'
    coverage = _source_coverage_text(message)
    if coverage:
        label += f' · {coverage}'
    return label, window.get('team_progress')


def _metric_person_value(person: dict, key: str) -> tuple[object, object, object, str | None, object, object]:
    row = person.get(f'{key}_actual') or {}
    actual = row.get('actual') if isinstance(row, dict) else row
    target = person.get(f'{key}_target')
    if target is None and isinstance(row, dict):
        target = row.get('target')
    completion = person.get(f'{key}_completion')
    if completion is None and isinstance(row, dict):
        completion = row.get('completion')
    status = row.get('status') if isinstance(row, dict) else None
    display = row.get('display') if isinstance(row, dict) else None
    parts = row.get('parts') if isinstance(row, dict) else None
    return target, actual, completion, status, display, parts


def _person_row(person: dict, message: dict) -> dict:
    cash_target, cash_actual, cash_completion, cash_status, cash_display, cash_parts = _metric_person_value(person, 'cash')
    heads_target, heads_actual, heads_completion, heads_status, heads_display, heads_parts = _metric_person_value(person, 'heads')
    return {
        'name': person.get('name') or person.get('display_name') or '未命名',
        'group': person.get('business_group') or person.get('home_group') or '—',
        'orders_target': person.get('orders_target'),
        'orders_actual': person.get('orders_actual'),
        'orders_completion': person.get('orders_completion'),
        'expected_orders': person.get('expected_orders'),
        'daily_orders': person.get('daily_orders'),
        'today_orders': person.get('today_orders'),
        'behind': person.get('behind'),
        'cash_target': cash_target,
        'cash_actual': cash_actual,
        'cash_completion': cash_completion,
        'cash_status': cash_status,
        'cash_display': cash_display,
        'cash_parts': cash_parts,
        'heads_target': heads_target if heads_target is not None else person.get('heads_target'),
        'heads_actual': heads_actual,
        'heads_completion': heads_completion if heads_completion is not None else person.get('heads_completion'),
        'heads_status': heads_status,
        'heads_display': heads_display,
        'heads_parts': heads_parts,
        'secondary_business_line': person.get('secondary_business_line'),
        'secondary_orders_target': person.get('secondary_orders_target'),
        'secondary_orders_actual': person.get('secondary_orders_actual'),
        'secondary_orders_completion': person.get('secondary_orders_completion'),
    }


def _employee_columns(message: dict) -> list[tuple[str, int]]:
    if message.get('personal_only'):
        columns = [('人员', 160), ('业务团队', 110), ('工单完成', 140), ('当日新增', 140)]
        if any(person.get('cash_actual') is not None for person in message.get('people') or []):
            columns.append((_cash_metric_label(message), 130))
        return columns
    columns = [
        ('人员', 140), ('业务团队', 90), ('工单目标', 100), ('工单完成', 100),
        ('工单完成率', 120), ('应完成', 90), ('日均需完成', 110),
    ]
    show_heads = _message_uses_heads(message) or (_team_key(message) == 'university' and _message_has_heads(message))
    show_cash = _message_has_cash(message) and not _message_uses_heads(message)
    if show_cash:
        label = _cash_metric_label(message)
        amount_label = '现金完成'
        columns.extend([(f'{label}目标', 125), (amount_label, 125), (f'{label}完成率', 120)])
    if show_heads:
        columns.extend([('人头目标', 110), ('人头完成', 110), ('人头完成率', 120)])
    return columns


def _employee_values(person: dict, message: dict) -> list[str]:
    row = _person_row(person, message)
    if message.get('personal_only'):
        values = [
            row['name'], row['group'],
            _count(row['orders_actual']) if row['orders_actual'] is not None else _missing(None),
            _count(row['today_orders']) if row['today_orders'] is not None else '—',
        ]
        if any(source.get('cash_actual') is not None for source in message.get('people') or []):
            values.append(_metric_display(
                row['cash_actual'], row['cash_status'], row['cash_display'], row['cash_parts'], money=True,
            ))
        return values
    values = [
        row['name'], row['group'],
        _count(row['orders_target']) if row['orders_target'] is not None else _missing(None),
        _count(row['orders_actual']) if row['orders_actual'] is not None else _missing(None),
        _percent(row['orders_completion']),
        _daily(row['expected_orders']) if row['expected_orders'] is not None else '—',
        _daily(row['daily_orders']),
    ]
    show_heads = _message_uses_heads(message) or (_team_key(message) == 'university' and _message_has_heads(message))
    show_cash = _message_has_cash(message) and not _message_uses_heads(message)
    if show_cash:
        values.extend([
            _money(row['cash_target']) if row['cash_target'] is not None else _missing(None, row['cash_status']),
            _metric_display(row['cash_actual'], row['cash_status'], row['cash_display'], row['cash_parts'], money=True),
            _percent(row['cash_completion']) if row['cash_completion'] is not None else _missing(None, row['cash_status']),
        ])
    if show_heads:
        values.extend([
            _hours(row['heads_target']) if row['heads_target'] is not None else _missing(None, row['heads_status']),
            _metric_display(row['heads_actual'], row['heads_status'], row['heads_display'], row['heads_parts']),
            _percent(row['heads_completion']) if row['heads_completion'] is not None else _missing(None, row['heads_status']),
        ])
    return values


def _behind_people(message: dict) -> list[dict]:
    return [_person_row(person, message) for person in message.get('people') or []
            if person.get('behind') is True]


def _no_behind_text(message: dict) -> str:
    coverage = message.get('source_coverage') or {}
    window = message.get('window') or {}
    start, through = window.get('person_start'), window.get('person_through')
    if (message.get('business_line') == 'abroad' and start and through
            and coverage.get('start_date') and coverage.get('through_date')
            and (coverage['start_date'] > start or coverage['through_date'] < through)):
        return '来源未覆盖完整绩效窗口，暂不判断落后'
    if not any(person.get('behind') is False for person in message.get('people') or []):
        return '暂无可判断的绩效进度'
    return '无人落后时间进度'


def _html_people(message: dict, data_through: str, dashboard_url: str | None,
                 preview_label: str) -> str:
    title = message.get('title') or message.get('id')
    meta, progress, remaining = _personal_window_text(message, data_through)
    personal_only = bool(message.get('personal_only'))
    columns = _employee_columns(message)
    headers = ''.join(f'<th>{_escape(label)}</th>' for label, _ in columns)
    rows = []
    for person in message.get('people') or []:
        values = _employee_values(person, message)
        cells = []
        for index, value in enumerate(values):
            css = ' class="numeric"' if index >= 2 else ''
            if index == 4 and person.get('behind') is True:
                css = ' class="numeric behind"'
            cells.append(f'<td{css}>{_escape(value)}</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    behind = [] if personal_only else _behind_people(message)
    behind_html = ('<ul>' + ''.join(
        f'<li><strong>{_escape(row["name"])}</strong> 工单 {_count(row["orders_actual"])}/{_count(row["orders_target"])}'
        f'（{_percent(row["orders_completion"])}），应完成 {_daily(row["expected_orders"])}，'
        f'日均需 {_daily(row["daily_orders"])} 条</li>' for row in behind) + '</ul>') if behind else f'<p>{_escape(_no_behind_text(message))}</p>'
    link = f'<p><a href="{_escape(dashboard_url)}">查看看板</a></p>' if dashboard_url else ''
    progress_html = '' if progress is None else f'<p class="progress">绩效月时间进度 {progress * 100:.1f}% · 剩余工作日 {remaining if remaining is not None else "—"}</p>'
    channel_html = ''
    if personal_only:
        channel_rows = _online_channel_rows(message)
        body = ''.join(
            '<tr>' + ''.join(
                f'<td class="numeric">{_escape(value)}</td>' if column else f'<td>{_escape(value)}</td>'
                for column, value in enumerate(row)
            ) + '</tr>'
            for row in channel_rows
        ) or '<tr><td colspan="4">暂无渠道数据</td></tr>'
        channel_html = (f'<h2>个人渠道分布</h2><table><thead><tr><th>二级渠道</th>'
                        f'<th class="numeric">月累计</th><th class="numeric">当日新增</th>'
                        f'<th class="numeric">占比</th></tr></thead><tbody>{body}</tbody></table>')
    colspan = len(columns)
    behind_section = '' if personal_only else f'<h2>落后时间进度（工单）</h2>{behind_html}'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_escape(title)}</title>
<style>:root{{--ink:{INK};--muted:{MUTED};--line:{LINE};--blue:{BLUE};--canvas:{CANVAS}}}*{{box-sizing:border-box}}
body{{margin:0;background:var(--canvas);color:var(--ink);font:15px/1.5 "Noto Sans CJK SC","PingFang SC","Hiragino Sans GB",sans-serif}}
main{{width:min(1200px,100%);margin:auto;padding:24px;background:#fff;min-height:100vh}}.eyebrow{{font-size:12px;color:var(--blue);font-weight:800}}
h1{{font:600 28px/1.25 "Noto Serif CJK SC","Songti SC",serif;margin:8px 0}}.meta,.progress{{color:var(--muted);font-size:14px;font-weight:700}}.progress{{margin:10px 0 14px}}
.note{{color:var(--muted);font-size:14px;margin:8px 0}}table{{width:100%;border-collapse:collapse;table-layout:auto;font-size:14px}}
th,td{{padding:10px 8px;border-bottom:1px solid #edf0f4;text-align:left;vertical-align:top;overflow-wrap:anywhere}}
thead th{{background:#f7f9fc;color:var(--muted);font-size:13px;white-space:normal}}.numeric{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.behind{{color:{RED};font-weight:800}}h2{{font:600 18px/1.3 "Noto Serif CJK SC","Songti SC",serif;margin:22px 0 6px}}
ul{{margin:0;padding-left:20px}}li{{margin:5px 0;color:{RED}}}a{{color:{BLUE}}}.local{{margin-top:22px;font-size:11px;color:#9aa4b2}}
</style></head><body><main><div class="eyebrow">DATA OXHOR / 人员月度贡献</div><h1>{_escape(title)}</h1>
<p class="meta">{_escape(meta)} · 剩余工作日 {remaining if remaining is not None else '—'}</p>{progress_html}
<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows) or f'<tr><td colspan="{colspan}">当前没有人员进度</td></tr>'}</tbody></table>
{channel_html}{behind_section}{link}<div class="local">{_escape(preview_label)}</div></main></body></html>'''


def _online_metrics(message: dict) -> list[dict]:
    metrics = message.get('team_metrics') or {}
    output = []
    orders = metrics.get('orders') or {}
    output.append({'name': '工单', 'metric': orders, 'unit': '条'})
    if message.get('business_line') == 'training' or metrics.get('cash') is not None:
        cash = metrics.get('cash') or {}
        output.append({'name': '语培现金' if message.get('business_line') == 'training' else _cash_metric_label(message),
                       'metric': cash, 'unit': '元'})
    return output


def _metric_cell(metric: dict, field: str, *, money=False) -> str:
    value = metric.get(field)
    if field == 'actual':
        return _metric_display(value, metric.get('status'), metric.get('display'), metric.get('parts'), money=money)
    if value is None:
        return _missing(None, metric.get('status'))
    return _money(value) if money else _count(value)


def _metric_status(metric: dict) -> str:
    if metric.get('status') in {'not_connected', 'not_configured', 'not_covered', 'future', 'unavailable', 'partial', 'separate_counts'}:
        return _status(metric.get('status'))
    return '已接入' if metric.get('target') is not None else '未配置'


def _html_online(message: dict, data_through: str, dashboard_url: str | None,
                  preview_label: str) -> str:
    title = message.get('title') or message.get('id')
    meta, progress = _team_window_text(message, data_through)
    rows = []
    for item in _online_metrics(message):
        metric = item['metric']
        money = item['unit'] == '元'
        rows.append('<tr>' + ''.join((
            f'<th>{_escape(item["name"])}</th>',
            f'<td class="numeric">{_escape(_metric_cell(metric, "target", money=money))}</td>',
            f'<td class="numeric">{_escape(_metric_cell(metric, "actual", money=money))}</td>',
            f'<td class="numeric">{_escape(_percent(metric.get("completion")) if metric.get("completion") is not None else _missing(None, metric.get("status")))}</td>',
        )) + '</tr>')
    progress_html = '' if progress is None else f'<p class="progress">自然月时间进度 {progress * 100:.1f}%</p>'
    link = f'<p><a href="{_escape(dashboard_url)}">查看看板</a></p>' if dashboard_url else ''
    channel_rows = ''.join(
        '<tr>' + ''.join(f'<td>{_escape(value)}</td>' for value in row) + '</tr>'
        for row in _online_channel_rows(message)
    ) or '<tr><td colspan="4">当前没有二级渠道工单</td></tr>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_escape(title)}</title>
<style>body{{margin:0;background:{CANVAS};color:{INK};font:16px/1.5 "Noto Sans CJK SC","PingFang SC",sans-serif}}main{{max-width:1050px;margin:auto;padding:26px;background:white;min-height:100vh}}
.eyebrow{{font-size:12px;color:{BLUE};font-weight:800}}h1{{font-size:28px;margin:8px 0}}.meta,.progress{{font-size:14px;color:{MUTED};font-weight:700}}
table{{width:100%;max-width:1050px;border-collapse:collapse;margin-top:18px}}th,td{{padding:8px 10px;border-bottom:1px solid #edf0f4;text-align:left}}thead th{{background:#f7f9fc;color:{MUTED}}}.numeric{{text-align:right;font-variant-numeric:tabular-nums}}a{{color:{BLUE}}}.local{{margin-top:28px;color:#9aa4b2;font-size:11px}}h2{{font-size:17px;margin:22px 0 0}}</style>
</head><body><main><div class="eyebrow">DATA OXHOR / 自然月进度</div><h1>{_escape(title)}</h1><p class="meta">{_escape(meta)}</p>{progress_html}
<table><thead><tr><th>指标</th><th class="numeric">目标</th><th class="numeric">完成</th><th class="numeric">完成率</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>二级渠道</h2><table><thead><tr><th>名称</th><th class="numeric">月累计</th><th class="numeric">当日新增</th><th class="numeric">占比</th></tr></thead><tbody>{channel_rows}</tbody></table>
{link}<div class="local">{_escape(preview_label)}</div></main></body></html>'''


def _online_channel_rows(message: dict) -> list[list[str]]:
    return [[
        str(channel.get('name') or '二级渠道待确认'),
        _count(channel.get('month')) if channel.get('month') is not None else '—',
        _count(channel.get('today')) if channel.get('today') is not None else '—',
        _percent(channel.get('share')) if channel.get('share') is not None else '—',
    ] for channel in message.get('channels') or []]


def _personal_channel_xlsx_rows(message: dict) -> tuple[list[str], list[list]]:
    headers = ['二级渠道', '月累计', '当日新增', '占比%']
    rows = [[
        str(channel.get('name') or '二级渠道待确认'),
        channel.get('month'),
        channel.get('today'),
        None if channel.get('share') is None else round(float(channel['share']) * 100, 1),
    ] for channel in message.get('channels') or []]
    return headers, rows


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    lines, current = [], ''
    for char in str(text if text is not None else '—'):
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    lines.append(current or ' ')
    return lines


def _table_height(draw, widths, headers, rows, cell_font, header_font) -> int:
    header_lines = [_wrap(draw, text, header_font, width - 14) for text, width in zip(headers, widths)]
    height = max(38, max(map(len, header_lines), default=1) * 20 + 10)
    if not rows:
        return height + 42
    for row in rows:
        lines = [_wrap(draw, str(value), cell_font, width - 14) for value, width in zip(row, widths)]
        height += max(42, max(map(len, lines), default=1) * 22 + 14)
    return height + 4


def _draw_table(draw, x, y, widths, headers, rows, *, cell_font, header_font, right_columns=(), empty='') -> int:
    header_lines = [_wrap(draw, text, header_font, width - 14) for text, width in zip(headers, widths)]
    header_height = max(38, max(map(len, header_lines), default=1) * 20 + 10)
    table_width = sum(widths)
    draw.rectangle((x, y, x + table_width, y + header_height), fill='#f1f4f8')
    cursor = x
    for lines, width in zip(header_lines, widths):
        for index, line in enumerate(lines):
            draw.text((cursor + 7, y + 5 + index * 20), line, font=header_font, fill=MUTED)
        cursor += width
    y += header_height
    if not rows:
        draw.text((x + 8, y + 8), empty, font=cell_font, fill=MUTED)
        return y + 38
    for index, row in enumerate(rows):
        wrapped = [_wrap(draw, str(value), cell_font, width - 14) for value, width in zip(row, widths)]
        row_height = max(40, max(map(len, wrapped), default=1) * 22 + 12)
        if index % 2:
            draw.rectangle((x, y, x + table_width, y + row_height), fill='#fafbfc')
        cursor = x
        for column, (lines, width) in enumerate(zip(wrapped, widths)):
            for line_index, line in enumerate(lines):
                text_width = draw.textlength(line, font=cell_font)
                xpos = cursor + width - 8 - text_width if column in right_columns else cursor + 8
                color = RED if column == 4 and row[-1] == '落后' else INK
                draw.text((xpos, y + 6 + line_index * 22), line, font=cell_font, fill=color)
            cursor += width
        draw.line((x, y + row_height, x + table_width, y + row_height), fill='#edf0f4')
        y += row_height
    return y + 4


def _render_person_png(message: dict, data_through: str, path: Path, dashboard_url: str | None) -> Path:
    title = str(message.get('title') or message.get('id'))
    meta, progress, remaining = _personal_window_text(message, data_through)
    personal_only = bool(message.get('personal_only'))
    people = message.get('people') or []
    columns = _employee_columns(message)
    headers = [name for name, _ in columns]
    widths = [width for _, width in columns]
    values = [_employee_values(person, message) for person in people]
    behind = [] if personal_only else _behind_people(message)
    channel_rows = _online_channel_rows(message) if personal_only else []
    if personal_only and not channel_rows:
        channel_rows = [['暂无渠道数据', '—', '—', '—']]
    channel_widths = [520, 180, 180, 140]
    channel_headers = ['二级渠道', '月累计', '当日新增', '占比']
    table_draw = ImageDraw.Draw(Image.new('RGB', (1, 1), 'white'))
    cell_font, header_font = _font(15), _font(13, bold=True)
    table_h = _table_height(table_draw, widths, headers, values, cell_font, header_font)
    behind_h = 0 if personal_only else (40 + sum(28 for _ in behind) if behind else 50)
    channel_h = (_table_height(table_draw, channel_widths, channel_headers,
                               channel_rows, cell_font, header_font) if channel_rows else 0)
    channel_section_h = 43 + channel_h if channel_rows else 0
    height = 225 + table_h + behind_h + channel_section_h + 36
    canvas_width = max(WIDTH, sum(widths) + 64)
    image = Image.new('RGB', (canvas_width, height), CANVAS)
    draw = ImageDraw.Draw(image)
    draw.rectangle((14, 14, canvas_width - 14, height - 14), fill='white', outline=LINE, width=1)
    draw.text((32, 29), 'DATA OXHOR / 人员月度贡献', font=_font(12, bold=True), fill=BLUE)
    draw.text((32, 51), title, font=_font(27, bold=True), fill=INK)
    draw.text((32, 94), meta + f' · 剩余工作日 {remaining if remaining is not None else "—"}', font=_font(15), fill=MUTED)
    if progress is not None:
        pct = max(0.0, min(1.0, float(progress)))
        draw.text((32, 126), '绩效月时间进度', font=_font(14), fill=MUTED)
        bar_x, bar_y, bar_w = 190, 132, 850
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 10), radius=5, fill='#e8edf3')
        if pct:
            draw.rounded_rectangle((bar_x, bar_y, bar_x + round(bar_w * pct), bar_y + 10), radius=5, fill=BLUE)
        draw.text((bar_x + bar_w + 12, 123), f'{pct * 100:.1f}%', font=_font(18, bold=True), fill=BLUE)
    y = 164
    y = _draw_table(draw, 32, y, widths, headers, values, cell_font=cell_font,
                    header_font=header_font, right_columns=tuple(range(2, len(headers))))
    if channel_rows:
        y += 18
        draw.text((32, y), '个人渠道分布', font=_font(17, bold=True), fill=INK)
        y += 25
        y = _draw_table(draw, 32, y, channel_widths, channel_headers, channel_rows,
                        cell_font=cell_font, header_font=header_font, right_columns=(1, 2, 3))
    if not personal_only:
        y += 18
        draw.text((32, y), '落后时间进度（工单）', font=_font(17, bold=True), fill=INK)
        y += 26
        if behind:
            for person in behind:
                line = (f"{person['name']}  工单 {_count(person['orders_actual'])}/{_count(person['orders_target'])}"
                        f"（{_percent(person['orders_completion'])}），应完成 {_daily(person['expected_orders'])}，"
                        f"日均需 {_daily(person['daily_orders'])} 条")
                draw.text((32, y), line, font=_font(14), fill=RED)
                y += 25
        else:
            draw.text((32, y), _no_behind_text(message), font=_font(14), fill=MUTED)
            y += 22
    footer = '流水见附件' + (' · 详细分析见看板' if dashboard_url else '')
    draw.text((32, y + 10), footer, font=_font(12), fill=MUTED)
    final_height = y + 40
    image = image.crop((0, 0, canvas_width, final_height))
    ImageDraw.Draw(image).rectangle((14, 14, canvas_width - 14, final_height - 14), outline=LINE, width=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, 'PNG')
    return path


def _online_rows(message: dict) -> list[list[str]]:
    rows = []
    metrics = message.get('team_metrics') or {}
    line = message.get('business_line')
    cash_label = '语培现金' if line == 'training' else _cash_metric_label(message)
    for name, key in [('工单', 'orders')] + ([(cash_label, 'cash')] if line == 'training' or metrics.get('cash') is not None else []):
        metric = metrics.get(key) or {}
        money = key == 'cash'
        rows.append([
            name,
            _metric_cell(metric, 'target', money=money),
            _metric_cell(metric, 'actual', money=money),
            _percent(metric.get('completion')) if metric.get('completion') is not None else _missing(None, metric.get('status')),
        ])
    return rows


def _render_online_png(message: dict, data_through: str, path: Path, dashboard_url: str | None) -> Path:
    title = str(message.get('title') or message.get('id'))
    meta, progress = _team_window_text(message, data_through)
    rows = _online_rows(message)
    widths = [240, 250, 250, 220]
    headers = ['指标', '目标', '完成', '完成率']
    channel_rows = _online_channel_rows(message)
    channel_widths = [520, 180, 180, 140]
    channel_headers = ['二级渠道', '月累计', '当日新增', '占比']
    font, bold = _font(17), _font(15, bold=True)
    draw_measure = ImageDraw.Draw(Image.new('RGB', (1, 1), 'white'))
    table_h = _table_height(draw_measure, widths, headers, rows, font, bold)
    channel_h = _table_height(draw_measure, channel_widths, channel_headers,
                              channel_rows, font, bold) if channel_rows else 0
    height = 164 + table_h + (20 + 25 + channel_h if channel_rows else 0) + 44
    image = Image.new('RGB', (WIDTH, height), CANVAS)
    draw = ImageDraw.Draw(image)
    draw.rectangle((14, 14, WIDTH - 14, height - 14), fill='white', outline=LINE, width=1)
    draw.text((32, 29), 'DATA OXHOR / 自然月进度', font=_font(12, bold=True), fill=BLUE)
    draw.text((32, 51), title, font=_font(27, bold=True), fill=INK)
    draw.text((32, 96), meta, font=_font(15), fill=MUTED)
    if progress is not None:
        pct = max(0.0, min(1.0, float(progress)))
        draw.text((32, 128), '自然月时间进度', font=_font(14), fill=MUTED)
        bar_x, bar_y, bar_w = 190, 134, 750
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 10), radius=5, fill='#e8edf3')
        if pct:
            draw.rounded_rectangle((bar_x, bar_y, bar_x + round(bar_w * pct), bar_y + 10), radius=5, fill=BLUE)
        draw.text((bar_x + bar_w + 12, 125), f'{pct * 100:.1f}%', font=_font(18, bold=True), fill=BLUE)
    y = 164
    y = _draw_table(draw, 32, y, widths, headers, rows, cell_font=font,
                    header_font=bold, right_columns=(1, 2, 3))
    if channel_rows:
        y += 18
        draw.text((32, y), '二级渠道', font=_font(17, bold=True), fill=INK)
        y += 25
        y = _draw_table(draw, 32, y, channel_widths, channel_headers, channel_rows,
                        cell_font=font, header_font=bold, right_columns=(1, 2, 3))
    footer = '流水见附件' + (' · 详细分析见看板' if dashboard_url else '')
    draw.text((32, y + 14), footer, font=_font(12), fill=MUTED)
    final_height = y + 44
    image = image.crop((0, 0, WIDTH, final_height))
    ImageDraw.Draw(image).rectangle((14, 14, WIDTH - 14, final_height - 14), outline=LINE, width=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, 'PNG')
    return path


def _html_for_message(message: dict, data_through: str, dashboard_url: str | None,
                      preview_label: str) -> str:
    if _message_is_online(message):
        return _html_online(message, data_through, dashboard_url, preview_label)
    return _html_people(message, data_through, dashboard_url, preview_label)


def _source_fields(fact: dict) -> dict:
    raw = fact.get('source_record')
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        raw = parsed if isinstance(parsed, dict) else {'原始记录': raw}
    if isinstance(raw, dict) and isinstance(raw.get('fields'), dict):
        raw = raw['fields']
    elif isinstance(raw, dict) and isinstance(raw.get('columns'), list) and isinstance(raw.get('values'), list):
        raw = dict(zip(raw['columns'], raw['values']))
    if not isinstance(raw, dict):
        raw = {}
    fields = {}
    for key, value in raw.items():
        name = str(key)
        if (name.lower() in TECHNICAL_FIELDS or name.startswith('_')
                or name.lower().startswith(('ingest_', 'query_', 'receipt_', 'normalized_'))):
            continue
        if ('日期' in name or '时间' in name) and value is not None:
            try:
                serial = float(value)
                if 20000 <= serial <= 80000:
                    timestamp = datetime(1899, 12, 30) + timedelta(days=serial)
                    value = timestamp if serial % 1 else timestamp.date()
            except (TypeError, ValueError, OverflowError):
                pass
        fields[name] = value
    return fields


def _status_text(value):
    return {
        'order_status_deleted': '删除',
        'order_status_recalled': '回收',
    }.get(value, value)


def _person_credit_text(fact: dict, field: str, kind: str) -> str:
    credits = fact.get('person_credits')
    if not isinstance(credits, dict):
        return ''
    parts = []
    for name, credit in credits.items():
        if not isinstance(credit, dict):
            continue
        value = credit.get(field)
        if value is None:
            shown = '未配置'
        elif field == 'weight' or kind == '工单':
            shown = _number_text(value)
        else:
            shown = _money(value)
        parts.append(f'{name}：{shown}')
    return '；'.join(parts)


def _reason_text(fact: dict, *, team_scope: bool = False) -> str:
    status = _status_text(fact.get('order_status'))
    if team_scope:
        return ''
    if status in {'删除', '回收'}:
        return f'工单状态为{status}，不计个人业绩'
    reason = fact.get('exclusion_reason')
    if reason and fact.get('counts_toward_completion') is False and not team_scope:
        return f'{reason}；不计个人业绩'
    return str(reason or ('' if fact.get('counts_toward_completion') is True else '未提供原因'))


def _detail_row(fact: dict, index: int, kind: str, *, team_scope: bool = False) -> dict:
    row = _source_fields(fact)
    owners = fact.get('owners') or []
    status = _status_text(fact.get('order_status'))
    counts_toward_completion = fact.get('counts_toward_completion')
    if team_scope:
        counts_toward_completion = True
    row.update({
        '发生日期': fact.get('event_date'),
        '业务线': _line_name(fact.get('business_line')),
        '工单ID': fact.get('work_order_id'),
        '资源ID': fact.get('resource_id'),
        '归属人员': '、'.join(map(str, owners)) if isinstance(owners, (list, tuple)) else str(owners or ''),
        '指标': _cash_metric_label({'business_line': fact.get('business_line')}) if kind == '现金' else kind,
        '数量/金额': fact.get('value'),
        '工单状态': _status_text(fact.get('order_status')),
        '是否计入工单完成': ('不适用' if kind == '现金' else
                              ('是' if counts_toward_completion is True else ('否' if counts_toward_completion is False else '未标明'))),
        '不计入原因': '' if kind == '现金' else _reason_text(fact, team_scope=team_scope),
    })
    if not team_scope:
        person_weights = _person_credit_text(fact, 'weight', kind)
        person_values = _person_credit_text(fact, 'value', kind)
        if person_weights or person_values:
            row['个人分配权重'] = person_weights
            row['个人贡献数量/金额'] = person_values
    return row


def _ledger_rows(message: dict, key: str, kind: str) -> list[dict]:
    ledgers = message.get('ledgers') or {}
    prefix = 'team' if _message_is_online(message) else 'personal'
    team_scope = prefix == 'team'
    facts = list(ledgers.get(f'{prefix}_{key}') or [])
    if (key == 'orders' and prefix == 'personal'
            and _team_key(message) == 'university'):
        facts.extend(ledgers.get('personal_secondary_orders') or [])
    output, seen = [], set()
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        identity = fact.get('fact_id') or (
            fact.get('business_line'), fact.get('work_order_id'), fact.get('resource_id'),
            fact.get('event_date'), fact.get('value'),
        )
        if identity in seen:
            continue
        seen.add(identity)
        output.append(_detail_row(fact, len(output) + 1, kind, team_scope=team_scope))
    return output


def _person_xlsx_rows(message: dict, data_through: str) -> tuple[list[str], list[list]]:
    if message.get('personal_only'):
        labels = ['人员', '业务团队', '工单完成', '当日新增']
        has_cash = any(person.get('cash_actual') is not None for person in message.get('people') or [])
        if has_cash:
            labels.append(_cash_metric_label(message))
        rows = []
        for source in message.get('people') or []:
            person = _person_row(source, message)
            row = [
                person['name'], person['group'],
                person['orders_actual'] if person['orders_actual'] is not None else _missing(None),
                person['today_orders'] if person['today_orders'] is not None else _missing(None),
            ]
            if has_cash:
                row.append(_metric_spreadsheet_value(
                    person['cash_actual'], person['cash_status'],
                    person['cash_display'], person['cash_parts'],
                ))
            rows.append(row)
        return labels, rows
    cash_label = _cash_metric_label(message)
    cash_actual_label = '现金完成(元)'
    labels = [
        '人员', '业务团队', '主线工单目标', '主线工单完成', '主线工单完成率%',
        '应完成工单', '日均需完成', '落后时间进度', f'{cash_label}目标(元)', cash_actual_label,
        f'{cash_label}完成率%', '人头目标', '人头完成', '人头完成率%', '另一业务线',
        '另一业务线工单目标', '另一业务线工单完成', '另一业务线完成率%',
    ]
    rows = []
    for source in message.get('people') or []:
        person = _person_row(source, message)
        rows.append([
            person['name'], person['group'],
            person['orders_target'] if person['orders_target'] is not None else _missing(None),
            person['orders_actual'] if person['orders_actual'] is not None else _missing(None),
            round(float(person['orders_completion']) * 100, 1) if person['orders_completion'] is not None else '未配置',
            person['expected_orders'], person['daily_orders'], _behind(person),
            person['cash_target'] if person['cash_target'] is not None else _missing(None, person['cash_status']),
            _metric_spreadsheet_value(person['cash_actual'], person['cash_status'],
                                      person['cash_display'], person['cash_parts']),
            round(float(person['cash_completion']) * 100, 1) if person['cash_completion'] is not None else _missing(None, person['cash_status']),
            person['heads_target'] if person['heads_target'] is not None else _missing(None, person['heads_status']),
            _metric_spreadsheet_value(person['heads_actual'], person['heads_status'],
                                      person['heads_display'], person['heads_parts']),
            round(float(person['heads_completion']) * 100, 1) if person['heads_completion'] is not None else _missing(None, person['heads_status']),
            _line_name(person['secondary_business_line']),
            person['secondary_orders_target'] if person['secondary_orders_target'] is not None else _missing(None),
            person['secondary_orders_actual'] if person['secondary_orders_actual'] is not None else _missing(None),
            round(float(person['secondary_orders_completion']) * 100, 1) if person['secondary_orders_completion'] is not None else '未配置',
        ])
    if _team_key(message) == 'virtual':
        labels = [label.replace('主线', '') for label in labels[:14]]
        rows = [row[:14] for row in rows]
    return labels, rows


def _online_xlsx_rows(message: dict, data_through: str) -> tuple[list[str], list[list]]:
    labels = ['业务线', '数据窗口', '指标', '目标', '完成', '完成率%', '状态']
    window, _ = _team_window_text(message, data_through)
    rows = []
    for item in _online_metrics(message):
        metric = item['metric']
        rows.append([
            _line_name(message.get('business_line')), window, item['name'], metric.get('target'),
            _metric_spreadsheet_value(metric.get('actual'), metric.get('status'),
                                      metric.get('display'), metric.get('parts')),
            None if metric.get('completion') is None else round(float(metric['completion']) * 100, 1),
            _metric_status(metric),
        ])
    return labels, rows


def _write_sheet(workbook: Workbook, name: str, headers: list[str], rows: list[list], note: str) -> None:
    sheet = workbook.create_sheet(name)
    last = max(1, len(headers))
    header_index = {header: index for index, header in enumerate(headers)}
    metric_index = header_index.get('指标')
    money_metrics = {'现金', '语培现金', '毛签金额', '签约金额', '实缴金额'}
    for row, text in ((1, name), (2, f'范围：{note}')):
        sheet.cell(row, 1, text)
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last)
        sheet.cell(row, 1).alignment = Alignment(wrap_text=True, vertical='top')
    sheet.row_dimensions[1].height = 25
    sheet.row_dimensions[2].height = 38
    head_row = 4
    for column, value in enumerate(headers, start=1):
        cell = sheet.cell(head_row, column, value)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='2D6CDF')
        cell.alignment = Alignment(wrap_text=True, vertical='center')
    for row_index, values in enumerate(rows, start=head_row + 1):
        for column, value in enumerate(values, start=1):
            if isinstance(value, (dict, list, tuple)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            cell = sheet.cell(row_index, column, value)
            cell.alignment = Alignment(wrap_text=True, vertical='top',
                                       horizontal='right' if isinstance(value, (int, float)) else 'left')
            header = str(headers[column - 1]) if column <= len(headers) else ''
            metric = str(values[metric_index]) if metric_index is not None and metric_index < len(values) else ''
            money_column = any(label in header for label in ('现金', '毛签金额', '签约金额', '实缴金额'))
            money_column = money_column or (header in {'目标', '完成', '数量/金额'} and metric in money_metrics)
            if money_column and isinstance(value, (int, float)) and not isinstance(value, bool):
                cell.number_format = '#,##0.00'
    for column, header in enumerate(headers, start=1):
        sample = [str(header)] + [str(row[column - 1]) for row in rows[:150]
                                  if column <= len(row) and row[column - 1] is not None]
        sheet.column_dimensions[get_column_letter(column)].width = min(48, max(12, max(map(len, sample)) + 2))
    sheet.freeze_panes = 'A5'
    sheet.auto_filter.ref = f'A4:{get_column_letter(max(1, len(headers)))}{max(4, 4 + len(rows))}'


def _write_detail_sheet(workbook: Workbook, name: str, rows: list[dict], note: str, *, show_business_line=True) -> None:
    standard = ['发生日期', '业务线', '工单ID', '归属人员', '指标']
    if any(row.get('资源ID') is not None for row in rows):
        standard.insert(3, '资源ID')
    if any('个人分配权重' in row or '个人贡献数量/金额' in row for row in rows):
        standard.extend(['个人分配权重', '个人贡献数量/金额'])
    standard.extend(['数量/金额', '工单状态', '是否计入工单完成', '不计入原因'])
    if not show_business_line:
        standard.remove('业务线')
        rows = [{k: v for k, v in row.items() if k != '业务线'} for row in rows]
    headers = list(standard)
    for row in rows:
        for field in row:
            if field not in headers:
                headers.append(field)
    values = [[row.get(header) for header in headers] for row in rows]
    _write_sheet(workbook, name, headers, values, note)


def _write_xlsx(message: dict, data_through: str, path: Path) -> Path:
    book = Workbook()
    book.remove(book.active)
    if _message_is_online(message):
        headers, rows = _online_xlsx_rows(message, data_through)
        window, _ = _team_window_text(message, data_through)
        _write_sheet(book, '进度汇总', headers, rows, window)
        scope = f'{window}；对应自然月团队核算范围，删除、回收计入团队业绩；个人业绩剔除。'
    else:
        headers, rows = _person_xlsx_rows(message, data_through)
        window, _, _ = _personal_window_text(message, data_through)
        _write_sheet(book, '个人进度', headers, rows,
                     f'{window}；个人行是贡献口径，不能相加替代部门去重工单量。')
        scope = f'{window}；只包含本消息相关人员的个人流水，删除、回收保留明细但不计个人业绩。'
    if message.get('personal_only'):
        channel_headers, channel_values = _personal_channel_xlsx_rows(message)
        _write_sheet(book, '渠道分布', channel_headers, channel_values,
                     f'{window}；按个人工单贡献统计。')
    orders = _ledger_rows(message, 'orders', '工单')
    cash = _ledger_rows(message, 'cash', '现金')
    _write_detail_sheet(book, '工单明细', orders, scope, show_business_line=_team_key(message) != 'virtual')
    if not message.get('personal_only') or cash:
        cash_scope = scope if cash else scope + '；当前范围没有已接入金额流水。'
        _write_detail_sheet(book, '现金明细', cash, cash_scope, show_business_line=_team_key(message) != 'virtual')
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    return path


def _dashboard_url(message: dict, base_url: str | None) -> str | None:
    if not base_url:
        return None
    page = DASHBOARD_PAGES.get(_team_key(message))
    if not page:
        return None
    return base_url.rstrip('/') + '/' + page


def _markdown(message: dict, data_through: str, dashboard_url: str | None) -> str:
    title = message.get('title') or message.get('id')
    if message.get('personal_only'):
        window, progress, remaining = _personal_window_text(message, data_through)
        lines = [f'## {title}', '', window]
        if progress is not None:
            lines.append(f'时间进度 {float(progress) * 100:.1f}% · 剩余工作日 {remaining if remaining is not None else "—"}')
        columns = [label for label, _ in _employee_columns(message)]
        people_rows = [_employee_values(person, message) for person in message.get('people') or []]
        lines.extend(['', '| ' + ' | '.join(columns) + ' |',
                      '| ' + ' | '.join('---' for _ in columns) + ' |'])
        lines.extend('| ' + ' | '.join(values) + ' |' for values in people_rows)
        lines.extend(['', '个人渠道分布', '', '| 二级渠道 | 月累计 | 当日新增 | 占比 |',
                      '| --- | ---: | ---: | ---: |'])
        channel_rows = _online_channel_rows(message)
        if channel_rows:
            lines.extend('| ' + ' | '.join(row) + ' |' for row in channel_rows)
        else:
            lines.append('| 暂无渠道数据 | — | — | — |')
        lines.extend(['', '![本地消息图片](message.png)', ''])
        if dashboard_url:
            lines.append(f'[查看看板]({dashboard_url})')
        lines.extend(['[查看HTML预览](message.html)', f'[下载{_detail_download_label(message)}](details.xlsx)', ''])
        return '\n'.join(lines)
    if _message_is_online(message):
        window, progress = _team_window_text(message, data_through)
        lines = [f'## {title}', '', window]
        if progress is not None:
            lines.append(f'自然月时间进度 {float(progress) * 100:.1f}%')
        for item in _online_metrics(message):
            metric = item['metric']
            money = item['unit'] == '元'
            target = _metric_cell(metric, 'target', money=money)
            actual = _metric_cell(metric, 'actual', money=money)
            rate = _percent(metric.get('completion')) if metric.get('completion') is not None else _missing(None, metric.get('status'))
            lines.append(f"{item['name']}目标 {target}，完成 {actual}，完成率 {rate}")
        lines.extend(['', '| 二级渠道 | 月累计 | 当日新增 | 占比 |', '| --- | ---: | ---: | ---: |'])
        channel_rows = _online_channel_rows(message)
        if channel_rows:
            lines.extend(f'| {name} | {month} | {today} | {share} |'
                         for name, month, today, share in channel_rows)
        else:
            lines.append('| 暂无 | — | — | — |')
    else:
        window, progress, remaining = _personal_window_text(message, data_through)
        lines = [f'## {title}', '', window]
        if progress is not None:
            lines.append(f'时间进度 {float(progress) * 100:.1f}% · 剩余工作日 {remaining if remaining is not None else "—"}')
        lines.extend(['', '**落后时间进度（工单）**'])
        behind = _behind_people(message)
        if behind:
            lines.extend(
                f"- {person['name']} 工单 {_count(person['orders_actual'])}/{_count(person['orders_target'])}"
                f"（{_percent(person['orders_completion'])}），应完成 {_daily(person['expected_orders'])}，"
                f"日均需 {_daily(person['daily_orders'])} 条"
                for person in behind
            )
        else:
            lines.append('- ' + _no_behind_text(message))
    lines.extend(['', '![本地消息图片](message.png)', ''])
    if dashboard_url:
        lines.append(f'[查看看板]({dashboard_url})')
    lines.extend(['[查看HTML预览](message.html)', f'[下载{_detail_download_label(message)}](details.xlsx)', ''])
    return '\n'.join(lines)


def _render_message(message: dict, data_through: str, output_dir: Path, index: int,
                    dashboard_base_url: str | None, preview_label: str) -> dict:
    folder = output_dir / _slug(message, index)
    folder.mkdir(parents=True, exist_ok=True)
    dashboard_url = _dashboard_url(message, dashboard_base_url)
    png_path = folder / 'message.png'
    if _message_is_online(message):
        _render_online_png(message, data_through, png_path, dashboard_url)
    else:
        _render_person_png(message, data_through, png_path, dashboard_url)
    html_path = folder / 'message.html'
    html_path.write_text(_html_for_message(message, data_through, dashboard_url, preview_label), encoding='utf-8')
    xlsx_path = _write_xlsx(message, data_through, folder / 'details.xlsx')
    markdown_path = folder / 'message.md'
    markdown_path.write_text(_markdown(message, data_through, dashboard_url), encoding='utf-8')
    return {
        'id': message['id'], 'channel_id': message['channel_id'],
        'business_line': message.get('business_line'), 'title': message.get('title') or message['id'],
        'dashboard_url': dashboard_url, 'png': png_path, 'html': html_path,
        'xlsx': xlsx_path, 'markdown': markdown_path,
    }


def _write_index(messages: list[dict], data_through: str, path: Path,
                 preview_label: str) -> Path:
    cards = []
    for item in messages:
        folder = Path(item['png']).parent.name
        cards.append(f'''<article><h2>{_escape(item['title'])}</h2>
<img src="{_escape(folder)}/message.png" alt="{_escape(item['title'])}">
<p><a href="{_escape(folder)}/message.html">打开简报</a> · <a href="{_escape(folder)}/details.xlsx">本地流水附件</a></p></article>''')
    path.write_text(f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>管理推送本地预览</title><style>body{{margin:0;background:{CANVAS};color:{INK};font:16px/1.5 "Noto Sans CJK SC","PingFang SC",sans-serif}}main{{max-width:1240px;margin:auto;padding:24px}}h1{{font-size:28px}}article{{margin:20px 0;padding:20px;background:#fff;border:1px solid {LINE};border-radius:10px}}article img{{width:100%;height:auto}}a{{color:{BLUE}}}.local{{color:{MUTED};font-size:12px}}</style>
</head><body><main><p class="local">{_escape(preview_label)} · 数据截止 {_escape(data_through)}</p><h1>管理推送</h1>{''.join(cards)}</main></body></html>''', encoding='utf-8')
    return path


def render_notifications(payload: dict, output_dir: str | Path,
                         dashboard_base_url: str | None = None) -> dict:
    """Create PNG, HTML, XLSX and Markdown previews for every message."""
    messages = _validate_payload(payload)
    data_through = str(payload.get('data_through') or '')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', data_through):
        raise ValueError('notifications payload requires ISO data_through')
    if dashboard_base_url:
        dashboard_base_url = dashboard_base_url.rstrip('/')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_label = _preview_label(payload, data_through)
    artifacts = [
        _render_message(message, data_through, output_dir, index, dashboard_base_url, preview_label)
        for index, message in enumerate(messages, start=1)
    ]
    index_html = _write_index(artifacts, data_through, output_dir / 'index.html', preview_label)
    return {
        'status': 'preview_ready', 'data_through': data_through,
        'output_dir': str(output_dir.resolve()), 'index_html': str(index_html.resolve()),
        'messages': [
            {key: str(value) if isinstance(value, Path) else value for key, value in artifact.items()}
            for artifact in artifacts
        ],
    }


def _preview_label(payload: dict, data_through: str) -> str:
    as_of = (payload.get('metadata') or {}).get('as_of_date')
    if as_of:
        try:
            if date.fromisoformat(data_through) < date.fromisoformat(str(as_of)) - timedelta(days=1):
                return '历史数据预览，未发送'
        except ValueError:
            pass
    return '本地预览，未发送'


def _read_shared_notifications(shared_result_path: str | Path) -> tuple[dict, dict]:
    shared_path = Path(shared_result_path).resolve()
    shared = json.loads(shared_path.read_text(encoding='utf-8'))
    reference = shared.get('notifications_ref') or {}
    relative_path, expected_hash = reference.get('path'), reference.get('sha256')
    if not isinstance(relative_path, str) or not expected_hash:
        raise ValueError('shared result requires notifications_ref path and sha256')
    notifications_path = (shared_path.parent / relative_path).resolve()
    if not notifications_path.is_relative_to(shared_path.parent.resolve()):
        raise ValueError('notifications_ref path must stay inside the shared result directory')
    actual_hash = hashlib.sha256(notifications_path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError('notifications_ref sha256 does not match the referenced file')
    payload = json.loads(notifications_path.read_text(encoding='utf-8'))
    shared_metadata = shared.get('metadata') or {}
    notify_metadata = payload.get('metadata') or {}
    for key in ('run_id', 'snapshot_id', 'data_through'):
        if shared_metadata.get(key) is None or notify_metadata.get(key) != shared_metadata.get(key):
            raise ValueError(f'notification {key} does not match shared result metadata')
    if payload.get('data_through') != shared_metadata.get('data_through'):
        raise ValueError('notification data_through does not match shared result metadata')
    return shared, payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Render a compact local preview from a management shared result.')
    parser.add_argument('--shared-result', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--dashboard-base-url')
    args = parser.parse_args(argv)
    try:
        shared, payload = _read_shared_notifications(args.shared_result)
        result = render_notifications(payload, args.output_dir, args.dashboard_base_url)
        manifest = {
            'status': 'preview_ready',
            'run_id': (shared.get('metadata') or {}).get('run_id'),
            'snapshot_id': (shared.get('metadata') or {}).get('snapshot_id'),
            'data_through': result['data_through'],
            'index_html': result['index_html'],
            'output_dir': result['output_dir'],
            'messages': [
                {'id': item['id'], 'channel_id': item['channel_id'],
                 'png': item['png'], 'html': item['html'], 'xlsx': item['xlsx'],
                 'markdown': item['markdown'], 'dashboard_url': item['dashboard_url']}
                for item in result['messages']
            ],
        }
        print(json.dumps(manifest, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
