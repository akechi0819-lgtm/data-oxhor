"use strict";

(() => {
  const UNIT_LABELS = {
    total: "全部管理单元",
    prep: "留学预备",
    high: "高中",
    university: "大学",
    virtual: "线上虚拟人",
    online: "线上平台",
  };
  const LINES = {
    training: { label: "语培", className: "training" },
    market: { label: "语培市场总盘", className: "training" },
    mixed: { label: "虚拟人", className: "training" },
    abroad: { label: "留学", className: "abroad" },
  };
  const METRICS = [
    { id: "orders", label: "工单", unit: "单" },
    { id: "cash", label: "现金", unit: "元" },
    { id: "heads", label: "人头", unit: "人" },
  ];
  const ACTIVITY_PAGE_SIZE = 50;
  const byId = (id) => document.getElementById(id);
  const state = {
    data: null,
    periodId: null,
    capacityMonth: null,
    capacityTeam: "all",
    capacityScope: "all",
    orderStatusMode: "01",
    unitId: "total",
    teamScope: "all",
    activeView: "overview",
    activityQuery: "",
    activityPage: 1,
    activityCosts: new Map(),
  };

  const ui = {
    periodSelect: byId("period-select"),
    unitSelect: byId("unit-select"),
    teamScopeControl: byId("team-scope-control"),
    teamScopeSelect: byId("team-scope-select"),
    capacityScope: byId("capacity-scope"),
    periodCaption: byId("period-caption"),
    freshness: byId("freshness"),
    freshnessLabel: byId("freshness-label"),
    freshnessDate: byId("freshness-date"),
    loadMessage: byId("load-message"),
    scopeNote: byId("scope-note"),
    lineCards: byId("line-cards"),
    personPeriod: byId("person-period"),
    peopleCount: byId("people-count"),
    peopleBody: byId("people-body"),
    countryCount: byId("country-count"),
    countryGroups: byId("country-groups"),
    personalMonth: byId("personal-month"),
    activitySearch: byId("activity-search"),
    activityCount: byId("activity-count"),
    activityScope: byId("activity-scope"),
    activityBody: byId("activity-body"),
    activityPageInfo: byId("activity-page-info"),
    activityPrevious: byId("activity-prev"),
    activityNext: byId("activity-next"),
    footerRun: byId("footer-run"),
    tabs: Array.from(document.querySelectorAll('[role="tab"][data-view]')),
    panels: Array.from(document.querySelectorAll('[role="tabpanel"]')),
  };

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }

  function cleanString(value) {
    if (typeof value === "string") return value.trim();
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    return "";
  }

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function safeArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function formatNumber(value) {
    if (isNumber(value)) {
      return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
    }
    if (typeof value === "string" && value.trim()) return escapeHTML(value.trim());
    return "—";
  }

  function formatPercent(value) {
    if (!isNumber(value)) return "—";
    return new Intl.NumberFormat("zh-CN", { style: "percent", maximumFractionDigits: 1 }).format(value);
  }

  function formatDate(value) {
    const match = typeof value === "string" && value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return match ? `${match[1]}-${match[2]}-${match[3]}` : cleanString(value) || "未提供";
  }

  function periodLabel(period) {
    if (!period) return "未选择期间";
    const title = cleanString(period.label) || `${formatDate(period.start_date)} 至 ${formatDate(period.through_date)}`;
    return period.status === "future" ? `${title}（期间尚未开始）` : title;
  }

  function getPeriod() {
    return safeArray(state.data && state.data.periods).find((period, index) => String(period.id ?? index) === state.periodId) || null;
  }

  function getTeam(period = getPeriod()) {
    return safeArray(period && period.teams).find((team) => String(team.id) === state.unitId) || null;
  }

  function getCutoffTeam() {
    const periods = safeArray(state.data && state.data.periods);
    const metadata = state.data && state.data.metadata ? state.data.metadata : {};
    const cutoff = cleanString(metadata.data_through);
    const cutoffMonth = cutoff.slice(0, 7);
    const reference = periods.find((period) => String(period.id) === cutoffMonth)
      || periods.find((period) => cleanString(period.start_date).slice(0, 7) === cutoffMonth || cleanString(period.through_date).slice(0, 7) === cutoffMonth)
      || periods.find((period) => cleanString(period.through_date) === cutoff)
      || getPeriod();
    return getTeam(reference);
  }

  function rawActual(value) {
    return isObject(value) ? (Object.prototype.hasOwnProperty.call(value, "actual") ? value.actual : null) : value;
  }

  function metricStatus(value, fallbackStatus = null, periodStatus = null) {
    const embeddedStatus = isObject(value) ? cleanString(value.status) : "";
    const status = cleanString(fallbackStatus) || embeddedStatus;
    if (periodStatus === "future" || status === "future") return "future";
    if (status) return status;
    return isObject(value) ? "unknown" : (value === null || value === undefined ? "not_connected" : "available");
  }

  function statusLabel(status) {
    if (status === "not_connected") return "数据未接入";
    if (status === "not_configured") return "归属待确认";
    if (status === "future") return "尚未开始";
    if (status === "not_covered") return "该期间未覆盖";
    if (status === "partial") return "部分接入";
    if (status === "available") return "已接入";
    if (status === "separate_counts") return "分业务统计";
    return "状态未确认";
  }

  function metricDisplay(value, unit = "") {
    const status = metricStatus(value);
    if (status === "separate_counts") {
      const display = isObject(value) ? cleanString(value.display) : "";
      if (display) return escapeHTML(display);
      const parts = safeArray(isObject(value) ? value.parts : null).map((part) => {
        const label = cleanString(part && part.label);
        const actual = part && part.actual;
        return actual === null || actual === undefined ? "" : `${label ? `${escapeHTML(label)} ` : ""}${formatNumber(actual)}${part.unit ? ` ${escapeHTML(part.unit)}` : ""}`;
      }).filter(Boolean);
      return parts.length ? parts.join("／") : "—";
    }
    if ((status === "available" || status === "partial") && isObject(value)) {
      const display = cleanString(value.display);
      if (display) return escapeHTML(display);
    }
    const actual = rawActual(value);
    if (actual === null || actual === undefined) return "—";
    const shown = formatNumber(actual);
    return unit ? `${shown} <span class="value-unit">${escapeHTML(unit)}</span>` : shown;
  }

  function metricValueMarkup(value, fallbackStatus = null, periodStatus = null, options = {}) {
    const status = metricStatus(value, fallbackStatus, periodStatus);
    const actual = rawActual(value);
    if (status === "future") return '<span class="value-state is-future">尚未开始</span>';
    if (status === "not_connected") return '<span class="value-state is-missing">数据未接入</span>';
    if (status === "not_configured") return '<span class="value-state is-unconfigured">归属待确认</span>';
    if (status === "not_covered") return '<span class="value-state is-missing">该期间未覆盖</span>';
    if (status === "unknown") return '<span class="value-state is-unknown">状态未确认</span>';
    if (status === "separate_counts") {
      const display = metricDisplay(value, options.unit || "");
      return display === "—" ? '<span class="value-state is-unknown">分业务人头未提供</span>' : `<span class="value-number">${display}</span>`;
    }
    if (status === "partial" && (actual === null || actual === undefined)) {
      return '<span class="value-state is-missing">部分数据未接入</span>';
    }
    if (status !== "available" && status !== "partial") return '<span class="value-state is-unknown">状态未确认</span>';
    if (actual === null || actual === undefined || (typeof actual === "number" && !isNumber(actual))) {
      return '<span class="value-state is-unknown">实际值未提供</span>';
    }
    return `<span class="value-number">${metricDisplay(value, options.unit || "")}</span>`;
  }

  function scalarMarkup(value, emptyLabel = "数据未接入") {
    if (value === null || value === undefined) return `<span class="value-state is-missing">${escapeHTML(emptyLabel)}</span>`;
    if (isObject(value)) {
      const status = metricStatus(value);
      return metricValueMarkup(value, status);
    }
    return `<span class="value-number">${formatNumber(value)}</span>`;
  }

  function metricDetail(metric, property, unit = "") {
    if (!isObject(metric) || metric[property] === null || metric[property] === undefined) return "";
    const value = property === "yoy" || property === "completion" ? formatPercent(metric[property]) : formatNumber(metric[property]);
    const suffix = unit && property !== "yoy" && property !== "completion" ? ` ${escapeHTML(unit)}` : "";
    return `${value}${suffix}`;
  }

  function renderLineMetricRow(lineId, metricId, metric, periodStatus) {
    const descriptor = METRICS.find((entry) => entry.id === metricId);
    const metricLabel = descriptor.label;
    const status = metricStatus(metric, null, periodStatus);
    const departmentDoesNotAssessAbroad = state.unitId === "prep" || state.unitId === "high";
    const notAssessed = lineId === "abroad" && metricId === "orders" && departmentDoesNotAssessAbroad;
    const current = notAssessed
      ? '<span class="value-state is-unassessed">本部门暂不考核</span>'
      : metricValueMarkup(metric, null, periodStatus, { unit: descriptor.unit });
    const comparable = status === "available";
    const progressAvailable = comparable || status === "partial";
    const prior = !notAssessed && comparable && isObject(metric) && metric.prior !== null && metric.prior !== undefined
      ? `${formatNumber(metric.prior)}${descriptor.unit ? ` <span class="value-unit">${escapeHTML(descriptor.unit)}</span>` : ""}`
      : "—";
    const yoy = !notAssessed && comparable && isObject(metric) && isNumber(metric.yoy)
      ? `<span class="yoy-value ${metric.yoy > 0 ? "positive" : metric.yoy < 0 ? "negative" : ""}">${formatPercent(metric.yoy)}</span>`
      : "—";
    const target = !notAssessed && progressAvailable ? metricDetail(metric, "target", descriptor.unit) : "";
    const completion = !notAssessed && progressAvailable ? metricDetail(metric, "completion") : "";
    const detail = notAssessed
      ? "人员留学贡献见财年产能"
      : [target ? `目标 ${target}` : "", completion ? `完成 ${completion}` : ""].filter(Boolean).join(" · ");
    return `<tr>
      <th scope="row"><span class="metric-label">${escapeHTML(metricLabel)}</span></th>
      <td><strong>${current}</strong>${detail ? `<small class="metric-detail">${detail}</small>` : ""}</td>
      <td>${prior}</td>
      <td>${yoy}</td>
    </tr>`;
  }

  function renderLineCard(lineId, team, period) {
    const descriptor = LINES[lineId];
    const line = isObject(team.lines) && isObject(team.lines[lineId]) ? team.lines[lineId] : {};
    const teamName = cleanString(team.name) || UNIT_LABELS[state.unitId] || state.unitId;
    const rows = METRICS.map(({ id }) => renderLineMetricRow(lineId, id, line[id], period.status)).join("");
    const periodBadge = period.status === "future" ? "尚未开始" : "团队 · 自然期间";
    const coverage = lineId === "abroad" && isObject(line.source_coverage) ? line.source_coverage : null;
    const coverageText = coverage && coverage.start_date && coverage.through_date
      ? `留学数据：${formatDate(coverage.start_date)}—${formatDate(coverage.through_date)}` : "";
    const supplemental = lineId === "abroad" && team.id === "total"
      ? renderSupplemental(line.supplemental) : "";
    return `<article class="line-card ${descriptor.className}">
      <div class="line-card-head">
        <div><div class="line-title"><span class="line-symbol" aria-hidden="true"></span><h3>${escapeHTML(descriptor.label)}</h3></div>
          <p class="line-scope">${escapeHTML(teamName)} · ${escapeHTML(periodLabel(period))}</p>${coverageText ? `<p class="line-coverage">${escapeHTML(coverageText)}</p>` : ""}
        </div>
        <span class="line-badge">${escapeHTML(periodBadge)}</span>
      </div>
      <div class="line-card-table-scroll" tabindex="0" aria-label="${escapeHTML(descriptor.label)}当期、同期、同比，可横向滚动">
        <table class="line-metric-table"><thead><tr><th scope="col">指标</th><th scope="col">当期</th><th scope="col">同期</th><th scope="col">同比</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>${supplemental}
    </article>`;
  }

  function metricHasActivity(value) {
    if (value === null || value === undefined) return false;
    const status = metricStatus(value);
    if (status === "not_covered" || status === "not_connected" || status === "future") return false;
    if (status === "separate_counts") {
      const parts = safeArray(value.parts);
      if (parts.length) return parts.some((part) => isNumber(part?.actual) && part.actual !== 0);
      const display = cleanString(value.display);
      const numbers = display.match(/-?\d[\d,]*(?:\.\d+)?/g) || [];
      return numbers.length ? numbers.some((part) => Number(part.replace(/,/g, "")) !== 0) : Boolean(display);
    }
    const actual = rawActual(value);
    if (isNumber(actual)) return actual !== 0;
    if (typeof actual === "string" && actual.trim()) {
      const parsed = Number(actual.replace(/,/g, ""));
      return Number.isFinite(parsed) ? parsed !== 0 : true;
    }
    if (actual !== null && actual !== undefined) return Boolean(actual);
    const display = cleanString(isObject(value) ? value.display : "");
    const numbers = display.match(/-?\d[\d,]*(?:\.\d+)?/g) || [];
    return numbers.length ? numbers.some((part) => Number(part.replace(/,/g, "")) !== 0) : Boolean(display);
  }

  function renderSupplemental(rows) {
    const ssc = safeArray(rows).find((row) => cleanString(row.id).toLowerCase() === "ssc");
    if (!ssc || ![ssc.orders, ssc.cash, ssc.heads].some(metricHasActivity)) return "";
    return `<div class="line-card-table-scroll line-supplemental"><table class="line-metric-table"><tbody><tr><th scope="row">SSC</th><td><small>工单</small><strong>${metricValueMarkup(ssc.orders, null, null, { unit: "单" })}</strong></td><td><small>现金（元）</small><strong>${metricValueMarkup(ssc.cash, null, null, { unit: "元" })}</strong></td><td><small>人头</small><strong>${metricValueMarkup(ssc.heads, null, null, { unit: "人" })}</strong></td></tr></tbody></table></div>`;
  }

  function renderLineCards(team, period) {
    if (!period) {
      ui.lineCards.innerHTML = '<div class="empty-panel">没有可展示的统计期间。</div>';
      return;
    }
    if (!team) {
      ui.lineCards.innerHTML = '<div class="empty-panel">当前期间没有所选管理单元的数据。</div>';
      return;
    }
    const mixed = team.id === "virtual";
    const market = team.id === "total";
    byId("progress-title").textContent = market ? "语培市场总盘与留学专项" : mixed ? "团队进度" : "语培与留学进度";
    ui.lineCards.style.gridTemplateColumns = mixed ? "1fr" : "";
    const displayTeam = market ? {...team, lines:{...team.lines, market:{...team.lines.training, orders:team.market_orders}}} : mixed ? {...team, lines:{...team.lines, mixed:{...team.lines.training, orders:team.combined_orders}}} : team;
    ui.lineCards.innerHTML = (market ? ["market", "abroad"] : mixed ? ["mixed"] : ["training", "abroad"]).map((lineId) => renderLineCard(lineId, displayTeam, period)).join("");
  }

  function goalValue(value) {
    if (value === null || value === undefined) return '<span class="value-state is-missing">目标未提供</span>';
    if (isObject(value)) {
      const status = metricStatus(value);
      if (status === "not_connected") return '<span class="value-state is-missing">目标未接入</span>';
      if (status === "not_configured") return '<span class="value-state is-unconfigured">归属待确认</span>';
      if (status === "future") return '<span class="value-state is-future">尚未开始</span>';
      if (status === "unknown") return '<span class="value-state is-unknown">目标状态未确认</span>';
      const actual = value.actual ?? value.target ?? null;
      return actual === null ? '<span class="value-state is-unknown">目标未提供</span>' : `<span class="value-number">${formatNumber(actual)}</span>`;
    }
    return `<span class="value-number">${formatNumber(value)}</span>`;
  }

  function personActual(value, team) {
    if (value === null || value === undefined) return metricValueMarkup(value, "not_connected");
    const embeddedStatus = isObject(value) ? cleanString(value.status) : "";
    const status = embeddedStatus || (team.person_through ? "available" : "unknown");
    return metricValueMarkup(value, status);
  }

  function personWithOrderStatus(person) {
    const view = person.order_status_views[state.orderStatusMode];
    return {
      ...person,
      ...view,
      training_target: person.training_target,
      combined_target: person.combined_target,
      abroad_target: person.abroad_target,
    };
  }

  function renderPeople(team, period) {
    const mixed = team?.id === "virtual";
    const headers = mixed ? ["人员", "工单目标", "工单完成", "完成率", "现金目标（元）", "现金完成（元）", "现金完成率", "人头"] : ["人员", "语培目标", "语培完成", "留学目标", "留学完成", "现金目标（元）", "现金完成（元）", "现金完成率", "人头"];
    ui.peopleBody.closest("table").querySelector("thead").innerHTML = `<tr>${headers.map(label=>`<th scope="col">${label}</th>`).join("")}</tr>`;
    if (!period) {
      ui.personPeriod.textContent = "个人绩效区间：没有可展示的统计期间";
      ui.peopleCount.textContent = "—";
      ui.peopleBody.innerHTML = '<tr><td colspan="9" class="table-empty">没有可展示的统计期间。</td></tr>';
      return;
    }
    if (!team) {
      ui.personPeriod.textContent = "个人绩效区间：当前管理单元没有数据";
      ui.peopleCount.textContent = "0 人";
      ui.peopleBody.innerHTML = '<tr><td colspan="9" class="table-empty">当前管理单元没有个人明细。</td></tr>';
      return;
    }
    const start = formatDate(team.person_start);
    const through = formatDate(team.person_through);
    ui.personPeriod.textContent = team.person_start || team.person_through
      ? `个人绩效区间：${start} 至 ${through}`
      : "个人绩效区间：数据未提供，不能沿用期间区间推定";
    const people = safeArray(team.people);
    ui.peopleCount.textContent = `${people.length} 人`;
    if (!people.length) {
      ui.peopleBody.innerHTML = '<tr><td colspan="9" class="table-empty">当前管理单元没有个人明细。</td></tr>';
      return;
    }
    ui.peopleBody.innerHTML = people.map((sourcePerson) => {
      const person = personWithOrderStatus(sourcePerson);
      const name = cleanString(person && person.name) || "未提供姓名";
      const personLine = cleanString(person && person.business_line);
      const personGroup = cleanString(person && person.home_group) || "业务组未提供";
      if (mixed) return `<tr><th scope="row" class="person-name">${escapeHTML(name)}</th>
        <td>${goalValue(person.combined_target)}</td><td>${personActual(person.combined_actual, team)}</td><td>${formatPercent(person.combined_completion)}</td>
        <td>${goalValue(person.cash_actual?.target)}</td><td>${personActual(person.cash_actual, team)}</td><td>${formatPercent(person.cash_actual?.completion)}</td><td>${personActual(person.heads_actual, team)}</td></tr>`;
      return `<tr>
        <th scope="row" class="person-name"><span>${escapeHTML(name)}</span><small class="person-identity">${escapeHTML(personGroup)} · ${escapeHTML(lineLabel(personLine))}</small></th>
        <td>${goalValue(person.training_target)}</td>
        <td>${personActual(person.training_actual, team)}${person.training_completion == null ? "" : `<small class="cell-substate">${formatPercent(person.training_completion)}</small>`}</td>
        <td>${person.home_group !== "大学" && person.abroad_target == null ? '<span class="value-state">不下达</span>' : goalValue(person.abroad_target)}</td>
        <td>${personActual(person.abroad_actual, team)}</td>
        <td>${goalValue(person.cash_actual && person.cash_actual.target)}</td>
        <td>${personActual(person.cash_actual, team)}</td>
        <td>${formatPercent(person.cash_actual && person.cash_actual.completion)}</td>
        <td>${personActual(person.heads_actual, team)}</td>
      </tr>`;
    }).join("");
  }

  function lineLabel(value) {
    const key = cleanString(value);
    return LINES[key] ? LINES[key].label : key || "未提供";
  }

  function renderCountryValue(value, highlight = false) {
    const number = rawActual(value);
    const positive = isNumber(number) && number > 0;
    const rendered = scalarMarkup(value);
    return highlight && positive ? `<span class="unassigned-value">${rendered}</span>` : rendered;
  }

  function renderCountries(team) {
    const groups = safeArray(team && team.country_groups);
    ui.countryCount.textContent = `${groups.length} 条线 · 展开查看国家`;
    ui.countryGroups.innerHTML = groups.map(group => `<details class="country-fold"><summary><strong>${escapeHTML(group.line)}</strong><span>${formatNumber(group.total)} 单</span></summary><div class="table-scroll"><table class="data-table"><thead><tr><th>国家</th><th>线上</th><th>线下</th><th>待确认</th><th>合计</th></tr></thead><tbody>${safeArray(group.countries).map(row => `<tr><th>${escapeHTML(row.country)}</th><td>${formatNumber(row.online)}</td><td>${formatNumber(row.offline)}</td><td>${formatNumber(row.unassigned)}</td><td>${formatNumber(row.total)}</td></tr>`).join("")}</tbody></table></div></details>`).join("") || '<p class="table-empty">暂无国家条线数据</p>';
  }

  function compareTable(rows, targets=false) {
    const heads = safeArray(rows).some(row => row.heads);
    const cashShare = targets && safeArray(rows).some(row => row.passive_cash_share);
    const value = m => formatNumber(m && m.actual);
    const old = m => formatNumber(m && m.prior);
    const change = m => formatPercent(m && m.yoy);
    const target = m => m && m.target != null ? formatNumber(m.target) : "未配置";
    const progress = m => m && m.completion != null ? `<progress max="1" value="${Math.min(1,Math.max(0,m.completion))}"></progress> ${formatPercent(m.completion)}` : "—";
    const shareCell = row => {
      const share = row.passive_cash_share || {};
      const note = `${share.note || "被动新生正向报入现金 ÷ 全渠道新生正向报入现金"}；分子 ${formatNumber(share.numerator)} 元；分母 ${formatNumber(share.denominator)} 元`;
      return `<td title="${escapeHTML(note)}">${formatPercent(share.ratio)}</td>`;
    };
    const table = `<table class="data-table"><thead><tr><th>业务组</th><th>工单完成</th><th>${targets?"工单目标":"同期工单"}</th><th>${targets?"工单进度":"工单同比"}</th><th>现金完成（元）</th><th>${targets?"现金目标":"同期现金"}</th><th>${targets?"现金进度":"现金同比"}</th>${cashShare?'<th>被动现金占新生收入</th>':''}${heads?'<th>人头</th><th>人头同比</th>':''}</tr></thead><tbody>${safeArray(rows).map(row=>`<tr><th>${escapeHTML(row.name)}</th><td>${value(row.orders)}</td><td>${targets?target(row.orders):old(row.orders)}</td><td>${targets?progress(row.orders):change(row.orders)}</td><td>${value(row.cash)}</td><td>${targets?target(row.cash):old(row.cash)}</td><td>${targets?progress(row.cash):change(row.cash)}</td>${cashShare?shareCell(row):''}${heads?`<td>${value(row.heads)}</td><td>${change(row.heads)}</td>`:''}</tr>`).join("")}</tbody></table>`;
    return table;
  }

  function renderAbroadProgress(rows) {
    const progress = metric => isNumber(metric?.completion)
      ? `<progress max="1" value="${Math.min(1, Math.max(0, metric.completion))}"></progress> ${formatPercent(metric.completion)}`
      : metric?.status === "not_covered" ? "该期间未覆盖" : "—";
    const target = metric => metric?.target == null ? "未配置" : formatNumber(metric.target);
    const rowHtml = row => `<tr><th>${escapeHTML(row.name)}</th><td>${target(row.orders)}</td><td>${metricValueMarkup(row.orders)}</td><td>${progress(row.orders)}</td><td>${target(row.cash)}</td><td>${metricValueMarkup(row.cash)}</td><td>${progress(row.cash)}</td><td>${metricValueMarkup(row.heads)}</td></tr>`;
    return `<table class="data-table"><thead><tr><th>维度</th><th>工单目标</th><th>工单完成</th><th>工单进度</th><th>现金目标（元）</th><th>现金完成（元）</th><th>现金进度</th><th>人头</th></tr></thead><tbody>${safeArray(rows).map(row=>rowHtml(row)).join("")}</tbody></table>`;
  }

  function renderRestored(team) {
    const isMarketTotal = state.unitId === "total";
    const scopeView = isMarketTotal ? team?.team_scope_views?.[state.teamScope] : null;
    ui.teamScopeControl.hidden = !isMarketTotal;
    ui.teamScopeSelect.value = state.teamScope;
    const businessGroups = isMarketTotal ? scopeView?.business_groups : team?.business_groups;
    byId("business-groups").innerHTML = compareTable(businessGroups, true);
    const abroadRows = safeArray(isMarketTotal ? scopeView?.study_abroad_progress : team?.abroad_progress);
    byId("abroad-target-section").hidden = !abroadRows.length;
    byId("abroad-targets").innerHTML = renderAbroadProgress(abroadRows);
    const coverage = team?.lines?.abroad?.source_coverage;
    byId("abroad-target-coverage").textContent = coverage ? `${coverage.start_date}—${coverage.through_date}` : "";
    byId("yoy-groups").innerHTML = compareTable(team && team.yoy_groups);
    const key=state.periodId+'|'+state.unitId;
    FlatTables.render(byId("channel-comparison"),team,{mode:"channels",key});
    FlatTables.render(byId("school-comparison"),team,{mode:"schools",key});
    FlatTables.render(byId("grade-comparison"),team,{mode:"grades",key});
  }
  function renderCapacity() {
    if (!state.data) return;
    const selectedPeriod = CapacityView.period(state.data.capacity, state.capacityMonth);
    if (state.activeView === "capacity") {
      ui.periodCaption.textContent = selectedPeriod
        ? `人员贡献 · ${CapacityView.monthLabel(selectedPeriod)}`
        : "人员贡献 · 没有可展示月份";
    }
    CapacityView.render(
      byId("capacity-workspace"),
      state.data.capacity,
      state.capacityMonth,
      state.capacityTeam,
      state.capacityScope,
      state.orderStatusMode,
    );
    CapacityRadar.render(byId("capacity-radar-workspace"), state.data.capacity.radar, state.capacityTeam);
  }

  function setupCapacityPeriodControl() {
    const capacity = state.data && state.data.capacity;
    const periods = CapacityView.periods(capacity);
    const available = new Set(periods.map((period) => String(period.id)));
    if (!available.has(String(state.capacityMonth))) {
      state.capacityMonth = CapacityView.defaultMonth(capacity) || null;
    }
    ui.periodSelect.replaceChildren();
    periods.forEach((period) => {
      const option = document.createElement("option");
      option.value = String(period.id);
      option.textContent = CapacityView.monthLabel(period);
      ui.periodSelect.append(option);
    });
    if (!periods.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "没有人员月份";
      ui.periodSelect.append(option);
    }
    ui.periodSelect.value = state.capacityMonth || "";
    ui.periodSelect.previousElementSibling.textContent = "人员月份";
    ui.periodSelect.disabled = periods.length < 2;
  }

  function setupCapacityTeamControl() {
    const options = CapacityView.groups(state.data && state.data.capacity, state.capacityMonth);
    const available = new Set(options.map((option) => option.id));
    if (state.capacityTeam !== "all" && !available.has(state.capacityTeam)) {
      state.capacityTeam = "all";
    }
    ui.unitSelect.innerHTML = '<option value="all">全部线下团队</option>'
      + options.map(({ id, label }) => `<option value="${escapeHTML(id)}">${escapeHTML(label)}</option>`).join("");
    ui.unitSelect.value = state.capacityTeam;
    ui.unitSelect.previousElementSibling.textContent = "人员团队";
    ui.unitSelect.setAttribute("aria-label", "筛选人员团队");
    ui.unitSelect.disabled = false;
  }

  function restoreOverviewPeriodControl() {
    const periods = safeArray(state.data && state.data.periods);
    ui.periodSelect.replaceChildren();
    periods.forEach((period, index) => {
      const option = document.createElement("option");
      option.value = String(period.id ?? index);
      option.textContent = periodLabel(period);
      ui.periodSelect.append(option);
    });
    ui.periodSelect.value = state.periodId || "";
    ui.periodSelect.previousElementSibling.textContent = "统计期间";
    ui.periodSelect.disabled = periods.length < 2;
  }

  function activityCashStatus(activity) {
    const explicit = cleanString(activity.cash_status);
    if (explicit) return explicit;
    if (activity.cash === null || activity.cash === undefined) return "not_connected";
    return isObject(activity.cash) ? metricStatus(activity.cash) : "unknown";
  }

  function activityCashMarkup(activity) {
    const status = activityCashStatus(activity);
    if (status === "not_connected") return '<span class="value-state is-missing">数据未接入</span>';
    if (status === "not_configured") return '<span class="value-state is-unconfigured">归属待确认</span>';
    if (status === "future") return '<span class="value-state is-future">尚未开始</span>';
    if (status === "not_covered") return '<span class="value-state is-missing">该期间未覆盖</span>';
    if (status !== "available" && status !== "partial") return '<span class="value-state is-unknown">状态未确认</span>';
    const cash = activity.cash;
    const actual = rawActual(cash);
    if (actual === null || actual === undefined) return '<span class="value-state is-missing">部分数据未提供</span>';
    const partialNote = status === "partial" ? '<small class="cell-substate is-alert">来源覆盖不一</small>' : "";
    return `${scalarMarkup(cash)}${partialNote}`;
  }

  function activityHeadsMarkup(activity) {
    const display = cleanString(activity.heads_display);
    if (isObject(activity.heads) && activity.heads.status === "not_covered") return scalarMarkup(activity.heads);
    if (display && (!isObject(activity.heads) || activity.heads.actual == null)) {
      return `<span class="value-number">${escapeHTML(display)}</span>`;
    }
    if (activity.heads && isObject(activity.heads)) return scalarMarkup(activity.heads);
    return scalarMarkup(activity.heads);
  }

  function activityRecoveryText(activity, index) {
    const status = activityCashStatus(activity);
    if (status === "not_connected") return "数据未接入";
    if (status === "not_configured") return "归属待确认";
    if (status === "future") return "尚未开始";
    if (status === "not_covered") return "该期间未覆盖";
    if (status !== "available" && status !== "partial") return "状态未确认";
    const cash = rawActual(activity.cash);
    if (!isNumber(cash)) return "数据未接入";
    const costText = state.activityCosts.get(index) ?? "";
    if (costText === "") return "待填投入";
    const investment = Number(costText);
    if (!Number.isFinite(investment) || investment <= 0 || cash / investment <= 0) return "—";
    return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(cash / investment)}×`;
  }

  function filteredActivities() {
    const activities = safeArray(state.data && state.data.activities);
    if (!state.activityQuery) return activities.map((activity, index) => ({ activity, index }));
    return activities.reduce((matches, activity, index) => {
      const name = typeof activity.name === "string" ? activity.name : "";
      if (name.includes(state.activityQuery)) matches.push({ activity, index });
      return matches;
    }, []);
  }

  function renderActivities() {
    const results = filteredActivities();
    const pageCount = Math.max(1, Math.ceil(results.length / ACTIVITY_PAGE_SIZE));
    state.activityPage = Math.max(1, Math.min(state.activityPage, pageCount));
    const start = (state.activityPage - 1) * ACTIVITY_PAGE_SIZE;
    const visible = results.slice(start, start + ACTIVITY_PAGE_SIZE);
    ui.activityCount.textContent = `${results.length} 项 · 每页 ${ACTIVITY_PAGE_SIZE} 项`;
    ui.activityPageInfo.textContent = `第 ${state.activityPage} / ${pageCount} 页`;
    ui.activityPrevious.disabled = state.activityPage <= 1;
    ui.activityNext.disabled = state.activityPage >= pageCount;
    const metadata = state.data && state.data.metadata ? state.data.metadata : {};
    ui.activityScope.textContent = `工单自 ${formatDate(metadata.orders_coverage_start)}、现金自 ${formatDate(metadata.cash_coverage_start)}，累计至 ${formatDate(metadata.data_through)}；不随期间或管理单元变化。`;
    if (!visible.length) {
      ui.activityBody.innerHTML = `<tr><td colspan="8" class="table-empty">${results.length ? "当前页没有活动。" : state.activityQuery ? "没有匹配的活动。" : "没有可展示的活动累计数据。"}</td></tr>`;
      return;
    }
    ui.activityBody.innerHTML = visible.map(({ activity, index }) => {
      const name = cleanString(activity.name) || "未命名活动";
      const costId = `activity-cost-${index}`;
      const costValue = state.activityCosts.get(index) ?? "";
      const recovery = activityRecoveryText(activity, index);
      return `<tr>
        <th scope="row" class="activity-name">${escapeHTML(name)}</th>
        <td class="numeric">${scalarMarkup(activity.training_orders)}</td>
        <td class="numeric">${scalarMarkup(activity.abroad_orders)}</td>
        <td class="numeric">${scalarMarkup(activity.orders)}</td>
        <td class="numeric">${activityHeadsMarkup(activity)}</td>
        <td class="numeric">${activityCashMarkup(activity)}</td>
        <td><label class="visually-hidden" for="${costId}">${escapeHTML(name)}投入金额</label><input class="cost-input" id="${costId}" data-activity-index="${index}" type="number" step="any" inputmode="decimal" value="${escapeHTML(costValue)}" aria-label="${escapeHTML(name)}投入金额" /></td>
        <td class="numeric"><strong class="recovery-value" id="activity-recovery-${index}">${escapeHTML(recovery)}</strong>${activityCashStatus(activity) === "partial" ? '<small class="cell-substate is-alert">来源覆盖不一</small>' : ""}</td>
      </tr>`;
    }).join("");
  }

  function renderOverview() {
    const period = getPeriod();
    const team = getTeam(period);
    const metadata = state.data && state.data.metadata ? state.data.metadata : {};
    const unitLabel = UNIT_LABELS[state.unitId] || state.unitId;
    ui.periodCaption.textContent = period
      ? `${periodLabel(period)} · ${unitLabel} · 数据截至 ${formatDate(metadata.data_through)}`
      : `数据截至 ${formatDate(metadata.data_through)}`;
    ui.scopeNote.textContent = period
      ? `${formatDate(period.start_date)} 至 ${formatDate(period.through_date)}${period.status === "future" ? " · 尚未开始" : ""}`
      : "等待期间数据";
    renderLineCards(team, period);
    const personalPeriod = safeArray(state.data.periods).find(p => p.id === ui.personalMonth.value);
    renderPeople(getTeam(personalPeriod), personalPeriod);
    renderRestored(team);
    renderCountries(team);
  }

  function renderAll() {
    renderOverview();
    renderCapacity();
    renderActivities();
  }

  function setupControls(data) {
    const periods = safeArray(data.periods);
    ui.periodSelect.replaceChildren();
    periods.forEach((period, index) => {
      const option = document.createElement("option");
      option.value = String(period.id ?? index);
      option.textContent = periodLabel(period);
      ui.periodSelect.append(option);
    });
    const throughDate = cleanString(data.metadata && data.metadata.data_through);
    const throughMonth = throughDate.slice(0, 7);
    const monthlyIdIndex = periods.findIndex((period) => String(period.id) === throughMonth);
    const defaultPeriodIndex = periods.findIndex((period) => cleanString(period.through_date) === throughDate);
    const currentMonthIndex = monthlyIdIndex >= 0 ? monthlyIdIndex : periods.findIndex((period) => {
      const startMonth = cleanString(period.start_date).slice(0, 7);
      const endMonth = cleanString(period.through_date).slice(0, 7);
      return startMonth === throughMonth || endMonth === throughMonth;
    });
    const selectedPeriodIndex = Math.max(0, periods.findIndex(period => period.id === "FY27"));
    state.periodId = periods.length ? String(periods[selectedPeriodIndex].id ?? selectedPeriodIndex) : null;
    ui.personalMonth.innerHTML = periods.filter(p=>/^\d{4}-\d{2}$/.test(p.id)).map(p=>`<option value="${p.id}">${escapeHTML(p.label)}</option>`).join("");
    ui.personalMonth.value = throughMonth;
    ui.periodSelect.value = state.periodId || "";
    ui.periodSelect.disabled = periods.length < 2;
    ui.unitSelect.value = state.unitId;
    ui.unitSelect.disabled = false;
    ui.activitySearch.disabled = false;
    const metadata = data.metadata || {};
    const through = formatDate(metadata.data_through);
    ui.freshnessLabel.textContent = "数据已载入";
    ui.freshnessDate.textContent = `截至 ${through}`;
    ui.freshness.classList.remove("is-error");
    ui.loadMessage.classList.remove("is-visible", "is-error");
    ui.footerRun.textContent = `数据截止 ${through} · 金额单位：元`;
  }

  function setView(viewId, focusTab = false) {
    const known = ["overview", "capacity", "activities"].includes(viewId) ? viewId : "overview";
    state.activeView = known;
    if(known === "capacity") {
      setupCapacityPeriodControl();
      setupCapacityTeamControl();
    } else {
      restoreOverviewPeriodControl();
      const choices = known === "activities" ? ["total"] : ["total","virtual","online"];
      if(known==='overview'&&!choices.includes(state.unitId))state.unitId='total';
      ui.unitSelect.innerHTML=choices.map(id=>`<option value="${id}">${UNIT_LABELS[id]}</option>`).join('');
      ui.unitSelect.value=known==='activities'?'total':state.unitId;
      ui.unitSelect.previousElementSibling.textContent='管理单元';
      ui.unitSelect.setAttribute('aria-label','选择管理单元');
      ui.periodSelect.value=state.periodId;
    }
    ui.periodSelect.closest('label').hidden=known==='activities';
    ui.unitSelect.closest('label').hidden=known==='activities';
    ui.capacityScope.closest('label').hidden=known!=='capacity';
    const virtualView = known === 'overview' && state.unitId === 'virtual';
    byId('page-title').textContent=known==='capacity'?'人员产能':known==='activities'?'市场活动':virtualView?'线上虚拟人经营看板':'市场总看板';
    document.querySelector('.breadcrumb strong').textContent=known==='capacity'?'人员产能':known==='activities'?'市场活动':virtualView?'线上虚拟人':'市场总览';
    document.body.dataset.unit = state.unitId;
    window.dispatchEvent(new Event('management-unit-change'));
    ui.periodSelect.disabled = known === "activities"
      || (known === "capacity"
        ? CapacityView.periods(state.data && state.data.capacity).length < 2
        : safeArray(state.data && state.data.periods).length < 2);
    ui.unitSelect.disabled = known === "activities";
    if (known === "overview") renderOverview();
    else if (known === "activities") ui.periodCaption.textContent = "市场活动 · 可用历史累计";
    for (const tab of ui.tabs) {
      const selected = tab.dataset.view === known;
      tab.setAttribute("aria-selected", selected ? "true" : "false");
      tab.tabIndex = selected ? 0 : -1;
      tab.classList.toggle("is-current", selected);
      if (selected && focusTab) tab.focus();
    }
    for (const panel of ui.panels) panel.hidden = panel.id !== `view-${known}`;
    if (known === "activities") renderActivities();
    if (known === "capacity") renderCapacity();
  }

  function showLoadError() {
    ui.loadMessage.textContent = "看板数据未能加载，请重新生成本地预览后刷新。";
    ui.loadMessage.classList.add("is-visible", "is-error");
    ui.freshnessLabel.textContent = "数据未接入";
    ui.freshnessDate.textContent = "等待数据文件";
    ui.freshness.classList.add("is-error");
    ui.lineCards.innerHTML = '<div class="empty-panel">没有有效的经营期间数据。</div>';
    ui.peopleBody.innerHTML = '<tr><td colspan="9" class="table-empty">没有有效的个人绩效数据。</td></tr>';
    ui.countryGroups.innerHTML = '<p>国家与条线数据未加载。</p>';
    ui.activityBody.innerHTML = '<tr><td colspan="8" class="table-empty">没有有效的活动累计数据。</td></tr>';
  }

  function syncOrderStatusToggles() {
    document.querySelectorAll(".order-status-bit-toggle").forEach((toggle) => {
      const bit = Number(toggle.dataset.statusBit);
      if (bit === 0 || bit === 1) toggle.checked = state.orderStatusMode[bit] === "1";
    });
  }

  document.addEventListener("change", (event) => {
    const toggle = event.target;
    if (!(toggle instanceof HTMLInputElement) || !toggle.matches(".order-status-bit-toggle")) return;
    const bit = Number(toggle.dataset.statusBit);
    if (bit !== 0 && bit !== 1) return;
    const nextMode = state.orderStatusMode.split("");
    nextMode[bit] = toggle.checked ? "1" : "0";
    state.orderStatusMode = nextMode.join("");
    syncOrderStatusToggles();
    if (!state.data) return;
    if (state.activeView === "capacity") renderCapacity();
    else renderOverview();
  });

  ui.tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => setView(tab.dataset.view));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let nextIndex = index;
      if (event.key === "Home") nextIndex = 0;
      else if (event.key === "End") nextIndex = ui.tabs.length - 1;
      else if (event.key === "ArrowDown" || event.key === "ArrowRight") nextIndex = (index + 1) % ui.tabs.length;
      else nextIndex = (index - 1 + ui.tabs.length) % ui.tabs.length;
      setView(ui.tabs[nextIndex].dataset.view, true);
    });
  });

  const corePanels = {targets:"target-panel",yoy:"yoy-panel",channels:"channels-panel",schools:"schools-panel",grades:"grades-panel",people:"people-panel",countries:"countries-panel"};
  Object.keys(corePanels).forEach(mode => byId("core-" + mode).addEventListener("click", () => {
    Object.entries(corePanels).forEach(([name,panel]) => {
      byId(panel).hidden = mode !== name;
      byId("core-"+name).setAttribute("aria-selected",String(mode===name));
    });
    document.querySelector('section[aria-labelledby="progress-title"]').hidden = !["targets","yoy"].includes(mode);
  }));
  window.addEventListener("hashchange", () => { if(state.data) setView(["capacity","activities"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview"); });
  ui.personalMonth.addEventListener("change", () => renderOverview());
  ui.periodSelect.addEventListener("change", () => {
    if (state.activeView === "capacity") {
      state.capacityMonth = ui.periodSelect.value || null;
      setupCapacityTeamControl();
      renderCapacity();
      return;
    }
    state.periodId = ui.periodSelect.value;
    renderOverview();
    renderCapacity();
  });
  ui.unitSelect.addEventListener("change", () => {
    if(state.activeView==='capacity'){state.capacityTeam=ui.unitSelect.value;renderCapacity();return;}
    state.unitId = Object.prototype.hasOwnProperty.call(UNIT_LABELS, ui.unitSelect.value) ? ui.unitSelect.value : "total";
    setView('overview');
    renderCapacity();
  });
  ui.teamScopeSelect.addEventListener("change", () => {
    state.teamScope = ["all", "online", "offline"].includes(ui.teamScopeSelect.value)
      ? ui.teamScopeSelect.value
      : "all";
    renderOverview();
  });
  ui.capacityScope.addEventListener("change", () => {
    state.capacityScope = ui.capacityScope.value;
    renderCapacity();
  });
  ui.activitySearch.addEventListener("input", () => {
    state.activityQuery = ui.activitySearch.value;
    state.activityPage = 1;
    renderActivities();
  });
  ui.activityPrevious.addEventListener("click", () => {
    state.activityPage = Math.max(1, state.activityPage - 1);
    renderActivities();
  });
  ui.activityNext.addEventListener("click", () => {
    state.activityPage += 1;
    renderActivities();
  });
  ui.activityBody.addEventListener("input", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || !input.matches(".cost-input")) return;
    const index = Number(input.dataset.activityIndex);
    if (!Number.isSafeInteger(index) || index < 0) return;
    state.activityCosts.set(index, input.value);
    const recovery = byId(`activity-recovery-${index}`);
    const activity = safeArray(state.data && state.data.activities)[index];
    if (recovery && activity) recovery.textContent = activityRecoveryText(activity, index);
  });
  const embeddedData = byId("dashboard-data");
  const dataReady = embeddedData
    ? Promise.resolve().then(() => JSON.parse(embeddedData.textContent))
    : fetch("./data.json", { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error("看板数据不可用");
      return response.json();
    });
  dataReady.then((data) => {
    if (!isObject(data) || data.schema_version !== "dashboard_rebuild.v1" || !Array.isArray(data.periods) || !data.periods.length) {
      throw new Error("看板数据结构不完整");
    }
    if (!isObject(data.metadata)) throw new Error("看板缺少数据截止信息");
    state.data = data;
    const requestedUnit = new URLSearchParams(location.search).get("unit");
    if (["total", "virtual", "online"].includes(requestedUnit)) state.unitId = requestedUnit;
    setupControls(data);
    renderAll();
    setView(["capacity","activities"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview");
  }).catch(() => {
    showLoadError();
  });
})();
