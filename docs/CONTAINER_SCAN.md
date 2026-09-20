# Container scan

Recorded September 18, 2026; release assessment remains incomplete.

A fresh Trivy 0.74.0 database scan found fixes now available for gzip, PCRE2,
SQLite and Perl. The runtime stage installs exact Debian Trixie package versions
from the vendor repository before removing privilege bits. The official Python
base's AMD64 image remains unchanged, so a tag refresh alone would not apply them.

The rebuilt AMD64 image has **zero critical findings, 44 high, 53 medium,
57 low and one unknown**, with zero Python findings. None of the remaining high
findings has a fixed version in this scan. This removes all three critical and
ten high package/advisory pairs from the September 18 pre-update scan.
Remaining package risks are visible; the historical reachability assessments
in the archive still require their stated operational boundaries and are not a clean
security certification. See the [scan receipt](../release/readiness-remediation-20260918/container-scan-summary.json) and compressed full report beside it.

The [deployment receipt](../release/readiness-remediation-20260918/deployment.json) records matching live package inventories and application hashes. This does not attest Render’s final image digest.

The [September 10–18 scan history](archive/CONTAINER_SCAN.md) preserves earlier inventories, advisory-by-advisory reachability checks and deployed privilege checks. Those dated assessments must be rechecked when packages or runtime boundaries change.

Next steps: assess the remaining advisories against the deployed runtime, apply vendor fixes when available and rescan the final image. No findings are suppressed.
