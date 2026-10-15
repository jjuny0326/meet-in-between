/* 라이트/다크 테마. <head>에서 바로 실행해 화면이 그려지기 전에 테마를 적용합니다(깜빡임 방지).
   기본은 웜 라이트이며, 사용자가 고른 테마는 이 브라우저에만 저장됩니다. */
"use strict";
(function () {
  const KEY = "date-meet-theme";
  const root = document.documentElement;
  function stored() {
    try { return localStorage.getItem(KEY); } catch { return null; }
  }
  function apply(theme) {
    root.dataset.theme = theme === "dark" ? "dark" : "light";
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "dark" ? "#23201F" : "#F6F1EA";
    const button = document.getElementById("theme-toggle");
    if (button) button.setAttribute("aria-label", theme === "dark" ? "라이트 모드로 바꾸기" : "다크 모드로 바꾸기");
  }
  apply(stored());
  // 모바일 하단 탭의 첫 화면. tabs.js가 불러오기 전에도 화면이 섞여 보이지 않게 먼저 정합니다.
  root.dataset.tab = "search";
  document.addEventListener("DOMContentLoaded", () => {
    apply(root.dataset.theme);
    const button = document.getElementById("theme-toggle");
    if (!button) return;
    button.addEventListener("click", () => {
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      apply(next);
      try { localStorage.setItem(KEY, next); } catch { /* 저장할 수 없어도 현재 탭에는 적용 */ }
    });
  });
})();
