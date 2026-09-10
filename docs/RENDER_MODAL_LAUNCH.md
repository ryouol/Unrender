# Render + Modal launch

This is the productionization workstream, not a completed deployment. Use the
Documents/Codex working checkout; the Desktop copy remains separate.

## Product behavior

The current launch is invite-only: public registration and email verification are
disabled in the Blueprint, per the user’s decision to defer email. Provision
accounts through `unrender-admin create-user`; grant credits deliberately. Self-service
email recovery is unavailable until SMTP is configured.

When public signup is enabled later, it requires TLS email delivery and zero welcome
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
at `/data`, operator-provisioned accounts with public registration closed, a Modal provider,
and a 300-second shutdown grace period. Automatic deployments are disabled until
final review, backup and canary gates pass. The template has not been applied to
Render and no recurring spend has been created.

Use Render's secret/environment fields for all `sync: false` values. The public
base URL must be the actual HTTPS origin; never use a guessed domain. Credentials
belong in Render/Modal secret management, never a commit, report, or Roy-OS note.
Required values:

- Render supplies `RENDER_EXTERNAL_URL` automatically. Set `UNRENDER_BASE_URL` only to override it with a verified custom HTTPS origin.
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`
- `UNRENDER_MODAL_MODEL`, revision, full snapshot digest, approved provider release

SMTP credentials are deferred and are not required for the invited-account launch.

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
was unreliable. Modal CLI authentication is verified for `royluo05`; Gmail was selected as the sender on September 10. The Google app password and
production model secrets remain outstanding; do not put credentials in this file.

## Small-instance capacity gate

The September 10 budget configuration limits each upload to 10 MiB, images to
4 megapixels, global accounted storage to 500 MiB and per-user storage to 50 MiB, and both
authentication and expensive-request concurrency to one each. The existing
256 MiB minimum-free-space and 128 MiB database-headroom settings remain in force.
The upload screen reads its limits from the server configuration.

A constrained Docker run completed on September 10 with 512 MiB RAM, no swap
and half a CPU: three rounds of concurrent sign-in, 4 MP image/2200-edge PDF
rendering and replay worker processing, followed by correction, three export
formats and database reopen. It took 28.37 seconds, with 218.1 MiB peak process
RSS and 233,549,824 bytes (222.7 MiB) peak cgroup memory. Exit code was zero and
OOMKilled was false. The harness is retained locally at
`outputs/local-verification/budget-capacity.py`.

This used the existing runtime image with current source mounted read-only.
It called service methods in threads; it did not run the HTTP listener, real
Modal inference or Gmail delivery. The inherited container healthcheck timed
out because the harness replaced the server command. This is a bounded capacity
smoke check, not an HTTP load test or proof of production readiness. Verify the
actual server and real provider under the same limit before launch.
Modal spending is authorized only within the available free credit. The earlier
US$30/month proposal is superseded; do not activate it.

Local validation of this budget change: 14 focused storage/sample/account/public-page
tests passed; JavaScript syntax, Ruff and diff whitespace checks passed. The
production configuration validates with synthetic model/email placeholders.
The focused tests do not establish live email or model inference.


## Private Modal model release

The trained `unrender-vol/runs/qwen3vl4b-table-fair/merged` source was fingerprinted
in CPU-only run `ap-kr4LgnpeEtmGU22BM2zU6I`: 8,891,676,902 bytes, Qwen3VLForConditionalGeneration,
manifest SHA-256 `3954f3395a9db64fcbd3b9dc94508ab0cf9af2f5f2156643504881ee712e8c7e`.
This identifies bytes, not model quality or customer accuracy.

Publish a private read-only copy with:
`modal run scripts/publish_modal_release.py --digest <inspected-sha256>`.
The copier rejects changed source bytes and commits the inference volume. Set
`UNRENDER_MODAL_MODEL=modal-volume/unrender-inference-cache` and set both revision
and model digest to the full inspected SHA-256. Every inference rechecks the
read-only release contents before loading them. No Hub credential is required.

Deploy exactly `modal deploy modal_train.py::production_app`; bare deployment
selects the research app and is not the production deployment. Set
`UNRENDER_MODAL_APP=unrender-production`. The production app exports only inference,
limits GPU containers to one, disables retries, and scales idle compute down after
two seconds. The 240-second function timeout bounds an individual invocation;
these controls are not a dollar cap. Measure cold/warm behavior before launch.
If using the alternative private Hub release, explicitly set `UNRENDER_HF_SECRET`
to the name of an existing Modal secret containing the Hub credential at deploy time.

The user's current budget is a $20 target with modest overages accepted. Keep
one backend instance and bounded inference; leave shared-workspace caps untouched.
