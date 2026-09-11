import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { TextEncoder } from "node:util";
import { webcrypto } from "node:crypto";

const AUTH_KEY = "unrender.auth-state.v2";
const LEGACY_AUTH_KEY = "unrender.auth-change.v1";
const JOB_KEY = "unrender.job-submission.v1";
const nodes = new Map();
const storageValues = new Map();
let anchorClicks = 0;

class FakeNode {
  constructor(tag = "div") {
    this.tag = tag;
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.textContent = "";
    this.value = "";
    this.children = [];
    this.style = {};
    this.attributes = new Map();
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  reset() { this.value = ""; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  remove() {}
  click() { if (this.tag === "a") anchorClicks += 1; }
  focus() {}
  removeAttribute(name) { this.attributes.delete(name); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  querySelector() { return new FakeNode(); }
  querySelectorAll() { return []; }
}

const document = {
  cookie: "unrender_csrf=old-secret",
  visibilityState: "visible",
  body: new FakeNode("body"),
  createElement(tag) { return new FakeNode(tag); },
  getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, new FakeNode());
    return nodes.get(id);
  },
  addEventListener() {},
};

const revoked = [];
const createdUrls = [];
class TestURL extends URL {
  static createObjectURL() {
    const value = `blob:test-${createdUrls.length + 1}`;
    createdUrls.push(value);
    return value;
  }
  static revokeObjectURL(value) { revoked.push(value); }
}

const localStorage = {
  getItem(key) { return storageValues.get(key) ?? null; },
  setItem(key, value) { storageValues.set(key, value); },
  removeItem(key) { storageValues.delete(key); },
};

const context = {
  AbortController,
  Error,
  FormData,
  Headers,
  Intl,
  JSON,
  Map,
  Math,
  Number,
  Object,
  Promise,
  Set,
  String,
  TextEncoder,
  Uint8Array,
  URL: TestURL,
  crypto: webcrypto,
  document,
  encodeURIComponent,
  decodeURIComponent,
  fetch: null,
  localStorage,
  window: {
    clearTimeout,
    setTimeout,
    addEventListener() {},
  },
};
context.globalThis = context;
vm.createContext(context);

const appPath = new URL("../unrender/product/static/app.js", import.meta.url);
const source = ["google.js", "library.js", "settings.js"].map((name) => fs.readFileSync(new URL(`../unrender/product/static/${name}`, import.meta.url), "utf8")).join("\n") + "\n" + fs.readFileSync(appPath, "utf8").replace(/\nbindEvents\(\);\nboot\(\);\s*$/, "");
vm.runInContext(
  `${source}
renderJobList = () => {};
renderLibrary = () => {};
loadProjects = async () => {};
renderJob = () => {};
globalThis.__mainViewCalls = [];
showMainView = (name) => globalThis.__mainViewCalls.push(name);
globalThis.__unrenderTest = {
  api, clearApiKeySecret, closeKeyDialog, createKey, downloadExport, editorRows,
  loadApiKeys, logout, queueCurrentUpload, resetPrivateState, showPublic, state,
  syncAuthRecordFromStorage, readDurableAuthRecord, publishAuthChange, reconcilePrincipal,
  EDITOR_PAGE_SIZE, EDITOR_MOUNTED_CELL_LIMIT,
};`,
  context,
  { filename: appPath.pathname },
);

const test = context.__unrenderTest;
function installAuthenticatedRecord(marker = "principal-a") {
  const previous = test.readDurableAuthRecord();
  // This helper models a completed explicit login: the new cookie already
  // exists before authenticated publication retires the legacy non-auth barrier.
  storageValues.delete(LEGACY_AUTH_KEY);
  storageValues.set(AUTH_KEY, JSON.stringify({
    version: 2,
    revision: (previous?.revision || 0) + 1,
    id: `auth-${Date.now()}-${Math.random()}`,
    phase: "authenticated",
    principalMarker: marker,
  }));
  test.syncAuthRecordFromStorage({ wipe: false });
}

installAuthenticatedRecord("old-principal");
test.state.account = { id: "old-account", email: "old@example.com" };
test.state.principalMarker = "old-principal";
test.state.jobs = [{ id: "old-job" }];
test.state.currentJob = { id: "old-job", result: { private: true } };
test.state.upload = { id: "old-upload" };
test.state.editorRows = [{ x: "secret" }];
test.state.objectUrls.add("blob:old-source");
document.getElementById("api-key-output").textContent = "unr_old_secret";
document.getElementById("api-key-dialog").open = true;
document.getElementById("job-source-image").setAttribute("src", "/api/jobs/old/source");
document.getElementById("upload-preview").setAttribute("src", "/api/uploads/old/pages/0");
document.getElementById("result-table").replaceChildren({ private: true });
document.getElementById("chart-type-input").replaceChildren({ oldSelection: true });
document.getElementById("result-loading").textContent = "Old account provider failure";
document.getElementById("toast").textContent = "Old account state";
document.getElementById("toast").hidden = false;

let releaseBody;
let bodyStarted;
const bodyWasStarted = new Promise((resolve) => { bodyStarted = resolve; });
context.fetch = async () => ({
  ok: true,
  status: 200,
  headers: { get: () => "application/json" },
  json: () => new Promise((resolve) => {
    releaseBody = resolve;
    bodyStarted();
  }),
});
const delayedOldAccount = test.api("/api/jobs/old-job");
await bodyWasStarted;
test.resetPrivateState();
releaseBody({ id: "old-job", result: { private: true } });
await assert.rejects(delayedOldAccount, (error) => error.code === "stale_auth_context");
assert.equal(test.state.account, null);
assert.equal(test.state.jobs.length, 0);
assert.equal(test.state.currentJob, null);
assert.equal(test.state.upload, null);
assert.equal(test.state.editorRows.length, 0);
assert.deepEqual(revoked, ["blob:old-source"]);
assert.equal(document.getElementById("api-key-output").textContent, "");
assert.equal(document.getElementById("api-key-dialog").open, false);
assert.equal(document.getElementById("job-source-image").attributes.has("src"), false);
assert.equal(document.getElementById("upload-preview").attributes.has("src"), false);
assert.deepEqual(document.getElementById("result-table").children, []);

// Non-2xx and network failures never claim global sign-out succeeded. Both are
// retried a bounded three times, persisted as failed, and expose retry state.
installAuthenticatedRecord("logout-principal");
test.state.account = { id: "logout-account" };
test.state.principalMarker = "logout-principal";
let logoutCalls = 0;
context.fetch = async (path) => {
  if (path === "/api/auth/logout") logoutCalls += 1;
  return { ok: false, status: 503 };
};
assert.equal(await test.logout(), false);
assert.equal(logoutCalls, 3);
assert.equal(test.readDurableAuthRecord().phase, "logout-failed");
assert.equal(document.getElementById("logout-retry-panel").hidden, false);
assert.equal(test.state.account, null);

logoutCalls = 0;
context.fetch = async (path) => {
  if (path === "/api/auth/logout") logoutCalls += 1;
  throw new TypeError("network unavailable");
};
assert.equal(await test.logout(), false);
assert.equal(logoutCalls, 3);
assert.equal(test.readDurableAuthRecord().phase, "logout-failed");

let ambiguousLogoutAttempts = 0;
context.fetch = async (path) => {
  if (path === "/api/auth/logout") {
    ambiguousLogoutAttempts += 1;
    if (ambiguousLogoutAttempts === 1) throw new TypeError("success response was lost");
    return { ok: false, status: 401 };
  }
  if (path === "/api/me") return { ok: false, status: 401 };
  throw new Error(`unexpected request ${path}`);
};
assert.equal(await test.logout(), false);
assert.equal(ambiguousLogoutAttempts, 3);
assert.equal(test.readDurableAuthRecord().phase, "signed-out-unconfirmed");
assert.match(document.getElementById("logout-status").textContent, /not confirmed/i);
const unconfirmed = test.readDurableAuthRecord();
const recoveredLogin = await test.publishAuthChange("authenticated", {
  explicitLogin: true,
  expected: unconfirmed,
  principalMarker: "recovered-principal",
});
assert.equal(recoveredLogin.phase, "authenticated");

context.fetch = async () => ({ ok: true, status: 200 });
assert.equal(await test.logout(), true);
assert.equal(test.readDurableAuthRecord().phase, "signed-out");
assert.equal(document.getElementById("logout-retry-panel").hidden, true);

// An ambiguous charged POST is replayed with the exact durable key/body, then
// cleared only after account/list/open convergence.
installAuthenticatedRecord("job-principal");
test.state.account = {
  id: "job-account", email: "job@example.com", credits: 2,
  credit_pack_size: 100, billing_configured: false, demo_account: false,
};
test.state.principalMarker = "job-principal";
test.state.upload = { id: "upload-1", page_count: 1 };
test.state.uploadPage = 0;
test.state.crop = { x: 0.1, y: 0.2, width: 0.3, height: 0.4 };
const postKeys = [];
const postBodies = [];
let ambiguous = true;
context.fetch = async (path, options = {}) => {
  if (path === "/api/jobs" && options.method === "POST") {
    postKeys.push(new Headers(options.headers).get("Idempotency-Key"));
    postBodies.push(options.body);
    if (ambiguous) {
      ambiguous = false;
      throw new TypeError("response lost after commit");
    }
    return {
      ok: true, status: 201, headers: { get: () => "application/json" },
      json: async () => ({ id: "job-1", status: "queued" }),
    };
  }
  if (path === "/api/me") {
    return {
      ok: true, status: 200, headers: { get: () => "application/json" },
      json: async () => ({ ...test.state.account, principal_marker: "job-principal" }),
    };
  }
  if (path.startsWith("/api/jobs?")) {
    return {
      ok: true, status: 200, headers: { get: () => "application/json" },
      json: async () => ({ items: [{ id: "job-1", status: "queued" }], next_cursor: null }),
    };
  }
  if (path === "/api/jobs/job-1") {
    return {
      ok: true, status: 200, headers: { get: () => "application/json" },
      json: async () => ({ id: "job-1", status: "review", result: null }),
    };
  }
  throw new Error(`unexpected request ${path}`);
};
await test.queueCurrentUpload();
assert.equal(JSON.parse(storageValues.get(JOB_KEY)).phase, "prepared");
await test.queueCurrentUpload();
assert.equal(postKeys.length, 2);
assert.equal(postKeys[0], postKeys[1]);
assert.equal(postBodies[0], postBodies[1]);
assert.equal(storageValues.has(JOB_KEY), false);
assert.equal(test.state.currentJob.id, "job-1");

test.state.upload = { id: "upload-2", page_count: 1 };
test.state.uploadPage = 0;
test.state.crop = null;
let successfulPosts = 0;
let failAccountRefresh = true;
context.fetch = async (path, options = {}) => {
  if (path === "/api/jobs" && options.method === "POST") {
    successfulPosts += 1;
    return {
      ok: true, status: 201, headers: { get: () => "application/json" },
      json: async () => ({ id: "job-2", status: "queued" }),
    };
  }
  if (path === "/api/me") {
    if (failAccountRefresh) {
      failAccountRefresh = false;
      throw new TypeError("post-success UI refresh failed");
    }
    return {
      ok: true, status: 200, headers: { get: () => "application/json" },
      json: async () => ({ ...test.state.account, principal_marker: "job-principal" }),
    };
  }
  if (path.startsWith("/api/jobs?")) {
    return {
      ok: true, status: 200, headers: { get: () => "application/json" },
      json: async () => ({ items: [{ id: "job-2", status: "queued" }], next_cursor: null }),
    };
  }
  if (path === "/api/jobs/job-2") {
    return {
      ok: true, status: 200, headers: { get: () => "application/json" },
      json: async () => ({ id: "job-2", status: "review", result: null }),
    };
  }
  throw new Error(`unexpected request ${path}`);
};
await test.queueCurrentUpload();
assert.equal(JSON.parse(storageValues.get(JOB_KEY)).phase, "accepted");
await test.queueCurrentUpload();
assert.equal(successfulPosts, 1);
assert.equal(storageValues.has(JOB_KEY), false);
assert.equal(test.state.currentJob.id, "job-2");

// An export body that finishes after account reset cannot create or click a blob URL.
installAuthenticatedRecord("export-principal");
test.state.account = { id: "export-account" };
test.state.principalMarker = "export-principal";
test.state.currentJob = { id: "export-job", status: "approved" };
const exportButton = new FakeNode("button");
let releaseBlob;
let blobStarted;
const blobWasStarted = new Promise((resolve) => { blobStarted = resolve; });
context.fetch = async () => ({
  ok: true,
  status: 200,
  blob: () => new Promise((resolve) => { releaseBlob = resolve; blobStarted(); }),
});
const delayedExport = test.downloadExport(test.state.currentJob, "csv", exportButton);
await blobWasStarted;
test.resetPrivateState();
releaseBlob(new Blob(["private export"]));
await delayedExport;
assert.equal(createdUrls.length, 0);
assert.equal(anchorClicks, 0);

// Replacing the visible version of the same job also invalidates an export
// captured from the prior result object.
installAuthenticatedRecord("version-export-principal");
test.state.account = { id: "version-export-account" };
test.state.principalMarker = "version-export-principal";
const oldVersion = { id: "version-export-job", status: "approved", result: { version: 1 } };
test.state.currentJob = oldVersion;
let releaseVersionBlob;
let versionBlobStarted;
const versionBlobWasStarted = new Promise((resolve) => { versionBlobStarted = resolve; });
context.fetch = async () => ({
  ok: true,
  status: 200,
  blob: () => new Promise((resolve) => {
    releaseVersionBlob = resolve;
    versionBlobStarted();
  }),
});
const delayedOldVersionExport = test.downloadExport(oldVersion, "csv", new FakeNode("button"));
await versionBlobWasStarted;
test.state.currentJob = {
  id: oldVersion.id, status: "approved", result: { version: 2 },
};
releaseVersionBlob(new Blob(["superseded private export"]));
await delayedOldVersionExport;
assert.equal(createdUrls.length, 0);
assert.equal(anchorClicks, 0);

installAuthenticatedRecord("old-export-principal");
test.state.account = { id: "old-export-account" };
test.state.principalMarker = "old-export-principal";
test.state.currentJob = { id: "old-export-job", status: "approved" };
let releaseOldUnauthorized;
context.fetch = () => new Promise((resolve) => { releaseOldUnauthorized = resolve; });
const delayedUnauthorized = test.downloadExport(
  test.state.currentJob,
  "csv",
  new FakeNode("button"),
);
await Promise.resolve();
test.resetPrivateState();
installAuthenticatedRecord("replacement-principal");
test.state.account = { id: "replacement-account" };
test.state.principalMarker = "replacement-principal";
test.state.currentJob = { id: "replacement-job", status: "review" };
releaseOldUnauthorized({ ok: false, status: 401 });
await delayedUnauthorized;
assert.equal(test.readDurableAuthRecord().phase, "authenticated");
assert.equal(test.readDurableAuthRecord().principalMarker, "replacement-principal");
assert.equal(test.state.account.id, "replacement-account");
assert.equal(createdUrls.length, 0);
assert.equal(anchorClicks, 0);

// Closing a key dialog invalidates and aborts a delayed create response before
// it can rematerialize the one-time secret.
installAuthenticatedRecord("key-principal");
test.state.account = { id: "key-account" };
test.state.principalMarker = "key-principal";
document.getElementById("api-key-dialog").open = true;
document.getElementById("api-key-name").value = "Delayed key";
let releaseKeyBody;
let keyBodyStarted;
const keyBodyWasStarted = new Promise((resolve) => { keyBodyStarted = resolve; });
context.fetch = async () => ({
  ok: true,
  status: 201,
  headers: { get: () => "application/json" },
  json: () => new Promise((resolve) => { releaseKeyBody = resolve; keyBodyStarted(); }),
});
const delayedKey = test.createKey({ preventDefault() {} });
await keyBodyWasStarted;
test.closeKeyDialog();
releaseKeyBody({ key: "unr_late_secret", prefix: "unr_late" });
await delayedKey;
assert.equal(document.getElementById("api-key-output").textContent, "");
assert.equal(document.getElementById("api-key-output").hidden, true);
assert.equal(document.getElementById("api-key-dialog").open, false);

document.getElementById("api-key-output").textContent = "unr_one_time_secret";
document.getElementById("api-key-output").hidden = false;
test.clearApiKeySecret();
assert.equal(document.getElementById("api-key-output").textContent, "");
assert.equal(document.getElementById("api-key-output").hidden, true);

const maximumResult = {
  series: Array.from({ length: 50 }, (_, seriesIndex) => ({
    name: `Series ${seriesIndex + 1}`,
    points: Array.from({ length: 200 }, (_, pointIndex) => ({
      x: `${seriesIndex}-${pointIndex}`,
      y: pointIndex,
    })),
  })),
};
const started = Date.now();
const maximumRows = test.editorRows(maximumResult);
assert.equal(maximumRows.length, 10000);
assert.ok(Date.now() - started < 1000);
// A maximum 50-series page mounts two series-editor nodes, nine table nodes
// per value, seven table shell/header nodes, and five paging controls.
assert.ok(
  (50 * 2) + (test.EDITOR_PAGE_SIZE * 9) + 7 + 5 <= test.EDITOR_MOUNTED_CELL_LIMIT,
);

// Returning from a file picker must not discard a first-time customer's upload.
installAuthenticatedRecord("upload-principal");
test.state.principalMarker = "upload-principal";
test.state.jobs = [];
test.state.jobsInitialized = true;
test.state.upload = { id: "pending-upload" };
const viewsBeforeFocus = context.__mainViewCalls.length;
const focusRequests = [];
context.fetch = async (path) => {
  focusRequests.push(path);
  return {
    ok: true, status: 200, headers: { get: () => "application/json" },
    json: async () => path === "/api/me"
      ? { id: "upload-user", principal_marker: "upload-principal", credits: 3 }
      : { items: [] },
  };
};
await test.reconcilePrincipal();
assert.deepEqual(focusRequests, ["/api/me"]);
assert.equal(context.__mainViewCalls.length, viewsBeforeFocus);
assert.equal(test.state.upload.id, "pending-upload");

// A failed initial list fetch retries on focus without replacing an upload.
test.state.jobsInitialized = false;
let listAttempts = 0;
context.fetch = async (path) => {
  if (path.startsWith("/api/jobs") && ++listAttempts === 1) throw new Error("temporary network failure");
  return {
    ok: true, status: 200, headers: { get: () => "application/json" },
    json: async () => path === "/api/me"
      ? { id: "upload-user", principal_marker: "upload-principal", credits: 3 }
      : { items: [] },
  };
};
await test.reconcilePrincipal();
assert.equal(test.state.jobsInitialized, false);
await test.reconcilePrincipal();
assert.equal(listAttempts, 2);
assert.equal(test.state.jobsInitialized, true);
assert.equal(test.state.upload.id, "pending-upload");
assert.equal(context.__mainViewCalls.length, viewsBeforeFocus);


// A delayed anonymous session check must not erase a user's sign-in input.
storageValues.clear();
test.state.authRecord = null;
test.state.principalMarker = null;
const anonymousEpoch = test.state.authEpoch;
document.getElementById("login-form").value = "typed sign-in fields";
context.fetch = async () => ({
  ok: false, status: 401, headers: { get: () => "application/json" },
  json: async () => ({ error: { message: "Authentication required" } }),
});
await assert.rejects(test.api("/api/me"), (error) => error.status === 401);
assert.equal(test.state.authEpoch, anonymousEpoch);
assert.equal(document.getElementById("login-form").value, "typed sign-in fields");
assert.equal(test.readDurableAuthRecord(), null);
