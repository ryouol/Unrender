const state = {
  account: null,
  jobs: [],
  currentJob: null,
  upload: null,
  uploadPage: 0,
  crop: null,
  cropStart: null,
  pollTimer: null,
  pollDelay: 1500,
  editorRows: [],
  authEpoch: 0,
  authController: new AbortController(),
  objectUrls: new Set(),
  publicConfig: { registration_open: false, sample_available: false },
};

const chartTypes = [
  "bar",
  "horizontal_bar",
  "grouped_bar",
  "stacked_bar",
  "line",
  "multi_line",
  "pie",
];

const byId = (id) => document.getElementById(id);
const routeSegment = (value) => encodeURIComponent(String(value));

function staleAuthError(message = "A previous account request was discarded") {
  const error = new Error(message);
  error.code = "stale_auth_context";
  return error;
}

function csrfToken() {
  const part = document.cookie.split("; ").find((item) => item.startsWith("unrender_csrf="));
  return part ? decodeURIComponent(part.split("=").slice(1).join("=")) : "";
}

async function api(path, options = {}) {
  const epoch = options.authEpoch ?? state.authEpoch;
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-CSRF-Token", csrfToken());
  }
  let body = options.body;
  if (body && !(body instanceof FormData) && typeof body !== "string") {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }
  const requestOptions = { ...options };
  delete requestOptions.authEpoch;
  let response;
  try {
    response = await fetch(path, {
      ...requestOptions,
      method,
      headers,
      body,
      signal: requestOptions.signal || state.authController.signal,
    });
  } catch (error) {
    if (epoch !== state.authEpoch || error?.name === "AbortError") {
      throw staleAuthError();
    }
    throw error;
  }
  if (epoch !== state.authEpoch) {
    throw staleAuthError();
  }
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (epoch !== state.authEpoch) {
    throw staleAuthError("A previous account response was discarded");
  }
  if (!response.ok) {
    const message = payload?.error?.message || `Request failed (${response.status})`;
    const error = new Error(message);
    error.code = payload?.error?.code || "request_failed";
    error.status = response.status;
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      showPublic();
      throw staleAuthError("The authenticated session ended");
    }
    throw error;
  }
  return payload;
}

function isStaleRequest(error) {
  return error?.code === "stale_auth_context" || error?.name === "AbortError";
}

function setHidden(id, hidden) {
  byId(id).hidden = hidden;
}

function showToast(message) {
  if (isStaleRequest(message)) return;
  const toast = byId("toast");
  toast.textContent = message?.message || String(message);
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { toast.hidden = true; }, 3600);
}

function showError(id, error) {
  if (isStaleRequest(error)) return;
  const element = byId(id);
  element.textContent = error?.message || String(error);
  element.hidden = false;
}

function clearError(id) {
  byId(id).hidden = true;
  byId(id).textContent = "";
}

function formatDate(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  }).format(new Date(value));
}

function statusLabel(status) {
  return {
    queued: "Queued",
    running: "Extracting",
    review: "Review needed",
    approved: "Approved",
    failed: "Needs attention",
    cancelled: "Cancelled",
  }[status] || status;
}

function stopPolling() {
  window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

function resetPrivateState() {
  stopPolling();
  window.clearTimeout(showToast.timer);
  state.authController.abort();
  state.authController = new AbortController();
  state.authEpoch += 1;
  for (const url of state.objectUrls) URL.revokeObjectURL(url);
  state.objectUrls.clear();
  document.cookie = "unrender_csrf=; Max-Age=0; Path=/; SameSite=Lax";
  state.account = null;
  state.jobs = [];
  state.currentJob = null;
  state.upload = null;
  state.uploadPage = 0;
  state.crop = null;
  state.cropStart = null;
  state.editorRows = [];
  state.pollDelay = 1500;
  byId("job-list").replaceChildren();
  byId("job-actions").replaceChildren();
  byId("audit-list").replaceChildren();
  byId("version-list").replaceChildren();
  byId("result-table").replaceChildren();
  byId("chart-type-input").replaceChildren();
  byId("api-key-list").replaceChildren();
  byId("api-key-output").textContent = "";
  byId("api-key-output").hidden = true;
  byId("api-key-form").reset();
  byId("login-form").reset();
  byId("register-form").reset();
  byId("generate-key-button").hidden = false;
  if (byId("api-key-dialog").open) byId("api-key-dialog").close();
  for (const id of [
    "job-status", "job-title", "job-meta", "source-page-label", "edit-state",
    "page-counter", "credit-count", "account-email", "result-loading",
  ]) {
    byId(id).textContent = "";
  }
  for (const id of ["job-source-image", "upload-preview"]) byId(id).removeAttribute("src");
  byId("file-input").value = "";
  byId("result-form").reset();
  byId("dropzone").removeAttribute("aria-busy");
  for (const id of ["open-sample-button", "queue-job-button", "buy-credits-button"]) {
    byId(id).disabled = false;
  }
  for (const [id, value] of [
    ["crop-left-input", 0], ["crop-top-input", 0],
    ["crop-width-input", 100], ["crop-height-input", 100],
  ]) byId(id).value = String(value);
  byId("crop-selection").hidden = true;
  byId("crop-selection").removeAttribute("style");
  byId("review-notice").hidden = true;
  byId("result-loading").hidden = true;
  byId("toggle-audit-button").textContent = "Show activity";
  byId("toggle-versions-button").textContent = "Show versions";
  byId("toast").textContent = "";
  byId("toast").hidden = true;
  for (const id of ["auth-error", "upload-error", "job-error"]) {
    byId(id).textContent = "";
    byId(id).hidden = true;
  }
  setHidden("result-form", true);
  setHidden("page-review", true);
  setHidden("audit-list", true);
  setHidden("version-list", true);
}

function showPublic() {
  resetPrivateState();
  setHidden("marketing-view", false);
  setHidden("workspace-view", true);
  setHidden("account-bar", true);
  setHidden("public-nav", false);
}

function applyPublicConfig() {
  const registrationOpen = state.publicConfig.registration_open;
  byId("register-tab").hidden = !registrationOpen;
  byId("open-sample-button").hidden = !state.publicConfig.sample_available;
  byId("show-register-button").textContent = registrationOpen
    ? "Create a workspace"
    : "Sign in to a workspace";
  if (!registrationOpen && byId("login-form").hidden) switchAuth("login");
}

function showWorkspace() {
  setHidden("marketing-view", true);
  setHidden("workspace-view", false);
  setHidden("account-bar", false);
  setHidden("public-nav", true);
  const isolatedDemo = state.account.demo_account;
  byId("account-email").textContent = isolatedDemo ? "Ephemeral sample" : state.account.email;
  byId("credit-count").textContent = isolatedDemo
    ? "Isolated demo"
    : `${state.account.credits} credit${state.account.credits === 1 ? "" : "s"}`;
  const buyButton = byId("buy-credits-button");
  buyButton.hidden = isolatedDemo || !state.account.billing_configured;
  buyButton.textContent = `Buy ${state.account.credit_pack_size} credits`;
  byId("new-upload-button").hidden = isolatedDemo;
  byId("empty-upload-button").hidden = isolatedDemo;
  byId("create-key-button").hidden = isolatedDemo;
}

function showMainView(name) {
  for (const view of ["empty-view", "upload-view", "job-view"]) {
    setHidden(view, view !== name);
  }
}

async function refreshAccount() {
  state.account = await api("/api/me");
  showWorkspace();
}

async function boot() {
  try {
    state.publicConfig = await api("/api/public-config");
  } catch (_) {
    state.publicConfig = { registration_open: false, sample_available: false };
  }
  applyPublicConfig();
  try {
    await refreshAccount();
    await loadJobs();
    if (state.jobs.length) await openJob(state.jobs[0].id);
    else showMainView("empty-view");
  } catch (error) {
    if (error.status === 401) showPublic();
    else showError("auth-error", error);
  }
}

function switchAuth(mode) {
  const login = mode === "login";
  byId("login-tab").setAttribute("aria-selected", String(login));
  byId("register-tab").setAttribute("aria-selected", String(!login));
  setHidden("login-form", !login);
  setHidden("register-form", login);
  clearError("auth-error");
  const form = byId(login ? "login-form" : "register-form");
  form.querySelector("input").focus();
}

async function submitAuth(event, mode) {
  event.preventDefault();
  clearError("auth-error");
  const form = event.currentTarget;
  const data = new FormData(form);
  resetPrivateState();
  const epoch = state.authEpoch;
  try {
    await api(`/api/auth/${mode}`, {
      method: "POST",
      body: { email: data.get("email"), password: data.get("password") },
      authEpoch: epoch,
    });
    form.reset();
    await refreshAccount();
    await loadJobs();
    showMainView(state.jobs.length ? "job-view" : "empty-view");
    if (state.jobs.length) await openJob(state.jobs[0].id);
  } catch (error) {
    showError("auth-error", error);
  }
}

async function demoLoginAndRun() {
  const button = byId("open-sample-button");
  resetPrivateState();
  const epoch = state.authEpoch;
  button.disabled = true;
  try {
    await api("/api/auth/demo", { method: "POST", authEpoch: epoch });
    await refreshAccount();
    await loadJobs();
    const completed = state.jobs.find((job) =>
      job.source_name === "budget-quarter-sample.webp" && ["review", "approved"].includes(job.status)
    );
    if (completed) await openJob(completed.id);
    else await runSample();
  } catch (error) {
    showToast(error);
  } finally {
    if (epoch === state.authEpoch) button.disabled = false;
  }
}

async function logout() {
  const epoch = state.authEpoch;
  try { await api("/api/auth/logout", { method: "POST" }); }
  finally {
    if (epoch === state.authEpoch) showPublic();
  }
}

async function loadJobs() {
  const jobs = [];
  let cursor = null;
  do {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}&limit=100` : "?limit=100";
    const payload = await api(`/api/jobs${query}`);
    jobs.push(...payload.items);
    cursor = payload.next_cursor;
  } while (cursor);
  state.jobs = jobs;
  renderJobList();
}

function renderJobList() {
  const list = byId("job-list");
  list.replaceChildren();
  if (!state.jobs.length) {
    const empty = document.createElement("p");
    empty.className = "job-list-empty";
    empty.textContent = "No extractions yet. Start with an image, a PDF page, or the saved sample.";
    list.append(empty);
    return;
  }
  for (const job of state.jobs) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-current", String(state.currentJob?.id === job.id));
    button.addEventListener("click", () => openJob(job.id));
    const name = document.createElement("strong");
    name.textContent = job.source_name;
    const meta = document.createElement("span");
    const status = document.createElement("span");
    status.textContent = statusLabel(job.status);
    status.className = `status-${job.status}`;
    const date = document.createElement("time");
    date.dateTime = job.created_at;
    date.textContent = formatDate(job.created_at);
    meta.append(status, date);
    button.append(name, meta);
    list.append(button);
  }
}

function startUpload() {
  stopPolling();
  state.upload = null;
  state.uploadPage = 0;
  state.crop = null;
  byId("file-input").value = "";
  setHidden("page-review", true);
  clearError("upload-error");
  showMainView("upload-view");
  byId("file-input").focus();
}

async function prepareFile(file) {
  if (!file) return;
  const epoch = state.authEpoch;
  clearError("upload-error");
  const form = new FormData();
  form.append("file", file);
  byId("dropzone").setAttribute("aria-busy", "true");
  try {
    state.upload = await api("/api/uploads", { method: "POST", body: form });
    state.uploadPage = 0;
    clearCrop();
    setHidden("page-review", false);
    updateUploadPreview();
  } catch (error) {
    showError("upload-error", error);
  } finally {
    if (epoch === state.authEpoch) byId("dropzone").removeAttribute("aria-busy");
  }
}

function updateUploadPreview() {
  if (!state.upload) return;
  const preview = byId("upload-preview");
  preview.src = `/api/uploads/${routeSegment(state.upload.id)}/pages/${Number(state.uploadPage)}`;
  byId("page-counter").textContent = `Page ${state.uploadPage + 1} of ${state.upload.page_count}`;
  byId("previous-page-button").disabled = state.uploadPage === 0;
  byId("next-page-button").disabled = state.uploadPage >= state.upload.page_count - 1;
  clearCrop();
}

function changePage(delta) {
  if (!state.upload) return;
  state.uploadPage = Math.max(0, Math.min(state.upload.page_count - 1, state.uploadPage + delta));
  updateUploadPreview();
}

function clearCrop() {
  state.crop = null;
  state.cropStart = null;
  const selection = byId("crop-selection");
  selection.hidden = true;
  selection.removeAttribute("style");
  for (const [id, value] of [
    ["crop-left-input", 0], ["crop-top-input", 0],
    ["crop-width-input", 100], ["crop-height-input", 100],
  ]) byId(id).value = String(value);
}

function renderCropSelection() {
  const selection = byId("crop-selection");
  if (!state.crop) {
    selection.hidden = true;
    return;
  }
  selection.hidden = false;
  selection.style.left = `${state.crop.x * 100}%`;
  selection.style.top = `${state.crop.y * 100}%`;
  selection.style.width = `${state.crop.width * 100}%`;
  selection.style.height = `${state.crop.height * 100}%`;
  byId("crop-left-input").value = String(Math.round(state.crop.x * 1000) / 10);
  byId("crop-top-input").value = String(Math.round(state.crop.y * 1000) / 10);
  byId("crop-width-input").value = String(Math.round(state.crop.width * 1000) / 10);
  byId("crop-height-input").value = String(Math.round(state.crop.height * 1000) / 10);
}

function applyKeyboardCrop() {
  const crop = {
    x: Number(byId("crop-left-input").value) / 100,
    y: Number(byId("crop-top-input").value) / 100,
    width: Number(byId("crop-width-input").value) / 100,
    height: Number(byId("crop-height-input").value) / 100,
  };
  if (!Object.values(crop).every(Number.isFinite)
    || crop.x < 0 || crop.y < 0 || crop.width < 0.05 || crop.height < 0.05
    || crop.x + crop.width > 1 || crop.y + crop.height > 1) {
    showToast("Crop percentages must stay within the source");
    return;
  }
  state.crop = crop.width === 1 && crop.height === 1 && crop.x === 0 && crop.y === 0
    ? null
    : crop;
  if (state.crop) renderCropSelection();
  else clearCrop();
}

function cropPoint(event) {
  const image = byId("upload-preview");
  const rectangle = image.getBoundingClientRect();
  const x = Math.max(0, Math.min(rectangle.width, event.clientX - rectangle.left));
  const y = Math.max(0, Math.min(rectangle.height, event.clientY - rectangle.top));
  return { x, y, rectangle };
}

function beginCrop(event) {
  if (!state.upload || event.button !== 0) return;
  event.preventDefault();
  const point = cropPoint(event);
  state.cropStart = point;
  const stage = byId("crop-stage");
  stage.setPointerCapture(event.pointerId);
  updateCrop(event);
}

function updateCrop(event) {
  if (!state.cropStart) return;
  const point = cropPoint(event);
  const start = state.cropStart;
  const left = Math.min(start.x, point.x);
  const top = Math.min(start.y, point.y);
  const width = Math.abs(start.x - point.x);
  const height = Math.abs(start.y - point.y);
  state.crop = {
    x: left / point.rectangle.width,
    y: top / point.rectangle.height,
    width: width / point.rectangle.width,
    height: height / point.rectangle.height,
  };
  renderCropSelection();
}

function finishCrop(event) {
  if (!state.cropStart) return;
  updateCrop(event);
  state.cropStart = null;
  if (!state.crop || state.crop.width < 0.05 || state.crop.height < 0.05) clearCrop();
}

async function queueCurrentUpload() {
  if (!state.upload) return;
  const epoch = state.authEpoch;
  const button = byId("queue-job-button");
  button.disabled = true;
  clearError("upload-error");
  try {
    const job = await api("/api/jobs", {
      method: "POST",
      body: { upload_id: state.upload.id, page_index: state.uploadPage, crop: state.crop },
    });
    await refreshAccount();
    await loadJobs();
    await openJob(job.id);
  } catch (error) {
    showError("upload-error", error);
  } finally {
    if (epoch === state.authEpoch) button.disabled = false;
  }
}

async function runSample() {
  try {
    const upload = await api("/api/uploads/demo", { method: "POST" });
    const job = await api("/api/jobs", {
      method: "POST", body: { upload_id: upload.id, page_index: 0, crop: null },
    });
    await refreshAccount();
    await loadJobs();
    await openJob(job.id);
  } catch (error) {
    showToast(error);
  }
}

async function openJob(jobId) {
  stopPolling();
  try {
    if (state.currentJob?.id !== jobId) state.pollDelay = 1500;
    const previousStatus = state.currentJob?.id === jobId ? state.currentJob.status : null;
    state.currentJob = await api(`/api/jobs/${routeSegment(jobId)}`);
    if (previousStatus && previousStatus !== state.currentJob.status) {
      state.pollDelay = 1500;
      await Promise.all([loadJobs(), refreshAccount()]);
    }
    else renderJobList();
    renderJob();
    showMainView("job-view");
    if (["queued", "running"].includes(state.currentJob.status)) {
      state.pollTimer = window.setTimeout(() => openJob(jobId), state.pollDelay);
      state.pollDelay = Math.min(4000, state.pollDelay + 500);
    }
  } catch (error) {
    if (error.status === 429 && state.currentJob?.id === jobId
      && ["queued", "running"].includes(state.currentJob.status)) {
      state.pollDelay = 5000;
      state.pollTimer = window.setTimeout(() => openJob(jobId), state.pollDelay);
    } else {
      showToast(error);
    }
  }
}

function actionButton(label, kind, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `button ${kind || "button-secondary"}`;
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

function renderJob() {
  const job = state.currentJob;
  if (!job) return;
  byId("job-status").textContent = statusLabel(job.status);
  byId("job-title").textContent = job.source_name;
  byId("job-meta").textContent = `${job.progress_stage} · Attempt ${job.attempt} · ${formatDate(job.updated_at)}`;
  byId("source-page-label").textContent = job.source_mime === "application/pdf" ? `PDF page ${job.page_index + 1}` : "Uploaded image";
  byId("job-source-image").src = `/api/jobs/${routeSegment(job.id)}/source?v=${routeSegment(job.updated_at)}`;
  const error = byId("job-error");
  if (job.error) {
    error.textContent = job.error.message;
    error.hidden = false;
  } else {
    error.hidden = true;
  }
  const resultReady = ["review", "approved"].includes(job.status) && job.result;
  setHidden("review-notice", !resultReady || job.status === "approved");
  setHidden("result-loading", Boolean(resultReady));
  setHidden("result-form", !resultReady);
  byId("result-loading").textContent = job.error?.message || job.progress_stage;
  byId("edit-state").textContent = job.status === "approved" ? "Approved" : resultReady ? "Not approved" : "";
  if (resultReady) renderEditor(job.result);
  renderJobActions();
  setHidden("audit-list", true);
  setHidden("version-list", true);
  byId("toggle-audit-button").textContent = "Show activity";
  byId("toggle-versions-button").textContent = "Show versions";
}

function renderJobActions() {
  const job = state.currentJob;
  const actions = byId("job-actions");
  actions.replaceChildren();
  if (["queued", "running"].includes(job.status)) {
    actions.append(actionButton("Cancel", "button-secondary", () => jobMutation("cancel")));
    return;
  }
  if (job.status === "review") {
    actions.append(actionButton("Approve result", "button-primary", () => jobMutation("approve")));
  }
  if (["review", "approved"].includes(job.status)) {
    for (const format of ["CSV", "JSON", "XLSX"]) {
      actions.append(actionButton(`Export ${format}`, "button-secondary", () => {
        window.location.assign(`/api/jobs/${routeSegment(job.id)}/export/${routeSegment(format.toLowerCase())}`);
      }));
    }
    actions.append(actionButton("Reprocess", "button-quiet", () => jobMutation("reprocess")));
  }
  if (["failed", "cancelled"].includes(job.status)) {
    actions.append(actionButton("Try again", "button-primary", () => jobMutation("reprocess")));
  }
  if (!["queued", "running"].includes(job.status)) {
    actions.append(actionButton("Delete", "button-danger", deleteCurrentJob));
  }
}

async function jobMutation(action) {
  const job = state.currentJob;
  if (!job) return;
  try {
    state.currentJob = await api(`/api/jobs/${routeSegment(job.id)}/${routeSegment(action)}`, { method: "POST" });
    await refreshAccount();
    await loadJobs();
    renderJob();
    if (["queued", "running"].includes(state.currentJob.status)) {
      state.pollDelay = 1500;
      state.pollTimer = window.setTimeout(() => openJob(job.id), state.pollDelay);
    }
    showToast(action === "approve" ? "Result approved" : action === "cancel" ? "Cancellation recorded" : "Extraction queued");
  } catch (error) {
    showToast(error);
  }
}

async function deleteCurrentJob() {
  const job = state.currentJob;
  if (!job || !window.confirm("Delete this source, result, and audit trail? This cannot be undone.")) return;
  try {
    const deletion = await api(`/api/jobs/${routeSegment(job.id)}`, { method: "DELETE" });
    state.currentJob = null;
    await loadJobs();
    if (state.jobs.length) await openJob(state.jobs[0].id);
    else showMainView("empty-view");
    showToast(deletion?.status === "deletion_queued"
      ? "Extraction hidden; source deletion will retry automatically"
      : "Extraction deleted");
  } catch (error) {
    showToast(error);
  }
}

function editorRows(result) {
  const series = result.series?.length ? result.series : [{ name: null, points: [] }];
  const rows = [];
  const pointCount = Math.max(0, ...series.map((item) => item.points?.length || 0));
  for (let pointIndex = 0; pointIndex < pointCount; pointIndex += 1) {
    const groups = [];
    series.forEach((item, seriesIndex) => {
      const point = item.points?.[pointIndex];
      if (!point) return;
      const xType = typeof point.x === "number" ? "number" : "string";
      const identity = `${xType}:${JSON.stringify(point.x)}`;
      let group = groups.find((candidate) => candidate.identity === identity);
      if (!group) {
        group = {
          identity,
          x: String(point.x),
          xType,
          values: series.map(() => ""),
        };
        groups.push(group);
      }
      group.values[seriesIndex] = String(point.y);
    });
    for (const { identity: _, ...row } of groups) {
      rows.push(row);
    }
  }
  return rows;
}

function renderEditor(result) {
  byId("chart-type-input").replaceChildren(...chartTypes.map((type) => {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = type.replaceAll("_", " ");
    option.selected = result.chart_type === type;
    return option;
  }));
  byId("chart-title-input").value = result.title || "";
  byId("x-label-input").value = result.x_axis?.label || "";
  byId("y-label-input").value = result.y_axis?.label || "";
  byId("y-unit-input").value = result.y_axis?.unit || "";
  state.editorRows = editorRows(result);
  renderResultTable(result.series?.length ? result.series : [{ name: null, points: [] }]);
}

function renderResultTable(series) {
  const table = byId("result-table");
  table.replaceChildren();
  const head = document.createElement("thead");
  const row = document.createElement("tr");
  const xHead = document.createElement("th");
  xHead.scope = "col";
  xHead.textContent = "Category / x";
  row.append(xHead);
  series.forEach((item, index) => {
    const th = document.createElement("th");
    th.scope = "col";
    const input = document.createElement("input");
    input.value = item.name || "";
    input.placeholder = series.length === 1 ? "Value" : `Series ${index + 1}`;
    input.dataset.seriesName = String(index);
    input.setAttribute("aria-label", `Series ${index + 1} name`);
    th.append(input);
    row.append(th);
  });
  const actionHead = document.createElement("th");
  actionHead.scope = "col";
  actionHead.className = "row-action";
  actionHead.textContent = "Row";
  row.append(actionHead);
  head.append(row);
  const body = document.createElement("tbody");
  state.editorRows.forEach((item, rowIndex) => {
    const tr = document.createElement("tr");
    const xCell = document.createElement("td");
    const xInput = document.createElement("input");
    xInput.value = item.x;
    xInput.dataset.xType = item.xType || "string";
    xInput.dataset.row = String(rowIndex);
    xInput.dataset.kind = "x";
    xInput.setAttribute("aria-label", `Row ${rowIndex + 1} category`);
    xCell.append(xInput);
    tr.append(xCell);
    series.forEach((_, seriesIndex) => {
      const cell = document.createElement("td");
      const input = document.createElement("input");
      input.type = "number";
      input.step = "any";
      input.value = item.values[seriesIndex] ?? "";
      input.dataset.row = String(rowIndex);
      input.dataset.series = String(seriesIndex);
      input.dataset.kind = "value";
      input.setAttribute("aria-label", `Row ${rowIndex + 1}, series ${seriesIndex + 1} value`);
      cell.append(input);
      tr.append(cell);
    });
    const removeCell = document.createElement("td");
    removeCell.className = "row-action";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      collectEditorRows();
      state.editorRows.splice(rowIndex, 1);
      renderResultTable(seriesFromInputs(series));
    });
    removeCell.append(remove);
    tr.append(removeCell);
    body.append(tr);
  });
  table.append(head, body);
}

function seriesFromInputs(fallback) {
  return fallback.map((item, index) => {
    const input = document.querySelector(`[data-series-name="${index}"]`);
    return { ...item, name: input ? input.value.trim() || null : item.name };
  });
}

function collectEditorRows() {
  const table = byId("result-table");
  if (!table.tBodies.length) return;
  const count = table.tBodies[0].rows.length;
  const seriesCount = table.tHead.rows[0].cells.length - 2;
  state.editorRows = Array.from({ length: count }, (_, rowIndex) => ({
    x: table.querySelector(`[data-kind="x"][data-row="${rowIndex}"]`)?.value || "",
    xType: table.querySelector(`[data-kind="x"][data-row="${rowIndex}"]`)?.dataset.xType || "string",
    values: Array.from({ length: seriesCount }, (_, seriesIndex) =>
      table.querySelector(`[data-kind="value"][data-row="${rowIndex}"][data-series="${seriesIndex}"]`)?.value || ""
    ),
  }));
}

function addEditorRow() {
  collectEditorRows();
  const series = state.currentJob.result.series?.length ? state.currentJob.result.series : [{ name: null, points: [] }];
  state.editorRows.push({ x: "", xType: "string", values: series.map(() => "") });
  renderResultTable(seriesFromInputs(series));
  byId("result-table").tBodies[0].lastElementChild.querySelector("input").focus();
}

function coerceX(value, xType) {
  const text = value.trim();
  if (xType === "number" && /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(text)) return Number(text);
  return text;
}

function buildEditedResult() {
  collectEditorRows();
  const original = state.currentJob.result;
  const seriesNames = Array.from(byId("result-table").querySelectorAll("[data-series-name]"))
    .map((input) => input.value.trim() || null);
  const series = seriesNames.map((name, seriesIndex) => ({
    name,
    points: state.editorRows
      .filter((row) => row.x.trim() && row.values[seriesIndex] !== "")
      .map((row) => ({ x: coerceX(row.x, row.xType), y: Number(row.values[seriesIndex]) })),
  }));
  return {
    chart_type: byId("chart-type-input").value,
    title: byId("chart-title-input").value.trim() || null,
    x_axis: {
      label: byId("x-label-input").value.trim() || null,
      unit: original.x_axis?.unit || null,
    },
    y_axis: {
      label: byId("y-label-input").value.trim() || null,
      unit: byId("y-unit-input").value.trim() || null,
    },
    series,
  };
}

async function saveCorrections(event) {
  event.preventDefault();
  try {
    const result = buildEditedResult();
    state.currentJob = await api(`/api/jobs/${routeSegment(state.currentJob.id)}/result`, {
      method: "PATCH", body: { result },
    });
    await loadJobs();
    renderJob();
    showToast("Corrections saved to the audit trail");
  } catch (error) {
    showToast(error);
  }
}

async function toggleAudit() {
  const list = byId("audit-list");
  if (!list.hidden) {
    list.hidden = true;
    byId("toggle-audit-button").textContent = "Show activity";
    return;
  }
  try {
    const jobId = state.currentJob.id;
    const items = [];
    const rollups = [];
    let cursor = null;
    do {
      const query = cursor ? `?cursor=${encodeURIComponent(cursor)}&limit=100` : "?limit=100";
      const payload = await api(`/api/jobs/${routeSegment(jobId)}/audit${query}`);
      items.push(...payload.items);
      rollups.push(...(payload.rollups || []));
      cursor = payload.next_cursor;
    } while (cursor);
    list.replaceChildren(...[...items, ...rollups].map((item) => {
      const entry = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = `${item.event.replaceAll("_", " ")}${item.count ? ` · ${item.count} archived events` : ""}`;
      const time = document.createElement("time");
      time.dateTime = item.created_at;
      time.textContent = formatDate(item.created_at);
      entry.append(title, time);
      return entry;
    }));
    list.hidden = false;
    byId("toggle-audit-button").textContent = "Hide activity";
  } catch (error) {
    showToast(error);
  }
}

async function restoreVersion(version) {
  try {
    const saved = await api(
      `/api/jobs/${routeSegment(state.currentJob.id)}/versions/${routeSegment(version.version)}`,
    );
    state.currentJob = await api(`/api/jobs/${routeSegment(state.currentJob.id)}/result`, {
      method: "PATCH", body: { result: saved.result },
    });
    await loadJobs();
    renderJob();
    showToast(`Version ${version.version} restored as a new correction`);
  } catch (error) {
    showToast(error);
  }
}

async function loadVersions(before = null, append = false) {
  const list = byId("version-list");
  const query = before === null ? "" : `?before=${encodeURIComponent(before)}`;
  const payload = await api(`/api/jobs/${routeSegment(state.currentJob.id)}/versions${query}`);
  if (!append) list.replaceChildren();
  else list.querySelector("[data-load-older]")?.remove();

  for (const item of payload.items) {
    const entry = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `Version ${item.version} · ${item.source}`;
    const time = document.createElement("time");
    time.dateTime = item.created_at;
    time.textContent = formatDate(item.created_at);
    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "text-button";
    restore.textContent = "Restore as new correction";
    restore.addEventListener("click", () => restoreVersion(item));
    entry.append(title, time, restore);
    list.append(entry);
  }
  if (payload.next_before !== null) {
    const moreEntry = document.createElement("li");
    moreEntry.dataset.loadOlder = "true";
    const more = document.createElement("button");
    more.type = "button";
    more.className = "text-button";
    more.textContent = "Load older versions";
    more.addEventListener("click", async () => {
      more.disabled = true;
      try {
        await loadVersions(payload.next_before, true);
      } catch (error) {
        if (!isStaleRequest(error)) more.disabled = false;
        showToast(error);
      }
    });
    moreEntry.append(more);
    list.append(moreEntry);
  }
  return payload.items.length;
}

async function toggleVersions() {
  const list = byId("version-list");
  if (!list.hidden) {
    list.hidden = true;
    byId("toggle-versions-button").textContent = "Show versions";
    return;
  }
  try {
    const count = await loadVersions();
    if (!count) {
      const empty = document.createElement("li");
      empty.textContent = "No extracted result yet.";
      list.append(empty);
    }
    list.hidden = false;
    byId("toggle-versions-button").textContent = "Hide versions";
  } catch (error) {
    showToast(error);
  }
}

async function openKeyDialog() {
  byId("api-key-output").hidden = true;
  byId("api-key-output").textContent = "";
  byId("generate-key-button").hidden = false;
  byId("api-key-dialog").showModal();
  byId("api-key-name").focus();
  await loadApiKeys();
}

async function loadApiKeys() {
  const list = byId("api-key-list");
  try {
    const keys = [];
    let cursor = null;
    do {
      const query = cursor ? `?cursor=${encodeURIComponent(cursor)}&limit=100` : "?limit=100";
      const payload = await api(`/api/keys${query}`);
      keys.push(...payload.items);
      cursor = payload.next_cursor;
    } while (cursor);
    list.replaceChildren();
    if (!keys.length) {
      const empty = document.createElement("li");
      empty.textContent = "No API keys yet.";
      list.append(empty);
      return;
    }
    for (const key of keys) {
      const item = document.createElement("li");
      const details = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = key.name;
      const metadata = document.createElement("small");
      metadata.textContent = `${key.prefix}… · ${key.revoked_at ? "Revoked" : key.last_used_at ? `Last used ${formatDate(key.last_used_at)}` : "Never used"}`;
      details.append(name, metadata);
      item.append(details);
      if (!key.revoked_at) {
        const revoke = document.createElement("button");
        revoke.type = "button";
        revoke.className = "text-button danger-text";
        revoke.textContent = "Revoke";
        revoke.addEventListener("click", () => revokeApiKey(key.id));
        item.append(revoke);
      }
      list.append(item);
    }
  } catch (error) {
    if (isStaleRequest(error)) return;
    list.replaceChildren();
    const failed = document.createElement("li");
    failed.textContent = error.message;
    list.append(failed);
  }
}

async function revokeAllApiKeys() {
  if (!window.confirm("Revoke every active API key for this workspace?")) return;
  try {
    const payload = await api("/api/keys", { method: "DELETE" });
    await loadApiKeys();
    showToast(`${payload.revoked} active API key${payload.revoked === 1 ? "" : "s"} revoked`);
  } catch (error) {
    showToast(error);
  }
}

async function revokeApiKey(keyId) {
  try {
    await api(`/api/keys/${routeSegment(keyId)}`, { method: "DELETE" });
    await loadApiKeys();
    showToast("API key revoked");
  } catch (error) {
    showToast(error);
  }
}

async function createKey(event) {
  event.preventDefault();
  try {
    const payload = await api("/api/keys", {
      method: "POST", body: { name: byId("api-key-name").value },
    });
    byId("api-key-output").textContent = payload.key;
    byId("api-key-output").hidden = false;
    byId("generate-key-button").hidden = true;
    await loadApiKeys();
  } catch (error) {
    showToast(error);
  }
}

async function buyCredits() {
  const button = byId("buy-credits-button");
  const epoch = state.authEpoch;
  button.disabled = true;
  try {
    const payload = await api("/api/billing/checkout", { method: "POST" });
    const destination = new URL(payload.url);
    if (destination.protocol !== "https:" || destination.hostname !== "checkout.stripe.com") {
      throw new Error("Checkout returned an unexpected destination");
    }
    window.location.assign(destination.href);
  } catch (error) {
    showToast(error);
    if (epoch === state.authEpoch) button.disabled = false;
  }
}

function bindEvents() {
  byId("login-tab").addEventListener("click", () => switchAuth("login"));
  byId("register-tab").addEventListener("click", () => switchAuth("register"));
  byId("show-register-button").addEventListener("click", () => {
    switchAuth(state.publicConfig.registration_open ? "register" : "login");
    byId("auth-title").scrollIntoView();
  });
  byId("login-form").addEventListener("submit", (event) => submitAuth(event, "login"));
  byId("register-form").addEventListener("submit", (event) => submitAuth(event, "register"));
  byId("open-sample-button").addEventListener("click", demoLoginAndRun);
  byId("logout-button").addEventListener("click", logout);
  byId("home-button").addEventListener("click", () => {
    if (state.account) showMainView(state.jobs.length ? "job-view" : "empty-view");
    else showPublic();
  });
  for (const id of ["new-upload-button", "empty-upload-button"]) byId(id).addEventListener("click", startUpload);
  byId("cancel-upload-button").addEventListener("click", () => {
    if (state.currentJob) openJob(state.currentJob.id); else showMainView("empty-view");
  });
  byId("file-input").addEventListener("change", (event) => prepareFile(event.target.files[0]));
  byId("previous-page-button").addEventListener("click", () => changePage(-1));
  byId("next-page-button").addEventListener("click", () => changePage(1));
  byId("clear-crop-button").addEventListener("click", clearCrop);
  byId("apply-crop-button").addEventListener("click", applyKeyboardCrop);
  byId("crop-stage").addEventListener("pointerdown", beginCrop);
  byId("crop-stage").addEventListener("pointermove", updateCrop);
  byId("crop-stage").addEventListener("pointerup", finishCrop);
  byId("crop-stage").addEventListener("pointercancel", clearCrop);
  byId("queue-job-button").addEventListener("click", queueCurrentUpload);
  byId("run-sample-button").addEventListener("click", runSample);
  byId("result-form").addEventListener("submit", saveCorrections);
  byId("add-row-button").addEventListener("click", addEditorRow);
  byId("toggle-versions-button").addEventListener("click", toggleVersions);
  byId("toggle-audit-button").addEventListener("click", toggleAudit);
  byId("create-key-button").addEventListener("click", openKeyDialog);
  byId("close-key-dialog").addEventListener("click", () => byId("api-key-dialog").close());
  byId("revoke-all-keys-button").addEventListener("click", revokeAllApiKeys);
  byId("api-key-form").addEventListener("submit", createKey);
  byId("buy-credits-button").addEventListener("click", buyCredits);
}

bindEvents();
boot();
