# Request admission

The app separates shared service capacity from ordinary account quotas. A public
request's forwarding headers and peer address do not establish its identity.
This change is live on Render at `be6c99b`, deployment
`dep-dahlkaifngtc73d1je80`. CI run 34550763910 passed all 233 tests (one skipped),
dependency audits, lint/types and the production container build/smoke checks.

| Scope | Default per minute | Configuration |
|---|---:|---|
| All ordinary requests, including invalid credentials/bodies | 600 | `UNRENDER_GLOBAL_RATE_LIMIT_PER_MINUTE` |
| All POST auth attempts except logout | 30 | `UNRENDER_GLOBAL_AUTH_RATE_LIMIT_PER_MINUTE` |
| All browser job-status polls | 1,200 | Twice the global request limit, minimum 240 |
| Validated tenant ordinary requests | 120 | `UNRENDER_RATE_LIMIT_PER_MINUTE` |
| Validated tenant browser job-status polls | 240 | Twice the tenant request limit, minimum 240 |
| Login/register attempts for one normalized identifier | 10 | `UNRENDER_AUTH_RATE_LIMIT_PER_MINUTE` |

Each scope has its own fixed UTC-minute bucket. Global admission runs before
body parsing and authentication for every request except `/health/live`; a valid
cookie does not exempt malformed requests, missing CSRF or invalid bearer keys.
Existing body-size, KDF and expensive-work concurrency limits still apply.
Successful authentication resolves the durable tenant ID used by its quota;
rotating sessions or API keys cannot reset that tenant quota. Cookie and bearer
credentials retain their route-specific authorization rules.

Login and registration use the same email normalization and account namespace.
Unknown accounts consume the same account quota before dummy password work.
Buckets contain identifier digests, not email addresses or raw credentials.
Logout is independent of the login quota, but still consumes ordinary capacity.
Account throttles can be deliberately exhausted; this is a short denial-of-service
tradeoff, not an identity-verification mechanism.

Global exhaustion still affects everyone and can reject readiness checks. These
are bounded capacity controls for the one-instance deployment, not an uptime or
resistance-to-distributed-attack guarantee. SQLite row budgets and housekeeping
bound retained counters. No global quota is a dollar cap.

## Hosted quota verification — September 11, 2026 UTC

The existing zero-credit operator test account completed exactly 120 ordinary
requests within one server minute; its next request returned 429. Another session
for that account and a changed forwarding header also received 429. The other
owned account still received 200, and readiness remained healthy. The sequence
took 11.31 seconds. No global quota was exhausted in production.

Hosted sign-in, Secure HttpOnly cookies, the existing approved chart and all three
exports passed, including the workbook audit sheet. Read-only SSH checks confirmed
SQLite integrity/foreign keys, the unchanged provider pin and retained backup
status after deployment. Operational checks were healthy. No upload or inference
ran, no account was created, and the owner's one extraction credit remained.
The sanitized receipt is
`release/launch-eval-results/request-limits-v1.json`.

API-key sharing, malformed authenticated requests and normalized login quotas
have regression coverage in CI; this hosted exercise did not independently replay
every regression or deliberately exhaust shared service capacity.

## Hosted ingress evidence — September 10, 2026

A temporary native-Python test web service in UNRENDER's Production environment,
Ohio, returned only peer/forwarding metadata for operator-owned requests. It had
no app data, disk, credentials or inference code. Tests observed:

- Normal public requests arrived from shared private Render proxy addresses.
- An arbitrary client-supplied X-Forwarded-For prefix and duplicate XFF fields
  survived before the appended client/edge hops. The leftmost value is unsafe.
- A request supplying multiple forged identity headers was rejected at the
  public edge. That single rejection does not prove every spoofing case blocked.
- Private DNS and direct private-IP requests on port 10000 both succeeded from
  the UNRENDER web service, preserving matching forged CF-Connecting-IP,
  True-Client-IP and XFF values. The sender's peer address was in the same /16
  as an observed public proxy. Broad private-CIDR trust is therefore unsafe.

The temporary service `srv-dahlarqd0e5s73fskpjg` was deleted after verification;
the project inventory again contains only the app and hourly monitor. No other
project changed, and no GPU call occurred. Private raw receipts are under
`outputs/local-verification/render-ingress/`; operator addresses are not committed.
This establishes the tested shared-workspace boundary, not every possible Render
ingress configuration. Public client-IP attribution remains unavailable; the
application's admission controls no longer require it.

Relevant platform documentation: [private networking](https://render.com/docs/private-network)
and [web service ingress](https://render.com/docs/web-services). The live probe
verified port 10000 directly because the private-network documentation also lists
that port as restricted; no restriction was assumed from that text alone.
