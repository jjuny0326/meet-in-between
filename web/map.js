/* 이미 조회한 좌표로 표시합니다. 장소 검색이나 경로 조회를 추가하지 않습니다. */
"use strict";
const MeetingMap = (() => {
  const get = id => document.getElementById(id);
  const labels = {cafe: "카페", food: "식사", culture: "문화시설"};
  let report = null, category = null, selectedRank = null;
  let map = null, overlays = [], sdkPromise = null, loading = false, focusVersion = 0;
  let openPromise = null, autoOpened = false;

  function coordinates(item) {
    const number = value => (typeof value === "number" || typeof value === "string" && value.trim()) ? Number(value) : NaN;
    const lng = number(item?.x), lat = number(item?.y);
    return Number.isFinite(lng) && Number.isFinite(lat) && Math.abs(lng) <= 180 && Math.abs(lat) <= 90 ? {lat, lng} : null;
  }
  function pointsFor(data, activity, rank = null) {
    const points = [];
    let missingStations = 0, missingPlaces = 0, failedGroups = 0;
    for (const item of data.recommendations) {
      if (rank !== null && item.rank !== rank) continue;
      const position = coordinates(item.station);
      if (position) points.push({kind: "station", rank: item.rank, name: item.station.place_name, position, item});
      else missingStations++;
      const group = item.places[activity];
      if (group?.error) { failedGroups++; continue; }
      for (const [index, place] of (group?.items || []).entries()) {
        const position = coordinates(place);
        if (position) points.push({kind: "place", rank: item.rank, name: place.name, position, item, place, index});
        else missingPlaces++;
      }
    }
    return {points, missingStations, missingPlaces, failedGroups};
  }
  // 같은 건물의 장소가 겹쳐도 모두 선택할 수 있도록 좌표별로 묶습니다.
  function groupPoints(points) {
    const groups = new Map();
    for (const point of points) {
      const key = `${point.position.lat},${point.position.lng}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(point);
    }
    return [...groups.values()];
  }
  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function scrollTo(id) {
    const target = get(id);
    target?.scrollIntoView({behavior: typeof motionEnabled === "function" && motionEnabled() ? "smooth" : "instant", block: "start"});
  }
  function highlight(rank) {
    for (const card of document.querySelectorAll(".candidate-card")) card.classList.toggle("map-selected", card.id === `candidate-${rank}`);
  }
  function showDetail(points) {
    const content = [];
    for (const point of points) {
      const box = node("div", "map-detail-item");
      box.append(node("strong", "", `${point.rank}번 후보 · ${point.name}`));
      if (point.kind === "station") {
        box.append(node("p", "", `A ${point.item.minutes_a.toFixed(1)}분 · B ${point.item.minutes_b.toFixed(1)}분`));
      } else {
        box.append(node("p", "", point.place.address || "주소 정보 없음"));
        if (point.place.access_check_required || point.place.access_check_reasons?.length) box.append(node("p", "map-access", "출입 조건 확인 필요 · 카드의 안내를 확인하세요."));
        const url = safePlaceUrl(point.place.url);
        if (url) {
          const link = node("a", "", "카카오맵 상세 보기 ↗");
          link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
          box.append(link);
        }
      }
      const card = node("button", "text-button", `${point.rank}번 후보 카드 보기 ↓`);
      card.type = "button";
      card.addEventListener("click", () => { if (typeof showTab === "function") showTab("results", {scroll: false}); highlight(point.rank); scrollTo(`candidate-${point.rank}`); get(`candidate-${point.rank}`)?.focus({preventScroll:true}); });
      box.append(card); content.push(box);
    }
    get("map-detail").replaceChildren(...content);
    highlight(points[0]?.rank);
  }
  function fit(points) {
    if (!map || !points.length) return;
    map.relayout();
    const bounds = new kakao.maps.LatLngBounds();
    for (const p of points) bounds.extend(new kakao.maps.LatLng(p.position.lat, p.position.lng));
    if (groupPoints(points).length === 1) { map.setCenter(new kakao.maps.LatLng(points[0].position.lat, points[0].position.lng)); map.setLevel(4); }
    else map.setBounds(bounds, 60, 45, 45, 45);
  }
  function draw(refit = true) {
    if (!map || !report) return;
    overlays.forEach(overlay => overlay.setMap(null)); overlays = [];
    get("map-detail").replaceChildren(); highlight(selectedRank);
    const data = pointsFor(report, category, selectedRank);
    for (const group of groupPoints(data.points)) {
      const main = group.find(p => p.kind === "station") || group[0];
      const marker = node("button", `map-pin rank-${main.rank} ${main.kind}`, main.kind === "station" ? String(main.rank) : `${main.rank}·${main.index + 1}`);
      marker.type = "button";
      marker.title = group.map(p => p.name).join(" / ");
      marker.setAttribute("aria-label", `${main.rank}번 후보 ${main.name}${group.length > 1 ? ` 외 ${group.length - 1}개 표시` : ""}`);
      if (group.length > 1) marker.append(node("small", "", `+${group.length - 1}`));
      marker.addEventListener("click", () => showDetail(group));
      overlays.push(new kakao.maps.CustomOverlay({map, position: new kakao.maps.LatLng(main.position.lat, main.position.lng), content: marker, yAnchor: 1, clickable: true, zIndex: main.kind === "station" ? 10 : 2}));
    }
    const stations = data.points.filter(p => p.kind === "station").length;
    const places = data.points.length - stations;
    get("map-status").textContent = `후보 역 ${stations}곳 · ${labels[category]} ${places}건 표시` +
      (data.missingStations + data.missingPlaces ? ` · 좌표 없는 역 ${data.missingStations}곳, 장소 ${data.missingPlaces}곳은 제외했어요. 이전 저장 결과라면 새 검색 후 표시돼요.` : "") +
      (data.failedGroups ? ` · ${data.failedGroups}개 후보의 장소 조회가 실패했어요.` : "") +
      (!places && !data.missingPlaces && !data.failedGroups ? " · 이 활동의 장소 검색 결과가 없어요." : "");
    if (refit) fit(data.points);
  }
  function controls() {
    if (!report) return;
    const buttons = [[null, "전체 후보"], ...report.recommendations.map(item => [item.rank, `${item.rank}. ${item.station.place_name}`])].map(([rank, label]) => {
      const button = node("button", rank ? `rank-${rank}` : "", label);
      button.type = "button"; button.setAttribute("aria-pressed", String(selectedRank === rank));
      button.addEventListener("click", () => focus(rank));
      return button;
    });
    get("map-candidates").replaceChildren(...buttons);
  }
  function loadSdk(key) {
    if (sdkPromise) return sdkPromise;
    sdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      let done = false;
      const finish = error => {
        if (done) return; done = true; clearTimeout(timer);
        if (error) { script.remove(); reject(error); } else resolve();
      };
      const timer = setTimeout(() => finish(new Error("지도 응답이 늦어요. 네트워크와 JavaScript 키의 도메인 설정을 확인하고 다시 시도해 주세요.")), 15000);
      script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false`;
      script.onerror = () => finish(new Error("지도를 불러오지 못했어요. JavaScript 키·허용 도메인·카카오맵 사용 설정을 확인해 주세요."));
      script.onload = () => {
        if (done) return;
        try { kakao.maps.load(() => finish()); } catch { finish(new Error("지도 설정을 확인하고 다시 시도해 주세요.")); }
      };
      document.head.append(script);
    }).catch(error => { sdkPromise = null; throw error; });
    return sdkPromise;
  }
  // 동시에 여러 번 불려도(탭 자동 열기 + '위치 보기') 같은 작업을 함께 기다립니다.
  function open() {
    if (openPromise) return openPromise;
    openPromise = openOnce().finally(() => { openPromise = null; });
    return openPromise;
  }
  async function openOnce() {
    if (!report) return;
    if (map) { draw(); return; }
    loading = true; get("map-load").disabled = true;
    get("map-status").textContent = "지도를 불러오는 중…";
    try {
      const response = await fetch("/api/map-config", {cache: "no-store"});
      if (!response.ok) throw new Error("지도 설정을 읽지 못했어요. 로컬 서버 연결을 확인해 주세요.");
      const config = await response.json();
      if (!config.javascript_key) throw new Error("지도 설정이 필요해요. .env에 KAKAO_JAVASCRIPT_KEY를 추가하고 카카오 개발자 콘솔에 이 화면의 접속 주소를 등록한 뒤 서버를 재시작해 주세요. REST API 키와는 다른 키예요.");
      await loadSdk(config.javascript_key);
      get("meeting-map").hidden = false;
      const first = pointsFor(report, category).points[0]?.position || {lat:37.5665, lng:126.978};
      map = new kakao.maps.Map(get("meeting-map"), {center: new kakao.maps.LatLng(first.lat, first.lng), level:7});
      map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
      map.setZoomable(false); // 페이지를 스크롤하다 지도가 확대되는 것을 방지합니다.
      if (typeof ResizeObserver === "function") new ResizeObserver(() => fit(pointsFor(report, category, selectedRank).points)).observe(get("meeting-map"));
      draw(); get("map-load").textContent = "지도 범위 맞추기";
    } catch (error) {
      get("map-status").textContent = error.message || "지도 로딩에 실패했어요. 비교 카드는 계속 사용할 수 있어요.";
      get("map-load").textContent = "지도 다시 불러오기";
      get("meeting-map").hidden = true;
    } finally { loading = false; get("map-load").disabled = false; }
  }
  async function focus(rank, place = null) {
    // 모바일 탭에서는 지도가 숨겨져 있을 수 있으므로 지도를 만들기 전에 지도 탭을 엽니다.
    if (typeof showTab === "function") showTab("map", {scroll: false});
    const version = ++focusVersion;
    const requestedReport = report, requestedCategory = category;
    selectedRank = rank; controls();
    if (!map) await open(); else draw();
    if (version !== focusVersion || report !== requestedReport || category !== requestedCategory) return;
    if (map && place) {
      const matching = pointsFor(report, category, rank).points.find(p => p.place === place);
      if (matching) { map.setCenter(new kakao.maps.LatLng(matching.position.lat, matching.position.lng)); map.setLevel(3); showDetail([matching]); }
    }
    scrollTo("map-section");
  }
  function update(nextReport, nextCategory) {
    const changed = report !== nextReport || category !== nextCategory;
    if (report !== nextReport) selectedRank = null;
    report = nextReport; category = nextCategory;
    controls(); if (map) draw(changed);
  }
  get("map-load")?.addEventListener("click", () => { focusVersion++; selectedRank = null; controls(); open(); });
  // 지도 화면이 보이게 될 때 호출합니다. 이미 열린 지도는 크기·범위를 다시 맞추고,
  // 아직 안 열었다면 결과가 있을 때 한 번만 자동으로 엽니다(실패하면 버튼으로 다시 시도).
  function refresh() {
    if (map && report) draw(true);
    else if (report && !autoOpened) { autoOpened = true; open(); }
  }
  return {update, focus, refresh, coordinates, pointsFor, groupPoints};
})();
