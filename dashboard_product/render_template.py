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
.comparison .metric { color: var(--muted); font-weight: 700; }
.drill-toggle { padding: 5px 9px; border: 1px solid #b9ccef; border-radius: 5px; background: var(--blue-soft); color: var(--blue); cursor: pointer; font-size: 11px; font-weight: 700; }
.drill-toggle:hover { background: #dce8ff; }
.drill-row td { padding: 0 12px 14px 28px; background: #fafbfd; }
.drill-table { margin-top: 10px; font-size: 12px; }
.drill-table th, .drill-table td { padding: 8px; }
.drill-table thead th { color: var(--muted); }
.drill-table .negative { color: #c34b3d; font-weight: 800; }
.empty-drill { padding: 12px 0 3px; color: var(--muted); }
footer { margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; }
@media (max-width: 980px) { main { padding: 22px 18px 28px; } .dashboard-grid { grid-template-columns: 1fr; } }
@media (max-width: 650px) { header { display: block; } .meta { min-width: 0; margin-top: 12px; text-align: left; } h1 { font-size: 32px; } .timeline, .cards { grid-template-columns: 1fr; } .timeline-label { align-items: flex-start; flex-direction: column; gap: 3px; } .panel { padding: 16px; } }
</style>
</head>
<body>
<main>
<header>
  <div><small>DATA OXHOR / OPERATIONS</small><h1>Cyber Shackles</h1><p>%(period_line)s</p></div>
  <div class="meta">Snapshot<br><b>%(snapshot_id)s</b><br>数据截至 %(data_through_date)s · 刷新 %(created_at)s</div>
</header>
<section class="controls"><label>范围<select id="scope"><option value="year">全年 FY27</option><option value="Q1">Q1</option><option value="Q2" selected>Q2</option><option value="Q3">Q3</option><option value="Q4">Q4</option></select></label><span class="hint">范围切换只影响本地汇总与下钻窗口</span></section>
<div id="timeline" class="timeline"></div>
<nav id="tabs" class="tabs"></nav>
<div id="view"></div>
<section class="panel comparison"><div class="panel-head"><div><h2>业务组同期对比</h2><p class="section-kicker">现金与工单按团队口径分别下钻到一级、二级渠道</p></div></div><div id="yoy-comparison" class="table-wrap"></div></section>
<section class="panel comparison"><div class="panel-head"><div><h2>业务组同期对比 · 年级</h2><p class="section-kicker">%(grade_kicker)s</p></div></div><div id="grade-comparison" class="table-wrap"></div></section>
<footer>Artifact %(artifact_id)s · Run %(run_id)s</footer>
</main>
<script>
const D = %(dashboard_json)s;
const SCHOOL_DRILL_GROUPS = %(school_grade_groups_json)s;
const TODAY = new Date(D.period.current_date);
const S = document.querySelector('#scope');
const T = document.querySelector('#tabs');
const V = document.querySelector('#view');
const YOY = document.querySelector('#yoy-comparison');
const GRADE = document.querySelector('#grade-comparison');
const EMPTY_DRILLS = { current: { cash: { channel: {}, school_grade: {} }, orders: { channel: {}, school_grade: {} } }, prior: { cash: { channel: {}, school_grade: {} }, orders: { channel: {}, school_grade: {} } } };
const DRILLS = D.drilldowns;
function escapeHtml(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character])); }
function money(value) { return value == null ? '未配置' : Math.round(value).toLocaleString() + ' 元'; }
function count(value) { return value == null ? '未配置' : Math.round(value).toLocaleString(); }
function pct(value) { return value == null ? 'N/A' : (value * 100).toFixed(1) + '%'; }
function target(group, key) { if (S.value === 'year') return group.annual_targets[key]; return (group.quarter_targets[S.value] || {})[key] ?? null; }
function totalTarget(team, key) { const values = team.groups.map(group => target(group, key)); return values.some(value => value != null) ? values.reduce((total, value) => total + (value || 0), 0) : null; }
function range() { if (S.value === 'year') return [0, 12]; return ({ Q1: [0, 3], Q2: [3, 3], Q3: [6, 3], Q4: [9, 3] })[S.value] || [0, 12]; }
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
function wireDrills(container) { container.querySelectorAll('.drill-toggle').forEach(button => { button.onclick = () => { const row = document.querySelector('#' + button.dataset.drill); row.hidden = !row.hidden; button.textContent = row.hidden ? '展开下钻' : '收起下钻'; }; }); }
function yoyGroups(team) {
  if (team.yoy_groups && team.yoy_groups.length) return team.yoy_groups;
  return ['青少', '初中', '高中', '大学'].map(name => ({ display_name: name, monthly_actuals: { cash: Array(12).fill(0), orders: Array(12).fill(0) }, prior_monthly_actuals: { cash: Array(12).fill(0), orders: Array(12).fill(0) } }));
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
  const fyStart = new Date('2026-06-01'); const fyEnd = new Date('2027-06-01'); const fyProgress = Math.max(0, Math.min(100, (TODAY - fyStart) / (fyEnd - fyStart) * 100)); const quarterRanges = { Q1: ['2026-06-01', '2026-09-01'], Q2: ['2026-09-01', '2026-12-01'], Q3: ['2026-12-01', '2027-03-01'], Q4: ['2027-03-01', '2027-06-01'] }; const quarter = quarterRanges[S.value]; const quarterProgress = S.value === 'year' ? fyProgress : Math.max(0, Math.min(100, (TODAY - new Date(quarter[0])) / (new Date(quarter[1]) - new Date(quarter[0])) * 100));
  document.querySelector('#timeline').innerHTML = '<div class="timeline-card"><div class="timeline-label"><span>FY27 年度时间进度</span><strong>' + fyProgress.toFixed(1) + '%</strong></div><div class="progress-track"><div class="progress-fill" style="width:' + fyProgress + '%"></div></div></div><div class="timeline-card"><div class="timeline-label"><span>' + (S.value === 'year' ? '全年' : S.value) + ' 时间进度</span><strong>' + quarterProgress.toFixed(1) + '%</strong></div><div class="progress-track"><div class="progress-fill" style="width:' + quarterProgress + '%"></div></div></div>';
}
function renderView() {
  const team = selectedTeam(); const [start, length] = range(); const sum = (group, key) => group.monthly_actuals[key].slice(start, start + length).reduce((total, value) => total + value, 0); const priorSum = (group, key) => group.prior_monthly_actuals[key].slice(start, start + length).reduce((total, value) => total + value, 0); const cash = team.groups.reduce((total, group) => total + sum(group, 'cash'), 0); const orders = team.groups.reduce((total, group) => total + sum(group, 'orders'), 0); const priorCash = team.groups.reduce((total, group) => total + priorSum(group, 'cash'), 0); const priorOrders = team.groups.reduce((total, group) => total + priorSum(group, 'orders'), 0); const cashTarget = totalTarget(team, 'cash'); const ordersTarget = totalTarget(team, 'orders'); const yoy = (current, prior) => prior > 0 ? (current - prior) / prior : null; const completion = (current, targetValue) => targetValue > 0 ? current / targetValue : null; const isTotal = team.team_id === 'market_total';
  const metricCard = (label, current, prior, targetValue, formatter, accent) => '<article class="metric-card" style="border-top-color:' + accent + '"><div class="metric-head"><small>' + label + '</small><span class="metric-scope">' + (S.value === 'year' ? '全年' : S.value) + '</span></div><strong>' + formatter(current) + '</strong><div class="metric-details"><span class="metric-detail"><em>同期</em>' + formatter(prior) + '</span><span class="metric-detail"><em>同比</em>' + pct(yoy(current, prior)) + '</span><span class="metric-detail"><em>目标</em>' + formatter(targetValue) + '</span><span class="metric-detail"><em>完成</em>' + pct(completion(current, targetValue)) + '</span></div></article>';
  let html = '<section class="cards">' + metricCard('被动报入现金', cash, priorCash, cashTarget, money, 'var(--blue)') + metricCard('被动工单', orders, priorOrders, ordersTarget, count, 'var(--orange)') + '</section><div class="dashboard-grid"><section class="panel"><div class="panel-head"><div><h2>' + (isTotal ? '市场总计 · 现金与工单' : '三大业务组 · 现金与工单') + '</h2><p class="section-kicker">目标、实际与完成率</p></div></div><div class="table-wrap"><table><thead><tr><th>业务组</th><th>现金目标</th><th>现金实际</th><th>现金完成</th><th>工单目标</th><th>工单实际</th><th>工单完成</th></tr></thead><tbody>';
  html += team.groups.map(group => '<tr><th>' + escapeHtml(group.display_name) + '</th><td>' + money(target(group, 'cash')) + '</td><td>' + money(sum(group, 'cash')) + '</td><td>' + progressBar(target(group, 'cash') ? sum(group, 'cash') / target(group, 'cash') : null) + '</td><td>' + count(target(group, 'orders')) + '</td><td>' + count(sum(group, 'orders')) + '</td><td>' + progressBar(target(group, 'orders') ? sum(group, 'orders') / target(group, 'orders') : null) + '</td></tr>').join('');
  html += '</tbody></table></div></section>';
  if (!isTotal) html += '<section class="panel people-panel"><div class="panel-head"><div><h2>人员月度贡献</h2><p class="section-kicker">按业务团队、绩效月查看目标、完成与渠道</p></div></div><div class="people-toolbar"><div class="people-filters"><label for="peopleGroup">业务团队</label><select id="peopleGroup">%(people_group_options)s</select></div><label for="perfMonth">绩效月</label><select id="perfMonth">' + D.months.map(month => '<option value="' + month + '">' + month + '</option>').join('') + '</select></div><div id="peopleDetail"></div></section>';
  V.innerHTML = html + '</div>';
  if (!isTotal) { const monthSelect = document.querySelector('#perfMonth'); const groupSelect = document.querySelector('#peopleGroup'); const currentMonth = TODAY.toISOString().slice(0, 7); monthSelect.value = D.months.includes(currentMonth) ? currentMonth : D.months[D.months.length - 1]; renderPeople(team, monthSelect.value); monthSelect.onchange = event => renderPeople(team, event.target.value); groupSelect.onchange = () => renderPeople(team, monthSelect.value); }
  renderComparison(YOY, 'channel'); renderComparison(GRADE, 'grade');
}
function init() { T.innerHTML = D.teams.map(team => '<button data-id="' + escapeHtml(team.team_id) + '">' + escapeHtml(team.display_name) + '</button>').join(''); T.querySelectorAll('button').forEach(button => button.onclick = () => { T.querySelectorAll('button').forEach(item => item.classList.remove('active')); button.classList.add('active'); renderView(); renderTimeline(); }); T.querySelector('button').classList.add('active'); S.onchange = () => { renderView(); renderTimeline(); }; renderView(); renderTimeline(); }
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
        '%(grade_kicker)s': chrome['grade_kicker'],
        '%(people_group_options)s': chrome['people_group_options'],
        '%(school_grade_groups_json)s': chrome['school_grade_groups_json'],
        '%(dashboard_json)s': dashboard_json,
    }
    for placeholder, value in values.items():
        template = template.replace(placeholder, value)
    return template
