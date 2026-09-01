# Operations runbook

## Deployment preflight

1. Build and scan the pinned container image.
2. Provide a persistent, encrypted `/data` volume owned by UID/GID `10001`.
3. Terminate TLS at the load balancer and set the exact public `UNRENDER_BASE_URL`.
4. Set `UNRENDER_ENV=production`, `UNRENDER_EXTRACTOR=modal`, `UNRENDER_WORKER_ENABLED=true`, `UNRENDER_SEED_DEMO=false`, and `UNRENDER_ALLOW_REGISTRATION=false`; production validation fails closed otherwise.
5. Configure an approved model repository, its full 40-character commit, the SHA-256 manifest of the complete resolved snapshot, and the canaried provider-release digest as `UNRENDER_MODAL_MODEL`, `UNRENDER_MODAL_REVISION`, `UNRENDER_MODAL_MODEL_DIGEST`, and `UNRENDER_MODAL_PROVIDER_RELEASE`. Production resolves only that Hub commit into the dedicated `unrender-inference-cache` volume (not the mutable research volume), rejects writable/escaping snapshot files, verifies every model byte, and rejects inference from a different reviewed-source/runtime release. Record the immutable Modal deployment/image identity beside the canary; the application handshake is a drift detector, not a substitute for platform attestation. Mount provider credentials through the platform secret manager.
6. Leave Stripe variables empty unless running an approved test-mode checkout. Live secret keys are rejected by configuration.
7. Start one application replica and verify `/health/live` and `/health/ready`.
8. Run one approved canary chart with non-sensitive data; confirm review, correction, approval, and all three exports.

The Dockerfile pins Python 3.11.16 slim-trixie by immutable multi-architecture manifest digest. Dependency upgrades must deliberately update both the readable tag and digest, then rerun the image build and scanner in CI.

`/health/live` proves the process responds. `/health/ready` verifies the database schema, a write/delete probe on the private volume, and the embedded worker thread. The readiness route is covered by the client-IP admission bucket and should also be private to the platform health network; `/health/live` stays cheap and unmetered. The container probe supplies the configured public Host header so production TrustedHost policy remains intact. Neither health route spends money or calls the external inference provider.

Provision controlled-beta accounts from a trusted one-off operator shell attached to the same encrypted `/data` volume. The password is prompted without echo and is never accepted as a command-line argument; the command does not start a worker or recover running jobs:

```bash
unrender-admin create-user analyst@example.com --credits 25
```

Do not expose this command through the web service or run it in a shared shell transcript.

## Logs and alerts

The application emits server logs plus privacy-safe structured job/provider lifecycle records to stdout. Provider records include an opaque job UUID, event/error code, provider name on success, and elapsed milliseconds; they exclude filenames, chart data, raw model output, tenant identity, cookies, and credentials. The deployment platform must capture these records and derive metrics without adding sensitive request fields.

Alert on:

- readiness failing for two consecutive checks;
- queue age over five minutes;
- job failure rate over 10% in 15 minutes;
- refund ledger mismatch or negative-balance invariant failure;
- storage over 80% capacity;
- repeated origin, CSRF, API-key, or webhook-signature failures;
- provider latency/error increase;
- backup age over 24 hours.

Provider success/failure and latency can be derived from the structured lifecycle records. Queue-age, ledger reconciliation, capacity, and backup-age dashboards still require platform queries/exporters and remain owner blockers.

## Backup and restore

Back up both the SQLite database and storage tree as one recovery set.

For a consistent SQLite backup while the app is live:

```bash
sqlite3 /data/unrender.sqlite3 ".backup '/backup/unrender.sqlite3'"
rsync -a --delete /data/storage/ /backup/storage/
```

Prefer a volume snapshot after briefly draining new uploads. Encrypt backups, restrict access, and test restore monthly.

Restore into a new empty volume and preserve file paths relative to `/data`. Before exposing the volume to the app, run `PRAGMA integrity_check`, confirm database and source files are owned by UID/GID `10001` with `0600` files and `0700` directories, and compare a sample of stored paths to the restored tree. Then start the production configuration with its required worker, keep ingress closed until `/health/ready` passes, and sample several job sources/exports. Never restore only the database or only the files, and do not weaken production validation to perform a restore drill.

Target assumptions for beta: RPO 24 hours and RTO 4 hours. These are internal objectives, not a customer SLA.

## Incident procedures

### Provider outage

Pause new-submission ingress and communicate that extraction is delayed. In the current single-process topology, production cannot run the web process with its worker disabled; keeping review/export live during a provider outage requires the documented split web/worker scale-up. Normalized provider failures return reserved credits. Resume submissions only after a provider canary returns the approved release digest.

### Suspected credential leak

Rotate the affected Modal, Stripe, or deployment secret; revoke exposed API keys through the workspace key-management UI (or a reviewed database operation if the UI is unavailable); invalidate sessions if session material may be involved; preserve audit/log evidence; and assess customer notification obligations with counsel.

### Suspected chart-data exposure

Stop public traffic, snapshot evidence, identify affected tenant IDs and paths, rotate access credentials, and do not delete evidence until counsel/incident leadership approves. The privacy notice is a draft and must be finalized before customer data is accepted.

### Database or volume pressure

Pause uploads, let housekeeping drain the deletion outbox, expand the volume, and verify database integrity plus the storage reconciliation count. Tenant storage and bandwidth quotas limit one account, but they do not replace platform capacity alerts. Do not delete job files manually because the database, outbox, and audit trail would diverge.

## Rollback

Deploy immutable image tags. Before a schema-changing release, snapshot `/data`. This release uses schema version 5 with forward migrations from versions 1–4 and no down migration. Version 5 adds bounded idempotency response/tombstone state. Roll back application code only when it still supports the on-disk schema; otherwise restore the coordinated snapshot.
