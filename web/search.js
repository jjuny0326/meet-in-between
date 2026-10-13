"use strict";

// 화면에는 서버가 발급한 선택 번호만 보관합니다. API 키와 좌표는 서버에 남습니다.
const searchState = { selected: { a: null, b: null }, versions: { a: 0, b: 0 }, searching: false, busy: false };
const activityInputs = [...document.querySelectorAll('input[name="activity"]')];
function selectedActivities() { return activityInputs.filter(input => input.checked).map(input => input.value); }
function canRecommend(selected, activities, pending) {
  return Boolean(selected.a && selected.b && activities.length && !pending);
}
function updateSearchButton() {
  $("find-button").disabled = !canRecommend(searchState.selected, selectedActivities(), searchState.busy || searchState.searching);
  for (const person of ["a", "b"]) $( `station-${person}-search`).disabled = searchState.searching || searchState.busy;
}
async function requestJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "요청을 처리하지 못했어요.");
  return data;
}
function connectionMessage(error) {
  return error instanceof TypeError || error instanceof SyntaxError
    ? "서버와 연결이 끊겼어요. 처리 중이던 요청이 완료됐을 수 있으니 ‘결과 다시 읽기’를 먼저 눌러 주세요."
    : error.message;
}
async function findStations(person) {
  if (searchState.searching || searchState.busy) return;
  const query = $(`station-${person}-query`).value.trim();
  const status = $(`station-${person}-status`);
  if (!query) { status.textContent = "역 이름을 입력해 주세요."; $(`station-${person}-query`).focus(); return; }
  const version = ++searchState.versions[person];
  searchState.selected[person] = null;
  searchState.searching = true;
  $(`station-${person}-options`).replaceChildren();
  status.textContent = "역을 찾고 있어요…";
  updateSearchButton();
  try {
    const data = await requestJson(`/api/stations?query=${encodeURIComponent(query)}`, { cache: "no-store" });
    if (version !== searchState.versions[person]) return;
    status.textContent = data.stations.length ? "이용할 역과 노선을 선택해 주세요." : "검색 결과가 없어요. 역 이름을 바꿔 보세요.";
    for (const station of data.stations) {
      const label = element("label", "station-option");
      const radio = document.createElement("input");
      radio.type = "radio"; radio.name = `station-${person}`; radio.value = station.token;
      const copy = element("span");
      copy.append(element("strong", "", station.name), element("small", "", station.address));
      radio.addEventListener("change", () => {
        searchState.selected[person] = station.token;
        status.textContent = `선택 완료 · ${station.name}`;
        updateSearchButton();
      });
      label.append(radio, copy);
      $(`station-${person}-options`).append(label);
    }
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
    searchState.versions[person]++;
    searchState.selected[person] = null;
    $(`station-${person}-options`).replaceChildren();
    $(`station-${person}-status`).textContent = "역 이름을 바꿨어요. 다시 검색해 주세요.";
    updateSearchButton();
  });
}
activityInputs.forEach(input => input.addEventListener("change", updateSearchButton));
$("meeting-form").addEventListener("submit", async event => {
  event.preventDefault();
  const preferences = selectedActivities();
  if (!canRecommend(searchState.selected, preferences, searchState.busy || searchState.searching)) return;
  searchState.busy = true;
  ++state.requestId; // 이전 저장 파일 읽기가 늦게 도착해 새 결과를 덮지 않게 합니다.
  $("search-controls").disabled = true;
  $("reload").disabled = true;
  $("report-file").disabled = true;
  $("meeting-form").setAttribute("aria-busy", "true");
  $("find-button").textContent = "만날 곳을 찾는 중…";
  $("search-status").textContent = "두 사람의 이동시간과 주변 장소를 비교하고 있어요. 수 분 걸릴 수 있어요. 창을 닫지 말고 기다려 주세요.";
  updateSearchButton();
  try {
    const data = await requestJson("/api/recommendations", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ station_a: searchState.selected.a, station_b: searchState.selected.b, preferences }),
    });
    showReport(data.report, "새 검색 결과");
    $("search-status").textContent = data.warning || "비교를 마쳤어요. 아래에서 후보별 이동시간과 장소를 살펴보세요.";
    $("comparison-title").setAttribute("tabindex", "-1");
    $("comparison-title").focus({ preventScroll: true });
    $("comparison-title").scrollIntoView({ behavior: motionEnabled() ? "smooth" : "instant", block: "start" });
  } catch (error) {
    $("search-status").textContent = connectionMessage(error) + (state.report ? " 아래의 기존 결과는 유지했어요." : "");
  } finally {
    searchState.busy = false;
    $("search-controls").disabled = false;
    $("reload").disabled = false;
    $("reload").textContent = "↻ 결과 다시 읽기";
    $("report-file").disabled = false;
    $("meeting-form").setAttribute("aria-busy", "false");
    $("find-button").textContent = "만남 후보 찾기 ↗";
    updateSearchButton();
  }
});
