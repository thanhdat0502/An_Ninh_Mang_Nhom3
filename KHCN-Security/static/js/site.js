"use strict";
// Preserve a working GET form without JavaScript; show native progress when JS is available.
// Native GET forms navigate away; API forms keep the page and manage their state.
const searchForm = document.querySelector('form[role="search"][method="get"]');
if (searchForm) {
  searchForm.addEventListener("submit", () => {
    const submit = searchForm.querySelector('button[type="submit"]');
    if (submit) {
      submit.textContent = "Đang tìm...";
      submit.setAttribute("aria-busy", "true");
    }
  });
}
window.addEventListener("pageshow", () => {
  const submit = searchForm?.querySelector('button[type="submit"]');
  if (submit) {
    submit.textContent = "Tìm đề tài";
    submit.removeAttribute("aria-busy");
  }
});
