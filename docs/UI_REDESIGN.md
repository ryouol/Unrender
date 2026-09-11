# Unrender UI redesign

This records the approved Instrument redesign and the disposition of every item in the production-hardening and UX checklist. It is a UI implementation report, not approval for public launch. Legal content, operator contacts, analytics configuration and deployed cloud access still require separate work.

**Stack:** Python/FastAPI/Starlette and Pydantic; SQLite and private files on the Render persistent disk; plain JavaScript, HTML and handwritten CSS; Docker on Render with Modal inference and backup integration. There is no React, Svelte, Supabase, Firebase or browser database SDK.

The [original source security audit and endpoint inventory](UI_SECURITY_BASELINE.md#endpoint-protection-inventory) preceded implementation. Final commands, results and browser evidence belong in [design-qa.md](../design-qa.md); this report deliberately does not duplicate changing test totals.

## Implemented direction

The user selected and refined the Instrument direction before coding: [approved board](design/approved-direction.png). The implementation uses native Helvetica Neue/Helvetica/Arial, white and platinum surfaces, quiet boundaries, medium-weight headings and one blue primary action. Light, Dark and System settings share semantic tokens; chart pixels retain their original colors in either theme. The brand now has a separate mark and favicon family. The displayed logo uses the small 192px derivative; the public example uses a sharp 1600×1000 chart rather than enlarging the old low-resolution replay fixture.

| Surface | Implemented behavior | Main files |
|---|---|---|
| Landing | Separate public explanation, source/table example, above-fold CTA, local correction → approval → CSV/JSON example, mobile menu and contextual sticky CTA. The example creates no account, upload or extraction job. | [landing.html](../unrender/product/static/landing.html), [landing.css](../unrender/product/static/landing.css), [landing.js](../unrender/product/static/landing.js) |
| Auth and account help | Dedicated `/login` and `/signup` entry points; invitation-only wording when registration is closed; existing login remains usable. `/account` retains invitation setup, verification and recovery. | [index.html](../unrender/product/static/index.html), [account.html](../unrender/product/static/account.html), [account.js](../unrender/product/static/account.js), [public_site.py](../unrender/product/public_site.py) |
| Onboarding and workspace | Focused empty state and upload flow; page/crop selection; 220px desktop sidebar; adjacent source/table panes; collapsible metadata; responsive review layout with a sticky source thumbnail on narrow screens. | [index.html](../unrender/product/static/index.html), [app.css](../unrender/product/static/app.css) |
| Review and completion | Visible workflow steps, unsaved-change status and discard protection. Save & approve performs the writes before one list refresh; dirty exports are blocked, including edits during download preparation. Approval enables Download workbook and a completion/next-step panel. Deletion and version restoration preserve view ownership. | [app.js](../unrender/product/static/app.js), [browser_workflow.mjs](../tests/browser_workflow.mjs) |
| Shared presentation | Theme selection, branded error/account/legal shells, page metadata and regenerated favicon derivatives. No new font or UI-framework download. | [theme.js](../unrender/product/static/theme.js), [public_site.py](../unrender/product/public_site.py), [build_web_assets.py](../scripts/build_web_assets.py), [third-party notices](../THIRD_PARTY_NOTICES.md) |

The model, weights, inference contract, credit rules and provider deployment were not changed by the redesign. Existing CSRF, origin, tenant-ownership, input-limit, private-source/export, account-generation, logout-barrier and stale-response guards remain part of the product. Hidden controls are presentation, not authorization.

Local validation used saved exact replay, including enabled local signup → upload → correction → approval → Download workbook. It did not make a new extraction-provider call or start a paid GPU run. Local signup verification does not enable public production signup. Browser checks covered 1440px, 1100px and 390px widths, light/dark presentation, theme persistence, menu focus/navigation, sticky CTA and dirty-edit safeguards; see [design-qa.md](../design-qa.md) for the exact evidence and limits.

## Checklist disposition

**✅ done** means implemented or retained with the stated scope. **⚠️ needs input** identifies missing owner/platform information. **➖ N/A** states why the literal requirement does not apply. No whole phase or whole-platform release is certified by these marks.

### Phase 1 — Security first

| Checklist item | Status and reason |
|---|---|
| Exposed keys in source/client assets | ✅ done — The baseline scan found no real production credential to relocate. Synthetic test fixtures and server-side credential locations are recorded in the [credential inventory](UI_SECURITY_BASELINE.md#credentials). The redesign adds no client credential or provider configuration. The scan did not establish the contents of git history, ignored secrets or platform stores. |
| Auth and validation on endpoints; route inventory | ✅ done — See the [endpoint inventory](UI_SECURITY_BASELINE.md#endpoint-protection-inventory), including the new public document shells. `/`, `/login`, `/signup` and `/app` return static UI, not tenant records. Auth/bootstrap/health and signed-webhook exceptions are intentional; private reads/writes retain their existing authentication, ownership and validation gates. |
| Database RLS/security rules on every table | ➖ N/A — SQLite has no Supabase/Postgres/Firebase anonymous role or RLS policy to enable. Server-side ownership checks and private database files enforce the boundary; see [database and storage](UI_SECURITY_BASELINE.md#database-and-storage). |
| Hardcoded true/disabled/bypassed auth gates | ✅ done — The baseline found no unconditional product auth bypass. Production registration/demo policy checks remain intact; the public illustrative example cannot invoke inference. |
| Public-read/public-write storage audit | ⚠️ needs input — Source delivery is authenticated and tenant files are outside the static mount; no public bucket is configured in source. Actual Render/Modal IAM, membership, credential scopes and volume access were not audited in this UI turn. An operator must verify deployed access before closing this item. |

Phase 1 does not waive existing [security-model launch actions](SECURITY_MODEL.md#required-launch-actions) or [external security gates](SECURITY_REVIEW.md#external-gates).

### Phase 2 — Make it real

| Checklist item | Status and reason |
|---|---|
| Custom 404 and 500 pages | ✅ done — Branded HTML errors provide a home action and inherit appearance tokens. API failures keep machine-readable responses; exceptions are not exposed in HTML. |
| CTA above the fold | ✅ done — The landing opens with Explore an example and a quieter own-chart path. Auth has a focused submit action; workspace empty/upload states provide their next action. |
| Per-page title and description | ✅ done — The fixed page map supplies route-specific titles/descriptions for landing, account shells and legal/contact pages. Shared auth markup no longer overrides the route description. Private/account routes remain noindex. |
| Open Graph/Twitter tags and image fallback | ✅ done — Route-specific social metadata uses the illustrative high-resolution chart as the shared fallback, with descriptive image text. Non-indexable error documents do not need campaign previews. |
| Complete favicon set | ✅ done — ICO, Apple touch icon, 16/32 PNGs, 192/512 PNGs and manifest are generated from the approved brand master. The builder no longer replaces the brand with the replay chart. |
| robots.txt and generated sitemap.xml | ✅ done — Existing origin-aware generation is retained. The sitemap lists the public landing only; private account routes and draft legal pages stay excluded. |
| Alt text on every image | ✅ done — Chart/source previews have descriptive alternatives; decorative brand/icon images use empty alt text. |
| Analytics wired with supplied measurement ID | ⚠️ needs input — Consent storage and settings exist, but no analytics provider, ID, event policy or approved disclosure was supplied. Collection remains off; no fictional measurement ID or tracking endpoint was added. |
| Privacy, terms and cookie consent | ⚠️ needs input — Styled draft pages and essential/optional consent with withdrawal are implemented. Legal operator, jurisdiction, effective terms, privacy contact and reviewed disclosures are pending. The banner does not mean analytics is installed. |
| Thank-you page after submissions | ➖ N/A as a separate page — There is no contact/lead form. Account completion uses a persistent inline outcome and sign-in next step; saves, approval and exports use contextual confirmation. Moving every table save to a thank-you route would interrupt review. |
| Real clickable email, phone and physical address | ⚠️ needs input — Contact scaffolding retains exact TODOs. Supply a monitored email for `mailto:`, a phone for `tel:` or an explicit decision that telephone support is inapplicable, and the legal operator/address. No business details were invented. |

### Phase 3 — Forms, states and dead ends

| Checklist item | Status and reason |
|---|---|
| Loading on every async action and route transition | ✅ done for the checked core/operator paths — Immediate busy/disabled/status feedback covers boot, upload, chart selection, PDF preview, activity/version loading, save, approval, export, API-key inventory and the operator's saved example. API-key results/errors retain request ownership; sample-button cleanup belongs to the active account. This records implemented feedback, not exhaustive testing of every failure permutation. |
| Form errors and inline validation | ✅ done — Native required/email/password/number constraints, associated example-field errors, form alerts and server validation are retained. PDF preview errors are surfaced. Server limits remain authoritative. |
| Success/error messages for submissions | ✅ done for the supported flows — Account, upload, correction, approval, deletion and export paths expose outcomes; export also has a completion panel. This does not assert that every provider/network failure permutation was visually exercised. |
| Broken buttons and dead handlers | ✅ done — New controls have real handlers; obsolete hidden registration code was removed. The primary action follows dirty/approved state, and Add row focuses the visible category input. Existing capability gates keep unavailable billing/demo actions out of the pilot flow. |
| Internal/external/footer links | ✅ done for current site navigation — Landing/auth/account/legal/footer targets are routed, local assets are served and the mobile menu closes on navigation. No external marketing/contact destinations were invented; actual contact links remain an owner-input item above. |
| Clickable logo → home | ✅ done — Brand links point to `/`; workspace navigation preserves the unsaved-edit confirmation. |
| Leftover placeholders and unused navigation | ✅ done for product copy/navigation — Removed the old chart-as-logo hero and unused registration control; no fake team/shared/trash items were added. Legal/contact placeholders remain deliberately flagged until the owner supplies real information. |
| Dynamic copyright year | ✅ done — The shared footer renders the server's current year. Minimal error pages do not require a duplicate footer. |

### Phase 4 — Mobile and performance

| Checklist item | Status and reason |
|---|---|
| No horizontal page scroll | ✅ done at checked widths — Flexible grid tracks and the sidebar breakpoint resolve the previous 1100px overflow. Intentional table/source scrolling remains inside its pane. See measured browser scope in [design-qa.md](../design-qa.md). |
| Real mobile breakpoints across pages | ✅ done — Landing, account/legal shells and workspace have narrow/tablet layouts. The workspace sidebar collapses below 1180px; review stacks at 760px and below. |
| Working mobile menu | ✅ done — Landing uses a labeled Menu button and native modal dialog for focus containment, Escape/close behavior, focus return and close-on-navigation. Auth/workspace controls remain directly available rather than adding an unnecessary drawer. |
| Sticky mobile CTA | ✅ done — The landing CTA appears when the main action leaves view and hides during dialogs. Upload's extraction action remains sticky; the mobile review keeps source context available. |
| Compressed/optimized images | ✅ done — The displayed brand is about 14 KB and the 1600×1000 chart about 47 KB; dimensions are reserved. The small lossless chart prioritizes crisp labels. ➖ Separate `srcset` derivatives/lazy loading are not needed for the current single lightweight above-fold chart; the dialog reuses that same URL. The full brand master is a build input, not the displayed logo. Tenant evidence is not downsampled further for decoration. |
| ≥44px mobile targets and readable type | ✅ done — Mobile controls have comfortable minimum targets, the example correction input is 44px, and mobile fields use 16px type. Focus outlines and reduced-motion behavior are retained. |

### Phase 5 — UX laws applied

| Principle | Status and implementation |
|---|---|
| Hick / Occam / Tesler | ✅ done — One primary review action per state; secondary export formats, reprocess and delete live under More. Chart metadata and keyboard crop controls use disclosure. |
| Fitts / target distance | ✅ done — Larger controls sit with the relevant source/table/form; mobile landing/upload actions remain within reach. |
| Jakob / Similarity / Uniform Connectedness | ✅ done — Conventional sign-in forms, document list, dropzone, table editor and modal menu use consistent fields, buttons and grouping across themes. |
| Proximity / Prägnanz | ✅ done — Source tools stay in the source heading, edit status stays with the table, and metadata is grouped below one disclosure. Quiet boundaries replace the old dense frame treatment. |
| Miller / manageable groups | ✅ done — Short navigation, four workflow steps and a small secondary-action group reduce simultaneous choices. Existing table pagination remains; “7±2” is not used to hide required chart rows or impose a fake job limit. |
| Doherty / perceived responsiveness | ✅ done as a design constraint — Local feedback appears immediately; duplicate list refreshes were removed from Save & approve. Long extraction shows honest stages, not fabricated progress or a claimed sub-400ms inference time. No production latency benchmark is claimed. |
| Von Restorff | ✅ done — Blue identifies the next principal action; secondary actions are quiet and destructive actions retain a distinct treatment. Editing an approved chart changes the primary action back to Save & approve. |
| Serial Position | ✅ done — Upload anchors the workspace entry, the primary review/export action leads its group, and the final conversion action closes the landing. Ordering remains consistent across themes. |
| Peak-End / Zeigarnik | ✅ done — Visible workflow steps lead to approval, Download workbook, a download-started confirmation and an extract-another-chart next step. The public example also has a clear approval/export ending. |
| Postel | ✅ done — Email/title normalization and native input affordances work with strict server schemas and finite-value checks. Passwords are not silently trimmed; review is still required before approval. |
| Pareto | ✅ done as prioritization — Work focused on landing → account entry → first upload → source review → correction → approval/export. This follows the requested journey, not a fabricated traffic-derived 80/20 measurement. |

### Phase 6 — Approved visual polish

| Checklist item | Status and reason |
|---|---|
| Propose one direction before coding | ✅ done — The Instrument board was selected, typography refined and the six-screen direction approved before implementation. |
| Magic UI | ➖ N/A — Its React component approach is not the current plain-JavaScript stack. Equivalent restrained presentation uses local CSS without introducing a framework. |
| Threlte / React Three Fiber | ➖ N/A — No 3D scene serves the chart-review workflow, and the product uses neither Svelte nor React. No WebGL dependency was added. |
| Vectary / Jitter | ➖ N/A — No 3D/motion export is required. If separately approved later, an exported asset would be bundled under `unrender/product/static/`; these authoring tools are not application dependencies. |

## Exact remaining owner-input markers

These markers remain in source. The associated content must be supplied and reviewed; deleting a marker alone does not complete its requirement.

| Source | Exact marker |
|---|---|
| [contact.html](../unrender/product/static/contact.html) | `<!-- TODO: provide monitored support email and render as a mailto link -->` |
| [contact.html](../unrender/product/static/contact.html) | `<!-- TODO: provide business telephone and render as a tel link -->` |
| [contact.html](../unrender/product/static/contact.html) | `<!-- TODO: provide legal operator name and physical business address -->` |
| [privacy.html](../unrender/product/static/privacy.html) | `<!-- TODO: provide legal operator, jurisdiction, effective date, and monitored privacy contact -->` |
| [privacy.html](../unrender/product/static/privacy.html) | `<!-- TODO: provide reviewed cookie and analytics disclosure before enabling analytics -->` |
| [terms.html](../unrender/product/static/terms.html) | `<!-- TODO: provide counsel-approved terms, legal operator, jurisdiction, and effective date -->` |
| [public_site.py](../unrender/product/public_site.py), emitted into the shared footer | `<!-- TODO: provide approved analytics provider, measurement ID, and privacy disclosure -->` |

The implementation note in [site.js](../unrender/product/static/site.js) is also retained exactly:

```js
// TODO: provide approved analytics provider and measurement ID. Keep network
// collection disabled until legal review; if enabled, require choice === "accepted",
// honour withdrawal, and never send chart contents, account IDs, URLs or filenames.
```

The terms draft additionally calls for the contracting entity/address, refund policy, monitored support contact, service levels, warranties, liability, dispute and termination terms. These are business/legal decisions, not copy the UI implementation can invent.

## Follow-up and release boundary

- Supply and review the legal/contact information above; decide whether analytics should be installed at all, then implement only the approved consent, event and CSP policy.
- Verify deployed Render/Modal access with the operator. Source inspection cannot attest to private cloud IAM, volume sharing or credential scopes.
- Use [design-qa.md](../design-qa.md) and [UI_CODE_REVIEW.md](UI_CODE_REVIEW.md) for the final tested scope and review disposition.
- Keep production signup, SMTP delivery, billing, credit policy and provider spending behind their existing operator decisions. Local replay validation does not authorize any of them.
- Revalidate larger-document preview fidelity separately if needed. The new marketing chart fixes the public asset's blur; CSS zoom cannot recover missing pixels in an uploaded raster or narrow PDF crop.

Public-launch readiness remains governed by [LAUNCH_READINESS.md](LAUNCH_READINESS.md), [LEGAL_REVIEW.md](LEGAL_REVIEW.md), [SECURITY_MODEL.md](SECURITY_MODEL.md) and the deployment/operational reviews. This redesign does not close those gates.
