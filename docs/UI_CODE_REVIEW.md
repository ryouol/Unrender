# UNRENDER UI review record

Reviewed the redesign against `5720cd86c45b2788149cbe213af1304b63b4ae0b`, including new files. Three simplify passes covered reuse, quality and efficiency. Four separate xhigh reviewers applied the change-size, breaking-change, testing and model-context skills. No GitHub comments were posted.

The numbered inventory below preserves all issues raised, including issues fixed before the final pass. Duplicate reports by breaking/testing reviewers are identified rather than silently omitted. Line references name the relevant implementation location; retired code includes its original reported line.

## Findings and disposition

1. **[P1, fixed] Save & approve could approve another selected chart.** `unrender/product/static/app.js:1831`. Saving chart A awaited a list refresh; selecting B could make the continuation approve B. The operation now captures chart, account and view, composes PATCH → approval for that chart, and checks ownership after asynchronous boundaries. Workflow tests cover selection changes.

2. **[P2, fixed] Mutation refresh could erase newer edits.** `unrender/product/static/app.js:1546`. A delayed approval refresh could rerender a subsequently selected/edited chart and announce success in the wrong view. The editor is locked for its operation, and post-refresh rendering/cleanup is scoped to the initiating view.

3. **[P2, fixed] Export could complete after new unsaved edits.** `unrender/product/static/app.js:1486`. The fetch checked dirty state before awaiting the blob but could download an obsolete result after an edit during that await. It now checks dirty state again before creating a download and before showing completion.

4. **[P2, fixed] Version restoration could discard unsaved corrections.** `unrender/product/static/app.js:1928`. Restore now refuses dirty state and uses the captured request signal, editor lock and view/account checks before the write and after refresh.

5. **[P2, fixed] Failed navigation marked unsaved values clean.** `unrender/product/static/app.js:1478`. Confirmed discard previously cleared only the flag before loading another chart; failure left the old unsaved inputs visible. Discard now renders the saved job before navigation, restoring values and state together.

6. **[P2, fixed] An older save could leave a newly selected editor locked.** `unrender/product/static/app.js:1657`. The form is shared between views. Rendering a new editor now retires inherited busy/inert state; the old operation's finally block cannot unlock or change the new view.

7. **[P3, fixed] Dead registration CTA remained in markup and JavaScript.** Retired `unrender/product/static/index.html:60`, with old handlers at `app.js:665` and `app.js:2135`. Removed `show-register-button`, its label update and its click handler; the dedicated account routes/tabs own this behavior.

8. **[P3, fixed] Duplicate accessibility utility.** Retired `.landing-sr-only` at `unrender/product/static/landing.css:5`. Landing now uses the already-loaded `.visually-hidden` utility.

9. **[P2, fixed] Sample error text referenced an undefined token.** `unrender/product/static/landing.css:81`. Replaced `--danger` with the shared `--red` semantic token, which exists in both themes.

10. **[P2, fixed] Save & approve duplicated full paginated list refresh/render.** `unrender/product/static/app.js:1831`. The composed path performs PATCH → approval → one list refresh. Standalone save remains available; failed approval preserves the successful correction for retry. Tests assert actual writes and refresh counts.

11. **[P3, fixed] Repeated dirty-state DOM/live-region writes.** `unrender/product/static/app.js:1469`. Subsequent keystrokes return early after the first dirty transition; the primary action, badge and completion state update once.

12. **[P2, fixed] Checkout returned to the marketing page.** `unrender/product/web.py:984`. Moving the workspace to `/app` left success/cancel URLs at `/?billing=…`. Both now return to `/app?billing=…`; the existing signed checkout/webhook test asserts the URLs. Billing remains disabled in the deployed pilot configuration.

13. **[P2, fixed; reported independently by breaking and testing reviewers] Dirty deletion left a deleted editor or asked for discard twice.** `unrender/product/static/app.js:1585`. After a successful DELETE, the code clears the deleted editor, source, history and completion before selecting the next chart, and fences list-refresh continuation. Tests cover next/last chart, delete failure and changed selection.

14. **[P3, fixed; reported independently by breaking and testing reviewers] Add row focused a hidden field.** `unrender/product/static/app.js:1798`. The single-series layout hides the redundant series input; Add row now focuses the visible category input. Covered by the workflow harness.

15. **[Size guidance, open for staged review] The change exceeds the skill's 800-line guideline.** `tests/browser_workflow.mjs:1`, `unrender/product/static/app.css:1`, `unrender/product/static/app.js:1831`. The review snapshot contained 2,559 changed text lines across 32 files, including 1,061 test lines; later pending-state fixes and documentation increase that total. This is not a mechanical diff. The asynchronous workflow portions also warrant the skill's under-500-line stage target. The independent brand stage was committed separately as `fada0e9` (19 changed text lines and seven binary files). The remaining integration stays in a draft PR, with the dependency-aware review sequence below. A separate commit does not by itself make the aggregate PR meet the limit.

16. **[P2, fixed] Core asynchronous transitions lacked explicit pending text.** `unrender/product/static/app.js:1324`, `app.js:1875`, `app.js:2014`, and `app.js:1130`. Chart opening, activity/version requests and PDF page loading now expose pending/error feedback with view/account ownership. This was raised during checklist verification, then checked by the testing reviewer.

17. **[P2, fixed] Editing an approved result retained the export primary action.** `unrender/product/static/app.js:1429`. Export correctly blocked unsaved data, but the prominent button led into that refusal. The first dirty transition now presents Save & approve. A real browser run and workflow test verify the composed write path.

18. **[P2, fixed] Discarding an approved edit did not restore its actions and badge.** `unrender/product/static/app.js:1481`; regression at `tests/browser_workflow.mjs:325`. The incremental review reproduced approved A → edit → confirmed navigation to unavailable B: values were restored, but Save & approve/Needs review remained. Calling `renderJob()` restores the saved status, actions, workflow and inputs together. The failed-navigation test now asserts the restored approval and Download workbook action.

19. **[P2, fixed] Example numeric control was below the requested mobile target size.** `unrender/product/static/landing.css:78`. The correction input was 40px high; it is now 44px. Browser measurement confirmed 44px and the corrected/approved example was recaptured.

The context reviewer reported **no findings**: prompts, weights, provider requests, history/context assembly, schema and extraction service are unchanged. Rust-specific context traits and test-suite instructions are inapplicable to this Python/plain-JavaScript product. Existing output bounds and safe DOM construction remain intact. A temporary checklist concern about identical account descriptions was rechecked: the shared static description had already been removed, and route-specific server descriptions are present.

## Staging and dependency notes

The smallest independent stage, brand generation and favicon assets, is already its own commit. Existing pages consume those favicon paths without requiring routing or layout changes.

Review the remaining draft in this order:

1. Shared theme/tokens and page layout, including their consumers. The global stylesheet removes the old hero rules and the new landing consumes its tokens, so whole-file cherry-picks can produce an incomplete surface.
2. Public document routes, account shells and matching navigation/checkout return URLs. `/`, `/login`, `/signup` and `/app` must agree across server and client.
3. The four-point local interactive example, its asset and its no-inference/no-account tests.
4. Workspace DOM/layout together with dirty navigation/export protections.
5. Save/approve/restore/deletion concurrency with the corresponding workflow scenarios and shared harness.

Smaller landing PRs require deliberate hunk extraction and remeasurement, not moving all tests away from their behavior or omitting coverage. Keep the UI draft based on `codex/render-modal-productization` so it does not also include the earlier deployment/security work from PR #2.

## Verification

- Full local suite: **244 passed, 1 skipped** in 86.70 seconds. Warnings: Starlette/httpx TestClient deprecation and two intentional local Modal-function test warnings.
- Final incremental review: **42 workflow scenarios**, account recovery checks, and **8 focused pytest tests** passed after the discard-state fix. The final API-key/sample pending-label patch was rereviewed independently; all 42 workflow scenarios and auth/two-tab/account checks passed again.
- Product CI scope: Ruff formatting/lint/security rules passed; mypy passed for 19 product source files. Historical research modules outside that CI scope were not rewritten to satisfy unrelated broad lint failures.
- Package wheel built successfully; new landing/theme assets, logo and chart were found inside the wheel.
- Browser: actual local signup and exact replay upload → review → correction → approval → export initiation; light/dark/system, 390/1100/1440 layouts, magnification, menu and audit/history. [Visual QA](../design-qa.md) records screenshots and limitations.
- No production deployment, paid extraction, email send, cloud IAM inspection or model-quality benchmark was performed in this UI pass.
