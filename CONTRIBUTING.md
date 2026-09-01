# Contributing

Use Python 3.11 and work from a branch. Install the development environment with `python -m pip install -e ".[dev]"`.

Before opening a pull request, run:

```bash
ruff check unrender/product unrender/schema/chart_schema.py tests/test_product.py
mypy unrender/product
pytest -q
node --check unrender/product/static/app.js
```

Changes to the product schema, job lifecycle, credit ledger, authentication, retention, or exports need regression tests. Never commit real customer charts, API keys, model credentials, Stripe secrets, generated model weights, or local database contents.
