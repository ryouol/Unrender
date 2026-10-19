# Container scan

CI now scans each built production image with the pinned Trivy 0.74.0 image and
a fresh vulnerability database. The `container-scan` workflow artifact retains
the full report for 30 days, including findings without fixes. Missing inventories,
Python findings, and high/critical OS findings with available fixes fail the check.
Remaining OS findings still require release assessment; a passing check is not a
security certification. Download the artifact from the relevant commit's CI run.

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
