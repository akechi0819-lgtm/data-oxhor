#!/usr/bin/env python3
"""Render the dashboard artifact as a self-contained HTML report."""

from dashboard_product.booklets import booklet_chrome, filter_dashboard_for_booklet


def render_html(artifact_data, booklet=None):
    dashboard = filter_dashboard_for_booklet(artifact_data['dashboard'], booklet)
    chrome = booklet_chrome(booklet)
    snapshot_id = artifact_data['snapshot_id']
    run_id = artifact_data['run_id']
    artifact_id = artifact_data['artifact_id']
    created_at = artifact_data['created_at']
    as_of_date = artifact_data['as_of_date']
    data_through_date = artifact_data['data_through_date']

    dashboard['period'] = {
        'project_label': 'FY27（2026-06-01 至 2027-05-31）',
        'performance_label': '每月 26 日至次月 25 日',
        'current_date': as_of_date,
        'fiscal_year_start': '2026-06-01'
    }

    import json

    dashboard_json = json.dumps(dashboard, ensure_ascii=False).replace('</', '<\\/')
    template = '''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(page_title)s</title>
<style>
:root {
  --ink: #182230;
  --muted: #687587;
  --line: #dfe5ec;
  --surface: #ffffff;
  --canvas: #f5f7fa;
  --blue: #2d6cdf;
  --blue-soft: #eaf1ff;
  --orange: #e87842;
  --green: #2b9a70;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--canvas);
  color: var(--ink);
  font: 14px/1.5 "Noto Sans SC", "PingFang SC", -apple-system, BlinkMacSystemFont, sans-serif;
}
main { max-width: 1540px; margin: auto; padding: 28px 34px 36px; }
header { display: flex; justify-content: space-between; gap: 30px; align-items: flex-end; padding: 8px 0 24px; border-bottom: 1px solid var(--line); }
header small, .eyebrow { color: var(--blue); font-size: 11px; font-weight: 800; letter-spacing: .14em; }
h1 { margin: 8px 0 6px; font: 600 38px/1.1 Georgia, "Songti SC", serif; letter-spacing: 0; }
p { margin: 0; color: var(--muted); }
.meta { min-width: 300px; color: var(--muted); font-size: 12px; line-height: 1.8; text-align: right; }
.meta b { color: var(--ink); font-weight: 700; }
.special-board-link { display: inline-block; margin-top: 8px; color: var(--blue); font-size: 12px; font-weight: 800; text-decoration: none; }
.special-board-link:hover, .special-board-link:focus-visible { text-decoration: underline; }
.controls { display: flex; align-items: flex-end; gap: 16px; flex-wrap: wrap; padding: 18px 0 12px; }
.controls label { display: grid; gap: 5px; color: var(--muted); font-size: 12px; font-weight: 700; }
select, button { font: inherit; }
select { min-width: 142px; padding: 9px 32px 9px 12px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--ink); }
.controls .hint { padding-bottom: 10px; color: var(--muted); font-size: 12px; }
.timeline { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 0 0 15px; }
.timeline-card { padding: 15px 17px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
.timeline-label { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 9px; color: var(--muted); font-weight: 700; }
.timeline-label strong { color: var(--blue); font-size: 16px; }
.progress-track, .bar { overflow: hidden; background: #e8edf3; }
.progress-track { height: 10px; border-radius: 99px; }
.progress-fill, .bar i { display: block; height: 100%; background: var(--blue); border-radius: inherit; }
.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 18px; }
.tabs button { padding: 10px 16px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--muted); cursor: pointer; font-weight: 700; }
.tabs button:hover { border-color: #aabbd4; color: var(--blue); }
.tabs button.active { border-color: var(--blue); background: var(--blue); color: #fff; }
.cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.metric-card { min-height: 146px; padding: 17px 20px 15px; border: 1px solid var(--line); border-top: 4px solid var(--blue); background: var(--surface); }
.metric-card:nth-child(2) { border-top-color: var(--orange); }
.metric-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.metric-card small { color: var(--muted); font-weight: 700; }
.metric-card .metric-scope { color: var(--muted); font-size: 11px; }
.metric-card strong { display: block; margin-top: 10px; font: 600 30px/1 Georgia, "Songti SC", serif; }
.metric-details { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 14px; }
.metric-detail { min-width: 0; color: var(--ink); font-size: 13px; font-weight: 700; }
.metric-detail em { display: block; margin-bottom: 2px; color: var(--muted); font-size: 10px; font-style: normal; font-weight: 600; }
@media (max-width: 620px) { .metric-details { grid-template-columns: repeat(2, minmax(0, 1fr)); row-gap: 9px; } }
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(350px, .8fr); gap: 14px; }
.panel { min-width: 0; padding: 20px; border: 1px solid var(--line); background: var(--surface); }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 15px; }
h2 { margin: 0; font: 600 21px/1.2 Georgia, "Songti SC", serif; }
.section-kicker { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.table-wrap { width: 100%; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; }
th, td { padding: 11px 9px; border-bottom: 1px solid #edf0f4; text-align: left; }
thead th { color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .04em; }
tbody th { color: var(--ink); font-weight: 800; }
.completion { display: flex; align-items: center; gap: 7px; }
.bar { display: inline-block; width: 68px; height: 7px; flex: 0 0 auto; border-radius: 99px; vertical-align: middle; }
.bar i { background: var(--green); }
.people-panel { display: flex; min-height: 0; flex-direction: column; grid-column: 1 / -1; }
.people-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.people-filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.people-toolbar label { color: var(--muted); font-size: 12px; font-weight: 700; }
.people-toolbar select { min-width: 110px; padding-top: 7px; padding-bottom: 7px; }
#peopleDetail { border-top: 1px solid var(--line); }
#peopleDetail table { min-width: 0; width: 100%; table-layout: fixed; white-space: normal; }
#peopleDetail th, #peopleDetail td { padding: 8px 6px; vertical-align: middle; }
#peopleDetail th:nth-child(1) { width: 8%; }
#peopleDetail th:nth-child(2) { width: 9%; }
#peopleDetail th:nth-child(3), #peopleDetail th:nth-child(4), #peopleDetail th:nth-child(6), #peopleDetail th:nth-child(7) { width: 8%; }
#peopleDetail th:nth-child(5), #peopleDetail th:nth-child(8) { width: 12%; }
#peopleDetail th:nth-child(9), #peopleDetail th:nth-child(10) { width: 7%; }
#peopleDetail .completion { gap: 4px; }
#peopleDetail .completion .bar { width: 42px; }
#peopleDetail .drill-row td { padding-left: 16px; }
.period-progress { display: grid; grid-template-columns: auto minmax(80px, 1fr) auto; align-items: center; gap: 10px; padding: 12px 0; color: var(--muted); font-size: 12px; font-weight: 700; }
.period-progress .bar { width: auto; height: 9px; }
.period-progress strong { color: var(--blue); }
.comparison { margin-top: 14px; }
.comparison + .comparison { margin-top: 14px; }
.comparison table { min-width: 760px; }
.channel-matrix table { min-width: 1680px; }
.channel-matrix .total-row th, .channel-matrix .total-row td { font-weight: 800; background: #f7f9fc; }
.channel-matrix thead th { text-align: center; vertical-align: bottom; }
.channel-matrix thead th:first-child, .channel-matrix tbody th { text-align: left; }
.channel-matrix td { text-align: right; }
.channel-matrix .group-head { border-left: 1px solid var(--line); }
.negative { color: #c34b3d; font-weight: 800; }
.comparison .metric { color: var(--muted); font-weight: 700; }
.drill-toggle { padding: 5px 9px; border: 1px solid #b9ccef; border-radius: 5px; background: var(--blue-soft); color: var(--blue); cursor: pointer; font-size: 11px; font-weight: 700; }
.drill-toggle:hover { background: #dce8ff; }
.drill-row td { padding: 0 12px 14px 28px; background: #fafbfd; }
.drill-table { margin-top: 10px; font-size: 12px; }
.drill-table th, .drill-table td { padding: 8px; }
.drill-table thead th { color: var(--muted); }
.drill-table .negative { color: #c34b3d; font-weight: 800; }
.empty-drill { padding: 12px 0 3px; color: var(--muted); }

body.capacity-mode .comparison { display: none; }
.capacity-layout { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(340px, .85fr); gap: 14px; }
.capacity-toolbar { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.capacity-toolbar label { display: grid; gap: 5px; color: var(--muted); font-size: 12px; font-weight: 700; }
.capacity-table tbody tr { cursor: pointer; }
.capacity-table tbody tr:hover { background: #f3f6fb; }
.capacity-table tbody tr.selected { background: var(--blue-soft); }
.radar-wrap { display: flex; justify-content: center; padding: 6px 0 2px; }
.radar-legend { display: flex; gap: 18px; justify-content: center; margin: 6px 0 10px; color: var(--muted); font-size: 12px; font-weight: 700; }
.radar-legend i { display: inline-block; width: 11px; height: 11px; margin-right: 6px; vertical-align: -1px; border: 1px solid transparent; }
.radar-legend .avg i { background: rgba(104,117,135,.28); border-color: #8b97a7; }
.radar-legend .person i { background: rgba(45,108,223,.28); border-color: var(--blue); }
.dim-table td:not(:first-child), .dim-table th:not(:first-child) { text-align: right; }
#scope:disabled { color: var(--muted); }
@media (max-width: 980px) { .capacity-layout { grid-template-columns: 1fr; } }
footer { margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; }
@media (max-width: 980px) { main { padding: 22px 18px 28px; } .dashboard-grid { grid-template-columns: 1fr; } }
@media (max-width: 650px) { header { display: block; } .meta { min-width: 0; margin-top: 12px; text-align: left; } h1 { font-size: 32px; } .timeline, .cards { grid-template-columns: 1fr; } .timeline-label { align-items: flex-start; flex-direction: column; gap: 3px; } .panel { padding: 16px; } }
</style>
</head>
<body>
<main>
<header>
  <div><small>DATA OXHOR / OPERATIONS</small><h1>Cyber Shackles</h1><p>%(period_line)s</p>%(special_board_link)s</div>
  <div class="meta">Snapshot<br><b>%(snapshot_id)s</b><br>数据截至 %(data_through_date)s · 刷新 %(created_at)s</div>
</header>
<section class="controls"><label>范围<select id="scope"><option value="year">全年 FY27</option><option value="Q1">Q1</option><option value="Q2" selected>Q2</option><option value="Q3">Q3</option><option value="Q4">Q4</option></select></label><label id="month-control" hidden>月份<select id="month"></select></label><span class="hint">范围和月份筛选只影响本地汇总与下钻窗口</span></section>
<div id="timeline" class="timeline"></div>
<nav id="tabs" class="tabs"></nav>
<div id="view"></div>
<section class="panel comparison"><div class="panel-head"><div><h2>业务组同期对比</h2><p class="section-kicker">现金与工单按团队口径分别下钻到一级、二级渠道</p></div></div><div id="yoy-comparison" class="table-wrap"></div></section>
<section class="panel comparison channel-matrix"><div class="panel-head"><div><h2>渠道同期对比</h2><p class="section-kicker">行是二级渠道，列是青少、初中、高中、大学，右侧合计该渠道全部现金、工单及占总现金占比，按合计现金降序；底行总计。组内现金占比仍是该渠道当期现金中该业务组份额</p></div></div><div id="channel-matrix" class="table-wrap"></div></section>
<section class="panel comparison"><div class="panel-head"><div><h2>业务组同期对比 · 年级</h2><p class="section-kicker">%(grade_kicker)s</p></div></div><div id="grade-comparison" class="table-wrap"></div></section>
<footer>Artifact %(artifact_id)s · Run %(run_id)s</footer>
</main>
<script>
const D = %(dashboard_json)s;
const SCHOOL_DRILL_GROUPS = %(school_grade_groups_json)s;
const TODAY = new Date(D.period.current_date);
const S = document.querySelector('#scope');
const M = document.querySelector('#month');
const MONTH_CONTROL = document.querySelector('#month-control');
const T = document.querySelector('#tabs');
const V = document.querySelector('#view');
const YOY = document.querySelector('#yoy-comparison');
const CHANNEL = document.querySelector('#channel-matrix');
const GRADE = document.querySelector('#grade-comparison');
const YOY_GROUP_NAMES = ['青少', '初中', '高中', '大学'];
const UNASSIGNED_GROUP = '业务组暂无法拆分';
const EMPTY_DRILLS = { current: { cash: { channel: {}, school_grade: {} }, orders: { channel: {}, school_grade: {} } }, prior: { cash: { channel: {}, school_grade: {} }, orders: { channel: {}, school_grade: {} } } };
const DRILLS = D.drilldowns;
const QUARTER_MONTHS = { Q1: ['2026-06', '2026-07', '2026-08'], Q2: ['2026-09', '2026-10', '2026-11'], Q3: ['2026-12', '2027-01', '2027-02'], Q4: ['2027-03', '2027-04', '2027-05'] };
function escapeHtml(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character])); }
function money(value) { return value == null ? '未配置' : Math.round(value).toLocaleString() + ' 元'; }
function count(value) { return value == null ? '未配置' : Math.round(value).toLocaleString(); }
function pct(value) { return value == null ? 'N/A' : (value * 100).toFixed(1) + '%'; }
function updateMonthOptions(reset = false) { if (S.value === 'year' || !M) { if (MONTH_CONTROL) MONTH_CONTROL.hidden = true; if (M) M.innerHTML = ''; return; } const previous = M.value; const options = QUARTER_MONTHS[S.value] || []; M.innerHTML = '<option value="all">全部' + S.value + '</option>' + options.map(month => '<option value="' + month + '">' + month + '</option>').join(''); M.value = !reset && options.includes(previous) ? previous : 'all'; MONTH_CONTROL.hidden = false; }
function selectedPeriodLabel() { return S.value === 'year' ? '全年' : (M?.value && M.value !== 'all' ? M.value : S.value); }
function target(group, key) { if (S.value === 'year') return group.annual_targets[key]; if (M?.value && M.value !== 'all') return null; return (group.quarter_targets[S.value] || {})[key] ?? null; }
function totalTarget(team, key) { const values = team.groups.map(group => target(group, key)); return values.some(value => value != null) ? values.reduce((total, value) => total + (value || 0), 0) : null; }
function range() { if (S.value === 'year') return [0, 12]; if (M?.value && M.value !== 'all') { const index = D.months.indexOf(M.value); return index >= 0 ? [index, 1] : [0, 3]; } return ({ Q1: [0, 3], Q2: [3, 3], Q3: [6, 3], Q4: [9, 3] })[S.value] || [0, 12]; }
function progressBar(value) { if (value == null) return '未配置'; const width = Math.min(100, Math.max(0, value * 100)); return '<span class="completion"><span class="bar"><i style="width:' + width + '%"></i></span>' + pct(value) + '</span>'; }
function selectedTeam() { return D.teams.find(team => team.team_id === T.querySelector('.active')?.dataset.id) || D.teams[0]; }
function addDrill(source, months, teamId, groupName, start, length, targetMap) {
  Object.entries(source || {}).forEach(([key, value]) => { const parts = key.split('|'); if (parts.length < 5 || parts[1] !== teamId || parts[2] !== groupName) return; const monthIndex = months.indexOf(parts[0]); if (monthIndex < start || monthIndex >= start + length) return; const drillKey = parts.slice(3).join('||'); targetMap[drillKey] = (targetMap[drillKey] || 0) + value; });
}
const GRADE_ORDER = ['学龄前', '幼儿园小班', '幼儿园中班', '幼儿园大班', '幼儿', '一年级', '二年级', '三年级', '四年级', '五年级', '六年级', '七年级', '八年级', '九年级', '高一', '高二', '高三', '大一', '大二', '大三', '大四', '研一', '研二', '研三', '研究生以上', '大学已毕业', '在职'];
function gradeRank(value) { const text = String(value == null ? '' : value).trim(); const exact = GRADE_ORDER.indexOf(text); if (exact >= 0) return exact; if (text.includes('学龄前') || text.includes('学前')) return 0; const preschool = text.match(/幼儿园(小班|中班|大班)/); if (preschool) return 1 + ['小班', '中班', '大班'].indexOf(preschool[1]); const numbered = text.match(/([一二三四五六七八九])年级/); if (numbered) return 5 + ['一', '二', '三', '四', '五', '六', '七', '八', '九'].indexOf(numbered[1]); const compact = text.match(/(高|大|研)(一|二|三|四)/); if (compact) return { 高: 14, 大: 17, 研: 21 }[compact[1]] + ['一', '二', '三', '四'].indexOf(compact[2]); return 1000; }
function sortGrades(grades, current, prior) { return grades.sort((a, b) => { const rankDifference = gradeRank(a) - gradeRank(b); if (rankDifference) return rankDifference; const valueDifference = (current[b] || 0) + (prior[b] || 0) - (current[a] || 0) - (prior[a] || 0); return valueDifference || String(a).localeCompare(String(b), 'zh-CN'); }); }
function compareDrill(current, prior, metric, labels) {
  const keys = [...new Set([...Object.keys(current), ...Object.keys(prior)])];
  if (!keys.length) return '<div class="empty-drill">当前范围暂无明细</div>';
  const formatter = metric === 'cash' ? money : count;
  let html = '<table class="drill-table"><thead><tr>' + labels.map(label => '<th>' + label + '</th>').join('') + '<th>当期</th><th>同期</th><th>同比</th></tr></thead><tbody>';
  (labels.length === 1 && labels[0] === '年级' ? sortGrades(keys, current, prior) : keys.sort((a, b) => (current[b] || 0) - (current[a] || 0))).forEach(key => { const parts = key.split('||'); const currentValue = current[key] || 0; const priorValue = prior[key] || 0; const yoy = priorValue > 0 ? (currentValue - priorValue) / priorValue : null; html += '<tr>' + parts.map(part => '<td>' + escapeHtml(part) + '</td>').join('') + '<td>' + formatter(currentValue) + '</td><td>' + formatter(priorValue) + '</td><td class="' + (yoy !== null && yoy < 0 ? 'negative' : '') + '">' + pct(yoy) + '</td></tr>'; });
  return html + '</tbody></table>';
}
function compareUniversityDrill(current, prior, metric, drillId) {
  const grouped = (values, result) => Object.entries(values).forEach(([key, value]) => { const parts = key.split('||'); const school = parts[0]; const grade = parts[1]; result[school] ??= {}; result[school][grade] = (result[school][grade] || 0) + value; });
  const currentSchools = {}; const priorSchools = {}; grouped(current, currentSchools); grouped(prior, priorSchools);
  const schools = [...new Set([...Object.keys(currentSchools), ...Object.keys(priorSchools)])];
  if (!schools.length) return '<div class="empty-drill">当前范围暂无明细</div>';
  let html = '<table class="drill-table"><thead><tr><th>学校</th><th>当期</th><th>同期</th><th>同比</th><th>下钻</th></tr></thead><tbody>';
  schools.sort((a, b) => Object.values(currentSchools[b] || {}).reduce((sum, value) => sum + value, 0) - Object.values(currentSchools[a] || {}).reduce((sum, value) => sum + value, 0)).forEach((school, index) => {
    const currentValue = Object.values(currentSchools[school] || {}).reduce((sum, value) => sum + value, 0); const priorValue = Object.values(priorSchools[school] || {}).reduce((sum, value) => sum + value, 0); const yoy = priorValue > 0 ? (currentValue - priorValue) / priorValue : null; const childId = drillId + '-school-' + index;
    html += '<tr><td>' + escapeHtml(school) + '</td><td>' + (metric === 'cash' ? money(currentValue) : count(currentValue)) + '</td><td>' + (metric === 'cash' ? money(priorValue) : count(priorValue)) + '</td><td class="' + (yoy !== null && yoy < 0 ? 'negative' : '') + '">' + pct(yoy) + '</td><td><button class="drill-toggle" data-drill="' + childId + '">展开年级</button></td></tr>';
    const grades = [...new Set([...Object.keys(currentSchools[school] || {}), ...Object.keys(priorSchools[school] || {})])]; let child = '<table class="drill-table"><thead><tr><th>年级</th><th>当期</th><th>同期</th><th>同比</th></tr></thead><tbody>';
    sortGrades(grades, currentSchools[school] || {}, priorSchools[school] || {}).forEach(grade => { const gradeCurrent = currentSchools[school]?.[grade] || 0; const gradePrior = priorSchools[school]?.[grade] || 0; const gradeYoy = gradePrior > 0 ? (gradeCurrent - gradePrior) / gradePrior : null; child += '<tr><td>' + escapeHtml(grade) + '</td><td>' + (metric === 'cash' ? money(gradeCurrent) : count(gradeCurrent)) + '</td><td>' + (metric === 'cash' ? money(gradePrior) : count(gradePrior)) + '</td><td class="' + (gradeYoy !== null && gradeYoy < 0 ? 'negative' : '') + '">' + pct(gradeYoy) + '</td></tr>'; });
    html += '<tr id="' + childId + '" class="drill-row" hidden><td colspan="5">' + child + '</tbody></table></td></tr>';
  });
  return html + '</tbody></table>';
}
function channelDrill(groupName, teamId, start, length, metric) { const current = {}; const prior = {}; addDrill(DRILLS.current[metric].channel, D.months, teamId, groupName, start, length, current); addDrill(DRILLS.prior[metric].channel, D.prior_months, teamId, groupName, start, length, prior); return compareDrill(current, prior, metric, ['一级渠道', '二级渠道']); }
function gradeDrill(groupName, teamId, start, length, metric, university, drillId) {
  const current = {}; const prior = {};
  addDrill(DRILLS.current[metric].school_grade, D.months, teamId, groupName, start, length, current);
  addDrill(DRILLS.prior[metric].school_grade, D.prior_months, teamId, groupName, start, length, prior);
  if (university) return compareUniversityDrill(current, prior, metric, drillId);
  const flatten = values => Object.entries(values).reduce((result, [key, value]) => { const grade = key.split('||')[1]; result[grade] = (result[grade] || 0) + value; return result; }, {});
  const currentGrades = flatten(current); const priorGrades = flatten(prior); const sortedGrades = sortGrades([...new Set([...Object.keys(currentGrades), ...Object.keys(priorGrades)])], currentGrades, priorGrades); return compareDrill(Object.fromEntries(sortedGrades.map(grade => [grade, currentGrades[grade] || 0])), Object.fromEntries(sortedGrades.map(grade => [grade, priorGrades[grade] || 0])), metric, ['年级']);
}
function wireDrills(container) { container.querySelectorAll('.drill-toggle').forEach(button => { if (button.dataset.wired) return; button.dataset.wired = '1'; const expand = button.textContent; const collapse = expand.replace('展开', '收起'); button.onclick = () => { const row = document.querySelector('#' + button.dataset.drill); row.hidden = !row.hidden; button.textContent = row.hidden ? expand : collapse; }; }); }
function yoyGroups(team) {
  return team.yoy_groups || [];
}
function sourceTeams() { return D.teams.filter(item => item.team_id && item.team_id !== 'market_total'); }
function groupOf(team, name) { return (team.groups || []).find(group => group.display_name === name); }
function addChannelMetric(source, months, teamId, start, length, targetMap) {
  Object.entries(source || {}).forEach(([key, value]) => { const parts = key.split('|'); if (parts.length < 5 || parts[1] !== teamId) return; const monthIndex = months.indexOf(parts[0]); if (monthIndex < start || monthIndex >= start + length) return; const group = parts[2], channel = parts[4]; targetMap[channel] ??= {}; targetMap[channel][group] = (targetMap[channel][group] || 0) + value; });
}
function matrixGroups(team) { return team.team_id === 'market_total' ? [...YOY_GROUP_NAMES, UNASSIGNED_GROUP] : YOY_GROUP_NAMES; }
function channelTotal(map, channel, groups) { return groups.reduce((sum, group) => sum + (map[channel]?.[group] || 0), 0); }
function channelGroupTotal(map, group) { return Object.keys(map).reduce((sum, channel) => sum + (map[channel]?.[group] || 0), 0); }
function channelMetricCells(cash, prior, orders, priorOrdersValue, shareBase) {
  const cashYoy = prior > 0 ? (cash - prior) / prior : null; const orderYoy = priorOrdersValue > 0 ? (orders - priorOrdersValue) / priorOrdersValue : null; const share = shareBase > 0 ? cash / shareBase : null;
  return '<td class="group-head">' + money(cash) + '</td><td class="' + (cashYoy !== null && cashYoy < 0 ? 'negative' : '') + '">' + pct(cashYoy) + '</td><td>' + count(orders) + '</td><td class="' + (orderYoy !== null && orderYoy < 0 ? 'negative' : '') + '">' + pct(orderYoy) + '</td><td>' + pct(share) + '</td>';
}
function renderChannelMatrix() {
  const team = selectedTeam(); const [start, length] = range(); const teamId = team.team_id;
  const matrixGroupNames = matrixGroups(team);
  const currentCash = {}, priorCash = {}, currentOrders = {}, priorOrders = {};
  addChannelMetric(DRILLS.current.cash.channel, D.months, teamId, start, length, currentCash);
  addChannelMetric(DRILLS.prior.cash.channel, D.prior_months, teamId, start, length, priorCash);
  addChannelMetric(DRILLS.current.orders.channel, D.months, teamId, start, length, currentOrders);
  addChannelMetric(DRILLS.prior.orders.channel, D.prior_months, teamId, start, length, priorOrders);
  const channels = [...new Set([...Object.keys(currentCash), ...Object.keys(priorCash), ...Object.keys(currentOrders), ...Object.keys(priorOrders)])];
  if (!channels.length) { CHANNEL.innerHTML = '<div class="empty-drill">当前范围暂无渠道明细</div>'; return; }
  const grandCash = channels.reduce((sum, channel) => sum + channelTotal(currentCash, channel, matrixGroupNames), 0);
  const grandPriorCash = channels.reduce((sum, channel) => sum + channelTotal(priorCash, channel, matrixGroupNames), 0);
  const grandOrders = channels.reduce((sum, channel) => sum + channelTotal(currentOrders, channel, matrixGroupNames), 0);
  const grandPriorOrders = channels.reduce((sum, channel) => sum + channelTotal(priorOrders, channel, matrixGroupNames), 0);
  channels.sort((a, b) => channelTotal(currentCash, b, matrixGroupNames) - channelTotal(currentCash, a, matrixGroupNames) || String(a).localeCompare(String(b), 'zh-CN'));
  const groupHead = matrixGroupNames.map(name => '<th class="group-head" colspan="5">' + escapeHtml(name) + '</th>').join('') + '<th class="group-head" colspan="5">合计</th>';
  const metricHead = matrixGroupNames.map(() => '<th class="group-head">现金</th><th>同比</th><th>工单</th><th>同比</th><th>现金占比</th>').join('') + '<th class="group-head">现金</th><th>同比</th><th>工单</th><th>同比</th><th>现金占比</th>';
  let html = '<table><thead><tr><th rowspan="2">二级渠道</th>' + groupHead + '</tr><tr>' + metricHead + '</tr></thead><tbody>';
  channels.forEach(channel => {
    const cashTotal = channelTotal(currentCash, channel, matrixGroupNames);
    html += '<tr><th>' + escapeHtml(channel) + '</th>';
    matrixGroupNames.forEach(group => {
      html += channelMetricCells(currentCash[channel]?.[group] || 0, priorCash[channel]?.[group] || 0, currentOrders[channel]?.[group] || 0, priorOrders[channel]?.[group] || 0, cashTotal);
    });
    html += channelMetricCells(cashTotal, channelTotal(priorCash, channel, matrixGroupNames), channelTotal(currentOrders, channel, matrixGroupNames), channelTotal(priorOrders, channel, matrixGroupNames), grandCash);
    html += '</tr>';
  });
  html += '<tr class="total-row"><th>总计</th>';
  matrixGroupNames.forEach(group => {
    html += channelMetricCells(channelGroupTotal(currentCash, group), channelGroupTotal(priorCash, group), channelGroupTotal(currentOrders, group), channelGroupTotal(priorOrders, group), grandCash);
  });
  html += channelMetricCells(grandCash, grandPriorCash, grandOrders, grandPriorOrders, grandCash) + '</tr>';
  CHANNEL.innerHTML = html + '</tbody></table>';
}
function renderTeamShareTable(groupName, parentCash, parentOrders, sum) {
  const teams = sourceTeams();
  if (!teams.length) return '<div class="empty-drill">当前范围暂无团队明细</div>';
  let html = '<table class="drill-table"><thead><tr><th>团队</th><th>现金目标</th><th>现金实际</th><th>现金完成</th><th>现金占比</th><th>工单目标</th><th>工单实际</th><th>工单完成</th><th>工单占比</th></tr></thead><tbody>';
  teams.forEach(item => {
    const group = groupOf(item, groupName); const cash = group ? sum(group, 'cash') : 0; const orders = group ? sum(group, 'orders') : 0; const cashTarget = group ? target(group, 'cash') : null; const ordersTarget = group ? target(group, 'orders') : null;
    html += '<tr><th>' + escapeHtml(item.display_name) + '</th><td>' + money(cashTarget) + '</td><td>' + money(cash) + '</td><td>' + progressBar(cashTarget ? cash / cashTarget : null) + '</td><td>' + pct(parentCash > 0 ? cash / parentCash : null) + '</td><td>' + count(ordersTarget) + '</td><td>' + count(orders) + '</td><td>' + progressBar(ordersTarget ? orders / ordersTarget : null) + '</td><td>' + pct(parentOrders > 0 ? orders / parentOrders : null) + '</td></tr>';
  });
  return html + '</tbody></table>';
}
function renderGroupRows(team, sum, priorSum) {
  if (team.team_id !== 'market_total') {
    return team.groups.map(group => '<tr><th>' + escapeHtml(group.display_name) + '</th><td>' + money(target(group, 'cash')) + '</td><td>' + money(sum(group, 'cash')) + '</td><td>' + progressBar(target(group, 'cash') ? sum(group, 'cash') / target(group, 'cash') : null) + '</td><td>' + count(target(group, 'orders')) + '</td><td>' + count(sum(group, 'orders')) + '</td><td>' + progressBar(target(group, 'orders') ? sum(group, 'orders') / target(group, 'orders') : null) + '</td></tr>').join('');
  }
  let html = '';
  team.groups.forEach((group, index) => {
    const drillId = 'group-channel-' + index; const cash = sum(group, 'cash'); const orders = sum(group, 'orders'); const priorCash = priorSum(group, 'cash'); const priorOrders = priorSum(group, 'orders');
    const totalCash = team.groups.reduce((total, item) => total + sum(item, 'cash'), 0); const totalOrders = team.groups.reduce((total, item) => total + sum(item, 'orders'), 0);
    const cashYoy = priorCash > 0 ? (cash - priorCash) / priorCash : null; const orderYoy = priorOrders > 0 ? (orders - priorOrders) / priorOrders : null;
    html += '<tr><th>' + escapeHtml(group.display_name) + '</th><td>' + money(target(group, 'cash')) + '</td><td>' + money(cash) + '</td><td>' + money(priorCash) + '</td><td>' + pct(cashYoy) + '</td><td>' + pct(totalCash > 0 ? cash / totalCash : null) + '</td><td>' + count(target(group, 'orders')) + '</td><td>' + count(orders) + '</td><td>' + count(priorOrders) + '</td><td>' + pct(orderYoy) + '</td><td>' + pct(totalOrders > 0 ? orders / totalOrders : null) + '</td><td><button class="drill-toggle" data-drill="' + drillId + '">展开团队严格归属渠道</button></td></tr>';
    html += '<tr id="' + drillId + '" class="drill-row" hidden><td colspan="12"><strong>现金渠道</strong>' + channelDrill(group.display_name, team.team_id, ...range(), 'cash') + '<strong>工单渠道</strong>' + channelDrill(group.display_name, team.team_id, ...range(), 'orders') + '</td></tr>';
  });
  return html;
}
function renderComparison(container, mode) {
  const team = selectedTeam(); const [start, length] = range(); const isGrade = mode === 'grade';
  let html = '<table><thead><tr><th>业务组</th><th>指标</th><th>去年同期</th><th>今年实际</th><th>同比</th><th>下钻</th></tr></thead><tbody>';
  yoyGroups(team).forEach((group, index) => ['cash', 'orders'].forEach((metric, metricIndex) => {
    const currentValue = group.monthly_actuals[metric].slice(start, start + length).reduce((sum, value) => sum + value, 0);
    const priorValue = group.prior_monthly_actuals[metric].slice(start, start + length).reduce((sum, value) => sum + value, 0);
    const yoy = priorValue > 0 ? (currentValue - priorValue) / priorValue : null;
    const drillId = mode + '-drill-' + index + '-' + metric;
    const detail = isGrade ? gradeDrill(group.display_name, team.team_id, start, length, metric, SCHOOL_DRILL_GROUPS.includes(group.display_name), drillId) : channelDrill(group.display_name, team.team_id, start, length, metric);
    html += '<tr>' + (metricIndex === 0 ? '<th rowspan="2">' + escapeHtml(group.display_name) + '</th>' : '') + '<td class="metric">' + (metric === 'cash' ? '现金' : '工单') + '</td><td>' + (metric === 'cash' ? money(priorValue) : count(priorValue)) + '</td><td>' + (metric === 'cash' ? money(currentValue) : count(currentValue)) + '</td><td class="' + (yoy !== null && yoy < 0 ? 'negative' : '') + '">' + pct(yoy) + '</td><td><button class="drill-toggle" data-drill="' + drillId + '">展开下钻</button></td></tr>';
    html += '<tr id="' + drillId + '" class="drill-row" hidden><td colspan="5">' + detail + '</td></tr>';
  }));
  container.innerHTML = html + '</tbody></table>'; wireDrills(container);
}
function performanceMonthProgress(month) { const [year, monthNumber] = month.split('-').map(Number); const end = new Date(year, monthNumber - 1, 25, 23, 59, 59); const start = new Date(year, monthNumber - 2, 26); return Math.max(0, Math.min(100, (TODAY - start) / (end - start) * 100)); }
function personTarget(person, month, metric) { return person.monthly_targets?.[month]?.[metric] ?? null; }
function personChannelDetail(person, month, metric) {
  const values = person.monthly_drilldowns?.[month]?.[metric] || {};
  const keys = Object.keys(values).sort((a, b) => (values[b] || 0) - (values[a] || 0));
  if (!keys.length) return '<div class="empty-drill">当前绩效月暂无渠道明细</div>';
  const formatter = metric === 'cash' ? money : count;
  return '<table class="drill-table"><thead><tr><th>一级渠道</th><th>二级渠道</th><th>完成</th></tr></thead><tbody>' + keys.map(key => { const parts = key.split('||'); return '<tr><td>' + escapeHtml(parts[0]) + '</td><td>' + escapeHtml(parts[1]) + '</td><td>' + formatter(values[key]) + '</td></tr>'; }).join('') + '</tbody></table>';
}
function renderPeople(team, month) {
  const container = document.querySelector('#peopleDetail'); const index = D.months.indexOf(month); const progress = performanceMonthProgress(month); const selectedGroup = document.querySelector('#peopleGroup')?.value || 'all';
  const allRows = (team.people || []).filter(person => person.business_group && (selectedGroup === 'all' || person.business_group === selectedGroup)).map(person => ({ person, cash: person.monthly_actuals?.cash?.[index] || 0, orders: person.monthly_actuals?.orders?.[index] || 0 }));
  let html = '<div class="period-progress"><span>绩效月时间进度</span><span class="bar"><i style="width:' + progress.toFixed(1) + '%"></i></span><strong>' + progress.toFixed(1) + '%</strong></div><table><thead><tr><th>人员</th><th>业务团队</th><th>工单目标</th><th>工单完成</th><th>工单完成率</th><th>现金目标</th><th>现金完成</th><th>现金完成率</th><th>工单渠道</th><th>现金渠道</th></tr></thead><tbody>';
  allRows.forEach((row, rowIndex) => {
    const orderTarget = personTarget(row.person, month, 'orders'); const cashTarget = personTarget(row.person, month, 'cash'); const orderCompletion = orderTarget > 0 ? row.orders / orderTarget : null; const cashCompletion = cashTarget > 0 ? row.cash / cashTarget : null; const orderDrillId = 'person-orders-' + rowIndex; const cashDrillId = 'person-cash-' + rowIndex;
    const drillButton = (id, label) => '<button class="drill-toggle" data-drill="' + id + '">' + label + '</button>';
    html += '<tr><th>' + escapeHtml(row.person.display_name) + '</th><td>' + escapeHtml(row.person.business_group) + '</td><td>' + count(orderTarget) + '</td><td>' + count(row.orders) + '</td><td>' + progressBar(orderCompletion) + '</td><td>' + money(cashTarget) + '</td><td>' + money(row.cash) + '</td><td>' + progressBar(cashCompletion) + '</td><td>' + drillButton(orderDrillId, '展开') + '</td><td>' + drillButton(cashDrillId, '展开') + '</td></tr>';
    html += '<tr id="' + orderDrillId + '" class="drill-row" hidden><td colspan="10">' + personChannelDetail(row.person, month, 'orders') + '</td></tr>';
    html += '<tr id="' + cashDrillId + '" class="drill-row" hidden><td colspan="10">' + personChannelDetail(row.person, month, 'cash') + '</td></tr>';
  });
  if (!allRows.length) html += '<tr><td colspan="10" class="empty-drill">当前筛选暂无人员</td></tr>';
  container.innerHTML = html + '</tbody></table>'; wireDrills(container);
}
function renderTimeline() {
  const fyStart = new Date('2026-06-01'); const fyEnd = new Date('2027-06-01'); const fyProgress = Math.max(0, Math.min(100, (TODAY - fyStart) / (fyEnd - fyStart) * 100)); const quarterRanges = { Q1: ['2026-06-01', '2026-09-01'], Q2: ['2026-09-01', '2026-12-01'], Q3: ['2026-12-01', '2027-03-01'], Q4: ['2027-03-01', '2027-06-01'] }; const quarter = quarterRanges[S.value]; let periodProgress = fyProgress; if (M?.value && M.value !== 'all') { const monthStart = new Date(M.value + '-01'); const monthEnd = new Date(monthStart); monthEnd.setMonth(monthEnd.getMonth() + 1); periodProgress = Math.max(0, Math.min(100, (TODAY - monthStart) / (monthEnd - monthStart) * 100)); } else if (S.value !== 'year') { periodProgress = Math.max(0, Math.min(100, (TODAY - new Date(quarter[0])) / (new Date(quarter[1]) - new Date(quarter[0])) * 100)); }
  document.querySelector('#timeline').innerHTML = '<div class="timeline-card"><div class="timeline-label"><span>FY27 年度时间进度</span><strong>' + fyProgress.toFixed(1) + '%</strong></div><div class="progress-track"><div class="progress-fill" style="width:' + fyProgress + '%"></div></div></div><div class="timeline-card"><div class="timeline-label"><span>' + selectedPeriodLabel() + ' 时间进度</span><strong>' + periodProgress.toFixed(1) + '%</strong></div><div class="progress-track"><div class="progress-fill" style="width:' + periodProgress + '%"></div></div></div>';
}

const CAPACITY_ID = 'staff_capacity';
const CAPACITY_DIMS = [
  { key: 'orders', label: '工单数', kind: 'count' },
  { key: 'heads', label: '签约量', kind: 'count' },
  { key: 'conversion', label: '转化率', kind: 'pct' },
  { key: 'partner', label: '渠道&校代贡献', kind: 'cash' },
  { key: 'tmk', label: 'TMK贡献', kind: 'cash' },
  { key: 'campaign', label: '活动贡献', kind: 'cash' }
];
let capacitySelected = null;
function isCapacityTab() { return T.querySelector('.active')?.dataset.id === CAPACITY_ID; }
function fyProgressRatio() { const fyStart = new Date('2026-06-01'); const fyEnd = new Date('2027-06-01'); return Math.max(0, Math.min(1, (TODAY - fyStart) / (fyEnd - fyStart))); }
function capacityMetrics(person) {
  const orders = Number(person.orders_actual || 0);
  const heads = Number(person.heads_actual || 0);
  const mix = person.cash_contributions || {};
  return {
    name: person.display_name,
    cash: Number(person.cash_actual || 0),
    orders,
    heads,
    conversion: orders > 0 ? heads / orders : 0,
    partner: Number(mix.partner || 0),
    tmk: Number(mix.tmk || 0),
    campaign: Number(mix.campaign || 0),
    capacity: Number(person.annual_cash_capacity || 800000),
    line: person.line,
    teamName: person.team_name,
    teamId: person.team_id,
    businessGroup: person.business_group
  };
}
function capacityPeerKey(row) {
  if (row.teamId === 'offline_market') return 'offline|' + (row.businessGroup || '未分组');
  return row.teamId || 'online';
}
function capacityPeerLabel(row) {
  if (row.teamId === 'offline_market') return (row.businessGroup || '未分组') + '均值';
  return (row.teamName || '团队') + '均值';
}
function capacityTeamAverage(rows, selected) {
  const key = selected ? capacityPeerKey(selected) : '';
  const peers = rows.filter(row => capacityPeerKey(row) === key);
  const mean = {};
  CAPACITY_DIMS.forEach(dim => { mean[dim.key] = peers.length ? peers.reduce((sum, row) => sum + (row[dim.key] || 0), 0) / peers.length : 0; });
  return { mean, peers, label: selected ? capacityPeerLabel(selected) : '团队均值' };
}
function capacityPeople() {
  const line = renderCapacityView._line || 'all';
  const rows = [];
  sourceTeams().forEach(team => {
    const teamLine = team.team_id === 'offline_market' ? 'offline' : 'online';
    (team.people || []).forEach(person => {
      const item = Object.assign({}, person, { line: person.line || teamLine, team_name: team.display_name, team_id: team.team_id });
      if (line !== 'all' && (item.line || teamLine) !== line) return;
      rows.push(capacityMetrics(item));
    });
  });
  rows.sort((a, b) => b.cash - a.cash || String(a.name).localeCompare(String(b.name), 'zh-CN'));
  return rows;
}
function formatDim(kind, value) {
  if (kind === 'cash') return money(value);
  if (kind === 'pct') return pct(value);
  return count(value);
}
function radarSvg(person, average, maxes) {
  const size = 320, cx = 160, cy = 168, radius = 96;
  const n = CAPACITY_DIMS.length;
  const rings = [0.25, 0.5, 0.75, 1].map(scale => {
    const pts = CAPACITY_DIMS.map((_, i) => {
      const angle = -Math.PI / 2 + i * 2 * Math.PI / n;
      return (cx + Math.cos(angle) * radius * scale).toFixed(1) + ',' + (cy + Math.sin(angle) * radius * scale).toFixed(1);
    }).join(' ');
    return '<polygon points="' + pts + '" fill="none" stroke="#dfe5ec" stroke-width="1"></polygon>';
  }).join('');
  const axes = CAPACITY_DIMS.map((dim, i) => {
    const angle = -Math.PI / 2 + i * 2 * Math.PI / n;
    const x = cx + Math.cos(angle) * radius;
    const y = cy + Math.sin(angle) * radius;
    const lx = cx + Math.cos(angle) * (radius + 28);
    const ly = cy + Math.sin(angle) * (radius + 28);
    return '<line x1="' + cx + '" y1="' + cy + '" x2="' + x.toFixed(1) + '" y2="' + y.toFixed(1) + '" stroke="#dfe5ec"></line><text x="' + lx.toFixed(1) + '" y="' + ly.toFixed(1) + '" text-anchor="middle" dominant-baseline="middle" font-size="11" font-weight="700" fill="#687587">' + escapeHtml(dim.label) + '</text>';
  }).join('');
  const pointsOf = values => CAPACITY_DIMS.map((dim, i) => {
    const angle = -Math.PI / 2 + i * 2 * Math.PI / n;
    const max = maxes[dim.key] > 0 ? maxes[dim.key] : 1;
    const rr = radius * Math.max(0, Math.min(1, (values[dim.key] || 0) / max));
    return (cx + Math.cos(angle) * rr).toFixed(1) + ',' + (cy + Math.sin(angle) * rr).toFixed(1);
  }).join(' ');
  return '<svg class="radar" viewBox="0 0 ' + size + ' 336" width="100%" height="336">' + rings + axes + '<polygon points="' + pointsOf(average) + '" fill="rgba(104,117,135,.22)" stroke="#8b97a7" stroke-width="2"></polygon><polygon points="' + pointsOf(person) + '" fill="rgba(45,108,223,.22)" stroke="#2d6cdf" stroke-width="2"></polygon></svg>';
}
function renderCapacityView() {
  S.value = 'year';
  S.disabled = true;
  updateMonthOptions();
  document.body.classList.add('capacity-mode');
  const hint = document.querySelector('.controls .hint');
  if (hint) hint.textContent = '产能页固定全年 FY27';
  const rows = capacityPeople();
  if (!rows.some(row => row.name === capacitySelected)) capacitySelected = rows[0]?.name || null;
  const selected = rows.find(row => row.name === capacitySelected) || rows[0];
  const peer = capacityTeamAverage(rows, selected); const mean = peer.mean;
  const maxes = {};
  CAPACITY_DIMS.forEach(dim => { maxes[dim.key] = Math.max(mean[dim.key] || 0, ...(peer.peers || []).map(row => row[dim.key] || 0), selected ? (selected[dim.key] || 0) : 0); });
  const pace = fyProgressRatio();
  let table = '<table class="capacity-table"><thead><tr><th>排名</th><th>人员</th><th>团队</th><th>业务组</th><th>已产生现金</th><th>标准参考产能</th><th>时间进度完成率</th></tr></thead><tbody>';
  rows.forEach((row, index) => {
    const expected = row.capacity > 0 ? row.capacity * pace : null;
    const rate = expected > 0 ? row.cash / expected : null;
    table += '<tr data-name="' + escapeHtml(row.name) + '"' + (row.name === capacitySelected ? ' class="selected"' : '') + '><td>' + (index + 1) + '</td><th>' + escapeHtml(row.name) + '</th><td>' + escapeHtml(row.teamName || '') + '</td><td>' + escapeHtml(row.businessGroup || '') + '</td><td>' + money(row.cash) + '</td><td>' + money(row.capacity) + '</td><td class="' + (rate !== null && rate < 1 ? 'negative' : '') + '">' + progressBar(rate) + '</td></tr>';
  });
  if (!rows.length) table += '<tr><td colspan="7" class="empty-drill">当前筛选暂无人员</td></tr>';
  table += '</tbody></table>';
  let radar = '<div class="empty-drill">当前筛选暂无人员</div>';
  if (selected) {
    let dims = '<table class="dim-table"><thead><tr><th>六维</th><th>个人</th><th>团队均值</th><th>相对均值</th></tr></thead><tbody>';
    CAPACITY_DIMS.forEach(dim => {
      const personValue = selected[dim.key] || 0;
      const avgValue = mean[dim.key] || 0;
      const rel = avgValue > 0 ? (personValue - avgValue) / avgValue : null;
      dims += '<tr><th>' + escapeHtml(dim.label) + '</th><td>' + formatDim(dim.kind, personValue) + '</td><td>' + formatDim(dim.kind, avgValue) + '</td><td class="' + (rel !== null && rel < 0 ? 'negative' : '') + '">' + pct(rel) + '</td></tr>';
    });
    dims += '</tbody></table>';
    radar = '<div class="radar-wrap">' + radarSvg(selected, mean, maxes) + '</div><div class="radar-legend"><span class="avg"><i></i>' + escapeHtml(peer.label) + '</span><span class="person"><i></i>' + escapeHtml(selected.name) + '</span></div>' + dims;
  }
  V.innerHTML = '<div class="capacity-layout"><section class="panel people-panel"><div class="panel-head"><div><h2>市场人员产能</h2><p class="section-kicker">全年已产生现金对照统一标准产能 80 万；时间进度完成率 = 现金 / (80万 × 年度时间进度)。按现金从高到低排列。</p></div></div><div class="capacity-toolbar"><label>团队<select id="capacityLine"><option value="all">全部</option><option value="offline">线下</option><option value="online">线上</option></select></label><span class="hint">点击一行看六维对比</span></div><div class="table-wrap">' + table + '</div></section><section class="panel"><div class="panel-head"><div><h2>个人六维对比</h2><p class="section-kicker">工单数、签约量、转化率，加上渠道&校代 / TMK / 活动三类现金贡献。灰色是本团队均值：线下按留学预备/高中/大学，线上私域整队一个均值。蓝色是个人。</p></div></div>' + radar + '</section></div>';
  const lineSelect = document.querySelector('#capacityLine');
  if (lineSelect) {
    lineSelect.value = renderCapacityView._line || 'all';
    lineSelect.onchange = event => { renderCapacityView._line = event.target.value; renderCapacityView(); };
  }
  V.querySelectorAll('.capacity-table tbody tr[data-name]').forEach(row => {
    row.onclick = () => { capacitySelected = row.dataset.name; renderCapacityView(); };
  });
}

function renderView() {
  if (isCapacityTab()) { renderCapacityView(); return; }
  document.body.classList.remove('capacity-mode');
  S.disabled = false;
  updateMonthOptions();
  const hint = document.querySelector('.controls .hint');
  if (hint) hint.textContent = '范围和月份筛选只影响本地汇总与下钻窗口';

  const team = selectedTeam(); const [start, length] = range(); const sum = (group, key) => group.monthly_actuals[key].slice(start, start + length).reduce((total, value) => total + value, 0); const priorSum = (group, key) => group.prior_monthly_actuals[key].slice(start, start + length).reduce((total, value) => total + value, 0); const cash = team.groups.reduce((total, group) => total + sum(group, 'cash'), 0); const orders = team.groups.reduce((total, group) => total + sum(group, 'orders'), 0); const priorCash = team.groups.reduce((total, group) => total + priorSum(group, 'cash'), 0); const priorOrders = team.groups.reduce((total, group) => total + priorSum(group, 'orders'), 0); const cashTarget = totalTarget(team, 'cash'); const ordersTarget = totalTarget(team, 'orders'); const yoy = (current, prior) => prior > 0 ? (current - prior) / prior : null; const completion = (current, targetValue) => targetValue > 0 ? current / targetValue : null; const isTotal = team.team_id === 'market_total';
  const metricCard = (label, current, prior, targetValue, formatter, accent) => '<article class="metric-card" style="border-top-color:' + accent + '"><div class="metric-head"><small>' + label + '</small><span class="metric-scope">' + selectedPeriodLabel() + '</span></div><strong>' + formatter(current) + '</strong><div class="metric-details"><span class="metric-detail"><em>同期</em>' + formatter(prior) + '</span><span class="metric-detail"><em>同比</em>' + pct(yoy(current, prior)) + '</span><span class="metric-detail"><em>目标</em>' + formatter(targetValue) + '</span><span class="metric-detail"><em>完成</em>' + pct(completion(current, targetValue)) + '</span></div></article>';
  const groupHead = isTotal
    ? '<tr><th>业务组</th><th>现金目标</th><th>现金实际</th><th>现金同期</th><th>现金同比</th><th>现金占比</th><th>工单目标</th><th>工单实际</th><th>工单同期</th><th>工单同比</th><th>工单占比</th><th>下钻</th></tr>'
    : '<tr><th>业务组</th><th>现金目标</th><th>现金实际</th><th>现金完成</th><th>工单目标</th><th>工单实际</th><th>工单完成</th></tr>';
  let html = '<section class="cards">' + metricCard('被动报入现金', cash, priorCash, cashTarget, money, 'var(--blue)') + metricCard('被动工单', orders, priorOrders, ordersTarget, count, 'var(--orange)') + '</section><div class="dashboard-grid"><section class="panel"><div class="panel-head"><div><h2>' + (isTotal ? '市场总计 · 现金与工单' : '三大业务组 · 现金与工单') + '</h2><p class="section-kicker">' + (isTotal ? '目标、实际、完成率；展开业务组查看线下、线上平台和虚拟人占比' : '目标、实际与完成率') + '</p></div></div><div class="table-wrap"><table><thead>' + groupHead + '</thead><tbody>';
  html += renderGroupRows(team, sum, priorSum);
  html += '</tbody></table></div></section>';
  if (!isTotal) html += '<section class="panel people-panel"><div class="panel-head"><div><h2>人员月度贡献</h2><p class="section-kicker">按业务团队、绩效月查看目标、完成与渠道</p></div></div><div class="people-toolbar"><div class="people-filters"><label for="peopleGroup">业务团队</label><select id="peopleGroup">%(people_group_options)s</select></div><label for="perfMonth">绩效月</label><select id="perfMonth">' + D.months.map(month => '<option value="' + month + '">' + month + '</option>').join('') + '</select></div><div id="peopleDetail"></div></section>';
  V.innerHTML = html + '</div>';
  if (isTotal) wireDrills(V);
  if (!isTotal) { const monthSelect = document.querySelector('#perfMonth'); const groupSelect = document.querySelector('#peopleGroup'); const currentMonth = TODAY.toISOString().slice(0, 7); monthSelect.value = D.months.includes(currentMonth) ? currentMonth : D.months[D.months.length - 1]; renderPeople(team, monthSelect.value); monthSelect.onchange = event => renderPeople(team, event.target.value); groupSelect.onchange = () => renderPeople(team, monthSelect.value); }
  renderComparison(YOY, 'channel'); renderChannelMatrix(); renderComparison(GRADE, 'grade');
}
function init() { T.innerHTML = D.teams.map(team => '<button data-id="' + escapeHtml(team.team_id) + '">' + escapeHtml(team.display_name) + '</button>').join('') + '<button data-id="' + CAPACITY_ID + '">市场人员产能</button>'; T.querySelectorAll('button').forEach(button => button.onclick = () => { T.querySelectorAll('button').forEach(item => item.classList.remove('active')); button.classList.add('active'); renderView(); renderTimeline(); }); T.querySelector('button').classList.add('active'); S.onchange = () => { updateMonthOptions(true); renderView(); renderTimeline(); }; M.onchange = () => { renderView(); renderTimeline(); }; updateMonthOptions(true); renderView(); renderTimeline(); }
init();
</script>
</body>
</html>'''
    values = {
        '%(snapshot_id)s': snapshot_id,
        '%(data_through_date)s': data_through_date,
        '%(created_at)s': created_at[:19].replace('T', ' '),
        '%(artifact_id)s': artifact_id,
        '%(run_id)s': run_id,
        '%(page_title)s': chrome['page_title'],
        '%(period_line)s': chrome['period_line'],
        '%(special_board_link)s': chrome['special_board_link'],
        '%(grade_kicker)s': chrome['grade_kicker'],
        '%(people_group_options)s': chrome['people_group_options'],
        '%(school_grade_groups_json)s': chrome['school_grade_groups_json'],
        '%(dashboard_json)s': dashboard_json,
    }
    for placeholder, value in values.items():
        template = template.replace(placeholder, value)
    return template
