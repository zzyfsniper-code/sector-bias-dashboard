const shareRequest = (() => {
  const host = 'https://tuoshui-portfolio-view.pages.dev';
  const storageKey = 'tuoshui.viewer.session';
  let session = '';
  try { session = sessionStorage.getItem(storageKey) || ''; } catch {}
  function remember(value) {
    session = value;
    try {
      if (value) sessionStorage.setItem(storageKey, value);
      else sessionStorage.removeItem(storageKey);
    } catch {}
  }
  return async (path, options = {}) => {
    const headers = new Headers(options.headers);
    const login=path.split('?')[0]==='/api/login';
    if(login)headers.set('Content-Type','text/plain;charset=UTF-8');
    if (!login) {
      if (!session) return new Response(null, {status: 401});
      headers.set('Authorization', 'Bearer ' + session);
    }
    if (path === '/api/logout') remember('');
    const reply = await fetch(host + path.replace('/api/', '/share/'), {
      ...options, headers, cache: 'no-store', credentials: 'omit', redirect: 'error',
    });
    if (login && reply.ok) {
      const data = await reply.json();
      if (!/^[a-f0-9]{64}$/.test(data.session)) throw Error('登录响应异常');
      remember(data.session);
      return Response.json({ok:true,board:data.board});
    } else if (reply.status === 401 || (path === '/api/logout' && reply.ok)) {
      remember('');
    }
    return reply;
  };
})();

(()=>{'use strict';let data,orderPage=0,chartRows=[],chartIndex=-1;const chartIds=['navChart','drawdownChart','regimeChart','holdingsChart'];const $=id=>document.getElementById(id),pct=v=>Number.isFinite(v)?(v*100).toFixed(2)+'%':'—',num=v=>Number.isFinite(v)?v.toFixed(2):'—',roles={legacy:'趋势仓',dividend:'红利低波',attack:'进攻仓'},stages=['强势','普通弱势','抄底'];
const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
function stockCell(code,name){const td=el('td');td.append(el('strong',name||code),el('small',code));return td}
function cell(row,value,cls){row.append(el('td',value,cls))}
function empty(body,n){const tr=el('tr'),td=el('td','此范围没有记录','empty');td.colSpan=n;tr.append(td);body.append(tr)}
function download(name,rows){const columns=Object.keys(rows[0]||{}),csv='\ufeff'+[columns,...rows.map(r=>columns.map(k=>r[k]))].map(a=>a.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n'),u=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=el('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}
function orderAction(r){if(r.reason==='trim')return '集中度减仓';if(r.side==='buy')return r.new_position?'新建仓':'加仓';if(r.full_exit!==undefined)return r.full_exit?'清仓':'减仓';return (data.holdings[r.date.slice(0,10)]||[]).some(h=>h.code===r.ts_code)?'减仓':'清仓'}
function recentOrders(){
    const days=data.series.filter(r=>r.date<=$('snapshotDate').value).slice(-10).map(r=>r.date),window=new Set(days),rows=data.orders.filter(r=>window.has(r.date.slice(0,10))).slice().sort((a,b)=>b.date.localeCompare(a.date)||a.ts_code.localeCompare(b.ts_code)),body=$('recentOrderRows');
    $('recentOrderRange').textContent=days.length?days[0]+' — '+days.at(-1)+' · '+days.length+' 个交易日':'暂无交易日数据';$('recentOrderCount').textContent=rows.length+' 条';body.replaceChildren();
    for(const r of rows){const date=r.date.slice(0,10),action=orderAction(r),tr=el('tr');tr.dataset.date=date;tr.dataset.code=r.ts_code;cell(tr,date);tr.append(stockCell(r.ts_code,r.name));cell(tr,action,r.side==='buy'?'up':'down');cell(tr,pct(r.weight_change),'num');cell(tr,num(r.raw_close),'num');cell(tr,r.in_pool?'是':'否');body.append(tr)}
    if(!rows.length)empty(body,6);
    $('recentOrders').scrollTop=0;
}
function overview(){const date=$('snapshotDate').value,rows=[...(data.holdings[date]||[])].sort((a,b)=>b.weight-a.weight),s=data.series.find(x=>x.date===date),b=$('holdings');b.replaceChildren();$('holdingCount').textContent=rows.length+'只';for(const r of rows){const tr=el('tr');tr.append(stockCell(r.code,r.name));const td=el('td');td.append(el('span',roles[r.role]||r.role,'badge '+(r.role==='dividend'?'defensive':r.role)));tr.append(td);cell(tr,pct(r.weight),'num');cell(tr,r.entry);cell(tr,num(r.price),'num');cell(tr,pct(r.pnl),'num '+(r.pnl>=0?'up':'down'));cell(tr,r.in_pool?'池内':'已退池 · 延续持有');b.append(tr)}if(!rows.length)empty(b,7);$('stage').textContent=date+' · '+stages[s.stage];$('allocation').replaceChildren();[['趋势仓',s.legacy_exposure,'#91392d'],['红利低波',s.style_exposure,'#467367'],['进攻仓',s.attack_exposure,'#b98d49'],['现金',1-s.exposure,'#c6c9cb']].forEach(([name,v,color])=>{const row=el('div',undefined,'alloc-row'),label=el('div',undefined,'alloc-label'),bar=el('div',undefined,'bar'),fill=el('i');label.append(el('span',name),el('strong',pct(v)));fill.style.width=Math.max(0,Math.min(100,v*100))+'%';fill.style.background=color;bar.append(fill);row.append(label,bar);$('allocation').append(row)});recentOrders()}
function pool(){const query=$('poolSearch').value.trim().toLowerCase(),scope=$('poolScope').value,rows=data.pool.filter(r=>(r.code+r.name+(r.last_article_title||'')).toLowerCase().includes(query)&&(scope==='all'||scope==='held'&&r.held||scope==='candidate'&&(r.defensive||r.attack||r.trend))),body=$('poolRows');body.replaceChildren();for(const r of rows){const tr=el('tr');tr.dataset.code=r.code;tr.append(stockCell(r.code,r.name));cell(tr,r.held?'持仓':r.signal);cell(tr,r.trend?'符合':'—');cell(tr,r.defensive?'符合':'—');cell(tr,r.attack?'符合':'—');cell(tr,num(r.price),'num');cell(tr,r.can_buy?'可买':'受限');cell(tr,r.last_published_ts?new Date(r.last_published_ts*1000).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'}):'—');const article=el('td',undefined,'article-title');article.append(el('span',r.last_article_title||'文章标题暂缺'),el('small','文章 '+r.last_article_id));tr.append(article);body.append(tr)}if(!rows.length)empty(body,9);$('poolMatch').textContent='显示 '+rows.length+' / '+data.pool.length+' 只'}
function orders(){const query=$('orderSearch').value.trim().toLowerCase(),from=$('orderFrom').value,to=$('orderTo').value,side=$('orderSide').value,rows=data.orders.filter(r=>(r.ts_code+r.name).toLowerCase().includes(query)&&(!from||r.date>=from)&&(!to||r.date<=to)&&(!side||r.side===side)).slice().reverse(),pages=Math.max(1,Math.ceil(rows.length/40));orderPage=Math.min(orderPage,pages-1);const body=$('orderRows');body.replaceChildren();for(const r of rows.slice(orderPage*40,(orderPage+1)*40)){const tr=el('tr');cell(tr,r.date.slice(0,10));tr.append(stockCell(r.ts_code,r.name));cell(tr,orderAction(r),r.side==='buy'?'up':'down');cell(tr,pct(r.weight_change),'num');cell(tr,num(r.raw_close),'num');cell(tr,r.in_pool?'是':'否');body.append(tr)}if(!rows.length)empty(body,6);$('orderCount').textContent=rows.length+' 笔流水 · 第 '+(orderPage+1)+' / '+pages+' 页';$('previous').disabled=orderPage===0;$('next').disabled=orderPage>=pages-1;if($('lastPage')){$('firstPage').disabled=orderPage===0;$('lastPage').disabled=orderPage>=pages-1;$('lastPage').onclick=()=>{orderPage=pages-1;orders()}}}
function chart(){
    if(!data||!$('navChart').offsetWidth)return;
    const cursor=chartRows[chartIndex]?.date||$('snapshotDate').value,range=$('period').value,start=range==='all'?null:new Date(new Date(data.as_of).valueOf()-Number(range)*864e5);
    chartRows=data.series.filter(x=>!start||new Date(x.date)>=start);
    if(!chartRows.length){$('chartTip').textContent='此范围没有记录';return}
    chartIndex=chartRows.findIndex(r=>r.date===cursor);if(chartIndex<0)chartIndex=chartRows.length-1;
    const a=chartRows[0],current=chartRows[chartIndex],values=chartRows.flatMap(r=>[r.nav/a.nav,r.benchmark_nav/a.benchmark_nav]);
    $('chartTip').textContent=current.date+' · 全期净值 '+current.nav.toFixed(4)+' · 实际仓位 '+pct(current.exposure);
    $('navValue').textContent=(current.nav/a.nav).toFixed(4);$('drawdownValue').textContent=pct(current.drawdown)+' / '+pct(current.max_drawdown);$('regimeValue').textContent=stages[current.stage];$('holdingsValue').textContent=current.holdings+' 只';
    for(const id of chartIds){
        const canvas=$(id),box=canvas.getBoundingClientRect(),ratio=window.devicePixelRatio||1;canvas.width=box.width*ratio;canvas.height=box.height*ratio;
        const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);
        const l=48,r=14,t=12,b=27,w=box.width-l-r,h=box.height-t-b,xx=i=>l+i*w/Math.max(1,chartRows.length-1);
        canvas.dataset.startDate=a.date;canvas.dataset.endDate=chartRows.at(-1).date;canvas.dataset.cursorDate=current.date;
        ctx.font='10px system-ui';ctx.lineWidth=1;
        if(id==='regimeChart'){
            const colors=['#91392d','#648b80','#b2883d'],rowHeight=h/3;
            for(let stage=0;stage<3;stage++){ctx.fillStyle='#fafaf7';ctx.fillRect(l,t+stage*rowHeight,w,rowHeight-2);ctx.fillStyle='#727b85';ctx.fillText(['强势','弱势','抄底'][stage],4,t+(stage+.5)*rowHeight+3)}
            chartRows.forEach((row,i)=>{const left=i===0?l:(xx(i-1)+xx(i))/2,right=i===chartRows.length-1?l+w:(xx(i)+xx(i+1))/2;ctx.fillStyle=colors[row.stage];ctx.fillRect(left,t+row.stage*rowHeight,Math.max(.5,right-left),rowHeight-2)});
        }else{
            const lo=id==='navChart'?Math.min(...values)*.96:id==='drawdownChart'?Math.min(-.01,...chartRows.map(r=>r.max_drawdown))*1.05:0;
            const hi=id==='navChart'?Math.max(...values)*1.04:id==='drawdownChart'?0:Math.max(8,...chartRows.map(r=>r.holdings));
            const yy=v=>t+(hi-v)/(hi-lo)*h,ticks=id==='navChart'||id==='holdingsChart'?4:2;
            for(let i=0;i<=ticks;i++){const v=lo+(hi-lo)*i/ticks,y=yy(v);ctx.strokeStyle='#eeefeb';ctx.beginPath();ctx.moveTo(l,y);ctx.lineTo(l+w,y);ctx.stroke();ctx.fillStyle='#727b85';ctx.fillText(id==='drawdownChart'?(v*100).toFixed(1)+'%':id==='holdingsChart'?v.toFixed(0):v.toFixed(2),1,y+3)}
            const lines=id==='navChart'?[['benchmark_nav','#aab4bd',false],['nav','#91392d',false]]:id==='drawdownChart'?[['drawdown','#277363',false],['max_drawdown','#8d979c',true]]:[['holdings','#496987',false]];
            for(const [key,color,dashed] of lines){ctx.strokeStyle=color;ctx.lineWidth=key==='benchmark_nav'?1.2:1.6;ctx.setLineDash(dashed?[4,3]:[]);ctx.beginPath();chartRows.forEach((row,i)=>{const v=id==='navChart'?row[key]/a[key]:row[key];if(i){if(id==='holdingsChart')ctx.lineTo(xx(i),yy(chartRows[i-1][key]));ctx.lineTo(xx(i),yy(v))}else ctx.moveTo(xx(i),yy(v))});ctx.stroke();ctx.setLineDash([]);const v=id==='navChart'?current[key]/a[key]:current[key];ctx.fillStyle=color;ctx.beginPath();ctx.arc(xx(chartIndex),yy(v),2.7,0,Math.PI*2);ctx.fill()}
        }
        ctx.strokeStyle='#b1896d';ctx.lineWidth=1;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(xx(chartIndex),t);ctx.lineTo(xx(chartIndex),t+h);ctx.stroke();ctx.setLineDash([]);
        ctx.fillStyle='#727b85';ctx.fillText(a.date,l,box.height-4);ctx.fillText(chartRows.at(-1).date,box.width-76,box.height-4);
    }
}
function inspectChart(event,commit=false){if(!chartRows.length)return;const box=event.currentTarget.getBoundingClientRect();chartIndex=Math.round(Math.max(0,Math.min(1,(event.clientX-box.left-48)/(box.width-62)))*(chartRows.length-1));chart();if(commit){$('snapshotDate').value=chartRows[chartIndex].date;overview()}}
function snapshotChanged(){overview();const date=$('snapshotDate').value;if(!chartRows.some(r=>r.date===date))$('period').value='all';chartRows=[];chartIndex=-1;chart()}
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==button.dataset.tab);chart()});$('snapshotDate').onchange=snapshotChanged;$('period').onchange=chart;['poolSearch','poolScope'].forEach(id=>$(id).oninput=pool);['orderSearch','orderFrom','orderTo','orderSide'].forEach(id=>$(id).oninput=()=>{orderPage=0;orders()});$('previous').onclick=()=>{orderPage--;orders()};$('next').onclick=()=>{orderPage++;orders()};$('downloadPool').onclick=()=>download('股票池_'+data.as_of+'.csv',data.pool);$('downloadOrders').onclick=()=>download('调仓历史.csv',data.orders);window.addEventListener('resize',chart);for(const id of chartIds){const canvas=$(id);canvas.onpointermove=e=>inspectChart(e);canvas.onclick=e=>inspectChart(e,true);canvas.onkeydown=e=>{if(!chartRows.length)return;if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();chartIndex=e.key==='Home'?0:e.key==='End'?chartRows.length-1:Math.max(0,Math.min(chartRows.length-1,chartIndex+(e.key==='ArrowRight'?1:-1)));chart()}else if(e.key==='Enter'){e.preventDefault();$('snapshotDate').value=chartRows[chartIndex].date;overview()}}}

$('firstPage').onclick=()=>{orderPage=0;orders()};
window.setPortfolioArchive=function(a){
 const oldDate=$('snapshotDate').value,wasLatest=!data||oldDate===data.as_of;
 const series=a.series.map(([date,nav,benchmark_nav,drawdown,max_drawdown,stage,holdings,exposure,legacy_exposure,style_exposure,attack_exposure])=>
   ({date,nav,benchmark_nav,drawdown,max_drawdown,stage,holdings,exposure,legacy_exposure,style_exposure,attack_exposure}));
 const holdings={};
 for(const [date,code,name,role,weight,entry,price,pnl,in_pool] of a.weights){
   (holdings[date]??=[]).push({code,name,role,weight,entry,price,pnl,in_pool});
 }
 const stocks=a.pool.map(([code,name,last_article_title,last_published_ts,last_article_id,price,can_buy,held,trend,defensive,attack])=>
   ({code,name,last_article_title,last_published_ts,last_article_id,price,can_buy,held,trend,defensive,attack,signal:trend||defensive||attack?'候选':'观察'}));
 const ledger=a.orders.map(([date,ts_code,name,side,weight_change,raw_close,in_pool,new_position,full_exit,reason])=>
   ({date,ts_code,name,side,weight_change,raw_close,in_pool,new_position,full_exit,reason}));
 const previousDay=data?.as_of;
 data={as_of:a.as_of,series,holdings,pool:stocks,orders:ledger};
 $('snapshotDate').replaceChildren(...series.slice().reverse().map(r=>new Option(r.date,r.date)));
 $('snapshotDate').value=wasLatest?a.as_of:oldDate;
 if(!$('snapshotDate').value)$('snapshotDate').value=a.as_of;
 $('poolDate').textContent='截至 '+a.as_of+' · 当前阶段的可接管名单';
 $('poolCount').textContent=stocks.length+' 只';
 if(!previousDay)$('orderFrom').value=series[0].date;
 if(!previousDay||$('orderTo').value===previousDay)$('orderTo').value=a.as_of;
 for(const id of ['orderFrom','orderTo']){$(id).min=series[0].date;$(id).max=a.as_of}
 $('reportPeriod').textContent=series[0].date+' — '+a.as_of+' · '+series.length+' 个交易日';
 const yearly=[];let prev=1,bench=1,start=1,startBench=1,peak=1,dd=0;
 series.forEach((r,i)=>{
   const year=r.date.slice(0,4);
   if(!i||series[i-1].date.slice(0,4)!==year){start=prev;startBench=bench;peak=prev;dd=0}
   peak=Math.max(peak,r.nav);dd=Math.min(dd,r.nav/peak-1);prev=r.nav;bench=r.benchmark_nav;
   if(i===series.length-1||series[i+1].date.slice(0,4)!==year)yearly.push([year,pct(prev/start-1),pct(bench/startBench-1),pct(dd)]);
 });
 window.renderLiveTable('yearly',['年份','组合收益','中证全指','组合最大回撤'],yearly);
 chartRows=[];chartIndex=-1;overview();pool();orders();chart();
};

})();
'use strict';
const byId=id=>document.getElementById(id);
const stagesLive=['强势','普通弱势','抄底'],rolesLive={legacy:'趋势',dividend:'红利',attack:'进攻'};
const percent=v=>Number.isFinite(v)?(v*100).toFixed(2)+'%':'—';
function dayChange(price,prev,ts,day){
 if(!Number.isFinite(price)||!Number.isFinite(prev)||price<=0||prev<=0||!day||ts?.slice(0,8)!==day.replaceAll('-',''))return '—';
 const change=(price-prev)/prev;
 return (change>0?'+':'')+percent(change);
}
function cnTime(v){
 if(!v)return '—';
 if(/^\d{14}$/.test(v))return v.slice(0,4)+'-'+v.slice(4,6)+'-'+v.slice(6,8)+' '+v.slice(8,10)+':'+v.slice(10,12)+':'+v.slice(12);
 const time=new Date(v);
 return Number.isFinite(+time)?time.toLocaleString('sv-SE',{timeZone:'Asia/Shanghai',hour12:false}):'—';
}
window.renderLiveTable=function(id,labels,rows){
 const container=byId(id);
 container.replaceChildren();
 if(!rows.length)return;
 const wrap=document.createElement('div'),tab=document.createElement('table');wrap.className='table-wrap';wrap.append(tab);container.append(wrap);
 const head=tab.createTHead().insertRow();for(const label of labels){const th=document.createElement('th');th.textContent=label;head.append(th)}
 const body=tab.createTBody();for(const row of rows){const tr=body.insertRow();row.forEach((value,i)=>{
   const td=tr.insertCell();td.textContent=value;
   if(labels[i]==='当日涨跌幅')td.className=value.startsWith('+')?'up':value.startsWith('-')?'down':'';
 })}
};
let busy=false,revision='',shown='',loading='';
function requestBoard(view){return shareRequest('/api/board?view='+view,{cache:'no-store',signal:AbortSignal.timeout(90000)})}
function signedOut(){
 revision='';shown='';byId('archivePanels').hidden=true;byId('board').hidden=true;byId('logout').hidden=true;byId('login').hidden=false;
 byId('error').textContent='';byId('loginStatus').textContent='';
}
async function archive(d){
 const key=d.display_revision;
 if(!d.has_archive){byId('archiveStatus').textContent='等待此收盘日期的完整历史资料';return}
 if(key===loading||key===shown)return;
 loading=key;byId('archiveStatus').textContent='正在读取组合走势、历史持仓和调仓流水…';
 try{
   const res=await requestBoard('archive');
   if(revision!==key)return;
   if(res.status===401){signedOut();return}
   if(!res.ok)throw Error();
   const a=await res.json();if(revision!==key)return;
   if(a.display_revision!==key){byId('archiveStatus').textContent='有新收盘数据，正在重新读取…';setTimeout(()=>refresh(),0);return}
   byId('archivePanels').hidden=false;window.setPortfolioArchive(a);shown=key;byId('archiveStatus').textContent='';
 }catch{if(revision===key){byId('archiveStatus').textContent='历史资料暂未取到，点击重新读取可重试。';byId('loadRetry').hidden=false}}
 finally{if(loading===key)loading=''}
}
function update(d){
 byId('board').hidden=false;byId('logout').hidden=false;byId('login').hidden=true;byId('error').textContent='';
 byId('asof').textContent=d.as_of;byId('nav').textContent=d.nav.toFixed(4);
 const m=d.metrics||{};
 const cards=[['累计收益',percent(m.cumulative_return)],['年化收益',percent(m.cagr)],['夏普比率',m.sharpe?.toFixed(2)??'—'],['卡玛比率',m.calmar?.toFixed(2)??'—'],
   ['最大回撤',percent(m.mdd)],['持仓数量',d.holdings.length+' 只'],['实际仓位',percent(d.exposure)],['基础股票池',d.pool_count+' 只']];
 byId('metrics').replaceChildren(...cards.map(([label,value])=>{const box=document.createElement('div');box.className='metric';const span=document.createElement('span'),strong=document.createElement('strong');span.textContent=label;strong.textContent=value;box.append(span,strong);return box}));
 const stamp=d.holdings.map(x=>x.quote_time).filter(Boolean).sort().at(-1);
 const last=d.ticks.at(-1),valid=d.ticks.filter(x=>x.status==='estimated').at(-1),min=d.server_minute;
 byId('quoteAt').textContent=cnTime(stamp);byId('estimateAt').textContent=valid?cnTime(valid.generated):'今日暂无';
 byId('confirmedAt').textContent=cnTime(d.confirmed_at);byId('checkedAt').textContent=cnTime(d.checked_at);
 const live=d.server_day===d.session&&((min>=570&&min<=690)||(min>=780&&min<900));
 const stale=live&&(!d.quote_batch_at||Date.parse(d.checked_at)-Date.parse(d.quote_batch_at)>4*60000);
 byId('streamState').textContent=stagesLive[d.stage]+' · '+(live?(stale?'尚未收到最近一轮持仓行情，请核对每只股票的报价时间':'交易时段，持仓报价按本机采集批次更新'):d.server_day===d.session&&min<570?'尚未开盘，显示最近收盘或已取得的报价':d.server_day===d.as_of?'当日正式收盘已确认':'当前为非连续交易时段')+'。';
 const steps={processing:'正在处理',daily:'等待股票日线',basic:'等待每日指标',limits:'等待涨跌停价',index:'等待基准指数',industry:'等待行业收盘',themes:'等待主题收盘',wind:'等待全指股息率',credit:'等待贷款数据',rates:'等待国债数据',articles:'等待脱水文章',upload:'等待上传',validation:'等待账本核对'};
 const notice=byId('closeProgress'),note=d.close_note;
 const wait=note&&note.day>d.as_of?note.day+' 正式收盘 · '+steps[note.step]+' · '+cnTime(note.asof):
   d.server_day>=d.session&&(d.server_day>d.session||min>=902)?'等待本机上传新的正式收盘结果':'';
 notice.hidden=!wait;notice.textContent=wait;
 let status='';let rows=[];
 if(last){
   const when=cnTime(last.generated);
   if(last.status==='estimated'){
     rows=last.orders.map(x=>[x.name+' '+x.code,x.after>x.before?'买入':'卖出',percent(x.before),percent(x.after),dayChange(x.price,x.prev_close,x.ts,last.day),cnTime(x.ts)]);
     status=when+' · '+(rows.length?'预计调仓 '+rows.length+' 只':'预计无需调仓');
   }else status=when+' · 本轮未形成名单，'+last.reason;
   if(min>=900)status+='（盘中记录）';
   else if(last.slot<Math.min(898,2*Math.floor((min-1)/2)))status+=' · 最新一轮尚未收到';
 }else status=d.server_day===d.session?(min<880?'今日 14:40 开始产生预计调仓':'今日暂未收到预计调仓记录'):'今日暂无预计调仓记录。下一次已知交易日 '+d.session;
 byId('status').textContent=status;
 renderLiveTable('changes',['股票','方向','调仓前','预计调仓后','当日涨跌幅','估算用行情时间'],rows);
 renderLiveTable('ticks',['生成时间','行情截至','结果'],d.ticks.map(x=>[cnTime(x.generated),cnTime(x.asof),x.status==='estimated'?'完成 · '+x.orders.length+' 只':x.reason]));
 renderLiveTable('quotes',['股票','代码','仓位身份','收盘权重','最近报价','当日涨跌幅','行情时间'],d.holdings.map(x=>[x.name,x.code,rolesLive[x.kind],percent(x.weight),x.price?.toFixed(2)??'—',dayChange(x.price,x.prev_close,x.quote_time,d.server_day),cnTime(x.quote_time)]));
 if(!d.holdings.length)byId('quotes').textContent='该收盘日空仓';
 const e=d.economy_note;byId('economyMeta').hidden=!e;
 if(e)byId('economyMeta').textContent='中长期贷款同比 '+e.growth.toFixed(2)+'%（'+e.month+'）　十年期国债：中国 '+e.cn10.toFixed(2)+'%（'+e.cn_day+'），美国 '+e.us10.toFixed(2)+'%（'+e.us_day+'）';
 if(revision!==d.display_revision){revision=d.display_revision;byId('archivePanels').hidden=true}
 void archive(d);
}
async function refresh(initial=null){
 if(busy)return;busy=true;byId('loadRetry').hidden=true;
 try{
   if(!initial){const res=await requestBoard('summary');if(res.status===401){signedOut();return}if(!res.ok)throw Error();initial=await res.json()}
   update(initial);
 }catch{byId('error').textContent='本次取数未完成，请核对页面所示的数据时间。';byId('loadRetry').hidden=false}
 finally{busy=false}
}
byId('login').onsubmit=async event=>{
 event.preventDefault();const button=event.currentTarget.querySelector('button');if(button.disabled)return;button.disabled=true;byId('loginStatus').textContent='正在验证密码…';
 try{const r=await shareRequest('/api/login?view=summary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:byId('pass').value}),signal:AbortSignal.timeout(90000)});
   if(!r.ok){byId('loginStatus').textContent=r.status===401?'密码错误，请重新输入':r.status===429?'登录次数已达上限，请稍后重试':'登录服务暂不可用';return}
   byId('pass').value='';byId('loginStatus').textContent='';byId('login').hidden=true;await refresh((await r.json()).board);
 }catch{byId('loginStatus').textContent='未能连接登录服务，请重试'}finally{button.disabled=false}
};
byId('logout').onclick=async()=>{try{await shareRequest('/api/logout',{method:'POST',signal:AbortSignal.timeout(15000)})}finally{location.reload()}};
byId('refresh').onclick=()=>refresh();byId('loadRetry').onclick=()=>refresh();
refresh();setInterval(()=>{if(!document.hidden&&!byId('board').hidden)refresh()},30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!byId('board').hidden)refresh()});
