const assert=require('node:assert/strict');
const {positionSize}=require('../../tri-momentum-vol-control/signal.js');
let checks=0;
for(const capital of [1,100,200.2,1000,12345.67,1000000]){
 for(const weight of [0,.14,.6581,1]){
  for(const price of [.001,2,2.135,8.412,140]){
   const s=positionSize(capital,weight,price);
   assert.ok(s);assert.equal(s.shares%100,0);assert.equal(s.lots,s.shares/100);
   assert.ok(s.cash>=0);assert.ok(s.amount+s.fee<=capital+1e-8);
   assert.ok(s.weight<=weight+1e-12);
   assert.ok(Math.abs(s.amount+s.fee+s.cash-capital)<1e-8);
   assert.equal(s.fee,s.amount*.001);
   const next=(s.shares+100)*price;
   assert.ok(next/(capital-next*.001)>weight-1e-12||next*(1+.001)>capital);
   checks++;
  }
 }
}
assert.equal(positionSize(200.2,1,2).shares,100);
assert.equal(positionSize(200.19,1,2).shares,0);
assert.equal(positionSize(1000000,0,2.135).cash,1000000);
for(const args of [[0,.5,2],[-1,.5,2],[NaN,.5,2],[Infinity,.5,2],[100,-.1,2],[100,1.1,2],[100,NaN,2],[100,.5,0],[100,.5,NaN],[100,.5,Infinity],[Number.MAX_VALUE,1,.001]]){
 assert.equal(positionSize(...args),null);checks++;
}
console.log(JSON.stringify({status:'PASS',sizing_cases:checks+3}));
