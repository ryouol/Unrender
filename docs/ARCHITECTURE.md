# Architecture

## Runtime shape

```text
Browser or API client
        │ session+CSRF / bearer key
        ▼
FastAPI transport ── security headers, origin check, limits
        │
        ▼
Product service ─── tenant checks, lifecycle, credits, audit
   │          │
   │          ├── SQLite (WAL): users, jobs, versions, ledger
   │          └── private data volume: uploads and job sources
   ▼
Durable worker ─── page render/crop ─── extractor boundary
                                            │
                           saved fixture or Modal infer-one
```

The transport layer parses HTTP and owns cookies/headers. `ProductService` owns business invariants and is testable without HTTP. `Storage` owns file validation and paths. The worker claims jobs transactionally and normalizes provider failures. Extractors return the same typed `ChartData` contract.

## Data and trust boundaries

- Passwords use salted scrypt hashes. Session, CSRF, and API-key secrets are stored only as SHA-256 digests.
- Every job, upload, API key, and result lookup includes the authenticated `user_id`.
- Files are addressed with server-generated UUIDs under a configured storage root; original names are display metadata only.
- Upload type is derived from file content, not the client MIME header. Images are decoded and dimension-limited; PDFs are opened, password checked, and page-limited.
- State changes through the browser require a valid session and CSRF header. Cross-origin state changes are rejected.
- Stripe events are applied only after signature verification and are idempotent by event ID. Configuration rejects live-mode secret keys.

## Job lifecycle

```text
prepared upload
      │ reserve credit
      ▼
   queued ── cancel ─────────────► cancelled + refund
      │ transactional claim
      ▼
   running ── cancel request ────► cancelled + refund
      │
      ├── normalized failure ────► failed + refund
      ▼
   review ── corrections ────────► review (new version)
      │ approve
      ▼
  approved ── correction ────────► review
```

An active reservation is stored on the job. Refunds use an attempt-scoped idempotency key, so retries cannot return the same credit twice. Startup moves interrupted `running` jobs back to `queued` without another charge. Reprocessing creates a new attempt and reservation.

The exact saved fixture is the only zero-credit job. It is hash-matched and replayed from deterministic ground truth; it never calls a provider.

## Persistence and recovery

SQLite runs in WAL mode with foreign keys, a busy timeout, explicit schema version, and short transactions. Sources are copied into job-owned storage before upload expiry. Sessions and prepared uploads expire independently; completed jobs follow the configured retention window.

This topology is appropriate for a controlled single-node beta. Do not mount one SQLite database over multiple application hosts. Scale-out requires:

1. managed Postgres with migrations and connection pooling;
2. private object storage with scoped URLs and lifecycle policies;
3. a real queue with leases, retries, and dead-letter handling;
4. separate web and worker processes;
5. distributed rate limiting and structured metrics.

## Known architectural limits

- The embedded worker is at-least-once around process interruption; provider calls themselves are not cancellable mid-request.
- SQLite backups and storage snapshots must be coordinated by the operator.
- Rate limits are IP-based and local to one database.
- The Modal adapter relies on deployment credentials outside this repository.
- There is no organization/team model, SSO, or per-role authorization yet.
