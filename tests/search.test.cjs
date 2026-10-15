const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(fetch, {motion = false} = {}) {
  const nodes = new Map();
  function node() { return {value:'', children:[], textContent:'', disabled:false, events:{},
    attributes:{}, focusCalls:[], scrollCalls:[],
    addEventListener(name, fn) {this.events[name]=fn;}, append(...items) {this.children.push(...items);},
    replaceChildren(...items) {this.children=items;},
    setAttribute(name, value) {this.attributes[name]=value;},
    removeAttribute(name) {delete this.attributes[name];}, dataset:{},
    focus(options) {this.focusCalls.push({...options});},
    scrollIntoView(options) {this.scrollCalls.push({...options});}}; }
  const get = id => {if (!nodes.has(id)) nodes.set(id,node()); return nodes.get(id);};
  const activity = {...node(),checked:true,value:'cafe'};
  const modes = ['burden','fair','transfers'].map((value,i)=>({...node(),value,checked:i===0}));
  const state = {requestId:0,report:{previous:true}};
  const shown = [];
  // 폴링 대기(1초)는 테스트에서 즉시 넘어가도록 바꿉니다.
  const context = vm.createContext({fetch, setTimeout:fn=>Promise.resolve().then(fn), clearTimeout:()=>{}, $, document:{
    querySelectorAll:selector=>selector.includes('recommendation-mode') ? modes : [activity], createElement:node,
    // 알려진 선택자만 반환해 잘못된 선택자가 들어오면 테스트에서 드러나게 합니다.
    querySelector:selector=>selector === '.recommendation' ? get('recommendation') : null,
  }, element:node, state, showReport:r=>shown.push(r), motionEnabled:()=>motion});
  function $(id) {return get(id);}
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/search.js'),'utf8'),context);
  return {context,get,activity,modes,shown};
}

// 추천 시작(POST)은 작업 번호를, 상태 조회(GET)는 jobs 순서대로 응답합니다.
const started = {job_id:'job-1', status:'running', stage:'queued', stage_index:null, message:'추천을 준비하고 있어요.'};
const done = (report, warning=null) => ({status:'done', stage:'done', stage_index:null, report, warning});
const ok = data => ({ok:true, json:async()=>data});
function jobFetch(jobs, log=[]) {
  return async (url, options={}) => {
    log.push({url, method:options.method || 'GET', body:options.body});
    if (options.method === 'POST') return ok(started);
    const next = jobs.shift();
    if (next && typeof next.message === 'string' && !('status' in next)) throw next;
    return ok(next);
  };
}

test('두 역과 활동을 선택해야 추천 가능', () => {
  const {context} = setup(()=>{throw Error('network forbidden');});
  assert.equal(context.canRecommend({a:'a',b:'b'},['cafe'],false),true);
  for(const [selected,activities,pending] of [[{a:null,b:'b'},['cafe'],false],[{a:'a',b:'b'},[],false],[{a:'a',b:'b'},['cafe'],true]])
    assert.equal(context.canRecommend(selected,activities,pending),false);
  // 노선만 다른 같은 역은 추천하지 않습니다.
  assert.equal(context.canRecommend({a:'a',b:'b'},['cafe'],false,{a:'강남',b:'강남'}),false);
  assert.equal(context.canRecommend({a:'a',b:'b'},['cafe'],false,{a:'강남',b:'원인재'}),true);
  assert.equal(vm.runInContext("stationKey('강남역 2호선')",context),'강남');
  assert.equal(vm.runInContext("stationKey('수원역(분당)')",context),'수원');
});

test('입력 변경 후 늦게 도착한 검색 결과는 표시하지 않음', async () => {
  let resolve;
  const {context,get} = setup(url=>url.startsWith('/api/station-suggestions')
    ? Promise.resolve(ok({stations:[]})) : new Promise(r=>{resolve=r;}));
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
  const {context,get,shown}=setup((url,options={})=>{
    if (options.method !== 'POST') return Promise.resolve(ok(done({new:true})));
    calls++; return new Promise(r=>{resolve=r;});
  });
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  const submit=get('meeting-form').events.submit;
  const pending=submit({preventDefault(){}});
  await submit({preventDefault(){}});
  assert.equal(calls,1); assert.equal(get('search-controls').disabled,true);
  assert.equal(get('meeting-form').attributes['aria-busy'],'true');
  resolve(ok(started));
  await pending;
  assert.equal(shown.length,1); assert.equal(get('search-controls').disabled,false);
  // 결과 표시만으로는 부족합니다. 뒤의 포커스·스크롤에서 예외가 나도 catch가 삼킬 수 있습니다.
  assert.equal(get('search-status').textContent,'비교를 마쳤어요. 아래에서 후보별 이동시간과 장소를 살펴보세요.');
  assert.equal(get('summary-title').attributes.tabindex,'-1');
  assert.deepEqual(get('summary-title').focusCalls,[{preventScroll:true}]);
  assert.deepEqual(get('recommendation').scrollCalls,[{behavior:'instant',block:'start'}]);
  assert.equal(get('meeting-form').attributes['aria-busy'],'false');
  assert.equal(get('reload').disabled,false);
  assert.equal(get('report-file').disabled,false);
  assert.equal(get('find-button').disabled,false);
  assert.equal(get('search-progress').hidden,true);
});

test('한도 오류는 이전 결과를 보존하고 버튼을 복구', async () => {
  const {context,get,shown}=setup(async()=>({ok:false,json:async()=>({error:'한도 부족'})}));
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  await get('meeting-form').events.submit({preventDefault(){}});
  assert.equal(shown.length,0);
  assert.match(get('search-status').textContent,/한도 부족.*기존 결과/);
  assert.equal(get('find-button').disabled,false);
  assert.equal(get('summary-title').focusCalls.length,0);
  assert.equal(get('recommendation').scrollCalls.length,0);
});

test('모션을 켜면 결과 열기 단계를 거친 뒤 요약으로 부드럽게 이동하고 서버 안내도 유지', async () => {
  const warning='결과 파일 저장에 실패했지만 계산 결과는 표시해요.';
  const {context,get,shown}=setup(jobFetch([done({recommendations:[{},{},{}]},warning)]),{motion:true});
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  await get('meeting-form').events.submit({preventDefault(){}});
  assert.equal(shown.length,1);
  assert.equal(get('search-status').textContent,warning);
  // 아직 공개 전: 결과는 숨기고 '결과 열기' 버튼에 포커스
  assert.equal(get('results').hidden,true);
  assert.equal(get('reveal-stage').hidden,false);
  assert.equal(get('reveal-title').textContent,'후보 3곳을 비교했어요');
  assert.deepEqual(get('reveal-button').focusCalls,[{preventScroll:true}]);
  assert.equal(get('summary-title').focusCalls.length,0);
  get('reveal-button').events.click();
  assert.equal(get('results').hidden,false);
  assert.equal(get('reveal-stage').hidden,true);
  assert.deepEqual(get('summary-title').focusCalls,[{preventScroll:true}]);
  assert.deepEqual(get('recommendation').scrollCalls,[{behavior:'smooth',block:'start'}]);
  assert.equal(get('meeting-form').attributes['aria-busy'],'false');
});

test('추천 기준 변경만으로는 호출하지 않고 제출할 때 선택값 전송', async () => {
  const log=[];
  const {context,get,modes}=setup(jobFetch([done({})],log));
  const requests=()=>log.filter(r=>r.method==='POST').map(r=>JSON.parse(r.body));
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  modes[0].checked=false; modes[2].checked=true;
  modes[2].events.change();
  assert.equal(log.length,0);
  assert.match(get('mode-help').textContent,/환승/);
  await get('meeting-form').events.submit({preventDefault(){}});
  assert.equal(requests()[0].recommendation_mode,'transfers');
  assert.equal(get('search-status').textContent,'비교를 마쳤어요. 아래에서 후보별 이동시간과 장소를 살펴보세요.');
});

test('서버가 알려준 실제 단계를 표시하고 완료되면 결과를 보여줌', async () => {
  const running={status:'running', stage:'routes', stage_index:1, message:'경로를 새로 조회하고 있어요 · 1번째 (구일)'};
  const log=[];
  const {context,get,shown}=setup(jobFetch([running, running, done({new:true})],log));
  const items=['candidates','routes','places','ai'].map(()=>({dataset:{},attributes:{},setAttribute(n,v){this.attributes[n]=v;},removeAttribute(n){delete this.attributes[n];}}));
  get('search-progress').children=items;
  const messages=[];
  let text='';
  Object.defineProperty(get('search-status'),'textContent',{get:()=>text,set:v=>{text=v;messages.push(v);}});
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  await get('meeting-form').events.submit({preventDefault(){}});
  assert.deepEqual(log.map(r=>r.method),['POST','GET','GET','GET']);
  assert.equal(log[1].url,'/api/recommendations/job-1');
  assert.deepEqual(items.map(i=>i.dataset.state),['done','current','pending','pending']);
  assert.equal(items[1].attributes['aria-current'],'step');
  // 같은 안내는 한 번만 넣어 화면 낭독기가 반복해서 읽지 않게 합니다.
  assert.equal(messages.filter(m=>m===running.message).length,1);
  assert.equal(shown.length,1);
  assert.equal(get('search-progress').hidden,true);
});

test('잠깐 연결이 끊겨도 같은 작업을 계속 조회해 결과를 받음', async () => {
  const jobs=[];
  const {context,get,shown}=setup(jobFetch(jobs));
  // 브라우저의 fetch 연결 실패와 같은 TypeError를 화면 코드의 실행 환경 안에서 만듭니다.
  const lost=()=>vm.runInContext('new TypeError("Failed to fetch")',context);
  jobs.push(lost(), lost(), done({new:true}));
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  await get('meeting-form').events.submit({preventDefault(){}});
  assert.equal(shown.length,1);
  assert.equal(get('search-status').textContent,'비교를 마쳤어요. 아래에서 후보별 이동시간과 장소를 살펴보세요.');
});

test('연결 실패가 계속되면 결과 다시 읽기를 안내하고 버튼을 복구', async () => {
  const jobs=[];
  const {context,get,shown}=setup(jobFetch(jobs));
  for (let i=0;i<5;i++) jobs.push(vm.runInContext('new TypeError("Failed to fetch")',context));
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  await get('meeting-form').events.submit({preventDefault(){}});
  assert.equal(shown.length,0);
  assert.match(get('search-status').textContent,/결과 다시 읽기/);
  assert.equal(get('find-button').disabled,false);
});

test('작업이 실패하면 서버의 안내를 보여주고 기존 결과를 유지', async () => {
  const {context,get,shown}=setup(jobFetch([{status:'error', error:'오늘의 경로 조회 한도를 모두 사용했어요.', error_status:429}]));
  vm.runInContext('searchState.selected={a:"a",b:"b"}',context);
  await get('meeting-form').events.submit({preventDefault(){}});
  assert.equal(shown.length,0);
  assert.match(get('search-status').textContent,/한도.*기존 결과/);
  assert.equal(get('meeting-form').attributes['aria-busy'],'false');
});

test('입력하면 로컬 역 목록 후보를 보여주고 고르면 선택 번호를 저장', async () => {
  const urls=[];
  const {context,get}=setup(async url=>{urls.push(url);return ok({stations:[{token:'local-105',name:'강남역',line:'2호선'}]});});
  get('station-a-query').value='강남';
  get('station-a-query').events.input();
  await new Promise(r=>setImmediate(r));
  assert.deepEqual(urls,['/api/station-suggestions?query=%EA%B0%95%EB%82%A8']);
  const option=get('station-a-options').children[0];
  const radio=option.children[0];
  assert.equal(radio.value,'local-105');
  radio.events.change();
  assert.equal(vm.runInContext('searchState.selected.a',context),'local-105');
  assert.match(get('station-a-status').textContent,/강남역 2호선/);
});

test('여러 후보 중 고르면 선택한 역만 남기고, 다시 펼칠 수 있음', async () => {
  const {get}=setup(async()=>ok({stations:[{token:'local-1',name:'강남역',line:'2호선'},{token:'local-2',name:'강남역',line:'신분당선'}]}));
  get('station-a-query').value='강남';
  get('station-a-query').events.input();
  await new Promise(r=>setImmediate(r));
  const [first,second,change]=get('station-a-options').children;
  assert.equal(change.hidden,true);
  second.children[0].events.change();
  assert.equal(first.hidden,true); assert.equal(second.hidden,false); assert.equal(change.hidden,false);
  change.events.click();
  assert.equal(first.hidden,false); assert.equal(change.hidden,true);
});

test('두 사람이 같은 역을 고르면 버튼을 막고 안내하며, 바꾸면 안내를 지움', async () => {
  const {get}=setup(async()=>ok({stations:[{token:'local-1',name:'강남역',line:'2호선'}]}));
  for (const person of ['a','b']) {
    get(`station-${person}-query`).value='강남';
    get(`station-${person}-query`).events.input();
    await new Promise(r=>setImmediate(r));
    get(`station-${person}-options`).children[0].children[0].events.change();
  }
  assert.equal(get('find-button').disabled,true);
  assert.match(get('search-status').textContent,/출발역이 같아요/);
  get('station-b-query').value='원인재';
  get('station-b-query').events.input();
  assert.doesNotMatch(get('search-status').textContent,/출발역이 같아요/);
});

test('늦게 도착한 자동완성은 버리고 빈 입력은 요청하지 않음', async () => {
  const urls=[]; let resolve;
  const {get}=setup(url=>{urls.push(url);return new Promise(r=>{resolve=r;});});
  get('station-a-query').value='강';
  get('station-a-query').events.input();
  await new Promise(r=>setImmediate(r));
  get('station-a-query').value='';
  get('station-a-query').events.input();
  resolve(ok({stations:[{token:'local-3',name:'강남역',line:'신분당선'}]}));
  await new Promise(r=>setImmediate(r));
  assert.equal(urls.length,1);
  assert.equal(get('station-a-options').children.length,0);
  assert.equal(get('station-a-status').textContent,'역 이름을 입력하면 목록이 나타나요.');
});
