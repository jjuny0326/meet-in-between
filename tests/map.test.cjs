const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(key='') {
  const elements = new Map(), overlays = [], calls = [];
  function node() { return {children:[],events:{},hidden:true,textContent:'',attrs:{},classList:{toggle(){}},
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
    addEventListener(name,fn){this.events[name]=fn;},setAttribute(k,v){this.attrs[k]=v;},
    remove(){},scrollIntoView(){},focus(){}}; }
  const get = id => {if(!elements.has(id))elements.set(id,node());return elements.get(id);};
  let scripts=0;
  const context=vm.createContext({setTimeout,clearTimeout,document:{getElementById:get,querySelectorAll:()=>[],createElement:node,
    head:{append(script){scripts++;script.onload();}}},
    fetch:async url=>{calls.push(url);return {ok:true,json:async()=>({javascript_key:key})};},safePlaceUrl:()=>null,
    kakao:{maps:{load:fn=>fn(),LatLng:class {constructor(lat,lng){this.lat=lat;this.lng=lng;}},
      LatLngBounds:class {extend(){}},ZoomControl:class {},ControlPosition:{RIGHT:1},
      Map:class {addControl(){}setZoomable(){}relayout(){}setBounds(){}setCenter(){}setLevel(){}},
      CustomOverlay:class {constructor(options){Object.assign(this,options);overlays.push(this);}setMap(value){this.map=value;}}
    }}
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/map.js'),'utf8'),context);
  return {api:vm.runInContext('MeetingMap',context),get,overlays,calls,scripts:()=>scripts};
}
function report() {
  return {recommendations:[1,2,3].map(rank=>({rank,station:{place_name:`역${rank}`,x:126.8+rank/100,y:37.5},minutes_a:40,minutes_b:41,
    places:{cafe:{items:[{id:'shared',name:'카페',address:'주소',x:126.8+rank/100,y:37.501}],error:null},food:{items:[],error:null}}}))};
}
test('좌표 0은 유효하고 빈 값·불리언·범위 밖 좌표는 제외',()=>{
  const {api}=setup();
  assert.equal(api.coordinates({x:0,y:0}).lat,0);
  for(const x of [null,undefined,'', ' ',true,'NaN',181])assert.equal(api.coordinates({x,y:37}),null);
});
test('활동과 후보 선택에 맞춰 지도점을 고르고 누락·실패를 구분',()=>{
  const {api}=setup(), data=report();
  assert.equal(api.pointsFor(data,'cafe').points.length,6);
  assert.equal(api.pointsFor(data,'food',2).points.length,1);
  delete data.recommendations[0].places.cafe.items[0].x;
  data.recommendations[1].places.cafe.error='실패';
  const points=api.pointsFor(data,'cafe');
  assert.equal(points.missingPlaces,1);assert.equal(points.failedGroups,1);assert.equal(points.points.length,4);
});
test('같은 좌표의 장소는 하나의 마커 안에 모두 유지',()=>{
  const {api}=setup();
  assert.equal(api.groupPoints([{position:{lat:37,lng:127},name:'a'},{position:{lat:37,lng:127},name:'b'}])[0].length,2);
});
test('지도는 명시적으로 열 때만 설정 조회, 키 누락시 카드 데이터 유지',async()=>{
  const {api,get,calls,scripts}=setup();const data=report();api.update(data,'cafe');
  assert.equal(calls.length,0);
  await api.focus(null);
  assert.deepEqual(calls,['/api/map-config']);assert.equal(scripts(),0);
  assert.match(get('map-status').textContent,/KAKAO_JAVASCRIPT_KEY/);
  assert.equal(data.recommendations.length,3);assert.equal(get('map-load').disabled,false);
});
test('SDK 한 번 로딩 후 필터 전환은 마커만 교체, 클릭시 상세 정보 표시',async()=>{
  const {api,get,overlays,calls,scripts}=setup('test-js');const data=report();api.update(data,'cafe');
  await api.focus(null);
  assert.equal(overlays.filter(o=>o.map).length,6);
  const place=overlays.find(o=>o.content.className.includes('place'));
  place.content.events.click();assert.equal(get('map-detail').children.length,1);
  await api.focus(2);assert.equal(overlays.filter(o=>o.map).length,2);
  api.update(data,'food');assert.equal(overlays.filter(o=>o.map).length,1);
  api.update(report(),'cafe');assert.equal(overlays.filter(o=>o.map).length,6);
  assert.equal(calls.length,1);assert.equal(scripts(),1);
});
