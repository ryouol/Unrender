import assert from "node:assert/strict";
import { appPath, source } from "./browser_product_source.mjs";
import vm from "node:vm";
import { TextEncoder } from "node:util";
import { webcrypto } from "node:crypto";

const AUTH_KEY = "unrender.auth-state.v2";
const LEGACY_AUTH_KEY = "unrender.auth-change.v1";
const storageValues = new Map();
const tabs = [];
const channelMembers = new Map();

class FakeNode {
  constructor() {
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
  close() { this.open = false; }
  removeAttribute(name) { this.attributes.delete(name); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  addEventListener() {}
  querySelector() { return new FakeNode(); }
  querySelectorAll() { return []; }
  focus() {}
}

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

function makeTab({ broadcast = true } = {}) {
  const nodes = new Map();
  const documentListeners = new Map();
  const windowListeners = new Map();
  const addListener = (map, type, listener) => {
    const listeners = map.get(type) || [];
    listeners.push(listener);
    map.set(type, listeners);
  };
  const document = {
    cookie: "unrender_csrf=shared",
    visibilityState: "visible",
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, new FakeNode());
      return nodes.get(id);
    },
    addEventListener(type, listener) { addListener(documentListeners, type, listener); },
  };
  const owner = { windowListeners };
  const scheduledTimers = new Map();
  let nextTimer = 1;
  const localStorage = {
    getItem(key) { return storageValues.get(key) ?? null; },
    setItem(key, value) {
      const oldValue = storageValues.get(key) ?? null;
      storageValues.set(key, value);
      for (const peer of tabs) {
        if (peer === owner) continue;
        const event = { key, oldValue, newValue: value };
        if (peer.deferStorageEvents) {
          peer.pendingStorageEvents.push(event);
          continue;
        }
        for (const listener of peer.windowListeners.get("storage") || []) {
          listener(event);
        }
      }
    },
    removeItem(key) {
      const oldValue = storageValues.get(key) ?? null;
      storageValues.delete(key);
      for (const peer of tabs) {
        if (peer === owner) continue;
        const event = { key, oldValue, newValue: null };
        if (peer.deferStorageEvents) {
          peer.pendingStorageEvents.push(event);
          continue;
        }
        for (const listener of peer.windowListeners.get("storage") || []) {
          listener(event);
        }
      }
    },
  };
  const context = {
    AbortController,
    BroadcastChannel: broadcast ? SharedBroadcastChannel : undefined,
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
    URL,
    crypto: webcrypto,
    document,
    encodeURIComponent,
    decodeURIComponent,
    fetch: null,
    localStorage,
    window: {
      clearTimeout(timer) { scheduledTimers.delete(timer); },
      setTimeout(callback, delay = 0) {
        const timer = nextTimer;
        nextTimer += 1;
        scheduledTimers.set(timer, { callback, delay });
        return timer;
      },
      addEventListener(type, listener) { addListener(windowListeners, type, listener); },
    },
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(
    `${source}
renderJobList = () => {};
renderLibrary = () => {};
loadProjects = async () => {};
renderJob = () => {};
showMainView = () => {};
globalThis.__tab = {
  state, installAuthCoordination, publishAuthChange, reconcilePrincipal, openJob, logout,
  handleExternalAuthChange, syncAuthRecordFromStorage, readDurableAuthRecord,
};`,
    context,
    { filename: appPath.pathname },
  );
  tabs.push(owner);
  context.__tab.installAuthCoordination();
  return {
    context,
    document,
    nodes,
    tab: context.__tab,
    windowListeners,
    documentListeners,
  };
}

function makeLegacyV1Tab({ deferStorageEvents = false } = {}) {
  const windowListeners = new Map();
  const pendingStorageEvents = [];
  const owner = { windowListeners, deferStorageEvents, pendingStorageEvents };
  const state = {
    authEpoch: 0,
    confidentialDom: "old-account-chart",
    restoredOldPrincipal: false,
    suppressPrincipalReconcileUntil: 0,
    observedV2Phase: null,
    sessionActive: true,
  };
  let releaseOldResponse;
  const oldResponse = new Promise((resolve) => { releaseOldResponse = resolve; });
  const reconciliations = [];
  const showPublic = () => {
    state.authEpoch += 1;
    state.confidentialDom = null;
  };
  const reconcilePrincipal = () => {
    const epoch = state.authEpoch;
    const authorized = state.sessionActive;
    const operation = (async () => {
      await oldResponse;
      if (epoch !== state.authEpoch) return;
      if (!authorized) return;
      state.confidentialDom = "old-account-chart-restored";
      state.restoredOldPrincipal = true;
    })();
    reconciliations.push(operation);
    return operation;
  };
  // This is the deployed ab13830/v1 handler contract, including its storage
  // listener dropping event detail. The v2 compatibility BroadcastChannel must
  // therefore deliver the reason and advance the old auth epoch.
  const authChangeReason = (event) => {
    const raw = typeof event === "string" ? event : event?.data ?? event?.newValue;
    try { return JSON.parse(raw)?.reason || "unknown"; }
    catch (_) { return "unknown"; }
  };
  const handleExternalAuthChange = (event) => {
    const reason = authChangeReason(event);
    if (["logout", "session-ended"].includes(reason)) {
      state.suppressPrincipalReconcileUntil = Number.POSITIVE_INFINITY;
      state.observedV2Phase = JSON.parse(storageValues.get(AUTH_KEY)).phase;
    } else {
      state.suppressPrincipalReconcileUntil = 0;
    }
    showPublic();
    if (reason !== "logout" && reason !== "session-ended") void reconcilePrincipal();
  };
  const channel = new SharedBroadcastChannel(LEGACY_AUTH_KEY);
  channel.addEventListener("message", handleExternalAuthChange);
  windowListeners.set("storage", [
    (event) => {
      if (event.key === LEGACY_AUTH_KEY) handleExternalAuthChange();
    },
  ]);
  tabs.push(owner);
  return {
    state,
    startPrincipalCheck() { return reconcilePrincipal(); },
    setSessionActive(value) { state.sessionActive = value; },
    pendingStorageEventCount() {
      return pendingStorageEvents.filter((event) => event.key === LEGACY_AUTH_KEY).length;
    },
    flushStorageEvents() {
      while (pendingStorageEvents.length) {
        const event = pendingStorageEvents.shift();
        for (const listener of windowListeners.get("storage") || []) listener(event);
      }
    },
    async releaseAndSettle() {
      releaseOldResponse();
      await Promise.all(reconciliations);
    },
  };
}

function setPrivateState(target, suffix = "old") {
  target.tab.state.account = { id: `${suffix}-user`, principal_marker: `${suffix}-principal` };
  target.tab.state.principalMarker = `${suffix}-principal`;
  target.tab.state.jobs = [{ id: `${suffix}-job` }];
  target.tab.state.currentJob = { id: `${suffix}-job`, result: { confidential: true } };
  target.document.getElementById("api-key-output").textContent = `unr_${suffix}_secret`;
  target.document.getElementById("result-table").replaceChildren({ confidential: true });
}

const accountPayload = {
  id: "new-user",
  email: "new@example.com",
  credits: 3,
  credit_pack_size: 100,
  billing_configured: false,
  demo_account: false,
  principal_marker: "new-principal",
};
const authenticatedFetch = async (path) => {
  if (path === "/api/me") {
    return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => accountPayload };
  }
  if (path.startsWith("/api/jobs")) {
    return {
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: async () => ({ items: [], next_cursor: null }),
    };
  }
  throw new Error(`unexpected path ${path}`);
};

// A logout barrier written by the previous browser release is promoted before
// any principal check and remains durable through a terminal non-auth state.
// Only an explicit authenticated transition may retire it, after the new
// cookie exists.
storageValues.set(LEGACY_AUTH_KEY, JSON.stringify({
  reason: "logout", nonce: "legacy-release-tab",
}));
const upgraded = makeTab({ broadcast: false });
let legacyPrincipalChecks = 0;
upgraded.context.fetch = async (path) => {
  if (path === "/api/me") legacyPrincipalChecks += 1;
  return authenticatedFetch(path);
};
await upgraded.tab.reconcilePrincipal();
assert.equal(legacyPrincipalChecks, 0);
assert.equal(upgraded.tab.readDurableAuthRecord().phase, "logout-failed");
assert.equal(storageValues.has(LEGACY_AUTH_KEY), true);
await upgraded.tab.publishAuthChange("session-ended", {
  expected: upgraded.tab.readDurableAuthRecord(),
});
assert.equal(JSON.parse(storageValues.get(LEGACY_AUTH_KEY)).reason, "session-ended");
storageValues.clear();
tabs.length = 0;
channelMembers.clear();

// A refreshed v2 tab wakes the exact deployed v1 handler after its durable v2
// barrier is committed. While the old cookie may still work, only the channel
// is touched: the deployed v1 storage listener drops event detail and therefore
// cannot safely receive a storage mutation before server revocation.
const rolloutAuthenticated = {
  version: 2,
  revision: 1,
  id: "rollout-authenticated",
  phase: "authenticated",
  principalMarker: "rollout-principal",
};
storageValues.set(AUTH_KEY, JSON.stringify(rolloutAuthenticated));
const modernRolloutTab = makeTab();
let releaseRolloutLogout;
modernRolloutTab.context.fetch = (path) => {
  if (path === "/api/auth/logout") {
    return new Promise((resolve) => { releaseRolloutLogout = resolve; });
  }
  return authenticatedFetch(path);
};
const deployedV1Tab = makeLegacyV1Tab({ deferStorageEvents: true });
const preLogoutPrincipalCheck = deployedV1Tab.startPrincipalCheck();
const rolloutLogout = modernRolloutTab.tab.logout();
for (let turn = 0; turn < 10 && deployedV1Tab.state.confidentialDom; turn += 1) {
  await new Promise((resolve) => setImmediate(resolve));
}
assert.equal(modernRolloutTab.tab.readDurableAuthRecord().phase, "logout-pending");
assert.equal(deployedV1Tab.state.confidentialDom, null);
assert.equal(
  deployedV1Tab.state.suppressPrincipalReconcileUntil,
  Number.POSITIVE_INFINITY,
);
assert.equal(deployedV1Tab.state.observedV2Phase, "logout-pending");
assert.equal(storageValues.has(LEGACY_AUTH_KEY), false);
assert.equal(deployedV1Tab.pendingStorageEventCount(), 0);
// The server revokes the shared cookie before terminal legacy persistence.
// Deliver that storage task only after every BroadcastChannel message: its
// dropped detail may start a check, but that check is now unauthorized (401).
deployedV1Tab.setSessionActive(false);
releaseRolloutLogout({ ok: true, status: 200 });
assert.equal(await rolloutLogout, true);
assert.equal(JSON.parse(storageValues.get(LEGACY_AUTH_KEY)).reason, "logout");
assert.equal(deployedV1Tab.pendingStorageEventCount() > 0, true);
deployedV1Tab.flushStorageEvents();
await deployedV1Tab.releaseAndSettle();
await preLogoutPrincipalCheck;
assert.equal(deployedV1Tab.state.restoredOldPrincipal, false);
assert.equal(deployedV1Tab.state.confidentialDom, null);
storageValues.clear();
tabs.length = 0;
channelMembers.clear();

// A failed global logout likewise never mutates legacy storage while the old
// cookie can still authorize. Live v1 tabs stay channel-quarantined, and their
// already-running old response is fenced even after every channel task ran.
storageValues.set(AUTH_KEY, JSON.stringify(rolloutAuthenticated));
const failedRolloutTab = makeTab();
failedRolloutTab.context.fetch = async (path) => {
  if (path === "/api/auth/logout") return { ok: false, status: 503 };
  if (path === "/api/me") {
    return { ok: true, status: 200, headers: { get: () => "application/json" } };
  }
  return authenticatedFetch(path);
};
const failedLegacyTab = makeLegacyV1Tab({ deferStorageEvents: true });
const failedOldCheck = failedLegacyTab.startPrincipalCheck();
assert.equal(await failedRolloutTab.tab.logout(), false);
assert.equal(failedRolloutTab.tab.readDurableAuthRecord().phase, "logout-failed");
assert.equal(storageValues.has(LEGACY_AUTH_KEY), false);
assert.equal(failedLegacyTab.pendingStorageEventCount(), 0);
await failedLegacyTab.releaseAndSettle();
await failedOldCheck;
assert.equal(failedLegacyTab.state.restoredOldPrincipal, false);
assert.equal(failedLegacyTab.state.confidentialDom, null);
assert.equal(
  failedLegacyTab.state.suppressPrincipalReconcileUntil,
  Number.POSITIVE_INFINITY,
);
storageValues.clear();
tabs.length = 0;
channelMembers.clear();

// A legacy logout always wins in memory when v2 persistence throws or silently
// ignores the promoted record. Neither failure mode can consult /api/me or keep
// private state visible by falling back to the older authenticated v2 record.
const persistenceAuthenticated = {
  version: 2,
  revision: 3,
  id: "persistence-authenticated",
  phase: "authenticated",
  principalMarker: "persistence-principal",
};
storageValues.set(AUTH_KEY, JSON.stringify(persistenceAuthenticated));
const throwingStorage = makeTab({ broadcast: false });
const silentStorage = makeTab({ broadcast: false });
setPrivateState(throwingStorage, "throwing-storage");
setPrivateState(silentStorage, "silent-storage");
storageValues.set(LEGACY_AUTH_KEY, JSON.stringify({
  reason: "logout", nonce: "persistence-failure",
}));
throwingStorage.context.localStorage.setItem = () => {
  throw new Error("storage denied");
};
silentStorage.context.localStorage.setItem = () => {};
let failedPersistencePrincipalChecks = 0;
for (const target of [throwingStorage, silentStorage]) {
  target.context.fetch = async (path) => {
    if (path === "/api/me") failedPersistencePrincipalChecks += 1;
    return authenticatedFetch(path);
  };
  const promoted = target.tab.syncAuthRecordFromStorage({ wipe: true });
  assert.equal(promoted.phase, "logout-failed");
  assert.equal(target.tab.state.authRecord.phase, "logout-failed");
  assert.equal(target.tab.state.account, null);
  assert.equal(target.tab.state.currentJob, null);
  await target.tab.reconcilePrincipal();
}
assert.equal(JSON.parse(storageValues.get(AUTH_KEY)).phase, "authenticated");
assert.equal(failedPersistencePrincipalChecks, 0);
storageValues.clear();
tabs.length = 0;
channelMembers.clear();

// Retiring a retained legacy barrier happens before an explicit-login v2
// publish, so a synchronous peer storage handler cannot promote the new
// authenticated record back to logout-failed.
const unconfirmedRecord = {
  version: 2,
  revision: 7,
  id: "lost-logout-response",
  phase: "signed-out-unconfirmed",
  principalMarker: null,
};
storageValues.set(AUTH_KEY, JSON.stringify(unconfirmedRecord));
storageValues.set(LEGACY_AUTH_KEY, JSON.stringify({
  reason: "logout", nonce: "retained-until-recovery",
}));
const recoveryWriter = makeTab();
const recoveryPeer = makeTab();
recoveryWriter.context.fetch = authenticatedFetch;
recoveryPeer.context.fetch = authenticatedFetch;
const recovered = await recoveryWriter.tab.publishAuthChange("authenticated", {
  explicitLogin: true,
  expected: unconfirmedRecord,
  principalMarker: "new-principal",
});
assert.equal(recovered.phase, "authenticated");
assert.equal(recoveryPeer.tab.readDurableAuthRecord().phase, "authenticated");
assert.equal(storageValues.has(LEGACY_AUTH_KEY), false);
storageValues.clear();
tabs.length = 0;
channelMembers.clear();

const first = makeTab();
const second = makeTab();
const storageOnly = makeTab({ broadcast: false });
setPrivateState(second);
setPrivateState(storageOnly, "storage-only");

const pending = await first.tab.publishAuthChange("logout");
assert.equal(pending.phase, "logout-pending");
for (const target of [second, storageOnly]) {
  assert.equal(target.tab.state.account, null);
  assert.equal(target.tab.state.currentJob, null);
  assert.equal(target.document.getElementById("api-key-output").textContent, "");
  assert.deepEqual(target.document.getElementById("result-table").children, []);
  assert.equal(target.tab.state.suppressPrincipalReconcileUntil, Number.POSITIVE_INFINITY);
}

let blockedFetches = 0;
second.context.fetch = async () => { blockedFetches += 1; throw new Error("must stay blocked"); };
await second.tab.reconcilePrincipal();
assert.equal(blockedFetches, 0);

// A new tab/reload inherits the durable barrier before any principal fetch.
const reopened = makeTab();
reopened.context.fetch = async () => { blockedFetches += 1; throw new Error("must stay blocked"); };
await reopened.tab.reconcilePrincipal();
assert.equal(blockedFetches, 0);
assert.equal(reopened.tab.state.suppressPrincipalReconcileUntil, Number.POSITIVE_INFINITY);

// Malformed and reordered notification payloads cannot lower canonical storage.
const durablePending = storageValues.get(AUTH_KEY);
second.tab.handleExternalAuthChange({ data: "not-json" });
second.tab.handleExternalAuthChange({ data: JSON.stringify({
  version: 2, revision: 999, id: "old-auth-event", phase: "authenticated",
  principalMarker: "old-principal",
}) });
assert.equal(storageValues.get(AUTH_KEY), durablePending);
assert.equal(second.tab.state.account, null);
assert.equal(blockedFetches, 0);

// A missed storage event is recovered on focus/BFCache lifecycle boundaries.
const lifecycle = makeTab();
const authenticatedRecord = {
  version: 2, revision: pending.revision + 1, id: "authenticated-before-miss",
  phase: "authenticated", principalMarker: "old-principal",
};
storageValues.set(AUTH_KEY, JSON.stringify(authenticatedRecord));
lifecycle.tab.syncAuthRecordFromStorage({ wipe: false });
setPrivateState(lifecycle, "old");
const missedSignedOut = {
  version: 2, revision: authenticatedRecord.revision + 1, id: "missed-signed-out",
  phase: "signed-out", principalMarker: null,
};
storageValues.set(AUTH_KEY, JSON.stringify(missedSignedOut));
lifecycle.context.fetch = async () => { blockedFetches += 1; throw new Error("must stay blocked"); };
for (const listener of lifecycle.windowListeners.get("pageshow") || []) listener({ persisted: true });
for (const listener of lifecycle.windowListeners.get("focus") || []) listener();
assert.equal(lifecycle.tab.state.account, null);
assert.equal(blockedFetches, 0);

// Only an explicit login transition from terminal signed-out can clear the barrier.
for (const target of [second, reopened, storageOnly, lifecycle]) target.context.fetch = authenticatedFetch;
first.context.fetch = authenticatedFetch;
const signedOut = first.tab.readDurableAuthRecord();
first.tab.syncAuthRecordFromStorage({ wipe: false });
const authenticated = await first.tab.publishAuthChange("authenticated", {
  explicitLogin: true,
  expected: signedOut,
  principalMarker: "new-principal",
});
assert.equal(authenticated.phase, "authenticated");
for (let turn = 0; turn < 10; turn += 1) {
  await new Promise((resolve) => setImmediate(resolve));
}
for (const [index, target] of [second, reopened, storageOnly, lifecycle].entries()) {
  assert.equal(
    target.tab.state.account?.id,
    "new-user",
    `tab ${index} did not reconcile: ${JSON.stringify({
      status: target.tab.state.logoutStatus,
      record: target.tab.state.authRecord,
      toast: target.document.getElementById("toast").textContent,
    })}`,
  );
  assert.equal(target.tab.state.principalMarker, "new-principal");
}

// Per-selection epochs prevent a delayed old selection from overwriting a newer one.
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

// A still-open v1 tab can publish a logout after v2 tabs authenticated. The
// legacy storage wakeup supersedes the v2 authenticated record fail-closed.
setPrivateState(second, "mixed-version");
let mixedVersionPrincipalChecks = 0;
second.context.fetch = async (path) => {
  if (path === "/api/me") mixedVersionPrincipalChecks += 1;
  return authenticatedFetch(path);
};
first.context.localStorage.setItem(LEGACY_AUTH_KEY, JSON.stringify({
  reason: "logout", nonce: "still-open-v1-tab",
}));
assert.equal(second.tab.state.account, null);
assert.equal(second.tab.state.currentJob, null);
assert.equal(second.tab.readDurableAuthRecord().phase, "logout-failed");
assert.equal(mixedVersionPrincipalChecks, 0);
