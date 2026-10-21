const assert=require('node:assert/strict');
const v=require('../../earnings-gap/volume.js'),core=require('../../earnings-gap/signal.js');
const r={ts_code:'600000.SH',name:'测试',origin:'forward',ann_date:'2026-10-21',reaction_date:'2026-10-21',list_date:'2000-01-01',report_period:'Q3',quarter_yoy:30,quarter_profit:1,volume_previous_shares:1000,volume_previous_date:'2026-10-20',volume_reference_day:'2026-10-21'};
const model={version:1,asof:'2026-10-21',times:[570,600,690,780,810,890,900],global_profile:{through:'2026-10-20',stock_days:64,median:[.05,.3,.6,.6,.7,.94,1]}};
const q={name:'测试',last:104,previous:100,open:102,high:105,low:101,timestamp:'20261021100000',volume_shares:500};
const clock=s=>new Date(`2026-10-21T${s}+08:00`);
let a=core.evaluate(r,q,clock('10:00:10'),[],[],model);
assert.equal(a.volume_state,'estimated');assert.equal(a.status_note,'量能预计达标');assert.ok(a.volume_forecast_shares>1450);
assert.equal(core.evaluate(r,{...q,open:101},clock('10:00:10'),[],[],model).volume_state,'estimated');
for(const time of ['093500','094500','100000','113000','133000','145000']){
 a=v.assess(r,{...q,timestamp:'20261021'+time},model,clock('10:00:10'),true);assert.ok(Number.isFinite(a.volume_forecast_ratio));
}
assert.equal(v.assess(r,q,model,clock('10:00:10'),false).volume_state,'pending');
assert.equal(v.assess({...r,volume_reference_day:'2026-10-20'},q,model,null,true).volume_state,'pending');
assert.equal(v.assess(r,q,{...model,global_profile:{...model.global_profile,through:'2026-10-21'}},null,true).volume_state,'pending');
assert.equal(v.assess(r,q,null,null,true).volume_state,'pending');
assert.equal(v.assess(r,q,{...model,asof:'2026-10-20'},null,true).volume_state,'pending');
const ownModel={...model,stock_profiles:{[r.ts_code]:{...model.global_profile,stock_days:20,median:Array(7).fill(.5)}}};
assert.equal(v.assess(r,q,ownModel,null,true).volume_forecast_shares,1000);
assert.equal(v.assess(r,{...q,volume_shares:1450},null,null,true).volume_state,'confirmed');
let close={...q,timestamp:'20261021150000',volume_shares:1449};
assert.equal(core.evaluate(r,close,clock('15:00:10'),[],[],model).status,'剔除');
assert.equal(core.evaluate(r,{...close,volume_shares:1450},clock('15:00:10'),[],[],model).status,'买入');
assert.equal(core.evaluate(r,{...close,volume_shares:null},clock('15:00:10'),[],[],model).status,'待核验');
assert.equal(v.assess(r,{...q,timestamp:'20261021120000'},model,null,true).volume_forecast_shares,500/.6);
const held={...r,entry_date:'2026-10-20',entry_price:100,entry_basis:100,basis_date:'2026-10-20',basis_last_close:100,stop_basis:92};
assert.equal(core.evaluate(held,{...q,volume_shares:null,high:111},clock('10:00:10'),['2026-10-20'],[],null).exit_reason,'止盈');
for(const symbol of ['sz300839','sh600233','sh688146']){
 const f=Array(40).fill('');Object.entries({1:'测试',3:'104',4:'100',5:'102',6:'100',30:'20261021100000',33:'105',34:'101'}).forEach(([i,x])=>f[i]=x);
 assert.equal(core.parseQuotes(`v_${symbol}="${f.join('~')}";`)[symbol].volume_shares,symbol==='sh688146'?100:10000);
}
console.log('VOLUME_TEST_PASS early forecasts, close gates, units, stale data and legacy exits');

for(const ratio of [1.4499,1.45,1.4501]){
 const expected=ratio>=1.45;
 const final={...q,timestamp:'20261021150000',volume_shares:ratio*1000};
 assert.equal(core.evaluate(r,final,clock('15:00:10'),[],[],model).status,expected?'买入':'剔除');
 const early=v.assess(r,{...q,volume_shares:ratio*1000*.3},model,null,true);
 assert.equal(early.volume_state,expected?'estimated':'waiting');
}
assert.equal(v.THRESHOLD,1.45);
console.log('VOLUME145_BOUNDARY_PASS 1.4499 / 1.45 / 1.4501 both estimated and close');
