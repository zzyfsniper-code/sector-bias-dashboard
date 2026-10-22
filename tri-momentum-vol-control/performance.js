/* One renderer for the daily main-page series and the immutable detail backtest. */
(function(){
'use strict';
const names={'cash_t14_v20':'三元动量波控','baseline_three':'三资产无波控','hold_159696.SZ':'纳指长期持有','hold_510300.SH':'沪深300长期持有','hold_518880.SH':'黄金长期持有'};
const colors={'cash_t14_v20':'#8b2e24','baseline_three':'#a88f68','hold_159696.SZ':'#304e60','hold_510300.SH':'#8a9590','hold_518880.SH':'#bc8c2a'};
const assets={'159696.SZ':['纳指ETF易方达','#304e60'],'510300.SH':['沪深300ETF','#8a9590'],'518880.SH':['黄金ETF','#bc8c2a'],cash:['现金','#dfd9cf']};
const pct=(x,d=2)=>Number.isFinite(x)?`${(x*100).toFixed(d)}%`:'—',number=x=>Number.isFinite(x)?x.toFixed(3):'—';
function metrics(m){
 const rows=[['年化收益',pct(m.annual_return),'已扣单边10bp'],['最大回撤',pct(-m.max_drawdown),'历史最大净值回落'],['夏普比率',number(m.sharpe_rf0),'无风险利率按0'],['Calmar比率',number(m.calmar),'年化收益 / 最大回撤'],['累计收益',pct(m.cumulative_return),'模型收益 · 非实盘'],['最长水下期',m.longest_underwater_days_exact+'天','严格口径 · 日历天'],['实际年化波动',pct(m.annual_volatility),'不等于14%目标'],['平均风险仓位',pct(m.mean_core_exposure),'剩余现金收益按0']];
 return '<div class="metric-grid">'+rows.map(r=>`<div><span>${r[0]}</span><strong>${r[1]}</strong><small>${r[2]}</small></div>`).join('')+'</div>';
}
function chart(root,initial,prefix=''){
 let data=initial,lo=0,hi=data.dates.length-1;
 const id=name=>prefix+name,$=name=>root.querySelector('#'+id(name));
 root.innerHTML=`<div class="chart-toolbar"><h3>净值、回撤与历史持仓</h3><label>区间 <select id="${id('chartPeriod')}"><option value="all">全部</option></select></label></div><div id="${id('chartLegend')}" class="legend"></div><div id="${id('chartStack')}" class="chart-stack"><div class="plot" id="${id('navChart')}" aria-label="策略与基准净值"></div><div class="plot" id="${id('drawdownChart')}" aria-label="策略回撤"></div><div class="plot" id="${id('riskChart')}" aria-label="风险仓位"></div><div class="legend holdings-legend">${Object.values(assets).map(([name,color])=>`<span><i style="background:${color}"></i>${name}</span>`).join('')}</div><div class="plot" id="${id('assetChart')}" aria-label="历史收盘持仓资产"></div><div id="${id('chartTooltip')}" class="chart-tooltip" hidden></div></div><div class="range-controls"><label>起点 <input id="${id('rangeStart')}" aria-label="区间起点" type="range" min="0" value="0"></label><label>终点 <input id="${id('rangeEnd')}" aria-label="区间终点" type="range" min="0"></label></div><div id="${id('rangeLabel')}" class="footnote"></div>`;
 $('chartLegend').innerHTML=Object.keys(names).map(key=>`<span><i style="background:${colors[key]}"></i>${names[key]}</span>`).join('');
 function hide(){ $('chartTooltip').hidden=true;root.querySelectorAll('.crosshair').forEach(p=>p.setAttribute('hidden','')); }
 function draw(){
  if(!root.getClientRects().length)return;
  const keys=Object.keys(names),w=Math.max(270,$('chartStack').clientWidth),left=w<500?42:50,right=15,width=w-left-right,points=hi-lo;
  let max=1,min=1;
  for(const key of keys){const series=data.curves[key].nav,base=series[lo];for(let i=lo;i<=hi;i++){max=Math.max(max,series[i]/base);min=Math.min(min,series[i]/base);}}
  const span=Math.max(.1,max-min);max+=span*.06;min-=span*.06;
  for(const [name,h,label,bounds] of [['navChart',225,'区间净值',null],['drawdownChart',120,'策略回撤',[-.3,0]],['riskChart',100,'风险仓位',[0,1]],['assetChart',130,'收盘持仓资产（模型）',[0,1]]]){
   const top=22,bottom=name==='assetChart'?24:12,values=name==='drawdownChart'?data.curves.cash_t14_v20.drawdown:name==='riskChart'?data.risk_exposure:null;
   let low=bounds?.[0]??min,high=bounds?.[1]??max;
   if(name==='drawdownChart')low=Math.min(-.05,...values.slice(lo,hi+1))*1.12;
   const x=i=>left+(i-lo)/points*width,y=v=>top+(high-v)/(high-low)*(h-top-bottom);
   let svg=`<text x="${left}" y="13">${label}</text>`;
   for(let j=0;j<3;j++){const value=low+(high-low)*j/2,yy=y(value);svg+=`<path class="grid" d="M${left},${yy}H${w-right}"/><text x="3" y="${yy+4}">${name==='navChart'?value.toFixed(1):pct(value,0)}</text>`;}
   if(name==='assetChart'){
    if(data.asset_weights){
     let lower=Array(points+1).fill(0);
     for(const [code,[,color]] of Object.entries(assets)){
      const upper=lower.map((v,j)=>v+data.asset_weights[code][lo+j]);
      let path=`M${x(lo)},${y(upper[0])}`;
      for(let j=0;j<=points;j++)path+=`${j?'V'+y(upper[j]):''}H${x(Math.min(hi,lo+j+.5))}`;
      path+=`V${y(lower[points])}`;
      for(let j=points;j>=0;j--)path+=`${j<points?'V'+y(lower[j]):''}H${x(Math.max(lo,lo+j-.5))}`;
      svg+=`<path class="asset-area" d="${path}Z" fill="${color}"/>`;lower=upper;
     }
    }else svg+=`<text x="${left}" y="55">持仓数据待更新</text>`;
   }else for(const key of name==='navChart'?keys:['cash_t14_v20']){
    const series=name==='navChart'?data.curves[key].nav:values,base=name==='navChart'?series[lo]:1;
    const path=series.slice(lo,hi+1).map((v,j)=>`${j?'L':'M'}${x(lo+j).toFixed(2)},${y(v/base).toFixed(2)}`).join('');
    svg+=`<path d="${path}" fill="none" stroke="${name==='riskChart'?'#1f6b54':colors[key]}" stroke-width="${key==='cash_t14_v20'?2:1.25}"/>`;
   }
   if(name==='assetChart'){for(const [j,anchor] of [[0,'start'],[.5,'middle'],[1,'end']]){const i=Math.round(lo+points*j);svg+=`<text x="${x(i)}" y="${h-3}" text-anchor="${anchor}">${data.dates[i]}</text>`;}}
   $(name).innerHTML=`<svg viewBox="0 0 ${w} ${h}" height="${h}" role="img" aria-label="${label}">${svg}<path class="crosshair" hidden/></svg>`;
  }
  $('rangeLabel').textContent=`${data.dates[lo]} — ${data.dates[hi]}；区间净值归一，回撤保留完整历史前高。持仓为当日收盘后模型配置。拖动起点和终点查看区间。`;
 }
 $('chartStack').addEventListener('pointermove',e=>{
  const plot=e.target.closest('.plot');if(!plot)return;
  const rect=plot.getBoundingClientRect(),stack=$('chartStack'),w=rect.width,left=w<500?42:50,x=Math.max(left,Math.min(w-15,e.clientX-rect.left));
  const i=Math.max(lo,Math.min(hi,Math.round(lo+(x-left)/(w-left-15)*(hi-lo)))),actualX=left+(i-lo)/(hi-lo)*(w-left-15);
  root.querySelectorAll('.crosshair').forEach(p=>{p.removeAttribute('hidden');p.setAttribute('d',`M${actualX},20V${p.closest('svg').getAttribute('height')-14}`);});
  const tip=$('chartTooltip');tip.innerHTML=`<strong>${data.dates[i]}</strong>`+Object.keys(names).map(key=>`<div><span style="color:${colors[key]}">${names[key]}</span><b>${(data.curves[key].nav[i]/data.curves[key].nav[lo]).toFixed(3)}</b></div>`).join('')+`<div><span>策略回撤</span><b>${pct(data.curves.cash_t14_v20.drawdown[i])}</b></div><div><span>风险仓位</span><b>${pct(data.risk_exposure[i])}</b></div>`;
  if(data.asset_weights)tip.innerHTML+='<div>收盘持仓（模型）</div>'+Object.entries(assets).filter(([code])=>data.asset_weights[code][i]>1e-8||code==='cash').map(([code,[label,color]])=>`<div><span style="color:${code==='cash'?'#827a6b':color}">${label}</span><b>${pct(data.asset_weights[code][i])}</b></div>`).join('');
  tip.hidden=false;
  const gap=16,tw=tip.offsetWidth,th=tip.offsetHeight,sw=stack.clientWidth,sh=stack.clientHeight;
  let tx=actualX+gap+tw<=sw-4?actualX+gap:actualX-tw-gap,ty=Math.max(4,Math.min(sh-th-4,plot.offsetTop+10));
  if(tx<4){const mouseY=e.clientY-stack.getBoundingClientRect().top;tx=Math.max(4,Math.min(sw-tw-4,actualX-tw/2));ty=mouseY+gap+th<=sh-4?mouseY+gap:mouseY-th-gap;}
  tip.style.left=`${tx}px`;tip.style.top=`${Math.max(4,ty)}px`;
 });
 $('chartStack').addEventListener('pointerleave',hide);
 for(const name of ['rangeStart','rangeEnd'])$(name).oninput=()=>{
  lo=Number($('rangeStart').value);hi=Number($('rangeEnd').value);
  if(hi<lo+2){if(name==='rangeStart')lo=Math.max(0,hi-2);else hi=Math.min(data.dates.length-1,lo+2);}
  $('rangeStart').value=lo;$('rangeEnd').value=hi;$('chartPeriod').value='all';hide();draw();
 };
 $('chartPeriod').onchange=()=>{const year=$('chartPeriod').value;lo=year==='all'?0:data.dates.findIndex(d=>d>=year+'-01-01');hi=data.dates.length-1;$('rangeStart').value=lo;$('rangeEnd').value=hi;hide();draw();};
 function update(next){
  const atEnd=hi===data.dates.length-1;data=next;
  if(atEnd)hi=data.dates.length-1;
  for(const name of ['rangeStart','rangeEnd'])$(name).max=data.dates.length-1;
  $('rangeStart').value=lo;$('rangeEnd').value=hi;
  const selected=$('chartPeriod').value;
  $('chartPeriod').innerHTML='<option value="all">全部</option>'+[...new Set(data.dates.map(d=>d.slice(0,4)))].map(y=>`<option value="${y}">${y}年以来</option>`).join('');
  $('chartPeriod').value=selected;hide();draw();
 }
 window.addEventListener('resize',()=>{hide();draw();});update(initial);
 return {draw,update};
}
window.TriPerformance={metrics,chart};
})();
