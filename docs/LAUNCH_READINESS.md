# Launch readiness

Status labels: **PASS** is demonstrated in repository evidence, **BLOCKED** needs owner/external action, and **DEFERRED** is intentionally outside the controlled beta.

| Gate | Status | Evidence or blocker |
|---|---|---|
| Core saved-sample workflow | PASS | `tests/test_product.py` runs upload → durable job → review → correction → approval → CSV/JSON/XLSX and audit |
| Failure, cancellation, refund/spend idempotency | PASS | Pre-dispatch cancellation/failure refunds exactly once; post-dispatch failure/cancellation consumes the credit; per-user/global failure circuits block later dispatch before spend. Adversarial tests cover all three states and preserved prior results. |
| Worker lease/restart recovery | PASS | Owner/token/generation leases heartbeat durably; every progress/result/terminal/provider/audit/refund commit is fenced. Fresh leases survive peer startup, exactly one reaper recovers an expiry, stale owners mutate nothing, post-dispatch ambiguity is never redriven/refunded, and long provider calls keep a valid lease while draining. |
| Tenant and browser request isolation | PASS | Cross-tenant lookup, CSRF, origin, session, and API-key paths are tested; logout/account switches abort outstanding requests, increment an auth epoch, wipe private tables/forms/images/key dialogs, and discard delayed old-account responses. Each public demo session is isolated and removed on sign-out. |
| API credential lifecycle | PASS | Keys are shown once, stored as hashes, cursor-paginated without hashes, bounded active/retained, individually revocable, and revocable all at once; complete-inventory tests cover the prior 101st-key class of bug. |
| API replay safety | PASS | Mutating v1 requests require a bounded `Idempotency-Key`; exact retries replay inside the configured window, changed/expired reuse returns `409`, compact tombstones prevent silent late double-charge during their documented retention horizon, and record count is tenant-bounded |
| Result-history bounds | PASS | Per-job version and per-tenant byte ceilings are transactional; lists are cursor-paginated metadata and selected bodies are fetched one at a time; reprocessing preflights capacity before reserving spend |
| Retained database-state bounds | PASS | Sessions, keys, jobs/uploads, audit detail/rollups, credit ledger, idempotency, billing events, provider attempts, and tenant/global row budgets are bounded; demo cleanup removes user/audit state and stress/restart tests verify caps. |
| Export safety | PASS | CSV/XLSX neutralize non-numeric formula prefixes; JSON preserves exact reviewed values; workbook regression is tested |
| Upload/body safety limits | PASS | Streaming body counting avoids a second accepted-body copy; route-specific upload/render and password-KDF concurrency ceilings, magic decoding, image dimensions, PDF page/password handling, finite crop/chart numbers, and storage-root deletion guard are tested. |
| Truthful sample | PASS | Exact source hash plus deterministic synthetic ground truth; `verified-fixture/synthetic-v1-0002906`; no provider call |
| Default no-spend behavior | PASS | Replay is default; only fixture succeeds; Stripe live keys are rejected |
| Model benchmark claims | PASS WITH CAVEATS | Saved research receipts are linked; product copy does not convert them into an accuracy guarantee |
| Dependency lock and package install | PASS | Fresh Python 3.11 environments installed all three hash-locked runtime/build/development sets, passed `pip check`, imported the app plus each shipped CLI, and built sdist/wheel `unrender-0.2.0` without build isolation |
| Container build | BLOCKED | Non-root Dockerfile, loopback health check using the configured public Host, and a real production-mode CI smoke are present; local verification was unavailable because the Docker daemon was stopped |
| Automated regression suite | PASS | The exact local pre-commit run on 2026-09-01 produced 139 passed/1 skipped, clean Ruff format/general/security rules, mypy, compileall, browser syntax/auth-epoch harness, actionlint, pip check, all three vulnerability audits, reproducible SBOM, dependency policy, secret scan, compose config, and clean exact-lock package build/install/import gates. CI repeats the hermetic suite; details are recorded in `docs/REMEDIATION_EVIDENCE.md`. |
| Visual QA | PASS | In-app browser exercised isolated demo cleanup, customer upload, keyboard crop, failure/refund, correction, version restore, approval, export audit, API-key create/revoke, desktop 1280×720, and mobile 390×844; evidence in `docs/VISUAL_QA.md` and `docs/screenshots/` |
| Accessibility baseline | PASS WITH LIMITS | Semantic snapshot, labels, unique IDs, responsive overflow, focus styling, and AA color pairs checked; external keyboard/screen-reader audit remains an owner gate |
| Repository security review | PASS WITH LIMITS | `docs/SECURITY_REVIEW.md`; two earlier independent review rounds plus the exact `13375b5` review drove the recorded remediation, all runtime/build/development locks have no known advisory, and external penetration/container testing remains blocked |
| Independent code review | IN PROGRESS | The exact review of `13375b5` is being remediated; a read-only review of the final committed SHA is required before PR approval. |
| Migration/restart safety | PASS | Schema v6 upgrades are cross-process serialized and transaction-atomic. Tests cover complete v1-v4 database shapes, inject a crash after every v4→v5 mutating statement, resume the legacy partial-rename shape, repeat initialization, run concurrent starters, and verify rows/source bytes/expiry/FKs. |
| Coordinated backup implementation | PASS | The admin backup takes an exclusive mutation lock and emits a hash inventory; restore rejects tampering/unsafe paths, checks SQLite/FKs, rewrites the root, and publishes only into an absent target. An active-mutation drill is tested. |
| Backup restore drill | BLOCKED | Run the coordinated command on the selected encrypted production volume and record measured RPO/RTO and ownership checks. |
| Real inference canary | BLOCKED | Owner must provide/deploy Modal credentials, resolve the exact non-spending `unrender/infer_one` contract, pin immutable model revision/digest, run an approved real canary, record platform deployment identity, and approve provider spend. |
| Fine-tuned weight distribution rights | BLOCKED | Owner/counsel must review weights, training-data provenance, and publication terms |
| PDF renderer dependency gate | PASS (engineering) | PyMuPDF is absent from code and runtime/dev locks. Locked pypdfium2/PDFium replaces it with render, encryption-rejection, hash-lock, SBOM, audit, and policy-drift coverage. This dependency check has no unresolved technical blocker. Retaining shipped notices and approving the complete distribution remain business/legal owner responsibilities, not engineering claims of sellability. |
| Customer privacy/terms | BLOCKED | Drafts exist; owner identity, contact, processor list, jurisdiction, retention, and deletion SLA require counsel approval |
| Production domain/TLS | BLOCKED | Owner must choose domain and deployment platform |
| Billing | BLOCKED | Test-mode code exists; owner must create/approve test Price and validate purchase/refund support before any live design |
| Observability and alert delivery | BLOCKED | Privacy-safe provider lifecycle logs are implemented and tested; the deployment platform, queue/ledger/capacity metrics, and alert destinations remain owner gates |
| Public paid launch | BLOCKED | Depends on every blocked item above; no live charges are authorized |
| Horizontal scaling | DEFERRED | Single-node beta is explicit; Postgres/object storage/queue migration is documented |
| Enterprise features | DEFERRED | SSO, organizations, RBAC, SLAs, and compliance are not part of v0.2 |

## Owner handoff checklist

1. Confirm product name/trademark and legal entity/contact details.
2. Complete model/data/font/dependency counsel review.
3. Select deployment platform, region, encrypted storage, domain, TLS, and secret manager.
4. Pin and canary the Modal model without exposing customer data.
5. Configure metrics, alerts, backups, and a restore drill.
6. Run accessibility, security, and independent code-review gates.
7. Conduct design-partner validation before enabling any paid mode.

Until those actions are complete, the honest release label is **controlled demo / design-partner candidate**, not generally available or enterprise-ready.
