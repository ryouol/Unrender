const libraryPreviews = { entries: new Map(), cards: new WeakMap(), queue: [], active: null, running: false, enabled: true, retry: null };

function previewIsCurrent(entry) {
  return libraryPreviews.entries.get(entry.card) === entry
    && entry.authEpoch === state.authEpoch
    && entry.principal === state.principalMarker
    && authContextMatches(entry.authEpoch, entry.authRecord);
}

function releaseLibraryPreview(entry) {
  if (entry.url) URL.revokeObjectURL(entry.url);
  entry.url = null;
  entry.image.removeAttribute("src");
}

function createLibraryPreview(job, card) {
  const container = libraryNode("div", "", "chart-preview");
  const image = document.createElement("img");
  image.alt = "";
  image.decoding = "async";
  const entry = {
    card, container, image, url: null, status: "queued", attempts: 0,
    path: `/api/jobs/${routeSegment(job.id)}/source?thumbnail=true&v=${routeSegment(job.updated_at)}`,
    authEpoch: state.authEpoch, authRecord: readDurableAuthRecord(), principal: state.principalMarker,
  };
  image.addEventListener("error", () => {
    if (previewIsCurrent(entry)) failLibraryPreview(entry);
  });
  container.append(image);
  libraryPreviews.cards.set(card, entry);
  return container;
}

function failLibraryPreview(entry) {
  releaseLibraryPreview(entry);
  entry.status = "failed";
  entry.container.replaceChildren(libraryNode("span", "Preview unavailable"));
}

function cancelPreviewRetry() {
  const retry = libraryPreviews.retry;
  if (!retry) return;
  libraryPreviews.retry = null;
  window.clearTimeout(retry.timer);
  retry.resolve();
}

function setLibraryPreviewsActive(enabled) {
  libraryPreviews.enabled = enabled;
  if (!enabled) {
    libraryPreviews.queue = [];
    cancelPreviewRetry();
  }
}

function resetLibraryPreviews() {
  libraryPreviews.queue = [];
  cancelPreviewRetry();
  for (const entry of libraryPreviews.entries.values()) releaseLibraryPreview(entry);
  libraryPreviews.entries.clear();
  libraryPreviews.active?.controller.abort();
}

async function waitForLibraryPreview() {
  await libraryPreviews.active?.finished;
}

function syncLibraryPreviews(cards) {
  const wanted = new Set(cards.slice(0, LIBRARY_PAGE_SIZE));
  for (const [card, entry] of libraryPreviews.entries) {
    if (!wanted.has(card)) {
      releaseLibraryPreview(entry);
      libraryPreviews.entries.delete(card);
    }
  }
  for (const card of wanted) {
    const entry = libraryPreviews.cards.get(card);
    if (entry) libraryPreviews.entries.set(card, entry);
  }
  if (libraryPreviews.retry && !previewIsCurrent(libraryPreviews.retry.entry)) cancelPreviewRetry();
  libraryPreviews.queue = libraryPreviews.enabled
    ? [...libraryPreviews.entries.values()].filter((entry) => entry.status === "queued") : [];
  void drainLibraryPreviews();
}

async function drainLibraryPreviews() {
  if (libraryPreviews.running) return;
  libraryPreviews.running = true;
  try {
    while (libraryPreviews.enabled && libraryPreviews.queue.length) {
      const entry = libraryPreviews.queue.shift();
      if (!previewIsCurrent(entry) || entry.status !== "queued") continue;
      entry.status = "loading";
      entry.attempts += 1;
      const controller = new AbortController();
      let finish;
      const finished = new Promise((resolve) => { finish = resolve; });
      libraryPreviews.active = { entry, controller, finished };
      try {
        const blob = await api(entry.path, {
          responseType: "blob", timeoutMs: 30000, signal: controller.signal,
          authEpoch: entry.authEpoch, authRecord: entry.authRecord,
        });
        if (!previewIsCurrent(entry) || controller.signal.aborted) continue;
        entry.url = URL.createObjectURL(blob);
        entry.status = "loaded";
        entry.image.src = entry.url;
      } catch (error) {
        if (!previewIsCurrent(entry) || controller.signal.aborted) continue;
        if (error.status === 503 && entry.attempts < 2) {
          entry.status = "queued";
          if (libraryPreviews.enabled) {
            await new Promise((resolve) => {
              libraryPreviews.retry = { entry, resolve, timer: window.setTimeout(resolve, 1000) };
            });
            libraryPreviews.retry = null;
            if (libraryPreviews.enabled && previewIsCurrent(entry)
              && !libraryPreviews.queue.includes(entry)) libraryPreviews.queue.unshift(entry);
          }
        } else failLibraryPreview(entry);
      } finally {
        libraryPreviews.active = null;
        finish();
      }
    }
  } finally {
    libraryPreviews.running = false;
  }
}
