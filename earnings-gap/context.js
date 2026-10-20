(function(root){
'use strict';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data=null,error='',expanded=false;
const feature=row=>data?.features?.[row.id]||{};
function industry(row){const f=feature(row);return '<span title="'+esc((data?.industry_basis||'申万一级 SW2021')+'；归属日期 '+(f.industry_date||'待核验'))+'">'+esc(f.industry_l1||'行业待核验')+'</span>';}
function pb(row){
 const f=feature(row),valid=Number.isFinite(f.pb_percentile),title=(data?.pb_basis||'自身近3年正PB，至少252个观测')+'；估值日期 '+(f.pb_date||'待核验')+'；有效观测 '+(f.pb_observations??'—')+'；'+(f.pb_source||'数据待补');
 return '<span class="pb-value" title="'+esc(title)+'">'+(valid?f.pb_percentile.toFixed(1)+'%':esc(f.pb_status||'待补数据'))+'</span><span class="sub">'+(Number.isFinite(f.pb)?'PB '+f.pb.toFixed(2)+'倍':'PB —')+' · '+esc(f.pb_date||'日期待核验')+'</span>';
}
root.EarningsGapDisplay={feature,industry,pb};
if(typeof document==='undefined')return;
const $=id=>document.getElementById(id);
function render(){
 if(!$('industryRows'))return;
 const period=$('industryPeriod').value,seasons=data?.seasons||[],season=seasons.find(r=>r.end_date===period)||seasons[0];
 if(!season){$('industryRows').innerHTML='<tr><td colspan="5" class="empty">'+esc(error||'行业统计正在读取，暂不能判断发生率。')+'</td></tr>';$('industryMeta').textContent='统计数据待核验';return;}
 const day=new Date(Date.now()+8*3600000).toISOString().slice(0,10),stale=data.asof<day;
 $('industryMeta').textContent='披露截至 '+season.disclosure_asof+' · 收盘确认截至 '+season.close_asof+' · 申万一级 SW2021（归属日 '+season.industry_date+'）';
 const notices=[error,data.refresh_status==='FAILED'?'本次展示数据更新失败，保留上次快照。':'',stale?'尚未更新至今天。':'',season.waiting_close?season.waiting_close+' 家待收盘。':'',season.missing?season.missing+' 家数据待核验。':'',season.pending?'发生率及排名为暂定值。':'',season.unknown_industry?'行业待核验 '+season.unknown_industry+' 家，单列且不参与排名。':''].filter(Boolean);
 $('industryStatus').textContent=notices.join(' ');$('industryStatus').hidden=!notices.length;
 const ranked=season.rows.filter(r=>r.industry_code),rows=expanded?season.rows:ranked.filter(r=>r.disclosed>0).slice(0,5);
 $('industryRows').innerHTML=rows.length?rows.map(r=>'<tr><td>'+esc(r.industry)+'</td><td class="num">'+(r.ratio_pct==null?'—':(r.pending?'≥':'')+r.ratio_pct.toFixed(2)+'%')+'</td><td class="num">'+r.confirmed+' 家</td><td class="num">'+r.disclosed+' 家</td><td>'+(!r.industry_code?'行业待核验':!r.disclosed?'尚无已披露':r.pending?[r.waiting_close?r.waiting_close+' 家待收盘':'',r.pending-r.waiting_close?r.pending-r.waiting_close+' 家待核验':''].filter(Boolean).join(' · '):r.disclosed<10?'小样本':'已核验')+'</td></tr>').join(''):'<tr><td colspan="5" class="empty">本报告期尚无可核验的行业披露记录。</td></tr>';
 $('industryToggle').textContent=expanded?'收起全部行业 ↑':'展开全部 '+ranked.length+' 个行业 →';
 $('industryToggle').setAttribute('aria-expanded',String(expanded));
}
async function refresh(){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),18000);
 try{const r=await fetch('earnings-gap/data/display_context.json?t='+Math.floor(Date.now()/60000),{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error('HTTP '+r.status);const next=await r.json();if(next.version!==1)throw Error('展示数据版本待核验');data=next;error='';const old=$('industryPeriod').value;$('industryPeriod').innerHTML=(data.seasons||[]).map(r=>'<option value="'+esc(r.end_date)+'">'+esc(r.end_date.slice(0,4)+({'03':'一季报','06':'中报','09':'三季报','12':'年报'})[r.end_date.slice(5,7)])+'</option>').join('');if((data.seasons||[]).some(r=>r.end_date===old))$('industryPeriod').value=old;}
 catch{error='展示数据读取失败，PB及行业信息待核验；不影响原有信号计算。';}
 finally{clearTimeout(timer);render();root.dispatchEvent(new Event('earnings-gap-context'));}
}
$('industryPeriod').onchange=()=>{expanded=false;render();};
$('industryToggle').onclick=()=>{expanded=!expanded;render();};
refresh();setInterval(()=>{if(!document.hidden)refresh();},300000);
})(typeof globalThis!=='undefined'?globalThis:this);
