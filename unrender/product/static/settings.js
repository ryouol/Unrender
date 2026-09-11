function openSettings() {
  if (!state.account) return;
  const account = state.account;
  byId("signin-methods-note").textContent = account.google_connected
    ? (account.has_password ? "Google and password sign-in are connected to this account." : "Sign in with your connected Google account. Google manages account recovery.")
    : "You sign in with an email address and password.";
  byId("connect-google-form").hidden = !state.publicConfig.google_available || account.google_connected || !account.has_password;
  byId("settings-retention").textContent = `Charts are retained for ${account.retention_days} days after their last update. Download exports you need to keep.`;
  byId("delete-account-button").hidden = Boolean(account.demo_account);
  clearError("settings-error");
  byId("settings-dialog").showModal();
}

function closeSettings() {
  byId("connect-google-form").reset();
  if (byId("settings-dialog").open) byId("settings-dialog").close();
}

function resetSettings() {
  closeSettings();
  byId("connect-google-form").inert = false;
  byId("connect-google-form").removeAttribute("aria-busy");
  for (const id of ["signin-methods-note", "settings-retention", "settings-error"]) byId(id).textContent = "";
}

async function connectGoogle(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (form.getAttribute("aria-busy") === "true") return;
  if (!discardEditorChanges()) return;
  const password = new FormData(form).get("password");
  const epoch = state.authEpoch;
  form.reset();
  form.setAttribute("aria-busy", "true");
  form.inert = true;
  clearError("settings-error");
  try {
    const result = await libraryApi("/api/auth/google/link", { method: "POST", body: { password } });
    const url = new URL(result.url);
    if (url.protocol !== "https:" || url.hostname !== "accounts.google.com") throw new Error("Google sign-in returned an unexpected destination.");
    window.location.assign(url.href);
  } catch (error) { showError("settings-error", error); }
  finally {
    if (epoch === state.authEpoch) { form.inert = false; form.removeAttribute("aria-busy"); }
  }
}

function deleteAccount() {
  const account = state.account;
  if (!account || account.demo_account) return;
  closeSettings();
  const fields = [];
  if (account.has_password) fields.push(dialogField("Current password", "password", { type: "password" }));
  else {
    const note = libraryNode("p", "Google accounts require a recent identity check. ", "dialog-note");
    const link = libraryNode("a", "Verify with Google");
    link.href = "/auth/google/reauthenticate";
    note.append(link);
    fields.push(note);
  }
  fields.push(dialogField("Type DELETE to confirm", "confirmation"));
  return openLibraryDialog({ title: "Delete your account?", note: "All charts, projects, review history, API keys, and account access will be permanently removed. This cannot be undone. Running extractions must finish or be cancelled first. Private backups expire under the backup retention policy.", fields, submit: "Permanently delete account", danger: true, action: async (data) => {
    if (data.get("confirmation") !== "DELETE") throw new Error("Type DELETE exactly to confirm.");
    if (account.has_password) await libraryApi("/api/auth/reauthenticate", { method: "POST", body: { password: data.get("password") } });
    const result = await libraryApi("/api/auth/delete-account", { method: "POST", body: { confirmation: "DELETE" } });
    quarantineAuth("signed-out", { clearCsrf: true });
    await publishAuthChange("session-ended");
    showToast(result?.status === "deletion_queued" ? "Account removed. Private file cleanup will retry automatically." : "Your account and workspace have been deleted.");
  } });
}

function bindSettingsEvents() {
  for (const id of ["settings-button", "footer-settings-button"]) byId(id).addEventListener("click", openSettings);
  byId("close-settings").addEventListener("click", closeSettings);
  byId("settings-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeSettings(); });
  byId("settings-dialog").addEventListener("close", () => byId("connect-google-form").reset());
  byId("connect-google-form").addEventListener("submit", connectGoogle);
  byId("delete-account-button").addEventListener("click", deleteAccount);
}

function bindReviewResize() {
  const divider = byId("review-divider");
  const layout = byId("review-layout");
  let dragging = false;
  const set = (value) => {
    const percent = Math.round(Math.max(30, Math.min(70, value)));
    layout.style.setProperty("--source-share", `${percent}%`);
    divider.setAttribute("aria-valuenow", String(percent));
  };
  divider.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    dragging = true;
    divider.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  divider.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const bounds = layout.getBoundingClientRect();
    set((event.clientX - bounds.left) / bounds.width * 100);
  });
  for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) divider.addEventListener(event, () => { dragging = false; });
  divider.addEventListener("keydown", (event) => {
    const current = Number(divider.getAttribute("aria-valuenow"));
    const values = { ArrowLeft: current - 5, ArrowRight: current + 5, Home: 30, End: 70 };
    if (!(event.key in values)) return;
    event.preventDefault();
    set(values[event.key]);
  });
  divider.addEventListener("dblclick", () => set(55));
}
