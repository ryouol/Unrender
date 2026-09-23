# API contract

## Authentication

Create an API key from the workspace. Send it as `Authorization: Bearer unr_…`. The full secret is shown once and only its digest is stored.

## Submit an extraction

`POST /api/v1/extractions?page_index=0`

Required headers:

- `Authorization: Bearer unr_…`;
- `Idempotency-Key` — 8–128 letters, numbers, `.`, `_`, `:`, or `-`, unique per logical submission.

Multipart body:

- `file` — PNG, JPEG, WebP, or PDF, required.

`page_index` is a zero-based query parameter and defaults to `0`. An exact retry with the same account, key, filename, page, and bytes returns the stored `202` response without another upload, job, or credit reservation during `UNRENDER_IDEMPOTENCY_TTL_HOURS` (720 hours by default). Reusing a live key for different input returns `idempotency_conflict`.

After the replay window, the key returns `idempotency_key_expired` and its response body is removed. That compact tombstone is retained for `UNRENDER_IDEMPOTENCY_TOMBSTONE_DAYS` (365 days by default), after which housekeeping may delete it. Clients must generate a new random key for each new logical request and must never recycle old keys; the server deliberately does not promise replay or duplicate detection after the documented tombstone horizon.

Successful response: `202 Accepted` with the job representation.

Submissions fail before persistence when the account has no credit or when its byte, outstanding-upload, storage, or request quota is exhausted. Default tenant limits are documented in `.env.example` and may be reduced by an operator.

One credit is reserved per attempt. Cancellation or failure before durable provider dispatch returns that reservation once. After dispatch, provider spend may have occurred, so a failure/cancellation consumes the credit and is not automatically redriven. Repeated recent provider failures open a circuit before dispatch; those blocked attempts are refunded because no call was made.

## Read an extraction

`GET /api/v1/extractions/{job_id}`

Returns only jobs owned by the API-key account. Unknown and cross-tenant IDs both return `job_not_found`.

Important fields:

```json
{
  "id": "uuid",
  "status": "queued | running | review | approved | failed | cancelled",
  "progress_stage": "human-readable stage",
  "attempt": 1,
  "extractor": "modal | saved-replay | null",
  "model_version": "string | null",
  "result": {},
  "original_result": {},
  "error": {"code": "string", "message": "safe message"}
}
```

`result` is extracted data, not verified data. Approval is currently an interactive workspace action. Clients must not treat `review` as an accuracy guarantee.

## Errors

All application errors use:

```json
{"error": {"code": "stable_machine_code", "message": "safe human message"}}
```

Relevant status codes:

- `400` invalid page/crop or signature;
- `401` missing/invalid authentication;
- `402` no chart credits;
- `403` CSRF/origin/registration policy;
- `404` tenant-scoped resource not found;
- `409` invalid lifecycle transition, idempotency conflict/expiry, or same-key request already in progress;
- `413` streamed body, tenant source storage, or result-history storage limit exceeded;
- `422` invalid upload or result contract;
- `429` request, upload-bandwidth, outstanding-upload, retained-version, or request-key quota reached;
- `503` provider/circuit/concurrent-work capacity or optional billing unavailable.

## Compatibility policy

The `/api/v1` upload/status surface is additive within v1. Removing or changing a field's meaning requires `/api/v2`. Browser-internal `/api/*` endpoints are not a public compatibility contract yet. Browser jobs, audit detail, and API-key inventories return bounded stable-cursor pages; result-history lists return bounded metadata pages and fetch one selected version body at a time. Each retained collection also has a configured count/byte/state ceiling. OpenAPI/Swagger endpoints are intentionally disabled on every environment; this file is the maintained public contract.


## Browser review concurrency contract

`GET /api/jobs/{id}` returns `result_version`, `result_sha256`, and an opaque
`review_revision` with the result. They are null until a result exists. The digest
is SHA-256 of the immutable stored `chart_json` UTF-8 bytes, not the pretty-printed
JSON export or workbook bytes. The revision also binds the job, immutable version
identity, extraction-receipt digest, attempt, status and approval timestamp. Restoring identical content
creates a new version and never revives an old revision.

The browser must send the revision from the **displayed** snapshot:

| Action | Request |
|---|---|
| Save corrections | `PATCH /api/jobs/{id}/result`, body `{result, expected_revision}` |
| Approve | `POST /api/jobs/{id}/approve`, body `{expected_revision}` |
| Restore | `POST /api/jobs/{id}/restore`, body `{version, expected_revision}` |
| Export | `GET /api/jobs/{id}/export/{format}?expected_revision=…` |

Revisions are required 64-character lowercase hexadecimal strings. Missing or
malformed request revisions receive 422. An outdated revision receives 409 with
`error.code = result_conflict`; it performs no correction, approval, restoration,
or export audit write. Ownership is checked before reading the result identity.
There is no unconditional-write endpoint or force-overwrite option.

Saves, restores and approvals check and mutate inside one immediate transaction.
Their responses contain their own committed snapshot, not a subsequent fetch that
could return another writer's result. Save & approve passes the revision returned
by save to approval; an intervening edit causes a conflict. If a mutation response
is lost, reload and review the current state before retrying. Repeating an old
revision cannot add another result version or approval event.

Restoration copies the requested immutable version on the server, creates a new
correction, clears approval, and records `restored_from_version`. Retained correction,
approval and export events include the exact version, content hash and review
revision. Audit retention/rollup limits still apply; this is not a permanent ledger.

Export captures the checked result and review status in one database snapshot,
then renders those captured bytes. A later edit cannot change that download or
its audit reference. Downloads expose `X-Unrender-Review-Revision`; XLSX includes
version, content hash and revision in its Audit sheet. All formats now carry the
[export manifest](#export-and-extraction-evidence-contract). A download is a
snapshot, not a promise that no later version exists.

The interface keeps local edits on conflict and offers Load latest version. A
failed reload keeps them; replacing dirty edits requires an explicit discard
choice. It does not merge edits automatically. Browser tabs with the previous
request contract must reload after deployment.

Revisions derive from immutable result history. Schema 15 additionally stores
per-version extraction receipts; the forward upgrade is described below. An
inconsistent current result or invalid receipt fails closed with 503
`result_history_inconsistent`. This change cannot retroactively prove what someone
saw before an old approval. Historical approvals require a fresh review before they
can be presented as having passed this contract; do not relabel old audit receipts.


## Export and extraction evidence contract

The current readiness branch uses one format, `unrender-export-v1`. This changes
browser-internal downloads; it does not wrap the public `/api/v1` job's `result`
field. Deploy the browser/server together and update download consumers.

- **JSON:** `{ "chart": <ChartData>, "provenance": <manifest> }`. Chart data is no
  longer the root object. The complete typed table remains under `chart`.
- **CSV:** the ordinary data columns, followed by `export_metadata_json`. There is
  exactly one nonempty manifest cell, on the first data record; subsequent records
  leave it empty. Every record has the same column count. Treat that cell as
  metadata for the whole file, not for one point. If sorting or filtering the CSV,
  preserve it separately; deleting that record discards the embedded manifest.
- **XLSX:** `Extracted data` has numeric cells; `Audit` has readable review/source
  fields and the identical manifest in `Export metadata JSON`.

CSV/XLSX axis headings include recorded units in brackets. The manifest also
preserves both axis labels and unit strings exactly. Exports never multiply or
divide values, normalize percentages, or guess a scale from a unit string.
`values_rescaled_on_export` is false. The chart contract still uses finite
binary-float numbers and has no independent verified scale field; neither exact
arbitrary-precision transcription nor correct model interpretation of scales is
claimed. Spreadsheet text cells remain escaped against formula injection.

Every manifest includes the job ID, original source name/SHA-256, zero-based PDF
page index (0 for images), normalized crop or null, immutable result version/hash,
review revision, approval state/time, axes, extraction receipt/hash, warnings, and
an accuracy notice. `result_sha256` hashes the stored compact ChartData JSON, not
the download bytes. `extraction_receipt_sha256` hashes the stored compact receipt's
UTF-8 bytes (`ExtractionReceipt.encode()`), not pretty-printed export metadata.
These identify snapshots; they are not signatures or an external tamper-proof log.

`GET /api/jobs/{id}` and its public status counterpart additionally return
`extraction_receipt`, `extraction_receipt_sha256`, and `extraction_warnings`.
Selected historical version bodies include the receipt and its hash. Version list
`byte_size` now includes both the chart and its receipt. Correction copies the
current receipt exactly; restore copies the selected historical receipt exactly;
reprocess creates fresh evidence. Changing human-edited units or values does not
erase the original extraction's warning. Current result model metadata follows
the selected version, including after a restore or failed reprocess.

`extraction-receipt-v1` records:

- `capture`: recorded now or historical details unavailable;
- `origin`: model, deterministic reference fixture, or unavailable;
- original dispatch attempt/execution generation, capture timestamp and measured
  provider round-trip milliseconds (includes transport; **not GPU kernel time**);
- extractor/model reference; source hash, page/crop, and the exact PNG bytes handed
  to the provider, **before its vision processor**;
- full raw-response hash/byte count, retained raw hash, and truncation flag;
- parsing status/version, verified EOS and output/cap token counts when available;
- configured model repository/revision/digest, matched provider release, and local
  prompt/schema identities. The approved production provider release binds these
  source files; prompt/schema hashes are local contract identities, not separately
  measured model internals. Development mocks are not production attestations.

Receipts are bounded to 8 KiB and charged to both per-user history and retained
storage limits. Dispatch reserves this overhead before billable work. Only the
latest successful raw response is retained on the job, possibly shortened; older
version receipts retain hashes and diagnostics, **not** a raw-output archive.
Standard job/account deletion and retention still remove their receipts.

Schema 14 → 15 is an atomic forward upgrade. Existing charts/versions remain;
older receipts explicitly say `historical_unavailable`. The upgrade does not
reconstruct parser/EOS/model evidence from today's configuration or copy the job's
latest model onto every historical version. Prior approvals still require fresh
review before claiming the new review guarantee. Drain workers and take a
coordinated recovery set before rollout. Old in-flight reservations do not cover
the new metadata allowance and fail closed before dispatch; do not silently
increase their allowance. Downgrade requires the matching pre-upgrade recovery
set in a fresh data directory, not old code on schema 15.

## September 2026 library and credential controls

The session-only `GET /api/library` returns at most 24 metadata rows, `page`, `total`,
and whole-workspace status `counts`. Query parameters are zero-based `page`, literal
`search` (maximum 120 characters), `project`, and `status` (`all`, `review`, `approved`,
`failed`, `queued`, or `running`). Search is literal, not a SQL wildcard expression.
The existing cursor-based `/api/jobs` contract remains available to integrations.

`POST /api/keys` additionally accepts `scope` (`read` or `extract`) and
`expires_in_days` (1–365, default 90). `read` permits retrieval of existing API
extractions; `extract` also permits submissions that use credits. Existing keys
retain their authority and have no expiry until rotated/revoked. New keys return
`scope` and `expires_at`; key listings expose these fields and never the secret.
Expired keys return 401; a read-only key used for submission returns 403.
