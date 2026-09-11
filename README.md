# Unrender

Unrender is a review-first workspace for turning chart images and PDF pages into structured data. It keeps the source beside an editable table, records every correction, and exports JSON, CSV, or XLSX. The XLSX audit sheet carries source, model, status, and approval metadata; JSON and CSV are data-only exports.

The product is designed for research and consulting teams that need chart data they can inspect and defend. It does **not** promise automatic accuracy: extraction results remain unverified until a person reviews and approves them.

## What is usable now

- Account-generation, cross-tab session revocation, CSRF, tenant, API-key, and rate-limit boundaries
- Validated PNG, JPEG, WebP, and PDF uploads with page selection and crop support
- Persistent `queued → running → review → approved` jobs with fenced worker leases, bounded restart recovery, pre-dispatch refunds, capacity reservations, reference-aware source deletion, and a retryable deletion outbox
- Non-destructive reprocessing that restores the last reviewed or approved result when a new attempt fails or is cancelled
- Side-by-side source review, a bounded paged editor for maximum-size results, version history, and an audit trail
- JSON, CSV, and XLSX exports; XLSX includes an audit sheet
- A tenant-idempotent programmatic upload/status API with credit, bandwidth, outstanding-upload, and storage quotas
- An isolated, ephemeral saved-sample workspace that runs without a GPU or external call
- An existing Modal inference adapter for the evaluated Qwen3-VL LoRA
- Optional Stripe **test-mode only** credit checkout with signed, idempotent webhooks

This repository is a production candidate, not a hosted production service. Launch blockers and owner actions are explicit in [`docs/LAUNCH_READINESS.md`](docs/LAUNCH_READINESS.md).

## Run the zero-cost demo

Python 3.11 is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.lock
python -m pip install --require-hashes -r requirements-build.lock
python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env
unrender-serve
```

Open `http://127.0.0.1:8000`, then choose **Open the reviewed sample**. Each sample visitor receives an isolated ephemeral tenant that can run only the bundled verification fixture and cannot create API keys, use billing, or upload arbitrary files. Replay performs no paid inference.

The same demo runs in a container:

```bash
docker compose up --build
```

## Production accounts and Render

See [`docs/RENDER_MODAL_LAUNCH.md`](docs/RENDER_MODAL_LAUNCH.md) for the Render + Modal
configuration, hosted verification, and remaining public-release gates. The invited
pilot is live at https://unrender.onrender.com. Public signup and email are off.
Enabling public signup later requires verified email and zero welcome credits;
password recovery revokes sessions and API keys while retaining saved work.

## Configure real extraction

The current production adapter calls the existing `modal_train.py::infer_one` deployment boundary. Set these values through your deployment secret manager:

```dotenv
UNRENDER_ENV=production
UNRENDER_BASE_URL=https://unrender.example.com
UNRENDER_DATA_DIR=/data/unrender
UNRENDER_EXTRACTOR=modal
UNRENDER_WORKER_ENABLED=true
UNRENDER_SEED_DEMO=false
UNRENDER_ALLOW_REGISTRATION=false
UNRENDER_MODAL_APP=unrender-production
UNRENDER_MODAL_FUNCTION=infer_one
UNRENDER_MODAL_MODEL=owner/approved-unrender-model
UNRENDER_MODAL_REVISION=<full 40-character model commit>
UNRENDER_MODAL_MODEL_DIGEST=<SHA-256 of the complete resolved model snapshot>
UNRENDER_MODAL_PROVIDER_RELEASE=<64-character approved provider release digest>
```

Production startup rejects HTTP base URLs, replay extraction, seeded demo accounts, public registration without verified email or with automatic credits, a disabled worker, local/mutable model paths, non-commit revisions, missing model-manifest verification, and an unapproved provider release. The production Modal function uses a dedicated inference-cache volume rather than the mutable research volume, loads a published private Modal release or the named Hub commit, verifies its complete read-only snapshot against the pinned digest, and measures reviewed source plus runtime package versions into the canaried release digest. `unrender-admin check-provider-contract` resolves the exact `unrender-production/infer_one` deployment without invoking billable inference. Provision invited accounts with `unrender-admin create-user analyst@example.com --credits 25`; its password prompts are not command-line arguments. Keep one application replica per SQLite data volume; the documented scale-up path is a managed database, object storage, and a dedicated queue worker.

## Product workflow

1. Upload a chart image or PDF and choose the page/crop.
2. Unrender reserves one chart credit and records a durable job.
3. The worker renders the selected source and calls the configured extractor.
4. The result enters review; it is never presented as verified automatically.
5. Corrections create immutable result versions.
6. Approval and exports are appended to the audit trail.
7. A cancellation/failure before provider dispatch returns its reserved credit exactly once. Once provider dispatch is durably recorded, the attempt consumes the credit even if the provider fails or cancellation arrives later; this prevents unbounded free paid inference.

The saved fixture costs zero credits because it makes no provider call.

## API

Create an API key in the workspace, then submit a chart:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/extractions?page_index=0" \
  -H "Authorization: Bearer $UNRENDER_API_KEY" \
  -H "Idempotency-Key: $(uuidgen)" \
  -F "file=@chart.png"
```

Every submission requires a tenant-scoped idempotency key. An exact retry inside the configured 720-hour default replay window returns the stored response without creating another job or reserving another credit; changed or expired keys return `409`. The expired response is compacted to a tombstone for another 365 days by default, after which the record may be removed, so clients must never recycle keys. Poll `GET /api/v1/extractions/{job_id}` with the same bearer key. Interactive schemas are intentionally disabled; the stable response, retention horizon, and error contracts are maintained in [`docs/API.md`](docs/API.md).

## Verify a change

```bash
ruff check unrender/product unrender/schema/chart_schema.py tests/test_product.py
mypy unrender/product
pytest -q
node --check unrender/product/static/app.js
python scripts/check_release_licenses.py
docker build -t unrender:local .
```

The product suite covers the complete saved-sample workflow, review/edit/approve/export behavior, visible/restorable result versions, tenant isolation, streamed-body and upload safety, tenant quotas, submission/refund idempotency, bounded restart recovery, API keys, and Stripe test events. The research/evaluation suite remains part of the default test run.

## Model evidence, stated narrowly

On the frozen 300-chart `common300` synthetic set, the current table LoRA scores 38.9% `cell@5_exact`, versus 13.5% for the pinned base model. It is at parity with the saved GPT-5.5 comparison on a small overlap and behind the saved Claude and Gemini comparisons. On eight public OWID charts it scores 67% versus 31% for the base, but that set has a contamination caveat and is too small for a launch claim.

Those values are research evidence, not a product accuracy guarantee. Receipts and caveats live in [`RESULTS.md`](RESULTS.md), [`RESULT_TO_CLAIM.md`](RESULT_TO_CLAIM.md), and [`MODEL_STATUS_REVIEW.md`](MODEL_STATUS_REVIEW.md).

The base Qwen/Unsloth model artifacts used by the research pipeline are published as Apache-2.0. The fine-tuned weights currently live on the owner's private Modal volume; publishing and independent license/provenance review remain owner gates.

## Repository map

| Path | Purpose |
|---|---|
| `unrender/product/` | Product web app, service layer, persistence, storage, worker, and extractor boundary |
| `unrender/schema/` | Strict chart data contract and exports |
| `unrender/data_gen/` | Deterministic synthetic chart generation |
| `unrender/eval/` | Providers, metrics, scoring, reports, and comparisons |
| `unrender/train/` | LoRA training workflow |
| `modal_train.py` | Modal generation, training, evaluation, and single-image inference functions |
| `tests/test_product.py` | Product workflow, security-boundary, durability, and billing regression tests |
| `docs/` | Product decision, architecture, operations, launch, legal, and security handoff |

## Documentation

- [`docs/PRODUCT_DECISION.md`](docs/PRODUCT_DECISION.md) — buyer, problem, positioning, pricing assumptions, and kill criteria
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — trust boundaries and job lifecycle
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — deploy, backup, restore, alerts, and incident steps
- [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) — controls, threats, and accepted limits
- [`docs/LAUNCH_READINESS.md`](docs/LAUNCH_READINESS.md) — evidence-backed gate checklist and owner blockers
- [`docs/REMEDIATION_EVIDENCE.md`](docs/REMEDIATION_EVIDENCE.md) — exact-review fixes, local gate results, and external release gates
- [`docs/LEGAL_REVIEW.md`](docs/LEGAL_REVIEW.md) — license/provenance inventory and counsel questions
- [`docs/LAUNCH_PLAN.md`](docs/LAUNCH_PLAN.md) — 30-day distribution and measurement plan

## License

The repository's own code is Apache-2.0; see [`LICENSE`](LICENSE). That does not determine the obligations of the combined product. The former PyMuPDF AGPL/commercial-license dependency has been removed from product code and locks; PDF handling now uses locked pypdfium2/PDFium, whose upstream permissive terms and shipped dependency notices are recorded in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). The checked-in CycloneDX inventory and machine policy validate that replacement. This engineering gate is not legal approval: public/commercial release remains blocked until the owner and qualified counsel approve the entity, privacy/terms, retention, subprocessors, support/refund terms, and intended distribution model in [`docs/LEGAL_REVIEW.md`](docs/LEGAL_REVIEW.md).
