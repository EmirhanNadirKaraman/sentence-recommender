// Run: node --test tests/reels-controller.test.cjs
// The shipped controller runs unchanged against a tiny DOM/player boundary.
// These tests exercise gesture outcomes, not implementation string matching.
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync('web/static/app.js','utf8').split('// --- the reels feed')[1].split('// --- the quiz')[0];
class Node {
  constructor() { this.events={}; this.dataset={}; this.textContent=''; this.style={setProperty(){}}; this.clientHeight=844; this.clientWidth=390; this.open=false; this.classes=new Set(); this.classList={toggle:(k,on)=>on?this.classes.add(k):this.classes.delete(k),contains:k=>this.classes.has(k)}; this.children={}; }
  addEventListener(type,fn) { (this.events[type] ||= []).push(fn); }
  emit(type,e={}) { e.target ||= this; e.preventDefault ||= ()=>{}; e.stopImmediatePropagation ||= ()=>{}; (this.events[type] || []).forEach(fn=>fn(e)); }
  querySelector(k) { return this.children[k] || null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  setAttribute(k,v) { this[k]=v; }
  setPointerCapture() {}
  releasePointerCapture() {}
  contains(n) { return n===this; }
  showModal() { this.open=true; }
  close() { this.open=false; }
}
function setup({fail=false}={}) {
  const ids={}; ['reel','reel-state','reel-track','reel-drawer','reel-title','reel-board','reel-panel','reel-taste','reel-at','reel-total','caption','caption-en','reel-loading','reel-status','reel-controls-slot'].forEach(k=>ids[k]=new Node());
  ids['reel-state'].textContent=JSON.stringify({at:0,total:3,video:'video0',src:'subtitle',list:'travel & food',sort:'level'});
  const previous=new Node(),next=new Node();
  [previous,next].forEach(n=>{n.children.img=new Node();n.children.span=new Node();});
  const links=['easier','harder'].map(act=>{const n=new Node();n.dataset.act=act;return n;});
  const doc=new Node(); doc.getElementById=id=>ids[id];
  doc.querySelector=k=>k==='.reel-previous'?previous:k==='.reel-next'?next:null;
  doc.querySelectorAll=k=>k==='.reel-pager a[data-act]'?links:[];
  let clock=0,seq=0;const timers=new Map(),requests=[],history=[],loads=[];
  const player={mute(){},loadVideoById(d){loads.push(d.videoId);},getCurrentTime(){return 0;},getPlayerState(){return 1;},pauseVideo(){},playVideo(){}};
  let playerCount=0,readyCallback;
  const win={matchMedia:()=>({matches:true})};
  const context={document:doc,window:win,URLSearchParams,JSON,Date,Promise,Math,Number,encodeURIComponent,
    location:{pathname:'/reels',search:'?src=subtitle&list=travel&sort=level'},
    history:{replaceState:(a,b,url)=>history.push(url)},
    setTimeout:(f,ms)=>{timers.set(++seq,{f,at:clock+ms});return seq;},clearTimeout:id=>timers.delete(id),setInterval(){},
    fetch:url=>{requests.push(url);const at=Number(new URL(url,'http://test').searchParams.get('i'));return Promise.resolve({ok:!(fail&&at===1),json:()=>Promise.resolve({at,total:3,video:'video'+at,title:'Title '+at,scoreboard:'',panel:'',taste:'',familiar:.8})});},
    loadCues:()=>Promise.resolve([]),quietEvents:e=>e,hearing:{tick(){}},cueAt:()=>-1,oneStep:()=>false,
    YT:{Player:function(id,options){playerCount++;readyCallback=options.events.onReady;return player;}},learned(){},offerUndo(){},wordsHtml(){return '';}
  };
  vm.runInNewContext(code.slice(code.indexOf('(function () {')),context);
  function advance(ms) { clock+=ms;for (const [id,t] of timers) if(t.at<=clock){timers.delete(id);t.f();} }
  async function settle(ms=0) { for(let i=0;i<10;i++) await Promise.resolve();advance(ms);for(let i=0;i<10;i++) await Promise.resolve(); }
  function wheel(delta,mode=0) {ids.reel.emit('wheel',{deltaY:delta,deltaMode:mode});}
  function swipe(from,to) {ids.reel.emit('pointerdown',{isPrimary:true,clientX:195,clientY:from,timeStamp:clock,pointerId:1});ids.reel.emit('pointermove',{clientX:195,clientY:to,pointerId:1});ids.reel.emit('pointerup',{clientX:195,clientY:to,timeStamp:clock+300,pointerId:1});}
  return {ids,doc,links,requests,history,loads,win,advance,settle,wheel,swipe,start:()=>{win.onYouTubeIframeAPIReady();readyCallback();},players:()=>playerCount,state:()=>JSON.parse(ids['reel-state'].textContent)};
}
test('one wheel burst advances one clip, retains filters and uses one player',async()=>{
  const r=setup();r.start();await r.settle();r.wheel(80);await r.settle();
  for(let i=0;i<20;i++){r.advance(10);r.wheel(30);await r.settle();}
  assert.equal(r.state().at,1);assert.equal(r.players(),1);assert.equal(r.ids['reel-track'].style.transform,'');
  assert.deepEqual(r.loads,['video0','video1']);
  for(const url of r.requests.concat(r.history,r.links.map(a=>a.href))) {
    const q=new URL(url,'http://test').searchParams;assert.equal(q.get('src'),'subtitle');assert.equal(q.get('list'),'travel & food');assert.equal(q.get('sort'),'level');
  }
  r.advance(181);r.wheel(80);await r.settle();assert.equal(r.state().at,2);assert.equal(r.players(),1);
});
test('touch drag, cancellation and first/last boundaries settle cleanly',async()=>{
  const r=setup();await r.settle();r.swipe(200,500);await r.settle();assert.equal(r.state().at,0);
  r.swipe(650,250);await r.settle();assert.equal(r.state().at,1);
  r.ids.reel.emit('pointerdown',{isPrimary:true,clientX:195,clientY:650,timeStamp:0,pointerId:1});
  r.ids.reel.emit('pointermove',{clientX:195,clientY:150,pointerId:1});r.ids.reel.emit('pointercancel');
  await r.settle();assert.equal(r.state().at,1);assert.equal(r.ids['reel-track'].style.transform,'');
  r.swipe(650,250);await r.settle();r.swipe(650,250);await r.settle();assert.equal(r.state().at,2);
});
test('failed fetch keeps current video, position and iframe',async()=>{
  const r=setup({fail:true});r.start();await r.settle();r.swipe(650,250);await r.settle();
  assert.equal(r.state().at,0);assert.equal(r.state().video,'video0');assert.equal(r.players(),1);
  assert.equal(r.ids['reel-track'].style.transform,'');assert.match(r.ids['reel-status'].textContent,/Try again/);
});
test('drawer scrolling does not change reels and delayed player readiness loads current clip',async()=>{
  const r=setup();await r.settle();r.ids['reel-drawer'].showModal();r.wheel(1000);await r.settle();assert.equal(r.state().at,0);
  r.ids['reel-drawer'].close();r.swipe(650,250);await r.settle();assert.equal(r.state().at,1);
  r.start();assert.deepEqual(r.loads,['video1']);assert.equal(r.players(),1);
});
