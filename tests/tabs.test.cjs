// 모바일 하단 탭 동작 검증: node --test tests/tabs.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup({mobile = true} = {}) {
  const buttons = ['search','results','map','guide'].map(tab => ({dataset:{tab}, attributes:{}, events:{},
    setAttribute(k,v){this.attributes[k]=v;}, removeAttribute(k){delete this.attributes[k];},
    addEventListener(n,f){this.events[n]=f;}}));
  const sections = {'comparison-title': {closest:()=>({dataset:{view:'results map'}})}, 'reading-guide': {closest:()=>({dataset:{view:'guide'}})}};
  const root = {dataset:{tab:'search'}};
  const docEvents = {}, scrolls = [], refreshed = [];
  const context = vm.createContext({
    matchMedia: () => ({matches: mobile}),
    window: {scrollTo: (o) => scrolls.push(o)},
    MeetingMap: {refresh: () => refreshed.push(true)},
    requestAnimationFrame: (fn) => fn(),
    document: {documentElement: root, querySelectorAll: () => buttons, getElementById: id => sections[id] || null,
      addEventListener: (n, f) => { docEvents[n] = f; }},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/tabs.js'), 'utf8'), context);
  return {context, buttons, root, docEvents, scrolls, refreshed};
}

test('처음에는 찾기 탭이 선택되고 탭을 누르면 화면과 표시가 바뀜', () => {
  const {buttons, root, scrolls} = setup();
  assert.equal(root.dataset.tab, 'search');
  assert.equal(buttons[0].attributes['aria-current'], 'page');
  buttons[1].events.click();
  assert.equal(root.dataset.tab, 'results');
  assert.equal(buttons[1].attributes['aria-current'], 'page');
  assert.equal(buttons[0].attributes['aria-current'], undefined);
  assert.equal(JSON.stringify(scrolls), JSON.stringify([{top: 0, behavior: 'instant'}]));
});

test('지도 탭을 열면 지도 크기를 다시 맞추고, 알 수 없는 탭은 무시', () => {
  const {context, root, refreshed} = setup();
  context.showTab('map');
  assert.equal(root.dataset.tab, 'map');
  assert.equal(refreshed.length, 1);
  context.showTab('unknown');
  assert.equal(root.dataset.tab, 'map');
});

test('페이지 안 링크는 그 내용이 있는 탭으로 먼저 이동 (모바일에서만)', () => {
  const link = {getAttribute: () => '#reading-guide'};
  const event = {target: {closest: () => link}};
  const mobile = setup();
  mobile.docEvents.click(event);
  assert.equal(mobile.root.dataset.tab, 'guide');
  const desktop = setup({mobile: false});
  desktop.docEvents.click(event);
  assert.equal(desktop.root.dataset.tab, 'search');
  assert.equal(desktop.scrolls.length, 0);
});

test('결과가 생기면 준비 표시를 하고, 다른 탭에 있으면 결과 탭에 새 결과 점을 찍음', () => {
  const {context, buttons, root} = setup();
  context.markResultReady();
  assert.equal(root.dataset.result, 'ready');
  assert.equal(buttons[1].dataset.new, 'true');
  context.showTab('results');
  assert.equal(buttons[1].dataset.new, undefined);
  context.markResultReady();
  assert.equal(buttons[1].dataset.new, undefined);
});
