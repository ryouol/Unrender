# Public accounts with email deferred

This release allows people to create a password account and sign in immediately,
while extraction access remains controlled through credits. Account activation
and verified email ownership are separate states. A password signup without an
email challenge must never mark the supplied address verified.

## Production settings

Use the production environment and the pinned Modal release. Keep the existing
HTTPS, private persistent storage, request quotas, provider deadline and single
worker safeguards. The account settings for the email-deferred beta are:

```text
UNRENDER_ALLOW_REGISTRATION=true
UNRENDER_REQUIRE_EMAIL_VERIFICATION=false
UNRENDER_INITIAL_CREDITS=0
UNRENDER_SEED_DEMO=false
```

Leave SMTP and Stripe configuration empty. Do not enable development mode or
replay to open registration. No account creation, sign-in or visit to the
illustrative landing-page example invokes Modal.

New accounts start with zero extraction credits. Uploads require available
credits and are rejected before file storage when the allowance is exhausted.
The signup page explains this before submission. The empty workspace disables
upload actions and links to the illustrative example; it does not present a
purchase flow while billing is unavailable. Grant credits deliberately through
the running service's trusted admin shell:

```bash
unrender-admin grant-credits analyst@example.com --credits 1 --reference beta-access-001
```

Use a unique, stable reference for each intended grant; repeating a reference
does not grant twice. Check the recipient against the person receiving access.
Refresh the signed-in workspace after a grant. One extraction attempt consumes
one credit once dispatched to the provider, including a dispatched failure.
Credit controls bound application-authorized extraction attempts; they are not
a dollar cap on the shared Render or Modal account.

## Access and recovery

Signup tells people to save their password and explains that lost access may be
unrecoverable while email recovery is unavailable. The account-help page remains
accessible and does not assume that a public signup had an inviter.
The owner approved `royluo05@gmail.com` as the public support contact. Account
help and the zero-credit workspace link to the contact page, which provides a
mailto link for account assistance and requests for extraction access. This
does not configure SMTP or send any messages automatically.

An operator may issue a one-use recovery link through the existing
`unrender-admin account-link` command only after independently establishing
ownership of the workspace. Receiving a request from, or proving control of,
the unverified email address originally entered at signup is not sufficient:
someone else could have entered that address. Do not issue a recovery link when
ownership cannot be established. Deliver authorized links privately, keep their
mode-0600 files out of logs and source control, and delete them after delivery.
See [OPERATIONS.md](OPERATIONS.md) for the command and expiration behavior.

Enabling email later must not grant mailbox holders reset access to existing
active, unverified workspaces. Verification requires both the email challenge
and the account's current password. A self-service password reset is eligible
only after verified email ownership has been established. Operator recovery
activates the account and changes its password; it does not by itself verify
mailbox ownership.

## Persistence and release checks

Accounts, chart sources, saved corrections, approvals and export records remain
on the private persistent disk across sign-out, process restarts and compatible
deployments. Chart retention is still 30 days after the last update by default;
this is not indefinite storage. Users should download exports they need to keep.
Deletion and retention cleanup remove live chart data according to the configured
policy. Coordinated backups and their retention are separate from live storage.

Before deploying the new account schema, close ingress, drain active jobs and
take a coordinated recovery set. An older image that cannot read the upgraded
schema requires restoration of the pre-upgrade recovery set into a new volume;
switching only the code back is insufficient.

Schema 10 preserves legacy login/session access in `account_active`, but clears
the old `email_verified` flag because earlier releases also set it for operator
activation without mailbox proof. Existing accounts keep their data and credits.
If email recovery is enabled later, legacy users must verify their mailbox again
using both the email challenge and their current password. Existing operator
setup links remain usable; they activate access without verifying a mailbox.

Verify the deployed configuration, then create a fresh account through `/signup`,
sign out and sign back in. Confirm the account remains unverified, has zero
credits, cannot upload or buy credits, and can open the illustrative example.
An unrelated account must not see any existing charts. Verify an existing
approved chart and its exports survive the deployment without spending an
inference credit. Record actual deployment and hosted checks in
[RENDER_MODAL_LAUNCH.md](RENDER_MODAL_LAUNCH.md); source tests alone do not prove
that production has these settings.
