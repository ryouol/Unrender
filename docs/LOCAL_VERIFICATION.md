# Local verification — September 10, 2026

## Checkout and startup

Verified checkout:
`/Users/royluo/Documents/Codex/2026-08-31/turn-this-into-a-workable-prompt-2/work/Unrender`.
HEAD and the live origin/main ref both resolve to `c74e8741e5b35c791a43e491c96f0f0cde5532e7`.
No open PR was returned by `gh pr list`. The September 9 hardening changes remain
uncommitted. The separate Desktop checkout was not used or reconciled.

From the verified checkout, run:

```sh
./scripts/run_local.sh
```

Open http://127.0.0.1:8000 and select **Open the reviewed sample**.
The launcher uses the existing `.venv`, binds only to loopback, explicitly selects
local development replay, enables isolated sample sessions and local signup (updated during productization), disables billing
and Stripe configuration, and stores state in ignored `outputs/local-runtime`.
It does not load or overwrite `.env`. Sample tenants cannot upload arbitrary
charts, create API keys, or use billing. This is not a public-demo release mode.
Stop with Ctrl-C; restart with the same command to preserve local state.

## Results

- Full pytest suite: **169 passed, 1 skipped, 1 warning**, 48.49 seconds.
  The warning is the upstream Starlette TestClient/httpx deprecation.
- Ruff formatting, product lint/security lint, and mypy passed. Fixed one
  formatting-only failure in `unrender/product/web.py`.
- Both frontend files passed Node syntax checks; both browser authentication
  regression scripts exited successfully.
- All three lockfile pip-audit runs reported no known vulnerabilities.
- Regenerated SBOM matched the checked-in inventory. License-policy structure
  passed; the owner/counsel public-release decision remains blocked.
- Source distribution and wheel built successfully. Public-site regressions
  passed again after the formatting correction (2 tests).
- Live `/health/live` and `/health/ready` passed, including after restart.
- Browser sample reached review, saved a numerical edit, restored the original
  fixture value, reached approval, and served the XLSX export successfully.
- Independent live HTTP smoke exercised sample preparation, worker processing,
  correction, approval, and CSV/JSON/XLSX exports. Checked all 18 data rows in the
  CSV count, JSON equality, and XLSX Audit sheet approval/model metadata.
- Sample arbitrary upload, API-key creation, and billing requests returned 403;
  a second sample tenant could not read the first tenant's job (404).
- Coordinated backup and verified restore succeeded. Both original and restored
  databases passed SQLite integrity and foreign-key checks and contained two
  approved jobs. The original app restarted successfully with those jobs intact.

Local evidence is ignored under `outputs/local-verification`: `receipt.json`,
`sample.csv`, `sample.json`, `sample.xlsx`, `smoke.py`, build logs, and backup/restore
sets. The smoke script can be rerun against the running local server; it creates
a new isolated sample session. Its queue-to-review timing is replay overhead,
not model inference latency or accuracy evidence.

## Container verification

Started the installed Docker Desktop daemon. Built `unrender:local-verified`
from the pinned Dockerfile base image. Image ID:
`sha256:52c9b6982d735eab9429efb8100e9108a20e5889e45a1a6a2528a98779102c82`.
The container passed Docker health checks, HTTP readiness, the installed health
CLI, and a non-root UID 10001 check. The same live HTTP smoke passed against its
loopback-only port 8001, including correction, approval, all exports, isolation,
and sample restrictions. The verification container was stopped afterward;
the native app remains available on port 8000. The stopped container is named
`unrender-local-verification-20260910`. No OS-layer vulnerability scanner was
available; Python lockfile audits do not replace a complete image scan.

## Product context and remaining gates

The local product implements review-first chart digitization with persistent jobs,
versioned corrections, explicit approval, and data-only CSV/JSON plus audited XLSX.
The uncommitted hardening adds public document metadata, error recovery, consent
controls with collection disabled, asset packaging, and busy/mobile UI states.

Real uploaded-chart extraction requires the Modal adapter and approved immutable
model and provider pins. It was not invoked in this run. The June status review's
34.8% hard-set result and the README's 38.9% common300 result describe different
research evidence; neither establishes accuracy on intended customer inputs.
A fixed launch-input evaluation and correction-time measurement remain necessary.

Public sample production configuration, TLS/IAM, real provider contract/canary,
latency/cost/failure measurements, production storage/alerts, legal/operator
content, source magnification, responsive correction layout, recovery/invite UX,
and additional independently checked samples remain launch work. Local checks do
not close those gates. No deployment, commit, or PR was created.

## Productization follow-up — September 10

Current local suite: **182 passed, 1 skipped** (57.32 seconds), with the existing
Starlette TestClient/httpx deprecation warning. Ruff check/format and mypy
(15 product modules) passed. Signup, verification, password recovery, preservation
of approved charts across recovery/reopening, and credential revocation have local
regression coverage; email transport is mocked, not a real delivery check.

The Modal adapter now applies a configurable 1–240-second async deadline to
lookup, scheduling and result retrieval. Regressions verify worker drain,
terminal timeout, retained dispatched credit, and no automatic redispatch.
The non-spending contract check now hydrates the lazy function handle. A separate
read-only review exercised the installed Modal 1.5.5 async cancellation bridge with
network operations replaced: three invocations timed out in approximately 1.002–
1.003 seconds, including two sequential calls in one worker thread. This does not
prove remote GPU cancellation or deployed shutdown behavior.

Rebuilt local ARM64 image `unrender:productization`:
`sha256:7c3bd3ddf6e72cd1c861e4db192b22b20363fbf397fd6a081754ff2dd5dca8c5`.
Network-disabled container check confirmed UID 10001, writable private data/home,
and the packaged 240-second setting. This build is not a Render-platform image
scan or deployment verification. Earlier HTTP smoke evidence above refers to its
recorded older image, not this rebuild.

Render browser remains signed out and Modal CLI has no profile. Real sender,
domain, approved model release, deployment, off-host backups and alerts remain
unverified. Source magnification and account recovery UI are now implemented
locally; those earlier outstanding items still need deployed UX verification.

### Render architecture and image scan follow-up

Built `linux/amd64` and made the architecture explicit in CI. Added account/public
site tests to CI lint coverage; actionlint and those Ruff checks passed.
Final image: `sha256:e624d2136c4de66817758c2111711b5c50fa1a4b6fe3c857fd21041f0f3081dc`.
Production-mode container health and runtime imports pass under local emulation,
with network disabled and placeholder model pins (no provider claim).

Trivy 0.74.0 completed a full image scan. Removed unused inherited pip/setuptools
from runtime after dependency checking; this resolved all nine Python findings.
Debian advisories remain unresolved; see `CONTAINER_SCAN.md`. Supplemental
read-only packaging review found no runtime dependency on the removed installers.
This evidence does not establish live deployment or real model functionality.
