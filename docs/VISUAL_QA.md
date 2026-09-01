# Visual and accessibility QA

## Evidence

The product was run locally with the replay extractor in the Codex in-app browser. The exact saved fixture was submitted, reviewed, corrected, approved, and reopened. API-key dialog open/close behavior and status synchronization were exercised.

Captured evidence:

- [`screenshots/landing-desktop.png`](screenshots/landing-desktop.png)
- [`screenshots/review-desktop.png`](screenshots/review-desktop.png)
- [`screenshots/review-mobile.png`](screenshots/review-mobile.png)

There is no baseline UI screenshot because no product interface existed at commit `9f13196`.

## Viewports and findings

- 1440×900: landing hierarchy, account entry, job list, source/editor split, action wrapping, table scroll, and source containment were visually checked.
- 390×844: review panes collapse to one column; job list remains usable; primary actions wrap without horizontal overflow; API-key access remains visible; the table fits its container.
- Measured mobile document overflow was non-positive. The review grid resolved to one column and the table client/scroll widths matched for the sample.
- A stale job-list status discovered during QA was fixed so polling refreshes the sidebar on lifecycle transitions.
- The mobile sidebar previously hid API-key access; QA changed it to a visible compact footer.
- The API-key close button previously submitted the form; it now closes without creating a key.

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
