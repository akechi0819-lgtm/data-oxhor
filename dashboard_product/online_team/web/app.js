"use strict";

(() => {
  const LINE_IDS = ["training", "abroad"];
  const LINE_CLASSES = { training: "training", abroad: "abroad" };
  const byId = (id) => document.getElementById(id);
  const state = {
    data: null,
    periodId: null,
    lineFilter: "all",
    channelQuery: "",
    channelSort: "orders",
    channelLineFilter: "all",
  };

  const ui = {
    periodSelect: byId("period-select"),
    lineSelect: byId("line-select"),
    pageTitle: byId("page-title"),
    periodCaption: byId("period-caption"),
    freshness: byId("freshness"),
    freshnessLabel: byId("freshness-label"),
    freshnessDate: byId("freshness-date"),
    loadMessage: byId("load-message"),
    lineCards: byId("line-cards"),
    scopeNote: byId("scope-note"),
    trainingDailyChart: byId("training-daily-chart"),
    abroadDailyChart: byId("abroad-daily-chart"),
    trainingDailyDetails: byId("training-daily-details"),
    abroadDailyDetails: byId("abroad-daily-details"),
    trainingCutoffSummary: byId("training-cutoff-summary"),
    abroadCutoffSummary: byId("abroad-cutoff-summary"),
    trendPeriodNote: byId("trend-period-note"),
    channelSearch: byId("channel-search"),
    channelLineSelect: byId("channel-line-select"),
    channelSort: byId("channel-sort"),
    channelCount: byId("channel-count"),
    platforms: {
      training: { panel: byId("training-platform-table"), body: byId("training-platform-body"), count: byId("training-platform-count") },
      abroad: { panel: byId("abroad-platform-table"), body: byId("abroad-platform-body"), count: byId("abroad-platform-count") },
    },
    groupBody: byId("group-body"),
    groupNote: byId("group-note"),
    dimensionList: byId("dimension-list"),
    dimensionNote: byId("dimension-note"),
  };

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[char]);
  }

  function cleanString(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "string") return value.trim();
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    return "";
  }

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function numberText(value) {
    if (!isNumber(value)) return value === null || value === undefined ? "—" : escapeHTML(value);
    return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
  }

  function metricUnit(metric, fallback) {
    const unit = cleanString(metric && metric.unit);
    return unit || fallback || "";
  }

  function valueWithUnit(value, unit) {
    if (value === null || value === undefined) return "—";
    const number = numberText(value);
    return unit ? `${number} ${escapeHTML(unit)}` : number;
  }

  function metricValueText(metric, unit) {
    const status = metric && metric.status;
    const display = cleanString(metric && metric.display);
    if (status === "not_covered") return "该期间未覆盖";
    if (status === "not_connected") return "未接入";
    if (status === "not_configured") return "归属待确认";
    if (status === "future") return "尚未开始";
    if (status === "separate_counts") return display ? escapeHTML(display) : "—";
    if ((status === "available" || status === "partial") && display) return escapeHTML(display);
    const actual = actualValue(metric);
    if (actual === null) return "—";
    return valueWithUnit(actual, unit);
  }

  function percentText(value) {
    if (value === null || value === undefined) return "—";
    if (!isNumber(value)) return escapeHTML(value);
    return new Intl.NumberFormat("zh-CN", { style: "percent", maximumFractionDigits: 1 }).format(value);
  }

  function safeArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function formatDate(value) {
    const match = typeof value === "string" && value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return cleanString(value) || "日期未提供";
    return `${match[1]}年${Number(match[2])}月${Number(match[3])}日`;
  }

  function formatDateShort(value) {
    if (typeof value !== "string") return "";
    const match = value.match(/^\d{4}-(\d{2})-(\d{2})$/);
    return match ? `${match[1]}-${match[2]}` : value;
  }

  function formatMonthDay(value) {
    const match = typeof value === "string" && value.match(/^\d{4}-(\d{2})-(\d{2})$/);
    return match ? `${Number(match[1])}/${Number(match[2])}` : "";
  }

  function getPeriod() {
    return safeArray(state.data && state.data.periods).find((period) => period.id === state.periodId) || null;
  }

  function activeLineIds() {
    return state.lineFilter === "all" ? LINE_IDS : [state.lineFilter];
  }

  function visibleChannelLineIds() {
    return activeLineIds().filter((lineId) => state.channelLineFilter === "all" || state.channelLineFilter === lineId);
  }

  function getBaseLine(period, lineId) {
    return period && period.lines && period.lines[lineId] ? period.lines[lineId] : null;
  }

  function getLine(period, lineId) {
    return getBaseLine(period, lineId);
  }

  function actualValue(value) {
    if (value && typeof value === "object" && !Array.isArray(value)) return value.actual ?? null;
    return value ?? null;
  }

  function statusMessage(status, periodStatus, metric) {
    if (periodStatus === "future" || (metric && metric.status === "future")) {
      return "该期间尚未开始";
    }
    if (status === "not_connected") return "未接入";
    if (status === "not_covered") return "该期间未覆盖";
    if (status === "separate_counts" && metric && metric.display) return metric.display;
    if (status === "partial" && metric && (metric.actual === null || metric.actual === undefined)) return "部分数据未提供";
    if (metric && metric.actual === null) return "暂无实际值";
    if (!metric) return "暂无数据";
    return "暂不可用";
  }

  function statusClass(status, periodStatus) {
    if (periodStatus === "future" || status === "future") return "future";
    if (status === "not_connected") return "not-connected";
    if (status === "not_covered") return "not-covered";
    return "";
  }

  function renderDifference(value, unit, kind) {
    if (value === null || value === undefined) return { text: "—", tone: "" };
    const tone = isNumber(value) ? (value < 0 ? "negative" : value > 0 ? "positive" : "") : "";
    const interpretation = !isNumber(value)
      ? ""
      : kind === "gap"
        ? value < 0 ? " · 未达目标" : value > 0 ? " · 超出目标" : " · 与目标持平"
        : value < 0 ? " · 慢于进度" : value > 0 ? " · 快于进度" : " · 与进度持平";
    return { text: `${valueWithUnit(value, unit)}${interpretation}`, tone };
  }

  function renderFootItem(label, text, tone = "") {
    return `<div class="metric-foot-item">${escapeHTML(label)}<strong class="${tone}">${text}</strong></div>`;
  }

  function renderMetricBlock(label, metric, period, fallbackUnit) {
    const isFuture = period.status === "future" || (metric && metric.status === "future");
    const status = metric && metric.status;
    const isCovered = status === "available" || status === "partial";
    const isReady = metric && !isFuture && (
      (isCovered && metric.actual !== null && metric.actual !== undefined)
      || (isCovered && cleanString(metric.display))
      || (status === "separate_counts" && cleanString(metric.display))
    );
    const unit = metricUnit(metric, fallbackUnit);
    const actualText = isReady ? metricValueText(metric, unit) : "";
    const target = metric && metric.target;
    const completion = isFuture ? null : metric && metric.completion;
    const yoy = isFuture ? null : metric && metric.yoy;
    const gap = isFuture ? null : metric && metric.gap;
    const timeGap = isFuture ? null : metric && metric.time_gap;
    const fallbackStatus = statusMessage(status, period.status, metric);
    const yoyTone = isNumber(yoy) ? (yoy < 0 ? "negative" : yoy > 0 ? "positive" : "") : "";
    let mainMarkup;

    if (isReady) {
      const progressWidth = isNumber(completion) ? Math.max(0, Math.min(100, completion * 100)) : null;
      const timeProgressWidth = isNumber(period.time_progress) ? Math.max(0, Math.min(100, period.time_progress * 100)) : null;
      const completionText = completion === null || completion === undefined ? "未配置" : percentText(completion);
      const gapDisplay = target === null || target === undefined ? { text: "未配置", tone: "" } : renderDifference(gap, unit, "gap");
      const timeDisplay = target === null || target === undefined ? { text: "未配置", tone: "" } : renderDifference(timeGap, unit, "time");
      mainMarkup = `
        <div class="metric-core">
          <div class="metric-actual">${actualText}</div>
          <div class="metric-target">目标<strong>${valueWithUnit(target, unit)}</strong></div>
        </div>
        ${progressWidth === null ? "" : `<div class="progress-track" role="img" aria-label="目标完成 ${escapeHTML(percentText(completion))}${timeProgressWidth === null ? "" : `；时间进度 ${escapeHTML(percentText(period.time_progress))}`} "><div class="progress-fill" style="width:${progressWidth}%"></div>${timeProgressWidth === null ? "" : `<span class="progress-marker" style="left:${timeProgressWidth}%" title="时间进度 ${escapeHTML(percentText(period.time_progress))}"></span>`}</div>`}
        <div class="metric-foot">
          ${renderFootItem("完成率", escapeHTML(completionText))}
          ${renderFootItem("差额（负数未达）", escapeHTML(gapDisplay.text), gapDisplay.tone)}
          ${renderFootItem("时间差额（负数落后）", escapeHTML(timeDisplay.text), timeDisplay.tone)}
        </div>`;
    } else {
      const targetText = target === null || target === undefined ? "未配置" : valueWithUnit(target, unit);
      mainMarkup = `<div class="metric-status ${statusClass(status, period.status)}">${escapeHTML(fallbackStatus)}</div><div class="metric-target standalone-target">目标<strong>${targetText}</strong></div>`;
    }

    return `<div class="metric-block">
      <div class="metric-topline"><span class="metric-label">${escapeHTML(label)}</span><span class="metric-yoy ${yoyTone}">同比<strong>${escapeHTML(percentText(yoy))}</strong></span></div>
      ${mainMarkup}
    </div>`;
  }

  function advertisingValue(advertising, key) {
    const value = advertising && advertising[key];
    return isNumber(value) ? value : null;
  }

  function advertisingNumber(advertising, key, unit) {
    const value = advertisingValue(advertising, key);
    return isNumber(value) ? `${numberText(value)} ${unit}` : "—";
  }

  function advertisingWindowLabel(advertising, period) {
    const throughDate = cleanString(advertising && advertising.roi_through_date);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(throughDate)) return "费用日期未提供";
    const startDate = cleanString(advertising && advertising.roi_start_date);
    const selectedStart = cleanString(period && period.start_date);
    if (/^\d{4}-\d{2}-\d{2}$/.test(startDate) && /^\d{4}-\d{2}-\d{2}$/.test(selectedStart) && startDate > selectedStart) {
      return `费用 ${formatMonthDay(startDate)}—${formatMonthDay(throughDate)}`;
    }
    return `费用截至 ${formatDate(throughDate).replace(/^\d{4}年/, "")}`;
  }

  function advertisingWindowTooltip(advertising) {
    const value = (key) => isNumber(advertising && advertising[key]) ? numberText(advertising[key]) : "—";
    return `计算期毛签 ${value("roi_cash")} 元、计算期花费 ${value("roi_spend")} 元、计算期工单 ${value("roi_orders")} 单。ROI＝计算期毛签÷计算期花费，单条工单成本＝计算期花费÷计算期工单。最新已提供花费 ${value("spend")} 元可能大于计算期花费，因为账户截止日期不同，整体按共同截止日期计算。`;
  }

  function advertisingWindowMarkup(advertising, period) {
    return `<span class="advertising-window" title="${escapeHTML(advertisingWindowTooltip(advertising))}">${escapeHTML(advertisingWindowLabel(advertising, period))}</span>`;
  }

  function advertisingSpend(advertising) {
    return advertisingNumber(advertising, "spend", "元");
  }

  function advertisingSpendStatus(advertising) {
    return advertising && isNumber(advertising.spend) ? "provided" : "missing";
  }

  function advertisingStatusMarkup(advertising) {
    const status = advertisingSpendStatus(advertising);
    const note = cleanString(advertising && advertising.note);
    const title = note ? ` title="${escapeHTML(note)}"` : "";
    const label = status === "provided" ? "已提供费用" : "未提供费用";
    return `<span class="advertising-status ${status}"${title}>${label}</span>`;
  }

  function renderAdvertisingMetrics(advertising, period) {
    return `<div class="advertising-summary" role="group" aria-label="投放指标">
      <div class="advertising-metric"><span>花费</span><strong>${escapeHTML(advertisingSpend(advertising))}</strong>${advertisingStatusMarkup(advertising)}</div>
      <div class="advertising-metric"><span>ROI</span><strong>${escapeHTML(advertisingNumber(advertising, "roi", "倍"))}</strong>${advertisingWindowMarkup(advertising, period)}</div>
      <div class="advertising-metric"><span>单条工单成本</span><strong>${escapeHTML(advertisingNumber(advertising, "cost_per_order", "元/单"))}</strong>${advertisingWindowMarkup(advertising, period)}</div>
    </div>`;
  }

  function renderAdvertisingCell(advertising, key, period) {
    const value = key === "spend"
      ? advertisingSpend(advertising)
      : key === "roi"
        ? advertisingNumber(advertising, "roi", "倍")
        : advertisingNumber(advertising, "cost_per_order", "元/单");
    return `<span class="ad-table-value">${escapeHTML(value)}</span>${key === "spend" ? advertisingStatusMarkup(advertising) : advertisingWindowMarkup(advertising, period)}`;
  }

  function renderLineCard(lineId, line, period) {
    const lineLabel = cleanString(line.label) || (lineId === "training" ? "语培" : "留学");
    const lineClass = LINE_CLASSES[lineId];
    const coverage = lineId === "abroad" && line.source_coverage;
    const coverageText = coverage && coverage.start_date && coverage.through_date
      ? `<p class="line-coverage">留学数据：${escapeHTML(cleanString(coverage.start_date))}—${escapeHTML(cleanString(coverage.through_date))}</p>` : "";
    return `<article class="line-card ${lineClass}">
      <div class="line-card-head">
        <div><div class="line-title"><span class="line-symbol" aria-hidden="true"></span><h3>${escapeHTML(lineLabel)}</h3></div>${coverageText}</div>
        <div class="line-card-head-actions"><span class="line-badge">${lineId === "training" ? "语培业务线" : "留学业务线"}</span></div>
      </div>
      ${renderMetricBlock("工单资源", line.orders, period, "单")}
      ${renderMetricBlock(lineId === "abroad" ? "现金" : "现金业绩", line.cash, period, "元")}
      ${renderAdvertisingMetrics(line.advertising, period)}
    </article>`;
  }

  function updatePeriodHeader(period) {
    const metadata = state.data.metadata || {};
    const start = period.start_date ? formatDate(period.start_date) : "起始日期未提供";
    const end = period.end_date ? formatDate(period.end_date) : "结束日期未提供";
    const through = period.through_date || metadata.data_through;
    const title = cleanString(metadata.title) || "线上团队 · 经营进度";
    const abroadCoverage = state.lineFilter === "abroad"
      ? getLine(period, "abroad")?.source_coverage : null;
    const freshnessThrough = abroadCoverage?.through_date || metadata.data_through || through;
    const uncovered = state.lineFilter === "abroad" && getLine(period, "abroad")?.orders?.status === "not_covered";
    ui.pageTitle.textContent = title;
    ui.periodCaption.textContent = period.status === "future"
      ? `${period.label || period.id} · ${start}至${end} · 该期间尚未开始`
      : `${period.label || period.id} · ${start}至${end} · 数据截至${formatDate(abroadCoverage ? freshnessThrough : through)}`;
    ui.freshness.classList.toggle("is-ready", !uncovered && period.status !== "future" && period.status === "available");
    ui.freshness.classList.toggle("is-future", period.status === "future");
    ui.freshness.classList.remove("is-error");
    ui.freshnessLabel.textContent = period.status === "future" ? "未到统计期" : uncovered ? "该期间未覆盖" : period.status === "available" ? "数据已更新" : "数据状态";
    ui.freshnessDate.textContent = period.status === "future" ? `统计期间 ${period.label || period.id}` : `数据截止 ${formatDate(freshnessThrough)}`;
    ui.trendPeriodNote.textContent = period.status === "future" ? "尚未开始" : `${formatDate(period.start_date)} — ${formatDate(through)}`;
    ui.scopeNote.textContent = period.status === "future"
      ? "本期时间进度 尚未开始"
      : `本期时间进度 ${percentText(period.time_progress)}`;
  }

  function renderLineCards(period) {
    const ids = activeLineIds();
    const cards = ids.map((lineId) => {
      const line = getLine(period, lineId);
      return line ? renderLineCard(lineId, line, period) : "";
    }).filter(Boolean);
    ui.lineCards.innerHTML = cards.length ? cards.join("") : `<div class="empty-panel">所选业务线在本期没有展示结果。</div>`;
    ui.lineCards.classList.toggle("single-line", ids.length === 1);
  }

  function drawTextElement(svg, x, y, text, className, anchor = "start") {
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", String(x));
    label.setAttribute("y", String(y));
    label.setAttribute("class", className);
    label.setAttribute("text-anchor", anchor);
    label.textContent = text;
    svg.appendChild(label);
    return label;
  }

  function drawLineElement(svg, x1, y1, x2, y2, className) {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", String(x1));
    line.setAttribute("y1", String(y1));
    line.setAttribute("x2", String(x2));
    line.setAttribute("y2", String(y2));
    line.setAttribute("class", className);
    svg.appendChild(line);
  }

  function niceAxis(maxValue) {
    const rawStep = Math.max(maxValue / 4, 1);
    const power = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const step = Math.ceil(rawStep / power) * power;
    return { step, max: step * 4 };
  }

  function appendSVGTitle(element, text) {
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = text;
    element.appendChild(title);
  }

  function drawRotatedAxisLabel(svg, x, y, text, anchor) {
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", String(x));
    label.setAttribute("y", String(y));
    label.setAttribute("class", "chart-axis-label chart-axis-title");
    label.setAttribute("text-anchor", anchor);
    label.setAttribute("transform", `rotate(-90 ${x} ${y})`);
    label.textContent = text;
    svg.appendChild(label);
  }

  function dailyValues(lineId, day) {
    const training = lineId === "training";
    const orderField = training ? "training_orders" : "abroad_orders";
    const spendField = training ? "training_spend" : "abroad_spend";
    const spendStatusField = training ? "training_spend_status" : "abroad_spend_status";
    const cashField = training ? "training_cash" : "abroad_cash";
    const roiField = training ? "training_roi" : "abroad_roi";
    const rawSpend = day[spendField];
    const spend = day[spendStatusField] === "missing" || !isNumber(rawSpend) ? null : rawSpend;
    return {
      orders: isNumber(day[orderField]) ? day[orderField] : null,
      spend,
      spendStatus: day[spendStatusField],
      cash: isNumber(day[cashField]) ? day[cashField] : null,
      roi: isNumber(day[roiField]) ? day[roiField] : null,
    };
  }

  function dailyAccessibleText(day, values) {
    const spend = values.spend === null
      ? "花费未提供，费用柱缺失"
      : `已提供花费 ${numberText(values.spend)} 元${values.spendStatus === "partial" ? "（部分来源）" : ""}`;
    const orders = values.orders === null ? "工单未提供" : `工单 ${numberText(values.orders)} 单`;
    const cash = values.cash === null ? "毛签未提供" : `毛签 ${numberText(values.cash)} 元`;
    const roi = values.roi === null ? "日 ROI —" : `日 ROI ${numberText(values.roi)} 倍`;
    return `${formatDate(day.date)}：${spend}；${orders}；${cash}；${roi}`;
  }

  function formatDayLabel(value) {
    const match = typeof value === "string" && value.match(/^\d{4}-(\d{2})-(\d{2})$/);
    return match ? `${Number(match[1])}-${Number(match[2])}` : cleanString(value) || "—";
  }

  function renderDailySummary(summaryNode, line, period, cutoffPoint) {
    const advertising = line && line.advertising;
    const orders = metricValueText(line && line.orders, "单");
    const cash = metricValueText(line && line.cash, "元");
    const cutoffDate = cutoffPoint && cutoffPoint.day.date
      ? cutoffPoint.day.date
      : line && line.source_coverage && line.source_coverage.through_date
        ? line.source_coverage.through_date
        : period.through_date;
    summaryNode.innerHTML = [
      `<span class="cutoff-date">截至 ${escapeHTML(formatDate(cutoffDate))}</span>`,
      `<span>期间花费 <strong>${escapeHTML(advertisingSpend(advertising))}</strong> ${advertisingStatusMarkup(advertising)}</span>`,
      `<span>期间工单 <strong>${escapeHTML(orders)}</strong></span>`,
      `<span>期间毛签 <strong>${escapeHTML(cash)}</strong></span>`,
    ].join("");
  }

  function renderDailyDetails(detailsNode, points, lineLabel) {
    if (!points.length) {
      detailsNode.hidden = true;
      detailsNode.replaceChildren();
      return;
    }
    const dateHeaders = points.map(({ day }) => `<th scope="col">${escapeHTML(formatDayLabel(day.date))}</th>`).join("");
    const metricRow = (label, key) => `<tr><th scope="row">${label}</th>${points.map(({ values }) => {
      const value = values[key];
      return `<td class="numeric">${value === null ? "—" : numberText(value)}</td>`;
    }).join("")}</tr>`;
    detailsNode.hidden = false;
    detailsNode.innerHTML = `<div class="table-scroll daily-details-scroll"><table class="data-table daily-values-table" aria-label="${escapeHTML(lineLabel)}每日数值明细">
      <thead><tr><th scope="col">日期</th>${dateHeaders}</tr></thead>
      <tbody>${metricRow("花费（元）", "spend")}${metricRow("工单（单）", "orders")}${metricRow("毛签（元）", "cash")}</tbody></table></div>`;
  }

  function renderDailyChart(lineId, line, period, daily, chart, detailsNode, summaryNode) {
    const visible = state.lineFilter === "all" || state.lineFilter === lineId;
    chart.closest(".daily-chart-panel").hidden = !visible;

    if (period.status === "future") {
      summaryNode.textContent = "该期间尚未开始";
      chart.innerHTML = `<div class="empty-chart">该期间尚未开始</div>`;
      detailsNode.hidden = true;
      detailsNode.replaceChildren();
      return;
    }

    const points = daily.map((day) => ({ day, values: dailyValues(lineId, day) }));
    const cutoffPoint = points.slice().reverse().find(({ values }) => values.spend !== null || values.orders !== null || values.cash !== null);
    renderDailySummary(summaryNode, line, period, cutoffPoint);
    renderDailyDetails(detailsNode, points, lineId === "training" ? "语培" : "留学");
    const orderValues = points.map((point) => point.values.orders).filter(isNumber);
    const spendValues = points.map((point) => point.values.spend).filter(isNumber);
    const cashValues = points.map((point) => point.values.cash).filter(isNumber);
    const amountValues = [...spendValues, ...cashValues];
    const lineLabel = lineId === "training" ? "语培" : "留学";
    if (!daily.length || (!orderValues.length && !spendValues.length && !cashValues.length)) {
      chart.innerHTML = `<div class="empty-chart">当前期间暂无可展示的趋势数据</div>`;
      return;
    }

    const viewportWidth = Math.max(320, Math.round(chart.clientWidth || (window.innerWidth <= 640 ? 360 : 520)));
    const width = Math.max(viewportWidth, 92 + Math.max(0, points.length - 1) * 42);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} 244`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("class", `daily-svg ${LINE_CLASSES[lineId]}-chart`);
    svg.style.width = `${width}px`;
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${lineLabel}每日花费、毛签与工单，左轴为金额元，右轴为工单单`);
    appendSVGTitle(svg, `${lineLabel}每日花费、毛签与工单 · ${period.label || period.id}`);
    const description = document.createElementNS("http://www.w3.org/2000/svg", "desc");
    description.textContent = "柱形显示花费，实线显示毛签金额，虚线显示工单量；各日期还提供日 ROI。";
    svg.appendChild(description);

    const chartBox = { left: 48, right: width - 44, top: 31, bottom: 192 };
    const orderAxis = niceAxis(Math.max(0, ...orderValues));
    const amountAxis = niceAxis(Math.max(0, ...amountValues));
    for (let tick = 0; tick <= 4; tick += 1) {
      const fraction = tick / 4;
      const y = chartBox.bottom - fraction * (chartBox.bottom - chartBox.top);
      drawLineElement(svg, chartBox.left, y, chartBox.right, y, "chart-gridline");
      drawTextElement(svg, chartBox.left - 7, y + 3, amountValues.length ? numberText(amountAxis.max * fraction) : "—", "chart-axis-label", "end");
      drawTextElement(svg, chartBox.right + 7, y + 3, orderValues.length ? numberText(orderAxis.max * fraction) : "—", "chart-axis-label", "start");
    }
    drawRotatedAxisLabel(svg, 10, (chartBox.top + chartBox.bottom) / 2, "花费/毛签（元）", "middle");
    drawRotatedAxisLabel(svg, width - 9, (chartBox.top + chartBox.bottom) / 2, "工单（单）", "middle");

    const xAt = (index) => points.length <= 1
      ? (chartBox.left + chartBox.right) / 2
      : chartBox.left + (index / (points.length - 1)) * (chartBox.right - chartBox.left);
    const yForAmount = (value) => chartBox.bottom - (value / amountAxis.max) * (chartBox.bottom - chartBox.top);
    const yForOrders = (value) => chartBox.bottom - (value / orderAxis.max) * (chartBox.bottom - chartBox.top);
    const slotWidth = (chartBox.right - chartBox.left) / Math.max(1, points.length - 1);
    const barWidth = Math.max(2, Math.min(18, slotWidth * 0.56));

    points.forEach(({ day, values }, index) => {
      if (values.spend === null) return;
      const x = xAt(index);
      const y = yForAmount(values.spend);
      const height = Math.max(1.5, chartBox.bottom - y);
      const bar = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      bar.setAttribute("x", String(x - barWidth / 2));
      bar.setAttribute("y", String(chartBox.bottom - height));
      bar.setAttribute("width", String(barWidth));
      bar.setAttribute("height", String(height));
      bar.setAttribute("rx", "2");
      bar.setAttribute("class", "chart-spend-bar");
      bar.setAttribute("data-date", cleanString(day.date));
      svg.appendChild(bar);
    });

    let cashPathData = "";
    let drawingCash = false;
    points.forEach(({ values }, index) => {
      if (values.cash === null) {
        drawingCash = false;
        return;
      }
      const x = xAt(index);
      const y = yForAmount(values.cash);
      cashPathData += `${drawingCash ? " L" : " M"}${x.toFixed(2)} ${y.toFixed(2)}`;
      drawingCash = true;
    });
    if (cashPathData) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", cashPathData.trim());
      path.setAttribute("class", "chart-cash-series");
      svg.appendChild(path);
    }

    let pathData = "";
    let drawing = false;
    points.forEach(({ values }, index) => {
      if (values.orders === null) {
        drawing = false;
        return;
      }
      const x = xAt(index);
      const y = yForOrders(values.orders);
      pathData += `${drawing ? " L" : " M"}${x.toFixed(2)} ${y.toFixed(2)}`;
      drawing = true;
    });
    if (pathData) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", pathData.trim());
      path.setAttribute("class", "chart-order-series");
      svg.appendChild(path);
    }

    points.forEach(({ values }, index) => {
      if (values.cash === null) return;
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("cx", String(xAt(index)));
      dot.setAttribute("cy", String(yForAmount(values.cash)));
      dot.setAttribute("r", "3.2");
      dot.setAttribute("class", "chart-cash-dot");
      svg.appendChild(dot);
    });

    points.forEach(({ values }, index) => {
      if (values.orders === null) return;
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      marker.setAttribute("x", String(xAt(index) - 2.5));
      marker.setAttribute("y", String(yForOrders(values.orders) - 2.5));
      marker.setAttribute("width", "5");
      marker.setAttribute("height", "5");
      marker.setAttribute("class", "chart-order-dot");
      svg.appendChild(marker);
    });

    points.forEach(({ day, values }, index) => {
      if (values.spend === null) return;
      const y = yForAmount(values.spend) - 6;
      const amountText = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(values.spend);
      const isFirst = index === 0;
      const isLast = index === points.length - 1;
      const labelX = xAt(index) + (isFirst ? 3 : isLast ? -3 : 0);
      const anchor = isFirst ? "start" : isLast ? "end" : "middle";
      const label = drawTextElement(svg, labelX, y, amountText, "chart-spend-label", anchor);
      label.setAttribute("data-date", cleanString(day.date));
      label.setAttribute("aria-label", `${formatDate(day.date)} 花费 ${numberText(values.spend)} 元`);
      appendSVGTitle(label, `${formatDate(day.date)} 花费 ${numberText(values.spend)} 元`);
    });

    points.forEach(({ day, values }, index) => {
      const label = dailyAccessibleText(day, values);
      const focusMark = document.createElementNS("http://www.w3.org/2000/svg", "g");
      focusMark.setAttribute("class", "chart-day-focus");
      focusMark.setAttribute("role", "img");
      focusMark.setAttribute("tabindex", "0");
      focusMark.setAttribute("aria-label", label);
      appendSVGTitle(focusMark, label);
      const hitArea = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      const hitWidth = points.length <= 1 ? chartBox.right - chartBox.left : Math.max(8, slotWidth);
      hitArea.setAttribute("x", String(xAt(index) - hitWidth / 2));
      hitArea.setAttribute("y", String(chartBox.top));
      hitArea.setAttribute("width", String(hitWidth));
      hitArea.setAttribute("height", String(chartBox.bottom - chartBox.top));
      hitArea.setAttribute("class", "chart-day-hit-area");
      focusMark.appendChild(hitArea);
      svg.appendChild(focusMark);
    });

    const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
    labelIndexes.forEach((index) => drawTextElement(svg, xAt(index), 222, formatDateShort(points[index].day.date), "chart-axis-label", index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"));
    const accessibleList = document.createElement("ul");
    accessibleList.className = "chart-accessible-data visually-hidden";
    accessibleList.setAttribute("aria-label", `${lineLabel}每日花费、工单、毛签与日 ROI 明细`);
    accessibleList.innerHTML = points.map(({ day, values }) => `<li>${escapeHTML(dailyAccessibleText(day, values))}</li>`).join("");
    chart.replaceChildren(svg, accessibleList);
  }

  function renderTrend(period) {
    const daily = safeArray(period.daily).slice().sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
    const training = getLine(period, "training");
    const abroad = getLine(period, "abroad");
    renderDailyChart("training", training, period, daily, ui.trainingDailyChart, ui.trainingDailyDetails, ui.trainingCutoffSummary);
    renderDailyChart("abroad", abroad, period, daily, ui.abroadDailyChart, ui.abroadDailyDetails, ui.abroadCutoffSummary);
  }

  function numericForSort(value) {
    if (value && typeof value === "object") value = actualValue(value);
    return isNumber(value) ? value : Number.NEGATIVE_INFINITY;
  }

  function channelGrossSigningText(row) {
    const metric = row.cash && typeof row.cash === "object" ? row.cash : null;
    const status = metric && metric.status;
    if (status === "not_covered") return "该期间未覆盖";
    if (status === "not_connected") return "未接入";
    if (status === "not_configured") return "归属待确认";
    if (status === "future") return "尚未开始";
    if (status === "separate_counts") return cleanString(metric.display) || "—";
    if ((status === "available" || status === "partial") && cleanString(metric.display)) return cleanString(metric.display);
    const value = actualValue(row.cash);
    return value === null ? "—" : valueWithUnit(value, metricUnit(metric, "元"));
  }

  function channelRows(period, lineId) {
    const line = getLine(period, lineId);
    const sourceChannels = safeArray(line && line.channels);
    const query = state.channelQuery.toLocaleLowerCase("zh-CN");
    const filtered = sourceChannels.filter((channel) => {
      const first = Array.isArray(channel.first_channels) ? channel.first_channels.join(" ") : cleanString(channel.first_channels);
      const lineLabel = lineId === "training" ? "语培" : "留学";
      return `${lineLabel} ${cleanString(channel.name)} ${first}`.toLocaleLowerCase("zh-CN").includes(query);
    });
    const sortField = { orders: "orders", share: "share", yoy: "orders_yoy" }[state.channelSort];
    filtered.sort((a, b) => {
      if (state.channelSort === "name") return cleanString(a.name).localeCompare(cleanString(b.name), "zh-CN");
      return numericForSort(b[sortField]) - numericForSort(a[sortField]);
    });
    return { lineId, line, channels: filtered, sourceCount: sourceChannels.length };
  }


  function renderChannelBusinessDetails(groups, period) {
    if (!groups.length) return "";
    const rows = groups.map((group) => {
      const groupName = cleanString(group.name) || "未命名业务组";
      const groupOrders = isNumber(group.orders) ? numberText(group.orders) + " 单" : "—";
      const groupCash = isNumber(group.cash) ? numberText(group.cash) + " 元" : "—";
      return "<tr>" +
        "<td><span class='channel-name'>" + escapeHTML(groupName) + "</span></td>" +
        "<td class='numeric'>" + escapeHTML(groupOrders) + "</td>" +
        "<td class='numeric'>" + escapeHTML(groupCash) + "</td>" +
        "<td class='numeric'>" + renderAdvertisingCell(group.advertising, "spend", period) + "</td>" +
        "<td class='numeric'>" + renderAdvertisingCell(group.advertising, "roi", period) + "</td>" +
        "<td class='numeric'>" + renderAdvertisingCell(group.advertising, "cost_per_order", period) + "</td>" +
        "</tr>";
    }).join("");
    return "<tr class='channel-expansion-row'><td colspan='9'><details class='channel-business-details'>" +
      "<summary>按业务组查看工单、毛签与账户费用 <span>" + groups.length + " 个业务组</span></summary>" +
      "<div class='table-scroll channel-business-scroll'><table class='data-table channel-business-table'>" +
      "<thead><tr><th scope='col'>业务组</th><th scope='col'>工单</th><th scope='col'>毛签</th><th scope='col'>花费</th><th scope='col'>ROI（倍）</th><th scope='col'>单条工单成本</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div></details></td></tr>";
  }

  function renderChannels(period) {
    const visibleLines = new Set(visibleChannelLineIds());
    if (period.status === "future") {
      LINE_IDS.forEach((lineId) => {
        const platform = ui.platforms[lineId];
        platform.panel.hidden = !visibleLines.has(lineId);
        platform.count.textContent = "尚未开始";
        platform.body.innerHTML = "<tr><td colspan='9' class='table-empty'>该期间尚未开始</td></tr>";
      });
      ui.channelCount.textContent = "尚未开始";
      return;
    }

    let visibleCount = 0;
    LINE_IDS.forEach((lineId) => {
      const platform = ui.platforms[lineId];
      const visible = visibleLines.has(lineId);
      const { line, channels, sourceCount } = channelRows(period, lineId);
      platform.panel.hidden = !visible;
      platform.count.textContent = channels.length + " 个平台";
      if (visible) visibleCount += channels.length;

      if (!channels.length) {
        const emptyText = state.channelQuery && sourceCount ? "没有匹配的平台。" : "当前期间暂无平台表现。";
        platform.body.innerHTML = "<tr><td colspan='9' class='table-empty'>" + escapeHTML(emptyText) + "</td></tr>";
        return;
      }

      platform.body.innerHTML = channels.map((channel) => {
        const platformName = cleanString(channel.name) || "未命名平台";
        const orders = metricValueText(channel.orders, "单");
        const yoy = channel.orders_yoy ?? (channel.orders && channel.orders.yoy);
        const today = channel.today_orders;
        const businessGroups = safeArray(channel.groups);
        const row = "<tr class='fee-" + advertisingSpendStatus(channel.advertising) + "'>" +
          "<td><span class='channel-name'>" + escapeHTML(platformName) + "</span></td>" +
          "<td class='numeric'>" + orders + "</td>" +
          "<td class='numeric'>" + escapeHTML(percentText(yoy)) + "</td>" +
          "<td class='numeric'>" + escapeHTML(percentText(channel.share)) + "</td>" +
          "<td class='numeric'>" + (today === null || today === undefined ? "—" : numberText(today) + " 单") + "</td>" +
          "<td class='numeric'>" + escapeHTML(channelGrossSigningText(channel)) + "</td>" +
          "<td class='numeric'>" + renderAdvertisingCell(channel.advertising, "spend", period) + "</td>" +
          "<td class='numeric'>" + renderAdvertisingCell(channel.advertising, "roi", period) + "</td>" +
          "<td class='numeric'>" + renderAdvertisingCell(channel.advertising, "cost_per_order", period) + "</td>" +
          "</tr>";
        return row + renderChannelBusinessDetails(businessGroups, period);
      }).join("");
    });
    ui.channelCount.textContent = visibleCount + " 个平台";
  }

  function renderGroups(period) {
    const panel = ui.groupBody.closest(".breakdown-panel");
    const visible = state.lineFilter !== "abroad";
    panel.hidden = !visible;
    panel.parentElement.classList.toggle("single-breakdown", state.lineFilter !== "all");
    ui.groupNote.hidden = true;
    if (!visible) return;
    const line = getLine(period, "training");
    const groups = safeArray(line && line.groups);
    if (period.status === "future") {
      ui.groupBody.innerHTML = `<tr><td colspan="8" class="table-empty">该期间尚未开始</td></tr>`;
      return;
    }
    if (!groups.length) {
      ui.groupBody.innerHTML = `<tr><td colspan="8" class="table-empty">当前期间暂无业务组拆解。</td></tr>`;
      return;
    }
    ui.groupBody.innerHTML = groups.map((group) => {
      const orderMetric = group.orders;
      const cashMetric = group.cash;
      const orderUnit = metricUnit(orderMetric, "单");
      const cashUnit = metricUnit(cashMetric, "元");
      const actual = actualValue(orderMetric);
      const target = orderMetric && typeof orderMetric === "object" ? orderMetric.target : null;
      const gap = orderMetric && typeof orderMetric === "object" ? orderMetric.gap : null;
      const groupCash = actualValue(cashMetric);
      const isGroupFuture = period.status === "future" || (orderMetric && orderMetric.status === "future");
      const orderText = isGroupFuture ? "尚未开始" : actual === null ? orderMetric && orderMetric.status === "not_connected" ? "待接入" : "—" : valueWithUnit(actual, orderUnit);
      const targetText = isGroupFuture && target === null ? "—" : target === null || target === undefined ? "未配置" : valueWithUnit(target, orderUnit);
      const gapText = isGroupFuture || target === null || target === undefined ? "—" : renderDifference(gap, orderUnit, "gap").text;
      const cashText = isGroupFuture ? "尚未开始" : groupCash === null ? cashMetric && cashMetric.status === "not_connected" ? "待接入" : "—" : valueWithUnit(groupCash, cashUnit);
      return `<tr><td>${escapeHTML(cleanString(group.name) || "未命名业务组")}</td><td>${escapeHTML(orderText)}</td><td>${escapeHTML(targetText)}</td><td>${escapeHTML(gapText)}</td><td>${escapeHTML(cashText)}</td><td>${renderAdvertisingCell(group.advertising, "spend", period)}</td><td>${renderAdvertisingCell(group.advertising, "roi", period)}</td><td>${renderAdvertisingCell(group.advertising, "cost_per_order", period)}</td></tr>`;
    }).join("");
  }

  function dimensionValueText(value, unit) {
    if (value && typeof value === "object") {
      if (value.status === "not_covered") return "该期间未覆盖";
      if (value.status === "not_connected") return "未接入";
      if (value.status === "separate_counts") return cleanString(value.display) || "—";
      if ((value.status === "available" || value.status === "partial") && cleanString(value.display)) return cleanString(value.display);
    }
    const actual = actualValue(value);
    return actual === null ? "—" : valueWithUnit(actual, unit);
  }

  function renderDimensionNode(dimension, depth = 0) {
    const children = safeArray(dimension.children);
    const name = cleanString(dimension.name) || "未命名条线";
    const orderValue = dimensionValueText(dimension.orders, "单");
    const yoy = dimension.yoy ?? (dimension.orders && dimension.orders.yoy);
    const prior = actualValue(dimension.prior_orders);
    const priorText = prior === null ? "" : `<span>同期 <strong>${valueWithUnit(prior, "单")}</strong></span>`;
    const classes = `dimension-item${depth ? " nested" : ""}`;
    const contents = `<span class="dimension-name">${escapeHTML(name)}</span><span class="dimension-summary-values"><span>工单 <strong>${escapeHTML(orderValue)}</strong></span>${priorText}<span>同比 <strong>${escapeHTML(percentText(yoy))}</strong></span></span>`;
    if (!children.length) return `<div class="${classes} dimension-leaf"><div class="dimension-row">${contents}</div></div>`;
    return `<details class="${classes}"><summary><span class="dimension-chevron" aria-hidden="true"></span>${contents}</summary><div class="dimension-children">${children.map((child) => renderDimensionNode(child, depth + 1)).join("")}</div></details>`;
  }

  function renderDimensions(period) {
    const panel = ui.dimensionList.closest(".breakdown-panel");
    const visible = state.lineFilter !== "training";
    panel.hidden = !visible;
    ui.dimensionNote.hidden = true;
    if (!visible) return;
    const line = getLine(period, "abroad");
    const dimensions = safeArray(line && line.dimensions);
    if (period.status === "future") {
      ui.dimensionList.innerHTML = `<div class="dimension-empty">该期间尚未开始</div>`;
      return;
    }
    if (!dimensions.length) {
      ui.dimensionList.innerHTML = `<div class="dimension-empty">当前期间暂无条线或国家拆解。</div>`;
      return;
    }
    ui.dimensionList.innerHTML = dimensions.map((dimension) => renderDimensionNode(dimension)).join("");
  }

  function renderAll() {
    const period = getPeriod();
    if (!period) {
      showError("没有可用的统计期间，请检查本期看板数据准备状态。");
      return;
    }
    updatePeriodHeader(period);
    renderLineCards(period);
    renderTrend(period);
    renderChannels(period);
    renderGroups(period);
    renderDimensions(period);
    ui.loadMessage.classList.remove("is-visible", "is-error");
    ui.loadMessage.textContent = "";
  }

  function setupPeriods(data) {
    const periods = safeArray(data.periods);
    ui.periodSelect.replaceChildren();
    periods.forEach((period) => {
      const option = document.createElement("option");
      option.value = cleanString(period.id);
      option.textContent = cleanString(period.label) || cleanString(period.id);
      ui.periodSelect.appendChild(option);
    });
    const preferred = cleanString(data.metadata && data.metadata.default_period);
    state.periodId = periods.some((period) => period.id === preferred)
      ? preferred
      : (periods.find((period) => period.status === "available") || periods[0] || {}).id || null;
    if (state.periodId) ui.periodSelect.value = state.periodId;
    ui.periodSelect.disabled = periods.length === 0;
    ui.lineSelect.disabled = false;
    ui.channelSearch.disabled = false;
    ui.channelLineSelect.disabled = false;
    ui.channelSort.disabled = false;
    syncChannelLineOptions();
  }

  function syncChannelLineOptions() {
    [...ui.channelLineSelect.options].forEach((option) => {
      option.disabled = option.value !== "all" && state.lineFilter !== "all" && option.value !== state.lineFilter;
    });
    ui.channelLineSelect.value = state.channelLineFilter;
  }

  function showError(message) {
    ui.loadMessage.textContent = message;
    ui.loadMessage.classList.add("is-visible", "is-error");
    ui.freshness.classList.add("is-error");
    ui.freshness.classList.remove("is-ready", "is-future");
    ui.freshnessLabel.textContent = "数据未就绪";
    ui.freshnessDate.textContent = "未载入本次结果";
  }

  function setNavigationObserver() {
    if (!("IntersectionObserver" in window)) return;
    const links = [...document.querySelectorAll(".nav-link")];
    const targets = links.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      links.forEach((link) => link.classList.toggle("is-current", link.getAttribute("href") === `#${visible.target.id}`));
    }, { rootMargin: "-18% 0px -65% 0px", threshold: [0, .2, .5] });
    targets.forEach((target) => observer.observe(target));
  }

  ui.periodSelect.addEventListener("change", () => {
    state.periodId = ui.periodSelect.value;
    renderAll();
  });
  ui.lineSelect.addEventListener("change", () => {
    state.lineFilter = ["all", ...LINE_IDS].includes(ui.lineSelect.value) ? ui.lineSelect.value : "all";
    state.channelLineFilter = "all";
    syncChannelLineOptions();
    renderAll();
  });
  ui.channelLineSelect.addEventListener("change", () => {
    const candidate = ui.channelLineSelect.value;
    state.channelLineFilter = candidate === "all" || activeLineIds().includes(candidate) ? candidate : "all";
    ui.channelLineSelect.value = state.channelLineFilter;
    const period = getPeriod();
    if (period) renderChannels(period);
  });
  ui.channelSearch.addEventListener("input", () => {
    state.channelQuery = ui.channelSearch.value.trim();
    const period = getPeriod();
    if (period) renderChannels(period);
  });
  ui.channelSort.addEventListener("change", () => {
    state.channelSort = ui.channelSort.value;
    const period = getPeriod();
    if (period) renderChannels(period);
  });
  const embeddedData = document.getElementById("dashboard-data");
  const dataReady = embeddedData
    ? Promise.resolve().then(() => JSON.parse(embeddedData.textContent))
    : fetch("./data.json", { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    });
  dataReady
    .then((data) => {
      if (!data || data.schema_version !== "dashboard_rebuild.v1" || !Array.isArray(data.periods) || !data.periods.length) {
        throw new Error("展示数据结构不符合 dashboard_rebuild.v1 或没有期间数据");
      }
      const hasLineData = data.periods.every((period) => period.lines && period.lines.training && period.lines.abroad);
      if (!hasLineData) throw new Error("看板期间缺少业务线结果");
      state.data = data;
      setupPeriods(data);
      renderAll();
      setNavigationObserver();
    })
    .catch(() => {
      showError("看板数据尚未准备好或内容不完整，请在数据准备完成后重新打开。");
    });
})();
