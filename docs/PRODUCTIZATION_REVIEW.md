# Productization review — September 10, 2026

Read-only subagent reviews applied all code-review skills (context, testing,
breaking changes, change size), plus three simplify passes (reuse, quality,
efficiency). This records every reported issue, including those fixed during the
review. A final review of the release diff remains required after remaining work.

1. **Fixed — duplicate export button busy state.** `static/app.js`'s actionButton
   now owns pending state and guards reenabling against stale auth/view epochs;
   downloadExport no longer duplicates the lifecycle. The quality and efficiency
   reviewers independently reported the same issue.
2. **Fixed — unused consent-state assignment.** Removed the unused `choice=value`
   write in `static/site.js`. Optional analytics still collects no data.
3. **Fixed P1 — reset versus old-password login.** `service.py::authenticate` now
   passes the validated password hash into `create_session`, which compares it
   within its write transaction. A deterministic interleaving regression rejects
   the old login after reset. Two reviewers reproduced and rechecked this fix.
4. **Fixed P1 — reset versus API-key issuance.** `web.py::create_key` passes the
   authenticated generation; `service.py::create_api_key` checks it transactionally.
   Regression coverage resets the password between admission and key creation.
5. **Fixed P2 — failed/reordered account mail.** `service.py::request_account_email`
   stores bounded independent challenges instead of replacing the only link.
   Failed sends delete their own challenge; completion invalidates siblings.
   Regressions cover failure, sibling consumption, capacity and expiration.
6. **Fixed locally P2; deployment verification pending — operator SSH.**
   `Dockerfile` now creates a non-root home, shell and private .ssh directory.
   Verify Render operator SSH before relying on grant-credits in production.
7. **Open P1 — Render client-IP attribution.** `render.yaml` uses Docker without
   a verified trusted proxy setup. The default Uvicorn proxy trust can group users
   behind the Render edge into a shared auth bucket. Verify ingress/header
   behavior and configure/test trust before release. Do not blindly trust spoofable
   forwarded values. See RENDER_MODAL_LAUNCH.md.
8. **Open P2 — review size.** PR #2 at `02c3a6b` has 2,134 changed text
   lines across 51 files (1,478 excluding README/docs). The smallest coherent
   first stage is schema v9 plus isolated migration-preservation coverage
   (roughly 45–50 lines). Follow with separate verified-signup/email and password
   recovery/credential-invalidation stages, each below 500 complex lines. Keep
   the independent Modal deadline as its own stage, then operator/deployment
   integration. Public-shell helpers must precede or accompany account UI:
   `/account` calls `document()` and requires the `account.html` allowlist entry.
   Public/workspace polish and UX evidence can follow. These are proposed review
   stages; PR #2 remains a combined draft and has not been split or merged.

Reviewed locations (paths relative to `unrender/product/`): account lifecycle
`service.py`, credential routes `web.py`, schema `database.py`, frontend
`static/app.js` and `static/site.js`; repository `Dockerfile`, `render.yaml`, and
`tests/test_accounts.py`. Line numbers move with fixes; final review must use the
final commit. No GitHub review comments have been posted.

Supplemental provider-deadline review found no concrete correctness issue in
`unrender/product/extractors.py` and its worker/canary regressions. The reviewer
also exercised the installed Modal SDK async bridge without network access;
local cancellation and repeated worker-thread calls drained correctly. This
closes local deadline behavior only; real provider cancellation and Render
termination timing remain required deployment checks.

9. **Open P1 — base-image vulnerability assessment.** `Dockerfile:13` pins a
   Debian base with 18 distinct high/critical advisories in the September 10
   Trivy scan. Package presence does not establish exploitability, but vendor and
   reachability assessment remains outstanding. See CONTAINER_SCAN.md for all
   advisories. Removed unused inherited installer packages at `Dockerfile:43`,
   resolving the scan's Python findings. Supplemental read-only review found no
   runtime dependency on those installers and no issue with explicit AMD64 CI.

Base-image follow-up: all 18 high/critical advisories now have an initial
source/vendor assessment in CONTAINER_SCAN.md. Seven have artifact-specific
component/architecture exclusions; eleven have no observed application route but
retain operational assumptions requiring deployed verification. This narrows
finding 9; it does not close it or suppress the scanner results.


## Published PR review follow-up

10. **Fixed P2 — concurrent legacy-password upgrade** (`service.py`, authenticate).
    A losing conditional rehash now reads and verifies the winning hash while
    rejecting a changed session generation; session creation still fences on
    the exact validated hash. Two simultaneous valid logins now both succeed.
    The existing reset-versus-login regression still rejects the old password.
11. **Fixed P2 — logout blocked by login limits** (`web.py`, auth grouping).
    Logout remains under general request limits but no longer shares the
    credential-attempt rate/concurrency group. Regression exhausts login attempts,
    successfully logs out with CSRF, and verifies the session is gone.

The context review found no applicable model-context changes. The testing review
found no additional defect but retained live SMTP, browser account-flow and
Render/Modal verification limits. All reviewer findings are recorded here;
code review is not deployment approval.

## September 10 final pass and deployment inventory

12. **Fixed P2 — initial job-list recovery** (`unrender/product/static/app.js:728`).
    Successful list initialization is tracked separately from the authenticated
    principal. Focus retries failed initialization without replacing an active
    upload. The Node regression exercises both failure recovery and picker focus.
13. **Fixed P2 — file selection during upload** (`unrender/product/static/app.js:1055`).
    The picker is disabled during upload and restored/reset on completion or
    private-state clearing, preventing silently discarded selections.
14. **Fixed P3 — verification KDF writer lock** (`unrender/product/service.py:992`).
    Password verification occurs before the write transaction; the transaction
    rechecks the live challenge and exact hash/generation. A regression performs
    a concurrent write during verification and verifies stale credentials fail.
15. **Fixed P2 — SMTP occupies authentication admission** (`unrender/product/web.py:215`).
    Email requests have a separate one-request slot. Registration holds the shared
    KDF slot only through account creation, then sends mail after releasing it.
    Slow-mail regressions cover registration, resend, and recovery while login
    succeeds and excess email requests receive 503.
16. **Fixed P3 — schema rollback instructions** (`docs/OPERATIONS.md:88`).
    The release uses schema 9; rollback to schema 8 requires the pre-v9 recovery set.
17. **Open change-size concern**: reviewed baseline 4bf1352 changes 2,354 text
    lines across 52 files (1,638 excluding README/docs). Smallest first stage is
    schema v9 and its v8 preservation test (~45–50 lines), followed by account
    verification, recovery/revocation, provider deadline, browser integration,
    deployment/operator integration, and visual/documentation stages. Existing
    PR remains draft. Context review found no new model-context injection.

Created Render project `UNRENDER` with a `Production` environment:
https://dashboard.render.com/project/prj-dahh1gbl550s73840e5g
No service has been deployed there. Wayline remains separate. No shared billing
settings were changed. Modal's September workspace billing summary showed $0
billed and $3.04849077 metered before adjustments; this is shared-workspace
history, not a project cap or forecast.

The user's $20 maximum has not been enforceably configured. Render bills
workspace bandwidth overages with a card on file. Modal's workspace spend cap
would affect other projects; environment compute budgets require Team/Enterprise
and omit storage. A combined project hard cap cannot be claimed from these
controls. The requested monthly-versus-total interpretation is still pending.
Real pinned model release, SMTP delivery, deployed proxy attribution, backup
restore, and live end-to-end inference remain release gates.

18. **Fixed P2 — cancellation released admission while work continued**
    (`unrender/product/web.py:190`). A shielded task now owns the acquired slot
    until actual completion; cancelling its caller does not free capacity early.
    This applies to both the middleware and registration KDF. A real-thread
    cancellation regression verifies admission stays occupied until completion.

Follow-up validation: 188 passed / 1 skipped before the cancellation change;
all 15 account tests including cancellation passed afterward. Formatting and
lint match CI. The previous commit's CI failure was formatting-only and is fixed
in this follow-up. These are local evidence, not live SMTP/provider verification.

## Private Modal release review

19. **Fixed P2 — publisher retry persistence** (`scripts/publish_modal_release.py:67`).
    The volume commit now runs for both a new release and an already verified
    target, so retrying after an ambiguous commit attempts persistence again.
20. **Fixed P2 — default app identity mismatch** (`unrender/product/config.py:91`).
    Defaults, environment example, README, and Render configuration now select
    `unrender-production`. Deploy explicitly with
    `modal deploy modal_train.py::production_app`; research remains separate.
    Private Hub users must explicitly name their existing secret with
    `UNRENDER_HF_SECRET` when deploying.

The reviewer found no concrete bypass in the descriptor-checked copy, inspected
SHA-256 comparison, read-only verification, and rename sequence. Focused tests
reject mismatched revision/digest and tampered release contents.
CPU-only publication completed successfully in Modal run
`ap-RkfwH2s4N8OiiiNA2eezXZ`, returning `private_release_verified` for digest
`3954f3395a9db64fcbd3b9dc94508ab0cf9af2f5f2156643504881ee712e8c7e`.
This establishes a committed private artifact, not inference quality or latency.

21. **Fixed P2 — scorer imported during inference startup**
    (`unrender/eval/__init__.py:9`). Live canary failed on missing `rapidfuzz`.
    Scoring exports now load lazily; provider import works without scorer extras.
    A subprocess regression hides rapidfuzz and verifies independent inference import.
22. **Fixed P2 — missing Qwen processor dependency** (`modal_train.py:68`).
    Live canary required Torchvision. The inference image now pins torchvision
    0.24.1 alongside the officially paired torch 2.9.1.

The deployed model subsequently returned valid schema data with no parse errors:
first call 91.29 seconds, immediate repeat 51.84 seconds, identical provider release
`9435fb6f0b24068f7006401fd44d49e3a925330267dfb2302156eb677104b08d`.
The Render template now pins this observed release and the verified private model.
Numerical readings still need review (for example the model returned 9.0 for
Q1 2017 where the saved sample reference is 9.8). This single low-resolution chart
is operational evidence, not a representative accuracy benchmark. Tokenizer regex
and truncation warnings appeared; no automatic tokenizer change was made that
would silently alter the trained release's preprocessing.

The full local production-configured HTTP flow also passed using the real remote
model: operator provisioning and sign-in, upload, inference (48.26 seconds),
correction of Q3 2016 from 9.0 to 9.2, approval, CSV/JSON/XLSX exports, workbook
audit-sheet presence, logout, application restart, re-login, and approved-job
persistence. Evidence is in `outputs/local-verification/live-product-flow/report.json`
and its exported files. TestClient's HTTPS URL is simulated; this does not prove
Render TLS, proxy attribution, disk ownership, or externally reachable production.

Latest completed CI at b164f77 passed both verification and container builds.
Modal billing reported $0.07880970 of UNRENDER app compute for the day at the
observation time, before credits and excluding storage and reporting delay.
