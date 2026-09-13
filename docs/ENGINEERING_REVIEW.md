# Engineering review guide

This guide is the entry point for an independent review of Unrender's controlled beta. It separates product behavior, implementation guarantees, and model evidence so reviewers can reproduce checks without cloud credentials.

[Live product](https://unrender.onrender.com/) · [Demo video](https://screen.studio/share/4lFdVojh) · [README and screenshots](../README.md) · [CI history](https://github.com/ryouol/Unrender/actions/workflows/ci.yml)

## Review baseline

The September 12, 2026 handoff describes runtime commit [`a14b961`](https://github.com/ryouol/Unrender/commit/a14b961db721004a4ad77d4e2ab5cdac343d1ef9), schema 14. Documentation-only commits may follow without a runtime redeploy. The latest deployment record is in [RENDER_MODAL_LAUNCH.md](RENDER_MODAL_LAUNCH.md).

The public beta supports Google and password signup with three welcome credits, personal projects, chart review, approval, exports, and deletion. Email delivery and customer billing are disabled. Local replay intentionally accepts only its bundled fixture. The private production model release is not downloadable from this repository.

The demo and screenshots explain the user experience. They are not a model evaluation, a load test, or evidence of an independent security review. Screenshot chart values are illustrative fixtures; see [provenance](screenshots/README.md).

## Suggested reading order

| Review question | Read | Inspect in code |
|---|---|---|
| What is the product meant to solve? | [README](../README.md), [product decision](PRODUCT_DECISION.md) | [Public pages](../unrender/product/public_site.py), [frontend](../unrender/product/static/) |
| How does a request reach inference? | [Architecture](ARCHITECTURE.md), [API](API.md) | [Web](../unrender/product/web.py), [service](../unrender/product/service.py), [worker](../unrender/product/worker.py), [extractors](../unrender/product/extractors.py) |
| What prevents cross-account access? | [Security model](SECURITY_MODEL.md), [Google sign-in](GOOGLE_SIGNIN.md) | [Security](../unrender/product/security.py), [Google account transactions](../unrender/product/google_accounts.py), [database](../unrender/product/database.py) |
| What happens when work fails or is deleted? | [Operations](OPERATIONS.md), [chart library](CHART_LIBRARY.md) | [Worker](../unrender/product/worker.py), [storage](../unrender/product/storage.py), [backup/restore](../unrender/product/backup.py) |
| Is the extracted data useful? | [Pilot evaluation](LAUNCH_EVALUATION.md), [research results](../RESULTS.md), [claim boundaries](../RESULT_TO_CLAIM.md) | [Metrics](../unrender/eval/metrics.py), [frozen inputs](../release/launch-eval-v1/), [saved predictions](../release/launch-eval-results/) |
| What remains before a broader release? | [Readiness](LAUNCH_READINESS.md), [container scan](CONTAINER_SCAN.md), [legal review](LEGAL_REVIEW.md) | [Production validation](../unrender/product/config.py), [Render blueprint](../render.yaml), [CI](../.github/workflows/ci.yml) |

## Reproduce the product locally

Use the exact installation and `sh scripts/run_local.sh` instructions in the [README](../README.md#run-locally). The launcher sets local destinations explicitly, so production credentials in an operator shell do not turn a replay review into a cloud inference call.

1. Open `/login` and choose **Run saved model replay**. Confirm the UI identifies the sample workspace.
2. Compare source and table, edit one value, and save a correction. Open version history.
3. Save and approve. Download CSV, JSON, and XLSX; inspect the workbook's Audit sheet.
4. Sign out. The ephemeral sample is deleted; open a new sample to start fresh.
5. For persistent projects and deletion, create a **local** password account and use its saved example. Check chart rename, project assignment, and project deletion with charts kept versus deleted. Account deletion requires recent authentication.

Do not use the shared production service for destructive, quota-exhaustion, or load tests. The test suite builds isolated temporary stores for these cases. Live arbitrary-chart extraction consumes credits and invokes Modal; local replay does not validate that provider path.

## Test map

| Area | Regression entry points |
|---|---|
| End-to-end review/export, tenant isolation, quotas, credit/refund idempotency, lease recovery | [`test_product.py`](../tests/test_product.py) |
| Password signup, activation, sessions, operator grants | [`test_accounts.py`](../tests/test_accounts.py) |
| Google token validation, state/browser binding, explicit linking, one-time credits | [`test_google_oauth.py`](../tests/test_google_oauth.py), [`test_google_signin.py`](../tests/test_google_signin.py), [`test_google_accounts.py`](../tests/test_google_accounts.py) |
| Projects, chart/account deletion, migration recovery | [`test_library.py`](../tests/test_library.py), [`test_account_deletion.py`](../tests/test_account_deletion.py), [`test_deletion_migration.py`](../tests/test_deletion_migration.py) |
| Frontend workflow, login races, stale responses, preview ordering | [`browser_workflow.mjs`](../tests/browser_workflow.mjs), [`browser_google.mjs`](../tests/browser_google.mjs), [`browser_auth_epoch.mjs`](../tests/browser_auth_epoch.mjs), [`browser_two_tab.mjs`](../tests/browser_two_tab.mjs), [`browser_previews.mjs`](../tests/browser_previews.mjs) |
| Packaging/release constraints, model contract, evidence integrity | [`test_release_policy.py`](../tests/test_release_policy.py), [`test_train_config.py`](../tests/test_train_config.py), [`test_integrity.py`](../tests/test_integrity.py) |

Run `pytest -q` for the full Python suite. It includes research/evaluation checks and wrappers for several Node browser harnesses. Those harnesses exercise frontend behavior with simulated browser surfaces; they are not a substitute for real-browser interaction or an external accessibility audit. Read [visual QA](../design-qa.md) for the separate captured browser checks.

The runtime baseline passed **320 tests / 1 skipped** locally; [PR #8](https://github.com/ryouol/Unrender/pull/8) records branch/PR CI, production rollout, and a synthetic hosted signup check. Main CI also passed. Known local warnings include the Starlette/httpx deprecation and Modal's notice when its function is invoked locally by tests. These local test invocations are not deployed GPU calls.

For offline model evaluation, use the rescore command in [LAUNCH_EVALUATION.md](LAUNCH_EVALUATION.md). Full research reproduction needs the original model artifacts/datasets and possibly paid provider access; a clean clone does not contain every generated image, training checkpoint, or frontier-provider response.

## Invariants worth challenging

- Every private lookup is scoped to the authenticated account. Sign-out revokes all account sessions; delayed browser responses must not restore another account's data.
- Account creation and its welcome ledger grant commit together. Returning sign-in, Google linking, and reauthentication must not mint credits.
- A job's credit reservation, dispatch decision, result version, and terminal state remain consistent under timeout, cancellation, duplicate requests, and restart.
- Fenced worker leases prevent a stale worker from committing results. An ambiguous dispatched attempt is not silently retried or refunded.
- Upload bytes are validated and durably published before database references become visible. Capacity is reserved before accepted work can exhaust private storage.
- Deletion revokes application access immediately and commits file cleanup to a durable outbox. Shared source references and backups have explicit lifecycle rules.
- Approval applies to the exact reviewed version. Exports preserve reviewed values and neutralize spreadsheet formula injection where applicable.

These are claims to inspect against source and tests, not a request to assume the implementation is correct.

## Tradeoffs and open questions

| Decision or limit | Review implication |
|---|---|
| One Render replica, SQLite, embedded worker, private disk | Simple operational footprint; no horizontal scaling or multi-host SQLite. Examine recovery, storage pressure, and contention before adding traffic. |
| GPU inference on Modal | Cloud identity and pinned artifacts are external dependencies. Queueing and model execution can dominate latency. |
| Three public welcome credits | Per-account allowance only. Multiple accounts can multiply free usage; rate limits and concurrency bounds do not establish a dollar cap. |
| Password signup without email verification | Mailbox ownership is not established. Operator recovery must not treat the originally entered address as sufficient proof. |
| No shared-team permissions | “Projects” organize one user's charts; they do not create organizational tenancy or collaboration roles. |
| Limited quality evidence | Three crisp synthetic charts are a smoke evaluation. Representative customer charts, correction-time measurements, and actual inference cost remain needed. |
| Recorded container advisories | The last documented scan has 3 critical and 51 high Debian findings without listed fixed versions. Assess applicability and remediation; do not call the image vulnerability-free. |
| Dated historical reviews | Preserve experimental receipts, but do not infer today's deployment state from June research notes or earlier rollout inventories. |

For feedback, report severity, exact file/line or workflow, reproduction, expected versus actual behavior, and the relevant test gap. Keep proposed fixes small enough to review independently. Use a `codex/` branch for agent-assisted work, follow [CI](../.github/workflows/ci.yml), and keep private customer files, secrets, generated checkpoints, and local `outputs/` out of commits. Use synthetic reproducers in [GitHub issues](https://github.com/ryouol/Unrender/issues); report sensitive details privately to the [support contact](https://unrender.onrender.com/contact).
