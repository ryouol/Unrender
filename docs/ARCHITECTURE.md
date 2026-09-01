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
   │          ├── SQLite (WAL): users, jobs, versions, ledger, reservations, deletion outbox
   │          └── private 0700/0600 data volume: staging, uploads, and job sources
   ▼
Durable worker ─── page render/crop ─── extractor boundary
                                            │
                           saved fixture or Modal infer_one
```

The transport layer parses HTTP and owns cookies/headers. `ProductService` owns business invariants and is testable without HTTP. `Storage` owns file validation and paths. The worker claims jobs transactionally and normalizes provider failures. Extractors return the same typed `ChartData` contract.

## Data and trust boundaries

- Passwords use salted scrypt hashes. Session, CSRF, and API-key secrets are stored only as SHA-256 digests.
- Every job, upload, API key, and result lookup includes the authenticated `user_id`.
- Files are addressed with server-generated UUIDs under a configured storage root; original names are display metadata only.
- Upload type is derived from file content, not the client MIME header. Images are decoded and dimension-limited; PDFs are opened, password checked, and page-limited.
- The ASGI boundary counts streamed chunks without retaining a second body copy. Accepted multipart data is framework-spooled and copied once through a bounded reader; per-route concurrency ceilings protect upload/render work and password KDFs.
- Customer uploads require available credit and remain under per-tenant bandwidth, outstanding-upload, and total stored-byte limits. Durable cross-process reservations account for staging, upload publication, job copies, worst-case result expansion, pending deletion, database headroom, and minimum free space before bytes or spend are admitted. Result history has separate per-job version and per-tenant byte ceilings; list routes return metadata pages and load one selected body explicitly.
- Public API submissions reserve upload, job, and credit in one SQLite transaction. A tenant-scoped request hash makes `Idempotency-Key` retries replay the saved response and rejects changed or expired reuse. Full responses expire on a configured horizon, then compact tombstones preserve the expired outcome for a separately configured retention period; clients must not recycle keys after that documented period.
- Paid browser submissions also require a durable account/upload/page/crop-bound `Idempotency-Key`; ambiguous retries reuse it until the server confirms one outcome. State changes through the browser require a valid session and CSRF header. Cross-origin state changes are rejected.
- Sessions carry an account generation. `/api/me` exposes a generation-bound one-way principal marker; browser tabs coordinate through BroadcastChannel/storage and lifecycle reconciliation, wipe all private state before async work, and fence every response with auth and selection epochs. Sign out increments the generation and revokes all account sessions.
- Stripe events are applied only after signature verification and are idempotent by event ID. Configuration rejects live-mode secret keys.
- Each anonymous sample session is a distinct ephemeral demo tenant. Server-side capability checks permit only the exact saved fixture and deny arbitrary upload, API-key, and billing surfaces.

## Job lifecycle

```text
prepared upload
      │ reserve credit
      ▼
   queued ── cancel ─────────────► cancelled + refund
      │ owner/token/generation lease claim
      ▼
   running, not dispatched ──────► cancel/failure + refund
      │
      ├── durable provider dispatch (credit becomes spent)
      ├── cancel/failure ─────────► cancelled/failed, no refund
      ▼
   review ── corrections ────────► review (new version)
      │ approve
      ▼
  approved ── correction ────────► review
```

An active reservation and durable provider-dispatch bit are stored on the job. Refunds use an attempt-scoped idempotency key and are permitted only before dispatch. After dispatch, provider spend may have occurred, so failure, cancellation, or lease expiry consumes the credit and the attempt is never automatically redriven. A per-user/global recent-provider-failure circuit breaker stops new dispatches before spend and refunds those un-dispatched reservations.

Every execution has an owner, unpredictable token, monotonically increasing generation, heartbeat, and lease expiry. Progress, result-version insertion, terminal state, provider outcome, audit, and refund are committed only after an atomic identity/lease check. Startup and competing reapers recover only expired leases with compare-and-swap identity; one bounded pre-dispatch recovery is followed by a durable terminal state. A draining worker stops claiming, keeps heartbeating a synchronous provider call, and reports not-ready until that call finishes.

The exact saved fixture is the only zero-credit job. It is hash-matched and replayed from deterministic ground truth; it never calls a provider.

## Persistence and recovery

SQLite runs in WAL mode with foreign keys, a busy timeout, a cross-process migration lock, crash-atomic schema transactions, and short business transactions. Startup reconciliation is serialized, ignores files younger than its safety grace, rechecks ownership before deletion, and preserves live durable storage reservations. Each reservation has an opaque owner token and renewable expiry; final source publication must consume that exact live lease atomically. Source bytes and containing namespaces are fsynced before SQLite references. Sources are copied into job-owned storage before upload expiry. Sessions and prepared uploads expire independently; completed jobs follow the configured retention window. Job deletion removes the last-reference upload row in the same immediate transaction and queues both source paths; shared uploads remain. File removal is first committed to a deletion outbox, then holds the cross-process operational lock across its final reference check and removal. It is retried by housekeeping and supplemented by storage reconciliation so a transient volume failure does not erase the only deletion record or restore preview access.

Sessions, API credentials, jobs, uploads, result versions, audit detail, credit ledger, idempotency records, billing events, provider attempts, and total tenant/global database rows all pass through centralized transactional admission or retention bounds. Admission preserves reserved capacity for every refundable obligation plus mandatory terminal, audit, and refund rows. Old audit detail is aggregated into bounded job/account rollups. Jobs, keys, and audit detail use stable cursor pagination so an active credential cannot disappear behind a fixed first-page cap. The browser editor pages a maximum-contract result into at most 500 mounted cells rather than expanding every point into the DOM.

This topology is appropriate for a controlled single-node beta. Do not mount one SQLite database over multiple application hosts. Scale-out requires:

1. managed Postgres with migrations and connection pooling;
2. private object storage with scoped URLs and lifecycle policies;
3. a real queue with leases, retries, and dead-letter handling;
4. separate web and worker processes;
5. distributed rate limiting and structured metrics.

## Known architectural limits

- Provider calls themselves are not cancellable mid-request. Once dispatched they are at-most-once across automatic recovery: an ambiguous expired attempt is terminal and charged rather than silently redriven.
- Backups must use the coordinated admin command, which takes the database/file mutation lock and writes a hash manifest; restore validates inventory, hashes, SQLite integrity, foreign keys, and rewrites stored root paths into a new empty data directory.
- Every non-liveness request first consumes a bucket derived only from the ASGI client address. Successfully authenticated routes also consume a bucket derived from the durable database user ID; raw cookies, bearer values, and forwarded headers never choose an application bucket. All counters remain local to one database, and the selected trusted edge must supply the intended client address.
- The Modal adapter relies on deployment credentials outside this repository. Production accepts only an owner/model Hub repository, a full commit, and the matching complete-snapshot digest. The inference function uses exact direct package pins and returns a release digest covering reviewed provider/schema source, the extraction prompt, measured runtime packages, and model identity. The app rejects a handshake mismatch, but an immutable Modal deployment/image record and a real canary remain owner gates.
- There is no organization/team model, SSO, or per-role authorization yet.
