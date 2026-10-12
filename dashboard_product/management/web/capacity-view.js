"use strict";

window.CapacityView = (() => {
  const LINE_LABELS = { training: "语培", abroad: "留学" };
  const METRIC_LABELS = { orders: "工单", cash: "现金" };
  const SCOPE_LABELS = { all: "合计（留学＋小语种）", study_abroad: "留学", small_language: "小语种" };
  const PENDING_SOURCES = new Set(["留学资源", "语培工单", "语培现金", "留学签约", "小语种签约"]);
  const numberFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
  const percentFormat = new Intl.NumberFormat("zh-CN", {
    style: "percent",
    maximumFractionDigits: 1,
  });

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }

  function clean(value) {
    return typeof value === "string" ? value.trim() : "";
  }

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function count(value) {
    return isNumber(value) ? Math.max(0, Math.trunc(value)) : 0;
  }

  function formatNumber(value, missing = "未接入") {
    return isNumber(value) ? numberFormat.format(value) : missing;
  }

  function formatRate(value, missing = "未接入") {
    return isNumber(value) ? percentFormat.format(value) : missing;
  }

  function orderStatusSwitch(bit, label, mode) {
    const checked = mode[bit] === "1" ? " checked" : "";
    return `<label class="order-status-control"><input class="order-status-bit-toggle" type="checkbox" role="switch" data-status-bit="${bit}" aria-label="包含${label}工单"${checked}><span class="order-status-track" aria-hidden="true"></span><span>包含${label}</span></label>`;
  }

  function periods(capacity) {
    return Array.isArray(capacity?.periods)
      ? capacity.periods
        .filter((period) => /^\d{4}-\d{2}$/.test(String(period?.id ?? "")))
        .slice()
        .sort((left, right) => String(left.id).localeCompare(String(right.id)))
      : [];
  }

  function period(capacity, monthId) {
    return periods(capacity).find((item) => String(item.id) === String(monthId)) || null;
  }

  function defaultMonth(capacity) {
    const available = periods(capacity);
    if (!available.length) return "";
    const connected = available.filter((item) => item?.coverage?.abroad?.connected === true);
    return String((connected.at(-1) || available.at(-1)).id);
  }

  function personRows(selectedPeriod) {
    // The contribution schema is scoped to offline personnel by its producer.
    return Array.isArray(selectedPeriod?.people) ? selectedPeriod.people : [];
  }

  function groupLabel(peerGroup, person) {
    const parts = String(peerGroup || "").split("|").map((part) => part.trim()).filter(Boolean);
    const lineToken = parts.find((part) => Object.prototype.hasOwnProperty.call(LINE_LABELS, part));
    const line = LINE_LABELS[lineToken] || LINE_LABELS[person?.business_line] || "";
    const group = clean(person?.home_group) || parts.find((part) => part !== lineToken) || "未分组";
    return [line, group].filter(Boolean).join(" · ") || String(peerGroup || "未分组");
  }

  function groups(capacity, monthId) {
    const selectedPeriod = period(capacity, monthId);
    const unique = new Map();
    for (const person of personRows(selectedPeriod)) {
      const id = clean(person?.peer_group) || "unassigned";
      if (!unique.has(id)) unique.set(id, groupLabel(id, person));
    }
    return [...unique].map(([id, label]) => ({ id, label }));
  }

  function monthLabel(item) {
    if (clean(item?.label)) return clean(item.label);
    const [year, month] = String(item?.id || "").split("-");
    return year && month ? `${year}年${Number(month)}月` : "未选择月份";
  }

  function targetTitle(metric, target) {
    const label = METRIC_LABELS[metric];
    if (!isNumber(target)) return `${label}目标：未配置`;
    const unit = metric === "cash" ? " 元" : " 单";
    return `${label}目标：${numberFormat.format(target)}${unit}`;
  }

  function amountCell(value, metric, group, missing = "未接入") {
    const unit = metric === "cash" ? "元" : "单";
    const label = isNumber(value) ? `${formatNumber(value)}${unit}` : missing;
    return `<td class="capacity-value ${group} ${metric}" aria-label="${escapeHTML(label)}">${escapeHTML(formatNumber(value, missing))}</td>`;
  }

  function rateCell(value, metric, group, { target, actual, missing = "未接入" } = {}) {
    const hasTarget = target !== undefined;
    const title = hasTarget ? ` title="${escapeHTML(targetTitle(metric, target))}"` : "";
    const focusable = hasTarget ? ' tabindex="0"' : "";
    let shown = formatRate(value, missing);
    if (actual === 0 && !isNumber(value) && !hasTarget) shown = "—";
    if (hasTarget) {
      if (!isNumber(actual)) shown = missing;
      else if (!isNumber(target)) shown = "未配置";
      else if (target === 0) shown = "—";
    }
    return `<td class="capacity-rate ${group} ${metric}"${title}${focusable}>${escapeHTML(shown)}</td>`;
  }

  function withOrderStatus(person, view) {
    const selected = { ...person };
    for (const bucket of ["self", "received", "own_total", "output", "created_total"]) {
      selected[bucket] = { ...person[bucket], orders: view[bucket].orders };
    }
    for (const bucket of ["self_rate", "completion"]) {
      selected[bucket] = { ...person[bucket], orders: view[bucket].orders };
    }
    return selected;
  }

  function renderPerson(person, coverage) {
    const self = person?.self || {};
    const selfRate = person?.self_rate || {};
    const completion = person?.completion || {};
    const targets = person?.targets || {};
    const received = person?.received || {};
    const ownTotal = person?.own_total || {};
    const output = person?.output || {};
    const createdTotal = person?.created_total || {};
    const pendingCount = count(person?.pending_count);
    const history = person?.source_kind === "confirmed_history";
    const own = person.business_line === "training" ? "training" : "abroad";
    const other = own === "training" ? "abroad" : "training";
    const missingFor = line => history ? "未提供" : (!coverage?.[line]?.orders_through || !coverage?.[line]?.cash_through) ? "未覆盖" : "未提供";
    const missing = missingFor(own);
    const outputMissing = missingFor(other);
    const createdMissing = missing === "未覆盖" || outputMissing === "未覆盖" ? "未覆盖" : missing;

    return `<tr>
      <th scope="row" class="capacity-person"><span>${escapeHTML(clean(person?.name) || "未命名")}</span>${pendingCount ? `<small class="capacity-pending-count">待核 ${numberFormat.format(pendingCount)} 条</small>` : ""}</th>
      ${amountCell(self.orders, "orders", "group-self", missing)}
      ${amountCell(self.cash, "cash", "group-self", missing)}
      ${rateCell(selfRate.orders, "orders", "group-self-rate", { actual: ownTotal.orders, missing })}
      ${rateCell(selfRate.cash, "cash", "group-self-rate", { actual: ownTotal.cash, missing })}
      ${amountCell(targets.orders, "orders", "group-targets", "未配置")}
      ${amountCell(targets.cash, "cash", "group-targets", "未配置")}
      ${rateCell(completion.orders, "orders", "group-completion", { target: targets.orders, actual: ownTotal.orders, missing })}
      ${rateCell(completion.cash, "cash", "group-completion", { target: targets.cash, actual: ownTotal.cash, missing })}
      ${amountCell(received.orders, "orders", "group-received", missing)}
      ${amountCell(received.cash, "cash", "group-received", missing)}
      ${amountCell(ownTotal.orders, "orders", "group-own-total", missing)}
      ${amountCell(ownTotal.cash, "cash", "group-own-total", missing)}
      ${amountCell(output.orders, "orders", "group-output", outputMissing)}
      ${amountCell(output.cash, "cash", "group-output", outputMissing)}
      ${amountCell(createdTotal.orders, "orders", "group-created-total", createdMissing)}
      ${amountCell(createdTotal.cash, "cash", "group-created-total", createdMissing)}
    </tr>`;
  }

  function render(container, capacity, monthId, selectedGroup = "all", productScope = "all", orderStatusMode = "01") {
    const selectedPeriod = period(capacity, monthId);
    if (!selectedPeriod) {
      container.innerHTML = '<div class="capacity-empty">当前没有可展示的人员贡献月份。</div>';
      return;
    }

    const selectedPeople = personRows(selectedPeriod).filter((person) =>
      selectedGroup === "all" || (clean(person?.peer_group) || "unassigned") === selectedGroup,
    );
    const scope = Object.prototype.hasOwnProperty.call(SCOPE_LABELS, productScope) ? productScope : "all";
    const rows = selectedPeople.map((person) => {
      const view = person.order_status_views[orderStatusMode];
      const selectedPerson = withOrderStatus(person, view);
      if (scope === "all") return renderPerson(selectedPerson, selectedPeriod.coverage);
      const selectedBreakdown = withOrderStatus(person.breakdowns[scope], view.breakdowns[scope]);
      return renderPerson({ ...selectedPerson, ...selectedBreakdown }, selectedPeriod.coverage);
    }).join("");
    const emptyRow = '<tr><td class="capacity-no-people" colspan="17">当前团队没有人员记录。</td></tr>';
    const totalPendingCount = count(selectedPeriod.pending_count);
    const selectedNames = new Set(selectedPeople.map((person) => clean(person?.name)).filter(Boolean));
    const pendingRows = Array.isArray(selectedPeriod.pending)
      ? selectedPeriod.pending.filter((item) => selectedNames.has(clean(item?.name)))
      : [];
    const pendingNotice = totalPendingCount
      ? `<p class="capacity-pending-notice" role="status"><span>贡献汇总暂不含 ${numberFormat.format(totalPendingCount)} 条待核记录</span><small>此数为全月去重数；下方明细按当前人员团队筛选，同一事件可能涉及多人。</small></p>`
      : "";
    const pendingDetailRows = pendingRows.map((item) => {
      const source = clean(item?.source);
      const safeSource = PENDING_SOURCES.has(source) ? source : "其他来源";
      return `<tr>
        <th scope="row">${escapeHTML(clean(item?.name) || "未提供")}</th>
        <td>${escapeHTML(safeSource)}</td>
        <td>${escapeHTML(clean(item?.reason) || "归属待核")}</td>
        <td class="capacity-pending-count-cell">${isNumber(item?.count) ? numberFormat.format(count(item.count)) : "未接入"}</td>
      </tr>`;
    }).join("");
    const pendingDisclosure = totalPendingCount
      ? `<details class="capacity-pending-details">
          <summary>展开待核明细 · 当前团队展示 ${pendingRows.length} 行</summary>
          <p>明细按人员列出，同一待核事件可能涉及多人，数量不能相加替代全月去重总数。</p>
          <div class="capacity-pending-scroll" role="region" tabindex="0" aria-label="待核人员贡献明细，可横向滚动">
            <table class="capacity-pending-table">
              <thead><tr><th scope="col">姓名</th><th scope="col">来源</th><th scope="col">原因</th><th scope="col">待核记录数</th></tr></thead>
              <tbody>${pendingDetailRows || '<tr><td colspan="4" class="capacity-pending-empty">当前人员团队暂无待核记录。</td></tr>'}</tbody>
            </table>
          </div>
        </details>`
      : "";
    container.innerHTML = `
      <section class="capacity-ledger" aria-labelledby="capacity-ledger-title">
        <div class="capacity-ledger-heading">
          <h2 id="capacity-ledger-title">人员贡献</h2>
          <div class="capacity-heading-controls">${orderStatusSwitch(0, "删除／回收", orderStatusMode)}${orderStatusSwitch(1, "死单", orderStatusMode)}<span>${selectedPeople.length} 人 · ${selectedPeriod?.coverage?.history ? "含历史月度结果" : "自然月"}</span></div>
        </div>

        ${pendingNotice}
        <div class="capacity-table-scroll" role="region" tabindex="0" aria-label="人员贡献表格，可用键盘方向键或滚动条横向查看">
          <table class="capacity-table">
            <caption class="capacity-visually-hidden">${escapeHTML(monthLabel(selectedPeriod))}人员贡献明细</caption>
            <thead>
              <tr class="capacity-groups">
                <th scope="col" rowspan="2" class="capacity-name-head">姓名</th>
                <th scope="colgroup" colspan="2" class="group-self">自主创造 <small>本业务</small></th>
                <th scope="colgroup" colspan="2" class="group-self-rate">自创率</th>
                <th scope="colgroup" colspan="2" class="group-targets">本业务目标</th><th scope="colgroup" colspan="2" class="group-completion">本业务完成率</th>
                <th scope="colgroup" colspan="2" class="group-received">额外接收 <small>本业务</small></th>
                <th scope="colgroup" colspan="2" class="group-own-total">本业务合计</th>
                <th scope="colgroup" colspan="2" class="group-output">额外输出 <small>对方业务</small></th>
                <th scope="colgroup" colspan="2" class="group-created-total">自创合计 <small>本＋对方</small></th>
              </tr>
              <tr class="capacity-metrics">
                ${Array.from({ length: 8 }, (_, index) => '<th scope="col">工单</th><th scope="col">' + (index === 1 || index === 3 ? '现金' : '现金（元）') + '</th>').join("")}
              </tr>
            </thead>
            <tbody>${rows || emptyRow}</tbody>
          </table>
        </div>
        ${pendingDisclosure}
      </section>`;
  }

  return { periods, period, defaultMonth, groups, monthLabel, render };
})();
