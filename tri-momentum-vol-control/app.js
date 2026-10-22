(() => {
'use strict';
const core=window.TriMomentumCore,$=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=(x,d=2)=>Number.isFinite(x)?`${(x*100).toFixed(d)}%`:'—',price=x=>Number.isFinite(x)&&x>0?x.toFixed(3):'—';
const change=x=>Number.isFinite(x)?`<span class="${x>0?'up':x<0?'down':''}">${x>0?'+':''}${pct(x)}</span>`:'—';
const names={'159696.SZ':'纳指ETF易方达','510300.SH':'沪深300ETF','518880.SH':'黄金ETF'},version='tri-momentum-vol-v1.1-20261015';
let backtest,live,performance,trackingChart,frozenChart,history=[],quotes={},networkOk=false,busy=false,timer,page=0;
async function request(url,ms=16000){const c=new AbortController(),t=setTimeout(()=>c.abort(),ms);try{const r=await fetch(url,{cache:'no-store',signal:c.signal});if(!r.ok)throw Error(`HTTP ${r.status}`);return r;}finally{clearTimeout(t);}}
async function json(name){return (await request(`data/${name}.json?t=${Date.now()}`)).json();}
function renderSignal(){if(!live)return;const s=live.signal,now=new Date(),gate=core.evaluate(live,quotes,now,networkOk),cn=core.chinaTime(now);
$('dataDate').textContent=live.data_as_of;$('updateTime').textContent=live.updated_at.slice(0,19).replace('T',' ');
$('targetName').textContent=s.selected_name;$('targetWeight').textContent=pct(s.risk_weight);$('cashWeight').textContent=`现金 ${pct(s.cash_weight)}`;$('estimatedVol').textContent=pct(s.estimated_volatility);$('executionDate').textContent=s.execution_date;
$('informationDate').textContent=`信息截至 ${s.information_date}`;$('signalStatus').textContent=gate.ready?'可执行参考':s.is_final?'前收信号已定':'预览 · 尚未最终确定';$('signalStatus').className='pill '+(gate.ready?'buy':'watch');
$('signalExplanation').textContent=gate.note+(s.is_final?'':`；${s.execution_date}的最终信号需等到${s.required_information_date}收盘后。`);
$('headerStatus').textContent=gate.ready?'执行窗口 · 人工参考':'冻结规则 · 模型跟踪';document.querySelector('.status-dot').classList.toggle('pass',gate.ready);
const m=live.model_current,hold=core.codes.filter(c=>m.weights[c]>1e-8).map(c=>`${names[c]} ${pct(m.weights[c])}`).join('、');$('modelCurrent').textContent=`截至${m.as_of}的模型持仓：${hold||'无风险资产'}，现金 ${pct(m.cash_weight)}。上次模型调仓${m.last_execution_date}；非账户实际持仓。`;
const issues=[...(live.issues||[])];if(/待更新|过期|不足|异常/.test(gate.note))issues.unshift(gate.note);$('dataWarning').hidden=!issues.length;$('dataWarning').textContent=issues.join('；');
$('assetRows').innerHTML=core.codes.slice().sort((a,b)=>s.scores[b]-s.scores[a]).map(c=>{const q=networkOk?quotes[c]:null,check=core.quoteCheck(q,now);const stamp=q?.timestamp,ts=stamp?`${stamp.slice(0,4)}-${stamp.slice(4,6)}-${stamp.slice(6,8)} ${stamp.slice(8,10)}:${stamp.slice(10,12)}:${stamp.slice(12,14)}`:'—';return `<tr class="${c===s.selected_code?'selected':''}"><td><span class="stock">${names[c]}</span><span class="code">${c}</span></td><td class="num">${change(s.scores[c])}</td><td class="num">${pct(s.volatilities[c])}</td><td class="num">${price(q?.last)}</td><td class="num">${q?change(q.last/q.previous-1):'—'}</td><td>${esc(ts)}<span class="sub">${cn.time>='15:00:00'?'收盘后参考，非盘中可执行价':check.ok?'时效通过':esc(check.note)}</span></td></tr>`;}).join('');
renderSizing();
}
function renderSizing(){
const input=$('capitalAmount'),capital=Number(input.value),result=$('sizingResult');
if(!input.value.trim()||!input.validity.valid||!Number.isFinite(capital)||capital<=0){result.innerHTML='<p class="footnote">请输入大于0的账户总资金，自动测算目标ETF持有份数。</p>';return;}
const s=live?.signal,q=networkOk&&s?quotes[s.selected_code]:null,size=q?core.positionSize(capital,s.risk_weight,q.last):null;
if(!size){result.innerHTML='<p class="footnote">行情或模型未就绪，暂不提供份数测算；不会沿用失败前的旧报价。</p>';return;}
const money=x=>x.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}),count=x=>x.toLocaleString('zh-CN');
const now=new Date(),gate=core.evaluate(live,quotes,now,networkOk),cn=core.chinaTime(now),check=core.quoteCheck(q,now);
const stage=!s.is_final?'预览信号，最终标的和份数可能变化。':gate.ready?'执行窗口参考测算，仍需人工核对成交价。':`仅作参考测算：${gate.note}。`;
const quoteNote=cn.time>='15:00:00'?'收盘后参考价':check.ok?'页面最新参考价':`${check.note}，非可执行报价`;
result.innerHTML=`<div class="sizing-results"><div><span>目标持有 · ${esc(names[s.selected_code])}</span><strong><b id="sizingShares">${count(size.shares)}</b> 份</strong><small>${count(size.lots)}手 · 100份/手</small></div><div><span>测算参考价</span><strong>${price(size.price)} 元</strong><small>${quoteNote}</small></div><div><span>预计买入金额</span><strong>${money(size.amount)} 元</strong><small>估算单边10bp成本 ${money(size.fee)} 元</small></div><div><span>预计剩余现金</span><strong>${money(size.cash)} 元</strong><small>取整后风险仓位 ${pct(size.weight)}</small></div></div><p class="footnote sizing-status">${stage}${size.shares===0?'按当前资金、仓位和参考价，不足买入1手。':''}</p>`;
}
function renderHistory(){const origin=$('originFilter').value,asset=$('assetFilter').value,year=$('yearFilter').value;const rows=history.filter(r=>(origin==='all'||(r.origin||'backtest')===origin)&&(!asset||r.selected_code===asset)&&(!year||r.execution_date.startsWith(year))).slice().reverse();page=Math.min(page,Math.max(0,Math.ceil(rows.length/25)-1));$('recordCount').textContent=`${rows.length}条模型记录`;$('pageInfo').textContent=rows.length?`${page*25+1}—${Math.min(rows.length,(page+1)*25)} / ${rows.length}`:'暂无记录';$('previousPage').disabled=page===0;$('nextPage').disabled=(page+1)*25>=rows.length;
$('historyRows').innerHTML=rows.slice(page*25,page*25+25).map(r=>{const previous=core.codes.filter(c=>(r.previous_weights?.[c]||0)>1e-8).map(c=>`${names[c]} ${pct(r.previous_weights[c],1)}`).join('、')||'现金';const label=({'backtest':'冻结回测','historical_extension':'历史延伸','frozen_model':'定版后模型'})[r.origin||'backtest'];return `<tr><td>${esc(r.execution_date)}</td><td>${esc(r.information_date)}</td><td>${previous}<span class="sub">→ ${esc(r.selected_name||names[r.selected_code])}${r.turnover<1e-10?' · 复核不交易':''}</span></td><td class="num">${pct(r.selected_score)}</td><td class="num">${pct(r.estimated_volatility)}</td><td class="num">${pct(r.risk_weight)} / ${pct(r.cash_weight)}</td><td class="num">${pct(r.turnover)}<span class="sub">费用 ${pct(r.fee,4)} 净资产</span></td><td><span class="pill">${label}</span><span class="sub">非实际成交</span></td></tr>`;}).join('')||'<tr><td colspan="8" class="empty">当前筛选下暂无模型记录。</td></tr>';
}
function details(){const b=backtest;$('rulesPanel').innerHTML='<div class="rules-grid">'+b.rules.map(r=>`<div>${esc(r[0])}</div><div>${esc(r[1])}</div>`).join('')+'</div><div class="note">动量窗口是20个价格点（19段收益），波动率窗口是20段收益（21个价格点），两者不要混用。14%是仓位缩放参数，不是实际波动率或最大回撤保证。无绝对动量过滤，三只资产全部下跌时仍选相对最强者。</div>';
$('backtestSummary').innerHTML=`<p class="note">${b.start} — ${b.end}｜冻结选定版本 cash_t14_v20｜159696使用已核验的Tushare历史复权价格缓存，沪深300与黄金使用Wind Excel复权价格。成立2023-08-17，上市2023-08-25；预热后开始计账。这里保留冻结业绩，主页面每日跟踪最新收盘。</p>`+window.TriPerformance.metrics(b.metrics);
$('annualRows').innerHTML=b.annual.map(r=>`<tr><td>${r.period}${['2023','2026'].includes(r.period)?'（部分年度）':''}</td><td class="num">${pct(r.net_return)}</td><td class="num">${pct(r['contrib_159696.SZ'])}</td><td class="num">${pct(r['contrib_510300.SH'])}</td><td class="num">${pct(r['contrib_518880.SH'])}</td><td class="num">${pct(r.fee_return)}</td></tr>`).join('');
frozenChart=window.TriPerformance.chart($('frozenCharts'),b);
}
function renderPerformance(p){
$('trackingSummary').innerHTML=window.TriPerformance.metrics(p.metrics);
$('trackingDate').textContent=`截至 ${p.end} · 每日18:10更新`;
$('trackingNote').textContent=`${p.start} — ${p.end}｜${p.frozen_end}及以前为冻结回测，之后为同规则模型跟踪；每日收盘重算全区间指标，不是账户实盘。${p.status==='PASS'?'':' 当前更新受限，保留最近有效数据；请查看上方提示。'}`;
if(trackingChart)trackingChart.update(p);else trackingChart=window.TriPerformance.chart($('trackingCharts'),p,'tracking');
const selected=$('yearFilter').value;$('yearFilter').innerHTML='<option value="">全部年份</option>'+[...new Set(p.dates.map(d=>d.slice(0,4)))].reverse().map(y=>`<option>${y}</option>`).join('');$('yearFilter').value=selected;
}
async function refresh(){if(busy||document.hidden)return;busy=true;$('refreshButton').disabled=true;try{
const [newLive,newHistory]=await Promise.all([json('live'),json('history')]);if(newLive.version!==version||newHistory.version!==version)throw Error('模型版本不一致');
if(!performance||performance.run_id!==newLive.run_id){
const next=await json('performance');if(next.version!==version||next.run_id!==newLive.run_id||next.end!==newLive.data_as_of)throw Error('业绩与信号批次不一致');
performance=next;renderPerformance(performance);
}
live=newLive;history=newHistory.records;
const response=await request(`https://qt.gtimg.cn/q=sz159696,sh510300,sh518880&_=${Date.now()}`,12000);quotes=core.parseQuotes(new TextDecoder('gbk').decode(await response.arrayBuffer()));if(!core.codes.every(c=>quotes[c]))throw Error('ETF报价不完整');networkOk=true;
const times=Object.values(quotes).map(q=>q.timestamp).sort(),stamp=times.at(-1),cn=core.chinaTime(new Date());$('quoteStatus').textContent=cn.time>='15:00:00'?`收盘后参考报价 ${stamp.slice(8,10)}:${stamp.slice(10,12)}:${stamp.slice(12,14)}`:`公开行情 ${stamp.slice(8,10)}:${stamp.slice(10,12)}:${stamp.slice(12,14)} · ${$('refreshInterval').value}秒刷新`;$('quoteStatus').className=cn.time>='15:00:00'?'offline':'live';
}catch(e){networkOk=false;$('quoteStatus').textContent=`更新失败，暂停可执行提示 · ${e.message}`;$('quoteStatus').className='offline';}finally{busy=false;$('refreshButton').disabled=false;renderSignal();renderHistory();}}
function schedule(){clearInterval(timer);timer=setInterval(refresh,Number($('refreshInterval').value)*1000);}
$('refreshButton').onclick=refresh;$('refreshInterval').onchange=()=>{schedule();refresh();};document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
$('capitalAmount').oninput=renderSizing;
for(const id of ['originFilter','assetFilter','yearFilter'])$(id).onchange=()=>{page=0;renderHistory();};$('previousPage').onclick=()=>{page--;renderHistory();};$('nextPage').onclick=()=>{page++;renderHistory();};
$('detailsButton').onclick=()=>{$('detailsDialog').showModal();frozenChart?.draw();};$('closeDetails').onclick=()=>$('detailsDialog').close();$('detailsDialog').onclick=e=>{if(e.target===$('detailsDialog'))$('detailsDialog').close();};
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-selected',String(b===button));});$('rulesPanel').hidden=button.dataset.tab!=='rules';$('backtestPanel').hidden=button.dataset.tab!=='backtest';frozenChart?.draw();});
setInterval(renderSignal,1000);
(async()=>{try{backtest=await json('backtest');if(backtest.version!==version)throw Error('回测版本不一致');details();await refresh();schedule();}catch(e){$('dataWarning').hidden=false;$('dataWarning').textContent='策略数据加载失败：'+e.message;$('quoteStatus').textContent='未就绪，暂停可执行提示';}})();
})();
