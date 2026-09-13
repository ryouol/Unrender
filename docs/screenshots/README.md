# Product screenshots

## README gallery — refined interface

The root README embeds these actual local application captures from the September 11, 2026 visual QA pass (1440 × 1024 pixels). They match the refined interface shipped in runtime `015624a` and retained in `a14b961`.

| Image | Visible state |
|---|---|
| [Review workspace](refined/review-desktop-final.png) | Source and editable table, with an unsaved correction |
| [Landing page](refined/landing-desktop-final.png) | Public entry before sign-in; conceptual chart-to-table artwork |
| [Chart library](refined/library-desktop-final.png) | Three illustrative charts, search, status/project filters |
| [Dark review](refined/review-dark-final.png) | Approved result and confirmation toast in dark mode |

The chart library and review captures use independently checked **illustrative local fixtures**, not live inference predictions or customer data. The four quarterly values do not measure model accuracy. The landing artwork is a concept illustration within the real page. Images are included as captured, not recreated as UI mockups. Account initials are from a synthetic local account; no credentials or personal customer uploads appear.

[Visual QA record](../../design-qa.md) documents the source, dimensions, and comparison method. Additional mobile/tablet captures and reference-comparison boards remain in `refined/`; comparison boards are not used as product screenshots in the README.

## Earlier v0.2 captures

The files below predate the refined interface and are retained as historical QA evidence, not current marketing screenshots.


These screenshots were captured from the local replay deployment during the v0.2 visual QA pass. The source sample is the bundled deterministic verification fixture; no live inference or paid provider call was used.

- `landing-desktop.png` — public positioning and account entry at 1440×900.
- `review-desktop.png` — source-side review workspace at 1440×900.
- `review-mobile.png` — responsive review workflow at 390×844.
- `api-keys-desktop.png` — existing-key inventory after a create/revoke lifecycle; only the non-secret prefix is visible.

There is no baseline “before” screenshot because the repository had no product UI at the audited baseline commit.
