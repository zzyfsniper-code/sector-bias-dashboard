(function(root){
'use strict';
const china=now=>new Date(now.getTime()+8*3600000).toISOString();
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
 if(weekday>0&&weekday<6&&minutes>=540){
  if(monitor.financial_asof<day)add(active?1:3,'今天的公告与筛选尚未完成更新');
  if(job&&china(new Date(job.created_at)).slice(0,10)<day)add(3,'今天尚无线上任务执行记录');
  if(minutes>=945&&(!monitor.data_updated_at||Date.parse(monitor.data_updated_at)<Date.parse(day+'T15:10:00+08:00')))add(active?1:3,'今日收盘归档尚未完成');
 }
 if(weekday>0&&weekday<6&&((minutes>=570&&minutes<=690)||(minutes>=780&&minutes<900))){
  const missing=screened.filter(r=>r.quote_fresh===false&&!r.exit_date&&!['未入选','剔除'].includes(r.status));
  if(missing.length)add(3,`${missing.length}只跟踪股票行情缺失或过期，暂停对应买卖确认`);
 }
 errors.forEach(text=>add(2,text));
 return {severity,title:severity>=3?'监控异常':severity===2?'存在待核验事项':severity===1?(Object.values(loading).some(Boolean)?'正在核验':'更新进行中'):'公告与筛选正常',messages};
}
function reportState(report,screened=[]){
 if(!report.complete||!report.financial_eligible)return report;
 const trade=screened.filter(r=>r.ts_code===report.ts_code&&r.end_date===report.end_date).sort((a,b)=>b.ann_date.localeCompare(a.ann_date))[0];
 return trade?{...report,result:trade.status,reason:trade.status_note||trade.exit_reason||report.reason,open_gap_pct:trade.open_gap_pct,signal_return_pct:trade.signal_return_pct,quote_time:trade.quote_time,quote_fresh:trade.quote_fresh}:report;
}
function filterReports(reports,filter){return filter==='all'?reports:reports.filter(r=>r.financial_eligible);}
const api={health,reportState,filterReports};root.EarningsGapMonitoring=api;if(typeof module!=='undefined')module.exports=api;
if(typeof document==='undefined')return;
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const periods={'03':'一季报','06':'中报','09':'三季报','12':'年报'},format=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';
let monitor=null,live=null,job=null,errors=[],liveError='',busy=false,screened=[];
const loading={monitor:true,live:true,job:true,quotes:true};
api.setLive=value=>{if(live?.updated_at!==value.updated_at)screened=[];live=value;liveError='';loading.live=false;render();};
api.setLiveError=message=>{liveError='交易数据读取失败：'+message;loading.live=false;loading.quotes=false;render();};
api.setScreening=(value,ready=true)=>{screened=value;if(ready)loading.quotes=false;render();};
const percent=value=>Number.isFinite(value)?`${value>0?'+':''}${value.toFixed(2)}%`:'—';
function render(){
 if(!$('monitorStatus'))return;
 const state=health(monitor,live,job,new Date(),liveError?[...errors,liveError]:errors,screened,loading);
 $('monitorStatus').textContent=state.title;$('monitorStatus').className='monitor-status '+(state.severity>=3?'bad':state.severity===2?'warn':state.severity===1?'running':'pass');
 $('monitorExplanation').textContent=state.messages.length?state.messages.join('；'):'公告清单已核对，筛选记录完整。符合财务条件后仍需通过反应日行情筛选。';
 $('monitorExplanation').className=state.severity>=3?'monitor-alert bad':state.severity===2?'monitor-alert warn':'';
 const confirmed=monitor&&monitor.source_status==='PASS';
 for(const [id,key] of [['monitorReceived','announcements'],['monitorProcessed','processed'],['monitorPending','pending'],['monitorCandidates','financial_candidates']])$(''+id).textContent=confirmed?String(monitor.counts?.[key]??'—'):'—';
 $('monitorTime').textContent=format(monitor?.attempt?.finished_at||monitor?.checked_at);
 $('monitorSourceDate').textContent=monitor?.source_asof||'未核验';
 $('monitorRun').textContent=job?`${job.status==='completed'?(job.conclusion==='success'?'成功':'失败'):'执行中'}（${job.event==='schedule'?'定时':'手动'}） · ${format(job.created_at)}`:'任务状态待核验';
 $('monitorRun').href=job?.html_url||monitor?.attempt?.run_url||'https://github.com/zzyfsniper-code/sector-bias-dashboard/actions/workflows/earnings-gap-data.yml';
 $('monitorScope').textContent=monitor?`核对范围 ${monitor.window_start} 至 ${monitor.financial_asof}；${monitor.counts?.companies??'—'}家公司；今日标注公告 ${monitor.counts?.today_announcements??'—'}条。更正报告单独记录。公告标注日用于确定行情反应日。`:'正在核对公告覆盖范围…';
 const all=(monitor?.reports||[]).map(r=>reportState(r,screened)),filter=$('monitorFilter').value,reports=filterReports(all,filter);$('monitorDetailsLabel').textContent=`查看公告与筛选记录（共${all.length}条）`;
 $('monitorReports').innerHTML=reports.length?reports.slice(0,50).map(r=>{const cause=r.profit_reason;return `<tr><td>${esc(r.ann_date)}</td><td>${esc(r.name)}<span class="sub">${esc(r.ts_code)}</span></td><td>${esc(r.end_date.slice(0,4))}${periods[r.end_date.slice(5,7)]||''}${r.corrected?'（更正）':''}</td><td class="num">${r.quarter_yoy==null?'—':Number(r.quarter_yoy).toFixed(2)+'%'}</td><td>${esc(r.result)}<span class="sub">${esc(r.reason)}</span>${Number.isFinite(r.open_gap_pct)?`<span class="sub">开盘 ${percent(r.open_gap_pct)} · 当日 ${percent(r.signal_return_pct)}</span>`:''}${r.quote_fresh&&r.quote_time?`<span class="sub">行情 ${esc(r.quote_time)}</span>`:''}</td><td class="profit-reason">${esc(cause?.summary||'原因尚未读取')}<span class="sub">${esc(cause?.metric||'')}${cause?.metric?' · ':''}${esc(cause?.scope||'')}${cause?.page?` · <a href="${esc(r.url)}#page=${cause.page}" target="_blank" rel="noopener noreferrer">第${cause.page}页 ↗</a>`:''}</span>${cause?.evidence?`<details class="reason-evidence"><summary>原文依据</summary><p>${esc(cause.evidence)}</p></details>`:''}</td><td><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">原文 ↗</a></td></tr>`;}).join(''):`<tr><td colspan="7" class="empty">${confirmed?(filter==='all'?'核对范围内暂无正式公告。':'核对范围内暂无符合财务条件的公告，可切换“全部公告”查看。'):'公告覆盖尚未核验，不能据此认定没有公告。'}</td></tr>`;
 $('monitorRowsNote').textContent=`${filter==='all'?'全部公告':'符合财务条件'} ${reports.length}条 / 共${all.length}条${reports.length>50?'；显示最近50条，可下载全部记录。':''}`;
 const reasons=all.filter(r=>r.profit_reason?.status==='FOUND').length;
 $('monitorReasonsNote').textContent=`利润原因已提取${reasons}条 / 共${all.length}条；摘要摘自公司报告，不参与交易筛选。按原文标注单季、累计或未明确口径；未提取到不等于公司未披露。`;
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
$('monitorRefresh').onclick=refresh;document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
refresh();setInterval(refresh,300000);setInterval(()=>{if(!document.hidden)render();},30000);
})(typeof globalThis!=='undefined'?globalThis:this);
