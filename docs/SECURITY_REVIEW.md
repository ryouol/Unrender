# Security review

Review date: 2026-09-01  
Scope: the FastAPI product surface in `unrender/product/`, its browser client, SQLite/storage boundary, packaging, container, and CI. Research/evaluation scripts were scanned for high-risk process, network, deserialization, and secret patterns but are not exposed by the product server.

## Outcome

No open Critical or High repository finding remains. Eight findings were fixed in this branch. Three Medium/Low deployment risks remain explicit controlled-beta gates because they require the chosen edge, storage platform, or an external test environment.

Evidence run locally:

- `ruff check --select S unrender/product` — passed;
- `pip-audit -r requirements-app.lock` with pip-audit 2.10.1 — no known vulnerabilities;
- current-tree and full-Git-history secret-pattern scans — zero matches for common live Stripe, GitHub, AWS, and private-key formats;
- systematic searches for DOM HTML sinks, string-to-code execution, unsafe message/storage use, SQL construction, unsafe deserialization, shell execution, unrestricted CORS, and debug/docs exposure;
- product lint, typing, JavaScript syntax, HTTP security regression tests, and the full repository test suite.

The dependency result is a point-in-time advisory check, not proof that dependencies are vulnerability-free. The CI workflow repeats it on every pull request.

## Fixed findings

### 1. Unvalidated host and production API schema exposure

- Rule ID: FASTAPI-CONFIG-001 / FASTAPI-DOCS-001
- Severity: Medium
- Location: `unrender/product/web.py:127-166`, `create_app`; `unrender/product/config.py:71-103`, `Settings.validate`
- Evidence: the earlier app accepted any `Host` value and disabled Swagger UI in production while leaving the OpenAPI JSON endpoint enabled.
- Impact: poisoned absolute URL generation or cache behavior at a permissive proxy, plus unnecessary production endpoint enumeration.
- Fix: validate `UNRENDER_BASE_URL` as one origin, enforce `TrustedHostMiddleware`, and set both documentation and OpenAPI URLs to `None` in production. Added hostile-host and unexpected-field HTTP tests.
- Mitigation: the deployment edge must also preserve the intended host and TLS configuration.
- False positive notes: a correctly configured edge could already reject hostile hosts, but that control was not visible in the repository.

### 2. Checkout navigation trusted a provider-returned URL

- Rule ID: JS-URL-001
- Severity: Medium
- Location: `unrender/product/web.py:109-124` and `:463-493`; `unrender/product/static/app.js:760-774`, `buyCredits`
- Evidence: the earlier browser code assigned `session.url` directly to `window.location`.
- Impact: an unexpected or compromised provider response could navigate a signed-in user to a phishing destination.
- Fix: require HTTPS and the exact `checkout.stripe.com` hostname on the server and again before browser navigation. A regression test rejects an attacker origin.
- Mitigation: Stripe remains test-mode-only and CSP remains strict.
- False positive notes: the value is returned by Stripe rather than an end user, so exploitation requires a provider/integration failure; the redirect is still a security-sensitive sink.

### 3. API keys had no product revocation path

- Rule ID: FASTAPI-AUTHZ-001
- Severity: Medium
- Location: `unrender/product/service.py:818-869`; `unrender/product/web.py:451-461`; `unrender/product/static/app.js:688-758`
- Evidence: keys were hashed and `revoked_at` existed in schema, but the product exposed creation only.
- Impact: a leaked integration key could not be invalidated by its owner without direct database access.
- Fix: add tenant-scoped list and idempotent revoke operations, audit revocations, reveal neither key hash nor secret, and test that a revoked key immediately receives HTTP 401.
- Mitigation: full keys are still shown once and the UI directs users to a secret manager.
- False positive notes: an operator could previously revoke a row manually, but that is not a reliable customer workflow.

### 4. Spreadsheet exports accepted formula-bearing cells

- Rule ID: EXPORT-FORMULA-001
- Severity: High
- Location: `unrender/product/service.py:744-802`, `ProductService.export`, `_safe_csv`, and `_xlsx`
- Evidence: chart labels/categories and source names were written directly to CSV/XLSX cells. A chart supplied by another party could begin a cell with `=`, `+`, `-`, or `@` and be interpreted as a formula by spreadsheet software.
- Impact: opening an exported workbook could execute spreadsheet formulas, potentially causing external requests, data disclosure, or unsafe command behavior in vulnerable spreadsheet configurations.
- Fix: neutralize formula-bearing text in CSV and XLSX while preserving valid signed numeric cells; keep JSON exact. Regression tests load the workbook and assert the cells are strings rather than formulas.
- Mitigation: users still review extracted rows before approval, and exports retain the original source for comparison.
- False positive notes: numeric values such as `-9.2` remain numeric text; only non-numeric active prefixes are neutralized.

### 5. Missing-user login returned before password KDF work

- Rule ID: FASTAPI-AUTHN-001
- Severity: Low
- Location: `unrender/product/service.py:228-239`, `ProductService.authenticate`
- Evidence: an unknown email skipped scrypt verification while a known email performed it.
- Impact: repeated timing measurements could assist account enumeration.
- Fix: verify against a process-local salted dummy hash when no user exists; error text remains identical.
- Mitigation: login requests also pass through the application rate limiter; production needs edge abuse controls.
- False positive notes: network variance makes the signal noisy, but eliminating the branch is inexpensive defense in depth.

### 6. Middleware rejection responses missed the normal security headers

- Rule ID: FASTAPI-HEADERS-001
- Severity: Low
- Location: `unrender/product/web.py:169-253`, `secure_response` and `request_guard`
- Evidence: size, rate, and origin rejection paths returned before the response-header block.
- Impact: error pages had a weaker browser policy than successful responses.
- Fix: one response hardening function now covers both early rejection and normal responses. HSTS remains production-only and no longer asserts control of all subdomains.
- Mitigation: the selected edge should set equivalent headers as defense in depth.
- False positive notes: JSON error bodies do not render active HTML, which lowers practical impact.

### 7. Dynamic same-origin paths were not component-encoded

- Rule ID: JS-URL-002
- Severity: Low
- Location: `unrender/product/static/app.js:269-277`, `:400-408`, and `:427-445`
- Evidence: server-issued job/upload identifiers were interpolated directly into URL paths.
- Impact: current IDs are generated UUIDs, so no exploit was present; future changes to identifier provenance could make path interpretation surprising.
- Fix: encode each dynamic identifier before assigning a URL-bearing property.
- Mitigation: server routing and tenant checks remain authoritative.
- False positive notes: this was preventive hardening because current identifiers are trusted UUIDs.

### 8. Production accepted public registration and a mutable model target

- Rule ID: FASTAPI-CONFIG-002 / AI-SUPPLY-CHAIN-001
- Severity: Medium
- Location: `unrender/product/config.py:87-103`, `Settings.validate`; `unrender/product/admin.py:16-50`
- Evidence: the earlier production checks required Modal and a non-empty revision, but still allowed open account registration, a local model path, and an arbitrary revision label.
- Impact: a public deployment could create unapproved inference spend, while a mutable or local-only model target made the production artifact neither reproducible nor reliably deployable.
- Fix: production now rejects public registration, accepts only an approved `owner/model` repository, and requires a full 40-character commit. A local operator command provisions invited accounts without placing passwords in process arguments and without starting a worker or recovering jobs.
- Mitigation: real provider credentials, model/data rights, canary output, and spend approval remain external launch gates.
- False positive notes: an operator could previously choose safe environment values manually, but repository configuration did not enforce those claims.

## Open deployment findings

### 9. Body limits and hostile document scanning depend partly on the edge

- Rule ID: FASTAPI-DOS-001
- Severity: Medium
- Location: `unrender/product/web.py:189-224` and `:358-366`; `unrender/product/storage.py:36-78`, `Storage.inspect`
- Evidence: decoded image pixels, PDF page count, supported magic, and application read size are bounded, but a chunked request without `Content-Length` can be spooled by the ASGI multipart stack before endpoint validation. PDFs are parsed but not malware-scanned or content-disarmed.
- Impact: an authenticated or newly registered attacker could consume bandwidth/disk/CPU, or submit a parser-hostile document.
- Fix: before external customer data, configure an edge request-body limit and timeout; isolate upload parsing; add malware/CDR scanning or explicitly reject PDFs for the first beta.
- Mitigation: registration can be closed, credits constrain successful extraction, PyMuPDF and Pillow are locked/audited, and pixel/page/file limits fail closed after parsing.
- False positive notes: some deployment platforms impose safe limits automatically; verify and record the exact runtime behavior.

### 10. Application rate limiting is single-node and proxy-sensitive

- Rule ID: FASTAPI-ABUSE-001
- Severity: Low
- Location: `unrender/product/web.py:189-224`; `unrender/product/service.py:1101-1119`, `rate_limit`
- Evidence: SQLite buckets use `request.client.host`; a reverse proxy can collapse users to one address, and multiple replicas would not share state.
- Impact: false throttling behind a proxy or inconsistent abuse enforcement across replicas.
- Fix: select a deployment platform, enforce per-IP/account limits at its trusted edge, and move shared limits to a managed store before horizontal scaling.
- Mitigation: the documented controlled beta is a single node and has a high configurable application fallback.
- False positive notes: direct deployments preserve client IP; trusted-proxy behavior is platform-specific and intentionally not guessed in app code.

### 11. Sessions lack user-facing inventory and global revocation

- Rule ID: FASTAPI-SESSION-001
- Severity: Low
- Location: `unrender/product/service.py:253-302`, session methods; browser account UI
- Evidence: logout revokes the current hashed session and expiry cleanup exists, but users cannot view other sessions or sign out everywhere.
- Impact: a copied session remains usable until expiry unless the operator deletes it.
- Fix: add session inventory, global revocation, security-event notification, and optionally MFA/SSO before a broad paid launch.
- Mitigation: sessions are random and hashed, use HttpOnly/SameSite cookies, use Secure in production, expire after a configurable period, and require CSRF for mutations.
- False positive notes: the risk is lower for a small design-partner beta with short retention and controlled accounts.

## External gates

Container scanning, hostile-file fuzzing, penetration testing, platform TLS/proxy validation, encrypted-volume verification, backup restoration, and real Modal canarying cannot be proven from this repository alone. They remain blocked in `docs/LAUNCH_READINESS.md`; the product must not be represented as generally available until those gates and the legal/privacy gates are closed.
