# Extraction receipts and export verification

Status: local readiness implementation; **not deployed**. No GPU or training run
was started. This milestone improves review evidence, not measured model accuracy.

## Changed behavior

Each immutable result version now stores an `extraction-receipt-v1` record.
Corrections inherit their current extraction evidence; restores inherit the chosen
historical version's evidence. A later model call cannot relabel an older result.
The review revision binds the receipt digest as well as result content/lifecycle.

Successful Modal results retain independently verified parse status/version,
completion/token counts, model/provider identities, prompt/schema hashes and raw
response hashes. The service binds these to original source and provider-input PNG
hashes, page/crop, dispatch attempt/generation and measured provider round-trip
latency. This is not a GPU benchmark or an accuracy certificate.

Every download carries the same source/review/evidence manifest. Both units are
editable and visible beside table values. CSV/XLSX headings preserve recorded
units; numeric cells are not rescaled. JSON now uses a chart/provenance envelope;
CSV stores the file manifest once in `export_metadata_json`; XLSX retains an Audit
sheet. See [the exact contract and limitations](../../docs/API.md#export-and-extraction-evidence-contract).

The bundled sample is deterministic synthetic reference data, not evidence of a
model extraction. Its entry point now says **Open reference example**, and its
receipt/UI/exports explicitly say no live inference ran. No EOS or raw-valid
claims are invented for the reference fixture or old historical versions.

Receipts have strict bounded types and an 8 KiB byte ceiling. History and global
storage admission account for them; worst-case result reservation includes their
bytes before provider dispatch. Malformed metadata fails publication without an
automatic additional paid attempt. Hashes cover the full raw response before the
existing retained-response truncation; a truncation flag makes that limit visible.

## Database upgrade and rollout

Schema 14 → 15 preserves external beta data and writes an explicit unavailable
receipt for every old version. There is one current runtime contract, no parallel
legacy read path. This narrow forward upgrade exists because deployed users have
real chart history; resetting their database would destroy it. Keep the upgrade
while schema-14 recovery sets remain supported; removal belongs with retiring
those recovery sets in the [readiness rollout task](../../docs/REVIEW_READINESS_PLAN.md).

Injected interruptions after either upgrade statement roll back the column and
schema version together; retry preserves chart contents. Drain workers and take
a coordinated backup before deployment. Existing pre-upgrade dispatch reservations
lack the new evidence overhead and are rejected before dispatch. Older approvals
cannot be retrospectively proven; fresh review is still required. Rollback uses
the matching pre-upgrade recovery set in a new directory. No hosted database was
modified in this work.

## Verification

Final full suite: **440 passed, one skipped**, four existing warnings, 130.65
seconds. The skipped test requires private train-table overlap data. Product
formatting/lint/security lint, type checking (25 files), and frontend syntax passed.
The browser workflow harness passed **78 scenarios**, including persistent warnings,
unit edits, safe text rendering and private-data clearing on navigation.

Tests exercise independently read CSV/JSON/XLSX bytes, source/page/crop input binding, version restoration across two provider
releases, inherited warnings after human edits, failed reprocess preserving the
approved prior receipt, historical upgrade interruption/retry, receipt-bound
approval conflicts, exact storage admission, raw truncation, malformed metadata,
and explicit reference-example origin. The existing two-connection review and
formula-injection regressions remain enabled.

Real browser check in a disposable local replay workspace: edit both axis units,
observe updated headings, save and approve version 2, confirm the warning remains,
open the evidence panel, and start the workbook download. A fresh final-code
session also verified the **Open reference example** entry point and explicit
reference-data disclosure before and after approval. No console errors or
warnings were recorded. The temporary tab and server were closed. This checks the
product workflow only; all model/provider tests are local mocks.

Remaining: coordinated provider/API deployment and bounded GPU canary, raw-output
archive/clean-clone evidence packaging, independent real-chart scale/quality
validation, serving comparisons and the wider readiness plan.

Reproduce locally with the repository's exact development lock installed:

```sh
python -m pytest -q
node tests/browser_workflow.mjs
ruff check unrender/product tests/test_extraction_provenance.py
ruff check --select S unrender/product
mypy unrender/product
```
