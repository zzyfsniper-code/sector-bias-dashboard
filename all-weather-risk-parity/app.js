(() => {
  const data = window.ALL_WEATHER_RISK_PARITY;
  const $ = (id) => document.getElementById(id);
  const pct = (value, digits = 2) => value == null ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
  const date = (value) => value ? String(value).slice(0, 10) : "—";
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
    const body = $("holdings-body");
    body.innerHTML = data.portfolio.assets.map((asset) => {
      const current = Number(asset.current_weight) * multiplier;
      const robust = Number(asset.target_weight);
      const target = robust * multiplier;
      const delta = target - current;
      const action = Math.abs(delta) < 0.0005 ? "维持" : delta > 0 ? "增配" : "减配";
      const actionClass = delta > 0.0005 ? "delta-up" : delta < -0.0005 ? "delta-down" : "";
      return `<tr><td><strong>${asset.name}</strong><small>${asset.market}</small></td><td>${asset.code}</td><td>${asset.role}</td><td>${pct(current, 1)}</td><td>${pct(robust, 1)}</td><td class="${actionClass}">${pct(target, 1)}</td><td class="${actionClass}">${action}</td></tr>`;
    }).join("");
    $("holding-total").textContent = `${(multiplier * 100).toFixed(0)}%`;
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

  function drawChart(canvas, keys, percent = false) {
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(320, rect.width);
    const height = Number(canvas.getAttribute("height"));
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
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
    ctx.fillStyle = "#6e797e";
    [0, Math.floor((data.series.length - 1) / 2), data.series.length - 1].forEach((i) => {
      const label = date(data.series[i].date);
      ctx.fillText(label, x(i) - 25, height - 8);
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
  window.addEventListener("resize", renderCharts);
  renderHeader();
  renderAssets();
  renderHistory();
  renderVersion();
  renderCharts();
})();
