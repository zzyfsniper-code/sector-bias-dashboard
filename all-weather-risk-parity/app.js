(() => {
  const data = window.ALL_WEATHER_RISK_PARITY;
  const $ = (id) => document.getElementById(id);
  const pct = (value, digits = 2) => value == null ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
  const date = (value) => value ? String(value).slice(0, 10) : "—";
  const money = (value) => `¥${Math.round(Number(value) || 0).toLocaleString("zh-CN")}`;
  const LOT_SIZE = 100;
  const versions = data?.performance || {};
  let selected = "base";

  if (!data) {
    $("header-status").textContent = "数据读取失败";
    return;
  }

  function renderHeader() {
    $("header-status").textContent = data.status === "PASS" ? `数据正常 · ${date(data.data_as_of)}` : "数据异常";
    $("header-status").previousElementSibling.classList.toggle("pass", data.status === "PASS");
    $("run-time").textContent = date(data.generated_at).replaceAll("-", "/");
    $("data-date").textContent = date(data.data_as_of);
    $("next-date").textContent = date(data.next_trade_date);
    $("validation-tag").textContent = data.status === "PASS" ? "校验通过" : "校验异常";
    $("validation-tag").classList.toggle("tag-live", data.status === "PASS");
    $("footer-run").textContent = `批次 ${data.run_id} · 数据至 ${date(data.data_as_of)}`;
    $("validation-seal").textContent = data.validation?.status === "PASS" ? "数据与规则校验通过" : "等待校验";
    $("validation-seal").classList.toggle("pass", data.validation?.status === "PASS");
  }

  function renderTrade() {
    const spec = versions[selected];
    const rate = Number(spec.financing_rate || 0);
    const action = data.trade.action || "持有当前组合，等待下一季度信号";
    $("target-exposure").textContent = `${Number(spec.exposure).toFixed(1)}x`;
    $("target-version").textContent = spec.label;
    $("action-text").textContent = action.includes("执行") ? "季度调仓待执行" : "持有当前组合";
    const nextSignal = date(data.trade.next_signal_date);
    const nextExecution = date(data.trade.next_execution_date);
    $("trade-summary").textContent = action.includes("执行")
      ? `最近信号已形成，${nextExecution} 收盘按新的 ERC 权重执行 ${spec.label}。`
      : `当前组合沿用最近一次季度权重，预计 ${nextSignal} 形成下一次信号，随后于 ${nextExecution} 收盘执行。`;
    $("action-badge").textContent = action.includes("执行") ? "待执行" : "持有";
    $("current-exposure").textContent = `${Number(spec.exposure).toFixed(1)}x`;
    $("flow-target").textContent = `${Number(spec.exposure).toFixed(1)}x`;
    $("execute-at").textContent = nextExecution;
    $("signal-date").textContent = date(data.trade.signal_date);
    $("next-signal-date").textContent = nextSignal;
    $("funding-label").textContent = rate ? `${pct(rate, 1)} / 年` : "0%";
    $("signal-chip").textContent = `截至 ${date(data.data_as_of)}`;
    $("signal-readout").textContent = date(data.trade.signal_date);
    $("execution-readout").textContent = date(data.trade.signal_execution_date);
    $("next-signal-readout").textContent = nextSignal;
    $("next-execution-readout").textContent = nextExecution;
  }

  function renderVersion() {
    const spec = versions[selected];
    const m = spec.metrics;
    $("version-cagr").textContent = pct(m.cagr);
    $("version-mdd").textContent = pct(m.max_drawdown);
    $("version-sharpe").textContent = Number(m.sharpe_zero_rf).toFixed(2);
    $("version-note").textContent = selected === "base"
      ? "基准组合不融资，四资产目标权重合计100%。"
      : selected === "levered_0"
        ? "四资产内部比例不变，总敞口放大至150%，暂不计融资成本。"
        : "四资产内部比例不变，总敞口150%；按50%融资敞口计提年化3%成本。";
    $("performance-period").textContent = `${date(m.start)} — ${date(m.end)}`;
    $("metric-cagr").textContent = pct(m.cagr);
    $("metric-vol").textContent = pct(m.volatility);
    $("metric-mdd").textContent = pct(m.max_drawdown);
    $("metric-sharpe").textContent = Number(m.sharpe_zero_rf).toFixed(2);
    $("metric-turnover").textContent = `${Number(m.annual_turnover * 100).toFixed(1)}%`;
    document.querySelectorAll("#version-tabs button").forEach((button) => button.classList.toggle("active", button.dataset.version === selected));
    renderTrade();
    renderHoldings();
  }

  function renderHoldings() {
    const multiplier = Number(versions[selected].exposure);
    const accountAmount = Math.max(0, Number($("account-amount").value) || 0);
    const grossTarget = accountAmount * multiplier;
    let purchaseTotal = 0;
    const body = $("holdings-body");
    body.innerHTML = data.portfolio.assets.map((asset) => {
      const current = Number(asset.current_weight) * multiplier;
      const robust = Number(asset.target_weight);
      const target = robust * multiplier;
      const delta = target - current;
      const action = Math.abs(delta) < 0.0005 ? "维持" : delta > 0 ? "增配" : "减配";
      const actionClass = delta > 0.0005 ? "delta-up" : delta < -0.0005 ? "delta-down" : "";
      const price = Number(asset.latest_price);
      const targetAmount = accountAmount * target;
      const shares = price > 0 ? Math.floor(targetAmount / price / LOT_SIZE) * LOT_SIZE : 0;
      const actualAmount = price > 0 ? shares * price : 0;
      purchaseTotal += actualAmount;
      return `<tr><td><strong>${asset.name}</strong><small>${asset.market}</small></td><td>${asset.code}</td><td>${asset.role}</td><td>${pct(current, 1)}</td><td class="${actionClass}">${pct(target, 1)}</td><td>${price > 0 ? price.toFixed(3) : "—"}</td><td>${money(targetAmount)}</td><td class="${actionClass}">${price > 0 ? `${shares.toLocaleString("zh-CN")} 份` : "—"}</td><td>${price > 0 ? money(actualAmount) : "—"}</td><td class="${actionClass}">${action}</td></tr>`;
    }).join("");
    $("holding-total").textContent = `${(multiplier * 100).toFixed(0)}%`;
    $("calc-capital").textContent = money(accountAmount);
    $("calc-gross").textContent = money(grossTarget);
    $("calc-purchase").textContent = money(purchaseTotal);
    const isLevered = multiplier > 1;
    $("calc-balance-label").textContent = isLevered ? "预计融资需求" : "预计剩余资金";
    $("calc-balance").textContent = money(isLevered ? Math.max(0, purchaseTotal - accountAmount) : Math.max(0, accountAmount - purchaseTotal));
    const roundingGap = Math.max(0, grossTarget - purchaseTotal);
    $("calc-note").textContent = isLevered
      ? `当前为${multiplier.toFixed(1)}x版本，目标总持仓约${money(grossTarget)}；预计融资需求按实际买入金额减自有资金估算，未使用名义额度约${money(roundingGap)}。`
      : `当前为稳健1.0x版本，按100份整数手向下取整后预计剩余资金约${money(Math.max(0, accountAmount - purchaseTotal))}；未使用额度主要来自手数取整。`;
  }

  function renderAssets() {
    $("asset-grid").innerHTML = data.rules.universe.map((asset) => `<article class="asset-card"><span class="asset-code">${asset.code}</span><h3>${asset.name}</h3><p>${asset.role} · ${asset.market}</p></article>`).join("");
  }

  function renderHistory() {
    const rows = [...data.signals].slice(-10).reverse();
    $("signal-history-body").innerHTML = rows.map((row) => {
      const sum = ["510300.SH", "513100.SH", "518880.SH", "511010.SH"].reduce((acc, code) => acc + Number(row[`weight_${code}`] || 0), 0);
      return `<tr><td>${date(row.signal_date)}</td><td>${date(row.execution_date)}</td><td>${pct(row["weight_510300.SH"], 1)}</td><td>${pct(row["weight_513100.SH"], 1)}</td><td>${pct(row["weight_518880.SH"], 1)}</td><td>${pct(row["weight_511010.SH"], 1)}</td><td>${pct(sum, 0)}</td></tr>`;
    }).join("");
  }

  function renderWeightDiagnostics() {
    const diagnostic = data.weight_diagnostics;
    if (!diagnostic) return;
    $("weight-diagnostic-status").textContent = `已计算 · ${date(diagnostic.signal_date)}`;
    $("weight-diagnostic-period").textContent = `${date(diagnostic.signal_date)} 信号 / ${date(diagnostic.execution_date)} 执行`;
    $("weight-window").textContent = `${date(diagnostic.window_start)} — ${date(diagnostic.window_end)}`;
    $("weight-volatility").textContent = pct(diagnostic.portfolio_annualized_volatility, 1);
    $("weight-risk-target").textContent = pct(diagnostic.target_risk_contribution, 0);
    $("weight-sum").textContent = pct(diagnostic.weight_sum, 0);
    $("weight-diagnostic-body").innerHTML = diagnostic.assets.map((asset) => {
      const capClass = asset.cap_applied ? "constraint-hit" : "";
      const capText = asset.cap_applied ? "触及60%上限" : "未触及上限";
      return `<tr><td><strong>${asset.name}</strong><small>${asset.code}</small></td><td>${pct(asset.annualized_volatility, 1)}</td><td>${pct(asset.final_weight, 1)}</td><td class="${capClass}">${pct(asset.risk_contribution, 1)}</td><td>${pct(asset.target_risk_contribution, 1)}</td><td class="${capClass}">${capText}</td></tr>`;
    }).join("");
    const capped = diagnostic.assets.filter((asset) => asset.cap_applied).map((asset) => asset.name);
    $("weight-cap-note").textContent = capped.length
      ? `${capped.join("、")}触及单资产60%上限；其余权重共同调整，组合权重仍合计100%。`
      : "本季度没有资产触及60%上限，最终权重由等风险贡献约束直接求解。";
  }

  const chartLabels = {
    base: "稳健 1.0x",
    levered_0: "1.5x · 0%融资",
    levered_3: "1.5x · 3%融资",
    base_dd: "稳健 1.0x回撤",
    levered_0_dd: "1.5x · 0%融资回撤",
    levered_3_dd: "1.5x · 3%融资回撤",
  };

  function chartValue(value, percent) {
    if (value == null || !Number.isFinite(Number(value))) return "—";
    return percent ? pct(value, 2) : Number(value).toFixed(3);
  }

  function drawChart(canvas, keys, percent = false, hoverIndex = null) {
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(320, rect.width);
    const height = Number(canvas.getAttribute("height"));
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const left = 58, right = width - 18, top = 18, bottom = height - 32;
    const values = data.series.flatMap((row) => keys.map((key) => Number(row[key]) * (percent ? 100 : 1)));
    let low = Math.min(...values), high = Math.max(...values);
    if (percent) high = Math.max(high, 0);
    const pad = Math.max((high - low) * .08, percent ? .25 : .03);
    low -= pad; high += pad;
    const x = (i) => left + (i / Math.max(data.series.length - 1, 1)) * (right - left);
    const y = (value) => bottom - ((value - low) / Math.max(high - low, 1e-9)) * (bottom - top);
    ctx.clearRect(0, 0, width, height);
    ctx.font = "12px Microsoft YaHei, Arial";
    ctx.lineWidth = 1;
    ctx.strokeStyle = "#e4dfd6";
    ctx.fillStyle = "#6e797e";
    for (let i = 0; i <= 5; i += 1) {
      const yy = top + (i / 5) * (bottom - top);
      ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(right, yy); ctx.stroke();
      const value = high - (i / 5) * (high - low);
      ctx.fillText(percent ? `${value.toFixed(1)}%` : value.toFixed(2), 4, yy + 4);
    }
    const colors = ["#1769aa", "#1f8b69", "#8b5cf6"];
    keys.forEach((key, seriesIndex) => {
      ctx.beginPath(); ctx.lineWidth = seriesIndex === 0 ? 3 : 2;
      ctx.strokeStyle = colors[seriesIndex];
      data.series.forEach((row, i) => {
        const value = Number(row[key]) * (percent ? 100 : 1);
        if (i === 0) ctx.moveTo(x(i), y(value)); else ctx.lineTo(x(i), y(value));
      });
      ctx.stroke();
    });
    canvas._chartState = { keys, percent, width, left, right, top, bottom };
    if (hoverIndex != null) {
      const index = Math.max(0, Math.min(data.series.length - 1, hoverIndex));
      const hoverX = x(index);
      ctx.save();
      ctx.strokeStyle = "rgba(23,35,43,.38)";
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(hoverX, top); ctx.lineTo(hoverX, bottom); ctx.stroke();
      ctx.setLineDash([]);
      keys.forEach((key, seriesIndex) => {
        const value = Number(data.series[index][key]) * (percent ? 100 : 1);
        if (!Number.isFinite(value)) return;
        ctx.fillStyle = colors[seriesIndex];
        ctx.strokeStyle = "#fffdf8";
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(hoverX, y(value), 4, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      });
      ctx.restore();
    }
    ctx.fillStyle = "#6e797e";
    [0, Math.floor((data.series.length - 1) / 2), data.series.length - 1].forEach((i) => {
      const label = date(data.series[i].date);
      ctx.fillText(label, x(i) - 25, height - 8);
    });
  }

  function pointerIndex(canvas, event) {
    const state = canvas._chartState;
    const rect = canvas.getBoundingClientRect();
    const logicalX = (event.clientX - rect.left) / Math.max(rect.width, 1) * state.width;
    const ratio = Math.max(0, Math.min(1, (logicalX - state.left) / (state.right - state.left)));
    return Math.round(ratio * (data.series.length - 1));
  }

  function showChartTooltip(canvas, tooltip, event, rows) {
    const parentRect = tooltip.parentElement.getBoundingClientRect();
    const localX = event.clientX - parentRect.left;
    const localY = event.clientY - parentRect.top;
    tooltip.innerHTML = `<strong>${date(data.series[pointerIndex(canvas, event)].date)}</strong>${rows.map(([label, value]) => `<div class="tooltip-row"><span>${label}</span><b>${value}</b></div>`).join("")}`;
    tooltip.hidden = false;
    const flip = localX > parentRect.width - tooltip.offsetWidth - 24;
    const offsetX = flip ? localX - 14 : localX + 14;
    const minX = 8;
    const maxX = Math.max(minX, parentRect.width - tooltip.offsetWidth - 8);
    tooltip.style.left = `${Math.max(minX, Math.min(maxX, offsetX))}px`;
    tooltip.style.top = `${Math.max(8, Math.min(parentRect.height - 8, localY))}px`;
    tooltip.style.transform = flip ? "translate(-100%,-50%)" : "translate(0,-50%)";
  }

  function bindChartHover(canvas, tooltip, keys, percent) {
    canvas.addEventListener("pointermove", (event) => {
      const index = pointerIndex(canvas, event);
      drawChart(canvas, keys, percent, index);
      const row = data.series[index];
      const rows = keys.map((key) => [chartLabels[key], chartValue(row[key], percent)]);
      showChartTooltip(canvas, tooltip, event, rows);
    });
    canvas.addEventListener("pointerleave", () => {
      tooltip.hidden = true;
      drawChart(canvas, keys, percent);
    });
  }

  function renderCharts() {
    drawChart($("nav-chart"), ["base", "levered_0", "levered_3"]);
    drawChart($("drawdown-chart"), ["base_dd", "levered_0_dd", "levered_3_dd"], true);
  }

  document.querySelectorAll("#version-tabs button").forEach((button) => button.addEventListener("click", () => {
    selected = button.dataset.version;
    renderVersion();
  }));
  $("calculate-positions").addEventListener("click", renderHoldings);
  $("account-amount").addEventListener("input", renderHoldings);
  window.addEventListener("resize", renderCharts);
  renderHeader();
  renderAssets();
  renderHistory();
  renderWeightDiagnostics();
  renderVersion();
  renderCharts();
  bindChartHover($("nav-chart"), $("nav-tooltip"), ["base", "levered_0", "levered_3"], false);
  bindChartHover($("drawdown-chart"), $("drawdown-tooltip"), ["base_dd", "levered_0_dd", "levered_3_dd"], true);
})();
