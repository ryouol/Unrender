# Audit remediation review — 2026-09-23

Baseline `584db2d`. All findings below were resolved before release. Paths and lines identify the reviewed locations; subsequent edits can shift lines. Duplicate findings from independent reviewers remain attributed.

## Simplify findings

1. **Reuse, quality, efficiency — P1:** `unrender/product/static/library.js:407` called undefined `reloadLibraryPage`. Changed to `reloadJobs`; search event regression added.
2. **Reuse, quality, efficiency — P1/P2:** `unrender/product/static/review-tools.js:19,32` normalized undo snapshots and discarded unfinished rows. Capture raw editor rows, series, fields and page; incomplete-row regression added.
3. **Quality, efficiency — P2:** `unrender/product/static/review-tools.js:114` cleared redo on focus. Focus now captures a pending snapshot; only an actual edit commits it. Focus/redo regression added.
4. **Reuse — P2:** `unrender/product/service.py:3616` consumed another reservation on duplicate dispatch admission. Reject already-dispatched claims before reservation; duplicate-call regression added.
5. **Reuse — cleanup:** `unrender/product/static/app.js:97` retained optional branches around an always-present AbortController. Removed the obsolete branches.
6. **Efficiency — P2:** `unrender/product/static/previews.js:71` let obsolete page thumbnails hold up the new queue. Abort an active request when its card leaves the wanted set.
7. **Quality — P2:** `unrender/product/static/review-tools.js:63` accepted numeric formats that number inputs discard. Canonicalize finite numbers before rendering; numeric-paste regression added.
8. **Quality — P2:** `unrender/product/static/library.js:119` removed a project filter without loading the corresponding page. Reload after reconciliation and invalidate older responses through the request counter.
9. **Quality — P2:** `unrender/product/library.py:52` regressed non-ASCII search. Use NFC normalization and Unicode case folding; accented-name regression added.

## Final Code Review findings

10. **Breaking changes — P2:** `unrender/product/static/app.js:576` required a recovered submission to appear in a filtered page. Open the authorized job directly; pagination no longer blocks durable submission recovery.
11. **Testing/breaking changes — P2:** `unrender/product/service.py:3257` counted expired keys as active and could prevent replacement. Exclude expired credentials and prune them under retained limits; replacement regression added.
12. **Breaking changes — P2:** `unrender/product/static/app.js:1455` could leave a source broken after thumbnail contention. Added bounded retries, preserved across same-chart polling and fenced by account/chart identity. Retry/auth regression added.
13. **Context — P2:** `unrender/product/static/review-tools.js:107` accepted an obsolete comparison after save/restore. Reset invalidates pending comparisons and captured job identity must still match; delayed-response regression added.
14. **Change size — P2:** `docs/PLATFORM_IMPROVEMENT_PLAN.md:17` promised small stages but the aggregate exceeded the review limit. Split into five stacked, independently reviewable branches: reliability, admission, library, review experience, and browser acceptance/documentation. Each stage is below 500 changed lines before later release-only evidence.
15. **Change size — P2:** `tests/test_product.py:1835` and `unrender/product/web.py:896` were missing from the first reliability commit. Added the dependent readiness test and maintenance lock before its stage branch was created.

The context/testing skills' Codex/Rust-specific instructions do not apply to this Python/JavaScript application. Their applicable state-boundary and behavioral-testing principles were reviewed. No GitHub review comments were posted.

## Validation

- Integrated Python suite: 680 passed, 3 skipped before the final expired-key regression; targeted follow-up: 8 passed.
- Browser workflow harness: 83 scenarios passed, including unfinished-row undo, focus/redo, numeric paste, stale comparisons, search and source retry.
- Product lint and type checks passed after fixes. Repository-wide exploratory lint also exposed existing violations outside the product CI scope; no unrelated cleanup was mixed into this release.
- Real local browser: correction/undo/redo, paste/reverse, approval, version comparison, dark theme and search/no-match controls exercised.
- Chromium and WebKit acceptance added to CI; CI results and deployment receipts are recorded separately after execution.
- Production coordinated schema-15 backup created at `/data/release-backups/pre-audit-remediation-20260923-schema15`; no queued/running jobs at the preflight check.

Remaining evidence gates are recorded in the implementation plan. This change does not establish a dollar budget, independent model accuracy, legal identity, enabled commercial billing/email, or external certification.
