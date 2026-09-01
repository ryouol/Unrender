# Operations runbook

## Deployment preflight

1. Build and scan the pinned container image.
2. Provide a persistent, encrypted `/data` volume owned by UID/GID `10001`.
3. Terminate TLS at the load balancer and set the exact public `UNRENDER_BASE_URL`.
4. Set `UNRENDER_ENV=production`, `UNRENDER_EXTRACTOR=modal`, `UNRENDER_WORKER_ENABLED=true`, `UNRENDER_SEED_DEMO=false`, and `UNRENDER_ALLOW_REGISTRATION=false`; production validation fails closed otherwise.
5. Configure an approved model repository, its full 40-character commit, the SHA-256 manifest of the complete resolved snapshot, and the canaried provider-release digest as `UNRENDER_MODAL_MODEL`, `UNRENDER_MODAL_REVISION`, `UNRENDER_MODAL_MODEL_DIGEST`, and `UNRENDER_MODAL_PROVIDER_RELEASE`. The exact deployment function name is `infer_one`. Production resolves only that Hub commit into the dedicated `unrender-inference-cache` volume (not the mutable research volume), descriptor-opens every path without following swapped directories/files, copies verified bytes into a private read-only content address, and rejects inference from a different reviewed-source/runtime release. Run `unrender-admin check-provider-contract` as a non-spending deployment-resolution canary, then record the immutable Modal deployment/image identity beside the real approved canary. The application handshake is a drift detector, not a substitute for platform attestation. Mount provider credentials through the platform secret manager.
6. Leave Stripe variables empty unless running an approved test-mode checkout. Live secret keys are rejected by configuration.
7. Start one application replica and verify `/health/live` and `/health/ready`.
8. Run one approved canary chart with non-sensitive data; confirm review, correction, approval, and all three exports.

Set the platform termination grace beyond the maximum provider call duration. On shutdown the worker stops claiming immediately and readiness turns false; if a dispatched provider call exceeds `UNRENDER_WORKER_SHUTDOWN_TIMEOUT_SECONDS`, the process logs the missed warning threshold but keeps heartbeating and waits for the fenced terminal commit. The platform must not send an earlier hard kill.

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

Use the coordinated admin command; do not combine an SQLite `.backup` with a later live `rsync`. The command takes an exclusive mutation lock, snapshots SQLite through its backup API, copies only committed upload/job objects, and writes a SHA-256 inventory before atomically publishing the recovery directory:

```bash
UNRENDER_DATA_DIR=/data unrender-admin backup \
  --destination /backup/unrender-2026-09-01T020000Z
```

The destination must not exist and must be outside `/data`. If any upload/job/database mutation is active—or any durable staging, upload-publication, or job-copy reservation remains—backup refuses immediately; drain writes or reconcile the interrupted publication and retry. Success is reported only after captured files, manifest, temporary tree, final tree, and their parent namespaces have been fsynced. Encrypt backups, restrict access, copy the completed directory as one unit, and alert on recovery-set age. A platform volume snapshot is acceptable only when the same mutation lock/drain contract is demonstrated.

Restore into a new absent data directory:

```bash
unrender-admin restore \
  --source /backup/unrender-2026-09-01T020000Z \
  --target /recovery/unrender-data
```

Restore rejects symbolic/special paths, extra/missing files, hash or size drift, an existing/nested target, SQLite integrity errors, and foreign-key violations. It rewrites stored absolute source paths from the captured root to the new root, fsyncs every restored file and namespace, and atomically publishes the target. Confirm the restored tree is owned by UID/GID `10001` with `0600` files and `0700` directories, start the required worker with ingress closed, wait for `/health/ready`, and sample job sources/exports. Never restore only the database or only the files, edit the manifest, or weaken production validation for a drill.

Target assumptions for beta: RPO 24 hours and RTO 4 hours. These are internal objectives, not a customer SLA.

## Incident procedures

### Provider outage

Pause new-submission ingress and communicate that extraction is delayed. In the current single-process topology, production cannot run the web process with its worker disabled; keeping review/export live during a provider outage requires the documented split web/worker scale-up. An attempt is refunded only when dispatch was never recorded. A dispatched provider failure consumes its credit; repeated recent failures open the pre-dispatch circuit so later attempts do not spend and are refunded. Resume submissions only after the non-spending contract check and an approved real canary return the expected deployment/release identity.

### Suspected credential leak

Rotate the affected Modal, Stripe, or deployment secret; revoke exposed API keys through the workspace key-management UI (or a reviewed database operation if the UI is unavailable); use **Sign out everywhere** to increment the account generation and invalidate every session if session material may be involved; preserve audit/log evidence; and assess customer notification obligations with counsel. Per-device session inventory and security-event notification are not part of the controlled pilot and remain broad-launch product work.

### Suspected chart-data exposure

Stop public traffic, snapshot evidence, identify affected tenant IDs and paths, rotate access credentials, and do not delete evidence until counsel/incident leadership approves. The privacy notice is a draft and must be finalized before customer data is accepted.

### Database or volume pressure

Pause uploads, let housekeeping drain the deletion outbox, expand the volume, and verify database integrity plus the storage reconciliation count. Admission includes configured global retained bytes, database headroom, pending deletions, cross-process storage/result reservations, and minimum free space, but these fail-closed controls do not replace platform capacity alerts. Do not delete job files manually because the database, outbox, and audit trail would diverge.

## Rollback

Deploy immutable image tags. Before a schema-changing release, create and verify a coordinated recovery set. This release uses schema version 8 with crash-atomic, cross-process-serialized forward migrations from versions 1–7 and no down migration. Version 6 added worker execution leases/fencing, provider-dispatch state, audit rollups, provider-attempt accounting, and startup coordination. Version 7 added account session generations, attempt-fenced result/retained-byte reservations, and durable staging/upload/job-copy reservations. Version 8 gives every storage reservation an opaque owner token: resize renews only that live lease, publication must atomically consume the matching unexpired reservation, and deletion holds the exclusive operational lock through reference check and file removal. Roll back application code only when it supports the on-disk schema; otherwise restore the coordinated recovery set into a new volume.
