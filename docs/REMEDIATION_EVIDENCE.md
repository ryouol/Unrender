# Exact-review remediation evidence

This record covers the remediation of independent reviews performed against
commits `13375b55dd3e89c067a1edb622e937f2c3a1b1a3`,
`f038311271c4513bba9dea37796bd15553bbc0f8`, and
`ab13830b7a10834e10e4d9f14ab627ebb8d224cd`. It records repository evidence, not
a claim that the service is approved for public or commercial launch. The final
commit SHA belongs in the handoff or pull request after a read-only review of
that exact tree.

## Implemented boundaries

- Durable, expiring owner/token/generation worker leases now fence progress,
  result versions, provider dispatch, terminal state, audits, and refunds. Only
  an expired lease can be recovered, and post-dispatch ambiguity is never
  silently redriven or refunded.
- SQLite migrations are cross-process serialized, transaction-atomic, and
  restart-safe across complete and interrupted legacy shapes.
- Modal deployment uses the exact `infer_one` contract and normalized immutable
  release digests; a non-spending resolver check is available before any real
  canary.
- Training inputs are copied into a private, content-addressed, read-only
  materialization after descriptor-level no-follow and before/after metadata
  checks. Symlinks, special files, writable sources, swaps, and cache drift are
  rejected.
- Browser logout and account switches abort outstanding work, advance an auth
  epoch, revoke object URLs, and clear every private table, form, image, editor,
  version, audit, render, source, and API-key dialog state.
- Request streams, uploads, render work, and password KDFs have separate bounded
  concurrency and body limits. Tenant and global database state, active keys,
  sessions, audit detail/rollups, provider attempts, and credit ledgers are
  bounded and cursor-paginated where inventory completeness matters.
- Dispatch state and failure circuits prevent pre-dispatch spend and repeated
  post-dispatch failure/cancellation from becoming a free-inference loop.
- Backup and restore use a coordinated mutation lock, hash inventory, safe-path
  validation, SQLite integrity checks, and publish into an absent destination.
- PyMuPDF was removed from product code and exact locks. PDF rendering now uses
  locked `pypdfium2`/PDFium with shipped notices, SBOM, and policy-drift checks.

## `f038311` finding map

The second review in this record reported 2 High, 8 Medium, and 5 actionable Low
findings. Each repository-controlled finding maps to an implementation and an
adversarial regression:

| Finding | Implemented boundary and regression |
|---|---|
| H1 — cross-tab principal privacy | Account session generations and `/api/me` principal markers combine with BroadcastChannel/storage/focus/visibility/pageshow coordination. Every private DOM/blob/poll/controller is synchronously reset; a localStorage-persisted logout barrier blocks reconciliation until explicit reauthentication; old auth/selection epochs cannot write. A Node two-tab/new-tab harness and a real shared-session Chromium journey cover logout, account replacement, and delayed responses. |
| H2 — deletion retained original upload | The immediate job-delete transaction queues the job source and the last-reference upload source, then removes both rows. Shared-upload, storage-outage, preview-denial, retry, and outbox-drain tests cover the lifecycle. |
| M1 — correction transport cap | The correction route has a result-contract-plus-envelope byte limit. Tests accept a service-valid result near 1 MiB, accept the exact route boundary, and reject the next byte with `413`. |
| M2 — ledger emergency capacity | Database admission reserves one future ledger append for every outstanding refundable obligation plus its mandatory terminal/audit rows. N-job reservation, billing, cancellation, failure, recovery, and exact-pressure tests preserve refunds. |
| M3 — browser submission idempotency | Paid browser creation requires a durable account/upload/page/crop-bound `Idempotency-Key`; ambiguous retries reuse the key until one response is confirmed. Missing, changed, same-key retry, and concurrent double-submit tests prove one job/charge. |
| M4 — result-history reservation | Initial, API, and reprocess attempts reserve an attempt-fenced worst-case result byte budget before credit/provider work. Success settles actual bytes; pre-dispatch termination releases it. Capacity rejection is deterministic and uncharged; startup never invents an unadmitted reservation for legacy/corrupt attempts. |
| M5 — maximum-result editor expansion | The editor holds the strict 10,000-row contract sparsely, renders 40 rows per page, and enforces at most 500 actual mounted descendants. Node and real Chromium performance assertions cover 50 series × 200 points. |
| M6 — crash-durable source publication | Staging, upload rename, and job copy fsync file bytes plus source/destination namespaces before SQLite references. Durable reservation records protect live crash remnants; fault injection at publication checkpoints verifies restart reconciliation. |
| M7 — global retained bytes/free space | Transactional cross-process reservations cover staging, uploads, job copies, worst-case results, pending deletion, database files, and configured headroom; minimum free space also fails closed. Multi-tenant/concurrent/low-free/restart tests exercise admission and cleanup. |
| M8 — central database-row admission | All service append paths use one transactional row-admission boundary with tenant/global budgets and mandatory terminal/refund/audit reserves. Static source assertions and exact-pressure lifecycle tests cover success, cancellation, failure, billing, and recovery. |
| L1 — API-key secret lifetime | Close, cancel, copy, dismiss, timeout, logout, and account switch clear the one-time secret synchronously; browser regressions exercise each path. |
| L2 — per-selection stale writes | Each job selection owns an epoch and `AbortController`; source, result, version, audit, correction, and mutation handlers verify it before every async write. Delayed old-selection tests cannot replace the current job. |
| L3 — invalid provider success log | Provider output is decoded and validated against `ChartData` plus product constraints before any success lifecycle record. Invalid output terminates as `model_output_invalid` and never emits success. |
| L4 — backup/restore durability | Backup and restore fsync files, manifests, staging/final trees, and parent namespaces before reporting success. Fault/durability tests exercise publication and restore. |
| L5 — session control | The controlled-pilot choice is bounded global revocation: sign out deletes all account sessions and increments the session generation, immediately invalidating old cookies across tabs. Per-device inventory and security-event notification remain explicitly outside the pilot and required before broader launch. |

## `ab13830` finding map

The next exact review reported 1 High, 5 Medium, and 1 actionable Low finding.
Each repository-controlled finding has a fail-closed implementation and an exact
adversarial regression:

| Finding | Implemented boundary and regression |
|---|---|
| H1 — cross-tab logout barrier bypass | The canonical v2 auth record is synchronously reread on storage, BroadcastChannel, focus, visibility, and pageshow. Missing, malformed, duplicated, or reordered notifications cannot clear quarantine. A v1 logout barrier is promoted before any `/api/me` check, including a fresh v2 tab beside a still-open v1 tab; throwing or silently ignored persistence still applies an in-memory non-auth barrier. V2 first commits its own barrier and wakes live deployed-v1 tabs only by BroadcastChannel while the old cookie may work. It mutates and retains legacy storage only after logout or an authoritative `401` proves that cookie unusable; an explicit login retires the legacy barrier only after the new cookie exists. The exact old handler is tested with every channel task delivered before an arbitrarily late dropped-detail storage task, plus failed revocation with no legacy storage mutation, so neither path can restore the old principal. Storage-only, new-tab, BFCache, both mixed-version directions, persistence-failure, lost-response, and explicit-login recovery remain covered. |
| M1 — free-reprocess row bypass | Reprocess admits its complete future row obligation before any status, attempt, audit, result-reservation, or credit transition even when the saved fixture costs zero. Exact-pressure rejection is byte-equivalent and leaves already-admitted terminal/recovery work executable. |
| M2 — reservation publication/delete race | Each retained-byte reservation has an opaque owner token and renewable expiry. Resize and release are token-fenced; publication must consume the matching live reservation in the same final transaction. Deletion holds an exclusive cross-process operational lock across final reference check and file removal. Expiry, stale-token, token-loss, and deterministic two-service races finish as either rejected-and-cleaned or committed-row-plus-file. |
| M3 — browser create idempotency | The account/upload/page/crop-bound key and request body stay durable through POST, account refresh, complete job inventory, and selected-job convergence. Ambiguous and post-success UI failures retry the same key/body; tests prove two POST attempts produce one logical charge. |
| M4 — sign-out-everywhere failure | Sign-out writes a durable local quarantine first, then awaits bounded keepalive-safe revocation attempts. Non-2xx/network ambiguity is persisted and surfaced with a retry action; a server-confirmed local 401 is explicitly labelled globally unconfirmed rather than success. Successful revocation alone publishes confirmed signed-out. |
| M5 — in-flight export privacy | Export uses a principal/auth-record/selection-scoped controller and checks the exact current job object before status handling, after the body, and immediately before download. Account switches and same-ID result-version changes abort or discard the blob; delayed 401/body tests trigger no URL or download and cannot overwrite replacement auth state. |
| L1 — API-key secret race | Dialog/list/create epochs, an abort controller, and a 30-second absolute deadline fence the one-time secret. Close, cancel, copy, dismiss, hidden/pagehide, logout, and account switch prevent any late response from repopulating the DOM. |

## Exact local gates on 2026-09-01

| Gate | Result |
|---|---|
| Python suite | **PASS** — 167 passed, 1 skipped; the single warning is Starlette TestClient's httpx deprecation |
| Ruff format, general lint, and `S` security rules | **PASS** |
| Mypy and compileall | **PASS** — 13 typed source files checked |
| Browser syntax plus auth-epoch and two-tab adversarial harnesses | **PASS** |
| GitHub Actions workflow lint | **PASS** |
| Runtime dependency consistency | **PASS** — `pip check` reported no broken requirements |
| Runtime, development, and build vulnerability audits | **PASS** — no known vulnerabilities found |
| Reproducible CycloneDX SBOM and default dependency policy | **PASS** — regenerated inventory was byte-identical; PyMuPDF absent |
| Public-release policy | **EXPECTED BLOCK** — owner/counsel privacy, terms, entity, and distribution approval remains unresolved |
| Credential-pattern and PyMuPDF source/import/graph scans | **PASS** |
| Compose configuration | **PASS** |
| Exact-lock sdist/wheel build, install, import, and notice packaging | **PASS** |
| Local image build | **BLOCKED** — Docker daemon was not running; CI contains the production image build and smoke |

The current real-browser pass used local Chrome for Testing 147 because the
in-app browser had no available runtime in this task. Two tabs shared one
browser context; logout synchronously cleared private state and a held old-job
response could not repopulate it after account replacement. A maximum-contract
50-series/10,000-row result mounted 467 descendants and 40 table rows in 4.5 ms. The
1280×720 desktop and 390×844 mobile views completed without page-level overflow;
mobile document and viewport widths were both 390 px. This is implementation QA,
not a formal cross-browser, accessibility, or performance certification.

The default dependency gate passing means the known repository-controlled
PyMuPDF issue is technically remediated. It does not substitute for counsel's
review of the complete distribution or the owner's launch approval.

## Required external and owner gates

Before any public or paid release, record evidence for all of the following:

1. A real Modal resolver/canary against the exact deployed `unrender/infer_one`
   identity, immutable model revision/digest, approved credentials, and spend.
2. A coordinated restore drill on the selected encrypted production volume,
   including hashes, ownership, measured RPO/RTO, and failure handling.
3. A production container smoke plus independent penetration, accessibility,
   screen-reader, and edge/proxy configuration validation.
4. Owner and qualified-counsel approval of entity/contact details, privacy,
   terms, retention/deletion promises, processors/regions, refund/support terms,
   weight and data provenance, notices, and the intended distribution model.
5. Deployment decisions for domain, TLS, secret management, billing test Price,
   alert destinations, capacity thresholds, and on-call ownership.

Until those gates are closed, the honest label remains **controlled demo /
design-partner candidate**. A final independent read-only review must validate
the committed SHA before merge, and no release evidence should be inferred from
an earlier working tree.
