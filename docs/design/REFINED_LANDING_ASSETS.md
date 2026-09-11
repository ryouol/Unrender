# Refined landing artwork and brand receipt

Approved visual: the 2026-09-11 landing mockup `exec-d8972c20-0a8b-4ee6-945d-ed66d601c7ae.png`, with the library mockup `exec-f495463b-0ead-4e7c-b171-884013f81e70.png` as a brand reference. Both are from the user's selected refinement of Unfold and Precision. The page is implemented in HTML and CSS; no screenshot is used as a page.

## Delivered assets

| Asset | Use | Source |
| --- | --- | --- |
| `unrender/product/static/artwork/unfold-hero-800.webp` and `unfold-hero-1600.webp` | Light landing hero, 2:1 aspect ratio | Built-in Image Gen `exec-eacd8c8b-54ab-4507-97e0-ddd46abf7e12.png` |
| `unrender/product/static/artwork/unfold-hero-dark-800.webp` and `unfold-hero-dark-1600.webp` | Dark landing hero, identical composition | Built-in Image Gen `exec-b92e7888-3144-45ad-9f57-1c78210b8083.png` |
| `unrender/product/static/icons/brand-mark.png` | 512 px transparent master | Built-in Image Gen `exec-97e7db0b-93e7-429e-a038-b70a8ba470d6.png` |
| `unrender/product/static/icons/brand-mark-dark.png` | White-frame, blue-pixel dark derivative | Same approved transparent master; deterministic color conversion |
| Existing favicon, Apple touch, 192 px and 512 px icon family | Browser/application identity | `scripts/build_web_assets.py`, using the new master |

Generated masters remain under the Codex image-generation directory. Every asset consumed by the application is copied into the repository. The web page uses responsive 800 px and 1600 px WebP exports (about 12–39 KB each), with intrinsic dimensions reserved to prevent layout movement. Paper and chart labels belong to the artwork; the headline, navigation, workflow descriptions, formats, and calls to action are real DOM text.

The image is a conceptual illustration, not a model result, accuracy benchmark, or executable demonstration. The interactive landing example, prepared correction flow, and example downloads were removed. The only landing request is the existing anonymous public configuration endpoint; no customer session, upload, or inference is requested.

## Final prompts

Generation used the built-in Image Gen tool, not the API/CLI fallback.

### Light hero

> Use case: product-mockup. Asset type: standalone landing-page hero artwork for UNRENDER. Reference image: approved website design; extract its art direction, not its page. Create ONLY the single sculptural paper artwork below the button in the reference, with no webpage header, no headline, no button, no logo, no footer. A crisp white paper line chart floats at a shallow perspective on the left, its lower edge unfolding in four physical paper ribbons toward a flat white spreadsheet sheet in the lower right. Premium photoreal studio render, platinum white background (#ffffff), soft neutral shadows, fine paper fiber, blue chart line, black Helvetica-like chart text. Match the reference composition and camera angle closely. Chart title exactly Quarterly Revenue. Plot four blue points with values Q1 12.4, Q2 18.6, Q3 16.8, Q4 24.2; table headings Quarter and Revenue ($m), same four rows. Let a few ribbons show the numeric values. All text belongs to the physical paper. The art fills an approximately 2:1 wide canvas with 8% white margin, fully visible paper edges, absolutely no cropped objects. High resolution and crisp legible print on the papers. This is illustrative brand artwork, not a screenshot or working UI. No gradient background, no words outside the paper, no sparkle effects, no generic app cards.

### Dark hero

> Use case: lighting-weather. Edit this hero illustration for a dark-mode website. Change ONLY the white background and ground to a completely uniform charcoal #15171b, and adjust soft studio illumination and shadows so the white paper sculpture reads naturally against that ground. Preserve exactly the paper geometry, camera angle, chart and table, blue line, framing, all text and values. Keep white/light platinum paper and crisp black text. No new objects, no UI, no text outside the paper. Maintain the same 2:1 landscape composition and wide margins.

### Brand mark

> Use case: logo-brand. Asset type: production transparent PNG brand symbol only for UNRENDER. Reference image is the approved website: faithfully recreate ONLY the extracted-pixel logo to the left of the word unrender in its header, at a very large crisp scale. One pure black thick square frame with a square white/transparent center and its top-right corner removed; the missing corner is a detached small vivid blue square floating diagonally above and to the right, with a clearly visible small gap. This is the reference's geometric open square with extracted blue pixel, not a letter U, not a G, no rounded corners. Precisely axis-aligned, sharp flat vector-like shapes, absolutely no 3D or gloss or gradients or shadow. Symbol should fill 80% of a square canvas with balanced transparent padding. Genuine alpha-transparent background, including the cutout center and missing corner. No wordmark, no typography, no other symbols. Keep faithful to the approved mark, do not redesign.

## Production processing

ImageMagick downscales the hero masters to 1600 × 800 (WebP quality 88) and 800 × 400 (quality 85). No paper geometry, labels, or chart values are redrawn in code.

The selected logo is a real RGBA image. Alpha thresholding removes faint generated background residue; the visible mark is trimmed, centered on a 1120 px transparent square, and resized to 512 px. The dark derivative changes black RGB to white while preserving that master alpha and blue pixel. Two attempted Image Gen dark recolor outputs baked a checkerboard into RGB and were rejected; neither is served or committed. The deterministic derivative avoids geometry drift and preserves actual transparency.

The existing `scripts/build_web_assets.py` produces the favicon and touch-icon derivatives from the new master. Dark 16 px and 32 px PNG favicons additionally derive from the white-frame master, and the Apple touch icon is flattened onto white so its black frame stays visible on a standalone icon surface. The shared asset script reproduces these additions, and public metadata links the dark favicons to the browser’s preferred color scheme. The selected master remains the single source for every size.

## Motion behavior

Scrolling moves and slightly scales the hero illustration through a bounded transform. IntersectionObserver reveals each copy section once. The browser keeps native scrolling and anchor navigation. There is no WebGL dependency, scroll hijacking, automatic camera loop, or continuously running renderer.

Pause freezes the illustration while copy remains readable. Reduced motion resets the illustration and shows every section without animation. Pending animation frames are canceled when the tab is hidden or the page leaves; back-forward cache restores observation on return. Browsers without IntersectionObserver keep all copy visible. JavaScript failure leaves a complete static page with working native links.

## Verification

- `node tests/browser_landing.mjs`: passed. Checks static markup, asset/anchor existence, public-only requests, configuration fallback, invitation CTA, pause, reduced motion, event coalescing, idle frames, hidden-tab suspension, and page lifecycle cleanup.
- `pytest tests/test_public_site.py -q`: 6 passed. Existing Starlette/httpx deprecation warning remains.
- Ruff checks and formatting for the touched Python test: passed.
- Visual comparison, real browser interactions, and the final `design-qa.md` gate are coordinated by the parent implementation task.
