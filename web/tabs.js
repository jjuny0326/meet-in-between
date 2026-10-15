/* 모바일(760px 이하) 하단 탭. 화면 전환은 <html data-tab="...">와 CSS가 담당하고,
   각 영역은 data-view="..."에 속한 탭 이름을 적어 둡니다. 데스크톱에서는 모든 영역을 한 페이지에 보여 줍니다. */
"use strict";
const TABS = ["search", "results", "map", "guide"];
const mobileTabs = typeof matchMedia === "function" ? matchMedia("(max-width: 760px)") : { matches: false };

function showTab(name, { scroll = true } = {}) {
  if (!TABS.includes(name)) return;
  const root = document.documentElement;
  const changed = root.dataset.tab !== name;
  root.dataset.tab = name;
  for (const button of document.querySelectorAll("[data-tab]")) {
    if (button.dataset.tab === name) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
    // 결과 탭을 열면 '새 결과' 표시를 지웁니다.
    if (name === "results" && button.dataset.tab === "results") delete button.dataset.new;
  }
  // 숨겨져 있던 지도는 보이는 순간 크기를 다시 계산해야 합니다.
  if (name === "map" && typeof MeetingMap !== "undefined") MeetingMap.refresh?.();
  // 숨겨져 있던 추천 설명은 보이는 순간에 길이를 재야 '더 보기' 버튼 필요 여부를 알 수 있습니다.
  if (name === "results" && typeof updateSummaryMore === "function") requestAnimationFrame(updateSummaryMore);
  if (changed && scroll && mobileTabs.matches) window.scrollTo({ top: 0, behavior: "instant" });
}

for (const button of document.querySelectorAll("[data-tab]")) {
  button.addEventListener("click", () => showTab(button.dataset.tab));
}

// 결과가 생기면 ②·③ 단계를 활성화하고, 다른 탭을 보고 있으면 ②에 '새 결과' 점을 표시합니다.
function markResultReady() {
  const root = document.documentElement;
  root.dataset.result = "ready";
  if (root.dataset.tab === "results") return;
  for (const button of document.querySelectorAll('[data-tab="results"]')) button.dataset.new = "true";
}

// 같은 페이지 안 링크(#...)는 그 내용이 들어 있는 탭으로 먼저 바꾼 뒤 이동합니다.
document.addEventListener("click", (event) => {
  if (!mobileTabs.matches) return;
  const link = event.target.closest?.('a[href^="#"]');
  const target = link && document.getElementById(link.getAttribute("href").slice(1));
  const view = target?.closest("[data-view]")?.dataset.view.split(" ")[0];
  if (view) showTab(view, { scroll: false });
});

showTab(document.documentElement.dataset.tab || "search", { scroll: false });
