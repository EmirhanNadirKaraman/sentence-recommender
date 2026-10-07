const test=require('node:test'), assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const all=fs.readFileSync('web/static/app.js','utf8');
const code=all.slice(all.indexOf('var hearing = (function () {'),all.indexOf('// The control bar under every player.'));
function setup(){
  const batches=[],timers=new Map();let id=0,periodic;
  const env={JSON,Math,Number,Blob,window:{addEventListener(){}},document:{addEventListener(){}},navigator:{},
    clearTimeout:k=>timers.delete(k),setTimeout:f=>{timers.set(++id,f);return id;},setInterval:f=>{periodic=f;},
    fetch:(url,o)=>{batches.push(JSON.parse(o.body));return Promise.resolve({ok:true,json:()=>Promise.resolve({})});}};
  vm.runInNewContext(code,env);
  return {tick:env.hearing.tick,batches,flush:()=>periodic(),reward:()=>{for(const [k,f] of timers){timers.delete(k);f();}}};
}
const cue={text:'A spoken line',at:0,duration:8,words:[['line','lemma','line']]};
test('opening, pausing and skipping a cue are not listening rewards',()=>{
  const h=setup();for(let i=0;i<40;i++)h.tick('video',0,cue,false,1);
  h.tick('video',-1,cue,true,1);h.tick('video',1,null,true,1);h.flush();assert.equal(h.batches.length,0);
});
test('early encounter is preserved, XP requires most of the line and rewards once',()=>{
  const h=setup();for(let i=0;i<4;i++)h.tick('video',0,cue,true,1);h.flush();
  assert.equal(h.batches[0][0].reward,false);
  for(let i=0;i<20;i++)h.tick('video',0,cue,true,1);h.reward();
  assert.equal(h.batches[1][0].reward,true);
  for(let i=0;i<100;i++)h.tick('video',0,cue,true,1);h.flush();assert.equal(h.batches.length,2);
});
test('listening duration follows playback speed without rewarding paused playback',()=>{
  for(const [rate,ticks] of [[2,12],[.5,48]]) {
    const h=setup();for(let i=0;i<ticks-1;i++)h.tick('video',0,cue,true,rate);h.flush();
    assert.ok(h.batches.flat().every(line=>!line.reward));
    h.tick('video',0,cue,true,rate);h.reward();assert.equal(h.batches.at(-1).at(-1).reward,true);
  }
});
