"use strict";

(() => {
  const LINE_IDS = ["training", "abroad"];
  const LINE_COLORS = { training: "#2e6fb1", abroad: "#087e80" };
  const LINE_CLASSES = { training: "training", abroad: "abroad" };
  const LINE_TAG_CLASSES = { training: "training-text", abroad: "abroad-text" };
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
    dailyChart: byId("daily-chart"),
    trendLegend: byId("trend-legend"),
    trendPeriodNote: byId("trend-period-note"),
    channelSearch: byId("channel-search"),
    channelLineSelect: byId("channel-line-select"),
    channelSort: byId("channel-sort"),
    channelCount: byId("channel-count"),
    channelBody: byId("channel-body"),
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

  function renderTrend(period) {
    const daily = safeArray(period.daily).slice().sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
    let series = activeLineIds().flatMap((lineId) => {
      const line = getLine(period, lineId);
      if (!line) return [];
      const isTraining = lineId === "training";
      return [{
        id: lineId,
        field: isTraining ? "training_orders" : "abroad_orders",
        label: cleanString(line.label) || (isTraining ? "语培" : "留学"),
        color: LINE_COLORS[lineId],
      }];
    });

    if (period.status === "future") {
      ui.trendLegend.innerHTML = series.map((item) => `<span class="legend-item"><i class="legend-line" style="--legend-color:${item.color}" aria-hidden="true"></i>${escapeHTML(item.label)}</span>`).join("");
      ui.dailyChart.innerHTML = `<div class="empty-chart">该期间尚未开始</div>`;
      return;
    }

    series = series.filter((item) => daily.some((day) => isNumber(day[item.field])));
    ui.trendLegend.innerHTML = series.map((item) => `<span class="legend-item"><i class="legend-line" style="--legend-color:${item.color}" aria-hidden="true"></i>${escapeHTML(item.label)}</span>`).join("");
    const points = series.flatMap((item) => daily.map((day) => day[item.field]).filter(isNumber));
    if (!daily.length || !points.length) {
      ui.dailyChart.innerHTML = `<div class="empty-chart">当前期间暂无可展示的趋势数据</div>`;
      return;
    }

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 720 230");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.setAttribute("class", "daily-svg");
    svg.setAttribute("role", "img");
    const lineNames = series.map((item) => item.label).join("、");
    svg.setAttribute("aria-label", `每日新增工单趋势，${lineNames}分别展示`);
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `每日新增工单趋势 · ${period.label || period.id}`;
    svg.appendChild(title);

    const chart = { left: 43, right: 704, top: 12, bottom: 196 };
    const maxValue = Math.max(0, ...points);
    const axis = niceAxis(maxValue);
    for (let tick = 0; tick <= 4; tick += 1) {
      const value = axis.step * tick;
      const y = chart.bottom - (value / axis.max) * (chart.bottom - chart.top);
      drawLineElement(svg, chart.left, y, chart.right, y, "chart-gridline");
      drawTextElement(svg, chart.left - 8, y + 3, numberText(value), "chart-axis-label", "end");
    }

    const xAt = (index) => daily.length <= 1
      ? (chart.left + chart.right) / 2
      : chart.left + (index / (daily.length - 1)) * (chart.right - chart.left);
    const yAt = (value) => chart.bottom - (value / axis.max) * (chart.bottom - chart.top);
    const labelIndexes = [...new Set([0, Math.floor((daily.length - 1) / 2), daily.length - 1])];
    labelIndexes.forEach((index) => drawTextElement(svg, xAt(index), 218, formatDateShort(daily[index].date), "chart-axis-label", index === 0 ? "start" : index === daily.length - 1 ? "end" : "middle"));

    series.forEach((item) => {
      let pathData = "";
      let drawing = false;
      let lastPoint = null;
      daily.forEach((day, index) => {
        const value = day[item.field];
        if (!isNumber(value)) {
          drawing = false;
          return;
        }
        const x = xAt(index);
        const y = yAt(value);
        pathData += `${drawing ? " L" : " M"}${x.toFixed(2)} ${y.toFixed(2)}`;
        drawing = true;
        lastPoint = { x, y };
      });
      if (pathData) {
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", pathData.trim());
        path.setAttribute("class", "chart-series");
        path.setAttribute("style", `--series-color:${item.color}`);
        svg.appendChild(path);
      }
      if (lastPoint) {
        const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        dot.setAttribute("cx", String(lastPoint.x));
        dot.setAttribute("cy", String(lastPoint.y));
        dot.setAttribute("r", "3.4");
        dot.setAttribute("class", "chart-dot");
        dot.setAttribute("style", `--series-color:${item.color}`);
        svg.appendChild(dot);
      }
    });

    ui.dailyChart.replaceChildren(svg);
  }

  function numericForSort(value) {
    if (value && typeof value === "object") value = actualValue(value);
    return isNumber(value) ? value : Number.NEGATIVE_INFINITY;
  }

  function channelCashText(row, line) {
    const rowMetric = row.cash && typeof row.cash === "object" ? row.cash : null;
    const metric = rowMetric || (line && line.cash);
    const status = metric && metric.status;
    if (status === "not_covered") return "该期间未覆盖";
    if (status === "not_connected") return "未接入";
    if (status === "not_configured") return "归属待确认";
    if (status === "future") return "尚未开始";
    if (status === "separate_counts") return cleanString(metric.display) || "—";
    if ((status === "available" || status === "partial") && cleanString(metric.display)) return cleanString(metric.display);
    if (row.cash === null || row.cash === undefined) {
      if (line && line.cash && line.cash.status === "not_connected") return "待接入";
      return "—";
    }
    return valueWithUnit(actualValue(row.cash), metricUnit(metric, "元"));
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

  function channelGroups(period) {
    return visibleChannelLineIds().map((lineId) => {
      const sorted = channelRows(period, lineId);
      return {
        lineId,
        line: sorted.line,
        title: cleanString(sorted.line && sorted.line.label) || (lineId === "training" ? "语培" : "留学"),
        styleClass: LINE_CLASSES[lineId],
        channels: sorted.channels,
        sourceCount: sorted.sourceCount,
      };
    });
  }

  function renderChannels(period) {
    if (period.status === "future") {
      ui.channelCount.textContent = "尚未开始";
      ui.channelBody.innerHTML = `<tr><td colspan="7" class="table-empty">该期间尚未开始</td></tr>`;
      return;
    }
    const groups = channelGroups(period);
    if (!groups.length) {
      ui.channelCount.textContent = "0 个渠道";
      ui.channelBody.innerHTML = `<tr><td colspan="7" class="table-empty">当前筛选下没有可显示的业务线。</td></tr>`;
      return;
    }
    const totalCount = groups.reduce((total, group) => total + group.channels.length, 0);
    const hasSourceChannels = groups.some((group) => group.sourceCount > 0);
    ui.channelCount.textContent = `${totalCount} 个渠道`;
    const noRowsMessage = state.channelQuery && hasSourceChannels ? "没有匹配的渠道。" : "当前期间暂无渠道结果。";
    ui.channelBody.innerHTML = groups.map(({ lineId, line, title, styleClass, channels, sourceCount }) => {
      const lineLabel = lineId === "training" ? cleanString(line && line.label) || "语培" : "留学";
      const rowMarkup = channels.length ? channels.map((channel) => {
        const first = Array.isArray(channel.first_channels) ? channel.first_channels.join(" / ") : cleanString(channel.first_channels);
        const orders = metricValueText(channel.orders, "单");
        const yoy = channel.orders_yoy ?? (channel.orders && channel.orders.yoy);
        const share = channel.share;
        const today = channel.today_orders;
        const name = cleanString(channel.name) || "未命名渠道";
        return `<tr>
          <td><span class="line-chip ${LINE_TAG_CLASSES[lineId]}">${escapeHTML(lineLabel)}</span></td>
          <td><span class="channel-name">${escapeHTML(name)}</span>${first ? `<span class="channel-sub">一级渠道：${escapeHTML(first)}</span>` : ""}</td>
          <td class="numeric">${orders}</td>
          <td class="numeric">${escapeHTML(percentText(yoy))}</td>
          <td class="numeric">${escapeHTML(percentText(share))}</td>
          <td class="numeric">${today === null || today === undefined ? "—" : `${numberText(today)} 单`}</td>
          <td class="numeric">${escapeHTML(channelCashText(channel, line))}</td>
        </tr>`;
      }).join("") : `<tr><td colspan="7" class="table-empty group-empty">${escapeHTML(state.channelQuery && sourceCount ? "没有匹配的渠道。" : "当前期间暂无渠道结果。")}</td></tr>`;
      return `<tr class="channel-group-row ${escapeHTML(styleClass || LINE_CLASSES[lineId])}"><th scope="rowgroup" colspan="7"><span>${escapeHTML(title || lineLabel)}</span><span class="channel-group-count">${channels.length} 个渠道</span></th></tr>${rowMarkup}`;
    }).join("");
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
      ui.groupBody.innerHTML = `<tr><td colspan="5" class="table-empty">该期间尚未开始</td></tr>`;
      return;
    }
    if (!groups.length) {
      ui.groupBody.innerHTML = `<tr><td colspan="5" class="table-empty">当前期间暂无业务组拆解。</td></tr>`;
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
      return `<tr><td>${escapeHTML(cleanString(group.name) || "未命名业务组")}</td><td>${escapeHTML(orderText)}</td><td>${escapeHTML(targetText)}</td><td>${escapeHTML(gapText)}</td><td>${escapeHTML(cashText)}</td></tr>`;
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
