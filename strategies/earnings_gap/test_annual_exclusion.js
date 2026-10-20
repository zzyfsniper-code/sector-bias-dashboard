const assert=require('node:assert/strict');
const core=require('../../earnings-gap/signal.js');
const monitor=require('../../earnings-gap/monitor.js');
const now=new Date('2026-10-20T15:01:00+08:00');
const q={name:'测试',last:104,previous:100,open:103,high:105,low:102,timestamp:'20261020150000'};
const annual={origin:'forward',ts_code:'600000.SH',name:'测试',report_period:'FY',end_date:'2025-12-31',
    ann_date:'2026-10-20',reaction_date:'2026-10-20',list_date:'2000-01-01',quarter_profit:100,quarter_yoy:100};
assert.equal(core.evaluate(annual,q,now,['2026-10-19','2026-10-20']).status,'剔除');
assert.equal(core.evaluate(annual,null,now).status_note,'年报不参与策略');
assert.equal(core.evaluate({...annual,report_period:'Q1',end_date:'2026-03-31'},q,now).status,'买入');
const held={...annual,entry_date:'2026-10-19',entry_price:100,entry_basis:100,basis_date:'2026-10-19',basis_last_close:100,stop_basis:92};
assert.equal(core.evaluate(held,{...q,open:111,high:111},now,['2026-10-19','2026-10-20']).exit_reason,'止盈');
const report=monitor.reportState({...annual,complete:false,financial_eligible:true});
assert.equal(report.reason,'年报不参与策略');assert.equal(report.financial_eligible,false);assert.equal(report.complete,true);
assert.deepEqual(monitor.filterReports([report],'financial'),[]);
assert.equal(monitor.filterReports([report],'all').length,1);
console.log('Annual exclusion JS checks PASS');
