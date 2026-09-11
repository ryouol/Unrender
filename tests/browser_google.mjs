import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { appPath, source } from "./browser_product_source.mjs";
import test from "node:test";
import vm from "node:vm";

const AUTH_KEY = "unrender.auth-state.v2";
const LEGACY_AUTH_KEY = "unrender.auth-change.v1";
const INTENT_KEY = "unrender.google-intent.v1";
const INTENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee".repeat(2);

class FakeNode {
  constructor() {
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.textContent = "";
    this.value = "";
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.attributes = new Map();
    this.classList = { toggle() {}, add() {}, remove() {} };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  reset() { this.value = ""; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() {}
  remove() {}
  addEventListener() {}
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  removeAttribute(name) { this.attributes.delete(name); }
  querySelector() { return new FakeNode(); }
  querySelectorAll() { return []; }
}

function storage() {
  const values = new Map();
  return {
    values,
    getItem(key) { return values.get(key) ?? null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); },
  };
}

function jsonResponse(body, status = 200) {
  return { ok: status < 400, status, headers: new Headers({ "Content-Type": "application/json" }), json: async () => body };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function record(phase, revision = 1) {
  return { version: 2, revision, id: `state-${revision}`, phase, principalMarker: phase === "authenticated" ? `principal-${revision}` : null };
}

function harness({ path = "/app", query = "" } = {}) {
  const nodes = new Map();
  const localStorage = storage();
  const sessionStorage = storage();
  const assignments = [];
  const requests = [];
  const document = {
    cookie: "unrender_csrf=browser-csrf",
    visibilityState: "visible",
    body: new FakeNode(),
    createElement() { return new FakeNode(); },
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, new FakeNode());
      return nodes.get(id);
    },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
  const location = { pathname: path, search: query, assign(value) { assignments.push(value); } };
  const context = {
    AbortController, Error, FormData, Headers, Intl, JSON, Map, Math, Number, Object,
    Promise, Set, String, TextEncoder, Uint8Array, URL, URLSearchParams,
    crypto: webcrypto, document, encodeURIComponent, decodeURIComponent, localStorage, sessionStorage,
    navigator: {},
    window: {
      location,
      history: { replaceState(_state, _title, value) { location.pathname = value; } },
      clearTimeout() {}, setTimeout() { return 1; }, addEventListener() {},
    },
  };
  const environment = {
    context, localStorage, sessionStorage, assignments, requests, document,
    respond: () => { throw new Error("Unexpected network request"); },
  };
  context.fetch = async (path, options) => {
    requests.push({ path, options });
    return environment.respond(path, options);
  };
  vm.createContext(context);
  // Execute production functions intact; only browser surfaces and the network
  // are simulated. In particular api(), boot(), and durable auth publication run.
  vm.runInContext(`${source}\nglobalThis.testApi = {
    startGoogleLogin, completeGoogleLogin, updateGoogleLoginGate, boot,
    readDurableAuthRecord, syncAuthRecordFromStorage, reconcilePrincipal, state,
  };`, context, { filename: appPath.pathname });
  const api = context.testApi;
  api.state.publicConfig.google_available = true;
  const install = (value) => {
    localStorage.setItem(AUTH_KEY, JSON.stringify(value));
    api.syncAuthRecordFromStorage({ wipe: false });
  };
  const pending = (expected = api.readDurableAuthRecord()) => {
    sessionStorage.setItem(INTENT_KEY, JSON.stringify({ intent: INTENT, expected }));
  };
  const start = () => {
    let prevented = false;
    api.startGoogleLogin({ preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
  };
  return Object.assign(environment, { api, install, pending, start });
}

test("Google starts with a tab-local random intent tied to the current durable account", () => {
  for (const phase of [null, "authenticated", "signed-out", "signed-out-unconfirmed"]) {
    const h = harness();
    if (phase) h.install(record(phase));
    const expected = h.api.readDurableAuthRecord();
    h.start();
    const pending = JSON.parse(h.sessionStorage.getItem(INTENT_KEY));
    assert.match(pending.intent, /^[a-f0-9-]{72}$/);
    assert.deepEqual(pending.expected, JSON.parse(JSON.stringify(expected)));
    assert.deepEqual(h.assignments, [`/auth/google/start?intent=${pending.intent}`]);
    assert.equal(h.requests.length, 0);
    h.start();
    assert.notEqual(JSON.parse(h.sessionStorage.getItem(INTENT_KEY)).intent, pending.intent);
  }
});

test("Google start cannot navigate when tab storage rejects or silently loses intent", () => {
  for (const mode of ["write-throws", "read-throws", "write-lost"]) {
    const h = harness();
    if (mode === "write-throws") h.sessionStorage.setItem = () => { throw new Error("denied"); };
    if (mode === "read-throws") h.sessionStorage.getItem = () => { throw new Error("denied"); };
    if (mode === "write-lost") h.sessionStorage.setItem = () => {};
    h.start();
    assert.deepEqual(h.assignments, []);
    assert.equal(h.requests.length, 0);
    assert.match(h.document.getElementById("auth-error").textContent, /Allow browser storage/);
  }
});

test("durable pending or failed logout blocks both Google buttons and completion", async () => {
  for (const phase of ["logout-pending", "logout-failed"]) {
    const h = harness();
    h.install(record(phase));
    h.api.updateGoogleLoginGate();
    for (const id of ["google-signin", "google-signup"]) {
      assert.equal(h.document.getElementById(id).attributes.get("aria-disabled"), "true");
    }
    h.start();
    assert.deepEqual(h.assignments, []);
    h.pending();
    await assert.rejects(h.api.completeGoogleLogin("/app"), /account changed/);
    assert.equal(h.requests.length, 0);
    assert.equal(h.api.readDurableAuthRecord().phase, phase);
  }
});

test("an in-flight logout and a migrated legacy logout block a fresh Google start", () => {
  const pendingLogout = harness();
  pendingLogout.api.state.logoutRequest = Promise.resolve();
  pendingLogout.start();
  assert.deepEqual(pendingLogout.assignments, []);

  const legacy = harness();
  legacy.localStorage.setItem(LEGACY_AUTH_KEY, JSON.stringify({ reason: "logout", id: "old-tab" }));
  legacy.api.syncAuthRecordFromStorage({ wipe: false });
  legacy.start();
  assert.deepEqual(legacy.assignments, []);
  assert.equal(legacy.api.readDurableAuthRecord().phase, "logout-failed");
});

test("missing intent and returns on a different route never complete Google login", async () => {
  const missing = harness();
  await missing.api.completeGoogleLogin("/app");
  assert.equal(missing.requests.length, 0);
  assert.equal(missing.api.readDurableAuthRecord(), null);
  const otherRoute = harness();
  otherRoute.pending();
  await otherRoute.api.completeGoogleLogin("/login");
  assert.equal(otherRoute.requests.length, 0);
  assert.equal(otherRoute.sessionStorage.getItem(INTENT_KEY), null);
});

test("malformed or stale saved intents are consumed without any authenticated request", async () => {
  const invalid = [
    "{", "null", "[]", "{}",
    JSON.stringify({ intent: INTENT }),
    JSON.stringify({ intent: "not-a-nonce", expected: null }),
    JSON.stringify({ intent: "x".repeat(72), expected: null }),
    JSON.stringify({ intent: INTENT, expected: {} }),
    JSON.stringify({ intent: INTENT, expected: record("authenticated") }),
  ];
  for (const encoded of invalid) {
    const h = harness();
    h.sessionStorage.setItem(INTENT_KEY, encoded);
    await assert.rejects(h.api.completeGoogleLogin("/app"));
    assert.equal(h.sessionStorage.getItem(INTENT_KEY), null);
    assert.equal(h.requests.length, 0);
    assert.equal(h.api.readDurableAuthRecord(), null);
  }
});

test("a tab returning from Google cannot replace an account established in another tab", async () => {
  const h = harness();
  h.install(record("authenticated"));
  h.pending();
  h.install(record("authenticated", 2));
  await assert.rejects(h.api.completeGoogleLogin("/app"), /account changed/);
  assert.equal(h.requests.length, 0);
  assert.equal(h.api.readDurableAuthRecord().principalMarker, "principal-2");
});

test("unreadable or unconsumable tab storage cannot submit a Google completion", async () => {
  const unreadable = harness();
  unreadable.sessionStorage.getItem = () => { throw new Error("denied"); };
  await unreadable.api.completeGoogleLogin("/app");
  assert.equal(unreadable.requests.length, 0);
  const unconsumable = harness();
  unconsumable.pending();
  unconsumable.sessionStorage.removeItem = () => { throw new Error("denied"); };
  await assert.rejects(unconsumable.api.completeGoogleLogin("/app"), /could not be confirmed/);
  assert.equal(unconsumable.requests.length, 0);
});

test("completion consumes intent once, posts with CSRF, and publishes the server principal", async () => {
  const h = harness();
  h.install(record("signed-out"));
  h.pending();
  h.respond = (path, options) => {
    assert.equal(path, "/api/auth/google/complete");
    assert.equal(h.sessionStorage.getItem(INTENT_KEY), null);
    assert.equal(options.method, "POST");
    assert.equal(options.headers.get("X-CSRF-Token"), "browser-csrf");
    assert.deepEqual(JSON.parse(options.body), { intent: INTENT });
    return jsonResponse({ principal_marker: "new-google-principal" });
  };
  await h.api.completeGoogleLogin("/app");
  assert.equal(h.api.readDurableAuthRecord().phase, "authenticated");
  assert.equal(h.api.readDurableAuthRecord().principalMarker, "new-google-principal");
  assert.equal(h.api.readDurableAuthRecord().revision, 2);
  assert.equal(h.api.state.logoutStatus, "idle");
  await h.api.completeGoogleLogin("/app");
  assert.equal(h.requests.length, 1);
});

test("expired server intent stays consumed and cannot publish an account", async () => {
  const h = harness();
  h.pending();
  h.respond = () => jsonResponse({ error: { code: "google_expired", message: "Please try Google again." } }, 400);
  await assert.rejects(h.api.completeGoogleLogin("/app"), (error) => error.code === "google_expired");
  assert.equal(h.api.readDurableAuthRecord(), null);
  assert.equal(h.sessionStorage.getItem(INTENT_KEY), null);
  await h.api.completeGoogleLogin("/app");
  assert.equal(h.requests.length, 1);
});

test("a completion without a server principal cannot publish authentication", async () => {
  const h = harness();
  h.pending();
  h.respond = () => jsonResponse({});
  await assert.rejects(h.api.completeGoogleLogin("/app"), (error) => error.code === "stale_auth_context");
  assert.equal(h.api.readDurableAuthRecord(), null);
});

test("logout while completion is fetching or parsing its body prevents auth revival", async () => {
  for (const boundary of ["response", "body"]) {
    const h = harness();
    const reached = deferred();
    const paused = deferred();
    h.pending();
    h.respond = () => {
      const response = jsonResponse({ principal_marker: "obsolete-google-principal" });
      if (boundary === "response") {
        reached.resolve();
        return paused.promise.then(() => response);
      }
      response.json = () => { reached.resolve(); return paused.promise; };
      return response;
    };
    const completion = h.api.completeGoogleLogin("/app");
    await reached.promise;
    h.install(record("logout-pending"));
    paused.resolve({ principal_marker: "obsolete-google-principal" });
    await assert.rejects(completion, (error) => error.code === "stale_auth_context");
    assert.equal(h.api.readDurableAuthRecord().phase, "logout-pending");
    assert.equal(h.api.state.account, null);
    assert.equal(h.sessionStorage.getItem(INTENT_KEY), null);
  }
});

test("auth publication compares the durable record again after waiting for its lock", async () => {
  const h = harness();
  const reached = deferred();
  const paused = deferred();
  h.context.navigator.locks = { request: async (_name, _options, callback) => {
    reached.resolve();
    await paused.promise;
    return callback();
  } };
  h.pending();
  h.respond = () => jsonResponse({ principal_marker: "obsolete-google-principal" });
  const completion = h.api.completeGoogleLogin("/app");
  await reached.promise;
  h.install(record("logout-failed"));
  paused.resolve();
  await assert.rejects(completion, (error) => error.code === "stale_auth_context");
  assert.equal(h.api.readDurableAuthRecord().phase, "logout-failed");
});

test("completion fails closed if authenticated publication cannot persist", async () => {
  const h = harness();
  h.pending();
  h.respond = () => jsonResponse({ principal_marker: "google-principal" });
  h.localStorage.setItem = () => {};
  await assert.rejects(h.api.completeGoogleLogin("/app"), /could not persist/);
  assert.equal(h.api.readDurableAuthRecord(), null);
  assert.equal(h.api.state.account, null);
});

test("query parameters cannot lower a persisted logout barrier or create an OAuth intent", async () => {
  for (const query of ["?google=success", "?google_complete=1", "?intent=" + INTENT, "?settings=account&reauthenticated=1&connected=1"]) {
    const h = harness({ query });
    h.install(record("logout-failed"));
    h.respond = (path) => {
      assert.equal(path, "/api/public-config");
      return jsonResponse({ registration_open: true, google_available: true });
    };
    await h.api.boot();
    assert.equal(h.api.state.googleCompletionPending, false);
    assert.equal(h.api.state.account, null);
    assert.equal(h.api.readDurableAuthRecord().phase, "logout-failed");
    assert.deepEqual(h.requests.map((request) => request.path), ["/api/public-config"]);
    assert.equal(h.document.getElementById("workspace-view").hidden, true);
  }
});

test("a success query without browser intent still requires an authoritative session", async () => {
  const h = harness({ query: "?google=success&google_complete=1&intent=" + INTENT });
  h.respond = (path) => {
    if (path === "/api/public-config") return jsonResponse({ google_available: true });
    assert.equal(path, "/api/me");
    return jsonResponse({ error: { code: "unauthorized", message: "Sign in first." } }, 401);
  };
  await h.api.boot();
  assert.deepEqual(h.requests.map((request) => request.path), ["/api/public-config", "/api/me"]);
  assert.equal(h.api.state.account, null);
  assert.equal(h.api.readDurableAuthRecord(), null);
  assert.equal(h.document.getElementById("workspace-view").hidden, true);
});

test("boot prevents lifecycle reconciliation while the Google exchange is pending", async () => {
  const h = harness();
  const reached = deferred();
  const paused = deferred();
  h.install(record("signed-out"));
  h.pending();
  h.respond = (path) => {
    if (path === "/api/public-config") return jsonResponse({ google_available: true });
    if (path === "/api/auth/google/complete") {
      reached.resolve();
      return paused.promise;
    }
    if (path === "/api/me") return jsonResponse({ id: "account", email: "chart@example.test", credits: 0, principal_marker: "google-principal" });
    if (path === "/api/jobs?limit=100") return jsonResponse({ items: [], next_cursor: null });
    if (path === "/api/projects") return jsonResponse({ items: [] });
    throw new Error(`Unexpected request: ${path}`);
  };
  const boot = h.api.boot();
  await reached.promise;
  await h.api.reconcilePrincipal();
  assert.deepEqual(h.requests.map((request) => request.path), ["/api/public-config", "/api/auth/google/complete"]);
  assert.equal(h.api.state.account, null);
  paused.resolve(jsonResponse({ principal_marker: "google-principal" }));
  await boot;
  assert.equal(h.api.state.googleCompletionPending, false);
  assert.equal(h.api.state.account.id, "account");
  assert.equal(h.api.readDurableAuthRecord().principalMarker, "google-principal");
  assert.equal(h.document.getElementById("workspace-view").hidden, false);
  assert.equal(h.document.getElementById("home-button").href, "/app");
});
