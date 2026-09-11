"use strict";

(() => {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);
  fetch("/api/public-config", { credentials: "omit", headers: { Accept: "application/json" }, signal: controller.signal })
    .then((response) => response.ok ? response.json() : null)
    .then((config) => {
      const limits = [config?.max_upload_bytes, config?.max_image_pixels, config?.max_pdf_pages];
      if (limits.every((value) => Number.isFinite(value) && value > 0)) {
        document.getElementById("landing-upload-limits").textContent = `Up to ${Number((limits[0] / 1048576).toFixed(1))} MiB per file · Images up to ${Number((limits[1] / 1000000).toFixed(1))} MP · PDFs up to ${limits[2]} pages`;
      }
      if (config?.registration_open === false) {
        for (const link of document.querySelectorAll("[data-signup-link]")) {
          link.href = "/contact";
          link.querySelector("span").textContent = "Request access";
        }
        document.getElementById("landing-access-note").textContent = "Account access is currently by invitation.";
      } else if (Number.isInteger(config?.initial_credits) && config.initial_credits > 0) {
        document.getElementById("landing-access-note").textContent = `Start with ${config.initial_credits} free testing credit${config.initial_credits === 1 ? "" : "s"}. One credit per extraction attempt.`;
      } else if (config?.initial_credits === 0) {
        document.getElementById("landing-access-note").textContent = "Accounts are free. Extraction access is granted separately.";
      }
    })
    .catch(() => {})
    .finally(() => window.clearTimeout(timeout));

  const artwork = document.getElementById("landing-artwork");
  const motionButton = document.getElementById("landing-motion");
  const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
  const events = new AbortController();
  const reveals = [...document.querySelectorAll("[data-reveal]")];
  let paused = false;
  let frame = null;
  const observer = typeof IntersectionObserver === "function" ? new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    }
  }, { threshold: 0.08 }) : null;

  function stopFrame() {
    if (frame !== null) window.cancelAnimationFrame(frame);
    frame = null;
  }
  function updateArtwork() {
    frame = null;
    const rect = artwork.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) return;
    const progress = Math.min(1, Math.max(0, window.scrollY / Math.max(1, window.innerHeight)));
    artwork.style.transform = `translateY(${-36 * progress}px) scale(${1 + .035 * progress})`;
  }
  function schedule() {
    if (!paused && !preference.matches && !document.hidden && frame === null) frame = window.requestAnimationFrame(updateArtwork);
  }
  function applyMotion() {
    stopFrame();
    motionButton.hidden = preference.matches;
    motionButton.textContent = paused ? "Resume motion" : "Pause motion";
    motionButton.setAttribute("aria-pressed", String(paused));
    document.body.classList.toggle("landing-motion-paused", paused || preference.matches);
    document.body.classList.toggle("landing-motion-enabled", Boolean(observer) && !preference.matches);
    if (preference.matches) artwork.style.transform = "";
    schedule();
  }
  function observeSections() {
    for (const item of reveals) observer?.observe(item);
  }
  motionButton.addEventListener("click", () => { paused = !paused; applyMotion(); }, { signal: events.signal });
  preference.addEventListener("change", applyMotion, { signal: events.signal });
  window.addEventListener("scroll", schedule, { passive: true, signal: events.signal });
  window.addEventListener("resize", schedule, { signal: events.signal });
  document.addEventListener("visibilitychange", () => document.hidden ? stopFrame() : schedule(), { signal: events.signal });
  window.addEventListener("pagehide", (event) => {
    stopFrame();
    controller.abort();
    observer?.disconnect();
    if (!event.persisted) events.abort();
  }, { signal: events.signal });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) { observeSections(); schedule(); }
  }, { signal: events.signal });
  observeSections();
  applyMotion();
})();
