"use strict";

window.CapacityRadar = (() => {
  const numberFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
  const percentFormat = new Intl.NumberFormat("zh-CN", {
    style: "percent",
    maximumFractionDigits: 1,
  });
  const relativeFormat = new Intl.NumberFormat("zh-CN", {
    style: "percent",
    maximumFractionDigits: 1,
    signDisplay: "always",
  });
  const AXIS_LABELS = {
    orders: "工单数",
    heads: "人头",
    conversion: "转化率",
    partner: "渠道校代现金",
    tmk: "TMK现金",
    campaign: "活动现金",
  };
  const TEAM_LABELS = {
    offline_market: "线下",
    online_private: "虚拟人",
    online_platform: "线上",
  };
  const states = new WeakMap();
  let nextId = 0;

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function number(value) {
    return isNumber(value) ? numberFormat.format(value) : "—";
  }

  function percent(value) {
    return isNumber(value) ? percentFormat.format(value) : "—";
  }

  function relativePercent(value) {
    return isNumber(value) ? relativeFormat.format(value) : "—";
  }

  function displayLabel(axis) {
    return AXIS_LABELS[axis?.key] || String(axis?.label || "未命名维度");
  }

  function businessLineLabel(person) {
    return person?.business_line === "abroad" ? "留学" : "语培";
  }

  function matchesGroup(person, selectedGroup) {
    if (!selectedGroup || selectedGroup === "all") return true;
    return person?.peer_group === selectedGroup
      || person?.home_group === selectedGroup
      || person?.home_team === selectedGroup;
  }

  function groupLabel(selectedGroup, people) {
    if (!selectedGroup || selectedGroup === "all") return "全部业务团队";
    const person = people.find((row) => matchesGroup(row, selectedGroup));
    if (person) {
      const team = TEAM_LABELS[person.home_team] || "团队";
      return `${businessLineLabel(person)} · ${team} · ${person.home_group || "未分组"}`;
    }
    const parts = String(selectedGroup).split("|");
    const team = TEAM_LABELS[parts[0]] || parts[0];
    return [team, parts[1]].filter(Boolean).join(" · ") || "当前团队";
  }

  function normalized(axis, field) {
    const value = axis?.[field];
    const scale = axis?.scale;
    if (!isNumber(value) || !isNumber(scale) || scale <= 0) return null;
    return Math.min(1, Math.max(0, value / scale));
  }

  function point(index, ratio, count) {
    const angle = -Math.PI / 2 + index * (Math.PI * 2 / count);
    const cx = 180;
    const cy = 124;
    const radius = 82 * ratio;
    return [cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius];
  }

  function pointList(axes, field) {
    return axes.map((axis, index) => {
      const ratio = normalized(axis, field);
      return ratio === null ? null : point(index, ratio, axes.length);
    });
  }

  function polygon(points) {
    if (!points.length || points.some((item) => item === null)) return "";
    return points.map((item) => item.map((value) => value.toFixed(2)).join(",")).join(" ");
  }

  function seriesSVG(axes, field, color) {
    const points = pointList(axes, field);
    const complete = points.length >= 3 && points.every((item) => item !== null);
    let svg = "";
    if (complete) {
      svg += `<polygon points="${polygon(points)}" fill="${color}" fill-opacity=".14" stroke="${color}" stroke-width="2"/>`;
    }
    points.forEach((item) => {
      if (item) svg += `<circle cx="${item[0].toFixed(2)}" cy="${item[1].toFixed(2)}" r="3.5" fill="${color}"/>`;
    });
    return svg;
  }

  function chartSVG(person, axes) {
    const name = escapeHTML(person?.name || "所选人员");
    const axisCount = axes.length;
    let svg = `<svg class="capacity-radar__svg" viewBox="0 0 360 255" role="img" aria-label="${name}与同组均值的六维对比">`;
    if (axisCount >= 3) {
      [0.25, 0.5, 0.75, 1].forEach((ratio) => {
        const points = axes.map((_, index) => point(index, ratio, axisCount));
        svg += `<polygon points="${polygon(points)}" fill="none" stroke="#dbe4ed"/>`;
      });
    }
    axes.forEach((axis, index) => {
      const angle = -Math.PI / 2 + index * (Math.PI * 2 / axisCount);
      const end = point(index, 1, axisCount);
      const labelPoint = point(index, 1.34, axisCount);
      const anchor = Math.abs(Math.sin(angle)) > 0.94
        ? "middle"
        : (Math.cos(angle) > 0 ? "start" : "end");
      const label = escapeHTML(displayLabel(axis));
      svg += `<line x1="180" y1="124" x2="${end[0].toFixed(2)}" y2="${end[1].toFixed(2)}" stroke="#e2e9ef"/>`;
      svg += `<text x="${labelPoint[0].toFixed(2)}" y="${(labelPoint[1] + 4).toFixed(2)}" text-anchor="${anchor}" font-size="12" fill="#344f69">${label}</text>`;
    });
    svg += seriesSVG(axes, "mean", "#98a8b7");
    svg += seriesSVG(axes, "value", "#2864ba");
    svg += "</svg>";
    return svg;
  }

  function axisValue(axis, field) {
    return axis?.key === "conversion" ? percent(axis?.[field]) : number(axis?.[field]);
  }

  function headsPartsText(parts) {
    if (!Array.isArray(parts)) return "";
    return parts.filter((part) => part && isNumber(part.actual))
      .map((part) => `${String(part.label || "客户")}${number(part.actual)}人`)
      .join(" / ");
  }

  function chartPanel(person) {
    const axes = Array.isArray(person?.radar?.axes) ? person.radar.axes : [];
    const label = escapeHTML(person?.name || "所选人员");
    const completeValue = axes.length > 0 && axes.every((axis) => isNumber(axis?.value));
    const completeMean = axes.length > 0 && axes.every((axis) => isNumber(axis?.mean));
    const chart = axes.length
      ? chartSVG(person, axes)
      : '<div class="capacity-radar__empty">六维数据暂未接入。</div>';
    const dataNote = completeValue && completeMean
      ? ""
      : '<p class="capacity-radar__note">缺少数据的维度以“—”显示，图中不补零。</p>';
    const rows = axes.map((axis) => {
      const parts = axis?.key === "heads" ? headsPartsText(Object.entries(person?.product_parts || {}).filter(([key])=>key==='study_abroad'||key==='small_language').map(([key,part])=>({label:key==='study_abroad'?'留学':'小语种',actual:part.heads}))) : "";
      return `
      <tr>
        <th scope="row">${escapeHTML(displayLabel(axis))}${parts ? `<small class="capacity-radar__parts">${escapeHTML(parts)}</small>` : ""}</th>
        <td>${escapeHTML(axisValue(axis, "value"))}</td>
        <td>${escapeHTML(axisValue(axis, "mean"))}</td>
        <td>${escapeHTML(relativePercent(axis?.relative))}</td>
      </tr>`;
    }).join("");
    const body = rows || '<tr><td class="capacity-radar__empty-row" colspan="4">六维数据暂未接入。</td></tr>';
    const peerCount = isNumber(person?.radar?.peer_count)
      ? ` · ${number(person.radar.peer_count)}人同组`
      : "";

    return `
      <div class="capacity-radar__details">
        <section class="capacity-radar__chart-card" aria-label="六维雷达图">
          <header class="capacity-radar__chart-heading">
            <h3>个人与同组基准</h3>
            <span>${label}${peerCount}</span>
          </header>
          ${chart}
          <div class="capacity-radar__legend" aria-label="图例">
            <span><i class="capacity-radar__legend-dot is-person" aria-hidden="true"></i>个人</span>
            <span><i class="capacity-radar__legend-dot is-peer" aria-hidden="true"></i>同组均值</span>
          </div>
          ${dataNote}
        </section>
        <section class="capacity-radar__table-card" aria-label="六维数值对比">
          <div class="capacity-radar__table-scroll">
            <table class="capacity-radar__values">
              <thead><tr><th scope="col">维度</th><th scope="col">个人</th><th scope="col">同组均值</th><th scope="col">相对均值</th></tr></thead>
              <tbody>${body}</tbody>
            </table>
          </div>
          <div class="capacity-radar__reference">
            <div><span>标准现金产能</span><strong>${number(person?.cash_capacity)}${isNumber(person?.cash_capacity) ? " 元" : ""}</strong></div>
            <div><span>现金进度完成</span><strong>${percent(person?.cash_progress_completion)}</strong></div>
          </div>
        </section>
      </div>`;
  }

  function draw(container, state) {
    const people = state.people;
    const selected = people.find((person) => person.name === state.selectedName) || null;
    const startDate = state.radar?.start_date || "";
    const throughDate = state.radar?.through_date || "";
    const range = startDate || throughDate
      ? `${escapeHTML(startDate || "—")} — ${escapeHTML(throughDate || "—")}`
      : "来源日期未接入";
    const groupText = escapeHTML(groupLabel(state.selectedGroup, people));
    const selectId = `${state.id}-person-select`;
    const peopleOptions = people.map((person) => {
      const name = String(person.name || "");
      const group = person.home_group ? ` · ${person.home_group}` : "";
      return `<option value="${escapeHTML(name)}"${name === state.selectedName ? " selected" : ""}>${escapeHTML(name)} · ${businessLineLabel(person)}${escapeHTML(group)}</option>`;
    }).join("");
    const peopleButtons = people.map((person) => {
      const name = String(person.name || "");
      const selectedClass = name === state.selectedName ? " is-selected" : "";
      return `<button type="button" class="capacity-radar__person-button${selectedClass}" data-capacity-radar-person="${escapeHTML(name)}" aria-pressed="${name === state.selectedName}">${escapeHTML(name)}</button>`;
    }).join("");
    const selectionControls = people.length
      ? `<div class="capacity-radar__selection">
          <label class="capacity-radar__person-picker" for="${selectId}"><span>选择人员</span>
            <select id="${selectId}" data-capacity-radar-select aria-label="选择六维图人员">${peopleOptions}</select>
          </label>
          <div class="capacity-radar__people" role="group" aria-label="点击选择人员">${peopleButtons}</div>
        </div>`
      : '<div class="capacity-radar__empty">当前团队暂无可展示的人员。</div>';
    const title = selected && selected.business_line === "abroad" ? "留学六维" : "语培六维";
    const details = selected
      ? chartPanel(selected)
      : '<div class="capacity-radar__empty">当前团队暂无可展示的六维数据。</div>';

    container.innerHTML = `
      <section class="capacity-radar-panel" aria-labelledby="${state.id}-title">
        <header class="capacity-radar__heading">
          <div><p class="capacity-radar__kicker">FY27累计</p><h2 id="${state.id}-title">${title}</h2></div>
          <div class="capacity-radar__coverage"><span>统计期间</span><strong>${range}</strong></div>
        </header>
        <div class="capacity-radar__filter-line"><span>当前团队</span><strong>${groupText}</strong></div>
        ${selectionControls}
        ${details}
      </section>`;
  }

  function ensureState(container) {
    let state = states.get(container);
    if (state) return state;
    state = { id: `capacity-radar-${++nextId}`, radar: null, people: [], selectedGroup: "all", selectedName: "" };
    states.set(container, state);
    container.addEventListener("change", (event) => {
      if (!event.target?.matches?.("[data-capacity-radar-select]")) return;
      const current = states.get(container);
      if (!current) return;
      current.selectedName = event.target.value;
      draw(container, current);
    });
    container.addEventListener("click", (event) => {
      const button = event.target?.closest?.("[data-capacity-radar-person]");
      if (!button) return;
      const current = states.get(container);
      if (!current) return;
      current.selectedName = button.dataset.capacityRadarPerson || "";
      draw(container, current);
    });
    return state;
  }

  function render(container, radar, selectedGroup = "all") {
    if (!container) return;
    const state = ensureState(container);
    state.radar = radar && typeof radar === "object" ? radar : {};
    state.selectedGroup = selectedGroup || "all";
    const sourcePeople = Array.isArray(state.radar.people) ? state.radar.people : [];
    state.people = sourcePeople.filter((person) =>
      matchesGroup(person, state.selectedGroup),
    ).slice().sort((left, right) =>
      String(left?.name || "").localeCompare(String(right?.name || ""), "zh-CN"),
    );
    if (!state.people.some((person) => person.name === state.selectedName)) {
      state.selectedName = String(state.people[0]?.name || "");
    }
    draw(container, state);
  }

  return { render };
})();
