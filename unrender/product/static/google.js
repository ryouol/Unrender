const GOOGLE_INTENT_KEY = "unrender.google-intent.v1";

function startGoogleLogin(event) {
  event.preventDefault();
  const expected = readDurableAuthRecord();
  if (!state.publicConfig.google_available || blocksExplicitLogin(expected) || state.logoutRequest) {
    showError("auth-error", new Error("Finish signing out everywhere before signing in again."));
    return;
  }
  try {
    const intent = crypto.randomUUID() + crypto.randomUUID();
    const encoded = JSON.stringify({ intent, expected });
    sessionStorage.setItem(GOOGLE_INTENT_KEY, encoded);
    if (sessionStorage.getItem(GOOGLE_INTENT_KEY) !== encoded) throw new Error("Browser storage is unavailable.");
    window.location.assign(`/auth/google/start?intent=${encodeURIComponent(intent)}`);
  } catch (_) {
    showError("auth-error", new Error("Allow browser storage to continue with Google, or sign in with your password."));
  }
}

async function completeGoogleLogin(path) {
  let pending;
  try {
    const encoded = sessionStorage.getItem(GOOGLE_INTENT_KEY);
    sessionStorage.removeItem(GOOGLE_INTENT_KEY);
    if (!encoded) return;
    pending = JSON.parse(encoded);
  } catch (_) {
    throw new Error("Google sign-in could not be confirmed in this browser. Please try again.");
  }
  if (path !== "/app") return;
  if (typeof pending?.intent !== "string" || !/^[a-f0-9-]{72}$/.test(pending.intent)
    || !Object.hasOwn(pending, "expected") || !sameAuthRecord(pending.expected, readDurableAuthRecord())
    || blocksExplicitLogin(pending.expected)) {
    throw new Error("Your account changed while Google was open. Please sign in again.");
  }
  const account = await api("/api/auth/google/complete", {
    method: "POST", body: { intent: pending.intent }, authRecord: pending.expected,
  });
  const committed = await publishAuthChange("authenticated", {
    explicitLogin: true, expected: pending.expected, principalMarker: account.principal_marker,
  });
  if (!committed) throw staleAuthError("A sign-out superseded this Google sign-in.");
}

function updateGoogleLoginGate() {
  const blocked = blocksExplicitLogin(readDurableAuthRecord()) || Boolean(state.logoutRequest);
  for (const id of ["google-signin", "google-signup"]) byId(id)?.setAttribute("aria-disabled", String(blocked));
}

function googleReturnError(code) {
  const messages = {
    google_expired: "Google sign-in expired. Please try again.",
    google_cancelled: "Google sign-in was cancelled. You can try again or use your password.",
    google_failed: "Google sign-in could not be completed. Please try again.",
    google_unavailable: "Google sign-in is temporarily unavailable. Please try again later.",
    google_link_required: "This email already has an account. Sign in with your password, then connect Google in Account settings.",
    google_already_linked: "This Google identity is already connected to another account.",
    google_account_mismatch: "Choose the Google account already connected to this workspace.",
    registration_closed: "New accounts require an invitation during the beta.",
    reauthentication_required: "Please verify your identity again before continuing.",
  };
  return messages[code] || (code ? "Google sign-in could not be completed. Please try again." : null);
}
