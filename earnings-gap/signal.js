(function(root){
'use strict';
const volume=root.EarningsGapVolume||(typeof require==='function'?require('./volume.js'):null);
const VERSION='eg-20261023-v5-pullback83',PULLBACK_EFFECTIVE='2026-10-23';
const DATA_VERSIONS=['eg-20261021-v4-volume145',VERSION];
function chinaTime(now){const s=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(now).split(' ');return {day:s[0],time:s[1],minutes:Number(s[1].slice(0,2))*60+Number(s[1].slice(3,5))};}
function parseQuotes(text){const out={};for(const m of text.matchAll(/v_([a-z]+\d+)="([^"]*)"/g)){const f=m[2].split('~');if(f.length<35||!/^\d{14}$/.test(f[30]))continue;const q={symbol:m[1],name:f[1],last:Number(f[3]),previous:Number(f[4]),open:Number(f[5]),high:Number(f[33]),low:Number(f[34]),timestamp:f[30],volume_shares:f[6]?.trim()&&Number.isFinite(Number(f[6]))&&Number(f[6])>=0?Number(f[6])*(m[1].startsWith('sh68')?1:100):null};if([q.last,q.previous,q.open,q.high,q.low].every(x=>Number.isFinite(x)&&x>0))out[m[1]]=q;}return out;}
function freshness(q,now){if(!q)return {ok:false,note:'行情待更新'};const cn=chinaTime(now),s=q.timestamp,day=`${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}`,time=`${s.slice(8,10)}:${s.slice(10,12)}:${s.slice(12,14)}`,mins=Number(s.slice(8,10))*60+Number(s.slice(10,12)),age=(now-new Date(`${day}T${time}+08:00`))/1000;const open=(cn.minutes>=570&&cn.minutes<=690)||(cn.minutes>=780&&cn.minutes<900),lunch=cn.minutes>690&&cn.minutes<780;return {ok:day===cn.day&&age>=-30&&(open?age<=120:lunch?mins>=689:cn.minutes>=900?mins>=900:age<=120),day,time,mins,age,note:open?'盘中':lunch?'午间休市':cn.minutes>=900?'收盘':'盘前'};}
function reactionDay(record,calendar=[]){
let day=record.ann_date,afterOpen=false;
if(record.available_at){
 if(!/(Z|[+-]\d{2}:\d{2})$/.test(record.available_at)||!Number.isFinite(Date.parse(record.available_at)))return null;
 const moment=chinaTime(new Date(record.available_at));day=day>moment.day?day:moment.day;afterOpen=moment.day===day&&moment.minutes>=570;
}else if(record.reaction_date)return record.reaction_date;
return calendar.find(d=>d>day||d===day&&!afterOpen)||null;
}
function evaluate(record,q,now,calendar=[],reactionCalendar=calendar,volumeModel=null){
const out={...record};if(record.origin==='historical'||record.exit_date||!record.entry_date&&['剔除','未入选'].includes(record.status))return out;
if(record.report_period==='FY'&&!record.entry_date)return {...out,status:'剔除',status_note:'年报不参与策略'};
const f=freshness(q,now);out.quote_fresh=f.ok;out.quote_note=f.ok?f.note:'行情过期';if(!f.ok)return {...out,status:record.entry_date?'持有':'待更新',status_note:q?'行情过期':'行情待更新'};
if(record.data_pending)return {...out,status:'待核验',status_note:'日线记录待补齐'};
const day=f.day,cn=chinaTime(now);out.quote_time=f.time;
if(!record.entry_date&&(q.name.toUpperCase().startsWith('ST')||q.name.toUpperCase().startsWith('*ST')))return {...out,status:'剔除',status_note:'ST股票'};
if(record.entry_date){
if(day<record.entry_date)return {...out,status:'待更新',status_note:'行情早于买入日'};
if(day===record.basis_date||day===record.entry_date){out.profit_pct=(q.last/(record.entry_basis||record.entry_price)*.997/1.003-1)*100;return {...out,status:day===record.entry_date?'买入':'持有',status_note:day===record.entry_date?'收盘确认':'收盘状态已更新'};}
if(record.basis_date&&record.basis_date!==calendar.filter(d=>d<day).at(-1))return {...out,status:'持有',status_note:'日线状态过旧，暂停确认退出',profit_pct:null};
const scale=q.previous/(record.basis_last_close||q.previous),entry=(record.entry_basis||record.entry_price)*scale,stop=(record.stop_basis||entry*.92/scale)*scale,target=entry*1.10;
out.profit_pct=(q.last/entry*.997/1.003-1)*100;out.hold_days=calendar.filter(d=>d>=record.entry_date&&d<day).length+1;
if(day===record.entry_date)return {...out,status:'买入',status_note:'收盘确认'};
const rate=/^(688|300|301)/.test(record.ts_code)?.2:.1,lower=Math.round(q.previous*(1-rate)*100)/100;
if(q.high<=lower+.005&&q.low>=lower-.005)return {...out,status:'持有',status_note:'跌停卖出受限'};
let price,reason;if(q.open<=stop){price=q.open;reason='止损';}else if(q.open>=target){price=target;reason='止盈';}else if(q.low<=stop){price=stop;reason='止损';}else if(q.high>=target){price=target;reason='止盈';}else if(out.hold_days>=10&&f.mins>=900&&cn.minutes>=900){price=q.last;reason='10日到期';}
if(reason){if(reason==='止损'&&stop>entry)reason='保护止损';return {...out,status:cn.minutes>=900&&f.mins>=900?'卖出':'卖出提示',status_note:reason,exit_date:day,exit_price:price,exit_reason:reason,profit_pct:(price/entry*.997/1.003-1)*100};}
return {...out,status:'持有',status_note:record.armed?'保护止损已生效':'等待退出条件'};
}
const reaction=reactionDay(record,reactionCalendar);if(day<record.ann_date||day!==reaction)return {...out,status:'待核验',status_note:'等待对应反应日记录'};
if(volume?.required(record,reaction))Object.assign(out,volume.assess(record,q,volumeModel,now,f.ok));
out.reaction_date=day;out.signal_return_pct=(q.last/q.previous-1)*100;out.open_gap_pct=(q.open/q.previous-1)*100;
if(cn.minutes<570)return {...out,status:'等待开盘',status_note:'开盘价尚未确认'};
if(!Number.isFinite(record.quarter_yoy)||record.quarter_yoy<30||!Number.isFinite(record.quarter_profit)||record.quarter_profit<0)return {...out,status:'待核验',status_note:'财务条件不足'};
if(!record.list_date||(new Date(day)-new Date(record.list_date))/86400000<90)return {...out,status:'剔除',status_note:'上市不足90日'};
const o=Math.round(q.open*100),p=Math.round(q.previous*100),l=Math.round(q.low*100),c=Math.round(q.last*100),cap=record.report_period==='H1'?105:107;
if(o*100<p*102)return {...out,status:'未入选',status_note:'高开不足2%'};if(l<=p)return {...out,status:'剔除',status_note:'已补缺口'};
const within=c*100<p*cap,closed=cn.minutes>=900&&f.mins>=900;
if(reaction>=PULLBACK_EFFECTIVE){
 if(!Number.isFinite(q.high)||q.high<=0||q.high<q.last)return {...out,status:'待核验',status_note:'冲高回落条件待核验：缺少有效最高价'};
 out.signal_high_pct=(q.high/q.previous-1)*100;out.pullback_excluded=Math.round(q.high*100)*100>=p*108&&c*100<p*103;
 if(out.pullback_excluded)return {...out,status:closed?'剔除':'观察',status_note:closed?'冲高回落：最高≥8%，收盘<3%':'冲高回落：最高≥8%，当前<3%'};
}
if(volume?.required(record,reaction)){
 if(closed&&out.volume_state!=='confirmed')return {...out,status:out.volume_state==='failed'?'剔除':'待核验',status_note:out.volume_note};
 if(!closed&&within&&out.volume_state!=='confirmed')return {...out,status:'观察',status_note:out.volume_note};
}
if(closed)return within?{...out,status:'买入',status_note:'收盘确认',entry_date:day,entry_price:q.last,entry_basis:q.last,profit_pct:(.997/1.003-1)*100}:{...out,status:'剔除',status_note:'收盘涨幅不符'};
return {...out,status:'观察',status_note:within?'当前满足买入条件':'等待涨幅回落'};
}
function positionDetails(record,q,now,live={},day=chinaTime(now).day){
const out={target_price:null,stop_price:null,stop_label:'止损',price_note:'目标价格待核验',holding_days:null,holding_note:'交易日历覆盖不足'};
if(!record.entry_date||record.entry_date>day)return out;
const closed=!!record.exit_date,end=closed?record.exit_date:day,schedule=live.reaction_calendar||[],calendar=live.calendar||[];
if(closed&&Number.isInteger(record.hold_days)&&record.hold_days>0){out.holding_days=record.hold_days;out.holding_note='已结束，含买入日及卖出日';}
else if(schedule.includes(record.entry_date)&&live.reaction_calendar_start<=record.entry_date&&live.reaction_calendar_end>=end){
 out.holding_days=new Set(schedule.filter(d=>d>=record.entry_date&&d<=end)).size;out.holding_note='含买入日，周末及节假日不计';
}else if(record.basis_date<=end&&Number.isInteger(record.hold_days)&&record.hold_days>0){out.holding_days=record.hold_days;out.holding_note=`截至${record.basis_date}；后续交易日历待更新`;}
if(!Number.isFinite(record.entry_price)||record.entry_price<=0)return out;
if(closed||!Number.isFinite(record.entry_basis)||record.entry_basis<=0){
 out.target_price=record.entry_price*1.10;out.stop_price=record.entry_price*.92;out.stop_label='初始止损';
 out.price_note='按买入日原始价格展示初始目标（止盈+10%、止损−8%），不还原后续除权或保护线；非实际成交价';return out;
}
let scale=1;const f=freshness(q,now),asof=record.basis_date||record.entry_date;
out.price_note=`截至${asof}的日线目标；未核验当天行情时不调整价格`;
if(f.ok&&f.day>=record.entry_date){
 if(f.day===record.basis_date||f.day===record.entry_date)out.price_note=`${f.day}已核验行情；价格为扣费前触发线，非保证成交价`;
 else if(record.basis_date===calendar.filter(d=>d<f.day).at(-1)){
  scale=q.previous/(record.basis_last_close||q.previous);out.price_note=`${f.day}已核验行情，已对齐当前报价口径；价格为扣费前触发线，非保证成交价`;
 }
}
out.target_price=record.entry_basis*1.10*scale;
out.stop_price=(Number.isFinite(record.stop_basis)&&record.stop_basis>0?record.stop_basis:record.entry_basis*.92)*scale;
if(out.stop_price>record.entry_basis*scale)out.stop_label='保护止损';
return out;
}
root.EarningsGapCore={VERSION,DATA_VERSIONS,chinaTime,parseQuotes,freshness,reactionDay,evaluate,positionDetails};if(typeof module!=='undefined')module.exports=root.EarningsGapCore;
})(typeof globalThis!=='undefined'?globalThis:this);
