# Render + Modal launch

## Current deployment — September 22, 2026

The cleanup release runs `a7673d90d8c88a639b946ecfe3f1da1f56f81add`, schema 15,
from [PR #13](https://github.com/ryouol/Unrender/pull/13) and
[PR #14](https://github.com/ryouol/Unrender/pull/14). Web and monitor deployments
became live at 00:34:59 and 00:34:52 UTC on September 23. Modal uses tag
`cleanup-6580d79`; model weights are unchanged. The current provider release is
`8ea1e0e748ac7a45232ea2626f0bed97c9fc5d4bca80ef39d878e51f360003d0`.

Maintenance enclosed the final backup and rollout. All original database rows
and four source files matched before deployment and after test-account removal.
Database integrity, foreign keys, public health checks and live source/package
inventory verification passed. The two-minute monitor passed at 00:38:24 UTC
following its maintenance-window failure. Email-delivery latency was not retested.

One isolated L4 canary and one hosted extraction reproduced the four visible
values, title and axes of the labelled bar chart. The hosted request reached
review in 69.73 seconds, used one credit despite repeated submission, and passed
correction, stale-approval rejection, approval, CSV/JSON/XLSX download and re-login
checks. The synthetic account was deleted. These checks do not measure
representative accuracy, capacity or a speedup; the unprinted single-series name
remains null, as recorded in the existing evaluation contract.

Merged-main CI passed: 673 tests, three skips, container and CPU training checks.
The fresh container scan has zero critical/Python findings and 44 high Debian
findings without listed fixes. The [deployment receipt](../release/cleanup-deployment-20260922/deployment.json),
[hosted workflow](../release/cleanup-deployment-20260922/hosted-workflow.json)
and [scan assessment](CONTAINER_SCAN.md) record the evidence. The controlled-beta
limits and independent-review gates remain in [readiness](LAUNCH_READINESS.md).
Documentation-only commits may follow without a runtime redeploy.


## Previous deployment — September 18, 2026

The live beta runs `2bc72d1b7b3b5f153e03ccd19d7de9c5c54077af`, schema 15,
from [PR #11](https://github.com/ryouol/Unrender/pull/11). The application,
`unrender-production/infer_one`, and the two-minute operations monitor are
coordinated. Model weights remain unchanged; the inference runtime now uses
Torch 2.14.0 and Transformers 5.17.0. The verified provider release is
`b0f38e8907a74aa5926dcb6e3a53cbf27259920084eeedcd0fbbfe3505a77886`.

Web deployment `dep-dammi3ou01pc73ar6dgg` became live at 16:39:56 UTC;
monitor deployment `dep-dammi75bedkc73cb7g7g` at 16:39:36 UTC. Submissions were
closed and jobs drained before the final coordinated recovery set
`/data/release-backups/pre-readiness-final-20260918-schema15`. An earlier same-day
backup restored under the new code, upgraded to schema 15 and initialized twice,
with every original table and four source files preserved.

Pre/post deployment and final post-canary cleanup comparisons preserved two
accounts, one session, four charts, eight saved versions, eleven credit-ledger
rows, five provider attempts, three projects, two Google identities and all four
source hashes exactly. Eight old result versions explicitly retain unavailable
historical evidence. All health checks, provider resolution and SQLite/FK checks
passed before reopening. The live 118 application-file hashes, 71 Python package
versions and complete Debian package manifest match the scanned local AMD64 image.
That is inventory verification, not attestation of Render's final image digest.

The isolated L4 check reproduced all 12 reference values, labels and units:
51.05 seconds cold inside the function, 11.06 seconds warm, normal EOS, peak
allocated memory 9.10 GB. A separate hosted extraction reached review in
68.95 seconds including startup and reproduced the same reference exactly. It
recorded one dispatch and one credit consumed despite repeated idempotent
submission. Correction, stale-approval rejection, version-3 approval, three
export formats, re-login persistence and browser workbook download passed.
Unapproved exports correctly identify their review state. The synthetic account
and chart were removed; existing customer data remained identical.

The monitor now runs every two minutes with a 55-second command deadline.
Its maintenance-window check failed, then the 16:42 and 16:44 scheduled checks
passed. Failure-only notifications remain configured; new email delivery latency
was not measured. Worker concurrency remains one. Email and billing remain off.
The fresh container scan has no critical or Python findings; 44 high Debian
findings remain without listed fixes. See [the scan assessment](CONTAINER_SCAN.md).

Branch, PR and merged-main verify/container/training-CPU jobs passed. The
[deployment receipt](../release/readiness-remediation-20260918/deployment.json)
and [hosted workflow receipt](../release/readiness-remediation-20260918/hosted-workflow.json)
contain the observed evidence. These are operational canaries, not a model-quality
benchmark. Independent annotation review, new training/recovery validation and
prospective quality/performance studies remain open in [the plan](AUDIT_REMEDIATION.md).
Later documentation-only commits do not require a runtime redeploy.

## Budget and access

The September 18 operating budget is approximately US$20/month, with modest
overages accepted.
The Render baseline is US$7/month web compute, US$0.25/month for the disk and
the monitor's US$1/month minimum: approximately US$8.25/month before Modal
compute/storage, taxes and any Render usage overages. The two-minute monitor
is billed for active execution time; its full-month cost has not been measured.
This is not a provider-enforced dollar cap.
[Render cron billing](https://render.com/docs/cronjobs) charges for active time
with a minimum of US$1/month per cron service.

Public Google and password registration include three welcome credits. Customer
billing and email delivery remain off. Account activation is separate from
mailbox verification; see PUBLIC_ACCOUNTS.md. The invitation commands remain
available for operator-provisioned access without email sending.
Grant credits deliberately with `unrender-admin grant-credits email --credits N
--reference pilot-001`; repeating the reference does not grant twice. Operator
recovery links are supported; self-service email recovery remains deferred.

Modal's dedicated `unrender-production` app allows one L4 container, zero automatic
retries, a 240-second function timeout, and a 120-second idle scale-down window.
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
digest both equal the full SHA-256. Cold loads verify the read-only snapshot
contents. Only the exact already-loaded model objects may reuse verification;
replacement, eviction or a different release forces verification again.
No Hugging Face credential or public model upload is needed.

Production app: https://modal.com/apps/royluo05/main/deployed/unrender-production

Deploy explicitly with `modal deploy modal_train.py::production_app`; the bare
module selects the separate research app. Approved provider release:
`8ea1e0e748ac7a45232ea2626f0bed97c9fc5d4bca80ef39d878e51f360003d0`.
All release pins are in `render.yaml`. The dedicated Modal API token is stored
in Render's private environment. Never copy credentials into git or reports. Render supplies the HTTPS origin through `RENDER_EXTERNAL_URL`.

## Operations and history

Use the [operations runbook](OPERATIONS.md) for configuration, backups, rollout and rollback. The [archived launch record](archive/RENDER_MODAL_LAUNCH.md) preserves earlier deployments and checks. Current open work is listed in [readiness](LAUNCH_READINESS.md).
