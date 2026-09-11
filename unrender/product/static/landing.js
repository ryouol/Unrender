"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const dialog = byId("landing-example-dialog");
  const menu = byId("landing-menu");
  const input = byId("demo-q3");
  const error = byId("demo-error");
  const status = byId("demo-status");
  const save = byId("demo-save");
  const approve = byId("demo-approve");
  const exports = byId("demo-export");
  let saved = false;
  let approved = false;
  let exampleOpener = null;
  let menuOpener = null;

  if (typeof dialog.showModal !== "function") return;
  document.body.classList.add("landing-enhanced");
  byId("landing-menu-open").hidden = false;

  if (typeof IntersectionObserver === "function") {
    const stickyAction = byId("landing-mobile-cta");
    const observer = new IntersectionObserver(([entry]) => {
      stickyAction.hidden = entry.isIntersecting;
    });
    observer.observe(document.querySelector(".landing-actions"));
  }

  function step(name) {
    for (const item of dialog.querySelectorAll("[data-demo-step]")) {
      if (item.dataset.demoStep === name) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    }
  }

  function reset() {
    input.value = "16.3";
    input.removeAttribute("aria-invalid");
    error.hidden = true;
    error.textContent = "";
    saved = false;
    approved = false;
    save.hidden = false;
    approve.hidden = true;
    exports.hidden = true;
    byId("demo-badge").textContent = "Needs review";
    status.textContent = "";
    step("review");
  }

  for (const opener of document.querySelectorAll("[data-open-example]")) {
    opener.setAttribute("aria-haspopup", "dialog");
    opener.setAttribute("aria-controls", "landing-example-dialog");
    opener.addEventListener("click", (event) => {
      event.preventDefault();
      exampleOpener = opener;
      reset();
      dialog.showModal();
      document.body.classList.add("landing-dialog-open");
      byId("demo-title").focus();
    });
  }
  dialog.addEventListener("close", () => {
    document.body.classList.remove("landing-dialog-open");
    reset();
    if (exampleOpener?.isConnected) exampleOpener.focus();
  });
  byId("demo-reset").addEventListener("click", () => {
    reset();
    status.textContent = "Example reset. Correct Q3 to begin again.";
    input.focus();
  });
  input.addEventListener("input", () => {
    saved = false;
    approved = false;
    save.hidden = false;
    approve.hidden = true;
    exports.hidden = true;
    error.hidden = true;
    input.removeAttribute("aria-invalid");
    byId("demo-badge").textContent = "Unsaved change";
    status.textContent = "";
    step("review");
  });
  byId("landing-demo-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (saved) return;
    if (!input.checkValidity() || Math.abs(input.valueAsNumber - 16.8) > 0.000001) {
      input.setAttribute("aria-invalid", "true");
      error.textContent = "Look at the Q3 label in the source: it reads 16.8. Enter that value to continue.";
      error.hidden = false;
      input.focus();
      return;
    }
    saved = true;
    approved = false;
    error.hidden = true;
    input.removeAttribute("aria-invalid");
    save.hidden = true;
    approve.hidden = false;
    exports.hidden = true;
    byId("demo-badge").textContent = "Correction saved";
    status.textContent = "Q3 corrected from 16.3 to 16.8. This change stays only in this example.";
    step("approve");
    approve.focus();
  });
  approve.addEventListener("click", () => {
    if (!saved) return;
    approved = true;
    approve.hidden = true;
    exports.hidden = false;
    byId("demo-badge").textContent = "Approved by you";
    status.textContent = "Example approved. Choose a format to download the illustrative data.";
    step("export");
    dialog.querySelector("[data-demo-export]").focus();
  });

  for (const button of dialog.querySelectorAll("[data-demo-export]")) {
    button.addEventListener("click", () => {
      if (!saved || !approved) return;
      const format = button.dataset.demoExport;
      if (!["csv", "json"].includes(format)) return;
      const points = [12.4, 18.6, 16.8, 24.2].map((y, index) => ({ x: `Q${index + 1}`, y }));
      const data = format === "csv"
        ? "Quarter,Revenue ($m)\r\n" + points.map(({ x, y }) => `${x},${y}`).join("\r\n") + "\r\n"
        : JSON.stringify({
          example: "Illustrative data; prepared locally without model inference",
          chart_type: "bar", title: "Quarterly revenue",
          x_axis: { label: "Quarter", unit: null }, y_axis: { label: "Revenue", unit: "$m" },
          series: [{ name: "Revenue", points }],
        }, null, 2) + "\n";
      const url = URL.createObjectURL(new Blob([data], {
        type: format === "csv" ? "text/csv;charset=utf-8" : "application/json;charset=utf-8",
      }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `unrender-illustrative-example.${format}`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      status.textContent = `${format.toUpperCase()} download started. You can download another format or try your own chart.`;
    });
  }

  byId("landing-menu-open").addEventListener("click", (event) => {
    menuOpener = event.currentTarget;
    menu.showModal();
    document.body.classList.add("landing-dialog-open");
  });
  menu.addEventListener("close", () => {
    document.body.classList.remove("landing-dialog-open");
    if (menuOpener?.isConnected) menuOpener.focus();
  });
  for (const link of menu.querySelectorAll("a")) {
    link.addEventListener("click", () => {
      menuOpener = null;
      menu.close();
      if (link.hash) {
        const destination = document.querySelector(link.hash);
        if (destination) {
          destination.setAttribute("tabindex", "-1");
          destination.focus({ preventScroll: true });
        }
      }
    });
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);
  fetch("/api/public-config", { credentials: "omit", headers: { Accept: "application/json" }, signal: controller.signal })
    .then((response) => response.ok ? response.json() : null)
    .then((config) => {
      const limits = [config?.max_upload_bytes, config?.max_image_pixels, config?.max_pdf_pages];
      if (!limits.every((value) => Number.isFinite(value) && value > 0)) return;
      const note = byId("landing-upload-limits");
      note.textContent = `Up to ${Number((limits[0] / 1048576).toFixed(1))} MiB per file · Images up to ${Number((limits[1] / 1000000).toFixed(1))} MP · PDFs up to ${limits[2]} pages`;
      note.hidden = false;
    })
    .catch(() => {})
    .finally(() => window.clearTimeout(timeout));
})();
