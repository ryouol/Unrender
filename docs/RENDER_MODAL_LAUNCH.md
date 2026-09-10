# Render + Modal launch

This is the productionization workstream, not a completed deployment. Use the
Documents/Codex working checkout; the Desktop copy remains separate.

## Product behavior

Public production signup is enabled only with TLS email delivery and zero welcome
credits. A customer creates an account, verifies their email with their signup
password, signs in, and receives their persistent private workspace. The operator
can grant credits with `unrender-admin grant-credits email --credits 25 --reference
pilot-001`. Repeating the same reference does not grant twice. Billing remains off.

Account recovery emails use 30-minute, hashed, single-use links; up to five
outstanding links per purpose are allowed so failed/reordered resends do not
invalidate already-delivered links. Completion invalidates sibling links. Reset
revokes sessions and API keys while preserving charts, corrections and exports.
Credential issuance is fenced against concurrent password resets. Existing v8
accounts retain access after the additive v9 migration.

Local signup can be tested using `scripts/run_local.sh` (development replay only).
Production email verification is exercised by integration tests with captured
mail transport, not by delivering messages to real people.

## Deployable shape

`render.yaml` declares one Docker web service, 512 MB memory, a 1 GB persistent disk
at `/data`, public production registration with verified email, a Modal provider,
and a 300-second shutdown grace period. Automatic deployments are disabled until
final review, backup and canary gates pass. The template has not been applied to
Render and no recurring spend has been created.

Use Render's secret/environment fields for all `sync: false` values. The public
base URL must be the actual HTTPS origin; never use a guessed domain. Credentials
belong in Render/Modal secret management, never a commit, report, or Roy-OS note.
Required values:

- `UNRENDER_BASE_URL` (the real Render/custom origin)
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`
- `UNRENDER_MODAL_MODEL`, revision, full snapshot digest, approved provider release
- `UNRENDER_SMTP_HOST`, username, password, and `UNRENDER_EMAIL_FROM`
- SMTP port 587 (STARTTLS) or 465 (TLS), using a verified sender domain

The image has a non-root shell/home/.ssh directory for Render operator access.
The platform still must verify persistent-disk ownership for UID/GID 10001.
Provision disk ownership through supported platform tooling; do not run the
application as root to work around a mount error.

## Required external checks before release

1. Render authentication and the GitHub repository connection are confirmed in
   the in-app browser (workspace "My Workspace"). The creation form is prepared
   for manual deployments. The user approved US$7.25/month on September 10:
   Starter compute ($7) plus a 1 GB private disk ($0.25). The browser form was
   last verified on Free without a disk and still needs updating before creation.
   Activation awaits complete configuration and capacity verification.
2. Authenticate Modal, locate/publish the exact approved trained model, verify
   complete snapshot and provider digests, deploy the real function and run owned
   chart canaries. The `royluo05` CLI profile is authenticated; the workspace app list has no
   UNRENDER deployment as of September 10. Read-only volume inspection found
   `unrender-vol/runs/qwen3vl4b-table-fair/merged`, including two safetensors
   shards (about 8.2 GiB total), tokenizer and processor files. File presence is
   not a verified immutable release or a quality result.
3. Verify email delivery and sender authentication with an authorized test inbox.
4. Resolve trusted-proxy client-IP attribution. Docker does not get Render's
   Python-runtime environment defaults. Do not blindly trust arbitrary forwarded
   headers: verify the Render edge's header rewriting and direct-ingress boundary,
   then configure/test the trusted proxies so separate users do not share one
   authentication bucket and spoofed headers cannot bypass limits.
5. Verify provider shutdown on the deployed SDK/network path. The app now uses
   a 240-second async deadline covering lookup, queueing and result retrieval,
   inside Render’s 300-second shutdown grace. Local regressions cover timeout,
   worker drain, retained spend and no redispatch. Cancellation of the local await
   does not prove remote GPU cancellation: record real queued/running behavior
   and confirm the terminal database commit before a deployment terminates it.
6. Validate the Blueprint with Render; build/scan and deploy the reviewed image.
   Verify health routes, private volume, signup/signin, reload/restart persistence,
   reset revocation, real inference, review, approval and all exports.
7. Schedule coordinated off-host backups and test restore from the selected
   backup service. A Render disk snapshot alone is not the app's coordinated
   database/file backup contract. Test alert delivery and outage/quota behavior.
8. Supply reviewed operator/support/privacy/terms and model/data rights decisions.
9. Run intended-input quality and correction-time evaluation before launch claims.

Sources: https://render.com/docs/blueprint-spec,
https://render.com/docs/environment-variables, https://render.com/docs/ssh.

## Scope still pending

Real Render and Modal deployment, SMTP provisioning, published legal/operator
content, provider evaluation, complete deployment regression, final review after
remaining changes, remain work; draft PR #2 is open. Source magnification, zero-credit onboarding, and a retention notice are implemented locally; final responsive verification remains in this workstream. Existing default chart retention is 30 days; persistence across
restarts does not mean indefinite retention.

Current preparation branch: `codex/render-modal-productization`, published in
[draft PR #2](https://github.com/ryouol/Unrender/pull/2). No Render service has
been activated. Use the isolated in-app Render tab: native Dia window targeting
was unreliable. Modal CLI authentication is verified for `royluo05`; email/domain choices and
production secrets remain outstanding.

## Small-instance capacity gate

The September 10 budget configuration limits each upload to 10 MiB, images to
4 megapixels, global accounted storage to 500 MiB and per-user storage to 50 MiB, and both
authentication and expensive-request concurrency to one each. The existing
256 MiB minimum-free-space and 128 MiB database-headroom settings remain in force.
The upload screen reads its limits from the server configuration.

These limits are a starting configuration, not proof of 512 MB suitability.
A Docker check with 512 MB RAM, no swap and half a CPU was started, but its
process handle disappeared after a tooling reconnect and Docker became
unavailable. No passing result was recovered. Repeat the constrained run with
signup/signin, allowed-size images/PDFs, correction, exports and overlapping
authentication, expensive HTTP requests and worker activity; verify peak memory and OOM status before activating this plan.
Modal spending is authorized only within the available free credit. The earlier
US$30/month proposal is superseded; do not activate it.

Local validation of this budget change: 14 focused storage/sample/account/public-page
tests passed; JavaScript syntax, Ruff and diff whitespace checks passed. The
production configuration validates with synthetic model/email placeholders.
These checks do not establish live email, model inference or memory capacity.
