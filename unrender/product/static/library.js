const library = { projects: [], filter: "all", project: "", search: "", page: 0, layout: "grid", dialog: null };
const LIBRARY_PAGE_SIZE = 24;

function chartName(job) { return job.display_name || job.source_name; }

function resetLibrary() {
  library.projects = [];
  library.filter = "all";
  library.project = "";
  library.search = "";
  library.page = 0;
  byId("chart-search").value = "";
  byId("project-filter").replaceChildren();
  byId("project-list").replaceChildren();
  closeLibraryDialog(true);
  if (byId("settings-dialog").open) byId("settings-dialog").close();
  byId("connect-google-form").reset();
  byId("connect-google-form").inert = false;
  byId("connect-google-form").removeAttribute("aria-busy");
}

function libraryNode(tag, text, className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
}

function libraryMenu(label, actions) {
  const menu = document.createElement("details");
  menu.className = "action-menu library-menu";
  const summary = libraryNode("summary", "More");
  summary.setAttribute("aria-label", label);
  const content = libraryNode("div", "", "action-menu-content");
  for (const [title, action, danger] of actions) {
    content.append(actionButton(title, danger ? "button-danger" : "button-quiet", async () => {
      menu.open = false;
      await action();
    }));
  }
  menu.append(summary, content);
  return menu;
}

async function loadProjects() {
  const result = await api("/api/projects");
  library.projects = result.items;
  if (library.project && !library.projects.some((project) => project.id === library.project)) library.project = "";
  const select = byId("project-filter");
  select.replaceChildren(libraryNode("option", "All projects"));
  select.children[0].value = "";
  for (const project of library.projects) {
    const option = libraryNode("option", project.name);
    option.value = project.id;
    select.append(option);
  }
  select.value = library.project;
  if (!byId("projects-view").hidden) renderProjects();
}

function renderLibrary() {
  const jobs = state.jobs.filter((job) => (
    (library.filter === "all" || job.status === library.filter)
    && (!library.project || job.project_id === library.project)
    && `${chartName(job)} ${job.source_name}`.toLocaleLowerCase().includes(library.search)
  ));
  const pages = Math.max(1, Math.ceil(jobs.length / LIBRARY_PAGE_SIZE));
  library.page = Math.min(library.page, pages - 1);
  for (const filter of ["all", "review", "approved"]) {
    byId(`count-${filter}`).textContent = String(state.jobs.filter((job) => filter === "all" || job.status === filter).length);
  }
  for (const button of document.querySelectorAll("[data-chart-filter]")) {
    button.setAttribute("aria-pressed", String(button.dataset.chartFilter === library.filter));
  }
  const list = byId("job-list");
  list.classList.toggle("is-list", library.layout === "list");
  list.replaceChildren();
  for (const job of jobs.slice(library.page * LIBRARY_PAGE_SIZE, (library.page + 1) * LIBRARY_PAGE_SIZE)) {
    const article = libraryNode("article", "", "chart-item");
    const open = document.createElement("button");
    open.type = "button";
    open.className = "chart-open";
    open.setAttribute("aria-label", `Open ${chartName(job)}`);
    open.addEventListener("click", () => openJob(job.id));
    const preview = libraryNode("div", "", "chart-preview");
    const image = document.createElement("img");
    image.src = `/api/jobs/${routeSegment(job.id)}/source?v=${routeSegment(job.updated_at)}`;
    image.alt = "";
    image.loading = "lazy";
    image.decoding = "async";
    image.addEventListener("error", () => { preview.replaceChildren(libraryNode("span", "Preview unavailable")); });
    preview.append(image);
    const name = libraryNode("strong", chartName(job), "chart-name");
    const meta = libraryNode("span", "", "chart-meta");
    const status = libraryNode("span", statusLabel(job.status), `status-${job.status}`);
    const time = libraryNode("time", formatDate(job.updated_at || job.created_at));
    time.dateTime = job.updated_at || job.created_at;
    meta.append(status, time);
    open.append(preview, name, meta);
    article.append(open, libraryMenu(`Actions for ${chartName(job)}`, [
      ["Rename chart", () => renameChart(job)],
      ["Move to project", () => moveChart(job)],
      ["Delete chart", () => deleteLibraryChart(job), true],
    ]));
    list.append(article);
  }
  byId("library-no-results").hidden = jobs.length > 0 || state.jobs.length === 0;
  byId("empty-view").hidden = state.jobs.length > 0 || byId("library-view").hidden;
  byId("library-pagination").hidden = pages === 1;
  byId("library-previous").disabled = library.page === 0;
  byId("library-next").disabled = library.page >= pages - 1;
  byId("library-page-note").textContent = `Page ${library.page + 1} of ${pages}`;
  byId("library-count").textContent = `${jobs.length} chart${jobs.length === 1 ? "" : "s"} · Private to your workspace`;
}

function showLibrary() {
  if (!state.account || !discardEditorChanges()) return;
  stopPolling();
  resetViewSelection();
  clearSelectedChart();
  showMainView("library-view");
  document.title = "My charts — Unrender";
}

async function showProjects() {
  if (!state.account || !discardEditorChanges()) return;
  stopPolling();
  const view = beginViewSelection();
  try {
    await loadProjects();
    if (view.epoch !== state.viewEpoch) return;
    state.currentJob = null;
    showMainView("projects-view");
    renderProjects();
    document.title = "Projects — Unrender";
  } catch (error) { showToast(error); }
}

function renderProjects() {
  const list = byId("project-list");
  list.replaceChildren();
  if (!library.projects.length) list.append(libraryNode("p", "Create a project to group charts for a report or analysis.", "library-no-results"));
  for (const project of library.projects) {
    const row = libraryNode("article", "", "project-row");
    const open = actionButton(project.name, "project-open", () => {
      library.project = project.id;
      byId("project-filter").value = project.id;
      library.page = 0;
      showLibrary();
    });
    row.append(open, libraryNode("span", `${project.chart_count} chart${project.chart_count === 1 ? "" : "s"}`), libraryMenu(`Actions for ${project.name}`, [
      ["Rename project", () => editProject(project)],
      ["Delete project", () => deleteProject(project), true],
    ]));
    list.append(row);
  }
}

function dialogField(label, name, { value = "", type = "text", options = null, hint = "" } = {}) {
  const wrapper = libraryNode("label", label);
  const input = document.createElement(options ? "select" : "input");
  input.name = name;
  if (options) {
    for (const [key, text] of options) {
      const option = libraryNode("option", text);
      option.value = key;
      input.append(option);
    }
  } else {
    input.type = type;
    input.required = true;
    input.maxLength = type === "password" ? 256 : name === "project_name" ? 80 : 120;
    if (type === "password") input.autocomplete = "current-password";
  }
  input.value = value;
  wrapper.append(input);
  if (hint) wrapper.append(libraryNode("span", hint, "label-hint"));
  return wrapper;
}

function closeLibraryDialog(force = false) {
  if (library.dialog?.pending && !force) return;
  const current = library.dialog;
  library.dialog = null;
  if (byId("library-dialog").open) byId("library-dialog").close();
  byId("library-dialog-fields").replaceChildren();
  current?.resolve(false);
}

function openLibraryDialog({ title, note, fields = [], submit = "Save", danger = false, action }) {
  closeLibraryDialog(true);
  byId("library-dialog-title").textContent = title;
  byId("library-dialog-note").textContent = note;
  byId("library-dialog-fields").replaceChildren(...fields);
  const button = byId("library-dialog-submit");
  button.textContent = submit;
  button.className = `button ${danger ? "button-danger" : "button-primary"}`;
  button.disabled = false;
  byId("library-dialog-close").disabled = false;
  byId("library-dialog-form").removeAttribute("aria-busy");
  clearError("library-dialog-error");
  const promise = new Promise((resolve) => { library.dialog = { action, resolve, pending: false, epoch: state.authEpoch }; });
  byId("library-dialog").showModal();
  return promise;
}

async function submitLibraryDialog(event) {
  event.preventDefault();
  const current = library.dialog;
  if (!current || current.pending || !byId("library-dialog-form").reportValidity()) return;
  current.pending = true;
  clearError("library-dialog-error");
  byId("library-dialog-submit").disabled = true;
  byId("library-dialog-close").disabled = true;
  byId("library-dialog-form").setAttribute("aria-busy", "true");
  try {
    await current.action(new FormData(event.currentTarget));
    if (current !== library.dialog || current.epoch !== state.authEpoch) return;
    current.resolve(true);
    closeLibraryDialog(true);
  } catch (error) {
    if (current === library.dialog) showError("library-dialog-error", error);
  } finally {
    if (current === library.dialog) {
      current.pending = false;
      byId("library-dialog-submit").disabled = false;
      byId("library-dialog-close").disabled = false;
      byId("library-dialog-form").removeAttribute("aria-busy");
    }
  }
}

function editProject(project = null) {
  return openLibraryDialog({
    title: project ? "Rename project" : "Create project", note: "A private collection of related charts.",
    fields: [dialogField("Project name", "project_name", { value: project?.name || "" })],
    action: async (data) => {
      await api(project ? `/api/projects/${routeSegment(project.id)}` : "/api/projects", {
        method: project ? "PATCH" : "POST", body: { name: String(data.get("project_name")).trim() },
      });
      await loadProjects();
      showToast(project ? "Project renamed" : "Project created");
    },
  });
}

async function deleteProject(project) {
  try {
    const latest = await api(`/api/projects/${routeSegment(project.id)}`);
    return await openLibraryDialog({
      title: `Delete ${latest.name}?`, note: `This project contains ${latest.chart_count} charts. Choose whether to keep them in My charts or permanently remove their sources, results, and history.`,
      fields: [dialogField("Charts in this project", "mode", { options: [["keep_charts", "Keep charts in My charts"], ["delete_charts", `Permanently delete all ${latest.chart_count} charts`]] })],
      submit: "Delete project", danger: true,
      action: async (data) => {
        const result = await api(`/api/projects/${routeSegment(project.id)}?mode=${routeSegment(data.get("mode"))}&expected_chart_count=${latest.chart_count}`, { method: "DELETE" });
        await Promise.all([loadJobs(), loadProjects()]);
        renderProjects();
        showToast(result.status === "deletion_queued" ? "Project removed. File cleanup will retry automatically." : "Project deleted");
      },
    });
  } catch (error) { showToast(error); }
}

function renameChart(job) {
  if (!discardEditorChanges()) return;
  return openLibraryDialog({ title: "Rename chart", note: "The original source filename stays in the audit record.", fields: [dialogField("Chart name", "name", { value: chartName(job) })], action: async (data) => {
    await api(`/api/jobs/${routeSegment(job.id)}`, { method: "PATCH", body: { display_name: String(data.get("name")).trim() } });
    await loadJobs();
    if (state.currentJob?.id === job.id) await openJob(job.id);
    showToast("Chart renamed");
  } });
}

async function moveChart(job) {
  if (!discardEditorChanges()) return;
  try {
    await loadProjects();
    return await openLibraryDialog({ title: "Move to project", note: chartName(job), fields: [dialogField("Project", "project", {
      value: job.project_id || "", options: [["", "No project"], ...library.projects.map((project) => [project.id, project.name])],
    })], action: async (data) => {
      await api(`/api/jobs/${routeSegment(job.id)}`, { method: "PATCH", body: { project_id: data.get("project") || null } });
      await Promise.all([loadJobs(), loadProjects()]);
      showToast("Chart moved");
    } });
  } catch (error) { showToast(error); }
}

function deleteLibraryChart(job) {
  if (["queued", "running"].includes(job.status)) {
    showToast("Open this chart and cancel its extraction before deleting it.");
    return;
  }
  return openLibraryDialog({ title: `Delete ${chartName(job)}?`, note: "This permanently removes the chart, corrections, and review history. A shared original upload is kept while another chart still uses it. This cannot be undone.", submit: "Delete chart", danger: true, action: async () => {
    const epoch = state.authEpoch;
    const previousView = state.viewEpoch;
    const result = await api(`/api/jobs/${routeSegment(job.id)}`, { method: "DELETE" });
    if (epoch !== state.authEpoch || previousView !== state.viewEpoch) throw staleAuthError();
    state.jobs = state.jobs.filter((item) => item.id !== job.id);
    if (state.currentJob?.id === job.id) {
      state.editorDirty = false;
      showLibrary();
    }
    const currentView = state.viewEpoch;
    await Promise.all([loadJobs(), loadProjects()]);
    if (epoch !== state.authEpoch || currentView !== state.viewEpoch) throw staleAuthError();
    showToast(result?.status === "deletion_queued" ? "Chart removed. File cleanup will retry automatically." : "Chart deleted");
  } });
}

async function discardUpload() {
  if (!state.upload) { showLibrary(); return; }
  const upload = state.upload;
  await openLibraryDialog({ title: "Discard this upload?", note: "The prepared upload will be removed. Charts already extracted from it are kept.", submit: "Discard upload", danger: true, action: async () => {
    await api(`/api/uploads/${routeSegment(upload.id)}`, { method: "DELETE" });
    if (state.upload === upload) {
      state.upload = null;
      byId("upload-preview").removeAttribute("src");
      showLibrary();
    }
    showToast("Upload discarded");
  } });
}

function bindLibraryEvents() {
  for (const id of ["library-button", "back-to-library"]) byId(id).addEventListener("click", showLibrary);
  byId("projects-button").addEventListener("click", showProjects);
  for (const id of ["new-project-button", "add-project-button"]) byId(id).addEventListener("click", () => editProject());
  byId("chart-search").addEventListener("input", (event) => { library.search = event.target.value.trim().toLocaleLowerCase(); library.page = 0; renderLibrary(); });
  byId("project-filter").addEventListener("change", (event) => { library.project = event.target.value; library.page = 0; renderLibrary(); });
  for (const button of document.querySelectorAll("[data-chart-filter]")) button.addEventListener("click", () => { library.filter = button.dataset.chartFilter; library.page = 0; renderLibrary(); });
  for (const layout of ["grid", "list"]) byId(`${layout}-view-button`).addEventListener("click", () => {
    library.layout = layout;
    for (const choice of ["grid", "list"]) byId(`${choice}-view-button`).setAttribute("aria-pressed", String(choice === layout));
    renderLibrary();
  });
  for (const [id, delta] of [["library-previous", -1], ["library-next", 1]]) byId(id).addEventListener("click", () => { library.page += delta; renderLibrary(); });
  byId("library-dialog-form").addEventListener("submit", submitLibraryDialog);
  byId("library-dialog-close").addEventListener("click", () => closeLibraryDialog());
  byId("library-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeLibraryDialog(); });
}
