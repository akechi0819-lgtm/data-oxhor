#!/usr/bin/env python3
"""Dashboard HTML 渲染模板"""

def render_html(artifact_data):
    """从 artifact 数据生成完整的看板 HTML"""

    dashboard = artifact_data['dashboard']
    snapshot_id = artifact_data['snapshot_id']
    run_id = artifact_data['run_id']
    artifact_id = artifact_data['artifact_id']
    created_at = artifact_data['created_at']
    as_of_date = artifact_data['as_of_date']
    data_through_date = artifact_data['data_through_date']

    # 注入到 dashboard 数据
    dashboard['period'] = {
        'project_label': 'FY27（2026-06-01 至 2027-05-31）',
        'performance_label': '每月 26 日至次月 25 日',
        'current_date': as_of_date,
        'fiscal_year_start': '2026-06-01'
    }

    import json
    dashboard_json = json.dumps(dashboard, ensure_ascii=False)

    html = f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cyber Shackles - 语培完成进度看板</title>
<style>
body {{
  margin: 0;
  background: #f4f6f8;
  color: #17212b;
  font: 14px "Noto Sans SC", "PingFang SC", sans-serif;
}}
main {{
  max-width: 1500px;
  margin: auto;
  padding: 30px;
}}
header {{
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid #d9e0e7;
  padding-bottom: 22px;
}}
h1 {{
  font: 600 38px Georgia, serif;
  margin: 8px 0;
}}
p, small, header .meta, .controls span, .muted {{
  color: #6f7c88;
}}
.meta {{
  text-align: right;
  line-height: 1.8;
}}
.meta b {{
  color: #17212b;
}}
.controls {{
  display: flex;
  gap: 18px;
  align-items: end;
  flex-wrap: wrap;
  padding: 18px 0;
}}
.controls label {{
  display: grid;
  gap: 6px;
  color: #96a49a;
}}
select, button {{
  background: #ffffff;
  color: #17212b;
  border: 1px solid #cbd5df;
  padding: 9px 12px;
  border-radius: 3px;
}}
button {{
  cursor: pointer;
}}
.active {{
  background: #1f6feb !important;
  color: #ffffff !important;
}}
.timeline {{
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}}
.timeline div {{
  background: #ffffff;
  border: 1px solid #d9e0e7;
  padding: 14px 16px;
}}
.timeline-label {{
  display: flex;
  justify-content: space-between;
  margin-bottom: 9px;
  color: #3b4854;
  font-weight: 600;
}}
.timeline-label strong {{ color: #1f6feb; font-size: 16px; }}
.progress-track {{
  height: 10px;
  overflow: hidden;
  background: #e5ebf1;
  border-radius: 99px;
}}
.progress-fill {{
  height: 100%;
  width: var(--w);
  background: #1f6feb;
  border-radius: inherit;
}}
.cards {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}}
.cards article {{
  background: #ffffff;
  color: #17212b;
  border: 1px solid #d9e0e7;
  padding: 18px;
  border-top: 4px solid #1f6feb;
}}
.cards article:nth-child(2) {{
  border-color: #f08c46;
}}
.cards strong {{
  display: block;
  font: 600 30px Georgia;
  margin: 12px 0 5px;
}}
.grid {{
  display: grid;
  grid-template-columns: 1.3fr 0.9fr;
  gap: 14px;
  margin-top: 14px;
}}
.panel {{
  background: #ffffff;
  border: 1px solid #d9e0e7;
  padding: 20px;
  overflow: auto;
}}
h2 {{
  font: 600 22px Georgia;
  margin: 0 0 16px;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  white-space: nowrap;
}}
th, td {{
  text-align: left;
  padding: 11px 8px;
  border-bottom: 1px solid #e6ebf0;
}}
th {{
  color: #6f7c88;
}}
tbody th {{
  color: #17212b;
}}
.bar {{
  display: inline-block;
  width: 70px;
  height: 6px;
  background: #e5ebf1;
  margin-right: 7px;
  vertical-align: middle;
}}
.bar i {{
  display: block;
  height: 100%;
  background: #1f6feb;
}}
.period-progress {{
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding: 12px;
  color: #3b4854;
  background: #f7f9fb;
  border: 1px solid #e1e7ed;
}}
.period-progress .bar {{
  flex: 1;
  width: auto;
  margin: 0;
  height: 9px;
}}
.period-progress strong {{ color: #1f6feb; min-width: 48px; text-align: right; }}
.drill-toggle {{
  padding: 3px 7px;
  color: #1f6feb;
  border-color: #b9d1f5;
  font-size: 12px;
}}
.drill-row td {{
  padding: 0 10px 14px 28px;
  background: #f7f9fb;
}}
.drill-table {{ margin-top: 10px; font-size: 12px; }}
.drill-table th, .drill-table td {{ padding: 7px 8px; }}
.drill-table th {{ color: #3b4854; }}
.empty-drill {{ color: #6f7c88; padding: 10px 0; }}
.tabs {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 14px; }}
.tabs button {{ border-radius: 5px; }}
@media (max-width: 620px) {{
  .timeline-label {{ align-items: flex-start; gap: 8px; flex-direction: column; }}
  .period-progress {{ align-items: stretch; flex-direction: column; }}
  .period-progress strong {{ text-align: left; }}
}}
footer {{
  border-top: 1px solid #35443c;
  margin-top: 20px;
  padding-top: 14px;
  color: #819087;
  font-size: 11px;
}}
@media (max-width: 900px) {{
  main {{
    padding: 18px;
  }}
  .grid, .cards, .timeline {{
    grid-template-columns: 1fr;
  }}
  header {{
    display: block;
  }}
  .meta {{
    text-align: left;
    margin-top: 10px;
  }}
}}
</style>
</head>
<body>
<main>
<header>
  <div>
    <small>DATA OXHOR / OPERATIONS</small>
    <h1>Cyber Shackles</h1>
    <p>FY27 财年：2026-06-01 至 2027-05-31</p>
  </div>
  <div class="meta">
    Snapshot<br>
    <b>{snapshot_id}</b><br>
    数据截至 {data_through_date} · 刷新 {created_at[:19].replace('T', ' ')}
  </div>
</header>

<section class="controls">
  <label>
    范围
    <select id="scope">
      <option value="year">全年 FY27</option>
      <option value="Q1">Q1</option>
      <option value="Q2" selected>Q2</option>
      <option value="Q3">Q3</option>
      <option value="Q4">Q4</option>
    </select>
  </label>
  <span>筛选仅本地计算，不重复查询数仓</span>
</section>

<div id="timeline"></div>
<nav id="tabs"></nav>
<div id="view"></div>

<section class="panel" style="margin-top: 14px;">
  <h2>业务组同期对比</h2>
  <p>当前年度与上一财年同期对比（按业务组）</p>
  <div id="yoy-comparison"></div>
</section>

<footer>
  Artifact {artifact_id} · Run {run_id}
</footer>
</main>

<script>
const D = {dashboard_json};

// 解析日期信息
const TODAY = new Date(D.period.current_date);
const FY_START = new Date(D.period.fiscal_year_start);

const S = document.querySelector('#scope');
const T = document.querySelector('#tabs');
const V = document.querySelector('#view');
const YOY = document.querySelector('#yoy-comparison');

function money(v) {{
  return v == null ? '未配置' : Math.round(v).toLocaleString() + ' 元';
}}

function count(v) {{
  return v == null ? '未配置' : Math.round(v).toLocaleString();
}}

function pct(v) {{
  return v == null ? '未配置' : (v * 100).toFixed(1) + '%';
}}

function target(g, k) {{
  if (S.value === 'year') return g.annual_targets[k];
  if (S.value[0] === 'Q') return (g.quarter_targets[S.value] || {{}})[k] ?? null;
  return null;
}}

function range() {{
  // MONTHS = ['2026-06', '2026-07', '2026-08', '2026-09', '2026-10', '2026-11', '2026-12', '2027-01', '2027-02', '2027-03', '2027-04', '2027-05']
  // 索引: Q1=0-2, Q2=3-5, Q3=6-8, Q4=9-11

  if (S.value === 'year') {{
    return [0, 12]; // 全年
  }}

  if (S.value === 'Q1') {{
    // Q1: 2026-06 到 2026-08 (索引 0-2)
    return [0, 3];
  }}

  if (S.value === 'Q2') {{
    // Q2: 2026-09 到 2026-11 (索引 3-5)
    return [3, 3];
  }}

  if (S.value === 'Q3') {{
    // Q3: 2026-12 到 2027-02 (索引 6-8)
    return [6, 3];
  }}

  if (S.value === 'Q4') {{
    // Q4: 2027-03 到 2027-05 (索引 9-11)
    return [9, 3];
  }}

  return [0, 12];
}}

function bar(v) {{
  if (v == null) return '未配置';
  return '<span class="bar"><i style="width:' +
    Math.min(100, Math.max(0, v * 100)) + '%"></i></span>' + pct(v);
}}

function renderYoY() {{
  const team = D.teams.find(t => t.team_id === T.querySelector('.active')?.dataset.id) || D.teams[0];
  const [st, len] = range();

  // 计算当前年度各业务组数据
  const currentData = {{}};
  team.groups.forEach(g => {{
    const cash = g.monthly_actuals.cash.slice(st, st + len).reduce((a, b) => a + b, 0);
    const orders = g.monthly_actuals.orders.slice(st, st + len).reduce((a, b) => a + b, 0);
    currentData[g.display_name] = {{ cash, orders }};
  }});

  // 上一财年使用与当前财年相同的自然月段，确保季度同比窗口一致。
  const priorData = {{}};
  team.groups.forEach(g => {{
    const cash = g.prior_monthly_actuals.cash.slice(st, st + len).reduce((a, b) => a + b, 0);
    const orders = g.prior_monthly_actuals.orders.slice(st, st + len).reduce((a, b) => a + b, 0);
    priorData[g.display_name] = {{ cash, orders }};
  }});

  let html = '<table><thead><tr><th>业务组</th><th>指标</th><th>去年同期</th><th>今年实际</th><th>同比增长</th><th>下钻</th></tr></thead><tbody>';

  team.groups.forEach((g, groupIndex) => {{
    const cur = currentData[g.display_name] || {{ cash: 0, orders: 0 }};
    const prior = priorData[g.display_name] || {{ cash: 0, orders: 0 }};

    // 现金对比
    const cashYoY = prior.cash > 0 ? (cur.cash - prior.cash) / prior.cash : null;
    const cashYoYStyle = cashYoY !== null && cashYoY < 0 ? ' style="color: #ff6b6b;"' : '';

    const drillId = 'drill-' + groupIndex;
    html += '<tr>';
    html += '<th rowspan="2">' + g.display_name + '</th>';
    html += '<td>现金</td>';
    html += '<td>' + money(prior.cash) + '</td>';
    html += '<td>' + money(cur.cash) + '</td>';
    html += '<td' + cashYoYStyle + '>' + (cashYoY !== null ? pct(cashYoY) : 'N/A') + '</td>';
    html += '<td rowspan="2"><span class="muted">工单下钻</span></td>';
    html += '</tr>';

    // 工单对比
    const ordersYoY = prior.orders > 0 ? (cur.orders - prior.orders) / prior.orders : null;
    const ordersYoYStyle = ordersYoY !== null && ordersYoY < 0 ? ' style="color: #ff6b6b;"' : '';

    html += '<tr>';
    html += '<td>工单</td>';
    html += '<td>' + count(prior.orders) + '</td>';
    html += '<td>' + count(cur.orders) + '</td>';
    html += '<td' + ordersYoYStyle + '>' + (ordersYoY !== null ? pct(ordersYoY) : 'N/A') + ' <button class="drill-toggle" data-drill="' + drillId + '">展开渠道</button></td>';
    html += '</tr>';
    html += '<tr id="' + drillId + '" class="drill-row" hidden><td colspan="6">' + channelDrill(g.display_name, team.team_id, st, len) + '</td></tr>';
  }});

  html += '</tbody></table>';
  YOY.innerHTML = html;
  YOY.querySelectorAll('.drill-toggle').forEach(button => {{
    button.onclick = () => {{
      const row = document.querySelector('#' + button.dataset.drill);
      row.hidden = !row.hidden;
      button.textContent = row.hidden ? '展开渠道' : '收起渠道';
    }};
  }});
}}

function channelDrill(groupName, teamId, start, length) {{
  const totals = {{current: {{}}, prior: {{}}}};
  const add = (source, months, target) => Object.entries(source || {{}}).forEach(([key, value]) => {{
    const parts = key.split('|');
    if (parts.length < 4 || parts[1] !== teamId || parts[2] !== groupName) return;
    const monthIndex = months.indexOf(parts[0]);
    if (monthIndex < start || monthIndex >= start + length) return;
    const channelKey = (parts[3] || '未归类') + '||' + (parts[4] || '未细分');
    target[channelKey] = (target[channelKey] || 0) + value;
  }});
  add(D.channels, D.months, totals.current);
  add(D.prior_channels, D.prior_months, totals.prior);
  const keys = [...new Set([...Object.keys(totals.current), ...Object.keys(totals.prior)])];
  if (!keys.length) return '<div class="empty-drill">当前范围暂无渠道明细</div>';
  const firstNames = [...new Set(keys.map(key => key.split('||')[0]))];
  let html = '<table class="drill-table"><thead><tr><th>一级渠道</th><th>二级渠道</th><th>当期</th><th>同期</th><th>同比</th></tr></thead><tbody>';
  firstNames.forEach(first => {{
    const firstKeys = keys.filter(key => key.startsWith(first + '||')).sort((a, b) => (totals.current[b] || 0) - (totals.current[a] || 0));
    firstKeys.forEach((key, index) => {{
      const second = key.split('||')[1];
      const current = totals.current[key] || 0;
      const prior = totals.prior[key] || 0;
      const yoy = prior > 0 ? (current - prior) / prior : null;
      html += '<tr><th>' + (index === 0 ? first : '') + '</th><td>' + second + '</td><td>' + count(current) + '</td><td>' + count(prior) + '</td><td>' + (yoy === null ? 'N/A' : pct(yoy)) + '</td></tr>';
    }});
  }});
  return html + '</tbody></table>';
}}

function render() {{
  const [st, len] = range();
  const team = D.teams.find(t => t.team_id === T.querySelector('.active')?.dataset.id) || D.teams[0];

  const sum = (g, k) => g.monthly_actuals[k].slice(st, st + len).reduce((a, b) => a + b, 0);

  const tot = ['cash', 'orders'].map(k => [
    k,
    team.groups.reduce((s, g) => s + sum(g, k), 0),
    team.groups.reduce((s, g) => s + (target(g, k) || 0), 0)
  ]);

  const today = TODAY;
  const fy0 = new Date('2026-06-01');
  const fy1 = new Date('2027-06-01');
  const fy = Math.max(0, Math.min(100, (today - fy0) / (fy1 - fy0) * 100));

  let periodProgress = 0;
  if (S.value === 'year') {{
    periodProgress = fy;
  }} else if (S.value === 'Q1') {{
    const q1Start = new Date('2026-06-01');
    const q1End = new Date('2026-09-01');
    periodProgress = Math.max(0, Math.min(100, (today - q1Start) / (q1End - q1Start) * 100));
  }} else if (S.value === 'Q2') {{
    const q2Start = new Date('2026-09-01');
    const q2End = new Date('2026-12-01');
    periodProgress = Math.max(0, Math.min(100, (today - q2Start) / (q2End - q2Start) * 100));
  }} else if (S.value === 'Q3') {{
    const q3Start = new Date('2026-12-01');
    const q3End = new Date('2027-03-01');
    periodProgress = Math.max(0, Math.min(100, (today - q3Start) / (q3End - q3Start) * 100));
  }} else if (S.value === 'Q4') {{
    const q4Start = new Date('2027-03-01');
    const q4End = new Date('2027-06-01');
    periodProgress = Math.max(0, Math.min(100, (today - q4Start) / (q4End - q4Start) * 100));
  }}

  T.querySelectorAll('button').forEach(b =>
    b.classList.toggle('active', b.dataset.id === team.team_id)
  );

  document.querySelector('#timeline').innerHTML =
    '<div><div class="timeline-label"><span>FY27 年度时间进度</span><strong>' + fy.toFixed(1) + '%</strong></div><div class="progress-track"><div class="progress-fill" style="--w:' + fy + '%"></div></div></div>' +
    '<div><div class="timeline-label"><span>' + S.value + ' 季度时间进度</span><strong>' + periodProgress.toFixed(1) + '%</strong></div><div class="progress-track"><div class="progress-fill" style="--w:' + periodProgress + '%"></div></div></div>';

  V.innerHTML =
    '<section class="cards">' +
      '<article><small>被动报入现金</small><strong>' + money(tot[0][1]) + '</strong></article>' +
      '<article><small>被动工单</small><strong>' + count(tot[1][1]) + '</strong></article>' +
    '</section>' +
    '<div class="grid">' +
      '<section class="panel"><h2>三大业务组 · 现金与工单</h2><table><thead><tr>' +
      '<th>业务组</th><th>现金目标</th><th>现金实际</th><th>现金完成</th><th>工单目标</th><th>工单实际</th><th>工单完成</th>' +
      '</tr></thead><tbody>' +
      team.groups.map(g =>
        '<tr><th>' + g.display_name + '</th>' +
        '<td>' + money(target(g, 'cash')) + '</td>' +
        '<td>' + money(sum(g, 'cash')) + '</td>' +
        '<td>' + bar(target(g, 'cash') ? sum(g, 'cash') / target(g, 'cash') : null) + '</td>' +
        '<td>' + count(target(g, 'orders')) + '</td>' +
        '<td>' + count(sum(g, 'orders')) + '</td>' +
        '<td>' + bar(target(g, 'orders') ? sum(g, 'orders') / target(g, 'orders') : null) + '</td>' +
        '</tr>'
      ).join('') +
      '</tbody></table></section>' +
      '<section class="panel">' +
        '<h2>人员月度贡献</h2>' +
        '<p class="muted">进度条表示团队内相对贡献，不代表个人目标完成率。</p>' +
        '<div style="margin-bottom: 12px;"><label style="display: inline-flex; gap: 8px; align-items: center;">绩效月筛选：<select id="perfMonth">' +
          D.months.map(m => '<option value="' + m + '">' + m + '</option>').join('') +
        '</select></label></div>' +
        '<div id="peopleDetail"></div>' +
      '</section>' +
    '</div>';

  // 初始化人员明细
  renderPeopleDetail(team, D.months[D.months.length - 1]);

  // 绑定绩效月筛选器
  document.querySelector('#perfMonth').onchange = (e) => {{
    renderPeopleDetail(team, e.target.value);
  }};

  renderYoY();
}}

function renderPeopleDetail(team, month) {{
  const monthIdx = D.months.indexOf(month);
  if (monthIdx < 0) return;

  const today = TODAY;
  const monthStart = new Date(month + '-01');
  const monthEnd = new Date(monthStart);
  monthEnd.setMonth(monthEnd.getMonth() + 1);
  const monthProgress = Math.max(0, Math.min(100, (today - monthStart) / (monthEnd - monthStart) * 100));

  // 在表格上方显示时间进度
  let html = '<div class="period-progress"><span>绩效月时间进度</span>';
  html += '<span class="bar"><i style="width:' + monthProgress.toFixed(1) + '%"></i></span>';
  html += '<strong>' + monthProgress.toFixed(1) + '%</strong></div>';

  html += '<table><thead><tr>' +
    '<th>人员</th><th>所属组</th><th>状态</th><th>现金完成</th><th>工单完成</th><th>综合进度</th>' +
    '</tr></thead><tbody>';

  // 获取该月每个人的数据
  const peopleData = team.people.map(person => {{
    const cashActual = person.monthly_actuals?.cash?.[monthIdx] || 0;
    const ordersActual = person.monthly_actuals?.orders?.[monthIdx] || 0;
    return {{ ...person, cashActual, ordersActual }};
  }});

  // 计算团队在该月的最大值（用于展示相对贡献）
  const maxCash = Math.max(...peopleData.map(p => p.cashActual), 1);
  const maxOrders = Math.max(...peopleData.map(p => p.ordersActual), 1);

  peopleData.forEach(person => {{
    const cashActual = person.cashActual;
    const ordersActual = person.ordersActual;

    // 计算相对贡献百分比，不与时间进度比较
    const cashPct = maxCash > 0 ? (cashActual / maxCash * 100) : 0;
    const ordersPct = maxOrders > 0 ? (ordersActual / maxOrders * 100) : 0;

    // 综合贡献 = (现金权重50% + 工单权重50%)
    const combinedPct = (cashPct * 0.5 + ordersPct * 0.5);

    const behindClass = '';

    // 现金进度条
    const cashBar = '<span class="bar"><i style="width:' + cashPct.toFixed(1) + '%"></i></span>' + money(cashActual);

    // 工单进度条
    const ordersBar = '<span class="bar"><i style="width:' + ordersPct.toFixed(1) + '%"></i></span>' + count(ordersActual);

    // 综合进度条
    const combinedBar = '<span class="bar"><i style="width:' + combinedPct.toFixed(1) + '%"></i></span>' + combinedPct.toFixed(1) + '%';

    html += '<tr' + behindClass + '><th>' + person.display_name + '</th>' +
      '<td>' + person.group_name + '</td>' +
      '<td>' + person.status + '</td>' +
      '<td>' + cashBar + '</td>' +
      '<td>' + ordersBar + '</td>' +
      '<td>' + combinedBar + '</td>' +
      '</tr>';
  }});

  html += '</tbody></table>';
  document.querySelector('#peopleDetail').innerHTML = html;
}}

function init() {{
  T.innerHTML = D.teams.map(t =>
    '<button data-id="' + t.team_id + '">' + t.display_name + '</button>'
  ).join('');

  T.querySelectorAll('button').forEach(b => {{
    b.onclick = () => {{
      T.querySelectorAll('button').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      render();
    }};
  }});

  T.querySelector('button').classList.add('active');
  S.onchange = render;
  render();
}}

init();
</script>
</body>
</html>'''

    return html
