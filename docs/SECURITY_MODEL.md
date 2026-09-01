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
- streamed request-body limits before framework parsing plus content-derived upload validation, size/page/pixel limits, and normalized decoding;
- per-tenant stored-byte, outstanding-upload, upload-bandwidth, result-history byte/version, and retained request-key quotas, with a credit precheck before customer persistence;
- parameterized SQL, foreign keys, explicit transactions, and credit-ledger idempotency;
- atomic public API upload/job/credit reservation and tenant-scoped request-hash idempotency with explicit replay and compact-tombstone retention horizons;
- an outer request limiter keyed only by the ASGI client address plus a post-authentication limiter keyed by durable user ID, never attacker-selected credential bytes;
- strict host validation, production-disabled API schemas, and forbidden unexpected request fields;
- CSP, frame/resource isolation, MIME sniffing denial, referrer and permissions policies, and HSTS in production;
- safe provider errors without internal exception text;
- signed, idempotent Stripe webhooks, checkout-destination allowlisting, and a hard block on live secret keys;
- API keys that are hashed at rest, listed without hashes, and immediately revocable;
- isolated ephemeral demo tenants whose server-side role permits only the exact saved fixture and denies customer data/key/billing capabilities;
- CSV/XLSX formula neutralization while the JSON export preserves exact values;
- SHA-locked runtime/dev/build dependencies, commit-pinned CI actions, and an immutable Python base-image digest;
- bounded worker recovery with dead-letter/refund behavior, retryable deletion outbox, and orphan-file reconciliation;
- privacy-safe provider lifecycle, latency, and error-code logs;
- no paid call in default replay/demo mode;
- production startup fails closed when public registration, demo seeding/replay, HTTP origins, a disabled worker, a mutable/non-digested model snapshot, or an unapproved provider release is configured; the provider release covers reviewed source, prompt, runtime packages, and model identity.

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
- tenant quotas and authenticated rate counters are local to one SQLite deployment, with no distributed WAF/rate limiter; client-IP attribution depends on a correctly configured trusted edge;
- no formal penetration test, dependency SBOM attestation, SOC 2, or external compliance audit;
- application-level encryption at rest is not implemented; the platform volume must provide it;
- provider calls cannot be cancelled after the synchronous remote call begins;
- privacy/terms files are drafts, not legal advice.

## Required launch actions

Complete a container scan, restore test, abuse test with hostile image/PDF samples, session revocation workflow, platform alert delivery, and counsel-approved retention/incident language before accepting external customer data. The repository security review, runtime dependency audit, secret-pattern scan, structured provider logs, and API-key revocation workflow are recorded in `docs/SECURITY_REVIEW.md`.
