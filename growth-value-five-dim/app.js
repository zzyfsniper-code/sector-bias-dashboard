(() => {
  "use strict";

  const data = window.STRATEGY_DATA;
  if (!data) {
    document.body.innerHTML = '<main style="padding:40px;font-family:sans-serif">策略数据未加载，请先运行 build_demo_data.py。</main>';
    return;
  }

  const state = {
    layer: data.meta.defaultLayer || "fund",
    cost: String(data.meta.defaultCostBps ?? 10),
    years: "all",
  };

  const dimensionMeta = {
    macro: { label: "动态宏观", short: "宏观", number: "01" },
    valuation: { label: "估值均值回归", short: "估值", number: "02" },
    momentum: { label: "短期动量", short: "动量", number: "03" },
    breadth: { label: "市场广度", short: "广度", number: "04" },
    crowding: { label: "风格拥挤度", short: "拥挤", number: "05" },
  };

  const SVG_NS = "http://www.w3.org/2000/svg";
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];

  function pct(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return `${(Number(value) * 100).toFixed(digits)}%`;
  }

  function signedPct(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const number = Number(value) * 100;
    return `${number > 0 ? "+" : ""}${number.toFixed(digits)}%`;
  }

  function number(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return Number(value).toFixed(digits);
  }

  function dateLabel(value, withTime = false) {
    if (!value) return "—";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    const options = { year: "numeric", month: "2-digit", day: "2-digit" };
    if (withTime) Object.assign(options, { hour: "2-digit", minute: "2-digit", hour12: false });
    return new Intl.DateTimeFormat("zh-CN", options).format(parsed).replaceAll("/", "-");
  }

  function svgElement(name, attributes = {}) {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  function setActiveControl(selector, attribute, value) {
    $$(selector).forEach((button) => {
      button.classList.toggle("active", button.dataset[attribute] === String(value));
    });
  }

  function bindControls() {
    $$("#layer-control button").forEach((button) => {
      button.addEventListener("click", () => {
        state.layer = button.dataset.layer;
        setActiveControl("#layer-control button", "layer", state.layer);
        renderPerformance();
        renderValidation();
      });
    });
    $$("#cost-control button").forEach((button) => {
      button.addEventListener("click", () => {
        state.cost = button.dataset.cost;
        setActiveControl("#cost-control button", "cost", state.cost);
        renderPerformance();
      });
    });
    $$("#range-control button").forEach((button) => {
      button.addEventListener("click", () => {
        state.years = button.dataset.years;
        setActiveControl("#range-control button", "years", state.years);
        renderCharts();
        renderSignalMatrix();
      });
    });
  }

  function renderMeta() {
    const pass = data.meta.validationStatus === "PASS";
    $("#run-time").textContent = dateLabel(data.meta.runCreatedAt, true);
    $("#signal-range").textContent = `${data.meta.signalStart} → ${data.meta.signalEnd}`;
    $("#performance-range").textContent = `截至 ${data.meta.performanceEnd}`;
    $("#header-status-text").textContent = pass ? "数据快照校验通过" : "数据快照待复核";
    $(".status-dot").classList.toggle("pass", pass);
    $("#validation-tag").textContent = pass ? "批次校验通过" : "批次待复核";
    $("#validation-tag").classList.toggle("tag-pass", pass);
    $("#validation-seal").textContent = pass ? "PASS · 批次完整" : "需要复核";
    $("#validation-seal").classList.toggle("pass", pass);
    $("#footer-run").textContent = `批次 ${data.meta.runId}`;
  }

  function renderCurrent() {
    const current = data.current;
    const plan = data.tradingPlan;
    const signalGrowth = Number(current.desiredGrowthWeight || 0);
    const signalValue = 1 - signalGrowth;
    const targetGrowth = Number(plan.targetGrowthWeight || 0);
    const targetValue = Number(plan.targetValueWeight || 0);
    const votes = Object.values(current.dimensions);
    const growthVotes = votes.filter((item) => item.signal > 0).length;
    const valueVotes = votes.filter((item) => item.signal < 0).length;
    const signalDirection = Number(current.binaryDirection) > 0 ? "成长" : Number(current.binaryDirection) < 0 ? "价值" : "中性";
    const positionText = (growth, value) => `成长 ${pct(growth, 0)} / 价值 ${pct(value, 0)}`;
    const changedHoldings = plan.holdings.filter((holding) => Math.abs(Number(holding.changeWeight || 0)) > 0.00005);
    const orderSummary = changedHoldings.length === 0
      ? `无需下单，维持${positionText(targetGrowth, targetValue)}`
      : changedHoldings.map((holding) => `${holding.action}${holding.code} ${signedPct(Number(holding.changeWeight), 2)}`).join("；");

    $("#allocation-donut").style.setProperty("--growth-share", `${targetGrowth * 100}%`);
    $("#growth-weight").textContent = pct(targetGrowth, 0);
    $("#value-weight").textContent = pct(targetValue, 0);
    $("#current-position").textContent = positionText(plan.currentGrowthWeight, plan.currentValueWeight);
    $("#current-position-date").textContent = `已执行 · 截至 ${plan.portfolioAsOf}`;
    $("#latest-signal").textContent = `${signalDirection} ${Number(current.binaryDirection) > 0 ? "+1" : Number(current.binaryDirection) < 0 ? "-1" : "0"}`;
    $("#latest-signal-detail").textContent = `${current.signalDate} · 五维总分 ${current.compositeScore > 0 ? "+" : ""}${current.compositeScore} · 平滑后${positionText(signalGrowth, signalValue)}`;
    $("#next-target").textContent = positionText(targetGrowth, targetValue);
    $("#next-target-date").textContent = `${plan.execution} · ${orderSummary}`;
    $("#effective-weight").textContent = `成长 ${pct(plan.currentGrowthWeight, 0)} / 价值 ${pct(plan.currentValueWeight, 0)}`;
    $("#target-weight").textContent = `成长 ${pct(plan.targetGrowthWeight, 0)} / 价值 ${pct(plan.targetValueWeight, 0)}`;
    $("#execution-time").textContent = plan.execution;
    $("#composite-score").textContent = `${current.compositeScore > 0 ? "+" : ""}${current.compositeScore}`;
    $("#signal-date").textContent = current.signalDate;
    $("#action-text").textContent = plan.status === "NO_TRADE"
      ? "下一交易日无需下单"
      : "下一交易日收盘执行调仓";
    $("#trade-status").textContent = plan.instruction;
    $("#trade-status").classList.toggle("hold", plan.status === "NO_TRADE");
    $("#trade-status").classList.toggle("rebalance", plan.status === "REBALANCE");
    $("#decision-summary").textContent = `${orderSummary}。当前 ${growthVotes} 个维度偏成长、${valueVotes} 个维度偏价值。`;
    $("#vote-as-of").textContent = `截至 ${current.signalDate}`;
    $("#signal-summary").textContent = `当前 ${growthVotes} : ${valueVotes}，总分 ${current.compositeScore > 0 ? "+" : ""}${current.compositeScore}`;

    $("#vote-stack").innerHTML = Object.entries(current.dimensions).map(([key, item]) => {
      const direction = item.signal > 0 ? "growth" : "value";
      const label = item.signal > 0 ? "成长" : "价值";
      return `<div class="vote-row ${direction}">
        <strong>${dimensionMeta[key].label}</strong>
        <span class="vote-bar"></span>
        <span class="vote-label">${label} ${item.signal > 0 ? "+1" : "-1"}</span>
      </div>`;
    }).join("");

    $("#freshness-list").innerHTML = plan.freshness.map((item) => `
      <div class="freshness-item ${item.carried ? "carried" : ""}">
        <strong>${dimensionMeta[item.dimension].short}</strong>
        <span>${item.dataDate} · ${item.status}</span>
      </div>`).join("");

    $("#dimension-grid").innerHTML = Object.entries(current.dimensions).map(([key, item]) => {
      const direction = item.signal > 0 ? "growth" : "value";
      const label = item.signal > 0 ? "偏成长" : "偏价值";
      return `<article class="dimension-card">
        <div class="dimension-card-head">
          <h3>${dimensionMeta[key].label}</h3>
          <span class="signal-pill ${direction}">${item.signal > 0 ? "+1" : "-1"}</span>
        </div>
        <div class="dimension-state ${direction}">${label}</div>
        <div class="dimension-meta">状态始于 ${item.lastChange} · 已持续 ${item.tradingDaysInState} 个交易日</div>
        <p class="dimension-evidence">${evidenceText(key, item.evidence)}</p>
      </article>`;
    }).join("");

    renderHoldings(plan);
  }

  function renderHoldings(plan) {
    $("#weight-rule").textContent = `${plan.weightRule}；组合信号截至 ${plan.signalAsOf}。`;
    $("#growth-current").textContent = pct(plan.currentGrowthWeight, 0);
    $("#growth-target").textContent = pct(plan.targetGrowthWeight, 0);
    $("#value-current").textContent = pct(plan.currentValueWeight, 0);
    $("#value-target").textContent = pct(plan.targetValueWeight, 0);

    $("#holdings-table").innerHTML = plan.holdings.map((holding) => {
      const style = holding.style === "growth" ? "growth" : "value";
      const styleLabel = holding.style === "growth" ? "成长" : "价值";
      const change = Number(holding.changeWeight || 0);
      const orderClass = change > 0.00005 ? "buy" : change < -0.00005 ? "sell" : "";
      const changeClass = change > 0.00005 ? "positive" : change < -0.00005 ? "negative" : "";
      return `<tr>
        <td><span class="style-badge ${style}">${styleLabel}</span></td>
        <td><span class="holding-instrument"><strong>${holding.code}</strong><span>${holding.name}</span></span></td>
        <td><span class="holding-type">${holding.type}</span></td>
        <td class="weight-cell">${pct(holding.currentWeight, 2)}</td>
        <td class="weight-cell">${pct(holding.targetWeight, 2)}</td>
        <td class="weight-cell change-cell ${changeClass}">${signedPct(change, 2)}</td>
        <td><span class="order-pill ${orderClass}">${holding.action}</span></td>
      </tr>`;
    }).join("");

    const currentTotal = plan.holdings.reduce((sum, item) => sum + Number(item.currentWeight || 0), 0);
    const targetTotal = plan.holdings.reduce((sum, item) => sum + Number(item.targetWeight || 0), 0);
    const changeTotal = plan.holdings.reduce((sum, item) => sum + Number(item.changeWeight || 0), 0);
    $("#current-total").textContent = pct(currentTotal, 2);
    $("#target-total").textContent = pct(targetTotal, 2);
    $("#change-total").textContent = signedPct(changeTotal, 2);
    $("#order-status").textContent = plan.status === "NO_TRADE" ? "模型无需下单" : "模型执行调仓";
  }

  function evidenceText(key, evidence) {
    const suffix = evidence.note || "";
    if (key === "macro") return `最近有效票 ${evidence.lastActionDate}，${evidence.activeFactors ?? 0} 个因子，原始得分 ${evidence.rawScore ?? "—"}。${suffix}`;
    if (key === "valuation") return `最新 PB 分位 ${pct(evidence.pbPercentile, 0)}，PE 分位 ${pct(evidence.pePercentile, 0)}。${suffix}`;
    if (key === "momentum") return `成交额票 ${signedVote(evidence.amountVote)}，收益票 ${signedVote(evidence.returnVote)}，原始得分 ${evidence.rawScore ?? "—"}。`;
    if (key === "breadth") return `数据至 ${evidence.diagnosticDate}，覆盖率 ${pct(evidence.coverage, 1)}，QRD / MAD 两票均偏成长。${suffix}`;
    return `成交额与换手率当前均未触发单边极端，最近有效方向继续偏成长。${suffix}`;
  }

  function signedVote(value) {
    if (value === null || value === undefined) return "—";
    return Number(value) > 0 ? "+1" : Number(value) < 0 ? "-1" : "0";
  }

  function renderPerformance() {
    const metrics = data.metrics[state.layer][state.cost];
    const layerLabel = data.curves[state.layer].label;
    $("#kpi-cagr").textContent = pct(metrics.cagr);
    $("#kpi-cagr-note").textContent = `${metrics.start} 至 ${metrics.end}`;
    $("#kpi-excess").textContent = signedPct(metrics.excess_cagr);
    $("#kpi-mdd").textContent = pct(metrics.max_drawdown);
    $("#kpi-mdd-note").textContent = `年化波动 ${pct(metrics.annual_volatility)}`;
    $("#kpi-win").textContent = pct(metrics.monthly_excess_win_rate);
    $("#kpi-win-note").textContent = `${metrics.switches} 次方向切换 · 平均 ${number(metrics.average_switch_interval_trading_days, 1)} 日`;
    $("#kpi-sharpe").textContent = number(metrics.sharpe_rf0);
    $("#curve-subtitle").textContent = `${layerLabel} · 五日平滑 · 单边 ${state.cost}bp · 对数净值轴`;
    $("#comparison-layer-label").textContent = layerLabel;
    renderCharts();
  }

  function sliceByRange(curve) {
    if (state.years === "all") return { ...curve, startIndex: 0 };
    const end = new Date(curve.dates[curve.dates.length - 1]);
    const cutoff = new Date(end);
    cutoff.setFullYear(cutoff.getFullYear() - Number(state.years));
    let startIndex = curve.dates.findIndex((date) => new Date(date) >= cutoff);
    if (startIndex < 0) startIndex = 0;
    const output = { startIndex };
    Object.entries(curve).forEach(([key, values]) => {
      output[key] = Array.isArray(values) ? values.slice(startIndex) : values;
    });
    return output;
  }

  function renderCharts() {
    const curve = sliceByRange(data.curves[state.layer].costs[state.cost]);
    renderNavChart(curve);
    renderDrawdownChart(curve);
  }

  function linePath(values, xScale, yScale) {
    let path = "";
    let started = false;
    values.forEach((value, index) => {
      if (value === null || value === undefined || !Number.isFinite(Number(value))) {
        started = false;
        return;
      }
      const command = started ? "L" : "M";
      path += `${command}${xScale(index).toFixed(2)},${yScale(Number(value)).toFixed(2)}`;
      started = true;
    });
    return path;
  }

  function navTicks(minimum, maximum) {
    const ticks = [];
    const minExp = Math.floor(Math.log10(Math.max(minimum, 0.0001)));
    const maxExp = Math.ceil(Math.log10(maximum));
    for (let exp = minExp; exp <= maxExp; exp += 1) {
      [1, 2, 5].forEach((base) => {
        const value = base * 10 ** exp;
        if (value >= minimum * 0.96 && value <= maximum * 1.04) ticks.push(value);
      });
    }
    if (ticks.length > 7) return ticks.filter((_, index) => index % 2 === 0);
    return ticks;
  }

  function addAxes(svg, options) {
    const { width, height, pad, xTicks, yTicks, xScale, yScale, xLabels, yFormatter } = options;
    yTicks.forEach((tick) => {
      const y = yScale(tick);
      svg.appendChild(svgElement("line", { x1: pad.left, x2: width - pad.right, y1: y, y2: y, class: "grid-line" }));
      const text = svgElement("text", { x: pad.left - 10, y: y + 3, "text-anchor": "end", class: "axis-text" });
      text.textContent = yFormatter(tick);
      svg.appendChild(text);
    });
    xTicks.forEach((index) => {
      const x = xScale(index);
      svg.appendChild(svgElement("line", { x1: x, x2: x, y1: pad.top, y2: height - pad.bottom, class: "grid-line" }));
      const text = svgElement("text", { x, y: height - pad.bottom + 20, "text-anchor": "middle", class: "axis-text" });
      text.textContent = xLabels[index].slice(0, 4);
      svg.appendChild(text);
    });
    svg.appendChild(svgElement("line", { x1: pad.left, x2: width - pad.right, y1: height - pad.bottom, y2: height - pad.bottom, class: "axis-line" }));
  }

  function renderNavChart(curve) {
    const svg = $("#nav-chart");
    const tooltip = $("#nav-tooltip");
    const width = 1000;
    const height = 360;
    const pad = { left: 55, right: 18, top: 18, bottom: 36 };
    const allValues = [...curve.strategy, ...curve.benchmark, ...curve.reportStrategy]
      .filter((value) => value !== null && Number(value) > 0)
      .map(Number);
    const rawMin = Math.min(...allValues);
    const rawMax = Math.max(...allValues);
    const minimum = Math.max(rawMin * 0.93, 0.05);
    const maximum = rawMax * 1.06;
    const logMin = Math.log(minimum);
    const logSpan = Math.log(maximum) - logMin || 1;
    const xScale = (index) => pad.left + (index / Math.max(curve.dates.length - 1, 1)) * (width - pad.left - pad.right);
    const yScale = (value) => height - pad.bottom - ((Math.log(value) - logMin) / logSpan) * (height - pad.top - pad.bottom);
    const xTicks = [...new Set([0, 1, 2, 3, 4, 5].map((item) => Math.round(item * (curve.dates.length - 1) / 5)))];
    svg.innerHTML = "";
    addAxes(svg, { width, height, pad, xTicks, yTicks: navTicks(minimum, maximum), xScale, yScale, xLabels: curve.dates, yFormatter: (tick) => tick < 1 ? tick.toFixed(1) : tick.toFixed(tick < 10 ? 1 : 0) });
    svg.appendChild(svgElement("path", { d: linePath(curve.reportStrategy, xScale, yScale), class: "series-report" }));
    svg.appendChild(svgElement("path", { d: linePath(curve.benchmark, xScale, yScale), class: "series-benchmark" }));
    svg.appendChild(svgElement("path", { d: linePath(curve.strategy, xScale, yScale), class: "series-strategy" }));
    attachTooltip(svg, tooltip, curve, xScale, yScale, pad, width, height, false);
  }

  function renderDrawdownChart(curve) {
    const svg = $("#drawdown-chart");
    const tooltip = $("#drawdown-tooltip");
    const width = 1000;
    const height = 260;
    const pad = { left: 55, right: 18, top: 17, bottom: 34 };
    const minimum = Math.min(...curve.drawdown.filter((value) => value !== null), ...curve.benchmarkDrawdown.filter((value) => value !== null), -0.05);
    const yMin = Math.floor(minimum * 10) / 10;
    const xScale = (index) => pad.left + (index / Math.max(curve.dates.length - 1, 1)) * (width - pad.left - pad.right);
    const yScale = (value) => pad.top + ((0 - value) / (0 - yMin)) * (height - pad.top - pad.bottom);
    const xTicks = [...new Set([0, 1, 2, 3, 4, 5].map((item) => Math.round(item * (curve.dates.length - 1) / 5)))];
    const yTicks = [0, 1, 2, 3, 4].map((item) => yMin + item * (0 - yMin) / 4);
    svg.innerHTML = "";
    addAxes(svg, { width, height, pad, xTicks, yTicks, xScale, yScale, xLabels: curve.dates, yFormatter: (tick) => pct(tick, 0) });
    const strategyPath = linePath(curve.drawdown, xScale, yScale);
    const areaPath = `${strategyPath}L${xScale(curve.drawdown.length - 1)},${yScale(0)}L${xScale(0)},${yScale(0)}Z`;
    svg.appendChild(svgElement("path", { d: areaPath, class: "drawdown-fill" }));
    svg.appendChild(svgElement("path", { d: linePath(curve.benchmarkDrawdown, xScale, yScale), class: "series-benchmark" }));
    svg.appendChild(svgElement("path", { d: strategyPath, class: "series-strategy" }));
    attachTooltip(svg, tooltip, { ...curve, strategy: curve.drawdown, benchmark: curve.benchmarkDrawdown }, xScale, yScale, pad, width, height, true);
  }

  function attachTooltip(svg, tooltip, curve, xScale, yScale, pad, width, height, isDrawdown) {
    const hoverLine = svgElement("line", { class: "hover-line", y1: pad.top, y2: height - pad.bottom, visibility: "hidden" });
    const hoverDot = svgElement("circle", { class: "hover-dot", r: 4, visibility: "hidden" });
    svg.appendChild(hoverLine);
    svg.appendChild(hoverDot);
    const overlay = svgElement("rect", { x: pad.left, y: pad.top, width: width - pad.left - pad.right, height: height - pad.top - pad.bottom, fill: "transparent" });
    svg.appendChild(overlay);
    overlay.addEventListener("pointermove", (event) => {
      const rect = svg.getBoundingClientRect();
      const viewX = (event.clientX - rect.left) / rect.width * width;
      const ratio = Math.max(0, Math.min(1, (viewX - pad.left) / (width - pad.left - pad.right)));
      const index = Math.round(ratio * (curve.dates.length - 1));
      const strategyValue = Number(curve.strategy[index]);
      if (!Number.isFinite(strategyValue)) return;
      const x = xScale(index);
      const y = yScale(strategyValue);
      hoverLine.setAttribute("x1", x);
      hoverLine.setAttribute("x2", x);
      hoverLine.setAttribute("visibility", "visible");
      hoverDot.setAttribute("cx", x);
      hoverDot.setAttribute("cy", y);
      hoverDot.setAttribute("visibility", "visible");
      tooltip.hidden = false;
      tooltip.style.left = `${event.clientX - rect.left}px`;
      tooltip.style.top = `${event.clientY - rect.top}px`;
      tooltip.innerHTML = isDrawdown
        ? `<strong>${curve.dates[index]}</strong>策略回撤 ${pct(strategyValue, 2)}<br>基准回撤 ${pct(curve.benchmark[index], 2)}`
        : `<strong>${curve.dates[index]}</strong>策略净值 ${number(strategyValue, 3)}<br>等权基准 ${number(curve.benchmark[index], 3)}<br>报告策略 ${number(curve.reportStrategy[index], 3)}`;
    });
    overlay.addEventListener("pointerleave", () => {
      tooltip.hidden = true;
      hoverLine.setAttribute("visibility", "hidden");
      hoverDot.setAttribute("visibility", "hidden");
    });
  }

  function signalRangeIndices() {
    const dates = data.signalHistory.dates;
    if (state.years === "all") return [0, dates.length - 1];
    const end = new Date(dates[dates.length - 1]);
    const cutoff = new Date(end);
    cutoff.setFullYear(cutoff.getFullYear() - Number(state.years));
    const start = Math.max(0, dates.findIndex((date) => new Date(date) >= cutoff));
    return [start, dates.length - 1];
  }

  function renderSignalMatrix() {
    const container = $("#signal-matrix");
    const [start, end] = signalRangeIndices();
    const dates = data.signalHistory.dates.slice(start, end + 1);
    const time = dates.map((date) => new Date(date).getTime());
    const width = 1120;
    const height = 202;
    const pad = { left: 104, right: 12, top: 12, bottom: 31 };
    const rowHeight = 24;
    const rowGap = 6;
    const minTime = time[0];
    const maxTime = time[time.length - 1];
    const xScale = (timestamp) => pad.left + ((timestamp - minTime) / Math.max(maxTime - minTime, 1)) * (width - pad.left - pad.right);
    const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "五维信号时间带" });
    Object.keys(dimensionMeta).forEach((key, rowIndex) => {
      const y = pad.top + rowIndex * (rowHeight + rowGap);
      const label = svgElement("text", { x: pad.left - 12, y: y + 16, "text-anchor": "end", class: "signal-label" });
      label.textContent = dimensionMeta[key].label;
      svg.appendChild(label);
      const values = data.signalHistory[key].slice(start, end + 1);
      let segmentStart = 0;
      for (let index = 1; index <= values.length; index += 1) {
        if (index === values.length || values[index] !== values[segmentStart]) {
          const x1 = xScale(time[segmentStart]);
          const nextTime = index < time.length ? time[index] : maxTime;
          const x2 = Math.max(xScale(nextTime), x1 + 1);
          const signalClass = values[segmentStart] > 0 ? "signal-growth" : values[segmentStart] < 0 ? "signal-value" : "signal-neutral";
          svg.appendChild(svgElement("rect", { x: x1, y, width: Math.max(x2 - x1, 1), height: rowHeight, rx: 2, class: signalClass }));
          segmentStart = index;
        }
      }
      svg.appendChild(svgElement("line", { x1: pad.left, x2: width - pad.right, y1: y + rowHeight + 3, y2: y + rowHeight + 3, class: "signal-grid" }));
    });
    [0, 1, 2, 3, 4, 5].forEach((step) => {
      const index = Math.round(step * (dates.length - 1) / 5);
      const x = xScale(time[index]);
      svg.appendChild(svgElement("line", { x1: x, x2: x, y1: pad.top, y2: height - pad.bottom, class: "signal-grid" }));
      const label = svgElement("text", { x, y: height - 8, "text-anchor": "middle", class: "signal-date-label" });
      label.textContent = dates[index].slice(0, 4);
      svg.appendChild(label);
    });
    container.innerHTML = "";
    container.appendChild(svg);
  }

  function resultKpi(label, value, note = "") {
    return `<div class="result-kpi"><span>${label}</span><strong>${value}</strong>${note ? `<small>${note}</small>` : ""}</div>`;
  }

  function voteLabel(value) {
    if (value === null || value === undefined) return '<span class="result-vote neutral">—</span>';
    if (Number(value) > 0) return '<span class="result-vote growth">成长 +1</span>';
    if (Number(value) < 0) return '<span class="result-vote value">价值 -1</span>';
    return '<span class="result-vote neutral">0 / 沿用</span>';
  }

  function renderMiniChart(container, dates, series, options = {}) {
    const width = 640;
    const height = 190;
    const pad = { left: 46, right: 14, top: 18, bottom: 31 };
    const referenceLines = options.referenceLines || [];
    const values = series.flatMap((item) => item.values)
      .concat(referenceLines.map((item) => item.value))
      .filter((value) => value !== null && value !== undefined && Number.isFinite(Number(value)))
      .map(Number);
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    const span = rawMax - rawMin || Math.max(Math.abs(rawMax), 1);
    const minimum = options.minimum ?? rawMin - span * 0.08;
    const maximum = options.maximum ?? rawMax + span * 0.08;
    const xScale = (index) => pad.left + index / Math.max(dates.length - 1, 1) * (width - pad.left - pad.right);
    const yScale = (value) => height - pad.bottom - (Number(value) - minimum) / Math.max(maximum - minimum, 1e-9) * (height - pad.top - pad.bottom);
    const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": options.ariaLabel || "指标历史曲线" });
    [0, 0.5, 1].forEach((ratio) => {
      const value = minimum + ratio * (maximum - minimum);
      const y = yScale(value);
      svg.appendChild(svgElement("line", { x1: pad.left, x2: width - pad.right, y1: y, y2: y, class: "result-grid" }));
      const label = svgElement("text", { x: pad.left - 8, y: y + 3, "text-anchor": "end", class: "result-axis" });
      label.textContent = options.percent ? `${Math.round(value * 100)}%` : value.toFixed(Math.abs(value) < 0.1 ? 3 : 2);
      svg.appendChild(label);
    });
    referenceLines.forEach((item) => {
      const y = yScale(item.value);
      svg.appendChild(svgElement("line", { x1: pad.left, x2: width - pad.right, y1: y, y2: y, class: "result-threshold" }));
    });
    series.forEach((item) => {
      svg.appendChild(svgElement("path", { d: linePath(item.values, xScale, yScale), class: `result-series ${item.className}` }));
    });
    [0, dates.length - 1].forEach((index) => {
      const label = svgElement("text", { x: xScale(index), y: height - 8, "text-anchor": index === 0 ? "start" : "end", class: "result-axis" });
      label.textContent = dates[index];
      svg.appendChild(label);
    });
    container.innerHTML = "";
    container.appendChild(svg);
  }

  function miniChartCard(title, subtitle, chartId, legends) {
    return `<article class="mini-chart-card">
      <div class="mini-chart-head"><div><h5>${title}</h5><p>${subtitle}</p></div>
      <div class="mini-legend">${legends.map((item) => `<span><i class="${item.className}"></i>${item.label}</span>`).join("")}</div></div>
      <div class="mini-chart" id="${chartId}"></div>
    </article>`;
  }

  function renderMacroResult(result) {
    const container = $("#algorithm-result-macro");
    const cellStyle = (value) => {
      if (value === null || value === undefined) return "";
      const distance = Math.min(Math.abs(Number(value) - 0.5) / 0.12, 1);
      if (Number(value) > result.threshold) return `background:rgba(187,57,46,${(0.14 + distance * 0.42).toFixed(2)});color:${distance > 0.55 ? "#fff" : "#6e251f"}`;
      if (Number(value) < 0.45) return `background:rgba(52,104,126,${(0.10 + distance * 0.30).toFixed(2)});color:${distance > 0.7 ? "#fff" : "#315868"}`;
      return "background:#f6f1e7;color:#5f686a";
    };
    container.innerHTML = `<div class="result-head">
      <div><h4>算法结果 · 144 个月滚动胜率热力图</h4><p>每格只使用该月当时已兑现的历史预测。红色表示胜率严格高于 55%，蓝色表示低于 45%。截至 ${result.asOf}。</p></div>
      <div class="result-kpis compact">${resultKpi("窗口", `${result.windowMonths} 月`)}${resultKpi("预热", `N ≥ ${result.minimumObservations}`)}${resultKpi("启用", `> ${pct(result.threshold, 0)}`)}</div>
    </div>
    <div class="heatmap-scroll"><table class="macro-heatmap"><thead><tr><th>宏观因子</th>${result.months.map((month) => `<th>${month}</th>`).join("")}<th>当前方向</th><th>N</th><th>状态</th></tr></thead><tbody>
    ${result.rows.map((row) => `<tr><td>${row.name}</td>${row.values.map((value) => `<td style="${cellStyle(value)}">${value === null ? "—" : pct(value, 2)}</td>`).join("")}<td>${voteLabel(row.view)}</td><td>${row.observations ?? "—"}</td><td><span class="active-pill ${row.active ? "on" : "off"}">${row.active ? "启用" : "未启用"}</span></td></tr>`).join("")}
    </tbody></table></div>
    <p class="result-footnote">N 是最近 144 个自然月中方向不为零且次月风格相对收益可判定的有效样本数；历史成熟期通常为 144。</p>`;
  }

  function renderValuationResult(result) {
    const current = result.current;
    const container = $("#algorithm-result-valuation");
    container.innerHTML = `<div class="result-head"><div><h4>算法结果 · 相对估值分位</h4><p>最近 60 个月 PB、PE 相对估值分位及 10% / 50% / 90% 触发线。截至 ${result.asOf}。</p></div></div>
      <div class="result-kpis">${resultKpi("PB 比值", number(current.pbRatio, 3), `分位 ${pct(current.pbPercentile, 1)}`)}${resultKpi("PB 状态", voteLabel(current.pbState))}${resultKpi("PE 比值", number(current.peRatio, 3), `分位 ${pct(current.pePercentile, 1)}`)}${resultKpi("PE 状态", voteLabel(current.peState))}</div>
      <div class="mini-chart-grid single">${miniChartCard("PB / PE 滚动分位", "低于 10% 支持成长，高于 90% 支持价值，回到 50% 退出", "valuation-percentile-chart", [{ label: "PB", className: "growth" }, { label: "PE", className: "value" }])}</div>`;
    renderMiniChart($("#valuation-percentile-chart"), result.dates, [
      { values: result.pbPercentile, className: "growth" },
      { values: result.pePercentile, className: "value" },
    ], { minimum: 0, maximum: 1, percent: true, referenceLines: [{ value: 0.1 }, { value: 0.5 }, { value: 0.9 }] });
  }

  function renderMomentumResult(result) {
    const current = result.current;
    const container = $("#algorithm-result-momentum");
    container.innerHTML = `<div class="result-head"><div><h4>算法结果 · 成长与价值强弱对比</h4><p>最近 60 个交易日；每张图中红线高于蓝线时，该分支投成长。截至 ${result.asOf}。</p></div>
      <div class="result-kpis compact">${resultKpi("成交额票", voteLabel(current.amountVote))}${resultKpi("收益票", voteLabel(current.returnVote))}${resultKpi("合计", `${current.rawScore > 0 ? "+" : ""}${current.rawScore}`)}</div></div>
      <div class="mini-chart-grid">${miniChartCard("成交额强度", "MA5(z-score 20日)", "momentum-amount-chart", [{ label: "成长", className: "growth" }, { label: "价值", className: "value" }])}${miniChartCard("加权收益", "20日窗口，半衰期5日", "momentum-return-chart", [{ label: "成长", className: "growth" }, { label: "价值", className: "value" }])}</div>`;
    renderMiniChart($("#momentum-amount-chart"), result.dates, [{ values: result.growthAmountZ, className: "growth" }, { values: result.valueAmountZ, className: "value" }]);
    renderMiniChart($("#momentum-return-chart"), result.dates, [{ values: result.growthReturn, className: "growth" }, { values: result.valueReturn, className: "value" }], { percent: true });
  }

  function renderBreadthResult(result) {
    const current = result.current;
    const container = $("#algorithm-result-breadth");
    container.innerHTML = `<div class="result-head"><div><h4>算法结果 · 横截面广度变化</h4><p>最近 120 个交易日；实线为 20 日均值，方向由均值的单日变化决定。截至 ${result.asOf}。</p></div>
      <div class="result-kpis compact">${resultKpi("QRD 票", voteLabel(current.qrdVote), `Δ ${number(current.qrdChange, 5)}`)}${resultKpi("MAD 票", voteLabel(current.madVote), `Δ ${number(current.madChange, 5)}`)}${resultKpi("PB覆盖", pct(current.coverage, 1))}</div></div>
      <div class="mini-chart-grid">${miniChartCard("倒数 QRD", `当前 ${number(current.qrd, 3)} · MA20 ${number(current.qrdMa, 3)}`, "breadth-qrd-chart", [{ label: "原值", className: "muted" }, { label: "MA20", className: "growth" }])}${miniChartCard("相对 MAD", `当前 ${number(current.mad, 3)} · MA20 ${number(current.madMa, 3)}`, "breadth-mad-chart", [{ label: "原值", className: "muted" }, { label: "MA20", className: "growth" }])}</div>`;
    renderMiniChart($("#breadth-qrd-chart"), result.dates, [{ values: result.qrd, className: "muted" }, { values: result.qrdMa, className: "growth" }]);
    renderMiniChart($("#breadth-mad-chart"), result.dates, [{ values: result.mad, className: "muted" }, { values: result.madMa, className: "growth" }]);
  }

  function renderCrowdingResult(result) {
    const current = result.current;
    const container = $("#algorithm-result-crowding");
    container.innerHTML = `<div class="result-head"><div><h4>算法结果 · 风格拥挤分位</h4><p>最近 120 个交易日；虚线为 95% 反向阈值，只有单边越线才产生新票。截至 ${result.asOf}。</p></div>
      <div class="result-kpis compact">${resultKpi("成交额票", voteLabel(current.amountVote))}${resultKpi("换手率票", voteLabel(current.turnoverVote))}${resultKpi("合计", `${current.rawScore > 0 ? "+" : ""}${current.rawScore}`)}</div></div>
      <div class="mini-chart-grid">${miniChartCard("成交额占比分位", "相对万得全 A", "crowding-amount-chart", [{ label: "成长", className: "growth" }, { label: "价值", className: "value" }])}${miniChartCard("换手率占比分位", "相对万得全 A", "crowding-turnover-chart", [{ label: "成长", className: "growth" }, { label: "价值", className: "value" }])}</div>`;
    const options = { minimum: 0, maximum: 1, percent: true, referenceLines: [{ value: 0.95 }] };
    renderMiniChart($("#crowding-amount-chart"), result.dates, [{ values: result.growthAmountPercentile, className: "growth" }, { values: result.valueAmountPercentile, className: "value" }], options);
    renderMiniChart($("#crowding-turnover-chart"), result.dates, [{ values: result.growthTurnoverPercentile, className: "growth" }, { values: result.valueTurnoverPercentile, className: "value" }], options);
  }

  function renderDimensionResults() {
    renderMacroResult(data.dimensionResults.macro);
    renderValuationResult(data.dimensionResults.valuation);
    renderMomentumResult(data.dimensionResults.momentum);
    renderBreadthResult(data.dimensionResults.breadth);
    renderCrowdingResult(data.dimensionResults.crowding);
  }

  function renderAlgorithms() {
    const combination = data.combination;
    $("#combination-card").innerHTML = `
      <div>
        <div class="card-kicker">五维合成</div>
        <h3>从五张票到最终仓位</h3>
        <p class="algorithm-summary">五维等权表决，方向为零时沿用前值，再用最近五个方向平滑成仓位。</p>
        <div class="formula-block"><span>组合公式</span><code>${combination.formula}</code></div>
      </div>
      <div class="combination-steps">${combination.steps.map((step) => `<div class="combination-step">${step}</div>`).join("")}</div>`;

    $("#algorithm-list").innerHTML = data.algorithms.map((algorithm, index) => {
      const factors = algorithm.factors ? `
        <h4>20 个宏观因子</h4>
        <div class="table-scroll"><table class="factor-table"><thead><tr><th>因子</th><th>指标</th><th>上行支持</th></tr></thead><tbody>
        ${algorithm.factors.map((row) => `<tr><td>${row[0]}</td><td>${row[1]}</td><td>${row[2]}</td></tr>`).join("")}
        </tbody></table></div>` : "";
      return `<details class="algorithm-card" ${algorithm.id === "macro" ? "open" : ""}>
        <summary>
          <span class="algorithm-index">${String(index + 1).padStart(2, "0")}</span>
          <span class="algorithm-title"><strong>${algorithm.title}</strong><span>${algorithm.frequency} · ${algorithm.source}</span></span>
          <span class="algorithm-summary">${algorithm.summary}</span>
          <span class="algorithm-toggle">+</span>
        </summary>
        <div class="algorithm-body">
          <div class="algorithm-column">
            <h4>计算步骤</h4>
            <ol>${algorithm.steps.map((step) => `<li>${step}</li>`).join("")}</ol>
            <div class="parameter-list">${algorithm.parameters.map((parameter) => `<span>${parameter}</span>`).join("")}</div>
            <p class="quality-note">${algorithm.quality}</p>
          </div>
          <div class="algorithm-column">
            <h4>公式</h4>
            <div class="formula-list">${algorithm.formulas.map((formula) => `<div class="formula-block"><span>${formula[0]}</span><code>${formula[1]}</code></div>`).join("")}</div>
            ${factors}
          </div>
        </div>
        <div class="algorithm-result" id="algorithm-result-${algorithm.id}"></div>
      </details>`;
    }).join("");
    renderDimensionResults();
  }

  function renderValidation() {
    const comparison = data.reportComparison[state.layer];
    const definitions = [
      ["年化收益", "cagr", true],
      ["年化超额", "excess_cagr", true],
      ["最大回撤", "max_drawdown", true],
      ["月度超额胜率", "monthly_excess_win_rate", true],
      ["信息比率", "information_ratio", false],
      ["平均切换间隔", "average_switch_interval_trading_days", false],
    ];
    $("#comparison-table").innerHTML = definitions.map(([label, key, isPercent]) => {
      const item = comparison[key];
      const formatter = isPercent ? pct : (value) => number(value, 2);
      const difference = isPercent ? signedPct(item.difference) : `${item.difference > 0 ? "+" : ""}${number(item.difference, 2)}`;
      return `<tr><td>${label}</td><td>${formatter(item.report)}</td><td>${formatter(item.current)}</td><td class="${item.difference >= 0 ? "positive" : "negative"}">${difference}</td></tr>`;
    }).join("");

    const annual = data.yearly[state.layer].slice(-8).reverse();
    $("#yearly-table").innerHTML = annual.map((row) => `<tr>
      <td>${row.year}${row.year === 2026 ? "*" : ""}</td>
      <td class="${row.strategy >= 0 ? "positive" : "negative"}">${signedPct(row.strategy)}</td>
      <td>${signedPct(row.benchmark)}</td>
      <td class="${row.excess >= 0 ? "positive" : "negative"}">${signedPct(row.excess)}</td>
    </tr>`).join("");
  }

  function renderBoundaries() {
    $("#boundary-list").innerHTML = data.boundaries.map((item) => `<li>${item}</li>`).join("");
  }

  renderMeta();
  renderCurrent();
  renderAlgorithms();
  renderBoundaries();
  bindControls();
  renderPerformance();
  renderSignalMatrix();
  renderValidation();
})();
