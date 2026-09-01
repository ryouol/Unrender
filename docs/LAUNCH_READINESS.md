# Launch readiness

Status labels: **PASS** is demonstrated in repository evidence, **BLOCKED** needs owner/external action, and **DEFERRED** is intentionally outside the controlled beta.

| Gate | Status | Evidence or blocker |
|---|---|---|
| Core saved-sample workflow | PASS | `tests/test_product.py` runs upload → durable job → review → correction → approval → CSV/JSON/XLSX and audit |
| Failure, cancellation, refund idempotency | PASS | Regression tests cover queued/running cancellation, provider failure, atomic completion races, prior approved-result preservation, and no double refund |
| Restart recovery | PASS | Interrupted running jobs return to queued without a second charge; one bounded recovery is followed by a durable terminal state and an idempotent refund |
| Tenant and browser request isolation | PASS | Cross-tenant lookup, CSRF, origin, session, and API-key paths are tested; each public demo session receives an isolated ephemeral tenant that is removed on sign-out |
| API credential lifecycle | PASS | Keys are shown once, stored as hashes, listed without hashes, and revocable; revoked-key rejection is tested |
| API replay safety | PASS | Mutating v1 requests require a bounded `Idempotency-Key`; exact retries replay inside the configured window, changed/expired reuse returns `409`, compact tombstones prevent silent late double-charge during their documented retention horizon, and record count is tenant-bounded |
| Result-history bounds | PASS | Per-job version and per-tenant byte ceilings are transactional; lists are cursor-paginated metadata and selected bodies are fetched one at a time; reprocessing preflights capacity before reserving spend |
| Export safety | PASS | CSV/XLSX neutralize non-numeric formula prefixes; JSON preserves exact reviewed values; workbook regression is tested |
| Upload safety limits | PASS | Magic decoding, image dimensions, PDF page/password handling, crop validation, and storage-root deletion guard |
| Truthful sample | PASS | Exact source hash plus deterministic synthetic ground truth; `verified-fixture/synthetic-v1-0002906`; no provider call |
| Default no-spend behavior | PASS | Replay is default; only fixture succeeds; Stripe live keys are rejected |
| Model benchmark claims | PASS WITH CAVEATS | Saved research receipts are linked; product copy does not convert them into an accuracy guarantee |
| Dependency lock and package install | PASS | Fresh Python 3.11 environments installed all three hash-locked runtime/build/development sets, passed `pip check`, imported the app plus each shipped CLI, and built sdist/wheel `unrender-0.2.0` without build isolation |
| Container build | BLOCKED | Non-root Dockerfile, loopback health check using the configured public Host, and a real production-mode CI smoke are present; local verification was unavailable because the Docker daemon was stopped |
| Automated regression suite | PASS | 110 tests passed, 1 optional Modal artifact test skipped locally; CI repeats the suite |
| Visual QA | PASS | In-app browser exercised isolated demo cleanup, customer upload, keyboard crop, failure/refund, correction, version restore, approval, export audit, API-key create/revoke, desktop 1280×720, and mobile 390×844; evidence in `docs/VISUAL_QA.md` and `docs/screenshots/` |
| Accessibility baseline | PASS WITH LIMITS | Semantic snapshot, labels, unique IDs, responsive overflow, focus styling, and AA color pairs checked; external keyboard/screen-reader audit remains an owner gate |
| Repository security review | PASS WITH LIMITS | `docs/SECURITY_REVIEW.md`; two independent review rounds found and drove remediation of four High plus Medium/Low findings, all runtime/build/development locks have no known advisory, and external penetration/container testing remains blocked |
| Independent code review | IN PROGRESS | The second exact review of `8733a00` is remediated in the working tree; a read-only review of the final committed SHA is required before PR approval |
| Real inference canary | BLOCKED | Owner must provide/deploy Modal credentials, verify `infer-one`, pin immutable model revision, and approve provider spend |
| Fine-tuned weight distribution rights | BLOCKED | Owner/counsel must review weights, training-data provenance, and publication terms |
| Customer privacy/terms | BLOCKED | Drafts exist; owner identity, contact, processor list, jurisdiction, retention, and deletion SLA require counsel approval |
| Production domain/TLS | BLOCKED | Owner must choose domain and deployment platform |
| Billing | BLOCKED | Test-mode code exists; owner must create/approve test Price and validate purchase/refund support before any live design |
| Observability and alert delivery | BLOCKED | Privacy-safe provider lifecycle logs are implemented and tested; the deployment platform, queue/ledger/capacity metrics, and alert destinations remain owner gates |
| Backup restore drill | BLOCKED | Run on the selected encrypted volume and record results |
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
