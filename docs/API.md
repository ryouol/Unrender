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

`page_index` is a zero-based query parameter and defaults to `0`. An exact retry with the same account, key, filename, page, and bytes returns the stored `202` response without another upload, job, or credit reservation. Reusing a key for a different request returns `idempotency_conflict`.

Successful response: `202 Accepted` with the job representation.

Submissions fail before persistence when the account has no credit or when its byte, outstanding-upload, storage, or request quota is exhausted. Default tenant limits are documented in `.env.example` and may be reduced by an operator.

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
- `409` invalid lifecycle transition, idempotency conflict, or same-key request already in progress;
- `413` streamed body or tenant storage limit exceeded;
- `422` invalid upload or result contract;
- `429` request, upload-bandwidth, or outstanding-upload quota reached;
- `503` provider or optional billing unavailable.

## Compatibility policy

The `/api/v1` upload/status surface is additive within v1. Removing or changing a field's meaning requires `/api/v2`. Browser-internal `/api/*` endpoints are not a public compatibility contract yet.
