"""Render notify HTML, PNG, XLSX, and DingTalk markdown from a digest."""

from __future__ import annotations

import html
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image, ImageDraw, ImageFont

FONTS = (
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/System/Library/Fonts/STHeiti Light.ttc',
)


def escape(value):
    return html.escape('' if value is None else str(value), quote=True)


def format_count(value):
    if value is None:
        return '未配置'
    return f'{int(round(value)):,}'


def format_money(value):
    if value is None:
        return '未配置'
    return f'{int(round(value)):,} 元'


def format_pct(value):
    if value is None:
        return '未配置'
    return f'{value * 100:.1f}%'


def format_daily(value):
    if value is None:
        return '—'
    if value <= 0:
        return '0'
    return f'{value:.1f}'


def format_heads(value):
    if value is None:
        return '未配置'
    number = float(value)
    if number.is_integer():
        return f'{int(number):,}'
    return f'{number:.1f}'


def uses_heads(digest):
    return digest.get('secondary_metric') == 'heads'


def progress_width(value):
    if value is None:
        return 0
    return max(0, min(100, value * 100))


def render_people_html(digest):
    people_rows = []
    for person in digest['people']:
        behind_class = ' behind' if person['behind'] else ''
        order_cell = (
            f"<td class='completion{behind_class}'><span class='bar'><i style='width:{progress_width(person['orders_completion']):.1f}%'></i></span>{escape(format_pct(person['orders_completion']))}</td>"
        )
        if uses_heads(digest):
            secondary_cell = (
                f"<td class='completion'><span class='bar'><i style='width:{progress_width(person.get('heads_completion')):.1f}%'></i></span>{escape(format_pct(person.get('heads_completion')))}</td>"
            )
            secondary_target = format_heads(person.get('heads_target'))
            secondary_actual = format_heads(person.get('heads_actual'))
        else:
            secondary_cell = (
                f"<td class='completion'><span class='bar'><i style='width:{progress_width(person['cash_completion']):.1f}%'></i></span>{escape(format_pct(person['cash_completion']))}</td>"
            )
            secondary_target = format_money(person['cash_target'])
            secondary_actual = format_money(person['cash_actual'])
        people_rows.append(
            '<tr>'
            f"<th>{escape(person['display_name'])}</th>"
            f"<td>{escape(person['business_group'])}</td>"
            f"<td>{escape(format_count(person['orders_target']))}</td>"
            f"<td>{escape(format_count(person['orders_actual']))}</td>"
            f'{order_cell}'
            f"<td>{escape(format_count(person['expected_orders']))}</td>"
            f"<td>{escape(format_daily(person['daily_orders']))}</td>"
            f"<td>{escape(secondary_target)}</td>"
            f"<td>{escape(secondary_actual)}</td>"
            f'{secondary_cell}'
            '</tr>'
        )
    if not people_rows:
        people_rows.append('<tr><td colspan="10" class="empty">当前团队暂无人员</td></tr>')
    behind_items = digest['behind']
    if behind_items:
        behind_html = '<ul class="behind-list">' + ''.join(
            (
                '<li>'
                f"<strong>{escape(item['display_name'])}</strong>"
                f" 工单 {escape(format_count(item['orders_actual']))}/{escape(format_count(item['orders_target']))}"
                f"（{escape(format_pct(item['orders_completion']))}），"
                f"应完成 {escape(format_count(item['expected_orders']))}，"
                f"日均需 {escape(format_daily(item['daily_orders']))} 条"
                '</li>'
            )
            for item in behind_items
        ) + '</ul>'
    else:
        behind_html = '<p class="empty">无人落后时间进度</p>'
    progress = digest['time_progress'] * 100
    secondary_headers = ('人头目标', '人头完成', '人头完成率') if uses_heads(digest) else ('现金目标', '现金完成', '现金完成率')
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{escape(digest['display_name'])} {escape(digest['perf_month'])}人员进度</title>
<style>
:root {{ --ink:#182230; --muted:#687587; --line:#dfe5ec; --surface:#fff; --canvas:#f5f7fa; --blue:#2d6cdf; --green:#2b9a70; --red:#c34b3d; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--canvas); color:var(--ink); font:14px/1.5 "PingFang SC","Hiragino Sans GB","Noto Sans SC",sans-serif; }}
.people-panel {{ width:1100px; margin:0; padding:22px 24px 18px; background:var(--surface); }}
.eyebrow {{ color:var(--blue); font-size:11px; font-weight:800; letter-spacing:.12em; }}
h1 {{ margin:6px 0 8px; font:600 26px/1.2 "Songti SC", Georgia, serif; }}
.meta {{ color:var(--muted); font-size:12px; font-weight:700; }}
.period-progress {{ display:grid; grid-template-columns:auto minmax(80px,1fr) auto; align-items:center; gap:10px; padding:14px 0 10px; color:var(--muted); font-size:12px; font-weight:700; }}
.bar {{ display:inline-block; overflow:hidden; width:68px; height:7px; background:#e8edf3; border-radius:99px; vertical-align:middle; }}
.bar i {{ display:block; height:100%; background:var(--green); border-radius:inherit; }}
.period-progress .bar {{ width:auto; height:9px; }}
.period-progress strong {{ color:var(--blue); }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th, td {{ padding:9px 7px; border-bottom:1px solid #edf0f4; text-align:left; }}
thead th {{ color:var(--muted); font-size:11px; font-weight:800; }}
tbody th {{ font-weight:800; }}
.completion {{ white-space:nowrap; }}
.completion.behind {{ color:var(--red); font-weight:800; }}
.completion.behind .bar i {{ background:var(--red); }}
h2 {{ margin:18px 0 8px; font:600 16px/1.3 "Songti SC", Georgia, serif; }}
.behind-list {{ margin:0; padding-left:18px; }}
.behind-list li {{ margin:4px 0; }}
.empty {{ color:var(--muted); }}
.footnote {{ margin-top:14px; color:var(--muted); font-size:11px; }}
</style>
</head>
<body>
<section class="people-panel">
  <div class="eyebrow">DATA OXHOR / 人员月度贡献</div>
  <h1>{escape(digest['display_name'])}</h1>
  <p class="meta">数据截止 {escape(digest['data_through_date'])} · {escape(digest.get('month_label', '绩效月'))} {escape(digest['perf_month'])}（{escape(digest['window_start'])} 至 {escape(digest['window_end'])}） · 剩余工作日 {digest['remaining_workdays']}</p>
  <div class="period-progress"><span>{escape(digest.get('month_label', '绩效月'))}时间进度</span><span class="bar"><i style="width:{progress:.1f}%"></i></span><strong>{progress:.1f}%</strong></div>
  <table>
    <thead><tr><th>人员</th><th>业务团队</th><th>工单目标</th><th>工单完成</th><th>工单完成率</th><th>应完成</th><th>日均需完成</th><th>{escape(secondary_headers[0])}</th><th>{escape(secondary_headers[1])}</th><th>{escape(secondary_headers[2])}</th></tr></thead>
    <tbody>
      {''.join(people_rows)}
    </tbody>
  </table>
  <h2>落后时间进度（工单）</h2>
  {behind_html}
</section>
</body>
</html>
'''


def _font(size, bold=False):
    path = FONTS[1] if bold else FONTS[0]
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def render_people_png(digest, path):
    path = Path(path)
    title_font = _font(28, bold=True)
    meta_font = _font(16)
    head_font = _font(13, bold=True)
    cell_font = _font(15)
    small_font = _font(14)
    width = 1400
    pad = 36
    row_h = 38
    header_h = 34
    people = digest['people']
    behind = digest['behind']
    top = 168
    behind_block = 28 + max(len(behind), 1) * 26
    height = top + header_h + max(len(people), 1) * row_h + behind_block + 90
    image = Image.new('RGB', (width, height), '#f5f7fa')
    draw = ImageDraw.Draw(image)
    draw.rectangle([16, 16, width - 16, height - 16], fill='#ffffff', outline='#dfe5ec')
    draw.text((pad, 32), 'DATA OXHOR / 人员月度贡献', font=_font(12, bold=True), fill='#2d6cdf')
    draw.text((pad, 54), digest['display_name'], font=title_font, fill='#182230')
    meta = (
        f"数据截止 {digest['data_through_date']}  ·  {digest.get('month_label', '绩效月')} {digest['perf_month']}"
        f"（{digest['window_start']} 至 {digest['window_end']}）  ·  剩余工作日 {digest['remaining_workdays']}"
    )
    draw.text((pad, 96), meta, font=meta_font, fill='#687587')
    progress = digest['time_progress'] * 100
    draw.text((pad, 128), f"{digest.get('month_label', '绩效月')}时间进度", font=meta_font, fill='#687587')
    bar_x, bar_y, bar_w, bar_h = 210, 132, 980, 10
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=6, fill='#e8edf3')
    fill_w = max(0, min(bar_w, int(bar_w * digest['time_progress'])))
    if fill_w:
        draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], radius=6, fill='#2d6cdf')
    draw.text((bar_x + bar_w + 12, 124), f'{progress:.1f}%', font=_font(18, bold=True), fill='#2d6cdf')

    if uses_heads(digest):
        columns = [
            ('人员', 110), ('业务团队', 90), ('工单目标', 80), ('工单完成', 80),
            ('工单完成率', 100), ('应完成', 80), ('日均需完成', 90),
            ('人头目标', 90), ('人头完成', 90), ('人头完成率', 100),
        ]
    else:
        columns = [
            ('人员', 110), ('业务团队', 90), ('工单目标', 80), ('工单完成', 80),
            ('工单完成率', 100), ('应完成', 80), ('日均需完成', 90),
            ('现金目标', 110), ('现金完成', 110), ('现金完成率', 100),
        ]
    x = pad
    y = top
    draw.rectangle([pad - 8, y, width - pad + 8, y + header_h], fill='#f7f9fc')
    for label, col_w in columns:
        draw.text((x, y + 8), label, font=head_font, fill='#687587')
        x += col_w
    y += header_h
    if not people:
        draw.text((pad, y + 8), '当前团队暂无人员', font=cell_font, fill='#687587')
        y += row_h
    for person in people:
        if uses_heads(digest):
            secondary_values = (
                format_heads(person.get('heads_target')),
                format_heads(person.get('heads_actual')),
                format_pct(person.get('heads_completion')),
            )
        else:
            secondary_values = (
                format_money(person['cash_target']),
                format_money(person['cash_actual']),
                format_pct(person['cash_completion']),
            )
        values = [
            person['display_name'],
            person['business_group'],
            format_count(person['orders_target']),
            format_count(person['orders_actual']),
            format_pct(person['orders_completion']),
            format_count(person['expected_orders']),
            format_daily(person['daily_orders']),
            *secondary_values,
        ]
        x = pad
        for (label, col_w), value in zip(columns, values):
            fill = '#c34b3d' if person['behind'] and label == '工单完成率' else '#182230'
            font = _font(15, bold=True) if label == '人员' else cell_font
            draw.text((x, y + 8), str(value), font=font, fill=fill)
            x += col_w
        draw.line([pad - 8, y + row_h - 1, width - pad + 8, y + row_h - 1], fill='#edf0f4')
        y += row_h
    y += 18
    draw.text((pad, y), '落后时间进度（工单）', font=_font(18, bold=True), fill='#182230')
    y += 30
    if behind:
        for item in behind:
            line = (
                f"{item['display_name']}  工单 {format_count(item['orders_actual'])}/{format_count(item['orders_target'])}"
                f"（{format_pct(item['orders_completion'])}），应完成 {format_count(item['expected_orders'])}，"
                f"日均需 {format_daily(item['daily_orders'])} 条"
            )
            draw.text((pad, y), line, font=small_font, fill='#c34b3d')
            y += 26
    else:
        draw.text((pad, y), '无人落后时间进度', font=small_font, fill='#687587')
        y += 26
    draw.text((pad, height - 52), '明细表另附下载，不在播报中展开。', font=_font(13), fill='#687587')
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, 'PNG')
    return path


def screenshot_people_panel(html_path, png_path):
    html_path = Path(html_path).resolve()
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1140, 'height': 900}, device_scale_factor=2)
        page.goto(html_path.as_uri(), wait_until='load')
        page.locator('.people-panel').screenshot(path=str(png_path), type='png')
        browser.close()
    return png_path


def write_people_image(digest, html_path, png_path):
    import os
    if os.environ.get('NOTIFY_FORCE_PIL') == '1':
        return render_people_png(digest, png_path)
    try:
        return screenshot_people_panel(html_path, png_path)
    except Exception:
        return render_people_png(digest, png_path)


def _sheet(workbook, title, headers, rows):
    sheet = workbook.create_sheet(title)
    header_font = Font(bold=True, color='FFFFFF')
    fill = PatternFill('solid', fgColor='2D6CDF')
    for index, header in enumerate(headers, start=1):
        cell = sheet.cell(1, index, header)
        cell.font = header_font
        cell.fill = fill
        cell.alignment = Alignment(horizontal='left')
    for row_index, row in enumerate(rows, start=2):
        for col_index, value in enumerate(row, start=1):
            sheet.cell(row_index, col_index, value)
    for index, header in enumerate(headers, start=1):
        width = max(len(str(header)), *(len(str(row[index - 1])) if row[index - 1] is not None else 0 for row in rows)) if rows else len(header)
        sheet.column_dimensions[get_column_letter(index)].width = min(42, max(12, width + 2))
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = f'A1:{get_column_letter(len(headers))}{max(1, len(rows) + 1)}'


def write_details_xlsx(digest, path):
    path = Path(path)
    workbook = Workbook()
    default = workbook.active
    workbook.remove(default)
    if uses_heads(digest):
        people_rows = [
            [
                person['display_name'],
                person['business_group'],
                person['orders_target'],
                person['orders_actual'],
                None if person['orders_completion'] is None else round(person['orders_completion'] * 100, 1),
                None if person['expected_orders'] is None else round(person['expected_orders'], 1),
                None if person['daily_orders'] is None else round(person['daily_orders'], 1),
                '是' if person['behind'] else '',
                person.get('heads_target'),
                person.get('heads_actual'),
                None if person.get('heads_completion') is None else round(person['heads_completion'] * 100, 1),
                person.get('cash_target'),
                person.get('cash_actual'),
                None if person.get('cash_completion') is None else round(person['cash_completion'] * 100, 1),
            ]
            for person in digest['people']
        ]
        people_headers = [
            '人员', '业务团队', '工单目标', '工单完成', '工单完成率%', '应完成工单', '日均需完成', '落后',
            '人头目标', '人头完成', '人头完成率%',
            '现金目标', '现金完成', '现金完成率%',
        ]
    else:
        people_rows = [
            [
                person['display_name'],
                person['business_group'],
                person['orders_target'],
                person['orders_actual'],
                None if person['orders_completion'] is None else round(person['orders_completion'] * 100, 1),
                None if person['expected_orders'] is None else round(person['expected_orders'], 1),
                None if person['daily_orders'] is None else round(person['daily_orders'], 1),
                '是' if person['behind'] else '',
                person['cash_target'],
                person['cash_actual'],
                None if person['cash_completion'] is None else round(person['cash_completion'] * 100, 1),
            ]
            for person in digest['people']
        ]
        people_headers = [
            '人员', '业务团队', '工单目标', '工单完成', '工单完成率%', '应完成工单', '日均需完成', '落后',
            '现金目标', '现金完成', '现金完成率%',
        ]
    _sheet(workbook, '人员进度', people_headers, people_rows)

    warehouse = digest['warehouse']
    _sheet(workbook, '工单明细', warehouse['orders']['columns'], warehouse['orders']['rows'])
    _sheet(workbook, '现金明细', warehouse['cash']['columns'], warehouse['cash']['rows'])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def render_markdown(digest, png_url, xlsx_url):
    progress = digest['time_progress'] * 100
    lines = [
        f"## {digest['display_name']} {digest['perf_month']}{digest.get('month_label', '绩效月')}人员进度",
        '',
        f"数据截止 {digest['data_through_date']}",
        f"时间进度 {progress:.1f}%（{digest['window_start']} 至 {digest['window_end']}）",
        f"剩余工作日 {digest['remaining_workdays']}",
        '',
        f'![]({png_url})',
        '',
        '**落后时间进度（工单）**',
    ]
    if digest['behind']:
        for item in digest['behind']:
            lines.append(
                f"- {item['display_name']} {format_count(item['orders_actual'])}/{format_count(item['orders_target'])}"
                f"（{format_pct(item['orders_completion'])}），应完成 {format_count(item['expected_orders'])}，"
                f"日均需 {format_daily(item['daily_orders'])} 条"
            )
    else:
        lines.append('- 无人落后时间进度')
    lines.extend(['', f'[下载工单与现金明细]({xlsx_url})'])
    text = '\n'.join(lines)
    for forbidden in ('full.html', 'online_market_special.html'):
        if forbidden in text:
            raise ValueError(f'markdown must not link booklet {forbidden}')
    return text


def dingtalk_title(digest):
    return f"{digest['display_name']}{digest['perf_month']}人员进度"
