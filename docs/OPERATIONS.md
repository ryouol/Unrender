# Operations runbook

## Deployment preflight

1. Build and scan the pinned container image.
2. Provide a persistent, encrypted volume at `/data`. On Render, set `UNRENDER_DATA_DIR=/data/unrender`; the app creates and owns this private 0700 subdirectory as UID 10001. The mount root and supplemental group are platform-managed.
3. Terminate TLS at the load balancer. Render supplies the exact HTTPS origin through `RENDER_EXTERNAL_URL`; use `UNRENDER_BASE_URL` only for a verified custom origin.
4. Set `UNRENDER_ENV=production`, `UNRENDER_EXTRACTOR=modal`, `UNRENDER_WORKER_ENABLED=true`, `UNRENDER_SEED_DEMO=false`, and choose the registration policy explicitly. For email-deferred public accounts, set `UNRENDER_ALLOW_REGISTRATION=true`, `UNRENDER_REQUIRE_EMAIL_VERIFICATION=false`, and `UNRENDER_INITIAL_CREDITS=0`, with every SMTP and Stripe value empty; see [PUBLIC_ACCOUNTS.md](PUBLIC_ACCOUNTS.md). Set registration false for invitation-only access. Production validation rejects unsafe combinations.
5. Pin the approved model bytes and canaried provider-release digest. The deployed private Modal volume release uses `UNRENDER_MODAL_MODEL=modal-volume/unrender-inference-cache` and the identical full SHA-256 for revision and model digest. The alternative Hub path requires a full 40-character commit plus the complete snapshot SHA-256. Both paths verify immutable release contents. Current pins and the explicit `modal_train.py::production_app` deployment command are in [RENDER_MODAL_LAUNCH.md](RENDER_MODAL_LAUNCH.md). Run `unrender-admin check-provider-contract` as a non-spending resolution canary, then verify real inference. The application handshake detects drift; it does not replace platform attestation. Store provider credentials in platform secret management.
6. Leave Stripe variables empty unless running an approved test-mode checkout. Live secret keys are rejected by configuration.
7. Start one application replica and verify `/health/live` and `/health/ready`.
8. Run one approved canary chart with non-sensitive data; confirm review, correction, approval, and all three exports.

Where supported, set termination grace beyond the configured provider deadline plus terminal-commit time. Render rejects custom grace for services with disks, so this topology cannot promise graceful completion of every in-flight call. Before planned deploys, close ingress, wait for queued/running jobs to reach terminal states, then deploy. Read-only status checks must use the configured data directory. Reopen ingress after readiness and persistence checks pass.

The adapter's `UNRENDER_PROVIDER_TIMEOUT_SECONDS` (default 240, allowed 1–240) covers lookup, dispatch and retrieval. Timeout is terminal and retains dispatched spend; remote execution may continue and must not be automatically redispatched. On shutdown the worker stops claiming, readiness becomes false, and it waits for the fenced terminal commit. If the platform kills it first, expired-lease recovery must retain dispatched spend and stop that attempt. Verify this separately from a clean restart; never interpret the local wait timeout as a platform guarantee.

The Dockerfile pins Python 3.11.16 slim-trixie by immutable multi-architecture manifest digest. Dependency upgrades must deliberately update both the readable tag and digest, then rerun the image build and scanner in CI.

`/health/live` proves the process responds. `/health/ready` verifies the database schema, a write/delete probe on the private volume, and the embedded worker thread. Readiness consumes the global request-capacity bucket; `/health/live` stays cheap and unmetered. The container probe supplies the configured public Host header so production TrustedHost policy remains intact. Neither health route spends money or calls the external inference provider. Global exhaustion can also reject readiness, so investigate request pressure before treating it as a storage failure.

Request limits use global capacity plus validated tenant/account quotas. They do
not trust forwarding headers or depend on ASGI peer addresses. Defaults and the
hosted ingress evidence are in [REQUEST_LIMITS.md](REQUEST_LIMITS.md).

Invite users from a trusted shell on the running service with its configured data directory (Render one-off jobs do not mount the service disk):

```bash
unrender-admin invite-user analyst@example.com --credits 0 --destination /tmp/analyst-invite.txt
```

The command saves a one-use, 30-minute setup link in a new mode-0600 file. Deliver it privately to the intended person after verifying their identity; do not paste it in shared logs or issue trackers. The recipient chooses their own password. Email delivery and public registration can remain disabled. Default credits are zero; grant a deliberate allowance separately. Account and challenge changes roll back if writing or syncing the file fails. Delete the link file after secure delivery. An expired or lost link can be replaced:

```bash
unrender-admin account-link analyst@example.com --destination /tmp/analyst-recovery.txt
```

Only issue recovery links after verifying the person's identity. A successful reissue invalidates prior account links. Completing recovery changes the password, signs out existing sessions, and revokes API keys; charts and credits remain. Neither command invokes inference. Existing destination files are never overwritten. A crash after file publication but before database commit can leave an unusable file; issue a new link through the operator command. Self-service email recovery remains unavailable until email is configured.

`create-user` remains available for operator-provisioned accounts and prompts for the password without echo. Do not expose administrative commands through the web service.

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
- backup age over 48 hours (the daily schedule plus retry grace).

Provider success/failure and latency can be derived from the structured lifecycle
records. The deployed hourly monitor covers the fixed conditions below;
historical dashboards and the remaining alert types are separate work.

The deployed `/health/operations` endpoint is separate from `/health/ready` and
does not control restarts. It emits fixed boolean checks without tenant data:
queued/current running attempts older than five minutes, at least three provider
failures in the last hour, any provider completion longer than 180 seconds in the
last hour, credit balance versus retained ledger deltas, and a successful backup
less than 48 hours old. A missing or invalid backup status fails when backups are
configured. Running attempts use their immutable start audit, not a heartbeat.
Missing current-attempt start evidence also requires attention.

Reads share a one-minute cache, a nonblocking lock and a two-second SQLite VM
budget. Contention, unavailable storage or a failed scan returns attention.
`render.yaml` defines an hourly `unrender-monitor` cron at minute 17 UTC using
`timeout --kill-after=5s 100s unrender-operations-check`. It retries twice, 30 seconds
apart, then exits nonzero so Render can send a failure notification. The cron has
a $1/month minimum and requires no app/Modal credentials or customer email setup.
The probe URL is the current `https://unrender.onrender.com` origin; change it when
moving to a custom domain or another deployment. Hourly cadence plus caching can
delay detection by about an hour and can miss an incident that starts and ends
between checks. Planned maintenance can cause a notification.

The monitor is `crn-dahl5uh594qs73ffkbk0` in UNRENDER's Production environment,
built from `02597a6`. Its first manual run started at 01:03:00 UTC on September 11,
reported failure at 01:04:05 and exited with status 1. The operator inbox received
Render's cron failure email at 01:04:09. This exercised the real public endpoint,
retry command and delivery path: the earlier pilot provider attempt took 191.53
seconds and was still within the one-hour lookback. The other operational checks
were healthy. The endpoint recovered after that event aged out, without changing
data or thresholds. No website outage, synthetic failure or GPU call was induced.
The second manual run logged success at 01:05:18 UTC and completed successfully
in 10.9 seconds according to Render. The first scheduled run then started at
01:17:00 UTC, logged a passed check at 01:17:07 and completed successfully at
01:17:10. The deployed command and schedule remained unchanged. Receipts are in
`release/launch-eval-results/operations-monitor-v1.json`.
The cron has an explicit failure-only notification override; no app/Modal
credentials, shared environment groups or persistent disk are attached.

The 15-minute job failure-rate dashboard and repeated authentication/signature
failure alerts above remain separate work; the fixed provider thresholds do not
implement them. Individual queue, ledger and backup failures are covered by local
regressions; they have not each been induced in production. The delivery check
does not establish notification latency or availability guarantees.

The UNRENDER Render service has an explicit **Only failure notifications** override;
workspace defaults and other services were not changed. The existing destination
is Email. Delivery evidence: the operator inbox contains the two UNRENDER deploy
failure notices from September 10 at 21:53:44 and 21:56:02 UTC. These are historical
failure receipts, not a newly induced outage or proof of every alert type.

[Render's supported platform notifications](https://render.com/docs/notifications)
include failed builds/deploys, unhealthy running services and persistent-disk use
above 80%. This covers platform health/capacity events without application SMTP.
Those native events do not inspect application data. The hourly cron above adds
stale-backup, queue, ledger and provider checks through a failed cron execution.
Recheck both service overrides
after service recreation; the current Blueprint specification does not document
a notification-policy field.

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

Deploy immutable image tags. Before a schema-changing release, create and verify a coordinated recovery set. This release uses schema version 14 with crash-atomic, cross-process-serialized forward migrations from versions 1–13 and no down migration. Version 6 added worker execution leases/fencing, provider-dispatch state, audit rollups, provider-attempt accounting, and startup coordination. Version 7 added account session generations, attempt-fenced result/retained-byte reservations, and durable staging/upload/job-copy reservations. Version 8 gives every storage reservation an opaque owner token: resize renews only that live lease, publication must atomically consume the matching unexpired reservation, and deletion holds the exclusive operational lock through reference check and file removal. Version 9 adds verified-email state and expiring, hashed account challenges while preserving existing accounts. Version 10 separates account activation from mailbox verification and records challenge delivery provenance. It preserves legacy account/session access, clears legacy mailbox flags that previously also represented operator activation, and requires fresh password-confirmed email verification before future email recovery. Schema 11 adds Google identities and recent authentication; schema 12 adds private projects and chart names; schema 13 binds Google login completion to its initiating browser; schema 14 indexes owner and chart lookups used by bulk deletion. Existing accounts, credits, charts, and sessions are preserved. Reverting to an image that supports only an earlier schema requires restoring its coordinated recovery set into a fresh data directory; do not run it over the upgraded database. Roll back application code only when it supports the on-disk schema; otherwise restore the coordinated recovery set into a new volume.

## Base-image advisory constraints

See `CONTAINER_SCAN.md` for the current package scan and runtime assessment.
Only restore recovery sets from the operator-controlled backup destination:
manifest hashes detect corruption but do not authenticate an arbitrary supplied
backup. The app does not support uploaded databases or operator execution of
customer-provided commands, Perl expressions, terminal descriptions or archives.
Verify deployed UID, mount/capability boundaries and operator access before
relying on the image-specific advisory assessment. Keep scan findings visible
and reassess when the base image or operational workflow changes.


## Scheduled off-host recovery copies

Set `UNRENDER_BACKUP_VOLUME=unrender-production-backups` only after creating that
private Modal v1 volume. This optional scheduler uses the Render service's existing
Modal credentials; it adds no GPU function, public backup endpoint or Render SSH
credential in Modal. It is disabled when the setting is empty.

The single-instance service checks hourly and creates a coordinated snapshot when
its previous verified copy is at least 24 hours old. It defers while an extraction
or source publication is active. During the local snapshot lock, requests receive
503 with Retry-After; `/health/live` remains available. This is a brief maintenance
window, not a zero-downtime backup promise. Each attempt has a 600-second deadline.

A snapshot includes SQLite, committed sources and a hash inventory. Temporary
space and snapshot size are checked before copying. Archives are limited to one
GiB. Upload readback uses concurrency one through the pinned Modal 1.5.5 SDK;
review this private-method contract when upgrading that dependency. The dedicated
backup subprocess also bounds the
pinned SDK multipart upload budget to 64 MiB (one 16 MiB segment plus SDK buffers);
the web and inference processes keep their SDK defaults. Recheck both private SDK
contracts when upgrading Modal. Seven archives
are retained after verification; at eight, the scheduler resumes verification and
pruning instead of uploading again. Unexpected extra archives or corrupt readback
fail closed and require operator investigation. These are application bounds for
this dedicated volume, not an account-wide dollar cap.

The private `/data/unrender/backup-status.json` records the last verified archive,
SHA-256, size and timestamp. `scheduled_backup_succeeded`,
`scheduled_backup_failed`, and `scheduled_backup_status_write_failed` appear in
structured logs. A status file older than 48 hours requires investigation; alert
delivery for this condition must be configured separately. Successful manual and
round-trip tests do not establish an RPO or restoration SLA.

To restore, download the named archive privately, verify its full SHA-256 against
its filename/status record, extract it using a safe tar extractor, and run
`unrender-admin restore --source EXTRACTED/snapshot --target NEW_EMPTY_DATA_DIR`.
Use an isolated target first and validate accounts, sources, approved charts and
exports before replacing the live data directory. Never restore onto the running
service's active data directory.

Render also provides encrypted daily disk snapshots, but its documentation warns
against treating whole-disk restores as database recovery. Keep the coordinated
recovery copy workflow above. See [Render disks](https://render.com/docs/disks)
and [Modal Volumes](https://modal.com/docs/guide/volumes); Modal notes that deleted
storage may remain billable for up to four days.
