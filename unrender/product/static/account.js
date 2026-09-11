"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const fragment = new URLSearchParams(location.hash.slice(1));
  const token = fragment.get("token");
  const purpose = fragment.get("account");
  // Remove bearer credentials from the address bar/history before any request.
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  const completing = Boolean(token && ["verify", "reset"].includes(purpose));
  const invitation = completing && purpose === "reset" && new URLSearchParams(location.search).get("mode") === "invite";
  const verifying = completing ? purpose === "verify" : new URLSearchParams(location.search).get("mode") === "verify";
  const form = byId("account-form");
  const button = byId("account-submit");
  const email = form.elements.namedItem("email");
  const password = form.elements.namedItem("password");
  if (completing) {
    form.hidden = false;
    byId("email-field").hidden = true;
    email.disabled = true;
    byId("password-field").hidden = false;
    password.disabled = false;
    password.required = true;
    password.autocomplete = verifying ? "current-password" : "new-password";
    byId("account-title").textContent = verifying ? "Verify your email" : "Choose a new password";
    byId("account-description").textContent = verifying
      ? "Enter the password you chose when signing up to finish verifying your account."
      : "Use at least 12 characters. Resetting your password signs out all sessions and revokes existing API keys. Your saved charts remain in your account.";
    button.textContent = verifying ? "Verify email" : "Reset password";
    if (invitation) {
      byId("account-title").textContent = "Create your workspace password";
      byId("account-description").textContent = "Your operator invited you to Unrender. Choose a password with at least 12 characters to activate your private workspace. This link works once and expires after 30 minutes.";
      button.textContent = "Activate workspace";
    }
  } else if (verifying) {
    byId("account-title").textContent = "Resend verification email";
    byId("account-description").textContent = "Enter the email you used to create your workspace.";
    button.textContent = "Send verification link";
  }
  fetch("/api/public-config", { headers: { Accept: "application/json" } })
      .then(async (response) => {
        if (!response.ok) throw new Error("Account options could not be loaded. Refresh to try again.");
        const config = await response.json();
        byId("email-help-links").hidden = !config.email_available;
        if (completing) return;
        if (config.email_available) {
          form.hidden = false;
          if (!verifying) byId("account-description").textContent = "Enter your email and we’ll send a link to reset your password.";
        } else {
          byId("account-title").textContent = "Request an account link";
          byId("account-description").textContent = "Email recovery is not available for this workspace. Ask the person who invited you for a new account setup or recovery link. Your saved charts remain in your account.";
        }
      })
      .catch((error) => {
        if (completing) return;
        byId("account-error").textContent = error.message;
        byId("account-error").hidden = false;
      });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    byId("account-error").hidden = true;
    try {
      const action = completing ? (verifying ? "verify-email" : "reset-password")
        : (verifying ? "request-verification" : "forgot-password");
      const response = await fetch(`/api/auth/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(completing ? { token, password: password.value } : { email: email.value.trim() }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || "Could not complete the request. Try again shortly.");
      form.reset();
      byId("account-status").textContent = completing
        ? "Your account is ready. Return to sign in with your password."
        : "If an eligible account exists, we’ve requested an email. Check your inbox and spam folder. Links expire after 30 minutes.";
      byId("account-status").hidden = false;
      if (completing) form.hidden = true;
    } catch (error) {
      byId("account-error").textContent = error.message;
      byId("account-error").hidden = false;
    } finally {
      button.disabled = false;
      form.removeAttribute("aria-busy");
    }
  });
})();
