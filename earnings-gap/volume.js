(function(root){
'use strict';
const THRESHOLD=1.45,EFFECTIVE='2026-10-21';
function required(record,reaction){return !record.entry_date&&reaction>=EFFECTIVE;}
function assess(record,quote,model,now,fresh){
 const pending={volume_state:'pending',volume_note:'量能待核验',volume_ratio:null,volume_forecast_ratio:null,volume_actual_shares:null,volume_forecast_shares:null};
 const stamp=quote?.timestamp||'',day=stamp.slice(0,4)+'-'+stamp.slice(4,6)+'-'+stamp.slice(6,8),minute=Number(stamp.slice(8,10))*60+Number(stamp.slice(10,12));
 const previous=record.volume_previous_shares,actual=quote?.volume_shares;
 if(!fresh||record.volume_reference_day!==day||!(record.volume_previous_date<day)||!Number.isFinite(previous)||previous<=0||!Number.isFinite(actual)||actual<0||minute<570)return pending;
 const out={...pending,volume_actual_shares:actual,volume_ratio:actual/previous},closed=minute>=900;
 if(closed)return {...out,volume_forecast_shares:actual,volume_forecast_ratio:out.volume_ratio,volume_state:out.volume_ratio+1e-12>=THRESHOLD?'confirmed':'failed',volume_note:out.volume_ratio+1e-12>=THRESHOLD?'量能已达标':'收盘量能不足1.45倍'};
 const own=model?.stock_profiles?.[record.ts_code],profile=own?.through<day?own:model?.global_profile;
 if(model?.version===1&&model.asof===day&&profile?.through<day&&Array.isArray(model.times)){
  let index=0;for(let i=0;i<model.times.length;i++){if(model.times[i]>minute)break;index=i;}
  const fraction=profile.median?.[index];
  if(Number.isFinite(fraction)&&fraction>0&&fraction<=1){
   out.volume_forecast_shares=Math.max(actual,actual/fraction);out.volume_forecast_ratio=out.volume_forecast_shares/previous;
   out.volume_profile_days=profile.stock_days;out.volume_profile_kind=profile===own?'自身最近完整日（最多20日）':'跨板块样本';out.volume_profile_through=profile.through;
   const lo=profile.p75?.[index],hi=profile.p25?.[index];
   if(lo>0&&hi>0){out.volume_forecast_low=actual/lo;out.volume_forecast_high=actual/hi;}
  }
 }
 const state=out.volume_ratio+1e-12>=THRESHOLD?'confirmed':out.volume_forecast_ratio===null?'pending':out.volume_forecast_ratio+1e-12>=THRESHOLD?'estimated':'waiting';
 return {...out,volume_state:state,volume_note:({confirmed:'量能已达标',estimated:'量能预计达标',waiting:'等待量能放大',pending:'量能曲线待核验'})[state]};
}
function cell(row,forecast=false){
 const ratio=forecast?row.volume_forecast_ratio:row.volume_ratio,shares=forecast?row.volume_forecast_shares:row.volume_actual_shares;
 if(!Number.isFinite(ratio)||!Number.isFinite(shares))return '<span title="量能数据或曲线待核验">—</span>';
 const sample=forecast?`${row.volume_profile_kind||'收盘量'} · ${row.volume_profile_days||'—'}个股票日 · 截至${row.volume_profile_through||row.reaction_date||'—'}`:'相对前一实际交易日成交量';
 return `<span title="${sample}">${ratio.toFixed(2)}倍</span><span class="sub">${(shares/10000).toLocaleString('zh-CN',{maximumFractionDigits:0})}万股</span>`;
}
root.EarningsGapVolume={THRESHOLD,EFFECTIVE,required,assess,cell};if(typeof module!=='undefined')module.exports=root.EarningsGapVolume;
})(typeof globalThis==='undefined'?this:globalThis);
