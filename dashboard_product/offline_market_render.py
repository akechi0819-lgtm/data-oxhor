"""Render the independent offline-market board as a self-contained HTML page."""

from __future__ import annotations

import json
from pathlib import Path


def render_html(artifact_data: dict) -> str:
    payload = json.dumps(artifact_data, ensure_ascii=False).replace("</", "<\\/")
    template = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>线下团队特供看板 · 留学</title>
<style>
:root {
  --ink: #19242e;
  --muted: #64727e;
  --line: #d9e0e5;
  --surface: #ffffff;
  --canvas: #f2f5f4;
  --teal: #087f76;
  --teal-soft: #e5f4f1;
  --green: #3c8f1c;
  --green-dark: #2c6f12;
  --yellow: #fff4b8;
  --red: #bd3a3a;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--canvas);
  color: var(--ink);
  font: 14px/1.5 "Noto Sans SC", "PingFang SC", -apple-system, BlinkMacSystemFont, sans-serif;
}
a { color: var(--teal); }
main { max-width: 1540px; margin: auto; padding: 28px 34px 40px; }
header { display: flex; justify-content: space-between; gap: 28px; align-items: flex-end; padding: 7px 0 22px; border-bottom: 1px solid var(--line); }
header small, .eyebrow { color: var(--teal); font-size: 11px; font-weight: 800; letter-spacing: .14em; }
h1 { margin: 8px 0 5px; font: 600 36px/1.12 Georgia, "Songti SC", serif; }
h2 { margin: 0; font-size: 20px; line-height: 1.25; }
h3 { margin: 0; font-size: 16px; }
p { margin: 0; color: var(--muted); }
.meta { min-width: 310px; color: var(--muted); font-size: 12px; line-height: 1.8; text-align: right; }
.meta b { color: var(--ink); }
.nav-link { display: inline-flex; margin-top: 12px; padding: 7px 11px; border: 1px solid #a7d3cc; border-radius: 6px; background: var(--teal-soft); text-decoration: none; font-weight: 800; }
.controls { display: flex; align-items: flex-end; gap: 15px; flex-wrap: wrap; padding: 18px 0 13px; }
.controls label { display: grid; gap: 5px; color: var(--muted); font-size: 12px; font-weight: 800; }
select { min-width: 148px; padding: 9px 31px 9px 11px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--ink); font: inherit; }
.hint { padding-bottom: 9px; color: var(--muted); font-size: 12px; }
.timeline { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 15px; }
.timeline-card, .panel, .metric-card { border: 1px solid var(--line); background: var(--surface); }
.timeline-card { padding: 14px 17px; border-radius: 8px; }
.timeline-label { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 9px; color: var(--muted); font-weight: 800; }
.timeline-label strong { color: var(--teal); }
.progress-track, .bar { overflow: hidden; background: #e6ecea; }
.progress-track { height: 9px; border-radius: 99px; }
.progress-fill, .bar i { display: block; height: 100%; border-radius: inherit; background: var(--teal); }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.metric-card { min-height: 136px; padding: 16px 18px 14px; border-top: 4px solid var(--teal); }
.metric-card:nth-child(2) { border-top-color: var(--green); }
.metric-card:nth-child(3) { border-top-color: #a7afb6; }
.metric-head { display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-weight: 800; }
.metric-scope { font-size: 11px; font-weight: 600; }
.metric-card strong { display: block; margin-top: 12px; font: 600 29px/1 Georgia, "Songti SC", serif; }
.metric-card .metric-note { margin-top: 10px; color: var(--muted); font-size: 12px; }
.panel { min-width: 0; margin-top: 14px; padding: 18px 19px; border-radius: 8px; }
.panel-head { display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; margin-bottom: 14px; }
.section-kicker { margin-top: 5px; font-size: 12px; }
.target-band { border-top: 4px solid var(--green); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 9px; border-bottom: 1px solid var(--line); white-space: nowrap; text-align: right; }
th:first-child, td:first-child { text-align: left; }
thead th { color: var(--muted); font-size: 12px; font-weight: 800; background: #f7faf9; }
tbody th { font-weight: 800; }
.target-band thead th { background: #eef7e9; }
.target-row th, .target-row td { background: #f4faef; font-weight: 800; }
.total-row th, .total-row td { background: #f5f8f7; font-weight: 900; }
.completion { display: inline-grid; grid-template-columns: 72px auto; align-items: center; gap: 7px; }
.completion .bar { height: 7px; border-radius: 99px; }
.completion .bar i { background: var(--green); }
.negative { color: var(--red); }
.muted-cell { color: var(--muted); }
.notice { padding: 11px 13px; border-left: 3px solid #d7a02a; background: #fff9df; color: #66531f; font-size: 12px; }
.notice + .notice { margin-top: 8px; }
.grid-two { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(320px, .75fr); gap: 14px; }
.drill-toggle { padding: 5px 9px; border: 1px solid #a7d3cc; border-radius: 5px; background: var(--teal-soft); color: var(--teal); cursor: pointer; font: inherit; font-size: 12px; font-weight: 800; }
.drill-toggle:hover, .drill-toggle:focus-visible { border-color: var(--teal); }
.drill-row td { padding: 5px 0 12px; background: #f8fbfa; }
.nested-table { width: calc(100% - 18px); margin: 4px 0 0 18px; }
.nested-table th, .nested-table td { padding-top: 8px; padding-bottom: 8px; }
.empty { padding: 24px 10px; color: var(--muted); text-align: center; }
@media (max-width: 1080px) { .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } .grid-two { grid-template-columns: 1fr; } }
@media (max-width: 680px) { main { padding: 20px 15px 28px; } header { display: block; } .meta { min-width: 0; margin-top: 12px; text-align: left; } h1 { font-size: 31px; } .timeline, .cards { grid-template-columns: 1fr; } .panel { padding: 15px; } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; transition: none !important; } }
</style>
</head>
<body>
<main>
<header>
  <div>
    <small>DATA OXHOR / OFFLINE MARKET</small>
    <h1>线下团队特供看板</h1>
    <p>留学线下 · 数据使用影子数仓</p>
    <a class="nav-link" href="full.html">← 返回主看板线下市场</a>
  </div>
  <div class="meta">影子 Snapshot<br><b id="snapshot"></b><br>数据截至 <b id="through"></b></div>
</header>
<section id="study-view">
<section class="controls" id="study-controls">
  <label>范围<select id="scope"><option value="year">全年 FY27</option><option value="Q1">Q1</option><option value="Q2">Q2</option><option value="Q3">Q3</option><option value="Q4">Q4</option></select></label>
  <label id="month-control" hidden>月份<select id="month"></select></label>
  <span class="hint">部门完成只加留学线下团队映射到的人。绩效月为上月 26 日至本月 25 日。现金实际暂未接入。</span>
</section>
<div id="timeline" class="timeline"></div>
  <div id="cards" class="cards"></div>
  <div class="notice">留学线下特供按团队人员加总：有效工单 ID、团队为空，并映射到孙伟、吴子玄、邓睿、王洪霞、王衡利、杨芸聿、马玥、高书航。认人顺序为资源录入人 → 活动主责 → 市场人员/数据提供方 → 转介绍；括号协作和“不算新”不计入。未映射的人不进部门完成。二级渠道、国家、学校仍是这批人的拆解。看板不展示一级渠道。</div>
  <section class="panel target-band"><div class="panel-head"><div><h2>目标</h2><p class="section-kicker">全年工单 2620、毛签 660 万元按留学官方记分卡累计；2026-10 部门目标单独登记。现金实际待接入。</p></div></div><div id="targets" class="table-wrap"></div></section>
  <section class="panel"><div class="panel-head"><div><h2>人员完成</h2><p class="section-kicker">部门完成等于下列人员加总；名单内无人命中时显示 0。2026-10 个人目标与部门目标分别登记。</p></div></div><div id="people" class="table-wrap"></div></section>
  <div class="grid-two">
    <section class="panel"><div class="panel-head"><div><h2>二级渠道进度</h2><p class="section-kicker">按活动类型、同名高校、个人/对公渠道和新东方部门查看当期、同期和同比。</p></div></div><div id="platforms" class="table-wrap"></div></section>
    <section class="panel"><div class="panel-head"><div><h2>国家与条线</h2><p class="section-kicker">先查看条线，再展开对应国家；不参与当前目标计算。</p></div></div><div id="dimensions"></div></section>
  </div>
  <section class="panel"><div class="panel-head"><div><h2>学校</h2><p class="section-kicker">只分大学以上、大学以下两类；点开后看具体学校名称。优先学生学校名称，其次所在学校；毕业 / 在职 / 研究生等向上信号计入大学以上。</p></div></div><div id="schools" class="table-wrap"></div></section>
</section>
</main>
<script>

const D = __PAYLOAD__;
const S = document.querySelector('#scope');
const M = document.querySelector('#month');
const MONTH_CONTROL = document.querySelector('#month-control');
const MONTHS = D.months;
const PRIOR_MONTHS = D.prior_months;
const SCHOOL_BANDS = ['大学以上', '大学以下'];
const PEOPLE_ORDER = D.study_abroad?.scope?.people || [];
const QUARTER_MONTHS = { Q1: ['2026-06', '2026-07', '2026-08'], Q2: ['2026-09', '2026-10', '2026-11'], Q3: ['2026-12', '2027-01', '2027-02'], Q4: ['2027-03', '2027-04', '2027-05'] };
document.querySelector('#snapshot').textContent = D.shadow_snapshot_id || '未绑定';
document.querySelector('#through').textContent = D.data_through_date || '未绑定';
function escapeHtml(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character])); }
function count(value) { return Math.round(value || 0).toLocaleString(); }
function pct(value) { return value == null ? '—' : (value * 100).toFixed(1) + '%'; }
function yoy(current, prior) { return prior > 0 ? (current - prior) / prior : null; }
function updateMonthOptions() { if (S.value === 'year') { M.innerHTML = ''; MONTH_CONTROL.hidden = true; return; } const options = QUARTER_MONTHS[S.value] || []; M.innerHTML = '<option value="all">全部' + S.value + '</option>' + options.map(month => '<option value="' + month + '">' + month + '</option>').join(''); M.value = 'all'; MONTH_CONTROL.hidden = false; }
function selectedPeriodLabel() { return S.value === 'year' ? '全年' : (M.value && M.value !== 'all' ? M.value : S.value); }
function periodRange() { if (S.value === 'year') return [0, 12]; if (M.value && M.value !== 'all') { const index = MONTHS.indexOf(M.value); return index >= 0 ? [index, 1] : [0, 3]; } return ({ Q1: [0, 3], Q2: [3, 3], Q3: [6, 3], Q4: [9, 3] })[S.value] || [0, 12]; }
function sumSeries(series, key) { const [start, length] = periodRange(); return (series?.[key] || []).slice(start, start + length).reduce((sum, value) => sum + (value || 0), 0); }
function selectedSeries(period) { return period.total; }
function targetFor(group) { if (group === 'total') return D.targets.total?.work_order_target || null; return D.targets.groups?.[group]?.work_order_target || null; }
function workTargetFor(group) { if (S.value === 'year') return targetFor(group); const target = group === 'total' ? D.targets.total : D.targets.groups?.[group]; if (M.value && M.value !== 'all') return target?.months?.[M.value] ?? null; return target?.quarters?.[S.value] ?? null; }
function selectedTarget() { return workTargetFor('total'); }
function cashTargetFor(group) { if (group === 'total') return D.targets.cash?.total || null; return D.targets.cash?.groups?.[group] || null; }
function selectedCashTarget() { return cashTargetFor('total'); }
function countTarget(value) { return Number(value).toLocaleString(undefined, {minimumFractionDigits: Number(value) % 1 ? 2 : 0, maximumFractionDigits: 2}); }
function cashMoney(value) { return value == null ? (M.value && M.value !== 'all' ? '月度目标待确认' : '未配置') : Number(value).toFixed(2) + ' 万元'; }
function completion(actual, target) { return target > 0 ? actual / target : null; }
function progressBar(value) { if (value == null) return '<span class="muted-cell">' + (M.value && M.value !== 'all' ? '月度目标待确认' : (S.value === 'year' ? '未配置' : '未拆季度')) + '</span>'; const width = Math.max(0, Math.min(100, value * 100)); return '<span class="completion"><span class="bar"><i style="width:' + width + '%"></i></span>' + pct(value) + '</span>'; }
function renderTimeline() {
  const fyStart = new Date('2026-05-26'); const fyEnd = new Date('2027-05-26'); const today = new Date(D.as_of_date); const fy = Math.max(0, Math.min(100, (today - fyStart) / (fyEnd - fyStart) * 100));
  const [start, length] = periodRange(); const starts = [new Date('2026-05-26'), new Date('2026-08-26'), new Date('2026-11-26'), new Date('2027-02-26')]; const ends = [new Date('2026-08-26'), new Date('2026-11-26'), new Date('2027-02-26'), new Date('2027-05-26')]; let periodProgress = fy; if (M.value && M.value !== 'all') { const monthStart = new Date(M.value + '-26'); monthStart.setMonth(monthStart.getMonth() - 1); const monthEnd = new Date(M.value + '-26'); periodProgress = Math.max(0, Math.min(100, (today - monthStart) / (monthEnd - monthStart) * 100)); } else if (S.value !== 'year') { periodProgress = Math.max(0, Math.min(100, (today - starts[start / 3]) / (ends[start / 3] - starts[start / 3]) * 100)); }
  document.querySelector('#timeline').innerHTML = '<div class="timeline-card"><div class="timeline-label"><span>FY27 时间进度</span><strong>' + fy.toFixed(1) + '%</strong></div><div class="progress-track"><span class="progress-fill" style="width:' + fy + '%"></span></div></div><div class="timeline-card"><div class="timeline-label"><span>' + selectedPeriodLabel() + ' 时间进度</span><strong>' + periodProgress.toFixed(1) + '%</strong></div><div class="progress-track"><span class="progress-fill" style="width:' + periodProgress + '%"></span></div></div>';
}
function renderCards() {
  const current = selectedSeries(D.study_abroad.current); const prior = selectedSeries(D.study_abroad.prior); const actual = sumSeries(current, 'orders'); const previous = sumSeries(prior, 'orders'); const target = selectedTarget(); const completionValue = completion(actual, target);
  const cards = [
    ['留学线下工单数', count(actual), '同期 ' + count(previous) + ' · 同比 ' + pct(yoy(actual, previous))],
    [S.value === 'year' ? '年度目标完成' : selectedPeriodLabel() + '目标完成', completionValue == null ? (M.value && M.value !== 'all' ? '月度目标待确认' : '—') : pct(completionValue), target == null ? (M.value && M.value !== 'all' ? '月度目标待确认' : '目标未配置') : '目标 ' + count(target) + ' 条'],
    ['现金实际', '待接入', '实际明细待接入']
  ];
  document.querySelector('#cards').innerHTML = cards.map(item => '<article class="metric-card"><div class="metric-head"><span>' + item[0] + '</span><span class="metric-scope">' + (S.value === 'year' ? 'FY27' : selectedPeriodLabel()) + '</span></div><strong>' + item[1] + '</strong><div class="metric-note">' + item[2] + '</div></article>').join('');
}
function renderTargets() {
  const total = { target: selectedTarget(), cash: selectedCashTarget(), actual: sumSeries(selectedSeries(D.study_abroad.current), 'orders') };
  const isYear = S.value === 'year'; const period = S.value; const isMonth = M.value && M.value !== 'all'; const workHeader = isYear ? '年度工单目标' : (isMonth ? '月度工单目标' : period + '工单目标'); const cashHeader = isYear ? '年度毛签目标（万元）' : (isMonth ? '月度毛签目标（万元）' : period + '毛签目标（万元）');
  const rate = completion(total.actual, total.target); const cashValue = isYear ? total.cash?.annual : (isMonth ? total.cash?.months?.[M.value] : total.cash?.quarters?.[period]);
  let html = '<table><thead><tr><th></th><th>' + workHeader + '</th><th>当前工单</th><th>工单完成率</th><th>' + cashHeader + '</th></tr></thead><tbody>';
  html += '<tr class="total-row"><th>合计</th><td>' + (total.target == null ? (isMonth ? '月度目标待确认' : (isYear ? '未配置' : '未拆季度')) : countTarget(total.target)) + '</td><td>' + count(total.actual) + '</td><td>' + progressBar(rate) + '</td><td>' + cashMoney(cashValue) + '</td></tr>';
  document.querySelector('#targets').innerHTML = html + '</tbody></table>';
}
function renderPlatforms() {
  const current = D.study_abroad.current.platforms || {}; const prior = D.study_abroad.prior.platforms || {}; const names = [...new Set([...Object.keys(current), ...Object.keys(prior)])];
  const rows = names.map(name => { const now = sumSeries(current[name]?.series, 'orders'); const old = sumSeries(prior[name]?.series, 'orders'); return { name, now, old }; }).filter(row => row.now > 0 || row.old > 0).sort((a, b) => b.now - a.now || a.name.localeCompare(b.name, 'zh-CN')); const total = rows.reduce((sum, row) => sum + row.now, 0);
  if (!rows.length) { document.querySelector('#platforms').innerHTML = '<div class="empty">当前范围暂无二级渠道数据</div>'; return; }
  let html = '<table><thead><tr><th>二级渠道</th><th>当前工单</th><th>同期工单</th><th>同比</th><th>当前占比</th></tr></thead><tbody>';
  rows.forEach(row => { const change = yoy(row.now, row.old); html += '<tr><th>' + escapeHtml(row.name) + '</th><td>' + count(row.now) + '</td><td>' + count(row.old) + '</td><td class="' + (change != null && change < 0 ? 'negative' : '') + '">' + pct(change) + '</td><td>' + pct(total > 0 ? row.now / total : null) + '</td></tr>'; });
  const priorTotal = rows.reduce((sum, row) => sum + row.old, 0); const totalChange = yoy(total, priorTotal);
  html += '<tr class="total-row"><th>合计</th><td>' + count(total) + '</td><td>' + count(priorTotal) + '</td><td class="' + (totalChange != null && totalChange < 0 ? 'negative' : '') + '">' + pct(totalChange) + '</td><td>100.0%</td></tr>';
  document.querySelector('#platforms').innerHTML = html + '</tbody></table>';
}
function renderCountryRows(currentValues, priorValues) { const names = [...new Set([...Object.keys(currentValues || {}), ...Object.keys(priorValues || {})])].map(name => { const now = sumSeries(currentValues[name], 'orders'); const old = sumSeries(priorValues[name], 'orders'); return { name, now, old }; }).sort((a, b) => b.now - a.now || a.name.localeCompare(b.name, 'zh-CN')); if (!names.length) return '<div class="empty">该条线暂无国家数据</div>'; return '<table class="nested-table"><thead><tr><th>意向国家</th><th>工单</th><th>同期</th><th>同比</th></tr></thead><tbody>' + names.map(row => { const change = yoy(row.now, row.old); return '<tr><th>' + escapeHtml(row.name) + '</th><td>' + count(row.now) + '</td><td>' + count(row.old) + '</td><td class="' + (change != null && change < 0 ? 'negative' : '') + '">' + pct(change) + '</td></tr>'; }).join('') + '</tbody></table>'; }
function renderLineDrilldown() { const current = D.study_abroad.current.lines || {}; const prior = D.study_abroad.prior.lines || {}; const names = [...new Set([...Object.keys(current), ...Object.keys(prior)])].map(name => { const now = sumSeries(current[name]?.series, 'orders'); const old = sumSeries(prior[name]?.series, 'orders'); return { name, now, old }; }).sort((a, b) => b.now - a.now || a.name.localeCompare(b.name, 'zh-CN')); if (!names.length) return '<div class="empty">暂无条线数据</div>'; let html = '<table><thead><tr><th>矫正条线</th><th>工单</th><th>同期</th><th>同比</th><th>下钻</th></tr></thead><tbody>'; names.forEach((row, index) => { const change = yoy(row.now, row.old); const drillId = 'line-drill-' + index; const currentCountries = current[row.name]?.countries || {}; const priorCountries = prior[row.name]?.countries || {}; html += '<tr><th>' + escapeHtml(row.name) + '</th><td>' + count(row.now) + '</td><td>' + count(row.old) + '</td><td class="' + (change != null && change < 0 ? 'negative' : '') + '">' + pct(change) + '</td><td><button class="drill-toggle" data-drill="' + drillId + '" aria-expanded="false">展开国家</button></td></tr><tr id="' + drillId + '" class="drill-row" hidden><td colspan="5">' + renderCountryRows(currentCountries, priorCountries) + '</td></tr>'; }); return html + '</tbody></table>'; }
function wireDimensionDrills() { document.querySelectorAll('#dimensions .drill-toggle').forEach(button => { button.onclick = () => { const row = document.querySelector('#' + button.dataset.drill); const open = row.hidden; row.hidden = !open; button.textContent = open ? '收起国家' : '展开国家'; button.setAttribute('aria-expanded', String(open)); }; }); }
function renderDimensions() { document.querySelector('#dimensions').innerHTML = renderLineDrilldown(); wireDimensionDrills(); }
function renderSchoolNameRows(currentValues, priorValues) { const names = [...new Set([...Object.keys(currentValues || {}), ...Object.keys(priorValues || {})])].map(name => { const now = sumSeries(currentValues[name], 'orders'); const old = sumSeries(priorValues[name], 'orders'); return { name, now, old }; }).sort((a, b) => b.now - a.now || a.name.localeCompare(b.name, 'zh-CN')); if (!names.length) return '<div class="empty">该类暂无学校数据</div>'; return '<table class="nested-table"><thead><tr><th>学校名称</th><th>工单</th><th>同期</th><th>同比</th></tr></thead><tbody>' + names.map(row => { const change = yoy(row.now, row.old); return '<tr><th>' + escapeHtml(row.name) + '</th><td>' + count(row.now) + '</td><td>' + count(row.old) + '</td><td class="' + (change != null && change < 0 ? 'negative' : '') + '">' + pct(change) + '</td></tr>'; }).join('') + '</tbody></table>'; }
function renderSchoolDrilldown() { const current = D.study_abroad.current.schools || {}; const prior = D.study_abroad.prior.schools || {}; const names = SCHOOL_BANDS.filter(name => (current[name] || prior[name])); if (!names.length) return '<div class="empty">暂无学校数据</div>'; let html = '<table><thead><tr><th>学校类别</th><th>工单</th><th>同期</th><th>同比</th><th>下钻</th></tr></thead><tbody>'; names.forEach((name, index) => { const now = sumSeries(current[name]?.series, 'orders'); const old = sumSeries(prior[name]?.series, 'orders'); const change = yoy(now, old); const drillId = 'school-drill-' + index; html += '<tr><th>' + escapeHtml(name) + '</th><td>' + count(now) + '</td><td>' + count(old) + '</td><td class="' + (change != null && change < 0 ? 'negative' : '') + '">' + pct(change) + '</td><td><button class="drill-toggle" data-drill="' + drillId + '" aria-expanded="false">展开学校</button></td></tr><tr id="' + drillId + '" class="drill-row" hidden><td colspan="5">' + renderSchoolNameRows(current[name]?.schools || {}, prior[name]?.schools || {}) + '</td></tr>'; }); return html + '</tbody></table>'; }
function wireSchoolDrills() { document.querySelectorAll('#schools .drill-toggle').forEach(button => { button.onclick = () => { const row = document.querySelector('#' + button.dataset.drill); const open = row.hidden; row.hidden = !open; button.textContent = open ? '收起学校' : '展开学校'; button.setAttribute('aria-expanded', String(open)); }; }); }
function renderSchools() { document.querySelector('#schools').innerHTML = renderSchoolDrilldown(); wireSchoolDrills(); }
function renderPeople() {
  const current = D.study_abroad.current.people || {};
  const prior = D.study_abroad.prior.people || {};
  const names = [...new Set([...(PEOPLE_ORDER || []), ...Object.keys(current), ...Object.keys(prior)])];
  const selectedMonth = M.value && M.value !== 'all' ? M.value : null;
  const peopleTargets = Object.fromEntries((D.targets.people || []).map(person => [person.display_name, person.monthly_targets || {}]));
  const rows = names.map(name => {
    const now = sumSeries(current[name], 'orders');
    const old = sumSeries(prior[name], 'orders');
    const targets = selectedMonth ? peopleTargets[name]?.[selectedMonth] : null;
    return { name, now, old, targets };
  });
  const total = rows.reduce((sum, row) => sum + row.now, 0);
  let html = '<table><thead><tr><th>市场人员</th><th>工单目标</th><th>签约目标</th><th>当前工单</th><th>同期工单</th><th>同比</th><th>当前占比</th></tr></thead><tbody>';
  rows.forEach(row => {
    const change = yoy(row.now, row.old);
    html += '<tr><th>' + escapeHtml(row.name) + '</th><td>' + (row.targets?.orders ?? '未配置') + '</td><td>' + (row.targets?.cash == null ? '未配置' : cashMoney(row.targets.cash / 10000)) + '</td><td>' + count(row.now) + '</td><td>' + count(row.old) + '</td><td class="' + (change != null && change < 0 ? 'negative' : '') + '">' + pct(change) + '</td><td>' + pct(total > 0 ? row.now / total : null) + '</td></tr>';
  });
  const priorTotal = rows.reduce((sum, row) => sum + row.old, 0);
  const totalChange = yoy(total, priorTotal);
  html += '<tr class="total-row"><th>合计</th><td>—</td><td>—</td><td>' + count(total) + '</td><td>' + count(priorTotal) + '</td><td class="' + (totalChange != null && totalChange < 0 ? 'negative' : '') + '">' + pct(totalChange) + '</td><td>100.0%</td></tr>';
  document.querySelector('#people').innerHTML = html + '</tbody></table>';
}
function renderStudy() { renderTimeline(); renderCards(); renderTargets(); renderPeople(); renderPlatforms(); renderDimensions(); renderSchools(); }
S.addEventListener('change', () => { updateMonthOptions(); renderStudy(); });
M.addEventListener('change', renderStudy);
updateMonthOptions();
renderStudy();
</script>
</body>
</html>
'''
    return template.replace("__PAYLOAD__", payload)


def render(artifact: Path, output: Path | None = None) -> dict:
    artifact = artifact.resolve()
    data = json.loads(artifact.read_text(encoding="utf-8"))
    target = output.resolve() if output else artifact.with_name("offline_market_special.html")
    target.write_text(render_html(data), encoding="utf-8")
    return {"status": "rendered", "output": str(target)}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = render(args.artifact, args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
