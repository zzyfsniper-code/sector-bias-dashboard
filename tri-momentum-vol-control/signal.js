/* Pure validation shared by the page and tests. Quotes never change model targets. */
(function(root){
'use strict';
const codes=['159696.SZ','510300.SH','518880.SH'];
function chinaTime(now){const s=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(now).split(' ');return {day:s[0],time:s[1]};}
function parseQuotes(text){const out={};for(const m of text.matchAll(/v_([a-z]+\d+)="([^"]*)"/g)){const f=m[2].split('~');if(f.length<35||!/^\d{14}$/.test(f[30]))continue;const code=m[1].slice(2)+'.'+m[1].slice(0,2).toUpperCase();if(!codes.includes(code))continue;const q={code,last:Number(f[3]),previous:Number(f[4]),bid:Number(f[9]),ask:Number(f[19]),timestamp:f[30]};if([q.last,q.previous].every(x=>Number.isFinite(x)&&x>0))out[code]=q;}return out;}
function quoteCheck(q,now){if(!q)return {ok:false,note:'报价缺失'};const cn=chinaTime(now),stamp=q.timestamp;const day=`${stamp.slice(0,4)}-${stamp.slice(4,6)}-${stamp.slice(6,8)}`,time=`${stamp.slice(8,10)}:${stamp.slice(10,12)}:${stamp.slice(12,14)}`;if(day!==cn.day)return {ok:false,note:'非当日报价',day,time};const age=(now.getTime()-Date.parse(`${day}T${time}+08:00`))/1000;if(!Number.isFinite(age)||age < -30||age>120)return {ok:false,note:'报价过期',day,time};if(!Number.isFinite(q.bid)||!Number.isFinite(q.ask)||q.bid<=0||q.ask<q.bid||q.ask/q.bid-1>.01)return {ok:false,note:'盘口异常',day,time};return {ok:true,note:'时效通过',day,time};}
function evaluate(live,quotes,now,networkOk=true){const cn=chinaTime(now),cal=live.calendar||[];if(live.status!=='PASS')return {ready:false,note:'模型更新异常'};if(!cal.length||cn.day<live.calendar_start||cn.day>live.calendar_end)return {ready:false,note:'交易日历过期，暂停提示'};const prior=cal.filter(d=>d<cn.day).at(-1),isTrade=cal.includes(cn.day),afterClose=cn.time>='16:00:00';const expected=isTrade&&afterClose?cn.day:prior;if(live.data_as_of!==expected)return {ready:false,note:`前收数据待更新（应为${expected}，当前${live.data_as_of}）`};if(!isTrade)return {ready:false,note:'非交易日，仅展示模型'};const next=cal.find(d=>d>cn.day);if(!next)return {ready:false,note:'未来交易日历不足'};const dayMs=Date.parse(cn.day+'T00:00:00+08:00'),weekday=new Date(dayMs+8*3600000).getUTCDay(),friday=dayMs+((5-weekday+7)%7)*86400000;const last=Date.parse(next+'T00:00:00+08:00')>friday;
if(!last)return {ready:false,note:'非周度执行日，不调仓'};
if(cn.time<'14:50:00')return {ready:false,note:'周度执行日，等待14:50'};
if(cn.time>='15:00:00')return {ready:false,note:'已收盘，不再提示执行'};
if(!live.signal?.is_final||live.signal.execution_date!==cn.day||live.signal.information_date!==prior)return {ready:false,note:'本周最终前收信号未就绪'};
if(!networkOk||!codes.every(c=>quoteCheck(quotes[c],now).ok))return {ready:false,note:'行情缺失或过期，暂停可执行提示'};
return {ready:true,note:'前收信号已定 · 行情时效通过 · 收盘附近人工执行'};}
root.TriMomentumCore={chinaTime,parseQuotes,quoteCheck,evaluate,codes};if(typeof module!=='undefined')module.exports=root.TriMomentumCore;
})(typeof window!=='undefined'?window:globalThis);
