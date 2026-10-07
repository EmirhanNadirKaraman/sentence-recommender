const test=require('node:test'), assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs');
const code=fs.readFileSync('web/static/cover.js','utf8');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.events={};this.dataset={};this.value='';this.textContent='';this.disabled=false;this.attributes={};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  addEventListener(name,fn){this.events[name]=fn;}
  setAttribute(k,v){this.attributes[k]=v;}
  removeAttribute(k){delete this.attributes[k];}
  scrollIntoView(){}
}
function setup(){
  const ids={};for(const id of ['cover-builder','cover-query','cover-name','cover-search-results','cover-search-status','cover-selected','cover-count','cover-build','cover-build-status','cover-result'])ids[id]=new Element();
  ids['cover-builder'].dataset={src:'subtitle',selected:'[]'};
  const timers=new Map(), pending=[];let serial=0;
  const context={Map,JSON,URL,URLSearchParams,AbortController,Array,Error,
    document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag)},
    location:{href:'http://localhost/cover?list=study_list'},history:{replaceState(){}},
    window:{matchMedia:()=>({matches:true})},
    setTimeout:fn=>{timers.set(++serial,fn);return serial;},clearTimeout:id=>timers.delete(id),
    fetch:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}))};
  vm.runInNewContext(code,context);
  return {ids,pending,async type(value){ids['cover-query'].value=value;ids['cover-query'].events.input();},
    run(){const jobs=[...timers.values()];timers.clear();jobs.forEach(fn=>fn());},
    async reply(index,data){pending[index].resolve({ok:true,json:async()=>data});await new Promise(setImmediate);},
    name(value){ids['cover-name'].value=value;ids['cover-name'].events.input();}};
}
const word=key=>({kind:'lemma',key,said:10,known:false});
test('late search results cannot replace a newer query, and prior request is aborted',async()=>{
  const h=setup();await h.type('ha');h.run();await h.type('haus');h.run();
  assert.equal(h.pending[0].options.signal.aborted,true);
  await h.reply(1,{results:[word('Haus')]});await h.reply(0,{results:[word('Haben')]});
  assert.equal(h.ids['cover-search-results'].children[0].attributes['aria-label'],'Add Haus');
  await h.type('');assert.equal(h.ids['cover-search-results'].children.length,0);
});
test('selected words survive search changes, duplicate additions are disabled, and removal enables them',async()=>{
  const h=setup();await h.type('haus');h.run();await h.reply(0,{results:[word('Haus')]});
  h.ids['cover-search-results'].children[0].events.click();
  assert.equal(h.ids['cover-count'].textContent,1);
  assert.equal(h.ids['cover-search-results'].children[0].disabled,true);
  await h.type('hund');h.run();await h.reply(1,{results:[word('Hund')]});
  h.ids['cover-search-results'].children[0].events.click();assert.equal(h.ids['cover-count'].textContent,2);
  h.ids['cover-selected'].children[1].children[1].events.click();assert.equal(h.ids['cover-count'].textContent,1);
  assert.equal(h.ids['cover-search-results'].children[0].disabled,false);
});
test('build sends all selected units once and failure keeps the draft editable',async()=>{
  const h=setup();await h.type('a');h.run();await h.reply(0,{results:[word('a')]});
  h.ids['cover-search-results'].children[0].events.click();h.name('mine');
  const first=h.ids['cover-build'].events.click();await h.ids['cover-build'].events.click();
  assert.equal(h.pending.length,2);assert.equal(h.ids['cover-query'].disabled,true);
  const form=h.pending[1].options.body;
  assert.deepEqual(JSON.parse(form.get('selected')),[{kind:'lemma',key:'a'}]);
  assert.equal(form.get('list'),'study_list');
  await h.reply(1,{error:'Try again'});await first;
  assert.equal(h.ids['cover-count'].textContent,1);assert.equal(h.ids['cover-build'].disabled,false);
  assert.equal(h.ids['cover-build-status'].textContent,'Try again');
});
test('partial feasible cover is shown honestly and the saved collection remains editable',async()=>{
  const h=setup();await h.type('a');h.run();await h.reply(0,{results:[word('a'),word('b')]});
  h.ids['cover-search-results'].children[0].events.click();h.ids['cover-search-results'].children[1].events.click();h.name('mine');
  const building=h.ids['cover-build'].events.click();
  await h.reply(1,{name:'mine',total:2,covered:1,known:[],unreachable:['b'],optimal:false,minutes:1,
    list_url:'/lists?name=mine',videos:[{title:'A video',url:'/video?id=v&t=10',minutes:1,estimated:false,
      examples:[{word:'a',text:'A real sentence',url:'/video?id=v&t=10',time:'0:10'}]}]});await building;
  function text(el){return el.textContent+' '+el.children.map(text).join(' ');}
  const copy=text(h.ids['cover-result']);
  assert.match(copy,/minimum size is not proven/);assert.match(copy,/Not covered yet/);
  assert.match(copy,/1 word within reach/);assert.equal(h.ids['cover-build'].disabled,false);
});
