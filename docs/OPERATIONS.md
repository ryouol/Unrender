# Operations runbook

## Deployment preflight

1. Build and scan the pinned container image.
2. Provide a persistent, encrypted `/data` volume owned by UID/GID `10001`.
3. Terminate TLS at the load balancer and set the exact public `UNRENDER_BASE_URL`.
4. Set `UNRENDER_ENV=production`, `UNRENDER_EXTRACTOR=modal`, `UNRENDER_SEED_DEMO=false`, and `UNRENDER_ALLOW_REGISTRATION=false`; production validation fails closed otherwise.
5. Configure an approved model repository and its full 40-character commit as `UNRENDER_MODAL_MODEL` / `UNRENDER_MODAL_REVISION`; production rejects local/mutable paths. Mount provider credentials through the platform secret manager when the approved repository requires them.
6. Leave Stripe variables empty unless running an approved test-mode checkout. Live secret keys are rejected by configuration.
7. Start one application replica and verify `/health/live` and `/health/ready`.
8. Run one approved canary chart with non-sensitive data; confirm review, correction, approval, and all three exports.

The Dockerfile pins Python 3.11.16 slim-trixie by immutable multi-architecture manifest digest. Dependency upgrades must deliberately update both the readable tag and digest, then rerun the image build and scanner in CI.

`/health/live` proves the process responds. `/health/ready` verifies the database schema and storage path. Neither calls the external inference provider.

Provision controlled-beta accounts from a trusted one-off operator shell attached to the same encrypted `/data` volume. The password is prompted without echo and is never accepted as a command-line argument; the command does not start a worker or recover running jobs:

```bash
unrender-admin create-user analyst@example.com --credits 25
```

Do not expose this command through the web service or run it in a shared shell transcript.

## Logs and alerts

The application currently emits server and worker logs to stdout. The deployment platform must capture and retain them without request bodies, cookies, API keys, uploaded content, or provider credentials.

Alert on:

- readiness failing for two consecutive checks;
- queue age over five minutes;
- job failure rate over 10% in 15 minutes;
- refund ledger mismatch or negative-balance invariant failure;
- storage over 80% capacity;
- repeated origin, CSRF, API-key, or webhook-signature failures;
- provider latency/error increase;
- backup age over 24 hours.

Queue age and failure/refund dashboards are owner blockers because structured metrics are not yet exported.

## Backup and restore

Back up both the SQLite database and storage tree as one recovery set.

For a consistent SQLite backup while the app is live:

```bash
sqlite3 /data/unrender.sqlite3 ".backup '/backup/unrender.sqlite3'"
rsync -a --delete /data/storage/ /backup/storage/
```

Prefer a volume snapshot after briefly draining new uploads. Encrypt backups, restrict access, and test restore monthly.

Restore into a new empty volume, preserve file paths relative to `/data`, start with the worker disabled, verify `/health/ready`, sample several job sources/exports, then enable the worker. Never restore only the database or only the files.

Target assumptions for beta: RPO 24 hours and RTO 4 hours. These are internal objectives, not a customer SLA.

## Incident procedures

### Provider outage

Disable the worker, keep web access available for existing review/exports, preserve queued jobs, and communicate that extraction is delayed. Re-enable after a provider canary succeeds. Failed jobs already return reserved credits.

### Suspected credential leak

Rotate the affected Modal, Stripe, or deployment secret; revoke exposed API keys in the database until a UI exists; invalidate sessions if session material may be involved; preserve audit/log evidence; and assess customer notification obligations with counsel.

### Suspected chart-data exposure

Stop public traffic, snapshot evidence, identify affected tenant IDs and paths, rotate access credentials, and do not delete evidence until counsel/incident leadership approves. The privacy notice is a draft and must be finalized before customer data is accepted.

### Database or volume pressure

Pause uploads, run the retention cleanup, expand the volume, and verify database integrity. Do not delete job files manually because the database and audit trail would diverge.

## Rollback

Deploy immutable image tags. Before a schema-changing release, snapshot `/data`. This release uses schema version 1 and has no down migration. Roll back application code only when it still supports the on-disk schema; otherwise restore the coordinated snapshot.
