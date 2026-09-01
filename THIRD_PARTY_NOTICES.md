# Third-party notices

This file is a release inventory, not a substitute for dependency-specific license texts or legal review.

## Bundled asset

IBM Plex Sans (regular and semibold WOFF2) is bundled under the SIL Open Font License 1.1. The license text is included at `unrender/product/static/fonts/LICENSE.txt`.

## Referenced model artifacts

The research pipeline references Qwen3-VL model artifacts distributed through Qwen/Unsloth. Their cited artifact pages identify Apache-2.0, but model and training-data obligations must be reviewed before redistributing fine-tuned weights. No model weights are bundled in the Python package or container.

## Runtime libraries

The application depends on Python, FastAPI/Starlette, Uvicorn, Pydantic, Pillow, PyMuPDF, OpenPyXL, the Modal and Stripe Python clients, NumPy, Matplotlib, and related transitive packages. Exact resolved versions and hashes are in `requirements-app.lock`. Generate and archive an SBOM plus all required license texts for a public binary/container release.

## External services

Modal and Stripe are optional external processors selected by the operator. Their service terms, data-processing terms, regions, security controls, and subprocessors are not granted by this repository license and must be reviewed before use with customer data.
