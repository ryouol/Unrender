# Google sign-in

Google authenticates identity; UNRENDER retains its existing private accounts, native
cookie sessions, chart ownership and credit ledger. This adds no hosted auth database
and makes no inference calls. Every new Google account starts with zero credits,
including in development. Returning users retain their existing allowance.

## Deployment configuration

Create a dedicated UNRENDER **Web application** OAuth client in a personal Google
Cloud project, with the UNRENDER app name, approved logo, support address,
homepage/privacy/terms URLs and intended external audience. Do not reuse Wayline's
client secret or alter unrelated project clients.

Set `UNRENDER_GOOGLE_CLIENT_ID` and `UNRENDER_GOOGLE_CLIENT_SECRET` together in the
UNRENDER Render service's private environment. Empty values disable Google sign-in;
partial or invalid configuration fails startup. Neither value is sent through public
configuration. No SMTP credentials or email delivery are required.

Register this exact production callback:

`https://unrender.onrender.com/auth/google/callback`

For local verification, use a separate development client and register the exact
loopback origin used by `UNRENDER_BASE_URL`, for example:

`http://127.0.0.1:8000/auth/google/callback`

Only `openid email profile` scopes are requested. No offline access, Gmail scopes,
Google API access-token persistence, refresh tokens, or automatic credit grants.
The application controls account creation through `UNRENDER_ALLOW_REGISTRATION`;
closing registration does not prevent an already connected Google identity signing in.
Google Testing status alone is not an access gate for these basic identity scopes.
Publish/verify the Google app's brand for the intended public experience.

## Browser integration contract

`GET /api/public-config` adds `google_available`. `/api/me` adds `has_password` and
`google_connected`. Show the Google links/dividers only when available. Use the
included official Google G with its aspect ratio preserved; the parent UI supplies
the neutral button layout. Google-only users recover access through Google.

The browser has a durable cross-tab sign-out barrier. To begin an explicit Google
login, generate a random nonce (16–128 URL-safe characters), save it and the current
canonical auth record in sessionStorage, and visit `/auth/google/start?intent=...`.
The server binds this intent to its one-use OAuth attempt and then to the newly
created native session. The callback redirects to `/app` without credentials.

Before clearing any sign-out barrier, require the saved canonical record still to
match; POST `/api/auth/google/complete` with `{ "intent": "..." }` and the session's
CSRF header. Until completion, the pending native session cannot read `/api/me` or access private
resources; it may only complete or sign out. Success atomically consumes the intent and returns
the account object. Only then publish the explicit authenticated change using the
saved expected record. A query parameter, `/api/me`, a missing storage intent, or a
stale callback must never reopen an old session. Completion expires after ten minutes.

The login/signup link IDs are `google-signin` and `google-signup`, with matching
`-divider` IDs. Error redirects carry a fixed `google` code: `google_cancelled`,
`google_expired`, `google_failed`, `google_unavailable`, `google_link_required`,
`google_already_linked`, `google_account_mismatch`, `registration_closed`, or
`reauthentication_required`. Render friendly text, never untrusted query contents.

## Linking and sensitive account changes

An email match never links or merges accounts. A user with an existing password
account signs in first, then POSTs `/api/auth/google/link` with `{ "password": "..." }`
and the native CSRF header. The response's `url` starts Google authorization.
Successful linking returns `/app?settings=account&connected=1`. It preserves the
original account, credits and password. A Google identity already connected to
another user cannot be reassigned. Existing account email is not changed.

Google identities are keyed by immutable `sub`. Google's proof of an external
non-Gmail/non-Workspace email is not accepted as current mailbox ownership; a
connected account can still authenticate with its Google identity. This distinction
preserves the existing protection against email-recovery account takeover.

POST `/api/auth/reauthenticate` with a password and CSRF header to record five-minute
recent-auth proof on the current native session. Google-only users visit
`/auth/google/reauthenticate`; the new OAuth flow must prove the already connected
Google subject in the same live native session. Success returns
`/app?settings=account&reauthenticated=1`. This return flag is informational only.
Sensitive mutations must call `ProductService.require_recent_auth(conn, user_id=...,
session_token=...)` **inside their mutation transaction**. Normal login does not
create this proof. Session expiration, logout or generation changes invalidate it.

## Migration and verification

Schema 11 preserves existing accounts/passwords/sessions, adds explicit passwordless
account support, Google identities and expiring OAuth attempts. Schema 13 follows the
project-library schema 12 and adds the one-use login completion receipt, including
upgrades from already initialized schema 11/12 databases. Credentials remain
server-side. Attempts use PKCE, nonce, one-use hashed state and a browser cookie;
linking/reauthentication also bind to the current session and its generation. The
callback query is cleared from the ASGI scope before Uvicorn access logging.
Authentication requests share bounded concurrency/global admission controls.

Before deployment take a coordinated backup. Rollback requires restoring the prior
schema backup into a fresh data directory rather than reverting code over schema 13.
Tests exercise real RSA-signed JWT validation, wrong audience/issuer/signature,
nonce/expiry/denial, browser mismatch/replay, explicit linking, zero grants, native
session continuation and recent-auth invalidation. No real Google consent or cloud
client configuration is implied by these local tests; verify the dedicated client's
actual consent, returning sign-in and cancellation after deployment configuration.

Primary references:

- https://developers.google.com/identity/openid-connect/openid-connect
- https://developers.google.com/identity/gsi/web/guides/verify-google-id-token
- https://developers.google.com/identity/protocols/oauth2/production-readiness/overview
- https://developers.google.com/identity/branding-guidelines
