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

  function drawChart(canvas, series, options = {}) {
    const dpr = window.devicePixelRatio || 1, rect = canvas.getBoundingClientRect();
    const height = Number(canvas.getAttribute("height")); canvas.width = Math.max(600, rect.width) * dpr; canvas.height = height * dpr;
    const ctx = canvas.getContext("2d"); ctx.scale(dpr,dpr);
    const width = canvas.width/dpr, h = height, pad = {l:54,r:18,t:18,b:34}, cw=width-pad.l-pad.r, ch=h-pad.t-pad.b;
    const values = series.flatMap(s => s.values).filter(Number.isFinite); let min = options.min ?? Math.min(...values), max = options.max ?? Math.max(...values);
    if (max === min) max += 1; const x = i => pad.l + i/(data.series.dates.length-1)*cw; const y = v => pad.t + (max-v)/(max-min)*ch;
    ctx.font="10px Microsoft YaHei"; ctx.fillStyle=color.text; ctx.strokeStyle=color.grid; ctx.lineWidth=1;
    for(let i=0;i<=4;i++){const yy=pad.t+i*ch/4, val=max-i*(max-min)/4;ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(width-pad.r,yy);ctx.stroke();ctx.fillText(options.percent?`${(val*100).toFixed(0)}%`:val.toFixed(1),4,yy+3)}
    if(options.bands){let start=null; data.series.regime_active.forEach((active,i)=>{if(active&&start===null)start=i;if((!active||i===data.series.regime_active.length-1)&&start!==null){const end=active?i:i-1;ctx.fillStyle=color.band;ctx.fillRect(x(start),pad.t,Math.max(2,x(end)-x(start)),ch);start=null}})}
    series.forEach(s=>{ctx.strokeStyle=s.color;ctx.lineWidth=s.width||2;ctx.beginPath();s.values.forEach((v,i)=>{if(!Number.isFinite(v))return;const xx=x(i),yy=y(v);i===0?ctx.moveTo(xx,yy):ctx.lineTo(xx,yy)});ctx.stroke()});
    const years=[]; data.series.dates.forEach((date,i)=>{const year=date.slice(0,4);if(!years.length||years.at(-1).year!==year)years.push({year,i})}); const step=Math.max(1,Math.ceil(years.length/8));years.filter((_,i)=>i%step===0).forEach(t=>{ctx.fillStyle=color.text;ctx.fillText(t.year,x(t.i)-10,h-10)});
  }
  function renderCharts(){
    drawChart($("nav-chart"),[
      {values:data.series.candidate_nav,color:color.candidate,width:2.5},
      {values:data.series.base_nav,color:color.base,width:1.6},
      {values:data.series.benchmark_nav,color:color.benchmark,width:1.4}],{bands:true,min:0});
    drawChart($("drawdown-chart"),[
      {values:data.series.candidate_drawdown,color:color.candidate,width:2.2},
      {values:data.series.base_drawdown,color:color.base,width:1.5}],{bands:true,percent:true,max:0});
  }
  renderCharts(); window.addEventListener("resize", renderCharts);
})();
