# Refined platform review receipt

Reviewed `codex/refined-platform` against baseline `58af157`, including relevant untracked files. All findings below are resolved in the current tree. Locations identify the fixes, using repository-relative paths and current line numbers.

1. **Shared chart cleanup — resolved (Simplify).** `unrender/product/static/app.js:1662` centralizes selected-chart cleanup; `unrender/product/static/app.js:605` reuses it during account reset.
2. **Duplicate authentication check — resolved (Simplify).** `unrender/product/static/app.js:112` removes redundant checking at the same boundary while preserving checks before and after asynchronous response-body reads.
3. **CSRF test helper reuse — resolved (Simplify).** `tests/test_google_signin.py:9` uses the existing `csrf_headers` helper.
4. **Shared browser source loading — resolved (Simplify).** `tests/browser_product_source.mjs:4` loads the production scripts in their page order for browser regression suites.
5. **Settings reset ownership — resolved (Simplify).** `unrender/product/static/settings.js:19` owns Settings cleanup; account reset delegates to it at `unrender/product/static/app.js:603`.
6. **Unused Google styling — resolved (Simplify).** `unrender/product/static/app.css:194` retains the mounted Google button styles after unused selectors were removed.
7. **Repeated source-card creation — resolved (Simplify).** `unrender/product/static/library.js:139` reuses unchanged mounted cards, preserving loaded previews during list refreshes.
8. **Full result serialization for metadata edits — resolved (Simplify).** `unrender/product/library.py:127` excludes extraction results from rename/move responses.
9. **Whole-table scans during bulk deletion — resolved (Simplify).** `unrender/product/database.py:518` migrates to schema 14 with indexes for owner, upload and chart lookups used by account/project cleanup.
10. **P2: Concurrent previews exceeded available capacity — resolved (Code Review 2).** `unrender/product/static/previews.js:86` limits thumbnail concurrency to one, limits mounted previews, retries temporary capacity errors once, and fences stale account responses. `unrender/product/static/app.js:1386` waits for an active thumbnail before displaying a full source.
11. **P2: Library chart statuses stayed stale — resolved (Code Review 2/testing).** `unrender/product/static/library.js:16` refreshes lists and account state; `unrender/product/static/library.js:184` refreshes on library entry. Visible active work receives bounded polling, with navigation/logout fencing and foreground recovery.
12. **Project deletion submitted an empty default — resolved (browser QA).** `unrender/product/static/library.js:322` explicitly initializes the selection to `keep_charts`; submitting without changing it preserves the charts.
13. **Blob previews blocked by CSP — resolved (browser QA).** `unrender/product/web.py:65` permits image blob URLs while retaining the other content restrictions.
14. **Hung account refresh prevented future library updates — resolved (integration review).** `unrender/product/static/library.js:21` gives the account request a 30-second deadline, allowing the refresh loop to recover.
15. **Unsaved edits retained an approved heading/export step — resolved (mobile QA).** `unrender/product/static/app.js:1538` switches headings, notices and workflow state back to review. Saving and approving restores the approved presentation; unsaved exports remain blocked.

The context review found no applicable model-visible prompt or agent-context behavior changes. Testing guidance was applied to this Python/FastAPI application through its existing service, HTTP and production-JavaScript harnesses; Codex Rust-specific suite paths were not imposed.

The change-size review flagged approximately 5,500 changed lines, exceeding the 800-line guideline; subsequent fixes increased the diff. Staged commits make review manageable. The smallest coherent first commit, `18158e2`, contains the native authentication foundation: 183 insertions and 4 deletions, or 187 changed lines. Intermediate commits are not independently deployable. The final tree is one release; schema recovery requirements are documented at `docs/OPERATIONS.md:161`.

Behavioral coverage includes 73 workflow scenarios, 17 Google browser scenarios and 7 preview browser scenarios. Focused server and migration checks accompany the changes. Final local verification is recorded below; deployment is recorded separately.

## Final local verification

The final suite passed **316 tests, 1 skipped**. All four browser wrappers passed (73 workflow scenarios, 17 Google scenarios, and dedicated preview coverage). Ruff and mypy passed. Docker image `sha256:8851612be1fce17670e4f69e9cd57233d48f531725d7c55e8e07ed6f4c8d24c0` passed 24 HTTP checks, restart/integrity checks, and 69 installed source/static hash comparisons. Its scan reports zero Python findings and the unchanged Debian baseline (3 critical, 51 high; no fixed package version in the scan). This is not a clean vulnerability scan. Browser design QA passed; see [design-qa.md](../design-qa.md). Production deployment and live Google consent are recorded separately when verified.
