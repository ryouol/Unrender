import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const nodes = new Map();

class FakeNode {
  constructor() {
    this.hidden = false;
    this.open = false;
    this.textContent = "";
    this.value = "";
    this.children = [];
    this.attributes = new Map();
  }

  replaceChildren(...children) {
    this.children = children;
  }

  reset() {
    this.value = "";
  }

  close() {
    this.open = false;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
}

const document = {
  cookie: "unrender_csrf=old-secret",
  getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, new FakeNode());
    return nodes.get(id);
  },
};

const revoked = [];
URL.revokeObjectURL = (value) => revoked.push(value);
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
  URL,
  document,
  encodeURIComponent,
  decodeURIComponent,
  fetch: null,
  window: {
    clearTimeout,
    setTimeout,
  },
};
context.globalThis = context;
vm.createContext(context);

const appPath = new URL("../unrender/product/static/app.js", import.meta.url);
const source = fs.readFileSync(appPath, "utf8").replace(/\nbindEvents\(\);\nboot\(\);\s*$/, "");
vm.runInContext(
  `${source}\nglobalThis.__unrenderTest = { api, loadApiKeys, logout, resetPrivateState, showPublic, state };`,
  context,
  { filename: appPath.pathname },
);

const { api, loadApiKeys, logout, resetPrivateState, showPublic, state } = context.__unrenderTest;
state.account = { id: "old-account", email: "old@example.com" };
state.jobs = [{ id: "old-job" }];
state.currentJob = { id: "old-job", result: { private: true } };
state.upload = { id: "old-upload" };
state.editorRows = [{ x: "secret" }];
state.objectUrls.add("blob:old-source");
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

const delayedOldAccount = api("/api/jobs/old-job");
await bodyWasStarted;
resetPrivateState();
releaseBody({ id: "old-job", result: { private: true } });
await assert.rejects(delayedOldAccount, (error) => error.code === "stale_auth_context");

assert.equal(state.account, null);
assert.equal(state.jobs.length, 0);
assert.equal(state.currentJob, null);
assert.equal(state.upload, null);
assert.equal(state.editorRows.length, 0);
assert.deepEqual(revoked, ["blob:old-source"]);
assert.equal(document.getElementById("api-key-output").textContent, "");
assert.equal(document.getElementById("api-key-dialog").open, false);
assert.equal(document.getElementById("job-source-image").attributes.has("src"), false);
assert.equal(document.getElementById("upload-preview").attributes.has("src"), false);
assert.deepEqual(document.getElementById("result-table").children, []);
assert.deepEqual(document.getElementById("chart-type-input").children, []);
assert.equal(document.getElementById("result-loading").textContent, "");
assert.equal(document.getElementById("toast").textContent, "");
assert.equal(document.getElementById("toast").hidden, true);

state.account = { id: "expired-account" };
context.fetch = async () => ({
  ok: false,
  status: 401,
  headers: { get: () => "application/json" },
  json: async () => ({ error: { code: "unauthorized", message: "Sign in" } }),
});
await loadApiKeys();
assert.equal(state.account, null);
assert.deepEqual(document.getElementById("api-key-list").children, []);

let releaseLogout;
let logoutStarted;
const logoutBodyStarted = new Promise((resolve) => { logoutStarted = resolve; });
context.fetch = async () => ({
  ok: true,
  status: 200,
  headers: { get: () => "application/json" },
  json: () => new Promise((resolve) => {
    releaseLogout = resolve;
    logoutStarted();
  }),
});
state.account = { id: "account-before-switch" };
const oldLogout = logout();
await logoutBodyStarted;
resetPrivateState();
state.account = { id: "new-account" };
releaseLogout({ status: "signed_out" });
await assert.rejects(oldLogout, (error) => error.code === "stale_auth_context");
assert.equal(state.account.id, "new-account");

state.account = { id: "second-account" };
showPublic();
assert.equal(state.account, null);
assert.equal(document.getElementById("workspace-view").hidden, true);
assert.equal(document.getElementById("marketing-view").hidden, false);
