import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { webcrypto } from "node:crypto";

class FakeNode {
  constructor() {
    this.hidden = false;
    this.open = false;
    this.textContent = "";
    this.value = "";
    this.children = [];
    this.attributes = new Map();
  }
  replaceChildren(...children) { this.children = children; }
  reset() { this.value = ""; }
  close() { this.open = false; }
  removeAttribute(name) { this.attributes.delete(name); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  addEventListener() {}
  querySelectorAll() { return []; }
}

const channelMembers = new Map();
const storageValues = new Map();
class SharedBroadcastChannel {
  constructor(name) {
    this.name = name;
    this.listeners = [];
    const members = channelMembers.get(name) || [];
    members.push(this);
    channelMembers.set(name, members);
  }
  addEventListener(type, listener) {
    if (type === "message") this.listeners.push(listener);
  }
  postMessage(data) {
    for (const member of channelMembers.get(this.name) || []) {
      if (member === this) continue;
      for (const listener of member.listeners) listener({ data });
    }
  }
}

function makeTab() {
  const nodes = new Map();
  const documentListeners = new Map();
  const windowListeners = new Map();
  const document = {
    cookie: "unrender_csrf=shared",
    visibilityState: "visible",
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, new FakeNode());
      return nodes.get(id);
    },
    addEventListener(type, listener) { documentListeners.set(type, listener); },
  };
  const context = {
    AbortController,
    BroadcastChannel: SharedBroadcastChannel,
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
    crypto: webcrypto,
    document,
    encodeURIComponent,
    decodeURIComponent,
    fetch: null,
    localStorage: {
      getItem(key) { return storageValues.get(key) ?? null; },
      setItem(key, value) { storageValues.set(key, value); },
    },
    window: {
      clearTimeout,
      setTimeout: () => 1,
      addEventListener(type, listener) { windowListeners.set(type, listener); },
    },
  };
  context.globalThis = context;
  vm.createContext(context);
  const appPath = new URL("../unrender/product/static/app.js", import.meta.url);
  const source = fs.readFileSync(appPath, "utf8").replace(/\nbindEvents\(\);\nboot\(\);\s*$/, "");
  vm.runInContext(
    `${source}
renderJobList = () => {};
renderJob = () => {};
showMainView = () => {};
globalThis.__tab = {
  state, installAuthCoordination, publishAuthChange, reconcilePrincipal, openJob,
};`,
    context,
    { filename: appPath.pathname },
  );
  context.__tab.installAuthCoordination();
  return { context, document, nodes, tab: context.__tab };
}

const first = makeTab();
const second = makeTab();
second.tab.state.account = { id: "old-user", principal_marker: "old-principal" };
second.tab.state.principalMarker = "old-principal";
second.tab.state.jobs = [{ id: "old-job" }];
second.tab.state.currentJob = { id: "old-job", result: { confidential: true } };
second.document.getElementById("api-key-output").textContent = "unr_two_tab_secret";
second.document.getElementById("result-table").replaceChildren({ confidential: true });
second.context.fetch = () => new Promise(() => {});

first.tab.publishAuthChange("logout");
assert.equal(second.tab.state.account, null);
assert.equal(second.tab.state.currentJob, null);
assert.equal(second.document.getElementById("api-key-output").textContent, "");
assert.deepEqual(second.document.getElementById("result-table").children, []);
assert.equal(second.tab.state.suppressPrincipalReconcileUntil, Number.POSITIVE_INFINITY);
let prematurePrincipalFetch = false;
second.context.fetch = async () => {
  prematurePrincipalFetch = true;
  throw new Error("old session must not be reconciled while logout is pending");
};
await second.tab.reconcilePrincipal();
assert.equal(prematurePrincipalFetch, false);

const reopened = makeTab();
assert.equal(reopened.tab.state.suppressPrincipalReconcileUntil, Number.POSITIVE_INFINITY);
let reopenedPrincipalFetch = false;
reopened.context.fetch = async () => {
  reopenedPrincipalFetch = true;
  throw new Error("a persisted logout barrier must block principal restoration");
};
await reopened.tab.reconcilePrincipal();
assert.equal(reopenedPrincipalFetch, false);

second.context.fetch = async (path) => {
  assert.equal(path, "/api/me");
  return {
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => ({
      id: "new-user",
      email: "new@example.com",
      credits: 3,
      credit_pack_size: 100,
      billing_configured: false,
      demo_account: false,
      principal_marker: "new-principal",
    }),
  };
};
reopened.context.fetch = second.context.fetch;
first.tab.publishAuthChange("authenticated");
await new Promise((resolve) => setImmediate(resolve));
assert.equal(second.tab.state.account.id, "new-user");
assert.equal(second.tab.state.principalMarker, "new-principal");
assert.equal(reopened.tab.state.account.id, "new-user");
assert.equal(reopened.tab.state.principalMarker, "new-principal");

let releaseOldJob;
second.context.fetch = (path) => {
  if (path.includes("old-delayed")) {
    return new Promise((resolve) => { releaseOldJob = resolve; });
  }
  return Promise.resolve({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => ({ id: "new-selected", status: "review", result: null }),
  });
};
const delayed = second.tab.openJob("old-delayed");
await Promise.resolve();
await second.tab.openJob("new-selected");
releaseOldJob({
  ok: true,
  status: 200,
  headers: { get: () => "application/json" },
  json: async () => ({ id: "old-delayed", status: "review", result: { confidential: true } }),
});
await delayed;
assert.equal(second.tab.state.currentJob.id, "new-selected");
