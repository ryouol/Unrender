# Launch readiness

Status labels: **PASS** is demonstrated in repository evidence, **BLOCKED** needs owner/external action, and **DEFERRED** is intentionally outside the controlled beta.

| Gate | Status | Evidence or blocker |
|---|---|---|
| Core saved-sample workflow | PASS | `tests/test_product.py` runs upload → durable job → review → correction → approval → CSV/JSON/XLSX and audit |
| Failure, cancellation, refund idempotency | PASS | Regression tests cover queued/running cancellation, provider failure, atomic completion races, and no double refund |
| Restart recovery | PASS | Interrupted running jobs return to queued without a second charge |
| Tenant and browser request isolation | PASS | Cross-tenant lookup, CSRF, origin, session, and API-key paths are tested |
| API credential lifecycle | PASS | Keys are shown once, stored as hashes, listed without hashes, and revocable; revoked-key rejection is tested |
| Export safety | PASS | CSV/XLSX neutralize non-numeric formula prefixes; JSON preserves exact reviewed values; workbook regression is tested |
| Upload safety limits | PASS | Magic decoding, image dimensions, PDF page/password handling, crop validation, and storage-root deletion guard |
| Truthful sample | PASS | Exact source hash plus deterministic synthetic ground truth; `verified-fixture/synthetic-v1-0002906`; no provider call |
| Default no-spend behavior | PASS | Replay is default; only fixture succeeds; Stripe live keys are rejected |
| Model benchmark claims | PASS WITH CAVEATS | Saved research receipts are linked; product copy does not convert them into an accuracy guarantee |
| Dependency lock and package install | PASS | Fresh Python 3.11 environments installed the hash-locked runtime, imported the app plus Modal provider client, and built/installed wheel `unrender-0.2.0` |
| Container build | BLOCKED | Non-root Dockerfile, health check, and CI build are present; local verification was unavailable because the Docker daemon was stopped |
| Automated regression suite | PASS | 86 tests passed, 1 optional Modal artifact test skipped locally; CI repeats suite |
| Visual QA | PASS | In-app browser exercised sample, correction, approval, dialog, desktop 1440×900 and mobile 390×844; evidence in `docs/screenshots/` |
| Accessibility baseline | PASS WITH LIMITS | Semantic snapshot, labels, unique IDs, responsive overflow, focus styling, and AA color pairs checked; external keyboard/screen-reader audit remains an owner gate |
| Repository security review | PASS WITH LIMITS | `docs/SECURITY_REVIEW.md`; no open critical/high finding and runtime lock has no known advisory; external penetration/container testing remains blocked |
| Independent code review | IN PROGRESS | Required after implementation and before PR approval; findings will be recorded on this branch |
| Real inference canary | BLOCKED | Owner must provide/deploy Modal credentials, verify `infer-one`, pin immutable model revision, and approve provider spend |
| Fine-tuned weight distribution rights | BLOCKED | Owner/counsel must review weights, training-data provenance, and publication terms |
| Customer privacy/terms | BLOCKED | Drafts exist; owner identity, contact, processor list, jurisdiction, retention, and deletion SLA require counsel approval |
| Production domain/TLS | BLOCKED | Owner must choose domain and deployment platform |
| Billing | BLOCKED | Test-mode code exists; owner must create/approve test Price and validate purchase/refund support before any live design |
| Observability and alert delivery | BLOCKED | Platform selection and structured queue/failure/cost metrics are required |
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
