/* Public-site consent has no access to account or chart state. */
(() => {
  "use strict";
  const key = "unrender.optional-analytics-consent.v1";
  const notice = document.getElementById("cookie-notice");
  if (!notice) return;
  let choice = null;
  try { choice = localStorage.getItem(key); } catch (_) { /* Default: no consent. */ }
  notice.hidden = choice === "accepted" || choice === "rejected";
  const save = (value) => {
    try { localStorage.setItem(key, value); } catch (_) { /* Choice stays in this page. */ }
    notice.hidden = true;
    document.getElementById("cookie-settings").focus();
  };
  document.getElementById("cookie-reject").addEventListener("click", () => save("rejected"));
  document.getElementById("cookie-accept").addEventListener("click", () => save("accepted"));
  document.getElementById("cookie-settings").addEventListener("click", () => {
    notice.hidden = false;
    document.getElementById("cookie-reject").focus();
  });
  // TODO: provide approved analytics provider and measurement ID. Keep network
  // collection disabled until legal review; if enabled, require choice === "accepted",
  // honour withdrawal, and never send chart contents, account IDs, URLs or filenames.
})();
