(() => {
  const data = window.CSI500_FLOW_STRATEGY;
  const $ = (id) => document.getElementById(id);
  const pct = (value, digits = 1) => value == null ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
  const num = (value, digits = 4) => value == null ? "—" : Number(value).toFixed(digits);
  const dateTime = (value) => value ? new Date(value).toLocaleString("zh-CN", {hour12:false}) : "—";
  const color = {candidate:"#6f211a", base:"#315d76", benchmark:"#d18c25", grid:"#ddd7ce", text:"#758087", band:"rgba(168,59,45,.12)"};

  if (!data) { $("header-status").textContent = "数据文件未加载"; return; }
  document.querySelector(".status-dot").classList.add(data.status === "PASS" ? "pass" : "");
  $("header-status").textContent = data.status === "PASS" ? `数据 ${data.data_as_of}` : "数据异常";
  $("validation-tag").textContent = data.validation.status === "PASS" ? "冻结结果校验通过" : "校验失败";
  $("run-time").textContent = dateTime(data.generated_at);
  $("data-date").textContent = data.data_as_of;
  $("execution-date").textContent = data.next_trade_date;
  $("action-badge").textContent = data.trade.action;
  $("next-target").textContent = pct(data.trade.next_target, 0);
  $("action-text").textContent = data.trade.action_text;
  $("trade-summary").textContent = `${data.trade.signal}；基础仓位 ${pct(data.trade.base_target,0)}，杠杆状态${data.leverage.active ? "已开启" : "未开启"}。`;
  $("current-target").textContent = pct(data.trade.current_target, 0);
  $("flow-target").textContent = pct(data.trade.next_target, 0);
  $("execute-at").textContent = `${data.next_trade_date} 开盘`;
  $("etf-weight").textContent = pct(data.trade.etf_target, 0);
  $("cash-weight").textContent = pct(data.trade.cash_target, 0);
  $("raw-signal").textContent = data.trade.signal;

  $("leverage-state").textContent = data.leverage.active ? "杠杆开启" : "常规状态";
  $("leverage-state").classList.toggle("pass", data.leverage.active);
  $("drawdown-value").textContent = pct(data.leverage.drawdown_250, 2);
  $("drawdown-gauge").style.width = `${Math.min(100, Math.max(0, Math.abs(data.leverage.drawdown_250) / .30 * 100))}%`;
  $("armed-state").textContent = data.leverage.armed ? "已解锁" : "未解锁";
  $("up-streak").textContent = `${data.leverage.current_positive_streak} / ${data.leverage.exit_positive_days} 日`;

  const c = data.performance.candidate, b = data.performance.base, bm = data.performance.benchmark;
  $("performance-period").textContent = `${data.performance.period.start} — ${data.performance.period.end}`;
  const metrics = [
    ["策略累计收益", pct(c.final_nav - 1), `原始策略 ${pct(b.final_nav - 1)}`],
    ["策略年化收益", pct(c.annual_return), `中证500 ${pct(bm.annual_return)}`],
    ["最大回撤", pct(c.max_drawdown), `原始策略 ${pct(b.max_drawdown)}`],
    ["夏普比率", num(c.sharpe, 2), `原始策略 ${num(b.sharpe,2)}`],
    ["历史杠杆事件", `${data.validation.completed_regime_events} 次`, `实际加杠杆 ${data.validation.actual_leverage_events} 次`],
  ];
  $("metric-grid").innerHTML = metrics.map(([label,value,note]) => `<div class="metric"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join("");

  $("indicator-date").textContent = data.data_as_of;
  $("mf-ratio").textContent = pct(data.indicators.mf_ratio, 3);
  $("alpha").textContent = num(data.indicators.alpha, 6);
  $("alpha-min").textContent = num(data.indicators.prior_alpha_min, 6);
  $("alpha-max").textContent = num(data.indicators.prior_alpha_max, 6);
  $("coverage").textContent = pct(data.indicators.member_coverage, 1);
  $("member-count").textContent = `${data.indicators.active_members} / ${data.indicators.expected_members} 只；权重快照 ${data.indicators.weight_snapshot_date}`;
  $("index-change").textContent = `${data.indicators.index_pct_chg >= 0 ? "+" : ""}${data.indicators.index_pct_chg.toFixed(2)}%`;
  $("index-close").textContent = `收盘 ${data.indicators.index_close.toFixed(2)}`;

  $("sample-note").textContent = data.validation.sample_note;
  $("event-score").textContent = `${data.validation.positive_actual_leverage_events} / ${data.validation.actual_leverage_events}`;
  $("events-body").innerHTML = data.events.map((event) => {
    const active = event.exit_date == null;
    const result = event.overlay_return == null ? "进行中" : (Math.abs(event.overlay_return) < 1e-10 ? "基础空仓" : event.overlay_return > 0 ? "盈利" : "亏损");
    return `<tr><td>${event.trigger_date}</td><td>${event.exit_date || "—"}</td><td>${pct(event.trigger_drawdown,1)}</td><td class="${event.overlay_return > 0 ? "positive" : "neutral"}">${event.overlay_return == null ? "—" : pct(event.overlay_return,2)}</td><td>${event.leveraged_days ?? "—"}</td><td>${active ? "进行中" : result}</td></tr>`;
  }).join("");

  const chartHover = {nav:null, drawdown:null, trigger:null};
  const chartPadding = {l:54, r:18, t:18, b:34};
  const triggerEvents = [];
  const eventLabels = new Map();
  const eventDrawdowns = new Map();
  data.events.forEach((event) => {
    triggerEvents.push({date:event.trigger_date, type:"trigger", drawdown:event.trigger_drawdown});
    eventLabels.set(event.trigger_date, "触发杠杆状态");
    eventDrawdowns.set(event.trigger_date, event.trigger_drawdown);
    if (event.exit_date) {
      triggerEvents.push({date:event.exit_date, type:"exit"});
      eventLabels.set(event.exit_date, "退出杠杆状态");
    }
  });
  const triggerDrawdown = data.series.benchmark_nav.map((value, index, values) => {
    if (index < 249 || !Number.isFinite(value)) return null;
    const rollingPeak = Math.max(...values.slice(index - 249, index + 1).filter(Number.isFinite));
    return value / rollingPeak - 1;
  });

  function chartGeometry(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const height = Number(canvas.dataset.chartHeight || canvas.getAttribute("height"));
    canvas.dataset.chartHeight = String(height);
    const width = Math.max(600, rect.width);
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    const cw = width - chartPadding.l - chartPadding.r;
    const ch = height - chartPadding.t - chartPadding.b;
    const geometry = {
      ctx, width, height, cw, ch,
      x:index => chartPadding.l + index / Math.max(1, data.series.dates.length - 1) * cw,
    };
    canvas._geometry = geometry;
    return geometry;
  }

  function drawBands(ctx, geometry) {
    let start = null;
    data.series.regime_active.forEach((active, index) => {
      if (active && start === null) start = index;
      if ((!active || index === data.series.regime_active.length - 1) && start !== null) {
        const end = active ? index : index - 1;
        ctx.fillStyle = color.band;
        ctx.fillRect(geometry.x(start), chartPadding.t, Math.max(2, geometry.x(end) - geometry.x(start)), geometry.ch);
        start = null;
      }
    });
  }

  function drawAxes(ctx, geometry, min, max, percent) {
    ctx.font = "10px Microsoft YaHei";
    ctx.lineWidth = 1;
    for (let index = 0; index <= 4; index += 1) {
      const yy = chartPadding.t + index * geometry.ch / 4;
      const value = max - index * (max - min) / 4;
      ctx.strokeStyle = color.grid;
      ctx.beginPath();
      ctx.moveTo(chartPadding.l, yy);
      ctx.lineTo(geometry.width - chartPadding.r, yy);
      ctx.stroke();
      ctx.fillStyle = color.text;
      ctx.fillText(percent ? `${(value * 100).toFixed(0)}%` : value.toFixed(1), 4, yy + 3);
    }
    const years = [];
    data.series.dates.forEach((date, index) => {
      const year = date.slice(0, 4);
      if (!years.length || years.at(-1).year !== year) years.push({year, index});
    });
    const step = Math.max(1, Math.ceil(years.length / 8));
    years.filter((_, index) => index % step === 0).forEach((tick) => {
      ctx.fillStyle = color.text;
      ctx.fillText(tick.year, geometry.x(tick.index) - 10, geometry.height - 10);
    });
  }

  function drawHover(ctx, geometry, series, index, y) {
    if (index == null) return;
    const xx = geometry.x(index);
    ctx.save();
    ctx.strokeStyle = "rgba(23,35,43,.4)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(xx, chartPadding.t);
    ctx.lineTo(xx, geometry.height - chartPadding.b);
    ctx.stroke();
    ctx.setLineDash([]);
    series.forEach((item) => {
      const value = item.values[index];
      if (!Number.isFinite(value)) return;
      ctx.fillStyle = item.color;
      ctx.strokeStyle = "#fffdf8";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(xx, y(value), 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
    ctx.restore();
  }

  function drawChart(canvas, series, options = {}, hoverIndex = null) {
    const geometry = chartGeometry(canvas);
    const {ctx} = geometry;
    const values = series.flatMap(item => item.values).filter(Number.isFinite);
    let min = options.min ?? Math.min(...values);
    let max = options.max ?? Math.max(...values);
    if (max === min) max += 1;
    const y = value => chartPadding.t + (max - value) / (max - min) * geometry.ch;
    if (options.bands) drawBands(ctx, geometry);
    drawAxes(ctx, geometry, min, max, options.percent);
    series.forEach((item) => {
      ctx.strokeStyle = item.color;
      ctx.lineWidth = item.width || 2;
      ctx.beginPath();
      let started = false;
      item.values.forEach((value, index) => {
        if (!Number.isFinite(value)) { started = false; return; }
        const xx = geometry.x(index), yy = y(value);
        if (!started) { ctx.moveTo(xx, yy); started = true; }
        else ctx.lineTo(xx, yy);
      });
      ctx.stroke();
    });
    drawHover(ctx, geometry, series, hoverIndex, y);
  }

  function drawTriggerChart(hoverIndex = null) {
    const canvas = $("trigger-chart");
    const geometry = chartGeometry(canvas);
    const {ctx} = geometry;
    const finite = triggerDrawdown.filter(Number.isFinite);
    const min = Math.min(-0.30, ...finite);
    const max = 0;
    const y = value => chartPadding.t + (max - value) / (max - min) * geometry.ch;
    drawBands(ctx, geometry);
    drawAxes(ctx, geometry, min, max, true);
    [[-0.15, color.candidate], [-0.05, "#1f6b54"]].forEach(([value, lineColor]) => {
      ctx.save();
      ctx.strokeStyle = lineColor;
      ctx.lineWidth = 1.3;
      ctx.setLineDash([6, 5]);
      ctx.beginPath();
      ctx.moveTo(chartPadding.l, y(value));
      ctx.lineTo(geometry.width - chartPadding.r, y(value));
      ctx.stroke();
      ctx.restore();
    });
    const series = [{values:triggerDrawdown, color:color.base, width:2}];
    ctx.strokeStyle = color.base;
    ctx.lineWidth = 2;
    ctx.beginPath();
    let started = false;
    triggerDrawdown.forEach((value, index) => {
      if (!Number.isFinite(value)) { started = false; return; }
      const xx = geometry.x(index), yy = y(value);
      if (!started) { ctx.moveTo(xx, yy); started = true; }
      else ctx.lineTo(xx, yy);
    });
    ctx.stroke();
    triggerEvents.forEach((event) => {
      const index = data.series.dates.indexOf(event.date);
      const value = Number.isFinite(triggerDrawdown[index]) ? triggerDrawdown[index] : event.drawdown;
      if (index < 0 || !Number.isFinite(value)) return;
      ctx.fillStyle = event.type === "trigger" ? color.candidate : "#1f6b54";
      ctx.strokeStyle = "#fffdf8";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(geometry.x(index), y(value), 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
    drawHover(ctx, geometry, series, hoverIndex, y);
  }

  function pointerIndex(canvas, event) {
    const rect = canvas.getBoundingClientRect();
    const geometry = canvas._geometry;
    const logicalX = (event.clientX - rect.left) / rect.width * geometry.width;
    return Math.max(0, Math.min(data.series.dates.length - 1, Math.round((logicalX - chartPadding.l) / geometry.cw * (data.series.dates.length - 1))));
  }

  function showTooltip(canvas, tooltip, event, html) {
    const rect = canvas.getBoundingClientRect();
    const localX = event.clientX - rect.left;
    const localY = event.clientY - rect.top;
    tooltip.innerHTML = html;
    tooltip.hidden = false;
    tooltip.style.left = `${canvas.offsetLeft + localX}px`;
    tooltip.style.top = `${canvas.offsetTop + localY}px`;
    tooltip.style.transform = localX > rect.width - 230 ? "translate(calc(-100% - 12px),-50%)" : "translate(12px,-50%)";
  }

  function bindHover(canvas, tooltip, key, rowsForIndex) {
    canvas.addEventListener("pointermove", (event) => {
      const index = pointerIndex(canvas, event);
      chartHover[key] = index;
      renderCharts();
      const rows = rowsForIndex(index);
      const eventLabel = eventLabels.get(data.series.dates[index]);
      showTooltip(canvas, tooltip, event, `<strong>${data.series.dates[index]}</strong>${rows.map(([label, value]) => `<div class="tooltip-row"><span>${label}</span><b>${value}</b></div>`).join("")}${eventLabel ? `<div class="tooltip-event">${eventLabel}</div>` : ""}`);
    });
    canvas.addEventListener("pointerleave", () => {
      chartHover[key] = null;
      tooltip.hidden = true;
      renderCharts();
    });
  }

  function renderCharts() {
    drawChart($("nav-chart"), [
      {values:data.series.candidate_nav, color:color.candidate, width:2.5},
      {values:data.series.base_nav, color:color.base, width:1.6},
      {values:data.series.benchmark_nav, color:color.benchmark, width:1.4},
    ], {bands:true, min:0}, chartHover.nav);
    drawChart($("drawdown-chart"), [
      {values:data.series.candidate_drawdown, color:color.candidate, width:2.2},
      {values:data.series.base_drawdown, color:color.base, width:1.5},
    ], {bands:true, percent:true, max:0}, chartHover.drawdown);
    drawTriggerChart(chartHover.trigger);
  }

  renderCharts();
  bindHover($("nav-chart"), $("nav-tooltip"), "nav", index => [
    ["200%策略净值", num(data.series.candidate_nav[index], 2)],
    ["100%策略净值", num(data.series.base_nav[index], 2)],
    ["中证500净值", num(data.series.benchmark_nav[index], 2)],
    ["杠杆状态", data.series.regime_active[index] ? "已开启" : "未开启"],
  ]);
  bindHover($("drawdown-chart"), $("drawdown-tooltip"), "drawdown", index => [
    ["200%策略回撤", pct(data.series.candidate_drawdown[index], 2)],
    ["100%策略回撤", pct(data.series.base_drawdown[index], 2)],
    ["杠杆状态", data.series.regime_active[index] ? "已开启" : "未开启"],
  ]);
  bindHover($("trigger-chart"), $("trigger-tooltip"), "trigger", index => [
    ["250日高点回撤", pct(Number.isFinite(triggerDrawdown[index]) ? triggerDrawdown[index] : eventDrawdowns.get(data.series.dates[index]), 2)],
    ["杠杆状态", data.series.regime_active[index] ? "已开启" : "未开启"],
  ]);
  window.addEventListener("resize", renderCharts);
})();
