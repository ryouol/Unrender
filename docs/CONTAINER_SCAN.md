# Container scan

CI now scans each built production image with the pinned Trivy 0.74.0 image and
a fresh vulnerability database. The `container-scan` workflow artifact retains
the full report for 30 days, including findings without fixes. Missing inventories,
Python findings, and high/critical OS findings with available fixes fail the check.
Remaining OS findings still require release assessment; a passing check is not a
security certification. Download the artifact from the relevant commit's CI run.

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
