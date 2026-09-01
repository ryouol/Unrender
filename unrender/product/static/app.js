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
  editorSeries: [],
  editorPage: 0,
  authEpoch: 0,
  authController: new AbortController(),
  principalMarker: null,
  viewEpoch: 0,
  viewController: new AbortController(),
  jobSubmission: null,
  keySecretTimer: null,
  authChannel: null,
  suppressPrincipalReconcileUntil: 0,
  objectUrls: new Set(),
  publicConfig: { registration_open: false, sample_available: false },
};

const AUTH_EVENT_KEY = "unrender.auth-change.v1";
const EDITOR_PAGE_SIZE = 100;
const EDITOR_MAX_ROWS = 10000;
const EDITOR_MOUNTED_CELL_LIMIT = 500;

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
      const hadPrincipal = Boolean(state.principalMarker);
      showPublic();
      if (hadPrincipal) publishAuthChange("session-ended");
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

function resetViewSelection() {
  state.viewController.abort();
  state.viewController = new AbortController();
  state.viewEpoch += 1;
}

function beginViewSelection() {
  resetViewSelection();
  return { epoch: state.viewEpoch, signal: state.viewController.signal };
}

function clearApiKeySecret() {
  window.clearTimeout(state.keySecretTimer);
  state.keySecretTimer = null;
  byId("api-key-output").textContent = "";
  byId("api-key-output").hidden = true;
  byId("copy-key-button").hidden = true;
  byId("dismiss-key-button").hidden = true;
}

function publishAuthChange(reason) {
  state.suppressPrincipalReconcileUntil = ["logout", "session-ended"].includes(reason)
    ? Number.POSITIVE_INFINITY
    : 0;
  const nonce = crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  const event = JSON.stringify({ reason, nonce });
  try { localStorage.setItem(AUTH_EVENT_KEY, event); } catch (_) { /* unavailable */ }
  state.authChannel?.postMessage(event);
}

function authChangeReason(event) {
  const raw = typeof event === "string" ? event : event?.data ?? event?.newValue;
  try {
    return JSON.parse(raw)?.reason || "unknown";
  } catch (_) {
    return "unknown";
  }
}

function resetPrivateState({ clearCsrf = true } = {}) {
  stopPolling();
  resetViewSelection();
  window.clearTimeout(showToast.timer);
  clearApiKeySecret();
  state.authController.abort();
  state.authController = new AbortController();
  state.authEpoch += 1;
  for (const url of state.objectUrls) URL.revokeObjectURL(url);
  state.objectUrls.clear();
  if (clearCsrf) document.cookie = "unrender_csrf=; Max-Age=0; Path=/; SameSite=Lax";
  state.account = null;
  state.jobs = [];
  state.currentJob = null;
  state.upload = null;
  state.uploadPage = 0;
  state.crop = null;
  state.cropStart = null;
  state.editorRows = [];
  state.editorSeries = [];
  state.editorPage = 0;
  state.jobSubmission = null;
  state.principalMarker = null;
  state.pollDelay = 1500;
  byId("job-list").replaceChildren();
  byId("job-actions").replaceChildren();
  byId("audit-list").replaceChildren();
  byId("version-list").replaceChildren();
  byId("result-table").replaceChildren();
  byId("series-editor-list").replaceChildren();
  byId("chart-type-input").replaceChildren();
  byId("api-key-list").replaceChildren();
  byId("api-key-form").reset();
  byId("login-form").reset();
  byId("register-form").reset();
  byId("generate-key-button").hidden = false;
  if (byId("api-key-dialog").open) byId("api-key-dialog").close();
  for (const id of [
    "job-status", "job-title", "job-meta", "source-page-label", "edit-state",
    "page-counter", "credit-count", "account-email", "result-loading",
    "editor-page-summary",
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

function showPublic({ clearCsrf = true } = {}) {
  resetPrivateState({ clearCsrf });
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

async function refreshAccount(options = {}) {
  const account = await api("/api/me", options);
  if (state.principalMarker && state.principalMarker !== account.principal_marker) {
    resetPrivateState({ clearCsrf: false });
  }
  state.principalMarker = account.principal_marker;
  state.account = account;
  showWorkspace();
  return account;
}

async function reconcilePrincipal() {
  if (Date.now() < state.suppressPrincipalReconcileUntil) return;
  try {
    const previous = state.principalMarker;
    const account = await refreshAccount();
    if (previous !== account.principal_marker || !state.jobs.length) {
      await loadJobs();
      if (state.jobs.length) await openJob(state.jobs[0].id);
      else showMainView("empty-view");
    }
  } catch (error) {
    if (!isStaleRequest(error) && error.status !== 401) showToast(error);
  }
}

function handleExternalAuthChange(event) {
  const reason = authChangeReason(event);
  if (["logout", "session-ended"].includes(reason)) {
    // Keep reconciliation blocked until an explicit successful authentication.
    // A timeout could restore a principal while server-side revocation is delayed.
    state.suppressPrincipalReconcileUntil = Number.POSITIVE_INFINITY;
  } else {
    state.suppressPrincipalReconcileUntil = 0;
  }
  showPublic({ clearCsrf: false });
  if (reason !== "logout" && reason !== "session-ended") void reconcilePrincipal();
}

function installAuthCoordination() {
  try {
    const previousReason = authChangeReason(localStorage.getItem?.(AUTH_EVENT_KEY));
    if (["logout", "session-ended"].includes(previousReason)) {
      state.suppressPrincipalReconcileUntil = Number.POSITIVE_INFINITY;
    }
  } catch (_) { /* unavailable */ }
  if (typeof BroadcastChannel === "function") {
    state.authChannel = new BroadcastChannel(AUTH_EVENT_KEY);
    state.authChannel.addEventListener("message", handleExternalAuthChange);
  }
  window.addEventListener("storage", (event) => {
    if (event.key === AUTH_EVENT_KEY) handleExternalAuthChange();
  });
  window.addEventListener("focus", () => { void reconcilePrincipal(); });
  window.addEventListener("pageshow", () => { void reconcilePrincipal(); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void reconcilePrincipal();
  });
}

async function boot() {
  installAuthCoordination();
  try {
    state.publicConfig = await api("/api/public-config");
  } catch (_) {
    state.publicConfig = { registration_open: false, sample_available: false };
  }
  applyPublicConfig();
  if (Date.now() < state.suppressPrincipalReconcileUntil) {
    showPublic({ clearCsrf: false });
    return;
  }
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
    publishAuthChange("authenticated");
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
    publishAuthChange("authenticated");
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
  const csrf = csrfToken();
  const request = fetch("/api/auth/logout", {
    method: "POST",
    headers: { "X-CSRF-Token": csrf, Accept: "application/json" },
  });
  state.suppressPrincipalReconcileUntil = Number.POSITIVE_INFINITY;
  showPublic();
  publishAuthChange("logout");
  try { await request; } catch (_) { /* local privacy reset is already complete */ }
}

async function loadJobs() {
  const authEpoch = state.authEpoch;
  const jobs = [];
  let cursor = null;
  do {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}&limit=100` : "?limit=100";
    const payload = await api(`/api/jobs${query}`, { authEpoch });
    if (authEpoch !== state.authEpoch) throw staleAuthError();
    jobs.push(...payload.items);
    cursor = payload.next_cursor;
  } while (cursor);
  if (authEpoch !== state.authEpoch) throw staleAuthError();
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
  resetViewSelection();
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
  const view = beginViewSelection();
  clearError("upload-error");
  const form = new FormData();
  form.append("file", file);
  byId("dropzone").setAttribute("aria-busy", "true");
  try {
    const upload = await api("/api/uploads", {
      method: "POST", body: form, signal: view.signal,
    });
    if (view.epoch !== state.viewEpoch) throw staleAuthError();
    state.upload = upload;
    state.jobSubmission = null;
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
  const fingerprint = JSON.stringify({
    principal: state.principalMarker,
    uploadId: state.upload.id,
    pageIndex: state.uploadPage,
    crop: state.crop,
  });
  if (state.jobSubmission?.fingerprint !== fingerprint) {
    state.jobSubmission = { fingerprint, key: crypto.randomUUID() };
  }
  const submission = state.jobSubmission;
  try {
    const job = await api("/api/jobs", {
      method: "POST",
      headers: { "Idempotency-Key": submission.key },
      body: { upload_id: state.upload.id, page_index: state.uploadPage, crop: state.crop },
    });
    if (state.jobSubmission === submission) state.jobSubmission = null;
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
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: { upload_id: upload.id, page_index: 0, crop: null },
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
  const view = beginViewSelection();
  try {
    if (state.currentJob?.id !== jobId) state.pollDelay = 1500;
    const previousStatus = state.currentJob?.id === jobId ? state.currentJob.status : null;
    const job = await api(`/api/jobs/${routeSegment(jobId)}`, { signal: view.signal });
    if (view.epoch !== state.viewEpoch) throw staleAuthError();
    state.currentJob = job;
    if (previousStatus && previousStatus !== state.currentJob.status) {
      state.pollDelay = 1500;
      await Promise.all([loadJobs(), refreshAccount()]);
      if (view.epoch !== state.viewEpoch) throw staleAuthError();
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
  const viewEpoch = state.viewEpoch;
  const signal = state.viewController.signal;
  try {
    const updated = await api(`/api/jobs/${routeSegment(job.id)}/${routeSegment(action)}`, {
      method: "POST", signal,
    });
    if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== job.id) throw staleAuthError();
    state.currentJob = updated;
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
  const viewEpoch = state.viewEpoch;
  try {
    const deletion = await api(`/api/jobs/${routeSegment(job.id)}`, {
      method: "DELETE", signal: state.viewController.signal,
    });
    if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== job.id) throw staleAuthError();
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
  return series.flatMap((item, seriesIndex) => (item.points || []).map((point) => ({
    seriesIndex,
    x: String(point.x),
    xType: typeof point.x === "number" ? "number" : "string",
    y: String(point.y),
  })));
}

function collectSeriesNames() {
  for (const input of byId("series-editor-list").querySelectorAll("[data-series-name]")) {
    state.editorSeries[Number(input.dataset.seriesName)].name = input.value.trim() || null;
  }
}

function renderSeriesEditor() {
  const list = byId("series-editor-list");
  list.replaceChildren(...state.editorSeries.map((series, index) => {
    const label = document.createElement("label");
    label.textContent = `Series ${index + 1}`;
    const input = document.createElement("input");
    input.value = series.name || "";
    input.placeholder = state.editorSeries.length === 1 ? "Value" : `Series ${index + 1}`;
    input.dataset.seriesName = String(index);
    input.maxLength = 500;
    label.append(input);
    return label;
  }));
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
  state.editorSeries = (result.series?.length ? result.series : [{ name: null }]).map(
    (series) => ({ name: series.name || null }),
  );
  state.editorPage = 0;
  renderSeriesEditor();
  renderResultTable();
}

function renderResultTable() {
  const table = byId("result-table");
  table.replaceChildren();
  const head = document.createElement("thead");
  const heading = document.createElement("tr");
  for (const title of ["Series", "Category / x", "Value", "Row"]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = title;
    if (title === "Row") th.className = "row-action";
    heading.append(th);
  }
  head.append(heading);
  const body = document.createElement("tbody");
  const start = state.editorPage * EDITOR_PAGE_SIZE;
  const pageRows = state.editorRows.slice(start, start + EDITOR_PAGE_SIZE);
  pageRows.forEach((item, pageIndex) => {
    const rowIndex = start + pageIndex;
    const tr = document.createElement("tr");
    const seriesCell = document.createElement("td");
    const seriesInput = document.createElement("input");
    seriesInput.type = "number";
    seriesInput.min = "1";
    seriesInput.max = String(state.editorSeries.length);
    seriesInput.value = String(item.seriesIndex + 1);
    seriesInput.dataset.row = String(rowIndex);
    seriesInput.dataset.kind = "series";
    seriesInput.setAttribute("aria-label", `Row ${rowIndex + 1} series number`);
    seriesCell.append(seriesInput);
    tr.append(seriesCell);
    const xCell = document.createElement("td");
    const xInput = document.createElement("input");
    xInput.value = item.x;
    xInput.dataset.xType = item.xType || "string";
    xInput.dataset.row = String(rowIndex);
    xInput.dataset.kind = "x";
    xInput.setAttribute("aria-label", `Row ${rowIndex + 1} category`);
    xCell.append(xInput);
    tr.append(xCell);
    const valueCell = document.createElement("td");
    const valueInput = document.createElement("input");
    valueInput.type = "number";
    valueInput.step = "any";
    valueInput.value = item.y;
    valueInput.dataset.row = String(rowIndex);
    valueInput.dataset.kind = "value";
    valueInput.setAttribute("aria-label", `Row ${rowIndex + 1} value`);
    valueCell.append(valueInput);
    tr.append(valueCell);
    const removeCell = document.createElement("td");
    removeCell.className = "row-action";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      collectEditorRows();
      state.editorRows.splice(rowIndex, 1);
      const pageCount = Math.max(1, Math.ceil(state.editorRows.length / EDITOR_PAGE_SIZE));
      state.editorPage = Math.min(state.editorPage, pageCount - 1);
      renderResultTable();
    });
    removeCell.append(remove);
    tr.append(removeCell);
    body.append(tr);
  });
  table.append(head, body);
  const mountedCells = heading.cells.length
    + (body.rows.length * heading.cells.length)
    + state.editorSeries.length
    + 5;
  if (mountedCells > EDITOR_MOUNTED_CELL_LIMIT) {
    throw new Error("Editor mounted-cell safety limit exceeded");
  }
  const pageCount = Math.max(1, Math.ceil(state.editorRows.length / EDITOR_PAGE_SIZE));
  byId("editor-page-summary").textContent = `${state.editorRows.length.toLocaleString()} values · page ${state.editorPage + 1} of ${pageCount}`;
  byId("editor-previous-page").disabled = state.editorPage === 0;
  byId("editor-next-page").disabled = state.editorPage >= pageCount - 1;
  byId("add-row-button").disabled = state.editorRows.length >= EDITOR_MAX_ROWS;
}

function collectEditorRows() {
  collectSeriesNames();
  const table = byId("result-table");
  if (!table.tBodies.length) return;
  for (const xInput of table.querySelectorAll('[data-kind="x"]')) {
    const rowIndex = Number(xInput.dataset.row);
    const seriesValue = Number(
      table.querySelector(`[data-kind="series"][data-row="${rowIndex}"]`)?.value,
    );
    state.editorRows[rowIndex] = {
      seriesIndex: Math.max(0, Math.min(state.editorSeries.length - 1, seriesValue - 1)),
      x: xInput.value,
      xType: xInput.dataset.xType || "string",
      y: table.querySelector(`[data-kind="value"][data-row="${rowIndex}"]`)?.value || "",
    };
  }
}

function changeEditorPage(delta) {
  collectEditorRows();
  const pageCount = Math.max(1, Math.ceil(state.editorRows.length / EDITOR_PAGE_SIZE));
  state.editorPage = Math.max(0, Math.min(pageCount - 1, state.editorPage + delta));
  renderResultTable();
}

function addEditorRow() {
  collectEditorRows();
  if (state.editorRows.length >= EDITOR_MAX_ROWS) {
    showToast("This result already contains the maximum 10,000 values");
    return;
  }
  state.editorRows.push({ seriesIndex: 0, x: "", xType: "string", y: "" });
  state.editorPage = Math.floor((state.editorRows.length - 1) / EDITOR_PAGE_SIZE);
  renderResultTable();
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
  const series = state.editorSeries.map((item, seriesIndex) => ({
    name: item.name,
    points: state.editorRows
      .filter((row) => row.seriesIndex === seriesIndex && row.x.trim() && row.y !== "")
      .map((row) => ({ x: coerceX(row.x, row.xType), y: Number(row.y) })),
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
  const jobId = state.currentJob?.id;
  const viewEpoch = state.viewEpoch;
  if (!jobId) return;
  try {
    const result = buildEditedResult();
    const updated = await api(`/api/jobs/${routeSegment(jobId)}/result`, {
      method: "PATCH", body: { result }, signal: state.viewController.signal,
    });
    if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== jobId) throw staleAuthError();
    state.currentJob = updated;
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
    const viewEpoch = state.viewEpoch;
    const signal = state.viewController.signal;
    const items = [];
    const rollups = [];
    let cursor = null;
    do {
      const query = cursor ? `?cursor=${encodeURIComponent(cursor)}&limit=100` : "?limit=100";
      const payload = await api(`/api/jobs/${routeSegment(jobId)}/audit${query}`, { signal });
      if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== jobId) {
        throw staleAuthError();
      }
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
  const jobId = state.currentJob?.id;
  const viewEpoch = state.viewEpoch;
  if (!jobId) return;
  try {
    const saved = await api(
      `/api/jobs/${routeSegment(jobId)}/versions/${routeSegment(version.version)}`,
      { signal: state.viewController.signal },
    );
    const updated = await api(`/api/jobs/${routeSegment(jobId)}/result`, {
      method: "PATCH", body: { result: saved.result }, signal: state.viewController.signal,
    });
    if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== jobId) throw staleAuthError();
    state.currentJob = updated;
    await loadJobs();
    renderJob();
    showToast(`Version ${version.version} restored as a new correction`);
  } catch (error) {
    showToast(error);
  }
}

async function loadVersions(before = null, append = false) {
  const list = byId("version-list");
  const jobId = state.currentJob?.id;
  const viewEpoch = state.viewEpoch;
  if (!jobId) throw staleAuthError();
  const query = before === null ? "" : `?before=${encodeURIComponent(before)}`;
  const payload = await api(`/api/jobs/${routeSegment(jobId)}/versions${query}`, {
    signal: state.viewController.signal,
  });
  if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== jobId) throw staleAuthError();
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
  clearApiKeySecret();
  byId("generate-key-button").hidden = false;
  byId("api-key-dialog").showModal();
  byId("api-key-name").focus();
  await loadApiKeys();
}

async function loadApiKeys() {
  const list = byId("api-key-list");
  const authEpoch = state.authEpoch;
  try {
    const keys = [];
    let cursor = null;
    do {
      const query = cursor ? `?cursor=${encodeURIComponent(cursor)}&limit=100` : "?limit=100";
      const payload = await api(`/api/keys${query}`, { authEpoch });
      if (authEpoch !== state.authEpoch) throw staleAuthError();
      keys.push(...payload.items);
      cursor = payload.next_cursor;
    } while (cursor);
    if (authEpoch !== state.authEpoch) throw staleAuthError();
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
    byId("copy-key-button").hidden = false;
    byId("dismiss-key-button").hidden = false;
    byId("generate-key-button").hidden = true;
    state.keySecretTimer = window.setTimeout(clearApiKeySecret, 30000);
    await loadApiKeys();
  } catch (error) {
    showToast(error);
  }
}

async function copyApiKeySecret() {
  const secret = byId("api-key-output").textContent;
  if (!secret) return;
  try {
    await navigator.clipboard.writeText(secret);
    showToast("API key copied; the on-screen copy was cleared");
  } catch (_) {
    showToast("Clipboard access failed; the on-screen key was still cleared");
  } finally {
    clearApiKeySecret();
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
  byId("editor-previous-page").addEventListener("click", () => changeEditorPage(-1));
  byId("editor-next-page").addEventListener("click", () => changeEditorPage(1));
  byId("toggle-versions-button").addEventListener("click", toggleVersions);
  byId("toggle-audit-button").addEventListener("click", toggleAudit);
  byId("create-key-button").addEventListener("click", openKeyDialog);
  byId("close-key-dialog").addEventListener("click", () => {
    clearApiKeySecret();
    byId("api-key-dialog").close();
  });
  byId("copy-key-button").addEventListener("click", copyApiKeySecret);
  byId("dismiss-key-button").addEventListener("click", clearApiKeySecret);
  byId("api-key-dialog").addEventListener("cancel", clearApiKeySecret);
  byId("api-key-dialog").addEventListener("close", clearApiKeySecret);
  byId("revoke-all-keys-button").addEventListener("click", revokeAllApiKeys);
  byId("api-key-form").addEventListener("submit", createKey);
  byId("buy-credits-button").addEventListener("click", buyCredits);
}

bindEvents();
boot();
