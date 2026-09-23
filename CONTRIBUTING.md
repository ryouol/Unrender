# Contributing

Use Python 3.11 and a branch. Follow the locked installation in the [README](README.md#run-locally); Node.js is required for browser tests.

Before opening a pull request, run:

```bash
ruff check unrender/product unrender/schema/chart_schema.py tests
ruff check --select S unrender/product
mypy unrender/product
pytest -q
node --check unrender/product/static/app.js
```

[CI](.github/workflows/ci.yml) defines the additional checks for evaluation, training, dependency audits and containers. Changes to schema, job lifecycle, credit accounting, authentication, retention or exports need regression coverage for the behavior they affect.

Keep each change focused. Explain the problem, resulting behavior and validation in the pull request. Separate mechanical file moves from logic changes. The [review guide](docs/ENGINEERING_REVIEW.md) maps code and tests; the [documentation index](docs/README.md) separates current contracts from historical evidence.

Do not commit customer charts, credentials, model weights or local databases. Use synthetic examples for public bug reports and the [security policy](SECURITY.md) for sensitive findings.
