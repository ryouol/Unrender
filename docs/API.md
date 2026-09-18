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
identity, attempt, status and approval timestamp. Restoring identical content
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
version, content hash and revision in its Audit sheet. A download is a snapshot,
not a promise that no later version exists. Complete source/model provenance and
unit preservation remain separate export-readiness work.

The interface keeps local edits on conflict and offers Load latest version. A
failed reload keeps them; replacing dirty edits requires an explicit discard
choice. It does not merge edits automatically. Browser tabs with the previous
request contract must reload after deployment.

No database migration is needed: revisions derive from existing immutable result
history, and an inconsistent current result fails closed with 503
`result_history_inconsistent`. This change cannot retroactively prove what someone
saw before an old approval. Historical approvals require a fresh review before they
can be presented as having passed this contract; do not relabel old audit receipts.
