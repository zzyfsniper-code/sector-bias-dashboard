(() => {
  const data = window.CSI500_FLOW_STRATEGY;
  const $ = (id) => document.getElementById(id);
  const pct = (value, digits = 1) => value == null ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
  const num = (value, digits = 4) => value == null ? "—" : Number(value).toFixed(digits);
  const dateTime = (value) => value ? new Date(value).toLocaleString("zh-CN", {hour12:false}) : "—";
  const color = {candidate:"#7b211b", base:"#315d76", benchmark:"#d18c25", rise:"#b8322a", fall:"#17805a", grid:"#ddd7ce", text:"#758087", band:"rgba(23,128,90,.11)"};

  if (!data) { $("header-status").textContent = "数据文件未加载"; return; }
  document.querySelector(".status-dot").classList.add(data.status === "PASS" ? "pass" : "");
  $("header-status").textContent = data.status === "PASS" ? `数据 ${data.data_as_of}` : "数据异常";
  $("validation-tag").textContent = data.validation.status === "PASS" ? "冻结结果校验通过" : "校验失败";
  $("run-time").textContent = dateTime(data.generated_at);
  $("data-date").textContent = data.data_as_of;
  $("execution-date").textContent = data.next_trade_date;
  $("action-badge").textContent = data.trade.action;
  $("action-badge").classList.add(data.trade.action === "BUY" ? "action-buy" : data.trade.action === "SELL" ? "action-sell" : "action-hold");
  $("next-target").textContent = pct(data.trade.next_target, 0);
  $("action-text").textContent = data.trade.action_text;
  $("trade-summary").textContent = `${data.trade.signal}；基础仓位 ${pct(data.trade.base_target,0)}，杠杆状态${data.leverage.active ? "已开启" : "未开启"}。`;
  $("current-target").textContent = pct(data.trade.current_target, 0);
  $("flow-target").textContent = pct(data.trade.next_target, 0);
  $("execute-at").textContent = `${data.next_trade_date} 开盘`;
  $("etf-weight").textContent = pct(data.trade.etf_target, 0);
  $("cash-weight").textContent = pct(data.trade.cash_target, 0);
  $("raw-signal").textContent = data.trade.signal;
  const rawSignalTone = data.trade.signal.includes("做多") ? "positive" : data.trade.signal.includes("退出") ? "negative" : null;
  if (rawSignalTone) $("raw-signal").classList.add(rawSignalTone);

  $("leverage-state").textContent = data.leverage.active ? "杠杆开启" : "常规状态";
  $("leverage-state").classList.toggle("market-long", data.leverage.active);
  $("drawdown-value").textContent = pct(data.leverage.drawdown_250, 2);
  $("drawdown-gauge").style.width = `${Math.min(100, Math.max(0, Math.abs(data.leverage.drawdown_250) / .30 * 100))}%`;
  $("armed-state").textContent = data.leverage.armed ? "已解锁" : "未解锁";
  $("up-streak").textContent = `${data.leverage.current_positive_streak} / ${data.leverage.exit_positive_days} 日`;

  const c = data.performance.candidate, b = data.performance.base, bm = data.performance.benchmark;
  $("performance-period").textContent = `${data.performance.period.start} — ${data.performance.period.end}`;
  const metrics = [
    ["策略累计收益", pct(c.final_nav - 1), `原始策略 ${pct(b.final_nav - 1)}`, c.final_nav >= 1 ? "positive" : "negative"],
    ["策略年化收益", pct(c.annual_return), `中证500 ${pct(bm.annual_return)}`, c.annual_return >= 0 ? "positive" : "negative"],
    ["最大回撤", pct(c.max_drawdown), `原始策略 ${pct(b.max_drawdown)}`, "negative"],
    ["夏普比率", num(c.sharpe, 2), `原始策略 ${num(b.sharpe,2)}`, c.sharpe >= 0 ? "positive" : "negative"],
    ["历史杠杆事件", `${data.validation.completed_regime_events} 次`, `实际加杠杆 ${data.validation.actual_leverage_events} 次`, ""],
  ];
  $("metric-grid").innerHTML = metrics.map(([label,value,note,tone]) => `<div class="metric"><span>${label}</span><strong class="${tone}">${value}</strong><small>${note}</small></div>`).join("");

  $("indicator-date").textContent = data.data_as_of;
  $("mf-ratio").textContent = pct(data.indicators.mf_ratio, 3);
  $("alpha").textContent = num(data.indicators.alpha, 6);
  $("alpha-min").textContent = num(data.indicators.prior_alpha_min, 6);
  $("alpha-max").textContent = num(data.indicators.prior_alpha_max, 6);
  $("coverage").textContent = pct(data.indicators.member_coverage, 1);
  $("member-count").textContent = `${data.indicators.active_members} / ${data.indicators.expected_members} 只；权重快照 ${data.indicators.weight_snapshot_date}`;
  $("index-change").textContent = `${data.indicators.index_pct_chg >= 0 ? "+" : ""}${data.indicators.index_pct_chg.toFixed(2)}%`;
  $("index-change").classList.add(data.indicators.index_pct_chg >= 0 ? "positive" : "negative");
  $("index-close").textContent = `收盘 ${data.indicators.index_close.toFixed(2)}`;

  $("sample-note").textContent = data.validation.sample_note;
  $("event-score").textContent = `${data.validation.positive_actual_leverage_events} / ${data.validation.actual_leverage_events}`;
  $("events-body").innerHTML = data.events.map((event) => {
    const active = event.exit_date == null;
    const result = event.overlay_return == null ? "进行中" : (Math.abs(event.overlay_return) < 1e-10 ? "基础空仓" : event.overlay_return > 0 ? "盈利" : "亏损");
    const returnTone = event.overlay_return > 0 ? "positive" : event.overlay_return < 0 ? "negative" : "neutral";
    return `<tr><td>${event.trigger_date}</td><td>${event.exit_date || "—"}</td><td>${pct(event.trigger_drawdown,1)}</td><td class="${returnTone}">${event.overlay_return == null ? "—" : pct(event.overlay_return,2)}</td><td>${event.leveraged_days ?? "—"}</td><td>${active ? "进行中" : result}</td></tr>`;
  }).join("");

  const reasonLabels = {
    exit_signal:"α 上沿退出",
    max_hold_exit:"最长持有期退出",
    OPEN:"持有中",
  };
  const baseTrades = data.base_trades || [];
  const completedBaseTrades = baseTrades.filter(trade => trade.status === "COMPLETED");
  const positiveBaseTrades = completedBaseTrades.filter(trade => trade.round_trip_return > 0).length;
  const averageBaseReturn = completedBaseTrades.length
    ? completedBaseTrades.reduce((sum, trade) => sum + trade.round_trip_return, 0) / completedBaseTrades.length
    : null;
  $("trade-score").innerHTML = completedBaseTrades.length
    ? `<strong>${positiveBaseTrades} / ${completedBaseTrades.length}</strong><br>胜率 ${pct(positiveBaseTrades / completedBaseTrades.length, 1)} · 平均单笔 ${pct(averageBaseReturn, 2)}`
    : "暂无已完成交易";
  $("base-trades-body").innerHTML = [...baseTrades].reverse().map((trade) => {
    const open = trade.status === "OPEN";
    const returnClass = trade.round_trip_return > 0 ? "positive" : "negative";
    const returnText = `${pct(trade.round_trip_return, 2)}${open ? '<small class="floating-tag">浮动</small>' : ""}`;
    return `<tr class="${open ? "open-trade" : ""}"><td>${trade.entry_signal_date}</td><td>${trade.entry_trade_date}</td><td>${trade.exit_signal_date || "—"}</td><td>${trade.exit_trade_date || "—"}</td><td>${trade.holding_days}</td><td class="${returnClass}">${returnText}</td><td class="${open ? "status-open" : ""}">${reasonLabels[trade.exit_reason] || trade.exit_reason}</td></tr>`;
  }).join("");

  const chartHover = {nav:null, drawdown:null, trigger:null, alpha:null};
  const chartKeys = ["nav", "drawdown", "trigger", "alpha"];
  const lastSeriesIndex = data.series.dates.length - 1;
  const chartRanges = Object.fromEntries(chartKeys.map(key => [key, {start:0, end:lastSeriesIndex}]));
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

  function chartGeometry(canvas, range) {
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
      ctx, width, height, cw, ch, start:range.start, end:range.end,
      x:index => chartPadding.l + (index - range.start) / Math.max(1, range.end - range.start) * cw,
    };
    canvas._geometry = geometry;
    return geometry;
  }

  function drawBands(ctx, geometry, range) {
    let start = null;
    for (let index = range.start; index <= range.end; index += 1) {
      const active = data.series.regime_active[index];
      if (active && start === null) start = index;
      if ((!active || index === range.end) && start !== null) {
        const end = active ? index : index - 1;
        ctx.fillStyle = color.band;
        ctx.fillRect(geometry.x(start), chartPadding.t, Math.max(2, geometry.x(end) - geometry.x(start)), geometry.ch);
        start = null;
      }
    }
  }

  function drawAxes(ctx, geometry, min, max, percent, formatter = null) {
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
      const label = formatter ? formatter(value) : percent ? `${(value * 100).toFixed(0)}%` : value.toFixed(1);
      ctx.fillText(label, 4, yy + 3);
    }
    const span = geometry.end - geometry.start;
    const tickCount = Math.min(7, span + 1);
    for (let tick = 0; tick < tickCount; tick += 1) {
      const index = geometry.start + Math.round(tick * span / Math.max(1, tickCount - 1));
      const date = data.series.dates[index];
      const label = span <= 756 ? date.slice(0, 7) : date.slice(0, 4);
      ctx.fillStyle = color.text;
      ctx.textAlign = tick === 0 ? "left" : tick === tickCount - 1 ? "right" : "center";
      ctx.fillText(label, geometry.x(index), geometry.height - 10);
    }
    ctx.textAlign = "left";
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
    const range = options.range || {start:0, end:lastSeriesIndex};
    const geometry = chartGeometry(canvas, range);
    const {ctx} = geometry;
    const values = series.flatMap(item => item.values.slice(range.start, range.end + 1)).filter(Number.isFinite);
    let min = options.min ?? Math.min(...values);
    let max = options.max ?? Math.max(...values);
    if (max === min) max += 1;
    if (options.yPadding) {
      const padding = (max - min) * options.yPadding;
      min -= padding;
      max += padding;
    }
    const y = value => chartPadding.t + (max - value) / (max - min) * geometry.ch;
    if (options.bands) drawBands(ctx, geometry, range);
    drawAxes(ctx, geometry, min, max, options.percent, options.axisFormatter);
    series.forEach((item) => {
      ctx.strokeStyle = item.color;
      ctx.lineWidth = item.width || 2;
      ctx.setLineDash(item.dash || []);
      ctx.beginPath();
      let started = false;
      for (let index = range.start; index <= range.end; index += 1) {
        const value = item.values[index];
        if (!Number.isFinite(value)) { started = false; continue; }
        const xx = geometry.x(index), yy = y(value);
        if (!started) { ctx.moveTo(xx, yy); started = true; }
        else ctx.lineTo(xx, yy);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    });
    drawHover(ctx, geometry, series, hoverIndex, y);
    return {geometry, y, series};
  }

  function drawTriggerChart(hoverIndex = null) {
    const canvas = $("trigger-chart");
    const range = chartRanges.trigger;
    const geometry = chartGeometry(canvas, range);
    const {ctx} = geometry;
    const finite = triggerDrawdown.slice(range.start, range.end + 1).filter(Number.isFinite);
    const min = Math.min(-0.18, ...finite);
    const max = 0;
    const y = value => chartPadding.t + (max - value) / (max - min) * geometry.ch;
    drawBands(ctx, geometry, range);
    drawAxes(ctx, geometry, min, max, true);
    [[-0.15, color.fall], [-0.05, color.rise]].forEach(([value, lineColor]) => {
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
    const series = [{values:triggerDrawdown, color:color.fall, width:2}];
    ctx.strokeStyle = color.fall;
    ctx.lineWidth = 2;
    ctx.beginPath();
    let started = false;
    for (let index = range.start; index <= range.end; index += 1) {
      const value = triggerDrawdown[index];
      if (!Number.isFinite(value)) { started = false; continue; }
      const xx = geometry.x(index), yy = y(value);
      if (!started) { ctx.moveTo(xx, yy); started = true; }
      else ctx.lineTo(xx, yy);
    }
    ctx.stroke();
    triggerEvents.forEach((event) => {
      const index = data.series.dates.indexOf(event.date);
      const value = Number.isFinite(triggerDrawdown[index]) ? triggerDrawdown[index] : event.drawdown;
      if (index < range.start || index > range.end || !Number.isFinite(value)) return;
      ctx.fillStyle = event.type === "trigger" ? color.fall : color.rise;
      ctx.strokeStyle = "#fffdf8";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(geometry.x(index), y(value), 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
    drawHover(ctx, geometry, series, hoverIndex, y);
  }

  function alphaSignalLabel(index) {
    if (data.series.raw_signal[index] === 1) return "做多触发";
    if (data.series.raw_signal[index] === -1) return "退出触发";
    if (data.series.signal_reason[index] === "max_hold_exit") return "到期退出";
    return data.series.base_target[index] ? "持有中" : "空仓";
  }

  function drawAlphaMarker(ctx, x, y, type) {
    ctx.save();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#fffdf8";
    ctx.fillStyle = type === "long" ? color.rise : type === "exit" ? color.fall : color.benchmark;
    ctx.beginPath();
    if (type === "long") {
      ctx.moveTo(x, y - 6); ctx.lineTo(x - 5, y + 4); ctx.lineTo(x + 5, y + 4); ctx.closePath();
    } else if (type === "exit") {
      ctx.moveTo(x, y + 6); ctx.lineTo(x - 5, y - 4); ctx.lineTo(x + 5, y - 4); ctx.closePath();
    } else {
      ctx.rect(x - 4, y - 4, 8, 8);
    }
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  function drawAlphaChart(hoverIndex = null) {
    const range = chartRanges.alpha;
    const alphaSeries = [
      {values:data.series.alpha, color:color.candidate, width:2.2},
      {values:data.series.prior_alpha_min, color:color.fall, width:1.2, dash:[5, 4]},
      {values:data.series.prior_alpha_max, color:color.rise, width:1.2, dash:[5, 4]},
    ];
    const finite = alphaSeries.flatMap(item => item.values.slice(range.start, range.end + 1)).filter(Number.isFinite);
    const rawMin = Math.min(...finite), rawMax = Math.max(...finite);
    const padding = Math.max(0.002, (rawMax - rawMin) * 0.08);
    const chart = drawChart(
      $("alpha-chart"),
      alphaSeries,
      {min:rawMin - padding, max:rawMax + padding, axisFormatter:value => value.toFixed(3), range},
      hoverIndex,
    );
    const {geometry, y} = chart;
    const {ctx} = geometry;
    if (rawMin < 0 && rawMax > 0) {
      ctx.save();
      ctx.strokeStyle = "rgba(23,35,43,.32)";
      ctx.setLineDash([3, 4]);
      ctx.beginPath();
      ctx.moveTo(chartPadding.l, y(0));
      ctx.lineTo(geometry.width - chartPadding.r, y(0));
      ctx.stroke();
      ctx.restore();
    }
    for (let index = range.start; index <= range.end; index += 1) {
      const value = data.series.alpha[index];
      if (!Number.isFinite(value)) continue;
      if (data.series.raw_signal[index] === 1) drawAlphaMarker(ctx, geometry.x(index), y(value), "long");
      else if (data.series.raw_signal[index] === -1) drawAlphaMarker(ctx, geometry.x(index), y(value), "exit");
      else if (data.series.signal_reason[index] === "max_hold_exit") drawAlphaMarker(ctx, geometry.x(index), y(value), "expiry");
    }
  }

  function pointerIndex(canvas, event) {
    const rect = canvas.getBoundingClientRect();
    const geometry = canvas._geometry;
    const logicalX = (event.clientX - rect.left) / rect.width * geometry.width;
    const index = geometry.start + Math.round((logicalX - chartPadding.l) / geometry.cw * (geometry.end - geometry.start));
    return Math.max(geometry.start, Math.min(geometry.end, index));
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

  function bindHover(canvas, tooltip, key, rowsForIndex, annotationForIndex = null) {
    canvas.addEventListener("pointermove", (event) => {
      const index = pointerIndex(canvas, event);
      chartHover[key] = index;
      renderChart(key);
      const rows = rowsForIndex(index);
      const eventLabel = annotationForIndex
        ? annotationForIndex(index)
        : eventLabels.get(data.series.dates[index]);
      showTooltip(canvas, tooltip, event, `<strong>${data.series.dates[index]}</strong>${rows.map(([label, value]) => `<div class="tooltip-row"><span>${label}</span><b>${value}</b></div>`).join("")}${eventLabel ? `<div class="tooltip-event">${eventLabel}</div>` : ""}`);
    });
    canvas.addEventListener("pointerleave", () => {
      chartHover[key] = null;
      tooltip.hidden = true;
      renderChart(key);
    });
  }

  function renderChart(key) {
    if (key === "nav") {
      drawChart($("nav-chart"), [
        {values:data.series.candidate_nav, color:color.candidate, width:2.5},
        {values:data.series.base_nav, color:color.base, width:1.6},
        {values:data.series.benchmark_nav, color:color.benchmark, width:1.4},
      ], {bands:true, yPadding:0.06, range:chartRanges.nav}, chartHover.nav);
    } else if (key === "drawdown") {
      drawChart($("drawdown-chart"), [
        {values:data.series.candidate_drawdown, color:color.fall, width:2.2},
        {values:data.series.base_drawdown, color:color.base, width:1.5},
      ], {bands:true, percent:true, max:0, range:chartRanges.drawdown}, chartHover.drawdown);
    } else if (key === "trigger") {
      drawTriggerChart(chartHover.trigger);
    } else if (key === "alpha") {
      drawAlphaChart(chartHover.alpha);
    }
  }

  function renderCharts() { chartKeys.forEach(renderChart); }

  function setupRangeControl(key) {
    const from = $(`${key}-range-from`);
    const to = $(`${key}-range-to`);
    const control = $(`${key}-range-control`);
    const startLabel = $(`${key}-range-start`);
    const endLabel = $(`${key}-range-end`);
    [from, to].forEach(input => { input.min = "0"; input.max = String(lastSeriesIndex); input.step = "1"; });
    from.value = "0";
    to.value = String(lastSeriesIndex);
    const update = (changed) => {
      let start = Number(from.value), end = Number(to.value);
      const minimumSpan = Math.min(5, lastSeriesIndex);
      if (end - start < minimumSpan) {
        if (changed === "from") start = Math.max(0, end - minimumSpan);
        else end = Math.min(lastSeriesIndex, start + minimumSpan);
      }
      from.value = String(start);
      to.value = String(end);
      chartRanges[key] = {start, end};
      startLabel.textContent = data.series.dates[start];
      endLabel.textContent = data.series.dates[end];
      control.style.setProperty("--range-start", `${start / Math.max(1, lastSeriesIndex) * 100}%`);
      control.style.setProperty("--range-end", `${end / Math.max(1, lastSeriesIndex) * 100}%`);
      chartHover[key] = null;
      $(`${key}-tooltip`).hidden = true;
      renderChart(key);
    };
    from.addEventListener("input", () => update("from"));
    to.addEventListener("input", () => update("to"));
    update("to");
  }

  chartKeys.forEach(setupRangeControl);
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
  bindHover($("alpha-chart"), $("alpha-tooltip"), "alpha", index => [
    ["回归 α", num(data.series.alpha[index], 4)],
    ["前40日下沿", num(data.series.prior_alpha_min[index], 4)],
    ["前40日上沿", num(data.series.prior_alpha_max[index], 4)],
    ["当日状态", alphaSignalLabel(index)],
    ["基础目标仓位", pct(data.series.base_target[index], 0)],
  ], () => null);
  window.addEventListener("resize", renderCharts);
})();
