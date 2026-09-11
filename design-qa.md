# UNRENDER — approved direction implementation QA

**final result: passed**

Reviewed September 10–11, 2026, against the approved Refined Instrument direction. This result covers the implemented local UI and its tested workflow. It does not certify the model's accuracy, the live deployment, legal readiness, or cloud permissions.

## Visual truth and capture conditions

- Source: [approved design board](docs/design/approved-direction.png). Original file: `/Users/royluo/.codex/generated_images/01a08975-3779-7aa1-ab3b-fc2a28dcf1b8/exec-dde45047-86e0-444b-9e50-724386bcbe49.png`.
- Implementation: `http://127.0.0.1:8000/`, using the Documents/Codex checkout and the real FastAPI application. Local extraction uses saved replay, with no Modal inference.
- Source pixels: **1672 × 941**, a six-screen board with labels and canvas margins. The board does not specify independent CSS viewports or device density. It is not a 4K single-page screenshot.
- Browser screenshots: **1440 × 1024**, **1100 × 900**, and **390 × 844** pixels at matching CSS viewport sizes; browser `devicePixelRatio` was **1**. No browser chrome, image stretching, or density resampling is included.
- Comparisons use the corresponding board panel, theme, and workflow state. The board's miniature frames are not compared pixel-for-pixel to a full desktop page. Landing content uses the same four-point revenue example. Workspace evidence uses the owned 18-row replay fixture, so row density and source artwork differ intentionally.

## Evidence

| State | Screenshot | Viewport |
|---|---|---|
| Landing, light | [landing-light.png](docs/design/landing-light.png) | 1440 × 1024 |
| Landing, dark | [landing-dark.png](docs/design/landing-dark.png) | 1440 × 1024 |
| Example, corrected and approved | [example-approved.png](docs/design/example-approved.png) | 1440 × 1024 |
| Create workspace | [sign-up.png](docs/design/sign-up.png) | 1440 × 1024 |
| Upload selection | [upload.png](docs/design/upload.png) | 1440 × 1024 |
| Saved result, review required | [review-light.png](docs/design/review-light.png) | 1440 × 1024 |
| Approved result | [workspace-light.png](docs/design/workspace-light.png) | 1440 × 1024 |
| Download started, dark | [approved-dark.png](docs/design/approved-dark.png) | 1440 × 1024 |
| Tablet workspace, dark | [tablet-dark.png](docs/design/tablet-dark.png) | 1100 × 900 |
| Mobile focused cell and visible source | [mobile-review.png](docs/design/mobile-review.png) | 390 × 844 |
| Mobile sign-in | [mobile-sign-in.png](docs/design/mobile-sign-in.png) | 390 × 844 |
| Mobile signup | [mobile-sign-up.png](docs/design/mobile-sign-up.png) | 390 × 844 |

The source board and implementation screenshots were opened together in the same comparison inputs: landing/light plus review/light; signup plus approved/dark plus mobile review; and landing/dark. They were inspected at original image resolution. Focused comparison covered the headline and CTA group, logo edges, form labels/focus state, source/table headings and cells, dark secondary controls, and approval/export copy. These details are readable in the full-resolution evidence; separate image crops were not needed.

## Required fidelity surfaces

| Surface | Result and evidence |
|---|---|
| Fonts and typography | The lighter, neutral grotesk direction is implemented with Helvetica Neue, Helvetica, Arial, then sans-serif. Headlines use regular optical weight, tight tracking and the approved two-line landing wrap. Form and table text remains legible, with tabular numeric values and 16px mobile inputs. No remote font request is required. Windows/Linux fallbacks have not been visually sampled. |
| Spacing and layout rhythm | Landing keeps the large left-aligned title, one primary CTA, and chart-to-table composition. Authentication is a focused column. Desktop review keeps source and values adjacent; secondary fields are in Details. At 1100px the sidebar becomes a horizontal strip, preserving the two-pane review. At 390px the source stays visible while editing the vertically stacked table. |
| Colors and tokens | White/platinum surfaces, graphite text, cobalt actions and restrained borders match the selected direction. Dark mode uses explicit foreground/surface tokens, not an image inversion. Secondary buttons and links were corrected after visual review. Focus, error and success colors have distinct states. |
| Image quality and assets | The generated blue brand mark has genuine alpha and optimized favicon derivatives. The displayed 192px asset is about 14KB. Standard icons use pinned MIT Phosphor assets. The exact four-point revenue chart is a 1600 × 1000 lossless PNG, about 46KB, rendered from its numbers. The original low-resolution replay fixture remains unchanged; magnification cannot recover absent detail. No fake enhancement or replacement of the uploaded source is claimed. |
| Copy and product truth | The landing explains image → extracted table → human review → export. The interactive example is labeled illustrative and runs locally. Supported limits come from public configuration. Approval is attributed to the user. Download completion says “Download started,” since the browser controls saving. XLSX promises audit metadata, not an embedded source image or independently verified accuracy. |

## Comparison history and resolved findings

Each P2 observation blocked the visual handoff until the relevant view was captured again.

| Priority | Earlier evidence / issue | Fix and post-fix evidence |
|---|---|---|
| P2 | Original tablet workspace overflowed at 1100px; correction panes and controls could clip. Initial live capture: `outputs/design-redesign/06-live-tablet.png`. | Responsive sidebar strip and bounded grid tracks. [Tablet capture](docs/design/tablet-dark.png), document scroll width exactly 1100. |
| P2 | Initial dark implementation used native WebKit button appearance, producing pale secondary buttons with light text. Capture: `outputs/design-redesign/16-approved-dark.png`. | Explicit button appearance and token colors. [Approved dark](docs/design/approved-dark.png) and [tablet dark](docs/design/tablet-dark.png) show readable controls. |
| P2 | Four columns in a single-series table crowded the Remove action at 390px. Capture: `outputs/design-redesign/18-mobile-review.png`. | Hide redundant series column for a single series, retain the data input, and focus the visible category on Add row. [Mobile review](docs/design/mobile-review.png): table client and scroll widths both 330px, page scroll width 390px. |
| P2 | Dark landing text links inherited the saturated action-background blue. Capture: `outputs/design-redesign/21-landing-dark.png`. | Use `--accent-ink` for link text. [Final dark landing](docs/design/landing-dark.png) was compared again with the source palette. |
| P2 | Editing an approved chart kept Download workbook as the primary action even though export correctly refused unsaved data. | Dirty state now immediately offers Save & approve. Browser verified edit → PATCH/save → approval → Download workbook. Regression also covers discarded edits followed by failed navigation. |
| P2 | Sample numeric input was 40px high, below the requested 44px tap target. | Raised to 44px; the existing table/dialog remains within the responsive layout. |
| P3 | Mobile authentication repeated navigation in its header and tabs, pushing appearance onto a second header row. | Hide redundant mobile header navigation; retain account tabs and brand/theme. [Mobile sign-in](docs/design/mobile-sign-in.png). |

## Functional and accessibility checks

- Tested the browser-only example: open, correct 16.3 to 16.8, save, approve, export, reset, close, and restore focus. No account or inference is needed. Changes invalidate sample approval.
- Tested local account creation, sign-in, sign-out, reload/session reconciliation, and account recovery entry with email delivery disabled. Recovery gives an operator-link path rather than offering unavailable email delivery.
- Uploaded the owned `budget-quarter.webp` through the browser file chooser, selected the preview, ran saved replay, corrected data, approved, and initiated an XLSX download. Export generation/content is also covered by the backend tests; no claim is made that the browser download was opened in Excel during this UI pass.
- Tested Fit and 2× source magnification, dirty export refusal, dirty approved primary action, saved approval, version list and audit activity, and the post-export next action.
- Tested Light, Dark, System, and preference persistence. Tested mobile menu focus/navigation and the sticky example CTA after the hero scrolls out of view.
- Checked keyboard-visible focus, labeled inputs, native modal focus containment, image alt text, 44px action targets, and reduced-motion CSS. Automated screen-reader and color-vision audits were not performed.
- No page-level horizontal overflow at 390, 1100, or 1440px in the inspected primary states. Multi-series data may use intentional internal table scrolling.
- In-app browser console inspection returned no logged errors (`[]`) after the final workflow and landing runs.

## Automated validation

Full local pytest: **244 passed, 1 skipped** (86.70s). After the last UI state changes, all **42 workflow scenarios**, auth-epoch, two-tab, account recovery and the **8 focused pytest checks** passed. Product CI lint/security/format checks and mypy (19 source files) passed. The wheel built with the new static pages, theme, chart and brand assets included. See [all review findings and scope](docs/UI_CODE_REVIEW.md).

## Accepted differences and remaining limits

- The operational workspace has an 18-row chart, tenant actions and audit history rather than the board's four-row illustration. The source pixels, record counts and filenames are real local replay data.
- The dark export state is integrated into the workspace, preserving review context and a next action. CSV/JSON are in More, and XLSX is the primary download.
- Local development exposes signup and saved replay for testing. Production configuration continues to control invitation-only access; this redesign does not enable public registration, SMTP or billing.
- No decorative 3D, new animation framework or external type service was added. Motion is limited to useful short control transitions and respects reduced motion.
- P3 follow-up: very narrow sidebar cards can wrap status/date over two lines. This remains readable and does not hide controls. Cross-platform font and real-device touch/screen-reader sampling remain useful before a broad launch.
- The source board supplies no mobile layout. Mobile evidence therefore validates a responsive interpretation of the approved type/color/components, not a nonexistent pixel-perfect mobile reference.

## Implementation checklist

- [x] Approved board and rendered implementation opened and compared together.
- [x] Typography, layout, colors, assets and copy reviewed explicitly.
- [x] Desktop, tablet, mobile, light, dark, authentication, review and export states inspected.
- [x] Actionable P0/P1/P2 visual and interaction findings fixed and rechecked.
- [x] Core local journey works; console checked; local preview kept running.
- [x] Business, operations and legal follow-ups are separated in [UI_REDESIGN.md](docs/UI_REDESIGN.md).
