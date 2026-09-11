# Security model

## Protected assets

Customer chart sources, extracted values, corrections, exports, identities, session/API credentials, credit balances, audit history, Modal credentials, and Stripe test secrets are sensitive.

## Implemented controls

- versioned salted scrypt password hashes at an OWASP-listed work factor, with transparent legacy rehash after successful login;
- hashed session, CSRF, and API-key tokens;
- HttpOnly session cookies, SameSite=Lax, and Secure cookies in production;
- CSRF validation plus exact-origin checks for browser state changes;
- per-user ownership checks in every product resource query;
- server-generated storage paths, process umask `077`, `0700` data directories, and `0600` database/source files;
- streamed request-body limits before framework parsing without a second retained body copy, route-specific expensive-work/KDF concurrency ceilings, plus content-derived upload validation, size/page/pixel limits, finite-number validation, and normalized decoding; PDFium native calls are serialized because its library contract is not thread-safe;
- per-tenant stored-byte, outstanding-upload, upload-bandwidth, job/upload/session/key/audit/ledger/result-history/request-key/database-row quotas and a global database-state ceiling, with a credit precheck before customer persistence;
- parameterized SQL, foreign keys, explicit transactions, and credit-ledger idempotency;
- atomic public API upload/job/credit reservation and tenant-scoped request-hash idempotency with explicit replay and compact-tombstone retention horizons;
- an outer request limiter keyed only by the ASGI client address plus a post-authentication limiter keyed by durable user ID, never attacker-selected credential bytes;
- strict host validation, production-disabled API schemas, and forbidden unexpected request fields;
- CSP, frame/resource isolation, MIME sniffing denial, referrer and permissions policies, and HSTS in production;
- safe provider errors without internal exception text;
- signed, idempotent Stripe webhooks, checkout-destination allowlisting, and a hard block on live secret keys;
- API keys that are hashed at rest, cursor-paginated without hashes, capped while active/retained, immediately revocable, and revocable all at once;
- isolated ephemeral demo tenants whose server-side role permits only the exact saved fixture and denies customer data/key/billing capabilities;
- CSV/XLSX formula neutralization while the JSON export preserves exact values;
- SHA-locked runtime/dev/build dependencies, commit-pinned CI actions, and an immutable Python base-image digest;
- owner/token/generation worker leases with heartbeat, expiry-only compare-and-swap recovery, fencing across progress/result/terminal/provider/audit/refund mutations, pre-dispatch-only refunds, per-job provider-attempt retention, a provider-failure circuit, retryable deletion outbox, and age-graced/rechecked orphan reconciliation;
- cross-process serialized, crash-atomic migrations plus coordinated mutation-locked/hash-inventoried backup and verified restore tooling;
- privacy-safe provider lifecycle, latency, and error-code logs;
- no paid call in default replay/demo mode;
- production startup fails closed when public registration grants automatic credits, password-only public registration has SMTP/billing configured, demo seeding/replay, HTTP origins, a disabled worker, a mutable/non-digested model snapshot, or an unapproved provider release is configured; the provider release covers reviewed source, prompt, runtime packages, and model identity.

## Abuse cases considered

- cross-tenant ID guessing;
- CSRF and cross-origin POSTs;
- malicious names and path traversal;
- spoofed file extensions/MIME headers;
- image decompression and oversized PDF abuse;
- job cancellation/failure refund duplication;
- worker crash and job replay;
- response-loss retries and zero-credit storage exhaustion;
- credential/header rotation against admission controls and oversized result-history responses;
- API-key disclosure and webhook replay;
- browser embedding and script injection;
- accidental production startup with demo/replay settings.

## Accepted limits for a controlled beta

- no MFA, SSO, organization roles, or session-management UI;
- no malware scanner or content-disarm service for PDFs;
- global capacity and tenant/account rate counters are local to one SQLite deployment, with no distributed WAF/rate limiter; forwarded client addresses are not trusted or used for admission. Global exhaustion can affect everyone, and short account throttles can be deliberately exhausted; see REQUEST_LIMITS.md;
- no formal penetration test, signed SBOM attestation, SOC 2, or external compliance audit; the checked-in CycloneDX inventory is unsigned;
- the PyMuPDF runtime was removed and replaced by hash-locked pypdfium2/PDFium with recorded upstream terms and shipped notices; final dependency/distribution approval remains an owner/counsel responsibility;
- application-level encryption at rest is not implemented; the platform volume must provide it;
- provider calls cannot be cancelled after the synchronous remote call begins;
- privacy/terms files are drafts, not legal advice.

## Required launch actions

Complete a container scan, production-volume coordinated restore drill, abuse test with hostile image/PDF samples, session revocation workflow, platform alert delivery, final dependency-notice review, and counsel-approved retention/incident language before accepting external customer data or distributing commercially. The repository security review, runtime dependency audit, CycloneDX inventory/policy gate, secret-pattern scan, structured provider logs, and API-key revocation workflow are recorded in `docs/SECURITY_REVIEW.md`.
