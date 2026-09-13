# Render + Modal launch

## Current deployment — September 12, 2026

The live beta at https://unrender.onrender.com runs merge commit
`a14b961db721004a4ad77d4e2ab5cdac343d1ef9`, schema 14.
[PR #8](https://github.com/ryouol/Unrender/pull/8) added a one-time configured
welcome grant to Google signup and sets the public beta allowance to three
credits for both Google and password accounts. Existing balances, returning
sign-in, and explicit linking do not receive another grant. Email and billing
remain disabled; the existing Render service, disk, and pinned Modal model are
unchanged. Later documentation-only commits do not require a runtime redeploy.

Deployment `dep-dai9d4m743jc73e8fb8g` became live at 00:03:07 UTC. A coordinated
backup preceded deployment. Pre/post snapshots preserved the existing user,
session, ledger and three-credit balance; only `UNRENDER_INITIAL_CREDITS` changed.
The hosted password signup check received three credits with one welcome ledger
entry, rejected duplicate signup, and retained its balance after sign-out/sign-in.
The synthetic verification account was removed without changing other accounts.
Public configuration, landing copy and both health routes were checked after
maintenance was disabled. No inference, email or billing was invoked by this rollout.

Local validation: 320 tests passed / 1 skipped; 73 workflow browser scenarios,
types and security lint passed. Branch, PR and main CI verify/container jobs passed.
The Google grant path is covered by local integration tests; this rollout did not
create a new real Google identity. See [engineering review](ENGINEERING_REVIEW.md)
and [readiness](LAUNCH_READINESS.md) for remaining evidence gaps.

## Historical refined-platform rollout — September 11, 2026

UNRENDER is deployed at https://unrender.onrender.com using the Documents/Codex
working checkout. The separate Desktop checkout is not the launch source.
The backend and premium interface were merged separately through PRs
[#2](https://github.com/ryouol/Unrender/pull/2) and
[#3](https://github.com/ryouol/Unrender/pull/3). Public password accounts followed
in [#4](https://github.com/ryouol/Unrender/pull/4). The refined platform followed
in [#6](https://github.com/ryouol/Unrender/pull/6). The service tracks `main`
with automatic deployments still off. This historical rollout ran merge commit
`015624a0af219107eb33ff4dc501f07dedc7051e`, schema 14.

Render project `UNRENDER`, Production environment:
https://dashboard.render.com/project/prj-dahh1gbl550s73840e5g

- Service: `srv-dahid9uq1p3s73dmjt1g`, Docker, Ohio, one 512 MB / half-CPU instance.
- Disk: `dsk-dahid9uq1p3s73dmjts0`, 1 GB mounted at `/data`.
- Application data: `/data/unrender`, private mode 0700, owned by UID 10001.
- Health: `/health/ready`; live HTTPS returned `ready`, `modal`, worker `running`.
- Automatic deploys and PR previews are off. Failure notifications use the
  service's explicit failure-only override. No other project's configuration changed.
- Live runtime code: `015624a0af219107eb33ff4dc501f07dedc7051e`; deployment
  `dep-dai3fnu1egvs73dactq0`, live September 11 at 17:19:28 UTC.
- Hourly monitor: `unrender-monitor`, `crn-dahl5uh594qs73ffkbk0`, Docker,
  Ohio, 512 MB / half-CPU. It runs at minute 17 UTC in the same Production
  environment, with auto-deploy off and an explicit failure-only notification
  override. It has no app/Modal credentials or persistent disk. Its build remains
  `02597a6`; the September 11 04:17 UTC scheduled run passed.

### Refined platform rollout — September 11, 17:18–17:22 UTC

PR #6 merged as `015624a0af219107eb33ff4dc501f07dedc7051e`. Branch, PR and main CI
runs `34625970573`, `34626014418` and `34626482105` all passed their verify and
container jobs. Local verification passed 316 tests with one skip, 73 workflow,
17 Google and 7 preview browser scenarios. The local container passed 24 HTTP
checks and restart/integrity checks. Its scan retains the documented Debian
baseline (3 critical, 51 high; no fixed package version listed), with zero Python
findings. A later lint-comment relocation leaves the Python AST unchanged; the
image's byte comparisons describe the source snapshot at build time. See
[REFINED_PLATFORM_REVIEW.md](REFINED_PLATFORM_REVIEW.md).

With maintenance enabled and work drained, the coordinated schema-10 recovery
set `/data/release-backups/pre-schema14-20260911T171807Z` was restored in an
isolated temporary directory. Stable snapshots of eight tables and all source
hashes matched; the restore migrated to schema 14, initialized successfully a
second time and verified all eight deletion indexes. The temporary restore was
removed; the recovery set remains available for rollback.

Deployment `dep-dai3fnu1egvs73dactq0` became live at 17:19:28 UTC. Exact pre/post
comparisons preserved seven users, eleven sessions, five uploads, five charts,
six result versions, nine ledger rows, five provider attempts and one aggregate
credit (API keys remained zero). SQLite integrity/FKs, private mode 0700 under
UID 10001, readiness and every operations check passed. Maintenance was disabled
at approximately 17:22 UTC, after preservation and health checks. Internal
health requests used the expected production Host header; all actual health
checks returned 200 with every operations check true. Independent public HTTPS
checks also returned 200 for live, ready and operations health, with all six
operations checks true.

Thirty live HTTPS checks passed using a synthetic zero-credit password account:
signup/session, nine foreign-chart/source/history/export surfaces returning 404,
a valid 64-pixel PNG rejected with 402, private project creation/rename/list and
deletion with charts kept, recent-authentication account deletion, and rejection
of the deleted session with 401. Synthetic accounts were removed. An initial
16-pixel upload fixture correctly returned 422; correcting the fixture produced
the expected credit rejection and did not require an application fix.
After all smoke checks, a final snapshot again matched every pre-upgrade stable
table and source exactly. Projects, Google identities and OAuth attempts remained
zero, confirming synthetic cleanup without changing the owner's account.

The owner browser kept its existing session and all five charts. A fresh approved
XLSX opened with 18 data rows and its Audit sheet (six rows including its header).
The logo returned to My charts. The hosted landing was captured without the
removed example module or overflow, and the current browser console had no
errors or warnings. No GPU inference,
email or billing call was made, and compute, disk, replicas and model/provider
pins were unchanged.

The only new application configuration was the dedicated Google client ID/secret
from a separate personal Google project. The client is configured for the
production audience and the application advertises Google sign-in. **Real Google
consent, sign-in and linking remain unverified.** The existing owner account is
a password account: sign in with that password, then use Account settings →
Connect Google and confirm the password. Matching email never links accounts.
Returning Google sign-in and preserved ownership/credits must be verified after
that explicit linking step. See [GOOGLE_SIGNIN.md](GOOGLE_SIGNIN.md).

Sanitized rollout receipt:
[refined-platform-v1.json](../release/launch-eval-results/refined-platform-v1.json).
The earlier rollout sections below remain historical evidence.

### Public account rollout — September 11, 04:56–05:00 UTC

PR #4 passed verify/container checks on its branch and PR, and merge commit
`449a6de` passed CI run `34563919196`. Simplify and specialized code-review
findings are recorded in [PUBLIC_ACCOUNT_REVIEW.md](PUBLIC_ACCOUNT_REVIEW.md).

With ingress closed and no active jobs or storage reservations, the schema-9
recovery set `/data/release-backups/pre-schema10-20260911T0454Z` was created and
restored in isolation. Only `UNRENDER_ALLOW_REGISTRATION` changed in the service
environment, to true; initial credits remained zero and every SMTP/Stripe value
remained empty. The saved flag was read back before explicit deployment. The
service branch changed to main; compute, disk, replicas and other projects did
not change, and automatic deployment remained off.

Deployment `dep-dahojlp42hec739qvh6g` became live at 04:56:37 UTC. Schema 10
preserved six existing active accounts, five charts, six versions and one credit.
Legacy mailbox flags became unverified as intended; existing sessions continued
to work. SQLite integrity, foreign keys, approved result/approval digest, source
checksum and all health checks passed.

A fresh synthetic zero-credit account passed public HTTPS signup, secure cookie
checks, logout/login and private job listing. Seven requests for the owner's
job, source, history and exports returned 404. A valid owned PNG upload returned
402 before creating any upload, job, challenge, credit grant or provider attempt.
Credentials stayed in the test process and were discarded after sign-out; one
`release-check-…@example.invalid` account remains for this persistence receipt.

The schema-10 recovery set
`/data/release-backups/post-schema10-20260911T0459Z` was also created and restored
in isolation. A second drained deployment of the same commit preserved the test
session and a fresh login returned the same account. Render reported
`dep-dahol44s728c73cua960` live at 04:59:31 UTC; maintenance was disabled after
health and integrity checks. The owner browser retained its workspace and
downloaded a fresh approved XLSX with 18 data rows and its Audit sheet. The
approved support mailto link was verified in the hosted browser.

The existing pinned `unrender-production/infer_one` contract resolved without
inference. No GPU call, credit grant, customer billing or email sending was part
of this release. Receipt: `release/launch-eval-results/public-accounts-v1.json`.
Local port 8000 runs the updated saved-sample replay mode separately from Modal.

### Premium interface rollout — September 11, 04:30 UTC

The reviewed UI commit `4ebdcaa` was deployed explicitly after its verify and
container checks passed. Ingress was closed using this service's maintenance
mode. No queued/running jobs or storage reservations remained. A coordinated
recovery set was created at
`/data/release-backups/pre-premium-4ebdcaa-20260911T0429Z` and restored into an
isolated temporary directory before the deployment began. The persistent
recovery set survived the rollout.

Render reported the deployment live at 04:30:36 UTC. The new process confirmed
the exact commit, schema 9, SQLite integrity, zero foreign-key errors, six
accounts, five charts, six saved versions and one remaining credit. The digest
of the approved chart's saved result/approval and its source checksum matched
the pre-deploy values. Readiness and every operations check passed before
maintenance was disabled. No model configuration, pricing plan, instance count
or other project's resource was changed; no inference was invoked.

Hosted browser verification confirmed the public landing page, persistent owner
session, existing charts and the new review workspace. A fresh XLSX download
opened successfully with 18 data rows and an Audit sheet containing the source,
job, model, approval status and approval timestamp. The browser download-event
observer timed out for the blob download, but the newly written local workbook
was independently inspected. Signup remained closed on that schema-9 runtime until the account-policy
release described above.

Render owns the disk mount root. The first startup correctly refused to chmod
`/data`; using the app-owned subdirectory fixed startup without running as root
or weakening permissions. Render injects a supplemental disk group; directory
privacy is enforced by owner-only mode, not by assuming GID 10001 on the mount.

Render rejects custom shutdown grace periods on services with disks. Do not add
`maxShutdownDelaySeconds: 300` to this topology: the API rejected that setting.
Drain active jobs before planned restarts/deployments. The app's 240-second
provider deadline does not establish a matching platform termination grace.
The hosted in-flight restart test passed after the recovery fix: the interrupted
attempt became terminal with `worker_lease_expired_after_dispatch`, stayed charged
once, and was not redispatched. Approved work and exports survived the restart.
The observed restart/recovery check took 70.08 seconds and included downtime.

## Budget and access

The user's current budget is approximately US$20/month, with modest overages
accepted. Keep Render and Modal. The earlier absolute ceiling is superseded.
The Render baseline is US$7/month web compute, US$0.25/month for the disk and
the monitor's US$1/month minimum: approximately US$8.25/month before Modal
compute/storage, taxes and any Render usage overages. The bounded hourly monitor
normally stays within its minimum. This is not a provider-enforced dollar cap.
[Render cron billing](https://render.com/docs/cronjobs) charges for active time
with a minimum of US$1/month per cron service.

Public password registration is enabled with zero welcome credits. Customer
billing and email delivery remain off. Account activation is separate from
mailbox verification; see PUBLIC_ACCOUNTS.md. The invitation commands remain
available for operator-provisioned access without email sending.
Grant credits deliberately with `unrender-admin grant-credits email --credits N
--reference pilot-001`; repeating the reference does not grant twice. Operator
recovery links are supported; self-service email recovery remains deferred.

Modal's dedicated `unrender-production` app allows one L4 container, zero automatic
retries, a 240-second function timeout, and a two-second idle scale-down window.
Account credits constrain authorized inference attempts. These controls reduce
runaway usage but do not cap all shared-workspace billing. Leave shared caps
untouched because other projects use the same accounts.

## Model release and evidence

The actual post-trained source is
`unrender-vol/runs/qwen3vl4b-table-fair/merged`, Qwen3VLForConditionalGeneration,
8,891,676,902 bytes. CPU inspection and publication verified this SHA-256:
`3954f3395a9db64fcbd3b9dc94508ab0cf9af2f5f2156643504881ee712e8c7e`.

The private release is stored in `unrender-inference-cache/releases/<digest>`.
`UNRENDER_MODAL_MODEL=modal-volume/unrender-inference-cache`; revision and model
digest both equal the full SHA-256. Each invocation verifies the read-only
snapshot contents. No Hugging Face credential or public model upload is needed.

Production app: https://modal.com/apps/royluo05/main/deployed/unrender-production

Deploy explicitly with `modal deploy modal_train.py::production_app`; the bare
module selects the separate research app. Approved provider release:
`e8b732574b07c243e27549220115419d52e3ce850c36022ac19ed33350707787`.
All release pins are in `render.yaml`. The dedicated Modal API token is stored
in Render's private environment. Never copy credentials into git, reports, or
Roy-OS. Render supplies the HTTPS origin through `RENDER_EXTERNAL_URL`.

The timing release was deployed under maintenance after confirming no queued or
running jobs. One direct Modal canary recovered all four labelled-bar values
exactly in 92.523 seconds; the source commit was `3fe2401`. The matching pin was
verified in the running Render process before public access resumed. A masked
environment-field edit initially retained the old value despite a save notice;
revealing this non-secret digest, editing it, and reading it back corrected the
setting. Treat the live process value as deployment evidence, not the save notice.

Readiness, SQLite integrity/foreign keys, an existing approved job and persisted
backup status survived the update. The stage timing receipt is
`release/launch-eval-results/stage-timing-v1.json`; it is a direct-provider canary,
not a new end-to-end customer benchmark. The full CI suite passed on `3fe2401`.
After maintenance ended, public HTTPS sign-in, account retrieval and all three
exports of the existing approved chart passed, including the XLSX audit sheet.
Roy's account retained one extraction credit; the direct operator canary did not
consume an application credit. It did use one billed Modal inference attempt.

Direct real inference took 91.29 seconds on the first observed call and 51.84
seconds on an immediate repeat. A local production-configured HTTP workflow with
real Modal inference completed in 48.26 seconds and passed correction, approval,
CSV/JSON/XLSX export, audit-sheet presence, and restart persistence. That local
TestClient evidence does not prove Render behavior. Hosted extraction completed in 82.89 seconds and passed sign-in, secure session
cookies, upload, correction, approval, all three exports, and re-login. Evidence
is recorded separately under `outputs/local-verification/render-live/`.

These are operational canaries on one low-resolution owned chart, not customer
accuracy benchmarks. Numerical values require correction; for example the model
returned 9.0 for Q1 2017 while the saved reference is 9.8. Preserve the review-first
promise. The historical 34.8% hard-set cell accuracy is not a current customer
benchmark. Tokenizer/truncation warnings remain recorded for model review;
preprocessing was not silently changed during deployment.

## Verification and remaining launch work

- The final container hardening release `2179df8` passed CI run 34554233524
  (240 tests / one skipped and the production image checks). It removes unused
  setuid/setgid permissions under `/usr`. Isolated startup/restart/storage tests
  and hosted non-root SSH, helper modes, health, database integrity, owner sign-in
  and approved exports passed. The model pin and owner's one credit are unchanged;
  no inference or email ran. See `release/launch-eval-results/runtime-hardening-v1.json`.
  Debian packages are unchanged; this mitigation does not patch their advisories.
- The whole-diff simplify/code review and focused rechecks are complete. Runtime
  `35f49f6` clears inherited cloud backup/SMTP destinations from the local sample
  launcher and rejects invalid reset challenges before expensive password work.
  CI run 34552450793 passed 240 tests / one skipped, dependency audits, package
  build and container smoke. Hosted recovery of the existing zero-credit test
  account passed new-password sign-in, old-session revocation and used-link
  rejection; the owner account was not reset and no email or inference ran.
  Database integrity, provider pin, backup status and approved work survived.
  See PRODUCTIZATION_REVIEW.md for all findings, review limits and the combined
  PR's size/staging concern.
- The pinned container built successfully on Render. Local constrained capacity
  testing used 512 MB, no swap, and half a CPU; peak cgroup memory was 222.7 MiB.
  That harness used replay and is not a hosted concurrency benchmark.
- Read-only Modal contract resolution from Render and non-root SSH access passed.
- The Render Blueprint validates after removing the unsupported shutdown setting
  and using the app-owned data subdirectory.
- Hosted authentication/inference/exports passed. Coordinated backup and isolated
  restore retained the approved job and source, with SQLite integrity checks; a
  private recovery archive was copied off-host to the operator machine. Runtime
  bf5da14 additionally enabled daily copies to the private Modal backup volume;
  its first automatic archive passed independent download, checksum and isolated
  restore of the approved chart, source and all three export formats.
- The first in-flight restart test exposed a post-startup lease-recovery gap.
  The deployed fix and regression recover leases expiring after startup. Hosted
  retest passed: one charged attempt, no redispatch, terminal failure, and approved
  work/export persistence. Failed diagnostic jobs were removed after recording
  the results; the approved example remains available.
- Request admission now separates shared capacity from validated tenant and
  normalized login quotas. The hosted test exhausted one zero-credit account at
  120 requests while another account and readiness remained available. A second
  session and changed forwarding header could not reset the exhausted quota.
  Public/private ingress probes established that forwarded identity is spoofable
  across the shared private boundary. Client IPs remain unavailable for attribution,
  but quotas no longer depend on them. See REQUEST_LIMITS.md. CI on `be6c99b`
  passed 233 tests / one skipped and both verification/container jobs. Hosted
  sign-in, approved exports, database integrity and the provider pin survived the
  update; no inference credit was spent.
- Render service failure alerts now have explicit UNRENDER-only overrides and
  an Email destination. The hourly monitor's first run detected the pilot's
  191.53-second provider attempt, exited with status 1, and delivered a failure
  notice to the operator inbox at 01:04:09 UTC on September 11. The public
  operational endpoint returned to healthy after the event naturally left its
  one-hour window; no threshold or production data was altered. See
  OPERATIONS.md for the monitor's cadence, thresholds and remaining alert gaps.
  Its first scheduled run started at 01:17:00 UTC and finished successfully at
  01:17:10 UTC, separately from the earlier manual alert/recovery checks.
  Scheduled coordinated off-host
  copies are enabled and the first restore drill passed; measured recovery
  objectives remain open. A disk snapshot alone does not meet the app's
  database/file consistency contract.
- Complete the base-image advisory assessment's deployment assumptions, provider
  timeout/cancellation coverage beyond the tested restart path, and intended-input
  numerical/correction-time evaluation.
- Public legal/operator details still need completion before a broad
  customer launch. Email setup is explicitly deferred, not silently considered
  tested. This is a controlled beta with public signup and operator-granted
  extraction access, not a claim that all release gates
  are complete.

The UI advertises 10 MiB uploads, 4 MP images, and the PDF page limit. The server
also enforces 50 MiB per-user storage and 500 MiB accounted global storage. Authentication and expensive-request
concurrency are each one. Default chart retention is 30 days; restart persistence
does not mean indefinite retention. Local testing at http://127.0.0.1:8000 uses
`scripts/run_local.sh` and the saved replay fixture, separately from production.

Operations and recovery commands: [OPERATIONS.md](OPERATIONS.md).
Review findings: [PRODUCTIZATION_REVIEW.md](PRODUCTIZATION_REVIEW.md).
Container advisories: [CONTAINER_SCAN.md](CONTAINER_SCAN.md).
Provider references: https://render.com/docs/disks,
https://render.com/docs/blueprint-spec, https://render.com/docs/ssh.

## Invitation release verification

Runtime `437322d` deployed successfully on September 10. Hosted HTTP checks
confirmed activation through the existing reset endpoint with SMTP disabled,
single-use token rejection, logout/relogin, and denial of a different tenant's
approved chart. The test account has zero credits and triggered no inference.
Runtime `914c55c` subsequently passed real Chromium activation, immediate sign-in,
and reload session persistence. The bearer fragment was removed from the address
bar before requests. The email-disabled recovery page directs users to their
inviter and hides the unavailable email form. No GPU calls or email were used.
Local validation: 199 passed, 1 skipped; Ruff, mypy and JavaScript syntax passed.

The browser check exposed an anonymous session-check race that API tests did not:
a late 401 erased sign-in input before submit. Runtime `914c55c` fixes it without
changing authenticated-session or cross-tab privacy protections. Three Node
browser-state suites and nine focused public/static tests passed after the fix.
A brief 502 was observed during the one-instance deployment; readiness recovered.
