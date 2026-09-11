# Third-party notices

This file is a release inventory, not a substitute for dependency-specific license texts or legal review.

## Bundled asset

IBM Plex Sans (regular and semibold WOFF2) is bundled under the SIL Open Font License 1.1. The license text is included at `unrender/product/static/fonts/LICENSE.txt`.

Phosphor regular SVG icons are bundled under the MIT license. Source: https://github.com/phosphor-icons/core/tree/2b75f3ad12b420c9504ef05df8d2564a28f8500e/assets/regular. Only filenames are shortened; paths are unmodified. The license is retained at `unrender/product/static/icons/PHOSPHOR-LICENSE.txt`.

The unmodified Google G at `unrender/product/static/icons/google-g.png` comes from https://developers.google.com/static/identity/images/g-logo.png. It identifies the Google sign-in action and remains subject to Google's branding guidelines at https://developers.google.com/identity/branding-guidelines; the repository license does not grant rights to Google's trademarks.

## Referenced model artifacts

The research pipeline references Qwen3-VL model artifacts distributed through Qwen/Unsloth. Their cited artifact pages identify Apache-2.0, but model and training-data obligations must be reviewed before redistributing fine-tuned weights. No model weights are bundled in the Python package or container.

## Runtime libraries

The application depends on Python, FastAPI/Starlette, Uvicorn, Pydantic, Pillow, pypdfium2/PDFium, OpenPyXL, the Modal and Stripe Python clients, NumPy, Matplotlib, and related transitive packages. Exact runtime versions/hashes are in `requirements-app.lock`; test/lint and wheel-build toolchains are separately resolved in `requirements-dev.lock` and `requirements-build.lock`. The checked-in CycloneDX inventory is `release/sbom.cdx.json`.

Google sign-in uses the Apache-2.0 `google-auth` library and its locked requests/cryptography dependencies. Package distributions retain their upstream license files. Google OAuth is an optional external identity service; no Google API access or refresh tokens are retained.

`PyMuPDF` has been removed from product code and both runtime/development locks. PDF validation and rasterization now use locked `pypdfium2==5.13.0`; upstream identifies the binding as Apache-2.0 OR BSD-3-Clause and PDFium as BSD-style with additional dependency notices. The platform wheels ship their applicable license files under package metadata; every binary distribution must retain them. This engineering replacement removes the former mandatory AGPL/commercial-license dependency, but it is not legal advice and does not approve the overall product release. The machine policy keeps public release blocked until the owner and qualified counsel approve the contracting/privacy/terms/distribution details.

## External services

Modal and Stripe are optional external processors selected by the operator. Their service terms, data-processing terms, regions, security controls, and subprocessors are not granted by this repository license and must be reviewed before use with customer data.
