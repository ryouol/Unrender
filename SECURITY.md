# Security policy

Please report vulnerabilities privately through GitHub's security advisory form for this repository. Do not include customer charts, access tokens, API keys, or webhook secrets in an issue.

The supported line is the latest release on `main`. Reports should include the affected version, reproduction steps, and expected impact. Receipt will be acknowledged within two business days; remediation timing depends on severity and reproducibility.

Unrender stores uploaded sources and extracted results on the configured data volume. Operators are responsible for encryption at rest, backups, TLS termination, secret management, and access to that volume. See `docs/OPERATIONS.md` and `docs/SECURITY_MODEL.md` for deployment controls and current limits.
