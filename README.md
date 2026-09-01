# Unrender

Unrender is a review-first workspace for turning chart images and PDF pages into structured data. It keeps the source beside an editable table, records every correction, and exports JSON, CSV, or XLSX with model and approval metadata.

The product is designed for research and consulting teams that need chart data they can inspect and defend. It does **not** promise automatic accuracy: extraction results remain unverified until a person reviews and approves them.

## What is usable now

- Account, session, CSRF, tenant, API-key, and rate-limit boundaries
- Validated PNG, JPEG, WebP, and PDF uploads with page selection and crop support
- Persistent `queued → running → review → approved` jobs with restart recovery, cancellation, failure refunds, and retention cleanup
- Side-by-side source review, editable values, version history, and an audit trail
- JSON, CSV, and XLSX exports; XLSX includes an audit sheet
- A programmatic upload/status API
- An exact saved sample that runs without a GPU or external call
- An existing Modal inference adapter for the evaluated Qwen3-VL LoRA
- Optional Stripe **test-mode only** credit checkout with signed, idempotent webhooks

This repository is a production candidate, not a hosted production service. Launch blockers and owner actions are explicit in [`docs/LAUNCH_READINESS.md`](docs/LAUNCH_READINESS.md).

## Run the zero-cost demo

Python 3.11 is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
unrender-serve
```

Open `http://127.0.0.1:8000`, then choose **Open the reviewed sample**. Replay mode accepts only the bundled verification fixture and performs no paid inference. A different upload fails safely and returns its reserved credit.

The same demo runs in a container:

```bash
docker compose up --build
```

## Configure real extraction

The current production adapter calls the existing `modal_train.py::infer_one` deployment boundary. Set these values through your deployment secret manager:

```dotenv
UNRENDER_ENV=production
UNRENDER_BASE_URL=https://unrender.example.com
UNRENDER_DATA_DIR=/data
UNRENDER_EXTRACTOR=modal
UNRENDER_SEED_DEMO=false
UNRENDER_ALLOW_REGISTRATION=false
UNRENDER_MODAL_APP=unrender
UNRENDER_MODAL_FUNCTION=infer-one
UNRENDER_MODAL_MODEL=owner/approved-unrender-model
UNRENDER_MODAL_REVISION=<full 40-character model commit>
```

Production startup rejects HTTP base URLs, replay extraction, seeded demo accounts, public registration, local/mutable model paths, and non-commit revisions. Provision invited accounts with `unrender-admin create-user analyst@example.com --credits 25`; its password prompts are not command-line arguments. Keep one application replica per SQLite data volume; the documented scale-up path is a managed database, object storage, and a dedicated queue worker.

## Product workflow

1. Upload a chart image or PDF and choose the page/crop.
2. Unrender reserves one chart credit and records a durable job.
3. The worker renders the selected source and calls the configured extractor.
4. The result enters review; it is never presented as verified automatically.
5. Corrections create immutable result versions.
6. Approval and exports are appended to the audit trail.
7. A failed or cancelled extraction returns its reserved credit exactly once.

The saved fixture costs zero credits because it makes no provider call.

## API

Create an API key in the workspace, then submit a chart:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/extractions \
  -H "Authorization: Bearer $UNRENDER_API_KEY" \
  -F "file=@chart.png" \
  -F "page_index=0"
```

Poll `GET /api/v1/extractions/{job_id}` with the same bearer key. Interactive API documentation is available at `/api/docs` outside production. The stable response and error contracts are documented in [`docs/API.md`](docs/API.md).

## Verify a change

```bash
ruff check unrender/product unrender/schema/chart_schema.py tests/test_product.py
mypy unrender/product
pytest -q
node --check unrender/product/static/app.js
docker build -t unrender:local .
```

The product suite covers the complete saved-sample workflow, review/edit/approve/export behavior, tenant isolation, request protections, upload safety, refund idempotency, restart recovery, API keys, and Stripe test events. The research/evaluation suite remains part of the default test run.

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
- [`docs/LEGAL_REVIEW.md`](docs/LEGAL_REVIEW.md) — license/provenance inventory and counsel questions
- [`docs/LAUNCH_PLAN.md`](docs/LAUNCH_PLAN.md) — 30-day distribution and measurement plan

## License

The code in this repository is Apache-2.0; see [`LICENSE`](LICENSE). Bundled IBM Plex Sans font files are covered by the included SIL Open Font License. Model weights, source charts, and third-party datasets retain their own terms; review [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) before distribution.
