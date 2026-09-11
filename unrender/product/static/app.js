const state = {
  account: null,
  googleCompletionPending: false,
  jobs: [],
  jobsInitialized: false,
  jobsRequest: 0,
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
  editorDirty: false,
  authEpoch: 0,
  authController: new AbortController(),
  principalMarker: null,
  viewEpoch: 0,
  viewController: new AbortController(),
  jobSubmission: null,
  jobSubmissionPending: false,
  keySecretTimer: null,
  keyDialogEpoch: 0,
  keyController: new AbortController(),
  keyListEpoch: 0,
  keyCreatePending: false,
  authChannel: null,
  legacyAuthChannel: null,
  authRecord: null,
  logoutStatus: "idle",
  logoutRequest: null,
  logoutCsrf: "",
  suppressPrincipalReconcileUntil: 0,
  objectUrls: new Set(),
  publicConfig: { registration_open: false, sample_available: false },
};

const AUTH_EVENT_KEY = "unrender.auth-state.v2";
const LEGACY_AUTH_EVENT_KEY = "unrender.auth-change.v1";
const AUTH_LOCK_NAME = "unrender.auth-state.v2.lock";
const JOB_SUBMISSION_KEY = "unrender.job-submission.v1";
const AUTH_PHASES = new Set([
  "authenticated", "logout-pending", "logout-failed", "signed-out", "signed-out-unconfirmed",
]);
const EDITOR_PAGE_SIZE = 40;
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
  const authRecord = options.authRecord ?? readDurableAuthRecord();
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
  delete requestOptions.authRecord;
  delete requestOptions.timeoutMs;
  delete requestOptions.responseType;
  const parentSignal = requestOptions.signal || state.authController.signal;
  const timed = options.timeoutMs ? new AbortController() : null;
  const cancel = () => timed?.abort();
  if (timed) parentSignal.addEventListener("abort", cancel, { once: true });
  if (parentSignal.aborted) cancel();
  let expired = false;
  const timer = timed ? window.setTimeout(() => { expired = true; timed.abort(); }, options.timeoutMs) : null;
  let response;
  let payload;
  try {
    response = await fetch(path, {
      ...requestOptions,
      method,
      headers,
      body,
      signal: timed?.signal || parentSignal,
    });
    if (!authContextMatches(epoch, authRecord)) throw staleAuthError();
    const contentType = response.headers.get("content-type") || "";
    payload = contentType.includes("application/json") ? await response.json()
      : options.responseType === "blob" && response.ok ? await response.blob() : null;
  } catch (error) {
    if (!authContextMatches(epoch, authRecord) || parentSignal.aborted) {
      throw staleAuthError();
    }
    if (expired) {
      const timeout = new Error(method === "GET" ? "The request timed out. Please try again." : "We could not confirm whether this change completed. Close this dialog and refresh your workspace before retrying.");
      timeout.code = "request_timeout";
      timeout.uncertainMutation = method !== "GET";
      throw timeout;
    }
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) error.uncertainMutation = true;
    throw error;
  } finally {
    if (timer !== null) window.clearTimeout(timer);
    if (timed) parentSignal.removeEventListener("abort", cancel);
  }
  if (!authContextMatches(epoch, authRecord)) {
    throw staleAuthError("A previous account response was discarded");
  }
  if (!response.ok) {
    const message = payload?.error?.message || `Request failed (${response.status})`;
    const error = new Error(message);
    error.code = payload?.error?.code || "request_failed";
    error.status = response.status;
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      const hadPrincipal = Boolean(state.principalMarker);
      // A fresh anonymous session check must not erase the sign-in form.
      if (!hadPrincipal && authRecord === null) throw error;
      quarantineAuth("signed-out", { clearCsrf: true });
      if (hadPrincipal) void publishAuthChange("session-ended");
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
  setHidden("workspace-loading", true);
  const preview = byId("upload-preview");
  preview.onload = null;
  preview.onerror = null;
  preview.removeAttribute("aria-busy");
  for (const [id, label] of [["toggle-audit-button", "Show activity"], ["toggle-versions-button", "Show versions"]]) {
    const button = byId(id);
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = label;
  }
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

function invalidateApiKeyDialog() {
  state.keyController.abort();
  state.keyController = new AbortController();
  state.keyDialogEpoch += 1;
  state.keyListEpoch += 1;
  state.keyCreatePending = false;
  clearApiKeySecret();
}

function parseAuthRecord(raw) {
  try {
    const value = JSON.parse(raw);
    if (value?.version !== 2 || !AUTH_PHASES.has(value.phase)) return null;
    if (!Number.isSafeInteger(value.revision) || value.revision < 1) return null;
    if (typeof value.id !== "string" || !value.id || value.id.length > 160) return null;
    if (value.phase === "authenticated"
      && (typeof value.principalMarker !== "string" || !value.principalMarker)) return null;
    return {
      version: 2,
      revision: value.revision,
      id: value.id,
      phase: value.phase,
      principalMarker: value.phase === "authenticated" ? value.principalMarker : null,
    };
  } catch (_) {
    return null;
  }
}

function readDurableAuthRecord() {
  try { return parseAuthRecord(localStorage.getItem?.(AUTH_EVENT_KEY)); }
  catch (_) { return null; }
}

function hasLegacyLogoutBarrier() {
  try {
    const value = JSON.parse(localStorage.getItem?.(LEGACY_AUTH_EVENT_KEY));
    return value?.reason === "logout" || value?.reason === "session-ended";
  } catch (_) {
    return false;
  }
}

function promotedLegacyBarrier(current) {
  if (state.authRecord && state.authRecord.phase !== "authenticated") {
    return state.authRecord;
  }
  return {
    version: 2,
    revision: (current?.revision || 0) + 1,
    id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
    phase: "logout-failed",
    principalMarker: null,
  };
}

function migrateLegacyAuthBarrier() {
  const current = readDurableAuthRecord();
  if (!hasLegacyLogoutBarrier() || (current && current.phase !== "authenticated")) {
    return current;
  }
  // localStorage replaces one value atomically. Publishing this fail-closed
  // record synchronously prevents boot, BFCache, focus, or a mixed-version tab
  // from consulting /api/me between observing the legacy barrier and persisting
  // its v2 replacement.
  const promoted = promotedLegacyBarrier(current);
  try { localStorage.setItem(AUTH_EVENT_KEY, JSON.stringify(promoted)); }
  catch (_) { return promoted; }
  const stored = readDurableAuthRecord();
  // A quota/security failure may throw, while hardened or mocked storage can
  // silently ignore a write. In either case, an observed legacy logout is a
  // stronger privacy signal than an older authenticated v2 record.
  if (!stored || stored.phase === "authenticated") return promoted;
  return stored;
}

function retireLegacyAuthBarrier() {
  try { localStorage.removeItem?.(LEGACY_AUTH_EVENT_KEY); }
  catch (_) { return false; }
  return !hasLegacyLogoutBarrier();
}

function legacyAuthReason(event) {
  const raw = typeof event === "string" ? event : event?.data ?? event?.newValue;
  try { return JSON.parse(raw)?.reason || "unknown"; }
  catch (_) { return "unknown"; }
}

function encodeLegacyAuthWake(reason) {
  return JSON.stringify({
    reason,
    nonce: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
  });
}

function emitLegacyAuthWake(reason) {
  state.legacyAuthChannel?.postMessage(encodeLegacyAuthWake(reason));
}

function persistLegacyAuthBarrier(reason) {
  const encoded = encodeLegacyAuthWake(reason);
  // Deployed v1's storage listener discarded event.newValue and treated the
  // wake as authenticated. Never mutate this key until the server has proved
  // the old cookie unusable; an arbitrarily delayed storage task can then only
  // reconcile to 401. The barrier remains for suspended/reloaded v1 tabs until
  // a later explicit login has installed a new cookie and retires it.
  try { localStorage.setItem(LEGACY_AUTH_EVENT_KEY, encoded); }
  catch (_) { return false; }
  return hasLegacyLogoutBarrier();
}

function sameAuthRecord(left, right) {
  if (!left || !right) return left === right;
  return left.revision === right.revision && left.id === right.id && left.phase === right.phase;
}

function authContextMatches(epoch, record) {
  return epoch === state.authEpoch && sameAuthRecord(record, readDurableAuthRecord());
}

function blocksPrincipalRestore(record) {
  return state.logoutStatus !== "idle" || Boolean(record && record.phase !== "authenticated");
}

function blocksExplicitLogin(record) {
  return ["pending", "failed"].includes(state.logoutStatus)
    || Boolean(record && ["logout-pending", "logout-failed"].includes(record.phase));
}

function updateLogoutGate() {
  const record = state.authRecord;
  const failed = record?.phase === "logout-failed" || state.logoutStatus === "failed";
  const pending = record?.phase === "logout-pending" || state.logoutStatus === "pending";
  const unconfirmed = record?.phase === "signed-out-unconfirmed"
    || state.logoutStatus === "unconfirmed";
  const retryable = failed || unconfirmed || (pending && !state.logoutRequest);
  byId("logout-retry-panel").hidden = !retryable;
  if (pending && retryable) {
    byId("logout-status").textContent = "Account-wide sign-out was interrupted before confirmation.";
  }
  if (unconfirmed) {
    byId("logout-status").textContent = "This browser is signed out, but account-wide revocation was not confirmed. Retry or sign in to continue.";
  }
  byId("retry-logout-button").disabled = Boolean(state.logoutRequest);
  for (const formId of ["login-form", "register-form"]) {
    const controls = byId(formId).querySelectorAll?.("input,button") || [];
    for (const control of controls) control.disabled = pending || failed;
  }
  byId("open-sample-button").disabled = pending || failed;
  updateGoogleLoginGate();
}

function applyAuthRecord(record, { wipe = true } = {}) {
  if (!record) {
    // Missing or malformed durable data is never permission to clear an
    // already-observed logout quarantine.
    updateLogoutGate();
    return state.authRecord;
  }
  if (sameAuthRecord(record, state.authRecord)) {
    updateLogoutGate();
    return record;
  }
  state.authRecord = record;
  if (record.phase !== "authenticated") {
    state.suppressPrincipalReconcileUntil = Number.POSITIVE_INFINITY;
    state.logoutStatus = record.phase === "logout-failed"
      ? "failed" : record.phase === "logout-pending"
        ? "pending" : record.phase === "signed-out-unconfirmed" ? "unconfirmed" : "confirmed";
    if (wipe) showPublic({ clearCsrf: record.phase === "signed-out", clearSubmission: true });
  } else {
    state.suppressPrincipalReconcileUntil = 0;
    state.logoutStatus = "idle";
    if (wipe) {
      const submission = readDurableJobSubmission();
      showPublic({
        clearCsrf: false,
        clearSubmission: Boolean(
          submission && submission.principalMarker !== record.principalMarker
        ),
      });
    }
  }
  updateLogoutGate();
  return record;
}

function syncAuthRecordFromStorage(options = {}) {
  const durable = migrateLegacyAuthBarrier() || readDurableAuthRecord();
  if (!durable && blocksPrincipalRestore(state.authRecord)) {
    updateLogoutGate();
    return state.authRecord;
  }
  return applyAuthRecord(durable, options);
}

async function withAuthMutationLock(callback) {
  if (globalThis.navigator?.locks?.request) {
    return globalThis.navigator.locks.request(AUTH_LOCK_NAME, { mode: "exclusive" }, callback);
  }
  return callback();
}

async function writeAuthRecord(phase, { expected = undefined, principalMarker = null } = {}) {
  return withAuthMutationLock(async () => {
    const current = readDurableAuthRecord();
    if (expected !== undefined && !sameAuthRecord(current, expected)) return null;
    if (phase === "authenticated" && !retireLegacyAuthBarrier()) {
      throw new Error("This browser could not retire its previous account privacy barrier");
    }
    const record = {
      version: 2,
      revision: Math.max(current?.revision || 0, state.authRecord?.revision || 0) + 1,
      id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
      phase,
      principalMarker: phase === "authenticated" ? principalMarker : null,
    };
    const encoded = JSON.stringify(record);
    localStorage.setItem(AUTH_EVENT_KEY, encoded);
    const stored = readDurableAuthRecord();
    if (!sameAuthRecord(stored, record)) {
      throw new Error("This browser could not persist the account privacy barrier");
    }
    state.authChannel?.postMessage(encoded);
    return applyAuthRecord(record, { wipe: false });
  });
}

async function publishAuthChange(reason, options = {}) {
  if (reason === "authenticated") {
    if (!options.explicitLogin || !options.principalMarker) return null;
    if (blocksExplicitLogin(options.expected)) return null;
    const authenticated = await writeAuthRecord("authenticated", {
      expected: options.expected,
      principalMarker: options.principalMarker,
    });
    if (authenticated) emitLegacyAuthWake("authenticated");
    return authenticated;
  }
  const phase = reason === "logout" ? "logout-pending" : "signed-out";
  const changed = await writeAuthRecord(phase, { expected: options.expected });
  if (changed) {
    const legacyReason = reason === "logout" ? "logout" : "session-ended";
    // While logout is merely pending, BroadcastChannel is the only safe wake
    // for a deployed v1 tab. Session-ended is reached from an authoritative
    // 401, so its durable legacy barrier is safe to publish immediately.
    if (reason !== "logout") persistLegacyAuthBarrier(legacyReason);
    emitLegacyAuthWake(legacyReason);
  }
  return changed;
}

function quarantineAuth(phase, { clearCsrf = false } = {}) {
  state.suppressPrincipalReconcileUntil = Number.POSITIVE_INFINITY;
  state.logoutStatus = phase === "logout-failed"
    ? "failed" : phase === "signed-out" ? "confirmed" : "pending";
  showPublic({ clearCsrf });
  updateLogoutGate();
}

function parseJobSubmission(raw) {
  try {
    const value = JSON.parse(raw);
    if (value?.version !== 1 || typeof value.principalMarker !== "string") return null;
    if (typeof value.fingerprint !== "string" || typeof value.key !== "string") return null;
    if (!value.body || typeof value.body.upload_id !== "string") return null;
    if (!Number.isSafeInteger(value.body.page_index) || value.body.page_index < 0) return null;
    if (!Number.isFinite(value.createdAt) || Date.now() - value.createdAt > 30 * 86400000) {
      return null;
    }
    if (value.phase !== "prepared" && value.phase !== "accepted") return null;
    if (value.phase === "accepted" && typeof value.jobId !== "string") return null;
    return value;
  } catch (_) {
    return null;
  }
}

function readDurableJobSubmission() {
  try { return parseJobSubmission(localStorage.getItem?.(JOB_SUBMISSION_KEY)); }
  catch (_) { return null; }
}

function persistJobSubmission(submission) {
  const encoded = JSON.stringify(submission);
  localStorage.setItem(JOB_SUBMISSION_KEY, encoded);
  const stored = readDurableJobSubmission();
  if (!stored || stored.key !== submission.key || stored.fingerprint !== submission.fingerprint
    || stored.phase !== submission.phase || stored.jobId !== submission.jobId) {
    throw new Error("This browser could not durably save the extraction request key");
  }
  state.jobSubmission = stored;
  return stored;
}

function clearDurableJobSubmission(expected = null) {
  const current = readDurableJobSubmission();
  if (expected && current?.key !== expected.key) return;
  try { localStorage.removeItem?.(JOB_SUBMISSION_KEY); } catch (_) { /* fail closed below */ }
  state.jobSubmission = null;
}

async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function recoverDurableJobSubmission() {
  if (state.jobSubmissionPending || !state.principalMarker) return false;
  let submission = readDurableJobSubmission();
  if (!submission) return false;
  if (submission.principalMarker !== state.principalMarker) {
    clearDurableJobSubmission(submission);
    return false;
  }
  const epoch = state.authEpoch;
  state.jobSubmission = submission;
  state.jobSubmissionPending = true;
  try {
    let jobId = submission.jobId;
    if (submission.phase !== "accepted") {
      const job = await api("/api/jobs", {
        method: "POST",
        headers: { "Idempotency-Key": submission.key },
        body: submission.body,
      });
      jobId = job.id;
      submission = persistJobSubmission({
        ...submission,
        phase: "accepted",
        jobId,
      });
      await refreshAccount();
      await loadJobs();
    }
    if (epoch !== state.authEpoch || state.principalMarker !== submission.principalMarker) {
      throw staleAuthError();
    }
    if (!state.jobs.some((job) => job.id === jobId)) await loadJobs();
    if (!state.jobs.some((job) => job.id === jobId)) return false;
    await openJob(jobId, { throwOnError: true });
    if (state.currentJob?.id !== jobId) throw staleAuthError();
    clearDurableJobSubmission(submission);
    return true;
  } catch (error) {
    showToast(error);
    return false;
  } finally {
    state.jobSubmissionPending = false;
  }
}

function resetPrivateState({ clearCsrf = true, clearSubmission = true } = {}) {
  stopPolling();
  resetViewSelection();
  window.clearTimeout(showToast.timer);
  invalidateApiKeyDialog();
  state.authController.abort();
  state.authController = new AbortController();
  state.authEpoch += 1;
  for (const url of state.objectUrls) URL.revokeObjectURL(url);
  state.objectUrls.clear();
  if (clearCsrf) document.cookie = "unrender_csrf=; Max-Age=0; Path=/; SameSite=Lax";
  state.account = null;
  state.jobs = [];
  resetLibrary();
  resetSettings();
  state.jobsInitialized = false;
  clearSelectedChart();
  state.upload = null;
  state.uploadPage = 0;
  state.crop = null;
  state.cropStart = null;
  if (clearSubmission) clearDurableJobSubmission();
  state.jobSubmissionPending = false;
  state.principalMarker = null;
  state.pollDelay = 1500;
  byId("job-list").replaceChildren();
  byId("api-key-list").replaceChildren();
  byId("api-key-form").reset();
  byId("login-form").reset();
  byId("register-form").reset();
  byId("generate-key-button").hidden = false;
  byId("generate-key-button").disabled = false;
  if (byId("api-key-dialog").open) byId("api-key-dialog").close();
  for (const id of [
    "page-counter", "credit-count", "account-email", "result-loading",
    "editor-page-summary",
  ]) {
    byId(id).textContent = "";
  }
  byId("upload-preview").removeAttribute("src");
  byId("file-input").value = "";
  byId("dropzone").removeAttribute("aria-busy");
  byId("file-input").disabled = false;
  for (const id of ["open-sample-button", "run-sample-button", "queue-job-button", "buy-credits-button"]) {
    byId(id).disabled = false;
  }
  byId("run-sample-button").textContent = "Use the saved example";
  byId("run-sample-button").removeAttribute("aria-busy");
  for (const [id, value] of [
    ["crop-left-input", 0], ["crop-top-input", 0],
    ["crop-width-input", 100], ["crop-height-input", 100],
  ]) byId(id).value = String(value);
  byId("crop-selection").hidden = true;
  byId("crop-selection").removeAttribute("style");
  byId("result-loading").hidden = true;
  byId("toggle-audit-button").textContent = "Show activity";
  byId("toggle-versions-button").textContent = "Show versions";
  byId("toast").textContent = "";
  byId("toast").hidden = true;
  for (const id of ["auth-error", "upload-error", "job-error"]) {
    byId(id).textContent = "";
    byId(id).hidden = true;
  }
  setHidden("page-review", true);
}

function routeTo(path) {
  if (window.location?.pathname !== path) window.history?.replaceState(null, "", path);
}

function showPublic({ clearCsrf = true, clearSubmission = true } = {}) {
  resetPrivateState({ clearCsrf, clearSubmission });
  setHidden("boot-notice", true);
  setHidden("marketing-view", false);
  setHidden("workspace-view", true);
  setHidden("account-bar", true);
  setHidden("public-nav", false);
  setHidden("product-nav", true);
  byId("home-button").href = "/";
  byId("home-button").setAttribute("aria-label", "Unrender home");
  switchAuth(window.location?.pathname === "/signup" ? "register" : "login", { focus: false });
  updateLogoutGate();
}

function applyPublicConfig() {
  const config = state.publicConfig;
  if (config.max_upload_bytes && config.max_image_pixels && config.max_pdf_pages) {
    byId("upload-limits").textContent = `PNG, JPEG, WebP, or PDF up to ${config.max_upload_bytes / (1024 * 1024)} MB · Images up to ${config.max_image_pixels / 1000000} MP · PDFs up to ${config.max_pdf_pages} pages`;
  }
  for (const id of ["google-signin", "google-signup", "google-signin-divider", "google-signup-divider"]) byId(id).hidden = !config.google_available;
  updateGoogleLoginGate();
  const registrationOpen = state.publicConfig.registration_open;
  byId("account-help-links").hidden = false;
  byId("resend-verification-link").hidden = !state.publicConfig.email_available;
  byId("register-tab").hidden = !registrationOpen;
  byId("open-sample-button").hidden = !state.publicConfig.sample_available;
  const initialCredits = config.initial_credits;
  byId("signup-access-note").textContent = Number.isInteger(initialCredits) && initialCredits > 0
    ? `Your workspace starts with ${initialCredits} extraction credit${initialCredits === 1 ? "" : "s"}. Each extraction attempt uses one credit.`
    : "Starts with 0 extraction credits. Upload access is granted separately during the beta.";
  byId("signup-recovery-note").hidden = Boolean(config.email_available);
  if (!state.account) switchAuth(window.location?.pathname === "/signup" ? "register" : "login", { focus: false });
}

function showWorkspace() {
  setHidden("boot-notice", true);
  routeTo("/app");
  document.title = "Workspace — Unrender";
  setHidden("marketing-view", true);
  setHidden("workspace-view", false);
  setHidden("account-bar", false);
  setHidden("public-nav", true);
  setHidden("product-nav", false);
  byId("home-button").href = "/app";
  byId("home-button").setAttribute("aria-label", "Unrender dashboard");
  byId("settings-button").textContent = state.account.email?.slice(0, 2).toUpperCase() || "U";
  const isolatedDemo = state.account.demo_account;
  byId("run-sample-button").hidden = !state.account.demo_mode;
  byId("account-email").textContent = isolatedDemo ? "Ephemeral sample" : state.account.email;
  byId("credit-count").textContent = isolatedDemo
    ? "Isolated demo"
    : `${state.account.credits} credit${state.account.credits === 1 ? "" : "s"}`;
  const buyButton = byId("buy-credits-button");
  buyButton.hidden = isolatedDemo || !state.account.billing_configured;
  buyButton.textContent = `Buy ${state.account.credit_pack_size} credits`;
  byId("new-upload-button").hidden = isolatedDemo;
  byId("empty-upload-button").hidden = isolatedDemo;
  const needsCredits = !isolatedDemo && state.account.credits <= 0;
  byId("new-upload-button").disabled = needsCredits;
  byId("empty-upload-button").disabled = needsCredits;
  byId("export-another-button").disabled = isolatedDemo || needsCredits;
  byId("workspace-access-notice").hidden = !needsCredits;
  byId("workspace-example-link").hidden = true;
  byId("workspace-access-link").hidden = !needsCredits || state.account.billing_configured;
  byId("create-key-button").hidden = isolatedDemo;
  const accessNote = byId("workspace-access-note");
  accessNote.hidden = !needsCredits;
  accessNote.textContent = state.account.billing_configured
    ? "Add extraction credits to upload a chart. Your existing charts remain available for review and export."
    : "Your workspace is ready. You’ll need extraction credits before you can upload. During the beta, credits are granted separately by the Unrender team. Your existing charts remain available for review and export.";
  byId("retention-note").textContent = isolatedDemo ? "" : `Charts are retained for ${state.account.retention_days} days after their last update. Download exports you need to keep.`;
}

function showMainView(name) {
  if (name === "empty-view") name = "library-view";
  for (const view of ["library-view", "projects-view", "empty-view", "upload-view", "job-view"]) setHidden(view, view !== name);
  byId("empty-view").hidden = name !== "library-view" || state.jobs.length > 0;
  byId("library-button").setAttribute("aria-current", name === "projects-view" ? "false" : "page");
  byId("projects-button").setAttribute("aria-current", name === "projects-view" ? "page" : "false");
  if (document.body.dataset.view !== name) window.scrollTo?.({ top: 0, behavior: "instant" });
  document.body.dataset.view = name;
  setLibraryPreviewsActive(name === "library-view");
  if (name === "library-view") renderLibrary();
}

async function fetchAccount(options = {}) {
  return api("/api/me", options);
}

function applyAccount(account) {
  const durable = readDurableAuthRecord();
  if (durable?.phase === "authenticated"
    && durable.principalMarker !== account.principal_marker) {
    quarantineAuth("signed-out", { clearCsrf: false });
    throw staleAuthError("The account changed before the response could be shown");
  }
  if (state.principalMarker && state.principalMarker !== account.principal_marker) {
    resetPrivateState({ clearCsrf: false });
  }
  state.principalMarker = account.principal_marker;
  state.account = account;
  showWorkspace();
  return account;
}

async function refreshAccount(options = {}) {
  return applyAccount(await fetchAccount(options));
}

async function reconcilePrincipal() {
  if (state.googleCompletionPending) return;
  const canonical = syncAuthRecordFromStorage({ wipe: true });
  if (blocksPrincipalRestore(canonical)) return;
  const authEpoch = state.authEpoch;
  try {
    const previous = state.principalMarker;
    const account = await fetchAccount({ authEpoch, authRecord: canonical });
    if (!authContextMatches(authEpoch, canonical)) throw staleAuthError();
    let authenticated = canonical;
    if (!authenticated) {
      authenticated = await publishAuthChange("authenticated", {
        explicitLogin: true,
        expected: null,
        principalMarker: account.principal_marker,
      });
    }
    if (!authenticated || authenticated.principalMarker !== account.principal_marker) {
      throw staleAuthError("The authenticated principal did not match the durable browser state");
    }
    applyAccount(account);
    if (previous !== account.principal_marker || !state.jobsInitialized) {
      await Promise.all([loadJobs(), loadProjects()]);
      if (await recoverDurableJobSubmission()) return;
      if (state.upload || !byId("upload-view").hidden) return;
      showLibrary();
    }
  } catch (error) {
    if (!isStaleRequest(error) && error.status !== 401) showToast(error);
  }
}

function handleExternalAuthChange(event) {
  // Notifications are only wakeups. The canonical durable record decides what
  // may be rendered, so malformed, duplicated, or reordered events cannot lower
  // a logout barrier.
  const canonical = syncAuthRecordFromStorage({ wipe: true });
  if (["logout", "session-ended"].includes(legacyAuthReason(event))
    && (!canonical || canonical.phase === "authenticated")) {
    applyAuthRecord(promotedLegacyBarrier(canonical), { wipe: true });
    return;
  }
  if (!blocksPrincipalRestore(canonical)) void reconcilePrincipal();
}

function handleAuthLifecycleBoundary() {
  const canonical = syncAuthRecordFromStorage({ wipe: true });
  if (!blocksPrincipalRestore(canonical)) void reconcilePrincipal().then(() => refreshLibrary());
}

function installAuthCoordination() {
  syncAuthRecordFromStorage({ wipe: false });
  if (typeof BroadcastChannel === "function") {
    state.authChannel = new BroadcastChannel(AUTH_EVENT_KEY);
    state.authChannel.addEventListener("message", handleExternalAuthChange);
    state.legacyAuthChannel = new BroadcastChannel(LEGACY_AUTH_EVENT_KEY);
    state.legacyAuthChannel.addEventListener("message", handleExternalAuthChange);
  }
  window.addEventListener("storage", (event) => {
    if (event.key === AUTH_EVENT_KEY || event.key === LEGACY_AUTH_EVENT_KEY) {
      handleExternalAuthChange(event);
    }
  });
  window.addEventListener("focus", handleAuthLifecycleBoundary);
  window.addEventListener("pageshow", handleAuthLifecycleBoundary);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") handleAuthLifecycleBoundary();
  });
}

async function boot() {
  const entryPath = window.location?.pathname;
  const entryQuery = new URLSearchParams(window.location?.search || "");
  state.googleCompletionPending = true;
  installAuthCoordination();
  try {
    state.publicConfig = await api("/api/public-config");
  } catch (_) {
    state.publicConfig = { registration_open: false, sample_available: false };
  }
  applyPublicConfig();
  const googleError = googleReturnError(entryQuery.get("google"));
  let completionError = null;
  try { await completeGoogleLogin(entryPath); }
  catch (error) { completionError = error; }
  finally { state.googleCompletionPending = false; }
  if (completionError) {
    showPublic({ clearCsrf: false });
    showError("auth-error", completionError);
    return;
  }
  const canonical = syncAuthRecordFromStorage({ wipe: false });
  if (blocksPrincipalRestore(canonical)) {
    showPublic({ clearCsrf: false });
    if (googleError) showError("auth-error", googleError);
    return;
  }
  try {
    await reconcilePrincipal();
    if (!state.account) {
      showPublic({ clearCsrf: false });
      if (googleError) showError("auth-error", googleError);
    } else if (entryQuery.get("settings") === "account") {
      openSettings();
      if (googleError) showError("settings-error", googleError);
      if (entryQuery.get("connected") === "1") showToast("Google is now connected to this account.");
      if (entryQuery.get("reauthenticated") === "1") showToast("Identity verified. You can now confirm account deletion in Settings.");
    }
  } catch (error) {
    if (error.status === 401) showPublic();
    else showError("auth-error", error);
  }
}

function switchAuth(mode, { focus = true } = {}) {
  const login = mode === "login";
  const invitationOnly = !login && !state.publicConfig.registration_open;
  routeTo(login ? "/login" : "/signup");
  document.title = `${login ? "Sign in" : "Create a workspace"} — Unrender`;
  byId("login-tab").setAttribute("aria-selected", String(login));
  byId("register-tab").setAttribute("aria-selected", String(!login));
  setHidden("login-form", !login);
  setHidden("register-form", login || invitationOnly);
  setHidden("invitation-note", !invitationOnly);
  byId("auth-title").textContent = login ? "Welcome back." : invitationOnly ? "Your next chart starts here." : "Create your account.";
  byId("auth-description").textContent = login ? "Sign in to your workspace."
    : invitationOnly ? "Unrender is available by invitation during the pilot. Use the setup link from your inviter to continue."
    : "A private place for your charts and reviewed data.";
  clearError("auth-error");
  if (focus && !invitationOnly) byId(login ? "login-form" : "register-form").querySelector("input").focus();
}

async function submitAuth(event, mode) {
  event.preventDefault();
  clearError("auth-error");
  const form = event.currentTarget;
  if (form.getAttribute("aria-busy") === "true") return;
  const data = new FormData(form);
  const expected = readDurableAuthRecord();
  if (blocksExplicitLogin(expected) || state.logoutRequest) {
    showError("auth-error", new Error("Finish signing out everywhere before signing in again"));
    return;
  }
  resetPrivateState();
  const epoch = state.authEpoch;
  form.setAttribute("aria-busy", "true");
  try {
    const outcome = await api(`/api/auth/${mode}`, {
      method: "POST",
      body: { email: String(data.get("email") || "").trim(), password: data.get("password") },
      authEpoch: epoch,
      authRecord: expected,
    });
    form.reset();
    if (outcome.verification_required) {
      switchAuth("login");
      byId("auth-notice").textContent = "Check your email to verify your account, then sign in. If it does not arrive, use Resend verification email.";
      byId("auth-notice").hidden = false;
      return;
    }
    byId("auth-notice").hidden = true;
    const account = await fetchAccount({ authEpoch: epoch, authRecord: expected });
    const committed = await publishAuthChange("authenticated", {
      explicitLogin: true,
      expected,
      principalMarker: account.principal_marker,
    });
    if (!committed) throw staleAuthError("A sign-out barrier superseded this login");
    applyAccount(account);
    await Promise.all([loadJobs(), loadProjects()]);
    if (await recoverDurableJobSubmission()) return;
    showLibrary();
    showToast(mode === "register"
      ? (account.credits > 0 ? "Workspace created. Upload a chart to begin." : "Account created. Request extraction access to upload your first chart.")
      : "Signed in. Your workspace is ready.");
  } catch (error) {
    showError("auth-error", error);
  } finally {
    form.removeAttribute("aria-busy");
  }
}

async function demoLoginAndRun() {
  const button = byId("open-sample-button");
  const expected = readDurableAuthRecord();
  if (blocksExplicitLogin(expected) || state.logoutRequest) {
    showToast("Finish signing out everywhere before opening the sample");
    return;
  }
  resetPrivateState();
  const epoch = state.authEpoch;
  button.disabled = true;
  try {
    await api("/api/auth/demo", { method: "POST", authEpoch: epoch, authRecord: expected });
    const account = await fetchAccount({ authEpoch: epoch, authRecord: expected });
    const committed = await publishAuthChange("authenticated", {
      explicitLogin: true,
      expected,
      principalMarker: account.principal_marker,
    });
    if (!committed) throw staleAuthError("A sign-out barrier superseded this login");
    applyAccount(account);
    await loadJobs();
    if (await recoverDurableJobSubmission()) return;
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
  if (state.logoutRequest) return state.logoutRequest;
  state.logoutCsrf = state.logoutCsrf || csrfToken();
  const expected = readDurableAuthRecord();
  quarantineAuth("logout-pending", { clearCsrf: false });
  const operation = (async () => {
    let pending = await publishAuthChange("logout", { expected });
    if (!pending) {
      pending = syncAuthRecordFromStorage({ wipe: true });
      if (pending?.phase !== "logout-pending" && pending?.phase !== "logout-failed") {
        throw new Error("Another account transition superseded this sign-out request");
      }
      if (pending.phase === "logout-failed") {
        pending = await publishAuthChange("logout", { expected: pending });
      }
    }
    let failure = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const response = await fetch("/api/auth/logout", {
          method: "POST",
          headers: { "X-CSRF-Token": state.logoutCsrf, Accept: "application/json" },
          keepalive: true,
        });
        if (response.ok) {
          const signedOut = await writeAuthRecord("signed-out", { expected: pending });
          if (!signedOut) throw new Error("The sign-out result was superseded");
          persistLegacyAuthBarrier("logout");
          emitLegacyAuthWake("logout");
          state.logoutStatus = "confirmed";
          state.logoutCsrf = "";
          document.cookie = "unrender_csrf=; Max-Age=0; Path=/; SameSite=Lax";
          showPublic({ clearCsrf: true });
          updateLogoutGate();
          return true;
        }
        failure = new Error(`Account-wide sign-out failed (${response.status})`);
      } catch (error) {
        failure = error;
      }
    }
    try {
      const localSession = await fetch("/api/me", {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (localSession.status === 401) {
        const unconfirmed = await writeAuthRecord("signed-out-unconfirmed", {
          expected: pending,
        });
        if (unconfirmed) {
          persistLegacyAuthBarrier("logout");
          emitLegacyAuthWake("logout");
          applyAuthRecord(unconfirmed, { wipe: true });
        }
        state.logoutStatus = "unconfirmed";
        state.logoutCsrf = "";
        document.cookie = "unrender_csrf=; Max-Age=0; Path=/; SameSite=Lax";
        updateLogoutGate();
        return false;
      }
    } catch (_) {
      // Network ambiguity remains a failed global sign-out, never a success claim.
    }
    const failed = await writeAuthRecord("logout-failed", { expected: pending });
    if (failed) {
      // Re-wake live v1 tabs, but keep storage untouched because the old
      // session may still be valid after an ambiguous/non-2xx response.
      emitLegacyAuthWake("logout");
      applyAuthRecord(failed, { wipe: true });
    }
    state.logoutStatus = "failed";
    byId("logout-status").textContent = failure?.message
      || "Account-wide sign-out could not be confirmed";
    updateLogoutGate();
    return false;
  })();
  state.logoutRequest = operation;
  try {
    return await operation;
  } catch (error) {
    state.logoutStatus = "failed";
    byId("logout-status").textContent = error?.message
      || "Account-wide sign-out could not be confirmed";
    updateLogoutGate();
    return false;
  } finally {
    if (state.logoutRequest === operation) state.logoutRequest = null;
    updateLogoutGate();
  }
}

async function loadJobs() {
  const authEpoch = state.authEpoch;
  const request = ++state.jobsRequest;
  const jobs = [];
  let cursor = null;
  do {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}&limit=100` : "?limit=100";
    const payload = await api(`/api/jobs${query}`, { authEpoch, timeoutMs: 30000 });
    if (authEpoch !== state.authEpoch) throw staleAuthError();
    jobs.push(...payload.items);
    cursor = payload.next_cursor;
  } while (cursor);
  if (authEpoch !== state.authEpoch) throw staleAuthError();
  if (request !== state.jobsRequest) return;
  state.jobs = jobs;
  state.jobsInitialized = true;
  renderJobList();
}

function renderJobList() {
  if (!byId("library-view").hidden) renderLibrary();
}

function startUpload() {
  if (!state.account || state.account.demo_account || state.account.credits <= 0) return;
  if (!discardEditorChanges()) return;
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
  if (!file || byId("dropzone").getAttribute("aria-busy") === "true") return;
  const epoch = state.authEpoch;
  const view = beginViewSelection();
  clearError("upload-error");
  const form = new FormData();
  form.append("file", file);
  byId("dropzone").setAttribute("aria-busy", "true");
  byId("file-input").disabled = true;
  try {
    const upload = await api("/api/uploads", {
      method: "POST", body: form, signal: view.signal,
    });
    if (view.epoch !== state.viewEpoch) throw staleAuthError();
    state.upload = upload;
    state.uploadPage = 0;
    clearCrop();
    setHidden("page-review", false);
    updateUploadPreview();
  } catch (error) {
    showError("upload-error", error);
  } finally {
    if (epoch === state.authEpoch) {
      byId("dropzone").removeAttribute("aria-busy");
      byId("file-input").disabled = false;
      byId("file-input").value = "";
    }
  }
}

function updateUploadPreview() {
  if (!state.upload) return;
  const preview = byId("upload-preview");
  const upload = state.upload;
  const page = state.uploadPage;
  const viewEpoch = state.viewEpoch;
  const authEpoch = state.authEpoch;
  const label = `Page ${page + 1} of ${upload.page_count}`;
  const finish = (failed) => {
    if (authEpoch !== state.authEpoch || viewEpoch !== state.viewEpoch
      || state.upload !== upload || state.uploadPage !== page) return;
    preview.removeAttribute("aria-busy");
    preview.onload = null;
    preview.onerror = null;
    byId("page-counter").textContent = failed ? `${label} — preview unavailable` : label;
    if (failed) showError("upload-error", new Error("The page preview could not load. Choose the page again or upload the file again."));
  };
  clearError("upload-error");
  preview.setAttribute("aria-busy", "true");
  byId("page-counter").textContent = `Loading ${label.toLowerCase()}…`;
  preview.onload = () => finish(false);
  preview.onerror = () => finish(true);
  preview.src = `/api/uploads/${routeSegment(upload.id)}/pages/${Number(page)}`;
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
  if (!state.upload || state.jobSubmissionPending) return;
  const epoch = state.authEpoch;
  const principal = state.principalMarker;
  const button = byId("queue-job-button");
  button.disabled = true;
  clearError("upload-error");
  const body = {
    upload_id: state.upload.id,
    page_index: state.uploadPage,
    crop: state.crop,
  };
  const fingerprint = JSON.stringify({
    principal,
    uploadId: body.upload_id,
    pageIndex: body.page_index,
    crop: body.crop,
  });
  let submission = state.jobSubmission || readDurableJobSubmission();
  try {
    if (submission && (submission.principalMarker !== principal
      || submission.fingerprint !== fingerprint)) {
      throw new Error(
        "Finish recovering the previous extraction request before starting a different one"
      );
    }
    if (!submission) {
      const key = `ui:${await sha256Hex(fingerprint)}`;
      submission = persistJobSubmission({
        version: 1,
        principalMarker: principal,
        fingerprint,
        body,
        key,
        phase: "prepared",
        jobId: null,
        createdAt: Date.now(),
      });
    }
    state.jobSubmissionPending = true;
    let job;
    if (submission.phase === "accepted") {
      job = { id: submission.jobId };
    } else {
      job = await api("/api/jobs", {
        method: "POST",
        headers: { "Idempotency-Key": submission.key },
        body: submission.body,
      });
      submission = persistJobSubmission({
        ...submission,
        phase: "accepted",
        jobId: job.id,
      });
    }
    if (epoch !== state.authEpoch || state.principalMarker !== principal) throw staleAuthError();
    await refreshAccount();
    await loadJobs();
    if (!state.jobs.some((item) => item.id === job.id)) {
      throw new Error("The extraction was accepted but has not converged into the workspace yet");
    }
    await openJob(job.id, { throwOnError: true });
    if (state.currentJob?.id !== job.id) throw staleAuthError();
    clearDurableJobSubmission(submission);
  } catch (error) {
    showError("upload-error", error);
  } finally {
    state.jobSubmissionPending = false;
    if (epoch === state.authEpoch) button.disabled = false;
  }
}

async function runSample() {
  const button = byId("run-sample-button");
  if (button.disabled) return;
  const authEpoch = state.authEpoch;
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Opening saved example…";
  button.setAttribute("aria-busy", "true");
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
  } finally {
    if (authEpoch === state.authEpoch) {
      button.disabled = false;
      button.textContent = label;
      button.removeAttribute("aria-busy");
    }
  }
}

async function openJob(jobId, { throwOnError = false } = {}) {
  if (state.editorDirty && state.currentJob?.id === jobId) return state.currentJob;
  if (!discardEditorChanges()) return null;
  stopPolling();
  setLibraryPreviewsActive(false);
  const view = beginViewSelection();
  const authEpoch = state.authEpoch;
  if (state.currentJob?.id !== jobId) {
    byId("workspace-loading").textContent = "Opening chart…";
    setHidden("workspace-loading", false);
  }
  try {
    if (state.currentJob?.id !== jobId) state.pollDelay = 1500;
    const previousStatus = state.currentJob?.id === jobId ? state.currentJob.status : null;
    const job = await api(`/api/jobs/${routeSegment(jobId)}`, { signal: view.signal, timeoutMs: 30000 });
    await waitForLibraryPreview();
    if (view.epoch !== state.viewEpoch) throw staleAuthError();
    state.currentJob = job;
    state.jobs = state.jobs.map((item) => item.id === job.id ? {
      ...item, status: job.status, updated_at: job.updated_at,
      display_name: job.display_name, project_id: job.project_id,
    } : item);
    if (previousStatus && previousStatus !== state.currentJob.status) {
      state.pollDelay = 1500;
      await Promise.all([loadJobs(), refreshAccount({ timeoutMs: 30000 })]);
      if (view.epoch !== state.viewEpoch) throw staleAuthError();
    }
    else renderJobList();
    renderJob();
    showMainView("job-view");
    if (["queued", "running"].includes(state.currentJob.status)) {
      state.pollTimer = window.setTimeout(() => openJob(jobId), state.pollDelay);
      state.pollDelay = Math.min(4000, state.pollDelay + 500);
    }
    return job;
  } catch (error) {
    if (error.status === 429 && state.currentJob?.id === jobId
      && ["queued", "running"].includes(state.currentJob.status)) {
      state.pollDelay = 5000;
      state.pollTimer = window.setTimeout(() => openJob(jobId), state.pollDelay);
    } else {
      if (throwOnError) throw error;
      showToast(error);
    }
    return null;
  } finally {
    if (authEpoch === state.authEpoch && view.epoch === state.viewEpoch) {
      setHidden("workspace-loading", true);
      if (!byId("library-view").hidden) {
        setLibraryPreviewsActive(true);
        renderLibrary();
      }
    }
  }
}

function actionButton(label, kind, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `button ${kind || "button-secondary"}`;
  button.textContent = label;
  button.addEventListener("click", async (event) => {
    if (button.disabled) return;
    button.disabled = true;
    const authEpoch = state.authEpoch;
    const viewEpoch = state.viewEpoch;
    button.setAttribute("aria-busy", "true");
    try {
      await handler(event);
    } finally {
      if (authEpoch === state.authEpoch && viewEpoch === state.viewEpoch) button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  });
  return button;
}

function renderJob() {
  const job = state.currentJob;
  if (!job) return;
  byId("job-status").textContent = statusLabel(job.status);
  byId("job-title").textContent = job.status === "approved" ? "Approved data" : ["review"].includes(job.status) ? "Review data" : statusLabel(job.status);
  byId("review-filename").textContent = chartName(job);
  byId("job-meta").textContent = `${job.status === "approved" ? "Approved by you" : job.status === "review" ? "Ready for your review" : job.progress_stage} · ${formatDate(job.updated_at)}`;
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
  setHidden("export-completion", true);
  renderWorkflowSteps(job.status === "approved" ? "export" : resultReady ? "review" : "extract");
  if (resultReady) renderEditor(job.result);
  renderJobActions();
  setHidden("audit-list", true);
  setHidden("version-list", true);
  byId("toggle-audit-button").textContent = "Show activity";
  byId("toggle-versions-button").textContent = "Show versions";
}

function renderWorkflowSteps(currentStep) {
  let completed = true;
  for (const step of byId("workflow-steps").querySelectorAll("[data-step]")) {
    const current = step.dataset.step === currentStep;
    if (current) completed = false;
    step.classList.toggle("is-complete", completed);
    step.classList.toggle("is-current", current);
    if (current) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
  }
}

function renderJobActions() {
  const job = state.currentJob;
  const actions = byId("job-actions");
  actions.replaceChildren();
  if (["queued", "running"].includes(job.status)) {
    actions.append(actionButton("Cancel extraction", "button-secondary", () => jobMutation("cancel")));
    return;
  }
  if (job.status === "review" || (job.status === "approved" && state.editorDirty)) {
    actions.append(actionButton("Save & approve", "button-primary", async () => {
      if (state.currentJob?.id !== job.id) return;
      if (state.editorDirty) await saveCorrections(null, { approve: true });
      else await jobMutation("approve");
    }));
  }
  if (["review", "approved"].includes(job.status)) {
    if (job.status === "approved" && !state.editorDirty) {
      actions.append(actionButton("Download workbook", "button-primary", () => downloadExport(job, "xlsx")));
    }
    const more = document.createElement("details");
    more.className = "action-menu";
    const summary = document.createElement("summary");
    summary.textContent = "More";
    summary.setAttribute("aria-label", "More chart actions");
    more.append(summary);
    const menu = document.createElement("div");
    menu.className = "action-menu-content";
    for (const format of job.status === "review" ? ["XLSX", "CSV", "JSON"] : ["CSV", "JSON"]) {
      menu.append(actionButton(`${job.status === "review" ? "Export draft" : "Download"} ${format}`, "button-quiet", () => downloadExport(job, format.toLowerCase())));
    }
    const reprocess = actionButton("Reprocess · 1 credit", "button-quiet", () => jobMutation("reprocess"));
    reprocess.disabled = !state.account || state.account.credits <= 0;
    menu.append(reprocess);
    menu.append(actionButton("Rename chart", "button-quiet", () => renameChart(job)));
    menu.append(actionButton("Move to project", "button-quiet", () => moveChart(job)));
    menu.append(actionButton("Delete chart", "button-danger", deleteCurrentJob));
    more.append(menu);
    actions.append(more);
  } else if (["failed", "cancelled"].includes(job.status)) {
    const retry = actionButton("Try again · 1 credit", "button-primary", () => jobMutation("reprocess"));
    retry.disabled = !state.account || state.account.credits <= 0;
    actions.append(retry);
    actions.append(actionButton("Delete chart", "button-danger", deleteCurrentJob));
  }
}

function markEditorDirty(event) {
  if (event?.target?.dataset.kind) event.target.classList.add("cell-edited");
  if (state.editorDirty) return;
  state.editorDirty = true;
  byId("editor-change-note").textContent = "Unsaved changes";
  byId("edit-state").textContent = "Needs review";
  setHidden("export-completion", true);
  if (state.currentJob) {
    byId("job-status").textContent = "Unsaved changes";
    byId("job-title").textContent = "Review data";
    byId("job-meta").textContent = `Last saved · ${formatDate(state.currentJob.updated_at)}`;
    setHidden("review-notice", false);
    renderWorkflowSteps("review");
    renderJobActions();
  }
}

function discardEditorChanges() {
  if (!state.editorDirty) return true;
  if (!window.confirm("Leave without saving your corrections? Your last saved version will be kept.")) return false;
  if (state.currentJob?.result) renderJob();
  state.editorDirty = false;
  return true;
}

async function downloadExport(job, format) {
  if (state.editorDirty) {
    showToast("Save your corrections before exporting so the download includes your changes.");
    return;
  }
  const authEpoch = state.authEpoch;
  const authRecord = readDurableAuthRecord();
  const principal = state.principalMarker;
  const viewEpoch = state.viewEpoch;
  const signal = state.viewController.signal;
  let objectUrl = null;
  try {
    const response = await fetch(
      `/api/jobs/${routeSegment(job.id)}/export/${routeSegment(format)}`,
      { headers: { Accept: "application/octet-stream" }, signal }
    );
    if (!authContextMatches(authEpoch, authRecord)
      || state.principalMarker !== principal
      || state.viewEpoch !== viewEpoch
      || state.currentJob !== job
      || signal.aborted) throw staleAuthError();
    if (!response.ok) {
      if (response.status === 401) {
        quarantineAuth("signed-out", { clearCsrf: true });
        void publishAuthChange("session-ended");
        throw staleAuthError("The authenticated session ended");
      }
      throw new Error(`Export failed (${response.status})`);
    }
    const blob = await response.blob();
    if (!authContextMatches(authEpoch, authRecord)
      || state.principalMarker !== principal
      || state.viewEpoch !== viewEpoch
      || state.currentJob !== job
      || signal.aborted) throw staleAuthError();
    if (state.editorDirty) throw new Error("The table changed during export. Save your corrections and download again.");
    objectUrl = URL.createObjectURL(blob);
    state.objectUrls.add(objectUrl);
    if (!authContextMatches(authEpoch, authRecord)
      || state.principalMarker !== principal
      || state.viewEpoch !== viewEpoch
      || state.currentJob !== job) throw staleAuthError();
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `unrender-${job.id}.${format}`;
    document.body?.append(anchor);
    anchor.click();
    anchor.remove();
    setHidden("export-completion", false);
    showToast("Download started. Check your browser’s downloads.");
  } catch (error) {
    if (!isStaleRequest(error)) showToast(error);
  } finally {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      state.objectUrls.delete(objectUrl);
    }
  }
}

async function jobMutation(action) {
  const job = state.currentJob;
  if (!job) return;
  if (state.editorDirty) {
    showToast("Save your corrections before changing this extraction.");
    return;
  }
  const viewEpoch = state.viewEpoch;
  const signal = state.viewController.signal;
  const form = byId("result-form");
  if (form.getAttribute("aria-busy") === "true") return;
  form.setAttribute("aria-busy", "true");
  form.inert = true;
  try {
    const updated = await api(`/api/jobs/${routeSegment(job.id)}/${routeSegment(action)}`, {
      method: "POST", signal,
    });
    if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== job.id) throw staleAuthError();
    state.currentJob = updated;
    await refreshAccount();
    if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== job.id) throw staleAuthError();
    await loadJobs();
    if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== job.id) throw staleAuthError();
    renderJob();
    if (["queued", "running"].includes(state.currentJob.status)) {
      state.pollDelay = 1500;
      state.pollTimer = window.setTimeout(() => openJob(job.id), state.pollDelay);
    }
    showToast(action === "approve" ? "Result approved" : action === "cancel" ? "Cancellation recorded" : "Extraction queued");
  } catch (error) {
    showToast(error);
  } finally {
    if (viewEpoch === state.viewEpoch) {
      form.inert = false;
      form.removeAttribute("aria-busy");
    }
  }
}

function clearSelectedChart() {
  state.currentJob = null;
  state.editorDirty = false;
  state.editorRows = [];
  state.editorSeries = [];
  state.editorPage = 0;
  byId("result-form").reset();
  byId("result-form").inert = false;
  byId("result-form").removeAttribute("aria-busy");
  byId("job-source-image").removeAttribute("src");
  byId("job-source-image").style.width = "";
  byId("job-source-image").className = "";
  byId("source-zoom").value = "1";
  for (const id of ["result-table", "series-editor-list", "chart-type-input", "job-actions", "audit-list", "version-list"]) byId(id).replaceChildren();
  for (const id of ["editor-change-note", "edit-state", "job-title", "job-status", "job-meta", "source-page-label", "review-filename"]) byId(id).textContent = "";
  for (const id of ["result-form", "export-completion", "job-error", "review-notice", "audit-list", "version-list"]) setHidden(id, true);
}

async function deleteCurrentJob() {
  if (state.currentJob) return deleteLibraryChart(state.currentJob);
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
  byId("result-form").inert = false;
  byId("result-form").removeAttribute("aria-busy");
  state.editorDirty = false;
  byId("editor-change-note").textContent = "";
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
  table.classList.toggle("single-series", state.editorSeries.length === 1);
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
      markEditorDirty();
      const pageCount = Math.max(1, Math.ceil(state.editorRows.length / EDITOR_PAGE_SIZE));
      state.editorPage = Math.min(state.editorPage, pageCount - 1);
      renderResultTable();
    });
    removeCell.append(remove);
    tr.append(removeCell);
    body.append(tr);
  });
  table.append(head, body);
  const mountedCells = table.querySelectorAll("*").length
    + byId("series-editor-list").querySelectorAll("*").length
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
  markEditorDirty();
  state.editorPage = Math.floor((state.editorRows.length - 1) / EDITOR_PAGE_SIZE);
  renderResultTable();
  byId("result-table").tBodies[0].lastElementChild.querySelector('[data-kind="x"]').focus();
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

async function saveCorrections(event, { approve = false } = {}) {
  event?.preventDefault();
  const form = byId("result-form");
  if (form.getAttribute("aria-busy") === "true") return false;
  if (!form.reportValidity()) return false;
  const jobId = state.currentJob?.id;
  const viewEpoch = state.viewEpoch;
  const authEpoch = state.authEpoch;
  const signal = state.viewController.signal;
  if (!jobId) return false;
  form.setAttribute("aria-busy", "true");
  form.inert = true;
  let saved = false;
  try {
    const result = buildEditedResult();
    const updated = await api(`/api/jobs/${routeSegment(jobId)}/result`, {
      method: "PATCH", body: { result }, signal,
    });
    if (authEpoch !== state.authEpoch || viewEpoch !== state.viewEpoch || state.currentJob?.id !== jobId) throw staleAuthError();
    state.currentJob = updated;
    saved = true;
    if (approve) {
      const approved = await api(`/api/jobs/${routeSegment(jobId)}/approve`, { method: "POST", signal });
      if (authEpoch !== state.authEpoch || viewEpoch !== state.viewEpoch || state.currentJob?.id !== jobId) throw staleAuthError();
      state.currentJob = approved;
    }
    await loadJobs();
    if (authEpoch !== state.authEpoch || viewEpoch !== state.viewEpoch || state.currentJob?.id !== jobId) throw staleAuthError();
    renderJob();
    showToast(approve ? "Corrections saved and result approved" : "Corrections saved to the audit trail");
    return true;
  } catch (error) {
    if (approve && saved && authEpoch === state.authEpoch
      && viewEpoch === state.viewEpoch && state.currentJob?.id === jobId) renderJob();
    showToast(error);
    return false;
  } finally {
    if (authEpoch === state.authEpoch && viewEpoch === state.viewEpoch) {
      form.inert = false;
      form.removeAttribute("aria-busy");
    }
  }
}

async function toggleAudit() {
  const list = byId("audit-list");
  const button = byId("toggle-audit-button");
  if (button.disabled) return;
  if (!list.hidden) {
    list.hidden = true;
    byId("toggle-audit-button").textContent = "Show activity";
    return;
  }
  const authEpoch = state.authEpoch;
  const viewEpoch = state.viewEpoch;
  button.disabled = true;
  button.textContent = "Loading activity…";
  button.setAttribute("aria-busy", "true");
  try {
    const jobId = state.currentJob.id;
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
  } finally {
    if (authEpoch === state.authEpoch && viewEpoch === state.viewEpoch) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = list.hidden ? "Show activity" : "Hide activity";
    }
  }
}

async function restoreVersion(version) {
  const jobId = state.currentJob?.id;
  const viewEpoch = state.viewEpoch;
  const signal = state.viewController.signal;
  const form = byId("result-form");
  if (!jobId || form.getAttribute("aria-busy") === "true") return;
  if (state.editorDirty) {
    showToast("Save your corrections before restoring a version.");
    return;
  }
  form.setAttribute("aria-busy", "true");
  form.inert = true;
  try {
    const saved = await api(
      `/api/jobs/${routeSegment(jobId)}/versions/${routeSegment(version.version)}`, { signal },
    );
    if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== jobId) throw staleAuthError();
    const updated = await api(`/api/jobs/${routeSegment(jobId)}/result`, {
      method: "PATCH", body: { result: saved.result }, signal,
    });
    if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== jobId) throw staleAuthError();
    state.currentJob = updated;
    await loadJobs();
    if (viewEpoch !== state.viewEpoch || state.currentJob?.id !== jobId) throw staleAuthError();
    renderJob();
    showToast(`Version ${version.version} restored as a new correction`);
  } catch (error) {
    showToast(error);
  } finally {
    if (viewEpoch === state.viewEpoch) {
      form.inert = false;
      form.removeAttribute("aria-busy");
    }
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
  const button = byId("toggle-versions-button");
  if (button.disabled) return;
  if (!list.hidden) {
    list.hidden = true;
    byId("toggle-versions-button").textContent = "Show versions";
    return;
  }
  const authEpoch = state.authEpoch;
  const viewEpoch = state.viewEpoch;
  button.disabled = true;
  button.textContent = "Loading versions…";
  button.setAttribute("aria-busy", "true");
  try {
    const count = await loadVersions();
    if (authEpoch !== state.authEpoch || viewEpoch !== state.viewEpoch) throw staleAuthError();
    if (!count) {
      const empty = document.createElement("li");
      empty.textContent = "No extracted result yet.";
      list.append(empty);
    }
    list.hidden = false;
    byId("toggle-versions-button").textContent = "Hide versions";
  } catch (error) {
    showToast(error);
  } finally {
    if (authEpoch === state.authEpoch && viewEpoch === state.viewEpoch) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = list.hidden ? "Show versions" : "Hide versions";
    }
  }
}

async function openKeyDialog() {
  invalidateApiKeyDialog();
  const dialogEpoch = state.keyDialogEpoch;
  byId("generate-key-button").hidden = false;
  byId("generate-key-button").disabled = false;
  byId("api-key-dialog").showModal();
  byId("api-key-name").focus();
  await loadApiKeys({ dialogEpoch });
}

async function loadApiKeys({ dialogEpoch = state.keyDialogEpoch } = {}) {
  if (dialogEpoch !== state.keyDialogEpoch || !byId("api-key-dialog").open) return;
  const list = byId("api-key-list");
  const authEpoch = state.authEpoch;
  const principal = state.principalMarker;
  const listEpoch = ++state.keyListEpoch;
  const signal = state.keyController.signal;
  const pending = document.createElement("li");
  pending.textContent = "Loading API keys…";
  pending.setAttribute("role", "status");
  list.replaceChildren(pending);
  try {
    const keys = [];
    let cursor = null;
    do {
      const query = cursor ? `?cursor=${encodeURIComponent(cursor)}&limit=100` : "?limit=100";
      const payload = await api(`/api/keys${query}`, { authEpoch, signal });
      if (authEpoch !== state.authEpoch || principal !== state.principalMarker
        || dialogEpoch !== state.keyDialogEpoch || listEpoch !== state.keyListEpoch
        || signal.aborted) throw staleAuthError();
      keys.push(...payload.items);
      cursor = payload.next_cursor;
    } while (cursor);
    if (authEpoch !== state.authEpoch || principal !== state.principalMarker
      || dialogEpoch !== state.keyDialogEpoch || listEpoch !== state.keyListEpoch
      || signal.aborted || !byId("api-key-dialog").open) throw staleAuthError();
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
    if (isStaleRequest(error) || authEpoch !== state.authEpoch || principal !== state.principalMarker
      || dialogEpoch !== state.keyDialogEpoch || listEpoch !== state.keyListEpoch
      || signal.aborted || !byId("api-key-dialog").open) return;
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
  if (state.keyCreatePending || !byId("api-key-dialog").open) return;
  const authEpoch = state.authEpoch;
  const principal = state.principalMarker;
  const dialogEpoch = state.keyDialogEpoch;
  const signal = state.keyController.signal;
  const button = byId("generate-key-button");
  state.keyCreatePending = true;
  button.disabled = true;
  window.clearTimeout(state.keySecretTimer);
  state.keySecretTimer = window.setTimeout(() => {
    if (dialogEpoch !== state.keyDialogEpoch) return;
    invalidateApiKeyDialog();
    byId("generate-key-button").hidden = false;
    byId("generate-key-button").disabled = false;
  }, 30000);
  try {
    const payload = await api("/api/keys", {
      method: "POST",
      body: { name: byId("api-key-name").value },
      authEpoch,
      signal,
    });
    if (authEpoch !== state.authEpoch || principal !== state.principalMarker
      || dialogEpoch !== state.keyDialogEpoch || signal.aborted
      || !byId("api-key-dialog").open) {
      payload.key = "";
      throw staleAuthError();
    }
    byId("api-key-output").textContent = payload.key;
    byId("api-key-output").hidden = false;
    byId("copy-key-button").hidden = false;
    byId("dismiss-key-button").hidden = false;
    byId("generate-key-button").hidden = true;
    await loadApiKeys({ dialogEpoch });
  } catch (error) {
    showToast(error);
  } finally {
    if (dialogEpoch === state.keyDialogEpoch) {
      state.keyCreatePending = false;
      button.disabled = false;
    }
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
    invalidateApiKeyDialog();
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

function closeKeyDialog() {
  invalidateApiKeyDialog();
  if (byId("api-key-dialog").open) byId("api-key-dialog").close();
}

function bindEvents() {
  for (const id of ["google-signin", "google-signup"]) byId(id)?.addEventListener("click", startGoogleLogin);
  bindLibraryEvents();
  bindSettingsEvents();
  bindReviewResize();
  byId("source-zoom").addEventListener("change", (event) => {
    const image = byId("job-source-image");
    const fit = event.target.value === "1";
    image.classList.toggle("source-actual", !fit);
    image.style.width = fit ? "" : `${image.naturalWidth * (event.target.value === "actual" ? 1 : Number(event.target.value))}px`;
  });
  byId("login-tab").addEventListener("click", () => switchAuth("login"));
  byId("register-tab").addEventListener("click", () => switchAuth("register"));
  byId("login-form").addEventListener("submit", (event) => submitAuth(event, "login"));
  byId("register-form").addEventListener("submit", (event) => submitAuth(event, "register"));
  byId("open-sample-button").addEventListener("click", demoLoginAndRun);
  byId("logout-button").addEventListener("click", logout);
  byId("retry-logout-button").addEventListener("click", logout);
  byId("home-button").addEventListener("click", (event) => {
    if (state.account) { event.preventDefault(); showLibrary(); }
    else if (!discardEditorChanges()) event.preventDefault();
  });
  byId("export-another-button").addEventListener("click", startUpload);
  byId("result-form").addEventListener("input", markEditorDirty);
  byId("result-form").addEventListener("change", markEditorDirty);
  window.addEventListener("beforeunload", (event) => {
    if (!state.editorDirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
  for (const id of ["new-upload-button", "empty-upload-button"]) byId(id).addEventListener("click", startUpload);
  byId("cancel-upload-button").addEventListener("click", discardUpload);
  byId("file-input").addEventListener("change", (event) => prepareFile(event.target.files[0]));
  const dropzone = byId("dropzone");
  dropzone.addEventListener("dragover", (event) => {
    if (!Array.from(event.dataTransfer?.types || []).includes("Files")) return;
    event.preventDefault();
    const busy = dropzone.getAttribute("aria-busy") === "true";
    event.dataTransfer.dropEffect = busy ? "none" : "copy";
    dropzone.classList.toggle("is-dragover", !busy);
  });
  dropzone.addEventListener("dragleave", (event) => {
    if (!dropzone.contains(event.relatedTarget)) dropzone.classList.remove("is-dragover");
  });
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragover");
    if (dropzone.getAttribute("aria-busy") === "true") return;
    const files = event.dataTransfer?.files;
    if (!files?.length) return;
    if (files.length !== 1) {
      showError("upload-error", new Error("Drop one chart image or PDF at a time."));
      return;
    }
    prepareFile(files[0]);
  });
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
  byId("create-key-button").addEventListener("click", () => { closeSettings(); openKeyDialog(); });
  byId("close-key-dialog").addEventListener("click", closeKeyDialog);
  byId("copy-key-button").addEventListener("click", copyApiKeySecret);
  byId("dismiss-key-button").addEventListener("click", invalidateApiKeyDialog);
  byId("api-key-dialog").addEventListener("cancel", (event) => {
    event.preventDefault();
    closeKeyDialog();
  });
  byId("api-key-dialog").addEventListener("close", invalidateApiKeyDialog);
  byId("revoke-all-keys-button").addEventListener("click", revokeAllApiKeys);
  byId("api-key-form").addEventListener("submit", createKey);
  byId("buy-credits-button").addEventListener("click", buyCredits);
  window.addEventListener("pagehide", closeKeyDialog);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") closeKeyDialog();
  });
}

bindEvents();
boot();
