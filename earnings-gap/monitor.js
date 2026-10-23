(function(root){
'use strict';
const china=now=>new Date(now.getTime()+8*3600000).toISOString();
const core=root.EarningsGapCore||(typeof require==='function'?require('./signal.js'):null);
function quoteState(live,quotes,now=new Date()){
 const cn=core.chinaTime(now),weekday=new Date(cn.day+'T00:00:00Z').getUTCDay();
 const covered=live.reaction_calendar_start<=cn.day&&cn.day<=live.reaction_calendar_end;
 const tradingDay=covered?live.reaction_calendar.includes(cn.day):weekday>0&&weekday<6;
 if(!tradingDay)return {className:'',text:'今日休市，等待下一交易日行情'};
 if(cn.minutes<570)return {className:'',text:cn.minutes<555?'盘前等待开盘，09:30后核验实时行情':'集合竞价中，09:30后按正式开盘行情筛选'};
 const watch=[...new Set((live.records||[]).filter(r=>!r.exit_date&&!['未入选','剔除'].includes(r.status)).map(r=>r.ts_code.slice(-2).toLowerCase()+r.ts_code.slice(0,6)))];
 const missing=watch.filter(code=>!core.freshness(quotes[code],now).ok);
 const stamp=Object.values(quotes).filter(q=>core.freshness(q,now).ok).map(q=>q.timestamp).sort().at(-1);
 if(missing.length)return {className:'offline',text:cn.minutes>=900?`${missing.length}只跟踪股票收盘行情尚未核验，暂停对应买卖确认`:`${missing.length}只跟踪股票行情缺失或过期，暂停对应买卖确认`};
 return {className:stamp?'live':'offline',text:stamp?`${cn.minutes>690&&cn.minutes<780?'午间休市 · ':cn.minutes>=900?'收盘行情 · ':''}行情 ${stamp.slice(8,10)}:${stamp.slice(10,12)}:${stamp.slice(12,14)}`:'尚未取得有效行情，暂停确认买卖'};
}
function health(monitor,live,job,now=new Date(),errors=[],screened=[],loading={}){
 const cn=china(now),day=cn.slice(0,10),minutes=Number(cn.slice(11,13))*60+Number(cn.slice(14,16)),weekday=new Date(day+'T00:00:00Z').getUTCDay(),messages=[];
 let severity=0;const add=(level,text)=>{severity=Math.max(severity,level);messages.push(text);};
 if(!monitor)return loading.monitor?{severity:1,title:'正在核验',messages:['正在读取公告监控记录…']}:{severity:3,title:'监控数据待核验',messages:['未取得监控记录，无法确认公告是否完整处理。',...errors]};
 if(monitor.status==='FAILED')add(3,'最近一次更新失败：'+(monitor.error||'请查看任务记录'));
 if(monitor.source_status!=='PASS')add(3,'巨潮公告清单未完成核对，覆盖数量暂不可确认');
 if(monitor.status==='PARTIAL')(monitor.issues||['部分公告尚未完成处理']).forEach(text=>add(2,text));
 if(monitor.status==='RUNNING')add(1,'公告采集与筛选正在运行');
 if(loading.live)add(1,'正在读取交易数据，尚未判断批次是否同步');
 else if(!live||live.updated_at!==monitor.data_updated_at)add(2,'页面交易数据与本次监控批次尚未同步');
 if(live&&live.version!==monitor.version)add(3,'策略数据版本不一致');
 const active=job&&['queued','in_progress','waiting','pending','requested'].includes(job.status);
 if(job&&job.status==='completed'&&job.conclusion!=='success')add(3,'最新线上任务失败：'+job.conclusion);
 if(active)add(now.getTime()-Date.parse(job.created_at)>30*60000?3:1,'线上任务'+(job.status==='queued'?'排队中':'执行中'));
 if(job?.status==='completed'&&monitor.attempt?.run_id&&String(job.id)!==String(monitor.attempt.run_id)&&Date.parse(job.created_at)>=Date.parse(monitor.attempt.started_at))add(2,'最新任务的监控快照尚未同步');
 if(loading.job)add(1,'正在读取线上任务状态');
 else if(!job)add(2,'线上任务状态暂无法核验');
 if(loading.quotes)add(1,'正在获取行情，暂不确认买卖');
 const calendarCovered=live?.reaction_calendar_start<=day&&day<=live?.reaction_calendar_end;
 const tradingDay=calendarCovered?live.reaction_calendar.includes(day):weekday>0&&weekday<6;
 if(live?.reaction_calendar_end&&!calendarCovered)add(3,'交易日历未覆盖今天，暂停反应日确认');
 if(tradingDay&&minutes>=540){
  if(monitor.financial_asof<day)add(active?1:3,'今天的公告与筛选尚未完成更新');
  if(job&&china(new Date(job.created_at)).slice(0,10)<day)add(3,'今天尚无线上任务执行记录');
  if(minutes>=945&&(!monitor.data_updated_at||Date.parse(monitor.data_updated_at)<Date.parse(day+'T15:10:00+08:00')))add(active?1:3,'今日收盘归档尚未完成');
 }
 if(tradingDay&&((minutes>=570&&minutes<=690)||(minutes>=780&&minutes<900))){
  const missing=screened.filter(r=>r.quote_fresh===false&&!r.exit_date&&!['未入选','剔除'].includes(r.status));
  if(missing.length)add(3,`${missing.length}只跟踪股票行情缺失或过期，暂停对应买卖确认`);
 }
 errors.forEach(text=>add(2,text));
 return {severity,title:severity>=3?'监控异常':severity===2?'存在待核验事项':severity===1?(Object.values(loading).some(Boolean)?'正在核验':'更新进行中'):'公告与筛选正常',messages};
}
function reportState(report,screened=[]){
 if(report.end_date?.slice(5,7)==='12')return {...report,complete:true,financial_eligible:false,strategy_excluded:true,result:'已排除',reason:'年报不参与策略'};
 if(!report.complete||!report.financial_eligible)return report;
 const trade=screened.filter(r=>r.ts_code===report.ts_code&&r.end_date===report.end_date).sort((a,b)=>b.ann_date.localeCompare(a.ann_date))[0];
 return trade?{...report,result:trade.status,reason:trade.status_note||trade.exit_reason||report.reason,reaction_date:trade.reaction_date||report.reaction_date,quarter_profit:trade.quarter_profit??report.quarter_profit,entry_date:trade.entry_date,open_gap_pct:trade.open_gap_pct,signal_return_pct:trade.signal_return_pct,signal_high_pct:trade.signal_high_pct,pullback_excluded:trade.pullback_excluded,quote_time:trade.quote_time,quote_fresh:trade.quote_fresh,gap_filled:trade.gap_filled,data_pending:trade.data_pending,volume_state:trade.volume_state,volume_ratio:trade.volume_ratio,volume_forecast_ratio:trade.volume_forecast_ratio,volume_actual_shares:trade.volume_actual_shares,volume_forecast_shares:trade.volume_forecast_shares,volume_profile_kind:trade.volume_profile_kind,volume_profile_days:trade.volume_profile_days,volume_profile_through:trade.volume_profile_through}:report;
}
function filterReports(reports,filter){return filter==='all'?reports:reports.filter(r=>r.financial_eligible);}
function financialReport(report,monitor){
 const prefix='live-'+report.ts_code+'-'+report.end_date+'-',checks=monitor.financial_checks||{};
 const key=checks[prefix+report.ann_date]?prefix+report.ann_date:Object.keys(checks).filter(k=>k.startsWith(prefix)&&k.slice(prefix.length)<=report.ann_date).sort().at(-1);
 return {...report,quarter_profit:report.quarter_profit??checks[key]?.quarter_profit};
}
function reactionDay(report,calendar,day){
 return core.reactionDay(report,calendar);
}
function latestReports(reports,key){
 const sorted=[...reports].sort((a,b)=>b.end_date.localeCompare(a.end_date)||b.ann_date.localeCompare(a.ann_date)||Number(!!b.corrected)-Number(!!a.corrected));
 const unique=new Map();for(const row of sorted)if(!unique.has(key(row)))unique.set(key(row),row);return [...unique.values()];
}
function marketState(row,day,synced=true,quotesReady=true){
 const waiting=label=>({label,passed:false,failed:false,known:false});
 if(!row.complete)return waiting('待复核');
 if(row.reaction_date!==day)return waiting('待反应日');
 if(!synced)return waiting('待核验');
 if(row.awaiting_open)return waiting('待开盘');
 if(['未入选','剔除','已排除'].includes(row.result))return {label:'未通过',passed:false,failed:true,known:true};
 if(row.closing_confirmed)return {label:'收盘通过',passed:true,failed:false,known:true};
 if(!quotesReady||row.quote_fresh!==true)return waiting(row.result==='等待开盘'?'待开盘':'待行情');
 if(row.result==='买入')return {label:'收盘通过',passed:true,failed:false,known:true};
 if(row.pullback_excluded&&row.result==='观察')return {label:'冲高回落',passed:false,failed:true,known:true};
 if(row.result==='观察'&&row.volume_state==='estimated'&&row.reason==='量能预计达标')return {label:'预计符合',passed:true,failed:false,known:true,estimated:true};
 if(row.result==='观察'&&row.volume_state==='pending')return waiting('量能待核验');
 if(row.result==='观察')return row.reason==='当前满足买入条件'?{label:'当前符合',passed:true,failed:false,known:true}:{label:'当前不符',passed:false,failed:true,known:true};
 return waiting(row.result==='等待开盘'?'待开盘':'待核验');
}
function currentState(row,day,synced=true,quotesReady=true){
 const base=marketState(row,day,synced,quotesReady),reason=row.reason||'',result=(label,details='',extra={})=>({...base,label,details,...extra});
 if(row.strategy_excluded)return result('年报不参与',reason,{passed:false,failed:true,known:true});
 if(!row.complete)return result('财务待核验',reason);
 if(row.financial_eligible===false)return result(reason.includes('ST股票')?'ST不参与':reason.includes('上市不足')?'上市不足90日':'财报不符',reason,{passed:false,failed:true,known:true});
 if(row.reaction_date!==day)return result('待反应日',row.reaction_date||'反应日待核验');
 if(!synced)return result('数据待同步');
 if(row.awaiting_open)return result('待开盘','09:30后按正式开盘行情筛选');
 if(base.passed)return result(row.closing_confirmed||row.result==='买入'?'收盘入选':base.estimated?'预计符合':'当前符合',base.estimated?'预计量能达标':'');
 if(!base.known){
  if(row.data_pending||reason.includes('日线'))return result('日线待补',reason);
  if(reason.startsWith('冲高回落条件待核验'))return result('最高价待核验',reason);
  if(row.volume_state==='pending')return result('量能待核验',reason);
  if(reason.includes('行情过期'))return result('行情过期');
  if(row.result==='等待开盘')return result('待开盘');
  return result(base.label==='待行情'?'行情待更新':'待核验',reason);
 }
 const failures=[];
 if(reason.includes('ST股票'))failures.push('ST不参与');
 if(reason.includes('上市不足'))failures.push('上市不足90日');
 if(reason.includes('高开不足')||Number.isFinite(row.open_gap_pct)&&row.open_gap_pct<2-1e-7)failures.push('高开不足');
 if(row.gap_filled||reason.includes('已补缺口'))failures.push('缺口已补');
 if(row.pullback_excluded||reason.startsWith('冲高回落：'))failures.push('冲高回落');
 const cap=row.end_date?.slice(5,7)==='06'?5:7;
 if(reason.includes('涨幅')||Number.isFinite(row.signal_return_pct)&&row.signal_return_pct>=cap)failures.push('涨幅不符');
 if(['waiting','failed'].includes(row.volume_state)||reason.includes('量能不足')||reason.includes('等待量能'))failures.push('量能不足');
 const detail=failures[0]==='冲高回落'&&Number.isFinite(row.signal_high_pct)?`最高 +${row.signal_high_pct.toFixed(2)}% · ${row.result==='观察'?'当前':'收盘'} ${row.signal_return_pct.toFixed(2)}%`:reason;
 return result(failures[0]||'未入选',failures.length>1?failures.slice(1).join(' · '):detail);
}
function dailyOverview(monitor,live,screened=[],now=new Date(),quotesReady=true){
 const day=china(now).slice(0,10),confirmed=monitor?.source_status==='PASS'&&monitor.financial_asof===day;
 const synced=confirmed&&live?.updated_at===monitor.data_updated_at&&live?.version===monitor.version;
 const tradingDay=live?.reaction_calendar?live.reaction_calendar.includes(day):null;
 const archived=tradingDay!==false&&synced&&monitor.status==='PASS'&&live.status==='PASS'&&live.financial_asof===day&&now.getTime()>=Date.parse(day+'T15:10:00+08:00')&&Date.parse(live.updated_at)>=Date.parse(day+'T15:10:00+08:00');
 const raw=(monitor?.reports||[]).map(r=>financialReport(reportState(r,screened),monitor));
 const all=latestReports(raw,r=>r.ts_code+'|'+r.end_date),calendar=live?.reaction_calendar||live?.calendar||[];
 const aligned=all.map(r=>({...r,reaction_date:reactionDay(r,calendar,day)}));
 const today=latestReports(aligned.filter(r=>r.reaction_date===day),r=>r.ts_code);
 const candidates=latestReports(today.filter(r=>r.financial_eligible),r=>r.ts_code).map(r=>{
  const closed=archived&&(live.records||[]).some(t=>t.ts_code===r.ts_code&&t.end_date===r.end_date&&t.entry_date===day&&!t.data_pending);
  const row={...r,closing_confirmed:closed,awaiting_open:tradingDay!==false&&core.chinaTime(now).minutes<570};return {...row,market:currentState(row,day,synced,quotesReady)};
 });
 const market=candidates.filter(r=>r.reaction_date===day);
 return {day,confirmed,synced,archived,tradingDay,all:raw,today,candidates,failures:today.filter(r=>r.complete&&!r.financial_eligible),
  announcements:confirmed?today.length:null,financial:confirmed?today.filter(r=>r.complete&&r.financial_eligible).length:null,
  market:synced&&market.every(r=>r.market.known)?market.filter(r=>r.market.passed).length:null,
  closing:archived?(live.records||[]).filter(r=>r.entry_date===day&&!r.data_pending).length:null};
}
const api={health,quoteState,reportState,filterReports,financialReport,reactionDay,marketState,currentState,dailyOverview};root.EarningsGapMonitoring=api;if(typeof module!=='undefined')module.exports=api;
if(typeof document==='undefined')return;
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const format=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';
let monitor=null,live=null,job=null,errors=[],liveError='',busy=false,screened=[];
const loading={monitor:true,live:true,job:true,quotes:true};
api.setLive=value=>{if(live?.updated_at!==value.updated_at)screened=[];live=value;liveError='';loading.live=false;render();};
api.setLiveError=message=>{liveError='交易数据读取失败：'+message;loading.live=false;loading.quotes=false;render();};
api.setScreening=(value,ready=true)=>{screened=value;if(ready)loading.quotes=false;render();};
const percent=value=>Number.isFinite(value)?`${value>0?'+':''}${value.toFixed(2)}%`:'—';
const money=value=>Number.isFinite(value)?(value/10000).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
const amount=value=>'<span class="'+(value<0?'down':'')+'">'+money(value)+'</span>';
const change=value=>'<span class="'+(value>0?'up':value<0?'down':'')+'">'+percent(value)+'</span>';
const period=row=>root.EarningsGapDisplay.period(row);
function original(row){
 try{const url=new URL(row.url);if(url.protocol==='https:'&&['static.cninfo.com.cn','pdf.dfcfw.com','data.eastmoney.com'].includes(url.hostname))return '<a href="'+esc(url.href)+'" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">原文 ↗</a>';}catch{}
 return '—';
}
function render(){
 if(!$('monitorStatus'))return;
 const now=new Date(),state=health(monitor,live,job,now,liveError?[...errors,liveError]:errors,screened,loading);
 $('monitorStatus').textContent=state.title;$('monitorStatus').className='monitor-status '+(state.severity>=3?'bad':state.severity===2?'warn':state.severity===1?'running':'pass');
 $('monitorExplanation').textContent=state.messages.join('；');$('monitorExplanation').hidden=!state.messages.length;
 $('monitorExplanation').className=state.severity>=3?'monitor-alert bad':state.severity===2?'monitor-alert warn':'';
 const confirmed=monitor&&monitor.source_status==='PASS';
 $('monitorProgress').textContent=confirmed?(monitor.counts?.processed??'—')+' / '+(monitor.counts?.announcements??'—'):'—';
 $('monitorPending').textContent=confirmed?String(monitor.counts?.pending??'—'):'—';$('monitorPending').className=monitor?.counts?.pending?'up':'down';
 const checked=monitor?.attempt?.finished_at||monitor?.checked_at;
 $('monitorTime').textContent=checked?new Date(checked).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';$('monitorTime').title=format(checked);
 $('monitorRun').textContent=job?(job.status==='completed'?(job.conclusion==='success'?'成功':'失败'):'执行中')+'（'+(job.event==='schedule'?'定时':'手动')+'）':'待核验';
 $('monitorRun').title=job?format(job.created_at):'';
 $('monitorRun').href=job?.html_url||monitor?.attempt?.run_url||'https://github.com/zzyfsniper-code/sector-bias-dashboard/actions/workflows/earnings-gap-data.yml';
 const daily=dailyOverview(monitor,liveError?null:live,screened,now,!loading.quotes);
 $('monitorToday').textContent=daily.day;
 for(const [id,value] of [['dailyAnnouncements',daily.announcements],['dailyFinancial',daily.financial],['dailyMarket',daily.market]])$(id).textContent=value==null?'—':value+' 家';
 const closing=daily.closing==null?(china(now).slice(11,16)<'15:00'?'待收盘':'待归档'):daily.closing+' 家';
 $('dailyClosing').textContent=daily.tradingDay===false?'休市':daily.confirmed?closing:'待核验';$('dailyClosing').className=daily.closing==null?'text-value':'';
 $('dailyCandidateCount').textContent=daily.confirmed?daily.candidates.length+' 家':'待核验';
 $('dailyCandidates').innerHTML=daily.confirmed&&daily.candidates.length?[...daily.candidates].sort((a,b)=>Number(b.market.passed)-Number(a.market.passed)||Number(!!a.market.estimated)-Number(!!b.market.estimated)).map(r=>{
  return '<tr class="'+(r.market.failed?'candidate-rejected':r.market.passed?'candidate-selected'+(r.market.estimated?' candidate-estimated':''):'candidate-pending')+'"><td><span class="stock">'+esc(r.name)+'</span><span class="sub">'+esc(r.ts_code)+' · '+root.EarningsGapDisplay.industry(r)+'</span></td><td class="num">'+root.EarningsGapDisplay.pb(r)+'</td><td>'+period(r)+'</td><td>'+esc(r.ann_date)+'<span class="sub">'+esc(r.reaction_date||'待确定')+'</span></td><td class="num">'+amount(r.quarter_profit)+'<span class="sub">同比 '+change(r.quarter_yoy)+'</span></td><td class="num">'+change(r.open_gap_pct)+'</td><td class="num">'+change(r.signal_return_pct)+'</td><td class="num">'+root.EarningsGapVolume.cell(r)+'</td><td class="num">'+root.EarningsGapVolume.cell(r,true)+'</td><td class="current-state"><span class="pill '+(r.market.failed?'reject':r.market.passed?'watch':'')+'" title="'+esc(r.reason||r.market.details||r.market.label)+'">'+esc(r.market.label)+'</span>'+(r.market.details?'<span class="sub">'+esc(r.market.details)+'</span>':'')+'</td><td>'+original(r)+'</td></tr>';
 }).join(''):'<tr><td colspan="11" class="empty">'+(daily.confirmed?'今日暂无财务候选或行情反应日候选。':'今日公告与筛选尚未核验，不能据此认定没有候选。')+'</td></tr>';
 $('dailyFailureCount').textContent=daily.confirmed?daily.failures.length+' 家':'待核验';
 $('dailyFailuresToggle').textContent=$('dailyFailuresPanel').hidden?'查看财务未通过的 '+daily.failures.length+' 家 →':'收起财务未通过名单 ↑';
 $('dailyFailuresToggle').disabled=!daily.confirmed;
 $('dailyFailures').innerHTML=daily.failures.length?daily.failures.map(r=>{const state=currentState(r,daily.day,daily.synced,!loading.quotes);return '<tr><td><span class="stock">'+esc(r.name)+'</span><span class="sub">'+esc(r.ts_code)+' · '+root.EarningsGapDisplay.industry(r)+'</span></td><td>'+period(r)+'</td><td class="num">'+amount(r.quarter_profit)+'</td><td class="num">'+change(r.quarter_yoy)+'</td><td class="current-state"><span class="pill reject">'+esc(state.label)+'</span><span class="sub">'+esc(state.details)+'</span></td><td>'+original(r)+'</td></tr>';}).join(''):'<tr><td colspan="6" class="empty">今日暂无已核验的财务未通过记录。</td></tr>';
 $('monitorScope').textContent=confirmed?monitor.window_start+' — '+monitor.financial_asof+' · '+(monitor.counts?.announcements??'—')+'条公告 / '+(monitor.counts?.companies??'—')+'家公司 · 财务通过 '+(monitor.counts?.financial_candidates??'—')+'家':'公告覆盖范围待核验';
 if(confirmed&&monitor.scope_exclusions?.length)$('monitorScope').textContent+=' · 已排除B股 '+monitor.scope_exclusions.filter(r=>r.reason==='B股不参与策略').length+'条、历史比较期 '+monitor.scope_exclusions.filter(r=>r.reason.includes('历史比较数据')).length+'条（明细可下载）';
 const all=daily.all,filter=$('monitorFilter').value,reports=filterReports(all,filter);
 $('monitorReports').innerHTML=reports.length?reports.slice(0,50).map(r=>'<tr><td>'+esc(r.ann_date)+'</td><td>'+esc(r.name)+'<span class="sub">'+esc(r.ts_code)+' · '+root.EarningsGapDisplay.industry(r)+'</span></td><td>'+period(r)+(r.corrected?'（更正）':'')+'</td><td class="num">'+amount(r.quarter_profit)+'</td><td class="num">'+change(r.quarter_yoy)+'</td><td>'+esc(r.result)+'<span class="sub">'+esc(r.reason)+'</span></td><td>'+original(r)+'</td></tr>').join(''):'<tr><td colspan="7" class="empty">'+(confirmed?(filter==='all'?'核对范围内暂无正式公告。':'暂无符合财务条件的公告，可切换“全部公告”查看。'):'公告覆盖尚未核验，不能据此认定没有公告。')+'</td></tr>';
 $('monitorRowsNote').textContent=(filter==='all'?'全部公告':'符合财务条件')+' '+reports.length+'条 / 共'+all.length+'条'+(reports.length>50?'；显示最近50条，可下载全部记录。':'');
}
async function fetchJson(url){const c=new AbortController(),t=setTimeout(()=>c.abort(),15000);try{const r=await fetch(url,{cache:'no-store',signal:c.signal});if(!r.ok)throw Error(`HTTP ${r.status}`);return await r.json();}finally{clearTimeout(t);}}
async function refresh(){
 if(busy||document.hidden)return;busy=true;errors=[];$('monitorRefresh').disabled=true;render();
 const results=await Promise.allSettled([
  fetchJson(`earnings-gap/data/monitor.json?t=${Math.floor(Date.now()/60000)}`),
  fetchJson('https://api.github.com/repos/zzyfsniper-code/sector-bias-dashboard/actions/workflows/earnings-gap-data.yml/runs?per_page=1')
 ]);
 if(results[0].status==='fulfilled')monitor=results[0].value;else errors.push('监控快照读取失败：'+results[0].reason.message);
 if(results[1].status==='fulfilled')job=results[1].value.workflow_runs?.[0]||null;else{job=null;errors.push('线上任务状态查询失败：'+results[1].reason.message);}
 loading.monitor=false;loading.job=false;busy=false;$('monitorRefresh').disabled=false;render();
}
$('monitorFilter').onchange=render;
$('dailyFailuresToggle').onclick=()=>{const panel=$('dailyFailuresPanel');panel.hidden=!panel.hidden;$('dailyFailuresToggle').setAttribute('aria-expanded',String(!panel.hidden));render();};
$('monitorRefresh').onclick=refresh;document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
root.addEventListener('earnings-gap-context',render);
refresh();setInterval(refresh,300000);setInterval(()=>{if(!document.hidden)render();},30000);
})(typeof globalThis!=='undefined'?globalThis:this);
