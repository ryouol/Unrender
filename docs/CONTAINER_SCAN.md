# Container scan

CI now scans each built production image with the pinned Trivy 0.74.0 image and
a fresh vulnerability database. The `container-scan` workflow artifact retains
the full report for 30 days, including findings without fixes. Missing inventories,
Python findings, and high/critical OS findings with available fixes fail the check.
Remaining OS findings still require release assessment; a passing check is not a
security certification. Download the artifact from the relevant commit's CI run.

## November 9 release continuation

The fresh scan of the November 2 candidate failed on newly available Debian
fixes. The runtime now pins `apt` and `libapt-pkg7.0` to `3.0.4` for
[CVE-2026-109518 / DSA-6607-1](https://security-tracker.debian.org/tracker/CVE-2026-109518),
and `zlib1g` to `1:1.3.dfsg+really1.3.1-1+deb13u1` for
[DSA-6613-1](https://security-tracker.debian.org/tracker/DSA-6613-1).
The latter addresses the scanner's
[CVE-2026-76844](https://security-tracker.debian.org/tracker/CVE-2026-76844),
[CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091), and
[CVE-2026-27171](https://security-tracker.debian.org/tracker/CVE-2026-27171)
entries. Five advisory/package entries must disappear from the final scan.
The inherited APT is used to install its own update, so both package operations
explicitly set `Acquire::Retries=0`: Debian's advisory identifies nonzero retries
as a prerequisite for the download-reuse attack. Package signature verification
remains enabled. No distribution, image-digest or Python-package change is added
to the November 2 candidate.

CI also exercises gzip/zlib round trips and a PNG encode/decode inside the built
Linux image. These supplement the existing product, CPU, browser and image checks;
they do not attempt to reproduce an exploit or prove every native library safe.

The new SQLite findings have no fixed Trixie package in the
[Debian tracker](https://security-tracker.debian.org/tracker/source-package/sqlite3).
Source review and the November 9 read-only production check found no virtual
tables or views, customer-supplied SQL/database ingestion, extension loading,
changeset processing or SQLite authorizer policy. The SQL wrappers use bound
values and application-owned statements. The narrower trigger assessment is:

| Advisory group | Required surface | Current product boundary |
| --- | --- | --- |
| CVE-2026-119372, CVE-2026-119373, CVE-2026-119374 | FTS queries or crafted FTS indexes | No FTS tables or MATCH queries; no uploaded databases are opened. |
| CVE-2026-119371, CVE-2026-119376, CVE-2026-119591 | Crafted SQL expressions, CTE chains or views | No SQL submission interface or stored views. |
| CVE-2026-119375, CVE-2026-119378 | Crafted database/WAL or R-Tree shadow tables | No database/WAL uploads or virtual tables. |
| CVE-2026-119377, CVE-2026-119379 | SQLite authorizer policy or supplied changesets | Neither API is used by the product. |

This supports no identified customer route for those triggers, not patched
SQLite or safety of arbitrary databases. Restore still opens SQLite and must
use only the existing operator-controlled recovery destination; manifest hashes
alone cannot authenticate an untrusted recovery set.

The additional GCC/libstdc++ findings
[CVE-2026-114690](https://security-tracker.debian.org/tracker/CVE-2026-114690),
[CVE-2026-114691](https://security-tracker.debian.org/tracker/CVE-2026-114691),
[CVE-2026-115455](https://security-tracker.debian.org/tracker/CVE-2026-115455),
and CVE-2026-115456 concern particular native C++ operations. Python source
inspection cannot exclude those operations inside every binary wheel. Keep this
native-library uncertainty visible and apply a Trixie fix when available; it is
not a claimed non-applicability exception. The
[glibc LANGUAGE finding](https://security-tracker.debian.org/tracker/source-package/glibc)
requires control of the process locale/environment and a supplied message catalog.
The hosted process has no LANGUAGE value and the product exposes no environment
configuration route to customers. Operator/SSH locale handling remains outside
that product-only assessment.

The existing non-root boundary was rechecked: UID/GID 10001, no effective
capabilities, NoNewPrivs=1, and no active fstab entries. Seccomp=0 is recorded;
no outer-platform sandbox claim is made. Direct SSH still fails before command
execution, but the dashboard shell works. The scheduled recovery archive was
downloaded from the existing private Modal backup volume into a mode-0600 file
on a FileVault-encrypted disk. Archive/manifest hashes, SQLite integrity and
foreign keys pass; all 12 persistent-table snapshots and source inventory match
production. Recheck this match after closing ingress before any rollout, and
create a new coordinated copy if production has changed. No customer data was
restored or migrated and no backup access was expanded.

## November 2 dependency remediation

The October 26 save-recovery release was blocked by Python dependency findings.
The November 2 audit also identified affected pyasn1, filelock, msgpack and
setuptools versions. This candidate updates the application locks to aiohttp
3.14.4, certifi 2026.10.19, Pillow 13.0.0 and pyasn1 0.6.5. aiohttp 3.14.4
requires yarl >=1.25.1, so the application/development yarl pin also becomes
1.25.1. The runtime pins Debian ca-certificates `20250419+deb13u1` for
[DSA-6572-1](https://security-tracker.debian.org/tracker/DSA-6572-1).

The development/training locks update filelock to 4.2.1; development updates
msgpack to 1.2.3; build and training locks update setuptools to 84.1.0.
The build-system requirement and build input agree with that exact pin.
Training and CPU-test Pillow inputs move to 13.0.0. All unrelated package
versions are preserved, and the application SBOM is regenerated from its lock.
These training-lock edits prepare a candidate; they do not run training or
release a model. The processor-audit validator also requires Pillow 13.0.0,
matching both training locks. Historical Pillow 12.3.0 processor evidence cannot
approve this candidate: regenerate the CPU audit and source-review packet, then
obtain the required source review before any future training. Existing datasets
and review records are not rewritten. Regression tests submit package metadata
from both actual lock files and reject the historical Pillow version.

Upstream evidence: [aiohttp](https://github.com/aio-libs/aiohttp/releases/tag/v3.14.4),
[certifi](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2),
[Pillow](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html),
[pyasn1](https://github.com/pyasn1/pyasn1/releases/tag/v0.6.5),
[filelock](https://github.com/tox-dev/filelock/releases/tag/4.2.1),
[msgpack](https://github.com/msgpack/msgpack-python/releases/tag/v1.2.3), and
[setuptools](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w).
Finding affected packages does not establish exploitation.

Pillow 13 removes deprecated APIs and changes some image operations. The product
uses none of the removed APIs; page preparation converts images to RGB before
resizing. A fixed-fixture comparison of Pillow 12.3.0 and 13.0.0 on the local
Python 3.14 runtime passed 43 cases with identical PNG bytes, decoded pixels,
dimensions and replay results. It covers RGB/RGBA/LA, grayscale, palette and
16-bit PNG, JPEG including CMYK and EXIF rotation, WebP, PDF pages, crops and
640-pixel previews. This bounded comparison is compatibility evidence, not a
claim about every image or Linux wheel; CI's product, CPU-processor and real
browser checks must also pass on the exact candidate.

Release acceptance requires passing dependency audits, SBOM/license structure,
product/browser/CPU checks, package build and production-image smoke/scan without
relaxing the existing gates. Before reopening a deployment, verify the coordinated
recovery copy, persistent records/source hashes, expected package-only changes,
schema/privileges, healthy endpoints and non-spending provider resolution.

The deployed inference provider is a separate boundary: `modal_train.py` still
pins Pillow 12.3.0 in `INFER_DIRECT_DEPENDENCIES`. Its source digest inputs, model
bytes and deployment are unchanged. Updating application/training locks does not
patch that provider. A provider upgrade and its required real inference canary
need separate authorization; neither is part of this recurring maintenance task.
The provider's live package inventory has not been scanned here. Keep
[issue 26](https://github.com/ryouol/Unrender/issues/26) open for that remaining
work, even after the application release passes its checks.

The October 19, 2026 update pins libc6 and libc-bin to `2.41-12+deb13u4`,
replacing `2.41-12+deb13u3` inherited from the pinned base image. Debian identifies
this version as fixing [CVE-2026-5450](https://security-tracker.debian.org/tracker/CVE-2026-5450)
(a heap overflow in a specific allocating scanf conversion) and
[CVE-2026-5928](https://security-tracker.debian.org/tracker/CVE-2026-5928)
(a wide-character stream pushback buffer under-read or crash). The October 12
image report contained four medium findings: both advisories on both packages.
This is preventive runtime maintenance; the findings do not establish an
exploitable application path. Other glibc advisories remain subject to assessment.

Release acceptance requires both fixed package versions in the built image,
absence of these four findings in its fresh scan, passing runtime smoke and
product/browser checks, and unchanged application/Python inventories. Before
reopening production, verify a coordinated recovery copy, matching persistent
records and source hashes, unchanged privileges and schema, healthy endpoints,
and the non-spending provider contract. No new inference canary is authorized
for this runtime-only update; the model and provider release remain unchanged.

The October 12, 2026 update pins multidict 6.9.1 in the application, development
and training locks and regenerates the runtime inventory. This addresses
[CVE-2026-104874](https://github.com/aio-libs/multidict/security/advisories/GHSA-54p9-h82j-f925),
a reference leak in specific C-extension items-view set operations. The initial
monitor-diagnostics CI failed on that advisory in the existing runtime. No other
package pins change. Updating a training lock does not deploy a model or provider;
those releases and their canary requirements remain separate.
The runtime also pins liblzma5 `5.8.1-1+deb13u2`, applying the newly available
[Debian DSA-6549-1 fix](https://security-tracker.debian.org/tracker/DSA-6549-1)
for a decoder reinitialization write after allocation failure. The scan did not
assign a severity to this finding; an unrated finding still warrants assessment.

The October 3, 2026 maintenance update pins PCRE2 `10.46-1~deb13u3` and
OpenSSL `3.5.7-1~deb13u3` across its three installed packages, addressing the
available Debian fixes for [CVE-2026-103111](https://security-tracker.debian.org/tracker/CVE-2026-103111),
[CVE-2026-75804](https://security-tracker.debian.org/tracker/CVE-2026-75804), and
[CVE-2026-84782](https://security-tracker.debian.org/tracker/CVE-2026-84782).
The application and development locks also update urllib3 to 2.8.0. Use the
corresponding CI artifact for the current scan; counts below are historical.

Recorded September 22, 2026 (September 23 UTC); release assessment remains incomplete.

A fresh Trivy 0.74.0 database scan of the cleanup image found **zero critical,
44 high, 53 medium, 57 low and six unknown findings**, all in Debian packages.
There are zero Python findings and no listed fixes for the remaining high findings.
No findings are suppressed. This is not a security certification.

The runtime retains the September 18 gzip, PCRE2, SQLite and Perl fixes. See the
[latest summary](../release/cleanup-deployment-20260922/container-scan-summary.json)
and compressed full report beside it. The [September 18 scan](../release/readiness-remediation-20260918/container-scan-summary.json)
records the earlier assessment, which had one unknown finding.

The [deployment receipt](../release/cleanup-deployment-20260922/deployment.json)
records matching live application hashes, Python versions and Debian packages.
This verifies inventories, not Render's final image digest.

The [September 10–18 scan history](archive/CONTAINER_SCAN.md) preserves earlier inventories, advisory-by-advisory reachability checks and deployed privilege checks. Those dated assessments must be rechecked when packages or runtime boundaries change.

Next steps: assess the remaining advisories against the deployed runtime, apply vendor fixes when available and rescan the final image. No findings are suppressed.
