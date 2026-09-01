# Exact-review remediation evidence

This record covers the remediation of the independent review performed against
commit `13375b55dd3e89c067a1edb622e937f2c3a1b1a3`. It records repository evidence,
not a claim that the service is approved for public or commercial launch. The
final commit SHA belongs in the handoff or pull request after a read-only review
of that exact tree.

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

## Exact local gates on 2026-09-01

| Gate | Result |
|---|---|
| Python suite | **PASS** — 139 passed, 1 skipped; the single warning is Starlette TestClient's httpx deprecation |
| Ruff format, general lint, and `S` security rules | **PASS** |
| Mypy and compileall | **PASS** — 13 typed source files checked |
| Browser syntax and auth-epoch adversarial harness | **PASS** |
| GitHub Actions workflow lint | **PASS** |
| Runtime dependency consistency | **PASS** — `pip check` reported no broken requirements |
| Runtime, development, and build vulnerability audits | **PASS** — no known vulnerabilities found |
| Reproducible CycloneDX SBOM and default dependency policy | **PASS** — regenerated inventory was byte-identical; PyMuPDF absent |
| Public-release policy | **EXPECTED BLOCK** — owner/counsel privacy, terms, entity, and distribution approval remains unresolved |
| Credential-pattern and PyMuPDF source/import/graph scans | **PASS** |
| Compose configuration | **PASS** |
| Exact-lock sdist/wheel build, install, import, and notice packaging | **PASS** |
| Local image build | **BLOCKED** — Docker daemon was not running; CI contains the production image build and smoke |

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
