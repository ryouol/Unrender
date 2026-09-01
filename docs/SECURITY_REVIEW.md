# Security review

Review date: 2026-09-01
Scope: the FastAPI product surface in `unrender/product/`, its browser client, SQLite/storage boundary, packaging, container, and CI. Research/evaluation scripts were scanned for high-risk process, network, deserialization, and secret patterns but are not exposed by the product server.

## Outcome

No open Critical or High repository finding is known after remediation. The first independent review of immutable pre-remediation HEAD `007db52` found three High, multiple Medium, and two Low/documentation issues; the fixes and regression evidence are recorded below. A fresh independent re-review of the final tree remains required before merge. Three Low/Medium deployment risks remain explicit controlled-beta gates because they require the chosen edge, storage platform, or an external test environment.

Evidence run locally:

- `ruff check --select S unrender/product` — passed;
- `pip-audit -r requirements-app.lock` with pip-audit 2.10.1 — no known vulnerabilities;
- hash-locked runtime, development, and build toolchains; the plain wheel includes every dependency needed by its product CLIs;
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
- Location: `unrender/product/web.py:109-124` and `:463-493`; `unrender/product/static/app.js:761-775`, `buyCredits`
- Evidence: the earlier browser code assigned `session.url` directly to `window.location`.
- Impact: an unexpected or compromised provider response could navigate a signed-in user to a phishing destination.
- Fix: require HTTPS and the exact `checkout.stripe.com` hostname on the server and again before browser navigation. A regression test rejects an attacker origin.
- Mitigation: Stripe remains test-mode-only and CSP remains strict.
- False positive notes: the value is returned by Stripe rather than an end user, so exploitation requires a provider/integration failure; the redirect is still a security-sensitive sink.

### 3. API keys had no product revocation path

- Rule ID: FASTAPI-AUTHZ-001
- Severity: Medium
- Location: `unrender/product/service.py:818-869`; `unrender/product/web.py:451-461`; `unrender/product/static/app.js:689-759`
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
- Location: `unrender/product/static/app.js:24`, `routeSegment`; route uses at `:273`, `:379`, `:408`, `:442`, `:459`, `:476`, `:652`, `:671`, and `:738`
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

### 9. Anonymous visitors shared one mutable demo tenant

- Rule ID: FASTAPI-AUTHZ-002
- Severity: High
- Evidence: independent sessions resolved to the same seeded user, so one visitor could list another visitor's jobs/uploads and use normal key, billing, mutation, and deletion paths.
- Impact: immediate cross-visitor disclosure and destructive access on a public demo.
- Fix: create a distinct ephemeral `demo` user for every sample session; enforce the role server-side; permit only the exact hash-matched fixture; deny customer uploads, keys, and billing; remove the tenant and queue its files after its last session ends. Isolation and logout cleanup are regression-tested.

### 10. Container readiness used a Host forbidden by production

- Rule ID: CONTAINER-HEALTH-001
- Severity: High
- Evidence: production TrustedHost accepted only the public hostname while the old Docker probe sent `Host: 127.0.0.1`, guaranteeing an unhealthy container.
- Impact: a correctly configured production instance could be restarted or removed from service continuously.
- Fix: ship `unrender-healthcheck`, which probes loopback while sending the configured public Host, and make CI boot an actual production-configured non-root container until it reports healthy.

### 11. Zero-credit API callers could persist unbounded files

- Rule ID: FASTAPI-DOS-002
- Severity: High
- Evidence: the old v1 route stored an upload before credit reservation; a `402` removed only the job copy and left upload rows/files. The reviewer reproduced three surviving files from three zero-credit calls.
- Impact: one invited or compromised account could fill the shared volume without spending a credit.
- Fix: reject customer persistence when balance is zero; enforce tenant stored-byte, unattached-upload, and upload-bandwidth quotas; count job copies; and atomically persist upload, job, credit reservation, and API response. Regression tests prove a rejected zero-credit request leaves no row, idempotency record, or file.

### 12. File deletion lost its retry record on storage failure

- Rule ID: STORAGE-DELETE-001
- Severity: Medium
- Evidence: job/retention rows were committed away before `Storage.delete`; a simulated volume failure left an unowned source with no durable retry handle.
- Impact: customer data could outlive deletion/retention promises indefinitely.
- Fix: commit every removal to `pending_deletions`, retry failures with attempt/error state, reconcile product-owned orphan files at startup/hourly cleanup, and return `202 deletion_queued` when immediate removal fails. File-outage, retention, and crash-orphan tests cover the paths.

### 13. Worker races, readiness, and crash replay violated credit/liveness invariants

- Rule ID: JOB-LIFECYCLE-001
- Severity: Medium
- Evidence: delete could race reprocess after a stale status read; production could start without a worker; interrupted provider work could be replayed indefinitely.
- Impact: a reserved credit could disappear with its job, readiness could lie, and repeated restarts could cause uncontrolled provider spend.
- Fix: re-read/delete inside `BEGIN IMMEDIATE`; require the embedded worker in production and include thread plus writable-volume state in readiness; store `recovery_count`, bound restart recovery, and dead-letter/refund on exhaustion while preserving a prior reviewed result.

### 14. Secrets and password hashes used weak host defaults

- Rule ID: STORAGE-PERM-001 / PASSWORD-KDF-001
- Severity: Medium
- Evidence: SQLite/WAL/SHM could be created `0644`; source directories inherited `0755`; legacy password hashes used the lowest prior scrypt work factor.
- Impact: other local users could read hashed credentials/customer data, and offline password guessing was cheaper than current guidance.
- Fix: set umask `077`, directories `0700`, database/WAL/SHM/source files `0600`; encode scrypt parameters, use an OWASP-listed `N=2^14,r=8,p=5` profile, and transparently upgrade legacy hashes after a successful login. Modes and rehashing are tested.

### 15. Public submissions were not idempotent

- Rule ID: API-IDEMPOTENCY-001
- Severity: Medium
- Evidence: retrying the same multipart request after a response loss produced two job IDs and reserved two credits.
- Impact: normal client retries could double-charge and double-spend provider capacity.
- Fix: require a tenant-scoped `Idempotency-Key`, bind it to a canonical filename/page/content hash, persist the initial response in the same transaction as upload/job/credit reservation, replay exact retries, reject different input with `409`, expire old keys, and test rows/files/balance.

### 16. Build, wheel, and provider artifacts were mutable or incomplete

- Rule ID: PYTHON-SUPPLY-CHAIN-001 / AI-SUPPLY-CHAIN-002
- Severity: Medium
- Evidence: build isolation fetched mutable tooling; dev dependencies were unhashed; the plain wheel exposed CLIs without their runtime imports; the Modal app/function could drift despite a pinned model commit.
- Impact: a clean build could differ or fail, and an unapproved provider deployment could serve production requests.
- Fix: exact build requirements plus hashed runtime/dev/build locks, no-isolation builds, core product dependencies for plain-wheel CLIs, production container smoke, and a required 64-character provider-release handshake derived from the provider contract/dependency runtime. A real canary and external image provenance remain owner gates.

### 17. Export and editor behavior could corrupt reviewed evidence

- Rule ID: EXPORT-INTEGRITY-001 / JS-DATA-INTEGRITY-001
- Severity: Medium
- Evidence: XLSX numeric cells were strings; UI grouping collapsed duplicate/mixed-type x-values, converted numeric-looking strings, and turned null series names into labels; product copy implied JSON/CSV contained metadata they did not.
- Impact: a saved or exported table could differ silently from the reviewed result.
- Fix: write typed workbook numbers, use a multi-series long-form export that preserves duplicates, retain x types/null names/point order through the editor, test mixed/duplicate cases, and narrow copy: JSON/CSV are data-only while XLSX carries the audit sheet. Visible/restorable result history now makes versions inspectable.

### 18. Public configuration, polling, and crop controls did not match production use

- Rule ID: PRODUCT-STATE-001 / ACCESSIBILITY-INPUT-001
- Severity: Medium
- Evidence: production advertised registration that it always rejected; rapid polling shared an IP bucket and stopped on `429`; asynchronous refunds left displayed credits stale; cropping was pointer-only.
- Impact: invited users hit a dead conversion path, active jobs appeared stuck, balances appeared wrong, and keyboard users could not complete multi-chart pages.
- Fix: expose non-secret public registration/sample flags, hide disabled CTAs, scope authenticated request buckets to credentials, give adaptive/backoff polling a dedicated allowance, refresh account state on transitions, reset delay on job switches, and provide validated keyboard percentage crop fields.

### 19. Provider failures emitted no actionable telemetry

- Rule ID: OBSERVABILITY-001
- Severity: Medium
- Evidence: normalized provider failures changed job state but emitted no `unrender.*` lifecycle record, so the documented provider alert could not be built.
- Impact: an operator could miss a provider outage until customers reported it.
- Fix: emit privacy-safe structured start/success/failure records with opaque job ID, provider/error code, and elapsed milliseconds; exclude source names, chart values, raw output, tenant identity, and credentials. Regression tests assert both required fields and absent private details.

## Open deployment findings

### 20. Hostile document scanning and edge timeouts are deployment controls

- Rule ID: FASTAPI-DOS-001
- Severity: Medium
- Evidence: decoded pixels, PDF pages/passwords, supported magic, streamed/chunked body bytes, tenant storage, and upload bandwidth are bounded in the app. PDFs are parsed but not malware-scanned/content-disarmed, and socket/CPU timeouts depend on the chosen edge/runtime.
- Impact: an invited attacker could submit a parser-hostile document or hold expensive connections within platform limits.
- Fix: before external customer data, record edge body/timeouts, isolate parsing, fuzz hostile images/PDFs, and add malware/CDR scanning or explicitly reject PDFs for the first beta.
- Mitigation: registration is closed in production; credits and per-tenant quotas constrain persistence; PyMuPDF/Pillow are locked and pixel/page/file limits fail closed.
- False positive notes: some deployment platforms impose safe limits automatically; verify and record the exact runtime behavior.

### 21. Application rate limiting remains single-node

- Rule ID: FASTAPI-ABUSE-001
- Severity: Low
- Location: `unrender/product/web.py:189-224`; `unrender/product/service.py:1101-1119`, `rate_limit`
- Evidence: authenticated traffic is scoped to a digest of its session/bearer credential and unauthenticated traffic to client IP, but SQLite counters are not shared across replicas.
- Impact: horizontal replicas would enforce inconsistent abuse limits; pre-auth IP attribution still depends on the trusted edge.
- Fix: select a deployment platform, enforce per-IP/account limits at its trusted edge, and move shared limits to a managed store before horizontal scaling.
- Mitigation: the documented controlled beta is one node; upload bytes and stored volume have separate tenant bounds.
- False positive notes: direct deployments preserve client IP; trusted-proxy behavior is platform-specific and intentionally not guessed in app code.

### 22. Sessions lack user-facing inventory and global revocation

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
