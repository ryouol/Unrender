# Evaluation contract: chart-table-v2

This is the only current scoring implementation. Historical measurements at
`c84b741c5358239bbb5d7290d4d9b2b98ea4b038` use a different ruler and are retained
as historical receipts, not a second runtime mode. Do not compare v1 percentages
to v2 as if a model improved or regressed.

## Primary quality

The headline is **micro cell F1 on exact-numeric charts at a declared 5% or 2%
value tolerance**. A cell must match the chart type, series identity, category/date,
axis units, and numerical value. Missing cells reduce recall; invented cells and
series reduce precision. Macro F1 gives every exact-numeric chart equal weight.
Report precision and recall alongside F1. An all-failed set cannot look successful.

Primary table scoring uses the **raw, strict ChartData response**. Repaired or
coerced outputs get no primary credit, even if the current parser recovers a table.
Recovery is reported separately and must not manufacture benchmark successes.
The current `chart-json-v2` parser only repairs complete-table formatting. Reports
include `parser_version` because this secondary recovery definition changed;
historical recovery rates used the earlier data-changing parser. The primary raw
scoring definition remains unchanged. Raw JSON validity, raw schema validity, raw semantic validity,
recovery count, and each input's outcome are distinct measurements. The current
wire schema is permissive; type validation alone does not establish chart semantics.

Matching is one-to-one and exact after these declared normalizations:

- Trim and collapse whitespace. Preserve letter case: Product A and Product a can
  be different categories. Do not fuzzy-match dates, years, or series names.
- Canonicalize unambiguous numeric keys using exact decimal arithmetic; accept
  valid thousands separators and equivalent numeric spellings. Preserve leading
  zero identifiers. Do not infer ambiguous date formats.
- Accept whole-word English month names and standard abbreviations as equivalent.
- Units are whitespace-normalized and case-sensitive. No implicit currency or
  scale conversion is performed. Labels must use the dataset's declared unit
  representation; unit-alias coverage is a known limitation to audit with the
  next human-labelled dataset.
- Duplicate category keys or duplicate/unnamed multi-series identities are
  structurally ambiguous. They cannot earn credit for the affected matches.

A zero truth value uses a fixed 1e-6 absolute tolerance; other values use the
larger of 1e-6 and the declared relative tolerance. It cannot borrow tolerance
from another large value. Negative pie values and nonpositive pie totals are invalid.

**Tables within tolerance** require every cell, series, axis label and unit,
with no extra/missing structure. **Chart exactness** additionally requires the
title and literally equal numerical values. Ordering is immaterial. Thus a value
within 5% can pass table tolerance and still fail chart exactness.

Unlabeled pies are a **separate proportion proxy**. They contribute neither to
exact-numeric cell metrics nor to full-table/exact-chart rates. Report the
`exact_points`, `proxy_points`, and `exact_chart_count` denominators. A zero rate
with zero eligible observations is not evidence of poor model performance.

`numeric_recall` is a diagnostic for numerical recovery without the unit/type
requirement. It still requires matching identities. It cannot substantiate a
usable-table claim; geometry outputs, for example, omit unit and axis metadata.
Matched-only MAE and median relative error include their match count and return
null when no values match. They must never hide missing cells.

## Coverage and failures

Every recorded input remains in the primary denominator, including infrastructure
errors. `conditional_model_metrics` exclude only infrastructure errors and are
explicitly secondary. Recovered invalid predictions remain invalid outcomes.

Library scoring and command-line scoring both reject duplicate IDs, invalid ground
truth and missing requested IDs. Cross-provider reports require identical coverage
or an explicitly supplied, preselected subset present in every file. Paired
bootstrap checks identical ground truth and annotation flags for each paired ID.
No success-conditioned intersection is permitted.

The runner makes one provider-function invocation per input and preserves failures
on resume. A retry experiment requires a fresh directory. This policy does not
attest the retry behavior internal to a provider SDK; transport retry instrumentation
belongs in the serving benchmark. Resume also checks the input file's SHA-256,
provider, model/revision, seed, prompt and generation settings. Missing or incompatible
metadata fails closed. Old evidence remains readable by the scorer.

Bootstrap resamples whole paired charts, not individual cells. It computes the
same exact-numeric F1 as the primary metric and counts failed outcomes. Its 3-point
improvement/positive-interval selection rule is a **v2 requirement**, not the
historical preregistration. Source-cluster confidence intervals and power planning
remain requirements for the next source-grouped real dataset.

## Reproduction and evidence

Run the CPU-only acceptance suite:

```bash
python -m pytest -q tests/test_eval.py tests/test_integrity.py tests/test_repair.py tests/test_metric_contract.py
```

Score one saved file with a fixed subset:

```bash
python -m unrender.eval.score --predictions PATH/predictions.jsonl \
  --subset unrender/eval/subsets/common300.json --out outputs/v2-score.json
```

The versioned scoreboard accepts a directory containing the saved Modal model
runs, plus the committed frontier files:

```bash
python analysis/scoreboard.py --model-root PATH/TO/SAVED/RUNS \
  --frontier-root outputs/eval_v1 --out outputs/evaluation-v2
```

Missing evidence is an error and cannot overwrite an existing report with blank
results. Reports carry the metric version; the scoreboard records raw artifact
SHA-256 hashes. It writes a new output directory and never overwrites historical
`RESULTS.md`. Incomplete frontier runs show expected/recorded coverage and missing
IDs, without a paired quality claim. Packaging the permitted private saved model
artifacts for clean-clone reproduction remains a separate readiness requirement.

The [initial saved-data rescore](../release/evaluation-v2/RESULTS.md) and
[summary with artifact/source hashes](../release/evaluation-v2/summary.json)
record the first implementation check. They do not replace a representative
real-world final evaluation.

## Dataset limitations

Common300 is a reused synthetic regression set, not a fresh final holdout. The
synthetic generator has categories beyond Z, including punctuation and lower-case
letters. Identity matching must preserve their distinction; this distribution is
also a reason to build a more representative dataset.

`real_v0` contains only eight public line charts and evaluates the earlier LoRA.
Its fetcher synthesizes titles, axis labels and series names from dataset constants;
source CSV truth does not establish that these metadata fields match the pixels.
Strict diagnostic scores remain inspectable, but semantic quality claims are
withheld until a visual metadata audit. Do not interpret a metadata mismatch as
proof of inability to read numbers, and do not assert contamination from a perfect
small-set numeric score alone.
