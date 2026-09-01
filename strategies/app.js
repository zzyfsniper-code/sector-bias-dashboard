(() => {
  const $ = (id) => document.getElementById(id);
  const pct = (value) => value == null ? "—" : `${(Number(value) * 100).toFixed(0)}%`;
  const state = {fresh:0, trades:0, dates:[]};
  const mark = (prefix, ok, date, action) => {
    $(prefix+"-status").textContent = ok ? "数据正常" : "数据异常";
    $(prefix+"-status").classList.toggle("pass", ok);
    if(ok) state.fresh += 1; if(action && action !== "NO_TRADE") state.trades += 1; if(date) state.dates.push(date);
  };
  Promise.allSettled([
    fetch("../growth-value-five-dim/data/strategy.json", {cache:"no-store"}).then(r => {if(!r.ok) throw new Error(r.status); return r.json()}),
    fetch("../csi500-flow-leverage/data/strategy.json", {cache:"no-store"}).then(r => {if(!r.ok) throw new Error(r.status); return r.json()})
  ]).then(([growth,csi]) => {
    if(growth.status === "fulfilled"){
      const d=growth.value, plan=d.tradingPlan || {}, current=d.current || {};
      const growthWeight=plan.targetGrowthWeight ?? current.desiredGrowthWeight ?? null;
      $("growth-signal").textContent=growthWeight == null ? "—" : (growthWeight>=.5?"偏成长":"偏价值");
      $("growth-target").textContent=`成长 ${pct(growthWeight)}`;
      $("growth-date").textContent=`数据 ${current.signalDate || d.meta?.signalEnd || "—"}`;
      $("growth-action").textContent=`动作 ${plan.status || "—"}`;
      mark("growth",d.meta?.validationStatus==="PASS" || d.validation?.status==="PASS",current.signalDate || d.meta?.signalEnd,plan.status);
    } else { mark("growth",false); }
    if(csi.status === "fulfilled"){
      const d=csi.value;
      $("csi-signal").textContent=d.trade.signal;
      $("csi-target").textContent=`ETF ${pct(d.trade.next_target)}`;
      $("csi-date").textContent=`数据 ${d.data_as_of}`;
      $("csi-action").textContent=`动作 ${d.trade.action}`;
      mark("csi",d.status==="PASS",d.data_as_of,d.trade.action);
    } else { mark("csi",false); }
    $("fresh-count").textContent=`${state.fresh} / 2`;
    $("trade-count").textContent=String(state.trades);
    $("updated").textContent=state.dates.length?`最新数据 ${state.dates.sort().at(-1)}`:"策略状态读取失败";
    document.querySelector(".site-header .status-dot").classList.toggle("pass", state.fresh === 2);
  });
})();
