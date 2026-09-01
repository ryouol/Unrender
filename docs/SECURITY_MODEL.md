# Security model

## Protected assets

Customer chart sources, extracted values, corrections, exports, identities, session/API credentials, credit balances, audit history, Modal credentials, and Stripe test secrets are sensitive.

## Implemented controls

- salted scrypt password hashes;
- hashed session, CSRF, and API-key tokens;
- HttpOnly session cookies, SameSite=Lax, and Secure cookies in production;
- CSRF validation plus exact-origin checks for browser state changes;
- per-user ownership checks in every product resource query;
- server-generated storage paths and restrictive file permissions;
- content-derived upload validation, size/page/pixel limits, and normalized decoding;
- parameterized SQL, foreign keys, explicit transactions, and credit-ledger idempotency;
- strict host validation, production-disabled API schemas, and forbidden unexpected request fields;
- CSP, frame/resource isolation, MIME sniffing denial, referrer and permissions policies, and HSTS in production;
- safe provider errors without internal exception text;
- signed, idempotent Stripe webhooks, checkout-destination allowlisting, and a hard block on live secret keys;
- API keys that are hashed at rest, listed without hashes, and immediately revocable;
- CSV/XLSX formula neutralization while the JSON export preserves exact values;
- SHA-locked Python dependencies, commit-pinned CI actions, and an immutable Python base-image digest;
- no paid call in default replay/demo mode.
- production startup fails closed when public registration, demo seeding/replay, HTTP origins, or an unpinned model is configured.

## Abuse cases considered

- cross-tenant ID guessing;
- CSRF and cross-origin POSTs;
- malicious names and path traversal;
- spoofed file extensions/MIME headers;
- image decompression and oversized PDF abuse;
- job cancellation/failure refund duplication;
- worker crash and job replay;
- API-key disclosure and webhook replay;
- browser embedding and script injection;
- accidental production startup with demo/replay settings.

## Accepted limits for a controlled beta

- no MFA, SSO, organization roles, or session-management UI;
- no malware scanner or content-disarm service for PDFs;
- no per-account quota beyond credits and the IP rate limit;
- no distributed WAF/rate limiter;
- no formal penetration test, dependency SBOM attestation, SOC 2, or external compliance audit;
- application-level encryption at rest is not implemented; the platform volume must provide it;
- provider calls cannot be cancelled after the synchronous remote call begins;
- privacy/terms files are drafts, not legal advice.

## Required launch actions

Complete a container scan, restore test, abuse test with hostile image/PDF samples, session revocation workflow, structured security logging, and counsel-approved retention/incident language before accepting external customer data. The repository security review, runtime dependency audit, secret-pattern scan, and API-key revocation workflow are recorded in `docs/SECURITY_REVIEW.md`.
