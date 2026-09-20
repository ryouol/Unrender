# Refined platform design QA — September 11, 2026

final result: passed

The approved paper-unfold landing, visual chart library, cutout/pixel brand and clean correction workspace are implemented. No actionable P0/P1/P2 visual or interaction findings remain in the checked states. This design result does not certify model accuracy or the absence of all software defects.

## Reference and capture method

Visual truth: `/Users/royluo/.codex/generated_images/01a08975-3779-7aa1-ab3b-fc2a28dcf1b8/`:

- Landing: `exec-d8972c20-0a8b-4ee6-945d-ed66d601c7ae.png` (1422 × 1106).
- Library: `exec-f495463b-0ead-4e7c-b171-884013f81e70.png` (1513 × 1039).
- Review: `exec-f727b601-f4a9-48ed-9754-7bbed1a7d388.png` (1513 × 1039).

Local implementation: `http://127.0.0.1:8000/` and `/app`, captured through the Codex browser at 1440 × 1024 CSS pixels, with 1440 × 1024 screenshot pixels. References were scaled uniformly to 1440 pixels wide, top-aligned, and cropped/padded to 1024 high. Earlier contain-based comparisons and scrolled/full-page stitching captures were superseded. Final landing scroll position was explicitly checked at zero. Comparison boards place reference left and implementation right in a single input.

The private library uses three independently checked, sharp local fixtures. Their values are illustrative test data; they are not inference results. The reference has different chart types/content, two review charts and one approved chart; the captured library has one review chart and two approved after testing. The review comparison contains four quarterly values and an edited Q3 cell. Extra metadata, row removal, save-without-approval, and audit controls support existing product behavior beyond the concept drawing.

## Final evidence

- [Landing comparison](docs/screenshots/refined/landing-comparison-final.png), [typography detail](docs/screenshots/refined/landing-detail-final.png).
- [Library comparison](docs/screenshots/refined/library-comparison-final.png), [heading and filters detail](docs/screenshots/refined/library-detail-final.png).
- [Review comparison](docs/screenshots/refined/review-comparison-final.png), [editable table detail](docs/screenshots/refined/review-detail-final.png).
- [Mobile landing](docs/screenshots/refined/landing-mobile.png), [mobile library](docs/screenshots/refined/library-mobile-viewport.png), [mobile review](docs/screenshots/refined/review-mobile-viewport.png), [mobile signup](docs/screenshots/refined/signup-mobile.png).
- [976-pixel review](docs/screenshots/refined/review-tablet-final.png), [dark review](docs/screenshots/refined/review-dark-final.png).

Mobile viewport captures are 390 × 844; tablet is 976 × 900. Full-page mobile stitching produced duplicated/blank areas in the browser capture, so viewport captures and actual DOM geometry were used instead. At 976 pixels, source and data top coordinates both measured 305.48 pixels, with widths 504.59 and 396.86; document overflow was false. Mobile intentionally stacks the source above the editor.

## Findings and iterations

1. **Resolved P2 — Landing type and artwork hierarchy.** Early captures used too much heading weight/space, then an overly light weight. Final Helvetica Neue 400, 86-pixel desktop cap, tighter tracking and hero spacing reproduce the approved two-line hierarchy. The final full and focused comparisons above supersede the earlier captures.
2. **Resolved P2 — Chart menu overlapped status.** More-specific library menu CSS now positions the three-dot button beside the filename, independently of status. The final library capture verifies the separation.
3. **Resolved P2 — Review hierarchy was too small and vertically loose.** Increased the review heading and table input size and reduced breadcrumb, stepper and pane gaps. Source and editor remain balanced in the final comparison; the 976-pixel check verifies side-by-side correction.
4. **Resolved P2 — Preview requests competed for server capacity.** The library now serializes private 640-pixel thumbnails, retains mounted cards, and releases object URLs on account/view changes. Browser captures show all three previews; authenticated access and retry behavior also have integration coverage. The CSP explicitly permits image blob URLs.
5. **Resolved P2 — Project deletion had an empty default value.** The form now explicitly selects keep-charts. Untouched submission was retested successfully in the browser, and the automated regression verifies the charts survive.
6. **Resolved P2 — Unsaved edits retained an approved heading.** Editing an approved result now restores the Review heading/step and marks unsaved changes. Export remains blocked until saving; approving restores the approved state. The final review capture and workflow regression verify this.

## Required fidelity surfaces

- **Typography:** Helvetica Neue/Helvetica/Arial stack, restrained 400 display weight, readable form text and tabular numeric input. Heading wrapping, real browser focus states and mobile text were inspected. Exact raster antialiasing in the generated reference is not reproducible as a font metric.
- **Spacing:** Open white layout, horizontal navigation, three-card desktop grid, flat split editor, minimal radius/shadow. Native controls remain at least 44 pixels high. The app retains additional working metadata/history controls rather than hiding capabilities shown in the existing product.
- **Colors:** White/graphite surfaces, restrained blue emphasis, semantic approval/error colors, and a separate dark palette. Dark artwork and brand assets were verified; source chart images retain their original colors.
- **Images:** Generated paper-unfold artwork is shipped as sharp responsive WebP assets, with the approved cutout/pixel brand raster and licensed Phosphor icons. No CSS-drawn substitute for the illustration or logo. Private previews are bounded thumbnails; source magnification uses the larger protected source.
- **Copy:** Static landing explains upload, review, approval and audited export without presenting a model demo. Limits come from public configuration. Local signup shows its three replay credits; production accounts start at zero and offer access contact. No fabricated performance/accuracy claims.

## Interaction verification

Checked in the browser: landing anchors, motion pause, light/dark selection; mobile signup/signin layout; password logout/login; signed-in logo to My charts; project creation, chart move, project keep-charts deletion and chart deletion; keyboard pane resize and 200%/Fit magnification; editing, saving, approval and workbook download. The downloaded workbook contained Q1–Q4 values 12.4, 18.6, 16.8, 24.2 and an Audit sheet. Browser console checks on the final local build returned no errors/warnings. Automated suites additionally cover auth races, pending writes, status refresh, preview cleanup and deletion isolation.

Google buttons are intentionally off in the local replay launcher. Dedicated production OAuth configuration and live consent are a separate release verification, not inferred from these screenshots. Account deletion is exercised against isolated synthetic data in the container/API tests.

## Follow-up polish

Native select controls and numeric spinners differ slightly by browser. The working table retains explicit row-removal and chart-details controls; a future compact toolbar could reduce density further. These are P3 refinements and do not block the checked workflows.
