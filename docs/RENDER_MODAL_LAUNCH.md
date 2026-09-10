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

`render.yaml` declares one Docker web service, 2 GB memory, a 20 GB persistent disk
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

1. Render authentication is confirmed in Dia (workspace "My Workspace", no
   services yet). Confirm domain, region, spending cap and repository connection
   during setup. The in-app browser has a separate unauthenticated session.
2. Authenticate Modal, locate/publish the exact approved trained model, verify
   complete snapshot and provider digests, deploy the real function and run owned
   chart canaries. No configured Modal profile was available in this local run.
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
remaining changes, and PR creation remain work. Source magnification, zero-credit onboarding, and a retention notice are implemented locally; final responsive verification remains in this workstream. Existing default chart retention is 30 days; persistence across
restarts does not mean indefinite retention.

Current preparation branch: `codex/render-modal-productization`. Changes remain
uncommitted; no PR or Render service has been created. Native-browser navigation
needs a brief uninterrupted session because concurrent user activity changes the
active tab. Modal CLI remains unauthenticated.
