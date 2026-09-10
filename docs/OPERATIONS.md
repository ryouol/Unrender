# Operations runbook

## Deployment preflight

1. Build and scan the pinned container image.
2. Provide a persistent, encrypted volume at `/data`. On Render, set `UNRENDER_DATA_DIR=/data/unrender`; the app creates and owns this private 0700 subdirectory as UID 10001. The mount root and supplemental group are platform-managed.
3. Terminate TLS at the load balancer. Render supplies the exact HTTPS origin through `RENDER_EXTERNAL_URL`; use `UNRENDER_BASE_URL` only for a verified custom origin.
4. Set `UNRENDER_ENV=production`, `UNRENDER_EXTRACTOR=modal`, `UNRENDER_WORKER_ENABLED=true`, `UNRENDER_SEED_DEMO=false`, and `UNRENDER_ALLOW_REGISTRATION=false`; production validation fails closed otherwise.
5. Pin the approved model bytes and canaried provider-release digest. The deployed private Modal volume release uses `UNRENDER_MODAL_MODEL=modal-volume/unrender-inference-cache` and the identical full SHA-256 for revision and model digest. The alternative Hub path requires a full 40-character commit plus the complete snapshot SHA-256. Both paths verify immutable release contents. Current pins and the explicit `modal_train.py::production_app` deployment command are in [RENDER_MODAL_LAUNCH.md](RENDER_MODAL_LAUNCH.md). Run `unrender-admin check-provider-contract` as a non-spending resolution canary, then verify real inference. The application handshake detects drift; it does not replace platform attestation. Store provider credentials in platform secret management.
6. Leave Stripe variables empty unless running an approved test-mode checkout. Live secret keys are rejected by configuration.
7. Start one application replica and verify `/health/live` and `/health/ready`.
8. Run one approved canary chart with non-sensitive data; confirm review, correction, approval, and all three exports.

Where supported, set termination grace beyond the configured provider deadline plus terminal-commit time. Render rejects custom grace for services with disks, so this topology cannot promise graceful completion of every in-flight call. Before planned deploys, close ingress, wait for queued/running jobs to reach terminal states, then deploy. Read-only status checks must use the configured data directory. Reopen ingress after readiness and persistence checks pass.

The adapter's `UNRENDER_PROVIDER_TIMEOUT_SECONDS` (default 240, allowed 1–240) covers lookup, dispatch and retrieval. Timeout is terminal and retains dispatched spend; remote execution may continue and must not be automatically redispatched. On shutdown the worker stops claiming, readiness becomes false, and it waits for the fenced terminal commit. If the platform kills it first, expired-lease recovery must retain dispatched spend and stop that attempt. Verify this separately from a clean restart; never interpret the local wait timeout as a platform guarantee.

The Dockerfile pins Python 3.11.16 slim-trixie by immutable multi-architecture manifest digest. Dependency upgrades must deliberately update both the readable tag and digest, then rerun the image build and scanner in CI.

`/health/live` proves the process responds. `/health/ready` verifies the database schema, a write/delete probe on the private volume, and the embedded worker thread. The readiness route is covered by the client-IP admission bucket and should also be private to the platform health network; `/health/live` stays cheap and unmetered. The container probe supplies the configured public Host header so production TrustedHost policy remains intact. Neither health route spends money or calls the external inference provider.

Provision controlled-beta accounts from a trusted shell on the running service with the configured data directory (Render one-off jobs do not mount the service disk). The password is prompted without echo and is never accepted as a command-line argument; the command does not start a worker or recover running jobs:

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
unrender-admin backup \
  --destination /backup/unrender-2026-09-01T020000Z
```

The command uses `UNRENDER_DATA_DIR` from the service environment (`/data/unrender` on Render). The destination must not exist and must be outside that data directory; copy the completed recovery set off-host. If any upload/job/database mutation is active—or any durable staging, upload-publication, or job-copy reservation remains—backup refuses immediately; drain writes or reconcile the interrupted publication and retry. Success is reported only after captured files, manifest, temporary tree, final tree, and their parent namespaces have been fsynced. Encrypt backups, restrict access, copy the completed directory as one unit, and alert on recovery-set age. A platform volume snapshot is acceptable only when the same mutation lock/drain contract is demonstrated.

Restore into a new absent data directory:

```bash
unrender-admin restore \
  --source /backup/unrender-2026-09-01T020000Z \
  --target /recovery/unrender-data
```

Restore rejects symbolic/special paths, extra/missing files, hash or size drift, an existing/nested target, SQLite integrity errors, and foreign-key violations. It rewrites stored absolute source paths from the captured root to the new root, fsyncs every restored file and namespace, and atomically publishes the target. Confirm the restored tree is owned by the runtime UID `10001` with `0600` files and `0700` directories (Render may assign its supplemental disk group), start the required worker with ingress closed, wait for `/health/ready`, and sample job sources/exports. Never restore only the database or only the files, edit the manifest, or weaken production validation for a drill.

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

Deploy immutable image tags. Before a schema-changing release, create and verify a coordinated recovery set. This release uses schema version 9 with crash-atomic, cross-process-serialized forward migrations from versions 1–8 and no down migration. Version 6 added worker execution leases/fencing, provider-dispatch state, audit rollups, provider-attempt accounting, and startup coordination. Version 7 added account session generations, attempt-fenced result/retained-byte reservations, and durable staging/upload/job-copy reservations. Version 8 gives every storage reservation an opaque owner token: resize renews only that live lease, publication must atomically consume the matching unexpired reservation, and deletion holds the exclusive operational lock through reference check and file removal. Version 9 adds verified-email state and expiring, hashed account challenges while preserving existing accounts. Reverting to a schema-8 image requires restoring the coordinated pre-v9 recovery set into a new volume; that image cannot open the upgraded database. Roll back application code only when it supports the on-disk schema; otherwise restore the coordinated recovery set into a new volume.

## Base-image advisory constraints

See `CONTAINER_SCAN.md` for the current package scan and runtime assessment.
Only restore recovery sets from the operator-controlled backup destination:
manifest hashes detect corruption but do not authenticate an arbitrary supplied
backup. The app does not support uploaded databases or operator execution of
customer-provided commands, Perl expressions, terminal descriptions or archives.
Verify deployed UID, mount/capability boundaries and operator access before
relying on the image-specific advisory assessment. Keep scan findings visible
and reassess when the base image or operational workflow changes.
