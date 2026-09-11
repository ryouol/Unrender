import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const staticRoot = new URL("../unrender/product/static/", import.meta.url);
const html = fs.readFileSync(new URL("landing.html", staticRoot), "utf8");
const source = fs.readFileSync(new URL("landing.js", staticRoot), "utf8");

// Marketing stays readable without JavaScript and never offers a simulated extraction.
assert.match(html, /Unlock the numbers\.<br>Keep the evidence\./);
assert.doesNotMatch(html, /<dialog|<form|data-open-example|data-demo-export|landing-example-dialog/);
for (const match of html.matchAll(/(?:src|href)="(\/static\/[^"#]+)"/g)) {
  assert.ok(fs.existsSync(new URL(match[1].slice(8), staticRoot)), match[1]);
}
for (const match of html.matchAll(/srcset="([^"]+)"/g)) {
  for (const item of match[1].split(",")) {
    const [path] = item.trim().split(/\s+/);
    assert.ok(path.startsWith("/static/"));
    assert.ok(fs.existsSync(new URL(path.slice(8), staticRoot)), path);
  }
}
for (const match of html.matchAll(/href="#([^"]+)"/g)) {
  assert.ok(html.includes(`id="${match[1]}"`), `Missing anchor destination ${match[1]}`);
}

async function render({ config = { registration_open: true, initial_credits: 0, max_upload_bytes: 10485760, max_image_pixels: 4000000, max_pdf_pages: 25 }, reduced = false, observers = true } = {}) {
  const nodes = [];
  const requests = [];
  const frames = new Map();
  const timers = new Map();
  const instances = [];
  let nextId = 0;
  let window;
  class Node extends EventTarget {
    constructor(tag, attributes = new Map(), position = -1) {
      super();
      this.tag = tag;
      this.attributes = attributes;
      this.position = position;
      this.hidden = attributes.has("hidden");
      this.href = attributes.get("href") || "";
      const contentStart = html.indexOf(">", position) + 1;
      const contentEnd = html.indexOf(`</${tag}>`, contentStart);
      this.textContent = position >= 0 && contentEnd >= 0 ? html.slice(contentStart, contentEnd).replace(/<[^>]*>/g, "") : "";
      this.style = {};
      const classes = new Set((attributes.get("class") || "").split(" "));
      this.classList = {
        add: (name) => classes.add(name),
        contains: (name) => classes.has(name),
        toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
      };
    }
    setAttribute(key, value) { this.attributes.set(key, value); }
    click() { this.dispatchEvent(new Event("click")); }
    querySelector(selector) {
      const end = html.indexOf(`</${this.tag}>`, this.position);
      return select(selector).find((node) => node.position > this.position && node.position < end);
    }
    getBoundingClientRect() { return { top: 400 - window.scrollY, bottom: 1000 - window.scrollY }; }
  }
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/gi)) {
    const attributes = new Map([...match[2].matchAll(/([\w:-]+)(?:="([^"]*)")?/g)].map((attr) => [attr[1], attr[2] || ""]));
    nodes.push(new Node(match[1], attributes, match.index));
  }
  function select(selector) {
    return nodes.filter((node) => selector.startsWith("[") ? node.attributes.has(selector.slice(1, -1)) : node.tag === selector);
  }
  const node = (id) => {
    const result = nodes.find((item) => item.attributes.get("id") === id);
    assert.ok(result, `Missing actual element: ${id}`);
    return result;
  };
  const document = Object.assign(new EventTarget(), { body: select("body")[0], hidden: false, getElementById: node, querySelectorAll: select });
  Object.defineProperty(document, "cookie", { get() { assert.fail("Marketing must not read account cookies"); }, set() { assert.fail("Marketing must not write account cookies"); } });
  const preference = Object.assign(new EventTarget(), { matches: reduced });
  window = Object.assign(new EventTarget(), {
    innerHeight: 900, scrollY: 0,
    matchMedia: () => preference,
    setTimeout(callback) { timers.set(++nextId, callback); return nextId; },
    clearTimeout: (id) => timers.delete(id),
    requestAnimationFrame(callback) { frames.set(++nextId, callback); return nextId; },
    cancelAnimationFrame: (id) => frames.delete(id),
  });
  class Observer {
    constructor(callback) { this.callback = callback; this.targets = new Set(); instances.push(this); }
    observe(target) { this.targets.add(target); }
    unobserve(target) { this.targets.delete(target); }
    disconnect() { this.targets.clear(); }
  }
  const forbidden = new Proxy({}, { get() { assert.fail("Marketing must not store customer or sample data"); } });
  const context = vm.createContext({
    document, window, AbortController, IntersectionObserver: observers ? Observer : undefined,
    localStorage: forbidden, sessionStorage: forbidden,
    fetch: async (url, options) => {
      requests.push({ url, credentials: options.credentials, signal: options.signal });
      return { ok: config !== null, json: async () => config };
    },
  });
  vm.runInContext(source, context, { filename: "landing.js" });
  await new Promise((resolve) => setImmediate(resolve));
  const emit = (target, name, properties = {}) => target.dispatchEvent(Object.assign(new Event(name), properties));
  const flush = () => { const pending = [...frames.values()]; frames.clear(); for (const callback of pending) callback(); };
  return { node, select, document, window, preference, frames, timers, instances, requests, emit, flush };
}

const page = await render();
assert.equal(page.requests.length, 1);
assert.equal(page.requests[0].url, "/api/public-config");
assert.equal(page.requests[0].credentials, "omit");
assert.match(page.node("landing-upload-limits").textContent, /10 MiB.*4 MP.*25 pages/);
assert.match(page.node("landing-access-note").textContent, /granted separately/);
assert.equal(page.node("landing-motion").hidden, false);
page.flush();
assert.equal(page.frames.size, 0, "Artwork must settle without an endless animation loop");
const origin = page.node("landing-artwork").style.transform;
page.window.scrollY = 360;
for (let i = 0; i < 20; i++) page.emit(page.window, "scroll");
assert.equal(page.frames.size, 1, "Scroll events must coalesce into one rendering frame");
page.flush();
assert.notEqual(page.node("landing-artwork").style.transform, origin);
assert.equal(page.frames.size, 0);
page.node("landing-motion").click();
const paused = page.node("landing-artwork").style.transform;
assert.equal(page.node("landing-motion").textContent, "Resume motion");
assert.equal(page.node("landing-motion").attributes.get("aria-pressed"), "true");
page.window.scrollY = 720;
page.emit(page.window, "scroll");
page.flush();
assert.equal(page.node("landing-artwork").style.transform, paused, "Pause must freeze the illustration while scrolling remains native");
assert.equal(page.document.body.classList.contains("landing-motion-paused"), true);
page.node("landing-motion").click();
page.flush();
assert.notEqual(page.node("landing-artwork").style.transform, paused);

const revealed = page.select("[data-reveal]")[0];
page.instances[0].callback([{ target: revealed, isIntersecting: true }]);
assert.equal(revealed.classList.contains("is-visible"), true);
assert.equal(page.instances[0].targets.has(revealed), false);
page.preference.matches = true;
page.emit(page.preference, "change");
assert.equal(page.node("landing-motion").hidden, true);
assert.equal(page.node("landing-artwork").style.transform, "");
assert.equal(page.frames.size, 0);
assert.equal(page.document.body.classList.contains("landing-motion-enabled"), false);
page.preference.matches = false;
page.emit(page.preference, "change");
assert.equal(page.frames.size, 1);
page.document.hidden = true;
page.emit(page.document, "visibilitychange");
assert.equal(page.frames.size, 0, "Background tabs must not render");
page.document.hidden = false;
page.emit(page.document, "visibilitychange");
assert.equal(page.frames.size, 1);
page.emit(page.window, "pagehide", { persisted: true });
assert.equal(page.frames.size, 0);
assert.equal(page.instances[0].targets.size, 0);
page.emit(page.window, "pageshow", { persisted: true });
assert.ok(page.instances[0].targets.size > 0, "Returning through the browser cache must restore reveal observation");
page.flush();
page.emit(page.window, "pagehide", { persisted: false });
page.emit(page.window, "scroll");
assert.equal(page.frames.size, 0, "Discarded pages must release event listeners");
assert.equal(page.requests[0].signal.aborted, true);
assert.equal(page.requests.length, 1, "No signup, sample, upload, or inference requests belong on marketing");

const staticPage = await render({ reduced: true });
assert.equal(staticPage.node("landing-motion").hidden, true);
assert.equal(staticPage.frames.size, 0);
const fallback = await render({ observers: false, config: null });
assert.equal(fallback.document.body.classList.contains("landing-motion-enabled"), false, "Without observers, all marketing copy must remain visible");
assert.match(fallback.node("landing-upload-limits").textContent, /current file limits in your workspace/);
assert.equal(fallback.select("[data-signup-link]")[0].href, "/signup");
const invited = await render({ config: { registration_open: false } });
for (const link of invited.select("[data-signup-link]")) {
  assert.equal(link.href, "/contact");
  assert.equal(link.querySelector("span").textContent, "Request access");
}
assert.match(invited.node("landing-access-note").textContent, /invitation/);
console.log("Static landing, public configuration, native scroll motion, reduced-motion, pause, and lifecycle boundaries passed");
