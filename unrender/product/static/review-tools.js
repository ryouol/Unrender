let comparisonRequest = 0;
const reviewHistory = { undo: [], redo: [], pending: null };
const historyFields = ["chart-type-input", "chart-title-input", "x-label-input", "y-label-input", "x-unit-input", "y-unit-input"];

function editorSnapshot() {
  collectEditorRows();
  for (const input of byId("series-editor-list").querySelectorAll("[data-series-name]")) {
    state.editorSeries[Number(input.dataset.seriesName)].name = input.value;
  }
  return JSON.stringify({ rows: state.editorRows, series: state.editorSeries, page: state.editorPage,
    fields: historyFields.map((id) => byId(id).value) });
}


function resetReviewTools() {
  comparisonRequest += 1;
  reviewHistory.pending = null;
  reviewHistory.undo = [];
  reviewHistory.redo = [];
  byId("bulk-values").value = "";
  byId("version-comparison").replaceChildren();
  byId("version-comparison").hidden = true;
  updateHistoryButtons();
}

function updateHistoryButtons() {
  byId("undo-edit").disabled = !reviewHistory.undo.length;
  byId("redo-edit").disabled = !reviewHistory.redo.length;
}

function checkpointEditor(snapshot = editorSnapshot()) {
  if (!state.currentJob?.result) return;
  if (snapshot.length > 1000000) return;
  if (reviewHistory.undo.at(-1) !== snapshot) {
    reviewHistory.undo.push(snapshot);
    if (reviewHistory.undo.length > 10) reviewHistory.undo.shift();
  }
  reviewHistory.redo = [];
  updateHistoryButtons();
}

function travelEditor(direction) {
  const from = reviewHistory[direction];
  if (!from.length) return;
  const current = editorSnapshot();
  const other = reviewHistory[direction === "undo" ? "redo" : "undo"];
  other.push(current);
  if (other.length > 10) other.shift();
  const saved = JSON.parse(from.pop());
  state.editorRows = saved.rows;
  state.editorSeries = saved.series;
  state.editorPage = saved.page;
  historyFields.forEach((id, index) => { byId(id).value = saved.fields[index]; });
  reviewHistory.pending = null;
  renderSeriesEditor();
  renderResultTable();
  markEditorDirty();
  updateHistoryButtons();
}

function reverseEditorRows() {
  checkpointEditor();
  collectEditorRows();
  const groups = state.editorSeries.map((_, index) => state.editorRows.filter((row) => row.seriesIndex === index).reverse());
  state.editorRows = groups.flat();
  state.editorPage = 0;
  markEditorDirty();
  renderResultTable();
}

function pasteEditorRows() {
  try {
    const text = byId("bulk-values").value.replace(/\r\n/g, "\n").replace(/\n+$/, "");
    if (!text || text.length > 1000000) throw new Error("Paste a table up to 1 MB.");
    const lines = text.split(/\r?\n/);
    if (lines.length > EDITOR_MAX_ROWS) throw new Error("Use at most 10,000 rows.");
    const rows = lines.map((line, index) => {
      const fields = line.split("\t");
      if (fields.length !== 2 && fields.length !== 3) throw new Error(`Row ${index + 1}: use category and value, optionally preceded by series number.`);
      const seriesIndex = fields.length === 3 ? Number(fields.shift()) - 1 : 0;
      const [x, value] = fields;
      if (!Number.isInteger(seriesIndex) || seriesIndex < 0 || seriesIndex >= state.editorSeries.length
        || (value.trim() !== "" && !Number.isFinite(Number(value)))) {
        throw new Error(`Row ${index + 1}: check the series number and numeric value.`);
      }
      return { seriesIndex, x, xType: "string", y: value.trim() === "" ? "" : String(Number(value)) };
    });
    checkpointEditor();
    state.editorRows = rows;
    state.editorPage = 0;
    markEditorDirty();
    renderResultTable();
    clearError("bulk-error");
    byId("bulk-values").value = "";
    showToast("Table replaced. Check every value, then save your corrections. Undo is available.");
  } catch (error) { showError("bulk-error", error); }
}

function describeComparisonRow(row) {
  return row ? `Series ${row.seriesIndex + 1}, ${row.x}: ${row.y || "empty"}` : "no row";
}

async function compareVersion(item) {
  const request = ++comparisonRequest;
  const job = state.currentJob;
  const epoch = state.viewEpoch;
  if (!job) return;
  try {
    const saved = await api(`/api/jobs/${routeSegment(job.id)}/versions/${item.version}`, { signal: state.viewController.signal });
    if (request !== comparisonRequest || epoch !== state.viewEpoch || state.currentJob !== job) return;
    const before = editorRows(saved.result);
    const after = editorRows(job.result);
    const panel = byId("version-comparison");
    const heading = libraryNode("h4", `Version ${item.version} compared with saved version ${job.result_version}`);
    const summary = libraryNode("p", `Saved rows: ${before.length} → ${after.length}. Unsaved edits are not included. Differences use row position.`);
    const differences = [];
    let changed = 0;
    for (let index = 0; index < Math.max(before.length, after.length); index += 1) {
      if (JSON.stringify(before[index]) === JSON.stringify(after[index])) continue;
      changed += 1;
      if (differences.length < 100) differences.push(libraryNode("li", `Row ${index + 1}: ${describeComparisonRow(before[index])} → ${describeComparisonRow(after[index])}`));
    }
    const list = document.createElement("ol");
    list.append(...differences);
    const metadataChanged = ["chart_type", "title", "x_axis", "y_axis"].some((key) => JSON.stringify(saved.result[key]) !== JSON.stringify(job.result[key]))
      || JSON.stringify(saved.result.series.map((series) => series.name)) !== JSON.stringify(job.result.series.map((series) => series.name));
    panel.replaceChildren(heading, summary, libraryNode("p", `${changed} changed rows; showing up to 100. Chart metadata or series names ${metadataChanged ? "also changed" : "unchanged"}. Restoring creates an unapproved correction.`), list);
    panel.hidden = false;
    panel.focus();
  } catch (error) { showToast(error); }
}

function bindReviewTools() {
  byId("undo-edit").addEventListener("click", () => travelEditor("undo"));
  byId("redo-edit").addEventListener("click", () => travelEditor("redo"));
  byId("reverse-rows").addEventListener("click", reverseEditorRows);
  byId("paste-values").addEventListener("click", pasteEditorRows);
  byId("result-form").addEventListener("focusin", (event) => {
    if (event.target.matches?.("input, select")) reviewHistory.pending = editorSnapshot();
  });
  byId("result-form").addEventListener("input", () => {
    if (reviewHistory.pending && reviewHistory.pending !== editorSnapshot()) {
      checkpointEditor(reviewHistory.pending);
      reviewHistory.pending = null;
    }
  }, true);
}
