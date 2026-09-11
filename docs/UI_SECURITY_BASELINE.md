# UI redesign — source security baseline

Reviewed commit: `5720cd86c45b2788149cbe213af1304b63b4ae0b` (clean tracked tree at inspection). Date: September 11, 2026 UTC. Authoritative source: Documents/Codex checkout, not Desktop.

**No new actionable source vulnerability was found in the requested redesign scope.** Authentication, tenant ownership, input validation, browser isolation and private-file delivery are implemented. This source review does not establish current cloud access settings or that a future redesign preserves these controls.

Stack: Python/FastAPI/Starlette with Pydantic, SQLite and an embedded worker; plain JavaScript, HTML and CSS; Render Docker hosting/persistent disk with Modal inference and backups. No React, Supabase, Postgres, Firebase or browser database/storage SDK is present in the product.

## Phase 1 disposition

| Item | Source result | Qualification |
|---|---|---|
| Exposed keys | ✅ No real secret identified in tracked text or client assets. | Scan excludes git history, binary pixels, ignored data and platform secret stores. |
| Endpoint protection | ✅ All 44 explicit HTTP routes inventoried below; static mount and Modal boundary also reviewed. | Public pages/auth/bootstrap/health routes are intentional exceptions with limited authority/output. |
| RLS/security rules | ➖ N/A: SQLite has no configured anonymous database role or RLS. | Python enforces tenant ownership; client filtering cannot replace it. |
| Broken auth gates | ✅ No unconditional auth bypass, disabled guard, permissive CORS, debug or reload mode found in product/deployment code. | Development demo/registration controls remain production validated. |
| Public storage | ✅ No public tenant-file static mount, browser bucket URL or public-read/write rule found in source. | ⚠️ Actual Render/Modal permissions, memberships, volume sharing and credential scopes were not inspected. |

## Credentials

Scanned 209 tracked UTF-8 text files, including 12 client text assets, for private-key blocks, common provider/GitHub/Modal/app token shapes, embedded credential URLs and credential-named literals. Six candidates were synthetic local-test fixtures in `tests/test_accounts.py`, `tests/test_product.py` and `tests/test_release_policy.py`. No production credential was found; values are omitted. No key migration/rotation is indicated by this scan. This is a targeted pattern/source review, not exhaustive secret detection.

| Name | Current location/boundary |
|---|---|
| `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | Server/provider SDK credentials; Blueprint secret inputs use `sync: false`: [render.yaml:65](../render.yaml#L65). |
| `UNRENDER_SMTP_USERNAME`, `UNRENDER_SMTP_PASSWORD` | Server environment only: [unrender/product/config.py:331](../unrender/product/config.py#L331). Delivery remains deferred. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Server environment: [unrender/product/config.py:407](../unrender/product/config.py#L407); Blueprint values empty: [render.yaml:69](../render.yaml#L69). `STRIPE_PRICE_ID` is an identifier, not a secret. |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `WANDB_API_KEY`, `HF_TOKEN` | Empty research environment placeholders: [.env.example:4](../.env.example#L4); not browser configuration. |
| `UNRENDER_HF_SECRET` | Optional Modal secret *name*, not value: [modal_train.py:772](../modal_train.py#L772). |
| Session, CSRF, account-link and user API-key secrets | Secure random generation: [unrender/product/security.py:68](../unrender/product/security.py#L68); hashed server storage: [unrender/product/service.py:1252](../unrender/product/service.py#L1252). |

Never put these secrets into public configuration, HTML, JavaScript, URLs or browser storage. `.env`, `.unrender-data` and `outputs/` are ignored; Docker excludes `.env*` except the empty example ([.dockerignore:16](../.dockerignore#L16)). Local replay clears inherited backup/SMTP/billing destinations ([scripts/run_local.sh:16](../scripts/run_local.sh#L16)). No ignored credential file was opened or copied into this report.

## Endpoint protection inventory

All routes receive security headers and TrustedHost validation. Non-liveness requests spend global capacity; authenticated routes also spend tenant quotas. Cookie mutations require a session-bound CSRF header. Unsafe methods reject a mismatching supplied Origin. Body limits precede parsing, and write schemas forbid extra fields. Public login/recovery cannot require a preexisting session. References: [unrender/product/web.py:51](../unrender/product/web.py#L51), [unrender/product/web.py:118](../unrender/product/web.py#L118), [unrender/product/web.py:266](../unrender/product/web.py#L266), [unrender/product/web.py:471](../unrender/product/web.py#L471), [unrender/product/web.py:612](../unrender/product/web.py#L612).

| Method / endpoint | Protection | Validation / allowed behavior | Source |
|---|---|---|---|
| `GET /` | Intentional public | Fixed public document; no tenant content. | [unrender/product/web.py:649](../unrender/product/web.py#L649) |
| `GET /privacy` | Intentional public | Fixed legal draft. | [unrender/product/web.py:653](../unrender/product/web.py#L653) |
| `GET /terms` | Intentional public | Fixed legal draft. | [unrender/product/web.py:657](../unrender/product/web.py#L657) |
| `GET /account` | Intentional public | Fixed shell; account token is consumed by POST only. | [unrender/product/web.py:661](../unrender/product/web.py#L661) |
| `GET /contact` | Intentional public | Fixed public shell. | [unrender/product/web.py:665](../unrender/product/web.py#L665) |
| `GET /robots.txt` | Intentional public | Fixed exclusions/configured origin. | [unrender/product/web.py:669](../unrender/product/web.py#L669) |
| `GET /sitemap.xml` | Intentional public | Fixed page allowlist. | [unrender/product/web.py:677](../unrender/product/web.py#L677) |
| `GET /api/public-config` | Intentional public | Allowlisted capability booleans and upload limits; no credentials. | [unrender/product/web.py:689](../unrender/product/web.py#L689) |
| `GET /health/live` | Intentional public | Constant status. | [unrender/product/web.py:701](../unrender/product/web.py#L701) |
| `GET /health/ready` | Intentional public | Database/storage/worker status; no tenant data. | [unrender/product/web.py:705](../unrender/product/web.py#L705) |
| `GET /health/operations` | Intentional public | Cached bounded checks; fixed boolean output. | [unrender/product/web.py:716](../unrender/product/web.py#L716) |
| `POST /api/auth/register` | Public, server policy gated | Credentials schema; normalized email/password; signup policy and verification. | [unrender/product/web.py:726](../unrender/product/web.py#L726) |
| `POST /api/auth/login` | Submitted credentials | Credentials schema; normalized account quota; KDF; verified account/hash fence. | [unrender/product/web.py:755](../unrender/product/web.py#L755) |
| `POST /api/auth/request-verification` | Intentional public | Email schema/normalization; configured SMTP, recipient quota, generic response. | [unrender/product/web.py:762](../unrender/product/web.py#L762) |
| `POST /api/auth/forgot-password` | Intentional public | Email schema/normalization; configured SMTP, recipient quota, generic response. | [unrender/product/web.py:767](../unrender/product/web.py#L767) |
| `POST /api/auth/verify-email` | One-use account capability | Bounded token/password; live hashed one-use challenge; password/hash/generation fence. | [unrender/product/web.py:772](../unrender/product/web.py#L772) |
| `POST /api/auth/reset-password` | One-use account capability | Bounded token/password; live one-use setup/reset challenge; new-password validation; transaction recheck. | [unrender/product/web.py:777](../unrender/product/web.py#L777) |
| `POST /api/auth/demo` | Public, server policy gated | Isolated ephemeral demo; production configuration forbids enabling it. | [unrender/product/web.py:782](../unrender/product/web.py#L782) |
| `POST /api/auth/logout` | Session + CSRF | Session-bound CSRF; account-wide session invalidation. | [unrender/product/web.py:788](../unrender/product/web.py#L788) |
| `GET /api/me` | Session | Allowlisted account serialization. | [unrender/product/web.py:798](../unrender/product/web.py#L798) |
| `POST /api/uploads` | Session + CSRF | Bounded multipart stream; decoded type/image/PDF checks; customer-only; quotas. | [unrender/product/web.py:802](../unrender/product/web.py#L802) |
| `POST /api/uploads/demo` | Session + CSRF | Fixed fixture copied into authenticated tenant; production extraction still charged. | [unrender/product/web.py:816](../unrender/product/web.py#L816) |
| `GET /api/uploads/{upload_id}/pages/{page_index}` | Session | Owned unexpired upload; page bounds; PNG output. | [unrender/product/web.py:820](../unrender/product/web.py#L820) |
| `POST /api/jobs` | Session + CSRF | Strict JobCreate; owned upload; page/crop bounds; required idempotency key; credits/quotas. | [unrender/product/web.py:831](../unrender/product/web.py#L831) |
| `GET /api/jobs` | Session | Tenant filter; decoded cursor; 1–100 limit. | [unrender/product/web.py:851](../unrender/product/web.py#L851) |
| `GET /api/jobs/{job_id}` | Session | Owned job; explicit output shaping. | [unrender/product/web.py:859](../unrender/product/web.py#L859) |
| `GET /api/jobs/{job_id}/source` | Session | Owned job; server-selected source path rendered to PNG. | [unrender/product/web.py:863](../unrender/product/web.py#L863) |
| `GET /api/jobs/{job_id}/audit` | Session | Owned job gate; bounded cursor page. | [unrender/product/web.py:869](../unrender/product/web.py#L869) |
| `GET /api/jobs/{job_id}/versions` | Session | Owned job; typed cursor; bounded inventory. | [unrender/product/web.py:878](../unrender/product/web.py#L878) |
| `GET /api/jobs/{job_id}/versions/{version}` | Session | Owned job and integer version; tenant filter. | [unrender/product/web.py:886](../unrender/product/web.py#L886) |
| `PATCH /api/jobs/{job_id}/result` | Session + CSRF | Strict envelope + ChartData validation; owned editable job; size/history bounds. | [unrender/product/web.py:890](../unrender/product/web.py#L890) |
| `POST /api/jobs/{job_id}/approve` | Session + CSRF | Owned job and valid status/result. | [unrender/product/web.py:898](../unrender/product/web.py#L898) |
| `POST /api/jobs/{job_id}/cancel` | Session + CSRF | Owned job and state/dispatch fencing. | [unrender/product/web.py:902](../unrender/product/web.py#L902) |
| `POST /api/jobs/{job_id}/reprocess` | Session + CSRF | Owned job; state, credit/quota/attempt checks. | [unrender/product/web.py:906](../unrender/product/web.py#L906) |
| `GET /api/jobs/{job_id}/export/{output_format}` | Session | Owned job; result-state/format allowlist; formula-safe spreadsheet output. | [unrender/product/web.py:910](../unrender/product/web.py#L910) |
| `DELETE /api/jobs/{job_id}` | Session + CSRF | Owned job; coordinated deletion/outbox. | [unrender/product/web.py:926](../unrender/product/web.py#L926) |
| `POST /api/keys` | Session + CSRF | Bounded name; customer-only; transactional credential-generation fence. | [unrender/product/web.py:933](../unrender/product/web.py#L933) |
| `GET /api/keys` | Session | Bounded tenant inventory; stored key hashes excluded. | [unrender/product/web.py:941](../unrender/product/web.py#L941) |
| `DELETE /api/keys` | Session + CSRF | Tenant-only key revocation. | [unrender/product/web.py:949](../unrender/product/web.py#L949) |
| `DELETE /api/keys/{key_id}` | Session + CSRF | Owned key lookup/revocation. | [unrender/product/web.py:953](../unrender/product/web.py#L953) |
| `POST /api/billing/checkout` | Session + CSRF | Customer-only; configured test billing; server-fixed price/credits; destination allowlist. | [unrender/product/web.py:957](../unrender/product/web.py#L957) |
| `POST /api/billing/webhook` | Stripe signature | Bounded raw body; verified Stripe signature; paid test completion; metadata/account/credit validation; idempotency. | [unrender/product/web.py:990](../unrender/product/web.py#L990) |
| `POST /api/v1/extractions` | Bearer API key | Bounded multipart/content; page validation; tenant idempotency; credits/quotas. | [unrender/product/web.py:1041](../unrender/product/web.py#L1041) |
| `GET /api/v1/extractions/{job_id}` | Bearer API key | Owned job and explicit serialization. | [unrender/product/web.py:1058](../unrender/product/web.py#L1058) |

`/static` exposes packaged code, fonts, icons and the owned saved demo fixture only ([unrender/product/web.py:421](../unrender/product/web.py#L421)). `/docs`, `/redoc`, `/openapi.json` are disabled ([unrender/product/web.py:395](../unrender/product/web.py#L395)). No product WebSocket or HTTP administration endpoint is declared.

`modal_train.py::production_app/infer_one` is a Modal SDK function, not a declared public HTTP endpoint ([modal_train.py:768](../modal_train.py#L768)); the product invokes it from its server adapter ([unrender/product/extractors.py:81](../unrender/product/extractors.py#L81)). The release publisher and research functions are operator SDK functions outside the website route surface. No `web_endpoint`, `fastapi_endpoint`, `asgi_app` or `wsgi_app` decorator was found. Actual platform caller permissions are not proved by these declarations.

## Database and storage

SQLite is opened directly by the server with foreign keys and private file modes ([unrender/product/database.py:600](../unrender/product/database.py#L600)). Its 18 tables are `schema_meta`, `users`, `account_challenges`, `sessions`, `uploads`, `jobs`, `result_versions`, `audit_events`, `audit_rollups`, `credit_ledger`, `api_keys`, `billing_events`, `provider_attempts`, `rate_limits`, `pending_deletions`, `api_idempotency`, `storage_reservations`, and `startup_state` ([unrender/product/database.py:17](../unrender/product/database.py#L17)). None has a browser/anonymous database grant in this architecture. Public health endpoints return fixed aggregate checks, not table access.

Ownership uses authenticated user IDs and parameterized queries: upload ID + user ID + expiry ([unrender/product/service.py:1596](../unrender/product/service.py#L1596)); job ID + user ID ([unrender/product/service.py:2156](../unrender/product/service.py#L2156)); repeated ownership inside mutation transactions ([unrender/product/service.py:2359](../unrender/product/service.py#L2359)); unrevoked API-key hash ([unrender/product/service.py:2995](../unrender/product/service.py#L2995)). Lists/audit/versions use the same tenant gate with bounded pagination. IDs are generated UUIDs ([unrender/product/service.py:165](../unrender/product/service.py#L165)).

Storage uses private directories (0700), files (0600), generated object names, byte/type/image/PDF/page/crop validation, and PNG preview delivery ([unrender/product/storage.py:49](../unrender/product/storage.py#L49), [unrender/product/storage.py:113](../unrender/product/storage.py#L113), [unrender/product/storage.py:200](../unrender/product/storage.py#L200)). Render tenant data is under `/data/unrender`, outside packaged static assets ([render.yaml:18](../render.yaml#L18)). Backups use the server Modal SDK without a web download endpoint ([unrender/product/scheduled_backup.py:147](../unrender/product/scheduled_backup.py#L147)). A volume name is not a public URL and does not itself prove deployed access is private. No S3/Supabase/Firebase bucket configuration was found in the product.

## Preserve during redesign

1. **Request and account lifecycle:** Keep `api()` CSRF/stale-response checks, `resetPrivateState()`, principal generations, durable logout barriers, abort controllers, and focus/pageshow/visibility reconciliation. They prevent stale private content after logout/account changes ([unrender/product/static/app.js:73](../unrender/product/static/app.js#L73), [unrender/product/static/app.js:555](../unrender/product/static/app.js#L555), [unrender/product/static/app.js:742](../unrender/product/static/app.js#L742)).
2. **Safe rendering and CSP:** Continue DOM construction/`textContent`. No `innerHTML`, dynamic string execution, inline event strings or remote script includes were found. Keep components compatible with the current same-origin script/style policy; do not weaken CSP for visual effects ([unrender/product/web.py:59](../unrender/product/web.py#L59)). Public metadata escapes its configured origin ([unrender/product/public_site.py:41](../unrender/product/public_site.py#L41)).
3. **Transient secrets:** localStorage holds validated auth coordination markers, pending-submission metadata/idempotency keys and consent—not session/API/reset secrets ([unrender/product/static/app.js:212](../unrender/product/static/app.js#L212), [unrender/product/static/app.js:462](../unrender/product/static/app.js#L462)). Preserve early account-fragment removal ([unrender/product/static/account.js:5](../unrender/product/static/account.js#L5)), authoritative one-use challenge checks ([unrender/product/service.py:1036](../unrender/product/service.py#L1036)), and API-key clearing after timeout/copy/dialog/lifecycle changes ([unrender/product/static/app.js:194](../unrender/product/static/app.js#L194), [unrender/product/static/app.js:1927](../unrender/product/static/app.js#L1927)).
4. **Server authority:** Hidden controls are presentation only. Keep authenticated preview/export routes, strict request envelopes, ChartData validation, format allowlists and formula-safe exports ([unrender/product/service.py:2349](../unrender/product/service.py#L2349), [unrender/product/service.py:2604](../unrender/product/service.py#L2604)). Do not add direct filesystem/bucket links or persistent offline caches for tenant images/results.
5. **Pilot policy:** Public registration, demo sessions and billing are disabled in the current Blueprint ([render.yaml:43](../render.yaml#L43)); production rejects replay/seeded demo and unsafe signup combinations ([unrender/product/config.py:160](../unrender/product/config.py#L160)). Styling work does not authorize signup, SMTP, analytics, credit grants or provider calls. Current consent controls send no analytics ([unrender/product/static/site.js:21](../unrender/product/static/site.js#L21)).

## Validation and limits

This pass read source, route declarations, focused regression code and existing security/operations documentation. It ran metadata-only pattern scans and AST inspection. It did not run tests, browser journeys, provider calls, emails or cloud changes. It did not rescan dependencies or reopen the historical fixed findings.

Preserve the HTTP CSRF/origin/tenant regression ([tests/test_product.py:1300](../tests/test_product.py#L1300)), disk privacy regression ([tests/test_product.py:595](../tests/test_product.py#L595)), account-link/reset-race coverage ([tests/test_accounts.py:130](../tests/test_accounts.py#L130)), and `tests/browser_auth_epoch.mjs`, `tests/browser_two_tab.mjs`, `tests/browser_account.mjs`. After implementing the redesign, run affected browser/account/privacy tests and a non-spending hosted sign-in/reload/logout/owned-export check. A claim of freshly verified cloud storage requires a separate Render/Modal access inspection. Existing image advisories, formal penetration testing and broader public-launch gates remain documented operating limits, not newly discovered redesign defects or completed work.

## Redesign route delta

The implementation adds `GET /app`, `GET /login`, and `GET /signup`: public, fixed, noindex HTML shells. They contain no server-rendered tenant data; all data and mutations still require the existing authenticated API routes. Root now serves the public landing page. This brings the explicit route inventory to 47. The redesigned local example uses four illustrative values, makes no inference request, and has no account/credit mutation. The production configuration and model boundary are unchanged.
