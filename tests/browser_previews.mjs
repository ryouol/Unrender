import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../unrender/product/static/previews.js", import.meta.url), "utf8");
const tick = () => new Promise(setImmediate);

function harness() {
  const requests = [], created = [], revoked = [], timers = new Map();
  let timerId = 0;
  const record = { phase: "authenticated", id: "principal-a" };
  class Node {
    constructor(tag = "div") { this.tag = tag; this.children = []; this.events = {}; }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    addEventListener(name, handler) { this.events[name] = handler; }
    removeAttribute(name) { delete this[name]; }
  }
  const state = { authEpoch: 1, principalMarker: "principal-a" };
  const context = {
    AbortController, Map, WeakMap, Set, Promise, LIBRARY_PAGE_SIZE: 24, state,
    document: { createElement: (tag) => new Node(tag) },
    libraryNode: (tag, text) => Object.assign(new Node(tag), { textContent: text }),
    routeSegment: encodeURIComponent,
    readDurableAuthRecord: () => record,
    authContextMatches: (epoch, current) => epoch === state.authEpoch && current === record,
    window: {
      setTimeout(handler) { timers.set(++timerId, handler); return timerId; },
      clearTimeout(id) { timers.delete(id); },
    },
    URL: {
      createObjectURL(blob) { const url = `blob:preview-${created.length}`; created.push({ url, blob }); return url; },
      revokeObjectURL(url) { revoked.push(url); },
    },
    api(path, options) {
      return new Promise((resolve, reject) => { requests.push({ path, options, resolve, reject }); });
    },
  };
  vm.createContext(context);
  vm.runInContext(`${source}\nglobalThis.preview = {
    createLibraryPreview, syncLibraryPreviews, resetLibraryPreviews,
    setLibraryPreviewsActive, waitForLibraryPreview, libraryPreviews,
  };`, context);
  const api = context.preview;
  const card = (id) => {
    const node = new Node("article");
    node.preview = api.createLibraryPreview({ id, updated_at: "2026-09-11" }, node);
    return node;
  };
  return { api, card, state, requests, created, revoked, timers };
}

test("twenty-four thumbnails are fetched serially and loaded cards are reused", async () => {
  const h = harness();
  const cards = Array.from({ length: 24 }, (_, i) => h.card(`chart-${i}`));
  h.api.syncLibraryPreviews(cards);
  for (let i = 0; i < cards.length; i++) {
    assert.equal(h.requests.length, i + 1);
    const request = h.requests[i];
    assert.match(request.path, /source\?thumbnail=true&v=/);
    assert.equal(request.options.responseType, "blob");
    assert.equal(request.options.timeoutMs, 30000);
    request.resolve({ type: "image/png", id: i });
    await tick();
  }
  assert.equal(h.created.length, 24);
  h.api.syncLibraryPreviews(cards);
  await tick();
  assert.equal(h.requests.length, 24);
  assert.equal(h.revoked.length, 0);
  assert.equal(h.api.libraryPreviews.entries.size, 24);
});

test("page replacement drops stale work, revokes removed images, and bounds queued cards", async () => {
  const h = harness();
  const first = Array.from({ length: 24 }, (_, i) => h.card(`old-${i}`));
  h.api.syncLibraryPreviews(first);
  h.requests[0].resolve({});
  await tick();
  assert.equal(h.created.length, 1);
  const second = Array.from({ length: 24 }, (_, i) => h.card(`new-${i}`));
  h.api.syncLibraryPreviews(second);
  assert.equal(h.requests.length, 2, "new page waits for the old in-flight request");
  assert.equal(h.api.libraryPreviews.entries.size, 24);
  assert.equal(h.api.libraryPreviews.queue.length, 24);
  assert.deepEqual(h.revoked, [h.created[0].url]);
  h.requests[1].resolve({ stale: true });
  await tick();
  assert.equal(h.created.length, 1, "late unmounted response never allocates an image URL");
  assert.match(h.requests[2].path, /new-0/);
  h.api.resetLibraryPreviews();
  h.requests[2].resolve({});
  await tick();
  assert.equal(h.api.libraryPreviews.entries.size, 0);
  assert.equal(h.api.libraryPreviews.queue.length, 0);
});

test("sign-out aborts active work, revokes loaded images, and discards late responses", async () => {
  const h = harness();
  h.api.syncLibraryPreviews([h.card("one"), h.card("two"), h.card("three")]);
  h.requests[0].resolve({});
  await tick();
  h.state.authEpoch += 1;
  h.state.principalMarker = null;
  h.api.resetLibraryPreviews();
  assert.equal(h.requests[1].options.signal.aborted, true);
  h.requests[1].resolve({});
  await tick();
  assert.equal(h.created.length, 1);
  assert.deepEqual(h.revoked, [h.created[0].url]);
  assert.equal(h.requests.length, 2);
});

test("a changed principal fences even an un-aborted successful response", async () => {
  const h = harness();
  h.api.syncLibraryPreviews([h.card("one")]);
  h.state.principalMarker = "principal-b";
  h.requests[0].resolve({});
  await tick();
  assert.equal(h.created.length, 0);
});

test("transient capacity failures receive only one delayed automatic retry", async () => {
  const h = harness();
  const card = h.card("one");
  h.api.syncLibraryPreviews([card]);
  h.requests[0].reject(Object.assign(new Error("busy"), { status: 503 }));
  await tick();
  assert.equal(h.requests.length, 1);
  assert.equal(h.timers.size, 1);
  [...h.timers.values()][0]();
  await tick();
  assert.equal(h.requests.length, 2);
  h.requests[1].reject(Object.assign(new Error("busy"), { status: 503 }));
  await tick();
  h.api.syncLibraryPreviews([card]);
  await tick();
  assert.equal(h.requests.length, 2);
  assert.equal(card.preview.children[0].textContent, "Preview unavailable");
});

test("pausing settles the active thumbnail before a review can start and leaves queued work idle", async () => {
  const h = harness();
  const cards = [h.card("one"), h.card("two")];
  h.api.syncLibraryPreviews(cards);
  h.api.setLibraryPreviewsActive(false);
  let ready = false;
  const idle = h.api.waitForLibraryPreview().then(() => { ready = true; });
  await tick();
  assert.equal(ready, false);
  h.requests[0].resolve({});
  await idle;
  assert.equal(ready, true);
  assert.equal(h.requests.length, 1);
  h.api.setLibraryPreviewsActive(true);
  h.api.syncLibraryPreviews(cards);
  assert.equal(h.requests.length, 2);
  h.requests[1].resolve({});
  await tick();
});

test("image decoding failure releases the URL and does not re-fetch on render", async () => {
  const h = harness();
  const card = h.card("one");
  h.api.syncLibraryPreviews([card]);
  h.requests[0].resolve({});
  await tick();
  card.preview.children[0].events.error();
  h.api.syncLibraryPreviews([card]);
  await tick();
  assert.equal(h.requests.length, 1);
  assert.deepEqual(h.revoked, [h.created[0].url]);
});
