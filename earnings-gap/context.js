(function(root){
'use strict';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data=null,error='',expanded=false,openIndustry=null;
const feature=row=>data?.features?.[row.id]||{};
function industry(row){const f=feature(row);return '<span title="'+esc((data?.industry_basis||'申万一级 SW2021')+'；归属日期 '+(f.industry_date||'待核验'))+'">'+esc(f.industry_l1||'行业待核验')+'</span>';}
function pb(row){
 const f=feature(row),valid=Number.isFinite(f.pb_percentile),title=(data?.pb_basis||'自身近3年正PB，至少252个观测')+'；估值日期 '+(f.pb_date||'待核验')+'；有效观测 '+(f.pb_observations??'—')+'；'+(f.pb_source||'数据待补');
 return '<span class="pb-value" title="'+esc(title)+'">'+(valid?f.pb_percentile.toFixed(1)+'%':esc(f.pb_status||'待补数据'))+'</span><span class="sub">'+(Number.isFinite(f.pb)?'PB '+f.pb.toFixed(2)+'倍':'PB —')+' · '+esc(f.pb_date||'日期待核验')+'</span>';
}
root.EarningsGapDisplay={feature,industry,pb};
if(typeof document==='undefined')return;
const $=id=>document.getElementById(id);
function original(row){
 try{const url=new URL(row.announcement_url);if(url.protocol==='https:'&&['static.cninfo.com.cn','pdf.dfcfw.com','data.eastmoney.com'].includes(url.hostname))return '<a href="'+esc(url.href)+'" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">原文 ↗</a>';}catch{}
 return '<a href="https://www.cninfo.com.cn/new/fulltextSearch?notautospecific=&keyWord='+encodeURIComponent(row.ts_code.slice(0,6)+' '+row.end_date.slice(0,4)+'年财报')+'" target="_blank" rel="noopener noreferrer" title="原文尚未匹配，前往巨潮检索">检索 ↗</a>';
}
function companyDetails(season){
 const row=season.rows.find(r=>(r.industry_code||'UNKNOWN')===openIndustry),panel=$('industryCompaniesPanel');
 panel.hidden=!row;if(!row)return;
 $('industryCompaniesTitle').textContent=row.industry+' · '+$('industryPeriod').selectedOptions[0].textContent+'已披露公司';
 $('industryCompaniesMeta').textContent='已披露 '+row.disclosed+' 家 · 收盘断层 '+row.confirmed+' 家；单季归母口径，金额单位：万元。';
 if(!Array.isArray(row.companies)||row.companies.length!==row.disclosed){$('industryCompanies').innerHTML='<tr><td colspan="8" class="empty">公司明细尚未齐备，请等待展示数据更新；不能据此认定没有已披露公司。</td></tr>';return;}
 const money=v=>Number.isFinite(v)?(v/10000).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
 const change=v=>Number.isFinite(v)?(v>0?'+':'')+v.toFixed(2)+'%':'—';
 $('industryCompanies').innerHTML=row.companies.length?row.companies.map(r=>{
  const label=r.state==='confirmed'?'收盘通过':r.state==='rejected'?'未通过':r.reason==='待收盘确认'?'待收盘确认':'待核验';
  return '<tr class="'+(r.state==='confirmed'?'candidate-selected':'')+'"><td><span class="stock">'+esc(r.name)+'</span><span class="sub">'+esc(r.ts_code)+'</span></td><td>'+esc(r.ann_date)+'<span class="sub">'+esc(r.reaction_date||'待确定')+'</span></td><td class="num '+(r.quarter_profit<0?'down':'')+'" title="'+esc(r.financial_source||'数据待补')+'">'+money(r.quarter_profit)+'</td><td class="num '+(r.quarter_yoy>0?'up':r.quarter_yoy<0?'down':'')+'">'+change(r.quarter_yoy)+'</td><td><span class="pill '+(r.financial_result==='未通过'?'reject':'')+'">'+esc(r.financial_result||'待核验')+'</span></td><td><span class="pill '+(r.state==='confirmed'?'watch':r.state==='rejected'?'reject':'')+'">'+label+'</span></td><td>'+esc(r.reason||'待核验')+'</td><td>'+original(r)+'</td></tr>';
 }).join(''):'<tr><td colspan="8" class="empty">本报告期该行业尚无已披露公司。</td></tr>';
}
function render(){
 if(!$('industryRows'))return;
 const period=$('industryPeriod').value,seasons=data?.seasons||[],season=seasons.find(r=>r.end_date===period)||seasons[0];
 if(!season){const inactive=data&&!error&&Array.isArray(data.seasons)&&!data.seasons.length;$('industryRows').innerHTML='<tr><td colspan="5" class="empty">'+esc(error||(inactive?'当前时段暂无参与策略的报告季（年报已剔除）。':'行业统计正在读取，暂不能判断发生率。'))+'</td></tr>';$('industryMeta').textContent=inactive?'仅统计一季报、中报、三季报':'统计数据待核验';$('industryCompaniesPanel').hidden=true;return;}
 const cn=new Date(Date.now()+8*3600000).toISOString(),day=cn.slice(0,10),stale=data.asof<day,lateClose=cn.slice(11,16)>='15:45'&&data.asof===day&&season.waiting_close>0&&season.close_asof<day,waitingLabel=cn.slice(11,16)>='15:00'?'待收盘归档':'待收盘';
 $('industryMeta').textContent='披露截至 '+season.disclosure_asof+' · 收盘确认截至 '+season.close_asof+' · 申万一级 SW2021（归属日 '+season.industry_date+'）';
 const notices=[error,data.refresh_status==='FAILED'?'本次展示数据更新失败，保留上次快照。':'',stale?'尚未更新至今天。':'',lateClose?'今日收盘行业统计尚未归档，请核验更新任务。':'',season.waiting_close?season.waiting_close+' 家'+waitingLabel+'。':'',season.missing?season.missing+' 家数据待核验。':'',season.pending?'发生率及排名为暂定值。':'',season.unknown_industry?'行业待核验 '+season.unknown_industry+' 家，单列且不参与排名。':''].filter(Boolean);
 $('industryStatus').textContent=notices.join(' ');$('industryStatus').hidden=!notices.length;
 const ranked=season.rows.filter(r=>r.industry_code),rows=expanded?season.rows:ranked.filter(r=>r.disclosed>0).slice(0,5);
 $('industryRows').innerHTML=rows.length?rows.map(r=>{const key=r.industry_code||'UNKNOWN',selected=key===openIndustry;return '<tr data-industry="'+esc(key)+'" class="industry-summary-row'+(selected?' industry-open':'')+'"><td><button class="industry-open-button" aria-controls="industryCompaniesPanel" aria-expanded="'+selected+'" title="查看本行业当季全部已披露公司">'+(selected?'▾ ':'▸ ')+esc(r.industry)+'</button></td><td class="num">'+(r.ratio_pct==null?'—':(r.pending?'≥':'')+r.ratio_pct.toFixed(2)+'%')+'</td><td class="num">'+r.confirmed+' 家</td><td class="num">'+r.disclosed+' 家</td><td>'+(!r.industry_code?'行业待核验':!r.disclosed?'尚无已披露':r.pending?[r.waiting_close?r.waiting_close+' 家'+waitingLabel:'',r.pending-r.waiting_close?r.pending-r.waiting_close+' 家待核验':''].filter(Boolean).join(' · '):r.disclosed<10?'小样本':'已核验')+'</td></tr>';}).join(''):'<tr><td colspan="5" class="empty">本报告期尚无可核验的行业披露记录。</td></tr>';
 $('industryToggle').textContent=expanded?'收起全部行业 ↑':'展开全部 '+ranked.length+' 个行业 →';
 $('industryToggle').setAttribute('aria-expanded',String(expanded));
 companyDetails(season);
}
async function refresh(){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),18000);
 try{const r=await fetch('earnings-gap/data/display_context.json?t='+Math.floor(Date.now()/60000),{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error('HTTP '+r.status);const next=await r.json();if(next.version!==1)throw Error('展示数据版本待核验');data=next;error='';const old=$('industryPeriod').value;$('industryPeriod').innerHTML=(data.seasons||[]).map(r=>'<option value="'+esc(r.end_date)+'">'+esc(r.end_date.slice(0,4)+({'03':'一季报','06':'中报','09':'三季报','12':'年报'})[r.end_date.slice(5,7)])+'</option>').join('');if((data.seasons||[]).some(r=>r.end_date===old))$('industryPeriod').value=old;}
 catch{error='展示数据读取失败，PB及行业信息待核验；不影响原有信号计算。';}
 finally{clearTimeout(timer);render();root.dispatchEvent(new Event('earnings-gap-context'));}
}
$('industryPeriod').onchange=()=>{expanded=false;openIndustry=null;render();};
$('industryToggle').onclick=()=>{expanded=!expanded;render();};
$('industryRows').onclick=event=>{const row=event.target.closest('tr[data-industry]');if(row){openIndustry=openIndustry===row.dataset.industry?null:row.dataset.industry;render();}};
$('industryCompaniesClose').onclick=()=>{openIndustry=null;render();};
refresh();setInterval(()=>{if(!document.hidden)refresh();},300000);
})(typeof globalThis!=='undefined'?globalThis:this);
