import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { TextEncoder } from "node:util";
import { webcrypto } from "node:crypto";

// Exercise real event handlers and editor rendering. Only network dependencies
// are replaced, so late replies must survive the same view fences as a browser.
const appPath = new URL("../unrender/product/static/app.js", import.meta.url);
const source = ["google.js", "library.js", "settings.js"].map((name) => fs.readFileSync(new URL(`../unrender/product/static/${name}`, import.meta.url), "utf8")).join("\n") + "\n" + fs.readFileSync(appPath, "utf8").replace(/\nbindEvents\(\);\nboot\(\);\s*$/, "");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function reached(stage) {
  let timer;
  try {
    await Promise.race([
      stage.promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Expected asynchronous stage was not reached")), 1500);
      }),
    ]);
  } finally { clearTimeout(timer); }
}

function makeJob(id = "chart-a", status = "review", title = `Saved ${id}`) {
  return {
    id, status, source_name: `${id}.png`, source_mime: "image/png", page_index: 0,
    updated_at: "2026-09-10T12:00:00Z", progress_stage: "Extracting values",
    result: ["review", "approved"].includes(status) ? {
      chart_type: "bar", title, x_axis: { label: "Quarter" }, y_axis: { label: "Revenue", unit: "USD" },
      series: [{ name: "Revenue", points: [{ x: "Q1", y: 12 }, { x: "Q2", y: 18 }] }],
    } : null,
  };
}

function harness({ authenticated = true } = {}) {
  const nodes = new Map();
  const storage = new Map();
  const createdUrls = [];
  const revokedUrls = [];
  const downloads = [];
  const windowListeners = new Map();
  const timers = new Map();
  let timerId = 0;

  class Node {
    constructor(tag = "div") {
      Object.assign(this, {
        tag, hidden: false, disabled: false, inert: false, open: false,
        textContent: "", value: "", children: [], dataset: {}, parent: null,
        style: { setProperty() {} }, attributes: new Map(), listeners: new Map(), fields: new Map(), focused: false,
      });
      const classes = new Set();
      this.classList = {
        contains: (name) => classes.has(name),
        add: (name) => classes.add(name),
        remove: (name) => classes.delete(name),
        toggle: (name, on = !classes.has(name)) => {
          if (on) classes.add(name); else classes.delete(name);
          return on;
        },
      };
    }
    append(...children) {
      for (const child of children) { child.parent = this; this.children.push(child); }
    }
    replaceChildren(...children) {
      for (const child of this.children) child.parent = null;
      this.children = [];
      this.append(...children);
      if (this.tag === "select") this.value = children.find((child) => child.selected)?.value || children[0]?.value || "";
    }
    get tBodies() { return this.children.filter((child) => child.tag === "tbody"); }
    get lastElementChild() { return this.children.at(-1); }
    get src() { return this.attributes.get("src") || ""; }
    set src(value) { this.attributes.set("src", value); }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    removeAttribute(name) { this.attributes.delete(name); }
    addEventListener(name, handler) {
      const handlers = this.listeners.get(name) || [];
      handlers.push(handler);
      this.listeners.set(name, handlers);
    }
    async dispatch(name, extra = {}) {
      const event = { target: this, currentTarget: this, preventDefault() {}, ...extra };
      for (const handler of this.listeners.get(name) || []) await handler(event);
    }
    async click() {
      if (this.disabled) return;
      if (this.tag === "a") downloads.push({ href: this.href, filename: this.download });
      await this.dispatch("click");
    }
    focus() { this.focused = true; }
    reset() {
      this.value = "";
      this.fields.clear();
      for (const input of this.querySelectorAll("input")) input.value = "";
    }
    reportValidity() { return true; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this); }
    querySelectorAll(selector) {
      const matches = (node) => {
        if (selector === "*") return true;
        if (/^[a-z]+$/.test(selector)) return node.tag === selector;
        const attributes = [...selector.matchAll(/\[data-([\w-]+)(?:="([^"]*)")?\]/g)];
        return attributes.length > 0 && attributes.every(([, key, value]) => {
          const camel = key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
          return camel in node.dataset && (value === undefined || node.dataset[camel] === value);
        });
      };
      return this.children.flatMap((child) => [
        ...(matches(child) ? [child] : []), ...child.querySelectorAll(selector),
      ]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  }

  const node = (id) => {
    if (!nodes.has(id)) nodes.set(id, new Node());
    return nodes.get(id);
  };
  node("chart-type-input").tag = "select";
  node("result-table").tag = "table";
  for (const id of ["chart-title-input", "x-label-input", "y-label-input", "y-unit-input"]) node(id).tag = "input";
  node("result-form").append(...[
    "chart-type-input", "chart-title-input", "x-label-input", "y-label-input", "y-unit-input",
    "result-table", "series-editor-list",
  ].map(node));
  for (const id of ["login-form", "register-form"]) node(id).append(new Node("input"));
  for (const name of ["upload", "extract", "review", "export"]) {
    const step = new Node("li");
    step.dataset.step = name;
    node("workflow-steps").append(step);
  }
  node("export-completion").hidden = true;
  node("toast").hidden = true;
  const document = {
    cookie: "unrender_csrf=test-secret", visibilityState: "visible", body: new Node("body"),
    querySelectorAll: () => [], getElementById: node, createElement: (tag) => new Node(tag), addEventListener() {},
  };
  class TestURL extends URL {
    static createObjectURL() {
      const value = `blob:test-${createdUrls.length + 1}`;
      createdUrls.push(value);
      return value;
    }
    static revokeObjectURL(value) { revokedUrls.push(value); }
  }
  class FormData {
    constructor(form) { this.fields = new Map(form?.fields); }
    get(name) { return this.fields.get(name) ?? null; }
  }
  const window = {
    location: { pathname: "/login" },
    history: { replaceState(_state, _unused, path) { window.location.pathname = path; } },
    confirm: () => true,
    setTimeout(handler) { timers.set(++timerId, handler); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    addEventListener(name, handler) { windowListeners.set(name, handler); },
  };
  const context = {
    AbortController, Error, FormData, Headers, Intl, JSON, Map, Math, Number, Object,
    Promise, Set, String, TextEncoder, Uint8Array, URL: TestURL, crypto: webcrypto,
    document, window, encodeURIComponent, decodeURIComponent,
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key),
    },
    fetch: async () => { throw new Error("Unexpected network request"); },
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(`${source}
    globalThis.test = {
      library, renderLibrary, showLibrary, closeLibraryDialog, editProject, deleteProject, moveChart,
      state, switchAuth, applyPublicConfig, renderJob, renderJobActions, markEditorDirty,
      showWorkspace,
      downloadExport, jobMutation, restoreVersion, saveCorrections, openJob, beginViewSelection,
      resetPrivateState, syncAuthRecordFromStorage, showPublic, deleteCurrentJob,
      updateUploadPreview,
    };
    bindEvents();
  `, context, { filename: appPath.pathname });
  const test = context.test;
  const replace = (name, implementation) => {
    context.replacement = implementation;
    vm.runInContext(`${name} = globalThis.replacement`, context);
    delete context.replacement;
  };
  replace("loadJobs", async () => {});
  replace("loadProjects", async () => {});
  replace("refreshAccount", async () => {});
  replace("renderJobList", () => {});
  if (authenticated) {
    storage.set("unrender.auth-state.v2", JSON.stringify({
      version: 2, revision: 1, id: "session-a", phase: "authenticated", principalMarker: "principal-a",
    }));
    test.syncAuthRecordFromStorage({ wipe: false });
    test.state.account = { id: "account-a", email: "a@example.com" };
    test.state.principalMarker = "principal-a";
  }
  const select = (job) => {
    test.beginViewSelection();
    test.state.currentJob = job;
    test.renderJob();
  };
  const editTitle = async (value) => {
    // Native inert prevents user edits and input events from reaching the form.
    if (node("result-form").inert) return false;
    node("chart-title-input").value = value;
    await node("result-form").dispatch("input", { target: node("chart-title-input") });
    return true;
  };
  return { test, node, context, window, windowListeners, replace, select, editTitle, createdUrls, revokedUrls, downloads };
}

let passed = 0;
async function check(name, run) {
  try { await run(); passed += 1; }
  catch (error) { error.message = `${name}: ${error.message}`; throw error; }
}

await check("closed registration keeps signup private and existing sign-in usable", async () => {
  const h = harness({ authenticated: false });
  h.window.location.pathname = "/signup";
  h.test.state.publicConfig = { registration_open: false, sample_available: false };
  h.test.applyPublicConfig();
  h.test.showPublic();
  assert.equal(h.window.location.pathname, "/signup");
  assert.equal(h.node("register-form").hidden, true);
  assert.equal(h.node("login-form").hidden, true);
  assert.match(h.node("auth-description").textContent, /invitation/i);
  await h.node("login-tab").click();
  assert.equal(h.window.location.pathname, "/login");
  assert.equal(h.node("login-form").hidden, false);
  assert.equal(h.node("register-form").hidden, true);
  assert.equal(h.node("login-form").querySelector("input").focused, true);
  const requests = [];
  h.replace("api", async (path, options) => { requests.push({ path, options }); return {}; });
  h.replace("fetchAccount", async () => ({ id: "account-a", principal_marker: "principal-a", email: "a@example.com", credits: 2 }));
  h.replace("publishAuthChange", async () => true);
  h.node("login-form").fields = new Map([["email", " a@example.com "], ["password", "example-password"]]);
  await h.node("login-form").dispatch("submit");
  assert.equal(requests[0].path, "/api/auth/login");
  assert.equal(requests[0].options.body.email, "a@example.com");
  assert.equal(requests[0].options.body.password, "example-password");
  assert.equal(h.test.state.account.id, "account-a");
  assert.equal(h.window.location.pathname, "/app");
  assert.equal(h.node("marketing-view").hidden, true);
  assert.equal(h.node("workspace-view").hidden, false);
  assert.equal(h.node("login-form").getAttribute("aria-busy"), null);
});

await check("open registration exposes the requested form", async () => {
  const h = harness({ authenticated: false });
  h.test.state.publicConfig.registration_open = true;
  await h.node("register-tab").click();
  assert.equal(h.window.location.pathname, "/signup");
  assert.equal(h.node("login-form").hidden, true);
  assert.equal(h.node("register-form").hidden, false);
  assert.equal(h.node("register-tab").getAttribute("aria-selected"), "true");
  assert.equal(h.node("register-form").querySelector("input").focused, true);
});

await check("public password signup discloses zero credits and opens a usable account without email", async () => {
  const h = harness({ authenticated: false });
  h.window.location.pathname = "/signup";
  h.test.state.publicConfig = {
    registration_open: true, sample_available: false,
    email_available: false, email_verification_required: false, initial_credits: 0,
  };
  h.test.applyPublicConfig();
  assert.match(h.node("signup-access-note").textContent, /0 extraction credits/);
  assert.equal(h.node("signup-recovery-note").hidden, false);
  assert.equal(h.node("invitation-note").hidden, true);
  const requests = [];
  h.replace("api", async (path, options) => { requests.push({ path, options }); return { ok: true }; });
  h.replace("fetchAccount", async () => ({
    id: "account-a", principal_marker: "principal-a", email: "a@example.com",
    credits: 0, email_verified: false, billing_configured: false, retention_days: 30,
  }));
  h.replace("publishAuthChange", async () => true);
  h.node("register-form").fields = new Map([["email", "a@example.com"], ["password", "a strong test password"]]);
  await h.node("register-form").dispatch("submit");
  assert.deepEqual(requests.map(({ path }) => path), ["/api/auth/register"]);
  assert.equal(h.window.location.pathname, "/app");
  assert.equal(h.node("workspace-view").hidden, false);
  assert.equal(h.node("workspace-access-note").hidden, false);
  assert.equal(h.node("workspace-access-notice").hidden, false);
  assert.match(h.node("toast").textContent, /Request extraction access/);
  assert.match(h.node("workspace-access-note").textContent, /credits before you can upload/);
  assert.match(h.node("retention-note").textContent, /30 days after their last update/);
  assert.equal(h.node("new-upload-button").disabled, true);
  assert.equal(h.node("empty-upload-button").disabled, true);
  assert.equal(h.node("workspace-example-link").hidden, true);
  assert.equal(h.node("buy-credits-button").hidden, true);
  await h.node("empty-upload-button").click();
  assert.deepEqual(requests.map(({ path }) => path), ["/api/auth/register"]);

  h.test.state.account.credits = 1;
  h.test.showWorkspace();
  assert.equal(h.node("new-upload-button").disabled, false);
  assert.equal(h.node("empty-upload-button").disabled, false);
  assert.equal(h.node("workspace-access-note").hidden, true);
  assert.equal(h.node("workspace-example-link").hidden, true);
});

await check("a last-credit chart keeps access guidance visible and cannot open upload after export", async () => {
  const h = harness();
  h.test.state.account.credits = 0;
  h.test.state.account.billing_configured = false;
  h.test.showWorkspace();
  h.replace("api", async () => makeJob("chart-a", "approved"));
  await h.test.openJob("chart-a", { throwOnError: true });
  assert.equal(h.node("job-view").hidden, false);
  assert.equal(h.node("empty-view").hidden, true);
  assert.equal(h.node("workspace-access-notice").hidden, false);
  assert.equal(h.node("workspace-access-link").hidden, false);
  h.context.fetch = async () => ({ ok: true, blob: async () => ({ bytes: "workbook" }) });
  await h.node("job-actions").children[0].click();
  assert.equal(h.downloads.length, 1);
  assert.equal(h.node("export-another-button").disabled, true);
  await h.node("export-another-button").dispatch("click");
  assert.equal(h.node("job-view").hidden, false);
  assert.equal(h.node("upload-view").hidden, true);
});

await check("signup allowance and recovery copy follow the configured mode", async () => {
  const h = harness({ authenticated: false });
  h.test.state.publicConfig = { registration_open: true, initial_credits: 3, email_available: true };
  h.test.applyPublicConfig();
  assert.match(h.node("signup-access-note").textContent, /starts with 3 extraction credits/);
  assert.equal(h.node("signup-recovery-note").hidden, true);
});

await check("workflow follows extraction, review and approval", async () => {
  const h = harness();
  for (const [status, active, complete] of [
    ["queued", "extract", ["upload"]],
    ["running", "extract", ["upload"]],
    ["review", "review", ["upload", "extract"]],
    ["approved", "export", ["upload", "extract", "review"]],
  ]) {
    h.select(makeJob("chart-a", status));
    const steps = h.node("workflow-steps").children;
    assert.deepEqual(steps.filter((step) => step.classList.contains("is-current")).map((step) => step.dataset.step), [active]);
    assert.deepEqual(steps.filter((step) => step.classList.contains("is-complete")).map((step) => step.dataset.step), complete);
    assert.deepEqual(steps.filter((step) => step.getAttribute("aria-current") === "step").map((step) => step.dataset.step), [active]);
    assert.equal(h.node("result-form").hidden, ["queued", "running"].includes(status));
    assert.equal(h.node("export-completion").hidden, true);
    if (status === "review") assert.equal(h.node("job-actions").children[0].textContent, "Save & approve");
    if (status === "approved") assert.equal(h.node("job-actions").children[0].textContent, "Download workbook");
  }
});

await check("edits update dirty state, hide export completion and guard navigation", async () => {
  const h = harness();
  h.select(makeJob());
  h.node("export-completion").hidden = false;
  await h.editTitle("Unsaved title");
  assert.equal(h.test.state.editorDirty, true);
  assert.equal(h.node("editor-change-note").textContent, "Unsaved changes");
  assert.equal(h.node("edit-state").textContent, "Needs review");
  assert.equal(h.node("export-completion").hidden, true);
  let prevented = false;
  const unload = { preventDefault() { prevented = true; } };
  h.windowListeners.get("beforeunload")(unload);
  assert.equal(prevented, true);
  assert.equal(unload.returnValue, "");
  h.window.confirm = () => false;
  let requests = 0;
  h.replace("api", async () => { requests += 1; });
  await h.test.openJob("chart-b");
  assert.equal(requests, 0);
  assert.equal(h.test.state.currentJob.id, "chart-a");
  assert.equal(h.node("chart-title-input").value, "Unsaved title");
  assert.equal(h.test.state.editorDirty, true);
});

await check("failed navigation after discarding never labels unsaved data clean", async () => {
  const h = harness();
  h.select(makeJob());
  await h.editTitle("Unsaved title");
  h.replace("api", async () => { throw new Error("Chart unavailable"); });
  await h.test.openJob("chart-b");
  assert.equal(h.test.state.currentJob.id, "chart-a");
  assert.ok(h.test.state.editorDirty || h.node("chart-title-input").value === "Saved chart-a");
});

await check("failed navigation after discarding approved edits restores saved status and actions", async () => {
  const h = harness();
  const job = makeJob("chart-a", "approved");
  h.select(job);
  await h.editTitle("Unsaved approved title");
  assert.equal(h.node("job-actions").children[0].textContent, "Save & approve");
  h.replace("api", async () => { throw new Error("Chart unavailable"); });
  await h.test.openJob("chart-b");
  assert.equal(h.test.state.currentJob, job);
  assert.equal(h.test.state.editorDirty, false);
  assert.equal(h.node("chart-title-input").value, "Saved chart-a");
  assert.equal(h.node("editor-change-note").textContent, "");
  assert.equal(h.node("edit-state").textContent, "Approved");
  assert.equal(h.node("job-actions").children[0].textContent, "Download workbook");
  assert.equal(h.node("workflow-steps").querySelector('[data-step="export"]').getAttribute("aria-current"), "step");
  assert.match(h.node("toast").textContent, /Chart unavailable/);
});

await check("further edits do not rewrite an already dirty status", async () => {
  const h = harness();
  h.select(makeJob());
  const writes = [];
  for (const id of ["editor-change-note", "edit-state"]) {
    let value = h.node(id).textContent;
    Object.defineProperty(h.node(id), "textContent", {
      get: () => value,
      set(next) { value = next; writes.push(id); },
    });
  }
  await h.editTitle("First edit");
  await h.editTitle("Second edit");
  await h.node("result-form").dispatch("change");
  assert.deepEqual(writes, ["editor-change-note", "edit-state"]);
  assert.equal(h.node("chart-title-input").value, "Second edit");
  assert.equal(h.test.state.editorDirty, true);
});

for (const phase of ["patch", "approve"]) {
  for (const change of ["selected chart", "view", "authentication"]) {
    await check(`save and approve retires a late ${phase} after changed ${change}`, async () => {
      const h = harness();
      h.select(makeJob());
      await h.editTitle("Corrected title");
      const reply = deferred();
      const started = deferred();
      const requests = [];
      let refreshes = 0;
      h.replace("loadJobs", async () => { refreshes += 1; });
      h.replace("api", async (path, options) => {
        requests.push({ path, options });
        if (phase === "approve" && options.method === "PATCH") return makeJob("chart-a", "review", "Corrected title");
        started.resolve();
        return reply.promise;
      });
      const pending = h.node("job-actions").children[0].click();
      await reached(started);
      if (change === "selected chart") h.test.state.currentJob = makeJob("chart-b");
      if (change === "view") h.test.beginViewSelection();
      if (change === "authentication") h.test.state.authEpoch += 1;
      const current = h.test.state.currentJob;
      reply.resolve(makeJob("chart-a", phase === "approve" ? "approved" : "review", "Corrected title"));
      await pending;
      assert.equal(requests.length, phase === "approve" ? 2 : 1);
      assert.equal(refreshes, 0);
      assert.equal(h.test.state.currentJob, current);
      assert.equal(h.test.state.editorDirty, true);
      assert.equal(h.node("toast").hidden, true);
    });
  }
}

await check("save and approve performs both writes before its single sidebar refresh", async () => {
  const h = harness();
  h.select(makeJob());
  await h.editTitle("Corrected title");
  const approved = deferred();
  const approving = deferred();
  const list = deferred();
  const listing = deferred();
  const order = [];
  const requests = [];
  h.replace("api", async (path, options) => {
    requests.push({ path, options });
    order.push(options.method);
    if (options.method === "PATCH") return makeJob("chart-a", "review", "Corrected title");
    approving.resolve();
    return approved.promise;
  });
  h.replace("loadJobs", async () => { order.push("list"); listing.resolve(); return list.promise; });
  h.replace("refreshAccount", async () => { order.push("account"); });
  const pending = h.node("job-actions").children[0].click();
  await reached(approving);
  assert.deepEqual(order, ["PATCH", "POST"]);
  assert.equal(requests[0].path, "/api/jobs/chart-a/result");
  assert.equal(requests[0].options.body.result.title, "Corrected title");
  assert.equal(requests[1].path, "/api/jobs/chart-a/approve");
  assert.equal(requests[0].options.signal, requests[1].options.signal);
  assert.equal(h.node("result-form").inert, true);
  assert.equal(await h.editTitle("Blocked while approving"), false);
  assert.equal(h.node("job-actions").children[0].disabled, true);
  approved.resolve(makeJob("chart-a", "approved", "Corrected title"));
  await reached(listing);
  assert.deepEqual(order, ["PATCH", "POST", "list"]);
  assert.equal(h.node("result-form").inert, true);
  list.resolve();
  await pending;
  assert.deepEqual(order, ["PATCH", "POST", "list"]);
  assert.equal(h.node("result-form").inert, false);
  assert.equal(h.node("result-form").getAttribute("aria-busy"), null);
  assert.equal(h.test.state.currentJob.status, "approved");
  assert.equal(h.test.state.editorDirty, false);
  assert.equal(h.node("chart-title-input").value, "Corrected title");
  assert.equal(h.node("job-actions").children[0].textContent, "Download workbook");
});

await check("save and approve never approves a failed correction", async () => {
  const h = harness();
  h.select(makeJob());
  await h.editTitle("Corrected title");
  const requests = [];
  let refreshes = 0;
  h.replace("api", async (path) => { requests.push(path); throw new Error("Save unavailable"); });
  h.replace("loadJobs", async () => { refreshes += 1; });
  await h.node("job-actions").children[0].click();
  assert.deepEqual(requests, ["/api/jobs/chart-a/result"]);
  assert.equal(refreshes, 0);
  assert.equal(h.test.state.editorDirty, true);
  assert.equal(h.node("chart-title-input").value, "Corrected title");
  assert.equal(h.node("result-form").inert, false);
});

await check("retrying failed approval retains saved corrections without another PATCH", async () => {
  const h = harness();
  h.select(makeJob());
  await h.editTitle("Corrected title");
  const methods = [];
  let approvals = 0;
  h.replace("api", async (_path, options) => {
    methods.push(options.method);
    if (options.method === "PATCH") return makeJob("chart-a", "review", "Corrected title");
    if (++approvals === 1) throw new Error("Approval unavailable");
    return makeJob("chart-a", "approved", "Corrected title");
  });
  await h.node("job-actions").children[0].click();
  assert.equal(h.test.state.editorDirty, false);
  assert.equal(h.test.state.currentJob.status, "review");
  assert.equal(h.node("chart-title-input").value, "Corrected title");
  assert.equal(h.node("result-form").inert, false);
  assert.equal(h.node("result-form").getAttribute("aria-busy"), null);
  assert.match(h.node("toast").textContent, /Approval unavailable/);
  await h.node("job-actions").children[0].click();
  assert.deepEqual(methods, ["PATCH", "POST", "POST"]);
  assert.equal(h.test.state.currentJob.status, "approved");
});

await check("dirty exports never request or announce a download", async () => {
  const h = harness();
  h.select(makeJob("chart-a", "approved"));
  await h.editTitle("Corrected title");
  let requests = 0;
  h.context.fetch = async () => { requests += 1; throw new Error("Must not export"); };
  await h.test.downloadExport(h.test.state.currentJob, "xlsx");
  assert.equal(requests, 0);
  assert.deepEqual(h.downloads, []);
  assert.deepEqual(h.createdUrls, []);
  assert.equal(h.node("export-completion").hidden, true);
});

await check("an edit while the export blob loads suppresses the stale download", async () => {
  const h = harness();
  h.select(makeJob("chart-a", "approved"));
  const blob = deferred();
  const started = deferred();
  h.context.fetch = async () => ({ ok: true, blob() { started.resolve(); return blob.promise; } });
  const pending = h.test.downloadExport(h.test.state.currentJob, "xlsx");
  await reached(started);
  await h.editTitle("Edited during download");
  blob.resolve({ bytes: "old workbook" });
  await pending;
  assert.deepEqual(h.downloads, []);
  assert.deepEqual(h.createdUrls, []);
  assert.equal(h.test.state.objectUrls.size, 0);
  assert.equal(h.node("export-completion").hidden, true);
  assert.equal(h.test.state.editorDirty, true);
  assert.match(h.node("toast").textContent, /changed during export/i);
});

await check("a clean export starts one download and revokes its URL", async () => {
  const h = harness();
  h.select(makeJob("chart-a", "approved"));
  h.context.fetch = async () => ({ ok: true, blob: async () => ({ bytes: "workbook" }) });
  await h.node("job-actions").children[0].click();
  assert.deepEqual(h.downloads, [{ href: "blob:test-1", filename: "unrender-chart-a.xlsx" }]);
  assert.deepEqual(h.createdUrls, h.revokedUrls);
  assert.equal(h.test.state.objectUrls.size, 0);
  assert.equal(h.node("export-completion").hidden, false);
});

await check("mutation keeps the editor inert until refresh completes", async () => {
  const h = harness();
  h.select(makeJob());
  const mutation = deferred();
  const refresh = deferred();
  const refreshing = deferred();
  let requests = 0;
  h.replace("api", async () => { requests += 1; return mutation.promise; });
  h.replace("refreshAccount", async () => { refreshing.resolve(); return refresh.promise; });
  const pending = h.test.jobMutation("approve");
  assert.equal(h.node("result-form").inert, true);
  assert.equal(h.node("result-form").getAttribute("aria-busy"), "true");
  assert.equal(await h.editTitle("Must remain unchanged"), false);
  await h.test.jobMutation("approve");
  assert.equal(requests, 1);
  mutation.resolve(makeJob("chart-a", "approved"));
  await reached(refreshing);
  assert.equal(h.node("result-form").inert, true);
  refresh.resolve();
  await pending;
  assert.equal(h.node("result-form").inert, false);
  assert.equal(h.node("result-form").getAttribute("aria-busy"), null);
  assert.equal(h.node("chart-title-input").value, "Saved chart-a");
  assert.equal(h.node("edit-state").textContent, "Approved");
});

for (const phase of ["refreshAccount", "loadJobs"]) {
  await check(`late mutation ${phase} cannot overwrite the next editor`, async () => {
    const h = harness();
    h.select(makeJob());
    const gate = deferred();
    const started = deferred();
    h.replace("api", async () => makeJob("chart-a", "approved"));
    h.replace(phase, async () => { started.resolve(); return gate.promise; });
    const pending = h.test.jobMutation("approve");
    await reached(started);
    h.select(makeJob("chart-b"));
    await h.editTitle("Unsaved chart B");
    gate.resolve();
    await pending;
    assert.equal(h.test.state.currentJob.id, "chart-b");
    assert.equal(h.node("chart-title-input").value, "Unsaved chart B");
    assert.equal(h.test.state.editorDirty, true);
    assert.equal(h.node("toast").hidden, true);
  });
}

await check("dirty mutation and restore keep corrections and make no requests", async () => {
  const h = harness();
  h.select(makeJob());
  await h.editTitle("Unsaved title");
  let requests = 0;
  h.replace("api", async () => { requests += 1; });
  await h.test.jobMutation("approve");
  await h.test.restoreVersion({ version: 1 });
  assert.equal(requests, 0);
  assert.equal(h.node("chart-title-input").value, "Unsaved title");
  assert.equal(h.test.state.editorDirty, true);
  assert.equal(h.node("result-form").inert, false);
});

await check("restore does not PATCH a version fetched for an abandoned chart", async () => {
  const h = harness();
  h.select(makeJob());
  const version = deferred();
  const started = deferred();
  const requests = [];
  h.replace("api", async (path, options) => { requests.push({ path, options }); started.resolve(); return version.promise; });
  const pending = h.test.restoreVersion({ version: 2 });
  await reached(started);
  assert.equal(h.node("result-form").inert, true);
  const signal = requests[0].options.signal;
  h.select(makeJob("chart-b"));
  await h.editTitle("Unsaved chart B");
  version.resolve({ result: makeJob().result });
  await pending;
  assert.equal(signal.aborted, true);
  assert.equal(requests.length, 1);
  assert.equal(h.test.state.currentJob.id, "chart-b");
  assert.equal(h.node("chart-title-input").value, "Unsaved chart B");
  assert.equal(h.test.state.editorDirty, true);
});

for (const phase of ["patch", "list"]) {
  await check(`restore fences a late ${phase} response and retains its original signal`, async () => {
    const h = harness();
    h.select(makeJob());
    const gate = deferred();
    const started = deferred();
    const requests = [];
    h.replace("api", async (path, options) => {
      requests.push({ path, options });
      if (options.method !== "PATCH") return { result: makeJob("chart-a", "review", "Historical title").result };
      if (phase === "patch") { started.resolve(); return gate.promise; }
      return makeJob("chart-a", "review", "Historical title");
    });
    if (phase === "list") h.replace("loadJobs", async () => { started.resolve(); return gate.promise; });
    const pending = h.test.restoreVersion({ version: 2 });
    await reached(started);
    assert.equal(requests.length, 2);
    assert.equal(requests[0].options.signal, requests[1].options.signal);
    assert.equal(requests[1].options.body.result.title, "Historical title");
    h.select(makeJob("chart-b"));
    await h.editTitle("Unsaved chart B");
    gate.resolve(makeJob("chart-a", "review", "Historical title"));
    await pending;
    assert.equal(h.test.state.currentJob.id, "chart-b");
    assert.equal(h.node("chart-title-input").value, "Unsaved chart B");
    assert.equal(h.test.state.editorDirty, true);
    assert.equal(h.node("toast").hidden, true);
  });
}

await check("restore succeeds in the same view and releases editor busy state", async () => {
  const h = harness();
  h.select(makeJob());
  const restored = makeJob("chart-a", "review", "Historical title");
  const requests = [];
  h.replace("api", async (path, options) => {
    requests.push({ path, options });
    return options.method === "PATCH" ? restored : { result: restored.result };
  });
  await h.test.restoreVersion({ version: 2 });
  assert.equal(requests.length, 2);
  assert.equal(h.test.state.currentJob, restored);
  assert.equal(h.node("chart-title-input").value, "Historical title");
  assert.equal(h.node("result-form").inert, false);
  assert.equal(h.node("result-form").getAttribute("aria-busy"), null);
  assert.equal(h.test.state.editorDirty, false);
  assert.match(h.node("toast").textContent, /Version 2 restored/);
});

for (const operation of ["save", "save-approve", "mutation", "restore"]) {
  await check(`switching jobs retires ${operation} busy state without unlocking a newer save`, async () => {
    const h = harness();
    h.select(makeJob());
    if (["save", "save-approve"].includes(operation)) await h.editTitle("Corrected chart A");
    const oldList = deferred();
    const listing = deferred();
    const newSave = deferred();
    h.replace("loadJobs", async () => { listing.resolve(); return oldList.promise; });
    h.replace("api", async (path, options = {}) => {
      if (path === "/api/jobs/chart-b") return makeJob("chart-b");
      if (path === "/api/jobs/chart-b/result") return newSave.promise;
      if (path.includes("/versions/")) return { result: makeJob().result };
      return makeJob("chart-a", path.endsWith("/approve") ? "approved" : "review");
    });
    const oldPending = operation === "save" ? h.test.saveCorrections()
      : operation === "save-approve" ? h.node("job-actions").children[0].click()
      : operation === "mutation" ? h.test.jobMutation("approve") : h.test.restoreVersion({ version: 1 });
    await reached(listing);
    await h.test.openJob("chart-b");
    assert.equal(h.node("result-form").inert, false);
    assert.equal(h.node("result-form").getAttribute("aria-busy"), null);
    assert.equal(await h.editTitle("Corrected chart B"), true);
    const newPending = h.test.saveCorrections();
    assert.equal(h.node("result-form").inert, true);
    oldList.resolve();
    await oldPending;
    assert.equal(h.node("result-form").inert, true);
    assert.equal(h.node("result-form").getAttribute("aria-busy"), "true");
    assert.equal(h.test.state.currentJob.id, "chart-b");
    assert.equal(h.node("chart-title-input").value, "Corrected chart B");
    assert.equal(h.test.state.editorDirty, true);
    newSave.resolve(makeJob("chart-b", "review", "Corrected chart B"));
    assert.equal(await newPending, true);
    assert.equal(h.node("result-form").inert, false);
    assert.equal(h.node("result-form").getAttribute("aria-busy"), null);
    assert.equal(h.test.state.editorDirty, false);
  });
}

await check("adding a single-series row focuses its visible category input", async () => {
  const h = harness();
  h.select(makeJob());
  await h.node("add-row-button").click();
  const table = h.node("result-table");
  const added = table.tBodies[0].lastElementChild;
  assert.equal(table.classList.contains("single-series"), true);
  assert.equal(added.querySelector('[data-kind="x"]').focused, true);
  assert.equal(added.querySelector('[data-kind="series"]').focused, false);
  assert.equal(h.test.state.editorRows.length, 3);
  assert.equal(h.test.state.editorDirty, true);
});

for (const remaining of [true, false]) {
  await check(`deleting a dirty chart ${remaining ? "returns to the library" : "clears the last editor"} without another discard prompt`, async () => {
    const h = harness();
    const job = makeJob();
    const next = makeJob("chart-b");
    h.select(job);
    h.test.state.jobs = remaining ? [job, next] : [job];
    await h.editTitle("Unsaved deleted title");
    h.node("export-completion").hidden = false;
    const account = h.test.state.account;
    const requests = [];
    let confirms = 0;
    h.window.confirm = () => ++confirms === 1;
    h.replace("api", async (path, options = {}) => {
      requests.push({ path, method: options.method || "GET" });
      return options.method === "DELETE" ? { status: "deleted" } : next;
    });
    const confirmed = h.test.deleteCurrentJob();
    assert.equal(h.node("library-dialog").open, true);
    await h.node("library-dialog-form").dispatch("submit");
    await confirmed;
    assert.equal(confirms, 0);
    assert.equal(h.test.state.account, account);
    assert.equal(h.test.state.editorDirty, false);
    assert.equal(h.node("export-completion").hidden, true);
    assert.equal(h.node("result-form").inert, false);
    assert.equal(h.node("result-form").getAttribute("aria-busy"), null);
    let prevented = false;
    h.windowListeners.get("beforeunload")({ preventDefault() { prevented = true; } });
    assert.equal(prevented, false);
    assert.deepEqual(requests, [{ path: "/api/jobs/chart-a", method: "DELETE" }]);
    assert.equal(h.test.state.currentJob, null);
    assert.equal(h.test.state.editorRows.length, 0);
    assert.equal(h.test.state.editorSeries.length, 0);
    assert.equal(h.node("chart-title-input").value, "");
    assert.equal(h.node("result-table").children.length, 0);
    assert.equal(h.node("job-source-image").getAttribute("src"), null);
    assert.equal(h.node("job-view").hidden, true);
    assert.equal(h.node("library-view").hidden, false);
    assert.equal(h.node("empty-view").hidden, remaining);
  });
}

for (const phase of ["delete", "list"]) {
  await check(`a late deletion ${phase} response preserves a newly selected dirty editor`, async () => {
    const h = harness();
    const job = makeJob();
    const next = makeJob("chart-b");
    h.select(job);
    h.test.state.jobs = [job, next];
    await h.editTitle("Unsaved chart A");
    const reply = deferred();
    const started = deferred();
    h.replace("api", async () => {
      if (phase === "delete") { started.resolve(); return reply.promise; }
      return { status: "deleted" };
    });
    if (phase === "list") h.replace("loadJobs", async () => { started.resolve(); return reply.promise; });
    const confirmation = h.test.deleteCurrentJob();
    const pending = h.node("library-dialog-form").dispatch("submit");
    await reached(started);
    h.select(next);
    await h.editTitle("Unsaved chart B");
    reply.resolve({ status: "deleted" });
    await pending;
    h.test.closeLibraryDialog(true);
    await confirmation;
    assert.equal(h.test.state.currentJob, next);
    assert.equal(h.node("chart-title-input").value, "Unsaved chart B");
    assert.equal(h.test.state.editorDirty, true);
    assert.equal(h.node("toast").hidden, true);
  });
}

await check("a failed deletion preserves corrections and the selected chart", async () => {
  const h = harness();
  const job = makeJob();
  h.select(job);
  await h.editTitle("Unsaved chart A");
  h.replace("api", async () => { throw new Error("Deletion unavailable"); });
  const confirmation = h.test.deleteCurrentJob();
  await h.node("library-dialog-form").dispatch("submit");
  assert.match(h.node("library-dialog-error").textContent, /Deletion unavailable/);
  h.test.closeLibraryDialog(true);
  await confirmation;
  assert.equal(h.test.state.currentJob, job);
  assert.equal(h.node("chart-title-input").value, "Unsaved chart A");
  assert.equal(h.test.state.editorDirty, true);

});

await check("editing an approved result immediately offers save and approve", async () => {
  const h = harness();
  h.select(makeJob("chart-a", "approved"));
  assert.equal(h.node("job-actions").children[0].textContent, "Download workbook");
  await h.editTitle("Corrected approved chart");
  assert.equal(h.node("job-actions").children[0].textContent, "Save & approve");
  const methods = [];
  h.replace("api", async (_path, options) => {
    methods.push(options.method);
    return makeJob("chart-a", options.method === "PATCH" ? "review" : "approved", "Corrected approved chart");
  });
  await h.node("job-actions").children[0].click();
  assert.deepEqual(methods, ["PATCH", "POST"]);
  assert.equal(h.test.state.editorDirty, false);
  assert.equal(h.node("job-actions").children[0].textContent, "Download workbook");
});

await check("a late chart request cannot dismiss the next selection's loading notice", async () => {
  const h = harness();
  h.select(makeJob());
  const oldReply = deferred();
  const newReply = deferred();
  h.replace("api", async (path) => path.endsWith("chart-b") ? oldReply.promise : newReply.promise);
  const oldPending = h.test.openJob("chart-b");
  assert.equal(h.node("workspace-loading").hidden, false);
  const newPending = h.test.openJob("chart-c");
  oldReply.resolve(makeJob("chart-b"));
  await oldPending;
  assert.equal(h.node("workspace-loading").hidden, false);
  newReply.resolve(makeJob("chart-c"));
  await newPending;
  assert.equal(h.node("workspace-loading").hidden, true);
  assert.equal(h.test.state.currentJob.id, "chart-c");
});

for (const kind of ["audit", "versions"]) {
  await check(`old ${kind} completion cannot unlock the next chart's history button`, async () => {
    const h = harness();
    h.select(makeJob());
    const oldReply = deferred();
    const newReply = deferred();
    const button = h.node(kind === "audit" ? "toggle-audit-button" : "toggle-versions-button");
    h.replace("api", async (path) => path.includes("chart-a") ? oldReply.promise : newReply.promise);
    const oldPending = button.click();
    assert.equal(button.disabled, true);
    assert.match(button.textContent, /Loading/);
    h.select(makeJob("chart-b"));
    assert.equal(button.disabled, false);
    const newPending = button.click();
    const payload = { items: [], rollups: [], next_cursor: null, next_before: null };
    oldReply.resolve(payload);
    await oldPending;
    assert.equal(button.disabled, true);
    assert.equal(button.getAttribute("aria-busy"), "true");
    assert.match(button.textContent, /Loading/);
    newReply.resolve(payload);
    await newPending;
    assert.equal(button.disabled, false);
    assert.equal(button.getAttribute("aria-busy"), null);
    assert.match(button.textContent, /Hide/);
  });
}

await check("old PDF preview completion cannot clear the current page's pending state", async () => {
  const h = harness();
  h.test.state.upload = { id: "upload-a", page_count: 3 };
  h.test.updateUploadPreview();
  const preview = h.node("upload-preview");
  const oldLoad = preview.onload;
  assert.equal(preview.getAttribute("aria-busy"), "true");
  h.test.state.uploadPage = 1;
  h.test.updateUploadPreview();
  oldLoad();
  assert.equal(preview.getAttribute("aria-busy"), "true");
  assert.match(h.node("page-counter").textContent, /Loading page 2/);
  preview.onload();
  assert.equal(preview.getAttribute("aria-busy"), null);
  assert.equal(h.node("page-counter").textContent, "Page 2 of 3");
  h.test.state.uploadPage = 2;
  h.test.updateUploadPreview();
  preview.onerror();
  assert.equal(preview.getAttribute("aria-busy"), null);
  assert.match(h.node("page-counter").textContent, /preview unavailable/);
  assert.equal(h.node("upload-error").hidden, false);
});

console.log(`Browser workflow regressions passed (${passed} scenarios)`);
