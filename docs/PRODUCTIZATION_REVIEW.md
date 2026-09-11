# Productization review — September 10, 2026

Read-only subagent reviews applied all code-review skills (context, testing,
breaking changes, change size), plus three simplify passes (reuse, quality,
efficiency). This records every reported issue, including those fixed during the
review. A final review of the release diff remains required after remaining work.

1. **Fixed — duplicate export button busy state.** `static/app.js`'s actionButton
   now owns pending state and guards reenabling against stale auth/view epochs;
   downloadExport no longer duplicates the lifecycle. The quality and efficiency
   reviewers independently reported the same issue.
2. **Fixed — unused consent-state assignment.** Removed the unused `choice=value`
   write in `static/site.js`. Optional analytics still collects no data.
3. **Fixed P1 — reset versus old-password login.** `service.py::authenticate` now
   passes the validated password hash into `create_session`, which compares it
   within its write transaction. A deterministic interleaving regression rejects
   the old login after reset. Two reviewers reproduced and rechecked this fix.
4. **Fixed P1 — reset versus API-key issuance.** `web.py::create_key` passes the
   authenticated generation; `service.py::create_api_key` checks it transactionally.
   Regression coverage resets the password between admission and key creation.
5. **Fixed P2 — failed/reordered account mail.** `service.py::request_account_email`
   stores bounded independent challenges instead of replacing the only link.
   Failed sends delete their own challenge; completion invalidates siblings.
   Regressions cover failure, sibling consumption, capacity and expiration.
6. **Fixed locally P2; deployment verification pending — operator SSH.**
   `Dockerfile` now creates a non-root home, shell and private .ssh directory.
   Verify Render operator SSH before relying on grant-credits in production.
7. **Open P1 — Render client-IP attribution.** `render.yaml` uses Docker without
   a verified trusted proxy setup. The default Uvicorn proxy trust can group users
   behind the Render edge into a shared auth bucket. Verify ingress/header
   behavior and configure/test trust before release. Do not blindly trust spoofable
   forwarded values. See RENDER_MODAL_LAUNCH.md.
8. **Open P2 — review size.** PR #2 at `02c3a6b` has 2,134 changed text
   lines across 51 files (1,478 excluding README/docs). The smallest coherent
   first stage is schema v9 plus isolated migration-preservation coverage
   (roughly 45–50 lines). Follow with separate verified-signup/email and password
   recovery/credential-invalidation stages, each below 500 complex lines. Keep
   the independent Modal deadline as its own stage, then operator/deployment
   integration. Public-shell helpers must precede or accompany account UI:
   `/account` calls `document()` and requires the `account.html` allowlist entry.
   Public/workspace polish and UX evidence can follow. These are proposed review
   stages; PR #2 remains a combined draft and has not been split or merged.

Reviewed locations (paths relative to `unrender/product/`): account lifecycle
`service.py`, credential routes `web.py`, schema `database.py`, frontend
`static/app.js` and `static/site.js`; repository `Dockerfile`, `render.yaml`, and
`tests/test_accounts.py`. Line numbers move with fixes; final review must use the
final commit. No GitHub review comments have been posted.

Supplemental provider-deadline review found no concrete correctness issue in
`unrender/product/extractors.py` and its worker/canary regressions. The reviewer
also exercised the installed Modal SDK async bridge without network access;
local cancellation and repeated worker-thread calls drained correctly. This
closes local deadline behavior only; real provider cancellation and Render
termination timing remain required deployment checks.

9. **Open P1 — base-image vulnerability assessment.** `Dockerfile:13` pins a
   Debian base with 18 distinct high/critical advisories in the September 10
   Trivy scan. Package presence does not establish exploitability, but vendor and
   reachability assessment remains outstanding. See CONTAINER_SCAN.md for all
   advisories. Removed unused inherited installer packages at `Dockerfile:43`,
   resolving the scan's Python findings. Supplemental read-only review found no
   runtime dependency on those installers and no issue with explicit AMD64 CI.

Base-image follow-up: all 18 high/critical advisories now have an initial
source/vendor assessment in CONTAINER_SCAN.md. Seven have artifact-specific
component/architecture exclusions; eleven have no observed application route but
retain operational assumptions requiring deployed verification. This narrows
finding 9; it does not close it or suppress the scanner results.


## Published PR review follow-up

10. **Fixed P2 — concurrent legacy-password upgrade** (`service.py`, authenticate).
    A losing conditional rehash now reads and verifies the winning hash while
    rejecting a changed session generation; session creation still fences on
    the exact validated hash. Two simultaneous valid logins now both succeed.
    The existing reset-versus-login regression still rejects the old password.
11. **Fixed P2 — logout blocked by login limits** (`web.py`, auth grouping).
    Logout remains under general request limits but no longer shares the
    credential-attempt rate/concurrency group. Regression exhausts login attempts,
    successfully logs out with CSRF, and verifies the session is gone.

The context review found no applicable model-context changes. The testing review
found no additional defect but retained live SMTP, browser account-flow and
Render/Modal verification limits. All reviewer findings are recorded here;
code review is not deployment approval.

## September 10 final pass and deployment inventory

12. **Fixed P2 — initial job-list recovery** (`unrender/product/static/app.js:728`).
    Successful list initialization is tracked separately from the authenticated
    principal. Focus retries failed initialization without replacing an active
    upload. The Node regression exercises both failure recovery and picker focus.
13. **Fixed P2 — file selection during upload** (`unrender/product/static/app.js:1055`).
    The picker is disabled during upload and restored/reset on completion or
    private-state clearing, preventing silently discarded selections.
14. **Fixed P3 — verification KDF writer lock** (`unrender/product/service.py:992`).
    Password verification occurs before the write transaction; the transaction
    rechecks the live challenge and exact hash/generation. A regression performs
    a concurrent write during verification and verifies stale credentials fail.
15. **Fixed P2 — SMTP occupies authentication admission** (`unrender/product/web.py:215`).
    Email requests have a separate one-request slot. Registration holds the shared
    KDF slot only through account creation, then sends mail after releasing it.
    Slow-mail regressions cover registration, resend, and recovery while login
    succeeds and excess email requests receive 503.
16. **Fixed P3 — schema rollback instructions** (`docs/OPERATIONS.md:88`).
    The release uses schema 9; rollback to schema 8 requires the pre-v9 recovery set.
17. **Open change-size concern**: reviewed baseline 4bf1352 changes 2,354 text
    lines across 52 files (1,638 excluding README/docs). Smallest first stage is
    schema v9 and its v8 preservation test (~45–50 lines), followed by account
    verification, recovery/revocation, provider deadline, browser integration,
    deployment/operator integration, and visual/documentation stages. Existing
    PR remains draft. Context review found no new model-context injection.

Created Render project `UNRENDER` with a `Production` environment:
https://dashboard.render.com/project/prj-dahh1gbl550s73840e5g
The service was subsequently deployed there; current status is in RENDER_MODAL_LAUNCH.md. Wayline remains separate. No shared billing
settings were changed. Modal's September workspace billing summary showed $0
billed and $3.04849077 metered before adjustments; this is shared-workspace
history, not a project cap or forecast.

The earlier absolute $20 ceiling was superseded by the user's clarification:
a $20 target with modest overages is acceptable. No combined provider-enforced
project cap is claimed. Email delivery is deferred; real model canaries have
passed. Deployment gates and current evidence are tracked in RENDER_MODAL_LAUNCH.md.

18. **Fixed P2 — cancellation released admission while work continued**
    (`unrender/product/web.py:190`). A shielded task now owns the acquired slot
    until actual completion; cancelling its caller does not free capacity early.
    This applies to both the middleware and registration KDF. A real-thread
    cancellation regression verifies admission stays occupied until completion.

Follow-up validation: 188 passed / 1 skipped before the cancellation change;
all 15 account tests including cancellation passed afterward. Formatting and
lint match CI. The previous commit's CI failure was formatting-only and is fixed
in this follow-up. These are local evidence, not live SMTP/provider verification.

## Private Modal release review

19. **Fixed P2 — publisher retry persistence** (`scripts/publish_modal_release.py:67`).
    The volume commit now runs for both a new release and an already verified
    target, so retrying after an ambiguous commit attempts persistence again.
20. **Fixed P2 — default app identity mismatch** (`unrender/product/config.py:91`).
    Defaults, environment example, README, and Render configuration now select
    `unrender-production`. Deploy explicitly with
    `modal deploy modal_train.py::production_app`; research remains separate.
    Private Hub users must explicitly name their existing secret with
    `UNRENDER_HF_SECRET` when deploying.

The reviewer found no concrete bypass in the descriptor-checked copy, inspected
SHA-256 comparison, read-only verification, and rename sequence. Focused tests
reject mismatched revision/digest and tampered release contents.
CPU-only publication completed successfully in Modal run
`ap-RkfwH2s4N8OiiiNA2eezXZ`, returning `private_release_verified` for digest
`3954f3395a9db64fcbd3b9dc94508ab0cf9af2f5f2156643504881ee712e8c7e`.
This establishes a committed private artifact, not inference quality or latency.

21. **Fixed P2 — scorer imported during inference startup**
    (`unrender/eval/__init__.py:9`). Live canary failed on missing `rapidfuzz`.
    Scoring exports now load lazily; provider import works without scorer extras.
    A subprocess regression hides rapidfuzz and verifies independent inference import.
22. **Fixed P2 — missing Qwen processor dependency** (`modal_train.py:68`).
    Live canary required Torchvision. The inference image now pins torchvision
    0.24.1 alongside the officially paired torch 2.9.1.

The deployed model subsequently returned valid schema data with no parse errors:
first call 91.29 seconds, immediate repeat 51.84 seconds, identical provider release
`9435fb6f0b24068f7006401fd44d49e3a925330267dfb2302156eb677104b08d`.
The Render template now pins this observed release and the verified private model.
Numerical readings still need review (for example the model returned 9.0 for
Q1 2017 where the saved sample reference is 9.8). This single low-resolution chart
is operational evidence, not a representative accuracy benchmark. Tokenizer regex
and truncation warnings appeared; no automatic tokenizer change was made that
would silently alter the trained release's preprocessing.

The full local production-configured HTTP flow also passed using the real remote
model: operator provisioning and sign-in, upload, inference (48.26 seconds),
correction of Q3 2016 from 9.0 to 9.2, approval, CSV/JSON/XLSX exports, workbook
audit-sheet presence, logout, application restart, re-login, and approved-job
persistence. Evidence is in `outputs/local-verification/live-product-flow/report.json`
and its exported files. TestClient's HTTPS URL is simulated; this does not prove
Render TLS, proxy attribution, disk ownership, or externally reachable production.

Latest completed CI at b164f77 passed both verification and container builds.
Modal billing reported $0.07880970 of UNRENDER app compute for the day at the
observation time, before credits and excluding storage and reporting delay.

## Hosted deployment findings

23. **Fixed P1 — Render disk-root ownership** (`render.yaml:17`). The mounted
    root is platform-owned, so chmod correctly failed under UID 10001. Configure
    `/data/unrender` inside the persistent disk. The app owns that directory and
    retains mode 0700; no permission checks or non-root execution were weakened.
24. **Removed invalid deployment assumption; restart path verified**
    (`render.yaml:8`). Render rejects custom shutdown grace on disk-backed
    services. Removed `maxShutdownDelaySeconds: 300`. Drain jobs before planned
    deploys; the subsequent hosted in-flight restart test verified retained spend
    without redispatch. Other timeout/cancellation scenarios remain separate.

Render's Blueprint validator accepted the updated configuration. Live HTTPS
readiness reports the Modal extractor and running worker. Non-root SSH and
provider contract resolution from Render passed. Current details and remaining
public-launch limits are in RENDER_MODAL_LAUNCH.md.

25. **Fixed P2 — stale backup path** (`docs/OPERATIONS.md:50` at review). The
    backup example now inherits the actual configured data directory rather than
    overriding it with the platform mount root. Updated mount ownership guidance.
26. **Fixed P2 — incompatible shutdown runbook** (`docs/OPERATIONS.md:14` at review).
    Replaced the unsupported grace requirement with the Render disk limitation,
    planned-drain procedure, and explicit forced-termination recovery gate.
27. **Fixed P3 — inaccurate displayed-quota claim**
    (`docs/RENDER_MODAL_LAUNCH.md:112` at review). Storage quotas are described as
    server-enforced; only upload/image/PDF limits are described as UI-visible.

28. **Fixed and verified on Render P1 — lease expires after worker startup**
    (`unrender/product/worker.py:60`). A real Render restart left a dispatched job
    running after its lease expired because recovery ran only during startup.
    The worker now revisits transactional, fenced recovery between jobs at the
    heartbeat cadence. Active leases stay untouched; expired dispatched attempts
    retain spent credits and cannot automatically redispatch. A regression expires
    the lease after the first new-worker poll and verifies terminal state, no
    second provider call, and one charged attempt. Hosted re-verification passed
    after deployment. This cadence is not a strict deadline while another job runs.

Hosted initial canary passed in 82.89 seconds with secure HttpOnly session cookie,
upload, correction, approval, CSV/JSON/XLSX and audit sheet. Coordinated backup
and isolated restore both retained the approved job and source; SQLite integrity
checks passed. A private recovery archive was copied to the operator machine.
This is one manual backup, not a scheduled backup service or recovery SLA.

Focused follow-up reuse/breaking, quality/testing, and efficiency/context/size
reviews found no additional issue in the periodic recovery change. Full local
validation passed: 194 tests, 1 skipped; Ruff, mypy (15 product files), and
Blueprint validation passed. Starlette's TestClient/httpx deprecation remains.

Live runtime `12043ac` passed the repeated dispatched-job restart test in 70.08
seconds: terminal `worker_lease_expired_after_dispatch`, attempt count one, credit
retained, approved prior job and all exports preserved. The failed diagnostic
jobs were removed afterward; the approved sample remains in the invited account.
The provider release is unchanged. No provider- or account-wide billing cap was
changed. Repository reports contain no login/provider secrets.

29. **Fixed P1 — lifecycle records absent from server log configuration**
    (`unrender/product/cli.py:16`). Uvicorn now installs a dedicated INFO-level
    product logger on stdout. The JSON formatter retains only operational fields
    and exception type; arbitrary extras and exception text/tracebacks are omitted.
    A subprocess entrypoint regression covers actual log configuration, not only
    records captured by pytest's configured logger. Hosted verification passed on `e09a8f1`: the owned-chart canary reached review in
    76.7 seconds and Render emitted both start and provider-success JSON records.
30. **Fixed P2 — reserved logging test attribute**
    (`tests/test_product.py:3871` at review). All three reviewers identified that
    `filename` cannot be supplied through LogRecord extras. The sensitive synthetic
    field is now `source_filename`, allowing the privacy assertions to execute.
31. **Fixed P2 — formatter lint rule**
    (`unrender/product/observability.py:13` at review). Changed timezone.utc to
    datetime.UTC to satisfy the repository's enforced UP017 rule.

Reuse/breaking, quality/testing, and efficiency/context/size review found no
remaining runtime defect in the logging change. Current event call sites use
constant messages; the formatter deliberately does not interpolate log arguments.

32. **Fixed P2 — private link publication could fail after account commit**
    (`unrender/product/admin.py:106` at review). Reuse/breaking and quality/testing
    reviewers both reported this. The operator publication callback now writes,
    flushes, and syncs before the surrounding account/challenge transaction commits.
    Failure rolls back account creation or challenge replacement; the CLI removes
    the incomplete file. Regression verifies no orphaned account and preservation
    of the previous working link. Follow-up review found no further defect.

Invitation checks cover activation, one-use consumption, reissue invalidation,
password strength, persistence across service recreation, session revocation,
atomic failure, private output permissions, and prevention of file overwrite.
Efficiency/context/size review found no actionable issue.

Invitation release `437322d` passed the full local suite (199 passed, 1 skipped),
Ruff, mypy, and JavaScript syntax checks. Render deployed it successfully. Hosted
HTTP activation, single-use rejection, logout/relogin and cross-tenant isolation
passed without SMTP or GPU usage. Interactive invitation form verification remains
separate from these API checks.

33. **Fixed P2 — account help offered unavailable email delivery**
    (`unrender/product/static/account.html:8` at discovery). The account page now
    consults public configuration and directs invited users to their inviter when
    email is disabled. Valid setup/recovery tokens still work without SMTP.
34. **Fixed P2 — token pages hid available recovery actions**
    (`unrender/product/static/account.js:40` at review). Quality review found that
    fetching configuration only for no-token pages hid resend/recovery links after
    expired token errors. Configuration now controls help links on all pages;
    fetch failure cannot disable token completion.
35. **Fixed P1 — anonymous session check erased sign-in input**
    (`unrender/product/static/app.js:118`). Real Chromium activation succeeded but
    sign-in submitted nothing: a delayed anonymous `/api/me` 401 reset the form.
    The 401 now preserves input only when no principal and no durable auth record
    exist. Existing epoch/context fences and authenticated-session quarantine stay
    intact. Local frontend with the hosted backend passed activation, immediate
    sign-in, and reload persistence; no GPU was used.
36. **Resolved P2 — startup gating could drop cross-tab restoration**
    (`unrender/product/static/app.js:751` in the discarded draft). All three
    reviewers found this. The draft suppression could abort boot reconciliation
    and discard its replacement. Removed startup gating entirely in favor of the
    anonymous-401 correction in finding 35; coordination paths are unchanged.
37. **Resolved P2 — late pageshow escaped startup gating**
    (`unrender/product/static/app.js:756` in the discarded draft). Breaking review
    identified that late image loading could deliver pageshow after boot, allowing
    another anonymous 401 to erase input. Removing the unnecessary anonymous wipe
    fixes the case regardless of event timing.

Node regressions cover anonymous input preservation, existing cross-tab privacy,
email availability states, token completion during config failure, and email help
on token pages. Recovery configuration tests now run in CI.

Hosted `914c55c` passed Chromium setup/recovery completion, immediate sign-in,
and session persistence after reload. The new no-email help state also passed in
the hosted browser. No page JavaScript exceptions occurred; expected anonymous
401 network responses still appear in developer tools. All three Node suites and
nine focused public/static tests passed.

38. **Fixed P1 — default Modal readback could exhaust instance memory**
    (`unrender/product/scheduled_backup.py:44` at review). All three reviewers
    identified whole-block prefetch based on host CPU count in Modal 1.5.5. The
    backup downloader uses the pinned SDK's file streaming method with concurrency
    one and a bounded writer; a real v1 Volume round trip verified this contract.
39. **Fixed P2 — stalled network transfer prevented future backups**
    (`unrender/product/scheduled_backup.py:136` at review). Quality and efficiency
    review identified the missing SDK deadline. Each scheduled attempt now runs
    in a child process with a 600-second deadline, kill/reap on timeout and
    termination on application shutdown. Failure allows the next hourly retry.
40. **Fixed P2 — archive limit was enforced after oversized local copying**
    (`unrender/product/scheduled_backup.py:74` at review). Snapshot preflight under
    the exclusive lock accounts for SQLite pages, committed source sizes, archive
    metadata headroom and three temporary copies. Oversized/low-space snapshots
    fail before copying; archive creation and download also enforce one GiB.
41. **Fixed P2 — local status failure replaced daily recovery history**
    (`unrender/product/scheduled_backup.py:122` at review). A recent remote copy is
    verified and reused before new uploads; verified success is also remembered
    in memory when publishing the local status file fails. Regression forces the
    status write failure, recreates the scheduler and verifies only one upload.
42. **Fixed P2 — automatic snapshot lock caused unhandled live request failures**
    (`unrender/product/scheduled_backup.py:74` at review). Breaking review identified
    contention with live mutations. Maintenance admission returns a retryable 503
    with Retry-After before entering routes; lock-timeout races also map to 503.
43. **Fixed P2 — non-API paths still entered the database rate limiter**
    (`unrender/product/web.py:475` at review). The first maintenance probe covered
    only /api; page/static/readiness requests could still wait then return 429.
    The probe now covers every path except the inexpensive liveness route.
44. **Fixed P2 — terminated child left partial backup files behind**
    (`unrender/product/scheduled_backup.py:174` at review). The parent owns the
    temporary workspace and removes it after the child is terminated and reaped.
    Regression leaves a partial child file and verifies deadline cleanup.

45. **Fixed P2 — snapshot could enter between admission probe and rate limiting**
    (`unrender/product/web.py:445`). All three reviewers identified the remaining
    race. The shared operational lock now covers the entire rate-limit transaction
    in the thread pool. A regression attempts an exclusive lock inside admission
    and verifies it cannot enter.
46. **Fixed P1 — multipart upload budget used host memory on a 512 MiB instance**
    (`unrender/product/scheduled_backup.py:212`). Breaking review identified Modal
    v1's host-derived upload budget. Only the isolated backup child sets the pinned
    SDK budget to 64 MiB. A subprocess contract test verifies one in-flight segment
    and unchanged parent SDK settings.
47. **Accepted size guidance — scheduled recovery spans more than 500 lines**
    (`unrender/product/scheduled_backup.py:1`). Efficiency review suggested staged
    commits for backup primitives, scheduling, tests and documentation. This is one
    optional recovery feature with coupled admission and SDK memory regressions;
    it remains together so the committed feature includes its tests and operating
    instructions. No unrelated refactor is included.

Backup validation: 210 tests passed, 1 skipped; Ruff and mypy across 17 product
files passed. A real Modal v1 test volume accepted the backup, bounded readback
matched its SHA-256, and isolated restore passed SQLite integrity plus account
and source checks. The disposable test volume was deleted.

Production runtime `bf5da14` enabled the daily scheduler on September 10. Its first
409,600-byte archive reached the private `unrender-production-backups` volume,
passed readback SHA-256, and emitted `scheduled_backup_succeeded`. An independent
download and isolated restore passed SQLite integrity/foreign keys, preserved the
approved chart and source hash, and regenerated CSV, JSON and XLSX with its audit
sheet. No GPU call or live-data modification was used for this restore drill.
Evidence: `outputs/local-verification/offhost-backup/production-report.json`.
Alert delivery and measured recovery objectives remain open.

48. **Fixed CI security-lint failure — runtime assertion in backup status handling**
    (`unrender/product/scheduled_backup.py:153`). GitHub CI rejected the runtime
    assertion under S101, a check omitted from the earlier local validation.
    Commit e497a18 replaces it with an explicit RuntimeError check. Security lint,
    formatting, mypy and all 13 focused backup tests pass locally. Earlier local
    Ruff success did not establish success of the full CI security-lint step.

Proxy review found that Render's current guidance recommends X-Forwarded-For,
but its [older feedback thread](https://feedback.render.com/features/p/send-the-correct-xforwardedfor)
contains conflicting observations about client-supplied prefixes. Its current
[private-network documentation](https://render.com/docs/private-network) also
confirms that services in the same workspace and region share private ingress.
No unconditional forwarded-header trust was added. Header rewriting and direct
ingress still need hosted verification before changing rate-limit attribution.

49. **Fixed P2 — frozen pilot fixtures could be overwritten**
    (`scripts/build_launch_eval.py:62` at review). Efficiency review found that
    regeneration replaced existing images and hashes in place. Generation now
    stages a complete set and refuses byte differences for an existing version.
    Isolated checks passed first publication, identical rerun and changed-manifest
    refusal without mutation. The final reuse/efficiency recheck was clean.
50. **Fixed P2 — Git ignored the frozen input PNGs**
    (`.gitignore:22`; `release/launch-eval-v1/manifest.json:9,52,101`). All three
    reviewers found that ordinary staging omitted the images. A narrow exception
    includes only this version's PNGs. Independent visual review confirmed all 15
    values, categories, axes, legend, dimensions and source hashes. The set uses
    the research renderer and is explicitly synthetic operational evidence, not
    representative accuracy or human correction-time evidence.

The final saved-output review found no numerical inconsistencies: 15 values match
exactly, with no extra points or series. It noted two null single-series names
(already reflected in name F1) and that client timing observations cannot be
reconstructed from the initial artifact alone. The report distinguishes numeric
exactness from JSON equality and adds separate read-only server timing/attempt
receipts; it does not claim independent reconstruction of client timings. All
three production attempts reached review without retry, and human correction
time remains unmeasured. CI passed on fixture commit `653e8af`.

51. **Fixed P3 — provider log memory units could be mistaken for configuration**
    (`docs/LAUNCH_EVALUATION.md:89` at review). The latency investigation initially
    repeated the log's `32.8GiB` label as the configured requirement. It now quotes
    that label explicitly and separately records the SDK setting, 32768 MiB
    (32 GiB). Read-only review found the three timing rows consistent with the
    supplied Modal observations and stored dispatch timestamps. Queue intervals
    are 5, 0 and 108 seconds at UI precision; execution remains distinct from
    GPU-only time, and fixture attribution is by timestamp rather than call ID.
