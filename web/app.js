/* 저장 결과를 화면에 그립니다. 지도/AI API는 호출하지 않습니다. */
"use strict";
const categories = { cafe: "카페", food: "식사", culture: "문화시설" };
const recommendationModes = {burden: "이동 부담 줄이기", fair: "공평하게 만나기", transfers: "환승 적게 하기"};
const state = { report: null, category: null, sort: "rank", requestId: 0 };
const $ = (id) => document.getElementById(id);

// 시스템 설정과 사용자의 선택을 모두 존중합니다. 숫자 자체는 애니메이션하지 않습니다.
const motionPreference = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
let motionDisabled = false;
try { motionDisabled = localStorage.getItem("date-meet-reduce-motion") === "true"; } catch { /* 저장 불가 환경에서도 사용 가능 */ }
const activeAnimations = new Set();
const revealObserver = typeof IntersectionObserver === "function" ? new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    revealObserver.unobserve(entry.target);
    animateEntry(entry.target, Number(entry.target.dataset.motionOrder || 0) * 65);
  }
}, { threshold: 0.08 }) : null;

function motionEnabled() {
  return !motionDisabled && !motionPreference.matches;
}

function playMotion(node, frames, options) {
  if (!motionEnabled() || typeof node.animate !== "function") return;
  const animation = node.animate(frames, options);
  activeAnimations.add(animation);
  animation.finished.then(() => activeAnimations.delete(animation), () => activeAnimations.delete(animation));
}

function animateEntry(node, delay = 0) {
  playMotion(node, [{ opacity: 0.35, transform: "translateY(16px)" }, { opacity: 1, transform: "translateY(0)" }],
    { duration: 440, delay, easing: "cubic-bezier(.2,.7,.2,1)" });
  for (const bar of node.querySelectorAll(".bar")) {
    playMotion(bar, [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }],
      { duration: 620, delay: delay + 80, easing: "cubic-bezier(.2,.7,.2,1)" });
  }
}

function syncMotionSetting() {
  if (!document.documentElement) return;
  const disabled = !motionEnabled();
  document.documentElement.dataset.motion = disabled ? "off" : "on";
  const button = $("motion-toggle");
  button.textContent = motionPreference.matches ? "모션 줄임 · 기기 설정" : motionDisabled ? "모션 켜기" : "모션 줄이기";
  button.setAttribute("aria-pressed", String(disabled));
  button.disabled = motionPreference.matches;
  if (disabled) {
    for (const animation of activeAnimations) animation.cancel();
    activeAnimations.clear();
  }
  updateJourneyScroll();
}

// 스크롤 위치는 바꾸지 않고 장식만 최대 12px 이동합니다.
function updateJourneyScroll() {
  const intro = document.querySelector?.(".intro");
  const story = document.querySelector?.(".meeting-story");
  if (!intro || !story) return;
  const rect = intro.getBoundingClientRect();
  const progress = Math.max(0, Math.min(1, -rect.top / Math.max(rect.height, 1)));
  const shiftLimit = window.innerWidth <= 760 ? 4 : 12;
  intro.style.setProperty("--postcard-shift", `${motionEnabled() ? progress * -shiftLimit : 0}px`);
  const storyTop = story.getBoundingClientRect().top;
  const storyProgress = Math.max(0, Math.min(1, (window.innerHeight - storyTop) / (window.innerHeight * .55)));
  story.style.setProperty("--story-progress", motionEnabled() ? storyProgress : 1);
}

function initPageMotion() {
  if (typeof window === "undefined" || !document.querySelectorAll) return;
  if (typeof IntersectionObserver === "function") {
    // 카드 재정렬용 observer와 분리해 검색 후에도 페이지 등장 효과를 유지합니다.
    const sections = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        animateEntry(entry.target, Number(entry.target.dataset.revealOrder || 0) * 80);
        sections.unobserve(entry.target);
      });
    }, { threshold: .12 });
    document.querySelectorAll("[data-reveal], .search-panel, .recommendation, .quick-comparison, .map-section, .reading-guide").forEach((node, index) => {
      node.dataset.revealOrder = node.hasAttribute("data-reveal") ? index % 3 : 0;
      sections.observe(node);
    });
    const art = document.querySelector(".journey");
    if (art) {
      const visibility = new IntersectionObserver(entries => {
        art.dataset.visible = String(entries[0].isIntersecting);
      });
      visibility.observe(art);
    }
  }
  let pending = false;
  const schedule = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; updateJourneyScroll(); });
  };
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  updateJourneyScroll();
}

// 외부 데이터는 HTML 문자열로 삽입하지 않고 textContent로 표시합니다.
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function validateReport(report) {
  if (report?.route_usage !== undefined) {
    const usage = report.route_usage;
    if (!usage || !["cache_hits", "api_calls", "ttl_seconds"].every(key => Number.isInteger(usage[key]) && usage[key] >= 0) ||
        !["oldest_fetched_at", "latest_fetched_at"].every(key => typeof usage[key] === "string" && Number.isFinite(Date.parse(usage[key])))) {
      throw new Error("경로 조회 기록 형식을 확인해 주세요.");
    }
  }
  if (report && (report.recommendation_mode !== undefined && (typeof report.recommendation_mode !== "string" || !Object.hasOwn(recommendationModes, report.recommendation_mode)) || report.recommendation_note !== undefined && typeof report.recommendation_note !== "string")) {
    throw new Error("추천 기준 형식을 확인해 주세요.");
  }
  const isNumber = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const strings = (list) => Array.isArray(list) && list.every((value) => typeof value === "string");
  if (!report || report.schema_version !== 1 || !Array.isArray(report.recommendations) ||
      report.recommendations.length < 1 || report.recommendations.length > 3 ||
      !Array.isArray(report.preferences) || !report.preferences.length ||
      !report.preferences.every((key) => Object.hasOwn(categories, key)) ||
      typeof report.collected_at !== "string" || !Number.isFinite(Date.parse(report.collected_at))) {
    throw new Error("지원하는 비교 결과 파일이 아니에요. latest_comparison.json을 선택해 주세요.");
  }
  const ranks = new Set();
  for (const item of report.recommendations) {
    if (!item || !Number.isInteger(item.rank) || item.rank < 1 || ranks.has(item.rank) ||
        typeof item.station?.place_name !== "string" || typeof item.station.line_name !== "string" ||
        !["minutes_a", "minutes_b", "transfers_a", "transfers_b", "total", "difference"].every((key) => isNumber(item[key]))) {
      throw new Error("후보의 역 정보나 이동시간 형식을 확인해 주세요.");
    }
    ranks.add(item.rank);
    for (const key of report.preferences) {
      const group = item.places?.[key];
      if (!group || !Array.isArray(group.items) || (group.error != null && typeof group.error !== "string")) throw new Error("장소 목록 형식을 확인해 주세요.");
      for (const place of group.items) {
        if (!place || typeof place.name !== "string" || typeof place.address !== "string" ||
            (place.access_check_reasons != null && !strings(place.access_check_reasons))) throw new Error("장소 정보 형식을 확인해 주세요.");
      }
    }
  }
  const analysis = report.analysis;
  if (!analysis || !["gemini", "rules"].includes(analysis.source) || typeof analysis.summary !== "string" ||
      typeof analysis.status !== "string" || !Array.isArray(analysis.comparisons) ||
      analysis.comparisons.length !== ranks.size ||
      new Set(analysis.comparisons.map((item) => item?.rank)).size !== ranks.size ||
      !analysis.comparisons.every((item) => item && ranks.has(item.rank) && strings(item.strengths) && strings(item.limitations)) ||
      (analysis.recommended_rank != null && !ranks.has(analysis.recommended_rank))) throw new Error("후보별 설명 형식을 확인해 주세요.");
  return report;
}

function safePlaceUrl(value) {
  try {
    const url = new URL(value);
    if (["https:", "http:"].includes(url.protocol) && url.hostname === "place.map.kakao.com" && !url.username && !url.password) {
      url.protocol = "https:";
      return url.href;
    }
  } catch { /* 링크가 잘못되면 이름만 표시 */ }
  return null;
}

function mapButton(rank, place = null) {
  const button = element("button", "map-card-button", place ? "위치 보기 ↗" : "지도에서 보기 ↗");
  button.type = "button";
  button.addEventListener("click", () => MeetingMap.focus(rank, place));
  return button;
}

function renderPlace(place, rank) {
  const li = element("li", "place");
  const title = element("div", "place-title");
  const url = safePlaceUrl(place.url);
  const name = element(url ? "a" : "span", "place-name", place.name);
  if (url) {
    name.href = url;
    name.target = "_blank";
    name.rel = "noopener noreferrer";
    name.setAttribute("aria-label", `${place.name} 카카오맵에서 보기 (새 탭)`);
  }
  title.append(name);
  const distance = Number(place.distance_m);
  if (place.distance_m !== "" && place.distance_m != null && Number.isFinite(distance) && distance >= 0) {
    title.append(element("span", "distance", `${Math.round(distance).toLocaleString("ko-KR")}m`));
  }
  li.append(title, element("p", "address", place.address || "주소 정보 없음"));
  if (typeof MeetingMap !== "undefined" && MeetingMap.coordinates(place)) li.append(mapButton(rank, place));
  const reasons = place.access_check_reasons || [];
  if (place.access_check_required || reasons.length) {
    const note = element("details", "access-note");
    note.append(element("summary", "", "출입 조건 확인 필요"));
    for (const reason of reasons.length ? reasons : ["방문 전 일반 이용객의 출입 조건을 확인해 주세요."]) note.append(element("p", "", reason));
    note.addEventListener("toggle", () => { if (note.open) animateEntry(note); });
    li.append(note);
  }
  return li;
}

function routeUsageText(usage) {
  if (!usage) return "이전 저장 결과에는 경로 재사용 기록이 없어요.";
  const format = value => new Intl.DateTimeFormat("ko-KR", {timeZone:"Asia/Seoul",dateStyle:"short",timeStyle:"medium"}).format(new Date(value));
  const times = usage.oldest_fetched_at === usage.latest_fetched_at ? format(usage.oldest_fetched_at) : `${format(usage.oldest_fetched_at)} ~ ${format(usage.latest_fetched_at)}`;
  return `이 결과 계산 시 · 이전 경로 재사용 ${usage.cache_hits}건 · 새 경로 조회 ${usage.api_calls}회 · 경로 조회 시각 ${times} (한국 시간). 주변 장소·AI 호출은 별도예요.`;
}

function renderCard(item, maxTime) {
  const report = state.report;
  const isRecommended = report.analysis.source === "gemini" && item.rank === report.analysis.recommended_rank;
  const card = element("article", `candidate-card${isRecommended ? " recommended" : ""}`);
  card.id = `candidate-${item.rank}`;
  card.tabIndex = -1;
  const titleId = `station-${item.rank}`;
  card.setAttribute("aria-labelledby", titleId);
  const top = element("div", "card-top");
  const rank = element("div", "rank-row");
  rank.append(element("span", "rank", `만남 후보 0${item.rank}`));
  if (isRecommended) rank.append(element("span", "recommend-badge", "✳ AI 추천"));
  const station = element("h3", "station-name", item.station.place_name);
  station.id = titleId;
  top.append(rank, station, element("p", "line-name", item.station.line_name));
  if (typeof MeetingMap !== "undefined" && MeetingMap.coordinates(item.station)) top.append(mapButton(item.rank));
  const travel = element("div", "travel");
  for (const [key, label, letter] of [["a", "첫 번째 사람", "A"], ["b", "두 번째 사람", "B"]]) {
    const person = element("div");
    const labelNode = element("div", "person-label");
    labelNode.append(element("span", `person-letter ${key}`, letter), document.createTextNode(label));
    const time = element("div", "travel-number", item[`minutes_${key}`].toFixed(1));
    time.append(element("small", "", "분"));
    const track = element("div", "bar-track");
    track.setAttribute("aria-hidden", "true");
    const bar = element("div", `bar ${key}`);
    bar.style.width = `${Math.min(100, item[`minutes_${key}`] / maxTime * 100)}%`;
    track.append(bar);
    person.append(labelNode, time, element("p", "transfer", `환승 ${item[`transfers_${key}`]}회`), track);
    const route = item[`route_${key}`];
    if (route && ["api", "cache"].includes(route.source) && typeof route.fetched_at === "string" && Number.isFinite(Date.parse(route.fetched_at))) {
      const fetched = new Intl.DateTimeFormat("ko-KR", {timeZone:"Asia/Seoul",dateStyle:"short",timeStyle:"short"}).format(new Date(route.fetched_at));
      person.append(element("p", "route-date", `${route.source === "cache" ? "재사용" : "새 조회"} · ${fetched} 조회 (한국 시간)`));
    }
    travel.append(person);
  }
  const difference = element("div", "time-difference");
  const gap = element("span", "", "시간 차이 ");
  gap.append(element("strong", "", `${item.difference.toFixed(1)}분`));
  difference.append(gap, element("span", "", `합계 ${item.total.toFixed(1)}분`));
  top.append(travel, difference);
  const places = element("section", "places-section");
  const group = item.places[state.category];
  const heading = element("h4", "places-heading", `함께 갈 ${categories[state.category]}`);
  heading.append(element("span", "", group.error ? "조회 실패" : `${group.items.length}곳`));
  places.append(heading);
  if (group.error) places.append(element("p", "place-empty place-error", `장소를 불러오지 못했어요. ${group.error}`));
  else if (!group.items.length) places.append(element("p", "place-empty", "반경 1km 검색에서 찾은 장소가 없어요."));
  else {
    const list = element("ul", "place-list");
    group.items.slice(0, 3).forEach((place) => list.append(renderPlace(place, item.rank)));
    places.append(list);
    if (group.items.length > 3) {
      const more = element("details", "more-places");
      const summary = element("summary", "", `장소 ${group.items.length - 3}곳 더 보기`);
      const extra = element("ul", "place-list");
      group.items.slice(3).forEach((place) => extra.append(renderPlace(place, item.rank)));
      more.append(summary, extra);
      more.addEventListener("toggle", () => {
        summary.textContent = more.open ? "추가 장소 접기" : `장소 ${group.items.length - 3}곳 더 보기`;
        if (more.open) animateEntry(extra);
      });
      places.append(more);
    }
    const flagged = group.items.filter((p) => p.access_check_required || p.access_check_reasons?.length).length;
    if (flagged) heading.append(element("span", "warning-count", `출입 확인 ${flagged}`));
  }
  const comment = report.analysis.comparisons.find((entry) => entry.rank === item.rank);
  const analysis = element("div", "card-analysis");
  for (const [key, label] of [["strengths", "좋은 점"], ["limitations", "생각해 볼 점"]]) {
    const list = element("ul", key);
    comment[key].forEach((text) => list.append(element("li", "", text)));
    analysis.append(element("h4", "", label), list);
  }
  card.append(top, places, analysis);
  return card;
}

function sortedCandidates(items, sort) {
  const value = (item) => sort === "difference" ? item.difference : sort === "transfers" ? item.transfers_a + item.transfers_b : item.rank;
  return [...items].sort((a, b) => value(a) - value(b) || a.rank - b.rank);
}

function renderComparisonTable(items) {
  const table = element("table");
  const caption = element("caption", "sr-only", "후보별 두 사람의 이동시간과 환승 횟수 비교");
  const head = element("thead");
  const names = element("tr");
  const blank = element("th", "", "이동 정보");
  blank.scope = "col";
  names.append(blank);
  for (const item of items) {
    const th = element("th");
    th.scope = "col";
    const link = element("a", "", item.station.place_name);
    link.href = `#candidate-${item.rank}`;
    th.append(link);
    names.append(th);
  }
  head.append(names);
  const body = element("tbody");
  for (const [label, format] of [
    ["A 이동", (r) => [r.minutes_a.toFixed(1), `환승 ${r.transfers_a}회`]],
    ["B 이동", (r) => [r.minutes_b.toFixed(1), `환승 ${r.transfers_b}회`]],
    ["시간 차이", (r) => `${r.difference.toFixed(1)}분`],
  ]) {
    const row = element("tr");
    const th = element("th", "", label);
    th.scope = "row";
    row.append(th);
    items.forEach((item) => {
      const value = format(item);
      const cell = element("td");
      if (Array.isArray(value)) {
        const time = element("strong", "table-time", value[0]);
        time.append(element("small", "", "분"));
        cell.append(time, element("span", "table-transfer", value[1]));
      } else cell.textContent = value;
      row.append(cell);
    });
    body.append(row);
  }
  table.append(caption, head, body);
  $("comparison-table").replaceChildren(table);
}

function renderCards() {
  revealObserver?.disconnect();
  for (const animation of activeAnimations) animation.cancel();
  activeAnimations.clear();
  const items = sortedCandidates(state.report.recommendations, state.sort);
  const maxTime = Math.max(1, ...items.flatMap((item) => [item.minutes_a, item.minutes_b]));
  $("candidate-grid").replaceChildren(...items.map((item) => renderCard(item, maxTime)));
  for (const [index, card] of [...$("candidate-grid").children].entries()) {
    card.dataset.motionOrder = String(index);
    if (revealObserver) revealObserver.observe(card);
    else animateEntry(card);
  }
  renderComparisonTable(items);
  const sortLabel = {rank: "선택 기준 순", difference: "시간 차이 적은 순", transfers: "환승 합계 적은 순"}[state.sort];
  $("list-status").textContent = `${categories[state.category]} 비교 · ${sortLabel} · 역 주변 1km에서 선별한 장소`;
  for (const button of $("category-filters").children) button.setAttribute("aria-pressed", String(button.dataset.category === state.category));
  if (typeof MeetingMap !== "undefined") MeetingMap.update(state.report, state.category);
}

function showReport(report, source) {
  state.report = validateReport(report);
  state.sort = "rank";
  $("sort-order").value = "rank";
  const mode = report.recommendation_mode || "burden";
  $("result-criterion").textContent = `이 결과의 추천 기준: ${recommendationModes[mode]} · 최대 3곳` + (report.recommendation_note ? ` — ${report.recommendation_note}` : "");
  $("route-usage").textContent = routeUsageText(report.route_usage);
  if (!report.preferences.includes(state.category)) state.category = report.preferences[0];
  const analysis = report.analysis;
  const recommendation = analysis.source === "gemini" ? report.recommendations.find((item) => item.rank === analysis.recommended_rank) : null;
  $("summary-type").textContent = analysis.source === "gemini" ? "AI의 한마디" : "비교 안내";
  $("summary-title").textContent = recommendation ? `이번 만남은 ${recommendation.station.place_name}, 어때요?` : "가는 길과 함께할 장소를 나란히 비교해요";
  $("summary-text").textContent = analysis.summary;
  $("summary-status").textContent = analysis.status;
  $("recommendation-link").href = recommendation ? `#candidate-${recommendation.rank}` : "#comparison-title";
  $("recommendation-link").textContent = recommendation ? "추천 후보 자세히 ↓" : "후보 비교하기 ↓";
  const date = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date(report.collected_at));
  const origins = Array.isArray(report.origins) && report.origins.length === 2 && report.origins.every(value => typeof value === "string") ? `A ${report.origins[0]} · B ${report.origins[1]} · ` : "";
  $("timestamp").textContent = `${origins}${source} · 결과 작성 ${date} (한국 시간)`;
  $("candidate-count").textContent = String(report.recommendations.length);
  $("category-filters").replaceChildren(...[...new Set(report.preferences)].map((key) => {
    const button = element("button", "", categories[key]);
    button.type = "button";
    button.dataset.category = key;
    button.addEventListener("click", () => { state.category = key; renderCards(); });
    return button;
  }));
  renderCards();
  $("results").hidden = false;
  $("empty-state").hidden = true;
  $("feedback").textContent = "";
}

function showError(error) {
  $("feedback").textContent = error.message + (state.report ? " 기존 결과를 유지했어요." : "");
  $("empty-state").hidden = Boolean(state.report);
  if (!state.report) $("timestamp").textContent = "표시할 저장 결과가 없어요.";
}

async function loadLatest() {
  const requestId = ++state.requestId;
  $("reload").disabled = true;
  $("reload").textContent = "읽는 중…";
  try {
    const response = await fetch("/data/latest_comparison.json", { cache: "no-store" });
    if (!response.ok) throw new Error(response.status === 404 ? "아직 저장된 비교 결과가 없어요." : "저장 결과를 읽지 못했어요.");
    const report = await response.json();
    if (requestId === state.requestId) showReport(report, "저장된 결과");
  } catch (error) {
    if (requestId === state.requestId) showError(error instanceof TypeError ? new Error("로컬 서버에 연결할 수 없어요. 서버를 실행하거나 결과 파일을 열어 주세요.") : error instanceof SyntaxError ? new Error("결과 파일의 JSON 형식이 올바르지 않아요.") : error);
  } finally {
    if (requestId === state.requestId) {
      $("reload").disabled = false;
      $("reload").textContent = "↻ 결과 다시 읽기";
    }
  }
}

$("reload").addEventListener("click", loadLatest);
$("motion-toggle").addEventListener("click", () => {
  motionDisabled = !motionDisabled;
  try { localStorage.setItem("date-meet-reduce-motion", String(motionDisabled)); } catch { /* 선택은 현재 탭에 반영 */ }
  syncMotionSetting();
});
motionPreference.addEventListener?.("change", syncMotionSetting);
syncMotionSetting();
initPageMotion();
$("sort-order").addEventListener("change", (event) => {
  state.sort = event.target.value;
  if (state.report) renderCards();
});
$("report-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const requestId = ++state.requestId;
  $("reload").disabled = false;
  $("reload").textContent = "↻ 결과 다시 읽기";
  try {
    if (file.size > 2 * 1024 * 1024) throw new Error("2MB 이하의 비교 결과 파일을 선택해 주세요.");
    const data = JSON.parse(await file.text());
    if (requestId === state.requestId) showReport(data, "직접 연 결과 파일");
  } catch (error) {
    if (requestId === state.requestId) showError(error instanceof SyntaxError ? new Error("JSON 형식의 비교 결과 파일을 선택해 주세요.") : error);
  }
  event.target.value = "";
});
loadLatest();
