# Visual and accessibility QA

## Evidence

The product was run locally with the replay extractor in the Codex in-app browser. The isolated public demo was opened, processed, corrected, restored from history as a new correction, approved, exported, and signed out; direct database inspection confirmed that sign-out removed its tenant, jobs, and pending deletions. A disposable customer workspace exercised registration, the native file chooser, a 10%/10%/80%/80% keyboard crop, a provider failure, the free saved sample, and API-key create/revoke without exposing the full key in QA output. Current credit semantics distinguish pre-dispatch refunds from charged post-dispatch failures; the automated adversarial suite, not this earlier visual pass, is the evidence for that invariant.

After the second exact-tree review, the current working tree was rerun from source (the served and local JavaScript SHA-256 values matched). A sample correction was saved and version 1 was restored through the new explicit one-version fetch. A 22-version workspace rendered exactly 20 metadata entries plus **Load older versions**, then appended the remaining two without duplicates or another pager. The same current build was inspected at 390×844: workspace navigation, actions, warning, source, and history controls remained readable, wrapped without horizontal page overflow, and preserved their existing focus/contrast treatment.

After the `f038311` review, the current tree was run in local Chrome for Testing
147 through Playwright because this task had no available in-app browser runtime.
Two real tabs shared one cookie jar. One tab held an old-account job response while
the other signed out; the observing tab synchronously cleared account, job, upload,
source, result, version, audit, API-key inventory, and one-time secret state. Releasing
the delayed response did not repopulate anything, and a different account received a
different principal marker. The logout request was also held for more than 1.2 seconds;
focus, pageshow, and visibility events still could not reconcile the old principal. A
real key create/copy flow cleared its secret after copy.

The maximum valid editor shape (50 series × 200 points, 10,000 logical rows) rendered
100 table rows and 454 total mounted cells in 2.4 ms. Desktop was checked at 1280×720.
At 390×844 the first pass exposed a 475 px intrinsic grid width; zero-minimum pane sizing
fixed it, and the final document/body and viewport widths all measured 390 px. This pass
is a targeted privacy, maximum-contract, and responsive regression—not a formal browser,
performance, or accessibility certification.

Captured evidence:

- [`screenshots/landing-desktop.png`](screenshots/landing-desktop.png)
- [`screenshots/review-desktop.png`](screenshots/review-desktop.png)
- [`screenshots/review-mobile.png`](screenshots/review-mobile.png)

There is no baseline UI screenshot because no product interface existed at commit `9f13196`.

## Viewports and findings

- 1280×720: landing hierarchy, account entry, isolated-demo labels, job list, source/editor split, action wrapping, table scroll, history, audit, and source containment were visually checked. Earlier 1440×900 evidence remains in `docs/screenshots/`.
- 390×844: review panes collapse to one column; the job list remains intentionally horizontally scrollable; primary actions wrap; API-key access remains visible; the table stays inside its container.
- A two-job mobile state exposed a grid min-content regression with 460 px document width. The responsive grid/sidebar/list tracks now use zero-minimum sizing; the recheck measured document `scrollWidth` and `clientWidth` at 375 px with no page-level horizontal overflow.
- Keyboard crop fields were filled through their accessible names. Applying the crop produced a visible selection at `left: 10%; top: 10%; width: 80%; height: 80%` before the job was queued.
- A stale job-list status discovered during QA was fixed so polling refreshes the sidebar on lifecycle transitions.
- The mobile sidebar previously hid API-key access; QA changed it to a visible compact footer.
- The API-key close button previously submitted the form; it now closes without creating a key.
- Browser diagnostics remained empty throughout the final customer/demo journeys.
- Current-tree two-tab privacy, maximum-result, desktop, and mobile assertions completed in Chrome for Testing 147; the CI-safe Node harnesses preserve the auth/selection timing cases without a browser binary.

## Accessibility baseline

- A skip link, semantic landmarks, headings, labels, table headers, status region, dialog label, descriptive image alternatives, and explicit button types are present.
- Automated static tests reject duplicate IDs, unlabeled form controls, unlabeled dialogs, images without `alt`, buttons without types, and pages without language/main/title/H1 contracts.
- Focus-visible styling uses a 3px blue outline.
- Checked color contrast ratios:

| Pair | Ratio |
|---|---:|
| Body ink on paper | 15.02:1 |
| Muted text on paper | 4.64:1 |
| Green text on surface | 9.37:1 |
| White on primary green | 6.49:1 |
| Amber notice text/background | 7.35:1 |
| Danger text/surface | 7.29:1 |
| Focus blue on paper | 5.20:1 |

## Remaining external check

Before accepting customer data, run VoiceOver/NVDA and real keyboard-only tests in the supported production browsers, including PDF page/crop, long multi-series tables, errors, dialog focus trapping, downloads, and 200% zoom. The current QA is a strong implementation baseline, not a formal WCAG conformance claim.
