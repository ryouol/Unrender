import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../unrender/product/static/landing.html", import.meta.url), "utf8");
const source = fs.readFileSync(new URL("../unrender/product/static/landing.js", import.meta.url), "utf8");

async function render({ configAvailable = true, nativeDialogs = true } = {}) {
  const nodes = [];
  const requests = [];
  const downloads = [];
  const blobs = new Map();
  const revoked = [];
  const timers = new Map();
  let nextTimer = 0;
  let document;

  class Node {
    constructor(tag, attributes = new Map(), position = -1) {
      this.tag = tag;
      this.attributes = attributes;
      this.position = position;
      this.dataset = Object.fromEntries([...attributes].filter(([key]) => key.startsWith("data-")).map(([key, value]) => [key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()), value]));
      this.hidden = attributes.has("hidden");
      this.value = attributes.get("value") || "";
      this.textContent = "";
      this.href = attributes.get("href") || "";
      this.hash = this.href.startsWith("#") ? this.href : "";
      this.isConnected = true;
      this.listeners = new Map();
      this.classList = { add() {}, remove() {} };
      this.open = false;
      if (!nativeDialogs) this.showModal = undefined;
    }
    addEventListener(type, handler) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(handler);
    }
    emit(type) {
      for (const handler of this.listeners.get(type) || []) handler({ currentTarget: this, preventDefault() {} });
    }
    setAttribute(key, value) { this.attributes.set(key, value); }
    removeAttribute(key) { this.attributes.delete(key); }
    focus() { document.activeElement = this; }
    showModal() { this.open = true; }
    close() { this.open = false; this.emit("close"); }
    append() {}
    remove() { this.isConnected = false; }
    click() {
      if (this.tag === "a" && this.download) downloads.push({ filename: this.download, blob: blobs.get(this.href) });
      else this.emit("click");
    }
    get valueAsNumber() { return this.value === "" ? NaN : Number(this.value); }
    checkValidity() { return Number.isFinite(this.valueAsNumber) && this.valueAsNumber >= 0 && this.valueAsNumber <= 100; }
    querySelectorAll(selector) {
      const end = html.indexOf(`</${this.tag}>`, this.position);
      return select(selector).filter((node) => node.position > this.position && node.position < end);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  }

  // Use the actual markup's element IDs, hidden flags and data attributes. The
  // harness supplies only DOM behavior; it does not call implementation internals.
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/gi)) {
    const attributes = new Map([...match[2].matchAll(/([\w:-]+)(?:="([^"]*)")?/g)].map((attr) => [attr[1], attr[2] || ""]));
    nodes.push(new Node(match[1], attributes, match.index));
  }
  const node = (id) => {
    const found = nodes.find((item) => item.attributes.get("id") === id);
    assert.ok(found, `Missing actual landing element: ${id}`);
    return found;
  };
  function select(selector) {
    if (selector.startsWith("#")) return [node(selector.slice(1))];
    if (selector.startsWith("[")) return nodes.filter((item) => item.attributes.has(selector.slice(1, -1)));
    return nodes.filter((item) => item.tag === selector);
  }
  document = {
    body: nodes.find((item) => item.tag === "body"),
    activeElement: null,
    getElementById: node,
    querySelectorAll: select,
    querySelector: (selector) => select(selector)[0] || null,
    createElement: (tag) => new Node(tag),
  };
  Object.defineProperty(document, "cookie", {
    get() { assert.fail("The public example must not access account cookies"); },
    set() { assert.fail("The public example must not write account cookies"); },
  });
  const forbiddenStorage = new Proxy({}, { get() { assert.fail("Example data must not enter browser storage"); } });
  const context = vm.createContext({
    document, AbortController, Blob,
    localStorage: forbiddenStorage, sessionStorage: forbiddenStorage,
    URL: {
      createObjectURL(blob) { const url = `blob:example-${blobs.size}`; blobs.set(url, blob); return url; },
      revokeObjectURL(url) { revoked.push(url); },
    },
    window: {
      setTimeout(callback, delay) { timers.set(++nextTimer, { callback, delay }); return nextTimer; },
      clearTimeout(id) { timers.delete(id); },
    },
    fetch: async (url, options = {}) => {
      requests.push({ url, method: options.method || "GET", credentials: options.credentials, body: options.body });
      return { ok: configAvailable, json: async () => ({ max_upload_bytes: 10485760, max_image_pixels: 4000000, max_pdf_pages: 25 }) };
    },
  });
  vm.runInContext(source, context, { filename: "landing.js" });
  await new Promise((resolve) => setImmediate(resolve));
  return { node, document, requests, downloads, blobs, revoked, timers, open: select("[data-open-example]")[0], exportButtons: select("[data-demo-export]") };
}

const example = await render();
const { node, document, downloads, exportButtons } = example;
example.open.click();
assert.equal(node("landing-example-dialog").open, true);
assert.equal(document.activeElement, node("demo-title"));

// Dispatching hidden controls directly must not bypass save/approval checks.
node("demo-approve").click();
exportButtons[0].click();
assert.equal(downloads.length, 0);
node("demo-q3").value = "16.8";
node("demo-q3").emit("input");
node("demo-approve").click();
exportButtons[0].click();
assert.equal(downloads.length, 0, "A corrected but unsaved input must not export");

node("demo-q3").value = "16.3";
node("landing-demo-form").emit("submit");
assert.equal(node("demo-error").hidden, false);
assert.equal(node("demo-approve").hidden, true);
node("demo-q3").value = "16.8";
node("demo-q3").emit("input");
node("landing-demo-form").emit("submit");
assert.equal(node("demo-error").hidden, true);
assert.equal(node("demo-approve").hidden, false);
assert.equal(document.activeElement, node("demo-approve"));
exportButtons[0].click();
assert.equal(downloads.length, 0, "Saving alone must not approve the example");
node("demo-approve").click();
assert.equal(node("demo-export").hidden, false);
assert.equal(document.activeElement, exportButtons[0]);

for (const button of exportButtons) button.click();
assert.deepEqual(downloads.map((item) => item.filename), ["unrender-illustrative-example.csv", "unrender-illustrative-example.json"]);
assert.deepEqual((await downloads[0].blob.text()).trim().split(/\r?\n/), ["Quarter,Revenue ($m)", "Q1,12.4", "Q2,18.6", "Q3,16.8", "Q4,24.2"]);
const json = JSON.parse(await downloads[1].blob.text());
assert.deepEqual(json.series[0].points, [{ x: "Q1", y: 12.4 }, { x: "Q2", y: 18.6 }, { x: "Q3", y: 16.8 }, { x: "Q4", y: 24.2 }]);
assert.match(json.example, /Illustrative/);

node("demo-q3").value = "17";
node("demo-q3").emit("input");
assert.equal(node("demo-save").hidden, false);
assert.equal(node("demo-approve").hidden, true);
assert.equal(node("demo-export").hidden, true);
node("demo-approve").click();
exportButtons[0].click();
assert.equal(downloads.length, 2, "An edit must invalidate the previous approval");
node("demo-reset").click();
assert.equal(node("demo-q3").value, "16.3");
assert.equal(document.activeElement, node("demo-q3"));
node("landing-example-dialog").close();
assert.equal(document.activeElement, example.open);
node("landing-menu-open").click();
assert.equal(node("landing-menu").open, true);
node("landing-menu").close();
assert.equal(document.activeElement, node("landing-menu-open"));
for (const { callback, delay } of example.timers.values()) if (delay === 1000) callback();
assert.equal(example.revoked.length, 2);
assert.deepEqual(example.requests, [{ url: "/api/public-config", method: "GET", credentials: "omit", body: undefined }]);

// Public configuration failure must not prevent the local example from opening.
const unavailable = await render({ configAvailable: false });
assert.equal(unavailable.node("landing-upload-limits").hidden, true);
unavailable.open.click();
assert.equal(unavailable.node("landing-example-dialog").open, true);
const unsupported = await render({ nativeDialogs: false });
assert.equal(unsupported.node("landing-menu-open").hidden, true);
assert.equal(unsupported.open.href, "#example");
assert.equal(unsupported.requests.length, 0);
console.log("Landing route assets and local correction/approval/export boundaries passed");
