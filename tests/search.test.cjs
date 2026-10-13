const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(fetch) {
  const nodes = new Map();
  function node() { return {value:'', children:[], textContent:'', disabled:false, events:{},
    addEventListener(name, fn) {this.events[name]=fn;}, append(...items) {this.children.push(...items);},
    replaceChildren(...items) {this.children=items;}, setAttribute(){}, focus(){}, scrollIntoView(){}}; }
  const get = id => {if (!nodes.has(id)) nodes.set(id,node()); return nodes.get(id);};
  const activity = {...node(),checked:true,value:'cafe'};
  const state = {requestId:0,report:{previous:true}};
  const shown = [];
  const context = vm.createContext({fetch, $, document:{querySelectorAll:()=>[activity],createElement:node},
    element:node, state, showReport:r=>shown.push(r), motionEnabled:()=>false});
  function $(id) {return get(id);}
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/search.js'),'utf8'),context);
  return {context,get,activity,shown};
}

test('두 역과 활동을 선택해야 추천 가능', () => {
  const {context} = setup(()=>{throw Error('network forbidden');});
  assert.equal(context.canRecommend({a:'a',b:'b'},['cafe'],false),true);
  for(const [selected,activities,pending] of [[{a:null,b:'b'},['cafe'],false],[{a:'a',b:'b'},[],false],[{a:'a',b:'b'},['cafe'],true]])
    assert.equal(context.canRecommend(selected,activities,pending),false);
});

test('입력 변경 후 늦게 도착한 검색 결과는 표시하지 않음', async () => {
  let resolve;
  const {context,get} = setup(()=>new Promise(r=>{resolve=r;}));
  get('station-a-query').value='old';
  const pending=context.findStations('a');
  get('station-a-query').value='new'; get('station-a-query').events.input();
  resolve({ok:true,json:async()=>({stations:[{token:'old',name:'old',address:''}]})});
  await pending;
  assert.equal(get('station-a-options').children.length,0);
  assert.equal(get('find-button').disabled,true);
});

test('중복 제출은 1회만 전송하고 완료 후 결과를 표시하며 입력 복구', async () => {
  let resolve,calls=0;
  const {context,get,shown}=setup(()=>{calls++;return new Promise(r=>{resolve=r;});});
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  const submit=get('meeting-form').events.submit;
  const pending=submit({preventDefault(){}});
  await submit({preventDefault(){}});
  assert.equal(calls,1); assert.equal(get('search-controls').disabled,true);
  resolve({ok:true,json:async()=>({report:{new:true}})});
  await pending;
  assert.equal(shown.length,1); assert.equal(get('search-controls').disabled,false);
});

test('한도 오류는 이전 결과를 보존하고 버튼을 복구', async () => {
  const {context,get,shown}=setup(async()=>({ok:false,json:async()=>({error:'한도 부족'})}));
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  await get('meeting-form').events.submit({preventDefault(){}});
  assert.equal(shown.length,0);
  assert.match(get('search-status').textContent,/한도 부족.*기존 결과/);
  assert.equal(get('find-button').disabled,false);
});

test('추천 기준 변경만으로는 호출하지 않고 제출할 때 선택값 전송', async () => {
  const requests=[];
  const {context,get}=setup(async(url,options)=>{requests.push(JSON.parse(options.body));return {ok:true,json:async()=>({report:{}})};});
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  get('recommendation-mode').value='transfers';
  get('recommendation-mode').events.change();
  assert.equal(requests.length,0);
  assert.match(get('mode-help').textContent,/환승/);
  await get('meeting-form').events.submit({preventDefault(){}});
  assert.equal(requests[0].recommendation_mode,'transfers');
});
