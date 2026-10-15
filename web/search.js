"use strict";

// 화면에는 서버가 발급한 선택 번호만 보관합니다. API 키와 좌표는 서버에 남습니다.
const searchState = { selected: { a: null, b: null }, names: { a: null, b: null }, versions: { a: 0, b: 0 }, searching: false, busy: false };
const activityInputs = [...document.querySelectorAll('input[name="activity"]')];
const modeInputs = [...document.querySelectorAll('input[name="recommendation-mode"]')];
const selectedMode = () => modeInputs.find(input => input.checked)?.value || "burden";
function selectedActivities() { return activityInputs.filter(input => input.checked).map(input => input.value); }
// 노선만 다른 같은 역('강남역 2호선'·'강남역 신분당선')도 같은 출발역으로 봅니다. 서버도 한 번 더 확인합니다.
const stationKey = name => String(name || "").trim().split(/\s+/)[0].replace(/\(.*$/, "").replace(/역$/, "");
const sameStation = names => Boolean(names?.a && names.a === names.b);
const SAME_STATION_MESSAGE = "두 사람의 출발역이 같아요. 한 사람의 역을 바꿔 주세요.";
const DEFAULT_SEARCH_STATUS = "두 출발역과 활동을 선택하면 후보 최대 3곳을 비교할 수 있어요.";
function canRecommend(selected, activities, pending, names) {
  return Boolean(selected.a && selected.b && activities.length && !pending && !sameStation(names));
}
function updateSearchButton() {
  $("find-button").disabled = !canRecommend(searchState.selected, selectedActivities(), searchState.busy || searchState.searching, searchState.names);
  // 같은 역 안내는 상황이 바뀌면 바로 지웁니다(검색 중 안내는 건드리지 않음).
  const status = $("search-status");
  if (sameStation(searchState.names)) status.textContent = SAME_STATION_MESSAGE;
  else if (status.textContent === SAME_STATION_MESSAGE) status.textContent = DEFAULT_SEARCH_STATUS;
  for (const person of ["a", "b"]) $( `station-${person}-search`).disabled = searchState.searching || searchState.busy;
}
async function requestJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "요청을 처리하지 못했어요.");
  return data;
}
// 추천은 서버의 백그라운드 작업으로 실행되고, 화면은 작업 번호로 진행 상황을 조회합니다(폴링).
const POLL_INTERVAL_MS = 1000;
const MAX_POLL_FAILURES = 5; // 연속 연결 실패 허용 횟수. 서버 작업은 그동안에도 계속 진행됩니다.
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const isConnectionError = error => error instanceof TypeError || error instanceof SyntaxError;

function showProgress(job) {
  const list = $("search-progress");
  list.hidden = false;
  const current = Number.isInteger(job.stage_index) ? job.stage_index : -1;
  [...list.children].forEach((item, index) => {
    const value = index < current ? "done" : index === current ? "current" : "pending";
    item.dataset.state = value;
    if (value === "current") item.setAttribute("aria-current", "step"); else item.removeAttribute("aria-current");
  });
  // 같은 문장을 반복해서 넣으면 화면 낭독기가 매초 다시 읽으므로, 바뀔 때만 갱신합니다.
  if (job.message && $("search-status").textContent !== job.message) $("search-status").textContent = job.message;
}

async function waitForJob(jobId) {
  let failures = 0;
  for (;;) {
    await wait(POLL_INTERVAL_MS);
    let job;
    try {
      job = await requestJson(`/api/recommendations/${encodeURIComponent(jobId)}`, { cache: "no-store" });
      failures = 0;
    } catch (error) {
      if (!isConnectionError(error) || ++failures >= MAX_POLL_FAILURES) throw error;
      $("search-status").textContent = `서버 연결을 다시 확인하고 있어요 (${failures}/${MAX_POLL_FAILURES - 1}). 추천은 서버에서 계속 진행돼요.`;
      continue;
    }
    if (job.status === "done") return job;
    if (job.status === "error") throw new Error(job.error || "추천을 완료하지 못했어요.");
    showProgress(job);
  }
}

function connectionMessage(error) {
  return error instanceof TypeError || error instanceof SyntaxError
    ? "서버와 연결이 끊겼어요. 처리 중이던 요청이 완료됐을 수 있으니 ‘결과 다시 읽기’를 먼저 눌러 주세요."
    : error.message;
}
// 입력하는 동안 로컬 역 목록에서 후보를 보여줍니다(외부 API 없음). 목록에 없으면 '역 검색'(카카오)을 씁니다.
const SUGGEST_DELAY_MS = 200;
const suggestTimers = { a: null, b: null };

function renderStationOptions(person, stations) {
  const options = $(`station-${person}-options`);
  options.replaceChildren();
  const status = $(`station-${person}-status`);
  const labels = [];
  // 고른 뒤에는 선택한 역만 남겨 다음 입력칸이 밀려나지 않게 하고, 필요하면 다시 펼칩니다.
  const change = element("button", "station-change", "다른 역·노선 보기");
  change.type = "button"; change.hidden = true;
  change.addEventListener("click", () => {
    labels.forEach(item => { item.hidden = false; });
    change.hidden = true;
  });
  for (const station of stations) {
    const label = element("label", "station-option");
    const radio = document.createElement("input");
    radio.type = "radio"; radio.name = `station-${person}`; radio.value = station.token;
    const copy = element("span");
    copy.append(element("strong", "", station.name), element("small", "", station.detail || ""));
    radio.addEventListener("change", () => {
      searchState.selected[person] = station.token;
      searchState.names[person] = stationKey(station.name);
      status.textContent = `선택 완료 · ${station.name}${station.detail && station.local ? ` ${station.detail}` : ""}`;
      if (labels.length > 1) {
        labels.forEach(item => { item.hidden = item !== label; });
        change.hidden = false;
      }
      updateSearchButton();
    });
    label.append(radio, copy);
    labels.push(label);
    options.append(label);
  }
  if (labels.length > 1) options.append(change);
}

async function suggestStations(person, query, version) {
  try {
    const data = await requestJson(`/api/station-suggestions?query=${encodeURIComponent(query)}`, { cache: "no-store" });
    if (version !== searchState.versions[person]) return; // 그사이 입력이 바뀌었으면 버립니다.
    renderStationOptions(person, data.stations.map(item => ({ token: item.token, name: item.name, detail: item.line, local: true })));
    $(`station-${person}-status`).textContent = data.stations.length
      ? "이용할 역과 노선을 선택해 주세요. 찾는 역이 없으면 ‘역 검색’을 눌러 주세요."
      : "수도권 역 목록에 없어요. ‘역 검색’을 눌러 찾아 주세요.";
  } catch (error) {
    if (version === searchState.versions[person]) $(`station-${person}-status`).textContent = "역 목록을 불러오지 못했어요. ‘역 검색’을 눌러 주세요.";
  }
}

async function findStations(person) {
  if (searchState.searching || searchState.busy) return;
  const query = $(`station-${person}-query`).value.trim();
  const status = $(`station-${person}-status`);
  if (!query) { status.textContent = "역 이름을 입력해 주세요."; $(`station-${person}-query`).focus(); return; }
  const version = ++searchState.versions[person];
  searchState.selected[person] = null;
  searchState.names[person] = null;
  searchState.searching = true;
  $(`station-${person}-options`).replaceChildren();
  status.textContent = "역을 찾고 있어요…";
  updateSearchButton();
  try {
    const data = await requestJson(`/api/stations?query=${encodeURIComponent(query)}`, { cache: "no-store" });
    if (version !== searchState.versions[person]) return;
    status.textContent = data.stations.length ? "이용할 역과 노선을 선택해 주세요." : "검색 결과가 없어요. 역 이름을 바꿔 보세요.";
    renderStationOptions(person, data.stations.map(item => ({ token: item.token, name: item.name, detail: item.address })));
  } catch (error) {
    if (version === searchState.versions[person]) status.textContent = connectionMessage(error);
  } finally { searchState.searching = false; updateSearchButton(); }
}
for (const person of ["a", "b"]) {
  $(`station-${person}-search`).addEventListener("click", () => findStations(person));
  $(`station-${person}-query`).addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); findStations(person); }
  });
  $(`station-${person}-query`).addEventListener("input", () => {
    const version = ++searchState.versions[person];
    searchState.selected[person] = null;
    searchState.names[person] = null;
    $(`station-${person}-options`).replaceChildren();
    clearTimeout(suggestTimers[person]);
    const query = $(`station-${person}-query`).value.trim();
    $(`station-${person}-status`).textContent = query ? "역 목록에서 찾고 있어요…" : "역 이름을 입력하면 목록이 나타나요.";
    updateSearchButton();
    // 글자를 칠 때마다 요청하지 않도록 잠깐 기다렸다가 마지막 입력으로만 찾습니다.
    if (query) suggestTimers[person] = setTimeout(() => suggestStations(person, query, version), SUGGEST_DELAY_MS);
  });
}
activityInputs.forEach(input => input.addEventListener("change", updateSearchButton));
const modeHelp = {
  burden: "두 사람 중 더 오래 걸리는 시간을 먼저 줄여요. 같으면 이동시간 합계를 비교해요.",
  fair: "가장 부담이 적은 후보보다 더 긴 이동시간이 15분 이내로 늘어나는 후보 중, 두 사람의 시간 차이를 줄여요. 조건에 따라 후보가 3곳보다 적을 수 있어요.",
  transfers: "각자 환승이 가장 적은 경로를 선택하고 두 사람의 환승 합계를 줄여요. 같으면 이동시간을 비교해요. 가장 빠른 경로보다 오래 걸릴 수 있어요.",
};
modeInputs.forEach(input => input.addEventListener("change", () => {
  $("mode-help").textContent = modeHelp[selectedMode()];
  $("search-status").textContent = "추천 기준을 바꿨어요. ‘만남 후보 찾기’를 누르면 새 기준으로 검색해요.";
}));

// 모바일은 결과가 다른 탭에 있으므로 '아래'가 아니라 탭 이름으로 안내합니다.
const resultsPlace = () => typeof matchMedia === "function" && matchMedia("(max-width: 760px)").matches ? "‘결과’ 탭에서" : "아래에서";

// 가장 먼저 읽을 결론(추천 요약)으로 이동합니다. 포커스는 화면 낭독기가 제목부터 읽게 합니다.
function focusSummary() {
  $("summary-title").setAttribute("tabindex", "-1");
  $("summary-title").focus({ preventScroll: true });
  document.querySelector(".recommendation").scrollIntoView({ behavior: motionEnabled() ? "smooth" : "instant", block: "start" });
}

// 새 검색 결과는 '결과 열기' 단계를 거쳐 공개합니다. 모션을 끈 경우에는 바로 보여줍니다.
function presentNewResult(report) {
  if (typeof showTab === "function") showTab("results", { scroll: false });
  if (!motionEnabled()) { focusSummary(); return; }
  const count = Array.isArray(report?.recommendations) ? report.recommendations.length : 0;
  $("results").hidden = true;
  $("reveal-title").textContent = count ? `후보 ${count}곳을 비교했어요` : "후보를 비교했어요";
  $("reveal-stage").hidden = false;
  $("reveal-stage").scrollIntoView({ behavior: "smooth", block: "center" });
  $("reveal-button").focus({ preventScroll: true });
}

$("reveal-button").addEventListener("click", () => {
  $("reveal-stage").hidden = true;
  const results = $("results");
  results.hidden = false;
  // 카드가 뒤집히며 나타나는 효과는 CSS(.is-revealing)가 담당하고, 끝나면 표시를 지웁니다.
  results.classList?.add("is-revealing");
  setTimeout(() => results.classList?.remove("is-revealing"), 1600);
  focusSummary();
});
$("meeting-form").addEventListener("submit", async event => {
  event.preventDefault();
  const preferences = selectedActivities();
  const recommendation_mode = selectedMode();
  if (!canRecommend(searchState.selected, preferences, searchState.busy || searchState.searching)) return;
  searchState.busy = true;
  ++state.requestId; // 이전 저장 파일 읽기가 늦게 도착해 새 결과를 덮지 않게 합니다.
  $("search-controls").disabled = true;
  $("reload").disabled = true;
  $("report-file").disabled = true;
  $("meeting-form").setAttribute("aria-busy", "true");
  $("find-button").textContent = "만날 곳을 찾는 중…";
  $("search-status").textContent = "추천을 시작하고 있어요.";
  updateSearchButton();
  try {
    const started = await requestJson("/api/recommendations", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ station_a: searchState.selected.a, station_b: searchState.selected.b, preferences, recommendation_mode }),
    });
    showProgress(started);
    // 버튼 아래에 생긴 진행 안내가 화면 밖에 있으면 보이는 곳까지만 내립니다.
    $("search-status").scrollIntoView({ behavior: motionEnabled() ? "smooth" : "instant", block: "nearest" });
    const data = await waitForJob(started.job_id);
    showReport(data.report, "새 검색 결과");
    $("search-status").textContent = data.warning || `비교를 마쳤어요. ${resultsPlace()} 후보별 이동시간과 장소를 살펴보세요.`;
    presentNewResult(data.report);
  } catch (error) {
    $("search-status").textContent = connectionMessage(error) + (state.report ? " 기존 결과는 그대로 남아 있어요." : "");
  } finally {
    searchState.busy = false;
    $("search-controls").disabled = false;
    $("reload").disabled = false;
    $("reload").textContent = "↻ 결과 다시 읽기";
    $("report-file").disabled = false;
    $("meeting-form").setAttribute("aria-busy", "false");
    $("search-progress").hidden = true;
    $("find-button").textContent = "만남 후보 찾기 →";
    updateSearchButton();
  }
});
