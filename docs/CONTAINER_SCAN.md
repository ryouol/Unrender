# Container scan — September 10, 2026

Status: **release assessment incomplete**. Scan results are package-level findings,
not proof of reachable exploitation or an accepted exception. No findings are suppressed.

Image: `sha256:e624d2136c4de66817758c2111711b5c50fa1a4b6fe3c857fd21041f0f3081dc` (`linux/amd64`).
Scanner: Trivy 0.74.0, verified macOS archive SHA-256
`1caada5e0e2091909357c7525d3aa76f4b660b13821bc143b190c7483e31cc11`.

The initial scan found nine Python-package findings in inherited pip/setuptools
and their vendored dependencies. The final Docker stage now runs `pip check`
then removes those unused installation tools. Rebuild/rescan reports zero Python
findings. Runtime imports and production-mode health checks pass without them.

Remaining Debian findings: 3 critical, 51 high, 57 medium, 57 low, 5 unknown
package/advisory pairs. The 54 high/critical pairs represent 18 distinct advisories.
No fixed package version is listed by this scan. These affect the pinned base
at `Dockerfile:13`; reachability/vendor disposition must be assessed before release.

| Advisory | Severity | Packages | Scanner status |
|---|---|---|---|
| CVE-2025-69720 | HIGH | libncursesw6, libtinfo6, ncurses-base, ncurses-bin | affected |
| CVE-2026-11822 | HIGH | libsqlite3-0 | affected |
| CVE-2026-11824 | HIGH | libsqlite3-0 | affected |
| CVE-2026-13221 | CRITICAL | perl-base | affected |
| CVE-2026-16742 | HIGH | libsystemd0, libudev1 | affected |
| CVE-2026-41992 | HIGH | gzip | affected |
| CVE-2026-42496 | CRITICAL | perl-base | fix_deferred |
| CVE-2026-42497 | HIGH | perl-base | fix_deferred |
| CVE-2026-48962 | HIGH | perl-base | affected |
| CVE-2026-54369 | HIGH | libacl1 | affected |
| CVE-2026-57432 | HIGH | perl-base | affected |
| CVE-2026-57433 | HIGH | perl-base | affected |
| CVE-2026-76642 | HIGH | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux | affected |
| CVE-2026-78408 | HIGH | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux | affected |
| CVE-2026-78409 | HIGH | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux | affected |
| CVE-2026-78410 | HIGH | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux | affected |
| CVE-2026-8376 | CRITICAL | perl-base | affected |
| CVE-2026-9538 | HIGH | perl-base | fix_deferred |

Full machine-readable before/after reports are local ignored artifacts under
`outputs/local-verification/render-image-trivy*.json`; build and scan logs are
alongside them. Docker Scout was unavailable without Docker account login; Trivy
completed instead. No image was pushed and no cloud resources were created.

Next: review vendor advisories and actual affected binaries/functions; update the
base or remove unused packages where safe; document any supported non-applicability
with evidence. Re-run the scan on the final deployed image digest.

## Runtime assessment of high/critical advisories

Checked September 10 against the exact image digest above. Debian's tracker still
lists the installed Trixie versions as vulnerable; switching to the listed fixes
would mean adopting packages from unstable/testing. No such distribution change
was made. Package findings remain visible, with these narrower dispositions.

### Affected component or architecture absent (7 distinct advisories)

- Archive::Tar is absent (`Tar.pm` absent; Perl module load fails):
  [CVE-2026-42496](https://security-tracker.debian.org/tracker/CVE-2026-42496),
  [CVE-2026-42497](https://security-tracker.debian.org/tracker/CVE-2026-42497), and
  [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538).
- File::GlobMapper is absent (`GlobMapper.pm` absent):
  [CVE-2026-48962](https://security-tracker.debian.org/tracker/CVE-2026-48962).
- Storable is absent (`Storable.pm` absent; module load fails):
  [CVE-2026-57433](https://security-tracker.debian.org/tracker/CVE-2026-57433).
- systemd-homed is absent; the app runs directly as UID 10001:
  [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742).
- Perl reports 8-byte pointer/integer sizes on x86_64; the advisory requires a
  32-bit Perl build:
  [CVE-2026-8376](https://security-tracker.debian.org/tracker/CVE-2026-8376).

These are artifact-specific non-applicability findings, not patched packages.
Reassess if the image architecture or installed components change.

### No application route found; operational assessment remains (11 advisories)

This is a source-based reachability assessment, not a proof against arbitrary
code execution elsewhere or against privileged operator actions.

- SQLite FTS5: the extension **is compiled in**, so the binary is affected.
  The product has no FTS tables or MATCH queries and does not accept database
  uploads. Customer inputs are decoded by Pillow/PDFium and database writes use
  application SQL. The documented triggers require a crafted FTS5 database and
  a matching query. Operator restore opens a database, so only trusted recovery
  sets may be restored; hashes establish consistency, not provenance.
  [CVE-2026-11822](https://security-tracker.debian.org/tracker/CVE-2026-11822),
  [CVE-2026-11824](https://security-tracker.debian.org/tracker/CVE-2026-11824).
- Perl regex and pack/unpack: product code does not invoke Perl or accept Perl
  expressions/templates. The interpreter is present, so operator scripts using
  untrusted data would require separate review.
  [CVE-2026-13221](https://security-tracker.debian.org/tracker/CVE-2026-13221),
  [CVE-2026-57432](https://security-tracker.debian.org/tracker/CVE-2026-57432).
- ncurses: the affected function is in the `infocmp` command, not a chart parser.
  The product does not execute that command. This is not an exception for
  operator use of attacker-controlled terminal descriptions.
  [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720).
- gzip: the trigger uses multiple crafted legacy compression inputs in one GNU
  gzip invocation. The product does not execute gzip or accept compressed-archive
  uploads; this does not establish safety of arbitrary operator decompression.
  [CVE-2026-41992](https://security-tracker.debian.org/tracker/CVE-2026-41992).
- ACL: the app does not call the affected pathname ACL functions or run with
  root privilege. Confirm the deployed identity and operator boundary; ordinary
  non-root file permissions do not patch the library.
  [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369).
- util-linux: the application does not invoke mount helpers or nsenter. The
  image has an unconfigured fstab. The advisories require privileged helper
  operations or specific authorized mount arrangements. Actual Render mount,
  capability and operator behavior is not yet verified, so no platform-level
  exclusion is claimed.
  [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642),
  [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408),
  [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409),
  [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410).

Evidence: `outputs/local-verification/runtime-advisory-evidence.json`, generated
inside the network-disabled AMD64 image; source inspection of
`unrender/product/storage.py`, `database.py`, `backup.py`, and product subprocess,
FTS/MATCH and extension-loading call searches. No exploit payloads were run.
Lower-severity findings have not been individually assessed. Release assessment
remains incomplete until deployed operational assumptions are checked and the
remaining findings receive a supported disposition.

## Deployed identity and privilege check

Read-only SSH inspection of live runtime `02597a6` on September 10 verified:

- PID 1 is `unrender-serve`, with all UID/GID values equal to 10001.
- Inheritable, permitted, effective and ambient capabilities are zero.
- `NoNewPrivs` is 1; the capability bounding mask is `00000000000400cb`.
- The operator SSH process also runs as UID/GID 10001.
- The live database has zero virtual tables; `/etc/fstab` has no active entries.
- `/proc/1/status` reports `Seccomp: 0`; this check does not establish a
  seccomp policy or characterize Render's outer isolation boundary.

These observations support the non-root/no-active-capabilities assumptions for
the current application process. They do not patch affected packages, prove
all mount-helper or operator workflows safe, or replace a scan of the final
deployed image digest. No privileged command or exploit payload was executed.
