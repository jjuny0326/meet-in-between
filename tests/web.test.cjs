// Node의 기본 테스트 도구로 실행: node --test tests/web.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const nodes = new Map();
const context = vm.createContext({
  URL, Intl,
  document: { getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, { addEventListener() {}, textContent: '', hidden: false });
    return nodes.get(id);
  } },
  fetch: () => new Promise(() => {}), // 어떤 서버/API에도 연결하지 않음
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8'), context);
const fixture = () => ({
  schema_version: 1, collected_at: '2026-10-13T22:04:00+09:00', preferences: ['cafe'],
  recommendations: [{ rank: 1, station: {place_name:'테스트역',line_name:'1호선'},
    minutes_a: 20, minutes_b: 30, transfers_a:0, transfers_b:1, total:50,difference:10,
    places: {cafe: {items:[],error:null}} }],
  analysis: {source:'rules',summary:'기본 설명',status:'AI 미사용',recommended_rank:null,
    comparisons:[{rank:1,strengths:['장점'],limitations:['한계']}]} });
test('AI 미사용, 장소 없음, 조회 실패 모두 유효한 결과로 취급', () => {
  const report = fixture();
  assert.equal(context.validateReport(report), report);
  report.recommendations[0].places.cafe.error = '조회 실패';
  assert.equal(context.validateReport(report), report);
});
test('누락된 설명과 잘못된 이동시간 또는 후보 번호를 거부', () => {
  for (const edit of [r=>r.recommendations[0].minutes_a=-1, r=>r.analysis.comparisons=[],
    r=>r.analysis.recommended_rank=7, r=>r.preferences=['unknown'], r=>r.collected_at='bad']) {
    const report = fixture(); edit(report); assert.throws(() => context.validateReport(report));
  }
  assert.throws(() => context.validateReport(null));
});
test('장소 링크는 카카오맵의 http/https만 허용', () => {
  assert.equal(context.safePlaceUrl('http://place.map.kakao.com/123'), 'https://place.map.kakao.com/123');
  for (const value of ['javascript:alert(1)', 'https://evil.example', 'https://place.map.kakao.com.evil.example/123', 'https://user@place.map.kakao.com/123', undefined]) {
    assert.equal(context.safePlaceUrl(value), null);
  }
});
test('파일 오류일 때 빈 화면 안내와 로딩 문구를 갱신', () => {
  context.showError(new Error('파일 없음'));
  assert.equal(nodes.get('empty-state').hidden, false);
  assert.match(nodes.get('timestamp').textContent, /없어요/);
});
test('정렬 기준을 바꿔도 후보 번호와 원본 순서는 보존', () => {
  const items = [
    {rank:1,difference:4,transfers_a:0,transfers_b:2},
    {rank:2,difference:1,transfers_a:1,transfers_b:3},
    {rank:3,difference:2,transfers_a:0,transfers_b:2},
  ];
  assert.equal(context.sortedCandidates(items, 'difference').map(i=>i.rank).join(','), '2,3,1');
  assert.equal(context.sortedCandidates(items, 'transfers').map(i=>i.rank).join(','), '1,3,2');
  assert.equal(context.sortedCandidates(items, 'rank').map(i=>i.rank).join(','), '1,2,3');
  assert.deepEqual(items.map(i=>i.rank), [1,2,3]);
});
test('시스템의 모션 줄이기 설정에서는 JS 애니메이션을 시작하지 않음', () => {
  let calls = 0;
  vm.runInContext('motionPreference.matches = true', context);
  try {
    context.playMotion({animate() { calls++; }}, [], {});
    assert.equal(calls, 0);
  } finally { vm.runInContext('motionPreference.matches = false', context); }
});
test('모션을 끄면 진행 중 애니메이션을 취소하고 CSS 모션도 끔', () => {
  let cancelled = 0;
  context.document.documentElement = {dataset:{}};
  nodes.set('motion-toggle', {setAttribute(){}, disabled:false});
  context.playMotion({animate() { return {finished:new Promise(()=>{}), cancel(){cancelled++;}}; }}, [], {});
  vm.runInContext('motionDisabled = true', context);
  try {
    context.syncMotionSetting();
    assert.equal(cancelled, 1);
    assert.equal(context.document.documentElement.dataset.motion, 'off');
    assert.equal(nodes.get('motion-toggle').textContent, '모션 켜기');
  } finally {
    vm.runInContext('motionDisabled = false', context);
    delete context.document.documentElement;
  }
});
test('애니메이션 API가 없는 환경에서도 기본 화면 처리를 계속함', () => {
  assert.doesNotThrow(() => context.playMotion({}, [], {}));
});

test('기준 없는 과거 파일과 세 기준은 허용하고 알 수 없는 기준은 거부', () => {
  for (const mode of [undefined,'burden','fair','transfers']) {
    const report=fixture(); report.recommendation_mode=mode;
    assert.equal(context.validateReport(report),report);
  }
  for (const mode of ['unknown',null,['fair']]) {
    const report=fixture();report.recommendation_mode=mode;
    assert.throws(()=>context.validateReport(report));
  }
});

test('경로 재사용 표시에는 원래 조회 시각과 새 호출 수를 구분', () => {
  const usage={cache_hits:10,api_calls:0,ttl_seconds:600,oldest_fetched_at:'2026-10-15T10:00:00+09:00',latest_fetched_at:'2026-10-15T10:01:00+09:00'};
  const report=fixture();report.route_usage=usage;
  assert.equal(context.validateReport(report),report);
  assert.match(context.routeUsageText(usage),/재사용 10건.*새 경로 조회 0회.*한국 시간/);
  assert.match(context.routeUsageText(undefined),/이전 저장 결과/);
  for(const edit of [r=>r.route_usage.cache_hits=-1,r=>r.route_usage.oldest_fetched_at='bad']) {
    const invalid=JSON.parse(JSON.stringify(report));edit(invalid);
    assert.throws(()=>context.validateReport(invalid));
  }
});

test('시간 차이 구간: 5분 미만 거의 같음, 15분 이상 차이 큼', () => {
  assert.equal(context.differenceLevel(0).key, 'even');
  assert.equal(context.differenceLevel(4.9).key, 'even');
  assert.equal(context.differenceLevel(5).key, 'normal');
  assert.equal(context.differenceLevel(14.9).key, 'normal');
  assert.equal(context.differenceLevel(15).key, 'large');
  assert.equal(context.differenceLevel(25).label, '차이 큼');
});
