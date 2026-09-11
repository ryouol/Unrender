"use strict";

(() => {
  const key = "unrender.appearance";
  const choices = new Set(["light", "dark", "system"]);
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  let preference = "light";
  try {
    const saved = localStorage.getItem(key);
    if (choices.has(saved)) preference = saved;
  } catch (_) { /* Appearance still works without browser storage. */ }
  function apply() {
    const theme = preference === "system" ? (system.matches ? "dark" : "light") : preference;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    for (const picker of document.querySelectorAll("[data-theme-picker]")) picker.value = preference;
    const markPath = `/static/icons/brand-mark${theme === "dark" ? "-dark" : ""}.png`;
    for (const mark of document.querySelectorAll(".wordmark img")) {
      if (mark.getAttribute("src") !== markPath) mark.setAttribute("src", markPath);
    }
  }
  apply();
  system.addEventListener("change", apply);
  document.addEventListener("DOMContentLoaded", () => {
    apply();
    for (const picker of document.querySelectorAll("[data-theme-picker]")) {
      picker.addEventListener("change", () => {
        if (!choices.has(picker.value)) return;
        preference = picker.value;
        try { localStorage.setItem(key, preference); } catch (_) { /* Session-only preference. */ }
        apply();
      });
    }
  });
  window.addEventListener("storage", (event) => {
    if (event.key !== key) return;
    preference = choices.has(event.newValue) ? event.newValue : "light";
    apply();
  });
})();
