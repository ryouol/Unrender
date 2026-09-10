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
8. **Open P2 — review size.** The combined pre-existing hardening and new feature
   diff exceeds the skill's 800-line guidance (review snapshot: 1,485 text lines,
   excluding binaries). Split into coherent review stages: first schema v9 and
   its migration-preservation test, then account service/security and tests,
   account UI/operator/deployment integration, and independent public-site polish.
   The additive schema is the smallest prerequisite stage. No PR yet exists.

Reviewed locations (paths relative to `unrender/product/`): account lifecycle
`service.py`, credential routes `web.py`, schema `database.py`, frontend
`static/app.js` and `static/site.js`; repository `Dockerfile`, `render.yaml`, and
`tests/test_accounts.py`. Line numbers move with fixes; final review must use the
final commit. No GitHub review comments or labels have been posted.

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
