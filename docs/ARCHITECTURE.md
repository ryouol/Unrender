# Architecture

## Runtime shape

```text
Browser or API client
        │ session+CSRF / bearer key
        ▼
FastAPI transport ── security headers, origin check, streamed-body limits
        │
        ▼
Product service ─── tenant checks, lifecycle, credits, audit
   │          │
   │          ├── SQLite (WAL): users, jobs, versions, ledger, idempotency, deletion outbox
   │          └── private 0700/0600 data volume: uploads and job sources
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
- The ASGI boundary buffers only a configured maximum, so chunked bodies are rejected before JSON parsing or multipart spooling can exceed the route limit.
- Customer uploads require available credit and remain under per-tenant bandwidth, outstanding-upload, and total stored-byte limits. Job copies count toward stored bytes.
- Public API submissions reserve upload, job, and credit in one SQLite transaction. A tenant-scoped request hash makes `Idempotency-Key` retries replay the saved response and rejects key reuse with different input.
- State changes through the browser require a valid session and CSRF header. Cross-origin state changes are rejected.
- Stripe events are applied only after signature verification and are idempotent by event ID. Configuration rejects live-mode secret keys.
- Each anonymous sample session is a distinct ephemeral demo tenant. Server-side capability checks permit only the exact saved fixture and deny arbitrary upload, API-key, and billing surfaces.

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

An active reservation is stored on the job. Refunds use an attempt-scoped idempotency key, so retries cannot return the same credit twice. Startup requeues an interrupted `running` job at most the configured number of times (one by default); exhaustion dead-letters the attempt, returns its credit, and retains any prior reviewed result. Reprocessing creates a new attempt and reservation while retaining the last review/approval as a fallback. A successful new extraction returns to `review`; a failed or cancelled attempt refunds the reservation and restores the preserved result state.

The exact saved fixture is the only zero-credit job. It is hash-matched and replayed from deterministic ground truth; it never calls a provider.

## Persistence and recovery

SQLite runs in WAL mode with foreign keys, a busy timeout, explicit sequential migrations, and short transactions. Sources are copied into job-owned storage before upload expiry. Sessions and prepared uploads expire independently; completed jobs follow the configured retention window. File removal is first committed to a deletion outbox, retried by housekeeping, and supplemented by storage reconciliation so a transient volume failure does not erase the only deletion record.

This topology is appropriate for a controlled single-node beta. Do not mount one SQLite database over multiple application hosts. Scale-out requires:

1. managed Postgres with migrations and connection pooling;
2. private object storage with scoped URLs and lifecycle policies;
3. a real queue with leases, retries, and dead-letter handling;
4. separate web and worker processes;
5. distributed rate limiting and structured metrics.

## Known architectural limits

- The embedded worker is at-least-once around process interruption; provider calls themselves are not cancellable mid-request.
- SQLite backups and storage snapshots must be coordinated by the operator.
- Rate limits are credential/session scoped for authenticated traffic and IP scoped before authentication; all counters remain local to one database.
- The Modal adapter relies on deployment credentials outside this repository. Production also requires an approved provider-release digest and rejects a runtime handshake mismatch, but the owner must still run a real canary before launch.
- There is no organization/team model, SSO, or per-role authorization yet.
