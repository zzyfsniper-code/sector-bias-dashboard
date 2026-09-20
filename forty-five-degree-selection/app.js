(() => {
  const data = window.FORTY_FIVE_DEGREE_STRATEGY;
  const $ = (id) => document.getElementById(id);
  const pct = (value, digits = 1) => value == null ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
  const num = (value, digits = 3) => value == null ? "—" : Number(value).toFixed(digits);
  if (!data) {
    $("header-status").textContent = "策略数据不存在";
    return;
  }

  $("data-date").textContent = data.dataAsOf || "—";
  $("member-date").textContent = data.constituentDate || "—";
  $("run-id").textContent = data.meta?.runId || "—";
  $("validation").textContent = data.validation?.status || "—";
  $("header-status").textContent = data.status === "PASS" ? `数据正常 · ${data.dataAsOf}` : "数据校验失败";
  document.querySelector(".site-header .status-dot").classList.toggle("pass", data.status === "PASS");

  const targets = data.selection?.targets || [];
  $("target-count").textContent = String(targets.length);
  $("target-body").innerHTML = targets.map((item) => `<tr><td><span class="rank">${item.rank}</span></td><td><strong>${item.name}</strong><small>${item.windCode}</small></td><td>${item.industry || "—"}</td><td>${pct(item.targetWeight, 0)}</td><td class="metric">${num(item.rSquared, 4)}</td><td class="metric">${pct(item.normalizedSlope, 2)}</td><td>${pct(item.pullbackRatio, 2)}</td><td>${num(item.volumeRatio7To200, 2)}×</td></tr>`).join("");
  $("empty-targets").hidden = targets.length > 0;

  const labels = [
    ["universe", "沪深300成分"],
    ["complete_history", "历史数据完整"],
    ["pullback", "回撤不超过8%"],
    ["volume", "量能不超过1.6倍"],
    ["regression", "回归条件通过"],
  ];
  $("funnel").innerHTML = labels.map(([key, label], index) => `<div><span>0${index + 1}</span><strong>${data.filterCounts?.[key] ?? "—"}</strong><small>${label}</small></div>`).join("");

  $("rules").innerHTML = Object.entries(data.rules || {}).map(([key, value]) => `<article class="card"><span>${key.toUpperCase()}</span><p>${value}</p></article>`).join("");
  $("limitations").innerHTML = (data.limitations || []).map((item) => `<li>${item}</li>`).join("");
})();
