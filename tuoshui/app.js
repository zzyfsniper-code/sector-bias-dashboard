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

'use strict';
const el=k=>document.getElementById(k),pct=x=>(x*100).toFixed(2)+'%',st=['强势','普通弱势','抄底'],role={legacy:'趋势',attack:'进攻',dividend:'红利'};
function table(id,labels,rows){
 const target=el(id);target.replaceChildren();if(!rows.length)return;
 const wrap=document.createElement('div'),tab=document.createElement('table');wrap.className='scroll';wrap.append(tab);target.append(wrap);
 for(const [i,line] of [labels,...rows].entries()){const tr=tab.insertRow();for(const val of line){const td=document.createElement(i?'td':'th');td.textContent=String(val);tr.append(td)}}
}
let busy=false;
let pool=[],detailRevision='',currentRevision='',loadingRevision='';
const poolDetails=el('poolTitle').parentElement;
function showPool(){const query=el('poolFilter').value.trim().toLowerCase();const rows=pool.filter(x=>(x.name+x.code+x.title).toLowerCase().includes(query));table('pool',['股票','最近提及','文章'],rows.map(x=>[x.name+' '+x.code,x.time,x.title]));if(!rows.length)el('pool').textContent='没有匹配的股票或文章'}
el('poolFilter').oninput=showPool;
poolDetails.ontoggle=()=>{if(poolDetails.open&&detailRevision)showPool()};
function requestBoard(full){return shareRequest('/api/board'+(full?'':'?view=summary'),{cache:'no-store',signal:AbortSignal.timeout(90000)})}
function drawDetails(d){
 pool=d.pool;detailRevision=d.display_revision||d.as_of;
 if(poolDetails.open)showPool();
 const a=d.history.map(x=>Math.log(x[1])),lo=Math.min(...a),hi=Math.max(...a),line=a.map((v,i)=>[(8+i/Math.max(1,a.length-1)*784).toFixed(1),(160-150*(v-lo)/(hi-lo||1)).toFixed(1)].join(',')).join(' '),svg=el('chart');
 svg.replaceChildren();const poly=document.createElementNS('http://www.w3.org/2000/svg','polyline');poly.setAttribute('fill','none');poly.setAttribute('stroke','#356d55');poly.setAttribute('stroke-width','2');poly.setAttribute('points',line);svg.append(poly);el('range').textContent=d.history[0][0]+' 至 '+d.as_of+' · 对数刻度';
}
async function loadDetails(revision){
 if(loadingRevision===revision)return;
 loadingRevision=revision;
 try{
  const r=await requestBoard(true);if(!r.ok)throw Error();
  const full=await r.json();
  if(currentRevision===revision&&(full.display_revision||full.as_of)===revision)drawDetails(full);
 }catch{if(currentRevision===revision){el('range').textContent='历史净值暂未取到，可点击刷新重试';el('pool').textContent='基础池暂未取到，可点击刷新重试'}}
 finally{if(loadingRevision===revision)loadingRevision=''}
}
async function refresh(initial=null){
 if(busy)return;busy=true;el('loadRetry').hidden=true;
 if(el('board').hidden)el('error').textContent='正在读取持仓和最新调仓记录…';
 try{
 let d=initial;
 if(!d){const res=await requestBoard(false);
 if(res.status===401){currentRevision='';el('board').hidden=true;el('login').hidden=false;el('loginStatus').textContent='';el('error').textContent='';return}
 if(!res.ok)throw Error('最新数据暂不可用，请稍后刷新。');d=await res.json()}
 el('error').textContent='';el('board').hidden=false;el('login').hidden=true;
 el('asof').textContent=d.as_of;el('nav').textContent=d.nav.toFixed(4);el('stage').textContent=st[d.stage];el('weight').textContent=pct(d.exposure);
 const steps={processing:'正在处理',daily:'等待股票日线',basic:'等待每日指标',limits:'等待涨跌停价',index:'等待基准指数',industry:'等待行业收盘',themes:'等待主题收盘',wind:'等待全指股息率',credit:'等待贷款数据',rates:'等待国债数据',articles:'等待脱水文章',upload:'等待上传',validation:'等待账本核对'};
 const pending=d.close_note,notice=el('closeProgress'),macro=el('economyMeta'),e=d.economy_note;
 notice.hidden=true;
 if(pending&&pending.day>d.as_of){notice.textContent=pending.day+' 正式收盘 · '+steps[pending.step]+'（'+pending.asof.slice(11,16)+'）';notice.hidden=false}
 else if(d.server_day===d.session&&d.server_minute>=902){notice.textContent='等待本机上传今天的正式收盘结果';notice.hidden=false}
 macro.hidden=!e;
 if(e)macro.textContent='中长期贷款同比 '+e.growth.toFixed(2)+'%（'+e.month+'）　十年期国债收益率：中国 '+e.cn10.toFixed(2)+'%（'+e.cn_day+'）／美国 '+e.us10.toFixed(2)+'%（'+e.us_day+'）';
 currentRevision=d.display_revision||d.as_of;
 el('poolTitle').textContent='收盘基础池 · '+(d.pool_count??d.pool?.length??0)+'只';
 const tick=d.ticks.at(-1),now=d.server_minute,expected=Math.min(898,2*Math.floor((now-1)/2));
 const overdue=tick&&now>=882&&tick.slot<expected;
 const fresh=tick&&tick.status==='estimated'&&!overdue;
 el('status').textContent=tick?(overdue?'本机最新一轮结果尚未收到，请查看下方已记录时点':fresh?(tick.orders.length?'预计有 '+tick.orders.length+' 只股票需要调仓':'本次估算完成，预计无需调仓'):'本次未形成预计名单 · '+tick.reason):d.server_day===d.session?(now<880?'等待本机今天14:40首次估算':now>=900?'今天未收到本机盘中估算记录':'等待本机上传预计结果'):(d.server_day>d.session?'等待最近交易日的本地收盘更新':'下一交易日 '+d.session+' 14:40开始估算');
 el('time').textContent='预计使用的收盘底稿 '+(tick?.base||d.as_of)+(tick?'　估算时点 '+new Date(tick.generated).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'')+(tick&&now>=900?'　已过收盘，以上为盘中记录':'');
 table('changes',['股票','方向','调仓前','预计调仓后'],fresh?tick.orders.map(x=>[x.name+' '+x.code,x.after>x.before?'买入':'卖出',pct(x.before),pct(x.after)]):[]);
 table('ticks',['北京时间','状态'],d.ticks.map(x=>[Math.floor(x.slot/60)+':'+String(x.slot%60).padStart(2,'0'),x.status==='estimated'?'完成 · '+x.orders.length+'只':x.reason]));
 table('holdings',['股票','代码','类别','收盘权重','最近报价','行情时间'],d.holdings.map(x=>[x.name,x.code,role[x.kind],pct(x.weight),x.price??'待更新',x.quote_time?x.quote_time.slice(4,6)+'-'+x.quote_time.slice(6,8)+' '+x.quote_time.slice(8,10)+':'+x.quote_time.slice(10,12):'—']));table('orders',['日期','股票','类别','方向','权重变化'],[...d.orders].reverse().map(x=>[x.date,x.name,role[x.kind],x.weight>0?'买入':'卖出',pct(x.weight)]));
 if(detailRevision!==currentRevision){
   if(d.pool&&d.history)drawDetails(d);
   else{detailRevision='';pool=[];el('chart').replaceChildren();el('range').textContent='正在读取历史净值…';el('pool').textContent='正在读取基础池…';void loadDetails(currentRevision)}
 }
 }catch(e){el('error').textContent=el('board').hidden?'暂时未能读取持仓，可以重试。':'刷新未完成，当前数据的时间见上方。';el('loadRetry').hidden=false}finally{busy=false}
}
el('login').onsubmit=async e=>{
 e.preventDefault();
 const button=el('login').querySelector('button'),status=el('loginStatus');
 if(button.disabled)return;
 button.disabled=true;status.textContent='正在验证密码…';
 try{
  const r=await shareRequest('/api/login?view=summary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:el('pass').value}),signal:AbortSignal.timeout(90000)});
  if(!r.ok){
   if(r.status===429){const seconds=Number(r.headers.get('Retry-After'));status.textContent=seconds>0?'登录次数已达上限，请在 '+Math.ceil(seconds/60)+' 分钟后重试。':'登录次数已达上限，请稍后重试。'}
   else status.textContent=r.status===401?'密码错误，请重新输入。':'登录服务暂时不可用，请重试。';
   return;
  }
  const data=await r.json();el('pass').value='';status.textContent='';el('login').hidden=true;await refresh(data.board||null);
 }catch{status.textContent='未能连接登录服务，请重试。'}finally{button.disabled=false}
};
el('logout').onclick=async()=>{try{await shareRequest('/api/logout',{method:'POST',signal:AbortSignal.timeout(15000)})}finally{location.reload()}};
el('refresh').onclick=()=>refresh();el('loadRetry').onclick=()=>refresh();refresh();setInterval(()=>{if(!document.hidden&&!el('board').hidden)refresh()},30000);
